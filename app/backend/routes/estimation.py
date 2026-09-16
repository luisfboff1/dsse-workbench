"""Rota /api/estimation — WLS state estimation (linear DC or nonlinear AC/Gauss-Newton)."""

from __future__ import annotations

import time
from dataclasses import replace as dataclass_replace
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .powerflow import TopologyInput, _topology_to_dict
from ..services.trace import build_dc_wls_trace, build_ac_gn_wls_trace
from ..services.dc_measurement_model import (
    _ac_measurement_label,
    build_configured_ac_measurements,
    configured_dc_rows,
    kind_by_pp_bus,
    kind_by_pp_line,
    solve_ac_ground_truth,
)
from ..services.network_builder import line_id_map_from_topology
from ..paths import ensure_src_on_path

ensure_src_on_path()

from tese_dsse.estimacao_estado import state_uncertainty  # noqa: E402

router = APIRouter()

BASE_MVA = 1.0


class EstimationRequest(BaseModel):
    topology: TopologyInput
    ground_truth: Literal["ac", "dc"] = Field(
        "ac",
        description=(
            "Operating point used as z_true. 'ac': solves a fresh AC power flow "
            "(NR, Iwamoto fallback) and uses its angles — bus.angle on the "
            "topology itself is always flat-start (0°), never a solved value, so "
            "this can't just read it off the topology. 'dc': DC power flow "
            "(rundcpp) directly. Ignored (always solved fresh as AC) when "
            "estimation_method='ac-gn-wls', which needs a real AC solve to build "
            "Ybus — there's no meaningful 'DC ground truth' for a voltage-magnitude "
            "state."
        ),
    )
    estimation_method: Literal["dc-wls", "ac-gn-wls"] = Field(
        "dc-wls",
        description=(
            "'dc-wls': linear DC WLS, angles-only state, one-shot solve. "
            "'ac-gn-wls': nonlinear AC WLS via Gauss-Newton, angles + voltage "
            "magnitudes, iterative."
        ),
    )
    noise_level: float = Field(
        0.01,
        ge=0.0,
        le=1.0,
        description="Desvio relativo do ruído gaussiano (ex: 0.01 = 1%)",
    )
    sigma_min: float = Field(1e-4, ge=1e-6, description="Sigma mínimo para medições")
    seed: int | None = Field(None, description="Seed para reprodutibilidade")
    trace: bool = Field(
        False,
        description="Se True, retorna execution_trace com estados intermediários do algoritmo.",
    )


@router.post("/run")
def run_estimation(req: EstimationRequest) -> dict:
    """Roda estimação de estado na topologia fornecida, com o método escolhido."""
    if req.estimation_method == "ac-gn-wls":
        return _run_ac_gn_wls(req)
    return _run_dc_wls(req)


