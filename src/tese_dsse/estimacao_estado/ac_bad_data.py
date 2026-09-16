"""Pipeline de bad data AC nao-linear + erro de parametro de linha.

Extraido/generalizado a partir de
``notebooks/simulacao/5_BUS_IEEE_AC_parameter_error_bad_data.ipynb`` (erro de
parametro pedido por Arturo, reuniao 2026-07-17 + artigo Bretas et al. 2017,
``docs/estudos/estimacao_estado/literatura/bretas2017_malicious_data_innovation.md``).

Ao contrario de ``bad_data.run_bad_data_pipeline`` (DC, ``H`` fixo entre
iteracoes), aqui ``H(x*)`` muda a cada iteracao -- o modelo AC e reconstruido
e resolvido do zero a cada passo, porque remover/corrigir uma medicao ou
corrigir um parametro de linha muda o ponto de operacao. Esse mesmo modulo e
importado tanto pelo notebook quanto por ``app/backend/routes/baddata.py``,
para garantir que os dois rodam exatamente o mesmo codigo e produzem os
mesmos numeros no mesmo caso.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from .ac_measurements import ACMeasurement, build_ac_ybus_model_from_pandapower
from .bad_data import (
    compute_geometric_diagnostics,
    detect_chi2,
    detect_chi2_cme,
    detect_chi2_cme_satterthwaite,
    identify_cme,
    identify_lnr,
)

__all__ = [
    "line_signature_score",
    "identify_by_line",
    "classify_attack_signature",
    "inject_parameter_error",
    "inject_topology_error",
    "correct_parameter_eq16",
    "correct_parameter_eq16_signcheck",
    "AcBadDataPipelineResult",
    "run_ac_bad_data_pipeline",
    "run_general_bad_data_pipeline",
    "rmse_against_truth",
]


def line_signature_score(
    measurements: list[ACMeasurement],
    cme_n: np.ndarray,
    line_from: int,
    line_to: int,
    line_id: int,
    threshold: float = 3.0,
    branch_kind: str = "line",
) -> tuple[list[int], list[int]]:
    """Indices das medicoes "proprias" de uma linha (fluxo `p`/`q` dos dois
    lados + injecao `p`/`q` das duas barras terminais) e quais delas estao
    acima do limiar em `|CME_N|` -- heuristica de identificacao de erro de
    parametro descrita na pg. 213 (Bretas et al. 2017, secao 3, item 2).

    Puramente estrutural: so olha `measurement.kind`/`element`/`branch_kind`,
    nao depende de nenhum valor numerico de `cme_n` alem de comparar com o
    limiar.

    `branch_kind` (default `"line"`) desambigua `line_id` de `net.line` vs.
    `net.trafo` -- as duas tabelas do pandapower tem indices INDEPENDENTES
    comecando em 0, entao `line_id=0` (uma linha) e `trafo_id=0` (um
    transformador) colidem numericamente em qualquer rede com ambos (ex.:
    IEEE 14-bus, que tem 5 transformadores com ids 0-4). Sem esse filtro,
    medicoes de fluxo de um TRANSFORMADOR de id igual eram incluidas nas
    "medidas proprias" da LINHA por engano, diluindo a fracao flagrada e
    causando identificacao errada de linha -- achado do Monte Carlo no
    14-bus, 2026-07-21 (ver `docs/governanca/decisoes_tecnicas.md`).
    """

    own = [
        i
        for i, m in enumerate(measurements)
        if (m.kind in ("p_branch", "q_branch") and m.element == line_id and m.branch_kind == branch_kind)
        or (m.kind in ("p_inj", "q_inj") and m.element in (line_from, line_to))
    ]
    flagged = [i for i in own if abs(cme_n[i]) > threshold]
    return own, flagged


def identify_by_line(
    measurements: list[ACMeasurement],
    net: Any,
    cme_n: np.ndarray,
    threshold: float = 3.0,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Ranqueia todas as linhas de `net` pela fracao de medicoes proprias
    flagradas (|CME_N| > threshold); retorna a linha vencedora, a medicao
    dessa linha com maior |CME_N| (usada por `correct_parameter_eq16`) e o
    ranking completo (para exibir numa tabela).

    So considera `net.line` (`branch_kind="line"`) -- transformadores
    (`net.trafo`) NAO entram como candidatos ainda; um ataque de parametro
    num transformador nao seria identificado por esta funcao (pendente,
    mesma categoria de `correct_topology`)."""

    rows: list[dict[str, Any]] = []
    for line_id, row in net.line.iterrows():
        line_id = int(line_id)
        from_bus, to_bus = int(row.from_bus), int(row.to_bus)
        own, flagged = line_signature_score(measurements, cme_n, from_bus, to_bus, line_id, threshold, branch_kind="line")
        fraction = len(flagged) / len(own) if own else 0.0
        rows.append(
            {
                "line_id": line_id,
                "from_bus": from_bus,
                "to_bus": to_bus,
                "n_own": len(own),
                "n_flagged": len(flagged),
                "fraction_flagged": fraction,
                "own_idx": own,
            }
        )
    rows.sort(key=lambda r: r["fraction_flagged"], reverse=True)
    best = rows[0]
    if best["own_idx"]:
        idx = max(best["own_idx"], key=lambda i: abs(cme_n[i]))
    else:
        idx = int(np.argmax(np.abs(cme_n)))
    return best["line_id"], idx, rows


