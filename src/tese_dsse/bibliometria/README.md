# Bibliometria (estilo Biblioshiny)

Pipeline reprodutível para a revisão bibliográfica da coleção *State Estimation* do Zotero.

```
Zotero (coleção) → OpenAlex (países, citações, referências) → classificação por regras → gráficos Plotly
```

## Módulos

| Arquivo | Função |
|---|---|
| [corpus.py](corpus.py) | Lê uma coleção do Zotero (com subcoleções) e normaliza num `DataFrame`; cache em `pesquisa/revisao_bibliografica/data/` |
| [openalex.py](openalex.py) | Enriquece cada item (DOI ou título) com países, instituições, citações, keywords e referências; cache JSON por item |
| [classificacao.py](classificacao.py) | Regras regex auditáveis: estática × dinâmica, agêntico, tipo de rede, métodos, problemas |
| [graficos.py](graficos.py) | Gráficos: produção anual, sunburst, roscas, métodos/problemas, heatmaps, nuvens de palavras, redes (co-ocorrência, coautoria, acoplamento), mapa de países, citações |

## Como usar

Notebook: [2026-10-13_bibliometria_state_estimation.ipynb](../../../notebooks/revisao_bibliografica/2026-10-13_bibliometria_state_estimation.ipynb)
(gerado por [gerar_notebook_bibliometria.py](../../../scripts/gerar_notebook_bibliometria.py)).

Parâmetros na 2ª célula: `COLECAO` (`VFE4S2IH` = State Estimation; `H2MW3JHF` = núcleo da tese),
`ATUALIZAR_ZOTERO`, `ATUALIZAR_OPENALEX`, `PASSO_PERIODO`, `SINONIMOS`.
Figuras saem em `pesquisa/revisao_bibliografica/figuras/` (HTML; nuvens também PNG/SVG/PDF).

## Decisões

- Classificação por regras e não por LLM: é auditável (seção 3 do notebook mostra o que cada regra pegou).
- Afiliações vêm do OpenAlex, pois o Zotero não as guarda.
- Tags de fluxo do Zotero (`to be read`) são ignoradas nas palavras.
- Registrado em [decisoes_tecnicas.md](../../../docs/governanca/decisoes_tecnicas.md).

## Dependências extras

`pip install wordcloud pycountry pyzotero python-dotenv` (plotly, networkx, pandas já no `.venv`).
Para exportar os gráficos Plotly em PNG/SVG/PDF: `kaleido` (+ Chrome).
