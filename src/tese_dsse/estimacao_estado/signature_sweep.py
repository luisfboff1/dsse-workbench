"""Varredura com ground truth do classificador de assinatura de ataque.

Mede sistematicamente ONDE `ac_bad_data.classify_attack_signature` erra --
o baseline de limiar fixo do objetivo O2 (`docs/visao/narrativa_tese.md`
secao 3): separar erro de MEDIDA x PARAMETRO x TOPOLOGIA a partir da mesma
assinatura residual. A secao 1.4 da narrativa diz por que isso e o no do
problema: a fronteira e subjetiva (`line_fraction_threshold` e escolhido a
mao), as assinaturas COLIDEM (varias medidas atacadas ao mesmo tempo imitam
um erro de parametro) e os indices classicos degradam quando `H` esta
errada.

Este modulo faz duas coisas ao mesmo tempo, de proposito:

1. **Avaliacao**: roda cenarios com verdade conhecida (tipo, linha,
   magnitude, ruido, numero de medidas atacadas) e registra o que o
   baseline previu -> matriz de confusao.
2. **Dataset**: para cada cenario extrai um vetor de features
   ADIMENSIONAIS e INVARIANTES AO TAMANHO DA REDE (`signature_features`),
   de modo que a mesma varredura que mede o erro do baseline ja e o
   conjunto de treino de um classificador aprendido que o substitua.

O baseline avaliado e o pipeline REAL de uma iteracao, nao so
`classify_attack_signature` isolada: primeiro detecta (chi2 sobre `CME_N`,
`dof=m`), e so classifica se detectou -- se nao detectou, a predicao e
`"none"`. Assim o falso alarme e o falso negativo entram na mesma matriz
que os erros de classificacao, que e como o pipeline se comporta de fato
(`run_general_bad_data_pipeline`).

Convencoes herdadas de decisoes ja registradas em
`docs/governanca/decisoes_tecnicas.md`:

- `sigma_min` e piso em pu-de-referencia; `p_sigma` normaliza por `sn_mva`
  (achado de 2026-07-19). Usar ~0.5% do `sn_mva` (=0.005) e nao herdar o
  piso de outra rede (achado 14).
- Deteccao por `CME_N` sozinha nao e confiavel com `UI` heterogeneo --
  por isso `run_case` grava TAMBEM o teste classico do residuo
  (`j_res_ratio`), como cross-check e como feature.
- `line_signature_score` sempre filtra por `branch_kind` (achado 5).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Sequence

import numpy as np

from .ac_bad_data import (
    classify_attack_signature,
    identify_by_line,
    inject_parameter_error,
    inject_parameter_error_unbalanced,
    line_signature_score,
)
from .ac_measurements import (
    ACMeasurement,
    build_ac_ybus_model_from_pandapower,
    synthetic_full_measurements_from_results,
)
from .bad_data import compute_geometric_diagnostics, detect_chi2, detect_chi2_cme
from .dc_linear import sample_noisy_measurement

__all__ = [
    "AttackType",
    "ScenarioSpec",
    "CaseOutcome",
    "NETWORK_BUILDERS",
    "build_base_case",
    "inject_measurement_attack",
    "inject_topology_outage",
    "line_own_measurement_indices",
    "signature_features",
    "FEATURE_COLUMNS",
    "run_case",
    "build_scenarios",
    "run_sweep",
    # --- filtro casado (assinatura de sensibilidade por linha) ---
    "build_line_signature_library",
    "matched_filter_correlations",
    "identify_by_matched_filter",
    "build_line_subspace_library",
    "subspace_scores",
    "identify_by_subspace",
    "normalized_residual_covariance",
    "subspace_scores_normalized",
    "identify_by_subspace_normalized",
    # --- identificacao como selecao de modelo (GLRT entre subespacos) ---
    "parameter_sensitivity_library",
    "glrt_delta_j",
    "identify_by_glrt",
    "fit_parameter_change",
    "classify_by_glrt",
    # --- nivel LINHA (uma amostra por (snapshot, linha)) ---
    "measurement_key",
    "align_signature_library",
    "line_level_features",
    "run_sweep_lines",
]

AttackType = Literal["none", "measurement", "parameter", "topology"]

#: Ordem canonica das classes na matriz de confusao.
CLASS_ORDER: tuple[AttackType, ...] = ("none", "measurement", "parameter", "topology")


# ---------------------------------------------------------------------------
# Redes suportadas
# ---------------------------------------------------------------------------


def _case5() -> Any:
    import pandapower.networks as pn

    return pn.case5()


def _case14() -> Any:
    import pandapower.networks as pn

    return pn.case14()


def _case33bw() -> Any:
    import pandapower.networks as pn

    return pn.case33bw()


NETWORK_BUILDERS = {"case5": _case5, "case14": _case14, "case33bw": _case33bw}


@dataclass
class BaseCase:
    """Rede resolvida + medicoes limpas (sem ruido, sem ataque) reusadas por
    todos os cenarios daquela rede/nivel de ruido -- evita repetir `runpp` e
    a geracao de medicoes a cada trial do Monte Carlo."""

    name: str
    net: Any
    clean: list[ACMeasurement]
    bus_degree: dict[int, int]
    n_bus: int
    n_line: int
    m: int
    meas_kind: str
    noise_level: float
    sigma_min: float


def build_base_case(
    name: str,
    *,
    meas_kind: str = "scada",
    noise_level: float = 0.01,
    sigma_min: float = 0.005,
) -> BaseCase:
    """Resolve o fluxo de potencia da rede `name` e gera o plano de medicao
    completo SEM ruido (o ruido entra por cenario, em `run_case`, para que
    cada trial tenha sua propria realizacao)."""

    import pandapower as pp

    net = NETWORK_BUILDERS[name]()
    pp.runpp(net, calculate_voltage_angles=True, init="flat", numba=False)
    clean = synthetic_full_measurements_from_results(
        net, kind=meas_kind, noise_level=noise_level, sigma_min=sigma_min
    )
    degree: dict[int, int] = {int(b): 0 for b in net.bus.index}
    for _, row in net.line.iterrows():
        if not bool(row.in_service):
            continue
        degree[int(row.from_bus)] += 1
        degree[int(row.to_bus)] += 1
    for _, row in net.trafo.iterrows():
        if not bool(row.in_service):
            continue
        degree[int(row.hv_bus)] += 1
        degree[int(row.lv_bus)] += 1
    return BaseCase(
        name=name,
        net=net,
        clean=clean,
        bus_degree=degree,
        n_bus=len(net.bus),
        n_line=len(net.line),
        m=len(clean),
        meas_kind=meas_kind,
        noise_level=noise_level,
        sigma_min=sigma_min,
    )


# ---------------------------------------------------------------------------
# Injecao de ataques
# ---------------------------------------------------------------------------


def inject_measurement_attack(
    measurements: Sequence[ACMeasurement],
    indices: Sequence[int],
    k_sigma: float,
    signs: Sequence[float] | None = None,
) -> list[ACMeasurement]:
    """Soma `k_sigma * sigma_i` (com sinal) as medicoes `indices` -- ataque
    de MEDIDA no sentido do artigo (eq. 18-19: o erro grosseiro e expresso
    em multiplos do proprio sigma da medicao, entao a magnitude e comparavel
    entre medicoes de escalas diferentes).

    `signs` permite o caso COERENTE (todos os sinais iguais, que e o que um
    atacante faria para imitar a assinatura fisica de um erro de parametro)
    versus o caso INCOERENTE (sinais aleatorios). Default: todos `+1`.
    """

    if signs is None:
        signs = [1.0] * len(indices)
    if len(signs) != len(indices):
        raise ValueError("signs precisa ter o mesmo tamanho de indices.")
    delta = {int(i): float(s) for i, s in zip(indices, signs)}
    out: list[ACMeasurement] = []
    for i, m in enumerate(measurements):
        if i in delta:
            m = ACMeasurement(
                kind=m.kind,
                element=m.element,
                value=float(m.value + delta[i] * k_sigma * m.sigma),
                sigma=m.sigma,
                side=m.side,
                branch_kind=m.branch_kind,
            )
        out.append(m)
    return out


def line_own_measurement_indices(
    measurements: Sequence[ACMeasurement], net: Any, line_id: int
) -> list[int]:
    """Indices das medicoes "proprias" da linha `line_id` -- mesma definicao
    estrutural que `line_signature_score` usa para pontuar (fluxos dos dois
    lados + injecoes das duas barras terminais). Usado para montar o ataque
    MULTI-MEDIDA que imita um erro de parametro: atacar exatamente as
    medidas que um erro naquela linha perturbaria."""

    from_bus = int(net.line.at[line_id, "from_bus"])
    to_bus = int(net.line.at[line_id, "to_bus"])
    own, _ = line_signature_score(
        list(measurements), np.zeros(len(measurements)), from_bus, to_bus, line_id,
        threshold=np.inf, branch_kind="line",
    )
    return own


def inject_topology_outage(net: Any, line_id: int) -> Any:
    """Rede FISICA real com a linha `line_id` ABERTA, enquanto o modelo do
    estimador continua achando que ela esta fechada -- erro de topologia por
    base de dados desatualizada (`narrativa_tese.md` secao 1.3).

    Complementa `ac_bad_data.inject_topology_error`, que faz o caso oposto
    (ramo extra FECHADO na realidade e desconhecido do modelo). Este aqui
    funciona em qualquer rede malhada, sem depender de existir uma linha
    "tie" fora de servico no `net`.

    O chamador gera as medicoes a partir do `net_real` retornado: os fluxos
    da linha aberta simplesmente NAO aparecem no conjunto (a linha esta fora
    de servico), que e exatamente a assinatura que
    `classify_attack_signature` chama de `"topology"`.

    Retorna `None` se a abertura ILHAR a rede -- checado por
    `unsupplied_buses`, nao por `net.converged`: numa rede RADIAL qualquer
    abertura desliga o trecho a jusante, e o pandapower ainda reporta
    `converged=True` (ele so tira as barras isoladas de servico), mas o
    `_ppc["internal"]` fica sem `V` e a geracao de medicoes quebra. Como
    consequencia, este tipo de erro de topologia e ESTRUTURALMENTE
    inexistente em rede radial pura (`case33bw` com todos os lacos abertos):
    la o caso equivalente e o oposto, `ac_bad_data.inject_topology_error`
    (ramo de reconfiguracao fechado sem o modelo saber).
    """

    import pandapower as pp
    import pandapower.topology as top

    net_real = deepcopy(net)
    net_real.line.at[line_id, "in_service"] = False
    try:
        pp.runpp(net_real, calculate_voltage_angles=True, init="flat", numba=False)
        if len(top.unsupplied_buses(net_real)) > 0:
            return None
    except Exception:
        return None
    if not bool(net_real.converged):
        return None
    return net_real


# ---------------------------------------------------------------------------
# Features da assinatura
# ---------------------------------------------------------------------------


def _concentration_stats(v: np.ndarray, prefix: str, threshold: float) -> dict[str, float]:
    """Estatisticas de FORMA de um vetor de escores (|CME_N| ou |r_N|), todas
    adimensionais e invariantes ao tamanho da rede -- e a forma, nao a
    magnitude, que separa "pico isolado" (medida) de "corcova espalhada"
    (parametro)."""

    a = np.abs(np.asarray(v, dtype=float))
    m = a.size
    order = np.sort(a)[::-1]
    total_sq = float(np.sum(a**2))
    p = (a**2) / total_sq if total_sq > 0 else np.full(m, 1.0 / m)
    with np.errstate(divide="ignore", invalid="ignore"):
        ent = -float(np.sum(np.where(p > 0, p * np.log(p), 0.0)))
    mean, std = float(a.mean()), float(a.std())
    kurt = float(np.mean(((a - mean) / std) ** 4)) if std > 1e-12 else 0.0
    return {
        f"{prefix}_max": float(order[0]),
        f"{prefix}_top2_over_top1": float(order[1] / order[0]) if m > 1 and order[0] > 0 else 0.0,
        f"{prefix}_top4_over_top1": float(order[3] / order[0]) if m > 3 and order[0] > 0 else 0.0,
        f"{prefix}_frac_above_thr": float(np.mean(a > threshold)),
        f"{prefix}_n_above_thr": float(np.sum(a > threshold)),
        # IPR: 1/m = totalmente espalhado, 1.0 = um unico pico.
        f"{prefix}_ipr": float(np.sum(p**2)),
        f"{prefix}_entropy_norm": float(ent / np.log(m)) if m > 1 else 0.0,
        f"{prefix}_kurtosis": kurt,
        f"{prefix}_mean_over_max": float(mean / order[0]) if order[0] > 0 else 0.0,
    }


def _measurement_buses(m: ACMeasurement, net: Any) -> tuple[int, ...]:
    if m.kind in ("v_bus", "va_bus", "p_inj", "q_inj"):
        return (int(m.element),)
    if m.branch_kind == "trafo":
        return (int(net.trafo.at[m.element, "hv_bus"]), int(net.trafo.at[m.element, "lv_bus"]))
    return (int(net.line.at[m.element, "from_bus"]), int(net.line.at[m.element, "to_bus"]))


def signature_features(
    measurements: Sequence[ACMeasurement],
    net: Any,
    geo: Any,
    bus_degree: dict[int, int],
    *,
    j_res_ratio: float,
    j_cme_ratio: float,
    threshold: float = 3.0,
) -> dict[str, float]:
    """Vetor de features da assinatura observada, para alimentar um
    classificador aprendido.

    Nenhuma feature depende do numero de barras/medicoes em unidades brutas
    -- todas sao razoes, fracoes ou escores ja normalizados.

    ATENCAO -- ser adimensional NAO bastou para transferir entre redes.
    Medido em 2026-08-10 (`signature_model.cross_network`): treinando no
    5-bus e testando no 14-bus a acuracia e 0,581 (baseline 0,394) mas o
    recall da classe `none` VAI A ZERO -- o modelo acusa ataque em 100% dos
    casos limpos; e no sentido inverso (14-bus -> 5-bus) da 0,088, muito
    PIOR que o baseline. Dentro da mesma rede o mesmo modelo vai a 0,82
    (5-bus) e 0,86 (14-bus) em leave-one-line-out.

    Ou seja: treinar POR REDE (o que e operacionalmente aceitavel -- cada
    alimentador tem o seu proprio modelo e pode ser simulado), ou trocar a
    representacao por uma que transfira de verdade (GNN sobre o grafo, ver
    `docs/estudos/estimacao_estado/plano_agente_assinatura.md` degrau 2b).
    Nunca reportar acuracia cross-network sem olhar o recall POR CLASSE: a
    acuracia global de 0,581 esconde um falso alarme de 100%.
    """

    cme_n = np.asarray(geo.CME_N, dtype=float)
    r_n = np.asarray(geo.r_N, dtype=float)
    ui = np.asarray(geo.UI, dtype=float)
    k_diag = np.asarray(geo.K_diag, dtype=float)
    m = cme_n.size

    feats: dict[str, float] = {}
    feats.update(_concentration_stats(cme_n, "cme", threshold))
    feats.update(_concentration_stats(r_n, "rn", threshold))

    peak = int(np.argmax(np.abs(cme_n)))
    peak_rn = int(np.argmax(np.abs(r_n)))
    feats["peak_agree_cme_rn"] = float(peak == peak_rn)
    feats["cme_over_rn_max"] = float(
        np.abs(cme_n[peak]) / np.abs(r_n[peak_rn]) if np.abs(r_n[peak_rn]) > 1e-12 else 0.0
    )
    feats["ui_max"] = float(ui.max())
    feats["ui_mean"] = float(ui.mean())
    feats["ui_at_peak"] = float(ui[peak])
    feats["kii_at_peak"] = float(k_diag[peak])
    feats["kii_mean"] = float(k_diag.mean())
    feats["j_res_ratio"] = float(j_res_ratio)
    feats["j_cme_ratio"] = float(j_cme_ratio)

    # --- tipo e vizinhanca da medida de pico -------------------------------
    peak_meas = measurements[peak]
    for kind in ("v_bus", "p_inj", "q_inj", "p_branch", "q_branch"):
        feats[f"peak_is_{kind}"] = float(peak_meas.kind == kind)
    peak_buses = _measurement_buses(peak_meas, net)
    feats["peak_bus_degree"] = float(np.mean([bus_degree.get(b, 0) for b in peak_buses]))

    # --- composicao do conjunto flagrado -----------------------------------
    flagged = [i for i in range(m) if abs(cme_n[i]) > threshold]
    n_flag = len(flagged)
    feats["flag_frac_of_all"] = float(n_flag / m)
    if n_flag:
        kinds = [measurements[i].kind for i in flagged]
        n_branch = sum(k in ("p_branch", "q_branch") for k in kinds)
        n_inj = sum(k in ("p_inj", "q_inj") for k in kinds)
        n_v = sum(k == "v_bus" for k in kinds)
        n_p = sum(k in ("p_inj", "p_branch") for k in kinds)
        n_q = sum(k in ("q_inj", "q_branch") for k in kinds)
        feats["flag_frac_branch"] = n_branch / n_flag
        feats["flag_frac_inj"] = n_inj / n_flag
        feats["flag_frac_vbus"] = n_v / n_flag
        # Erro de parametro perturba P e Q da mesma linha juntos; ataque de
        # medida isolado normalmente atinge so um dos dois.
        feats["flag_pq_balance"] = min(n_p, n_q) / max(1, max(n_p, n_q))
        buses = {b for i in flagged for b in _measurement_buses(measurements[i], net)}
        elements = {
            (measurements[i].branch_kind, measurements[i].element)
            for i in flagged
            if measurements[i].kind in ("p_branch", "q_branch")
        }
        feats["flag_n_buses_over_flagged"] = len(buses) / n_flag
        feats["flag_n_branches_over_flagged"] = len(elements) / n_flag
        feats["flag_mean_bus_degree"] = float(
            np.mean([bus_degree.get(b, 0) for b in buses])
        )
    else:
        for key in (
            "flag_frac_branch", "flag_frac_inj", "flag_frac_vbus", "flag_pq_balance",
            "flag_n_buses_over_flagged", "flag_n_branches_over_flagged",
            "flag_mean_bus_degree",
        ):
            feats[key] = 0.0

    # --- ranking de linhas (a variavel de decisao do baseline) -------------
    _line_id, _idx, ranking = identify_by_line(list(measurements), net, cme_n, threshold=threshold)
    fractions = np.array([row["fraction_flagged"] for row in ranking], dtype=float)
    best = ranking[0]
    feats["best_fraction"] = float(fractions[0])
    feats["second_fraction"] = float(fractions[1]) if fractions.size > 1 else 0.0
    feats["fraction_gap"] = feats["best_fraction"] - feats["second_fraction"]
    feats["n_lines_ge_half"] = float(np.sum(fractions >= 0.5))
    feats["frac_lines_ge_half"] = float(np.mean(fractions >= 0.5))
    feats["best_n_own_over_m"] = float(best["n_own"] / m)

    best_line = int(best["line_id"])
    own_branch = [
        i for i in best["own_idx"]
        if measurements[i].kind in ("p_branch", "q_branch")
        and measurements[i].branch_kind == "line"
        and measurements[i].element == best_line
    ]
    own_inj = [i for i in best["own_idx"] if measurements[i].kind in ("p_inj", "q_inj")]
    feats["best_has_flow_in_set"] = float(bool(own_branch))
    # Discriminante fisico central: um erro de PARAMETRO na linha vencedora
    # perturba h() dos FLUXOS dela e das injecoes terminais ao mesmo tempo;
    # um ataque de MEDIDA numa injecao de barra de grau 2 flagra 50% das
    # medidas proprias sem tocar em NENHUM fluxo -- e cai exatamente no
    # limiar de 0.5 do baseline (achado 13, redes radiais).
    feats["best_own_branch_flagged_frac"] = float(
        np.mean([abs(cme_n[i]) > threshold for i in own_branch]) if own_branch else 0.0
    )
    feats["best_own_inj_flagged_frac"] = float(
        np.mean([abs(cme_n[i]) > threshold for i in own_inj]) if own_inj else 0.0
    )
    feats["best_branch_inj_flag_gap"] = (
        feats["best_own_branch_flagged_frac"] - feats["best_own_inj_flagged_frac"]
    )
    return feats


#: Nomes das features na ordem canonica (preenchido na primeira chamada de
#: `run_case`; exposto para o notebook selecionar colunas sem hardcode).
FEATURE_COLUMNS: list[str] = []


# ---------------------------------------------------------------------------
# Cenario e execucao
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioSpec:
    """Um cenario com verdade conhecida."""

    network: str
    true_type: AttackType
    line_id: int | None
    """Linha atacada (`parameter`/`topology`), ou a linha CUJAS medidas foram
    atacadas no modo `line_cluster` (`measurement`). `None` no modo aleatorio
    e em `none`."""
    magnitude: float
    """`n_sigmas` do erro relativo de parametro, ou `k_sigma` do ataque de
    medida. `0.0` para `none`/`topology`."""
    n_attacked: int
    """Numero de medicoes atacadas (so `measurement`)."""
    target_mode: str
    """`"line_cluster"` (medidas proprias de uma linha -- imita parametro),
    `"random"` (medidas quaisquer) ou `"n/a"`."""
    coherent_signs: bool
    noise_level: float
    seed: int
    param_mode: str = "symmetric"
    """`"symmetric"` = mesmo fator em `r`/`x`/`c` (nosso caso historico);
    `"unbalanced"` = `g`, `b` e `b_sh` erram por percentuais DIFERENTES, que
    e a convencao da linha do grupo do Arturo (Zou et al. 2020, EPSR
    187:106490; Bretas et al., PowerTech 2025). Ver
    `ac_bad_data.inject_parameter_error_unbalanced`."""


@dataclass
class CaseOutcome:
    spec: ScenarioSpec
    true_type: AttackType
    true_line: int | None
    pred_type: AttackType
    pred_line: int | None
    detected_cme: bool
    detected_res: bool
    converged: bool
    attacked_indices: tuple[int, ...] = ()
    features: dict[str, float] = field(default_factory=dict)
    line_rows: list[dict[str, Any]] = field(default_factory=list)
    """Uma entrada por LINHA da rede (features locais + `line_label`), so
    preenchida quando `run_case` recebe `signature_lib`. E o dataset do
    classificador por-linha, que e o que permite treinar numa rede e aplicar
    em outra."""

    def to_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "network": self.spec.network,
            "true_type": self.true_type,
            "true_line": self.true_line,
            # Linha em torno da qual o cenario foi MONTADO, para qualquer
            # classe -- inclui o ataque de medida `line_cluster`, cuja
            # `true_line` e None (o alvo e a medida, nao a linha). E o que
            # `signature_model.leave_one_line_out` precisa para segurar TODOS
            # os casos daquela linha fora do treino; usar `true_line` deixaria
            # os ataques multi-medida daquela linha no treino, o que e
            # vazamento estrutural exatamente no caso mais dificil.
            "scenario_line": self.spec.line_id,
            "pred_type": self.pred_type,
            "pred_line": self.pred_line,
            "correct_type": self.true_type == self.pred_type,
            "correct_line": (
                self.true_line == self.pred_line
                if self.true_type in ("parameter", "topology")
                else None
            ),
            "magnitude": self.spec.magnitude,
            "n_attacked": self.spec.n_attacked,
            "target_mode": self.spec.target_mode,
            "coherent_signs": self.spec.coherent_signs,
            "param_mode": self.spec.param_mode,
            "noise_level": self.spec.noise_level,
            "seed": self.spec.seed,
            "detected_cme": self.detected_cme,
            "detected_res": self.detected_res,
            "converged": self.converged,
            "n_attacked_effective": len(self.attacked_indices),
        }
        row.update(self.features)
        return row


def run_case(
    base: BaseCase,
    spec: ScenarioSpec,
    *,
    alpha: float = 0.05,
    line_threshold: float = 3.0,
    line_fraction_threshold: float = 0.5,
    max_gn_iter: int = 30,
    tol: float = 1e-8,
    signature_lib: tuple[np.ndarray, list[tuple], list[int]] | None = None,
) -> CaseOutcome | None:
    """Monta o cenario, roda UMA estimacao WLS AC e classifica -- a decisao
    da PRIMEIRA iteracao do pipeline geral, que e a que determina se o
    pipeline inteiro vai pelo caminho certo. Retorna `None` se o cenario for
    infactivel (ex.: abertura que ilha a rede).

    `signature_lib = (S, lib_keys, line_ids)` de
    `build_line_signature_library` liga a extracao de features POR LINHA
    (`CaseOutcome.line_rows`), incluindo a correlacao de filtro casado.
    """

    rng = np.random.default_rng(spec.seed)

    net_model = base.net
    clean = base.clean

    if spec.true_type == "topology":
        assert spec.line_id is not None
        net_real = inject_topology_outage(base.net, spec.line_id)
        if net_real is None:
            return None
        try:
            clean = synthetic_full_measurements_from_results(
                net_real, kind=base.meas_kind, noise_level=base.noise_level,
                sigma_min=base.sigma_min,
            )
        except Exception:
            return None
        net_model = base.net  # modelo desatualizado: acha que a linha esta fechada
    elif spec.true_type == "parameter":
        assert spec.line_id is not None
        if spec.param_mode == "unbalanced":
            # Tres percentuais INDEPENDENTES da mesma ordem de grandeza, com
            # sinais sorteados -- reproduz o padrao do caso de referencia do
            # grupo (g -5,3% / b +7,0% / b_sh +6,8%) sem fixar aqueles numeros.
            base_pct = spec.magnitude * 0.01
            deltas = [
                float(s * base_pct * m)
                for s, m in zip(rng.choice([-1.0, 1.0], size=3), rng.uniform(0.6, 1.0, size=3))
            ]
            try:
                net_model, _info = inject_parameter_error_unbalanced(
                    base.net, spec.line_id,
                    dg_pct=deltas[0], db_pct=deltas[1], dbsh_pct=deltas[2],
                )
            except Exception:
                return None
        else:
            net_model, _factor = inject_parameter_error(
                base.net, spec.line_id, param_sigma_pct=0.01, n_sigmas=spec.magnitude
            )

    values = np.array([m.value for m in clean], dtype=float)
    sigmas = np.array([m.sigma for m in clean], dtype=float)
    noisy = sample_noisy_measurement(values, sigmas, seed=spec.seed)
    meas = [
        ACMeasurement(
            kind=m.kind, element=m.element, value=float(noisy[i]),
            sigma=m.sigma, side=m.side, branch_kind=m.branch_kind,
        )
        for i, m in enumerate(clean)
    ]

    attacked: tuple[int, ...] = ()
    if spec.true_type == "measurement":
        if spec.target_mode == "line_cluster":
            assert spec.line_id is not None
            pool = line_own_measurement_indices(meas, base.net, spec.line_id)
        else:
            pool = list(range(len(meas)))
        if len(pool) < spec.n_attacked:
            return None
        chosen = rng.choice(np.asarray(pool), size=spec.n_attacked, replace=False)
        attacked = tuple(int(i) for i in np.sort(chosen))
        signs = (
            [1.0] * spec.n_attacked
            if spec.coherent_signs
            else list(rng.choice([-1.0, 1.0], size=spec.n_attacked))
        )
        meas = inject_measurement_attack(meas, attacked, spec.magnitude, signs=signs)

    try:
        model = build_ac_ybus_model_from_pandapower(net_model, meas)
        result = model.solve(x0=model.flat_start(), max_iter=max_gn_iter, tol=tol)
        H = model.jacobian_finite_difference(result.x)
        r = model.z - model.h(result.x)
        sigma = model.sigma
        geo = compute_geometric_diagnostics(H, np.diag(1.0 / sigma**2), r, sigma)
    except Exception:
        return None
    if not np.all(np.isfinite(geo.CME_N)):
        return None

    m_cur, n_cur = H.shape
    detected_cme, j_cme, thr_cme = detect_chi2_cme(geo.CME_N, m_cur, alpha=alpha)
    detected_res, thr_res = detect_chi2(float(result.objective), dof=m_cur - n_cur, alpha=alpha)

    if detected_cme:
        pred_type, pred_line, _idx = classify_attack_signature(
            meas, net_model, geo.CME_N,
            threshold=line_threshold, line_fraction_threshold=line_fraction_threshold,
        )
    else:
        pred_type, pred_line = "none", None

    j_res_ratio = float(result.objective) / thr_res if thr_res > 0 else 0.0
    j_cme_ratio = float(j_cme) / thr_cme if thr_cme > 0 else 0.0
    feats = signature_features(
        meas, net_model, geo, base.bus_degree,
        j_res_ratio=j_res_ratio, j_cme_ratio=j_cme_ratio, threshold=line_threshold,
    )
    if not FEATURE_COLUMNS:
        FEATURE_COLUMNS.extend(feats.keys())

    line_rows: list[dict[str, Any]] = []
    if signature_lib is not None:
        S_full, lib_keys, lib_line_ids = signature_lib
        S = align_signature_library(S_full, lib_keys, meas)
        mf_corrs = matched_filter_correlations(S, lib_line_ids, geo.r_N)
        _lid, _idx2, ranking = identify_by_line(meas, net_model, geo.CME_N, threshold=line_threshold)
        line_rows = line_level_features(
            meas, net_model, geo, base.bus_degree, ranking, mf_corrs, lib_line_ids,
            j_res_ratio=j_res_ratio, j_cme_ratio=j_cme_ratio, threshold=line_threshold,
        )
        # Rotulo POR LINHA: esta linha e o sitio do que esta errado?
        for row in line_rows:
            lid = int(row["line_id"])
            if spec.true_type in ("parameter", "topology") and lid == spec.line_id:
                row["line_label"] = spec.true_type
            elif (
                spec.true_type == "measurement"
                and spec.target_mode == "line_cluster"
                and lid == spec.line_id
            ):
                row["line_label"] = "meas_cluster"
            else:
                row["line_label"] = "ok"

    true_line = spec.line_id if spec.true_type in ("parameter", "topology") else None
    return CaseOutcome(
        spec=spec,
        true_type=spec.true_type,
        true_line=true_line,
        pred_type=pred_type,  # type: ignore[arg-type]
        pred_line=pred_line,
        detected_cme=bool(detected_cme),
        detected_res=bool(detected_res),
        converged=bool(result.converged),
        attacked_indices=attacked,
        features=feats,
        line_rows=line_rows,
    )


SIGMA_MIN_DEFAULT = 0.005
"""Piso de sigma em pu-de-referencia = 0.5% do `sn_mva` da propria rede
(achado 14 de `manual_bad_data.md`: nunca herdar o piso de outra rede, senao
o falso alarme do teste `CME_N` explode)."""


def build_scenarios(
    network: str,
    *,
    line_ids: Sequence[int],
    param_magnitudes: Sequence[float] = (2.0, 5.0, 10.0, 20.0, 40.0),
    meas_magnitudes: Sequence[float] = (3.0, 5.0, 8.0, 15.0, 30.0),
    n_attacked_values: Sequence[int] = (1, 2, 3, 4),
    noise_levels: Sequence[float] = (0.005, 0.01, 0.02),
    n_seeds_none: int = 400,
    n_seeds_parameter: int = 16,
    n_seeds_topology: int = 30,
    n_seeds_measurement: int = 3,
    seed0: int = 20260810,
    param_mode: str = "unbalanced",
) -> Iterator[ScenarioSpec]:
    """Grade fatorial dos quatro fatores pedidos -- linha, magnitude, ruido e
    numero de medidas atacadas -- mais o modo de escolha do alvo, que e o que
    separa o ataque multi-medida "aleatorio" do multi-medida CONCENTRADO numa
    linha (o que imita um erro de parametro, secao 1.4 da narrativa).

    Os `n_seeds_*` sao diferentes por classe de proposito: a classe
    `measurement` tem 55x mais combinacoes de fatores (5 magnitudes x 4
    numeros de medidas x 3 modos de alvo) que `topology` (nenhuma), entao
    usar o mesmo numero de sementes para todas produziria uma matriz de
    confusao dominada por `measurement` e uma taxa de falso alarme medida
    com poucas amostras. Os defaults deixam as quatro classes na mesma ordem
    de grandeza.

    `n_seeds_none` e alto (400 por nivel de ruido) porque a classe `none`
    nao tem NENHUM fator alem do ruido: e so replicacao Monte Carlo. Com
    poucas amostras ela vira ruido no treino do classificador aprendido --
    medido: com 120 casos `none` o recall dessa classe no GBM caiu para
    0,47 enquanto o baseline ficava em 0,94, o que so refletia falta de
    amostra, nao dificuldade real. Ela tambem e a unica que estima a taxa
    de FALSO ALARME, que precisa de precisao para ser comparada com o
    `alpha` nominal.
    """

    counter = seed0
    for noise in noise_levels:
        # Classe "none": so ruido, sem ataque -- mede falso alarme.
        for _ in range(n_seeds_none):
            counter += 1
            yield ScenarioSpec(network, "none", None, 0.0, 0, "n/a", True, noise, counter)

        for line_id in line_ids:
            for mag in param_magnitudes:
                for _ in range(n_seeds_parameter):
                    counter += 1
                    yield ScenarioSpec(network, "parameter", int(line_id), float(mag), 0, "n/a", True, noise, counter, param_mode)

            for _ in range(n_seeds_topology):
                counter += 1
                yield ScenarioSpec(network, "topology", int(line_id), 0.0, 0, "n/a", True, noise, counter)

            for mag in meas_magnitudes:
                for n_att in n_attacked_values:
                    for mode, coherent in (("line_cluster", True), ("line_cluster", False), ("random", True)):
                        if n_att == 1 and not coherent:
                            continue  # sinal unico: coerente e incoerente sao o mesmo caso
                        for _ in range(n_seeds_measurement):
                            counter += 1
                            yield ScenarioSpec(
                                network, "measurement", int(line_id), float(mag), int(n_att),
                                mode, coherent, noise, counter,
                            )


def run_sweep(
    network: str,
    scenarios: Sequence[ScenarioSpec] | Iterator[ScenarioSpec],
    *,
    meas_kind: str = "scada",
    sigma_min: float = SIGMA_MIN_DEFAULT,
    alpha: float = 0.05,
    line_threshold: float = 3.0,
    line_fraction_threshold: float = 0.5,
    progress_every: int = 250,
    verbose: bool = True,
) -> Any:
    """Roda a varredura e devolve um `pandas.DataFrame` com uma linha por
    cenario (verdade + predicao do baseline + features). Reaproveita o
    `BaseCase` por nivel de ruido."""

    import pandas as pd

    bases: dict[float, BaseCase] = {}
    rows: list[dict[str, Any]] = []
    skipped = 0
    for i, spec in enumerate(scenarios):
        base = bases.get(spec.noise_level)
        if base is None:
            base = build_base_case(
                network, meas_kind=meas_kind, noise_level=spec.noise_level, sigma_min=sigma_min
            )
            bases[spec.noise_level] = base
        outcome = run_case(
            base, spec, alpha=alpha, line_threshold=line_threshold,
            line_fraction_threshold=line_fraction_threshold,
        )
        if outcome is None:
            skipped += 1
            continue
        rows.append(outcome.to_row())
        if verbose and progress_every and (i + 1) % progress_every == 0:
            acc = np.mean([r["correct_type"] for r in rows]) if rows else 0.0
            print(f"  {i + 1} cenarios | acuracia parcial do baseline: {acc:.3f}")
    if verbose:
        print(f"Concluido: {len(rows)} casos validos, {skipped} descartados (infactiveis).")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Filtro casado: biblioteca de assinaturas de linha
# ---------------------------------------------------------------------------


def build_line_signature_library(
    net_base: Any,
    measurements: Sequence[ACMeasurement],
    *,
    factor_test: float = 1.10,
    seed_plan: int = 2026,
    load_jitter: float = 0.05,
) -> tuple[np.ndarray, list[int]]:
    """Pre-calcula `S[:, j]` -- a assinatura de sensibilidade da linha `j`:
    quanto cada medicao se desloca (em unidades de sigma) quando `r`/`x`/`c`
    daquela linha erram por `factor_test`.

    NAO depende de nenhum ataque real -- so de um cenario de planejamento
    tipico (carga perturbada por `load_jitter`), entao e 100% pre-computavel
    offline, uma vez por rede. E preciso um ponto de operacao nao-degenerado:
    `flat start` NAO funciona (achado 12 de `manual_bad_data.md`).

    Promovido do notebook `5_BUS_IEEE_AC_vulnerabilidade_topologica.ipynb`
    (secao 44), que era a pendencia registrada na decisao de 2026-07-21
    ("ainda so implementado no notebook, nao promovido pra biblioteca").
    """

    import pandapower as pp

    rng_plan = np.random.default_rng(seed_plan)
    net_plan = deepcopy(net_base)
    load_factor = 1.0 + rng_plan.uniform(-load_jitter, load_jitter, size=len(net_plan.load))
    net_plan.load["p_mw"] = net_plan.load["p_mw"].to_numpy() * load_factor
    net_plan.load["q_mvar"] = net_plan.load["q_mvar"].to_numpy() * load_factor
    pp.runpp(net_plan, calculate_voltage_angles=True, init="flat", numba=False)

    model_plan = build_ac_ybus_model_from_pandapower(net_plan, list(measurements))
    x_ref = model_plan.state_from_results(net_plan.res_bus["vm_pu"], net_plan.res_bus["va_degree"])
    h_true = model_plan.h(x_ref)
    sigma_ref = model_plan.sigma

    line_ids = [int(i) for i in net_base.line.index]
    S = np.zeros((len(measurements), len(line_ids)))
    for j, line_id in enumerate(line_ids):
        net_test = deepcopy(net_plan)
        for col in ("r_ohm_per_km", "x_ohm_per_km", "c_nf_per_km"):
            net_test.line.at[line_id, col] *= factor_test
        pp.runpp(net_test, calculate_voltage_angles=True, init="flat", numba=False)
        model_test = build_ac_ybus_model_from_pandapower(net_test, list(measurements))
        S[:, j] = (model_test.h(x_ref) - h_true) / sigma_ref
    return S, line_ids


def matched_filter_correlations(S: np.ndarray, line_ids: Sequence[int], r_N: np.ndarray) -> np.ndarray:
    """Correlacao de Pearson entre o residuo normalizado OBSERVADO (`-r_N`) e
    cada assinatura pre-calculada. Uma entrada por linha, na ordem de
    `line_ids`. Usa Pearson (nao produto interno) porque a magnitude do
    deslocamento e desconhecida -- o que identifica a linha e a FORMA."""

    observed = -np.asarray(r_N, dtype=float)
    out = np.zeros(S.shape[1])
    for j in range(S.shape[1]):
        s = S[:, j]
        if np.std(s) < 1e-12 or np.std(observed) < 1e-12:
            out[j] = 0.0
        else:
            out[j] = float(np.corrcoef(s, observed)[0, 1])
    return out


def identify_by_matched_filter(
    S: np.ndarray, line_ids: Sequence[int], r_N: np.ndarray
) -> tuple[int, list[tuple[int, float]]]:
    """Retorna `(linha_vencedora, ranking[(line_id, correlacao)])`."""

    corrs = matched_filter_correlations(S, line_ids, r_N)
    ranking = sorted(zip([int(l) for l in line_ids], corrs), key=lambda t: -t[1])
    return ranking[0][0], ranking


# ---------------------------------------------------------------------------
# Nivel LINHA: features por (snapshot, linha) em vez de por snapshot
# ---------------------------------------------------------------------------
#
# Por que existe: `signature_features` produz UM vetor por snapshot, e a
# decisao e "que tipo de ataque houve nesta rede". Isso amarra o modelo a
# rede em que foi treinado -- medido em 2026-08-10, treinar no 5-bus e testar
# no 14-bus da 0,581 com falso alarme de 100%, e no sentido inverso 0,088.
#
# A alternativa (arXiv 2209.12629, que reivindica independencia da
# configuracao da rede) e mudar a UNIDADE de classificacao: uma amostra passa
# a ser um (snapshot, LINHA), com features todas locais aquela linha. O vetor
# tem tamanho fixo qualquer que seja o numero de barras, e o numero de
# amostras de treino CRESCE com o tamanho da rede em vez de ficar constante.


def measurement_key(m: ACMeasurement) -> tuple:
    """Identidade estavel de uma medicao, para alinhar a biblioteca de
    assinaturas (construida no plano de medicao COMPLETO) com um conjunto que
    perdeu medicoes -- e o caso do erro de topologia, onde os fluxos da linha
    aberta somem da lista."""

    return (m.kind, int(m.element), m.side, m.branch_kind)


def align_signature_library(
    S: np.ndarray, lib_keys: Sequence[tuple], measurements: Sequence[ACMeasurement]
) -> np.ndarray:
    """Reordena/filtra `S` para as linhas de `measurements`, casando por
    `measurement_key`. Medicoes ausentes da biblioteca viram zero."""

    index = {k: i for i, k in enumerate(lib_keys)}
    out = np.zeros((len(measurements), S.shape[1]))
    for i, m in enumerate(measurements):
        j = index.get(measurement_key(m))
        if j is not None:
            out[i, :] = S[j, :]
    return out


def line_level_features(
    measurements: Sequence[ACMeasurement],
    net: Any,
    geo: Any,
    bus_degree: dict[int, int],
    ranking: list[dict[str, Any]],
    mf_corrs: np.ndarray,
    line_ids: Sequence[int],
    *,
    j_res_ratio: float,
    j_cme_ratio: float,
    threshold: float = 3.0,
) -> list[dict[str, Any]]:
    """Uma linha de saida por LINHA da rede, com features locais a ela.

    Todas adimensionais e de tamanho fixo -- nenhuma depende do numero de
    barras/medicoes. As poucas features de contexto global (`ctx_*`) sao
    razoes ja normalizadas, iguais para todas as linhas do mesmo snapshot,
    e existem porque a decisao "esta linha esta errada" depende de quanto
    sinal ha na rede toda (ex.: nada errado em lugar nenhum)."""

    cme = np.abs(np.asarray(geo.CME_N, dtype=float))
    rn = np.abs(np.asarray(geo.r_N, dtype=float))
    ui = np.asarray(geo.UI, dtype=float)
    kii = np.asarray(geo.K_diag, dtype=float)
    m = cme.size
    cme_max_global = float(cme.max()) if m else 0.0
    rn_max_global = float(rn.max()) if m else 0.0

    by_line = {int(r["line_id"]): r for r in ranking}
    mf = {int(l): float(c) for l, c in zip(line_ids, mf_corrs)}
    mf_sorted = sorted(mf.values(), reverse=True)
    fractions = sorted((float(r["fraction_flagged"]) for r in ranking), reverse=True)

    ctx = {
        "ctx_j_res_ratio": j_res_ratio,
        "ctx_j_cme_ratio": j_cme_ratio,
        "ctx_frac_flagged": float(np.mean(cme > threshold)),
        "ctx_cme_ipr": float(np.sum((cme**2 / (np.sum(cme**2) + 1e-30)) ** 2)),
        "ctx_best_fraction": fractions[0] if fractions else 0.0,
        "ctx_mf_best": mf_sorted[0] if mf_sorted else 0.0,
        "ctx_mf_second": mf_sorted[1] if len(mf_sorted) > 1 else 0.0,
    }

    rows: list[dict[str, Any]] = []
    for line_id in line_ids:
        line_id = int(line_id)
        r = by_line.get(line_id)
        own = list(r["own_idx"]) if r else []
        own_branch = [
            i for i in own
            if measurements[i].kind in ("p_branch", "q_branch")
            and measurements[i].branch_kind == "line"
            and measurements[i].element == line_id
        ]
        own_inj = [i for i in own if measurements[i].kind in ("p_inj", "q_inj")]
        from_bus = int(net.line.at[line_id, "from_bus"])
        to_bus = int(net.line.at[line_id, "to_bus"])
        outros_mf = [v for l, v in mf.items() if l != line_id]

        try:
            loading = float(net.res_line.loading_percent.at[line_id]) / 100.0
        except Exception:
            loading = 0.0

        rows.append({
            "line_id": line_id,
            # --- filtro casado (correlacao de FORMA com a assinatura pre-calculada)
            "mf_corr": mf[line_id],
            "mf_margin": mf[line_id] - (max(outros_mf) if outros_mf else 0.0),
            "mf_is_best": float(mf[line_id] >= max(mf.values())),
            # --- contagem de flagradas (a estatistica do baseline)
            "frac_flagged": float(r["fraction_flagged"]) if r else 0.0,
            "frac_own_branch_flagged": float(np.mean([cme[i] > threshold for i in own_branch])) if own_branch else 0.0,
            "frac_own_inj_flagged": float(np.mean([cme[i] > threshold for i in own_inj])) if own_inj else 0.0,
            # --- magnitude RELATIVA (nunca absoluta: nao transfere)
            "cme_own_over_global": (max(cme[i] for i in own) / cme_max_global) if own and cme_max_global > 0 else 0.0,
            "rn_own_over_global": (max(rn[i] for i in own) / rn_max_global) if own and rn_max_global > 0 else 0.0,
            "cme_own_mean_over_global": (float(np.mean([cme[i] for i in own])) / cme_max_global) if own and cme_max_global > 0 else 0.0,
            # --- geometria local
            "ui_own_mean": float(np.mean([ui[i] for i in own])) if own else 0.0,
            "ui_own_max": float(np.max([ui[i] for i in own])) if own else 0.0,
            "kii_own_mean": float(np.mean([kii[i] for i in own])) if own else 0.0,
            # --- estrutura
            "has_flow_in_set": float(bool(own_branch)),
            "n_own_over_m": len(own) / m if m else 0.0,
            "frac_own_that_are_flows": len(own_branch) / len(own) if own else 0.0,
            "deg_from": float(bus_degree.get(from_bus, 0)),
            "deg_to": float(bus_degree.get(to_bus, 0)),
            "deg_min": float(min(bus_degree.get(from_bus, 0), bus_degree.get(to_bus, 0))),
            # --- fisica: linha pouco carregada quase nao mostra erro de parametro
            "loading": loading,
            **ctx,
        })
    return rows


def run_sweep_lines(
    network: str,
    scenarios: Sequence[ScenarioSpec] | Iterator[ScenarioSpec],
    *,
    meas_kind: str = "scada",
    sigma_min: float = 0.005,
    alpha: float = 0.05,
    line_threshold: float = 3.0,
    line_fraction_threshold: float = 0.5,
    progress_every: int = 500,
    verbose: bool = True,
) -> tuple[Any, Any]:
    """Como `run_sweep`, mas devolve `(df_snapshot, df_linha)`.

    `df_linha` tem uma linha por (cenario, LINHA da rede) -- o formato longo
    que permite treinar um classificador cujo vetor de entrada tem tamanho
    fixo qualquer que seja a rede. `snapshot_id` liga as duas tabelas.
    """

    import pandas as pd

    bases: dict[float, BaseCase] = {}
    libs: dict[float, tuple[np.ndarray, list[tuple], list[int]]] = {}
    snap_rows: list[dict[str, Any]] = []
    line_rows: list[dict[str, Any]] = []
    skipped = 0
    for i, spec in enumerate(scenarios):
        base = bases.get(spec.noise_level)
        if base is None:
            base = build_base_case(
                network, meas_kind=meas_kind, noise_level=spec.noise_level, sigma_min=sigma_min
            )
            bases[spec.noise_level] = base
            S, lids = build_line_signature_library(base.net, base.clean)
            libs[spec.noise_level] = (S, [measurement_key(m) for m in base.clean], lids)
            if verbose:
                print(f"  biblioteca de assinaturas (ruido {spec.noise_level}): S{S.shape}")
        outcome = run_case(
            base, spec, alpha=alpha, line_threshold=line_threshold,
            line_fraction_threshold=line_fraction_threshold,
            signature_lib=libs[spec.noise_level],
        )
        if outcome is None:
            skipped += 1
            continue
        snap_id = len(snap_rows)
        row = outcome.to_row()
        row["snapshot_id"] = snap_id
        snap_rows.append(row)
        for lr in outcome.line_rows:
            lr = dict(lr)
            lr["snapshot_id"] = snap_id
            lr["network"] = network
            lr["true_type"] = outcome.true_type
            lr["magnitude"] = spec.magnitude
            lr["noise_level"] = spec.noise_level
            lr["n_attacked"] = spec.n_attacked
            lr["target_mode"] = spec.target_mode
            line_rows.append(lr)
        if verbose and progress_every and (i + 1) % progress_every == 0:
            print(f"  {i + 1} cenarios | {len(line_rows)} amostras por-linha")
    if verbose:
        print(f"Concluido: {len(snap_rows)} snapshots, {len(line_rows)} amostras por-linha, "
              f"{skipped} descartados.")
    return pd.DataFrame(snap_rows), pd.DataFrame(line_rows)


def build_line_subspace_library(
    net_base: Any,
    measurements: Sequence[ACMeasurement],
    *,
    eps: float = 0.05,
    seed_plan: int = 2026,
    load_jitter: float = 0.05,
) -> dict[int, np.ndarray]:
    """Filtro casado de SUBESPACO: para cada linha, uma base ortonormal das
    TRES direcoes de sensibilidade `dh/dg`, `dh/db`, `dh/db_sh` (em unidades
    de sigma), em vez de um unico vetor.

    Por que existe: `build_line_signature_library` monta UM vetor por linha,
    perturbando `r`/`x`/`c` pelo MESMO fator. Isso e um template SIMETRICO —
    e falha quando o erro real e DESBALANCEADO (`g`, `b`, `b_sh` com
    percentuais diferentes), que e o modelo de erro da linha do grupo do
    Arturo (Zou et al. 2020; Bretas et al., PowerTech 2025). Medido no
    `case9` com erro desbalanceado: fracao flagrada 0,458, filtro casado de
    vetor unico **0,243** (pior que a fracao!), subespaco 3D **0,812**.

    Um erro desbalanceado vive em algum lugar do subespaco tridimensional
    gerado por essas direcoes, nao numa direcao fixa. Por isso o escore certo
    e a fracao do residuo EXPLICADA pela projecao ortogonal nesse subespaco,
    e nao a correlacao com um vetor.

    Direcoes degeneradas sao descartadas por SVD -- necessario porque linhas
    com `r = 0` (os "trafos" do `case9`) nao tem sensibilidade a `g`.

    Retorna `{line_id: U}` com `U` de shape `(m, k<=3)` ortonormal.
    """

    import pandapower as pp

    from .ac_bad_data import inject_parameter_error_unbalanced

    rng = np.random.default_rng(seed_plan)
    net_plan = deepcopy(net_base)
    factor = 1.0 + rng.uniform(-load_jitter, load_jitter, size=len(net_plan.load))
    net_plan.load["p_mw"] = net_plan.load["p_mw"].to_numpy() * factor
    net_plan.load["q_mvar"] = net_plan.load["q_mvar"].to_numpy() * factor
    pp.runpp(net_plan, calculate_voltage_angles=True, init="flat", numba=False)

    model_plan = build_ac_ybus_model_from_pandapower(net_plan, list(measurements))
    x_ref = model_plan.state_from_results(net_plan.res_bus["vm_pu"], net_plan.res_bus["va_degree"])
    h_ref = model_plan.h(x_ref)
    sigma_ref = model_plan.sigma

    lib: dict[int, np.ndarray] = {}
    for line_id in [int(i) for i in net_base.line.index]:
        cols = []
        for which in ("dg_pct", "db_pct", "dbsh_pct"):
            kwargs = {"dg_pct": 0.0, "db_pct": 0.0, "dbsh_pct": 0.0}
            kwargs[which] = eps
            try:
                net_pert, _ = inject_parameter_error_unbalanced(net_plan, line_id, **kwargs)
                model_pert = build_ac_ybus_model_from_pandapower(net_pert, list(measurements))
                cols.append((model_pert.h(x_ref) - h_ref) / (eps * sigma_ref))
            except Exception:
                cols.append(np.zeros(len(measurements)))
        S = np.column_stack(cols)
        U, sv, _ = np.linalg.svd(S, full_matrices=False)
        keep = sv > 1e-8 * max(float(sv.max()), 1e-30)
        lib[line_id] = U[:, keep]
    return lib


def subspace_scores(lib: dict[int, np.ndarray], r_N: np.ndarray) -> dict[int, float]:
    """Fracao da energia de `r_N` explicada pela projecao ortogonal no
    subespaco de cada linha. Em [0, 1]; quanto maior, mais o residuo
    observado "cabe" no que um erro de parametro daquela linha produziria."""

    r = np.asarray(r_N, dtype=float)
    norm2 = float(r @ r)
    if norm2 < 1e-24:
        return {int(l): 0.0 for l in lib}
    return {
        int(l): (float(np.sum((U.T @ r) ** 2)) / norm2) if U.size else 0.0
        for l, U in lib.items()
    }


def identify_by_subspace(
    lib: dict[int, np.ndarray], r_N: np.ndarray
) -> tuple[int | None, list[tuple[int, float]]]:
    """Retorna `(linha_vencedora, ranking[(line_id, escore)])`."""

    scores = subspace_scores(lib, r_N)
    if not scores:
        return None, []
    ranking = sorted(scores.items(), key=lambda t: -t[1])
    return ranking[0][0], ranking


def normalized_residual_covariance(H: np.ndarray, W: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Covariancia do residuo NORMALIZADO `r_N`: `D^-1/2 (I-K) R D^-1/2`."""

    from .bad_data import hat_matrix

    K = hat_matrix(H, W)
    R = np.diag(np.asarray(sigma, dtype=float) ** 2)
    Omega = (np.eye(len(sigma)) - K) @ R
    d = np.sqrt(np.clip(np.diag(Omega), 1e-30, None))
    return Omega / np.outer(d, d)


