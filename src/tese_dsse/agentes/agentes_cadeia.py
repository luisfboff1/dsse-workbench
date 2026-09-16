"""Agentes cross-layer: um por camada da cadeia operacional.

Os agentes que ja existiam em `tipos_agentes.py` sao **por ilha**: cada cluster
da rede hospeda um agente de observabilidade, um estimador, um de bad data. A
particao ali e geografica.

Estes sao outra coisa. A particao aqui e **por camada da cadeia**, e o que eles
produzem nao e uma estimativa, e um juizo sobre a confiabilidade do que a
camada entregou. Os dois eixos sao ortogonais e coexistem: uma ilha pode ter
seus tres agentes locais enquanto o Communication Agent, que e global, observa
o enlace daquela ilha.

## Por que a cadeia de propagacao e o produto

Cada agente isolado e uma checagem trivial -- "o atraso passou do limite", "o
residuo passou do limiar". O que nenhum deles faz sozinho e explicar por que o
estado nao merece confianca. Isso so aparece quando o juizo de um vira entrada
do proximo:

    Communication Agent ve atraso anormal na RTU-3
      -> SCADA Agent rebaixa os pontos daquela RTU a suspect
        -> Estimation Agent perde redundancia e aumenta a incerteza
          -> Control Agent recusa a acao de controle agressiva

E o argumento central do eixo multiagente da tese: a decisao de nao atuar nao
e tomada por nenhum agente sozinho, e nenhum limiar fixo produziria a mesma
decisao, porque cada camada isolada estava dentro do seu proprio limite.

Os agentes NAO recalculam nada da cadeia. Recebem os artefatos que as camadas
ja produziram e emitem `AgentMessage`s. Desligar a camada de agentes nao muda
um numero sequer do resultado da cadeia -- e por isso que comparar "com" e
"sem" agentes e legitimo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .base import AgentMessage

__all__ = [
    "ChainAgentTeam",
    "Finding",
    "Recommendation",
    "run_chain_agents",
]

Severity = Literal["ok", "info", "warning", "critical"]

#: Ordem de execucao. E a ordem da propria cadeia: um agente so pode reagir ao
#: que os anteriores ja concluiram.
AGENT_ORDER: tuple[str, ...] = (
    "field", "communication", "scada", "topology", "estimation", "control",
)

#: Recomendacao final do Control Agent. A escala e deliberadamente grossa --
#: um operador nao age sobre uma probabilidade, age sobre "posso, posso com
#: ressalva, ou nao posso".
Recommendation = Literal["dispatch", "derate", "block"]


@dataclass
class Finding:
    """Uma conclusao de um agente sobre a sua camada."""

    agent: str
    layer: str
    severity: Severity
    title: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)
    caused_by: list[str] = field(default_factory=list)
    """IDs de mensagens de agentes anteriores que levaram a esta conclusao.
    Vazio = o agente chegou nela sozinho, olhando so a propria camada."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "layer": self.layer,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "evidence": self.evidence,
            "caused_by": self.caused_by,
        }


