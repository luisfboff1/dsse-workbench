# -*- coding: utf-8 -*-
"""Planos de medicao: quais grandezas sao medidas, onde, e com que variancia.

O plano de medicao nao e detalhe de montagem do caso -- e uma variavel de
projeto que muda o que o estimador consegue detectar. Dois planos com o mesmo
numero de medicoes e magnitudes de erro identicas dao resultados opostos se a
variancia for homogenea num e heterogenea no outro (hipotese A4 de
`docs/planejamento/artigo_bad_data_conferencia.md`).

Dois planos implementados:

- `plano_uniforme`: tudo medido, mesma precisao relativa em tudo. E o que
  `synthetic_full_measurements_from_results` ja fazia, exposto aqui com nome
  para poder aparecer como variavel nas tabelas.
- `plano_crawford_baran`: o de Crawford & Baran, TPWRS 41(4):2571-2578, 2026,
  secao IV. Pseudo-medida de carga (P e Q) em TODA barra com ruido grande,
  poucos fluxos de ramo precisos delimitando "ilhas de medicao", e tensao so
  em pontos de grande variacao. E o plano com que eles detectam falha de banco
  de 400 kvar com `r^N = 201,8`.

Ver `docs/estudos/estimacao_estado/literatura/crawford_baran_2026_signature_topology_dsse.md`.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .ac_measurements import ACMeasurement, synthetic_full_measurements_from_results

__all__ = ["plano_uniforme", "plano_crawford_baran", "PLANOS", "resumo_plano",
           "medidas_criticas"]

# Valores de Crawford & Baran 2026, secao IV ("Measurement values were
# generated using CYME CYMDIST power flow results"): pseudo-medida de carga
# com +-30%, fluxo e tensao com +-3%.
CB_SIGMA_PSEUDO = 0.30
CB_SIGMA_FLUXO = 0.03
CB_SIGMA_TENSAO = 0.03


def plano_uniforme(
    net: Any, *, noise_level: float = 0.01, sigma_min: float = 0.005
) -> list[ACMeasurement]:
    """Instrumentacao total, precisao relativa igual em tudo (nosso padrao)."""

    return synthetic_full_measurements_from_results(
        net, kind="scada", noise_level=noise_level, sigma_min=sigma_min
    )


def _sigma(valor: float, relativo: float, piso: float) -> float:
    return max(abs(float(valor)) * relativo, piso)


def plano_crawford_baran(
    net: Any,
    *,
    n_ilhas: int = 7,
    n_tensoes: int = 12,
    sigma_piso_mva: float = 1e-4,
    sigma_piso_pu: float = 1e-3,
) -> list[ACMeasurement]:
    """Plano de Crawford & Baran 2026: variancia deliberadamente heterogenea.

    - `p_inj`/`q_inj` em **toda** barra, sigma = 30% do valor (pseudo-medida
      de carga: e uma estimativa, nao um medidor);
    - `p_branch`/`q_branch` em `n_ilhas` ramos que particionam o alimentador,
      sigma = 3% (medidor de verdade). Sao eles que criam as "ilhas de
      medicao" do artigo;
    - `v_bus` em `n_tensoes` barras de maior desvio de tensao, sigma = 3%.

    A escolha dos ramos e por maior fluxo ativo (tronco do alimentador), que e
    o que particiona de fato; a das barras e por maior desvio de |V| em
    relacao a 1,0 pu, que e o criterio do artigo ("areas of large voltage
    variation like the end of the main feeder and ends of large laterals").

    **Os defaults 7 e 12 nao sao arbitrarios**: sao os do Feeder 1 do artigo
    ("there are 7 three-phase flow measurements on the feeder, creating 7
    measurement islands. There are also 12 voltage measurements at the end of
    the main laterals"). E com 7 ilhas que o plano deixa de ter **medida
    critica** no `case33bw`: com 4 sobram 5 `q_inj` criticas (`K_ii = 1`, ou
    seja, residuo identicamente nulo, impossivel de detectar), o que
    contradiria a premissa do proprio artigo de que em DSSE nao ha medidas
    criticas. Validar com `medidas_criticas` ao trocar de rede.
    """

    completo = synthetic_full_measurements_from_results(
        net, kind="scada", noise_level=0.01, sigma_min=0.005
    )

    em_servico = [int(i) for i in net.line.index if bool(net.line.at[i, "in_service"])]
    fluxo = {i: abs(float(net.res_line.at[i, "p_from_mw"])) for i in em_servico}
    ramos_medidos = set(sorted(fluxo, key=fluxo.get, reverse=True)[:n_ilhas])

    desvio = {int(b): abs(float(net.res_bus.at[b, "vm_pu"]) - 1.0) for b in net.bus.index}
    barras_medidas = set(sorted(desvio, key=desvio.get, reverse=True)[:n_tensoes])

    plano: list[ACMeasurement] = []
    for m in completo:
        el = int(m.element)
        if m.kind in ("p_inj", "q_inj"):
            novo_sigma = _sigma(m.value, CB_SIGMA_PSEUDO, sigma_piso_mva)
        elif m.kind in ("p_branch", "q_branch"):
            if m.branch_kind == "line" and el not in ramos_medidos:
                continue
            novo_sigma = _sigma(m.value, CB_SIGMA_FLUXO, sigma_piso_mva)
        elif m.kind == "v_bus":
            if el not in barras_medidas:
                continue
            novo_sigma = _sigma(m.value, CB_SIGMA_TENSAO, sigma_piso_pu)
        else:
            novo_sigma = m.sigma
        plano.append(
            ACMeasurement(kind=m.kind, element=m.element, value=m.value,
                          sigma=novo_sigma, side=m.side, branch_kind=m.branch_kind)
        )
    return plano


PLANOS = {"uniforme": plano_uniforme, "crawford_baran": plano_crawford_baran}


def medidas_criticas(K_diag: np.ndarray, tol: float = 1e-3) -> list[int]:
    """Indices das medidas criticas (`K_ii ~ 1`), que tem residuo sempre nulo.

    Um plano com medida critica nao pode ser usado para estudar
    detectabilidade: aquele erro e invisivel por construcao, nao por fisica.
    Checar SEMPRE ao montar um plano novo ou ao trocar de rede.
    """

    return [int(i) for i in np.where(np.asarray(K_diag) > 1.0 - tol)[0]]


def resumo_plano(meas: list[ACMeasurement]) -> dict[str, float | int]:
    """Numeros que caracterizam um plano, para virar coluna de tabela.

    `razao_sigma` (maior sigma relativo / menor) e a medida direta da
    heterogeneidade de variancia -- a variavel da hipotese A4.
    """

    sig = np.array([m.sigma for m in meas], dtype=float)
    rel = np.array([m.sigma / max(abs(m.value), 1e-9) for m in meas], dtype=float)
    por_tipo: dict[str, int] = {}
    for m in meas:
        por_tipo[m.kind] = por_tipo.get(m.kind, 0) + 1
    return {
        "m": len(meas),
        "sigma_min": float(sig.min()),
        "sigma_max": float(sig.max()),
        "razao_sigma": float(np.percentile(rel, 95) / max(np.percentile(rel, 5), 1e-12)),
        **{f"n_{k}": v for k, v in sorted(por_tipo.items())},
    }