def subspace_scores_normalized(
    lib: dict[int, np.ndarray], r_N: np.ndarray, omega_n: np.ndarray
) -> dict[int, float]:
    """Escore de subespaco DESENVIESADO: energia projetada dividida pela
    energia que se esperaria so do ruido naquele subespaco.

        score_l = ||U_l^T r_N||^2 / trace(U_l^T Omega_N U_l)

    Por que: `subspace_scores` (bruto) compara energias projetadas de
    subespacos que capturam quantidades DIFERENTES de ruido -- um subespaco
    alinhado com as direcoes de residuo mais ruidosas ganha por default,
    mesmo sem erro nenhum naquela linha. Sob H0, `E[||U^T r_N||^2] =
    trace(U^T Omega_N U)`, entao dividir por isso coloca todas as linhas na
    mesma escala (razao ~1 sob H0, >>1 quando o erro e mesmo daquela linha).

    Medido com erro desbalanceado, bruto -> normalizado (top-1 / top-3):
    5-bus 0,535/0,722 -> **0,556/0,785**; 9-bus 0,812/0,917 ->
    **0,847/0,944**; 14-bus 0,286/0,442 -> **0,389/0,606**. Ganho maior
    justamente na rede onde o metodo estava pior.
    """

    r = np.asarray(r_N, dtype=float)
    out: dict[int, float] = {}
    for line_id, U in lib.items():
        if U.size == 0:
            out[int(line_id)] = 0.0
            continue
        num = float(np.sum((U.T @ r) ** 2))
        den = float(np.trace(U.T @ omega_n @ U))
        out[int(line_id)] = num / den if den > 1e-12 else 0.0
    return out


