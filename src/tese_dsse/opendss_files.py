from __future__ import annotations

from pathlib import Path

try:
    from .paths import SIM_OPENDSS_MODELS_DIR
except ImportError:  # pragma: no cover - direct script execution
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from tese_dsse.paths import SIM_OPENDSS_MODELS_DIR


DEMO_MASTER_DSS = """Clear
New Circuit.dsse_demo basekv=12.47 pu=1.0 phases=3 bus1=sourcebus

New Linecode.demo nphases=3 r1=0.642 x1=0.083 r0=0.642 x0=0.083 units=km

New Line.line1 bus1=sourcebus.1.2.3 bus2=loadbus.1.2.3 phases=3 length=1 units=km linecode=demo
New Load.load1 bus1=loadbus.1.2.3 phases=3 conn=wye kv=12.47 kw=300 kvar=120 model=1

Set VoltageBases=[12.47]
CalcVoltageBases
Solve mode=snapshot
"""


DEMO_BUSCOORDS_DSS = """BusCoords
sourcebus 0 0
loadbus 1000 0
"""


DEMO_RUN_DSS = """Clear
Compile Master.dss
Solve
Plot Circuit Power Max=500 dots=n labels=y subs=n C1=$0000FF
Show Voltages LN Nodes
Show Currents Elements
"""


def create_demo_dss_model(target_dir: str | Path | None = None) -> dict[str, Path]:
    if target_dir is None:
        target = SIM_OPENDSS_MODELS_DIR / "demo_minimal"
    else:
        target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    files = {
        "master": target / "Master.dss",
        "buscoords": target / "BusCoords.dss",
        "run_gui": target / "Run_OpenDSS_GUI.dss",
    }

    files["master"].write_text(DEMO_MASTER_DSS, encoding="utf-8")
    files["buscoords"].write_text(DEMO_BUSCOORDS_DSS, encoding="utf-8")
    files["run_gui"].write_text(DEMO_RUN_DSS, encoding="utf-8")
    return files


if __name__ == "__main__":
    for label, path in create_demo_dss_model().items():
        print(f"{label}: {path}")
