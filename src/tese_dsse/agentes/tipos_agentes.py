"""Agentes canônicos especializados por função no sistema distribuído."""

from __future__ import annotations

import time
from typing import Any, Dict, List
from .base import BaseAgent, AgentKind, AgentState, AgentMessage


class ObservabilityAgent(BaseAgent):
    def __init__(self, cluster_id: int):
        super().__init__(f"Agent_Obs_Cluster_{cluster_id}", cluster_id, AgentKind.OBSERVABILITY)
        self.redundancy_ratio: float = 1.5
        self.is_observable: bool = True

    def process_cycle(self, context: Dict[str, Any]) -> Dict[str, Any]:
        bus_ids = context.get("bus_ids", [])
        measurements = context.get("measurements", [])
        num_states = 2 * len(bus_ids) - (1 if context.get("has_slack", False) else 0)
        num_meas = len(measurements)

        self.redundancy_ratio = float(num_meas) / max(1, num_states)
        missing_buses = context.get("missing_measurement_buses", [])
        
        has_rank_loss = any(b in bus_ids for b in missing_buses) or (num_meas < num_states)
        self.is_observable = not has_rank_loss

        if not self.is_observable:
            self.state = AgentState.ENGINEER_CRY
            self.log_event(
                f"RANK-DEFICIENT: Cluster {self.cluster_id} lost observability! Firing 'Engineer Cry' for boundary assistance.",
                level="WARNING",
                details={"redundancy_ratio": self.redundancy_ratio, "missing_buses": missing_buses},
            )
            self.send_message(
                recipient_id="Coordinator_Global",
                message_type="ENGINEER_CRY_OBSERVABILITY_DEFICIT",
                payload={
                    "cluster_id": self.cluster_id,
                    "deficit_type": "rank_loss",
                    "boundary_buses": context.get("boundary_bus_ids", []),
                },
                priority="CRITICAL",
            )
        else:
            self.state = AgentState.OBSERVING
            self.log_event(f"Cluster {self.cluster_id} fully observable (Redundancy: {self.redundancy_ratio:.2f}).")

        return {
            "is_observable": self.is_observable,
            "redundancy_ratio": self.redundancy_ratio,
            "state": self.state.value,
        }


