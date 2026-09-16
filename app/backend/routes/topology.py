"""Rota /api/topologies — topologias IEEE disponíveis + casos pandapower."""

from __future__ import annotations

import inspect

import numpy as np
from fastapi import APIRouter, HTTPException

router = APIRouter()

# Topologias IEEE em pu (espelha src/lib/topologies.ts do frontend)
TOPOLOGIES = [
    {
        "id": "ieee-5bus",
        "name": "IEEE 5-Bus System",
        "buses": [
            {
                "id": 1,
                "name": "Gen 1",
                "type": "slack",
                "voltage": 1.06,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0,
                "qLoad": 0,
                "geoX": 100,
                "geoY": 300,
            },
            {
                "id": 2,
                "name": "Gen 2",
                "type": "pv",
                "voltage": 1.00,
                "angle": 0,
                "pGen": 0.4,
                "qGen": 0,
                "pLoad": 0.2,
                "qLoad": 0.1,
                "qMin": -0.4,
                "qMax": 0.5,
                "geoX": 350,
                "geoY": 150,
            },
            {
                "id": 3,
                "name": "Gen 3",
                "type": "pv",
                "voltage": 1.00,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.45,
                "qLoad": 0.15,
                "qMin": -0.4,
                "qMax": 0.4,
                "geoX": 600,
                "geoY": 150,
            },
            {
                "id": 4,
                "name": "Load 1",
                "type": "pq",
                "voltage": 1.00,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.4,
                "qLoad": 0.05,
                "geoX": 450,
                "geoY": 400,
            },
            {
                "id": 5,
                "name": "Load 2",
                "type": "pq",
                "voltage": 1.00,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.6,
                "qLoad": 0.1,
                "geoX": 750,
                "geoY": 350,
            },
        ],
        "lines": [
            {
                "id": 1,
                "from_bus": 1,
                "to_bus": 2,
                "resistance": 0.02,
                "reactance": 0.06,
                "susceptance": 0.03,
            },
            {
                "id": 2,
                "from_bus": 1,
                "to_bus": 3,
                "resistance": 0.08,
                "reactance": 0.24,
                "susceptance": 0.025,
            },
            {
                "id": 3,
                "from_bus": 2,
                "to_bus": 3,
                "resistance": 0.06,
                "reactance": 0.18,
                "susceptance": 0.02,
            },
            {
                "id": 4,
                "from_bus": 2,
                "to_bus": 4,
                "resistance": 0.06,
                "reactance": 0.18,
                "susceptance": 0.02,
            },
            {
                "id": 5,
                "from_bus": 2,
                "to_bus": 5,
                "resistance": 0.04,
                "reactance": 0.12,
                "susceptance": 0.015,
            },
            {
                "id": 6,
                "from_bus": 3,
                "to_bus": 4,
                "resistance": 0.01,
                "reactance": 0.03,
                "susceptance": 0.01,
            },
            {
                "id": 7,
                "from_bus": 4,
                "to_bus": 5,
                "resistance": 0.08,
                "reactance": 0.24,
                "susceptance": 0.025,
            },
        ],
    },
    {
        "id": "ieee-14bus",
        "name": "IEEE 14-Bus",
        "buses": [
            {
                "id": 1,
                "name": "Gen 1",
                "type": "slack",
                "voltage": 1.06,
                "angle": 0,
                "pGen": 2.32,
                "qGen": 0,
                "pLoad": 0,
                "qLoad": 0,
                "geoX": 100,
                "geoY": 300,
            },
            {
                "id": 2,
                "name": "Gen 2",
                "type": "pv",
                "voltage": 1.045,
                "angle": 0,
                "pGen": 0.4,
                "qGen": 0,
                "pLoad": 0.217,
                "qLoad": 0.127,
                "qMin": -0.4,
                "qMax": 0.5,
                "geoX": 300,
                "geoY": 150,
            },
            {
                "id": 3,
                "name": "Gen 3",
                "type": "pv",
                "voltage": 1.01,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.942,
                "qLoad": 0.19,
                "qMin": 0,
                "qMax": 0.4,
                "geoX": 550,
                "geoY": 200,
            },
            {
                "id": 4,
                "name": "Bus 4",
                "type": "pq",
                "voltage": 1.0,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.478,
                "qLoad": -0.039,
                "geoX": 200,
                "geoY": 450,
            },
            {
                "id": 5,
                "name": "Bus 5",
                "type": "pq",
                "voltage": 1.0,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.076,
                "qLoad": 0.016,
                "geoX": 350,
                "geoY": 350,
            },
            {
                "id": 6,
                "name": "Gen 6",
                "type": "pv",
                "voltage": 1.07,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.112,
                "qLoad": 0.075,
                "qMin": -0.06,
                "qMax": 0.24,
                "geoX": 500,
                "geoY": 450,
            },
            {
                "id": 7,
                "name": "Bus 7",
                "type": "pq",
                "voltage": 1.0,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0,
                "qLoad": 0,
                "geoX": 300,
                "geoY": 550,
            },
            {
                "id": 8,
                "name": "Gen 8",
                "type": "pv",
                "voltage": 1.09,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0,
                "qLoad": 0,
                "qMin": -0.06,
                "qMax": 0.24,
                "geoX": 450,
                "geoY": 550,
            },
            {
                "id": 9,
                "name": "Bus 9",
                "type": "pq",
                "voltage": 1.0,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.295,
                "qLoad": 0.166,
                "geoX": 650,
                "geoY": 350,
            },
            {
                "id": 10,
                "name": "Bus 10",
                "type": "pq",
                "voltage": 1.0,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.09,
                "qLoad": 0.058,
                "geoX": 700,
                "geoY": 500,
            },
            {
                "id": 11,
                "name": "Bus 11",
                "type": "pq",
                "voltage": 1.0,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.035,
                "qLoad": 0.018,
                "geoX": 500,
                "geoY": 650,
            },
            {
                "id": 12,
                "name": "Bus 12",
                "type": "pq",
                "voltage": 1.0,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.061,
                "qLoad": 0.016,
                "geoX": 600,
                "geoY": 550,
            },
            {
                "id": 13,
                "name": "Bus 13",
                "type": "pq",
                "voltage": 1.0,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.135,
                "qLoad": 0.058,
                "geoX": 700,
                "geoY": 650,
            },
            {
                "id": 14,
                "name": "Bus 14",
                "type": "pq",
                "voltage": 1.0,
                "angle": 0,
                "pGen": 0,
                "qGen": 0,
                "pLoad": 0.149,
                "qLoad": 0.05,
                "geoX": 800,
                "geoY": 500,
            },
        ],
        "lines": [
            {
                "id": 1,
                "from_bus": 1,
                "to_bus": 2,
                "resistance": 0.01938,
                "reactance": 0.05917,
                "susceptance": 0.0528,
            },
            {
                "id": 2,
                "from_bus": 1,
                "to_bus": 5,
                "resistance": 0.05403,
                "reactance": 0.22304,
                "susceptance": 0.0492,
            },
            {
                "id": 3,
                "from_bus": 2,
                "to_bus": 3,
                "resistance": 0.04699,
                "reactance": 0.19797,
                "susceptance": 0.0438,
            },
            {
                "id": 4,
                "from_bus": 2,
                "to_bus": 4,
                "resistance": 0.05811,
                "reactance": 0.17632,
                "susceptance": 0.034,
            },
            {
                "id": 5,
                "from_bus": 2,
                "to_bus": 5,
                "resistance": 0.05695,
                "reactance": 0.17388,
                "susceptance": 0.0346,
            },
            {
                "id": 6,
                "from_bus": 3,
                "to_bus": 4,
                "resistance": 0.06701,
                "reactance": 0.17103,
                "susceptance": 0.0128,
            },
            {
                "id": 7,
                "from_bus": 4,
                "to_bus": 5,
                "resistance": 0.01335,
                "reactance": 0.04211,
                "susceptance": 0,
            },
            {
                "id": 8,
                "from_bus": 4,
                "to_bus": 7,
                "resistance": 0,
                "reactance": 0.20912,
                "susceptance": 0,
            },
            {
                "id": 9,
                "from_bus": 4,
                "to_bus": 9,
                "resistance": 0,
                "reactance": 0.55618,
                "susceptance": 0,
            },
            {
                "id": 10,
                "from_bus": 5,
                "to_bus": 6,
                "resistance": 0,
                "reactance": 0.25202,
                "susceptance": 0,
            },
            {
                "id": 11,
                "from_bus": 6,
                "to_bus": 11,
                "resistance": 0.09498,
                "reactance": 0.1989,
                "susceptance": 0,
            },
            {
                "id": 12,
                "from_bus": 6,
                "to_bus": 12,
                "resistance": 0.12291,
                "reactance": 0.25581,
                "susceptance": 0,
            },
            {
                "id": 13,
                "from_bus": 6,
                "to_bus": 13,
                "resistance": 0.06615,
                "reactance": 0.13027,
                "susceptance": 0,
            },
            {
                "id": 14,
                "from_bus": 7,
                "to_bus": 8,
                "resistance": 0,
                "reactance": 0.17615,
                "susceptance": 0,
            },
            {
                "id": 15,
                "from_bus": 7,
                "to_bus": 9,
                "resistance": 0,
                "reactance": 0.11001,
                "susceptance": 0,
            },
            {
                "id": 16,
                "from_bus": 9,
                "to_bus": 10,
                "resistance": 0.03181,
                "reactance": 0.0845,
                "susceptance": 0,
            },
            {
                "id": 17,
                "from_bus": 9,
                "to_bus": 14,
                "resistance": 0.12711,
                "reactance": 0.27038,
                "susceptance": 0,
            },
            {
                "id": 18,
                "from_bus": 10,
                "to_bus": 11,
                "resistance": 0.08205,
                "reactance": 0.19207,
                "susceptance": 0,
            },
            {
                "id": 19,
                "from_bus": 12,
                "to_bus": 13,
                "resistance": 0.22092,
                "reactance": 0.19988,
                "susceptance": 0,
            },
            {
                "id": 20,
                "from_bus": 13,
                "to_bus": 14,
                "resistance": 0.17093,
                "reactance": 0.34802,
                "susceptance": 0,
            },
        ],
    },
]

