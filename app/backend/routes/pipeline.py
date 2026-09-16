"""Rota /api/pipeline — a cadeia operacional inteira, do campo ao estimador.

Encadeia, numa unica chamada:

    power flow (true state) -> medicoes -> RTU -> canal -> RTDB
                            -> processador de topologia -> vetor z -> WLS

Cada camada devolve a sua propria tabela e os seus proprios eventos, para que
a propagacao de um ataque seja visivel camada a camada em vez de aparecer so
como um residuo grande no fim.

**Por que existe um `run_id` aqui e nao no resto do app.** Os outros endpoints
sao stateless: mandam a topologia inteira e recebem o resultado. Uma cadeia
com timestamps, RTDB e trace precisa que o resultado sobreviva a requisicao
para poder ser consultado por sujeito (`/trace/{subject}`) sem reexecutar a
simulacao -- reexecutar com o mesmo seed daria o mesmo numero, mas nao o mesmo
custo. O armazenamento e em memoria do processo e limitado a
`_MAX_RUNS`; morre com o servidor, de proposito: e cache de sessao, nao
persistencia (para persistir, o caminho e `/api/scenarios`).

As medicoes NAO sao remontadas aqui: sao as mesmas de
`services/dc_measurement_model.py` que `/api/estimation/run` usa. Isso e o que
garante que rodar a cadeia sem ataque e sem atraso reproduza exatamente o
resultado do estimador direto -- e o teste de sanidade da camada inteira.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .powerflow import TopologyInput, _topology_to_dict
from ..services.dc_measurement_model import (
    build_configured_ac_measurements,
    kind_by_pp_bus,
    kind_by_pp_line,
    solve_ac_ground_truth,
)
from ..services.network_builder import build_net_from_frontend, line_id_map_from_topology
from ..paths import ensure_src_on_path

ensure_src_on_path()

from tese_dsse.cadeia_scada import (  # noqa: E402
    RTDB,
    ChannelConfig,
    PipelineTrace,
    SwitchTelemetry,
    build_points,
    delivery_statistics,
    group_buses_into_rtus,
    process_topology,
    transmit,
)
from tese_dsse.seguranca.ataques import (  # noqa: E402
    ATTACK_CATALOG,
    apply_channel_attacks,
    apply_sensor_attacks,
    apply_topology_attacks,
    catalog_as_list,
)

router = APIRouter()

#: Cache de corridas em memoria. OrderedDict + popitem(last=False) = FIFO.
_RUNS: "OrderedDict[str, dict]" = OrderedDict()
_MAX_RUNS = 20


class ChannelInput(BaseModel):
    base_delay_ms: float = Field(50.0, ge=0.0, le=600_000.0)
    jitter_ms: float = Field(0.0, ge=0.0, le=60_000.0)
    drop_probability: float = Field(0.0, ge=0.0, le=1.0)


class AttackInput(BaseModel):
    attack_id: str
    target: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class OPFLimitsInput(BaseModel):
    """Constraints and merit order for the control layer.

    Costs are relative, not market prices: what matters is that the upstream
    grid is dearer than local generation, so the optimum depends on whether the
    network can carry the local injection — i.e. on the model. With the order
    reversed the OPF would answer "import everything" and the topology would
    barely matter, which defeats the purpose of running it here.
    """

    vm_min_pu: float = Field(0.95, gt=0.0, lt=2.0)
    vm_max_pu: float = Field(1.05, gt=0.0, lt=2.0)
    max_loading_percent: float = Field(100.0, gt=0.0)
    ext_grid_cost: float = 60.0
    gen_cost: float = 20.0
    sgen_cost: float = 5.0


class PipelineRequest(BaseModel):
    topology: TopologyInput
    estimation_method: Literal["ac-gn-wls"] = Field(
        "ac-gn-wls",
        description=(
            "Only AC Gauss-Newton for now. The DC path builds its measurement "
            "rows through a different helper (configured_dc_rows), which returns "
            "arrays instead of ACMeasurement objects — wiring it into the chain "
            "is a separate change, not a flag."
        ),
    )
    noise_level: float = Field(0.01, ge=0.0, le=1.0)
    sigma_min: float = Field(1e-4, ge=1e-6)
    seed: int | None = None
    add_noise: bool = Field(
        True,
        description=(
            "When False, z = z_true (no measurement noise) so an attack's effect "
            "can be read in isolation — same ablation switch as /api/baddata/detect."
        ),
    )
    n_rtus: int = Field(
        0, ge=0, le=64,
        description="0 = auto (one RTU per ~4 buses, at least 2 when the network allows).",
    )
    channel: ChannelInput = Field(default_factory=ChannelInput)
    stale_after_s: float = Field(10.0, ge=0.0)
    unreliable_policy: Literal["last_known", "assume_closed", "assume_open", "flow_inference"] = (
        "last_known"
    )
    attacks: list[AttackInput] = Field(default_factory=list)
    run_estimation: bool = True
    run_opf: bool = Field(
        False,
        description=(
            "Run the control layer: OPF on the model the operator believes (the "
            "reconstructed topology), OPF on the true model, and the physical result "
            "of dispatching the first onto the real network. Off by default because "
            "runopp is markedly slower than the rest of the chain."
        ),
    )
    opf_limits: OPFLimitsInput = Field(default_factory=lambda: OPFLimitsInput())
    run_agents: bool = Field(
        True,
        description=(
            "Run the cross-layer agent team over the chain artefacts. Agents never "
            "recompute anything, so turning this off changes no number in the result "
            "— it only removes the assessment."
        ),
    )


@router.get("/attacks")
def list_attacks() -> dict:
    """Catalogo de ataques por camada — alimenta o seletor da aba Pipeline."""
    return {"attacks": catalog_as_list(), "layers": ["measurement", "rtu", "channel", "topology"]}


@router.post("/run")
def run_pipeline(req: PipelineRequest) -> dict:
    t_start = time.perf_counter()
    trace = PipelineTrace()
    topo_dict = _topology_to_dict(req.topology)
    attacks = [a.model_dump() for a in req.attacks]

    _validate_attacks(attacks)

    # ── 1. physical / true state ─────────────────────────────────────────────
    try:
        net, bus_id_map = solve_ac_ground_truth(build_net_from_frontend, topo_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"AC power flow (true state) did not converge: {exc}. The chain needs a "
                "solved operating point before anything downstream can run."
            ),
        ) from exc

    pp_to_frontend = {v: k for k, v in bus_id_map.items()}
    true_state = _true_state(net, pp_to_frontend)
    trace.log(
        "physical", 0.0, "TRUE_STATE",
        f"AC power flow converged: {len(true_state['buses'])} buses, "
        f"{len(true_state['lines'])} branches",
        n_buses=len(true_state["buses"]), n_lines=len(true_state["lines"]),
    )

    # ── 2. measurement layer (mesmo codigo de /api/estimation/run) ───────────
    kind_by_bus = kind_by_pp_bus(topo_dict, bus_id_map)
    slack_pp = int(net.ext_grid.bus.iloc[0])
    line_id_map = line_id_map_from_topology(topo_dict)
    line_kind_by_pp = kind_by_pp_line(topo_dict, line_id_map)
    pp_line_to_frontend = {v: k for k, v in line_id_map.items()}

    try:
        clean_measurements, meas_meta = build_configured_ac_measurements(
            net, kind_by_bus, req.noise_level, req.sigma_min, slack_pp, pp_to_frontend,
            line_kind_by_pp, pp_line_to_frontend,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Error building measurements: {exc}") from exc

    if not clean_measurements:
        raise HTTPException(
            status_code=422,
            detail="No measurements configured — place at least one meter on a bus in Topology.",
        )

    z_true = np.array([m.value for m in clean_measurements], dtype=float)
    sigma = np.array([m.sigma for m in clean_measurements], dtype=float)

    if req.add_noise:
        from tese_dsse.estimacao_estado.dc_linear import sample_noisy_measurement

        z_field = sample_noisy_measurement(z_true, sigma, req.seed)
    else:
        z_field = z_true.copy()

    trace.log(
        "measurement", 0.0, "FIELD",
        f"{len(z_field)} field measurements generated "
        f"({'with' if req.add_noise else 'without'} noise)",
        n_measurements=len(z_field), add_noise=req.add_noise,
    )

    # ── 3. RTU layer ─────────────────────────────────────────────────────────
    frontend_bus_ids = sorted(bus_id_map.keys())
    n_rtus = req.n_rtus or max(2, min(len(frontend_bus_ids), round(len(frontend_bus_ids) / 4) or 1))
    n_rtus = min(n_rtus, len(frontend_bus_ids))
    bus_to_rtu = group_buses_into_rtus(frontend_bus_ids, n_rtus)

    points, rtus = build_points(
        meas_meta, list(z_field), list(sigma), bus_to_rtu, t0_s=0.0, trace=trace
    )
    points = apply_sensor_attacks(points, attacks, trace=trace)

    # ── 4. communication layer ───────────────────────────────────────────────
    channel = ChannelConfig(
        base_delay_ms=req.channel.base_delay_ms,
        jitter_ms=req.channel.jitter_ms,
        drop_probability=req.channel.drop_probability,
        seed=req.seed,
    )
    channel_attacked = apply_channel_attacks(channel, attacks)
    deliveries = transmit(points, channel_attacked, trace=trace)

    # ── 5. SCADA RTDB ────────────────────────────────────────────────────────
    rtdb = RTDB()
    rtdb.ingest_all(deliveries, trace=trace)
    received = [d.receive_time_s for d in deliveries if not d.dropped]
    now_s = max(received) if received else 0.0
    snapshot = rtdb.snapshot(now_s, stale_after_s=req.stale_after_s, trace=trace)

    # ── 6. topology processor ────────────────────────────────────────────────
    telemetry_true = _switch_telemetry(topo_dict)
    # `telemetry_true` é gerada por `from_closed`, então é sempre conclusiva
    # (código 1 ou 2) e `sw.closed` nunca é None aqui — o `is True` só existe
    # para não depender disso silenciosamente se a origem mudar.
    truth_closed = {sw.switch_id: sw.closed is True for sw in telemetry_true}
    telemetry = apply_topology_attacks(telemetry_true, attacks, now_s=now_s, trace=trace)

    measured_flow = {
        r.line_id: r.value
        for r in snapshot.usable
        if r.line_id is not None and r.quantity == "p_branch"
    }
    topo_snapshot = process_topology(
        telemetry,
        policy=req.unreliable_policy,
        last_known=truth_closed,
        measured_flow_by_line=measured_flow,
        version=1,
        now_s=now_s,
        trace=trace,
    )
    mismatched = topo_snapshot.differs_from(truth_closed)
    if mismatched:
        trace.log(
            "topology", now_s, "SNAPSHOT",
            f"Reconstructed topology DIFFERS from the real one on {len(mismatched)} "
            f"switch(es): {mismatched}. The estimator will solve the wrong problem.",
            level="error", mismatched_switch_ids=mismatched,
        )

    # ── 7. vetor z a partir do RTDB ──────────────────────────────────────────
    usable = [r for r in snapshot.usable if r.measurement_index is not None]
    usable.sort(key=lambda r: r.measurement_index)
    kept_idx = [int(r.measurement_index) for r in usable]
    dropped_idx = sorted(set(range(len(clean_measurements))) - set(kept_idx))

    trace.log(
        "estimation", now_s, "Z_VECTOR",
        f"z vector assembled from {len(kept_idx)} of {len(clean_measurements)} "
        f"measurements ({len(dropped_idx)} dropped by SCADA)",
        level="warning" if dropped_idx else "info",
        n_kept=len(kept_idx), n_dropped=len(dropped_idx), dropped_indices=dropped_idx,
    )

    estimation = None
    if req.run_estimation:
        estimation = _estimate(
            net, clean_measurements, usable, topo_snapshot, true_state, trace, now_s,
            pp_to_frontend, line_id_map,
        )

    measurement_rows = [
        {
            "index": i,
            "quantity": meas_meta[i]["quantity"],
            "meterKind": meas_meta[i]["meterKind"],
            "busId": meas_meta[i]["busId"],
            "lineId": meas_meta[i]["lineId"],
            "z_true": round(float(z_true[i]), 6),
            "z_field": round(float(z_field[i]), 6),
            "sigma": round(float(sigma[i]), 8),
        }
        for i in range(len(clean_measurements))
    ]
    channel_stats = delivery_statistics(deliveries)

    # ── 8. control layer (OPF) ───────────────────────────────────────────────
    opf = None
    if req.run_opf:
        net_believed, _ = _believed_net(net, topo_snapshot, trace, now_s, line_id_map)
        try:
            opf = _run_control_layer(net, net_believed, req.opf_limits, trace, now_s)
        except Exception as exc:
            # Falha do OPF não pode derrubar a corrida inteira: as 7 camadas
            # anteriores já produziram resultado válido e o usuário perderia
            # tudo por causa da camada opcional.
            opf = {"error": f"{type(exc).__name__}: {exc}"}
            trace.log(
                "opf", now_s, "OPF",
                f"Control layer failed: {type(exc).__name__}: {exc}",
                level="error",
            )

    # ── 9. cross-layer agents ────────────────────────────────────────────────
    layers_payload = {
        "physical": true_state,
        "measurement": {
            "n_measurements": len(clean_measurements),
            "rows": measurement_rows,
        },
        "rtu": {"rtus": [r.to_dict() for r in rtus.values()],
                "points": [p.to_dict() for p in points]},
        "channel": {"statistics": channel_stats,
                    "packets": [d.to_dict() for d in deliveries]},
        "rtdb": snapshot.to_dict(),
        "topology": {**topo_snapshot.to_dict(),
                     "mismatched_switch_ids": mismatched,
                     "matches_reality": not mismatched},
        "estimation": estimation,
        "opf": opf,
    }

    agents = None
    if req.run_agents:
        from tese_dsse.agentes import run_chain_agents

        agents = run_chain_agents(layers_payload)
        for f in agents["findings"]:
            if f["severity"] in ("warning", "critical"):
                trace.log(
                    "estimation" if f["layer"] == "estimation" else f["layer"],  # type: ignore[arg-type]
                    now_s, f["agent"],
                    f"{f['title']} — {f['detail']}",
                    level="error" if f["severity"] == "critical" else "warning",
                    agent=f["agent"], caused_by=f["caused_by"],
                )

    elapsed_ms = (time.perf_counter() - t_start) * 1000.0
    run_id = uuid.uuid4().hex[:12]

    result = {
        "run_id": run_id,
        "elapsed_ms": round(elapsed_ms, 2),
        "config": {
            "n_rtus": n_rtus,
            "channel": channel_attacked.to_dict(),
            "channel_nominal": channel.to_dict(),
            "stale_after_s": req.stale_after_s,
            "unreliable_policy": req.unreliable_policy,
            "add_noise": req.add_noise,
            "seed": req.seed,
            "attacks": attacks,
        },
        "layers": {
            "physical": true_state,
            "measurement": {
                "n_measurements": len(clean_measurements),
                "rows": measurement_rows,
            },
            "rtu": {
                "rtus": [r.to_dict() for r in rtus.values()],
                "points": [p.to_dict() for p in points],
            },
            "channel": {
                "statistics": channel_stats,
                "packets": [d.to_dict() for d in deliveries],
            },
            "rtdb": snapshot.to_dict(),
            "topology": {
                **topo_snapshot.to_dict(),
                "mismatched_switch_ids": mismatched,
                "matches_reality": not mismatched,
            },
            "estimation": estimation,
            "opf": opf,
            "agents": agents,
        },
        "trace": trace.to_dict(),
    }

    _RUNS[run_id] = result
    while len(_RUNS) > _MAX_RUNS:
        _RUNS.popitem(last=False)

    return result


@router.get("/run/{run_id}")
def get_run(run_id: str) -> dict:
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=f"Run '{run_id}' not found — runs are kept in memory (last {_MAX_RUNS}) "
                   "and are lost when the backend restarts.",
        )
    return run


@router.get("/run/{run_id}/trace/{subject}")
def get_trace(run_id: str, subject: str) -> dict:
    """A linha da vida de um sensor/ponto/chave atravessando as camadas."""
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    events = [e for e in run["trace"]["events"] if e["subject"] == subject]
    if not events:
        raise HTTPException(
            status_code=404,
            detail=f"Nothing traced for subject '{subject}' in run '{run_id}'. "
                   f"Known subjects: {run['trace']['subjects'][:10]}…",
        )
    from tese_dsse.cadeia_scada.traco import LAYERS

    order = {name: i for i, name in enumerate(LAYERS)}
    events.sort(key=lambda e: (order.get(e["layer"], 99), e["timestamp_s"]))
    return {"run_id": run_id, "subject": subject, "events": events, "n_events": len(events)}


# ─── helpers ─────────────────────────────────────────────────────────────────


def _validate_attacks(attacks: list[dict]) -> None:
    unknown = sorted({a["attack_id"] for a in attacks if a["attack_id"] not in ATTACK_CATALOG})
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown attack id(s): {unknown}. See GET /api/pipeline/attacks.",
        )


def _true_state(net: Any, pp_to_frontend: dict[int, int]) -> dict:
    """O estado verdadeiro, nomeado como entidade propria.

    Ate agora o app produzia estes numeros dentro do resultado do power flow e
    seguia em frente. Separa-los importa: e contra este dicionario que o estado
    estimado no fim da cadeia e comparado, e e ele que o atacante NAO ve.
    """
    buses = [
        {
            "id": pp_to_frontend.get(int(idx), int(idx)),
            "vm_pu": round(float(row.vm_pu), 6),
            "va_degree": round(float(row.va_degree), 6),
            "p_mw": round(float(row.p_mw), 6),
            "q_mvar": round(float(row.q_mvar), 6),
        }
        for idx, row in net.res_bus.iterrows()
    ]
    lines = [
        {
            "id": int(idx),
            "p_from_mw": round(float(row.p_from_mw), 6),
            "q_from_mvar": round(float(row.q_from_mvar), 6),
            "p_to_mw": round(float(row.p_to_mw), 6),
            "loading_percent": round(float(row.loading_percent), 3),
        }
        for idx, row in net.res_line.iterrows()
    ]
    return {"buses": buses, "lines": lines, "converged": bool(net["converged"])}


def _switch_telemetry(topo_dict: dict) -> list[SwitchTelemetry]:
    """Telemetria coerente a partir das chaves da topologia.

    Quando a topologia nao traz `switches` (redes montadas a mao no app nao
    tem esse conceito), toda linha vira uma chave normalmente fechada. E a
    mesma convencao que `routes/topology.py` ja usa ao exportar case33bw, onde
    o pandapower nao cria `net.switch` e as linhas em servico sao tratadas como
    seccionadoras fechadas.
    """
    switches = topo_dict.get("switches") or []
    if switches:
        # `topology.switches[].id` é uma sequência própria (sw_seq em
        # topology.py), sem vínculo explícito com `lines[].id` — o backend
        # nunca exportou essa ligação. Resolver pelos terminais é a única
        # ponte disponível, e é suficiente porque o app não modela ramos
        # paralelos entre o mesmo par de barras.
        line_by_ends: dict[tuple[int, int], int] = {}
        for line in topo_dict.get("lines", []):
            ends = (int(line["from_bus"]), int(line["to_bus"]))
            line_by_ends.setdefault(ends, int(line["id"]))
            line_by_ends.setdefault(ends[::-1], int(line["id"]))

        return [
            SwitchTelemetry.from_closed(
                switch_id=int(sw["id"]),
                from_bus=int(sw["from_bus"]),
                to_bus=int(sw["to_bus"]),
                closed=bool(sw.get("closed", True)),
                name=str(sw.get("name") or f"SW-{sw['id']}"),
                line_id=line_by_ends.get((int(sw["from_bus"]), int(sw["to_bus"]))),
            )
            for sw in switches
        ]

    return [
        SwitchTelemetry.from_closed(
            switch_id=int(line["id"]),
            from_bus=int(line["from_bus"]),
            to_bus=int(line["to_bus"]),
            closed=True,
            name=f"SW-L{line['id']}",
            line_id=int(line["id"]),
        )
        for line in topo_dict.get("lines", [])
    ]


def _believed_net(
    net: Any,
    topo_snapshot: Any,
    trace: PipelineTrace,
    now_s: float,
    line_id_map: dict[int, int],
) -> tuple[Any, set[int]]:
    """A rede como o operador acredita que ela é — o modelo reconstruído.

    Compartilhada pelo estimador e pelo OPF de propósito: os dois têm de
    trabalhar sobre exatamente o mesmo modelo errado, senão a diferença medida
    na camada de controle não seria atribuível ao erro de topologia.

    `topo_snapshot.open_line_ids` está no espaço de ids do FRONTEND (é de lá
    que vem `topology.lines[].id`); `net.line.index` está no do pandapower. Sem
    a tradução por `line_id_map`, desligar a linha aberta ou erra a linha ou
    estoura em `net.line.at[...]` — os dois espaços coincidem por acaso em
    algumas topologias e divergem na maioria.
    """
    open_frontend = set(topo_snapshot.open_line_ids)
    open_lines = {line_id_map[i] for i in open_frontend if i in line_id_map}
    if not open_lines:
        return net, open_lines

    import copy

    import pandapower as pp

    believed = copy.deepcopy(net)
    for line_idx in open_lines:
        if line_idx in believed.line.index:
            believed.line.at[line_idx, "in_service"] = False
    try:
        pp.runpp(believed, algorithm="nr", max_iteration=50, numba=False)
    except Exception:
        # A rede reconstruída pode nem convergir — é um resultado, não um bug:
        # o operador acabou de montar um modelo impossível a partir de status
        # telemetrado errado.
        trace.log(
            "estimation", now_s, "MODEL",
            "The reconstructed network does not converge in the power flow: the "
            "model handed to the estimator is physically inconsistent.",
            level="error", open_line_ids=sorted(open_lines),
        )
    return believed, open_lines


def _run_control_layer(
    net_true: Any,
    net_believed: Any,
    limits_input: OPFLimitsInput,
    trace: PipelineTrace,
    now_s: float,
) -> dict:
    """Camada de controle: OPF sobre o modelo do operador vs. sobre a verdade."""
    from tese_dsse.powerflow.opf import OPFLimits, opf_under_uncertainty

    limits = OPFLimits(**limits_input.model_dump())
    assessment = opf_under_uncertainty(net_true, net_believed, limits)

    if not assessment.operator.converged:
        trace.log(
            "opf", now_s, "OPF",
            f"The operator's OPF did NOT converge on the reconstructed model. "
            f"{assessment.operator.reason}",
            level="error",
        )
    else:
        hidden = len(assessment.hidden_violations)
        trace.log(
            "opf", now_s, "OPF",
            f"OPF dispatched {len(assessment.operator.setpoints)} setpoints; "
            f"largest error vs. perfect information {assessment.max_setpoint_error_mw:.4f} MW; "
            f"{hidden} hidden violation(s)",
            level="error" if hidden else "info",
            max_setpoint_error_mw=round(assessment.max_setpoint_error_mw, 6),
            n_hidden_violations=hidden,
            cost_gap=assessment.cost_gap,
        )
        for v in assessment.hidden_violations:
            trace.log(
                "opf", now_s, f"{v.element}-{v.index}",
                f"HIDDEN VIOLATION: {v.kind} on {v.element} {v.index}, value "
                f"{v.value:.4f} against a {v.limit:.4f} limit. The operator's OPF "
                "considered this constraint satisfied.",
                level="error", **v.to_dict(),
            )

    return {**assessment.to_dict(), "limits": limits.to_dict()}


def _estimate(
    net: Any,
    clean_measurements: list,
    usable: list,
    topo_snapshot: Any,
    true_state: dict,
    trace: PipelineTrace,
    now_s: float,
    pp_to_frontend: dict[int, int],
    line_id_map: dict[int, int],
) -> dict:
    """Roda o WLS AC sobre o que o SCADA entregou.

    Usa `build_ac_ybus_model_from_pandapower` — exatamente o mesmo solver de
    `/api/estimation/run`. A Ybus vem do `net` do power flow; a topologia
    reconstruida entra pela lista de ramos abertos, que zera a contribuicao de
    quem o processador julgou aberto. Quando a reconstrucao esta errada, e aqui
    que o erro de modelo se materializa.
    """
    from dataclasses import replace as dataclass_replace

    from tese_dsse.estimacao_estado.ac_measurements import build_ac_ybus_model_from_pandapower
    from tese_dsse.estimacao_estado.dc_linear import chi2_limit

    if not usable:
        return {
            "ran": False,
            "reason": "No usable measurements left in the RTDB — every point was dropped or "
                      "marked bad. Lower the packet loss or remove the sensor-failure attacks.",
        }

    net_est, open_lines = _believed_net(net, topo_snapshot, trace, now_s, line_id_map)

    # Um processador de topologia real **remove** as medições dos ramos que o
    # modelo considera desenergizados: não existe equação de fluxo para uma
    # linha fora de serviço, e o estimador nem monta a linha correspondente da
    # Jacobiana. Aqui isso é literal — sem o filtro, o modelo AC estoura com
    # KeyError ('line', idx) ao procurar um ramo que ele mesmo desligou.
    #
    # E é justamente aqui que o ataque de topologia dói: essas medições estão
    # perfeitamente corretas e chegaram íntegras: o operador as descarta porque
    # o modelo dele diz que aquele trecho está morto. Perde-se redundância boa
    # por causa de um status falsificado.
    if open_lines:
        before = len(usable)
        usable = [
            r for r in usable
            if r.line_id is None or line_id_map.get(int(r.line_id)) not in open_lines
        ]
        discarded = before - len(usable)
        if discarded:
            trace.log(
                "estimation", now_s, "TOPOLOGY_FILTER",
                f"{discarded} flow measurement(s) discarded: the reconstructed model "
                f"treats branch(es) {sorted(open_lines)} as de-energised. Those "
                "measurements were correct and arrived intact.",
                level="warning", n_discarded=discarded, open_line_ids=sorted(open_lines),
            )

    measurements = [
        dataclass_replace(clean_measurements[r.measurement_index], value=float(r.value))
        for r in usable
    ]
    n_states = len(net.bus) * 2 - 1
    if len(measurements) < n_states:
        return {
            "ran": False,
            "reason": (
                f"Network not observable with what survived the chain: {len(measurements)} "
                f"measurement(s) for {n_states} unknown(s)."
            ),
            "n_measurements": len(measurements),
            "n_states": n_states,
        }

    try:
        model = build_ac_ybus_model_from_pandapower(net_est, measurements)
        result = model.solve(x0=model.flat_start(), max_iter=30, tol=1e-8)
    except Exception as exc:
        return {"ran": False, "reason": f"Gauss-Newton failed: {exc}"}

    x_hat = result.x
    state_table = model.state_to_table(x_hat)
    est_by_bus = {
        int(b): (float(vm), float(va))
        for b, vm, va in zip(state_table.bus, state_table.vm_pu, state_table.va_degree)
    }

    residuals = np.asarray(model.residuals(x_hat)) if hasattr(model, "residuals") else None
    if residuals is None:
        residuals = np.array([m.value for m in measurements]) - np.asarray(model.h(x_hat))

    sigmas = np.array([m.sigma for m in measurements])
    J = float(np.sum((residuals / sigmas) ** 2))
    dof = max(1, len(measurements) - n_states)
    # chi2_limit(alpha, dof) — alpha primeiro, e alpha=0.05 para 95% de
    # confiança, como em estimation.py e baddata.py. Inverter os dois devolve
    # nan em silêncio, e `J <= nan` é sempre False: o teste reprovaria toda
    # estimativa, inclusive as perfeitas.
    limit = float(chi2_limit(0.05, dof))

    # `est_by_bus` vem indexado por barra do pandapower; `true_state` ja foi
    # traduzido para os ids do frontend em `_true_state`. Comparar sem traduzir
    # casa barras diferentes quando os dois espacos de id nao coincidem — que e
    # o caso de toda topologia carregada do pandapower (pp 0..n-1 contra
    # frontend 1..n). Todo id que sai desta funcao e id do frontend, como no
    # resto da API.
    true_by_bus = {b["id"]: b for b in true_state["buses"]}
    errors_vm, errors_va = [], []
    comparison = []
    for pp_bus, (vm, va) in sorted(est_by_bus.items()):
        frontend_bus = pp_to_frontend.get(int(pp_bus), int(pp_bus))
        truth = true_by_bus.get(frontend_bus)
        if truth is None:
            continue
        e_vm = vm - truth["vm_pu"]
        e_va = va - truth["va_degree"]
        errors_vm.append(abs(e_vm))
        errors_va.append(abs(e_va))
        comparison.append({
            "busId": frontend_bus,
            "vm_true": truth["vm_pu"], "vm_est": round(vm, 6), "vm_error": round(e_vm, 6),
            "va_true": truth["va_degree"], "va_est": round(va, 6), "va_error": round(e_va, 6),
        })

    trace.log(
        "estimation", now_s, "WLS",
        f"AC WLS {'converged' if result.converged else 'did NOT converge'} in "
        f"{len(result.iterations)} iterations; J={J:.3f} (threshold {limit:.3f})",
        level="info" if result.converged else "error",
        J=round(J, 6), chi2_limit=round(limit, 6), converged=bool(result.converged),
    )

    return {
        "ran": True,
        "converged": bool(result.converged),
        "iterations": len(result.iterations),
        "n_measurements": len(measurements),
        "n_states": n_states,
        "J": round(J, 6),
        "chi2_limit": round(limit, 6),
        "chi2_passed": bool(J <= limit),
        "max_vm_error": round(float(max(errors_vm)), 6) if errors_vm else None,
        "max_va_error_deg": round(float(max(errors_va)), 6) if errors_va else None,
        "rmse_vm": round(float(np.sqrt(np.mean(np.square(errors_vm)))), 8) if errors_vm else None,
        "comparison": comparison,
        "model_open_line_ids": sorted(open_lines),
    }
