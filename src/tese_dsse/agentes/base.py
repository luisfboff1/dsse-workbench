"""Abstrações fundamentais, enums e protocolo de mensagens do framework multiagente."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import time


class AgentState(str, Enum):
    IDLE = "idle"
    OBSERVING = "observing"
    ESTIMATING = "estimating"
    FLAGGED_ANOMALY = "flagged_anomaly"
    ENGINEER_CRY = "engineer_cry"
    CONSENSUS = "consensus"
    RECONFIGURING = "reconfiguring"


class AgentKind(str, Enum):
    OBSERVABILITY = "observability"
    PSEUDO_MEASUREMENT = "pseudo_measurement"
    ESTIMATOR = "estimator"
    BAD_DATA = "bad_data"
    THERMAL_ENVIRONMENT = "thermal_environment"
    COORDINATOR = "coordinator"


@dataclass
class AgentMessage:
    """Envelope padronizado para comunicação sob demanda entre agentes."""
    sender_id: str
    recipient_id: str
    message_type: str
    payload: Dict[str, Any]
    priority: str = "NORMAL"
    timestamp_ms: float = field(default_factory=lambda: time.time() * 1000.0)
    bytes_size: int = 0

    def __post_init__(self):
        if self.bytes_size == 0:
            import json
            try:
                self.bytes_size = len(json.dumps(self.payload).encode("utf-8")) + 64
            except Exception:
                self.bytes_size = 128


@dataclass
class AgentCluster:
    """Representação de uma ilha/sub-rede particionada gerenciada por uma equipe de agentes."""
    cluster_id: int
    name: str
    bus_ids: List[int]
    line_ids: List[int]
    boundary_bus_ids: List[int] = field(default_factory=list)
    boundary_line_ids: List[int] = field(default_factory=list)
    neighbor_cluster_ids: List[int] = field(default_factory=list)
    enabled_agent_kinds: List[AgentKind] = field(default_factory=lambda: [
        AgentKind.OBSERVABILITY,
        AgentKind.PSEUDO_MEASUREMENT,
        AgentKind.ESTIMATOR,
        AgentKind.BAD_DATA,
        AgentKind.THERMAL_ENVIRONMENT,
    ])
    local_state_dim: int = 0
    matrix_dim: tuple = (0, 0)


class AgentPlugin(ABC):
    @property
    @abstractmethod
    def plugin_id(self) -> str:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def author(self) -> str:
        pass

    @property
    @abstractmethod
    def category(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {}

    @abstractmethod
    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        pass


class BaseAgent(ABC):
    def __init__(self, agent_id: str, cluster_id: int, kind: AgentKind):
        self.agent_id = agent_id
        self.cluster_id = cluster_id
        self.kind = kind
        self.state: AgentState = AgentState.IDLE
        self.inbox: List[AgentMessage] = []
        self.outbox: List[AgentMessage] = []
        self.event_log: List[Dict[str, Any]] = []

    def log_event(self, message: str, level: str = "INFO", details: Optional[Dict[str, Any]] = None):
        self.event_log.append({
            "timestamp_ms": time.time() * 1000.0,
            "agent_id": self.agent_id,
            "cluster_id": self.cluster_id,
            "kind": self.kind.value,
            "level": level,
            "message": message,
            "details": details or {},
        })

    def receive_message(self, message: AgentMessage):
        self.inbox.append(message)

    def send_message(self, recipient_id: str, message_type: str, payload: Dict[str, Any], priority: str = "NORMAL"):
        msg = AgentMessage(
            sender_id=self.agent_id,
            recipient_id=recipient_id,
            message_type=message_type,
            payload=payload,
            priority=priority,
        )
        self.outbox.append(msg)
        return msg

    @abstractmethod
    def process_cycle(self, context: Dict[str, Any]) -> Dict[str, Any]:
        pass
