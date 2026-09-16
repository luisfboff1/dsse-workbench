"""Estrutura de dados para medicoes sinteticas multitaxa.

Cada `Measurement` carrega `true_value`, `measured_value`, `sigma`,
`timestamp`, `sensor_class` e `tampered`. A versao tabular vive em
DataFrames com schema canonico definido em `MEASUREMENT_COLUMNS`.

A separacao entre "spec do sensor" (`SensorSpec`, fixa no tempo) e
"medicao instantanea" (`Measurement`, com timestamp e valor) facilita o
loop temporal e a deduplicacao por sensor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

SensorClass = Literal["PMU", "SCADA", "AMI", "SMART_METER"]
LocationKind = Literal["bus", "line", "trafo"]
LineSide = Literal["from", "to"]
Variable = Literal[
    "v_mag",
    "v_angle",
    "p_inj",
    "q_inj",
    "p_branch",
    "q_branch",
    "i_mag",
]


@dataclass(frozen=True)
class SensorSpec:
    """Sensor fisico instalado em um local da rede.

    Determina o que sera medido em cada timestamp dentro da janela em que
    o sensor "publica". A classe dita a frequencia de publicacao
    (definida em `measurement_layer.SENSOR_DEFAULTS`).
    """

    sensor_class: SensorClass
    sensor_id: str
    location_kind: LocationKind
    location_id: int
    variable: Variable
    side: LineSide | None = None  # obrigatorio se location_kind != "bus"


@dataclass(frozen=True)
class Measurement:
    """Medicao instantanea — uma linha do dataset final."""

    timestamp: pd.Timestamp
    sensor_class: SensorClass
    sensor_id: str
    location_kind: LocationKind
    location_id: int
    side: LineSide | None
    variable: Variable
    true_value: float
    measured_value: float
    sigma: float
    tampered: bool = False


@dataclass
class SensorPlacement:
    """Coleção declarativa de sensores na rede.

    Use heuristicas em `sensor_placement.py` ou monte na mao para casos
    didaticos.
    """

    sensors: list[SensorSpec] = field(default_factory=list)

    def add(self, *sensors: SensorSpec) -> "SensorPlacement":
        self.sensors.extend(sensors)
        return self

    def by_class(self, sensor_class: SensorClass) -> list[SensorSpec]:
        return [s for s in self.sensors if s.sensor_class == sensor_class]

    def __iter__(self):
        return iter(self.sensors)

    def __len__(self) -> int:
        return len(self.sensors)


MEASUREMENT_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "sensor_class",
    "sensor_id",
    "location_kind",
    "location_id",
    "side",
    "variable",
    "true_value",
    "measured_value",
    "sigma",
    "tampered",
)


def measurements_to_dataframe(measurements: list[Measurement]) -> pd.DataFrame:
    """Converte lista de `Measurement` para DataFrame com schema canonico."""
    if not measurements:
        return pd.DataFrame(columns=list(MEASUREMENT_COLUMNS))
    rows = [
        {
            "timestamp": m.timestamp,
            "sensor_class": m.sensor_class,
            "sensor_id": m.sensor_id,
            "location_kind": m.location_kind,
            "location_id": m.location_id,
            "side": m.side,
            "variable": m.variable,
            "true_value": m.true_value,
            "measured_value": m.measured_value,
            "sigma": m.sigma,
            "tampered": m.tampered,
        }
        for m in measurements
    ]
    return pd.DataFrame(rows, columns=list(MEASUREMENT_COLUMNS))
