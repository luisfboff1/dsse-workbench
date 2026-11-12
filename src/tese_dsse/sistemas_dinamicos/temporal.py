"""Offline AC time-series study: physical snapshots and paired WLS/EKF.

The caller supplies an already configured pandapower network and its meter
factory. All estimators see exactly the same sampled (possibly attacked)
measurement vector. Neither initialization nor Q uses the evaluated truth.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

import numpy as np
import pandapower as pp

from ..estimacao_estado.ac_measurements import (
    ACMeasurement,
    build_ac_ybus_model_from_pandapower,
)
from .kalman import InnovationAdaptation, run_extended_kalman_filter
from ..auditoria import AuditTrail, resolve_audit


@dataclass(frozen=True)
class TemporalAttack:
    channel: int
    start_hour: float
    end_hour: float
    bias_sigma: float


@dataclass
class TemporalFrame:
    hour: float
    load_factor: float
    dg_factor: float
    physical_buses: list[dict]
    physical_lines: list[dict]
    measurements: list[ACMeasurement]
    truth: np.ndarray
    observed: np.ndarray
    attacked: np.ndarray
    wls_state: np.ndarray
    wls_covariance: np.ndarray | None
    wls_converged: bool
    wls_iterations: int
    wls_objective: float
    ekf_state: np.ndarray
    ekf_covariance: np.ndarray
    innovation: float | None
    events: list[dict]


def _covariance(model, state: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    weighted = model.jacobian_finite_difference(state) / sigma[:, None]
    if np.linalg.matrix_rank(weighted) < model.num_states:
        raise ValueError("Meter placement is not observable: weighted Jacobian has deficient rank.")
    covariance = np.linalg.solve(weighted.T @ weighted, np.eye(model.num_states))
    return (covariance + covariance.T) / 2


def run_temporal_study(
    net,
    *,
    measurement_factory: Callable[[object], list[ACMeasurement]],
    hours: np.ndarray,
    load_factors: np.ndarray,
    dg_factors: np.ndarray,
    seed: int = 42,
    attack: TemporalAttack | None = None,
    load_event_bus: int | None = None,
    load_event_start: float = 0,
    load_event_end: float = 0,
    load_event_factor: float = 1,
    angle_process_std: float = 0.005,
    voltage_process_std: float = 0.005,
    verbose: bool = False,
    audit: AuditTrail | None = None,
) -> tuple[object, list[TemporalFrame]]:
    """Run fixed-topology, synchronized offline QSTS and random-walk EKF.

    Process standard deviations are rad / sqrt(hour) and pu / sqrt(hour).
    R is evaluated from configured sensor rules at each frame. The first EKF
    state/P come from WLS on frame zero; that observation is not assimilated
    twice. The supplied network is restored even if a frame fails.
    """
    trail = resolve_audit(audit, verbose, title="run_temporal_study")
    hours = np.asarray(hours, dtype=float)
    load_factors = np.asarray(load_factors, dtype=float)
    dg_factors = np.asarray(dg_factors, dtype=float)
    if (
        hours.ndim != 1
        or len(hours) < 2
        or load_factors.shape != hours.shape
        or dg_factors.shape != hours.shape
        or not all(np.all(np.isfinite(a)) for a in (hours, load_factors, dg_factors))
        or np.any(np.diff(hours) <= 0)
        or np.any(load_factors < 0)
        or np.any(dg_factors < 0)
    ):
        raise ValueError(
            "Supply increasing times and finite nonnegative profiles of the same size."
        )
    if not all(np.isfinite(v) and v > 0 for v in (angle_process_std, voltage_process_std)):
        raise ValueError("Process standard deviations must be finite and positive.")
    if attack and (
        not np.isfinite(attack.bias_sigma)
        or attack.channel < 0
        or not 0 <= attack.start_hour < attack.end_hour <= hours[-1]
    ):
        raise ValueError("Invalid attack channel or time window.")
    if load_event_bus is not None and (
        load_event_bus not in net.bus.index
        or not 0 <= load_event_start < load_event_end <= hours[-1]
        or not np.isfinite(load_event_factor)
        or load_event_factor < 0
    ):
        raise ValueError("Invalid load-event bus, multiplier or time window.")

    original_load = net.load[["p_mw", "q_mvar"]].copy()
    original_dg = net.sgen[["p_mw", "q_mvar"]].copy()
    rng = np.random.default_rng(seed)
    frames: list[TemporalFrame] = []
    model = None
    previous_wls = previous_ekf = previous_P = None
    signature = None
    try:
        for k, hour in enumerate(hours):
            net.load.loc[:, ["p_mw", "q_mvar"]] = original_load * load_factors[k]
            net.sgen.loc[:, ["p_mw", "q_mvar"]] = original_dg * dg_factors[k]
            load_active = load_event_bus is not None and load_event_start <= hour < load_event_end
            if load_active:
                indices = net.load.index[net.load.bus == load_event_bus]
                net.load.loc[indices, ["p_mw", "q_mvar"]] *= load_event_factor
            pp.runpp(
                net,
                calculate_voltage_angles=True,
                init="auto" if k == 0 else "results",
                max_iteration=50,
                tolerance_mva=1e-9,
                numba=False,
            )
            if not net.converged or not np.all(np.isfinite(net.res_bus.vm_pu)):
                raise ValueError(f"AC power flow failed at hour {hour:g}; no trajectory published.")
            clean = measurement_factory(net)
            current_signature = [(m.kind, m.element, m.side, m.branch_kind) for m in clean]
            if signature is not None and signature != current_signature:
                raise ValueError(
                    "Temporal study requires a fixed, synchronized measurement layout."
                )
            signature = current_signature
            truth = np.array([m.value for m in clean])
            sigma = np.array([m.sigma for m in clean])
            if not len(clean) or np.any(sigma <= 0) or not np.all(np.isfinite(sigma)):
                raise ValueError(
                    "Configure observable meters with finite positive uncertainty in Topology."
                )
            observed = truth + rng.normal(size=len(clean)) * sigma
            attacked = np.zeros(len(clean), dtype=bool)
            if attack:
                if attack.channel >= len(clean):
                    raise ValueError(
                        "Attack measurement channel does not exist in this meter layout."
                    )
                if attack.start_hour <= hour < attack.end_hour:
                    observed[attack.channel] += attack.bias_sigma * sigma[attack.channel]
                    attacked[attack.channel] = True
            noisy = [replace(m, value=float(z)) for m, z in zip(clean, observed)]
            if model is None:
                model = build_ac_ybus_model_from_pandapower(net, noisy)
                if len(clean) < model.num_states:
                    raise ValueError(
                        f"Not observable: {len(clean)} measurements for {model.num_states} states."
                    )
                previous_wls = model.flat_start()
            model.measurements = noisy
            result = model.solve(x0=previous_wls, max_iter=30, tol=1e-8)
            if (
                not np.all(np.isfinite(result.x))
                or not np.isfinite(result.objective)
                or np.any(result.x[model.vm_state_offset :] <= 0)
            ):
                raise ValueError(
                    f"Invalid WLS state at hour {hour:g}: non-finite values or non-positive voltage magnitude."
                )
            covariance = _covariance(model, result.x, sigma) if result.converged else None
            events = []
            if not result.converged:
                events.append({"type": "wls_not_converged", "action": "inspect_measurements"})
            if k == 0:
                if not result.converged:
                    raise ValueError("Frame-zero WLS did not converge; EKF cannot be initialized.")
                previous_ekf, previous_P = result.x.copy(), covariance.copy()
                innovation = None
            else:
                dt = float(hours[k] - hours[k - 1])
                process_variances = (
                    np.r_[
                        np.full(model.vm_state_offset, angle_process_std**2),
                        np.full(model.num_buses, voltage_process_std**2),
                    ]
                    * dt
                )
                filtered = run_extended_kalman_filter(
                    np.vstack([frames[-1].observed, observed]),
                    h=model.h,
                    jacobian=model.jacobian_finite_difference,
                    R=np.diag(sigma**2),
                    x0=previous_ekf,
                    P0=previous_P,
                    Q=np.diag(process_variances),
                    adaptation=InnovationAdaptation(),
                )
                previous_ekf = filtered.states[-1]
                previous_P = filtered.covariances[-1]
                innovation = float(filtered.max_normalized_innovation[-1])
                events.extend({**event, "k": k} for event in filtered.events)
            if (
                not np.all(np.isfinite(previous_ekf))
                or not np.all(np.isfinite(previous_P))
                or np.any(previous_ekf[model.vm_state_offset :] <= 0)
            ):
                raise ValueError(
                    f"Invalid EKF state at hour {hour:g}: non-finite values or non-positive voltage magnitude."
                )
            if np.any(attacked):
                events.append(
                    {
                        "type": "scheduled_measurement_bias",
                        "channel": attack.channel,
                        "action": "injected",
                        "bias_sigma": attack.bias_sigma,
                    }
                )
            if load_active:
                events.append(
                    {
                        "type": "scheduled_load_change",
                        "bus": int(load_event_bus),
                        "action": "physical_change",
                        "factor": load_event_factor,
                    }
                )
            frames.append(
                TemporalFrame(
                    float(hour),
                    float(load_factors[k]),
                    float(dg_factors[k]),
                    net.res_bus.reset_index().to_dict("records"),
                    net.res_line.reset_index().to_dict("records"),
                    clean,
                    truth,
                    observed,
                    attacked,
                    result.x.copy(),
                    covariance,
                    bool(result.converged),
                    len(result.iterations),
                    float(result.objective),
                    previous_ekf.copy(),
                    previous_P.copy(),
                    innovation,
                    events,
                )
            )
            if result.converged:
                previous_wls = result.x.copy()
            if trail:
                with trail.section(f"temporal frame k={k}, hour={hour:g}"):
                    trail.step("observed measurements", observed)
                    trail.step("WLS state", result.x)
                    trail.step("EKF state", previous_ekf)
                    trail.step("EKF posterior covariance", previous_P)
    finally:
        net.load.loc[:, ["p_mw", "q_mvar"]] = original_load
        net.sgen.loc[:, ["p_mw", "q_mvar"]] = original_dg
    return model, frames