def identify_by_subspace_normalized(
    lib: dict[int, np.ndarray], r_N: np.ndarray, omega_n: np.ndarray
) -> tuple[int | None, list[tuple[int, float]]]:
    """`(linha_vencedora, ranking)` usando o escore desenviesado. E o
    identificador de linha recomendado: use o top-k deste ranking como
    candidatas para a verificacao fisica."""

    scores = subspace_scores_normalized(lib, r_N, omega_n)
    if not scores:
        return None, []
    ranking = sorted(scores.items(), key=lambda t: -t[1])
    return ranking[0][0], ranking


# ---------------------------------------------------------------------------
# Identificacao como SELECAO DE MODELO entre subespacos (GLRT)
# ---------------------------------------------------------------------------
#
# Formulacao. Depois de resolver o WLS com o parametro errado `p0`, o residuo
# `r = z - h(x_hat, p0)` satisfaz `H^T W r = 0`. Cada hipotese de erro define
# um subespaco de direcoes admissiveis no espaco de medicao:
#
#     H_0        : r e so ruido
#     H_med(i)   : r ~ e_i             (direcao canonica -- uma medida errada)
#     H_par(l)   : r em span(S_l)      S_l = dh/dp_l, (m x 3) para g, b, b_sh
#     H_top(l)   : r na direcao da mudanca topologica de l
#
# Liberando o parametro da linha `l`, a reducao do custo e EXATAMENTE (no
# modelo linearizado):
#
#     J_0 - J_l = r^T W M_l (M_l^T W M_l)^+ M_l^T W r ,   M_l = (I - K) S_l
#
# O fator `(I - K)` e o ponto central: remove a parte da sensibilidade que o
# ESTADO absorve -- o mesmo mascaramento que `UI`/`CME` quantificam na linha
# do Bretas, aqui aplicado ao SUBESPACO do parametro em vez de a uma medida
# isolada. Sob H0, `J_0 - J_l ~ chi2(k_l)` com `k_l = rank(M_l)`, entao o
# escore comparavel entre linhas de dimensoes diferentes e `(J_0-J_l)/k_l`.
#
# Duas consequencias:
#
# 1. UNIFICACAO. Com `S = e_i` (uma medida), a formula reduz a `r_N,i^2` -- o
#    teste do residuo normalizado classico e o caso `k=1` desta familia.
#    Verificado numericamente (concordancia < 1e-9).
# 2. CUSTO. Bretas et al. (PowerTech 2025) evitam aumentar o vetor de estado
#    (`X = {x} -> {x, rho}`) por custo, e pagam com correcao SEQUENCIAL. A
#    projecao no subespaco pre-calculado da o mesmo efeito com UMA execucao do
#    estimador: acerto de linha 0,833 vs 0,370 com 1 vs 11,9 execucoes (9-bus).
#
# Ganho sobre o escore de subespaco normalizado (top-1 / top-3):
# 9-bus 0,847/0,944 -> 0,854/0,944; 14-bus 0,419/0,619 -> 0,519/0,719.


