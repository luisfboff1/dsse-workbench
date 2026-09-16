from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx

try:
    from .opendss_connection import build_minimal_circuit, import_opendss
    from .paths import SIM_OUTPUTS_DIR, ensure_project_dirs
except ImportError:  # pragma: no cover - direct script execution
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from tese_dsse.opendss_connection import build_minimal_circuit, import_opendss
    from tese_dsse.paths import SIM_OUTPUTS_DIR, ensure_project_dirs


def _clean_bus_name(bus_name: str) -> str:
    return bus_name.split(".")[0].lower()


def active_circuit_voltage_by_bus(dss: Any) -> dict[str, float]:
    voltages: dict[str, float] = {}
    for bus in dss.Circuit.AllBusNames():
        dss.Circuit.SetActiveBus(bus)
        values = list(dss.Bus.puVmagAngle())
        magnitudes = [float(values[i]) for i in range(0, len(values), 2)]
        if magnitudes:
            voltages[_clean_bus_name(bus)] = sum(magnitudes) / len(magnitudes)
    return voltages


def active_circuit_coordinates(dss: Any | None = None) -> dict[str, tuple[float, float]]:
    if dss is None:
        dss = import_opendss()

    coordinates: dict[str, tuple[float, float]] = {}
    for bus in dss.Circuit.AllBusNames():
        dss.Circuit.SetActiveBus(bus)
        try:
            has_coordinates = bool(dss.Bus.Coorddefined())
        except Exception:
            has_coordinates = False
        x = float(dss.Bus.X())
        y = float(dss.Bus.Y())
        if has_coordinates or x != 0.0 or y != 0.0:
            coordinates[_clean_bus_name(bus)] = (x, y)
    return coordinates


def active_circuit_graph(dss: Any | None = None) -> nx.Graph:
    if dss is None:
        dss = import_opendss()

    graph = nx.Graph()
    voltages = active_circuit_voltage_by_bus(dss)

    for bus, vm_pu in voltages.items():
        graph.add_node(bus, vm_pu=vm_pu)

    for element_name in dss.Circuit.AllElementNames():
        if not element_name.lower().startswith(("line.", "transformer.")):
            continue
        dss.Circuit.SetActiveElement(element_name)
        bus_names = [_clean_bus_name(bus) for bus in dss.CktElement.BusNames()]
        if len(bus_names) >= 2 and bus_names[0] != bus_names[1]:
            graph.add_edge(bus_names[0], bus_names[1], element=element_name)

    return graph


def plot_active_circuit_graph(
    dss: Any | None = None,
    output_path: str | Path | None = None,
    title: str = "OpenDSS circuit graph",
    labels: bool = True,
    edge_labels: bool = True,
    prefer_coordinates: bool = True,
) -> Path:
    ensure_project_dirs()
    if dss is None:
        dss = import_opendss()
    if output_path is None:
        output_path = SIM_OUTPUTS_DIR / "opendss_circuit_graph.png"
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    graph = active_circuit_graph(dss)
    if graph.number_of_nodes() == 0:
        raise ValueError("Nao ha barras no circuito ativo do OpenDSS.")

    import matplotlib.pyplot as plt

    coordinates = active_circuit_coordinates(dss) if prefer_coordinates else {}
    if coordinates and set(coordinates).issuperset(set(graph.nodes)):
        pos = coordinates
    elif len(coordinates) >= 2:
        auto_pos = nx.spring_layout(graph, seed=42)
        pos = {node: coordinates.get(node, auto_pos[node]) for node in graph.nodes}
    else:
        pos = nx.spring_layout(graph, seed=42)

    node_values = [graph.nodes[node].get("vm_pu", 1.0) for node in graph.nodes]
    node_labels = {
        node: f"{node}\n{graph.nodes[node].get('vm_pu', 0):.4f} pu" for node in graph.nodes
    }

    fig, ax = plt.subplots(figsize=(9, 6))
    nodes = nx.draw_networkx_nodes(
        graph,
        pos,
        node_color=node_values,
        cmap="viridis",
        vmin=min(node_values),
        vmax=max(node_values),
        node_size=1500,
        edgecolors="#1f2933",
        linewidths=1.2,
        ax=ax,
    )
    nx.draw_networkx_edges(graph, pos, width=2.0, edge_color="#52606d", ax=ax)
    if labels:
        font_size = 9 if graph.number_of_nodes() <= 30 else 6
        nx.draw_networkx_labels(graph, pos, labels=node_labels, font_size=font_size, ax=ax)
    if edge_labels and graph.number_of_edges() <= 40:
        edge_label_map = nx.get_edge_attributes(graph, "element")
        nx.draw_networkx_edge_labels(graph, pos, edge_labels=edge_label_map, font_size=8, ax=ax)
    fig.colorbar(nodes, ax=ax, label="Tensao media da barra (p.u.)")
    ax.set_title(title)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)
    return output


def compile_and_plot_dss_file(
    dss_file: str | Path,
    output_path: str | Path | None = None,
    title: str | None = None,
    labels: bool = False,
    edge_labels: bool = False,
) -> Path:
    dss_path = Path(dss_file).resolve()
    if not dss_path.exists():
        raise FileNotFoundError(dss_path)

    dss = import_opendss()
    dss.Text.Command("Clear")
    dss.Text.Command(f'Compile "{dss_path}"')
    dss.Text.Command("Solve")

    plot_title = title or f"OpenDSS feeder - {dss_path.parent.name}"
    if output_path is None:
        output_path = SIM_OUTPUTS_DIR / f"{dss_path.parent.name}_opendss_graph.png"
    return plot_active_circuit_graph(
        dss,
        output_path=output_path,
        title=plot_title,
        labels=labels,
        edge_labels=edge_labels,
    )


def plot_minimal_demo() -> Path:
    dss = build_minimal_circuit()
    dss.Text.Command("Solve")
    return plot_active_circuit_graph(dss, title="OpenDSS minimal demo")


if __name__ == "__main__":
    print(plot_minimal_demo())
