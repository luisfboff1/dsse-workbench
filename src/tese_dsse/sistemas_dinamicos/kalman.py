"""Filtros de Kalman reutilizaveis para estimacao dinamica de estado.

O modulo implementa o nucleo temporal usado nos estudos do Capitulo 8 de
Bretas et al. (2021): passeio aleatorio, inovacao normalizada, discriminacao
de erro grosseiro por assimetria e reinicio estatico para mudancas abruptas
de carga.

Os dados usados para calibrar ``Q`` devem ser anteriores e separados do
periodo avaliado. A funcao :func:`calibrate_process_noise` recebe apenas esse
historico; ela nao acessa a trajetoria de teste nem conhece o estimador.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

import numpy as np

from ..auditoria import AuditTrail, resolve_audit

Array = np.ndarray
MeasurementFunction = Callable[[Array], Array]
JacobianFunction = Callable[[Array], Array]
StaticRestart = Callable[[Array, Array], tuple[Array, Array]]


@dataclass(frozen=True)
class ProcessNoiseCalibration:
    """Resultado da calibracao diagonal do ruido de processo."""

    Q: Array
    rates: Array
    num_history_samples: int
    statistic: str
    alpha: float
    floor: float


@dataclass(frozen=True)
class InnovationAdaptation:
    """Parametros do processamento adaptativo de anomalias."""

    anomaly_threshold: float = 3.0
    skewness_threshold: float = 2.0
    max_measurement_removals: int = 10
    use_absolute_skewness: bool = True


@dataclass
class DynamicEstimationResult:
    """Trajetoria estimada e diagnosticos do filtro."""

    states: Array
    covariances: Array
    max_normalized_innovation: Array
    innovation_argmax: Array
    innovation_skewness: Array
    anomaly_flags: Array
    final_measurement_masks: Array
    events: list[dict[str, object]] = field(default_factory=list)


def calibrate_process_noise(
    state_history: Array,
    *,
    alpha: float = 1.0,
    floor: float | Array = 1e-5,
    statistic: Literal["max", "quantile", "std"] = "quantile",
    quantile: float = 0.99,
    verbose: bool = False,
    audit: AuditTrail | None = None,
) -> ProcessNoiseCalibration:
    """Calibra ``Q = alpha**2 * diag(q_i**2)`` a partir de historico separado.

    Parameters
    ----------
    state_history:
        Matriz ``(tempo, estados)`` de um periodo historico anterior ao teste.
        Em dados reais, pode conter estados previamente estimados; em simulacao,
        pode vir de uma execucao de calibracao independente.
    statistic:
        ``"max"`` reproduz a taxa maxima descrita no Cap. 8; ``"quantile"``
        (padrao) e mais robusto a um unico salto historico; ``"std"`` usa o
        desvio padrao das diferencas.
    """

    trail = resolve_audit(audit, verbose, title="calibrate_process_noise")
    history = np.asarray(state_history, dtype=float)
    if history.ndim != 2 or history.shape[0] < 2:
        raise ValueError("state_history deve ter formato (tempo, estados) e >= 2 amostras.")
    if not np.all(np.isfinite(history)):
        raise ValueError("state_history contem valores nao finitos.")
    if alpha <= 0:
        raise ValueError("alpha deve ser positivo.")
    if statistic == "quantile" and not 0.0 < quantile <= 1.0:
        raise ValueError("quantile deve estar no intervalo (0, 1].")

    deltas = np.diff(history, axis=0)
    if statistic == "max":
        rates = np.max(np.abs(deltas), axis=0)
    elif statistic == "quantile":
        rates = np.quantile(np.abs(deltas), quantile, axis=0)
    elif statistic == "std":
        rates = np.std(deltas, axis=0, ddof=1 if deltas.shape[0] > 1 else 0)
    else:
        raise ValueError(f"statistic desconhecida: {statistic!r}.")

    floor_array = np.broadcast_to(np.asarray(floor, dtype=float), rates.shape)
    if np.any(floor_array <= 0):
        raise ValueError("floor deve ser estritamente positivo.")
    rates = np.maximum(rates, floor_array)
    Q = alpha**2 * np.diag(rates**2)

    trail.step("diferencas historicas", deltas, formula="Delta x_k = x_k - x_{k-1}")
    trail.step("taxas q_i", rates)
    trail.step("covariancia Q", Q, formula="Q = alpha^2 diag(q_i^2)")
    return ProcessNoiseCalibration(
        Q=Q,
        rates=rates,
        num_history_samples=history.shape[0],
        statistic=statistic,
        alpha=float(alpha),
        floor=float(np.min(floor_array)),
    )


def sample_skewness(values: Array) -> float:
    """Terceiro momento central normalizado de uma amostra."""

    sample = np.asarray(values, dtype=float).reshape(-1)
    if sample.size == 0:
        raise ValueError("A amostra de assimetria nao pode ser vazia.")
    mean = float(np.mean(sample))
    std = float(np.std(sample))
    if std < 1e-12:
        return 0.0
    return float(np.mean((sample - mean) ** 3) / std**3)


def _validate_filter_inputs(
    measurements: Array,
    R: Array,
    x0: Array,
    P0: Array,
    Q: Array,
    F: Array | None,
) -> tuple[Array, Array, Array, Array, Array, Array]:
    z = np.asarray(measurements, dtype=float)
    x = np.asarray(x0, dtype=float).reshape(-1)
    P = np.asarray(P0, dtype=float)
    process_noise = np.asarray(Q, dtype=float)
    measurement_noise = np.asarray(R, dtype=float)
    transition = np.eye(x.size) if F is None else np.asarray(F, dtype=float)

    if z.ndim != 2:
        raise ValueError("measurements deve ter formato (tempo, medicoes).")
    n = x.size
    m = z.shape[1]
    for name, matrix, shape in (
        ("P0", P, (n, n)),
        ("Q", process_noise, (n, n)),
        ("F", transition, (n, n)),
        ("R", measurement_noise, (m, m)),
    ):
        if matrix.shape != shape:
            raise ValueError(f"{name} deve ter forma {shape}, recebeu {matrix.shape}.")
    if not all(np.all(np.isfinite(a)) for a in (z, x, P, process_noise, measurement_noise, transition)):
        raise ValueError("Entradas do filtro contem valores nao finitos.")
    if np.any(np.diag(measurement_noise) <= 0):
        raise ValueError("R deve ter diagonal estritamente positiva.")
    return z, measurement_noise, x, P, process_noise, transition


def _kalman_gain(P_pred: Array, H: Array, S: Array) -> Array:
    """Calcula o ganho sem formar ``inv(S)`` explicitamente."""

    return np.linalg.solve(S, H @ P_pred).T


def run_extended_kalman_filter(
    measurements: Array,
    *,
    h: MeasurementFunction,
    jacobian: JacobianFunction,
    R: Array,
    x0: Array,
    P0: Array,
    Q: Array,
    F: Array | None = None,
    adaptation: InnovationAdaptation | None = None,
    static_restart: StaticRestart | None = None,
    verbose: bool = False,
    audit: AuditTrail | None = None,
) -> DynamicEstimationResult:
    """Executa EKF com processamento adaptativo opcional.

    ``static_restart(z_k, x_pred)`` deve devolver ``(x_restart, P_restart)``.
    Ele e chamado quando existe anomalia, mas a assimetria nao caracteriza GE.
    """

    trail = resolve_audit(audit, verbose, title="run_extended_kalman_filter")
    z, R, x, P, Q, F = _validate_filter_inputs(measurements, R, x0, P0, Q, F)
    steps, m = z.shape
    n = x.size
    if steps < 1:
        raise ValueError("measurements precisa conter pelo menos um passo.")

    states = np.zeros((steps, n), dtype=float)
    covariances = np.zeros((steps, n, n), dtype=float)
    max_innovation = np.zeros(steps, dtype=float)
    innovation_argmax = np.full(steps, -1, dtype=int)
    skewness_values = np.zeros(steps, dtype=float)
    anomaly_flags = np.zeros(steps, dtype=bool)
    masks = np.ones((steps, m), dtype=bool)
    events: list[dict[str, object]] = []
    states[0] = x
    covariances[0] = P
    identity = np.eye(n)

    for k in range(1, steps):
        x_pred = F @ x
        P_pred = F @ P @ F.T + Q
        active = np.ones(m, dtype=bool)
        removals = 0

        while True:
            predicted_measurements = np.asarray(h(x_pred), dtype=float).reshape(-1)
            H_full = np.asarray(jacobian(x_pred), dtype=float)
            if predicted_measurements.shape != (m,) or H_full.shape != (m, n):
                raise ValueError("h(x) ou jacobian(x) retornou dimensao incompatível.")

            H_active = H_full[active]
            R_active = R[np.ix_(active, active)]
            innovation = z[k, active] - predicted_measurements[active]
            S = H_active @ P_pred @ H_active.T + R_active
            rho = np.sqrt(np.maximum(np.diag(S), np.finfo(float).eps))
            normalized = innovation / rho
            local_worst = int(np.argmax(np.abs(normalized)))
            global_worst = int(np.flatnonzero(active)[local_worst])
            max_abs = float(np.abs(normalized[local_worst]))
            gamma = sample_skewness(normalized)
            is_anomaly = bool(
                adaptation is not None
                and max_abs > adaptation.anomaly_threshold
            )

            if not is_anomaly:
                break

            gamma_test = abs(gamma) if adaptation.use_absolute_skewness else gamma
            is_gross_error = gamma_test > adaptation.skewness_threshold
            if is_gross_error and removals < adaptation.max_measurement_removals:
                if active.sum() - 1 <= n:
                    events.append(
                        {
                            "k": k,
                            "type": "gross_error_unremoved",
                            "channel": global_worst,
                            "max_abs_lambda": max_abs,
                            "gamma": gamma,
                            "action": "preserved_observability",
                        }
                    )
                    break
                events.append(
                    {
                        "k": k,
                        "type": "gross_error",
                        "channel": global_worst,
                        "max_abs_lambda": max_abs,
                        "gamma": gamma,
                        "action": "remove_measurement",
                    }
                )
                active[global_worst] = False
                removals += 1
                continue

            if static_restart is not None:
                x_pred, P_pred = static_restart(z[k].copy(), x_pred.copy())
                x_pred = np.asarray(x_pred, dtype=float).reshape(n)
                P_pred = np.asarray(P_pred, dtype=float).reshape(n, n)
                events.append(
                    {
                        "k": k,
                        "type": "state_change",
                        "channel": global_worst,
                        "max_abs_lambda": max_abs,
                        "gamma": gamma,
                        "action": "static_restart",
                    }
                )
                # Recalcula inovacao/Jacobiana no ponto reiniciado e publica.
                predicted_measurements = np.asarray(h(x_pred), dtype=float).reshape(-1)
                H_full = np.asarray(jacobian(x_pred), dtype=float)
                H_active = H_full[active]
                R_active = R[np.ix_(active, active)]
                innovation = z[k, active] - predicted_measurements[active]
                S = H_active @ P_pred @ H_active.T + R_active
                rho = np.sqrt(np.maximum(np.diag(S), np.finfo(float).eps))
                normalized = innovation / rho
                local_worst = int(np.argmax(np.abs(normalized)))
                global_worst = int(np.flatnonzero(active)[local_worst])
                max_abs = float(np.abs(normalized[local_worst]))
                gamma = sample_skewness(normalized)
            else:
                events.append(
                    {
                        "k": k,
                        "type": "state_change",
                        "channel": global_worst,
                        "max_abs_lambda": max_abs,
                        "gamma": gamma,
                        "action": "reported_only",
                    }
                )
            break

        gain = _kalman_gain(P_pred, H_active, S)
        x = x_pred + gain @ innovation
        correction = identity - gain @ H_active
        # Forma de Joseph: preserva simetria e semidefinicao positiva melhor.
        P = correction @ P_pred @ correction.T + gain @ R_active @ gain.T
        P = 0.5 * (P + P.T)

        states[k] = x
        covariances[k] = P
        max_innovation[k] = max_abs
        innovation_argmax[k] = global_worst
        skewness_values[k] = gamma
        anomaly_flags[k] = bool(
            adaptation is not None
            and max_abs > adaptation.anomaly_threshold
        )
        masks[k] = active

        if trail:
            with trail.section(f"passo k={k}"):
                trail.step("estado predito", x_pred)
                trail.step("max |lambda|", max_abs)
                trail.step("assimetria gamma", gamma)
                trail.step("estado atualizado", x)

    return DynamicEstimationResult(
        states=states,
        covariances=covariances,
        max_normalized_innovation=max_innovation,
        innovation_argmax=innovation_argmax,
        innovation_skewness=skewness_values,
        anomaly_flags=anomaly_flags,
        final_measurement_masks=masks,
        events=events,
    )


def run_linear_kalman_filter(
    measurements: Array,
    *,
    H: Array,
    R: Array,
    x0: Array,
    P0: Array,
    Q: Array,
    F: Array | None = None,
    offset: Array | None = None,
    adaptation: InnovationAdaptation | None = None,
    static_restart: StaticRestart | None = None,
    verbose: bool = False,
    audit: AuditTrail | None = None,
) -> DynamicEstimationResult:
    """Atalho para o KF linear ``z = Hx + offset + v``."""

    matrix = np.asarray(H, dtype=float)
    constant = np.zeros(matrix.shape[0]) if offset is None else np.asarray(offset, dtype=float)
    if constant.shape != (matrix.shape[0],):
        raise ValueError("offset deve ter uma entrada por medicao.")
    return run_extended_kalman_filter(
        measurements,
        h=lambda state: matrix @ state + constant,
        jacobian=lambda _state: matrix,
        R=R,
        x0=x0,
        P0=P0,
        Q=Q,
        F=F,
        adaptation=adaptation,
        static_restart=static_restart,
        verbose=verbose,
        audit=audit,
    )


__all__ = [
    "DynamicEstimationResult",
    "InnovationAdaptation",
    "ProcessNoiseCalibration",
    "calibrate_process_noise",
    "run_extended_kalman_filter",
    "run_linear_kalman_filter",
    "sample_skewness",
]
