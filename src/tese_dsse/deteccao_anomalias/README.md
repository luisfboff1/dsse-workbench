# deteccao_anomalias

Deteccao de dados ruins (bad data) e anomalias na DSSE.

## Responsabilidade

Identificar medicoes inconsistentes ou anomalas e separar erro grosseiro de
ruido normal, antes ou depois da estimacao de estado.

## Escopo planejado

- Teste qui-quadrado da funcao objetivo `J` para deteccao **global**.
- Teste do **residuo normalizado maximo** (Largest Normalized Residual, LNR).
- Identificacao e remocao iterativa de medidas ruins.
- Deteccao de anomalias baseada em dados (estatistica/ML) para padroes que
  fogem do comportamento normal da rede.

## Conexoes

- Consome o `residual`, `W` e `J` produzidos pelos solvers de
  [`estimacao_estado`](../estimacao_estado).
- Complementa [`seguranca`](../seguranca): aqui o foco e erro/ruido nao
  intencional; la, ataques deliberados (FDIA furtivos passam pelo LNR).

## Convencoes

- Funcoes pesadas em `.py`; notebooks apenas chamam.
- Use `tese_dsse.auditoria.AuditTrail` para o `verbose` padronizado.
- Docstrings em portugues, identificadores em ingles.