def parameter_sensitivity_library(
    net_base: Any,
    measurements: Sequence[ACMeasurement],
    *,
    eps: float = 0.05,
    seed_plan: int = 2026,
    load_jitter: float = 0.05,
) -> dict[int, np.ndarray]:
    """`S_l = dh/dp_l` (m x 3) em unidades FISICAS -- sem dividir por sigma,
    ao contrario de `build_line_subspace_library`, porque o GLRT ja carrega a
    metrica `W`. Calculada UMA vez, offline, num ponto de operacao de
    planejamento (flat start nao serve)."""

    import pandapower as pp

    from .ac_bad_data import inject_parameter_error_unbalanced

    rng = np.random.default_rng(seed_plan)
    net_plan = deepcopy(net_base)
    factor = 1.0 + rng.uniform(-load_jitter, load_jitter, size=len(net_plan.load))
    net_plan.load["p_mw"] = net_plan.load["p_mw"].to_numpy() * factor
    net_plan.load["q_mvar"] = net_plan.load["q_mvar"].to_numpy() * factor
    pp.runpp(net_plan, calculate_voltage_angles=True, init="flat", numba=False)

    model_plan = build_ac_ybus_model_from_pandapower(net_plan, list(measurements))
    x_ref = model_plan.state_from_results(
        net_plan.res_bus["vm_pu"], net_plan.res_bus["va_degree"])
    h_ref = model_plan.h(x_ref)

    lib: dict[int, np.ndarray] = {}
    for line_id in [int(i) for i in net_base.line.index]:
        cols = []
        for which in ("dg_pct", "db_pct", "dbsh_pct"):
            kwargs = {"dg_pct": 0.0, "db_pct": 0.0, "dbsh_pct": 0.0}
            kwargs[which] = eps
            try:
                net_pert, _ = inject_parameter_error_unbalanced(net_plan, line_id, **kwargs)
                model_pert = build_ac_ybus_model_from_pandapower(net_pert, list(measurements))
                cols.append((model_pert.h(x_ref) - h_ref) / eps)
            except Exception:
                cols.append(np.zeros(len(measurements)))
        lib[line_id] = np.column_stack(cols)
    return lib