def classify_attack_signature(
    measurements: list[ACMeasurement],
    net: Any,
    cme_n: np.ndarray,
    *,
    threshold: float = 3.0,
    line_fraction_threshold: float = 0.5,
) -> tuple[Literal["measurement", "parameter", "topology"], int | None, int]:
    """Classifica o tipo de ataque a partir da assinatura do maior `CME_N`
    atual (Bretas et al. 2017, secao 3, passos 4-6 do algoritmo).

    - ``"topology"``: a linha vencedora de `identify_by_line` (maior fracao
      de medidas proprias flagradas) NAO TEM nenhuma medida de fluxo no
      conjunto atual -- os fluxos "desaparecem" da lista porque a linha foi
      excluida do modelo do estimador. Deteccao/classificacao funcionam;
      correcao ainda NAO esta implementada (`correct_topology` pendente).
    - ``"parameter"``: a linha vencedora TEM fluxo(s) no conjunto atual, e a
      fracao de medidas proprias flagradas esta >= `line_fraction_threshold`
      (default 0.5 -- limiar validado empiricamente no 5-bus: 0.625 na
      linha atacada vs. <=0.50 nas demais, ver
      `docs/estudos/estimacao_estado/literatura/bretas2017_malicious_data_innovation.md`,
      achado 1).
    - ``"measurement"``: nenhuma linha explica o padrao (fracao da melhor
      linha abaixo do limiar) -- pico isolado numa unica medida.

    Retorna `(tipo, line_id_ou_None, idx_medida)`. `idx_medida` e o indice
    em `measurements` a corrigir: para `"measurement"`, a propria medida
    isolada (usa `correct_measurement`/eq. 17); para `"parameter"`/
    `"topology"`, a medida de maior `|CME_N|` da linha vencedora (usa
    `correct_parameter_eq16`, para `"parameter"`).

    Nota: com um unico ataque a fracao da linha vencedora ou fica bem acima
    do limiar (parametro/topologia) ou bem abaixo (medida isolada) -- o
    artigo cita que multiplas medidas atacadas na mesma vizinhanca podem
    ficar ambiguas com um ataque de parametro; `line_fraction_threshold`
    controla esse trade-off, nao ha garantia formal de separacao.
    """

    line_id, idx, ranking = identify_by_line(measurements, net, cme_n, threshold=threshold)
    best = next(row for row in ranking if row["line_id"] == line_id)

    if best["fraction_flagged"] < line_fraction_threshold:
        isolated_idx = int(np.argmax(np.abs(cme_n)))
        return "measurement", None, isolated_idx

    has_flow = any(
        m.kind in ("p_branch", "q_branch") and m.element == line_id for m in measurements
    )
    if not has_flow:
        return "topology", line_id, idx
    return "parameter", line_id, idx


