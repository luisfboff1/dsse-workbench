# sistemas_dinamicos

Estimadores dinamicos para a DSSE variante no tempo.

## Responsabilidade

Estimar o estado quando ele **evolui no tempo**, com um modelo de processo
`x_{k+1} = f(x_k) + w_k`, em vez de tratar cada instante isoladamente.

## Escopo implementado

- Filtro de Kalman (KF) linear e filtro de Kalman estendido (EKF).
- Passeio aleatorio ou matriz de transicao `F` fornecida pelo chamador.
- Calibracao diagonal de `Q` usando somente um historico anterior e separado.
- Inovacao normalizada, assimetria, remocao adaptativa de erro grosseiro e
  reinicio por estimador estatico em mudancas de estado.
- Resultado estruturado com estados, covariancias, mascaras e eventos.

API publica em [`kalman.py`](kalman.py):

- `calibrate_process_noise()`;
- `run_linear_kalman_filter()`;
- `run_extended_kalman_filter()`;
- `InnovationAdaptation` e `DynamicEstimationResult`.

UKF, FASE com previsao explicita e fusao multi-rate permanecem no backlog.

## Diferenca para `estimacao_estado`

- [`estimacao_estado`](../estimacao_estado) resolve **snapshots estaticos**
  (um instante por chamada do WLS).
- Aqui ha **dinamica temporal**: o estado e propagado de um passo para o outro.

## Conexoes

- Reutiliza `h(x)` e `H(x)` dos [modelos](docs/simulacao/modelos.md) AC/DC de `estimacao_estado`.
- Consome series temporais de medicoes de [`geracao_dados`](../geracao_dados).
- O caso de validacao atual esta em
  [`14_BUS_IEEE_dynamic_AC.ipynb`](../../../notebooks/simulacao/14_BUS_IEEE_dynamic_AC.ipynb).

## Regra de validacao para `Q`

Nunca calibre `Q` com `x_true` do mesmo periodo usado para avaliar o filtro.
Use um periodo historico anterior, uma janela de calibracao que termina antes do
teste ou estados estimados em operacao. Em [simulacao](docs/notebooks/simulacao.md), a trajetoria de calibracao
deve ser gerada separadamente da trajetoria avaliada.

## Convencoes

- Funcoes pesadas em `.py`; notebooks apenas chamam.
- Use `tese_dsse.auditoria.AuditTrail` para o `verbose` padronizado.
- Docstrings em portugues, identificadores em ingles.
