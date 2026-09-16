"""Catalogo de ataques e falhas por camada da cadeia operacional.

Uso academico/defensivo: avaliar a robustez do estimador e das defesas, no
mesmo espirito do que `estimacao_estado/ac_bad_data.py` ja faz para erro de
medida e de parametro. O que muda aqui e o **ponto de injecao**: em vez de
corromper o vetor `z` pronto, corrompe-se a camada onde a falha realmente
acontece, e deixa-se a propagacao acontecer sozinha ate o estimador.

Essa distincao e o ponto da plataforma. Um bias somado direto em `z` produz um
outlier isolado que o LNR acha em uma iteracao. O *mesmo* bias aplicado a uma
RTU comprometida corrompe um bloco de medicoes correlacionadas e produz uma
assinatura espalhada, indistinguivel a olho nu de um erro de parametro -- que
e exatamente a colisao de assinaturas que a tese ataca (ver
`docs/planejamento/o2_assinatura.md`).

Cada ataque declara em que camada opera. A camada define quando ele e
aplicado no pipeline, e nao ha ataque que atravesse duas camadas: se algo
precisa disso, sao dois ataques coordenados, que e como funciona na pratica.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from ..cadeia_scada.canal import ChannelConfig
from ..cadeia_scada.processador_topologia import SwitchTelemetry
from ..cadeia_scada.rtu import RTUPoint, apply_point_mapping_swap
from ..cadeia_scada.traco import PipelineTrace

__all__ = [
    "ATTACK_CATALOG",
    "AttackLayer",
    "AttackSpec",
    "apply_channel_attacks",
    "apply_sensor_attacks",
    "apply_topology_attacks",
    "catalog_as_list",
]

AttackLayer = Literal["measurement", "rtu", "channel", "topology"]


@dataclass(frozen=True)
class AttackSpec:
    """Descricao de um ataque -- o que a UI lista e o que a rota valida."""

    attack_id: str
    layer: AttackLayer
    label: str
    description: str
    target_kind: str
    """O que `target` significa: 'sensor_id', 'rtu_id', 'switch_id' ou 'none'."""
    params: dict[str, str] = field(default_factory=dict)
    stealthy: bool = False
    """True quando o ataque nao produz nenhum valor fora de faixa -- ou seja,
    quando nenhuma checagem de plausibilidade local o pega, so a analise de
    consistencia entre camadas."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attack_id": self.attack_id,
            "layer": self.layer,
            "label": self.label,
            "description": self.description,
            "target_kind": self.target_kind,
            "params": self.params,
            "stealthy": self.stealthy,
        }


