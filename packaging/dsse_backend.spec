# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller para o backend do DSSE Workbench.

Build:  .venv/Scripts/pyinstaller packaging/dsse_backend.spec --noconfirm

Tres coisas que o PyInstaller nao descobre sozinho e por isso estao explicitas:

1. `tese_dsse` mora em `src/`, fora do pacote `app/`, e varias rotas importam
   submodulos dele dentro de funcoes (`from tese_dsse.powerflow.lindistflow
   import run_distflow`). Import dentro de funcao e invisivel para a analise
   estatica, entao os modulos precisam entrar como `hiddenimports`.

   Aqui a lista sai de uma varredura do diretorio, NAO de
   `collect_submodules`: aquela funcao importa o pacote num subprocesso
   isolado, que so enxerga o `sys.path` do venv -- e `tese_dsse` nao esta
   instalado, mora em `src/`. O subprocesso morre sem conseguir importar e o
   PyInstaller aborta com um `OSError: [Errno 22]` (e um `KeyboardInterrupt`
   espurio) que nao tem nada a ver com a causa real. Varrer arquivo e
   deterministico e nao importa nada.

   Recolhemos so `estimacao_estado` e `powerflow`, os dois unicos subpacotes
   que o backend usa: varrer `tese_dsse` inteiro arrastaria
   `zotero_integration` (pyzotero) e os modulos de visualizacao (matplotlib)
   para dentro de um bundle que nunca os chama.
2. De `pandapower` recolhemos **so os arquivos de dados**, nao os submodulos.

   `collect_all("pandapower")` forcava 361 hiddenimports -- todos os
   conversores (PowerFactory, CIM, UCTE, JAO, matpower), protection,
   contingency -- e esses arrastavam torch (528 MB), transformers (105 MB),
   onnxruntime e plotly para dentro do bundle. Verificado em 18/08/2026: com
   torch, tensorflow, transformers, onnxruntime, plotly, matplotlib e sklearn
   todos bloqueados na importacao, `/api/powerflow/run` (AC e DC),
   `/api/estimation/run` e o carregamento de casos continuam devolvendo 200.
   O que o app usa de fato o modulegraph acha sozinho seguindo os imports
   reais; so `pandapower.networks` fica explicito porque e importado dentro de
   funcao em `routes/topology.py`.

   **OpenDSS fica DE FORA de proposito.** Nenhuma rota do app, nenhum modulo de
   `tese_dsse` que o app importa, e nem o proprio pandapower carregam
   `opendssdirect` (verificado em 18/08/2026). Incluir custaria ~65 MB so de
   DLL. Se algum dia uma rota passar a usar OpenDSS, `collect_all("opendssdirect")`
   NAO basta: as bibliotecas nativas (`dss_capi.dll`, 29 MB) moram em
   `dss_python_backend`, nao em `opendssdirect` -- aquele collect_all devolve
   zero binarios e o bundle so quebra em runtime. O certo e recolher tambem
   `dss` e `dss_python_backend`.
3. O `dist/` do Vite entra como dado sob o nome `frontend`, que e onde
   `app.backend.paths.frontend_dist` procura quando congelado.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

PACKAGING_DIR = Path(SPECPATH).resolve()
REPO_ROOT = PACKAGING_DIR.parent
FRONTEND_DIST = REPO_ROOT / "app" / "frontend" / "dist"

if not (FRONTEND_DIST / "index.html").is_file():
    raise SystemExit(
        f"Build do frontend nao encontrado em {FRONTEND_DIST}.\n"
        "Rode `npm run build` em app/frontend antes de empacotar."
    )

datas = [(str(FRONTEND_DIST), "frontend")]
binaries = []
# Modulos de `estimacao_estado` que o backend nunca importa (nem direto, nem
# via `__init__`) e que sozinhos puxariam scikit-learn e matplotlib para o
# bundle -- centenas de MB para codigo que so roda em notebook.
UNUSED_BY_APP = {
    "tese_dsse.estimacao_estado.signature_model",
    "tese_dsse.estimacao_estado.signature_sweep",
    "tese_dsse.estimacao_estado.dc_plots",
}


def submodules_of(subpackage: str) -> list[str]:
    """Modulos de um subpacote de `tese_dsse`, lidos do disco.

    Sem import e sem subprocesso -- ver a nota 1 no topo sobre por que
    `collect_submodules` nao serve aqui.
    """
    folder = REPO_ROOT / "src" / Path(*subpackage.split("."))
    if not folder.is_dir():
        raise SystemExit(f"Subpacote nao encontrado: {folder}")
    found = [subpackage]
    for module in sorted(folder.glob("*.py")):
        if module.stem == "__init__":
            continue
        found.append(f"{subpackage}.{module.stem}")
    return found


hiddenimports = ["tese_dsse", "tese_dsse.auditoria"]
for subpackage in ("tese_dsse.estimacao_estado", "tese_dsse.powerflow"):
    hiddenimports += [m for m in submodules_of(subpackage) if m not in UNUSED_BY_APP]

datas += collect_data_files("pandapower")
hiddenimports.append("pandapower.networks")

a = Analysis(
    [str(PACKAGING_DIR / "backend_entry.py")],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    # Caminho absoluto de proposito: `runtime_hooks` resolve relativo ao
    # diretorio de trabalho, nao ao do spec (diferente do script principal),
    # entao um nome solto so funciona se o build rodar de dentro de packaging/.
    runtime_hooks=[str(PACKAGING_DIR / "rthook_pandapower.py")],
    # Pesos mortos que o pandapower/matplotlib arrastam e o backend nunca usa.
    excludes=[
        "tkinter",
        "PyQt5",
        "PySide2",
        "IPython",
        "notebook",
        "pytest",
        # Nenhuma rota chama codigo que precise destes -- confirmado
        # bloqueando a importacao de todos e exercitando as rotas (ver nota 2).
        # Sem os excludes explicitos, os conversores do pandapower reintroduzem
        # torch e companhia pela porta dos fundos.
        "sklearn",
        "matplotlib",
        "torch",
        "tensorflow",
        "transformers",
        "onnxruntime",
        "plotly",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="dsse-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Console habilitado: o Electron le a porta do stdout deste processo.
    # Com `console=False` o stdout some no Windows e o app trava esperando.
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="dsse-backend",
)
