"""Utilitarios para estimacao de estado DC linear em redes pandapower.

O modulo concentra a logica que vinha sendo repetida nos notebooks:
montagem de ramos e medicoes, WLS DC puro, correcao iterativa aproximada
de perdas e metricas de comparacao.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pandapower as pp
from pandapower.pypower.idx_brch import BR_R, BR_X, F_BUS, T_BUS
from scipy.stats import chi2

from ..auditoria import AuditTrail, resolve_audit


@dataclass(frozen=True)
class DCLinearModel:
    """Modelo linear ``z = H theta + c + e`` usado pelo estimador DC."""

    H: np.ndarray
    c: np.ndarray
    measurement_table: pd.DataFrame


def chi2_limit(alpha: float, degrees_of_freedom: int) -> float:
    """Retorna o limiar do teste qui-quadrado para a cauda direita ``alpha``."""

    return float(chi2.ppf(1.0 - alpha, df=int(degrees_of_freedom)))


def sigma_weight_from_reference(
    z_ref: np.ndarray,
    noise_rel: float,
    sigma_min: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Constroi ``sigma`` e ``W = diag(1/sigma^2)`` a partir de uma referencia."""

    sigma = np.maximum(np.abs(np.asarray(z_ref, dtype=float)) * noise_rel, sigma_min)
    W = np.diag(1.0 / sigma**2)
    return sigma, W


def sample_noisy_measurement(
    z_true: np.ndarray,
    sigma: np.ndarray,
    seed: int | None = None,
) -> np.ndarray:
    """``z_true + N(0, sigma)`` via ``np.random.default_rng(seed)`` — uma
    chamada, mesma forma (array de sigma na ordem de z_true) sempre.

    Única função de amostragem de ruído do projeto: app/backend/routes/
    estimation.py e baddata.py chamam esta função (antes reconstruíam
    `np.random.default_rng(seed).normal(0.0, sigma)` inline em 6 lugares
    diferentes) e notebooks/simulacao/5_BUS_IEEE_bad_data_analytics.ipynb
    (seção 13, "Verificação vs. Workbench") também — com o mesmo `z_true`/
    `sigma`/`seed`, os três produzem o `z_noisy` EXATO, byte a byte, porque é
    literalmente a mesma chamada de RNG. Isso é o que torna a seção 13 do
    notebook uma validação de verdade (não uma comparação estatística
    aproximada) do pipeline WLS/bad-data compartilhado — se essa função
    mudar, os dois lados mudam juntos, não é possível ficarem dessincronizados
    de novo como aconteceu em 2026-07-03 (ver `configured_dc_rows` em
    dc_measurement_model.py: o notebook usa m=17 desde sempre, o app tinha
    regressado pra m=11 sem ninguém notar até essa comparação apontar)."""

    rng = np.random.default_rng(seed)
    return np.asarray(z_true, dtype=float) + rng.normal(0.0, np.asarray(sigma, dtype=float))