TOPOLOGY_MAP = {t["id"]: t for t in TOPOLOGIES}


@router.get("/")
def list_topologies() -> list[dict]:
    """Lista topologias disponíveis (sem dados completos)."""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "n_buses": len(t["buses"]),
            "n_lines": len(t["lines"]),
        }
        for t in TOPOLOGIES
    ]


@router.get("/{topology_id}")
def get_topology(topology_id: str) -> dict:
    """Retorna topologia completa por ID."""
    if topology_id not in TOPOLOGY_MAP:
        raise HTTPException(
            status_code=404, detail=f"Topology '{topology_id}' not found."
        )
    return TOPOLOGY_MAP[topology_id]


# ─── Pandapower built-in cases ────────────────────────────────────────────────

# Named (non-"case*") network generators in pandapower.networks that take no
# required arguments — mostly distribution (LV/MV) feeders that the default
# case*-only discovery misses entirely. Curated by hand instead of blind
# introspection because pandapower.networks also exports generic element
# builders (create_bus, create_line, ...) that aren't network generators.
_EXTRA_PP_NETWORKS = [
    "GBnetwork",
    "GBreducednetwork",
    "create_cigre_network_hv",
    "create_cigre_network_lv",
    "create_cigre_network_mv",
    "create_dickert_lv_network",
    "create_kerber_dorfnetz",
    "create_kerber_landnetz_freileitung_1",
    "create_kerber_landnetz_freileitung_2",
    "create_kerber_landnetz_kabel_1",
    "create_kerber_landnetz_kabel_2",
    "create_kerber_vorstadtnetz_kabel_1",
    "create_kerber_vorstadtnetz_kabel_2",
    "create_synthetic_voltage_control_lv_network",
    "example_multivoltage",
    "example_simple",
    "four_loads_with_branches_out",
    "iceland",
    "ieee_european_lv_asymmetric",
    "kb_extrem_dorfnetz",
    "kb_extrem_dorfnetz_trafo",
    "kb_extrem_landnetz_freileitung",
    "kb_extrem_landnetz_freileitung_trafo",
    "kb_extrem_landnetz_kabel",
    "kb_extrem_landnetz_kabel_trafo",
    "kb_extrem_vorstadtnetz_1",
    "kb_extrem_vorstadtnetz_2",
    "kb_extrem_vorstadtnetz_trafo_1",
    "kb_extrem_vorstadtnetz_trafo_2",
    "lv_schutterwald",
    "mv_oberrhein",
    "panda_four_load_branch",
    "simple_four_bus_system",
    "simple_mv_open_ring_net",
]


