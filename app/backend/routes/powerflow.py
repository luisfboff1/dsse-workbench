"""Rota /api/powerflow — Power flow AC e DC via pandapower."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

router = APIRouter()

BASE_MVA = 1.0


# ─── Modelos de request ──────────────────────────────────────────────────────


class BusInput(BaseModel):
    id: int
    name: str
    type: Literal["slack", "pv", "pq"]
    voltage: float = 1.0
    angle: float = 0.0
    pGen: float = 0.0
    qGen: float = 0.0
    pLoad: float = 0.0
    qLoad: float = 0.0
    # sgen: geração distribuída de PQ fixo (não controla tensão, ao contrário
    # de pGen/gen) — PV/wind/DG num alimentador MV/LV, tipicamente. Ver
    # load_pandapower_case() em topology.py.
    pGenDG: float = 0.0
    qGenDG: float = 0.0
    qMin: float = -0.3
    qMax: float = 0.3
    geoX: float | None = None
    geoY: float | None = None


class LineInput(BaseModel):
    id: int
    from_bus: int = Field(..., alias="from_bus")
    to_bus: int
    resistance: float
    reactance: float
    susceptance: float = 0.0

    model_config = {"populate_by_name": True}


class MeasurementInput(BaseModel):
    """Medidor configurado numa barra — ver MEASUREMENT_KINDS em estimation.py
    para as grandezas/sigma que cada `kind` implica."""

    busId: int
    kind: Literal["pmu", "ami", "scada", "pseudo"]


class LineMeasurementInput(BaseModel):
    """Medidor de fluxo de linha (branch flow) — TC/TP nos dois terminais
    físicos da linha (`from` e `to`, pela convenção de topology.lines), em
    vez de injeção de barra. Configurar um medidor de linha soma DUAS
    medições independentes (uma por terminal — cada RTU tem seu próprio erro
    de medição, mesmo que o valor verdadeiro seja P_ji = -P_ij exato em DC
    sem perdas). Mesmos 4 tipos/tiers de σ de MeasurementInput
    (MEASUREMENT_KIND_SPECS) — só a grandeza física medida muda (P_ij/Q_ij em
    vez de P_inj/Q_inj). Ver kind_by_pp_line() em dc_measurement_model.py."""

    lineId: int
    kind: Literal["pmu", "ami", "scada", "pseudo"]


class SwitchInput(BaseModel):
    """Chave/disjuntor com estado, como `Switch` no frontend (types.ts).

    Só é lido pela cadeia operacional (`routes/pipeline.py`), que precisa do
    estado real da chave para gerar a telemetria dos contatos auxiliares 52a/52b
    e depois comparar a topologia reconstruída com a verdade. Os outros
    endpoints continuam ignorando este campo: para eles a rede ativa já vem
    resolvida em `lines`. Campo opcional — topologias montadas à mão no app não
    têm conceito de chave, e as salvas antes desta adição não o trazem.
    """

    id: int
    from_bus: int = Field(..., alias="from_bus")
    to_bus: int
    closed: bool = True
    name: str | None = None
    r_pu: float | None = None
    x_pu: float | None = None
    b_pu: float | None = None

    model_config = {"populate_by_name": True}


class TopologyInput(BaseModel):
    id: str = "custom"
    name: str = "Custom"
    buses: list[BusInput]
    lines: list[LineInput]
    switches: list[SwitchInput] = Field(default_factory=list)
    measurements: list[MeasurementInput] = Field(default_factory=list)
    line_measurements: list[LineMeasurementInput] = Field(default_factory=list)
    # Needed to invert line.susceptance back into c_nf_per_km correctly in
    # build_net_from_frontend() — most pandapower cases are 50 Hz, but not
    # all (case5/PJM is 60 Hz). Wrong frequency here doesn't break P balance,
    # only skews Q_inj/Q_branch by a few percent on any AC solve.
    frequency_hz: float = 50.0

    @model_validator(mode="before")
    @classmethod
    def remap_from_field(cls, data: Any) -> Any:
        """Mapeia 'from'→'from_bus' e 'to'→'to_bus' do frontend para o Pydantic.

        Vale para `lines` e `switches`: os dois usam 'from'/'to' no JSON do
        frontend, e 'from' é palavra reservada em Python, então não pode ser
        nome de campo do Pydantic.
        """
        if not isinstance(data, dict):
            return data

        data = dict(data)
        for key in ("lines", "switches"):
            if key not in data or not isinstance(data[key], list):
                continue
            fixed = []
            for item in data[key]:
                if isinstance(item, dict):
                    item = dict(item)
                    if "from" in item and "from_bus" not in item:
                        item["from_bus"] = item.pop("from")
                    if "to" in item and "to_bus" not in item:
                        item["to_bus"] = item.pop("to")
                fixed.append(item)
            data[key] = fixed
        return data


class PowerFlowRequest(BaseModel):
    topology: TopologyInput
    method: Literal["pandapower-ac", "pandapower-dc", "lindistflow"] = "pandapower-ac"
    maxIterations: int = 50
    tolerance: float = 1e-4


class CompareRequest(BaseModel):
    topology: TopologyInput


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _topology_to_dict(topology: TopologyInput) -> dict:
    data = topology.model_dump(by_alias=False)
    # Reconverte linhas para o formato que network_builder espera
    return data


def _extract_results(net: Any, bus_id_map: dict[int, int]) -> dict:
    """Extrai resultados do net pandapower e monta resposta JSON."""

    buses_out = []
    for frontend_id, pp_idx in sorted(bus_id_map.items()):
        try:
            vm = float(net.res_bus.at[pp_idx, "vm_pu"])
            va = float(net.res_bus.at[pp_idx, "va_degree"])
        except (KeyError, AttributeError):
            vm, va = 1.0, 0.0

        # Potência gerada = ext_grid + gen
        p_gen = 0.0
        q_gen = 0.0
        if len(net.res_ext_grid) > 0:
            for eg_idx in net.ext_grid[net.ext_grid.bus == pp_idx].index:
                try:
                    p_gen += float(net.res_ext_grid.at[eg_idx, "p_mw"])
                    q_gen += (
                        float(net.res_ext_grid.at[eg_idx, "q_mvar"])
                        if "q_mvar" in net.res_ext_grid.columns
                        else 0.0
                    )
                except KeyError:
                    pass
        if len(net.res_gen) > 0:
            for gen_idx in net.gen[net.gen.bus == pp_idx].index:
                try:
                    p_gen += float(net.res_gen.at[gen_idx, "p_mw"])
                    q_gen += (
                        float(net.res_gen.at[gen_idx, "q_mvar"])
                        if "q_mvar" in net.res_gen.columns
                        else 0.0
                    )
                except KeyError:
                    pass
        if len(net.res_sgen) > 0:
            for sgen_idx in net.sgen[net.sgen.bus == pp_idx].index:
                try:
                    p_gen += float(net.res_sgen.at[sgen_idx, "p_mw"])
                    q_gen += (
                        float(net.res_sgen.at[sgen_idx, "q_mvar"])
                        if "q_mvar" in net.res_sgen.columns
                        else 0.0
                    )
                except KeyError:
                    pass

        p_load = 0.0
        q_load = 0.0
        if len(net.res_load) > 0:
            for load_idx in net.load[net.load.bus == pp_idx].index:
                try:
                    p_load += float(net.res_load.at[load_idx, "p_mw"])
                    q_load += (
                        float(net.res_load.at[load_idx, "q_mvar"])
                        if "q_mvar" in net.res_load.columns
                        else 0.0
                    )
                except KeyError:
                    pass

        buses_out.append(
            {
                "id": frontend_id,
                "voltage": round(vm, 6),
                "angle": round(va, 4),
                "pGen": round(p_gen / BASE_MVA, 5),
                "qGen": round(q_gen / BASE_MVA, 5),
                "pLoad": round(p_load / BASE_MVA, 5),
                "qLoad": round(q_load / BASE_MVA, 5),
            }
        )

    # Map pp_idx -> frontend_id for line results
    pp_to_frontend = {v: k for k, v in bus_id_map.items()}
    lines_out = []
    if len(net.res_line) > 0:
        for line_idx in net.line.index:
            try:
                p_from = float(net.res_line.at[line_idx, "p_from_mw"]) / BASE_MVA
                q_from = (
                    float(net.res_line.at[line_idx, "q_from_mvar"]) / BASE_MVA
                    if "q_from_mvar" in net.res_line.columns
                    else 0.0
                )
                p_to = float(net.res_line.at[line_idx, "p_to_mw"]) / BASE_MVA
                q_to = (
                    float(net.res_line.at[line_idx, "q_to_mvar"]) / BASE_MVA
                    if "q_to_mvar" in net.res_line.columns
                    else 0.0
                )
                pl = (
                    float(net.res_line.at[line_idx, "pl_mw"]) / BASE_MVA
                    if "pl_mw" in net.res_line.columns
                    else abs(p_from + p_to)
                )
            except KeyError:
                p_from = q_from = p_to = q_to = pl = 0.0

            lines_out.append(
                {
                    "id": int(line_idx) + 1,
                    "from": pp_to_frontend.get(int(net.line.at[line_idx, "from_bus"])),
                    "to": pp_to_frontend.get(int(net.line.at[line_idx, "to_bus"])),
                    "pFrom": round(p_from, 5),
                    "qFrom": round(q_from, 5),
                    "pTo": round(p_to, 5),
                    "qTo": round(q_to, 5),
                    "loss": round(abs(pl), 6),
                }
            )

    return {"buses": buses_out, "lines": lines_out}


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/run")
def run_powerflow(req: PowerFlowRequest) -> dict:
    """Roda power flow AC, DC ou LinDistFlow e retorna resultados."""
    from ..services.network_builder import build_net_from_frontend
    import pandapower as pp

    topo_dict = _topology_to_dict(req.topology)
    t0 = time.perf_counter()

    if req.method == "lindistflow":
        from ..paths import ensure_src_on_path

        ensure_src_on_path()
        from tese_dsse.powerflow.lindistflow import run_distflow

        try:
            ldf_res = run_distflow(topo_dict)
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"DistFlow error: {exc}"
            ) from exc

        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "converged": ldf_res["converged"],
            "method": req.method,
            "iterations": ldf_res.get("iterations", 1),
            "iterationHistory": [],
            "executionTime": round(elapsed_ms, 2),
            "buses": ldf_res["buses"],
            "lines": ldf_res.get("lines", []),
        }

    try:
        net, bus_id_map = build_net_from_frontend(topo_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Error building network: {exc}"
        ) from exc

    converged = False
    iterations = 0
    iteration_history: list[dict] = []

    try:
        if req.method == "pandapower-ac":
            pp.runpp(
                net,
                algorithm="nr",
                max_iteration=req.maxIterations,
                tolerance_mva=req.tolerance,
                numba=False,
            )
            converged = bool(net["converged"])
            iterations = (
                int(net._ppc.get("iterations", 0))
                if hasattr(net, "_ppc") and net._ppc
                else 0
            )
        else:  # pandapower-dc
            pp.rundcpp(net)
            converged = True
            iterations = 1
    except Exception:
        converged = False
        iterations = 0

    elapsed_ms = (time.perf_counter() - t0) * 1000

    results = (
        _extract_results(net, bus_id_map) if converged else {"buses": [], "lines": []}
    )

    return {
        "converged": converged,
        "method": req.method,
        "iterations": iterations,
        "iterationHistory": iteration_history,
        "executionTime": round(elapsed_ms, 2),
        **results,
    }


@router.post("/compare")
def compare_methods(req: CompareRequest) -> dict:
    """Roda AC, DC e LinDistFlow na mesma topologia e retorna comparação lado a lado."""
    from ..services.network_builder import build_net_from_frontend
    import pandapower as pp

    from ..paths import ensure_src_on_path

    ensure_src_on_path()
    from tese_dsse.powerflow.lindistflow import run_distflow

    topo_dict = _topology_to_dict(req.topology)
    results = {}

    for method in ["pandapower-ac", "pandapower-dc"]:
        t0 = time.perf_counter()
        algo_used = method
        try:
            net, bus_id_map = build_net_from_frontend(topo_dict)
            if method == "pandapower-ac":
                try:
                    pp.runpp(net, algorithm="nr", max_iteration=50, numba=False)
                    if not bool(net["converged"]):
                        raise RuntimeError("NR did not converge.")
                    algo_used = "nr"
                except Exception:
                    # Fallback: Iwamoto step-size control (projetado para redes de difícil convergência)
                    net2, bus_id_map = build_net_from_frontend(topo_dict)
                    pp.runpp(
                        net2, algorithm="iwamoto_nr", max_iteration=100, numba=False
                    )
                    if not bool(net2["converged"]):
                        raise RuntimeError(
                            "Power flow nr did not converge after 50 iterations! "
                            "Iwamoto NR also did not converge after 100 iterations."
                        )
                    net = net2
                    algo_used = "iwamoto_nr"
                converged = True
            else:
                pp.rundcpp(net)
                converged = True
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            msg = str(exc)
            if "did not converge" in msg:
                msg += (
                    " All AC solvers failed (NR + Iwamoto NR). "
                    "Possible causes: network beyond the maximum loadability point, "
                    "shunts with negative conductance, or degenerate data."
                )
            results[method] = {
                "converged": False,
                "buses": [],
                "lines": [],
                "executionTime": round(elapsed_ms, 2),
                "error": msg,
            }
            continue

        elapsed_ms = (time.perf_counter() - t0) * 1000
        res = _extract_results(net, bus_id_map)
        results[method] = {
            "converged": converged,
            "algorithm": algo_used,
            "executionTime": round(elapsed_ms, 2),
            **res,
        }

    # LinDistFlow
    t0 = time.perf_counter()
    ldf_error: str | None = None
    try:
        ldf_res = run_distflow(topo_dict)
        elapsed_ldf = (time.perf_counter() - t0) * 1000
        results["lindistflow"] = {
            "converged": ldf_res["converged"],
            "iterations": ldf_res.get("iterations", 1),
            "executionTime": round(elapsed_ldf, 2),
            "buses": ldf_res["buses"],
            "lines": ldf_res.get("lines", []),
        }
    except Exception as exc:
        ldf_error = str(exc)
        results["lindistflow"] = {
            "converged": False,
            "buses": [],
            "lines": [],
            "executionTime": 0,
            "error": ldf_error,
        }

    # Tabela comparativa por barramento
    buses_ac = {b["id"]: b for b in results.get("pandapower-ac", {}).get("buses", [])}
    buses_dc = {b["id"]: b for b in results.get("pandapower-dc", {}).get("buses", [])}
    buses_ldf = {b["id"]: b for b in results.get("lindistflow", {}).get("buses", [])}
    all_ids = sorted(
        set(list(buses_ac.keys()) + list(buses_dc.keys()) + list(buses_ldf.keys()))
    )

    def pct(
        est: float | None, ref: float | None, min_ref: float = 0.01
    ) -> float | None:
        """Erro percentual: None se ref ausente, zero ou abaixo do limiar (ângulo ~0)."""
        if est is None or ref is None or abs(ref) < min_ref:
            return None
        return round(abs(est - ref) / abs(ref) * 100, 2)

    def abs_diff(est: float | None, ref: float | None) -> float | None:
        if est is None or ref is None:
            return None
        return round(abs(est - ref), 4)

    comparison = []
    for bus_id in all_ids:
        ac = buses_ac.get(bus_id, {})
        dc = buses_dc.get(bus_id, {})
        ldf = buses_ldf.get(bus_id, {})
        ac_v = ac.get("voltage")
        ac_a = ac.get("angle")
        dc_v = dc.get("voltage")
        dc_a = dc.get("angle")
        ldf_v = ldf.get("voltage")
        ldf_a = ldf.get("angle")
        comparison.append(
            {
                "busId": bus_id,
                # tensões
                "ac_voltage": ac_v,
                "dc_voltage": dc_v,
                "ldf_voltage": ldf_v,
                "dc_voltage_err_pct": pct(dc_v, ac_v, min_ref=0.01),
                "ldf_voltage_err_pct": pct(ldf_v, ac_v, min_ref=0.01),
                # ângulos
                "ac_angle": ac_a,
                "dc_angle": dc_a,
                "ldf_angle": ldf_a,
                "dc_angle_err": abs_diff(dc_a, ac_a),
                "ldf_angle_err": abs_diff(ldf_a, ac_a),
                "dc_angle_err_pct": pct(dc_a, ac_a, min_ref=0.01),
                "ldf_angle_err_pct": pct(ldf_a, ac_a, min_ref=0.01),
            }
        )

    return {
        "ac": results.get("pandapower-ac", {}),
        "dc": results.get("pandapower-dc", {}),
        "ldf": results.get("lindistflow", {}),
        "ldf_error": ldf_error,
        "comparison": comparison,
    }
