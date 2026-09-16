# Empacotamento — DSSE Workbench como aplicativo instalável

Transforma o workbench (hoje: `scripts/run_app.ps1`, dois terminais, `.venv` e
Node na máquina) num instalador `.exe` que qualquer pessoa baixa e abre, sem
Python, sem Node, sem VSCode.

## Como funciona

Nada fica hospedado — o app roda inteiro na máquina de quem instalou:

1. O **Electron** ([app/electron/main.js](../app/electron/main.js)) sobe o
   backend como processo filho.
2. O **backend** é um `.exe` do PyInstaller com Python, FastAPI, pandapower e
   OpenDSS embutidos. Ele escuta só em `127.0.0.1`, numa **porta efêmera** que
   ele mesmo escolhe e anuncia no stdout (`DSSE_BACKEND_PORT=<porta>`) — porta
   fixa quebraria ao abrir duas cópias do app.
3. O mesmo backend **serve a SPA**. A janela carrega
   `http://127.0.0.1:<porta>/`, então o `fetch('/api/...')` relativo do
   frontend continua valendo — sem CORS, sem `file://`, sem reescrever caminho
   de asset.

A única coisa que usa rede é a **atualização automática**, e mesmo assim só
para ler arquivos estáticos de uma GitHub Release.

## Build local

```bash
# 1. dependências do bundle (menores que requirements.txt da raiz — ver o
#    comentário lá dentro sobre por que não reusamos aquele arquivo)
pip install -r packaging/requirements-app.txt

# 2. frontend (o spec aborta se dist/ não existir)
cd app/frontend && npm ci && npm run build && cd ../..

# 3. backend → packaging/dist/dsse-backend/
pyinstaller packaging/dsse_backend.spec --noconfirm \
  --distpath packaging/dist --workpath packaging/build

# 4. instalador + portable + zip → packaging/release/
cd app/electron && npm install && npm run dist
```

## Atrás de proxy corporativo

Numa rede que exige proxy (o PC do lab, por exemplo), `npm config set proxy`
**não basta**: cobre só o registry. O postinstall do Electron baixa o binário
do Chromium do GitHub com `got`, que ignora a config do npm e falha com
`RequestError: connect ETIMEDOUT`. Exporte as variáveis antes, na mesma sessão
do shell:

```powershell
$env:HTTP_PROXY  = "http://<proxy>:<porta>"
$env:HTTPS_PROXY = $env:HTTP_PROXY
$env:ELECTRON_GET_USE_PROXY   = "true"
$env:GLOBAL_AGENT_HTTP_PROXY  = $env:HTTP_PROXY
$env:GLOBAL_AGENT_HTTPS_PROXY = $env:HTTP_PROXY
```

O `electron-builder` também baixa NSIS e winCodeSign do GitHub, então
`npm run dist` precisa rodar na mesma janela — num terminal novo as variáveis
somem e o build quebra no meio.

## Publicar uma versão

As releases são publicadas automaticamente no repositório público **[`luisfboff1/dsse-workbench-releases`](https://github.com/luisfboff1/dsse-workbench-releases)**, garantindo que usuários finais e o `electron-updater` consigam baixar os instaladores e receber atualizações sem precisar de token ou acesso ao repositório privado da tese.
Documentação completa em [DISTRIBUICAO_RELEASES.md](DISTRIBUICAO_RELEASES.md).

O `version` em [app/electron/package.json](../app/electron/package.json) **tem
que bater com a tag** — é por ele que o `electron-updater` decide se há
atualização.

Use [scripts/release_app.ps1](../scripts/release_app.ps1) para os passos 1-3
(bump de version + commit + tag) — deriva os dois do mesmo número, então não
tem como voltar a divergir como em 18/08/2026:

```powershell
.\scripts\release_app.ps1 -Bump patch   # ou -Bump minor / -Bump major
# revise o commit/tag criados, depois rode o push que o script imprime
```

Ou manualmente:

```bash
# edite "version" para a nova versão (ex: 0.6.2), então:
git tag app-v0.6.2 && git push origin app-v0.6.2
```

[.github/workflows/release-app.yml](../.github/workflows/release-app.yml) faz o
resto e publica os instaladores diretamente no repositório público
[`luisfboff1/dsse-workbench`](https://github.com/luisfboff1/dsse-workbench).

Para manter o código-fonte aberto da ferramenta sincronizado com o repositório público:
```powershell
python scripts/sync_public_workbench.py --push
```
E para incorporar contribuições/PRs da comunidade de volta ao workspace:
```powershell
python scripts/sync_public_workbench.py --pull
```

## O que o usuário recebe

| Artefato | Wizard | Atualização automática |
|---|---|---|
| `DSSE Workbench Setup <v>.exe` | sim (escolhe pasta, cria atalhos) | **sim** |
| `DSSE Workbench <v>.exe` (portable) | não instala, roda direto | não |
| `DSSE Workbench-<v>-win.zip` | não | não |

Só o instalador NSIS recebe atualização — `portable` e `zip` não têm como se
substituir no lugar. Divulgue o instalador como download principal e deixe os
outros dois para quem não pode instalar nada na máquina.

Para trocar o wizard por instalação de um clique só, mude `"oneClick"` para
`true` em `build.nsis`.

## Onde ficam os dados do usuário

Cenários salvos vão para `%APPDATA%/dsse-workbench/cenarios_app/`, não para
dentro do repositório — o app instalado roda de `Program Files`, que é
somente-leitura. O Electron passa esse caminho ao backend via `DSSE_DATA_DIR`;
em dev, sem a variável, tudo continua indo para `simulacao/cenarios_app/` como
antes. Ver [app/backend/paths.py](../app/backend/paths.py).

O desinstalador **preserva** esses dados (`deleteAppDataOnUninstall: false`).

## Diagnóstico do bundle

O backend empacotado aceita `DSSE_DIAG=1`, que imprime como o pandapower está
resolvendo seus arquivos de dados e sai, sem subir servidor:

```powershell
$env:DSSE_DIAG = "1"; .\packaging\dist\dsse-backend\dsse-backend.exe
```

Existe porque essa classe de erro só aparece congelada — em dev tudo funciona,
e de fora do bundle não há como inspecionar. Foi o que permitiu achar o
problema do `pandapower.__init__` (ver
[rthook_pandapower.py](rthook_pandapower.py)), depois de duas hipóteses
erradas feitas por dedução.

Se um caso de rede voltar a falhar com `JSONDecodeError: Expecting value:
line 1 column 1`, comece por aqui: `isfile=False` em algum alvo aponta direto
para o culpado.

## Pendência conhecida: assinatura de código

O instalador não é assinado, então o Windows SmartScreen mostra *"O Windows
protegeu o seu computador"* na primeira execução — o usuário precisa clicar em
**Mais informações → Executar assim mesmo**. Não é erro de build. Remover o
aviso exige certificado de assinatura (~US$200-400/ano); enquanto não houver,
avise no texto do download.
