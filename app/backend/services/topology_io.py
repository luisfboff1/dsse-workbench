"""Importação e Exportação de Topologias.

Este módulo lida com leitura e escrita de diversos formatos de rede,
sempre usando o formato Topology JSON do frontend como modelo pivô.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

if TYPE_CHECKING:
    import pandapower as pp


def get_import_formats() -> list[dict]:
    """Lista formatos de importação suportados."""
    return [
        {"id": "workbench_json", "name": "DSSE Workbench JSON", "ext": ".json"},
        {
            "id": "roseau_json",
            "name": "French HTA Feeder (Roseau Load Flow)",
            "ext": ".json",
        },
        {"id": "pandapower_json", "name": "pandapower JSON", "ext": ".json"},
        {"id": "pandapower_excel", "name": "pandapower Excel", "ext": ".xlsx"},
        {
            "id": "ieee_excel",
            "name": "IEEE Tabular Benchmark (Bus/Line)",
            "ext": ".xlsx",
        },
        {"id": "matpower", "name": "MATPOWER", "ext": ".m, .mat"},
        {"id": "opendss", "name": "OpenDSS", "ext": ".dss, .zip"},
        {"id": "cim", "name": "CIM CGMES", "ext": ".xml, .zip"},
        {"id": "ucte", "name": "UCTE DEF", "ext": ".ucte"},
        {"id": "csv", "name": "CSV (ZIP/Single)", "ext": ".csv, .zip"},
        {"id": "geojson", "name": "GeoJSON", "ext": ".geojson, .json"},
        {"id": "graphml", "name": "GraphML", "ext": ".graphml, .xml"},
    ]


def get_export_formats() -> list[dict]:
    """Lista formatos de exportação suportados."""
    return [
        {"id": "workbench_json", "name": "DSSE Workbench JSON", "ext": ".json"},
        {"id": "pandapower_json", "name": "pandapower JSON", "ext": ".json"},
        {"id": "pandapower_excel", "name": "pandapower Excel", "ext": ".xlsx"},
        {"id": "csv", "name": "CSV (ZIP)", "ext": ".zip"},
        {"id": "graphml", "name": "GraphML", "ext": ".graphml"},
    ]


def get_csv_template() -> tuple[bytes, str, str]:
    """Gera um ZIP com templates CSV vazios (headers + 1 exemplo)."""
    import pandas as pd

    buses_df = pd.DataFrame(
        [
            {
                "bus_id": 1,
                "name": "Bus 1",
                "type": "slack",
                "vn_kv": 1.0,
                "vm_pu": 1.0,
                "pd_mw": 0.0,
                "qd_mvar": 0.0,
                "pg_mw": 0.0,
                "x_coord": 0.0,
                "y_coord": 0.0,
            },
            {
                "bus_id": 2,
                "name": "Bus 2",
                "type": "pq",
                "vn_kv": 1.0,
                "vm_pu": 1.0,
                "pd_mw": 0.5,
                "qd_mvar": 0.2,
                "pg_mw": 0.0,
                "x_coord": 1.0,
                "y_coord": 1.0,
            },
        ]
    )

    lines_df = pd.DataFrame(
        [
            {
                "from_bus": 1,
                "to_bus": 2,
                "r_ohm_per_km": 0.01,
                "x_ohm_per_km": 0.05,
                "length_km": 1.0,
                "c_nf_per_km": 10.0,
                "max_i_ka": 1.0,
            }
        ]
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("buses.csv", buses_df.to_csv(index=False))
        z.writestr("lines.csv", lines_df.to_csv(index=False))

    return buf.getvalue(), "template.zip", "application/zip"


def ppnet_to_topology(
    net: "pp.pandapowerNet",
    source_id: str = "imported",
    source_name: str = "Imported Network",
) -> dict:
    """Converte pandapowerNet para o formato Topology JSON do frontend.

    Refatorado da lógica que estava inline em load_pandapower_case().
    Toda importação passa por aqui como formato pivô.
    """
    import numpy as np

    sn_mva = float(getattr(net, "sn_mva", 1.0))
    freq_hz = float(getattr(net, "f_hz", 50.0))

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
    if "gen" in net:
        gen_df = (
            net.gen[net.gen["in_service"]]
            if "in_service" in net.gen.columns
            else net.gen
        )
    else:
        import pandas as pd

        gen_df = pd.DataFrame(columns=["bus", "p_mw", "vm_pu"])

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

    if line_switch_open:
        line_df = line_df[~line_df.index.isin(line_switch_open)]
    if trafo_switch_open:
        trafo_df = trafo_df[~trafo_df.index.isin(trafo_switch_open)]

    kept_bus_idx = set(int(b) for b in bus_df.index)

    slack_buses = set(int(b) for b in ext_grid_df["bus"]) & kept_bus_idx
    gen_buses = (
        (set(int(b) for b in gen_df["bus"]) & kept_bus_idx)
        if len(gen_df) > 0
        else set()
    )

    load_p: dict[int, float] = {}
    load_q: dict[int, float] = {}
    for _, row in load_df.iterrows():
        b = int(row.bus)
        if b not in kept_bus_idx:
            continue
        load_p[b] = load_p.get(b, 0.0) + float(row.p_mw) / sn_mva
        load_q[b] = load_q.get(b, 0.0) + float(row.q_mvar) / sn_mva

    dg_p: dict[int, float] = {}
    dg_q: dict[int, float] = {}
    for _, row in sgen_df.iterrows():
        b = int(row.bus)
        if b not in kept_bus_idx:
            continue
        dg_p[b] = dg_p.get(b, 0.0) + float(row.p_mw) / sn_mva
        dg_q[b] = dg_q.get(b, 0.0) + float(row.q_mvar) / sn_mva

    gen_p: dict[int, float] = {}
    gen_vm: dict[int, float] = {}
    for _, row in gen_df.iterrows():
        b = int(row.bus)
        if b not in kept_bus_idx:
            continue
        gen_p[b] = gen_p.get(b, 0.0) + float(row.p_mw) / sn_mva
        gen_vm[b] = float(row.vm_pu)

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
            vm = 1.0
            va = 0.0

        bus_dict = {
            "id": seq_id,
            "name": str(net.bus.at[pp_idx, "name"] or f"Bus {pp_idx}"),
            "type": bus_type,
            "nominal_voltage_kv": (
                round(float(net.bus.at[pp_idx, "vn_kv"]), 4)
                if "vn_kv" in net.bus.columns
                else 1.0
            ),
            "voltage": round(vm, 5),
            "angle": round(va, 4),
            "pGen": round(gen_p.get(b, 0.0), 5),
            "qGen": 0.0,
            "pLoad": round(load_p.get(b, 0.0), 5),
            "qLoad": round(load_q.get(b, 0.0), 5),
            "pGenDG": round(dg_p.get(b, 0.0), 5),
            "qGenDG": round(dg_q.get(b, 0.0), 5),
        }

        if (
            hasattr(net, "bus_geodata")
            and net.bus_geodata is not None
            and len(net.bus_geodata) > 0
        ):
            if pp_idx in net.bus_geodata.index:
                geo = net.bus_geodata.loc[pp_idx]
                bus_dict["geoX"] = float(geo.x)
                bus_dict["geoY"] = float(geo.y)

        buses_out.append(bus_dict)

    lines_out = []
    seq = 1
    for _, row in line_df.iterrows():
        fb = int(row.from_bus)
        tb = int(row.to_bus)
        if fb not in kept_bus_idx or tb not in kept_bus_idx:
            continue
        vn_kv = float(net.bus.at[fb, "vn_kv"])
        z_base = vn_kv**2 / sn_mva
        r_pu = float(row.r_ohm_per_km) * float(row.length_km) / z_base
        x_pu = float(row.x_ohm_per_km) * float(row.length_km) / z_base
        c_nf = float(row.c_nf_per_km) * float(row.length_km)
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
        b_val = c_nf * 1e-9 * 2 * np.pi * freq_hz * z_base
        line_param[int(row.name)] = {
            "r_pu": round(r, 7),
            "x_pu": round(max(x, 1e-7), 7),
            "b_pu": round(b_val, 7),
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
            else:
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

    open_switches_compat = [s for s in all_switches if not s["closed"]]

    topology = {
        "id": source_id,
        "name": source_name,
        "buses": buses_out,
        "lines": lines_out,
        "switches": all_switches,
        "openSwitches": open_switches_compat,
        "frequency_hz": freq_hz,
        "meta": {
            "source": "imported",
            "sn_mva": sn_mva,
        },
    }

    return topology


def _check_convergence_and_size(topology: dict, net: "pp.pandapowerNet" = None) -> dict:
    """Tenta rodar fluxo de carga e adiciona warnings e size_warning ao topology."""
    import pandapower as pp

    topology.setdefault("warnings", [])

    if net is not None:
        try:
            pp.runpp(net)
        except Exception:
            topology["warnings"].append(
                "Power flow did not converge — network parameters may need adjustment"
            )

    num_buses = len(topology.get("buses", []))
    if num_buses < 500:
        topology["size_warning"] = None
    elif num_buses <= 2000:
        topology["size_warning"] = "large"
    else:
        topology["size_warning"] = "very_large"

    return topology


def import_file(
    file_bytes: bytes, filename: str, extra_files: dict[str, bytes] | None = None
) -> dict:
    """Dispatcher principal — detecta formato pela extensão e chama o importador certo."""
    extra_files = extra_files or {}
    ext = os.path.splitext(filename)[1].lower()

    try:
        # Detectar por formato ou tentar os importadores correspondentes
        if ext == ".json":
            try:
                topology = _import_workbench_json(file_bytes)
                return _check_convergence_and_size(topology)
            except Exception:
                try:
                    return _import_roseau_json(file_bytes, filename)
                except Exception:
                    try:
                        return _import_pandapower_json(file_bytes)
                    except Exception:
                        return _import_geojson(file_bytes)

        elif ext == ".xlsx":
            try:
                return _import_pandapower_excel(file_bytes)
            except Exception:
                return _import_ieee_tabular_excel(file_bytes, filename)

        elif ext in (".m", ".mat"):
            return _import_matpower(file_bytes, filename)

        elif ext == ".dss":
            return _import_opendss(file_bytes, extra_files)

        elif ext == ".xml":
            try:
                return _import_cim(file_bytes, filename)
            except Exception:
                return _import_graphml(file_bytes)

        elif ext == ".ucte":
            return _import_ucte(file_bytes)

        elif ext == ".csv":
            return _import_csv(file_bytes, extra_files)

        elif ext == ".zip":
            try:
                return _import_csv(file_bytes, extra_files)
            except Exception:
                try:
                    return _import_cim(file_bytes, filename)
                except Exception:
                    return _import_opendss(file_bytes, extra_files)

        elif ext == ".geojson":
            return _import_geojson(file_bytes)

        elif ext == ".graphml":
            return _import_graphml(file_bytes)

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported extension: {ext}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to import {filename}: {str(e)}"
        )


def _import_workbench_json(file_bytes: bytes) -> dict:
    try:
        topology = json.loads(file_bytes)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")
    if "buses" not in topology or "lines" not in topology:
        raise ValueError("Missing 'buses' or 'lines' in Workbench JSON")
    return topology


def _import_roseau_json(file_bytes: bytes, filename: str = "roseau.json") -> dict:
    """Importa rede no formato Roseau Load Flow (ex.: départs HTA representatifs data.gouv.fr)."""
    import pandas as pd
    import pandapower as pp

    data = json.loads(file_bytes)
    if not isinstance(data, dict) or "buses" not in data or "branches" not in data:
        raise ValueError("Not a valid Roseau Load Flow JSON format")

    net = pp.create_empty_network(sn_mva=10.0, f_hz=50.0)
    bus_map: dict[str, int] = {}
    net.bus_geodata = pd.DataFrame(columns=["x", "y"])

    # 1. Classificar e criar barras com nível de tensão MT (20 kV) ou BT (0.4 kV)
    for b in data.get("buses", []):
        bid = str(b["id"])
        coords = b.get("geometry", {}).get("coordinates", [0, 0])
        raw_vn = b.get("nominal_voltage", 20000.0)
        vn_kv = raw_vn / 1000.0 if raw_vn > 100.0 else raw_vn
        pots = b.get("results", {}).get("potentials", [])
        if pots and isinstance(pots[0], (list, tuple)) and len(pots[0]) >= 2:
            v0 = pots[0]
            mag = (float(v0[0]) ** 2 + float(v0[1]) ** 2) ** 0.5
            v_ll = mag * (3.0**0.5)
            vn_kv = 20.0 if v_ll > 5000.0 else 0.4
        else:
            raw_vn = b.get("nominal_voltage")
            if raw_vn:
                vn_kv = float(raw_vn) / 1000.0 if float(raw_vn) > 100.0 else float(raw_vn)
            else:
                vn_kv = 20.0 if ("MV" in bid or "BUZEN" in bid) else 0.4

        idx = pp.create_bus(net, vn_kv=vn_kv, name=bid)
        bus_map[bid] = idx
        if coords and len(coords) >= 2:
            net.bus_geodata.loc[idx] = {"x": float(coords[0]), "y": float(coords[1])}
        geom = b.get("geometry")
        if geom and "coordinates" in geom and geom["coordinates"] != [0, 0]:
            coords = geom["coordinates"]
            if len(coords) >= 2 and (coords[0] != 0 or coords[1] != 0):
                net.bus_geodata.loc[idx] = {"x": float(coords[0]), "y": float(coords[1])}
        if geom and "coordinates" in geom:
            c_coords = geom["coordinates"]
            if isinstance(c_coords, (list, tuple)) and len(c_coords) >= 2:
                if float(c_coords[0]) != 0.0 or float(c_coords[1]) != 0.0:
                    net.bus_geodata.loc[idx] = {"x": float(c_coords[0]), "y": float(c_coords[1])}

    # 2. Fonte / Nó Slack
    sources = data.get("sources", [])
    slack_bid = (
        str(sources[0]["bus"])
        if sources
        else (list(bus_map.keys())[0] if bus_map else None)
    )
    if slack_bid and slack_bid in bus_map:
        pp.create_ext_grid(net, bus=bus_map[slack_bid], vm_pu=1.0)

    params = {str(p["id"]): p for p in data.get("lines_params", [])}
    lines_params = {str(p["id"]): p for p in data.get("lines_params", [])}
    trafos_params = {str(p["id"]): p for p in data.get("transformers_params", [])}

    # 3. Branches (Linhas, Chaves e Transformadores)
    for br in data.get("branches", []):
        b1, b2 = str(br.get("bus1")), str(br.get("bus2"))
        if b1 not in bus_map or b2 not in bus_map:
            continue
        btype = br.get("type", "line")

        # Herdar coordenadas geográficas para barras virtuais de subestação (ex.: MVVoltage_source)
        if (
            b1 == "MVVoltage_source"
            and bus_map[b1] not in net.bus_geodata.index
            and bus_map[b2] in net.bus_geodata.index
        ):
            c = net.bus_geodata.loc[bus_map[b2]]
            net.bus_geodata.loc[bus_map[b1]] = {
                "x": float(c["x"]) - 0.0003,
                "y": float(c["y"]) + 0.0003,
            }
        elif (
            b2 == "MVVoltage_source"
            and bus_map[b2] not in net.bus_geodata.index
            and bus_map[b1] in net.bus_geodata.index
        ):
            c = net.bus_geodata.loc[bus_map[b1]]
            net.bus_geodata.loc[bus_map[b2]] = {
                "x": float(c["x"]) - 0.0003,
                "y": float(c["y"]) + 0.0003,
            }

        if btype == "line":
            pid = str(br.get("params_id"))
            p = params.get(pid, {})
            p = lines_params.get(pid, {})
            z = p.get("z_line", [[[0.2]], [[0.1]]])
            r = float(z[0][0][0]) if z else 0.2
            x = float(z[1][0][0]) if len(z) > 1 else 0.1
            raw_imax = float(p.get("max_current", 300.0))
            imax = raw_imax / 1000.0 if raw_imax > 10.0 else raw_imax
            length = float(br.get("length", 1.0))
            pp.create_line_from_parameters(
                net,
                from_bus=bus_map[b1],
                to_bus=bus_map[b2],
                length_km=max(length, 0.001),
                r_ohm_per_km=max(r, 0.001),
                x_ohm_per_km=max(x, 1e-5),
                c_nf_per_km=10.0,
                max_i_ka=max(imax, 0.05),
                name=str(br.get("id", f"{b1}-{b2}")),
            )
        elif btype == "switch":
            # Conecta fisicamente o ramo como chave de baixa impedância
            l_idx = pp.create_line_from_parameters(
                net,
                from_bus=bus_map[b1],
                to_bus=bus_map[b2],
                length_km=0.001,
                r_ohm_per_km=0.001,
                x_ohm_per_km=0.001,
                c_nf_per_km=0.0,
                max_i_ka=1.0,
                name=str(br.get("id", f"SW_{b1}_{b2}")),
            )
            pp.create_switch(
                net,
                bus=bus_map[b1],
                element=bus_map[b2],
                et="b",
                element=l_idx,
                et="l",
                closed=bool(br.get("closed", True)),
                name=str(br.get("id", f"SW_{b1}_{b2}")),
            )
        elif btype == "transformer":
            pid = str(br.get("params_id"))
            tp = trafos_params.get(pid, {})
            sn_va = float(tp.get("sn", 100000.0))
            sn_mva = max(sn_va / 1e6, 0.01)
            uhv_v = float(tp.get("uhv", 20000.0))
            ulv_v = float(tp.get("ulv", 400.0))
            vsc = float(tp.get("vsc", 0.04))
            vk_pct = max(vsc * 100.0, 1.0)
            psc = float(tp.get("psc", 2000.0))
            vkr_pct = max((psc / sn_va) * 100.0, 0.1)
            pfe_kw = float(tp.get("p0", 200.0)) / 1000.0
            i0_pct = float(tp.get("i0", 0.02)) * 100.0

    # Loads (somando potências de fases ativas e reativas)
            v1 = float(net.bus.at[bus_map[b1], "vn_kv"])
            v2 = float(net.bus.at[bus_map[b2], "vn_kv"])
            hv_b = bus_map[b1] if v1 >= v2 else bus_map[b2]
            lv_b = bus_map[b2] if v1 >= v2 else bus_map[b1]

            pp.create_transformer_from_parameters(
                net,
                hv_bus=hv_b,
                lv_bus=lv_b,
                sn_mva=sn_mva,
                vn_hv_kv=max(uhv_v / 1000.0, 1.0),
                vn_lv_kv=max(ulv_v / 1000.0, 0.1),
                vk_percent=vk_pct,
                vkr_percent=vkr_pct,
                pfe_kw=pfe_kw,
                i0_percent=i0_pct,
                name=str(br.get("id", f"T_{b1}_{b2}")),
            )

    # 4. Loads (somando potências de fases ativas e reativas)
    for ld in data.get("loads", []):
        bus_id = str(ld.get("bus"))
        if bus_id in bus_map:
            powers = ld.get("powers", [])
            p_total_mw = 0.0
            q_total_mvar = 0.0
            for phase_p in powers:
                if isinstance(phase_p, (list, tuple)) and len(phase_p) >= 2:
                    p_total_mw += float(phase_p[0]) / 1e6
                    q_total_mvar += float(phase_p[1]) / 1e6
            if p_total_mw != 0.0 or q_total_mvar != 0.0:
                pp.create_load(
                    net, bus=bus_map[bus_id], p_mw=p_total_mw, q_mvar=q_total_mvar
                )

    stem = os.path.splitext(os.path.basename(filename))[0]
    topology = ppnet_to_topology(
        net, source_id=f"roseau_{stem}", source_name=f"Départ HTA {stem}"
    )
    return _check_convergence_and_size(topology, net)


def _import_ieee_tabular_excel(
    file_bytes: bytes, filename: str = "ieee_tabular.xlsx"
) -> dict:
    """Importa planilhas Excel tabulares no padrão benchmark IEEE (ex.: IEEE_70bus.xlsx com abas Bus/Line)."""
    import pandas as pd
    import pandapower as pp

    with pd.ExcelFile(io.BytesIO(file_bytes)) as xl:
        sheet_names_lower = {str(s).strip().lower(): s for s in xl.sheet_names}
        if "bus" not in sheet_names_lower or "line" not in sheet_names_lower:
            raise ValueError("Excel file does not contain 'Bus' and 'Line' sheets")

        buses_df = xl.parse(sheet_names_lower["bus"])
        lines_df = xl.parse(sheet_names_lower["line"])
        no_df = xl.parse(sheet_names_lower["no"]) if "no" in sheet_names_lower else None
        coords_df = (
            xl.parse(sheet_names_lower["coordonnees"])
            if "coordonnees" in sheet_names_lower
            else None
        )

    net = pp.create_empty_network(sn_mva=10.0, f_hz=50.0)
    bus_map: dict[Any, int] = {}
    if coords_df is not None:
        net.bus_geodata = pd.DataFrame(columns=["x", "y"])

    for _, row in buses_df.iterrows():
        nid_col = [
            c
            for c in row.index
            if "node" in str(c).lower()
            or "bus" in str(c).lower()
            or "id" in str(c).lower()
        ]
        nid = row[nid_col[0]] if nid_col else _
        try:
            nid_key = int(nid)
        except (ValueError, TypeError):
            nid_key = nid

        idx = pp.create_bus(net, vn_kv=12.66, name=f"Bus {nid_key}")
        bus_map[nid_key] = idx

        type_cols = [c for c in row.index if "type" in str(c).lower()]
        btype = (
            int(row[type_cols[0]])
            if type_cols and not pd.isna(row[type_cols[0]])
            else 3
        )
        vm = (
            float(row.get("Initial voltage", 1.0))
            if not pd.isna(row.get("Initial voltage"))
            else 1.0
        )

        if btype == 1:
            pp.create_ext_grid(net, bus=idx, vm_pu=vm)
        elif btype == 2:
            pg_col = [c for c in row.index if "p gen" in str(c).lower()]
            pg = (
                float(row[pg_col[0]]) * 10.0
                if pg_col and not pd.isna(row[pg_col[0]])
                else 0.0
            )
            pp.create_gen(net, bus=idx, p_mw=pg, vm_pu=vm)

        pl_col = [
            c
            for c in row.index
            if "p con" in str(c).lower() or "pload" in str(c).lower()
        ]
        ql_col = [
            c
            for c in row.index
            if "q con" in str(c).lower() or "qload" in str(c).lower()
        ]
        pl = (
            float(row[pl_col[0]]) * 10.0
            if pl_col and not pd.isna(row[pl_col[0]])
            else 0.0
        )
        ql = (
            float(row[ql_col[0]]) * 10.0
            if ql_col and not pd.isna(row[ql_col[0]])
            else 0.0
        )
        if pl != 0.0 or ql != 0.0:
            pp.create_load(net, bus=idx, p_mw=pl, q_mvar=ql)

    for _, row in lines_df.iterrows():
        fb_col = [
            c
            for c in row.index
            if "start" in str(c).lower() or "from" in str(c).lower()
        ]
        tb_col = [
            c for c in row.index if "end" in str(c).lower() or "to" in str(c).lower()
        ]
        fb = int(row[fb_col[0]]) if fb_col else None
        tb = int(row[tb_col[0]]) if tb_col else None
        if fb in bus_map and tb in bus_map:
            r_col = [c for c in row.index if str(c).strip().startswith("R")]
            x_col = [c for c in row.index if str(c).strip().startswith("X")]
            r = float(row[r_col[0]]) if r_col and not pd.isna(row[r_col[0]]) else 0.01
            x = float(row[x_col[0]]) if x_col and not pd.isna(row[x_col[0]]) else 0.01
            pp.create_line_from_parameters(
                net,
                from_bus=bus_map[fb],
                to_bus=bus_map[tb],
                length_km=1.0,
                r_ohm_per_km=r,
                x_ohm_per_km=max(x, 1e-5),
                c_nf_per_km=0.0,
                max_i_ka=1.0,
            )

    # Chaves normalmente abertas (NO / tie-switches)
    if no_df is not None and not no_df.empty:
        for val in no_df.iloc[:, 0].dropna():
            try:
                line_idx = int(val) - 1
                if 0 <= line_idx < len(net.line):
                    net.line.loc[line_idx, "in_service"] = False
            except (ValueError, TypeError):
                pass

    stem = os.path.splitext(os.path.basename(filename))[0]
    topology = ppnet_to_topology(
        net, source_id=f"excel_{stem}", source_name=f"IEEE Benchmark ({stem})"
    )
    return _check_convergence_and_size(topology, net)


def _import_pandapower_json(file_bytes: bytes) -> dict:
    import pandapower as pp

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        net = pp.from_json(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    topology = ppnet_to_topology(
        net, source_id="pp_json", source_name="pandapower JSON"
    )
    return _check_convergence_and_size(topology, net)


def _import_pandapower_excel(file_bytes: bytes) -> dict:
    import pandas as pd
    import pandapower as pp

    with pd.ExcelFile(io.BytesIO(file_bytes)) as xl:
        sheet_names_lower = {str(s).strip().lower() for s in xl.sheet_names}
        if "no" in sheet_names_lower or "coordonnees" in sheet_names_lower or "parametres" in sheet_names_lower:
            raise ValueError("Detected IEEE tabular Excel benchmark format, not pandapower Excel")
        if "bus" not in sheet_names_lower or "line" not in sheet_names_lower:
            raise ValueError("Not a pandapower Excel network (missing bus/line sheets)")
        # Verificar se as colunas da aba bus batem com pandapower (vn_kv) ou IEEE
        sheet_bus_name = next(s for s in xl.sheet_names if str(s).strip().lower() == "bus")
        bus_sample = xl.parse(sheet_bus_name, nrows=2)
        cols_lower = {str(c).lower() for c in bus_sample.columns}
        if "vn_kv" not in cols_lower and "in_service" not in cols_lower:
            raise ValueError("Excel bus sheet does not contain pandapower columns")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        net = pp.from_excel(tmp_path)
        if len(net.bus) == 0:
            raise ValueError("Not a pandapower Excel network (zero buses)")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    topology = ppnet_to_topology(
        net, source_id="pp_excel", source_name="pandapower Excel"
    )
    return _check_convergence_and_size(topology, net)


def _import_matpower(file_bytes: bytes, filename: str) -> dict:
    ext = os.path.splitext(filename)[1].lower()

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        if ext == ".m":
            from pandapower.converter.matpower.from_mpc import from_mpc

            net = from_mpc(tmp_path)
        else:
            from pandapower.converter.pypower.from_ppc import from_ppc
            from scipy.io import loadmat

            mat = loadmat(tmp_path)
            ppc = mat.get("mpc") or mat.get("ppc") or list(mat.values())[-1]
            net = from_ppc(ppc)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    topology = ppnet_to_topology(net, source_id="matpower", source_name="MATPOWER")
    return _check_convergence_and_size(topology, net)


def _import_opendss(file_bytes: bytes, extra_files: dict[str, bytes]) -> dict:
    try:
        from pandapower.converter.opendss import from_opendss
    except ImportError:
        raise ValueError("OpenDSS converter not available")

    with tempfile.TemporaryDirectory() as tmpdir:
        master_file = None
        if file_bytes[:4] == b"PK\x03\x04" or extra_files.get("is_zip"):
            buf = io.BytesIO(file_bytes)
            with zipfile.ZipFile(buf, "r") as z:
                z.extractall(tmpdir)
                for f in z.namelist():
                    if f.lower().endswith(".dss") and "master" in f.lower():
                        master_file = os.path.join(tmpdir, f)
                if not master_file:
                    for f in z.namelist():
                        if f.lower().endswith(".dss"):
                            master_file = os.path.join(tmpdir, f)
                            break
        else:
            master_file = os.path.join(tmpdir, "master.dss")
            with open(master_file, "wb") as f:
                f.write(file_bytes)
            for name, content in extra_files.items():
                with open(os.path.join(tmpdir, name), "wb") as f:
                    f.write(content)

        if not master_file:
            raise ValueError("No main .dss file found")

        net = from_opendss(master_file)

    topology = ppnet_to_topology(net, source_id="opendss", source_name="OpenDSS")
    return _check_convergence_and_size(topology, net)


def _import_cim(file_bytes: bytes, filename: str) -> dict:
    from pandapower.converter.cim.from_cim import from_cim

    ext = os.path.splitext(filename)[1].lower()

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        net = from_cim(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    topology = ppnet_to_topology(net, source_id="cim", source_name="CIM CGMES")
    return _check_convergence_and_size(topology, net)


def _import_ucte(file_bytes: bytes) -> dict:
    from pandapower.converter.ucte.from_ucte import from_ucte

    with tempfile.NamedTemporaryFile(suffix=".ucte", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        net = from_ucte(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    topology = ppnet_to_topology(net, source_id="ucte", source_name="UCTE DEF")
    return _check_convergence_and_size(topology, net)


def _import_csv(file_bytes: bytes, extra_files: dict[str, bytes]) -> dict:
    import ast
    import re
    import pandas as pd
    import pandapower as pp

    dfs_to_classify: list[tuple[str, pd.DataFrame]] = []

    if file_bytes[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as z:
            for name in z.namelist():
                if name.lower().endswith(".csv"):
                    with z.open(name) as f:
                        dfs_to_classify.append((name, pd.read_csv(f)))
    else:
        dfs_to_classify.append(("main.csv", pd.read_csv(io.BytesIO(file_bytes))))
        for extra_name, extra_bytes in extra_files.items():
            if extra_name.lower().endswith(".csv"):
                dfs_to_classify.append(
                    (extra_name, pd.read_csv(io.BytesIO(extra_bytes)))
                )

    buses_df = None
    lines_df = None
    switches_df = None

    for fname, df in dfs_to_classify:
        nl = fname.lower()
        cols = {c.lower() for c in df.columns}
        if "switch" in nl or (
            "closed" in cols and ("bus" in cols or "element" in cols)
        ):
            switches_df = df
        elif (
            "line" in nl
            or "bus_in" in cols
            or "bus_out" in cols
            or "from_bus" in cols
            or "r_ohm_per_km" in cols
            or ("r" in cols and "x" in cols)
        ):
            lines_df = df
        elif (
            "bus" in nl
            or "bus_id" in cols
            or "nominal_voltage" in cols
            or "vn_kv" in cols
        ):
            buses_df = df
        else:
            # Fallback por inspeção de colunas
            if "from" in cols or "to" in cols:
                lines_df = df
            else:
                buses_df = df

    if buses_df is None or lines_df is None:
        raise ValueError("Missing 'buses' or 'lines' data for CSV import.")

    net = pp.create_empty_network(sn_mva=10.0, f_hz=50.0)
    bus_map: dict[Any, int] = {}
    has_slack = False

    for _, row in buses_df.iterrows():
        b_id = (
            row.get("bus_id")
            if "bus_id" in row
            else row.get("id", row.get("bus", row.get("name")))
        )
        if pd.isna(b_id):
            continue
        try:
            b_id = int(b_id)
        except (ValueError, TypeError):
            pass

        raw_vn = row.get("vn_kv", row.get("nominal_voltage", row.get("voltage", 1.0)))
        vn_kv = 1.0 if pd.isna(raw_vn) else float(raw_vn)
        if vn_kv > 100.0:
            vn_kv /= 1000.0  # Ex: 20000.0 V -> 20 kV

        name = row.get("name", str(b_id))
        idx = pp.create_bus(net, vn_kv=vn_kv, name=str(name))
        bus_map[b_id] = idx

        btype = str(row.get("type", "")).lower()
        vm_pu = (
            float(row.get("vm_pu", row.get("voltage_pu", 1.0)))
            if not pd.isna(row.get("vm_pu", row.get("voltage_pu", 1.0)))
            else 1.0
        )

        b_id_str = str(b_id).lower()
        is_slack = (
            btype == "slack"
            or "d.inf" in b_id_str
            or "slack" in b_id_str
            or "substation" in b_id_str
            or "source" in b_id_str
        )

        if is_slack:
            pp.create_ext_grid(net, bus=idx, vm_pu=vm_pu)
            has_slack = True
        elif btype == "pv":
            raw_pg = row.get("pg_mw", row.get("pGen", 0.0))
            pg = float(raw_pg) if not pd.isna(raw_pg) else 0.0
            if pg > 0:
                pp.create_gen(net, bus=idx, p_mw=pg, vm_pu=vm_pu)

        # Cargas: tentar matriz trifásica ou escalares MW/MVAr
        pd_mw = 0.0
        qd_mvar = 0.0
        raw_load = row.get("load")
        if not pd.isna(raw_load) and raw_load:
            try:
                if isinstance(raw_load, str):
                    try:
                        load_phases = json.loads(raw_load)
                    except Exception:
                        load_phases = ast.literal_eval(raw_load)
                else:
                    load_phases = raw_load
                if isinstance(load_phases, (list, tuple)) and len(load_phases) > 0:
                    p_w = sum(
                        ph[0]
                        for ph in load_phases
                        if isinstance(ph, (list, tuple)) and len(ph) > 0
                    )
                    q_var = sum(
                        ph[1]
                        for ph in load_phases
                        if isinstance(ph, (list, tuple)) and len(ph) > 1
                    )
                    pd_mw = float(p_w) / 1e6
                    qd_mvar = float(q_var) / 1e6
            except Exception:
                pass

        if pd_mw == 0.0 and qd_mvar == 0.0:
            raw_pd = row.get("pd_mw", row.get("pLoad", row.get("p_mw", 0.0)))
            raw_qd = row.get("qd_mvar", row.get("qLoad", row.get("q_mvar", 0.0)))
            pd_mw = float(raw_pd) if not pd.isna(raw_pd) else 0.0
            qd_mvar = float(raw_qd) if not pd.isna(raw_qd) else 0.0

        if pd_mw != 0.0 or qd_mvar != 0.0:
            pp.create_load(net, bus=idx, p_mw=pd_mw, q_mvar=qd_mvar)

        raw_pg_dg = row.get("pGenDG", row.get("p_sgen_mw", 0.0))
        raw_qg_dg = row.get("qGenDG", row.get("q_sgen_mvar", 0.0))
        pg_dg = float(raw_pg_dg) if not pd.isna(raw_pg_dg) else 0.0
        qg_dg = float(raw_qg_dg) if not pd.isna(raw_qg_dg) else 0.0
        if pg_dg != 0.0 or qg_dg != 0.0:
            pp.create_sgen(net, bus=idx, p_mw=pg_dg, q_mvar=qg_dg)

        x = row.get(
            "x_coord",
            row.get("geoX", row.get("x", row.get("lon", row.get("longitude")))),
        )
        y = row.get(
            "y_coord",
            row.get("geoY", row.get("y", row.get("lat", row.get("latitude")))),
        )
        if not pd.isna(x) and not pd.isna(y):
            if not hasattr(net, "bus_geodata") or net.bus_geodata is None:
                net.bus_geodata = pd.DataFrame(columns=["x", "y"])
            net.bus_geodata.loc[idx] = {"x": float(x), "y": float(y)}

    # Fallback para slack se nenhum foi criado
    if not has_slack and len(net.bus) > 0:
        pp.create_ext_grid(net, bus=net.bus.index[0], vm_pu=1.0)

    for _, row in lines_df.iterrows():
        fb = row.get(
            "from_bus", row.get("from", row.get("bus_in", row.get("from_bus_id")))
        )
        tb = row.get("to_bus", row.get("to", row.get("bus_out", row.get("to_bus_id"))))
        r = row.get("r_ohm_per_km", row.get("resistance", row.get("R", row.get("r"))))
        x = row.get("x_ohm_per_km", row.get("reactance", row.get("X", row.get("x"))))
        length = row.get("length_km", row.get("length", 1.0))
        if pd.isna(length) or float(length) <= 0:
            length = 1.0

        if pd.isna(fb) or pd.isna(tb) or pd.isna(r) or pd.isna(x):
            continue

        try:
            fb = int(fb)
        except (ValueError, TypeError):
            pass
        try:
            tb = int(tb)
        except (ValueError, TypeError):
            pass

        if fb in bus_map and tb in bus_map:
            raw_c = row.get("c_nf_per_km", row.get("capacitance", row.get("C", 0.0)))
            raw_max_i = row.get(
                "max_i_ka", row.get("Imax", row.get("imax", row.get("max_i", 1.0)))
            )
            c = float(raw_c) if not pd.isna(raw_c) else 0.0
            max_i = float(raw_max_i) if not pd.isna(raw_max_i) else 1.0
            if max_i > 10.0:
                max_i /= 1000.0  # Ex: 325 A -> 0.325 kA

            pp.create_line_from_parameters(
                net,
                from_bus=bus_map[fb],
                to_bus=bus_map[tb],
                length_km=float(length),
                r_ohm_per_km=float(r),
                x_ohm_per_km=max(float(x), 1e-6),
                c_nf_per_km=c,
                max_i_ka=max_i,
            )

            # Extração de coordenadas geográficas via Linestring em 'position'
            pos_str = str(row.get("position", ""))
            if "linestring" in pos_str.lower():
                pts = re.findall(r"[-+]?\d+\.\d+", pos_str)
                if len(pts) >= 4:
                    lon_start, lat_start = float(pts[0]), float(pts[1])
                    lon_end, lat_end = float(pts[-2]), float(pts[-1])
                    if not hasattr(net, "bus_geodata") or net.bus_geodata is None:
                        net.bus_geodata = pd.DataFrame(columns=["x", "y"])
                    fb_idx = bus_map[fb]
                    tb_idx = bus_map[tb]
                    if fb_idx not in net.bus_geodata.index:
                        net.bus_geodata.loc[fb_idx] = {"x": lon_start, "y": lat_start}
                    if tb_idx not in net.bus_geodata.index:
                        net.bus_geodata.loc[tb_idx] = {"x": lon_end, "y": lat_end}

    if switches_df is not None and not switches_df.empty:
        for _, row in switches_df.iterrows():
            sb = row.get("bus")
            se = row.get("element")
            et = str(row.get("et", "l"))
            closed = bool(row.get("closed", True))
            try:
                sb = int(sb)
            except (ValueError, TypeError):
                pass
            try:
                se = int(se)
            except (ValueError, TypeError):
                pass
            if sb in bus_map:
                pp.create_switch(net, bus=bus_map[sb], element=se, et=et, closed=closed)

    topology = ppnet_to_topology(net, source_id="csv", source_name="CSV Import")
    return _check_convergence_and_size(topology, net)


def _import_geojson(file_bytes: bytes) -> dict:
    import json
    import pandas as pd
    import pandapower as pp

    try:
        data = json.loads(file_bytes)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    net = pp.create_empty_network()
    bus_map: dict[Any, int] = {}

    features = data.get("features", [])
    buses = [f for f in features if f.get("geometry", {}).get("type") == "Point"]
    lines = [f for f in features if f.get("geometry", {}).get("type") == "LineString"]
    if not features or (not buses and not lines):
        raise ValueError("Invalid GeoJSON: no Point or LineString features found")

    for b in buses:
        props = b.get("properties", {})
        coords = b.get("geometry", {}).get("coordinates", [0, 0])
        name = props.get("name", "Bus")
        vn_kv = float(props.get("vn_kv", 1.0))
        idx = pp.create_bus(net, vn_kv=vn_kv, name=str(name))
        b_id = props.get("id", name)
        bus_map[b_id] = idx

        if not hasattr(net, "bus_geodata"):
            net.bus_geodata = pd.DataFrame(columns=["x", "y"])
        net.bus_geodata.loc[idx] = {"x": float(coords[0]), "y": float(coords[1])}

    for l in lines:
        props = l.get("properties", {})
        fb = props.get("from_bus", props.get("from"))
        tb = props.get("to_bus", props.get("to"))
        if fb in bus_map and tb in bus_map:
            pp.create_line_from_parameters(
                net,
                from_bus=bus_map[fb],
                to_bus=bus_map[tb],
                length_km=float(props.get("length_km", 1.0)),
                r_ohm_per_km=float(props.get("r_ohm_per_km", 0.1)),
                x_ohm_per_km=max(float(props.get("x_ohm_per_km", 0.1)), 1e-6),
                c_nf_per_km=float(props.get("c_nf_per_km", 10.0)),
                max_i_ka=float(props.get("max_i_ka", 1.0)),
            )

    topology = ppnet_to_topology(net, source_id="geojson", source_name="GeoJSON")
    return _check_convergence_and_size(topology, net)


def _import_graphml(file_bytes: bytes) -> dict:
    import networkx as nx
    import pandapower as pp

    try:
        G = nx.read_graphml(io.BytesIO(file_bytes))
    except Exception as e:
        raise ValueError(f"Invalid GraphML: {e}")

    net = pp.create_empty_network()
    bus_map: dict[Any, int] = {}

    for n, data in G.nodes(data=True):
        vn_kv = float(data.get("vn_kv", 1.0))
        name = str(data.get("name", n))
        idx = pp.create_bus(net, vn_kv=vn_kv, name=name)
        bus_map[n] = idx

    for u, v, data in G.edges(data=True):
        if u in bus_map and v in bus_map:
            length = float(data.get("length_km", 1.0))
            r = float(data.get("r_ohm_per_km", 0.1))
            x = float(data.get("x_ohm_per_km", 0.1))
            pp.create_line_from_parameters(
                net,
                from_bus=bus_map[u],
                to_bus=bus_map[v],
                length_km=length,
                r_ohm_per_km=r,
                x_ohm_per_km=max(x, 1e-6),
                c_nf_per_km=10.0,
                max_i_ka=1.0,
            )

    topology = ppnet_to_topology(net, source_id="graphml", source_name="GraphML")
    return _check_convergence_and_size(topology, net)


def export_topology(topology: dict, format: str) -> tuple[bytes, str, str]:
    """Exporta topologia para o formato pedido.

    Returns: (file_bytes, filename, content_type)
    """
    if format == "workbench_json":
        return _export_workbench_json(topology)
    elif format == "pandapower_json":
        return _export_pandapower_json(topology)
    elif format == "pandapower_excel":
        return _export_pandapower_excel(topology)
    elif format == "csv":
        return _export_csv_export(topology)
    elif format == "graphml":
        return _export_graphml_export(topology)
    else:
        raise HTTPException(
            status_code=400, detail=f"Unsupported export format: {format}"
        )


def _export_workbench_json(topology: dict) -> tuple[bytes, str, str]:
    content = json.dumps(topology, indent=2).encode("utf-8")
    return content, "topology.json", "application/json"


def _export_pandapower_json(topology: dict) -> tuple[bytes, str, str]:
    import pandapower as pp
    from app.backend.services.network_builder import build_net_from_frontend

    net, _ = build_net_from_frontend(topology)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        pp.to_json(net, tmp_path)
        with open(tmp_path, "rb") as f:
            content = f.read()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return content, "topology_pp.json", "application/json"


def _export_pandapower_excel(topology: dict) -> tuple[bytes, str, str]:
    import pandapower as pp
    from app.backend.services.network_builder import build_net_from_frontend

    net, _ = build_net_from_frontend(topology)

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        pp.to_excel(net, tmp_path)
        with open(tmp_path, "rb") as f:
            content = f.read()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return (
        content,
        "topology.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _export_csv_export(topology: dict) -> tuple[bytes, str, str]:
    import pandas as pd

    buses_list = []
    for b in topology.get("buses", []):
        row = dict(b)
        row["bus_id"] = b.get("id")
        row["vn_kv"] = b.get("vn_kv", 1.0)
        row["pd_mw"] = b.get("pLoad", 0.0)
        row["qd_mvar"] = b.get("qLoad", 0.0)
        row["pg_mw"] = b.get("pGen", 0.0)
        if "geoX" in b:
            row["x_coord"] = b["geoX"]
        if "geoY" in b:
            row["y_coord"] = b["geoY"]
        buses_list.append(row)

    lines_list = []
    for l in topology.get("lines", []):
        row = dict(l)
        row["from_bus"] = l.get("from_bus", l.get("from"))
        row["to_bus"] = l.get("to_bus", l.get("to"))
        row["r_ohm_per_km"] = l.get("resistance", 0.01)
        row["x_ohm_per_km"] = l.get("reactance", 0.01)
        row["length_km"] = 1.0
        lines_list.append(row)

    buses_df = pd.DataFrame(buses_list)
    lines_df = pd.DataFrame(lines_list)
    switches_df = pd.DataFrame(topology.get("switches", []))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("buses.csv", buses_df.to_csv(index=False))
        z.writestr("lines.csv", lines_df.to_csv(index=False))
        if not switches_df.empty:
            z.writestr("switches.csv", switches_df.to_csv(index=False))

    return buf.getvalue(), "topology_csv.zip", "application/zip"


def _export_graphml_export(topology: dict) -> tuple[bytes, str, str]:
    import networkx as nx

    G = nx.Graph()
    for b in topology.get("buses", []):
        attrs = {k: v for k, v in b.items() if k != "id"}
        G.add_node(b["id"], **attrs)

    for l in topology.get("lines", []):
        attrs = {
            k: v for k, v in l.items() if k not in ["from", "to", "from_bus", "to_bus"]
        }
        u = l.get("from_bus", l.get("from"))
        v = l.get("to_bus", l.get("to"))
        G.add_edge(u, v, **attrs)

    buf = io.BytesIO()
    nx.write_graphml(G, buf)

    return buf.getvalue(), "topology.graphml", "application/xml"
