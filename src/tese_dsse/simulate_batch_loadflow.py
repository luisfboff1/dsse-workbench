from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

try:
    from .pandapower_connection import solve_three_bus_distribution_network
    from .paths import SIM_OUTPUTS_DIR, ensure_project_dirs
except ImportError:  # pragma: no cover - direct script execution
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from tese_dsse.pandapower_connection import solve_three_bus_distribution_network
    from tese_dsse.paths import SIM_OUTPUTS_DIR, ensure_project_dirs


def load_scale_for_step(step: int, steps: int) -> float:
    daily_component = 1.0 + 0.18 * math.sin(2.0 * math.pi * step / max(steps, 1))
    faster_component = 0.04 * math.sin(2.0 * math.pi * step / 12.0)
    return max(0.45, daily_component + faster_component)


def run_batch_loadflow(steps: int = 120, interval_seconds: int = 4) -> pd.DataFrame:
    records = []
    for step in range(steps):
        load_scale = load_scale_for_step(step, steps)
        result = solve_three_bus_distribution_network(load_scale=load_scale)
        records.append(
            {
                "step": step,
                "time_s": step * interval_seconds,
                "load_scale": load_scale,
                "converged": result["converged"],
                "vm_source_pu": result["bus_vm_pu"][0],
                "vm_mid_pu": result["bus_vm_pu"][1],
                "vm_load_pu": result["bus_vm_pu"][2],
                "va_source_degree": result["bus_va_degree"][0],
                "va_mid_degree": result["bus_va_degree"][1],
                "va_load_degree": result["bus_va_degree"][2],
                "line_1_loading_percent": result["line_loading_percent"][0],
                "line_2_loading_percent": result["line_loading_percent"][1],
            }
        )
    return pd.DataFrame.from_records(records)


def save_outputs(df: pd.DataFrame, output_dir: Path = SIM_OUTPUTS_DIR) -> dict[str, Path]:
    ensure_project_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "pandapower_batch_loadflow.csv"
    png_path = output_dir / "pandapower_batch_loadflow_vm_load.png"
    df.to_csv(csv_path, index=False)

    try:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.plot(df["time_s"], df["vm_load_pu"], label="Load bus")
        ax.plot(df["time_s"], df["vm_mid_pu"], label="Mid bus", alpha=0.85)
        ax.set_xlabel("Tempo (s)")
        ax.set_ylabel("Tensao (p.u.)")
        ax.set_title("Batch load flow - pandapower demo")
        ax.grid(True, alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(png_path, dpi=160)
        plt.close(fig)
    except Exception as exc:  # pragma: no cover - optional plot path
        print(f"Aviso: nao foi possivel gerar figura: {exc}")

    return {"csv": csv_path, "plot": png_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a small pandapower batch load-flow demo.")
    parser.add_argument("--steps", type=int, default=120)
    parser.add_argument("--interval-seconds", type=int, default=4)
    args = parser.parse_args()

    df = run_batch_loadflow(steps=args.steps, interval_seconds=args.interval_seconds)
    outputs = save_outputs(df)
    print(df.head().to_string(index=False))
    print("")
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
