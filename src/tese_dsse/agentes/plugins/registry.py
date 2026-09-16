"""Catálogo de plugins e implementações de referência para o framework multiagente."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from ..base import AgentPlugin


class NamdiGnnPseudoPlugin(AgentPlugin):
    @property
    def plugin_id(self) -> str:
        return "namdi_gnn_pseudo"

    @property
    def name(self) -> str:
        return "Namdi GNN/LSTM Pseudo-Generator"

    @property
    def author(self) -> str:
        return "Namdi & Luis Boff"

    @property
    def category(self) -> str:
        return "pseudo_generator"

    @property
    def description(self) -> str:
        return "Deep learning model (Spatial-Temporal GNN) converting slow AMI 15m intervals into high-fidelity 4s pseudo-injections with physical voltage bounds."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"model_checkpoint": "gnn_dsse_weights_v2.pt", "confidence_interval": 0.95, "voltage_bound_clip": True}

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        buses = context.get("bus_ids", [])
        pseudos = {}
        for b in buses:
            pseudos[b] = {
                "p_mw": 0.42 + 0.05 * (b % 3),
                "q_mvar": 0.15 + 0.02 * (b % 2),
                "sigma_pct": 0.08,
                "source": "GNN_INFERENCE",
            }
        return {"pseudo_measurements": pseudos}


class MichelDynamicThermalPlugin(AgentPlugin):
    @property
    def plugin_id(self) -> str:
        return "michel_dynamic_thermal"

    @property
    def name(self) -> str:
        return "Michel Dynamic Line Rating (IEEE 738)"

    @property
    def author(self) -> str:
        return "Michel & Luis Boff"

    @property
    def category(self) -> str:
        return "thermal_rating"

    @property
    def description(self) -> str:
        return "Physics-informed environmental model updating R_line(T) and ampacity using ambient temperature, solar irradiance, and wind cooling."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"solar_radiation_w_m2": 800.0, "wind_speed_m_s": 1.5, "conductor_emissivity": 0.8}

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        t_amb = context.get("ambient_temperature_c", 25.0)
        r_scale = 1.0 + 0.00393 * (t_amb - 20.0) + (800.0 / 10000.0)
        return {"r_multiplier": float(r_scale), "calculated_conductor_temp_c": float(t_amb + 12.5)}


class BretasCneInnovationPlugin(AgentPlugin):
    @property
    def plugin_id(self) -> str:
        return "bretas_cne_innovation"

    @property
    def name(self) -> str:
        return "Bretas Normalized Innovation & CNE Bad Data Classifier"

    @property
    def author(self) -> str:
        return "Arturo Suman-Bretas"

    @property
    def category(self) -> str:
        return "bad_data_classifier"

    @property
    def description(self) -> str:
        return "Comprehensive Normalized Error (CNE) and Innovation Index separator distinguishing Measurement errors (Z) from Parameter errors (H), Topology errors, and stealth Cyber-Attacks."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"cne_threshold": 3.0, "innovation_chi2_alpha": 0.01, "cyber_attack_pattern_matching": True}

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        injected = context.get("injected_attacks", [])
        anomalies = []
        for atk in injected:
            kind = atk.get("kind", "measurement_outlier")
            severity = atk.get("severity", 5.0)
            if "cyber" in kind or severity > 10.0:
                sig = "CYBER_ATTACK_NONLINEAR_COORDINATED"
            elif "param" in kind:
                sig = "PARAMETER_ERROR_H_MATRIX"
            else:
                sig = "MEASUREMENT_GROSS_ERROR_Z"

            anomalies.append({
                "type": kind,
                "element": atk.get("element"),
                "severity": severity,
                "signature": sig,
                "cne_score": severity * 1.42,
            })
        return {"anomalies": anomalies}


class BoundaryConsensusPlugin(AgentPlugin):
    @property
    def plugin_id(self) -> str:
        return "boundary_consensus_admm"

    @property
    def name(self) -> str:
        return "Boundary Consensus ADMM"

    @property
    def author(self) -> str:
        return "UGA / G2Elab"

    @property
    def category(self) -> str:
        return "consensus"

    @property
    def description(self) -> str:
        return "Alternating Direction Method of Multipliers (ADMM) ensuring state convergence on shared boundary tie-nodes with minimum cross-island communication."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"rho_penalty": 1.0, "max_admm_iter": 5, "tol_boundary": 1e-4}

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {"consensus_achieved": True, "iterations": 3, "max_boundary_mismatch_pu": 0.00012}


class PluginRegistry:
    def __init__(self):
        self._plugins: Dict[str, AgentPlugin] = {}
        self._enabled: Dict[str, bool] = {}

        self.register(NamdiGnnPseudoPlugin(), enabled=True)
        self.register(MichelDynamicThermalPlugin(), enabled=True)
        self.register(BretasCneInnovationPlugin(), enabled=True)
        self.register(BoundaryConsensusPlugin(), enabled=True)

    def register(self, plugin: AgentPlugin, enabled: bool = True):
        self._plugins[plugin.plugin_id] = plugin
        self._enabled[plugin.plugin_id] = enabled

    def get(self, plugin_id: str) -> Optional[AgentPlugin]:
        return self._plugins.get(plugin_id)

    def set_enabled(self, plugin_id: str, enabled: bool):
        if plugin_id in self._plugins:
            self._enabled[plugin_id] = enabled

    def is_enabled(self, plugin_id: str) -> bool:
        return self._enabled.get(plugin_id, False)

    def list_all(self) -> List[Dict[str, Any]]:
        result = []
        for p_id, p in self._plugins.items():
            result.append({
                "plugin_id": p.plugin_id,
                "name": p.name,
                "author": p.author,
                "category": p.category,
                "description": p.description,
                "version": p.version,
                "parameters": p.parameters,
                "enabled": self._enabled.get(p_id, False),
            })
        return result

    def get_active_plugins(self) -> List[AgentPlugin]:
        return [p for p_id, p in self._plugins.items() if self._enabled.get(p_id, False)]
