# Distribuição de Releases e Atualizações Automáticas

Este documento explica como funciona a distribuição pública do **DSSE Simulation Workbench** mantendo o repositório principal da tese (`phd-thesis`) estritamente privado.

---

## 1. O Problema Resolvido

- O repositório da tese (`luisfboff1/phd-thesis`) contém códigos, dados de pesquisa e rascunhos confidenciais que **devem permanecer privados**.
- No entanto, o `electron-updater` (mecanismo que atualiza os apps Windows dos usuários automaticamente) precisa consultar uma URL pública do GitHub Releases para saber se há versão nova e baixar os arquivos (`.exe` e `latest.yml`).
- Em um repositório privado, requisições anônimas de checagem de update recebem `HTTP 404 Not Found` do GitHub, bloqueando atualizações automáticas e downloads de qualquer usuário sem token.

---

## 2. A Arquitetura de Repositório Público de Releases

Para resolver isso sem abrir o código da tese, a distribuição é desacoplada em dois repositórios:

```
[Seu Computador]
   │
   │  git push origin app-vX.Y.Z
   ▼
[luisfboff1/phd-thesis] (PRIVADO)
   │  - Contém todo o código-fonte, modelos e simulações
   │  - GitHub Actions (.github/workflows/release-app.yml) roda aqui
   │  - Compila o backend (.exe) e o frontend
   │  - Usa o secret RELEASES_GH_TOKEN para publicar
   │
   ▼ (upload direto via GitHub Actions)
[luisfboff1/dsse-workbench-releases] (PÚBLICO)
   │  - Repositório público vazio, dedicado exclusivamente a releases
   │  - Não contém código-fonte da tese
   │  - Hospeda os instaladores: Setup-X.Y.Z.exe, latest.yml, zip
   │
   ▼ (download anônimo sem token)
[Usuários Finais & App Instalado]
   - autoUpdater consulta luisfboff1/dsse-workbench-releases
   - Download de updates e notificações funcionam 100% sem login
```

---

## 3. Onde os Agentes e Luis Trabalham

**100% do trabalho continua sendo feito nesta pasta (`phd-thesis`).**
- Não é necessário clonar o repositório `dsse-workbench-releases`.
- Não é necessário abrir duas pastas no editor.
- O ciclo de publicação é disparado unicamente por tags criadas neste repositório.

---

## 4. Como Publicar uma Nova Versão

Sempre que terminar alterações no app (`app/frontend`, `app/electron` ou `src/tese_dsse`):

1. **Subir a versão** em [`app/electron/package.json`](../app/electron/package.json):
   ```json
   "version": "0.6.2"
   ```
2. **Commitar:**
   ```powershell
   git add -A
   git commit -m "feat(app): sua mensagem aqui v0.6.2"
   ```
3. **Criar a tag com o mesmo número:**
   ```powershell
   git tag app-v0.6.2
   ```
4. **Enviar para o GitHub:**
   ```powershell
   git push origin main
   git push origin app-v0.6.2
   ```

O GitHub Actions (`release-app.yml`) rodará automaticamente no runner Windows, criará o instalador e fará o upload dos arquivos diretamente para `https://github.com/luisfboff1/dsse-workbench-releases/releases`.

---

## 5. Verificação Manual de Atualizações no App

Os usuários agora têm duas formas de buscar atualizações no próprio app:

1. **Pela interface (Aba Help):**
   - No rodapé da barra lateral de Help, há o badge com a versão atual instalada (`v0.6.1`) e o botão **"Check for updates"**.
   - O botão dá feedback instantâneo via toast:
     - *"Checking for updates…"*
     - *"You are on the latest version!"*
     - *"Version X.Y.Z is available! Downloading update in the background…"*
2. **Pelo menu nativo da janela:**
   - Menu superior do Windows: `Help -> Check for Updates...`
   - Menu `Help -> GitHub Releases & Downloads` (abre a página pública no navegador).
   - Menu `Help -> About DSSE Workbench`.