ATTACK_CATALOG: dict[str, AttackSpec] = {
    # ── camada de medicao ────────────────────────────────────────────────────
    "sensor_bias": AttackSpec(
        attack_id="sensor_bias", layer="measurement", label="Sensor bias",
        description=(
            "Soma um offset constante ao valor de um sensor. E o erro grosseiro "
            "classico da literatura de bad data -- serve de linha de base para "
            "comparar com os ataques de camada mais profunda."
        ),
        target_kind="sensor_id",
        params={"magnitude_sigma": "Offset em multiplos do sigma da medicao (default 5)"},
    ),
    "sensor_scaling": AttackSpec(
        attack_id="sensor_scaling", layer="measurement", label="Scaling attack",
        description=(
            "Multiplica a leitura por um fator. Diferente do bias, o erro cresce "
            "com o carregamento: passa despercebido em carga leve e dispara em "
            "carga pesada, o que quebra limiar fixo calibrado fora do pico."
        ),
        target_kind="sensor_id",
        params={"factor": "Fator multiplicativo (default 1.1)"},
    ),
    "sensor_freeze": AttackSpec(
        attack_id="sensor_freeze", layer="measurement", label="Frozen sensor",
        description=(
            "Congela a leitura num valor fixo. O dado continua chegando com "
            "qualidade boa e timestamp novo -- so o conteudo parou. Invisivel "
            "para qualquer checagem de freshness."
        ),
        target_kind="sensor_id",
        params={"frozen_value": "Valor congelado (default: o valor atual)"},
        stealthy=True,
    ),
    "sensor_failure": AttackSpec(
        attack_id="sensor_failure", layer="measurement", label="Sensor failure",
        description=(
            "O sensor para de reportar: o ponto e marcado como bad e sai do "
            "vetor z. Testa perda de observabilidade, nao corrupcao de dado."
        ),
        target_kind="sensor_id", params={},
    ),
    "false_data_injection": AttackSpec(
        attack_id="false_data_injection", layer="measurement",
        label="False data injection",
        description=(
            "Substitui a leitura por um valor escolhido pelo atacante. Sem "
            "restricao de furtividade nesta versao: o FDI construido no "
            "espaco-coluna de H (que nao altera o residuo) e trabalho do modulo "
            "de FDIA furtivo previsto no __init__ deste pacote."
        ),
        target_kind="sensor_id",
        params={"value": "Valor injetado (obrigatorio)"},
    ),
    # ── camada de RTU ────────────────────────────────────────────────────────
    "rtu_compromise": AttackSpec(
        attack_id="rtu_compromise", layer="rtu", label="RTU compromise",
        description=(
            "Aplica um bias a TODOS os pontos de uma RTU. E o cenario que "
            "distingue esta plataforma do bad data classico: o erro fica "
            "correlacionado dentro de um bloco fisico, e a assinatura no "
            "residuo passa a se parecer com erro de modelo, nao com outlier."
        ),
        target_kind="rtu_id",
        params={"magnitude_sigma": "Offset em multiplos do sigma de cada ponto (default 3)"},
    ),
    "point_mapping_corruption": AttackSpec(
        attack_id="point_mapping_corruption", layer="rtu",
        label="SCADA point mapping corruption",
        description=(
            "Troca os valores de dois pontos do SCADA. Nenhum valor sai da faixa "
            "plausivel, nenhum ponto some, nenhum timestamp e velho -- e o "
            "estimador recebe a potencia da barra A atribuida a barra B."
        ),
        target_kind="sensor_id",
        params={"other_point_id": "point_id do segundo ponto da troca (obrigatorio)"},
        stealthy=True,
    ),
    "bad_timestamp": AttackSpec(
        attack_id="bad_timestamp", layer="rtu", label="Bad timestamp",
        description=(
            "Adultera o source_timestamp do ponto. Um timestamp adiantado faz um "
            "dado velho parecer novo e escapar da checagem de stale; um atrasado "
            "faz um dado bom ser descartado."
        ),
        target_kind="sensor_id",
        params={"offset_s": "Deslocamento em segundos, positivo ou negativo (default -30)"},
        stealthy=True,
    ),
    # ── camada de comunicacao ────────────────────────────────────────────────
    "delay_attack": AttackSpec(
        attack_id="delay_attack", layer="channel", label="Delay attack",
        description=(
            "Atrasa seletivamente o trafego de uma RTU. Todas as medicoes seguem "
            "legitimas e corretas; o que fica errado e a simultaneidade do "
            "snapshot que o SCADA entrega ao estimador."
        ),
        target_kind="rtu_id",
        params={"delay_ms": "Atraso imposto ao enlace, em ms (default 5000)"},
        stealthy=True,
    ),
    "packet_loss": AttackSpec(
        attack_id="packet_loss", layer="channel", label="Packet loss",
        description=(
            "Eleva a probabilidade de perda no enlace. Perda alta o bastante "
            "derruba a redundancia abaixo do necessario e a rede deixa de ser "
            "observavel -- e o gatilho do 'engineer cry' do agente de "
            "observabilidade."
        ),
        target_kind="none",
        params={"drop_probability": "Probabilidade de perda por pacote, 0..1 (default 0.2)"},
    ),
    # ── camada de topologia ──────────────────────────────────────────────────
    "breaker_status_falsification": AttackSpec(
        attack_id="breaker_status_falsification", layer="topology",
        label="Breaker status falsification",
        description=(
            "Inverte os dois contatos de um disjuntor de forma COERENTE (52a e "
            "52b continuam complementares). O processador nao tem como suspeitar "
            "-- o status parece perfeito, so descreve outra rede. Reconstroi uma "
            "Ybus errada e o estimador resolve corretamente o problema errado."
        ),
        target_kind="switch_id", params={}, stealthy=True,
    ),
    "contact_desync": AttackSpec(
        attack_id="contact_desync", layer="topology", label="Contact desync (Intermediate / Indeterminate)",
        description=(
            "Quebra a complementaridade dos contatos, levando o double-bit ao "
            "codigo 0 (Intermediate) ou 3 (Indeterminate). Nao mente sobre a rede: "
            "destroi a certeza sobre ela, e forca o processador a decidir por "
            "politica. E o cenario em que a atuacao de um agente (inferencia por "
            "fluxo medido) muda o resultado."
        ),
        target_kind="switch_id",
        params={"mode": "'both_off' (codigo 0, Intermediate) ou 'both_on' (codigo 3, Indeterminate); default both_on"},
    ),
}