@router.post("/preview")
def preview_measurements(req: EstimationRequest) -> dict:
    """O que 'topology.measurements' vai efetivamente medir, sem rodar nada:
    ground truth (mesma fonte que /run usaria) + sigma por medidor, sem
    injetar ruído nem resolver WLS. Serve pra mostrar, antes de rodar, o que
    cada medidor mede e quão incerto ele é — 'quantas medições tem e quais'.
    """
    from ..services.network_builder import build_net_from_frontend
    import pandapower as pp

    from tese_dsse.estimacao_estado.dc_linear import (
        branch_table_from_rundcpp,
        build_linear_dc_model_from_rundcpp,
        extract_active_power_measurements,
        sample_noisy_measurement,
    )

    topo_dict = _topology_to_dict(req.topology)

    try:
        net, bus_id_map = build_net_from_frontend(topo_dict)
        pp.rundcpp(net)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"DC power flow error: {exc}") from exc

    pp_to_frontend = {v: k for k, v in bus_id_map.items()}
    kind_by_bus = kind_by_pp_bus(topo_dict, bus_id_map)
    slack_pp = int(net.ext_grid.bus.iloc[0])
    non_slack_pp = sorted(v for v in bus_id_map.values() if v != slack_pp)
    line_id_map = line_id_map_from_topology(topo_dict)
    line_kind_by_pp = kind_by_pp_line(topo_dict, line_id_map)
    pp_line_to_frontend = {v: k for k, v in line_id_map.items()}

    if req.estimation_method == "ac-gn-wls":
        try:
            net_ac, bus_id_map = solve_ac_ground_truth(build_net_from_frontend, topo_dict)
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"AC power flow (ground truth) did not converge: {exc}"
            ) from exc
        pp_to_frontend = {v: k for k, v in bus_id_map.items()}
        kind_by_bus = kind_by_pp_bus(topo_dict, bus_id_map)
        slack_pp = int(net_ac.ext_grid.bus.iloc[0])
        try:
            measurements, meas_meta = build_configured_ac_measurements(
                net_ac, kind_by_bus, req.noise_level, req.sigma_min, slack_pp, pp_to_frontend,
                line_kind_by_pp, pp_line_to_frontend,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Error building AC measurements: {exc}") from exc

        # Same rng call shape (seed + sigma array, in this exact row order) as
        # /run — with the same seed this reproduces exactly the z_noisy /run
        # would use, so the preview is a faithful "what will Run actually see".
        sigma_arr = np.array([m.sigma for m in measurements])
        z_noisy_arr = sample_noisy_measurement(np.array([m.value for m in measurements]), sigma_arr, req.seed)
        rows = [
            {
                "label": _ac_measurement_label(m, net_ac),
                "meterKind": meta["meterKind"],
                "quantity": m.kind,
                "busId": meta["busId"],
                "lineId": meta["lineId"],
                "value": round(float(m.value), 5),
                "valueNoisy": round(float(z_noisy_arr[i]), 5),
                "sigma": round(float(m.sigma), 6),
                "sigmaPct": round(100.0 * m.sigma / abs(m.value), 2) if abs(m.value) > 1e-9 else None,
            }
            for i, (m, meta) in enumerate(zip(measurements, meas_meta))
        ]
        n_states = len(bus_id_map) - 1 + len(bus_id_map)
        return {"measurements": rows, "nMeasurements": len(rows), "nStates": n_states}

    try:
        branch_table = branch_table_from_rundcpp(net)
        model = build_linear_dc_model_from_rundcpp(net, non_slack_pp, branch_table)
        if req.ground_truth == "ac":
            net_ac, _ = solve_ac_ground_truth(build_net_from_frontend, topo_dict)
            angle_true_by_pp = {
                pp_idx: float(net_ac.res_bus.at[pp_idx, "va_degree"]) for pp_idx in bus_id_map.values()
            }
            theta_ref = np.deg2rad([angle_true_by_pp[b] for b in non_slack_pp])
            z_true_full = model.H @ theta_ref + model.c
        else:
            angle_true_by_pp = {
                pp_idx: float(net.res_bus.at[pp_idx, "va_degree"]) for pp_idx in bus_id_map.values()
            }
            z_true_full, _ = extract_active_power_measurements(net, BASE_MVA, branch_table)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Error computing ground truth: {exc}") from exc

    _H, _c, z_true, sigma, labels, meta = configured_dc_rows(
        model, pp_to_frontend, non_slack_pp, kind_by_bus,
        z_true_full, angle_true_by_pp, req.noise_level, req.sigma_min,
        line_kind_by_pp, pp_line_to_frontend,
    )
    # Same call (sample_noisy_measurement) as /run — with the same seed this
    # reproduces exactly the z_noisy /run would use.
    z_noisy = sample_noisy_measurement(z_true, sigma, req.seed)
    rows = [
        {
            "label": labels[i],
            "meterKind": meta[i]["meterKind"],
            "quantity": meta[i]["quantity"],
            "busId": meta[i]["busId"],
            "lineId": meta[i]["lineId"],
            "value": round(float(z_true[i]), 5),
            "valueNoisy": round(float(z_noisy[i]), 5),
            "sigma": round(float(sigma[i]), 6),
            "sigmaPct": round(100.0 * sigma[i] / abs(z_true[i]), 2) if abs(z_true[i]) > 1e-9 else None,
        }
        for i in range(len(labels))
    ]
    return {"measurements": rows, "nMeasurements": len(rows), "nStates": len(non_slack_pp)}


def _run_dc_wls(req: EstimationRequest) -> dict:
    """
    Fluxo:
    1. Constrói pandapower net + roda DC (rundcpp) — sempre necessário para as
       matrizes Bbus/Bf do modelo linear, mesmo quando ground_truth='ac'.
    2. z_true vem de duas fontes possíveis (mesma convenção de baddata.py):
       - 'ac': z_true = H_DC · θ_topo + c_DC, usando uma AC power flow real
         (ver comentário abaixo — não é o campo bus.angle).
       - 'dc': z_true direto do resultado do DC power flow.
    3. Filtra o modelo completo (toda barra + toda linha) para só as barras
       com medidor configurado — cada uma contribui uma linha P_inj com sigma
       escalado pelo tipo de medidor (PMU mais preciso, AMI/pseudo mais
       ruidosos). Barras sem medidor não entram — sem medidor de linha ainda,
       as linhas do modelo original nunca entram.
    4. PMU também adiciona uma linha extra: medição direta do próprio ângulo
       (H = vetor one-hot, não precisa de biblioteca extra — o estado do
       modelo DC já É o ângulo).
    5. Adiciona ruído gaussiano e resolve WLS linear com solve_dc_pure.
    """
    from ..services.network_builder import build_net_from_frontend
    import pandapower as pp

    from tese_dsse.estimacao_estado.dc_linear import (
        branch_table_from_rundcpp,
        build_linear_dc_model_from_rundcpp,
        solve_dc_pure,
        extract_active_power_measurements,
        sample_noisy_measurement,
        chi2_limit,
    )

    topo_dict = _topology_to_dict(req.topology)

    t0 = time.perf_counter()
    try:
        net, bus_id_map = build_net_from_frontend(topo_dict)
        pp.rundcpp(net)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"DC power flow error: {exc}"
        ) from exc

    pp_to_frontend = {v: k for k, v in bus_id_map.items()}
    kind_by_bus = kind_by_pp_bus(topo_dict, bus_id_map)
    line_id_map = line_id_map_from_topology(topo_dict)
    line_kind_by_pp = kind_by_pp_line(topo_dict, line_id_map)
    pp_line_to_frontend = {v: k for k, v in line_id_map.items()}

    slack_pp = int(net.ext_grid.bus.iloc[0])
    non_slack_pp = sorted(v for v in bus_id_map.values() if v != slack_pp)

    try:
        branch_table = branch_table_from_rundcpp(net)
        model = build_linear_dc_model_from_rundcpp(net, non_slack_pp, branch_table)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Error building linear DC model: {exc}"
        ) from exc

    try:
        if req.ground_truth == "ac":
            # Bus.angle on the topology is always flat-start (0°) — see
            # load_pandapower_case() in topology.py, PQ-bus V/θ are never
            # solved or user-editable there. So "AC ground truth" has to
            # solve a real AC power flow here, the same way the DC branch
            # below solves its own (rundcpp) — reading a static field would
            # silently make z_true = H·0 + c, i.e. not AC at all.
            net_ac, _ = solve_ac_ground_truth(build_net_from_frontend, topo_dict)
            angle_true_by_pp = {
                pp_idx: float(net_ac.res_bus.at[pp_idx, "va_degree"])
                for pp_idx in bus_id_map.values()
            }
            theta_ref = np.deg2rad([angle_true_by_pp[b] for b in non_slack_pp])
            z_true_full = model.H @ theta_ref + model.c
        else:
            angle_true_by_pp = {
                pp_idx: float(net.res_bus.at[pp_idx, "va_degree"])
                for pp_idx in bus_id_map.values()
            }
            z_true_full, _ = extract_active_power_measurements(net, BASE_MVA, branch_table)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Error computing ground truth / extracting measurements: {exc}. "
                + ("Try ground_truth='dc' instead." if req.ground_truth == "ac" else "")
            ),
        ) from exc

    # ── Filtra pro que foi configurado em Topology, + linhas extras de PMU ──
    H_final, c_final, z_true_final, sigma_final, labels_final, meta_final = configured_dc_rows(
        model, pp_to_frontend, non_slack_pp, kind_by_bus,
        z_true_full, angle_true_by_pp, req.noise_level, req.sigma_min,
        line_kind_by_pp, pp_line_to_frontend,
    )

    n = len(non_slack_pp)
    m = len(labels_final)
    if m == 0:
        raise HTTPException(
            status_code=422,
            detail="No measurements configured — place at least one meter on a bus in Topology.",
        )
    if m < n:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Network not observable with the current meter placement: {m} "
                f"measurement(s) for {n} unknown angle(s) — need at least as many "
                "measurements as unknowns. Add more meters in Topology."
            ),
        )

    # Adicionar ruído gaussiano
    z_noisy = sample_noisy_measurement(z_true_final, sigma_final, req.seed)
    W = np.diag(1.0 / np.square(sigma_final))

    # Resolver WLS
    try:
        result = solve_dc_pure(z_noisy, H_final, W, c_final)
    except np.linalg.LinAlgError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Network not observable with the current meter placement "
                f"(singular gain matrix): {exc}. Add more meters in Topology."
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"WLS solver error: {exc}"
        ) from exc

    theta_hat = np.asarray(result["theta_hat"])
    residual = np.asarray(result["residual"])
    z_hat = np.asarray(result["z_hat"])

    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Incerteza a priori do estado: sigma_theta = sqrt(diag(G^-1)), com G = H^T W H.
    # Nao depende de z nem do estado verdadeiro -- e a metrica de confianca que
    # sobrevive em operacao real, onde nao existe ground truth para calcular RMSE.
    # Complementar (e estatisticamente independente) do J/chi2: sob ruido gaussiano
    # Cov(x_hat - x, r) = 0, entao o J nao informa nada sobre o erro do estado.
    try:
        sigma_theta_rad, halfwidth_rad = state_uncertainty(H_final, W, confidence=0.95)
        sigma_theta_deg = np.rad2deg(sigma_theta_rad)
        halfwidth_deg = np.rad2deg(halfwidth_rad)
    except np.linalg.LinAlgError:
        sigma_theta_deg = halfwidth_deg = None

    # Construir estado estimado (slack = 0, resto = theta_hat)
    states = []
    theta_idx = 0
    for pp_idx in sorted(bus_id_map.values()):
        frontend_id = pp_to_frontend[pp_idx]
        if pp_idx == slack_pp:
            angle_est_deg = 0.0
            angle_std_deg = 0.0  # slack e referencia: variancia nula por construcao
            angle_ci_deg = 0.0
        else:
            angle_est_deg = float(np.rad2deg(theta_hat[theta_idx]))
            angle_std_deg = (
                float(sigma_theta_deg[theta_idx]) if sigma_theta_deg is not None else None
            )
            angle_ci_deg = (
                float(halfwidth_deg[theta_idx]) if halfwidth_deg is not None else None
            )
            theta_idx += 1
        angle_true_deg = angle_true_by_pp[pp_idx]
        states.append(
            {
                "busId": frontend_id,
                "angleTrue_deg": round(angle_true_deg, 4),
                "angleEst_deg": round(angle_est_deg, 4),
                "error_deg": round(abs(angle_est_deg - angle_true_deg), 6),
                "angleStd_deg": round(angle_std_deg, 6) if angle_std_deg is not None else None,
                "angleCi95_deg": round(angle_ci_deg, 6) if angle_ci_deg is not None else None,
            }
        )

    # Resíduos
    residuals = []
    for i in range(len(z_noisy)):
        residuals.append(
            {
                "idx": i,
                "label": labels_final[i],
                "meterKind": meta_final[i]["meterKind"],
                "quantity": meta_final[i]["quantity"],
                "busId": meta_final[i]["busId"],
                "lineId": meta_final[i]["lineId"],
                "z_true": round(float(z_true_final[i]), 5),
                "z_noisy": round(float(z_noisy[i]), 5),
                "z_hat": round(float(z_hat[i]), 5),
                "sigma": round(float(sigma_final[i]), 6),
                "residual": round(float(residual[i]), 5),
                "residual_normalized": round(
                    float(result["residual_over_sigma"][i]), 3
                ),
            }
        )

    dof = m - n

    return {
        "converged": True,
        "method": "dc-wls",
        "groundTruth": req.ground_truth,
        "iterations": 1,
        "J": round(float(result["J"]), 4),
        "dof": dof,
        # alpha=0.05 (95%) — mesmo teste chi2(alpha, dof) real do Bad Data tab
        # e do notebook (chi2_limit == scipy.stats.chi2.ppf), não a aproximação
        # normal (dof + 2*sqrt(2*dof)) que o frontend calculava antes.
        "chi2Threshold": round(chi2_limit(0.05, dof), 4) if dof > 0 else None,
        "executionTime": round(elapsed_ms, 2),
        "states": states,
        "residuals": residuals,
        "iterationHistory": [{"iteration": 0, "J": round(float(result["J"]), 4)}],
        "noiseLevel": req.noise_level,
        "nMeasurements": m,
        "nStates": n,
        "execution_trace": build_dc_wls_trace(
            H_final=H_final,
            c_final=c_final,
            sigma_final=sigma_final,
            z_true_final=z_true_final,
            z_noisy=z_noisy,
            labels_final=labels_final,
            result=result,
            dof=dof,
            chi2_threshold=round(chi2_limit(0.05, dof), 4) if dof > 0 else None,
            elapsed_ms=elapsed_ms,
        ).to_dict() if req.trace else None,
    }


