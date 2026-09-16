"""Trace ponta a ponta da cadeia operacional (correlation id).

O `ExecutionTrace` que ja existe em `app/backend/services/trace.py` registra os
estados intermediarios de UM algoritmo (as matrizes do DC-WLS, as iteracoes do
Gauss-Newton). Este modulo e outra coisa: registra o caminho de UM DADO
atravessando as camadas da cadeia.

    Sensor S17 -> RTU-3 -> packet #541 -> SCADA point P_BUS5
                -> topology snapshot #32 -> SE iteration #32

E o que permite responder "por que essa medicao entrou no vetor z com esse
valor e essa qualidade?" sem reconstruir a simulacao inteira na mao. Sem isso,
um ataque injetado na camada de comunicacao aparece no estimador como um
residuo grande e nada mais -- a cadeia causal fica invisivel, que e exatamente
o que a plataforma existe para estudar.

Convencao de tempo: todos os timestamps sao segundos de simulacao (float),
comecando em `t=0`. Nao ha relogio de parede em lugar nenhum da cadeia -- e o
que torna uma corrida reproduzivel bit a bit dado o mesmo seed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "LAYERS",
    "Layer",
    "LayerEvent",
    "PipelineTrace",
]

#: Ordem canonica das camadas. E a ordem em que os eventos sao mostrados no
#: painel de trace do app e a ordem em que a cadeia executa -- os dois nao
#: podem divergir, entao existe uma lista so.
LAYERS: tuple[str, ...] = (
    "physical",
    "measurement",
    "rtu",
    "channel",
    "rtdb",
    "topology",
    "estimation",
    "opf",
)

Layer = Literal[
    "physical",
    "measurement",
    "rtu",
    "channel",
    "rtdb",
    "topology",
    "estimation",
    "opf",
]


@dataclass(frozen=True)
class LayerEvent:
    """Um acontecimento em uma camada, atribuido a um sujeito rastreavel.

    `subject` e a chave de correlacao: o `sensor_id` de uma medicao, o
    `point_id` de um ponto do RTDB, ou `SW-<id>` para um switch. Todo evento
    que fala do mesmo dado usa o MESMO subject em todas as camadas -- e assim
    que `PipelineTrace.trail()` consegue montar a linha da vida sem que cada
    camada precise conhecer as outras.
    """

    layer: Layer
    timestamp_s: float
    subject: str
    message: str
    level: Literal["info", "warning", "error"] = "info"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "timestamp_s": round(float(self.timestamp_s), 6),
            "subject": self.subject,
            "message": self.message,
            "level": self.level,
            "details": self.details,
        }


@dataclass
class PipelineTrace:
    """Coletor de eventos de uma corrida da cadeia.

    Deliberadamente burro: so acumula. Nenhuma camada consulta o trace para
    decidir alguma coisa -- se consultasse, desligar o trace mudaria o
    resultado numerico, e a corrida deixaria de ser reproduzivel com e sem
    observabilidade ligada.
    """

    events: list[LayerEvent] = field(default_factory=list)

    def log(
        self,
        layer: Layer,
        timestamp_s: float,
        subject: str,
        message: str,
        *,
        level: Literal["info", "warning", "error"] = "info",
        **details: Any,
    ) -> None:
        self.events.append(
            LayerEvent(
                layer=layer,
                timestamp_s=float(timestamp_s),
                subject=str(subject),
                message=message,
                level=level,
                details=details,
            )
        )

    # ── consultas ────────────────────────────────────────────────────────────

    def trail(self, subject: str) -> list[LayerEvent]:
        """A linha da vida de um sujeito, em ordem de camada e depois de tempo.

        Ordena por camada antes de por tempo de proposito: um pacote pode ser
        recebido (channel, t=0.05) depois de o snapshot de topologia ja ter
        sido montado (topology, t=0.0), e mostrar o caminho fora da ordem
        causal confunde mais do que ajuda.
        """
        order = {name: i for i, name in enumerate(LAYERS)}
        found = [e for e in self.events if e.subject == subject]
        return sorted(found, key=lambda e: (order.get(e.layer, 99), e.timestamp_s))

    def by_layer(self, layer: Layer) -> list[LayerEvent]:
        return [e for e in self.events if e.layer == layer]

    def problems(self) -> list[LayerEvent]:
        """So os eventos de warning/error -- o resumo que a UI mostra primeiro."""
        return [e for e in self.events if e.level in ("warning", "error")]

    def subjects(self) -> list[str]:
        """Sujeitos rastreaveis, sem repeticao, na ordem em que apareceram."""
        seen: dict[str, None] = {}
        for e in self.events:
            seen.setdefault(e.subject, None)
        return list(seen)

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {name: 0 for name in LAYERS}
        for e in self.events:
            counts[e.layer] = counts.get(e.layer, 0) + 1
        return {
            "events": [e.to_dict() for e in self.events],
            "n_events": len(self.events),
            "events_by_layer": counts,
            "problems": [e.to_dict() for e in self.problems()],
            "subjects": self.subjects(),
        }
