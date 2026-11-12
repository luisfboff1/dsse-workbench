"""Rota /api/baddata — Pipeline de detecção/identificação/correção de bad data."""

from __future__ import annotations

import time
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .powerflow import TopologyInput, _topology_to_dict
from ..services.dc_measurement_model import (
    _ac_measurement_label,
    build_configured_ac_measurements,
    configured_ac_linearized_rows,
    configured_dc_rows,
    kind_by_pp_bus,
    kind_by_pp_line,
    solve_ac_ground_truth,
)
from ..services.network_builder import is_trafo_branch, line_id_map_from_topology, trafo_frontend_ids
from ..paths import ensure_src_on_path

# garante que src/ está no path para qualquer rota importada
ensure_src_on_path()

router = APIRouter()


def _json_finito(obj: Any) -> Any:
    """inf/nan (o t_hat alem do polo e infinito) viram None: JSON nao tem infinito."""
    if isinstance(obj, dict):
        return {k: _json_finito(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_finito(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        return float(obj) if np.isfinite(obj) else None
    return obj

BASE_MVA = 1.0


class GeometryRequest(BaseModel):
    topology: TopologyInput
    method: Literal["dc", "ac"] = Field(
        "dc",
        description=(
            "'dc': linear DC model, only P injection (see z_true_method for how "
            "z_true is computed). 'ac': the full AC measurement set (P, Q, |V|, "
            "and θ for PMU) linearized at the true AC operating point — usually "
            "far more redundant (higher DoF) at the same meter placement, since "
            "every meter contributes several rows instead of just one. Ignores "
            "z_true_method (AC always solves its own fresh power flow)."
        ),
    )
    noise_level: float = Field(0.01, ge=0.0, le=0.5)
    sigma_min: float = Field(0.005, ge=1e-6)
    seed: int | None = None
    alpha: float = Field(0.05, ge=0.001, le=0.2)
    z_true_method: Literal["topology_angles", "rundcpp"] = Field(
        "topology_angles",
        description=(
            "DC only. Como calcular z_true: 'topology_angles' resolve um AC power flow "
            "fresco (NR, fallback Iwamoto) e usa seus ângulos → z=Hθ+c — o campo "
            "bus.angle da topologia é sempre flat-start (0°), então isso não dá "
            "pra só ler; 'rundcpp' usa o resultado do DC PF diretamente."
        ),
    )


class BadDataRequest(BaseModel):
    topology: TopologyInput
    method: Literal["dc", "ac"] = Field(
        "dc", description="Mesma convenção de GeometryRequest.method — ver ali."
    )
    noise_level: float = Field(0.01, ge=0.0, le=0.5)
    sigma_min: float = Field(0.005, ge=1e-6)
    seed: int | None = None
    add_noise: bool = Field(
        True,
        description=(
            "Se True (padrão), z = z_true + N(0,sigma) — o mesmo que Bretas et al. (2017) "
            "descrevem fazer em toda simulação deles ('random noise was added to the set of "
            "measurements... vary up to ±2σᵢ'), e a prática padrão de validação de bad data "
            "(Abur & Gómez-Expósito 2004): testa se o limiar χ² controla falso alarme sob "
            "ruído real. Se False, z = z_true exato (sigma continua definido, só não vira "
            "ruído amostrado) — usar para isolar o efeito de um erro específico (ex.: erro "
            "de parâmetro puro) sem a variância de uma realização de ruído misturada, ou "
            "para reproduzir exatamente um caso do notebook."
        ),
    )
    # Ataque: em medida (z), em parâmetro de linha (H/h(x)) ou nos dois —
    # 'parameter'/'both' só implementados para method='ac' (ver
    # temas/revisao_bibliografica/literatura/bretas2017_malicious_data_innovation.md
    # e notebooks/simulacao/2026-07-18_5_BUS_IEEE_AC_parameter_error_bad_data.ipynb).
    attack_target: Literal["measurement", "parameter", "both", "topology"] = "measurement"
    # Erro de topologia (AC only, 12/11/2026): o status de uma chave no CAMPO difere
    # do cadastro do operador. "open_line": a linha attack_line_id esta aberta no
    # campo e fechada no modelo (em rede radial isso ilha o alimentador e a rota
    # recusa). "close_tie": uma chave de interligacao entre attack_tie_from_bus e
    # attack_tie_to_bus existe no cadastro como ABERTA, mas esta FECHADA no campo
    # (o caso de distribuicao do artigo do CIRED; a GLRT tem a coluna dessa chave).
    attack_topology_mode: Literal["open_line", "close_tie"] = "close_tie"
    attack_tie_from_bus: int | None = Field(None, description="close_tie: barra (frontend) de uma ponta da chave.")
    attack_tie_to_bus: int | None = Field(None, description="close_tie: barra (frontend) da outra ponta.")
    # Injeção de erro grosseiro em medida
    inject_bad_data: bool = True
    bad_data_index: int | None = Field(
        None, description="Índice da medição para erro; None = automático (maior fluxo)"
    )
    bad_data_magnitude: float = Field(
        5.0, ge=1.0, description="Magnitude do erro em múltiplos de sigma"
    )
    # Injeção de erro de parâmetro de linha (r, x, c simétrico) — AC only
    attack_line_id: int | None = Field(
        None, description="Id (frontend) da linha a atacar — obrigatório quando attack_target ∈ {parameter, both}."
    )
    attack_param_sigma_pct: float = Field(
        0.01, ge=0.0001, le=0.5,
        description="Incerteza percentual assumida para o parâmetro de linha ('sigma' do parâmetro) — não há um valor padrão na literatura, ver bretas2017_malicious_data_innovation.md.",
    )
    attack_param_n_sigmas: float = Field(
        10.0, ge=0.0, le=100.0, description="Magnitude do erro de parâmetro, em múltiplos de attack_param_sigma_pct."
    )
    attack_param_symmetric: bool = Field(
        True, description="Se True, distorce r, x e c pelo mesmo fator; se False, só r e x."
    )
    # Dois modelos de erro de parametro (decisoes_tecnicas.md, 03/11/2026):
    # "rxc": r, x (e c) do MODELO = verdade x fator -- comprimento cadastrado
    #   errado; convencao de Bretas 2017 (eq. 16 corrige r/x/c). Usa os campos
    #   attack_param_sigma_pct/n_sigmas/symmetric acima.
    # "admittance": g, b e b_sh com percentuais proprios, na convencao do
    #   notebook do laco e de Zou 2020 / Bretas PowerTech 2025: CAMPO = MODELO x
    #   (1 + t), com o MODELO = a topologia do app (o cadastro) e o erro no
    #   campo. E a variavel em que h(x) e afim (P1) e em que o t_hat do GLRT e
    #   definido, entao o t_hat estimado se compara direto com o t daqui.
    attack_param_mode: Literal["rxc", "admittance"] = "rxc"
    attack_param_t_g: float = Field(-0.3, gt=-1.0, le=10.0, description="admittance: t de g (campo = modelo·(1+t)).")
    attack_param_t_b: float = Field(-0.3, gt=-1.0, le=10.0, description="admittance: t de b.")
    attack_param_t_bsh: float = Field(-0.3, gt=-1.0, le=10.0, description="admittance: t de b_sh.")
    # Combinação do pipeline — 'by_line' (identificação) e 'by_parameter'
    # (correção, eq. 16) só disponíveis em method='ac'.
    # "cme" usa o limiar chi2(m) nominal do artigo. Ele assume que as m
    # parcelas CME_N_i^2 tem variancia parecida -- quando o plano mistura
    # classes de sensor de precisao muito diferente (pseudo vs PMU) o UI fica
    # heterogeneo e o falso alarme medido chega a 100% SEM ataque nenhum.
    # "cme_satterthwaite" calcula graus de liberdade efetivos e controla isso
    # (0-7%). Ver docs/governanca/regra_sigma_min.md secao 6b.
    detection: Literal["residual", "cme", "cme_satterthwaite"] = "residual"
    # "glrt": classify_by_glrt (medida x parametro x topologia pelo t_hat) e a
    # correcao de cada tipo, via run_general_bad_data_pipeline -- o mesmo laco
    # do notebook notebooks/bad_data/2026-10-28_laco_bad_data_IEEE14_57.ipynb.
    # Com "glrt" o campo `correction` e ignorado: a correcao segue o tipo.
    identification: Literal["lnr", "cme", "by_line", "glrt"] = "lnr"
    correction: Literal["remove", "ztrue", "by_parameter"] = "remove"
    alpha: float = Field(0.05, ge=0.001, le=0.2)
    z_true_method: Literal["topology_angles", "rundcpp"] = Field(
        "topology_angles",
        description=(
            "DC only — see GeometryRequest.z_true_method."
        ),
    )


@router.post("/geometry")
def analyze_geometry(req: GeometryRequest) -> dict:
    """
    Analisa a geometria do espaço de medições sem injeção de bad data.

    Retorna: K matrix completa, K_diag, UI, sigma, z_true, labels,
    DOF, chi2_threshold — para o usuário explorar o risco de mascaramento
    antes de definir qual medição atacar. O espaço de medições é o que foi
    configurado em topology.measurements (ver dc_measurement_model.py) — sem
    medidor numa barra, ela não observa nada aqui.
    """
    from ..services.network_builder import build_net_from_frontend
    import pandapower as pp

    from tese_dsse.estimacao_estado.dc_linear import (
        branch_table_from_rundcpp,
        build_linear_dc_model_from_rundcpp,
        solve_dc_pure,
        extract_active_power_measurements,
        chi2_limit,
        sample_noisy_measurement,
    )
    from tese_dsse.estimacao_estado.bad_data import (
        hat_matrix,
        undetectability_index,
        compute_geometric_diagnostics,
    )

    topo_dict = _topology_to_dict(req.topology)
    t0 = time.perf_counter()
    line_id_map = line_id_map_from_topology(topo_dict)
    line_kind_by_pp = kind_by_pp_line(topo_dict, line_id_map)
    pp_line_to_frontend = {v: k for k, v in line_id_map.items()}

    if req.method == "ac":
        try:
            net, bus_id_map = solve_ac_ground_truth(build_net_from_frontend, topo_dict)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"AC power flow error: {exc}") from exc

        pp_to_frontend = {v: k for k, v in bus_id_map.items()}
        kind_by_bus = kind_by_pp_bus(topo_dict, bus_id_map)
        slack_pp = int(net.ext_grid.bus.iloc[0])

        try:
            H, c, z_true, sigma, labels, meta, n = configured_ac_linearized_rows(
                net, kind_by_bus, req.noise_level, req.sigma_min, slack_pp, pp_to_frontend,
                line_kind_by_pp, pp_line_to_frontend,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Error building AC model: {exc}") from exc

        solver_info = {
            "z_true_method": "ac_linearized",
            "z_true_formula": "z_true = h(x_true); H, c linearized at x_true (finite-difference Jacobian)",
            "operating_point": "Fresh AC power flow (NR, Iwamoto fallback)",
            "dc_model": "N/A — AC Ybus model, small-signal linearized at the true operating point",
            "noise_model": "σᵢ scaled per meter kind — see measurement_kinds.py",
        }
    else:
        try:
            net, bus_id_map = build_net_from_frontend(topo_dict)
            pp.rundcpp(net)
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"DC power flow failed: {exc}"
            ) from exc

        pp_to_frontend = {v: k for k, v in bus_id_map.items()}
        kind_by_bus = kind_by_pp_bus(topo_dict, bus_id_map)
        slack_pp = int(net.ext_grid.bus.iloc[0])
        non_slack_pp = sorted(v for v in bus_id_map.values() if v != slack_pp)

        try:
            branch_table = branch_table_from_rundcpp(net)
            model = build_linear_dc_model_from_rundcpp(net, non_slack_pp, branch_table)

            if req.z_true_method == "topology_angles":
                net_ac, _ = solve_ac_ground_truth(build_net_from_frontend, topo_dict)
                angle_true_by_pp = {
                    pp_idx: float(net_ac.res_bus.at[pp_idx, "va_degree"])
                    for pp_idx in bus_id_map.values()
                }
                theta_ref = np.deg2rad([angle_true_by_pp[b] for b in non_slack_pp])
                z_true_full = model.H @ theta_ref + model.c
                solver_info = {
                    "z_true_method": "topology_angles",
                    "z_true_formula": "z_true = H_DC · θ_AC + c_DC",
                    "operating_point": "Fresh AC power flow (NR, Iwamoto fallback)",
                    "dc_model": "Bbus/Bf matrices via pandapower rundcpp",
                    "noise_model": "σᵢ scaled per meter kind — see measurement_kinds.py",
                }
            else:
                angle_true_by_pp = {
                    pp_idx: float(net.res_bus.at[pp_idx, "va_degree"])
                    for pp_idx in bus_id_map.values()
                }
                z_true_full, _ = extract_active_power_measurements(net, BASE_MVA, branch_table)
                solver_info = {
                    "z_true_method": "rundcpp",
                    "z_true_formula": "z_true = DC flows (res_bus/res_line from rundcpp)",
                    "operating_point": "DC operating point (pandapower rundcpp)",
                    "dc_model": "Bbus/Bf matrices via pandapower rundcpp",
                    "noise_model": "σᵢ scaled per meter kind — see measurement_kinds.py",
                }
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"Error building model: {exc}"
            ) from exc

        H, c, z_true, sigma, labels, meta = configured_dc_rows(
            model, pp_to_frontend, non_slack_pp, kind_by_bus,
            z_true_full, angle_true_by_pp, req.noise_level, req.sigma_min,
            line_kind_by_pp, pp_line_to_frontend, net=net,
        )
        n = len(non_slack_pp)

    m = len(labels)
    if m == 0:
        raise HTTPException(
            status_code=422,
            detail="No measurements configured — place at least one meter on a bus or line in Topology.",
        )
    if m < n:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Network not observable with the current meter placement: {m} "
                f"measurement(s) for {n} unknown angle(s). Add more meters in Topology."
            ),
        )

    W = np.diag(1.0 / np.square(sigma))
    z_clean = sample_noisy_measurement(z_true, sigma, req.seed)

    # Estimação baseline (sem bad data)
    try:
        res_base = solve_dc_pure(z_clean, H, W, c)
    except np.linalg.LinAlgError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Network not observable with the current meter placement "
                f"(singular gain matrix): {exc}. Add more meters in Topology."
            ),
        ) from exc
    r_base = np.asarray(res_base["residual"])

    # Geometria
    K = hat_matrix(H, W)
    K_diag = np.diag(K)
    UI = undetectability_index(K_diag)
    diag = compute_geometric_diagnostics(H, W, r_base, sigma)

    DOF = m - n
    threshold = float(chi2_limit(req.alpha, DOF))

    measurements = []
    for i in range(m):
        measurements.append(
            {
                "idx": i,
                "label": labels[i],
                "meterKind": meta[i]["meterKind"],
                "quantity": meta[i]["quantity"],
                "busId": meta[i]["busId"],
                "lineId": meta[i]["lineId"],
                "z_true": round(float(z_true[i]), 6),
                "sigma": round(float(sigma[i]), 6),
                "K_diag": round(float(K_diag[i]), 5),
                "UI": round(float(UI[i]), 4),
                "sigma_r": round(float(diag.sigma_r[i]), 6),
                "r_N_clean": round(float(diag.r_N[i]), 4),
            }
        )

    elapsed_ms = (time.perf_counter() - t0) * 1000

    return {
        "m": m,
        "n": n,
        "DOF": DOF,
        "chi2_threshold": round(threshold, 4),
        "J_baseline": round(float(res_base["J"]), 4),
        "alpha": req.alpha,
        "measurements": measurements,
        "labels": labels,
        "K_matrix": K.round(5).tolist(),
        "H_matrix": H.round(5).tolist(),
        "executionTime": round(elapsed_ms, 2),
        "solver_info": solver_info,
    }