def _run_ac_gn_wls(req: EstimationRequest) -> dict:
    """
    Fluxo:
    1. Roda AC power flow (Newton-Raphson, fallback Iwamoto) — é o ground
       truth E a fonte das matrizes Ybus/Yf/Yt usadas pelo modelo de medição.
    2. Monta medições só para as barras com medidor configurado em Topology
       (_build_configured_ac_measurements) — cada tipo mede um subconjunto de
       {V, θ, P, Q}, PMU sendo o único com θ direto.
    3. Adiciona ruído gaussiano (ACMeasurement é imutável — reconstrói cada
       medição com o valor ruidoso via dataclasses.replace).
    4. Resolve WLS não linear por Gauss-Newton (flat start V=1, θ=0), com
       Jacobiana por diferenças finitas.
    """
    from ..services.network_builder import build_net_from_frontend
    import pandapower as pp

    from tese_dsse.estimacao_estado.ac_measurements import build_ac_ybus_model_from_pandapower
    from tese_dsse.estimacao_estado.dc_linear import sample_noisy_measurement, chi2_limit

    topo_dict = _topology_to_dict(req.topology)
    t0 = time.perf_counter()

    try:
        net, bus_id_map = build_net_from_frontend(topo_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Error building network: {exc}"
        ) from exc

    try:
        pp.runpp(net, algorithm="nr", max_iteration=50, numba=False)
        if not bool(net["converged"]):
            raise RuntimeError("NR did not converge.")
    except Exception:
        try:
            net2, bus_id_map = build_net_from_frontend(topo_dict)
            pp.runpp(net2, algorithm="iwamoto_nr", max_iteration=100, numba=False)
            if not bool(net2["converged"]):
                raise RuntimeError("Iwamoto NR also did not converge.")
            net = net2
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"AC power flow (ground truth) did not converge: {exc}. "
                    "ac-gn-wls needs a solved AC operating point to build the "
                    "Ybus-based measurement model — try dc-wls instead, or fix "
                    "the network data."
                ),
            ) from exc

    pp_to_frontend = {v: k for k, v in bus_id_map.items()}
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
        raise HTTPException(
            status_code=422, detail=f"Error building AC measurements: {exc}"
        ) from exc

    if not clean_measurements:
        raise HTTPException(
            status_code=422,
            detail="No measurements configured — place at least one meter on a bus in Topology.",
        )

    n_states = len(bus_id_map) - 1 + len(bus_id_map)  # angles (n-1) + |V| (n)
    if len(clean_measurements) < n_states:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Network not observable with the current meter placement: "
                f"{len(clean_measurements)} measurement(s) for {n_states} unknown(s) "
                "(θ for every non-slack bus + |V| for every bus). Add more meters "
                "in Topology, or use dc-wls (fewer unknowns, angles only)."
            ),
        )

    z_true = np.array([m.value for m in clean_measurements])
    sigma = np.array([m.sigma for m in clean_measurements])
    z_noisy = sample_noisy_measurement(z_true, sigma, req.seed)
    noisy_measurements = [
        dataclass_replace(m, value=float(v))
        for m, v in zip(clean_measurements, z_noisy)
    ]

    try:
        model = build_ac_ybus_model_from_pandapower(net, noisy_measurements)
        result = model.solve(x0=model.flat_start(), max_iter=30, tol=1e-8)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"AC Gauss-Newton WLS solver error: {exc}"
        ) from exc

    x_hat = result.x
    z_hat = model.h(x_hat)
    state_table = model.state_to_table(x_hat)
    est_by_bus = {
        int(b): (float(vm), float(va))
        for b, vm, va in zip(state_table.bus, state_table.vm_pu, state_table.va_degree)
    }

    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Incerteza a priori do estado no ponto convergido: sqrt(diag((H^T W H)^-1)),
    # com H = J(x_hat). Estado do modelo AC = [angulos das angle_buses | |V| de
    # bus_order], entao os dois blocos sao fatiados separadamente. Ver comentario
    # equivalente no ramo DC sobre por que isto -- e nao o J/chi2 -- e a metrica
    # de confianca da estimativa.
    angle_std_by_pp: dict[int, float] = {}
    vm_std_by_pp: dict[int, float] = {}
    try:
        H_ac = model.jacobian_finite_difference(x_hat)
        W_ac = np.diag(1.0 / np.square(sigma))
        sigma_x, _ = state_uncertainty(H_ac, W_ac, confidence=0.95)
        for bus in model.angle_buses:
            angle_std_by_pp[int(bus)] = float(
                np.rad2deg(sigma_x[model.angle_state_index[bus]])
            )
        for pos, bus in enumerate(model.bus_order):
            vm_std_by_pp[int(bus)] = float(sigma_x[model.vm_state_offset + pos])
    except (np.linalg.LinAlgError, AttributeError, ValueError):
        angle_std_by_pp, vm_std_by_pp = {}, {}

    states = []
    for pp_idx in sorted(bus_id_map.values()):
        frontend_id = pp_to_frontend[pp_idx]
        v_est, theta_est = est_by_bus[pp_idx]
        v_true = float(net.res_bus.at[pp_idx, "vm_pu"])
        theta_true = float(net.res_bus.at[pp_idx, "va_degree"])
        # slack nao entra em angle_buses: angulo fixo, desvio nulo por construcao.
        angle_std = angle_std_by_pp.get(pp_idx, 0.0 if pp_idx == slack_pp else None)
        vm_std = vm_std_by_pp.get(pp_idx)
        states.append(
            {
                "busId": frontend_id,
                "angleTrue_deg": round(theta_true, 4),
                "angleEst_deg": round(theta_est, 4),
                "error_deg": round(abs(theta_est - theta_true), 6),
                "vTrue_pu": round(v_true, 5),
                "vEst_pu": round(v_est, 5),
                "vError_pu": round(abs(v_est - v_true), 6),
                "angleStd_deg": round(angle_std, 6) if angle_std is not None else None,
                "angleCi95_deg": round(1.959964 * angle_std, 6) if angle_std is not None else None,
                "vStd_pu": round(vm_std, 7) if vm_std is not None else None,
                "vCi95_pu": round(1.959964 * vm_std, 7) if vm_std is not None else None,
            }
        )

    residual = z_noisy - z_hat
    residuals = []
    for i, meas in enumerate(noisy_measurements):
        residuals.append(
            {
                "idx": i,
                "label": _ac_measurement_label(meas, net),
                "meterKind": meas_meta[i]["meterKind"],
                "quantity": meas.kind,
                "busId": meas_meta[i]["busId"],
                "lineId": meas_meta[i]["lineId"],
                "z_true": round(float(z_true[i]), 5),
                "z_noisy": round(float(z_noisy[i]), 5),
                "z_hat": round(float(z_hat[i]), 5),
                "sigma": round(float(sigma[i]), 6),
                "residual": round(float(residual[i]), 5),
                "residual_normalized": round(float(residual[i] / sigma[i]), 3),
            }
        )

    m_count = len(noisy_measurements)
    n_count = model.num_states
    dof = m_count - n_count
    iteration_history = [
        {"iteration": it.iteration, "J": round(float(it.objective), 4), "stepNormInf": round(float(it.step_norm_inf), 6)}
        for it in result.iterations
    ]

    return {
        "converged": bool(result.converged),
        "method": "ac-gn-wls",
        "groundTruth": "ac",
        "iterations": len(result.iterations),
        "J": round(float(result.objective), 4),
        "dof": dof,
        "chi2Threshold": round(chi2_limit(0.05, dof), 4) if dof > 0 else None,
        "executionTime": round(elapsed_ms, 2),
        "states": states,
        "residuals": residuals,
        "iterationHistory": iteration_history,
        "noiseLevel": req.noise_level,
        "nMeasurements": m_count,
        "nStates": n_count,
        "execution_trace": build_ac_gn_wls_trace(
            result=result,
            model=model,
            z_true=z_true,
            z_noisy=z_noisy,
            sigma=sigma,
            dof=dof,
            chi2_threshold=round(chi2_limit(0.05, dof), 4) if dof > 0 else None,
            elapsed_ms=elapsed_ms,
        ).to_dict() if req.trace else None,
    }