@dataclass
class ChainAgentTeam:
    """Executa os agentes em ordem de camada, propagando mensagens."""

    delay_threshold_ms: float = 1000.0
    loss_threshold: float = 0.05
    spread_threshold_s: float | None = None
    """`None` = deriva do ciclo de varredura das proprias RTUs (recomendado).

    Um limiar fixo nao funciona aqui, e a primeira versao deste modulo errou
    exatamente nisso: com 1,0 s fixo, uma cadeia perfeitamente saudavel de
    SCADA (periodo de varredura de 4 s) reportava snapshot inconsistente e o
    Control Agent bloqueava todo despacho. Um snapshot que cobre **um ciclo de
    varredura** e o comportamento normal de um SCADA, nao um sintoma; o que e
    anomalo e cobrir varios. Ver `_spread_threshold`."""
    spread_cycles: float = 1.5
    """Quantos ciclos de varredura de dispersao ainda sao normais."""
    voltage_plausible_pu: tuple[float, float] = (0.5, 1.5)

    findings: list[Finding] = field(default_factory=list)
    messages: list[AgentMessage] = field(default_factory=list)
    _inbox: dict[str, list[AgentMessage]] = field(default_factory=dict)

    # ── infraestrutura ───────────────────────────────────────────────────────

    def _emit(self, sender: str, recipient: str, mtype: str, payload: dict, priority="NORMAL") -> str:
        msg = AgentMessage(
            sender_id=sender, recipient_id=recipient, message_type=mtype,
            payload=payload, priority=priority,
        )
        self.messages.append(msg)
        self._inbox.setdefault(recipient, []).append(msg)
        return mtype

    def _received(self, agent: str, mtype: str | None = None) -> list[AgentMessage]:
        msgs = self._inbox.get(agent, [])
        return [m for m in msgs if mtype is None or m.message_type == mtype]

    def _add(self, **kw: Any) -> None:
        self.findings.append(Finding(**kw))

    # ── agentes ──────────────────────────────────────────────────────────────

    def field_agent(self, layers: dict) -> None:
        """Plausibilidade fisica das leituras de campo.

        Nao tem como saber se um valor esta *certo* -- so se e possivel. Uma
        tensao de 3 pu nao precisa de estimador para ser rejeitada.
        """
        rows = layers.get("measurement", {}).get("rows", [])
        lo, hi = self.voltage_plausible_pu
        implausible = [
            r for r in rows
            if r.get("quantity") == "v_bus" and not (lo <= float(r.get("z_field", 1.0)) <= hi)
        ]
        non_finite = [r for r in rows if not _finite(r.get("z_field"))]

        if implausible or non_finite:
            self._emit("Agent_Field", "Agent_SCADA", "IMPLAUSIBLE_READINGS", {
                "point_indices": [r["index"] for r in implausible + non_finite],
            }, priority="HIGH")
            self._add(
                agent="Agent_Field", layer="measurement", severity="critical",
                title=f"{len(implausible) + len(non_finite)} physically implausible reading(s)",
                detail=(
                    "Voltage outside the "
                    f"[{lo}, {hi}] pu band, or a non-finite value. No estimator should "
                    "receive this; the rejection is local and needs no redundancy."
                ),
                evidence={"indices": [r["index"] for r in implausible + non_finite]},
            )
        else:
            self._add(
                agent="Agent_Field", layer="measurement", severity="ok",
                title="Field readings within the physical band",
                detail=f"{len(rows)} measurements checked for local plausibility.",
                evidence={"n_measurements": len(rows)},
            )

    def communication_agent(self, layers: dict) -> None:
        """Saude do enlace, por RTU."""
        stats = layers.get("channel", {}).get("statistics", {})
        by_rtu = stats.get("delay_ms_by_rtu", {})
        loss = float(stats.get("loss_rate", 0.0))

        degraded = {r: d for r, d in by_rtu.items() if float(d) > self.delay_threshold_ms}

        if degraded:
            self._emit("Agent_Comms", "Agent_SCADA", "DEGRADED_LINK", {
                "rtu_ids": sorted(degraded),
                "delay_ms": {r: round(float(d), 1) for r, d in degraded.items()},
            }, priority="HIGH")
            worst = max(degraded.items(), key=lambda kv: float(kv[1]))
            self._add(
                agent="Agent_Comms", layer="channel", severity="critical",
                title=f"Abnormal delay on {len(degraded)} RTU(s)",
                detail=(
                    f"{worst[0]} at {float(worst[1]):.0f} ms against a "
                    f"{self.delay_threshold_ms:.0f} ms limit. The measurements are still "
                    "legitimate; what was lost is the simultaneity of the snapshot."
                ),
                evidence={"delay_ms_by_rtu": degraded},
            )

        if loss > self.loss_threshold:
            self._emit("Agent_Comms", "Agent_Estimation", "REDUNDANCY_LOSS", {
                "loss_rate": loss,
            }, priority="HIGH")
            self._add(
                agent="Agent_Comms", layer="channel", severity="warning",
                title=f"Packet loss at {loss * 100:.1f}%",
                detail=(
                    f"Above the {self.loss_threshold * 100:.0f}% limit. Every lost packet "
                    "is one measurement fewer, and redundancy falls with it."
                ),
                evidence={"loss_rate": loss, "n_dropped": stats.get("n_dropped")},
            )

        if not degraded and loss <= self.loss_threshold:
            self._add(
                agent="Agent_Comms", layer="channel", severity="ok",
                title="Healthy link",
                detail=(
                    f"Peak delay {stats.get('delay_ms_max', 0):.0f} ms, loss "
                    f"{loss * 100:.1f}%."
                ),
                evidence=dict(stats),
            )

    def _spread_threshold(self, layers: dict) -> tuple[float, str]:
        """Limiar de dispersao do snapshot, e como ele foi obtido.

        Deriva do ciclo de varredura mais lento entre as RTUs da corrida: e o
        proprio sistema dizendo qual dispersao e normal. Um SCADA de 4 s produz
        snapshot com ate ~4 s de dispersao sem nada de errado; um de PMU, com
        milissegundos. Comparar os dois contra o mesmo numero fixo nao faz
        sentido.
        """
        if self.spread_threshold_s is not None:
            return float(self.spread_threshold_s), "limiar fixo configurado"

        periods = [
            float(r.get("scan_period_s", 0.0))
            for r in layers.get("rtu", {}).get("rtus", [])
        ]
        slowest = max(periods) if periods else 4.0
        return slowest * self.spread_cycles, (
            f"{self.spread_cycles:g} x o ciclo de varredura mais lento ({slowest:g} s)"
        )

    def scada_agent(self, layers: dict) -> None:
        """Frescor e qualidade do RTDB, escalando o que a comunicacao reportou."""
        summary = layers.get("rtdb", {}).get("summary", {})
        records = layers.get("rtdb", {}).get("records", [])
        spread = float(summary.get("timestamp_spread_s", 0.0))
        spread_limit, limit_origin = self._spread_threshold(layers)

        caused: list[str] = []
        escalated: list[str] = []
        for msg in self._received("Agent_SCADA", "DEGRADED_LINK"):
            caused.append(msg.message_type)
            rtus = set(msg.payload.get("rtu_ids", []))
            escalated = [r["point_id"] for r in records if r.get("rtu_id") in rtus]

        if escalated:
            # A escalada e o ponto da cadeia: sozinho, o SCADA veria pontos com
            # timestamp valido e qualidade boa. E o aviso da camada de baixo que
            # muda a leitura deles.
            self._emit("Agent_SCADA", "Agent_Estimation", "SUSPECT_POINTS", {
                "point_ids": escalated,
                "reason": "degraded link reported by the Communication Agent",
            }, priority="HIGH")
            self._add(
                agent="Agent_SCADA", layer="rtdb", severity="critical",
                title=f"{len(escalated)} point(s) downgraded to suspect on a link warning",
                detail=(
                    "These points carry a valid timestamp and good quality in the "
                    "database. On its own SCADA would have no reason to distrust them; "
                    "the reason came from the communication layer."
                ),
                evidence={"point_ids": escalated[:20], "n": len(escalated)},
                caused_by=caused,
            )

        n_stale = int(summary.get("n_stale", 0))
        n_bad = int(summary.get("n_bad", 0))
        if spread > spread_limit:
            self._emit("Agent_SCADA", "Agent_Estimation", "INCONSISTENT_SNAPSHOT", {
                "timestamp_spread_s": spread, "limit_s": spread_limit,
            }, priority="HIGH")
            self._add(
                agent="Agent_SCADA", layer="rtdb", severity="warning",
                title=f"Snapshot spans {spread:.2f} s",
                detail=(
                    f"Above the {spread_limit:.2f} s limit ({limit_origin}). The estimator "
                    "will treat measurements from different instants as simultaneous."
                ),
                evidence={
                    "timestamp_spread_s": spread, "limit_s": round(spread_limit, 3),
                    "limit_origin": limit_origin, "n_stale": n_stale,
                },
            )
        elif not escalated:
            self._add(
                agent="Agent_SCADA", layer="rtdb", severity="ok" if not n_bad else "warning",
                title="RTDB consistent" if not n_bad else f"{n_bad} unusable point(s)",
                detail=(
                    f"Spread {spread:.3f} s within expectation (limit {spread_limit:.2f} s, "
                    f"{limit_origin}); {n_stale} stale, {n_bad} bad out of "
                    f"{summary.get('n_points', 0)} points."
                ),
                evidence={**summary, "limit_s": round(spread_limit, 3)},
            )

    def topology_agent(self, layers: dict) -> None:
        """Coerencia do status de chave, e se ha como resolver o inconclusivo."""
        topo = layers.get("topology", {})
        summary = topo.get("summary", {})
        unreliable = summary.get("unreliable_ids", []) or []
        policy = summary.get("policy", "last_known")

        if unreliable:
            resolved_by_flow = [
                sw for sw in topo.get("switches", [])
                if sw.get("switch_id") in unreliable and "fluxo" in str(sw.get("resolution_reason", ""))
            ]
            self._emit("Agent_Topology", "Agent_Estimation", "UNRELIABLE_TOPOLOGY", {
                "switch_ids": unreliable, "policy": policy,
                "resolved_by_flow": [s["switch_id"] for s in resolved_by_flow],
            }, priority="CRITICAL")
            self._add(
                agent="Agent_Topology", layer="topology", severity="critical",
                title=f"{len(unreliable)} switch(es) with an inconclusive reading",
                detail=(
                    f"Double-bit codes 0/3, resolved by the '{policy}' policy. "
                    + (
                        f"{len(resolved_by_flow)} resolved by inference from measured flow, "
                        "the only decision here that uses another layer's information."
                        if resolved_by_flow else
                        "None can be resolved from measured flow: with no meter on the "
                        "branch, the decision is a guess."
                    )
                ),
                evidence={"switch_ids": unreliable, "policy": policy},
            )

        if not topo.get("matches_reality", True):
            # Este achado so existe porque a simulacao conhece a verdade. Num
            # sistema real ele e inalcancavel -- e exatamente por isso que a
            # plataforma existe: para medir o que o operador NAO teria como ver.
            self._add(
                agent="Agent_Topology", layer="topology", severity="critical",
                title="Reconstructed topology differs from the real one",
                detail=(
                    f"Switches {topo.get('mismatched_switch_ids')}. Outside the simulator "
                    "this finding would be invisible: no field data would reveal it."
                ),
                evidence={"mismatched_switch_ids": topo.get("mismatched_switch_ids")},
            )
        elif not unreliable:
            self._add(
                agent="Agent_Topology", layer="topology", severity="ok",
                title="Every switch reading is conclusive",
                detail=f"{summary.get('n_switches', 0)} switches, none in code 0 or 3.",
                evidence=dict(summary),
            )

    def estimation_agent(self, layers: dict) -> None:
        """Confianca no estado estimado, agregando o que veio das camadas acima."""
        est = layers.get("estimation") or {}
        caused = [m.message_type for m in self._received("Agent_Estimation")]

        if not est.get("ran"):
            self._emit("Agent_Estimation", "Agent_Control", "NO_STATE", {
                "reason": est.get("reason"),
            }, priority="CRITICAL")
            self._add(
                agent="Agent_Estimation", layer="estimation", severity="critical",
                title="No estimated state",
                detail=str(est.get("reason", "the estimator did not run")),
                evidence={}, caused_by=caused,
            )
            return

        chi2_failed = est.get("chi2_passed") is False
        redundancy = (
            float(est["n_measurements"]) / max(1, int(est.get("n_states", 1)))
            if est.get("n_measurements") else 0.0
        )

        confidence: Severity = "ok"
        motivos: list[str] = []
        if chi2_failed:
            confidence = "critical"
            motivos.append(f"J={est.get('J')} above the {est.get('chi2_limit')} threshold")
        if redundancy < 1.5:
            confidence = "critical" if confidence == "critical" else "warning"
            motivos.append(f"redundancy {redundancy:.2f} below 1.5")
        if caused:
            confidence = "critical" if confidence == "critical" else "warning"
            motivos.append(
                "upstream layers raised " + ", ".join(sorted(set(caused)))
            )

        if confidence != "ok":
            self._emit("Agent_Estimation", "Agent_Control", "LOW_CONFIDENCE_STATE", {
                "reasons": motivos, "chi2_passed": est.get("chi2_passed"),
                "redundancy": round(redundancy, 3),
            }, priority="CRITICAL" if confidence == "critical" else "HIGH")

        self._add(
            agent="Agent_Estimation", layer="estimation", severity=confidence,
            title=(
                "Estimated state is trustworthy" if confidence == "ok"
                else "Reduced confidence in the estimated state"
            ),
            detail=(
                "; ".join(motivos) if motivos
                else f"chi2 passed, redundancy {redundancy:.2f}, converged in "
                     f"{est.get('iterations')} iterations."
            ),
            evidence={
                "J": est.get("J"), "chi2_limit": est.get("chi2_limit"),
                "redundancy": round(redundancy, 3),
                "max_vm_error": est.get("max_vm_error"),
            },
            caused_by=caused,
        )

    def control_agent(self, layers: dict) -> Recommendation:
        """Decide se o estado merece confianca suficiente para agir sobre ele.

        E o unico agente que produz uma **acao**, e por isso o unico que precisa
        conviver com um falso negativo caro: bloquear um despacho legitimo custa
        dinheiro, despachar sobre um estado corrompido custa a rede.
        """
        opf = layers.get("opf")
        caused = [m.message_type for m in self._received("Agent_Control")]
        blocking = [m for m in self._received("Agent_Control") if m.priority == "CRITICAL"]

        # A propria camada de controle nao respondeu. Isto vem antes de tudo:
        # sem OPF nao existe setpoint, entao nao existe despacho a liberar,
        # independentemente de as camadas anteriores estarem limpas. Antes desta
        # verificacao o agente olhava so `n_hidden_violations` (que vale 0 numa
        # corrida que nem chegou a despachar) e devolvia "dispatch" com o OPF
        # falhado logo ao lado -- a tela dizia "pode atuar" embaixo de um alarme
        # de prioridade alta dizendo que o controle nao produziu resposta.
        opf_failed = (
            isinstance(opf, dict)
            and isinstance(opf.get("operator"), dict)
            and opf["operator"].get("converged") is False
        )

        if opf_failed:
            rec: Recommendation = "block"
            title = "Control action BLOCKED: the OPF produced no setpoint"
            detail = (
                "The control layer returned no answer on the reconstructed model, so "
                "there is no dispatch to authorise. "
                # `reason` traz o diagnostico de factibilidade numa segunda
                # linha (ver `diagnose_infeasibility`), que e justamente a parte
                # que o operador precisa ler; o painel de alarmes e uma linha so,
                # entao colapsa em vez de truncar.
                + " ".join(str(opf["operator"].get("reason") or "").split())
            )
            severity: Severity = "critical"
        elif blocking:
            rec = "block"
            title = "Control action BLOCKED"
            detail = (
                "The delivered state does not support a control action: "
                + "; ".join(sorted({m.message_type for m in blocking}))
                + ". No single layer was outside its own limit; the decision comes "
                "from the accumulation across layers."
            )
            severity = "critical"
        elif caused:
            rec = "derate"
            title = "Control action DERATED"
            detail = (
                "Upstream layers have raised flags ("
                + ", ".join(sorted(set(caused)))
                + "). Dispatch conservative actions only, no switching."
            )
            severity = "warning"
        else:
            rec = "dispatch"
            title = "Control action released"
            detail = "No layer raised a problem."
            severity = "ok"

        evidence: dict[str, Any] = {"recommendation": rec}
        if opf_failed:
            evidence["opf_converged"] = False
        if isinstance(opf, dict) and "n_hidden_violations" in opf:
            hidden = int(opf.get("n_hidden_violations", 0))
            evidence["n_hidden_violations"] = hidden
            evidence["max_setpoint_error_mw"] = opf.get("max_setpoint_error_mw")
            if hidden and rec == "dispatch":
                # Contradicao util: nenhum agente viu problema, e o despacho
                # mesmo assim deixou violacao invisivel. E o caso que motiva
                # medir a camada de controle em vez de parar no estimador.
                severity = "critical"
                title = "No alarm anywhere, and still a hidden violation"
                detail = (
                    f"{hidden} constraint(s) violated on the real network that the "
                    "operator's OPF considered satisfied. The upstream agents had no "
                    "way to notice: every layer was inside its own limit."
                )

        self._add(
            agent="Agent_Control", layer="opf", severity=severity,
            title=title, detail=detail, evidence=evidence, caused_by=caused,
        )
        return rec

    # ── execucao ─────────────────────────────────────────────────────────────

    def run(self, layers: dict) -> dict[str, Any]:
        self.field_agent(layers)
        self.communication_agent(layers)
        self.scada_agent(layers)
        self.topology_agent(layers)
        self.estimation_agent(layers)
        recommendation = self.control_agent(layers)

        worst = "ok"
        for f in self.findings:
            if f.severity == "critical":
                worst = "critical"
                break
            if f.severity == "warning":
                worst = "warning"

        return {
            "recommendation": recommendation,
            "worst_severity": worst,
            "findings": [f.to_dict() for f in self.findings],
            "messages": [
                {
                    "sender": m.sender_id, "recipient": m.recipient_id,
                    "type": m.message_type, "priority": m.priority,
                    "payload": m.payload, "bytes": m.bytes_size,
                }
                for m in self.messages
            ],
            "n_messages": len(self.messages),
            "total_bytes": sum(m.bytes_size for m in self.messages),
            "propagation": _propagation_chain(self.findings),
        }


def _propagation_chain(findings: list[Finding]) -> list[dict[str, Any]]:
    """So os achados que existem por causa de outra camada.

    E a narrativa que a UI mostra em destaque: a lista de decisoes que nenhum
    agente teria tomado olhando apenas a propria camada.
    """
    return [
        {"agent": f.agent, "layer": f.layer, "title": f.title, "caused_by": f.caused_by}
        for f in findings if f.caused_by
    ]


def _finite(v: Any) -> bool:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return x == x and abs(x) != float("inf")


def run_chain_agents(layers: dict, **thresholds: Any) -> dict[str, Any]:
    """Atalho: monta o time com os limiares dados e roda sobre os artefatos."""
    return ChainAgentTeam(**thresholds).run(layers)
