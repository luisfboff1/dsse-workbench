# observabilidade

Analise de observabilidade e geracao/placement de medicoes para a DSSE.

## Responsabilidade

Garantir que o conjunto de medicoes torna o estado **observavel** e oferecer
ferramentas para diagnosticar e corrigir a falta de observabilidade.

## Escopo planejado

- Matriz de observabilidade a partir da Jacobiana `H` das medicoes.
- Identificacao de ilhas observaveis e barras nao observaveis.
- Geracao de **pseudo-medicoes** (ex.: previsao de carga) para restaurar
  observabilidade.
- **Placement otimo** de medidores (PMU/SCADA) sob restricao de custo.
- Indices de redundancia local/global e medidas criticas.

## Conexoes

- Consome `H` produzido em [`estimacao_estado`](../estimacao_estado) (modelos
  AC/DC) e a tabela de medicoes.
- Alimenta o pipeline de [`geracao_dados`](../geracao_dados) quando precisa
  sintetizar medicoes adicionais.

## Convencoes

- Funcoes pesadas ficam em `.py` aqui; notebooks apenas chamam.
- Use `tese_dsse.auditoria.AuditTrail` para o parametro `verbose` padronizado
  (passo a passo dos calculos para auditoria).
- Docstrings em portugues, identificadores em ingles.
