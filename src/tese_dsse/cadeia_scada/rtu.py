"""Camada de RTU/IED: agrupa medicoes de campo em unidades remotas.

O que esta camada acrescenta em relacao a `field_measurements` cru:

1. **Point mapping.** Cada medicao ganha um `point_id` canonico
   (`P_BUS5`, `V_BUS3`, `PF_LINE2`), que e o nome pelo qual o SCADA a conhece.
   O ataque de corrupcao de point mapping vive exatamente aqui: trocar o
   `point_id` de duas medicoes validas produz um estado consistente e errado,
   sem nenhum valor fora da faixa.
2. **Agrupamento fisico.** Medicoes nao chegam uma a uma ao centro de
   controle; chegam por RTU. Comprometer *uma* RTU afeta um bloco inteiro de
   pontos correlacionados -- que e o que diferencia o ataque realista do
   outlier isolado da literatura classica de bad data.
3. **Taxa de varredura.** Uma RTU varre seus pontos com um periodo proprio, e
   o `source_timestamp` do dado nasce dessa varredura, nao do instante em que
   o operador aperta Run.

A taxa vem de `geracao_dados.measurement_layer.SENSOR_DEFAULTS`, que ja
modelava frequencia de publicacao por classe de sensor (PMU 30 Hz, SCADA 4 s,
AMI 15 min, smart meter 4x/dia). **So o `period_seconds` e lido dali** -- o
sigma continua vindo de `estimacao_estado.sensor_calibration`, e os dois
sistemas de sigma seguem separados como decidido em
`docs/governanca/decisoes_tecnicas.md`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from .traco import PipelineTrace

__all__ = [
    "PSEUDO_SCAN_PERIOD_S",
    "RTU",
    "RTUPoint",
    "SCAN_PERIOD_BY_KIND",
    "Quality",
    "build_points",
    "group_buses_into_rtus",
    "point_id_for",
    "scan_period_for",
]

Quality = Literal["good", "suspect", "bad"]

#: Uma pseudo-medicao nao e um medidor: e um perfil de carga historico
#: aplicado onde nao ha instrumentacao. Nao tem taxa de varredura fisica, mas
#: precisa de um numero para a cadeia funcionar. 15 min e a granularidade
#: tipica de um perfil de carga de distribuidora -- mesma ordem do AMI.
PSEUDO_SCAN_PERIOD_S = 15.0 * 60.0

#: Mapa das 4 classes do app (`pmu`/`scada`/`ami`/`pseudo`, minusculas) para as
#: classes de `SENSOR_DEFAULTS` (maiusculas). `pseudo` nao existe la porque
#: aquele modulo so descreve sensores fisicos.
_KIND_TO_SENSOR_CLASS = {"pmu": "PMU", "scada": "SCADA", "ami": "AMI"}


def _scan_period_table() -> dict[str, float]:
    """Le `period_seconds` de SENSOR_DEFAULTS, com fallback se o import falhar.

    O fallback existe porque esta camada precisa continuar funcionando se
    `geracao_dados` ganhar uma dependencia pesada -- os numeros sao os mesmos
    de SENSOR_DEFAULTS na data de escrita, e o teste
    `test_scan_period_bate_com_sensor_defaults` falha se divergirem.
    """
    table: dict[str, float] = {"pseudo": PSEUDO_SCAN_PERIOD_S}
    try:
        from ..geracao_dados.measurement_layer import SENSOR_DEFAULTS

        for kind, sensor_class in _KIND_TO_SENSOR_CLASS.items():
            table[kind] = float(SENSOR_DEFAULTS[sensor_class].period_seconds)
    except Exception:  # pragma: no cover - caminho de degradacao
        table.update({"pmu": 1.0 / 30.0, "scada": 4.0, "ami": 15.0 * 60.0})
    return table


SCAN_PERIOD_BY_KIND: dict[str, float] = _scan_period_table()


def scan_period_for(meter_kind: str) -> float:
    """Periodo de varredura (s) da classe de medidor."""
    return SCAN_PERIOD_BY_KIND.get(meter_kind, SCAN_PERIOD_BY_KIND["scada"])


#: Prefixo do `point_id` por grandeza. Os codigos de grandeza sao os mesmos de
#: `ACMeasurement.kind` usados pelo estimador, para nao existir um segundo
#: vocabulario de grandezas no repo.
_POINT_PREFIX = {
    "p_inj": "P",
    "q_inj": "Q",
    "v_bus": "V",
    "va_bus": "VA",
    "p_branch": "PF",
    "q_branch": "QF",
    "switch_status": "SW",
}


def point_id_for(quantity: str, bus_id: int | None, line_id: int | None, ordinal: int) -> str:
    """Nome canonico do ponto SCADA.

    `ordinal` desempata os casos em que o mesmo par (grandeza, equipamento)
    gera mais de um ponto -- um medidor de linha produz P_ij *e* P_ji, e os
    dois sao `p_branch` da mesma `line_id`. Sem o desempate, o segundo
    sobrescreveria o primeiro no RTDB e a cadeia perderia metade das medicoes
    de fluxo em silencio.
    """
    prefix = _POINT_PREFIX.get(quantity, quantity.upper())
    if bus_id is not None:
        return f"{prefix}_BUS{bus_id}"
    if line_id is not None:
        return f"{prefix}_LINE{line_id}_{ordinal}"
    return f"{prefix}_{ordinal}"


@dataclass(frozen=True)
class RTUPoint:
    """Uma medicao de campo ja mapeada para um ponto de uma RTU.

    Imutavel: os ataques e a transmissao produzem copias (via
    `dataclasses.replace`), nunca mutam o original. E o que permite comparar o
    ponto limpo com o ponto atacado no fim da corrida sem ter guardado uma
    copia manual de tudo.
    """

    point_id: str
    sensor_id: str
    rtu_id: str
    quantity: str
    """Grandeza medida: p_inj/q_inj/v_bus/va_bus/p_branch/q_branch/switch_status."""
    equipment_id: str
    """`BUS-5`, `LINE-2` -- o equipamento fisico, no vocabulario do operador."""
    phase: str
    value: float
    sigma: float
    source_timestamp_s: float
    meter_kind: str
    quality: Quality = "good"
    bus_id: int | None = None
    line_id: int | None = None
    measurement_index: int | None = None
    """Indice da medicao no vetor z original -- a ponte de volta para o
    estimador. `None` para pontos que nao sao medicao analogica (status de
    switch, por exemplo)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "point_id": self.point_id,
            "sensor_id": self.sensor_id,
            "rtu_id": self.rtu_id,
            "quantity": self.quantity,
            "equipment_id": self.equipment_id,
            "phase": self.phase,
            "value": round(float(self.value), 6),
            "sigma": round(float(self.sigma), 8),
            "source_timestamp_s": round(float(self.source_timestamp_s), 6),
            "meter_kind": self.meter_kind,
            "quality": self.quality,
            "bus_id": self.bus_id,
            "line_id": self.line_id,
            "measurement_index": self.measurement_index,
        }


