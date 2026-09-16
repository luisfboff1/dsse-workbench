"""Cyber security para a DSSE: ataques (FDIA) e defesa.

Escopo planejado deste subpacote (ainda em construcao):

- Geracao de False Data Injection Attacks (FDIA) furtivos (stealthy),
  construidos no espaco-coluna de H para nao alterar o residuo.
- Ataques nao furtivos / ruido malicioso para testes de robustez.
- Mecanismos de defesa: deteccao por residuo, consistencia entre PMU/SCADA,
  protecao de um conjunto minimo de medidas.
- Metricas de impacto do ataque sobre o estado estimado.

Convencoes:

- Reutilizar ``tese_dsse.auditoria.AuditTrail`` para o ``verbose`` padronizado.
- Funcoes pesadas vivem aqui (.py); notebooks apenas as chamam.
- Uso estritamente academico/defensivo (avaliacao de robustez de estimadores).

Ja implementado: o catalogo de ataques por camada da cadeia operacional
(`ataques.py`), usado por `app/backend/routes/pipeline.py`. Cobre injecao em
medicao, RTU, comunicacao e topologia -- o FDIA furtivo (construido no
espaco-coluna de H) segue pendente.
"""

from __future__ import annotations

from .ataques import (
    ATTACK_CATALOG,
    AttackLayer,
    AttackSpec,
    apply_channel_attacks,
    apply_sensor_attacks,
    apply_topology_attacks,
    catalog_as_list,
)

__all__: list[str] = [
    "ATTACK_CATALOG",
    "AttackLayer",
    "AttackSpec",
    "apply_channel_attacks",
    "apply_sensor_attacks",
    "apply_topology_attacks",
    "catalog_as_list",
]