def glrt_delta_j(
    S: np.ndarray, H: np.ndarray, W: np.ndarray, r: np.ndarray,
    K: np.ndarray | None = None,
) -> tuple[float, int]:
    """`(J_0 - J_S, k)` -- quanto o custo cai ao liberar as direcoes de `S`, e
    o rank efetivo depois de remover o que o estado absorve.

    Caso `k=1` com `S = e_i` devolve exatamente `r_N,i^2`, o residuo
    normalizado ao quadrado: o teste classico e um membro desta familia.
    """

    from .bad_data import hat_matrix

    if K is None:
        K = hat_matrix(H, W)
    S2 = np.asarray(S, dtype=float)
    if S2.ndim == 1:
        S2 = S2.reshape(-1, 1)
    M = (np.eye(H.shape[0]) - K) @ S2
    A = M.T @ W @ M
    b = np.atleast_1d(M.T @ (W @ r))
    u, sv, vt = np.linalg.svd(np.atleast_2d(A))
    keep = sv > 1e-10 * max(float(sv.max()), 1e-30)
    if not keep.any():
        return 0.0, 0
    A_pinv = (vt[keep].T * (1.0 / sv[keep])) @ u[:, keep].T
    return float(b @ A_pinv @ b), int(keep.sum())


def identify_by_glrt(
    sens_lib: dict[int, np.ndarray],
    H: np.ndarray,
    W: np.ndarray,
    r: np.ndarray,
    *,
    per_dof: bool = True,
) -> tuple[int | None, list[tuple[int, float]], dict[int, int]]:
    """Ranqueia as linhas por `(J_0 - J_l)/k_l` (default; `per_dof=False` usa
    `J_0 - J_l` cru). Retorna `(vencedora, ranking, k_por_linha)`.

    UMA execucao do estimador basta: `H`, `W` e `r` vem dela, e `sens_lib` e
    pre-calculada offline por `parameter_sensitivity_library`."""

    from .bad_data import hat_matrix

    K = hat_matrix(H, W)
    scores: dict[int, float] = {}
    ks: dict[int, int] = {}
    for line_id, S in sens_lib.items():
        dj, k = glrt_delta_j(S, H, W, r, K=K)
        ks[int(line_id)] = k
        scores[int(line_id)] = (dj / k if (per_dof and k) else dj)
    if not scores:
        return None, [], ks
    ranking = sorted(scores.items(), key=lambda t: -t[1])
    return ranking[0][0], ranking, ks


