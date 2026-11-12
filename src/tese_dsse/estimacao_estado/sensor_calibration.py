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

import os
import warnings
from dataclasses import dataclass
from typing import Literal

import numpy as np

__all__ = [
    "MeasurementKind",
    "MEASUREMENT_KINDS",
    "MeasurementKindSpec",
    "MEASUREMENT_KIND_SPECS",
    "p_sigma",
    "relative_sigma",
    "meter_full_scale",
    "typical_power_scale",
    "audit_power_sigmas",
    "SigmaFloorWarning",
    "FULL_SCALE_FACTOR",
    "ZERO_READING_SCALE",
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


# --------------------------------------------------------------------------
# Piso de sigma por MEDIDOR (2026-11-11)
# --------------------------------------------------------------------------
# O erro de um medidor de potencia tem dois termos (classe de exatidao):
# um proporcional a leitura e um constante, em % do FUNDO DE ESCALA do
# proprio medidor. Ate 11/11/2026 o fundo de escala era o `sn_mva` da rede,
# uma base numerica sem relacao com o medidor -- a mesma rede com base 1, 10
# ou 100 MVA dava pesos diferentes, e isso causou ~8 incidentes (ver
# docs/governanca/regra_sigma_min.md). Agora o fundo de escala de cada
# medidor sai do ponto de operacao do elemento que ele mede: o par (P, Q) da
# mesma barra ou da mesma ponta de ramo. O resultado nao depende mais da base
# nem da unidade escolhida.

FULL_SCALE_FACTOR = 2.0
"""Fundo de escala = 2 x |S| de operacao do elemento medido (TC/TP
dimensionado para o dobro da carga tipica do circuito)."""

ZERO_READING_SCALE = 0.1
"""Leitura quase nula (barra de passagem, linha em vazio): o fundo de escala
nao cai abaixo de 10% da |S| tipica da rede (`typical_power_scale`)."""


def typical_power_scale(apparent_powers) -> float:
    """|S| tipica da rede: mediana dos |S| nao nulos dos pontos medidos.

    Calculada sobre TODOS os pontos de operacao da rede (todas as barras e
    pontas de ramo), nao so sobre os medidores configurados, para que app e
    notebook deem o mesmo piso no mesmo caso.
    """

    vals = [abs(float(x)) for x in apparent_powers if abs(float(x)) > 1e-12]
    return float(sorted(vals)[len(vals) // 2]) if vals else 1.0


def meter_full_scale(p: float, q: float, s_typ: float, s_local: float = 0.0) -> float:
    """Fundo de escala de um medidor de P/Q (mesma unidade de `p`, `q`).

    `max(2|S|, s_local, 0.1 * s_typ)`. Para medidor de INJECAO, `s_local` e
    o maior |S| dos ramos ligados a barra (`bus_throughput`): numa barra de
    passagem nao ha carga, o medidor ve o que atravessa a barra. Sem isso a
    injecao zero ficava ~20x mais precisa que os fluxos vizinhos, virava
    medida quase critica (K_ii = 0,9988 na barra 7 do IEEE 14) e os metodos
    que dividem por (1 - K) erravam a identificacao (11/11/2026).
    """

    return max(FULL_SCALE_FACTOR * float(np.hypot(p, q)), float(s_local), ZERO_READING_SCALE * float(s_typ))


def p_sigma(
    kind: MeasurementKind,
    value: float,
    noise_level: float,
    sigma_min: float,
    *,
    full_scale: float,
) -> float:
    """Sigma de uma medicao de P/Q, na unidade de `value`:
    `max(sigma_min * full_scale, |value| * noise_level * mult)`.

    `sigma_min` e a fracao do fundo de escala do medidor (classe de
    exatidao, padrao 0.005 = 0,5%); `full_scale` vem de `meter_full_scale`.
    Nao existe mais parametro `sn_mva`: chamar com ele da TypeError de
    proposito, para nenhum codigo antigo voltar a amarrar o piso na base.
    """

    spec = MEASUREMENT_KIND_SPECS[kind]
    return max(sigma_min * float(full_scale), abs(value) * noise_level * spec.p_sigma_mult, 1e-12)


def relative_sigma(kind: MeasurementKind, noise_level: float) -> float:
    """Sigma relativo nominal da classe (sem piso), para a auditoria."""

    return noise_level * MEASUREMENT_KIND_SPECS[kind].p_sigma_mult


# --------------------------------------------------------------------------
# Auditoria automatica: o piso esta dominando o sinal?
# --------------------------------------------------------------------------

class SigmaFloorWarning(UserWarning):
    """O piso de sigma domina leituras relevantes (resultado nao confiavel)."""


AUDIT_SIGNIFICANT = 0.25
"""Leitura relevante: |z| >= 25% da mediana dos |z| nao nulos."""
AUDIT_MAX_REL = 0.10
"""Sigma acima de 10% da leitura..."""
AUDIT_CLASS_FACTOR = 2.0
"""...e acima de 2x o sigma relativo da propria classe."""
AUDIT_MAX_SHARE = 0.10
"""Avisa se mais de 10% das leituras relevantes estao nessa situacao."""


def audit_power_sigmas(values, sigmas, rel_sigmas, labels=None, *, magnitudes=None, context: str = "") -> dict:
    """Confere, medida a medida, se o piso domina leituras relevantes de P/Q.

    `magnitudes` e a |S| do ponto medido (o par P, Q do mesmo medidor); sem
    ela usa |z|. Uma leitura relevante e "dominada" quando sigma > 10% de
    |S| E sigma > 2x o sigma relativo da sua classe vezes |S| (`rel_sigmas`,
    ex. 1% no SCADA): o ruido vem de um piso alheio ao medidor. Comparar com
    |S| e nao com |z| evita marcar o Q pequeno de uma linha com P alto, cujo
    sigma (% do fundo de escala do mesmo TC) e fisico. Se mais de 10% das leituras
    relevantes forem dominadas, emite `SigmaFloorWarning` dizendo quais; com
    a variavel de ambiente `TESE_DSSE_STRICT_SIGMA=1`, levanta erro.
    Devolve o relatorio (share, n, piores) para quem quiser registrar.
    """

    vals = np.abs(np.asarray(values if magnitudes is None else magnitudes, dtype=float))
    sig = np.asarray(sigmas, dtype=float)
    rel = np.asarray(rel_sigmas, dtype=float)
    labels = list(labels) if labels is not None else [str(i) for i in range(len(vals))]
    nz = vals[vals > 1e-12]
    report = {"n_significant": 0, "n_dominated": 0, "share": 0.0, "worst": []}
    if nz.size == 0:
        return report
    sig_mask = vals >= AUDIT_SIGNIFICANT * float(np.median(nz))
    ratio = np.where(vals > 0, sig / np.maximum(vals, 1e-300), np.inf)
    dom = sig_mask & (ratio > AUDIT_MAX_REL) & (sig > AUDIT_CLASS_FACTOR * rel * vals)
    n_sig, n_dom = int(sig_mask.sum()), int(dom.sum())
    order = np.argsort(-np.where(dom, ratio, -1))[: min(n_dom, 5)]
    report.update(n_significant=n_sig, n_dominated=n_dom, share=n_dom / max(n_sig, 1),
                  worst=[(labels[k], float(vals[k]), float(sig[k]), float(ratio[k])) for k in order])
    if n_sig and report["share"] > AUDIT_MAX_SHARE:
        msg = (f"{context}piso de sigma domina {n_dom} de {n_sig} leituras relevantes de P/Q "
               f"({report['share']:.0%}): sigma > {AUDIT_MAX_REL:.0%} da leitura e > "
               f"{AUDIT_CLASS_FACTOR:g}x a classe. Piores: "
               + "; ".join(f"{l} z={v:.4g} sigma={s_:.3g} ({r:.0%})" for l, v, s_, r in report["worst"])
               + ". Ver docs/governanca/regra_sigma_min.md.")
        if os.environ.get("TESE_DSSE_STRICT_SIGMA") == "1":
            raise ValueError(msg)
        warnings.warn(msg, SigmaFloorWarning, stacklevel=3)
    return report


def v_sigma(kind: MeasurementKind, noise_level: float, sigma_min: float) -> float:
    """Sigma de uma medicao de |V| (pu): `max(sigma_min, noise_level * mult)`."""

    spec = MEASUREMENT_KIND_SPECS[kind]
    return max(sigma_min, noise_level * max(spec.v_sigma_mult, 1e-6))


def va_sigma_deg(kind: MeasurementKind, noise_level: float) -> float:
    """Sigma de uma medicao de angulo (PMU), em graus."""

    spec = MEASUREMENT_KIND_SPECS[kind]
    return max(spec.va_sigma_deg_base, noise_level * 2.0)