def inject_parameter_error(
    net: Any,
    line_id: int,
    param_sigma_pct: float = 0.01,
    n_sigmas: float = 10.0,
    symmetric: bool = True,
) -> tuple[Any, float]:
    """Constroi uma copia de `net` com `r`/`x` (e `c`, se `symmetric`) da
    linha `line_id` alterados pelo mesmo fator relativo -- "erro de
    parametro" pedido por Arturo: `p_errado = p_real * (1 + n_sigmas *
    param_sigma_pct)`. `param_sigma_pct` e uma suposicao explicita de
    incerteza percentual de cadastro de parametro de linha (o artigo so
    define "k sigma" para erro de MEDIDA, eq. 18-19; nao ha um sigma
    equivalente definido para parametro -- ver
    docs/estudos/estimacao_estado/literatura/bretas2017_malicious_data_innovation.md).

    Roda `pp.runpp` na rede alterada (necessario para popular o Ybus/branches
    internos que `build_ac_ybus_model_from_pandapower` le) -- o resultado do
    fluxo de potencia da rede errada em si nao e usado em lugar nenhum.
    Retorna `(net_errado, fator)`.
    """

    import pandapower as pp

    factor = 1.0 + param_sigma_pct * n_sigmas
    net_wrong = deepcopy(net)
    net_wrong.line.at[line_id, "r_ohm_per_km"] *= factor
    net_wrong.line.at[line_id, "x_ohm_per_km"] *= factor
    if symmetric:
        net_wrong.line.at[line_id, "c_nf_per_km"] *= factor
    pp.runpp(net_wrong, calculate_voltage_angles=True, init="flat", numba=False)
    return net_wrong, factor


def inject_topology_error(net: Any, closed_extra_line_id: int) -> Any:
    """Constroi uma copia de `net` com uma chave/linha adicional FECHADA
    (`closed_extra_line_id`, tipicamente uma linha "tie" que em `net` esta
    com `in_service=False` por padrao, ex.: os 5 lacos de reconfiguracao do
    `pandapower.networks.case33bw()`) -- simula uma reconfiguracao de rede
    de distribuicao (comutacao automatica) que o modelo do estimador NAO
    sabe que aconteceu.

    Ao contrario de `inject_parameter_error` (que retorna a rede ERRADA
    pro modelo do estimador), aqui a rede "errada" continua sendo o
    proprio `net` ORIGINAL, sem nenhuma mudanca -- e a rede FISICA REAL
    que muda. Retorna `net_real` (a rede fisica verdadeira, com o ramo
    extra fechado); o chamador deve:

    1. Gerar as medicoes a partir de `net_real` (`synthetic_full_measurements_from_results`).
    2. REMOVER as medicoes de fluxo (`p_branch`/`q_branch`) do ramo
       `closed_extra_line_id` desse conjunto -- o modelo do estimador nao
       tem esse ramo na sua propria `net.line`/Ybus (continua com
       `in_service=False` para ele), entao nao ha `h(x)` definido pra uma
       medicao de um ramo que o modelo desconhece (`build_ac_ybus_model_from_pandapower(net, ...)`
       levantaria `KeyError` no `branch_lookup`).
    3. Rodar o pipeline com `net_model=net` (original) e essas medicoes
       filtradas.

    Roda `pp.runpp` na rede reconfigurada (necessario para popular
    Ybus/branches internos usados na geracao de medicoes)."""

    import pandapower as pp

    net_real = deepcopy(net)
    net_real.line.at[closed_extra_line_id, "in_service"] = True
    pp.runpp(net_real, calculate_voltage_angles=True, init="flat", numba=False)
    return net_real


def correct_parameter_eq16(net: Any, line_id: int, cne: float, symmetric: bool = True) -> Any:
    """Corrige `r`/`x`/`c` da linha `line_id` pela eq. 16 (Bretas et al.
    2017): `p_corrigido = p_errado * (1 + CNE/100)`, com o mesmo `CNE` (da
    medicao com maior `|CME_N|` associada aquela linha) aplicado as tres
    grandezas -- coerente com a injecao simetrica de `inject_parameter_error`.
    Roda `pp.runpp` na rede corrigida antes de retornar. Retorna uma copia
    (nao muta `net`).
    """

    import pandapower as pp

    factor_corrected = 1.0 + cne / 100.0
    net_corrected = deepcopy(net)
    net_corrected.line.at[line_id, "r_ohm_per_km"] *= factor_corrected
    net_corrected.line.at[line_id, "x_ohm_per_km"] *= factor_corrected
    if symmetric:
        net_corrected.line.at[line_id, "c_nf_per_km"] *= factor_corrected
    pp.runpp(net_corrected, calculate_voltage_angles=True, init="flat", numba=False)
    return net_corrected


