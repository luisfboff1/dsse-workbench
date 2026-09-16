"""Estimadores dinamicos para sistemas variantes no tempo (DSSE dinamica).

Escopo deste subpacote:

- Filtro de Kalman (KF) para modelos lineares.
- Filtro de Kalman estendido (EKF) e unscented (UKF) para h(x) nao linear.
- Forecasting-Aided State Estimation (FASE) com modelos de transicao de carga.
- Estimacao recursiva multi-snapshot (janelas temporais).

Diferenca para ``estimacao_estado``:

- ``estimacao_estado`` resolve snapshots estaticos (um instante por chamada).
- Aqui o estado evolui no tempo: ha um modelo de processo x_{k+1} = f(x_k) + w.

Convencoes:

- Reutilizar ``tese_dsse.auditoria.AuditTrail`` para o ``verbose`` padronizado.
- Funcoes pesadas vivem aqui (.py); notebooks apenas as chamam.
"""

from __future__ import annotations

from .kalman import (
    DynamicEstimationResult,
    InnovationAdaptation,
    ProcessNoiseCalibration,
    calibrate_process_noise,
    run_extended_kalman_filter,
    run_linear_kalman_filter,
    sample_skewness,
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