def branch_table_from_lines(net: Any, base_mva: float | None = None) -> pd.DataFrame:
    """Tabela de ramos para redes pandapower sem transformadores modelados no DC.

    Usa os dados fisicos de ``net.line`` para calcular ``r_pu``, ``x_pu``,
    ``b_kl = 1/x_pu`` e ``g_kl = r/(r^2+x^2)``.
    """

    base = float(base_mva if base_mva is not None else net.sn_mva)
    rows: list[dict[str, Any]] = []
    for line_id, line in net.line.iterrows():
        fb = int(line.from_bus)
        tb = int(line.to_bus)
        v_kv = float(net.bus.at[fb, "vn_kv"])
        z_base = v_kv**2 / base
        r_pu = float(line.r_ohm_per_km) * float(line.length_km) / z_base
        x_pu = float(line.x_ohm_per_km) * float(line.length_km) / z_base
        denom = r_pu**2 + x_pu**2
        rows.append(
            {
                "branch_id": len(rows),
                "kind": "line",
                "element": int(line_id),
                "from_bus": fb,
                "to_bus": tb,
                "from_IEEE": (
                    str(net.bus.at[fb, "name"])
                    if "name" in net.bus.columns
                    else str(fb)
                ),
                "to_IEEE": (
                    str(net.bus.at[tb, "name"])
                    if "name" in net.bus.columns
                    else str(tb)
                ),
                "r_pu": r_pu,
                "x_pu": x_pu,
                "b_kl": 1.0 / x_pu if abs(x_pu) > 0 else np.nan,
                "g_kl": r_pu / denom if denom > 0 else 0.0,
                "r_over_x": r_pu / x_pu if abs(x_pu) > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows).set_index("branch_id")


def branch_table_from_rundcpp(net_template: Any) -> pd.DataFrame:
    """Tabela de ramos a partir da matriz interna do ``pandapower.rundcpp``.

    Inclui linhas e transformadores na mesma ordem da matriz ``branch`` do
    PYPOWER/pandapower. Essa ordem e a mesma usada por ``Bf``.
    """

    pp.rundcpp(net_template)
    ppc = net_template._ppc
    branch_lookup = net_template._pd2ppc_lookups["branch"]
    branch_array = ppc["internal"].get("branch", ppc["branch"])
    branch_is = np.asarray(
        ppc["internal"].get("branch_is", np.ones(ppc["branch"].shape[0], dtype=bool)),
        dtype=bool,
    )
    ppc_to_bus = {
        int(ppc_idx): int(pp_bus)
        for pp_bus, ppc_idx in enumerate(net_template._pd2ppc_lookups["bus"])
    }

    rows: list[dict[str, Any]] = []
    active_branch_id = 0
    for kind, key in [("line", "line"), ("trafo", "trafo")]:
        if key not in branch_lookup:
            continue
        start, end = branch_lookup[key]
        for local_id, ppc_idx in enumerate(range(start, end)):
            if ppc_idx >= len(branch_is) or not branch_is[ppc_idx]:
                continue
            row = branch_array[active_branch_id]
            fb = ppc_to_bus[int(row[F_BUS])]
            tb = ppc_to_bus[int(row[T_BUS])]
            r_pu = float(row[BR_R])
            x_pu = float(row[BR_X])
            denom = r_pu**2 + x_pu**2
            rows.append(
                {
                    "branch_id": len(rows),
                    "kind": kind,
                    "element": int(local_id),
                    "from_bus": fb,
                    "to_bus": tb,
                    "from_IEEE": (
                        str(net_template.bus.at[fb, "name"])
                        if "name" in net_template.bus.columns
                        else str(fb)
                    ),
                    "to_IEEE": (
                        str(net_template.bus.at[tb, "name"])
                        if "name" in net_template.bus.columns
                        else str(tb)
                    ),
                    "r_pu": r_pu,
                    "x_pu": x_pu,
                    "b_kl": 1.0 / x_pu if abs(x_pu) > 0 else np.nan,
                    "g_kl": r_pu / denom if denom > 0 else 0.0,
                    "r_over_x": r_pu / x_pu if abs(x_pu) > 0 else np.nan,
                }
            )
            active_branch_id += 1
    return pd.DataFrame(rows).set_index("branch_id")


def build_linear_dc_model_from_rundcpp(
    net_template: Any,
    angle_buses: list[int],
    branch_table: pd.DataFrame,
) -> DCLinearModel:
    """Monta ``H``, ``c`` e tabela de medicoes usando ``Bbus`` e ``Bf``."""

    pp.rundcpp(net_template)
    internal = net_template._ppc["internal"]
    Bbus = internal["Bbus"].toarray()
    Bf = internal["Bf"].toarray()
    Pbusinj = np.asarray(internal["Pbusinj"], dtype=float)
    Pfinj = np.asarray(internal["Pfinj"], dtype=float)
    bus_lookup = net_template._pd2ppc_lookups["bus"]
    state_cols = [int(bus_lookup[b]) for b in angle_buses]

    H_rows: list[np.ndarray] = []
    c_rows: list[float] = []
    meas_rows: list[dict[str, Any]] = []
    for bus in net_template.bus.index:
        bus = int(bus)
        ppc_bus = int(bus_lookup[bus])
        H_rows.append(Bbus[ppc_bus, state_cols])
        c_rows.append(Pbusinj[ppc_bus])
        meas_rows.append(
            {
                "kind": "p_bus",
                "element": bus,
                "side": "-",
                "label": f"P_inj_{bus}",
                "bus": bus,
            }
        )

    for branch_id, row in branch_table.iterrows():
        bid = int(branch_id)
        H_rows.append(Bf[bid, state_cols])
        c_rows.append(Pfinj[bid])
        meas_rows.append(
            {
                "kind": row["kind"],
                "element": int(row["element"]),
                "branch_id": bid,
                "side": "from",
                "label": f"P_{int(row['from_bus'])}->{int(row['to_bus'])}",
                "from_bus": int(row["from_bus"]),
                "to_bus": int(row["to_bus"]),
            }
        )

    for branch_id, row in branch_table.iterrows():
        bid = int(branch_id)
        H_rows.append(-Bf[bid, state_cols])
        c_rows.append(-Pfinj[bid])
        meas_rows.append(
            {
                "kind": row["kind"],
                "element": int(row["element"]),
                "branch_id": bid,
                "side": "to",
                "label": f"P_{int(row['to_bus'])}->{int(row['from_bus'])}",
                "from_bus": int(row["from_bus"]),
                "to_bus": int(row["to_bus"]),
            }
        )

    measurement_table = pd.DataFrame(meas_rows)
    measurement_table.insert(0, "i", range(len(measurement_table)))
    return DCLinearModel(
        H=np.vstack(H_rows).astype(float),
        c=np.asarray(c_rows, dtype=float),
        measurement_table=measurement_table,
    )


def extract_active_power_measurements(
    net_solved: Any,
    base_mva: float,
    branch_table: pd.DataFrame | None = None,
) -> tuple[np.ndarray, pd.DataFrame]:
    """Extrai injeções ativas e fluxos ativos de linhas/trafos em pu."""

    rows: list[dict[str, Any]] = []
    values: list[float] = []
    for bus in net_solved.bus.index:
        bus = int(bus)
        value = -float(net_solved.res_bus.at[bus, "p_mw"]) / base_mva
        values.append(value)
        rows.append(
            {
                "kind": "p_bus",
                "element": bus,
                "side": "-",
                "label": f"P_inj_{bus}",
                "z_pu": value,
            }
        )

    if branch_table is None:
        branch_table = branch_table_from_lines(net_solved, base_mva=base_mva)

    for branch_id, row in branch_table.iterrows():
        kind = str(row["kind"])
        element = int(row["element"])
        if kind == "line":
            value = float(net_solved.res_line.at[element, "p_from_mw"]) / base_mva
        elif kind == "trafo":
            value = float(net_solved.res_trafo.at[element, "p_hv_mw"]) / base_mva
        else:
            raise ValueError(f"Tipo de ramo nao suportado: {kind}")
        values.append(value)
        rows.append(
            {
                "kind": "p_line" if kind == "line" else kind,
                "element": element,
                "branch_id": int(branch_id),
                "side": "from",
                "label": f"P_{int(row['from_bus'])}->{int(row['to_bus'])}",
                "from_bus": int(row["from_bus"]),
                "to_bus": int(row["to_bus"]),
                "z_pu": value,
            }
        )

    for branch_id, row in branch_table.iterrows():
        kind = str(row["kind"])
        element = int(row["element"])
        if kind == "line":
            value = float(net_solved.res_line.at[element, "p_to_mw"]) / base_mva
        elif kind == "trafo":
            value = float(net_solved.res_trafo.at[element, "p_lv_mw"]) / base_mva
        else:
            raise ValueError(f"Tipo de ramo nao suportado: {kind}")
        values.append(value)
        rows.append(
            {
                "kind": "p_line" if kind == "line" else kind,
                "element": element,
                "branch_id": int(branch_id),
                "side": "to",
                "label": f"P_{int(row['to_bus'])}->{int(row['from_bus'])}",
                "from_bus": int(row["from_bus"]),
                "to_bus": int(row["to_bus"]),
                "z_pu": value,
            }
        )

    table = pd.DataFrame(rows)
    table.insert(0, "i", range(len(table)))
    return np.asarray(values, dtype=float), table


def solve_dc_pure(
    z: np.ndarray,
    H: np.ndarray,
    W: np.ndarray,
    c: np.ndarray | None = None,
    *,
    verbose: bool = False,
    audit: AuditTrail | None = None,
) -> dict[str, Any]:
    """Resolve o WLS linear DC sem correcao de perdas.

    Com ``verbose=True`` (ou uma trilha ``audit``), registra a montagem da
    matriz de ganho, do lado direito e do estado estimado para auditoria.
    """

    audit = resolve_audit(audit, verbose, title="DC puro (WLS linear)")
    z = np.asarray(z, dtype=float)
    H = np.asarray(H, dtype=float)
    offset = np.zeros(len(z), dtype=float) if c is None else np.asarray(c, dtype=float)
    G = H.T @ W @ H
    audit.step("z (medicoes)", z, formula="z")
    audit.step("G = H.T W H (matriz de ganho)", G, formula="G = H.T W H")
    b = H.T @ W @ (z - offset)
    audit.step("b = H.T W (z - c)", b, formula="b = H.T W (z-c)")
    theta_hat = np.linalg.solve(G, b)
    audit.step("theta_hat (estado estimado)", theta_hat, formula="G theta = b")
    z_hat = H @ theta_hat + offset
    residual = z - z_hat
    sigma_diag = 1.0 / np.sqrt(np.diag(W))
    J = float(residual @ W @ residual)
    audit.step("J = r.T W r (objetivo)", J, formula="J")
    return {
        "theta_hat": theta_hat,
        "z_hat": z_hat,
        "residual": residual,
        "residual_over_sigma": residual / sigma_diag,
        "J": J,
        "iterations": 1,
        "history_J": [J],
        "history_theta": [theta_hat.copy()],
    }


def solve_dc_with_loss_correction(
    z: np.ndarray,
    H: np.ndarray,
    W: np.ndarray,
    measurement_table: pd.DataFrame,
    branch_table: pd.DataFrame,
    angle_buses: list[int],
    slack_bus: int,
    bus_ids: list[int] | None = None,
    c: np.ndarray | None = None,
    tol: float = 1e-10,
    max_iter: int = 30,
    verbose: bool = False,
    audit: AuditTrail | None = None,
) -> dict[str, Any]:
    """Resolve o WLS DC com correcao iterativa aproximada de perdas."""

    audit = resolve_audit(audit, verbose, title="DC com correcao de perdas")
    z = np.asarray(z, dtype=float)
    H = np.asarray(H, dtype=float)
    offset = np.zeros(len(z), dtype=float) if c is None else np.asarray(c, dtype=float)
    bus_to_idx = {int(b): i for i, b in enumerate(angle_buses)}
    if bus_ids is None:
        bus_ids = sorted(set(bus_to_idx) | {int(slack_bus)})
    bus_ids = [int(b) for b in bus_ids]
    G = H.T @ W @ H
    sigma_diag = 1.0 / np.sqrt(np.diag(W))
    b_initial = H.T @ W @ (z - offset)

    def theta_of(theta_vec: np.ndarray, bus: int) -> float:
        return (
            0.0
            if int(bus) == int(slack_bus)
            else float(theta_vec[bus_to_idx[int(bus)]])
        )

    def losses_per_branch(theta_vec: np.ndarray) -> dict[int, float]:
        losses: dict[int, float] = {}
        for bid, row in branch_table.iterrows():
            fb = int(row["from_bus"])
            tb = int(row["to_bus"])
            dtheta = theta_of(theta_vec, fb) - theta_of(theta_vec, tb)
            losses[int(bid)] = float(row["g_kl"]) * dtheta**2
        return losses

    def correction_from_losses(losses: dict[int, float]) -> np.ndarray:
        delta = np.zeros(len(z), dtype=float)
        loss_at_bus = {int(b): 0.0 for b in bus_ids}
        for bid, loss in losses.items():
            fb = int(branch_table.at[bid, "from_bus"])
            tb = int(branch_table.at[bid, "to_bus"])
            loss_at_bus[fb] = loss_at_bus.get(fb, 0.0) + 0.5 * loss
            loss_at_bus[tb] = loss_at_bus.get(tb, 0.0) + 0.5 * loss

        for _, row in measurement_table.iterrows():
            i = int(row["i"])
            if row["kind"] == "p_bus":
                delta[i] = loss_at_bus.get(int(row["element"]), 0.0)
            else:
                bid = (
                    int(row["branch_id"])
                    if "branch_id" in row and pd.notna(row["branch_id"])
                    else int(row["element"])
                )
                delta[i] = 0.5 * losses[bid]
        return delta

    theta = np.linalg.solve(G, b_initial)
    residual0 = z - offset - H @ theta
    history_J = [float(residual0 @ W @ residual0)]
    history_theta = [theta.copy()]
    history_delta = [np.zeros(len(z), dtype=float)]
    history_z_corr = [(z - offset).copy()]
    history_b = [b_initial.copy()]

    step_inf = np.inf
    iterations = 0
    for nu in range(1, max_iter + 1):
        losses = losses_per_branch(theta)
        delta = correction_from_losses(losses)
        z_corr = z - offset - delta
        b_corr = H.T @ W @ z_corr
        theta_new = np.linalg.solve(G, b_corr)
        step_inf = float(np.max(np.abs(theta_new - theta)))
        theta = theta_new

        residual_corr = z_corr - H @ theta
        J_nu = float(residual_corr @ W @ residual_corr)
        history_J.append(J_nu)
        history_theta.append(theta.copy())
        history_delta.append(delta.copy())
        history_z_corr.append(z_corr.copy())
        history_b.append(b_corr.copy())
        iterations = nu

        if audit.enabled:
            with audit.section(f"iteracao {nu}"):
                audit.step("delta (correcao de perdas)", delta, formula="delta(theta)")
                audit.step("z_corr = z - c - delta", z_corr, formula="z_corr")
                audit.step("theta", theta, formula="G theta = H.T W z_corr")
                audit.step("J = r.T W r", J_nu, formula="J")
                audit.step("||dtheta||_inf", step_inf, formula="max_i |dtheta[i]|")
        if step_inf < tol:
            if audit.enabled:
                audit.note(
                    f"Convergiu: ||dtheta||_inf = {step_inf:.2e} < tol = {tol:.2e}"
                )
            break

    losses = losses_per_branch(theta)
    delta = correction_from_losses(losses)
    z_corr = z - offset - delta
    b_final = H.T @ W @ z_corr
    z_hat = H @ theta + offset + delta
    residual = z - z_hat
    J = float(residual @ W @ residual)

    return {
        "theta_hat": theta,
        "z_hat": z_hat,
        "residual": residual,
        "residual_over_sigma": residual / sigma_diag,
        "J": J,
        "iterations": iterations,
        "history_J": history_J,
        "history_theta": history_theta,
        "history_delta": history_delta,
        "history_z_corr": history_z_corr,
        "history_b": history_b,
        "G": G,
        "b_initial": b_initial,
        "b_final": b_final,
        "z_corr": z_corr,
        "L_per_line": losses,
        "losses_per_branch": losses,
        "delta": delta,
        "max_delta_loss": float(np.max(np.abs(delta))),
        "last_step_inf": step_inf,
    }


def result_metrics(
    result: dict[str, Any],
    theta_ref: np.ndarray,
    chi2_threshold: float,
) -> dict[str, Any]:
    """Metricas resumidas para comparar estimadores/cenarios."""

    err_deg = np.rad2deg(np.asarray(result["theta_hat"]) - np.asarray(theta_ref))
    r_norm = np.asarray(result["residual_over_sigma"], dtype=float)
    return {
        "J": float(result["J"]),
        "passa_chi2": bool(result["J"] < chi2_threshold),
        "max_err_deg": float(np.max(np.abs(err_deg))),
        "rmse_err_deg": float(np.sqrt(np.mean(err_deg**2))),
        "mean_abs_res_norm": float(np.mean(np.abs(r_norm))),
        "max_abs_res_norm": float(np.max(np.abs(r_norm))),
        "iterations": int(result["iterations"]),
    }