@dataclass
class RTU:
    """Unidade remota: um grupo de pontos com uma taxa de varredura."""

    rtu_id: str
    bus_ids: list[int] = field(default_factory=list)
    points: list[RTUPoint] = field(default_factory=list)
    scan_period_s: float = 4.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rtu_id": self.rtu_id,
            "bus_ids": sorted(self.bus_ids),
            "n_points": len(self.points),
            "scan_period_s": round(float(self.scan_period_s), 6),
            "point_ids": [p.point_id for p in self.points],
        }


def group_buses_into_rtus(bus_ids: list[int], n_rtus: int) -> dict[int, str]:
    """Reparte barras entre `n_rtus` unidades, em blocos contiguos.

    Estrategia deliberadamente simples e deterministica. Para um agrupamento
    com sentido eletrico (por alimentador ou por ilha), a rota passa o mapa
    produzido por `agentes.partition_feeder_radial`/`partition_spectral` em vez
    de chamar esta funcao -- o particionador ja existe e nao vale duplicar a
    heuristica aqui.
    """
    ordered = sorted(bus_ids)
    if not ordered:
        return {}
    n = max(1, min(int(n_rtus), len(ordered)))
    per = math.ceil(len(ordered) / n)
    mapping: dict[int, str] = {}
    for i, bus in enumerate(ordered):
        mapping[bus] = f"RTU-{i // per + 1}"
    return mapping