# ---------------------------------------------------------------------------
# Topologia NAO e uma hipotese concorrente: e uma REGIAO de H_par
# ---------------------------------------------------------------------------
#
# Medido (case9 e case14): a fracao da direcao de topologia `S_top(l)` que cabe
# em `span(S_par(l))` da MESMA linha e **1,0000** -- mediana E minimo. Faz
# sentido: abrir o ramo e o erro de parametro no limite `dp = -p0`. Logo
# `H_top(l)` e `H_par(l)` NAO sao hipoteses concorrentes, sao aninhadas, e
# compara-las por AIC/p-valor e mal-posto -- medido: dependendo da rede e do
# criterio, uma delas vence SISTEMATICAMENTE (topologia 0/36 no case9;
# parametro 0/180 no case14).
#
# O que as separa nao e a DIRECAO, e a MAGNITUDE do `dp` ajustado. Dai a
# decisao em dois niveis:
#
#   nivel 1 (QUAL linha) : argmax_l (J_0 - J_l)/k_l          -- geometria
#   nivel 2 (QUAL tipo)  : |dp_hat| pequeno -> parametro     -- magnitude
#                          |dp_hat| ~ 1     -> topologia
#
# `|dp_hat|` mediano medido (mudanca fracionaria): erro de parametro 0,21-0,22
# contra 3,5-8,1 na abertura de ramo -- separacao de 16x a 39x. O valor passar
# de 1,0 na topologia e esperado: a linearizacao "estoura" para dp = -1, o que
# so torna a separacao mais limpa. Resultado (so casos detectados):
# case9 acuracia de tipo **0,848** e acerto de linha **0,905** (baseline
# 0,298/0,293); case14 **0,769** e **0,835** (baseline 0,317/0,230), com
# topologia 36/36 e 59/59 -- perfeita nas duas redes.
#
# Consequencia pratica: NAO e preciso uma biblioteca de sensibilidade de
# topologia. `parameter_sensitivity_library` basta para os tres tipos.


