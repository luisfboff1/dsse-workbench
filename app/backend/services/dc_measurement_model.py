"""Ground truth solve + measurement-config filtering shared by
app/backend/routes/estimation.py's DC-WLS and AC-GN-WLS paths and
baddata.py's endpoints (DC and AC) — all build the same measurement set
filtered down to whatever `topology.measurements`/`topology.line_measurements`
actually configured, then either feed it to the linear DC model directly or
linearize the nonlinear AC model around the true operating point so the exact
same downstream pipeline (hat_matrix, solve_dc_pure, run_bad_data_pipeline —
all in bad_data.py/dc_linear.py) works unchanged for both.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .measurement_kinds import (
    MEASUREMENT_KIND_SPECS,
    default_measurements,
    p_sigma,
    v_sigma,
    va_sigma_deg,
)


def solve_ac_ground_truth(build_net_from_frontend, topo_dict: dict) -> tuple[Any, dict[int, int]]:
    """Roda AC power flow (Newton-Raphson, fallback Iwamoto) — usado como
    ground truth real. `bus.angle` na topologia é sempre flat-start (0°) —
    ver load_pandapower_case() em topology.py — então não dá pra só ler o
    campo, precisa resolver de verdade."""
    import pandapower as pp

    try:
        net_ac, bus_id_map_ac = build_net_from_frontend(topo_dict)
        pp.runpp(net_ac, algorithm="nr", max_iteration=50, numba=False)
        if not bool(net_ac["converged"]):
            raise RuntimeError("NR did not converge.")
    except Exception:
        net_ac, bus_id_map_ac = build_net_from_frontend(topo_dict)
        pp.runpp(net_ac, algorithm="iwamoto_nr", max_iteration=100, numba=False)
        if not bool(net_ac["converged"]):
            raise RuntimeError("Iwamoto NR also did not converge.")
    return net_ac, bus_id_map_ac


def kind_by_pp_bus(topo_dict: dict, bus_id_map: dict[int, int]) -> dict[int, str]:
    """{pp_bus_idx: meter kind}, defaulting to 'todo bus com SCADA' quando a
    topologia não configurou nenhum medidor de barra — ver MeasurementInput
    em powerflow.py."""
    measurements = topo_dict.get("measurements") or default_measurements(topo_dict["buses"])
    return {
        bus_id_map[m["busId"]]: m["kind"]
        for m in measurements
        if m["busId"] in bus_id_map
    }


def kind_by_pp_line(topo_dict: dict, line_id_map: dict[int, int]) -> dict[int, str]:
    """{pp_line_idx: meter kind} a partir de topology.line_measurements — sem
    default: ao contrário de barra (toda barra vira SCADA se nada foi
    configurado), uma linha só ganha medidor se o usuário clicar nela e
    escolher um tipo — ver LineMeasurementInput em powerflow.py. Reflete que
    fluxo de linha é opt-in/mais raro na prática (RTU por disjuntor é mais
    caro que agregação na barra)."""
    line_measurements = topo_dict.get("line_measurements") or []
    return {
        line_id_map[m["lineId"]]: m["kind"]
        for m in line_measurements
        if m["lineId"] in line_id_map
    }


def configured_dc_rows(
    model,
    pp_to_frontend: dict[int, int],
    non_slack_pp: list[int],
    kind_by_bus: dict[int, str],
    z_true_full: np.ndarray,
    angle_true_by_pp: dict[int, float],
    noise_level: float,
    sigma_min: float,
    line_kind_by_pp: dict[int, str] | None = None,
    pp_line_to_frontend: dict[int, int] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str], list[dict]]:
    """Filtra o modelo DC completo (toda barra + toda linha) pro que foi
    configurado em `topology.measurements`/`topology.line_measurements`, e
    soma linhas extras de ângulo direto para barras com PMU (H = one-hot, não
    precisa de biblioteca AC — o estado do modelo DC já É o ângulo).

    Fluxo de linha soma OS DOIS lados (`P_i->j` e `P_j->i`) — cada terminal
    da linha tem seu próprio RTU/CT-TP físico e seu próprio erro de medição
    independente, então mesmo que `P_j->i = -P_i->j` exatamente no valor
    *verdadeiro* (DC sem perdas), são duas amostras ruidosas independentes da
    mesma grandeza física, não a mesma informação duplicada — é a convenção
    padrão de redundância usada em bad-data (Abur & Exposito) e é o que
    `notebooks/simulacao/5_BUS_IEEE_bad_data_analytics.ipynb` usa (ver
    `measurement_table` não filtrada de
    `dc_linear.build_linear_dc_model_from_rundcpp`, que já gera os dois lados
    em blocos: todo "from" primeiro, depois todo "to", mesma ordem de ramo —
    é essa ordem que preservamos aqui). Até 2026-07-03 só o lado "from" era
    incluído; mudou porque um medidor de linha configurado no app não batia
    com o `m`/DOF do notebook de referência (11 vs 17 medições no IEEE
    5-bus), o que também deixava o `J`/threshold χ² não comparáveis.

    Retorna (H, c, z_true, sigma, labels, meta), onde `meta[i]` é
    `{"busId", "lineId", "meterKind", "quantity"}` (exatamente um de
    busId/lineId é não-None) — `meterKind` é o tipo de medidor
    (pmu/scada/ami/pseudo), `quantity` é a grandeza física ("p_inj"/"theta"
    para barra, "p_branch" para linha). Usado pelas rotas para remontar
    tabelas de diagnóstico próprias (ex. K_diag/UI/CME em baddata.py) sem
    duplicar essa filtragem.
    """
    line_kind_by_pp = line_kind_by_pp or {}
    pp_line_to_frontend = pp_line_to_frontend or {}

    rows: list[dict] = []
    meas_table = model.measurement_table
    p_bus_rows = meas_table[meas_table["kind"] == "p_bus"]
    for i, row in p_bus_rows.iterrows():
        pp_bus = int(row["bus"])
        kind = kind_by_bus.get(pp_bus)
        if kind is None:
            continue
        idx = int(i)
        z_val = float(z_true_full[idx])
        rows.append(
            {
                "H": model.H[idx, :],
                "c": float(model.c[idx]),
                "z_true": z_val,
                "sigma": p_sigma(kind, z_val, noise_level, sigma_min),
                "label": f"P_inj_{pp_to_frontend[pp_bus]}",
                "busId": pp_to_frontend[pp_bus],
                "lineId": None,
                "meterKind": kind,
                "quantity": "p_inj",
            }
        )

    if line_kind_by_pp:
        line_rows = meas_table[(meas_table["kind"] == "line") & (meas_table["side"].isin(["from", "to"]))]
        for i, row in line_rows.iterrows():
            pp_line = int(row["element"])
            kind = line_kind_by_pp.get(pp_line)
            if kind is None:
                continue
            idx = int(i)
            z_val = float(z_true_full[idx])
            rows.append(
                {
                    "H": model.H[idx, :],
                    "c": float(model.c[idx]),
                    "z_true": z_val,
                    "sigma": p_sigma(kind, z_val, noise_level, sigma_min),
                    "label": row["label"],
                    "busId": None,
                    "lineId": pp_line_to_frontend.get(pp_line, pp_line),
                    "meterKind": kind,
                    "quantity": "p_branch",
                }
            )

    for j, pp_idx in enumerate(non_slack_pp):
        if kind_by_bus.get(pp_idx) != "pmu":
            continue
        h_row = np.zeros(len(non_slack_pp))
        h_row[j] = 1.0
        rows.append(
            {
                "H": h_row,
                "c": 0.0,
                "z_true": float(np.deg2rad(angle_true_by_pp[pp_idx])),
                "sigma": float(np.deg2rad(va_sigma_deg("pmu", noise_level))),
                "label": f"theta_PMU_{pp_to_frontend[pp_idx]}",
                "busId": pp_to_frontend[pp_idx],
                "lineId": None,
                "meterKind": "pmu",
                "quantity": "theta",
            }
        )

    if not rows:
        n = len(non_slack_pp)
        return (
            np.zeros((0, n)),
            np.zeros(0),
            np.zeros(0),
            np.zeros(0),
            [],
            [],
        )

    H = np.vstack([r["H"] for r in rows])
    c = np.array([r["c"] for r in rows])
    z_true = np.array([r["z_true"] for r in rows])
    sigma = np.array([r["sigma"] for r in rows])
    labels = [r["label"] for r in rows]
    meta = [
        {"busId": r["busId"], "lineId": r["lineId"], "meterKind": r["meterKind"], "quantity": r["quantity"]}
        for r in rows
    ]
    return H, c, z_true, sigma, labels, meta


def _ac_measurement_label(m: Any, net: Any = None) -> str:
    if m.kind == "v_bus":
        return f"V_{m.element}"
    if m.kind == "va_bus":
        return f"theta_PMU_{m.element}"
    if m.kind == "p_inj":
        return f"P_inj_{m.element}"
    if m.kind == "q_inj":
        return f"Q_inj_{m.element}"
    if m.kind in ("p_branch", "q_branch") and net is not None:
        fb = int(net.line.at[m.element, "from_bus"])
        tb = int(net.line.at[m.element, "to_bus"])
        if m.side == "to":
            fb, tb = tb, fb
        prefix = "P" if m.kind == "p_branch" else "Q"
        return f"{prefix}_{fb}->{tb}"
    return f"{m.kind}_{m.element}"


def build_configured_ac_measurements(
    net: Any,
    kind_by_bus: dict[int, str],
    noise_level: float,
    sigma_min: float,
    slack_pp: int,
    pp_to_frontend: dict[int, int],
    line_kind_by_pp: dict[int, str] | None = None,
    pp_line_to_frontend: dict[int, int] | None = None,
) -> tuple[list, list[dict]]:
    """Monta ACMeasurement pras barras e linhas com medidor configurado.

    Barra: cada tipo contribui um subconjunto de {V, θ, P, Q} (ver
    MEASUREMENT_KIND_SPECS). P/Q vêm de S_inj = V·conj(Ybus·V) (inclui shunts
    corretamente).

    Linha: todo tipo contribui {P_ij, Q_ij, P_ji, Q_ji} — OS DOIS terminais,
    lidos direto de `net.res_line` (já resolvido). Cada ponta é um RTU/CT-TP
    físico independente com seu próprio erro de medição, não a mesma
    informação duplicada (mesma convenção de `configured_dc_rows`, ver seu
    docstring). Ao contrário de barra, não há grandeza extra gated por
    has_voltage/has_angle: um "PMU de linha" mede a mesma P/Q só que com
    fasor sincronizado, ou seja, mais preciso (sigma menor via
    p_sigma_mult), não uma grandeza a mais — não existe "tensão" ou "ângulo"
    de uma linha como variável de estado própria.

    Retorna (measurements, meta) — meta[i] é
    {"busId", "lineId", "meterKind", "quantity"} (exatamente um de
    busId/lineId é não-None) na mesma ordem/índice de measurements[i].
    `quantity` usa os mesmos códigos de ACMeasurement.kind ("p_inj"/"q_inj"/
    "v_bus"/"va_bus"/"p_branch"/"q_branch") — QUANTITY_LABEL no frontend
    (measurements.ts) já sabe rotular todos eles.

    **Ordem determinística, agrupada por tipo** (não pela ordem em que o
    usuário clicou pra configurar os medidores): todo `v_bus` primeiro (por
    índice pandapower crescente), depois todo `p_inj`/`q_inj`, depois todo
    `va_bus`, depois os fluxos de linha (por índice de linha crescente,
    `p_branch`/`q_branch` por lado `from`/`to`). Isso bate com a mesma ordem
    de `ac_measurements.synthetic_full_measurements_from_results()` usada
    nos notebooks (`v_bus` → injeções → fluxos, sempre em ordem de índice) —
    importante porque `sample_noisy_measurement` sorteia ruído na ordem do
    array: se a ordem diverge, o mesmo seed sorteia números diferentes pra
    cada medição, e o `J`/CME_N final do app deixa de ser comparável ao do
    notebook mesmo usando exatamente os mesmos dados de entrada. Antes desta
    correção, a ordem vinha da iteração de um dict populado a partir de
    `topology.measurements`/`topology.line_measurements` — ou seja,
    dependia de em que ordem o usuário tinha clicado nos medidores.
    """
    from tese_dsse.estimacao_estado.ac_measurements import ACMeasurement

    ppc = net._ppc
    Ybus = ppc["internal"]["Ybus"]
    V = ppc["internal"]["V"]
    base_mva = float(ppc["baseMVA"])
    S_inj = (V * np.conj(np.asarray(Ybus @ V).reshape(-1))) * base_mva
    bus_to_ppc = net._pd2ppc_lookups["bus"]

    measurements: list = []
    meta: list[dict] = []

    def add_bus(kind: str, value: float, sigma: float, pp_bus: int, meter_kind: str) -> None:
        measurements.append(ACMeasurement(kind=kind, element=pp_bus, value=value, sigma=sigma))
        meta.append({"busId": pp_to_frontend[pp_bus], "lineId": None, "meterKind": meter_kind, "quantity": kind})

    ordered_buses = sorted(kind_by_bus.keys())

    # Passo 1: v_bus (todas as barras com medidor que mede tensão)
    for pp_bus in ordered_buses:
        kind = kind_by_bus[pp_bus]
        if MEASUREMENT_KIND_SPECS[kind].has_voltage:
            v_value = float(net.res_bus.vm_pu.at[pp_bus])
            add_bus("v_bus", v_value, v_sigma(kind, noise_level, sigma_min), pp_bus, kind)

    # Passo 2: p_inj/q_inj (toda barra configurada sempre contribui as duas)
    for pp_bus in ordered_buses:
        kind = kind_by_bus[pp_bus]
        ppc_index = int(bus_to_ppc[pp_bus])
        p_value = float(np.real(S_inj[ppc_index]))
        q_value = float(np.imag(S_inj[ppc_index]))
        add_bus("p_inj", p_value, p_sigma(kind, p_value, noise_level, sigma_min, sn_mva=base_mva), pp_bus, kind)
        add_bus("q_inj", q_value, p_sigma(kind, q_value, noise_level, sigma_min, sn_mva=base_mva), pp_bus, kind)

    # Passo 3: va_bus (PMU, ângulo direto) — slack excluído: referência fixa
    # (0°), não faz parte do vetor de estado — um PMU ali daria uma linha de
    # Jacobiano zero (h(x) não depende de x nessa linha): não erra nada mas
    # não contribui informação nenhuma, só consome DOF. Mesma exclusão que o
    # DC-WLS já faz em non_slack_pp.
    for pp_bus in ordered_buses:
        kind = kind_by_bus[pp_bus]
        if MEASUREMENT_KIND_SPECS[kind].has_angle and pp_bus != slack_pp:
            va_value = float(net.res_bus.va_degree.at[pp_bus])
            add_bus("va_bus", va_value, va_sigma_deg(kind, noise_level), pp_bus, kind)

    if line_kind_by_pp:
        pp_line_to_frontend = pp_line_to_frontend or {}
        for pp_line in sorted(line_kind_by_pp.keys()):
            kind = line_kind_by_pp[pp_line]
            for side in ("from", "to"):
                p_value = float(net.res_line.at[pp_line, f"p_{side}_mw"])
                q_value = float(net.res_line.at[pp_line, f"q_{side}_mvar"])
                measurements.append(
                    ACMeasurement(
                        kind="p_branch",
                        element=pp_line,
                        value=p_value,
                        sigma=p_sigma(kind, p_value, noise_level, sigma_min, sn_mva=base_mva),
                        side=side,
                        branch_kind="line",
                    )
                )
                meta.append(
                    {
                        "busId": None,
                        "lineId": pp_line_to_frontend.get(pp_line, pp_line),
                        "meterKind": kind,
                        "quantity": "p_branch",
                    }
                )
                measurements.append(
                    ACMeasurement(
                        kind="q_branch",
                        element=pp_line,
                        value=q_value,
                        sigma=p_sigma(kind, q_value, noise_level, sigma_min, sn_mva=base_mva),
                        side=side,
                        branch_kind="line",
                    )
                )
                meta.append(
                    {
                        "busId": None,
                        "lineId": pp_line_to_frontend.get(pp_line, pp_line),
                        "meterKind": kind,
                        "quantity": "q_branch",
                    }
                )

    return measurements, meta


def configured_ac_linearized_rows(
    net: Any,
    kind_by_bus: dict[int, str],
    noise_level: float,
    sigma_min: float,
    slack_pp: int,
    pp_to_frontend: dict[int, int],
    line_kind_by_pp: dict[int, str] | None = None,
    pp_line_to_frontend: dict[int, int] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str], list[dict], int]:
    """Monta o modelo de medição AC configurado (barras + linhas) e o
    lineariza no ponto de operação verdadeiro (x_true, do próprio runpp que
    já resolveu `net`) — não precisa rodar Gauss-Newton para isso, x_true já
    está disponível.

    A linearização usa a mesma convenção afim do modelo DC (z ≈ H·x + c):
    ``H = ∂h/∂x |_{x_true}`` (diferenças finitas) e ``c = h(x_true) − H·x_true``,
    de forma que ``H·x_true + c == h(x_true)`` exatamente. Isso deixa (H, c,
    z_true, sigma) no formato EXATO que configured_dc_rows() produz — então
    hat_matrix/compute_geometric_diagnostics/solve_dc_pure/
    run_bad_data_pipeline funcionam sem nenhuma mudança para o caso AC, só
    que agora "θ" na teoria linear é, na verdade, o vetor de estado AC
    completo [θ; |V|]. `p_branch`/`q_branch` (fluxo de linha) usam
    Yf/Yt do próprio pandapower via ACYbusMeasurementModel — ver
    ac_measurements.py.

    É uma linearização de pequeno sinal em torno do ponto verdadeiro — não
    do estimado (que exigiria resolver Gauss-Newton primeiro). Mesma filosofia
    do que /geometry já faz no caso DC: descreve a geometria do problema de
    medição, não de uma realização de ruído específica.

    Retorna (H, c, z_true, sigma, labels, meta, n_states).
    """
    from tese_dsse.estimacao_estado.ac_measurements import build_ac_ybus_model_from_pandapower

    measurements, meta = build_configured_ac_measurements(
        net, kind_by_bus, noise_level, sigma_min, slack_pp, pp_to_frontend,
        line_kind_by_pp, pp_line_to_frontend,
    )
    if not measurements:
        return np.zeros((0, 0)), np.zeros(0), np.zeros(0), np.zeros(0), [], [], 0

    model = build_ac_ybus_model_from_pandapower(net, measurements)
    x_true = model.state_from_results(net.res_bus.vm_pu, net.res_bus.va_degree)

    H = model.jacobian_finite_difference(x_true)
    z_at_true = model.h(x_true)
    c = z_at_true - H @ x_true

    z_true = np.array([m.value for m in measurements])
    sigma = np.array([m.sigma for m in measurements])
    labels = [_ac_measurement_label(m, net) for m in measurements]

    return H, c, z_true, sigma, labels, meta, model.num_states
