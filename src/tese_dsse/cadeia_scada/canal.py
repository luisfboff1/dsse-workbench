"""Camada de comunicacao: transporte dos pontos da RTU ate o SCADA.

**Escopo desta versao (Fase 1).** O atraso e um *atributo por pacote*, nao uma
fila de eventos: cada ponto sai da RTU, sofre `delay = base + jitter` e chega.
Nao ha reordenacao, nao ha replay, nao ha concorrencia por banda. Isso e
suficiente para o caso de estudo que motiva a camada -- o snapshot
inconsistente, em que medicoes legitimas de instantes diferentes sao agregadas
como se fossem simultaneas -- e nao e suficiente para ataques que dependem da
ordem dos pacotes.

A Fase 2 troca `transmit()` por um simulador de eventos discretos (SimPy, mesma
stack do dataset de comunicacao FDI) mantendo esta assinatura. Por isso
`PacketDelivery` ja carrega `sequence`, `reordered` e `replayed`: os campos
existem, sempre valem `False` aqui, e a UI que os exibe nao precisa mudar
quando a Fase 2 chegar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .rtu import RTUPoint
from .traco import PipelineTrace

__all__ = ["ChannelConfig", "PacketDelivery", "transmit"]


@dataclass(frozen=True)
class ChannelConfig:
    """Parametros do canal.

    `per_rtu_delay_ms` sobrescreve `base_delay_ms` para RTUs especificas -- e
    como se modela uma RTU num enlace ruim (ou sob ataque de atraso) sem
    degradar a rede inteira, que e o cenario em que o Communication Agent tem
    o que detectar.
    """

    base_delay_ms: float = 50.0
    jitter_ms: float = 0.0
    drop_probability: float = 0.0
    per_rtu_delay_ms: dict[str, float] = field(default_factory=dict)
    seed: int | None = None

    def delay_for(self, rtu_id: str) -> float:
        return float(self.per_rtu_delay_ms.get(rtu_id, self.base_delay_ms))

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_delay_ms": self.base_delay_ms,
            "jitter_ms": self.jitter_ms,
            "drop_probability": self.drop_probability,
            "per_rtu_delay_ms": dict(self.per_rtu_delay_ms),
            "seed": self.seed,
        }


@dataclass(frozen=True)
class PacketDelivery:
    """Um pacote levando um ponto de uma RTU ao SCADA."""

    packet_id: int
    sequence: int
    source: str
    destination: str
    point: RTUPoint
    send_time_s: float
    receive_time_s: float
    delay_ms: float
    dropped: bool = False
    reordered: bool = False
    replayed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "sequence": self.sequence,
            "source": self.source,
            "destination": self.destination,
            "point_id": self.point.point_id,
            "sensor_id": self.point.sensor_id,
            "send_time_s": round(float(self.send_time_s), 6),
            "receive_time_s": round(float(self.receive_time_s), 6),
            "delay_ms": round(float(self.delay_ms), 3),
            "dropped": self.dropped,
            "reordered": self.reordered,
            "replayed": self.replayed,
        }


def transmit(
    points: list[RTUPoint],
    config: ChannelConfig,
    *,
    destination: str = "SCADA",
    trace: PipelineTrace | None = None,
) -> list[PacketDelivery]:
    """Transporta cada ponto num pacote, aplicando atraso, jitter e perda.

    O `send_time` e o `source_timestamp` do proprio ponto (o instante em que a
    RTU o leu), nao um instante unico para todos -- caso contrario a dispersao
    de varredura montada em `rtu.build_points` seria apagada aqui e o caso do
    snapshot inconsistente nunca apareceria.

    Pacote perdido continua na lista, com `dropped=True` e
    `receive_time_s = inf`. Devolver a perda em vez de omiti-la e o que
    permite ao RTDB distinguir "nunca chegou" de "chegou e esta velho", e ao
    painel mostrar a taxa de perda real.
    """
    rng = np.random.default_rng(config.seed)
    deliveries: list[PacketDelivery] = []

    for seq, point in enumerate(points, start=1):
        delay_ms = config.delay_for(point.rtu_id)
        if config.jitter_ms > 0:
            # Jitter uniforme e simetrico, truncado em zero: um pacote pode
            # chegar mais rapido que o nominal, nunca antes de ser enviado.
            delay_ms = max(0.0, delay_ms + float(rng.uniform(-config.jitter_ms, config.jitter_ms)))

        dropped = bool(rng.random() < config.drop_probability) if config.drop_probability > 0 else False
        send_time = float(point.source_timestamp_s)
        receive_time = float("inf") if dropped else send_time + delay_ms / 1000.0

        delivery = PacketDelivery(
            packet_id=seq,
            sequence=seq,
            source=point.rtu_id,
            destination=destination,
            point=point,
            send_time_s=send_time,
            receive_time_s=receive_time,
            delay_ms=delay_ms,
            dropped=dropped,
        )
        deliveries.append(delivery)

        if trace is not None:
            if dropped:
                trace.log(
                    "channel",
                    send_time,
                    point.sensor_id,
                    f"packet #{seq} ({point.point_id}) PERDIDO no enlace {point.rtu_id}->{destination}",
                    level="warning",
                    packet_id=seq,
                    rtu_id=point.rtu_id,
                    delay_ms=round(delay_ms, 3),
                )
            else:
                trace.log(
                    "channel",
                    receive_time,
                    point.sensor_id,
                    f"packet #{seq} {point.rtu_id}->{destination}, atraso {delay_ms:.1f} ms",
                    packet_id=seq,
                    rtu_id=point.rtu_id,
                    delay_ms=round(delay_ms, 3),
                    send_time_s=round(send_time, 6),
                    receive_time_s=round(receive_time, 6),
                )

    return deliveries


def delivery_statistics(deliveries: list[PacketDelivery]) -> dict[str, Any]:
    """Resumo do canal: perda, atraso medio/maximo e dispersao por RTU."""
    total = len(deliveries)
    dropped = [d for d in deliveries if d.dropped]
    ok = [d for d in deliveries if not d.dropped]
    delays = [d.delay_ms for d in ok]

    by_rtu: dict[str, list[float]] = {}
    for d in ok:
        by_rtu.setdefault(d.source, []).append(d.delay_ms)

    return {
        "n_packets": total,
        "n_dropped": len(dropped),
        "loss_rate": round(len(dropped) / total, 6) if total else 0.0,
        "delay_ms_mean": round(float(np.mean(delays)), 3) if delays else 0.0,
        "delay_ms_max": round(float(np.max(delays)), 3) if delays else 0.0,
        "delay_ms_by_rtu": {
            rtu: round(float(np.mean(v)), 3) for rtu, v in sorted(by_rtu.items())
        },
    }