def fit_parameter_change(
    S: np.ndarray, H: np.ndarray, W: np.ndarray, r: np.ndarray,
    *, eps_lib: float = 1.0, K: np.ndarray | None = None,
) -> tuple[np.ndarray, float, int]:
    """`(dp_hat, J_0 - J, k)` -- a mudanca FRACIONARIA de parametro que melhor
    explica o residuo, junto com o quanto ela reduz o custo.

    `dp_hat` sai como mudanca FRACIONARIA direta: `dp_hat[0] = -0.053`
    significa "g caiu 5,3%"; `dp_hat ~ -1` significa "o parametro foi a zero",
    isto e, o ramo sumiu. E o que permite o nivel 2 da classificacao.

    Nao ha reescala por `eps_lib`: `parameter_sensitivity_library` ja divide a
    diferenca por `eps`, entao `S` esta em "delta h por unidade de mudanca
    fracionaria" e o coeficiente de minimos quadrados ja e a propria mudanca
    fracionaria. `eps_lib` fica no argumento so para o caso de uma biblioteca
    montada sem essa normalizacao."""

    from .bad_data import hat_matrix

    if K is None:
        K = hat_matrix(H, W)
    S2 = np.asarray(S, dtype=float)
    if S2.ndim == 1:
        S2 = S2.reshape(-1, 1)
    M = (np.eye(H.shape[0]) - K) @ S2
    A = M.T @ W @ M
    b = np.atleast_1d(M.T @ (W @ r))
    u, sv, vt = np.linalg.svd(np.atleast_2d(A))
    keep = sv > 1e-10 * max(float(sv.max()), 1e-30)
    if not keep.any():
        return np.zeros(S2.shape[1]), 0.0, 0
    A_pinv = (vt[keep].T * (1.0 / sv[keep])) @ u[:, keep].T
    coef = A_pinv @ b
    return coef, float(b @ A_pinv @ b), int(keep.sum())