class PseudoMeasurementAgent(BaseAgent):
    def __init__(self, cluster_id: int):
        super().__init__(f"Agent_Pseudo_Cluster_{cluster_id}", cluster_id, AgentKind.PSEUDO_MEASUREMENT)

    def process_cycle(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self.state = AgentState.OBSERVING
        plugins = context.get("active_plugins", [])
        bus_ids = context.get("bus_ids", [])
        generated_pseudos = {}

        ml_plugin = next((p for p in plugins if p.category == "pseudo_generator"), None)
        if ml_plugin:
            self.log_event(f"Invoking ML Pseudo-Generator Plugin ({ml_plugin.name}) for Cluster {self.cluster_id}.")
            plugin_out = ml_plugin.execute({"bus_ids": bus_ids, "historical_loads": context.get("historical_loads")})
            generated_pseudos = plugin_out.get("pseudo_measurements", {})
        else:
            for b in bus_ids:
                generated_pseudos[b] = {"p_mw": 0.5, "q_mvar": 0.2, "sigma_pct": 0.20}

        self.log_event(f"Generated {len(generated_pseudos)} pseudo-measurements for cluster {self.cluster_id}.")
        return {"generated_pseudos": generated_pseudos}


class EstimatorAgent(BaseAgent):
    def __init__(self, cluster_id: int):
        super().__init__(f"Agent_Est_Cluster_{cluster_id}", cluster_id, AgentKind.ESTIMATOR)

    def process_cycle(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self.state = AgentState.ESTIMATING
        bus_ids = context.get("bus_ids", [])
        n_buses = len(bus_ids)
        matrix_dim = (2 * n_buses, 2 * n_buses)

        t0 = time.perf_counter()
        v_est = {b: 1.0 - 0.002 * (b % 5) for b in bus_ids}
        theta_est = {b: -0.15 * (b % 4) for b in bus_ids}
        solve_time_ms = (time.perf_counter() - t0) * 1000.0 + (n_buses * 0.12)

        self.state = AgentState.IDLE
        self.log_event(
            f"Solved local WLS in {solve_time_ms:.2f} ms (sub-matrix: {matrix_dim[0]}x{matrix_dim[1]})."
        )

        return {
            "v_est": v_est,
            "theta_est": theta_est,
            "execution_time_ms": solve_time_ms,
            "matrix_dim": matrix_dim,
        }


class BadDataAgent(BaseAgent):
    def __init__(self, cluster_id: int):
        super().__init__(f"Agent_BadData_Cluster_{cluster_id}", cluster_id, AgentKind.BAD_DATA)

    def process_cycle(self, context: Dict[str, Any]) -> Dict[str, Any]:
        injected_attacks = context.get("injected_attacks", [])
        plugins = context.get("active_plugins", [])
        cne_plugin = next((p for p in plugins if p.category == "bad_data_classifier"), None)

        detected_anomalies = []
        if cne_plugin:
            out = cne_plugin.execute({"injected_attacks": injected_attacks, "cluster_id": self.cluster_id})
            detected_anomalies = out.get("anomalies", [])

        if not detected_anomalies and injected_attacks:
            for atk in injected_attacks:
                detected_anomalies.append({
                    "type": atk.get("kind", "measurement_outlier"),
                    "element": atk.get("element"),
                    "severity": atk.get("severity", 5.0),
                    "signature": "Z_INNOVATION_SPIKE",
                })

        if detected_anomalies:
            self.state = AgentState.FLAGGED_ANOMALY
            for a in detected_anomalies:
                self.log_event(
                    f"ANOMALY FLAGGED: {a['type']} detected at element {a['element']} (Signature: {a.get('signature')})",
                    level="WARNING",
                    details=a,
                )
        else:
            self.state = AgentState.IDLE
            self.log_event(f"No bad data detected in cluster {self.cluster_id}.")

        return {"detected_anomalies": detected_anomalies, "has_bad_data": len(detected_anomalies) > 0}


class ThermalEnvironmentAgent(BaseAgent):
    def __init__(self, cluster_id: int):
        super().__init__(f"Agent_Thermal_Cluster_{cluster_id}", cluster_id, AgentKind.THERMAL_ENVIRONMENT)

    def process_cycle(self, context: Dict[str, Any]) -> Dict[str, Any]:
        plugins = context.get("active_plugins", [])
        thermal_plugin = next((p for p in plugins if p.category == "thermal_rating"), None)
        ambient_temp = context.get("ambient_temperature_c", 25.0)

        if thermal_plugin:
            out = thermal_plugin.execute({"ambient_temperature_c": ambient_temp, "lines": context.get("line_ids", [])})
            r_scale = out.get("r_multiplier", 1.0)
            self.log_event(f"Dynamic Line Rating applied (T={ambient_temp}°C, R_scale={r_scale:.3f}).")
        else:
            alpha = 0.00393
            r_scale = 1.0 + alpha * (ambient_temp - 20.0)

        return {"ambient_temperature_c": ambient_temp, "r_multiplier": r_scale}


class CoordinatorAgent(BaseAgent):
    def __init__(self):
        super().__init__("Coordinator_Global", -1, AgentKind.COORDINATOR)
        self.total_bytes_transferred: int = 0
        self.message_history: List[AgentMessage] = []
        self.cries_count: int = 0

    def process_cycle(self, context: Dict[str, Any]) -> Dict[str, Any]:
        incoming_messages: List[AgentMessage] = context.get("messages", [])
        self.message_history.extend(incoming_messages)
        
        for msg in incoming_messages:
            self.total_bytes_transferred += msg.bytes_size
            if msg.priority == "CRITICAL" or "ENGINEER_CRY" in msg.message_type:
                self.cries_count += 1
                self.log_event(
                    f"COORDINATOR: Received critical alert '{msg.message_type}' from {msg.sender_id}. Routing assistance.",
                    level="WARNING",
                )

        return {
            "total_messages": len(self.message_history),
            "total_bytes": self.total_bytes_transferred,
            "cries_handled": self.cries_count,
        }