def correct_parameter_eq16_signcheck(
    net: Any,
    measurements: list[ACMeasurement],
    line_id: int,
    cne: float,
    *,
    alpha: float = 0.05,
    symmetric: bool = True,
) -> tuple[Any, float]:
    """Aplica a eq. 16 (Bretas et al. 2017) nos dois sinais possiveis de
    `cne` (`+CNE` e `-CNE`) e fica com o que resulta em menor `J` apos
    resolver o WLS de novo -- resolve uma ambiguidade de sinal real que
    `correct_parameter_eq16` sozinha nao trata.

    Por que a ambiguidade existe: eq. 16 (`p_C = p_E*(1+CNE_i/100)`) trata
    `CNE_i/100` como se ja fosse a correcao percentual do parametro -- so
    da certo quando a medida de maior `|CME_N|` associada a linha (a
    escolhida por `identify_by_line`) tem, por coincidencia, a sensibilidade
    "certa" em relacao ao parametro. Medidas `p_branch_from`/`p_branch_to`
    do MESMO ramo tem sensibilidade de sinal OPOSTO ao parametro por
    convencao (fluxo medido saindo de cada lado) -- confirmado numericamente
    (`dP_from/dfator` e `dP_to/dfator` com sinais opostos e magnitude
    parecida). Sem esse ajuste, a correcao pode DIVERGIR em vez de
    convergir a cada iteracao (achado do Monte Carlo, 2026-07-21 --
    ver `docs/governanca/decisoes_tecnicas.md`).

    Mantem a formula e a magnitude de `CNE` exatamente como o artigo propoe
    -- nao usa nenhuma sensibilidade/derivada alternativa (avaliado e
    descartado: precisaria reintroduzir manualmente o fator `(1+UI_i)` de
    recuperacao de mascaramento que ja esta embutido no `CNE`, ou perderia
    essa correcao). So decide o SINAL comparando qual das duas opcoes reduz
    mais o `J` -- custo extra e 2 resolucoes de WLS (barato: ~6ms cada no
    5-bus), so quando o tipo classificado e `"parameter"`.

    Retorna `(net_corrigido, sinal_usado)`, com `sinal_usado` em
    `{+1.0, -1.0}`.
    """

    net_plus = correct_parameter_eq16(net, line_id, cne, symmetric=symmetric)
    net_minus = correct_parameter_eq16(net, line_id, -cne, symmetric=symmetric)

    def _J(net_candidate: Any) -> float:
        model = build_ac_ybus_model_from_pandapower(net_candidate, measurements)
        result = model.solve(x0=model.flat_start(), max_iter=30, tol=1e-8)
        H = model.jacobian_finite_difference(result.x)
        r = model.z - model.h(result.x)
        sigma = model.sigma
        geo = compute_geometric_diagnostics(H, np.diag(1.0 / sigma**2), r, sigma)
        _, J, _ = detect_chi2_cme(geo.CME_N, len(measurements), alpha=alpha)
        return J

    J_plus = _J(net_plus)
    J_minus = _J(net_minus)
    return (net_plus, 1.0) if J_plus <= J_minus else (net_minus, -1.0)


