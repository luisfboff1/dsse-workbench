"""Processador de topologia: status telemetrado -> rede reconstruida.

Esta e a camada que o app nao tinha. Ate aqui, `routes/topology.py` decidia
quais ramos estao ativos lendo o campo `closed` da chave -- ou seja, lendo a
**verdade**. Um operador real nunca ve a verdade: ve dois contatos auxiliares
por disjuntor, e reconstroi a rede a partir deles.

## Os quatro estados NAO sao uma convencao nossa

Um disjuntor reporta dois contatos auxiliares: **52a** (fecha junto com o
disjuntor) e **52b** (abre junto com o disjuntor). Em operacao normal eles sao
complementares. Dois bits, quatro combinacoes -- e essas quatro combinacoes sao
um **objeto padronizado de protocolo**, nao um modelo inventado aqui:

- **DNP3**: *Double-Bit Binary Input*, Object Group 3 (estatico) e 4 (evento).
- **IEC 61850**: `Dbpos` / *double point status* (`DPS`), usado no `Pos.stVal`
  de um `XCBR` (disjuntor) ou `XSWI` (seccionadora).

Os dois usam a MESMA numeracao, que e simplesmente o valor de 2 bits com o
contato "fechado" como bit alto -- `codigo = 2*52a + 52b`:

| Codigo | (52a, 52b) | DNP3 / IEC 61850                 | Leitura                        | Confiavel |
|--------|------------|----------------------------------|--------------------------------|-----------|
| 0      | (0, 0)     | Intermediate / intermediate-state| em transito, ou contato solto  | **nao**   |
| 1      | (0, 1)     | Determined OFF / off             | aberto, coerente               | sim       |
| 2      | (1, 0)     | Determined ON / on               | fechado, coerente              | sim       |
| 3      | (1, 1)     | Indeterminate / bad-state        | contradicao fisica             | **nao**   |

Seguir a numeracao da norma em vez de uma propria e o que permite dizer a um
operador (ou a uma RTE/distribuidora) que a ferramenta consome o mesmo objeto
que o SCADA dele ja recebe do campo. Um `import` futuro de historian ou uma
integracao real por DNP3/IEC-104 mapeia campo a campo, sem tradutor.

Os codigos 0 e 3 sao o ponto em que o processador precisa *decidir* sem saber
-- e portanto o ponto em que um agente tem funcao. Ver `UnreliablePolicy`.

## Por que isso importa para seguranca

O ataque de topologia nao mexe em nenhuma medicao analogica. Ele inverte um
par de contatos, o processador reconstroi uma rede que nao existe, a `Ybus`
sai errada, e o estimador resolve corretamente o problema errado. O residuo
resultante nao tem a assinatura de um outlier isolado -- ele se espalha pelas
medicoes ao redor do ramo, exatamente como o erro de parametro estudado em
`estimacao_estado/ac_bad_data.py`. E por isso que o caso interessa a tese: as
duas assinaturas colidem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .traco import PipelineTrace

__all__ = [
    "STATUS_LABEL",
    "SwitchTelemetry",
    "TopologySnapshot",
    "UnreliablePolicy",
    "process_topology",
]

UnreliablePolicy = Literal["last_known", "assume_closed", "assume_open", "flow_inference"]

#: Rotulos na nomenclatura da norma (DNP3 double-bit / IEC 61850 Dbpos).
STATUS_LABEL: dict[int, str] = {
    0: "Intermediate",
    1: "Determined OFF (open)",
    2: "Determined ON (closed)",
    3: "Indeterminate",
}

#: Os dois codigos em que a leitura e conclusiva. Os outros dois existem e
#: chegam ao SCADA como qualquer outro dado -- so nao dizem o estado da chave.
RELIABLE_CODES: frozenset[int] = frozenset({1, 2})


@dataclass(frozen=True)
class SwitchTelemetry:
    """Os dois contatos auxiliares de uma chave, como chegam do campo."""

    switch_id: int
    from_bus: int
    to_bus: int
    contact_a: int
    """52a -- 1 quando o disjuntor esta fechado."""
    contact_b: int
    """52b -- 1 quando o disjuntor esta aberto."""
    name: str = ""
    line_id: int | None = None

    @property
    def status_code(self) -> int:
        """Valor de 2 bits do DNP3 double-bit / IEC 61850 Dbpos: `2*52a + 52b`.

        0 = Intermediate, 1 = Determined OFF (aberto), 2 = Determined ON
        (fechado), 3 = Indeterminate. Ver a tabela no topo do modulo.
        """
        return 2 * int(bool(self.contact_a)) + int(bool(self.contact_b))

    @property
    def reliable(self) -> bool:
        return self.status_code in RELIABLE_CODES

    @property
    def closed(self) -> bool | None:
        """Estado da chave se a leitura for conclusiva, senao `None`.

        `None` e informacao, nao ausencia dela: e a diferenca entre "a chave
        esta aberta" e "o campo nao esta dizendo em que posicao a chave esta".
        Quem precisa de um booleano usa a politica de resolucao.
        """
        code = self.status_code
        if code == 2:
            return True
        if code == 1:
            return False
        return None

    @classmethod
    def from_closed(cls, switch_id: int, from_bus: int, to_bus: int, closed: bool, **kw: Any) -> SwitchTelemetry:
        """Telemetria coerente a partir do estado verdadeiro da chave.

        E o caminho normal: a simulacao sabe o estado real, e os contatos sao
        gerados complementares. Um ataque depois quebra a complementaridade.
        """
        return cls(
            switch_id=switch_id, from_bus=from_bus, to_bus=to_bus,
            contact_a=1 if closed else 0, contact_b=0 if closed else 1, **kw,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "switch_id": self.switch_id,
            "name": self.name or f"SW-{self.switch_id}",
            "from_bus": self.from_bus,
            "to_bus": self.to_bus,
            "line_id": self.line_id,
            "contact_a": int(bool(self.contact_a)),
            "contact_b": int(bool(self.contact_b)),
            "status_code": self.status_code,
            "status_label": STATUS_LABEL[self.status_code],
            "reliable": self.reliable,
        }


@dataclass
class TopologySnapshot:
    """A rede que o estimador vai usar, e como ela foi decidida."""

    version: int
    telemetry: list[SwitchTelemetry]
    resolved_closed: dict[int, bool]
    """switch_id -> fechado (True) / aberto (False), ja resolvido."""
    resolution_reason: dict[int, str] = field(default_factory=dict)
    unreliable_ids: list[int] = field(default_factory=list)
    policy: UnreliablePolicy = "last_known"

    @property
    def active_line_ids(self) -> list[int]:
        """Linhas energizadas segundo esta reconstrucao."""
        return sorted(
            sw.line_id
            for sw in self.telemetry
            if sw.line_id is not None and self.resolved_closed.get(sw.switch_id, True)
        )

    @property
    def open_line_ids(self) -> list[int]:
        return sorted(
            sw.line_id
            for sw in self.telemetry
            if sw.line_id is not None and not self.resolved_closed.get(sw.switch_id, True)
        )

    def differs_from(self, truth_closed: dict[int, bool]) -> list[int]:
        """Chaves em que a reconstrucao discorda da verdade.

        Lista vazia = o processador acertou a rede. Nao vazia = o estimador
        esta prestes a resolver o problema errado, e esta e a lista de ramos
        responsaveis. E a metrica central do caso de estudo de ataque de
        topologia.
        """
        return sorted(
            sw_id
            for sw_id, resolved in self.resolved_closed.items()
            if sw_id in truth_closed and bool(truth_closed[sw_id]) != bool(resolved)
        )

    def summary(self) -> dict[str, Any]:
        codes = [sw.status_code for sw in self.telemetry]
        return {
            "version": self.version,
            "policy": self.policy,
            "n_switches": len(self.telemetry),
            "n_closed": sum(1 for v in self.resolved_closed.values() if v),
            "n_open": sum(1 for v in self.resolved_closed.values() if not v),
            "n_unreliable": len(self.unreliable_ids),
            "unreliable_ids": self.unreliable_ids,
            "status_counts": {str(c): codes.count(c) for c in (0, 1, 2, 3)},
            "active_line_ids": self.active_line_ids,
            "open_line_ids": self.open_line_ids,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "switches": [
                {
                    **sw.to_dict(),
                    "resolved_closed": bool(self.resolved_closed.get(sw.switch_id, True)),
                    "resolution_reason": self.resolution_reason.get(sw.switch_id, "telemetria coerente"),
                }
                for sw in self.telemetry
            ],
        }


def process_topology(
    telemetry: list[SwitchTelemetry],
    *,
    policy: UnreliablePolicy = "last_known",
    last_known: dict[int, bool] | None = None,
    measured_flow_by_line: dict[int, float] | None = None,
    flow_threshold: float = 1e-3,
    version: int = 1,
    now_s: float = 0.0,
    trace: PipelineTrace | None = None,
) -> TopologySnapshot:
    """Reconstroi a topologia a partir dos contatos auxiliares.

    Para os codigos 0 e 1 nao ha decisao: a telemetria e coerente e vale. Para
    2 e 3, `policy` escolhe o que fazer, e cada opcao tem um custo diferente:

    - `last_known`: mantem o ultimo estado confiavel. E o comportamento de
      SCADA classico. Falha quando a chave de fato manobrou durante a falha da
      telemetria.
    - `assume_closed`: conservador para observabilidade (a rede fica mais
      conectada, o estimador tende a convergir), perigoso para operacao.
    - `assume_open`: conservador para seguranca operacional, tende a ilhar a
      rede e destruir a observabilidade.
    - `flow_inference`: decide pelo fluxo medido no ramo -- se passa corrente,
      a chave esta fechada. **E aqui que um agente atua**: e a unica politica
      que usa informacao de outra camada (as medicoes analogicas do RTDB) para
      resolver uma ambiguidade da camada de status. Requer que o ramo tenha
      medidor de fluxo; sem medidor, cai em `last_known`.
    """
    last_known = last_known or {}
    measured_flow_by_line = measured_flow_by_line or {}

    resolved: dict[int, bool] = {}
    reasons: dict[int, str] = {}
    unreliable: list[int] = []

    for sw in telemetry:
        code = sw.status_code

        # `closed` ja e None exatamente nos codigos nao conclusivos (0 e 3),
        # entao a decisao "tem leitura?" nao precisa repetir a tabela aqui.
        conclusive = sw.closed
        if conclusive is not None:
            resolved[sw.switch_id] = conclusive
            reasons[sw.switch_id] = f"telemetria conclusiva ({STATUS_LABEL[code]})"
            continue

        unreliable.append(sw.switch_id)
        decided, reason = _resolve_unreliable(
            sw, policy, last_known, measured_flow_by_line, flow_threshold
        )
        resolved[sw.switch_id] = decided
        reasons[sw.switch_id] = reason

        if trace is not None:
            trace.log(
                "topology", now_s, f"SW-{sw.switch_id}",
                f"chave {sw.name or sw.switch_id} em estado {code} "
                f"({STATUS_LABEL[code]}) -> resolvida como "
                f"{'CLOSED' if decided else 'OPEN'} por {reason}",
                level="warning",
                switch_id=sw.switch_id, status_code=code, policy=policy,
                resolved_closed=decided, reason=reason,
            )

    snapshot = TopologySnapshot(
        version=version, telemetry=list(telemetry), resolved_closed=resolved,
        resolution_reason=reasons, unreliable_ids=unreliable, policy=policy,
    )

    if trace is not None:
        trace.log(
            "topology", now_s, "SNAPSHOT",
            f"topology snapshot #{version}: {snapshot.summary()['n_closed']} fechadas, "
            f"{snapshot.summary()['n_open']} abertas, {len(unreliable)} nao confiaveis",
            **snapshot.summary(),
        )
    return snapshot


def _resolve_unreliable(
    sw: SwitchTelemetry,
    policy: UnreliablePolicy,
    last_known: dict[int, bool],
    measured_flow_by_line: dict[int, float],
    flow_threshold: float,
) -> tuple[bool, str]:
    if policy == "assume_closed":
        return True, "politica assume_closed"
    if policy == "assume_open":
        return False, "politica assume_open"

    if policy == "flow_inference":
        if sw.line_id is not None and sw.line_id in measured_flow_by_line:
            flow = abs(float(measured_flow_by_line[sw.line_id]))
            decided = flow > flow_threshold
            return decided, (
                f"inferencia por fluxo medido (|P|={flow:.4g} "
                f"{'>' if decided else '<='} {flow_threshold:g})"
            )
        # Sem medidor no ramo o agente nao tem o que inferir. Cair em
        # last_known em silencio seria enganoso; o motivo diz por que.
        fallback = last_known.get(sw.switch_id, True)
        return fallback, "sem medidor de fluxo no ramo -> ultimo estado conhecido"

    return last_known.get(sw.switch_id, True), "ultimo estado conhecido"
