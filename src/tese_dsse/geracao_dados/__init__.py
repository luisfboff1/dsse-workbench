"""Geracao de dados sinteticos para DSSE multitaxa.

Modulo que implementa o plano C descrito em
`docs/estudos/estimacao_estado/plano_geracao_dados_sinteticos.md`.
Pipeline em duas etapas operacionais:

- C1 (`batch_powerflow`): roda fluxo de potencia em uma rede pandapower
  iterando sobre uma janela temporal e variando cargas conforme um
  conjunto de `LoadShape`s. Produz o "ground truth" denso.
- C2 (`measurement_layer`): a partir do ground truth, instancia medicoes
  por classe de sensor (PMU, SCADA, AMI, smart meter), aplica ruido
  gaussiano com `sigma` por classe e faz subamostragem temporal.

A camada `Measurement` fica desacoplada do estimador: cada medicao guarda
`true_value`, `measured_value` e `sigma`, alem de timestamp e classe. O
estimador WLS sobre `ACYbusMeasurementModel` consome `measured_value`
e `sigma`; metricas de avaliacao podem usar `true_value`.
"""

from .load_shapes import (
    LoadShape,
    SinusoidalDailyShape,
    SimbenchShapeProvider,
    build_default_shape_per_load,
)
from .batch_powerflow import (
    BatchPowerFlowResult,
    GroundTruthSchema,
    run_batch_powerflow,
)
from .measurement import (
    Measurement,
    SensorClass,
    SensorPlacement,
    SensorSpec,
    measurements_to_dataframe,
)
from .sensor_placement import (
    auto_place_sensors_transmission,
    auto_place_sensors_distribution,
)
from .measurement_layer import (
    SENSOR_DEFAULTS,
    apply_measurement_layer,
    subsample_by_sensor_class,
)

__all__ = [
    "LoadShape",
    "SinusoidalDailyShape",
    "SimbenchShapeProvider",
    "build_default_shape_per_load",
    "BatchPowerFlowResult",
    "GroundTruthSchema",
    "run_batch_powerflow",
    "Measurement",
    "SensorClass",
    "SensorPlacement",
    "SensorSpec",
    "measurements_to_dataframe",
    "auto_place_sensors_transmission",
    "auto_place_sensors_distribution",
    "SENSOR_DEFAULTS",
    "apply_measurement_layer",
    "subsample_by_sensor_class",
]