def rmse_against_truth(
    model: Any,
    x_hat: np.ndarray,
    true_vm_pu: np.ndarray,
    true_va_degree: np.ndarray,
) -> tuple[float, float]:
    """RMSE(theta) em graus e RMSE(|V|) em pu entre o estado estimado `x_hat`
    e o estado verdadeiro (tipicamente `net.res_bus.vm_pu`/`va_degree` da
    rede original, nao atacada, na mesma ordem de barras que `model`).

    So faz sentido em contexto de demonstracao/validacao (comparar
    estrategias de correcao) -- `x_true` nao esta disponivel na pratica
    (usa-lo pra decidir QUAL correcao aplicar seria "cola"); usar so para
    reportar o resultado de um experimento, depois da decisao ja tomada.
    Extraido do `rmse_of` inline de
    ``notebooks/simulacao/5_BUS_IEEE_AC_parameter_error_bad_data.ipynb``
    (secao 11/12) -- mesma formula, agora compartilhada com o app
    (`app/backend/routes/baddata.py`).
    """

    st = model.state_to_table(x_hat).to_dataframe()
    rmse_va = float(np.sqrt(np.mean((st["va_degree"].to_numpy() - np.asarray(true_va_degree)) ** 2)))
    rmse_vm = float(np.sqrt(np.mean((st["vm_pu"].to_numpy() - np.asarray(true_vm_pu)) ** 2)))
    return rmse_va, rmse_vm


@dataclass
class AcBadDataPipelineResult:
    """Resultado de uma execucao do ciclo deteccao->identificacao->correcao AC."""

    x_hat: np.ndarray
    model: Any  # ACYbusMeasurementModel do ultimo passo (state_to_table, etc.)
    net_final: Any  # rede pandapower final (parametros corrigidos, se correction='by_parameter')
    J_final: float
    threshold_final: float
    detected_final: bool
    n_iterations: int
    n_measurements_final: int
    flagged_indices: list[int] = field(default_factory=list)
    flagged_scores: list[float] = field(default_factory=list)
    flagged_lines: list[int | None] = field(default_factory=list)
    flagged_types: list[str] = field(default_factory=list)
    """Tipo classificado por iteracao (`"measurement"`/`"parameter"`/
    `"topology"`) -- so preenchido por `run_general_bad_data_pipeline`;
    `run_ac_bad_data_pipeline` deixa vazio (o tipo ja e fixo por `correction=`)."""
    actions: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)


