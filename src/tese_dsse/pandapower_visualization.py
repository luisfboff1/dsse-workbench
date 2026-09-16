from __future__ import annotations

from pathlib import Path

try:
    from .pandapower_connection import create_three_bus_distribution_network, import_pandapower
    from .paths import SIM_OUTPUTS_DIR, ensure_project_dirs
except ImportError:  # pragma: no cover - direct script execution
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from tese_dsse.pandapower_connection import create_three_bus_distribution_network, import_pandapower
    from tese_dsse.paths import SIM_OUTPUTS_DIR, ensure_project_dirs


def plot_power_flow_results_html(net=None, output_path: str | Path | None = None) -> Path:
    ensure_project_dirs()
    pp = import_pandapower()
    if net is None:
        net = create_three_bus_distribution_network(load_scale=1.0)

    if not getattr(net, "converged", False):
        pp.runpp(net, algorithm="nr", calculate_voltage_angles=True)

    if output_path is None:
        output = SIM_OUTPUTS_DIR / "pandapower_powerflow_results.html"
    else:
        output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    from pandapower.plotting.plotly import pf_res_plotly

    pf_res_plotly(
        net,
        filename=str(output),
        auto_open=False,
        climits_volt=(0.98, 1.02),
        climits_load=(0, 100),
        line_width=3,
        bus_size=18,
    )
    return output


def plot_demo_power_flow_results_html() -> Path:
    net = create_three_bus_distribution_network(load_scale=1.0)
    return plot_power_flow_results_html(net)


if __name__ == "__main__":
    print(plot_demo_power_flow_results_html())