def catalog_as_list() -> list[dict[str, Any]]:
    """Catalogo serializado, agrupavel por camada na UI."""
    return [spec.to_dict() for spec in ATTACK_CATALOG.values()]


def _matches(point: RTUPoint, target: str) -> bool:
    """Um alvo de camada de medicao casa por sensor_id ou por point_id.

    Aceitar os dois evita que o usuario precise saber qual dos dois nomes a UI
    mostrou -- `S17` e `P_BUS5` designam o mesmo dado em pontos diferentes da
    cadeia.
    """
    return target in (point.sensor_id, point.point_id)


def apply_sensor_attacks(
    points: list[RTUPoint],
    attacks: list[dict[str, Any]],
    *,
    trace: PipelineTrace | None = None,
) -> list[RTUPoint]:
    """Aplica os ataques das camadas `measurement` e `rtu` sobre os pontos.

    As duas camadas sao aplicadas na mesma passagem, nesta ordem: primeiro os
    de medicao (que atingem um sensor), depois os de RTU (que atingem um
    bloco). Um ataque de RTU aplicado depois de um de sensor soma sobre ele --
    e o comportamento pretendido para o cenario coordenado.
    """
    out = list(points)

    for atk in [a for a in attacks if ATTACK_CATALOG.get(a.get("attack_id", ""), None)
                and ATTACK_CATALOG[a["attack_id"]].layer == "measurement"]:
        out = _apply_one_measurement_attack(out, atk, trace)

    for atk in [a for a in attacks if ATTACK_CATALOG.get(a.get("attack_id", ""), None)
                and ATTACK_CATALOG[a["attack_id"]].layer == "rtu"]:
        out = _apply_one_rtu_attack(out, atk, trace)

    return out


def _apply_one_measurement_attack(
    points: list[RTUPoint], atk: dict[str, Any], trace: PipelineTrace | None
) -> list[RTUPoint]:
    attack_id = atk["attack_id"]
    target = str(atk.get("target", ""))
    params = atk.get("params") or {}
    out = list(points)

    for i, p in enumerate(points):
        if not _matches(p, target):
            continue

        if attack_id == "sensor_bias":
            mag = float(params.get("magnitude_sigma", 5.0))
            new_value = p.value + mag * p.sigma
            out[i] = replace(p, value=new_value)
            _log(trace, "measurement", p, f"bias de {mag}sigma: {p.value:.4f} -> {new_value:.4f}",
                 attack_id=attack_id, magnitude_sigma=mag)

        elif attack_id == "sensor_scaling":
            factor = float(params.get("factor", 1.1))
            new_value = p.value * factor
            out[i] = replace(p, value=new_value)
            _log(trace, "measurement", p, f"scaling x{factor}: {p.value:.4f} -> {new_value:.4f}",
                 attack_id=attack_id, factor=factor)

        elif attack_id == "sensor_freeze":
            frozen = float(params.get("frozen_value", p.value))
            out[i] = replace(p, value=frozen)
            _log(trace, "measurement", p, f"sensor congelado em {frozen:.4f}",
                 attack_id=attack_id, frozen_value=frozen)

        elif attack_id == "sensor_failure":
            out[i] = replace(p, quality="bad")
            _log(trace, "measurement", p, "sensor em falha -> quality=bad, sai do vetor z",
                 attack_id=attack_id, level="error")

        elif attack_id == "false_data_injection":
            if "value" not in params:
                continue
            injected = float(params["value"])
            out[i] = replace(p, value=injected)
            _log(trace, "measurement", p, f"FDI: {p.value:.4f} -> {injected:.4f}",
                 attack_id=attack_id, injected_value=injected)

    return out