def _pp_case_names() -> list[str]:
    import pandapower.networks as pn

    case_fns = {
        name
        for name, obj in inspect.getmembers(pn, inspect.isfunction)
        if name.startswith("case")
    }
    extra_fns = {name for name in _EXTRA_PP_NETWORKS if hasattr(pn, name)}
    return sorted(case_fns | extra_fns)


# Voltage-class census (2026-07-02): computed once by instantiating every case
# and checking dominant bus vn_kv — hardcoded here instead of at request time
# because some cases (case9241pegase, the *rte ones) take seconds to build,
# and /pandapower/list has to stay instant for the dropdown. These are static
# reference networks; the classification doesn't change.
#
# Everything not listed here defaults to "transmission" below — that covers
# every "case*" except case33bw, plus GBnetwork/GBreducednetwork/
# create_cigre_network_hv/iceland/example_multivoltage (all HV-dominant).
_PP_VOLTAGE_CLASS_OVERRIDES: dict[str, str] = {
    # Distribution (MV) — 1kV < dominant vn_kv <= 35kV
    "case33bw": "distribution",
    "create_cigre_network_mv": "distribution",
    "simple_mv_open_ring_net": "distribution",
    "mv_oberrhein": "distribution",
    "example_simple": "distribution",
    # LV (BT) — dominant vn_kv <= 1kV
    "create_cigre_network_lv": "lv",
    "lv_schutterwald": "lv",
    "create_dickert_lv_network": "lv",
    "create_kerber_dorfnetz": "lv",
    "create_kerber_landnetz_freileitung_1": "lv",
    "create_kerber_landnetz_freileitung_2": "lv",
    "create_kerber_landnetz_kabel_1": "lv",
    "create_kerber_landnetz_kabel_2": "lv",
    "create_kerber_vorstadtnetz_kabel_1": "lv",
    "create_kerber_vorstadtnetz_kabel_2": "lv",
    "create_synthetic_voltage_control_lv_network": "lv",
    "four_loads_with_branches_out": "lv",
    "ieee_european_lv_asymmetric": "lv",
    "kb_extrem_dorfnetz": "lv",
    "kb_extrem_dorfnetz_trafo": "lv",
    "kb_extrem_landnetz_freileitung": "lv",
    "kb_extrem_landnetz_freileitung_trafo": "lv",
    "kb_extrem_landnetz_kabel": "lv",
    "kb_extrem_landnetz_kabel_trafo": "lv",
    "kb_extrem_vorstadtnetz_1": "lv",
    "kb_extrem_vorstadtnetz_2": "lv",
    "kb_extrem_vorstadtnetz_trafo_1": "lv",
    "kb_extrem_vorstadtnetz_trafo_2": "lv",
    "panda_four_load_branch": "lv",
    "simple_four_bus_system": "lv",
}


