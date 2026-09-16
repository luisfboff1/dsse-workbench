"""DistFlow backward-forward sweep para redes radiais de distribuição.

Referências:
  Baran & Wu (1989), "Network reconfiguration in distribution systems
  for loss reduction and load balancing."
  DOI: 10.1109/61.25591

Equações exatas (DistFlow):
    P_ij = P_d_j - P_g_j + Σ_k P_jk + R_ij · ℓ_ij
    Q_ij = Q_d_j        + Σ_k Q_jk + X_ij · ℓ_ij
    V²_j = V²_i - 2(R·P_ij + X·Q_ij) + (R²+X²) · ℓ_ij
    ℓ_ij = (P²_ij + Q²_ij) / V²_i

LinDistFlow é o caso especial ℓ=0 (sem perdas, passo único).
DistFlow iterativo converge para a solução exata da rede radial.

Correção de ângulo de primeira ordem (Baran & Wu não incluem, adicionamos):
    θ_i − θ_j ≈ (X_ij·P_ij − R_ij·Q_ij) / V_i   [rad]
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Any


def _build_tree(
    buses_raw: list[dict],
    lines_raw: list[dict],
    slack_id: int,
) -> tuple[list[int], dict[int, list[tuple[int, dict]]], dict[int, tuple[int, dict]]]:
    """BFS a partir do slack. Retorna (bfs_order, children, parent_info)."""
    # Verificação de radialidade por contagem de arestas: uma árvore com n
    # barramentos tem exatamente n-1 ramos. Uma rede malhada (ex. IEEE 14-bus)
    # pode alcançar todos os barramentos via BFS mesmo assim — o BFS apenas
    # descartaria os ramos redundantes em silêncio, produzindo um subconjunto
    # de árvore geradora arbitrário e resultados errados (V² divergindo para
    # negativo/NaN em parte da rede). Falhar aqui, alto e claro, é melhor que
    # devolver números que parecem válidos mas não são.
    n_expected = len(buses_raw) - 1
    if len(lines_raw) > n_expected:
        raise ValueError(
            f"Meshed network: {len(lines_raw)} lines for {len(buses_raw)} "
            f"buses (a radial tree needs exactly {n_expected}). "
            "DistFlow requires a radial (loop-free) network."
        )
    if len(lines_raw) < n_expected:
        raise ValueError(
            f"Network too sparse: {len(lines_raw)} lines for {len(buses_raw)} "
            f"buses (a radial tree needs exactly {n_expected}). Some buses may "
            "be unreachable — DistFlow requires a fully connected radial network."
        )

    adj: dict[int, list[tuple[int, dict]]] = defaultdict(list)
    for line in lines_raw:
        fid = int(line.get("from_bus", line.get("from", 0)))
        tid = int(line.get("to_bus", line.get("to", 0)))
        adj[fid].append((tid, line))
        adj[tid].append((fid, line))

    visited: set[int] = {slack_id}
    children: dict[int, list[tuple[int, dict]]] = defaultdict(list)
    parent_info: dict[int, tuple[int, dict]] = {}
    bfs_order: list[int] = []
    queue: deque[int] = deque([slack_id])

    while queue:
        node = queue.popleft()
        bfs_order.append(node)
        for neighbor, line in adj[node]:
            if neighbor not in visited:
                visited.add(neighbor)
                children[node].append((neighbor, line))
                parent_info[neighbor] = (node, line)
                queue.append(neighbor)

    if len(bfs_order) != len(buses_raw):
        raise ValueError(
            f"Network not fully connected: BFS reached {len(bfs_order)} of "
            f"{len(buses_raw)} buses. DistFlow requires a connected radial network."
        )

    return bfs_order, children, parent_info


def run_distflow(
    topology: dict[str, Any],
    max_iter: int = 30,
    tol: float = 1e-8,
) -> dict[str, Any]:
    """DistFlow iterativo completo (Baran & Wu 1989).

    Inclui termos de perda (R²+X²)·ℓ e itera backward-forward até convergência.
    Converge para a solução exata de fluxo de potência em redes radiais.

    Parâmetros
    ----------
    topology : dict com 'buses' e 'lines' no formato do frontend.
    max_iter : número máximo de iterações (padrão 30, geralmente converge em 3-5).
    tol      : critério de parada em ΔV² (padrão 1e-8 pu²).

    Retorna
    -------
    dict com 'converged', 'iterations', 'buses' (id, voltage, angle).
    """
    buses_raw: list[dict] = topology["buses"]
    lines_raw: list[dict] = topology["lines"]

    slack_bus = next((b for b in buses_raw if b["type"] == "slack"), None)
    if slack_bus is None:
        raise ValueError("No slack bus found in the topology.")

    slack_id = int(slack_bus["id"])
    V0 = float(slack_bus.get("voltage", 1.0))
    theta0_deg = float(slack_bus.get("angle", 0.0))
    bus_data = {int(b["id"]): b for b in buses_raw}

    bfs_order, children, parent_info = _build_tree(buses_raw, lines_raw, slack_id)

    # ── Warm start: varredura backward sem perdas (= LinDistFlow 0ª iteração) ──
    P_branch: dict[int, float] = {}
    Q_branch: dict[int, float] = {}
    for node in reversed(bfs_order):
        b = bus_data[node]
        p = float(b.get("pLoad", 0.0)) - float(b.get("pGen", 0.0)) - float(b.get("pGenDG", 0.0))
        q = float(b.get("qLoad", 0.0)) - float(b.get("qGenDG", 0.0))
        p += sum(P_branch[c] for c, _ in children[node])
        q += sum(Q_branch[c] for c, _ in children[node])
        P_branch[node] = p
        Q_branch[node] = q

    # Varredura forward inicial (V² sem perdas)
    V_sq: dict[int, float] = {slack_id: V0 ** 2}
    for node in bfs_order:
        for child, line in children[node]:
            R = float(line["resistance"])
            X = float(line["reactance"])
            V_sq[child] = V_sq[node] - 2.0 * (R * P_branch[child] + X * Q_branch[child])
            V_sq[child] = max(V_sq[child], 1e-6)

    # ── Iterações com perdas ───────────────────────────────────────────────────
    converged = False
    n_iter = 0

    for n_iter in range(1, max_iter + 1):
        V_sq_old = dict(V_sq)

        # Correntes quadráticas ℓ = (P²+Q²)/V² usando estado anterior
        ell: dict[int, float] = {}
        for child_node, (parent_node, _) in parent_info.items():
            V_p = max(V_sq.get(parent_node, 1.0), 1e-9)
            P = P_branch[child_node]
            Q = Q_branch[child_node]
            ell[child_node] = (P * P + Q * Q) / V_p

        # Varredura backward COM perdas (ℓ da iteração anterior)
        for node in reversed(bfs_order):
            if node == slack_id:
                continue
            parent_node, line = parent_info[node]
            R = float(line["resistance"])
            X = float(line["reactance"])
            l = ell.get(node, 0.0)

            b = bus_data[node]
            p = float(b.get("pLoad", 0.0)) - float(b.get("pGen", 0.0)) - float(b.get("pGenDG", 0.0))
            q = float(b.get("qLoad", 0.0)) - float(b.get("qGenDG", 0.0))
            # Fluxos dos filhos (já atualizados nesta varredura, reverse order)
            p += sum(P_branch[c] for c, _ in children[node])
            q += sum(Q_branch[c] for c, _ in children[node])
            # Perdas no ramo pai→node
            p += R * l
            q += X * l

            P_branch[node] = p
            Q_branch[node] = q

        # Varredura forward COM perdas
        for node in bfs_order:
            for child, line in children[node]:
                R = float(line["resistance"])
                X = float(line["reactance"])
                P = P_branch[child]
                Q = Q_branch[child]
                l = ell.get(child, 0.0)
                V_sq[child] = (
                    V_sq[node]
                    - 2.0 * (R * P + X * Q)
                    + (R * R + X * X) * l
                )
                V_sq[child] = max(V_sq[child], 1e-6)

        # Critério de convergência em ΔV²
        max_dv2 = max(abs(V_sq[k] - V_sq_old[k]) for k in V_sq)
        if max_dv2 < tol:
            converged = True
            break

    # ── Ângulos (correção de 1ª ordem pós-convergência) ───────────────────────
    theta_deg: dict[int, float] = {slack_id: theta0_deg}
    for node in bfs_order:
        V_node = math.sqrt(max(V_sq[node], 1e-9))
        for child, line in children[node]:
            R = float(line["resistance"])
            X = float(line["reactance"])
            P = P_branch[child]
            Q = Q_branch[child]
            delta_rad = (X * P - R * Q) / V_node
            theta_deg[child] = theta_deg[node] - math.degrees(delta_rad)

    # ── Resultado: barramentos ──────────────────────────────────────────────
    # pGen/pLoad/qLoad vêm direto da topologia (são entrada conhecida, não
    # calculada). qGen fica em 0 — DistFlow não modela despacho reativo
    # separado de geração; só a injeção líquida entra na varredura.
    buses_out = []
    for b in buses_raw:
        bid = int(b["id"])
        v = math.sqrt(max(V_sq.get(bid, 1.0), 1e-9))
        buses_out.append({
            "id": bid,
            "voltage": round(v, 6),
            "angle": round(theta_deg.get(bid, 0.0), 4),
            "pGen": round(float(b.get("pGen", 0.0)), 5),
            "qGen": 0.0,
            "pLoad": round(float(b.get("pLoad", 0.0)), 5),
            "qLoad": round(float(b.get("qLoad", 0.0)), 5),
            "pGenDG": round(float(b.get("pGenDG", 0.0)), 5),
            "qGenDG": round(float(b.get("qGenDG", 0.0)), 5),
        })

    # ── Resultado: fluxos de linha (para a tabela Branch Flows) ─────────────
    # P_branch[child]/Q_branch[child] já é o fluxo entrando no ramo pai→filho;
    # a perda é R·ℓ (ativa) e X·ℓ (reativa), com ℓ recalculado no estado final.
    lines_out = []
    for child_node, (parent_node, line) in parent_info.items():
        R = float(line["resistance"])
        X = float(line["reactance"])
        V_p = max(V_sq.get(parent_node, 1.0), 1e-9)
        P = P_branch[child_node]
        Q = Q_branch[child_node]
        ell_final = (P * P + Q * Q) / V_p
        loss_p = R * ell_final
        loss_q = X * ell_final
        lines_out.append({
            "id": int(line["id"]),
            "from": parent_node,
            "to": child_node,
            "pFrom": round(P, 5),
            "qFrom": round(Q, 5),
            "pTo": round(P - loss_p, 5),
            "qTo": round(Q - loss_q, 5),
            "loss": round(abs(loss_p), 6),
        })

    return {
        "converged": converged,
        "iterations": n_iter,
        "buses": buses_out,
        "lines": lines_out,
    }


def run_lindistflow(topology: dict[str, Any]) -> dict[str, Any]:
    """LinDistFlow (passo único sem perdas) — mantido para compatibilidade.

    Para comparações precisas use run_distflow() que inclui termos de perda.
    """
    return run_distflow(topology, max_iter=1, tol=0.0)
