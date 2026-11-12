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
            # Barra PV com P = 0 continua controlando tensao: e o compensador
            # sincrono (barras 3, 6 e 8 do IEEE 14). Exigir pGen > 0 aqui
            # transformava essas barras em PQ e derrubava |V| (0,92-0,96 pu
            # contra 1,01-1,09 do case14), ver decisoes_tecnicas.md 03/11/2026.
            pp.create_gen(
                net,
                bus=pp_bus,
                p_mw=float(b.get("pGen", 0.0)) * BASE_MVA,
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

        p_sh = float(b.get("pShunt", 0.0) or 0.0)
        q_sh = float(b.get("qShunt", 0.0) or 0.0)
        if p_sh != 0.0 or q_sh != 0.0:
            pp.create_shunt(net, bus=pp_bus, p_mw=p_sh * BASE_MVA, q_mvar=q_sh * BASE_MVA, name=f"shunt_{b['name']}")

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

    meter_kind = {m["lineId"]: m["kind"] for m in (topology.get("line_measurements") or [])}
    for line in lines:
        from_id = line.get("from_bus", line.get("from"))
        to_id = line.get("to_bus", line.get("to"))
        from_pp = bus_id_map[from_id]
        to_pp = bus_id_map[to_id]
        r_pu = float(line["resistance"])
        x_pu = float(line["reactance"])

        if is_trafo_branch(line):
            # Trafo com relacao fora do nominal (BUG-011): tap no lado "from"
            # (convencao MATPOWER), impedancia no lado "to". Com vn = 1 nas duas
            # barras e no trafo, o tap_pos +-1 com passo |tap - 1| da a relacao.
            # O id do frontend e o medidor configurado vao junto, para quem le
            # o net (medicoes, resultados) mapear sem a topologia.
            tap = float(line["tapRatio"])
            t = pp.create_transformer_from_parameters(
                net,
                hv_bus=from_pp,
                lv_bus=to_pp,
                sn_mva=BASE_MVA,
                vn_hv_kv=BASE_KV,
                vn_lv_kv=BASE_KV,
                vkr_percent=r_pu * 100.0,
                vk_percent=math.hypot(r_pu, max(x_pu, 1e-6)) * 100.0,
                pfe_kw=0.0,
                i0_percent=0.0,
                shift_degree=0.0,
                tap_side="hv",
                tap_neutral=0,
                tap_min=-1,
                tap_max=1,
                tap_pos=1 if tap > 1.0 else -1,
                tap_step_percent=abs(tap - 1.0) * 100.0,
                tap_changer_type="Ratio",  # pandapower 3: sem isso o tap e ignorado (TAP = 1 no ppc)
                name=f"L{line['id']}",
            )
            net.trafo.at[t, "frontend_id"] = int(line["id"])
            net.trafo.at[t, "meter_kind"] = meter_kind.get(line["id"])
            continue
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


def is_trafo_branch(line: dict[str, Any]) -> bool:
    """Ramo que `build_net_from_frontend` monta como trafo: `tapRatio` presente
    e diferente de 1. Trafo nominal fica linha (fisica identica, e assim
    continua valendo para ataque de parametro, biblioteca do GLRT etc.)."""
    tap = line.get("tapRatio")
    return tap is not None and abs(float(tap) - 1.0) > 1e-9


def line_id_map_from_topology(topology: dict[str, Any]) -> dict[int, int]:
    """Frontend line id -> pandapower line index (so ramos que viram LINHA).

    Não vem de `build_net_from_frontend()` (que só retorna `bus_id_map`) para
    não mudar a assinatura usada em ~12 call sites — em vez disso, deriva do
    mesmo laço de `build_net_from_frontend`, que insere as linhas na ordem de
    `topology["lines"]` pulando só os trafos (`is_trafo_branch`). O índice
    pandapower de cada linha é a posição dela entre os ramos que não são
    trafo. Ramo-trafo não está neste mapa: o id do frontend dele fica em
    `net.trafo["frontend_id"]`. Se o laço de criação mudar, esta função muda junto.
    """
    linhas = [line for line in topology["lines"] if not is_trafo_branch(line)]
    return {int(line["id"]): pp_idx for pp_idx, line in enumerate(linhas)}


def trafo_frontend_ids(net: Any) -> dict[int, int]:
    """pp trafo index -> frontend line id, para trafos montados por
    `build_net_from_frontend` (vazio para redes sem trafo)."""
    if len(net.trafo) == 0 or "frontend_id" not in net.trafo.columns:
        return {}
    return {int(t): int(f) for t, f in net.trafo["frontend_id"].items() if f == f}