def run_ac_bad_data_pipeline(
    net_model: Any,
    measurements: list[ACMeasurement],
    *,
    detection: Literal["residual", "cme", "cme_satterthwaite"] = "residual",
    identification: Literal["lnr", "cme", "by_line"] = "lnr",
    correction: Literal["remove", "ztrue", "by_parameter"] = "remove",
    alpha: float = 0.05,
    line_threshold: float = 3.0,
    max_iter: int = 8,
    max_gn_iter: int = 30,
    tol: float = 1e-8,
) -> AcBadDataPipelineResult:
    """Roda deteccao -> identificacao -> correcao/remocao iterativamente
    sobre um modelo AC nao-linear (Gauss-Newton), reconstruindo e resolvendo
    o modelo do zero a cada iteracao.

    - ``detection``: ``"residual"`` (chi2 sobre ``J=r^T W r``, dof=``m-n``)
      ou ``"cme"`` (chi2 sobre ``sum(CME_N^2)``, dof=``m``).
    - ``identification``: ``"lnr"``/``"cme"`` (maior residuo/CME normalizado,
      uma medicao) ou ``"by_line"`` (agrupa por linha via
      ``identify_by_line`` -- heuristica da pg. 213 do artigo).
    - ``correction``: ``"remove"`` (descarta a medicao flagrada),
      ``"ztrue"`` (corrige a medicao via CNE, eq. 17) ou ``"by_parameter"``
      (corrige `r`/`x`/`c` da linha identificada via eq. 16 -- exige
      ``identification="by_line"``).
    """

    if correction == "by_parameter" and identification != "by_line":
        raise ValueError("correction='by_parameter' requer identification='by_line'.")

    net_cur = deepcopy(net_model)
    meas_cur = list(measurements)
    flagged_indices: list[int] = []
    flagged_scores: list[float] = []
    flagged_lines: list[int | None] = []
    actions: list[str] = []
    history: list[dict[str, Any]] = []

    result: Any = None
    model: Any = None
    detected, J, threshold = True, float("nan"), float("nan")

    for iteration in range(max_iter):
        model = build_ac_ybus_model_from_pandapower(net_cur, meas_cur)
        result = model.solve(x0=model.flat_start(), max_iter=max_gn_iter, tol=tol)
        H_star = model.jacobian_finite_difference(result.x)
        r_cur = model.z - model.h(result.x)
        sigma_cur = model.sigma
        W_cur = np.diag(1.0 / sigma_cur**2)
        m_cur, n_cur = H_star.shape
        geo = compute_geometric_diagnostics(H_star, W_cur, r_cur, sigma_cur)

        if detection == "residual":
            J = float(result.objective)
            detected, threshold = detect_chi2(J, dof=m_cur - n_cur, alpha=alpha)
        elif detection == "cme_satterthwaite":
            detected, J, threshold, _h = detect_chi2_cme_satterthwaite(
                geo.CME_N, geo.K_diag, geo.UI, alpha=alpha)
        else:
            detected, J, threshold = detect_chi2_cme(geo.CME_N, m_cur, alpha=alpha)

        record: dict[str, Any] = {
            "iter": iteration, "J": J, "threshold": threshold, "detected": detected, "m": m_cur,
            "converged": bool(result.converged),
        }
        if not detected:
            history.append(record)
            break

        line_id: int | None = None
        if identification == "lnr":
            idx, score = identify_lnr(geo.r_N)
        elif identification == "cme":
            idx, score = identify_cme(geo.CME_N)
        else:
            line_id, idx, _ranking = identify_by_line(meas_cur, net_cur, geo.CME_N, threshold=line_threshold)
            score = float(abs(geo.CME_N[idx]))

        record["flagged_idx"] = idx
        record["flagged_score"] = score
        record["flagged_line"] = line_id
        history.append(record)
        flagged_indices.append(idx)
        flagged_scores.append(score)
        flagged_lines.append(line_id)

        if correction == "remove":
            meas_cur = [m for i, m in enumerate(meas_cur) if i != idx]
            actions.append("removed")
        elif correction == "ztrue":
            old = meas_cur[idx]
            new_value = old.value - geo.CNE[idx] * sigma_cur[idx]
            meas_cur[idx] = ACMeasurement(
                kind=old.kind, element=old.element, value=new_value,
                sigma=old.sigma, side=old.side, branch_kind=old.branch_kind,
            )
            actions.append("corrected_measurement")
        else:
            assert line_id is not None
            net_cur, _sign = correct_parameter_eq16_signcheck(net_cur, meas_cur, line_id, float(geo.CNE[idx]), alpha=alpha)
            actions.append(f"corrected_parameter_line{line_id}")
    else:
        iteration = max_iter - 1

    return AcBadDataPipelineResult(
        x_hat=result.x,
        model=model,
        net_final=net_cur,
        J_final=J,
        threshold_final=threshold,
        detected_final=detected,
        n_iterations=len(history),
        n_measurements_final=len(meas_cur),
        flagged_indices=flagged_indices,
        flagged_scores=flagged_scores,
        flagged_lines=flagged_lines,
        actions=actions,
        history=history,
    )


