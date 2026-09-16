"""Deteccao de dados ruins e anomalias na DSSE.

Escopo planejado deste subpacote (ainda em construcao):

- Teste do residuo normalizado maximo (Largest Normalized Residual, LNR).
- Teste qui-quadrado da funcao objetivo J para deteccao global.
- Identificacao e remocao iterativa de medidas ruins.
- Deteccao de anomalias baseada em dados (estatistica/ML) para padroes
  que fogem do comportamento normal da rede.

Convencoes:

- Reutilizar ``tese_dsse.auditoria.AuditTrail`` para o ``verbose`` padronizado.
- Funcoes pesadas vivem aqui (.py); notebooks apenas as chamam.
"""

from __future__ import annotations

__all__: list[str] = []
