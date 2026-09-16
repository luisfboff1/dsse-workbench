"""C2 — Aplica camada de medicoes sobre o ground truth.

Para cada `SensorSpec` em um `SensorPlacement`, percorre os timestamps
publicaveis daquele sensor (definido pela classe), extrai o valor verdadeiro
do ground truth, soma ruido gaussiano com `sigma` da tabela
`SENSOR_DEFAULTS` e produz `Measurement`s.

Nota sobre subamostragem:
- Cada classe de sensor tem `period_seconds` (frequencia natural). O ground
  truth e gerado em `step_seconds`. Sensores cujo `period_seconds >
  step_seconds` so publicam em multiplos do periodo.
- Smart meters publicam em horarios fixos (default 00, 06, 12, 18). AMI em
  multiplos do periodo. SCADA e PMU em todos os timestamps (asincronia
  interna ignorada nesta versao).

Convencao de sinal de injecao: usamos `S = V * conj(Ybus * V)` (positivo
= gerador). E o que `batch_powerflow.py` ja salva em `p_inj_mw`/`q_inj_mvar`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .measurement import (
    SensorClass,
    SensorPlacement,
    SensorSpec,
)


@dataclass(frozen=True)
class SensorDefaults:
    """Especificacao por classe de sensor.

    - `period_seconds`: frequencia natural de publicacao;
    - `sigma_*`: desvio-padrao do ruido (em pu para tensao, em MW/MVAr para
      potencias, em rad para angulos, em kA para correntes);
    - `publish_offsets_seconds`: timestamps fixos do dia em que o sensor
      publica (None = publica em todo multiplo do periodo).
    """

    period_seconds: float
    sigma_v_mag_pu: float
    sigma_v_angle_rad: float
    sigma_power_mva: float
    sigma_i_mag_ka: float
    publish_offsets_seconds: tuple[int, ...] | None = None


SENSOR_DEFAULTS: dict[SensorClass, SensorDefaults] = {
    "PMU": SensorDefaults(
        period_seconds=1.0 / 30.0,  # 30 Hz; em pratica usaremos step do batch
        sigma_v_mag_pu=0.001,
        sigma_v_angle_rad=np.deg2rad(0.01),
        sigma_power_mva=0.005,
        sigma_i_mag_ka=0.0005,
    ),
    "SCADA": SensorDefaults(
        period_seconds=4.0,
        sigma_v_mag_pu=0.005,  # ~0.5%
        sigma_v_angle_rad=np.deg2rad(0.5),  # SCADA nao mede angulo, mas se for
        sigma_power_mva=0.02,
        sigma_i_mag_ka=0.005,
    ),
    "AMI": SensorDefaults(
        period_seconds=15.0 * 60.0,  # 15 min
        sigma_v_mag_pu=0.01,
        sigma_v_angle_rad=np.deg2rad(1.0),
        sigma_power_mva=0.05,
        sigma_i_mag_ka=0.01,
    ),
    "SMART_METER": SensorDefaults(
        period_seconds=6.0 * 3600.0,  # 4x/dia
        sigma_v_mag_pu=0.01,
        sigma_v_angle_rad=np.deg2rad(2.0),
        sigma_power_mva=0.10,
        sigma_i_mag_ka=0.02,
        publish_offsets_seconds=(0, 6 * 3600, 12 * 3600, 18 * 3600),
    ),
}


def _resolve_sigma(spec: SensorSpec) -> float:
    defaults = SENSOR_DEFAULTS[spec.sensor_class]
    if spec.variable == "v_mag":
        return defaults.sigma_v_mag_pu
    if spec.variable == "v_angle":
        return defaults.sigma_v_angle_rad
    if spec.variable in ("p_inj", "q_inj", "p_branch", "q_branch"):
        return defaults.sigma_power_mva
    if spec.variable == "i_mag":
        return defaults.sigma_i_mag_ka
    raise ValueError(f"variable nao suportada: {spec.variable}")


def _publish_mask(
    timestamps: pd.DatetimeIndex,
    spec: SensorSpec,
    *,
    step_seconds: float,
) -> np.ndarray:
    """Boolean mask de quais timestamps este sensor publica."""
    defaults = SENSOR_DEFAULTS[spec.sensor_class]

    if defaults.publish_offsets_seconds is not None:
        seconds_of_day = np.asarray(
            timestamps.hour * 3600 + timestamps.minute * 60 + timestamps.second,
            dtype=int,
        )
        offsets = np.asarray(defaults.publish_offsets_seconds, dtype=int)
        return np.isin(seconds_of_day, offsets)

    if defaults.period_seconds <= step_seconds:
        return np.ones(len(timestamps), dtype=bool)

    period_steps = int(round(defaults.period_seconds / step_seconds))
    if period_steps <= 1:
        return np.ones(len(timestamps), dtype=bool)
    base = timestamps[0]
    diffs = np.asarray((timestamps - base).total_seconds(), dtype=float)
    return np.isclose(diffs % defaults.period_seconds, 0.0, atol=step_seconds / 2.0)


def _value_lookup(
    bus_truth: pd.DataFrame,
    branch_truth: pd.DataFrame,
    spec: SensorSpec,
) -> pd.Series:
    """Retorna serie indexada por timestamp com o valor verdadeiro do sensor."""
    if spec.location_kind == "bus":
        sub = bus_truth[bus_truth["bus"] == spec.location_id]
        if spec.variable == "v_mag":
            return sub.set_index("timestamp")["vm_pu"]
        if spec.variable == "v_angle":
            return sub.set_index("timestamp")["va_degree"].apply(np.deg2rad)
        if spec.variable == "p_inj":
            return sub.set_index("timestamp")["p_inj_mw"]
        if spec.variable == "q_inj":
            return sub.set_index("timestamp")["q_inj_mvar"]
        raise ValueError(
            f"Variavel {spec.variable} nao se aplica a barra; use line/trafo."
        )

    if spec.location_kind in ("line", "trafo"):
        if spec.side is None:
            raise ValueError("Sensor de linha/trafo precisa de `side`.")
        kind = spec.location_kind
        sub = branch_truth[
            (branch_truth["branch_kind"] == kind)
            & (branch_truth["branch_id"] == spec.location_id)
        ]
        if spec.variable == "p_branch":
            col = "p_from_mw" if spec.side == "from" else "p_to_mw"
            return sub.set_index("timestamp")[col]
        if spec.variable == "q_branch":
            col = "q_from_mvar" if spec.side == "from" else "q_to_mvar"
            return sub.set_index("timestamp")[col]
        if spec.variable == "i_mag":
            col = "i_from_ka" if spec.side == "from" else "i_to_ka"
            return sub.set_index("timestamp")[col]

    raise ValueError(f"Combinacao nao suportada: {spec}")


def apply_measurement_layer(
    bus_truth: pd.DataFrame,
    branch_truth: pd.DataFrame,
    placement: SensorPlacement,
    *,
    step_seconds: float,
    seed: int = 0,
) -> pd.DataFrame:
    """Gera o DataFrame `long` de medicoes para todos os sensores."""

    rng = np.random.default_rng(seed)
    timestamps = pd.DatetimeIndex(sorted(bus_truth["timestamp"].unique()))

    rows: list[dict] = []
    for spec in placement:
        truth_series = _value_lookup(bus_truth, branch_truth, spec)
        truth_series = truth_series.reindex(timestamps)
        if truth_series.isna().any():
            raise ValueError(
                f"Ground truth nao tem dados para sensor {spec.sensor_id}"
            )
        sigma = _resolve_sigma(spec)
        mask = _publish_mask(timestamps, spec, step_seconds=step_seconds)
        if not mask.any():
            continue
        active_ts = timestamps[mask]
        true_values = truth_series.loc[active_ts].to_numpy()
        noise = rng.normal(0.0, sigma, size=true_values.size)
        measured = true_values + noise

        for ts, true_val, meas_val in zip(active_ts, true_values, measured):
            rows.append(
                {
                    "timestamp": ts,
                    "sensor_class": spec.sensor_class,
                    "sensor_id": spec.sensor_id,
                    "location_kind": spec.location_kind,
                    "location_id": spec.location_id,
                    "side": spec.side,
                    "variable": spec.variable,
                    "true_value": float(true_val),
                    "measured_value": float(meas_val),
                    "sigma": float(sigma),
                    "tampered": False,
                }
            )

    if not rows:
        from .measurement import MEASUREMENT_COLUMNS
        return pd.DataFrame(columns=list(MEASUREMENT_COLUMNS))
    return pd.DataFrame(rows)


def subsample_by_sensor_class(
    measurements_df: pd.DataFrame,
) -> dict[SensorClass, pd.DataFrame]:
    """Particiona o DataFrame por `sensor_class`."""
    return {
        cls: df.reset_index(drop=True)
        for cls, df in measurements_df.groupby("sensor_class", observed=True)
    }
