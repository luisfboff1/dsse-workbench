"""Analise de observabilidade e geracao/placement de medicoes (DSSE).

Escopo planejado deste subpacote (ainda em construcao):

- Matriz de observabilidade a partir de H (Jacobiana das medicoes).
- Identificacao de ilhas observaveis e barras nao observaveis.
- Geracao de pseudo-medicoes para restaurar observabilidade.
- Placement otimo de medidores (PMU/SCADA) sob restricao de custo.
- Indices de redundancia e criticidade de medidas.

Convencoes:

- Reutilizar ``tese_dsse.auditoria.AuditTrail`` para o ``verbose`` padronizado.
- Funcoes pesadas vivem aqui (.py); notebooks apenas as chamam.
- Estado e medicoes seguem as convencoes de ``estimacao_estado``.
"""

from __future__ import annotations

__all__: list[str] = []
