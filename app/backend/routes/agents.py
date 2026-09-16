"""Rotas /api/agents — Multi-Agent Framework, partição topológica e plugins testbed."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .powerflow import TopologyInput, _topology_to_dict
from ..services.network_builder import build_net_from_frontend
from ..paths import ensure_src_on_path

ensure_src_on_path()

from tese_dsse.agentes import (
    partition_spectral,
    partition_feeder_radial,
    MultiAgentSimulationEngine,
    AgentCluster,
)

router = APIRouter()
GLOBAL_ENGINE = MultiAgentSimulationEngine()


class PartitionRequest(BaseModel):
    topology: Optional[TopologyInput] = None
    k_clusters: int = Field(2, ge=1, le=20)
    method: Literal["spectral", "radial_feeder"] = "spectral"


class AttackInput(BaseModel):
    element: int
    kind: str = "measurement_outlier"
    severity: float = 5.0


class SimulationRequest(BaseModel):
    topology: Optional[TopologyInput] = None
    clusters: Optional[List[Dict[str, Any]]] = None
    k_clusters: int = Field(2, ge=1, le=20)
    partition_method: Literal["spectral", "radial_feeder"] = "spectral"
    missing_measurement_buses: List[int] = Field(default_factory=list)
    injected_attacks: List[AttackInput] = Field(default_factory=list)
    ambient_temperature_c: float = 25.0
    enabled_plugins: Optional[List[str]] = None


@router.post("/partition")
def partition_network(req: PartitionRequest) -> Dict[str, Any]:
    try:
        if req.topology:
            topo_dict = _topology_to_dict(req.topology)
            net, bus_map = build_net_from_frontend(topo_dict)
            reverse_map = {v: k for k, v in bus_map.items()}
        else:
            import pandapower.networks as pn
            net = pn.case14()
            reverse_map = {int(b): int(b) for b in net.bus.index}

        if req.method == "radial_feeder":
            clusters = partition_feeder_radial(net, k_clusters=req.k_clusters)
        else:
            clusters = partition_spectral(net, k_clusters=req.k_clusters)

        serialized_clusters = []
        for cl in clusters:
            frontend_bus_ids = [reverse_map.get(b, b) for b in cl.bus_ids]
            frontend_boundary_ids = [reverse_map.get(b, b) for b in cl.boundary_bus_ids]
            serialized_clusters.append({
                "cluster_id": cl.cluster_id,
                "name": cl.name,
                "bus_ids": frontend_bus_ids,
                "line_ids": cl.line_ids,
                "boundary_bus_ids": frontend_boundary_ids,
                "boundary_line_ids": cl.boundary_line_ids,
                "neighbor_cluster_ids": cl.neighbor_cluster_ids,
                "enabled_agent_kinds": [k.value for k in cl.enabled_agent_kinds],
            })

        return {
            "k_clusters": len(clusters),
            "method": req.method,
            "clusters": serialized_clusters,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Clustering failed: {exc}")


@router.post("/simulate")
def run_agentic_simulation(req: SimulationRequest) -> Dict[str, Any]:
    try:
        if req.topology:
            topo_dict = _topology_to_dict(req.topology)
            net, bus_map = build_net_from_frontend(topo_dict)
            reverse_map = {v: k for k, v in bus_map.items()}
            forward_map = bus_map
        else:
            import pandapower.networks as pn
            net = pn.case14()
            reverse_map = {int(b): int(b) for b in net.bus.index}
            forward_map = reverse_map

        agent_clusters = None
        if req.clusters:
            agent_clusters = []
            for c_data in req.clusters:
                pp_bus_ids = [forward_map.get(b, b) for b in c_data.get("bus_ids", [])]
                pp_boundary_ids = [forward_map.get(b, b) for b in c_data.get("boundary_bus_ids", [])]
                agent_clusters.append(AgentCluster(
                    cluster_id=c_data["cluster_id"],
                    name=c_data["name"],
                    bus_ids=pp_bus_ids,
                    line_ids=c_data.get("line_ids", []),
                    boundary_bus_ids=pp_boundary_ids,
                    boundary_line_ids=c_data.get("boundary_line_ids", []),
                    neighbor_cluster_ids=c_data.get("neighbor_cluster_ids", []),
                ))

        pp_missing_buses = [forward_map.get(b, b) for b in req.missing_measurement_buses]
        raw_attacks = [
            {"element": forward_map.get(a.element, a.element), "kind": a.kind, "severity": a.severity}
            for a in req.injected_attacks
        ]

        result = GLOBAL_ENGINE.run_simulation(
            net=net,
            clusters=agent_clusters,
            k_clusters=req.k_clusters,
            partition_method=req.partition_method,
            missing_measurement_buses=pp_missing_buses,
            injected_attacks=raw_attacks,
            ambient_temperature_c=req.ambient_temperature_c,
            active_plugin_ids=req.enabled_plugins,
        )

        mapped_v = {}
        mapped_theta = {}
        for b_str, v in result["estimated_v_pu"].items():
            b_orig = reverse_map.get(int(b_str), int(b_str))
            mapped_v[str(b_orig)] = v
        for b_str, th in result["estimated_theta_deg"].items():
            b_orig = reverse_map.get(int(b_str), int(b_str))
            mapped_theta[str(b_orig)] = th

        result["estimated_v_pu"] = mapped_v
        result["estimated_theta_deg"] = mapped_theta

        for cl_id, cl_dict in result["clusters"].items():
            cl_dict["bus_ids"] = [reverse_map.get(b, b) for b in cl_dict["bus_ids"]]
            cl_dict["boundary_bus_ids"] = [reverse_map.get(b, b) for b in cl_dict["boundary_bus_ids"]]

        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Simulation failed: {exc}")


@router.get("/plugins")
def list_plugins() -> Dict[str, Any]:
    return {"plugins": GLOBAL_ENGINE.plugin_registry.list_all()}


@router.post("/plugins/{plugin_id}/toggle")
def toggle_plugin(plugin_id: str, enabled: bool = Query(True)) -> Dict[str, Any]:
    p = GLOBAL_ENGINE.plugin_registry.get(plugin_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found.")
    GLOBAL_ENGINE.plugin_registry.set_enabled(plugin_id, enabled)
    return {"status": "ok", "plugin_id": plugin_id, "enabled": enabled}


@router.post("/compare")
def compare_scalability(req: PartitionRequest) -> Dict[str, Any]:
    try:
        if req.topology:
            topo_dict = _topology_to_dict(req.topology)
            net, _ = build_net_from_frontend(topo_dict)
        else:
            import pandapower.networks as pn
            net = pn.case14()

        k_values = [1, 2, 3, 4]
        results = []
        for k in k_values:
            if k > len(net.bus):
                continue
            sim = GLOBAL_ENGINE.run_simulation(net, k_clusters=k, partition_method=req.method)
            results.append({
                "k_clusters": k,
                "benchmark": sim["benchmark"],
            })

        return {"comparison": results}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Comparison failed: {exc}")