def run_general_bad_data_pipeline(
    net_model: Any,
    measurements: list[ACMeasurement],
    *,
    detection: Literal["residual", "cme", "cme_satterthwaite"] = "cme_satterthwaite",
    alpha: float = 0.05,
    line_threshold: float = 3.0,
    line_fraction_threshold: float = 0.5,
    max_iter: int = 8,
    max_gn_iter: int = 30,
    tol: float = 1e-8,
) -> AcBadDataPipelineResult:
    """Roda deteccao -> classificacao -> correcao iterativamente, decidindo
    o TIPO de ataque (medida/parametro/topologia) a CADA ITERACAO pela
    assinatura observada (`classify_attack_signature`), em vez de fixar
    `identification=`/`correction=` no inicio como `run_ac_bad_data_pipeline`
    faz. E o algoritmo geral de 7 passos do artigo (Bretas et al. 2017,
    secao 3) -- necessario para cenarios com MAIS DE UM TIPO de ataque
    simultaneo (ex.: uma medida atacada E uma linha com parametro errado ao
    mesmo tempo), onde nao da pra saber de antemao qual correcao usar em
    cada iteracao.

    Ataque de topologia e DETECTADO e CLASSIFICADO corretamente, mas a
    correcao ainda nao esta implementada (`correct_topology` pendente) --
    se esse tipo for classificado numa iteracao, o pipeline registra a
    deteccao em `actions`/`history` e PARA (nao tenta corrigir, nao entra
    em loop infinito).

    Usa `detection="cme"` por padrao (nao `"residual"`, ao contrario de
    `run_ac_bad_data_pipeline`) porque e o que o algoritmo geral do artigo
    especifica (chi2 sobre `CME_N`, nao sobre o residuo classico) -- ver
    passo 3 do algoritmo (secao 3 do artigo).
    """

    if detection not in ("residual", "cme", "cme_satterthwaite"):
        raise ValueError(f"detection invalido: {detection!r}")

    net_cur = deepcopy(net_model)
    meas_cur = list(measurements)
    flagged_indices: list[int] = []
    flagged_scores: list[float] = []
    flagged_lines: list[int | None] = []
    flagged_types: list[str] = []
    actions: list[str] = []
    history: list[dict[str, Any]] = []

    result: Any = None
    model: Any = None
    detected, J, threshold = True, float("nan"), float("nan")

    for iteration in range(max_iter):
        model = build_ac_ybus_model_from_pandapower(net_cur, meas_cur)
        result = model.solve(x0=model.flat_start(), max_iter=max_gn_iter, tol=tol)
        H_star = model.jacobian_finite_difference(result.x)
        r_cur = model.z - model.h(result.x)
        sigma_cur = model.sigma
        W_cur = np.diag(1.0 / sigma_cur**2)
        m_cur, n_cur = H_star.shape
        geo = compute_geometric_diagnostics(H_star, W_cur, r_cur, sigma_cur)

        if detection == "residual":
            J = float(result.objective)
            detected, threshold = detect_chi2(J, dof=m_cur - n_cur, alpha=alpha)
        elif detection == "cme_satterthwaite":
            detected, J, threshold, _h = detect_chi2_cme_satterthwaite(
                geo.CME_N, geo.K_diag, geo.UI, alpha=alpha)
        else:
            detected, J, threshold = detect_chi2_cme(geo.CME_N, m_cur, alpha=alpha)

        record: dict[str, Any] = {
            "iter": iteration, "J": J, "threshold": threshold, "detected": detected, "m": m_cur,
            "converged": bool(result.converged),
        }
        if not detected:
            history.append(record)
            break

        attack_type, line_id, idx = classify_attack_signature(
            meas_cur, net_cur, geo.CME_N,
            threshold=line_threshold, line_fraction_threshold=line_fraction_threshold,
        )
        score = float(abs(geo.CME_N[idx]))

        record["flagged_idx"] = idx
        record["flagged_score"] = score
        record["flagged_line"] = line_id
        record["attack_type"] = attack_type
        history.append(record)
        flagged_indices.append(idx)
        flagged_scores.append(score)
        flagged_lines.append(line_id)
        flagged_types.append(attack_type)

        if attack_type == "measurement":
            old = meas_cur[idx]
            new_value = old.value - geo.CNE[idx] * sigma_cur[idx]
            meas_cur[idx] = ACMeasurement(
                kind=old.kind, element=old.element, value=new_value,
                sigma=old.sigma, side=old.side, branch_kind=old.branch_kind,
            )
            actions.append("corrected_measurement")
        elif attack_type == "parameter":
            assert line_id is not None
            net_cur, _sign = correct_parameter_eq16_signcheck(net_cur, meas_cur, line_id, float(geo.CNE[idx]), alpha=alpha)
            actions.append(f"corrected_parameter_line{line_id}")
        else:  # topology -- deteccao/classificacao ok, correcao pendente
            actions.append(f"topology_detected_line{line_id}_correction_not_implemented")
            break
    else:
        iteration = max_iter - 1

    return AcBadDataPipelineResult(
        x_hat=result.x,
        model=model,
        net_final=net_cur,
        J_final=J,
        threshold_final=threshold,
        detected_final=detected,
        n_iterations=len(history),
        n_measurements_final=len(meas_cur),
        flagged_indices=flagged_indices,
        flagged_scores=flagged_scores,
        flagged_lines=flagged_lines,
        flagged_types=flagged_types,
        actions=actions,
        history=history,
    )


