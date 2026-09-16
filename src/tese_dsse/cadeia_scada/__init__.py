"""Cadeia operacional: medidor -> RTU -> comunicacao -> SCADA -> topologia.

O miolo que faltava entre o `measurement_layer` e o estimador. Ate esta
adicao, o app ia direto do ground truth ao vetor `z`, o que torna impossivel
representar tres coisas que sao centrais na tese:

1. que o dado chega **agrupado por RTU**, entao comprometer uma unidade afeta
   um bloco correlacionado de medicoes;
2. que o dado chega **com idades diferentes**, entao o "snapshot" do SCADA e
   uma agregacao de instantes distintos;
3. que a topologia e **reconstruida a partir de status telemetrado**, entao
   ela pode estar errada sem que nenhuma medicao analogica esteja.

Ordem de execucao e responsabilidade de quem chama (hoje
`app/backend/routes/pipeline.py`); os modulos aqui nao se conhecem, e cada um
recebe o que a camada anterior produziu:

    build_points  ->  transmit  ->  RTDB.ingest_all  ->  RTDB.snapshot
                                                     ->  process_topology

Plano completo, fases e decisoes em
`docs/planejamento/cadeia_operacional_scada.md`.
"""

from __future__ import annotations

from .canal import ChannelConfig, PacketDelivery, delivery_statistics, transmit
from .processador_topologia import (
    STATUS_LABEL,
    SwitchTelemetry,
    TopologySnapshot,
    UnreliablePolicy,
    process_topology,
)
from .rtdb import RTDB, PointRecord, RTDBSnapshot, degrade
from .rtu import (
    RTU,
    SCAN_PERIOD_BY_KIND,
    RTUPoint,
    build_points,
    group_buses_into_rtus,
    point_id_for,
    scan_period_for,
)
from .traco import LAYERS, LayerEvent, PipelineTrace

__all__ = [
    "ChannelConfig",
    "LAYERS",
    "LayerEvent",
    "PacketDelivery",
    "PipelineTrace",
    "PointRecord",
    "RTDB",
    "RTDBSnapshot",
    "RTU",
    "RTUPoint",
    "SCAN_PERIOD_BY_KIND",
    "STATUS_LABEL",
    "SwitchTelemetry",
    "TopologySnapshot",
    "UnreliablePolicy",
    "build_points",
    "degrade",
    "delivery_statistics",
    "group_buses_into_rtus",
    "point_id_for",
    "process_topology",
    "scan_period_for",
    "transmit",
]