@router.post("/detect")
def detect_bad_data(req: BadDataRequest) -> dict:
    """
    Roda o pipeline completo de bad data: detecção → identificação → correção.

    Despacha para `_detect_bad_data_dc` (medição, `H` fixo) ou
    `_detect_bad_data_ac` (medição e/ou parâmetro de linha, Gauss-Newton
    não-linear, reconstruído a cada iteração — ver
    `tese_dsse.estimacao_estado.ac_bad_data.run_ac_bad_data_pipeline`, mesma
    função usada por
    `notebooks/simulacao/2026-07-18_5_BUS_IEEE_AC_parameter_error_bad_data.ipynb`).
    """
    if req.method == "ac":
        return _detect_bad_data_ac(req)
    return _detect_bad_data_dc(req)


def _detect_bad_data_dc(req: BadDataRequest) -> dict:
    """
    Pipeline DC linear: `H` fixo entre iterações, erro de medida apenas
    (ver `_detect_bad_data_ac` para erro de parâmetro/AC não-linear).
    Retorna diagnósticos geométricos (hat matrix, UI, CME, CNE, LNR) + pipeline
    result. Mesmo espaço de medições configurado em topology.measurements que
    /geometry usa (ver dc_measurement_model.py).
    """
    from ..services.network_builder import build_net_from_frontend
    import pandapower as pp

    from tese_dsse.estimacao_estado.dc_linear import (
        branch_table_from_rundcpp,
        build_linear_dc_model_from_rundcpp,
        solve_dc_pure,
        extract_active_power_measurements,
        chi2_limit,
        sample_noisy_measurement,
    )
    from tese_dsse.estimacao_estado.bad_data import (
        run_bad_data_pipeline,
        compute_geometric_diagnostics,
        hat_matrix,
    )

    if req.attack_target != "measurement":
        raise HTTPException(
            status_code=422,
            detail="attack_target='parameter'/'both' is only implemented for method='ac' — see bretas2017_malicious_data_innovation.md.",
        )
    if req.identification in ("by_line", "glrt") or req.correction == "by_parameter":
        raise HTTPException(
            status_code=422,
            detail="identification='by_line'/'glrt' and correction='by_parameter' are AC-only (need a line topology to group measurements by).",
        )

    topo_dict = _topology_to_dict(req.topology)
    t0 = time.perf_counter()
    line_id_map = line_id_map_from_topology(topo_dict)
    line_kind_by_pp = kind_by_pp_line(topo_dict, line_id_map)
    pp_line_to_frontend = {v: k for k, v in line_id_map.items()}

    try:
        net, bus_id_map = build_net_from_frontend(topo_dict)
        pp.rundcpp(net)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"DC power flow error: {exc}"
        ) from exc

    pp_to_frontend = {v: k for k, v in bus_id_map.items()}
    kind_by_bus = kind_by_pp_bus(topo_dict, bus_id_map)
    slack_pp = int(net.ext_grid.bus.iloc[0])
    non_slack_pp = sorted(v for v in bus_id_map.values() if v != slack_pp)

    try:
        branch_table = branch_table_from_rundcpp(net)
        model = build_linear_dc_model_from_rundcpp(net, non_slack_pp, branch_table)

        if req.z_true_method == "topology_angles":
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
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Error building model: {exc}"
        ) from exc

    H, c, z_true, sigma, labels, meta = configured_dc_rows(
        model, pp_to_frontend, non_slack_pp, kind_by_bus,
        z_true_full, angle_true_by_pp, req.noise_level, req.sigma_min,
        line_kind_by_pp, pp_line_to_frontend, net=net,
    )
    n = len(non_slack_pp)

    m = len(labels)
    if m == 0:
        raise HTTPException(
            status_code=422,
            detail="No measurements configured — place at least one meter on a bus or line in Topology.",
        )
    if m < n:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Network not observable with the current meter placement: {m} "
                f"measurement(s) for {n} unknown angle(s). Add more meters in Topology."
            ),
        )

    W = np.diag(1.0 / np.square(sigma))
    # add_noise=False: z = z_true exato (sigma so entra como peso), para
    # isolar o efeito de um erro especifico ou reproduzir um caso do
    # notebook (ver docstring de BadDataRequest.add_noise).
    z_noisy = sample_noisy_measurement(z_true, sigma, req.seed) if req.add_noise else z_true.copy()

    # Injetar bad data
    bad_data_idx_actual: int | None = None
    if req.inject_bad_data:
        if req.bad_data_index is not None:
            idx = req.bad_data_index
        else:
            # Escolhe medição com maior valor absoluto (linha com maior fluxo)
            idx = int(np.argmax(np.abs(z_true)))
        idx = int(np.clip(idx, 0, len(z_noisy) - 1))
        z_noisy[idx] += req.bad_data_magnitude * sigma[idx]
        bad_data_idx_actual = idx

    # Rodar pipeline
    try:
        pipeline_result = run_bad_data_pipeline(
            z_noisy,
            H,
            W,
            c,
            sigma,
            solve_fn=solve_dc_pure,
            detection=req.detection,
            identification=req.identification,
            correction=req.correction,
            alpha=req.alpha,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc

    # Diagnóstico geométrico inicial (antes do pipeline)
    try:
        init_res = solve_dc_pure(z_noisy, H, W, c)
    except np.linalg.LinAlgError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Network not observable with the current meter placement "
                f"(singular gain matrix): {exc}. Add more meters in Topology."
            ),
        ) from exc
    r_init = np.asarray(init_res["residual"])
    diag = compute_geometric_diagnostics(H, W, r_init, sigma)

    # Hat matrix completa e dados extras
    K = hat_matrix(H, W)
    K_diag = np.diag(K)
    DOF = m - n
    threshold_val = float(chi2_limit(req.alpha, DOF))

    # z_hat = H @ theta_hat + c (valores estimados das medições)
    z_hat_arr = np.asarray(init_res.get("z_hat", []))
    z_hat = [round(float(v), 5) for v in z_hat_arr] if len(z_hat_arr) == m else []

    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Montar tabela de medições
    measurements = []
    for i in range(len(z_noisy)):
        measurements.append(
            {
                "idx": i,
                "label": labels[i],
                "meterKind": meta[i]["meterKind"],
                "quantity": meta[i]["quantity"],
                "busId": meta[i]["busId"],
                "lineId": meta[i]["lineId"],
                "z_true": round(float(z_true[i]), 5),
                "z_noisy": round(float(z_noisy[i]), 5),
                "residual": round(float(r_init[i]), 5),
                "r_N": round(float(diag.r_N[i]), 3),
                "K_diag": round(float(K_diag[i]), 4),
                "UI": round(float(diag.UI[i]), 4),
                "e_U": round(float(diag.e_U[i]), 5),
                "CME": round(float(diag.CME[i]), 5),
                "CME_N": round(float(diag.CME_N[i]), 3),
                "CNE": round(float(diag.CNE[i]), 3),
                "sigma": round(float(sigma[i]), 6),
                "z_hat": round(float(z_hat[i]), 5) if z_hat else None,
                "isBadData": i == bad_data_idx_actual,
                "isFlagged": i in pipeline_result.flagged_indices,
            }
        )

    return {
        "converged": True,
        "injectedBadDataIdx": bad_data_idx_actual,
        "m": m,
        "n": n,
        "DOF": DOF,
        "chi2_threshold": round(threshold_val, 4),  # chi2(alpha, m-n) — referência residual
        "chi2_threshold_initial": round(
            float(pipeline_result.history[0]["threshold"]), 4
        ),  # correto para o método usado
        "J_initial": round(
            float(init_res["J"]), 4
        ),  # sempre o J residual (mesma base para todos)
        "J_detection_initial": round(
            float(pipeline_result.history[0]["J"]), 4
        ),  # J usado pela detecção (CME ou residual)
        "K_matrix": K.round(5).tolist(),
        "pipeline": {
            "J_final": round(float(pipeline_result.J_final), 4),
            "threshold": round(float(pipeline_result.threshold_final), 4),
            "detected": bool(pipeline_result.detected_final),
            "nIterations": pipeline_result.n_iterations,
            "nMeasurementsFinal": pipeline_result.n_measurements_final,
            "flaggedIndices": pipeline_result.flagged_indices,
            "flaggedScores": [round(s, 3) for s in pipeline_result.flagged_scores],
            "actions": pipeline_result.actions,
            "history": _json_finito(pipeline_result.history),
            # um passo por iteracao que agiu: veredito do GLRT, t_hat e a correcao
            "glrtSteps": [
                {
                    "iter": h["iter"], "J": round(float(h["J"]), 4), "threshold": round(float(h["threshold"]), 4),
                    "type": h["attack_type"],
                    "lineId": pp_line_to_frontend.get(h["flagged_line"], h["flagged_line"]) if h.get("flagged_line") is not None else None,
                    "measurementLabel": labels[h["flagged_idx"]] if h["attack_type"] == "measurement" and h["flagged_idx"] < len(labels) and h.get("m") == m else None,
                    "tHat": round(float(h["t_hat"]), 4) if h.get("t_hat") is not None and np.isfinite(h["t_hat"]) else None,
                    "tHatCI": [round(float(v), 4) if np.isfinite(v) else None for v in h["t_hat_ic"]] if h.get("t_hat_ic") else None,
                    "action": a,
                }
                for h, a in zip([h for h in pipeline_result.history if "attack_type" in h], pipeline_result.actions)
            ] if req.identification == "glrt" else None,
        },
        "measurements": measurements,
        "executionTime": round(elapsed_ms, 2),
        "config": {
            "detection": req.detection,
            "identification": req.identification,
            "correction": req.correction,
            "alpha": req.alpha,
        },
    }


