"""Resolucao de caminhos do backend, valida tanto em dev quanto empacotado.

Existe porque o app tem dois modos de execucao com regras de path opostas:

- **dev** (`uvicorn app.backend.main:app` a partir do repo): `tese_dsse` mora em
  `src/`, que nao esta instalado, entao precisa entrar no `sys.path` na mao; e
  os cenarios salvos vao para dentro do proprio repo, onde o Luis quer ve-los
  versionados.
- **empacotado** (PyInstaller dentro do Electron): `tese_dsse` ja vem embutido
  como pacote importavel normal, entao mexer no `sys.path` e no-op; e o
  executavel roda de `Program Files`, que e somente-leitura -- gravar cenario
  ali falha com `PermissionError`. Por isso os dados do usuario vao para
  `%APPDATA%` (ou o equivalente do SO).

Todo modulo do backend que precise de `src/` ou de disco gravavel deve passar
por aqui, nunca montar o caminho na mao.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# PyInstaller marca o processo com `frozen` e extrai o bundle em `_MEIPASS`.
IS_FROZEN = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

#: Raiz do repositorio. So faz sentido em dev -- no empacotado nao ha repo.
REPO_ROOT: Path | None = None if IS_FROZEN else Path(__file__).resolve().parents[2]


def ensure_src_on_path() -> None:
    """Garante que `import tese_dsse` funcione.

    Em dev insere `src/` no `sys.path`; no empacotado nao faz nada, porque o
    PyInstaller ja embutiu `tese_dsse` como pacote de primeira classe (ver
    `hiddenimports` em `packaging/dsse_backend.spec`).

    Idempotente -- pode ser chamada por quantos modulos quiserem.
    """
    if IS_FROZEN or REPO_ROOT is None:
        return
    src = str(REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _default_data_dir() -> Path:
    """Diretorio gravavel de dados do usuario, por SO."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "dsse-workbench"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "dsse-workbench"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "dsse-workbench"
    return Path.home() / ".local" / "share" / "dsse-workbench"


def data_dir() -> Path:
    """Raiz gravavel para dados do usuario.

    Precedencia:

    1. `DSSE_DATA_DIR` -- o Electron sempre seta isso com `app.getPath('userData')`,
       para que app e instalador concordem sobre onde ficam os dados.
    2. Em dev, `simulacao/cenarios_app` no repo, preservando o comportamento
       antigo (cenarios versionados junto com a tese).
    3. No empacotado sem env var (rodar o .exe do backend na mao, para debug),
       o diretorio padrao do SO.
    """
    override = os.environ.get("DSSE_DATA_DIR")
    if override:
        return Path(override)
    if REPO_ROOT is not None:
        return REPO_ROOT / "simulacao"
    return _default_data_dir()


def scenario_dir() -> Path:
    """Pasta dos cenarios salvos pelo workbench."""
    return data_dir() / "cenarios_app"


def frontend_dist() -> Path | None:
    """Build do Vite, quando disponivel para o backend servir.

    No empacotado o `dist/` vem embutido no bundle do PyInstaller, e o backend
    e quem serve a SPA -- assim o Electron carrega `http://127.0.0.1:<porta>/`
    em vez de `file://`, o `fetch('/api/...')` relativo continua valendo e nao
    ha CORS nem caminho de asset para reescrever.

    Em dev devolve o `dist/` do repo se ele existir, o que permite conferir o
    layout empacotado so subindo o uvicorn e abrindo a porta 8000. O fluxo
    normal de dev (Vite na 5173 com proxy) nao passa por aqui.
    """
    if IS_FROZEN:
        candidate = Path(sys._MEIPASS) / "frontend"  # type: ignore[attr-defined]
    elif REPO_ROOT is not None:
        candidate = REPO_ROOT / "app" / "frontend" / "dist"
    else:
        return None
    return candidate if (candidate / "index.html").is_file() else None


def display_path(path: Path) -> str:
    """Caminho curto para mostrar na UI.

    Em dev encurta para relativo ao repo (`simulacao/cenarios_app/x.json`); no
    empacotado nao ha raiz comum util, entao devolve o absoluto -- que e o que
    o usuario precisa para achar o arquivo no Explorer.
    """
    if REPO_ROOT is not None:
        try:
            return str(path.relative_to(REPO_ROOT))
        except ValueError:
            pass
    return str(path)
