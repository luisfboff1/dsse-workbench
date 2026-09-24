"""Constrói redes pandapower a partir do JSON de topologia do frontend.

Convencao de unidades:
- Todos os valores do frontend estão em per-unit (base MVA = 1, base kV = 1).
- Com base_mva=1 e vn_kv=1, z_base = vn_kv^2 / base_mva = 1 Ω,
  logo R(pu) == R(Ω) e P(pu) == P(MW). Nenhuma conversao necessaria.
"""

from __future__ import annotations

import math
from typing import Any

import pandapower as pp

BASE_MVA = 1.0
BASE_KV = 1.0  # vn_kv em pu
FREQUENCY_HZ = 50.0


def build_net_from_frontend(topology: dict[str, Any]) -> tuple[Any, dict[int, int]]:
    """Constrói pandapower net a partir de topology dict do frontend.

    Retorna ``(net, bus_id_map)`` onde ``bus_id_map[frontend_id] = pp_bus_idx``.
    """
    buses: list[dict] = topology["buses"]
    lines: list[dict] = topology["lines"]
    freq_hz = float(topology.get("frequency_hz", FREQUENCY_HZ))

    net = pp.create_empty_network(sn_mva=BASE_MVA, f_hz=freq_hz)
    bus_id_map: dict[int, int] = {}

    for b in buses:
        pp_bus = pp.create_bus(net, vn_kv=BASE_KV, name=b["name"])
        bus_id_map[b["id"]] = pp_bus

        if b["type"] == "slack":
            pp.create_ext_grid(
                net,
                bus=pp_bus,
                vm_pu=float(b.get("voltage", 1.0)),
                va_degree=float(b.get("angle", 0.0)),
                name=b["name"],
            )
        elif b["type"] == "pv":
            p_gen = float(b.get("pGen", 0.0))
            if p_gen > 0:
                pp.create_gen(
                    net,
                    bus=pp_bus,
                    p_mw=p_gen * BASE_MVA,
                    vm_pu=float(b.get("voltage", 1.0)),
                    name=b["name"],
                    min_q_mvar=float(b.get("qMin", -0.3)) * BASE_MVA,
                    max_q_mvar=float(b.get("qMax", 0.3)) * BASE_MVA,
                )

        p_load = float(b.get("pLoad", 0.0))
        q_load = float(b.get("qLoad", 0.0))
        if p_load != 0.0 or q_load != 0.0:
            pp.create_load(
                net,
                bus=pp_bus,
                p_mw=p_load * BASE_MVA,
                q_mvar=q_load * BASE_MVA,
                name=f"load_{b['name']}",
            )

        p_gen_dg = float(b.get("pGenDG", 0.0))
        q_gen_dg = float(b.get("qGenDG", 0.0))
        if p_gen_dg != 0.0 or q_gen_dg != 0.0:
            pp.create_sgen(
                net,
                bus=pp_bus,
                p_mw=p_gen_dg * BASE_MVA,
                q_mvar=q_gen_dg * BASE_MVA,
                name=f"sgen_{b['name']}",
            )

    for line in lines:
        from_id = line.get("from_bus", line.get("from"))
        to_id = line.get("to_bus", line.get("to"))
        from_pp = bus_id_map[from_id]
        to_pp = bus_id_map[to_id]
        r_pu = float(line["resistance"])
        x_pu = float(line["reactance"])
        # Inverse of load_pandapower_case()'s b_pu = c_nf*1e-9*2*pi*f*z_base
        # (topology.py) — with z_base=1 and length_km=1 here (same pu
        # convention as r/x above), c_nf_per_km = b_pu / (1e-9*2*pi*f). Uses
        # the topology's own frequency_hz (case5/PJM is 60 Hz, not every
        # pandapower case is 50) — using the wrong one here doesn't break P
        # balance, only skews Q_inj/Q_branch by a few percent on an AC solve.
        b_pu = float(line.get("susceptance", 0.0))
        c_nf_per_km = b_pu / (1e-9 * 2.0 * math.pi * freq_hz) if b_pu else 0.0

        pp.create_line_from_parameters(
            net,
            from_bus=from_pp,
            to_bus=to_pp,
            length_km=1.0,
            r_ohm_per_km=r_pu,  # z_base = 1, logo pu == Ω
            x_ohm_per_km=max(x_pu, 1e-6),
            c_nf_per_km=c_nf_per_km,
            max_i_ka=10.0,
            name=f"L{line['id']}",
        )

    return net, bus_id_map


def line_id_map_from_topology(topology: dict[str, Any]) -> dict[int, int]:
    """Frontend line id -> pandapower line index.

    Não vem de `build_net_from_frontend()` (que só retorna `bus_id_map`) para
    não mudar a assinatura usada em ~12 call sites — em vez disso, deriva do
    mesmo laço `for line in lines: pp.create_line_from_parameters(...)`
    acima, que insere as linhas em `topology["lines"]` ordem sem filtrar
    nada, então o índice pandapower de cada linha é sempre a posição dela
    nessa lista (0, 1, 2, ...). Se essa função de criação de linhas mudar
    (passar a pular/filtrar linhas), esta função precisa mudar junto.
    """
    return {int(line["id"]): pp_idx for pp_idx, line in enumerate(topology["lines"])}