def _detect_bad_data_ac(req: BadDataRequest) -> dict:
    """
    Pipeline AC não-linear (Gauss-Newton), reconstruído do zero a cada
    iteração — `H(x*)` muda quando uma medição é removida/corrigida ou
    quando um parâmetro de linha é corrigido. Suporta ataque em medida,
    em parâmetro de linha (`r`/`x`/`c` simétrico) ou nos dois ao mesmo
    tempo (`attack_target`).

    Mesma função de pipeline
    (`tese_dsse.estimacao_estado.ac_bad_data.run_ac_bad_data_pipeline`)
    usada por
    `notebooks/simulacao/2026-07-18_5_BUS_IEEE_AC_parameter_error_bad_data.ipynb` —
    rodar o mesmo caso nos dois lugares deve dar os mesmos números. Ver
    `temas/revisao_bibliografica/literatura/bretas2017_malicious_data_innovation.md`
    para a base teórica (Bretas et al. 2017, eq. 16/17, identificação pg. 213).
    """
    from ..services.network_builder import build_net_from_frontend

    from tese_dsse.estimacao_estado import build_ac_ybus_model_from_pandapower, chi2_limit
    from tese_dsse.estimacao_estado.ac_measurements import ACMeasurement
    from tese_dsse.estimacao_estado.ac_bad_data import (
        run_ac_bad_data_pipeline,
        inject_parameter_error,
        identify_by_line,
        line_signature_score,
        rmse_against_truth,
        run_general_bad_data_pipeline,
        inject_parameter_error_unbalanced,
    )
    from tese_dsse.estimacao_estado.bad_data import compute_geometric_diagnostics
    from tese_dsse.estimacao_estado.dc_linear import sample_noisy_measurement

    if req.correction == "by_parameter" and req.identification not in ("by_line", "glrt"):
        raise HTTPException(
            status_code=422,
            detail="correction='by_parameter' requires identification='by_line'.",
        )

    topo_dict = _topology_to_dict(req.topology)
    t0 = time.perf_counter()
    line_id_map = line_id_map_from_topology(topo_dict)
    line_kind_by_pp = kind_by_pp_line(topo_dict, line_id_map)
    pp_line_to_frontend = {v: k for k, v in line_id_map.items()}

    try:
        net, bus_id_map = solve_ac_ground_truth(build_net_from_frontend, topo_dict)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"AC power flow error: {exc}") from exc

    pp_to_frontend = {v: k for k, v in bus_id_map.items()}
    kind_by_bus = kind_by_pp_bus(topo_dict, bus_id_map)
    slack_pp = int(net.ext_grid.bus.iloc[0])

    try:
        clean_measurements, meta = build_configured_ac_measurements(
            net, kind_by_bus, req.noise_level, req.sigma_min, slack_pp, pp_to_frontend,
            line_kind_by_pp, pp_line_to_frontend,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Error building AC measurements: {exc}") from exc

    m = len(clean_measurements)
    if m == 0:
        raise HTTPException(
            status_code=422,
            detail="No measurements configured — place at least one meter on a bus or line in Topology.",
        )
    labels = [_ac_measurement_label(mm, net) for mm in clean_measurements]

    # ── Resolve a linha atacada (id do frontend -> índice pandapower) ──────
    attack_pp_line: int | None = None
    if req.attack_target in ("parameter", "both"):
        if req.attack_line_id is None:
            raise HTTPException(
                status_code=422,
                detail="attack_line_id is required when attack_target is 'parameter' or 'both'.",
            )
        attack_pp_line = line_id_map.get(req.attack_line_id)
        if attack_pp_line is None:
            is_trafo = any(int(ln["id"]) == req.attack_line_id and is_trafo_branch(ln) for ln in topo_dict["lines"])
            raise HTTPException(status_code=422, detail=(
                f"L{req.attack_line_id} is a transformer with an off-nominal tap: the parameter attack "
                "(r/x/c of a line) does not apply to it. Pick a line." if is_trafo
                else f"Line {req.attack_line_id} not found in topology."))

    # ── Erro de admitância: vai no CAMPO, o modelo do operador é a topologia ──
    # Como no notebook do laço: campo = cadastro·(1+t), σ do plano do cadastro e
    # valores lidos no campo (medidas_de). A biblioteca e o δ do GLRT são do
    # modelo, então pôr o erro no modelo mudaria o caso: com t = −0,7 na L0 do
    # IEEE 14, t̂ = −0,69 com o erro no campo contra −0,58 com o erro no modelo.
    cadastro = None
    if attack_pp_line is not None and req.attack_param_mode == "admittance":
        try:
            net_field, _ = inject_parameter_error_unbalanced(
                net, attack_pp_line, dg_pct=req.attack_param_t_g, db_pct=req.attack_param_t_b,
                dbsh_pct=req.attack_param_t_bsh,
            )
            field_meas, _ = build_configured_ac_measurements(
                net_field, kind_by_bus, req.noise_level, req.sigma_min, slack_pp, pp_to_frontend,
                line_kind_by_pp, pp_line_to_frontend,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Error injecting parameter error: {exc}") from exc
        clean_measurements = [
            ACMeasurement(kind=c.kind, element=c.element, value=f.value, sigma=c.sigma, side=c.side,
                          branch_kind=c.branch_kind)
            for c, f in zip(clean_measurements, field_meas)
        ]
        cadastro, net = net, net_field  # daqui em diante `net` é a verdade (o campo)

    # ── Erro de topologia: o status de uma chave no campo difere do cadastro ──
    # Mesmo arranjo do erro de admitancia: `net` passa a ser o campo (verdade),
    # `cadastro` e o modelo do operador; as medidas sao lidas no campo com os σ
    # do plano do cadastro. close_tie acrescenta a chave nos DOIS (aberta no
    # cadastro, fechada no campo) com um id de frontend novo, para a GLRT poder
    # nomea-la (coluna de linha fora de servico, ver classify_by_glrt nivel 2).
    topology_attack_info: dict | None = None
    if req.attack_target == "topology":
        import pandapower as pp
        import pandapower.topology as pp_top
        from copy import deepcopy

        net_field = deepcopy(net)
        cad = deepcopy(net)
        if req.attack_topology_mode == "open_line":
            if req.attack_line_id is None or line_id_map.get(req.attack_line_id) is None:
                raise HTTPException(status_code=422, detail="open_line needs attack_line_id (a line, not a transformer).")
            pl = line_id_map[req.attack_line_id]
            net_field.line.at[pl, "in_service"] = False
            tie_front = req.attack_line_id
        else:
            fb, tb = req.attack_tie_from_bus, req.attack_tie_to_bus
            if fb is None or tb is None or fb == tb or fb not in bus_id_map or tb not in bus_id_map:
                raise HTTPException(status_code=422, detail="close_tie needs two different buses (attack_tie_from_bus, attack_tie_to_bus).")
            pf, pt = bus_id_map[fb], bus_id_map[tb]
            ja = net.line[((net.line.from_bus == pf) & (net.line.to_bus == pt)) | ((net.line.from_bus == pt) & (net.line.to_bus == pf))]
            if len(ja):
                raise HTTPException(status_code=422, detail=f"Buses {fb} and {tb} are already connected by a line; pick two buses that are not.")
            # parametros da chave = os da primeira linha que toca a barra de origem (tipico do alimentador)
            ref = net.line[(net.line.from_bus == pf) | (net.line.to_bus == pf)]
            ref = ref.iloc[0] if len(ref) else net.line.iloc[0]
            kw = dict(length_km=float(ref.length_km), r_ohm_per_km=float(ref.r_ohm_per_km),
                      x_ohm_per_km=float(ref.x_ohm_per_km), c_nf_per_km=float(ref.c_nf_per_km),
                      max_i_ka=float(ref.max_i_ka), name=f"tie {fb}-{tb}")
            pl = int(pp.create_line_from_parameters(cad, pf, pt, in_service=False, **kw))
            pl_f = int(pp.create_line_from_parameters(net_field, pf, pt, in_service=True, **kw))
            assert pl == pl_f
            tie_front = max(line_id_map.keys(), default=0) + 1
            pp_line_to_frontend[pl] = tie_front
        try:
            pp.runpp(net_field, calculate_voltage_angles=True, init="flat", numba=False)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Power flow with the field topology did not converge: {exc}") from exc
        ilhadas = set(pp_top.unsupplied_buses(net_field))
        if ilhadas:
            raise HTTPException(status_code=422, detail=(
                f"Opening L{req.attack_line_id} disconnects {len(ilhadas)} bus(es) from the source: on a radial "
                "feeder use 'tie switch closed in the field' instead."))
        try:
            field_meas, _ = build_configured_ac_measurements(
                net_field, kind_by_bus, req.noise_level, req.sigma_min, slack_pp, pp_to_frontend,
                line_kind_by_pp, pp_line_to_frontend,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Error building field measurements: {exc}") from exc
        clean_measurements = [
            ACMeasurement(kind=c.kind, element=c.element, value=f.value, sigma=c.sigma, side=c.side,
                          branch_kind=c.branch_kind)
            for c, f in zip(clean_measurements, field_meas)
        ]
        cadastro, net = cad, net_field
        topology_attack_info = {
            "mode": req.attack_topology_mode,
            "lineId": tie_front,
            "fromBus": pp_to_frontend[int(net.line.at[pl, "from_bus"])],
            "toBus": pp_to_frontend[int(net.line.at[pl, "to_bus"])],
            "inTopology": req.attack_topology_mode == "open_line",
            "fieldClosed": req.attack_topology_mode == "close_tie",
        }

    # ── Ruído normal de medição (opcional) + injeção de bad data em medida ──
    # add_noise=False: z = z_true exato (sigma so entra como peso) -- para
    # isolar o efeito de um erro especifico (ex.: erro de parametro puro,
    # pedido do Arturo) sem a variancia de uma realizacao de ruido
    # misturada, ou para reproduzir exatamente um caso do notebook (ver
    # docstring de BadDataRequest.add_noise).
    z_true_arr = np.array([mm.value for mm in clean_measurements])
    sigma_arr = np.array([mm.sigma for mm in clean_measurements])
    z_noisy_arr = (
        sample_noisy_measurement(z_true_arr, sigma_arr, req.seed) if req.add_noise else z_true_arr.copy()
    )
    attacked_measurements = [
        ACMeasurement(kind=mm.kind, element=mm.element, value=float(v), sigma=mm.sigma,
                      side=mm.side, branch_kind=mm.branch_kind)
        for mm, v in zip(clean_measurements, z_noisy_arr)
    ]
    # Snapshot antes da injeção de bad-data em medida (ACMeasurement é frozen,
    # então essa cópia rasa continua válida mesmo depois de
    # attacked_measurements[idx] ser reatribuído abaixo) -- usado só pelo
    # cenário "Baseline" da comparação RMSE (ver mais abaixo): mesmo ruído,
    # zero ataque de nenhum tipo.
    baseline_measurements = list(attacked_measurements)

    bad_data_idx_actual: int | None = None
    if req.attack_target in ("measurement", "both") and req.inject_bad_data:
        idx = req.bad_data_index if req.bad_data_index is not None else int(np.argmax(np.abs(z_true_arr)))
        idx = int(np.clip(idx, 0, m - 1))
        old = attacked_measurements[idx]
        attacked_measurements[idx] = ACMeasurement(
            kind=old.kind, element=old.element, value=old.value + req.bad_data_magnitude * old.sigma,
            sigma=old.sigma, side=old.side, branch_kind=old.branch_kind,
        )
        bad_data_idx_actual = idx

    # ── Rede "atacada": parâmetros corretos, ou distorcidos numa linha ──────
    net_model = cadastro if topology_attack_info is not None else net
    param_attack_info: dict | None = None
    if attack_pp_line is not None:
        try:
            if req.attack_param_mode == "admittance":
                net_model = cadastro  # o erro já está no campo (`net`), ver acima
                r_true = float(net.line.at[attack_pp_line, "r_ohm_per_km"])
                factor_wrong = float(net_model.line.at[attack_pp_line, "r_ohm_per_km"]) / r_true if r_true else 1.0
            else:
                net_model, factor_wrong = inject_parameter_error(
                    net, attack_pp_line, param_sigma_pct=req.attack_param_sigma_pct,
                    n_sigmas=req.attack_param_n_sigmas, symmetric=req.attack_param_symmetric,
                )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Error injecting parameter error: {exc}") from exc
        param_attack_info = {
            "lineId": req.attack_line_id,
            "fromBus": pp_to_frontend[int(net.line.at[attack_pp_line, "from_bus"])],
            "toBus": pp_to_frontend[int(net.line.at[attack_pp_line, "to_bus"])],
            "factor": round(factor_wrong, 6),
            "mode": req.attack_param_mode,
            "tField": ({"g": req.attack_param_t_g, "b": req.attack_param_t_b, "bsh": req.attack_param_t_bsh}
                       if req.attack_param_mode == "admittance" else None),
            "trueParams": {
                "r": round(float(net.line.at[attack_pp_line, "r_ohm_per_km"]), 6),
                "x": round(float(net.line.at[attack_pp_line, "x_ohm_per_km"]), 6),
                "c": round(float(net.line.at[attack_pp_line, "c_nf_per_km"]), 6),
            },
            "wrongParams": {
                "r": round(float(net_model.line.at[attack_pp_line, "r_ohm_per_km"]), 6),
                "x": round(float(net_model.line.at[attack_pp_line, "x_ohm_per_km"]), 6),
                "c": round(float(net_model.line.at[attack_pp_line, "c_nf_per_km"]), 6),
            },
        }

    # ── Diagnóstico geométrico inicial (antes do pipeline) ──────────────────
    try:
        model_init = build_ac_ybus_model_from_pandapower(net_model, attacked_measurements)
        result_init = model_init.solve(x0=model_init.flat_start(), max_iter=30, tol=1e-8)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"AC estimation error: {exc}") from exc

    n_states = model_init.num_states
    if m < n_states:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Network not observable with the current meter placement: {m} "
                f"measurement(s) for {n_states} unknown(s). Add more meters in Topology."
            ),
        )

    H_init = model_init.jacobian(result_init.x, sparse=True)
    z_hat_arr = model_init.h(result_init.x)
    r_init = model_init.z - z_hat_arr
    sigma_init = model_init.sigma
    W_init = 1.0 / sigma_init**2  # vetor: diagonal de W
    diag = compute_geometric_diagnostics(H_init, W_init, r_init, sigma_init)

    DOF = m - n_states
    threshold_val = float(chi2_limit(req.alpha, DOF))

    # ── Ranking por linha (diagnóstico, sempre calculado — mostra se um
    # ataque "tem cara" de erro de parâmetro, mesmo que não tenha sido um) ──
    line_ranking = None
    if len(net.line) > 0:
        _best_line, _best_idx, ranking_rows = identify_by_line(
            attacked_measurements, net_model, diag.CME_N, threshold=3.0
        )
        line_ranking = [
            {
                "lineId": pp_line_to_frontend.get(r["line_id"], r["line_id"]),
                "fromBus": pp_to_frontend.get(r["from_bus"], r["from_bus"]),
                "toBus": pp_to_frontend.get(r["to_bus"], r["to_bus"]),
                "nOwn": r["n_own"],
                "nFlagged": r["n_flagged"],
                "fractionFlagged": round(r["fraction_flagged"], 3),
            }
            for r in ranking_rows
        ]

    # ── Matriz de incidência estrutural (medição × linha, binária) —
    # diagnóstico "seção 8b" do notebook: quais medições pertencem ao
    # conjunto "próprio" de cada linha (puramente estrutural, não depende
    # de nenhum ataque ter acontecido — sempre calculada junto do ranking
    # acima). Ordem de colunas = ordem natural de `net.line` (não a ordem
    # ordenada-por-fração do `line_ranking`), pra colunas não pularem de
    # posição entre execuções diferentes.
    structural_incidence = None
    structural_incidence_lines = None
    if len(net.line) > 0:
        structural_incidence_lines = [
            f"L{pp_line_to_frontend.get(int(lid), int(lid))}" for lid in net.line.index
        ]
        structural_incidence = [[0] * len(net.line) for _ in range(m)]
        for j, (lid, row) in enumerate(net.line.iterrows()):
            own, _flagged = line_signature_score(
                attacked_measurements, diag.CME_N, int(row.from_bus), int(row.to_bus), int(lid), threshold=3.0,
            )
            for i in own:
                structural_incidence[i][j] = 1

    # ── Rodar pipeline ───────────────────────────────────────────────────
    try:
        if req.identification == "glrt":
            pipeline_result = run_general_bad_data_pipeline(
                net_model, attacked_measurements,
                detection=req.detection, classifier="glrt", parameter_correction="t_hat", alpha=req.alpha,
            )
        else:
            pipeline_result = run_ac_bad_data_pipeline(
                net_model, attacked_measurements,
                detection=req.detection, identification=req.identification, correction=req.correction,
                alpha=req.alpha,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc

    # ── Se alguma iteração corrigiu por parâmetro, reporta o resultado ──────
    parameter_correction_info = None
    corrected_line_actions = [a for a in pipeline_result.actions if a.startswith("corrected_parameter_line")]
    if corrected_line_actions:
        corrected_line_id = int(corrected_line_actions[-1].replace("corrected_parameter_line", ""))
        final_net = pipeline_result.net_final
        r_c = float(final_net.line.at[corrected_line_id, "r_ohm_per_km"])
        x_c = float(final_net.line.at[corrected_line_id, "x_ohm_per_km"])
        c_c = float(final_net.line.at[corrected_line_id, "c_nf_per_km"])
        r_true_v = float(net.line.at[corrected_line_id, "r_ohm_per_km"])
        x_true_v = float(net.line.at[corrected_line_id, "x_ohm_per_km"])
        c_true_v = float(net.line.at[corrected_line_id, "c_nf_per_km"])
        # "Errado" = o net que entrou na correção (net_model, antes de
        # qualquer correct_parameter_eq16) -- normalmente o mesmo net_model
        # atacado, já que remover/corrigir MEDIÇÃO não toca r/x/c. Guardado
        # aqui (não só em parameterAttack) pra este bloco ficar
        # autocontido mesmo se a linha identificada não for a atacada.
        r_w = float(net_model.line.at[corrected_line_id, "r_ohm_per_km"])
        x_w = float(net_model.line.at[corrected_line_id, "x_ohm_per_km"])
        c_w = float(net_model.line.at[corrected_line_id, "c_nf_per_km"])
        # eq. 16: p_C = p_E * (1 + CNE/100) — reconstrói o CNE efetivamente
        # usado a partir de r_errado -> r_corrigido (mesmo fator aplicado a
        # r/x/c, ver correct_parameter_eq16).
        cne_used = (r_c / r_w - 1.0) * 100.0 if r_w else None
        parameter_correction_info = {
            "lineId": pp_line_to_frontend.get(corrected_line_id, corrected_line_id),
            "wrongParams": {"r": round(r_w, 6), "x": round(x_w, 6), "c": round(c_w, 6)},
            "correctedParams": {"r": round(r_c, 6), "x": round(x_c, 6), "c": round(c_c, 6)},
            "trueParams": {"r": round(r_true_v, 6), "x": round(x_true_v, 6), "c": round(c_true_v, 6)},
            "cneUsed": round(cne_used, 4) if cne_used is not None and req.identification != "glrt" else None,
            # GLRT: a correcao e p <- (1 + t_hat) p; t_hat da ultima correcao desta linha
            "tHat": next((round(float(h["t_hat"]), 4) for h in reversed(pipeline_result.history)
                          if h.get("attack_type") == "parameter" and h.get("flagged_line") == corrected_line_id
                          and "t_hat" in h), None),
            "residualErrorPct": round((r_c - r_true_v) / r_true_v * 100, 4) if r_true_v else None,
        }

    # ── Comparação RMSE vs. estado verdadeiro — só faz sentido quando um
    # erro de PARÂMETRO está em jogo (é aí que "corrigir a medida" e
    # "corrigir o parâmetro" são alternativas genuinamente diferentes, com
    # trade-offs distintos — ver seção 12 do notebook de erro de parâmetro).
    # x_true só existe aqui porque isto é uma demonstração/validação —
    # usá-lo para DECIDIR qual correção aplicar seria "cola" (não disponível
    # na prática); aqui só reporta o resultado depois da decisão já tomada.
    # Sempre compara contra as mesmas duas combinações de referência
    # (residual/lnr/remove e by_line/by_parameter), reaproveitando
    # pipeline_result quando a escolha do usuário já é uma delas, em vez de
    # depender de qual pipeline o usuário escolheu rodar.
    rmse_comparison = None
    if req.attack_target in ("parameter", "both"):
        true_vm_pu = net.res_bus.vm_pu.to_numpy()
        true_va_degree = net.res_bus.va_degree.to_numpy()

        model_base = build_ac_ybus_model_from_pandapower(net, baseline_measurements)
        result_base = model_base.solve(x0=model_base.flat_start(), max_iter=30, tol=1e-8)
        rmse_va_base, rmse_vm_base = rmse_against_truth(model_base, result_base.x, true_vm_pu, true_va_degree)
        rmse_va_wrong, rmse_vm_wrong = rmse_against_truth(model_init, result_init.x, true_vm_pu, true_va_degree)

        def _reference_pipeline(identification: str, correction: str) -> Any:
            if req.identification == identification and req.correction == correction:
                return pipeline_result
            return run_ac_bad_data_pipeline(
                net_model, attacked_measurements,
                detection="residual", identification=identification, correction=correction,
                alpha=req.alpha,
            )

        pr_meas = _reference_pipeline("lnr", "remove")
        rmse_va_meas, rmse_vm_meas = rmse_against_truth(pr_meas.model, pr_meas.x_hat, true_vm_pu, true_va_degree)
        pr_param = _reference_pipeline("by_line", "by_parameter")
        rmse_va_param, rmse_vm_param = rmse_against_truth(pr_param.model, pr_param.x_hat, true_vm_pu, true_va_degree)

        rmse_comparison = [
            {
                "scenario": "baseline", "label": "Baseline (correct H)",
                "J": round(float(result_base.objective), 4), "detected": bool(result_base.objective > threshold_val),
                "rmseAngleDeg": round(rmse_va_base, 6), "rmseVoltagePu": round(rmse_vm_base, 6),
            },
            {
                "scenario": "no_correction", "label": "Parameter error, no correction",
                "J": round(float(result_init.objective), 4), "detected": bool(result_init.objective > threshold_val),
                "rmseAngleDeg": round(rmse_va_wrong, 6), "rmseVoltagePu": round(rmse_vm_wrong, 6),
            },
            {
                "scenario": "best_measurement", "label": "Best measurement correction (residual/LNR/remove)",
                "J": round(float(pr_meas.J_final), 4), "detected": bool(pr_meas.detected_final),
                "rmseAngleDeg": round(rmse_va_meas, 6), "rmseVoltagePu": round(rmse_vm_meas, 6),
            },
            {
                "scenario": "parameter_correction", "label": "Parameter correction (eq. 16)",
                "J": round(float(pr_param.J_final), 4), "detected": bool(pr_param.detected_final),
                "rmseAngleDeg": round(rmse_va_param, 6), "rmseVoltagePu": round(rmse_vm_param, 6),
            },
        ]

    elapsed_ms = (time.perf_counter() - t0) * 1000

    measurements_out = []
    for i in range(m):
        measurements_out.append(
            {
                "idx": i,
                "label": labels[i],
                "meterKind": meta[i]["meterKind"],
                "quantity": meta[i]["quantity"],
                "busId": meta[i]["busId"],
                "lineId": meta[i]["lineId"],
                "z_true": round(float(z_true_arr[i]), 5),
                "z_noisy": round(float(attacked_measurements[i].value), 5),
                "residual": round(float(r_init[i]), 5),
                "r_N": round(float(diag.r_N[i]), 3),
                "K_diag": round(float(diag.K_diag[i]), 4),
                "UI": round(float(diag.UI[i]), 4),
                "e_U": round(float(diag.e_U[i]), 5),
                "CME": round(float(diag.CME[i]), 5),
                "CME_N": round(float(diag.CME_N[i]), 3),
                "CNE": round(float(diag.CNE[i]), 3),
                "sigma": round(float(sigma_init[i]), 6),
                "z_hat": round(float(z_hat_arr[i]), 5),
                "isBadData": i == bad_data_idx_actual,
                "isFlagged": i in pipeline_result.flagged_indices,
            }
        )

    return {
        "converged": bool(result_init.converged),
        "injectedBadDataIdx": bad_data_idx_actual,
        "m": m,
        "n": n_states,
        "DOF": DOF,
        "chi2_threshold": round(threshold_val, 4),
        "chi2_threshold_initial": round(float(pipeline_result.history[0]["threshold"]), 4),
        "J_initial": round(float(result_init.objective), 4),
        "J_detection_initial": round(float(pipeline_result.history[0]["J"]), 4),
        "K_matrix": diag.K.round(5).tolist() if diag.K is not None else None,
        "pipeline": {
            "J_final": round(float(pipeline_result.J_final), 4),
            "threshold": round(float(pipeline_result.threshold_final), 4),
            "detected": bool(pipeline_result.detected_final),
            "nIterations": pipeline_result.n_iterations,
            "nMeasurementsFinal": pipeline_result.n_measurements_final,
            "flaggedIndices": pipeline_result.flagged_indices,
            "flaggedScores": [round(s, 3) for s in pipeline_result.flagged_scores],
            "flaggedLines": [
                (pp_line_to_frontend.get(l, l) if l is not None else None) for l in pipeline_result.flagged_lines
            ],
            "actions": pipeline_result.actions,
            "history": _json_finito(pipeline_result.history),
            # um passo por iteracao que agiu: veredito do GLRT, t_hat e a correcao
            "glrtSteps": [
                {
                    "iter": h["iter"], "J": round(float(h["J"]), 4), "threshold": round(float(h["threshold"]), 4),
                    "type": h["attack_type"],
                    "lineId": pp_line_to_frontend.get(h["flagged_line"], h["flagged_line"]) if h.get("flagged_line") is not None else None,
                    "measurementLabel": labels[h["flagged_idx"]] if h["attack_type"] == "measurement" and h["flagged_idx"] < len(labels) and h.get("m") == m else None,
                    "tHat": round(float(h["t_hat"]), 4) if h.get("t_hat") is not None and np.isfinite(h["t_hat"]) else None,
                    "tHatCI": [round(float(v), 4) if np.isfinite(v) else None for v in h["t_hat_ic"]] if h.get("t_hat_ic") else None,
                    "action": a,
                }
                for h, a in zip([h for h in pipeline_result.history if "attack_type" in h], pipeline_result.actions)
            ] if req.identification == "glrt" else None,
        },
        "measurements": measurements_out,
        "executionTime": round(elapsed_ms, 2),
        "config": {
            "detection": req.detection,
            "identification": req.identification,
            "correction": req.correction,
            "alpha": req.alpha,
            "attackTarget": req.attack_target,
        },
        "lineRanking": line_ranking,
        "parameterAttack": param_attack_info,
        "topologyAttack": topology_attack_info,
        "parameterCorrection": parameter_correction_info,
        "structuralIncidence": structural_incidence,
        "structuralIncidenceLines": structural_incidence_lines,
        "rmseComparison": rmse_comparison,
    }


class OfflineFigureRequest(BaseModel):
    topology: TopologyInput
    noise_level: float = Field(0.01, ge=0.0, le=0.5)
    sigma_min: float = Field(0.005, ge=1e-6)
    # Layout do unifilar calculado no frontend (computeOneLineLayout, o mesmo ELK
    # da aba Topology): {"nodes": {bus_id: [x, y, w]}, "edges": {line_id: [[x, y], ...]}}
    layout: dict[str, dict[str, Any]]


@router.post("/offline-figure")
def offline_figure(req: OfflineFigureRequest) -> dict:
    """Figura da etapa offline do GLRT (S_l, M = (I-K) S_l, delta_l) para a rede e
    o plano configurados. Mesma figura do notebook do laco e do guia (secao 7.1);
    devolve o HTML autocontido para um iframe."""
    from ..services.network_builder import build_net_from_frontend
    from tese_dsse.estimacao_estado.figura_offline import figura_offline
    from tese_dsse.estimacao_estado.signature_sweep import branch_delta, parameter_sensitivity_library

    topo_dict = _topology_to_dict(req.topology)
    line_id_map = line_id_map_from_topology(topo_dict)
    pp_line_to_frontend = {v: k for k, v in line_id_map.items()}
    try:
        net, bus_id_map = solve_ac_ground_truth(build_net_from_frontend, topo_dict)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"AC power flow error: {exc}") from exc
    pp_to_frontend = {v: k for k, v in bus_id_map.items()}
    plan, _meta = build_configured_ac_measurements(
        net, kind_by_pp_bus(topo_dict, bus_id_map), req.noise_level, req.sigma_min, int(net.ext_grid.bus.iloc[0]),
        pp_to_frontend, kind_by_pp_line(topo_dict, line_id_map), pp_line_to_frontend,
    )
    if not plan:
        raise HTTPException(status_code=422, detail="No measurements configured — place meters in Topology.")
    trafo_by_frontend = {f: t for t, f in trafo_frontend_ids(net).items()}
    ramos = {}
    for l, pts in req.layout.get("edges", {}).items():
        if int(l) in line_id_map:
            ramos[f"L{line_id_map[int(l)]}"] = pts
        elif int(l) in trafo_by_frontend:
            ramos[f"T{trafo_by_frontend[int(l)]}"] = pts
    layout = {
        "nos": {str(bus_id_map[int(b)]): v for b, v in req.layout.get("nodes", {}).items() if int(b) in bus_id_map},
        "ramos": ramos,
    }
    try:
        html = figura_offline(net, plan, parameter_sensitivity_library(net, plan), branch_delta(net), uid="app",
                              layout=layout, rot_barra=pp_to_frontend, rot_linha=pp_line_to_frontend,
                              rot_trafo={t: f for f, t in trafo_by_frontend.items()})
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Offline figure error (observable plan?): {exc}") from exc
    return {"html": "<!doctype html><html><head><meta charset='utf-8'></head><body style='margin:0'>" + html + "</body></html>"}