def line_gb_from_rx(net: Any, line_id: int) -> tuple[float, float, float]:
    """`(g, b, c_nf_per_km)` da linha, com `g + jb = 1/(r + jx)` sobre o
    comprimento TOTAL do trecho (ohms, nao por km).

    `b` sai NEGATIVO para uma linha indutiva, que e a convencao das eq. 6-7
    de Bretas et al. (PowerTech 2025): `Q_km = -V_k^2 (b + b_sh) + ...`.
    """

    row = net.line.loc[line_id]
    length = float(row.length_km)
    r = float(row.r_ohm_per_km) * length
    x = float(row.x_ohm_per_km) * length
    denom = r * r + x * x
    if denom <= 0.0:
        raise ValueError(f"linha {line_id} tem impedancia nula")
    return r / denom, -x / denom, float(row.c_nf_per_km)


def inject_parameter_error_unbalanced(
    net: Any,
    line_id: int,
    *,
    dg_pct: float,
    db_pct: float,
    dbsh_pct: float,
) -> tuple[Any, dict[str, float]]:
    """Erro de parametro DESBALANCEADO: `g`, `b` e `b_sh` erram por
    percentuais DIFERENTES, em vez do mesmo fator em `r`/`x`/`c`.

    E a convencao da linha do proprio grupo -- Zou et al. 2020 (EPSR
    187:106490, *"against **unbalanced** false data injection attacks"*) e
    Bretas, Caraballo, Ejiofor, Bretas (PowerTech 2025), cujo caso de
    referencia e `g = -5,3%`, `b = +7,0%`, `b_sh = +6,8%`. Sem isso os
    nossos resultados nao sao comparaveis com os deles.

    Por que nao da para fazer isso mexendo em `r`/`x` direto: `g` e `b` sao
    funcoes ACOPLADAS de `r` e `x` (`g = r/(r²+x²)`, `b = -x/(r²+x²)`), entao
    mudar so `r` mexe nos dois. O caminho e converter para admitancia,
    aplicar os percentuais, e voltar:

        r' = g'/(g'² + b'²)        x' = -b'/(g'² + b'²)

    Os percentuais sao aplicados ao valor COM SINAL, entao `db_pct > 0`
    aumenta o modulo de `b` (que e negativo numa linha indutiva) -- leitura
    natural de "b increased by 7%". `b_sh` e proporcional a `c_nf_per_km`,
    entao ali o percentual vai direto.

    Retorna `(net_errado, deltas_efetivos)` com os valores antes/depois para
    a tabela de relatorio. `inject_parameter_error` continua existindo para o
    caso simetrico (mesmo fator em `r`/`x`/`c`).
    """

    import pandapower as pp

    g, b, c_nf = line_gb_from_rx(net, line_id)
    g_new = g * (1.0 + dg_pct)
    b_new = b * (1.0 + db_pct)
    denom = g_new * g_new + b_new * b_new
    if denom <= 0.0:
        raise ValueError("parametros corrompidos: admitancia resultante nula")

    length = float(net.line.at[line_id, "length_km"])
    net_wrong = deepcopy(net)
    net_wrong.line.at[line_id, "r_ohm_per_km"] = (g_new / denom) / length
    net_wrong.line.at[line_id, "x_ohm_per_km"] = (-b_new / denom) / length
    net_wrong.line.at[line_id, "c_nf_per_km"] = c_nf * (1.0 + dbsh_pct)
    pp.runpp(net_wrong, calculate_voltage_angles=True, init="flat", numba=False)

    g_chk, b_chk, c_chk = line_gb_from_rx(net_wrong, line_id)
    return net_wrong, {
        "g_true": g, "g_wrong": g_chk, "g_pct": 100.0 * (g_chk / g - 1.0),
        "b_true": b, "b_wrong": b_chk, "b_pct": 100.0 * (b_chk / b - 1.0),
        "bsh_true": c_nf, "bsh_wrong": c_chk,
        "bsh_pct": 100.0 * (c_chk / c_nf - 1.0) if c_nf else 0.0,
    }
