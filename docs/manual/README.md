# Manual do app (DSSE Workbench)

Manual de uso do aplicativo, escrito para quem vai **usar** o app, não para
quem desenvolve. Está **em inglês**, porque o público inclui gente de fora do
grupo, e organizado na ordem em que o app é usado de verdade (define-se a
rede, roda-se o fluxo de potência, estima-se o estado, e só então bad data,
cadeia de medição, console e agentes).

| Arquivo | O que é |
|---|---|
| [manual_app.html](manual_app.html) | O manual. Abrir com duplo clique; funciona offline. |
| [manual_app.pdf](manual_app.pdf) | O mesmo manual em PDF A4, com sumário e numeração de página. |

Documentação vizinha, com outro propósito:

- [docs/ARQUITETURA.md](../ARQUITETURA.md) — como o app é montado por dentro
  (backend, API, fluxo de dados). Referência de quem desenvolve.
- [packaging/README.md](../../packaging/README.md) — empacotamento, instalador
  e publicação de versão.
- [docs/planejamento/cadeia_operacional_validacao.md](../planejamento/cadeia_operacional_validacao.md)
  — roteiro de validação da cadeia operacional.
- A aba **Help** do próprio app — documentação matemática (algoritmos,
  equações, métodos de bad data), mantida em
  `app/frontend/src/lib/helpContent.ts`.

## Regenerar figuras e PDF

Os dois scripts precisam do Playwright — numa máquina nova, instalar as
ferramentas de trabalho antes (uma vez só):

```bash
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
```

```bash
.venv/Scripts/python.exe scripts/capturar_screenshots_app.py   # figuras + marcações
.venv/Scripts/python.exe scripts/gerar_manual_pdf.py           # PDF
```

O [script de captura](../../scripts/capturar_screenshots_app.py) sobe o app,
visita cada aba, executa a ação principal dela e **recorta o painel** de que
cada figura trata, salvando em
[docs/assets/capturas_app/manual/](../assets/capturas_app/manual/). Em seguida
pergunta ao DOM o retângulo de cada elemento marcado e grava `coords.js` junto
das imagens; o HTML cita a marcação pelo nome e converte para porcentagem, de
modo que figura e numeração são sempre regeneradas juntas.

Quatro decisões que não são detalhe:

- **Recorte, não página inteira.** O manual também é PDF, e um print de página
  inteira tem milhares de pixels de altura: numa página A4 ele seria cortado.
- **Captura em 2×.** Reduzida para caber na página, uma captura em 1× fica
  ilegível impressa.
- **Marcação medida, nunca escrita à mão.** Coordenada escrita no HTML
  envelhece em silêncio: o número continua desenhado, apontando para o lugar
  errado. Marcação que não casa mais some da figura e a legenda avisa.

- **Cada capítulo de aba abre com a aba inteira** (`Figure N.0`), antes dos
  recortes. Os recortes respondem "onde fica este controle"; nenhum deles
  responde "com o que essa tela se parece", e sem isso quem lê vê pedaços sem
  conseguir situar nenhum. A abertura não leva números: é imagem de
  orientação, não de instrução, e numerar ali competiria com os recortes.
  Onde a página inteira é alta demais para servir de abertura — a aba Bad
  Data tem 3393 px depois de rodar os quatro estágios — captura-se a
  viewport, e a legenda diz que é o topo da aba. Mesmo critério que já valia
  para o `app_bad_data.png` de slides.

## O tamanho da figura também é medido, não escrito

O `coords.js` guarda, além das marcações, a **largura e a altura reais em px
CSS** de cada figura. O HTML usa esses números para nunca ampliar uma figura
além do tamanho que ela tem na tela do app.

Sem isso, o CSS antigo (`figure.shot img { width: 100% }`) esticava toda
figura até a largura da coluna, independentemente do tamanho dela: o painel
de medidores da Topology, que tem 248x137 px, virava 840 px de largura — 3,4x
ampliado e borrado — e a coluna de configuração do estimador virava quase
1800 px de altura. Na impressão o problema não aparecia, porque as regras de
`@media print` já limitavam por altura; era só na tela.

Regra: recorte não passa de 620 px de altura, abertura de capítulo não passa
de 1000 px, e nenhuma das duas passa da largura que tem no app nem da largura
da coluna.


Para marcar um elemento novo: acrescente uma `Figure`/`Pin` em
`MANUAL_FIGURES` no script de captura, cite o nome no `data-pins` da figura no
HTML (na mesma ordem dos passos numerados ao lado) e rode os dois comandos
acima.
