"""SCADA RTDB: a base de tempo real que o estimador realmente enxerga.

O ponto inteiro desta camada e que o SCADA **nao** entrega um instante: ele
entrega o ultimo valor conhecido de cada ponto, e cada ponto tem uma idade
diferente. O estimador trata esse conjunto como se fosse um snapshot
simultaneo, e nao e. `RTDBSnapshot.timestamp_spread_s` mede exatamente essa
mentira -- e a metrica do caso de estudo de atraso.

Regras de qualidade implementadas aqui:

- **stale**: `now - source_timestamp > stale_after_s`. Um valor velho nao e um
  valor errado; e um valor que descreve outro instante da rede.
- **not updated**: o pacote nunca chegou (perda). O ponto fica no banco com o
  ultimo valor conhecido, ou ausente se nunca houve um -- e a diferenca entre
  os dois casos e visivel, porque um operador precisa distinguir "sem
  telemetria" de "telemetria congelada".
- **quality**: `good` -> `suspect` -> `bad`. A degradacao e monotona: uma
  camada posterior nunca promove a qualidade de um ponto que uma anterior
  rebaixou. Sem essa regra, um ataque que rebaixa a qualidade poderia ser
  apagado pela checagem seguinte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .canal import PacketDelivery
from .rtu import Quality, RTUPoint
from .traco import PipelineTrace

__all__ = ["PointRecord", "RTDB", "RTDBSnapshot"]

#: Ordem de severidade -- `degrade()` so caminha para a direita.
_QUALITY_RANK: dict[str, int] = {"good": 0, "suspect": 1, "bad": 2}


def degrade(current: Quality, proposed: Quality) -> Quality:
    """Pior das duas qualidades. Ver a regra de monotonicidade no docstring."""
    return current if _QUALITY_RANK[current] >= _QUALITY_RANK[proposed] else proposed


@dataclass
class PointRecord:
    """Uma linha do banco de tempo real."""

    point_id: str
    rtu_id: str
    quantity: str
    equipment_id: str
    phase: str
    value: float
    sigma: float
    source_timestamp_s: float
    receive_timestamp_s: float
    quality: Quality
    stale: bool
    last_update_s: float
    sensor_id: str
    packet_id: int | None
    meter_kind: str
    bus_id: int | None = None
    line_id: int | None = None
    measurement_index: int | None = None
    never_received: bool = False

    @property
    def age_s(self) -> float:
        """Idade do dado no instante em que o snapshot foi tirado."""
        return float(self.last_update_s - self.source_timestamp_s)

    def to_dict(self) -> dict[str, Any]:
        return {
            "point_id": self.point_id,
            "rtu_id": self.rtu_id,
            "quantity": self.quantity,
            "equipment_id": self.equipment_id,
            "phase": self.phase,
            "value": round(float(self.value), 6),
            "sigma": round(float(self.sigma), 8),
            "source_timestamp_s": round(float(self.source_timestamp_s), 6),
            "receive_timestamp_s": (
                None if not np.isfinite(self.receive_timestamp_s) else round(float(self.receive_timestamp_s), 6)
            ),
            "quality": self.quality,
            "stale": self.stale,
            "age_s": round(self.age_s, 6),
            "sensor_id": self.sensor_id,
            "packet_id": self.packet_id,
            "meter_kind": self.meter_kind,
            "bus_id": self.bus_id,
            "line_id": self.line_id,
            "measurement_index": self.measurement_index,
            "never_received": self.never_received,
        }


@dataclass
class RTDBSnapshot:
    """O que o processador de topologia e o estimador recebem."""

    now_s: float
    records: list[PointRecord]
    stale_after_s: float

    @property
    def usable(self) -> list[PointRecord]:
        """Pontos que entram no vetor z.

        Um ponto `bad` e excluido: o SCADA sabe que aquele dado nao presta e
        nao ha razao para o estimador gastar um grau de liberdade com ele.
        Um ponto `suspect` (tipicamente stale) **entra**, porque descartar todo
        dado velho quebraria a observabilidade da rede na primeira falha de
        enlace -- e o comportamento real: o operador estima com o que tem e
        convive com o vies. E dai que sai o caso de estudo.
        """
        return [r for r in self.records if r.quality != "bad" and not r.never_received]

    @property
    def timestamp_spread_s(self) -> float:
        """Diferenca entre a medicao mais nova e a mais velha do snapshot.

        Zero significaria um snapshot verdadeiramente simultaneo. Qualquer
        valor acima disso e o tamanho da inconsistencia que o estimador vai
        tratar como se fosse ruido de medicao.
        """
        ts = [r.source_timestamp_s for r in self.usable]
        return float(max(ts) - min(ts)) if ts else 0.0

    def summary(self) -> dict[str, Any]:
        recs = self.records
        return {
            "now_s": round(float(self.now_s), 6),
            "stale_after_s": self.stale_after_s,
            "n_points": len(recs),
            "n_usable": len(self.usable),
            "n_stale": sum(1 for r in recs if r.stale),
            "n_bad": sum(1 for r in recs if r.quality == "bad"),
            "n_suspect": sum(1 for r in recs if r.quality == "suspect"),
            "n_never_received": sum(1 for r in recs if r.never_received),
            "timestamp_spread_s": round(self.timestamp_spread_s, 6),
            "max_age_s": round(max((r.age_s for r in recs), default=0.0), 6),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"summary": self.summary(), "records": [r.to_dict() for r in self.records]}


@dataclass
class RTDB:
    """Banco de pontos de tempo real.

    Mantem um registro por `point_id`. Uma entrega nova sobrescreve a antiga
    **so se for mais recente na origem** -- e o que impede que um pacote
    reordenado (Fase 2) ou um replay sobrescreva um dado bom com um dado
    velho. A checagem ja esta aqui porque implementa-la depois exigiria
    reprocessar historicos.
    """

    records: dict[str, PointRecord] = field(default_factory=dict)

    def ingest(self, delivery: PacketDelivery, *, trace: PipelineTrace | None = None) -> None:
        p: RTUPoint = delivery.point

        if delivery.dropped:
            existing = self.records.get(p.point_id)
            if existing is None:
                self.records[p.point_id] = PointRecord(
                    point_id=p.point_id, rtu_id=p.rtu_id, quantity=p.quantity,
                    equipment_id=p.equipment_id, phase=p.phase, value=float("nan"),
                    sigma=p.sigma, source_timestamp_s=p.source_timestamp_s,
                    receive_timestamp_s=float("inf"), quality="bad", stale=True,
                    last_update_s=p.source_timestamp_s, sensor_id=p.sensor_id,
                    packet_id=delivery.packet_id, meter_kind=p.meter_kind,
                    bus_id=p.bus_id, line_id=p.line_id,
                    measurement_index=p.measurement_index, never_received=True,
                )
            if trace is not None:
                trace.log(
                    "rtdb", delivery.send_time_s, p.sensor_id,
                    f"{p.point_id} sem atualizacao (pacote perdido) -> quality=bad",
                    level="error", point_id=p.point_id, rtu_id=p.rtu_id,
                )
            return

        existing = self.records.get(p.point_id)
        if existing is not None and existing.source_timestamp_s > p.source_timestamp_s:
            if trace is not None:
                trace.log(
                    "rtdb", delivery.receive_time_s, p.sensor_id,
                    f"{p.point_id} descartado: chegou mais velho que o valor em banco",
                    level="warning", point_id=p.point_id,
                )
            return

        self.records[p.point_id] = PointRecord(
            point_id=p.point_id, rtu_id=p.rtu_id, quantity=p.quantity,
            equipment_id=p.equipment_id, phase=p.phase, value=float(p.value),
            sigma=float(p.sigma), source_timestamp_s=float(p.source_timestamp_s),
            receive_timestamp_s=float(delivery.receive_time_s),
            quality=p.quality, stale=False,
            last_update_s=float(delivery.receive_time_s), sensor_id=p.sensor_id,
            packet_id=delivery.packet_id, meter_kind=p.meter_kind,
            bus_id=p.bus_id, line_id=p.line_id,
            measurement_index=p.measurement_index,
        )

        if trace is not None:
            trace.log(
                "rtdb", delivery.receive_time_s, p.sensor_id,
                f"{p.point_id} gravado no RTDB (valor {p.value:.4f}, quality={p.quality})",
                point_id=p.point_id, rtu_id=p.rtu_id, value=round(float(p.value), 6),
                quality=p.quality,
            )

    def ingest_all(self, deliveries: list[PacketDelivery], *, trace: PipelineTrace | None = None) -> None:
        for d in deliveries:
            self.ingest(d, trace=trace)

    def snapshot(
        self, now_s: float, *, stale_after_s: float = 10.0, trace: PipelineTrace | None = None
    ) -> RTDBSnapshot:
        """Congela o banco, marcando o que esta velho demais.

        `now_s` e o instante do operador -- normalmente o maior `receive_time`
        entre os pacotes que chegaram, ou seja, o momento em que o SCADA
        terminou de receber a rodada.
        """
        out: list[PointRecord] = []
        for rec in self.records.values():
            age = now_s - rec.source_timestamp_s
            rec.last_update_s = float(now_s)
            if not rec.never_received and age > stale_after_s:
                rec.stale = True
                rec.quality = degrade(rec.quality, "suspect")
                if trace is not None:
                    trace.log(
                        "rtdb", now_s, rec.sensor_id,
                        f"{rec.point_id} STALE: idade {age:.2f} s > limite {stale_after_s:.2f} s",
                        level="warning", point_id=rec.point_id, age_s=round(age, 6),
                    )
            out.append(rec)

        out.sort(key=lambda r: r.point_id)
        snap = RTDBSnapshot(now_s=float(now_s), records=out, stale_after_s=float(stale_after_s))

        if trace is not None and snap.timestamp_spread_s > 0:
            trace.log(
                "rtdb", now_s, "SNAPSHOT",
                f"snapshot com dispersao de {snap.timestamp_spread_s:.3f} s entre a medicao "
                "mais nova e a mais velha -- o estimador vai trata-lo como simultaneo",
                level="warning" if snap.timestamp_spread_s > 1.0 else "info",
                timestamp_spread_s=round(snap.timestamp_spread_s, 6),
                n_usable=len(snap.usable),
            )
        return snap
