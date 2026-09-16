"""Calibracao de sigma por classe de sensor (PMU/SCADA/AMI/Pseudo) para
medicoes AC/DC de snapshot -- fonte unica compartilhada entre os notebooks
de simulacao (`notebooks/simulacao/*.ipynb`, via `ac_measurements.
synthetic_full_measurements_from_results(..., kind=...)`) e o backend do
app (`app/backend/services/measurement_kinds.py`, que so reexporta daqui
para nao quebrar os imports existentes nas rotas). Mudar um multiplicador
aqui muda os dois lugares juntos -- essa e a razao de existir.

Os multiplicadores nao sao valores de datasheet reais, sao proporcoes
relativas plausiveis usadas para modular o par (noise_level, sigma_min):
PMU mais preciso que SCADA, AMI mais ruidoso (medidor de consumo, nao de
qualidade de energia), pseudo-medicao (perfil de carga historico, nao
medidor fisico) a mais incerta de todas.

`v_sigma_mult` do SCADA e 0.2 (nao 1.0) de proposito: um sensor de tensao
(TP) e tipicamente bem mais preciso, em termos relativos, que uma medicao
de potencia (que soma o erro do TP *e* do TC, e TC degrada em carga
parcial) -- Abur & Exposito e a literatura do proprio Bretas usam essa
mesma ordem de assimetria (~0.2-0.5% tensao vs ~1-2% potencia).

Sistema separado de `geracao_dados/measurement_layer.py` (`SENSOR_DEFAULTS`),
que usa sigma ABSOLUTO fixo por classe (PMU/SCADA/AMI/SMART_METER) para
gerar datasets sinteticos multi-taxa -- proposito diferente (serie
temporal com timing realista por sensor), nao mexido aqui.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "MeasurementKind",
    "MEASUREMENT_KINDS",
    "MeasurementKindSpec",
    "MEASUREMENT_KIND_SPECS",
    "p_sigma",
    "v_sigma",
    "va_sigma_deg",
]

MeasurementKind = Literal["pmu", "ami", "scada", "pseudo"]

MEASUREMENT_KINDS: tuple[MeasurementKind, ...] = ("pmu", "ami", "scada", "pseudo")


@dataclass(frozen=True)
class MeasurementKindSpec:
    label: str
    has_voltage: bool
    """Mede |V| na barra (v_bus)."""
    has_angle: bool
    """Mede theta diretamente na barra (va_bus) -- so um PMU sincronizado
    faz isso; para os demais tipos, theta so existe como saida do
    estimador."""
    p_sigma_mult: float
    """Multiplicador sobre noise_level para o sigma de P/Q."""
    v_sigma_mult: float
    """Multiplicador sobre noise_level para o sigma de |V| (pu)."""
    va_sigma_deg_base: float
    """Piso de sigma de theta em graus (so usado quando has_angle=True)."""


MEASUREMENT_KIND_SPECS: dict[MeasurementKind, MeasurementKindSpec] = {
    "pmu": MeasurementKindSpec(
        label="PMU",
        has_voltage=True,
        has_angle=True,
        p_sigma_mult=0.1,
        v_sigma_mult=0.1,
        va_sigma_deg_base=0.02,
    ),
    "scada": MeasurementKindSpec(
        label="SCADA",
        has_voltage=True,
        has_angle=False,
        p_sigma_mult=1.0,
        v_sigma_mult=0.2,
        va_sigma_deg_base=0.0,
    ),
    "ami": MeasurementKindSpec(
        label="AMI",
        has_voltage=False,
        has_angle=False,
        p_sigma_mult=3.0,
        v_sigma_mult=0.0,
        va_sigma_deg_base=0.0,
    ),
    "pseudo": MeasurementKindSpec(
        label="Pseudo",
        has_voltage=False,
        has_angle=False,
        p_sigma_mult=10.0,
        v_sigma_mult=0.0,
        va_sigma_deg_base=0.0,
    ),
}


def p_sigma(
    kind: MeasurementKind,
    value: float,
    noise_level: float,
    sigma_min: float,
    sn_mva: float = 1.0,
) -> float:
    """Sigma de uma medicao de P/Q: `max(sigma_min, |valor| * noise_level * mult)`,
    em pu normalizado pela base da propria rede (`sn_mva`), depois escalado
    de volta pra unidade "crua" de `value` (MW/MVAr no sn_mva do `net`).

    `sigma_min` e um piso ABSOLUTO definido em pu-de-referencia (o app
    sempre usa sn_mva=1, entao pra ele isso ja e a propria escala). Sem essa
    normalizacao, o piso so "morde" em redes com sn_mva=1 -- uma rede
    pandapower nativa com sn_mva!=1 (ex.: `pn.case5()`, sn_mva=100) tem os
    mesmos valores fisicos ~sn_mva vezes maiores em MW, entao o mesmo piso
    absoluto vira irrelevante la, mudando o peso relativo de medicoes
    pequenas (tipicamente Q de linhas pouco carregadas) entre as duas redes
    mesmo com o MESMO estado fisico. Achado e corrigido em 2026-07-19 ao
    tentar bater J entre o notebook de erro de parametro (`pn.case5()`,
    sn_mva=100) e o app (sn_mva=1 sempre) -- ver
    `docs/governanca/decisoes_tecnicas.md`.
    """

    spec = MEASUREMENT_KIND_SPECS[kind]
    value_pu = value / sn_mva
    sigma_pu = max(sigma_min, abs(value_pu) * noise_level * spec.p_sigma_mult)
    return sigma_pu * sn_mva


def v_sigma(kind: MeasurementKind, noise_level: float, sigma_min: float) -> float:
    """Sigma de uma medicao de |V| (pu): `max(sigma_min, noise_level * mult)`."""

    spec = MEASUREMENT_KIND_SPECS[kind]
    return max(sigma_min, noise_level * max(spec.v_sigma_mult, 1e-6))


def va_sigma_deg(kind: MeasurementKind, noise_level: float) -> float:
    """Sigma de uma medicao de angulo (PMU), em graus."""

    spec = MEASUREMENT_KIND_SPECS[kind]
    return max(spec.va_sigma_deg_base, noise_level * 2.0)