def build_points(
    measurements_meta: list[dict[str, Any]],
    values: list[float],
    sigmas: list[float],
    bus_to_rtu: dict[int, str],
    *,
    line_to_rtu: dict[int, str] | None = None,
    t0_s: float = 0.0,
    trace: PipelineTrace | None = None,
) -> tuple[list[RTUPoint], dict[str, RTU]]:
    """Converte o vetor de medicoes do estimador em pontos de RTU.

    `measurements_meta[i]` e o dict `{busId, lineId, meterKind, quantity}` que
    `build_configured_ac_measurements`/`configured_dc_rows` ja devolvem -- esta
    camada nao inventa medicao nenhuma, so reetiqueta o que o app ja produzia,
    o que garante que o vetor z reconstruido no fim da cadeia seja comparavel
    ao vetor z que `/api/estimation/run` monta direto.

    O `source_timestamp` de cada ponto e `t0 + (indice_na_rtu % janela) * ...`?
    Nao: e `t0 - atraso_de_varredura`, onde o atraso de varredura e a posicao
    do ponto dentro do ciclo de varredura da sua RTU. Uma RTU com periodo de
    4 s que varre 8 pontos le o primeiro 4 s antes de fechar o ciclo e o
    ultimo praticamente agora -- e essa dispersao, e nao o atraso de rede, que
    ja torna o snapshot do SCADA inconsistente mesmo com comunicacao perfeita.
    """
    line_to_rtu = line_to_rtu or {}
    points: list[RTUPoint] = []
    rtus: dict[str, RTU] = {}
    ordinal_by_key: dict[tuple[str, int | None, int | None], int] = {}
    position_in_rtu: dict[str, int] = {}

    for idx, meta in enumerate(measurements_meta):
        bus_id = meta.get("busId")
        line_id = meta.get("lineId")
        quantity = str(meta.get("quantity", "unknown"))
        meter_kind = str(meta.get("meterKind", "scada"))

        if bus_id is not None:
            rtu_id = bus_to_rtu.get(int(bus_id), "RTU-1")
            equipment_id = f"BUS-{bus_id}"
        elif line_id is not None:
            rtu_id = line_to_rtu.get(int(line_id), _rtu_for_line(line_id, bus_to_rtu))
            equipment_id = f"LINE-{line_id}"
        else:  # pragma: no cover - meta sempre traz bus ou line
            rtu_id, equipment_id = "RTU-1", "UNKNOWN"

        key = (quantity, bus_id, line_id)
        ordinal_by_key[key] = ordinal_by_key.get(key, 0) + 1
        ordinal = ordinal_by_key[key]

        scan_period = scan_period_for(meter_kind)
        slot = position_in_rtu.get(rtu_id, 0)
        position_in_rtu[rtu_id] = slot + 1
        # Envelhecimento dentro do ciclo: o ponto lido no inicio da varredura
        # e o mais velho. Limitado a um ciclo -- uma RTU nao acumula atraso
        # indefinidamente, ela recomeca a varredura.
        scan_age = (slot % max(1, len(measurements_meta))) / max(1, len(measurements_meta))
        source_ts = t0_s - scan_period * scan_age

        point = RTUPoint(
            point_id=point_id_for(quantity, bus_id, line_id, ordinal),
            sensor_id=f"S{idx + 1}",
            rtu_id=rtu_id,
            quantity=quantity,
            equipment_id=equipment_id,
            phase="abc",
            value=float(values[idx]),
            sigma=float(sigmas[idx]),
            source_timestamp_s=float(source_ts),
            meter_kind=meter_kind,
            bus_id=int(bus_id) if bus_id is not None else None,
            line_id=int(line_id) if line_id is not None else None,
            measurement_index=idx,
        )
        points.append(point)

        rtu = rtus.get(rtu_id)
        if rtu is None:
            rtu = RTU(rtu_id=rtu_id, scan_period_s=scan_period)
            rtus[rtu_id] = rtu
        rtu.points.append(point)
        rtu.scan_period_s = max(rtu.scan_period_s, scan_period)
        if point.bus_id is not None and point.bus_id not in rtu.bus_ids:
            rtu.bus_ids.append(point.bus_id)

        if trace is not None:
            trace.log(
                "rtu",
                source_ts,
                point.sensor_id,
                f"{point.sensor_id} mapeado para {point.point_id} na {rtu_id}",
                point_id=point.point_id,
                rtu_id=rtu_id,
                quantity=quantity,
                equipment_id=equipment_id,
                meter_kind=meter_kind,
            )

    return points, rtus


def _rtu_for_line(line_id: int, bus_to_rtu: dict[int, str]) -> str:
    """RTU de um medidor de linha sem mapa explicito.

    Cai na RTU da menor barra conhecida: um TC/TP de linha esta fisicamente no
    painel de uma das subestacoes que a linha conecta, nunca no meio do vao.
    """
    if not bus_to_rtu:
        return "RTU-1"
    return bus_to_rtu[min(bus_to_rtu)]


def apply_point_mapping_swap(points: list[RTUPoint], point_a: str, point_b: str) -> list[RTUPoint]:
    """Troca o `point_id` de dois pontos -- ataque de corrupcao de mapeamento.

    Fica aqui, e nao em `seguranca/ataques.py`, porque e uma operacao sobre a
    estrutura da propria camada de RTU; `ataques.py` a invoca. O efeito e
    silencioso por construcao: nenhum valor sai da faixa plausivel, os dois
    pontos continuam existindo, e so o estimador (que le o valor de `P_BUS5` e
    o atribui a barra 5) percebe alguma coisa, na forma de residuos espalhados.
    """
    idx_a = next((i for i, p in enumerate(points) if p.point_id == point_a), None)
    idx_b = next((i for i, p in enumerate(points) if p.point_id == point_b), None)
    if idx_a is None or idx_b is None:
        return points
    out = list(points)
    out[idx_a] = replace(points[idx_a], value=float(points[idx_b].value))
    out[idx_b] = replace(points[idx_b], value=float(points[idx_a].value))
    return out
