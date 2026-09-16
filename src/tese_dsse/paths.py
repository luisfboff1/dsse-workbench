from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REVISAO_DIR = PROJECT_ROOT / "pesquisa" / "revisao_bibliografica"
REVISAO_DATA_DIR = REVISAO_DIR / "data"
REVISAO_FIGURES_DIR = REVISAO_DIR / "figures"
REVISAO_REPORTS_DIR = REVISAO_DIR / "reports"
NEWTON_WLS_DIR = PROJECT_ROOT / "pesquisa" / "newton_raphson_estimacao_estado"
NEWTON_WLS_DATA_DIR = NEWTON_WLS_DIR / "data"
SIMULATION_DIR = PROJECT_ROOT / "simulacao"
SIM_DATA_DIR = SIMULATION_DIR / "data"
SIM_OUTPUTS_DIR = SIMULATION_DIR / "outputs"
SIM_OPENDSS_MODELS_DIR = SIMULATION_DIR / "modelos_opendss"
SIM_PANDAPOWER_MODELS_DIR = SIMULATION_DIR / "modelos_pandapower"
DOCS_DIR = PROJECT_ROOT / "docs"


def ensure_project_dirs() -> None:
    """Create the project output folders used by the simulation scripts."""
    for folder in (
        REVISAO_DATA_DIR,
        REVISAO_FIGURES_DIR,
        REVISAO_REPORTS_DIR,
        NEWTON_WLS_DATA_DIR,
        SIM_DATA_DIR,
        SIM_OUTPUTS_DIR,
        SIM_OPENDSS_MODELS_DIR,
        SIM_PANDAPOWER_MODELS_DIR,
        DOCS_DIR,
    ):
        folder.mkdir(parents=True, exist_ok=True)
