"""Funcoes de visualizacao para notebooks de estimacao DC linear."""

from __future__ import annotations

import json
from typing import Any

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from scipy.stats import chi2


def bus_positions_from_geo(net: Any, seed: int = 0) -> dict[int, tuple[float, float]]:
    """Retorna posicoes de barras usando ``net.bus.geo`` ou um layout de grafo."""

    pos: dict[int, tuple[float, float]] = {}
    for bus, row in net.bus.iterrows():
        geo = row.get("geo", None)
        if isinstance(geo, str) and geo:
            try:
                data = json.loads(geo)
                x, y = data["coordinates"]
                pos[int(bus)] = (float(x), float(y))
            except Exception:
                pass
    if len(pos) == len(net.bus):
        return pos

    graph = nx.Graph()
    graph.add_nodes_from([int(b) for b in net.bus.index])
    for _, line in net.line.iterrows():
        graph.add_edge(int(line.from_bus), int(line.to_bus))
    if hasattr(net, "trafo"):
        for _, trafo in net.trafo.iterrows():
            graph.add_edge(int(trafo.hv_bus), int(trafo.lv_bus))
    return {int(k): tuple(v) for k, v in nx.spring_layout(graph, seed=seed).items()}


def plot_pandapower_topology(
    net: Any,
    slack_bus: int | None = None,
    seed: int = 0,
    title: str = "Topologia da rede",
    ax=None,
):
    """Plota linhas e transformadores com labels de barra."""

    if ax is None:
        _, ax = plt.subplots(figsize=(11, 7))
    bus_ids = [int(b) for b in net.bus.index]
    graph = nx.Graph()
    graph.add_nodes_from(bus_ids)

    line_edges = []
    for lid, line in net.line.iterrows():
        edge = (int(line.from_bus), int(line.to_bus))
        graph.add_edge(*edge, kind="line", element=int(lid))
        line_edges.append(edge)

    trafo_edges = []
    if hasattr(net, "trafo"):
        for tid, trafo in net.trafo.iterrows():
            edge = (int(trafo.hv_bus), int(trafo.lv_bus))
            graph.add_edge(*edge, kind="trafo", element=int(tid))
            trafo_edges.append(edge)

    pos = bus_positions_from_geo(net, seed=seed)
    nx.draw_networkx_edges(graph, pos, edgelist=line_edges, width=1.4, edge_color="#4c78a8", ax=ax)
    if trafo_edges:
        nx.draw_networkx_edges(
            graph,
            pos,
            edgelist=trafo_edges,
            width=1.6,
            edge_color="#f58518",
            style="dashed",
            ax=ax,
        )
    nx.draw_networkx_nodes(graph, pos, node_size=220, node_color="#f7f7f7", edgecolors="#222222", ax=ax)
    if slack_bus is not None:
        nx.draw_networkx_nodes(
            graph,
            pos,
            nodelist=[int(slack_bus)],
            node_size=330,
            node_color="#cc3333",
            edgecolors="#222222",
            ax=ax,
        )
    labels = {
        b: str(net.bus.at[b, "name"]) if "name" in net.bus.columns else str(b)
        for b in bus_ids
    }
    nx.draw_networkx_labels(graph, pos, labels=labels, font_size=8, ax=ax)
    ax.set_title(title)
    ax.axis("equal")
    ax.axis("off")
    return ax, pos


def plot_chi2_distribution(
    df_chi2: int,
    alpha: float,
    chi2_threshold: float,
    j_values: dict[str, float] | None = None,
    colors: dict[str, str] | None = None,
    ax=None,
):
    """Plota a distribuicao qui-quadrado e, opcionalmente, valores de J."""

    if ax is None:
        _, ax = plt.subplots(figsize=(10, 5))
    max_x = chi2.ppf(0.9995, df=df_chi2)
    if j_values:
        max_x = max(max_x, max(j_values.values()) * 1.08, chi2_threshold * 1.15)
    x = np.linspace(0.0, max_x, 1600)
    y = chi2.pdf(x, df=df_chi2)
    ax.plot(x, y, color="black", linewidth=2, label=f"Chi2(df={df_chi2})")
    ax.fill_between(x[x <= chi2_threshold], y[x <= chi2_threshold], color="#8ab17d", alpha=0.35)
    ax.fill_between(x[x >= chi2_threshold], y[x >= chi2_threshold], color="#e76f51", alpha=0.35)
    ax.axvline(chi2_threshold, color="red", linestyle="--", linewidth=2, label=f"chi2 = {chi2_threshold:.2f}")
    if j_values:
        for name, value in j_values.items():
            color = colors.get(name, None) if colors else None
            status = "passa" if value <= chi2_threshold else "alarme"
            ax.axvline(value, color=color, linewidth=2.0, alpha=0.95, label=f"{name}: J={value:.2f} ({status})")
    ax.set_xlabel("J")
    ax.set_ylabel("densidade")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    return ax


def plot_residual_bars(results, sigmas, colors=None, scenario_order=None):
    """Plota barras de residuos normalizados para varios cenarios."""

    scenario_order = scenario_order or list(results.keys())
    n = len(scenario_order)
    ncols = 2 if n > 1 else 1
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(13, 3.5 * nrows), squeeze=False, sharex=True, sharey=True)
    for ax, name in zip(axes.flat, scenario_order):
        result = results[name]
        sigma_vec = sigmas[name]
        r_norm = result["residual"] / sigma_vec
        ax.bar(np.arange(len(r_norm)), r_norm, color=(colors or {}).get(name, None), edgecolor="black", linewidth=0.25)
        ax.axhline(0.0, color="black", linewidth=0.7)
        ax.axhline(3.0, color="red", linestyle="--", linewidth=0.8)
        ax.axhline(-3.0, color="red", linestyle="--", linewidth=0.8)
        ax.set_title(f"Cenario {name}: J = {result['J']:.2f}")
        ax.set_xlabel("indice da medicao")
        ax.set_ylabel("r_i / sigma_i")
        ax.grid(True, axis="y", alpha=0.3)
    for ax in axes.flat[n:]:
        ax.axis("off")
    fig.tight_layout()
    return fig, axes