def _apply_one_rtu_attack(
    points: list[RTUPoint], atk: dict[str, Any], trace: PipelineTrace | None
) -> list[RTUPoint]:
    attack_id = atk["attack_id"]
    target = str(atk.get("target", ""))
    params = atk.get("params") or {}

    if attack_id == "point_mapping_corruption":
        other = str(params.get("other_point_id", ""))
        source = next((p for p in points if _matches(p, target)), None)
        if source is None or not other:
            return points
        out = apply_point_mapping_swap(points, source.point_id, other)
        if trace is not None and out is not points:
            trace.log(
                "rtu", source.source_timestamp_s, source.sensor_id,
                f"point mapping corrompido: {source.point_id} <-> {other} (valores trocados)",
                level="error", attack_id=attack_id, other_point_id=other,
            )
        return out

    out = list(points)
    for i, p in enumerate(points):
        if attack_id == "rtu_compromise":
            if p.rtu_id != target:
                continue
            mag = float(params.get("magnitude_sigma", 3.0))
            new_value = p.value + mag * p.sigma
            out[i] = replace(p, value=new_value)
            _log(trace, "rtu", p, f"RTU {target} comprometida: bias de {mag}sigma aplicado",
                 attack_id=attack_id, magnitude_sigma=mag, level="error")

        elif attack_id == "bad_timestamp":
            if not _matches(p, target):
                continue
            offset = float(params.get("offset_s", -30.0))
            out[i] = replace(p, source_timestamp_s=p.source_timestamp_s + offset)
            _log(trace, "rtu", p, f"timestamp adulterado em {offset:+.1f} s",
                 attack_id=attack_id, offset_s=offset)

    return out


def apply_channel_attacks(config: ChannelConfig, attacks: list[dict[str, Any]]) -> ChannelConfig:
    """Devolve uma nova ChannelConfig com os ataques de canal aplicados.

    Nao muta a configuracao original: a UI mostra lado a lado o canal nominal
    e o canal sob ataque, e isso exige que os dois objetos coexistam.
    """
    per_rtu = dict(config.per_rtu_delay_ms)
    drop = config.drop_probability

    for atk in attacks:
        spec = ATTACK_CATALOG.get(atk.get("attack_id", ""))
        if spec is None or spec.layer != "channel":
            continue
        params = atk.get("params") or {}
        if spec.attack_id == "delay_attack":
            per_rtu[str(atk.get("target", ""))] = float(params.get("delay_ms", 5000.0))
        elif spec.attack_id == "packet_loss":
            drop = float(params.get("drop_probability", 0.2))

    return replace(config, per_rtu_delay_ms=per_rtu, drop_probability=drop)


def apply_topology_attacks(
    telemetry: list[SwitchTelemetry],
    attacks: list[dict[str, Any]],
    *,
    now_s: float = 0.0,
    trace: PipelineTrace | None = None,
) -> list[SwitchTelemetry]:
    """Adultera os contatos auxiliares antes do processador de topologia."""
    out = list(telemetry)

    for atk in attacks:
        spec = ATTACK_CATALOG.get(atk.get("attack_id", ""))
        if spec is None or spec.layer != "topology":
            continue
        try:
            target_id = int(atk.get("target"))
        except (TypeError, ValueError):
            continue
        params = atk.get("params") or {}

        for i, sw in enumerate(out):
            if sw.switch_id != target_id:
                continue

            if spec.attack_id == "breaker_status_falsification":
                new_sw = replace(sw, contact_a=1 - int(bool(sw.contact_a)),
                                 contact_b=1 - int(bool(sw.contact_b)))
                out[i] = new_sw
                if trace is not None:
                    trace.log(
                        "topology", now_s, f"SW-{sw.switch_id}",
                        f"status falsificado: chave realmente "
                        f"{'FECHADA' if sw.status_code == 2 else 'ABERTA'}, "
                        f"reportada como {'FECHADA' if new_sw.status_code == 2 else 'ABERTA'} "
                        "-- contatos seguem coerentes, o processador nao tem como suspeitar",
                        level="error", attack_id=spec.attack_id, switch_id=sw.switch_id,
                        true_status=sw.status_code, reported_status=new_sw.status_code,
                    )

            elif spec.attack_id == "contact_desync":
                mode = str(params.get("mode", "both_on"))
                bit = 0 if mode == "both_off" else 1
                out[i] = replace(sw, contact_a=bit, contact_b=bit)
                if trace is not None:
                    trace.log(
                        "topology", now_s, f"SW-{sw.switch_id}",
                        f"contatos dessincronizados ({mode}) -> estado "
                        f"{out[i].status_code}, decisao passa para a politica",
                        level="warning", attack_id=spec.attack_id,
                        switch_id=sw.switch_id, mode=mode,
                    )

    return out


def _log(
    trace: PipelineTrace | None, layer: str, point: RTUPoint, message: str,
    *, level: str = "warning", **details: Any,
) -> None:
    if trace is None:
        return
    trace.log(
        layer, point.source_timestamp_s, point.sensor_id,  # type: ignore[arg-type]
        f"{point.point_id}: {message}", level=level,  # type: ignore[arg-type]
        point_id=point.point_id, rtu_id=point.rtu_id, **details,
    )
