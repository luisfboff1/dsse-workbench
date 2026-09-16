"""Algoritmos de partição topológica e detecção de fronteiras para DSSE multiagente."""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandapower as pp
from typing import Dict, List
from .base import AgentCluster


def _build_networkx_graph(net: pp.pandapowerNet) -> nx.Graph:
    G = nx.Graph()
    for b in net.bus.index:
        G.add_node(int(b))
    for idx, row in net.line.iterrows():
        fb = int(row.from_bus)
        tb = int(row.to_bus)
        r = float(row.r_ohm_per_km) * float(row.length_km)
        x = float(row.x_ohm_per_km) * float(row.length_km)
        z = np.sqrt(r**2 + x**2) if (r**2 + x**2) > 0 else 0.01
        weight = 1.0 / z
        G.add_edge(fb, tb, line_id=int(idx), weight=weight)
    return G


def partition_spectral(net: pp.pandapowerNet, k_clusters: int = 2) -> List[AgentCluster]:
    G = _build_networkx_graph(net)
    num_nodes = len(G.nodes)
    k = max(1, min(k_clusters, num_nodes))
    nodes = list(G.nodes)

    if k == 1:
        cluster = AgentCluster(
            cluster_id=0,
            name="Island 0",
            bus_ids=nodes,
            line_ids=list(net.line.index),
        )
        return [cluster]

    try:
        from scipy.sparse.csgraph import laplacian
        from scipy.linalg import eigh
        from sklearn.cluster import KMeans

        adj = nx.to_numpy_array(G, nodelist=nodes, weight="weight")
        L_norm = laplacian(adj, normed=True)
        vals, vecs = eigh(L_norm)
        vecs_k = vecs[:, :k]
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10).fit(vecs_k)
        labels = kmeans.labels_
    except Exception:
        labels = [i % k for i in range(num_nodes)]

    cluster_buses: Dict[int, List[int]] = {i: [] for i in range(k)}
    for node, label in zip(nodes, labels):
        cluster_buses[int(label)].append(int(node))

    cluster_buses = {idx: buses for idx, buses in enumerate(b for b in cluster_buses.values() if b)}

    clusters: List[AgentCluster] = []
    for c_id, b_ids in cluster_buses.items():
        lines_in_cluster = []
        for l_idx, row in net.line.iterrows():
            fb, tb = int(row.from_bus), int(row.to_bus)
            if fb in b_ids and tb in b_ids:
                lines_in_cluster.append(int(l_idx))

        clusters.append(AgentCluster(
            cluster_id=c_id,
            name=f"Island {c_id}",
            bus_ids=b_ids,
            line_ids=lines_in_cluster,
        ))

    detect_boundary_elements(net, clusters)
    return clusters


def partition_feeder_radial(net: pp.pandapowerNet, k_clusters: int = 2, root_bus: int = 0) -> List[AgentCluster]:
    G = _build_networkx_graph(net)
    k = max(1, min(k_clusters, len(G.nodes)))

    if k == 1:
        cluster = AgentCluster(
            cluster_id=0,
            name="Radial Subtree 0",
            bus_ids=list(G.nodes),
            line_ids=list(net.line.index),
        )
        return [cluster]

    if root_bus not in G.nodes:
        root_bus = list(G.nodes)[0]

    bfs_edges = list(nx.bfs_edges(G, source=root_bus))
    bfs_order = [root_bus] + [v for u, v in bfs_edges]
    
    chunk_size = int(np.ceil(len(bfs_order) / k))
    clusters: List[AgentCluster] = []

    for i in range(k):
        sub_nodes = bfs_order[i * chunk_size : (i + 1) * chunk_size]
        if not sub_nodes:
            continue
        lines_in_cluster = []
        for l_idx, row in net.line.iterrows():
            fb, tb = int(row.from_bus), int(row.to_bus)
            if fb in sub_nodes and tb in sub_nodes:
                lines_in_cluster.append(int(l_idx))

        clusters.append(AgentCluster(
            cluster_id=len(clusters),
            name=f"Radial Subtree {len(clusters)}",
            bus_ids=sub_nodes,
            line_ids=lines_in_cluster,
        ))

    detect_boundary_elements(net, clusters)
    return clusters


def detect_boundary_elements(net: pp.pandapowerNet, clusters: List[AgentCluster]):
    bus_to_cluster: Dict[int, int] = {}
    for cl in clusters:
        for b in cl.bus_ids:
            bus_to_cluster[b] = cl.cluster_id

    boundary_buses: Dict[int, set] = {cl.cluster_id: set() for cl in clusters}
    boundary_lines: Dict[int, set] = {cl.cluster_id: set() for cl in clusters}
    neighbor_clusters: Dict[int, set] = {cl.cluster_id: set() for cl in clusters}

    for l_idx, row in net.line.iterrows():
        fb, tb = int(row.from_bus), int(row.to_bus)
        c_from = bus_to_cluster.get(fb)
        c_to = bus_to_cluster.get(tb)

        if c_from is not None and c_to is not None and c_from != c_to:
            boundary_buses[c_from].add(fb)
            boundary_buses[c_to].add(tb)
            boundary_lines[c_from].add(int(l_idx))
            boundary_lines[c_to].add(int(l_idx))
            neighbor_clusters[c_from].add(c_to)
            neighbor_clusters[c_to].add(c_from)

    for cl in clusters:
        cl.boundary_bus_ids = sorted(list(boundary_buses[cl.cluster_id]))
        cl.boundary_line_ids = sorted(list(boundary_lines[cl.cluster_id]))
        cl.neighbor_cluster_ids = sorted(list(neighbor_clusters[cl.cluster_id]))
