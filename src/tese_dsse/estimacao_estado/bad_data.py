"""Analise geometrica de erros grosseiros (Bretas et al. 2013).

As funcoes abaixo operam sobre ``H``, ``W``, ``r`` e ``sigma`` de forma
generica -- nao importa se ``H`` vem de um estimador DC linear (constante)
ou de um estimador AC (Jacobiano avaliado no ponto convergido, ``H(x*)``).
A decomposicao geometrica do erro (``e = e_U + e_D``), a hat matrix, o
Undetectability Index e o CME dependem apenas da forma matricial do
problema WLS, nao do modelo fisico por tras de ``H``.

Nomenclatura (artigo original, secao II-III, eq. 5-10):

- ``K`` -- hat matrix (``P`` no artigo).
- ``e_U = K e`` -- componente nao-detectavel (mascarada) do erro.
- ``e_D = (I - K) e = r`` -- componente detectavel (o residuo classico).
- ``UI_i = K_ii / (1 - K_ii)`` -- Undetectability Index.
- ``CME_i = sqrt(r_i^2 + e_U,i^2)`` -- Composed Measurement Error (eq. 9-10).
- ``CME_N = CME / sigma`` -- normalizacao exigida para comparar com o
  limiar de decisao (~3), do mesmo jeito que o residuo normalizado do LNR.
- ``CNE_i = (1 + UI_i) * r_i / sigma_i`` -- Composed Normalized Error
  (Bretas & Bretas 2018, eq. 20): normaliza o residuo por sigma e DEPOIS
  compoe o erro, entao vive no subespaco do residuo (dim ``m-n``); CME_N e
  CNE sao formalmente iguais mas numericamente diferentes (Remark 2 do
  artigo). Papel de cada um (reuniao Arturo 2026-07-05): deteccao -> CME_N;
  identificacao -> CME_N; **correcao -> CNE** (unica etapa que usa o CNE).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .dc_linear import chi2_limit

__all__ = [
    "GeometricDiagnostics",
    "hat_matrix",
    "undetectability_index",
    "residual_covariance",
    "state_covariance",
    "state_uncertainty",
    "normalized_residual",
    "masked_error",
    "composed_measurement_error",
    "composed_normalized_error",
    "compute_geometric_diagnostics",
    "detect_chi2",
    "detect_chi2_cme",
    "identify_lnr",
    "identify_cme",
    "remove_measurement",
    "correct_measurement",
    "extended_gauss_weights",
    "BadDataPipelineResult",
    "run_bad_data_pipeline",
    "chi2_limit",
]


def hat_matrix(H: np.ndarray, W: np.ndarray) -> np.ndarray:
    """``K = H (H^T W H)^-1 H^T W`` -- projeta ``z`` sobre ``col(H)`` (eq. 5)."""

    H = np.asarray(H, dtype=float)
    G = H.T @ W @ H
    return H @ np.linalg.solve(G, H.T @ W)


def undetectability_index(K_diag: np.ndarray) -> np.ndarray:
    """``UI_i = K_ii / (1 - K_ii)``."""

    K_diag = np.asarray(K_diag, dtype=float)
    return K_diag / np.maximum(1.0 - K_diag, 1e-12)


def residual_covariance(H: np.ndarray, W: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """``Omega = R - H (H^T W H)^-1 H^T``, com ``R = diag(sigma^2)``."""

    H = np.asarray(H, dtype=float)
    R = np.diag(np.asarray(sigma, dtype=float) ** 2)
    G = H.T @ W @ H
    return R - H @ np.linalg.solve(G, H.T)


def normalized_residual(
    r: np.ndarray, H: np.ndarray, W: np.ndarray, sigma: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """``r_N = r / sqrt(diag(Omega))``. Retorna ``(r_N, sigma_r)``."""

    Omega = residual_covariance(H, W, sigma)
    sigma_r = np.sqrt(np.maximum(np.diag(Omega), 1e-16))
    return np.asarray(r, dtype=float) / sigma_r, sigma_r


def masked_error(K_diag: np.ndarray, r: np.ndarray) -> np.ndarray:
    """``e_U,i = K_ii/(1-K_ii) * r_i`` -- componente mascarada (eq. 6-8)."""

    return undetectability_index(K_diag) * np.asarray(r, dtype=float)


def composed_measurement_error(
    r: np.ndarray, e_U: np.ndarray, sigma: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """``CME = sqrt(r^2 + e_U^2)``; ``CME_N = CME / sigma`` (eq. 9-10)."""

    r = np.asarray(r, dtype=float)
    e_U = np.asarray(e_U, dtype=float)
    cme = np.sqrt(r**2 + e_U**2)
    return cme, cme / np.asarray(sigma, dtype=float)


def composed_normalized_error(
    r: np.ndarray, sigma: np.ndarray, UI: np.ndarray
) -> np.ndarray:
    """``CNE_i = (1 + UI_i) * r_i / sigma_i`` (Bretas & Bretas 2018, eq. 20).

    Primeiro normaliza o residuo por ``sigma`` (nao pelo ``sigma_r`` da
    eq. 15 -- as duas leituras fecham: ``(1+UI)*r/sigma ==
    sqrt(1+UI)*r_N(eq.15)``) e depois compoe o erro (``UI_i = 1/II_i^2``).
    Por isso o CNE vive no subespaco do residuo (dim ``m-n``) e nao no
    espaco de medidas (dim ``m``) como o ``CME_N`` -- as matrizes de
    projecao sao diferentes em cada espaco, logo os valores sao
    numericamente diferentes (Remark 2 do artigo). Como a correcao de uma
    medida so pode ser feita no subespaco do residuo, o CNE e a grandeza
    correta para a correcao via ``z_true`` (``correct_measurement``);
    adimensional, em multiplos de ``sigma``. Com o mascaramento
    ``r_i ~ (1-K_ii) b sigma_i``, um erro injetado ``b*sigma`` produz
    ``CNE ~ b`` exato -- e o que o artigo valida ("the added error magnitude
    and the estimated normalized error, CNE, are very close"). Preserva o
    sinal de ``r``.
    """

    r = np.asarray(r, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    return (1.0 + np.asarray(UI, dtype=float)) * r / sigma


@dataclass(frozen=True)
class GeometricDiagnostics:
    """Pacote de diagnosticos geometricos de uma estimacao WLS (Bretas 2013)."""

    K: np.ndarray
    K_diag: np.ndarray
    UI: np.ndarray
    sigma_r: np.ndarray
    r_N: np.ndarray
    e_U: np.ndarray
    CME: np.ndarray
    CME_N: np.ndarray
    CNE: np.ndarray


def compute_geometric_diagnostics(
    H: np.ndarray, W: np.ndarray, r: np.ndarray, sigma: np.ndarray
) -> GeometricDiagnostics:
    """Calcula hat matrix, UI, resíduo normalizado, ``e_U``, CME e CNE de uma vez."""

    K = hat_matrix(H, W)
    K_diag = np.diag(K)
    UI = undetectability_index(K_diag)
    r_N, sigma_r = normalized_residual(r, H, W, sigma)
    e_U = masked_error(K_diag, r)
    CME, CME_N = composed_measurement_error(r, e_U, sigma)
    CNE = composed_normalized_error(r, sigma, UI)
    return GeometricDiagnostics(
        K=K, K_diag=K_diag, UI=UI, sigma_r=sigma_r, r_N=r_N, e_U=e_U, CME=CME,
        CME_N=CME_N, CNE=CNE,
    )


def state_covariance(H: np.ndarray, W: np.ndarray) -> np.ndarray:
    """``Cov(x_hat) = G^-1 = (H^T W H)^-1`` -- covariancia do ESTADO estimado.

    Complemento exato de :func:`residual_covariance`: aquela vive no espaco
    de medidas (dim ``m``) e diz o quanto o residuo pode variar; esta vive no
    espaco de estados (dim ``n``) e diz o quanto a ESTIMATIVA pode variar.

    Sob ruido gaussiano sem erro grosseiro, ``x_hat - x = G^-1 H^T W e`` e
    ``r = (I - K) e`` sao **descorrelacionados** (``Cov(x_hat - x, r) = 0``,
    ver `state_uncertainty`), ou seja: o ``J(x)`` do teste qui-quadrado nao
    carrega informacao sobre o erro do estado naquele snapshot. Quem responde
    "qual a confianca da minha estimativa" e esta matriz, nao o ``J``.

    Nao depende de ``z``: so de topologia, ponto de operacao (via ``H``) e de
    onde estao os medidores (via ``W``). E portanto uma metrica *a priori*,
    calculavel sem estado verdadeiro -- ao contrario do RMSE.
    """

    H = np.asarray(H, dtype=float)
    G = H.T @ np.asarray(W, dtype=float) @ H
    return np.linalg.inv(G)


def state_uncertainty(
    H: np.ndarray, W: np.ndarray, confidence: float = 0.95
) -> tuple[np.ndarray, np.ndarray]:
    """Desvio padrao por estado e meia-largura do intervalo de confianca.

    Retorna ``(sigma_x, half_width)`` onde ``sigma_x_i = sqrt(G^-1_ii)`` e
    ``half_width_i = k * sigma_x_i``, com ``k`` o quantil normal bilateral
    (``k ~ 1.96`` para 95%). Unidades sao as do proprio estado (rad para
    angulo, pu para modulo de tensao no estimador AC).

    E o "RMSE esperado" de cada estado antes de ver qualquer medida: numa
    barra de fim de alimentador mal observada ``sigma_x`` explode, e e
    exatamente ali que um ataque passa despercebido pelo qui-quadrado.
    """

    from scipy.stats import norm

    sigma_x = np.sqrt(np.maximum(np.diag(state_covariance(H, W)), 0.0))
    k = float(norm.ppf(0.5 + confidence / 2.0))
    return sigma_x, k * sigma_x


def detect_chi2(J: float, dof: int, alpha: float = 0.05) -> tuple[bool, float]:
    """Teste classico: ``J > chi2_(1-alpha, dof)`` => bad data detectado."""

    threshold = chi2_limit(alpha, dof)
    return bool(J > threshold), threshold


def detect_chi2_cme(
    CME_N: np.ndarray, m: int, alpha: float = 0.05
) -> tuple[bool, float, float]:
    """Deteccao via CME (Bretas & Bretas 2018, eq. 18-19).

    ``J_cme = sum(CME_N_i^2)`` vive no espaco de medidas (dimensao ``m``),
    nao no subespaco do residuo (``m - n``); por isso o limiar qui-quadrado
    usa ``m`` graus de liberdade, nao ``m - n`` como em ``detect_chi2``.
    Retorna ``(detectado, J_cme, limiar)``.
    """

    J_cme = float(np.sum(np.asarray(CME_N, dtype=float) ** 2))
    threshold = chi2_limit(alpha, m)
    return bool(J_cme > threshold), J_cme, threshold


def detect_chi2_cme_satterthwaite(
    CME_N: np.ndarray,
    K_diag: np.ndarray,
    UI: np.ndarray,
    alpha: float = 0.05,
) -> tuple[bool, float, float, float]:
    """Deteccao via CME com graus de liberdade EFETIVOS (Satterthwaite).

    `detect_chi2_cme` assume `J_cme ~ chi2(m)`, o que so vale se as `m`
    parcelas `CME_N_i^2` tiverem variancia parecida. Quando o plano de medicao
    mistura classes de sensor com precisoes muito diferentes (pseudo tem
    `p_sigma_mult=10`, PMU tem 0,1), o `UI` fica heterogeneo, a variancia de
    cada parcela diverge, e o teste perde calibracao: falso alarme medido de
    ate 100% SEM ataque nenhum (matriz de 36 combinacoes, 16/08/2026).

    Aqui, em vez de assumir variancia unitaria, ela e calculada explicitamente
    a partir de `H`/`W` -- que sao conhecidos sem nenhum ataque:

        c_i = Var(CME_N_i | H0) = (1 - K_ii)(1 + UI_i^2)

    e a soma e aproximada por `J ~ g * chi2(h)` (Satterthwaite, casamento de
    dois momentos):

        h = (sum c_i)^2 / sum c_i^2      (graus de liberdade efetivos)
        g = sum c_i^2 / sum c_i          (fator de escala)

    Retorna `(detectado, J_cme, limiar, h_efetivo)`.

    E aproximacao de dois momentos, nao exata -- por isso continua valendo a
    regra de rodar `detect_chi2` (residuo classico) em paralelo, que nao sofre
    desta inflacao. Ver `docs/governanca/regra_sigma_min.md` secao 6b.
    """

    cme = np.asarray(CME_N, dtype=float)
    k = np.asarray(K_diag, dtype=float)
    ui = np.asarray(UI, dtype=float)

    c = (1.0 - k) * (1.0 + ui**2)
    c = c[np.isfinite(c) & (c > 0)]
    J_cme = float(np.sum(cme**2))
    if c.size == 0:
        return bool(J_cme > chi2_limit(alpha, len(cme))), J_cme, chi2_limit(alpha, len(cme)), float(len(cme))

    s1 = float(np.sum(c))
    s2 = float(np.sum(c**2))
    h = s1**2 / s2
    g = s2 / s1
    threshold = g * chi2_limit(alpha, h)
    return bool(J_cme > threshold), J_cme, float(threshold), float(h)


def identify_lnr(r_N: np.ndarray) -> tuple[int, float]:
    """Largest Normalized Residual: indice e ``|r_N|`` do maior resíduo."""

    r_N = np.asarray(r_N, dtype=float)
    idx = int(np.argmax(np.abs(r_N)))
    return idx, float(abs(r_N[idx]))


def identify_cme(CME_N: np.ndarray) -> tuple[int, float]:
    """Indice e ``|CME_N|`` do maior CME normalizado (generalized LNR test)."""

    CME_N = np.asarray(CME_N, dtype=float)
    idx = int(np.argmax(np.abs(CME_N)))
    return idx, float(abs(CME_N[idx]))


def remove_measurement(
    z: np.ndarray,
    H: np.ndarray,
    W: np.ndarray,
    idx: int,
    c: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None, np.ndarray]:
    """Remove a medicao ``idx``; retorna ``(z, H, W, c, mask)`` reduzidos."""

    z = np.asarray(z, dtype=float)
    H = np.asarray(H, dtype=float)
    mask = np.ones(len(z), dtype=bool)
    mask[idx] = False
    z2 = z[mask]
    H2 = H[mask]
    W2 = np.asarray(W)[np.ix_(mask, mask)]
    c2 = np.asarray(c, dtype=float)[mask] if c is not None else None
    return z2, H2, W2, c2, mask


def correct_measurement(
    z: np.ndarray, idx: int, CNE: np.ndarray, sigma: np.ndarray
) -> np.ndarray:
    """Aproxima ``z_true`` na medicao ``idx`` em vez de remove-la.

    Correcao via CNE (Bretas & Bretas 2018, eq. 20 + Conclusion; reuniao
    Arturo 2026-07-05): a correcao acontece no subespaco do residuo
    (dim ``m-n``) -- nao ha como corrigir diretamente no espaco de medidas
    -- e o CNE e a projecao do erro nesse subespaco, uma representacao do
    erro melhor que o proprio residuo. NAO usar o CME nem o CME normalizado
    aqui (sao do espaco de medidas; a versao anterior desta funcao usava o
    CME e produzia J corrigido *maior* que o J removido). O CNE ja carrega
    o sinal de ``r_N`` e estima o erro em multiplos de ``sigma``:
    ``z_true,i ~= z_i - CNE_i * sigma_i``.
    Retorna uma copia de ``z`` com a medicao ``idx`` corrigida (mesma
    dimensao -- ao contrario de ``remove_measurement``, nenhuma medicao e
    descartada).
    """

    z = np.asarray(z, dtype=float).copy()
    CNE = np.asarray(CNE, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    z[idx] = z[idx] - CNE[idx] * sigma[idx]
    return z


def extended_gauss_weights(W: np.ndarray, UI: np.ndarray) -> np.ndarray:
    """Pesos da funcao objetivo estendida de Gauss (Bretas & Bretas 2018, eq. 18).

    ``J_ext(theta) = sum_i (1 + 1/II_i^2) * r_i^2``, com ``II_i`` o
    Innovation Index. Como ``UI_i = K_ii/(1-K_ii) = 1/II_i^2`` (ja calculado
    por ``undetectability_index``), o multiplicador por medicao e
    ``(1 + UI_i)`` e o novo peso diagonal e ``W_ext = diag(1+UI) @ W``.
    Minimizar com ``W_ext`` em vez de ``W`` minimiza a norma do CME (o erro
    completo), nao so a norma do residuo.
    """

    W = np.asarray(W, dtype=float)
    UI = np.asarray(UI, dtype=float)
    return np.diag(1.0 + UI) @ W


@dataclass
class BadDataPipelineResult:
    """Resultado de uma execucao do ciclo deteccao->identificacao->correcao."""

    theta_hat: np.ndarray
    J_final: float
    threshold_final: float
    detected_final: bool
    n_iterations: int
    n_measurements_final: int
    flagged_indices: list[int] = field(default_factory=list)
    flagged_scores: list[float] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)


def run_bad_data_pipeline(
    z: np.ndarray,
    H: np.ndarray,
    W: np.ndarray,
    c: np.ndarray | None,
    sigma: np.ndarray,
    solve_fn: Callable[..., dict[str, Any]],
    *,
    detection: str = "residual",
    identification: str = "lnr",
    correction: str = "remove",
    alpha: float = 0.05,
    max_iter: int = 10,
) -> BadDataPipelineResult:
    """Roda deteccao -> identificacao -> correcao/remocao iterativamente.

    Cada etapa e escolhida independentemente (8 combinacoes possiveis):

    - ``detection``: ``"residual"`` (chi2 sobre ``J=r^T W r``, dof=``m-n``)
      ou ``"cme"`` (chi2 sobre ``sum(CME_N^2)``, dof=``m`` --
      ``detect_chi2_cme``).
    - ``identification``: ``"lnr"`` (maior residuo normalizado) ou ``"cme"``
      (maior CME normalizado).
    - ``correction``: ``"remove"`` (descarta a medicao flagrada,
      ``remove_measurement``) ou ``"ztrue"`` (aproxima ``z_true`` via CNE,
      ``correct_measurement``, mantendo o numero de medicoes).

    Reproduz fielmente o efeito notado por Luis na reuniao de 2026-06-29: se
    a deteccao por residuo nao disparar, a identificacao (LNR ou CME) nunca
    e alcancada -- o loop sai no primeiro ``not detected``.

    ``solve_fn`` deve ter a assinatura de ``solve_dc_pure`` (ou equivalente
    AC): ``solve_fn(z, H, W, c) -> dict`` com chaves ``"theta_hat"``,
    ``"residual"`` e ``"J"``.
    """

    if detection not in ("residual", "cme"):
        raise ValueError(f"detection invalido: {detection!r}")
    if identification not in ("lnr", "cme"):
        raise ValueError(f"identification invalido: {identification!r}")
    if correction not in ("remove", "ztrue"):
        raise ValueError(f"correction invalido: {correction!r}")

    z_cur = np.asarray(z, dtype=float).copy()
    H_cur = np.asarray(H, dtype=float).copy()
    W_cur = np.asarray(W, dtype=float).copy()
    c_cur = np.asarray(c, dtype=float).copy() if c is not None else None
    sigma_cur = np.asarray(sigma, dtype=float).copy()

    flagged_indices: list[int] = []
    flagged_scores: list[float] = []
    actions: list[str] = []
    history: list[dict[str, Any]] = []

    res: dict[str, Any] = {}
    detected = True
    J = float("nan")
    threshold = float("nan")

    for iteration in range(max_iter):
        res = solve_fn(z_cur, H_cur, W_cur, c_cur)
        r = np.asarray(res["residual"], dtype=float)
        m_cur, n_cur = H_cur.shape
        diag = compute_geometric_diagnostics(H_cur, W_cur, r, sigma_cur)

        if detection == "residual":
            J = float(res["J"])
            detected, threshold = detect_chi2(J, dof=m_cur - n_cur, alpha=alpha)
        elif detection == "cme_satterthwaite":
            detected, J, threshold, _h = detect_chi2_cme_satterthwaite(
                diag.CME_N, diag.K_diag, diag.UI, alpha=alpha)
        else:
            detected, J, threshold = detect_chi2_cme(diag.CME_N, m_cur, alpha=alpha)

        record: dict[str, Any] = {
            "iter": iteration,
            "J": J,
            "threshold": threshold,
            "detected": detected,
            "m": m_cur,
        }

        if not detected:
            history.append(record)
            break

        if identification == "lnr":
            idx, score = identify_lnr(diag.r_N)
        else:
            idx, score = identify_cme(diag.CME_N)

        record["flagged_idx"] = idx
        record["flagged_score"] = score
        history.append(record)
        flagged_indices.append(idx)
        flagged_scores.append(score)

        if correction == "remove":
            z_cur, H_cur, W_cur, c_cur, submask = remove_measurement(
                z_cur, H_cur, W_cur, idx, c_cur
            )
            sigma_cur = sigma_cur[submask]
            actions.append("removed")
        else:
            z_cur = correct_measurement(z_cur, idx, diag.CNE, sigma_cur)
            actions.append("corrected")
    else:
        iteration = max_iter - 1

    return BadDataPipelineResult(
        theta_hat=res["theta_hat"],
        J_final=J,
        threshold_final=threshold,
        detected_final=detected,
        n_iterations=len(history),
        n_measurements_final=len(z_cur),
        flagged_indices=flagged_indices,
        flagged_scores=flagged_scores,
        actions=actions,
        history=history,
    )