def classify_by_glrt(
    sens_lib: dict[int, np.ndarray],
    H: np.ndarray,
    W: np.ndarray,
    r: np.ndarray,
    r_N: np.ndarray,
    *,
    eps_lib: float = 1.0,
    tau_topology: float = 1.0,
    tau_measurement: float = 6.0,
) -> tuple[str, int | None, dict[str, Any]]:
    """Classifica medida x parametro x topologia por seleção de modelo entre
    subespacos, em UMA execucao do estimador.

    Substituto de `ac_bad_data.classify_attack_signature` (a regra da p. 213).
    Medido nos casos detectados -- acuracia de tipo / acerto de linha:
    case9 **0,848 / 0,905** contra 0,298/0,293 do baseline; case14
    **0,769 / 0,835** contra 0,317/0,230. Topologia sai 36/36 e 59/59.

    - `tau_topology`: |dp_hat| acima disto e abertura de ramo, nao erro de
      parametro. Interpretacao fisica direta: `dp_hat = -1` e "o parametro foi
      a zero". Default 1,0 -- o otimo medido fica em 1,0 (case9) e 1,5
      (case14); a separacao e larga, entao o valor exato importa pouco.
    - `tau_measurement`: |r_N| do pico isolado acima disto, com `dp_hat`
      pequeno, indica erro de MEDIDA.

    Retorna `(tipo, line_id_ou_None, diagnostico)`.
    """

    from .bad_data import hat_matrix

    K = hat_matrix(H, W)
    melhor_l, melhor_score, melhor_dp, melhor_k = None, -np.inf, None, 0
    for line_id, S in sens_lib.items():
        dp, dj, k = fit_parameter_change(S, H, W, r, eps_lib=eps_lib, K=K)
        if k and dj / k > melhor_score:
            melhor_l, melhor_score, melhor_dp, melhor_k = int(line_id), dj / k, dp, k

    mag = float(np.max(np.abs(melhor_dp))) if melhor_dp is not None else 0.0
    rn_peak = float(np.max(np.abs(np.asarray(r_N))))
    diag = {"line": melhor_l, "score": melhor_score, "dp_hat": melhor_dp,
            "mag_dp": mag, "k": melhor_k, "rn_peak": rn_peak}

    if mag > tau_topology:
        return "topology", melhor_l, diag
    if rn_peak > tau_measurement:
        return "measurement", None, diag
    return "parameter", melhor_l, diag
