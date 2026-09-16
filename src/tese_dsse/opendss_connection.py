from __future__ import annotations

from pathlib import Path
from typing import Any


def import_opendss():
    try:
        import opendssdirect as dss
    except ImportError as exc:  # pragma: no cover - environment diagnostic
        raise RuntimeError(
            "OpenDSSDirect.py nao esta instalado. Rode scripts/instalar_dependencias_simulacao.ps1."
        ) from exc
    return dss


def dss_version() -> str:
    dss = import_opendss()
    return dss.Basic.Version()


def build_minimal_circuit() -> Any:
    """Build a tiny feeder directly in OpenDSSDirect and return the dss module."""
    dss = import_opendss()
    dss.Text.Command("Clear")
    dss.Text.Command("New Circuit.dsse_demo basekv=12.47 pu=1.0 phases=3 bus1=sourcebus")
    dss.Text.Command(
        "New Linecode.demo nphases=3 r1=0.642 x1=0.083 r0=0.642 x0=0.083 units=km"
    )
    dss.Text.Command(
        "New Line.line1 bus1=sourcebus.1.2.3 bus2=loadbus.1.2.3 "
        "phases=3 length=1 units=km linecode=demo"
    )
    dss.Text.Command(
        "New Load.load1 bus1=loadbus.1.2.3 phases=3 conn=wye kv=12.47 "
        "kw=300 kvar=120 model=1"
    )
    dss.Text.Command("Set VoltageBases=[12.47]")
    dss.Text.Command("CalcVoltageBases")
    return dss


def solve_minimal_power_flow() -> dict[str, Any]:
    dss = build_minimal_circuit()
    dss.Text.Command("Solve mode=snapshot")

    return {
        "engine": "OpenDSSDirect.py",
        "version": dss.Basic.Version(),
        "converged": bool(dss.Solution.Converged()),
        "iterations": int(dss.Solution.Iterations()),
        "bus_names": list(dss.Circuit.AllBusNames()),
        "bus_vmag_pu": [float(value) for value in dss.Circuit.AllBusMagPu()],
        "total_power_kw_kvar": [float(value) for value in dss.Circuit.TotalPower()],
    }


def compile_dss_file(path: str | Path) -> dict[str, Any]:
    dss_file = Path(path).resolve()
    if not dss_file.exists():
        raise FileNotFoundError(dss_file)

    dss = import_opendss()
    dss.Text.Command("Clear")
    dss.Text.Command(f'Compile "{dss_file}"')
    dss.Text.Command("Solve")

    return {
        "file": str(dss_file),
        "converged": bool(dss.Solution.Converged()),
        "bus_count": int(dss.Circuit.NumBuses()),
        "element_count": int(dss.Circuit.NumCktElements()),
        "bus_names": list(dss.Circuit.AllBusNames()),
    }


if __name__ == "__main__":
    print(solve_minimal_power_flow())
