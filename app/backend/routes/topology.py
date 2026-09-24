"""Rota /api/topologies — topologias IEEE disponíveis + casos pandapower."""

from __future__ import annotations

import inspect
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
    """Carrega um caso pandapower e converte para o formato Topology do frontend."""
    import pandapower.networks as pn
    from app.backend.services.topology_io import ppnet_to_topology

    if case_name not in _pp_case_names():
        raise HTTPException(
            status_code=404,
            detail=f"Case '{case_name}' not found in pandapower.networks",
        )

    net = getattr(pn, case_name)()
    return ppnet_to_topology(
        net, source_id=f"pp_{case_name}", source_name=f"pandapower · {case_name}"
    )


from fastapi import UploadFile, File, Form
from fastapi.responses import StreamingResponse
import io


@router.get("/import/formats")
def list_import_formats():
    from app.backend.services.topology_io import get_import_formats

    return get_import_formats()


@router.get("/export/formats")
def list_export_formats():
    from app.backend.services.topology_io import get_export_formats

    return get_export_formats()


@router.get("/import/csv-template")
def download_csv_template():
    from app.backend.services.topology_io import get_csv_template

    file_bytes, filename, content_type = get_csv_template()
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
async def import_topology(
    file: UploadFile = File(...),
    format: str = Form(None),
    extra_files: list[UploadFile] = File(default=[]),
):
    """Importa topologia de arquivo externo."""
    from app.backend.services.topology_io import import_file

    file_bytes = await file.read()
    extra_files_dict = {}
    for ef in extra_files:
        extra_files_dict[ef.filename] = await ef.read()

    return import_file(file_bytes, file.filename, extra_files_dict)


@router.post("/export/{format}")
async def export_topology_endpoint(format: str, topology: dict):
    """Exporta topologia para arquivo."""
    from app.backend.services.topology_io import export_topology

    file_bytes, filename, content_type = export_topology(topology, format)

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{topology_id}")
def get_topology(topology_id: str) -> dict:
    """Retorna topologia completa por ID (deve ficar no final para não interceptar rotas estáticas)."""
    if topology_id not in TOPOLOGY_MAP:
        raise HTTPException(
            status_code=404, detail=f"Topology '{topology_id}' not found."
        )
    return TOPOLOGY_MAP[topology_id]