def _pp_voltage_class(name: str) -> str:
    return _PP_VOLTAGE_CLASS_OVERRIDES.get(name, "transmission")


@router.get("/pandapower/list")
def list_pandapower_cases() -> list[dict]:
    """List pandapower.networks cases by name, with a static voltage-class tag.

    Metadata beyond name/voltageClass is loaded only when the user selects a
    case. Some pandapower cases are expensive to instantiate, so the list
    endpoint must stay lightweight.
    """
    return [
        {"name": name, "voltageClass": _pp_voltage_class(name)}
        for name in _pp_case_names()
    ]


@router.get("/pandapower/{case_name}")
def load_pandapower_case(case_name: str) -> dict:
    """
    Carrega um caso pandapower e converte para o formato Topology do frontend.

    Valores em per-unit no base do próprio caso (sn_mva, vn_kv da barra).
    Transformadores são incluídos como linhas (reatância de curto-circuito pu).
    """
    import pandapower.networks as pn

    if case_name not in _pp_case_names():
        raise HTTPException(
            status_code=404,
            detail=f"Case '{case_name}' not found in pandapower.networks",
        )

    net = getattr(pn, case_name)()
    sn_mva = float(net.sn_mva)
    freq_hz = float(getattr(net, "f_hz", 50.0))

    # Filtra elementos out-of-service em todas as tabelas (backup/tie-switches
    # abertas, equipamento reserva). pandapower mantém essas linhas no
    # DataFrame mesmo desligadas — ex. case33bw tem 5 de 37 linhas com
    # in_service=False (as chaves de interligação do alimentador radial
    # reconfigurável); incluí-las faria a rede parecer malhada quando na
    # operação normal ela é radial.
    bus_df = (
        net.bus[net.bus["in_service"]] if "in_service" in net.bus.columns else net.bus
    )
    line_df = (
        net.line[net.line["in_service"]]
        if "in_service" in net.line.columns
        else net.line
    )
    load_df = (
        net.load[net.load["in_service"]]
        if "in_service" in net.load.columns
        else net.load
    )
    gen_df = (
        net.gen[net.gen["in_service"]] if "in_service" in net.gen.columns else net.gen
    )
    ext_grid_df = (
        net.ext_grid[net.ext_grid["in_service"]]
        if "in_service" in net.ext_grid.columns
        else net.ext_grid
    )
    trafo_df = (
        net.trafo[net.trafo["in_service"]]
        if "in_service" in net.trafo.columns
        else net.trafo
    )
    sgen_df = (
        net.sgen[net.sgen["in_service"]]
        if "in_service" in net.sgen.columns
        else net.sgen
    )

    # Segunda forma de "desligado" no pandapower: uma chave em net.switch com
    # closed=False, presa a UM lado de uma linha/trafo específica (não à linha
    # inteira via in_service). É assim que redes MT reais representam pontos
    # normalmente abertos — ex. create_cigre_network_mv, mv_oberrhein e
    # simple_mv_open_ring_net não usam in_service=False em nada, usam isso.
    # Sem tratar isso, essas redes MT genuinamente radiais apareciam como
    # malhadas.
    line_switch_open: set[int] = set()
    trafo_switch_open: set[int] = set()
    switch_df = getattr(net, "switch", None)
    if switch_df is not None and len(switch_df) > 0 and "closed" in switch_df.columns:
        open_sw = switch_df[~switch_df["closed"]]
        line_switch_open = set(
            int(e) for e in open_sw.loc[open_sw["et"] == "l", "element"]
        )
        trafo_switch_open = set(
            int(e) for e in open_sw.loc[open_sw["et"] == "t", "element"]
        )
        # et == 'b' (chave bus-bus) ainda não é suportado — ver DESIGN_SYSTEM.md.

    if line_switch_open:
        line_df = line_df[~line_df.index.isin(line_switch_open)]
    if trafo_switch_open:
        trafo_df = trafo_df[~trafo_df.index.isin(trafo_switch_open)]

    kept_bus_idx = set(int(b) for b in bus_df.index)

    # --- Classificação de barras ---
    slack_buses = set(int(b) for b in ext_grid_df["bus"]) & kept_bus_idx
    gen_buses = (
        (set(int(b) for b in gen_df["bus"]) & kept_bus_idx)
        if len(gen_df) > 0
        else set()
    )

    # Cargas agregadas por barra (convertidas para pu)
    load_p: dict[int, float] = {}
    load_q: dict[int, float] = {}
    for _, row in load_df.iterrows():
        b = int(row.bus)
        if b not in kept_bus_idx:
            continue
        load_p[b] = load_p.get(b, 0.0) + float(row.p_mw) / sn_mva
        load_q[b] = load_q.get(b, 0.0) + float(row.q_mvar) / sn_mva

    # sgen agregado por barra — geração distribuída/renovável: PQ fixo, NÃO
    # controla tensão (ao contrário de `gen`, por isso fica separado de
    # gen_p/gen_vm e nunca vira barra "pv"). Campo próprio (pGenDG/qGenDG)
    # em vez de somar em pGen ou virar carga negativa, pra ficar visível na
    # legenda da Topology em vez de desaparecer dentro de outro número.
    dg_p: dict[int, float] = {}
    dg_q: dict[int, float] = {}
    for _, row in sgen_df.iterrows():
        b = int(row.bus)
        if b not in kept_bus_idx:
            continue
        dg_p[b] = dg_p.get(b, 0.0) + float(row.p_mw) / sn_mva
        dg_q[b] = dg_q.get(b, 0.0) + float(row.q_mvar) / sn_mva

    # Geração por barra
    gen_p: dict[int, float] = {}
    gen_vm: dict[int, float] = {}
    for _, row in gen_df.iterrows():
        b = int(row.bus)
        if b not in kept_bus_idx:
            continue
        gen_p[b] = gen_p.get(b, 0.0) + float(row.p_mw) / sn_mva
        gen_vm[b] = float(row.vm_pu)

    # --- Barras ---
    pp_idx_to_id: dict[int, int] = {}
    buses_out = []
    for seq_id, pp_idx in enumerate(bus_df.index, start=1):
        pp_idx_to_id[int(pp_idx)] = seq_id
        b = int(pp_idx)

        if b in slack_buses:
            bus_type = "slack"
            eg = net.ext_grid[net.ext_grid.bus == b].iloc[0]
            vm = float(eg.vm_pu)
            va = 0.0
        elif b in gen_buses:
            bus_type = "pv"
            vm = gen_vm.get(b, 1.0)
            va = 0.0
        else:
            bus_type = "pq"
            # V/θ de um barramento PQ são incógnitas do power flow, não entrada —
            # flat start (1 pu, 0°); ver isBusFieldEditable() no frontend.
            vm = 1.0
            va = 0.0

        buses_out.append(
            {
                "id": seq_id,
                "name": str(net.bus.at[pp_idx, "name"] or f"Bus {pp_idx}"),
                "type": bus_type,
                "voltage": round(vm, 5),
                "angle": round(va, 4),
                "pGen": round(gen_p.get(b, 0.0), 5),
                "qGen": 0.0,
                "pLoad": round(load_p.get(b, 0.0), 5),
                "qLoad": round(load_q.get(b, 0.0), 5),
                "pGenDG": round(dg_p.get(b, 0.0), 5),
                "qGenDG": round(dg_q.get(b, 0.0), 5),
            }
        )

    # --- Linhas ---
    lines_out = []
    seq = 1
    for _, row in line_df.iterrows():
        fb = int(row.from_bus)
        tb = int(row.to_bus)
        if fb not in kept_bus_idx or tb not in kept_bus_idx:
            continue
        vn_kv = float(net.bus.at[fb, "vn_kv"])
        z_base = vn_kv**2 / sn_mva  # ohms
        r_pu = float(row.r_ohm_per_km) * float(row.length_km) / z_base
        x_pu = float(row.x_ohm_per_km) * float(row.length_km) / z_base
        c_nf = float(row.c_nf_per_km) * float(row.length_km)
        # net.f_hz, not hardcoded 50 — case5 (PJM) is 60 Hz. Getting this
        # wrong doesn't break DC/P-balance at all (only shows up as Q_inj/
        # Q_branch being off by a few percent on an AC solve), so it's easy
        # to miss — found by comparing this app's AC ground truth against
        # 5_BUS_IEEE_bad_data_analytics.ipynb's pn.case5() solved directly.
        b_pu = c_nf * 1e-9 * 2 * np.pi * freq_hz * z_base
        lines_out.append(
            {
                "id": seq,
                "from": pp_idx_to_id[fb],
                "to": pp_idx_to_id[tb],
                "resistance": round(r_pu, 7),
                "reactance": round(max(x_pu, 1e-7), 7),
                "susceptance": round(b_pu, 7),
            }
        )
        seq += 1

    # --- Transformadores como linhas (reatância de curto-circuito) ---
    for _, row in trafo_df.iterrows():
        hv = int(row.hv_bus)
        lv = int(row.lv_bus)
        if hv not in kept_bus_idx or lv not in kept_bus_idx:
            continue
        sn_t = float(row.sn_mva)
        vk = float(row.vk_percent) / 100.0
        vkr = (
            float(row.get("vkr_percent", 0.0)) / 100.0
            if "vkr_percent" in row.index
            else 0.0
        )
        z_pu = vk * sn_mva / sn_t
        r_pu = vkr * sn_mva / sn_t
        x_pu = float(np.sqrt(max(z_pu**2 - r_pu**2, 0.0)))
        lines_out.append(
            {
                "id": seq,
                "from": pp_idx_to_id[hv],
                "to": pp_idx_to_id[lv],
                "resistance": round(r_pu, 7),
                "reactance": round(max(x_pu, 1e-6), 7),
                "susceptance": 0.0,
            }
        )
        seq += 1

    # --- Todos os switches (normalmente abertos E fechados) ---
    # Exportamos TODOS os switches:
    # 1. Switches explícitos de net.switch (com estado closed real de net.switch).
    # 2. Todas as demais linhas e trafos da rede não cobertos por net.switch
    #    (com closed=True se in_service, ou closed=False se tie-lines/out-of-service).
    # Isso permite reconfiguração completa de alimentadores (ex: case33bw, IEEE 33-bus)
    # onde o usuário fecha uma tie-line e abre qualquer um dos ramos fechados para
    # manter a rede radial.
    line_param: dict[int, dict] = {}
    for _, row in net.line.iterrows():
        fb = int(row.from_bus)
        tb = int(row.to_bus)
        if fb not in kept_bus_idx or tb not in kept_bus_idx:
            continue
        vn_kv = float(net.bus.at[fb, "vn_kv"])
        z_base = vn_kv**2 / sn_mva
        r = float(row.r_ohm_per_km) * float(row.length_km) / z_base
        x = float(row.x_ohm_per_km) * float(row.length_km) / z_base
        c_nf = float(row.c_nf_per_km) * float(row.length_km)
        b = c_nf * 1e-9 * 2 * np.pi * freq_hz * z_base
        line_param[int(row.name)] = {
            "r_pu": round(r, 7),
            "x_pu": round(max(x, 1e-7), 7),
            "b_pu": round(b, 7),
        }

    trafo_param: dict[int, dict] = {}
    for _, row in net.trafo.iterrows():
        hv = int(row.hv_bus)
        lv = int(row.lv_bus)
        if hv not in kept_bus_idx or lv not in kept_bus_idx:
            continue
        sn_t = float(row.sn_mva)
        vk = float(row.vk_percent) / 100.0
        vkr = (
            float(row.get("vkr_percent", 0.0)) / 100.0
            if "vkr_percent" in row.index
            else 0.0
        )
        z_pu = vk * sn_mva / sn_t
        r_pu = vkr * sn_mva / sn_t
        x_pu = float(np.sqrt(max(z_pu**2 - r_pu**2, 0.0)))
        trafo_param[int(row.name)] = {
            "r_pu": round(r_pu, 7),
            "x_pu": round(max(x_pu, 1e-6), 7),
            "b_pu": 0.0,
        }

    all_switches: list[dict] = []
    sw_seq = 1
    covered_lines: set[int] = set()
    covered_trafos: set[int] = set()

    if switch_df is not None and len(switch_df) > 0:
        for sw_idx, sw_row in switch_df.iterrows():
            et = str(sw_row.get("et", ""))
            if et not in ("l", "t"):
                continue
            elem = int(sw_row["element"])
            closed = bool(sw_row["closed"])

            if et == "l":
                if elem not in net.line.index:
                    continue
                line_row = net.line.loc[elem]
                fb = int(line_row.from_bus)
                tb = int(line_row.to_bus)
                params = line_param.get(elem, {})
                covered_lines.add(elem)
            else:  # 't'
                if elem not in net.trafo.index:
                    continue
                tr_row = net.trafo.loc[elem]
                fb = int(tr_row.hv_bus)
                tb = int(tr_row.lv_bus)
                params = trafo_param.get(elem, {})
                covered_trafos.add(elem)

            if fb not in kept_bus_idx or tb not in kept_bus_idx:
                continue

            entry: dict = {
                "id": sw_seq,
                "from": pp_idx_to_id[fb],
                "to": pp_idx_to_id[tb],
                "name": str(sw_row.get("name") or f"SW {sw_seq}"),
                "closed": closed,
            }
            entry.update(params)
            all_switches.append(entry)
            sw_seq += 1

    # Demais linhas não presentes em net.switch (chaves seccionadoras / tie-lines)
    for elem, row in net.line.iterrows():
        elem_int = int(elem)
        if elem_int in covered_lines:
            continue
        fb = int(row.from_bus)
        tb = int(row.to_bus)
        if fb not in kept_bus_idx or tb not in kept_bus_idx:
            continue
        in_svc = bool(row.in_service) if "in_service" in row else True
        if elem_int in line_switch_open:
            in_svc = False
        name = str(row.get("name") or f"L{pp_idx_to_id[fb]}↔{pp_idx_to_id[tb]}")
        all_switches.append(
            {
                "id": sw_seq,
                "from": pp_idx_to_id[fb],
                "to": pp_idx_to_id[tb],
                "name": name,
                "closed": in_svc,
                **line_param.get(elem_int, {}),
            }
        )
        sw_seq += 1

    # Demais trafos não presentes em net.switch
    for elem, row in net.trafo.iterrows():
        elem_int = int(elem)
        if elem_int in covered_trafos:
            continue
        hv = int(row.hv_bus)
        lv = int(row.lv_bus)
        if hv not in kept_bus_idx or lv not in kept_bus_idx:
            continue
        in_svc = bool(row.in_service) if "in_service" in row else True
        if elem_int in trafo_switch_open:
            in_svc = False
        name = str(row.get("name") or f"T{pp_idx_to_id[hv]}↔{pp_idx_to_id[lv]}")
        all_switches.append(
            {
                "id": sw_seq,
                "from": pp_idx_to_id[hv],
                "to": pp_idx_to_id[lv],
                "name": name,
                "closed": in_svc,
                **trafo_param.get(elem_int, {}),
            }
        )
        sw_seq += 1

    # Retrocompatibilidade: openSwitches (só os abertos)
    open_switches_compat = [s for s in all_switches if not s["closed"]]

    return {
        "id": f"pp_{case_name}",
        "name": f"pandapower · {case_name}  (base {sn_mva:.0f} MVA)",
        "buses": buses_out,
        "lines": lines_out,
        "switches": all_switches,
        "openSwitches": open_switches_compat,
        "frequency_hz": freq_hz,
        "meta": {
            "source": "pandapower",
            "case_name": case_name,
            "sn_mva": sn_mva,
        },
    }
