# seguranca

Cyber security para a DSSE: modelagem de ataques e mecanismos de defesa.

> Uso estritamente academico e defensivo: o objetivo e avaliar a robustez dos
> estimadores e projetar contramedidas, nao operar ataques reais.

## Responsabilidade

Estudar como dados maliciosos afetam a estimacao de estado e como detecta-los
e mitiga-los.

## Escopo planejado

- **Ataques** False Data Injection (FDIA) furtivos, construidos no espaco-coluna
  de `H` (`a = H c`) para nao alterar o residuo do WLS.
- Ataques nao furtivos / ruido malicioso para testes de robustez.
- **Defesa**: deteccao por residuo, consistencia cruzada PMU/SCADA, protecao de
  um conjunto minimo de medidas, regras de plausibilidade.
- Metricas de impacto do ataque sobre o estado estimado.

## Conexoes

- Usa `H` e o estado de [`estimacao_estado`](../estimacao_estado) para construir
  ataques furtivos.
- Complementa [`deteccao_anomalias`](../deteccao_anomalias) (bad data classico)
  com ameacas deliberadas e coordenadas.

## Convencoes

- Funcoes pesadas em `.py`; notebooks apenas chamam.
- Use `tese_dsse.auditoria.AuditTrail` para o `verbose` padronizado.
- Docstrings em portugues, identificadores em ingles.
