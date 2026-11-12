"""Bancada de IDENTIFICACAO: os metodos da literatura e o nosso nos mesmos casos.

So identificacao: todo caso tem um erro (medida, parametro ou topologia), e a
pergunta e "qual elemento e de que tipo". Nenhum metodo e barrado por um teste
de deteccao antes; limiares que fazem parte da REGRA DE CLASSIFICACAO de um
metodo (o beta = 3 da lista de Bretas 2017, o mu^N > 3 dos suspeitos de
Kabiri) ficam, porque sem eles o metodo nao e o publicado. Cada metodo recebe
o mesmo `Contexto` (uma estimacao WLS AC convergida no modelo do operador) e
devolve um `Veredito`. Nada de verdade de campo entra na decisao.

Metodos, cada um conferido no PDF (fichas em
`temas/revisao_bibliografica/literatura/`):

- ``lnr``: maior |r^N| (classico; Abur & Gomez-Exposito 2004).
- ``cme_artigo``: maior |CME^N|, CME_i = r_i sqrt(1 + 1/II_i^2), II_i =
  sqrt(1-K_ii)/sqrt(K_ii), CME^N = CME/sigma (Bretas 2013 eqs. 9-12;
  Bretas & Bretas 2018 eqs. 16-19; Bretas 2017 eqs. 11-15). Com R diagonal e
  identico ao LNR (o 2013 diz isso).
- ``cme_codigo``: o mesmo com o fator que estava no codigo, r sqrt(1+UI^2)
  (sem fundamento publicado; mantido so para comparar).
- ``cne``: maior |CNE|, CNE_i = r^N_i sqrt(1 + 1/II_i^2) (Bretas 2017 eq. 14).
  VARIANTE: os artigos usam o CNE para corrigir, nao para identificar.
- ``bretas2017_artigo`` / ``bretas2017_codigo``: passos 3 a 6 do algoritmo de
  Bretas et al. 2017 (EPSR 149, p. 213), texto literal, alimentados por cada
  CME^N (beta = 3, "very high" = 10).
- ``nlm``: Zhu & Abur 2006 (eqs. 15-16, 22, 28; passo 2 p. 588): multiplicador
  de Lagrange normalizado por parametro escalar r, x, b_sh de cada linha
  contra o maior r^N; o maior dos dois e o culpado. Nao classifica topologia.
- ``kabiri``: Kabiri & Amjady 2018 (IJEPES 97:309, sec. 3.3), tres estagios:
  mu^N de status por ramo (coluna do ramo inteiro), suspeitos com mu^N > 3,
  G, B, Bcap re-estimados junto com o estado, eq. 41/42 com
  epsilon_th = 0,2; senao gamma^N por G, B, Bcap contra r^N.
- ``glrt_antigo`` / ``glrt_t_hat``: `classify_by_glrt` sem e com `delta`.

Aproximacoes declaradas: a coluna de status de Kabiri e a de escala uniforme do
ramo (primeira ordem do modelo de disjuntor; o NLM e invariante a escala);
erro de parametro injetado como mudanca fracionaria uniforme de g, b, b_sh.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .ac_bad_data import inject_parameter_error_unbalanced
from .ac_measurements import ACMeasurement, build_ac_ybus_model_from_pandapower
from .bad_data import hat_matrix
from .signature_sweep import branch_delta, classify_by_glrt, fit_parameter_change, parameter_sensitivity_library

BETA = 3.0  # Bretas 2017 caracteristica (1): "beta e igual a tres desvios padrao"
MUITO_ALTO = 10.0  # Bretas 2017 passo 4: "very high CME^N values (beyond 10 standard deviations)"
EPS_TH = 0.2  # Kabiri & Amjady 2018 sec. 3.3, eqs. 41-42


@dataclass
class Bibliotecas:
    """Tudo o que depende so do MODELO do operador (calcular uma vez por modelo)."""

    gbs: dict[int, np.ndarray]  # colunas por g, b, b_sh fracionarios (ou fechamento, m x 1)
    rx: dict[int, np.ndarray]  # colunas por r, x, b_sh fracionarios (Zhu & Abur)
    delta: dict[int, float]  # PTDF_ll das linhas em servico


def biblioteca_rx(net_base: Any, meas: list[ACMeasurement], *, eps: float = 0.05,
                  seed_plan: int = 2026, load_jitter: float = 0.05) -> dict[int, np.ndarray]:
    """Colunas dh/dp para p = r, x, b_sh de cada linha EM SERVICO, mesmo ponto de
    planejamento de `parameter_sensitivity_library` (carga com jitter).

    E a parametrizacao de Zhu & Abur 2006 (eq. 3: p = p_t + p_e, parametros de
    linha r, x, b_sh). Por unidade de mudanca fracionaria: o NLM e invariante a
    escala da coluna, entao isso nao altera lambda^N.
    """

    import pandapower as pp

    rng = np.random.default_rng(seed_plan)
    net_plan = deepcopy(net_base)
    f = 1.0 + rng.uniform(-load_jitter, load_jitter, size=len(net_plan.load))
    net_plan.load["p_mw"] = net_plan.load["p_mw"].to_numpy() * f
    net_plan.load["q_mvar"] = net_plan.load["q_mvar"].to_numpy() * f
    pp.runpp(net_plan, calculate_voltage_angles=True, init="flat", numba=False)
    mdl = build_ac_ybus_model_from_pandapower(net_plan, list(meas))
    x_ref = mdl.state_from_results(net_plan.res_bus["vm_pu"], net_plan.res_bus["va_degree"])
    h_ref = mdl.h(x_ref)
    lib: dict[int, np.ndarray] = {}
    for l in [int(i) for i in net_base.line.index]:
        if not bool(net_plan.line.at[l, "in_service"]):
            continue
        cols = []
        for col in ("r_ohm_per_km", "x_ohm_per_km", "c_nf_per_km"):
            net_p = deepcopy(net_plan)
            net_p.line.at[l, col] *= 1.0 + eps
            try:
                pp.runpp(net_p, calculate_voltage_angles=True, init="flat", numba=False)
                cols.append((build_ac_ybus_model_from_pandapower(net_p, list(meas)).h(x_ref) - h_ref) / eps)
            except Exception:
                cols.append(np.zeros(len(meas)))
        lib[l] = np.column_stack(cols)
    return lib


def montar_bibliotecas(net_model: Any, meas: list[ACMeasurement]) -> Bibliotecas:
    return Bibliotecas(gbs=parameter_sensitivity_library(net_model, meas),
                       rx=biblioteca_rx(net_model, meas), delta=branch_delta(net_model))


@dataclass
class Contexto:
    """Uma estimacao WLS AC convergida no modelo do operador."""

    net_model: Any
    meas: list[ACMeasurement]
    H: np.ndarray
    W: np.ndarray
    r: np.ndarray
    sigma: np.ndarray
    K: np.ndarray
    libs: Bibliotecas
    J: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def K_diag(self) -> np.ndarray:
        return np.clip(np.diag(self.K), 1e-12, 1.0 - 1e-12)

    @property
    def UI(self) -> np.ndarray:
        """UI_i = K_ii/(1-K_ii) = 1/II_i^2 (II de Bretas 2013 eq. 9 / 2017 eq. 11)."""
        k = self.K_diag
        return k / (1.0 - k)

    @property
    def r_N(self) -> np.ndarray:
        """r_i / sqrt(Omega_ii), Omega = (I-K) R (Bretas & Bretas 2018 eq. 15)."""
        return self.r / (self.sigma * np.sqrt(1.0 - self.K_diag))

    @property
    def cme_n_artigo(self) -> np.ndarray:
        """CME^N_i = (r_i/sigma_i) sqrt(1 + 1/II_i^2) (Bretas 2017 eq. 15)."""
        return self.r / self.sigma * np.sqrt(1.0 + self.UI)

    @property
    def cme_n_codigo(self) -> np.ndarray:
        """Fator que estava em `bad_data.composed_measurement_error`: sqrt(1 + UI^2)."""
        return self.r / self.sigma * np.sqrt(1.0 + self.UI**2)

    @property
    def cne(self) -> np.ndarray:
        """CNE_i = r^N_i sqrt(1 + 1/II_i^2) (Bretas 2017 eq. 14)."""
        return self.r_N * np.sqrt(1.0 + self.UI)


@dataclass
class Veredito:
    tipo: str  # "measurement" | "parameter" | "topology" | "inconclusive"
    linha: int | None = None
    medida: int | None = None
    t_est: float | None = None


def estimar(net_model: Any, meas: list[ACMeasurement], x0: np.ndarray | None = None):
    """`(modelo, x, H, W, r, J)` de uma estimacao WLS AC no `net_model`."""

    mdl = build_ac_ybus_model_from_pandapower(net_model, meas)
    res = mdl.solve(x0=mdl.flat_start() if x0 is None else x0, max_iter=30, tol=1e-8)
    H = np.asarray(mdl.jacobian(res.x), dtype=float)
    W = np.diag(1.0 / np.asarray(mdl.sigma, dtype=float) ** 2)
    r = mdl.z - mdl.h(res.x)
    return mdl, res.x, H, W, r, float(r @ W @ r)


def montar_contexto(net_model: Any, meas: list[ACMeasurement], libs: Bibliotecas) -> Contexto:
    mdl, _, H, W, r, J = estimar(net_model, meas)
    return Contexto(net_model=net_model, meas=meas, H=H, W=W, r=r,
                    sigma=np.asarray(mdl.sigma, dtype=float), K=hat_matrix(H, W), libs=libs, J=J)


def nlm(ctx: Contexto, s: np.ndarray) -> float:
    """|lambda^N| de uma coluna: |s' W r| / sqrt(s' W (I-K) s).

    Zhu & Abur 2006 sem injecoes nulas: lambda = -H_p' W r (eqs. 15-16),
    Lambda = H_p' W Omega W H_p = H_p' W (I-K) H_p (eq. 22, com Omega = (I-K)R),
    lambda^N = lambda/sqrt(Lambda) (eq. 28). Kabiri & Amjady usam a mesma forma
    (eqs. 34, 37-40).
    """

    den = float(s @ ctx.W @ ((np.eye(len(ctx.r)) - ctx.K) @ s))
    if den <= 1e-14:
        return 0.0
    return abs(float(s @ (ctx.W @ ctx.r))) / np.sqrt(den)


# ---------------------------------------------------------------------------
# Identificacao so de medida
# ---------------------------------------------------------------------------


def _so_medida(score: np.ndarray) -> Veredito:
    return Veredito("measurement", medida=int(np.argmax(np.abs(score))))


def metodo_lnr(ctx: Contexto) -> Veredito:
    return _so_medida(ctx.r_N)


def metodo_cme_artigo(ctx: Contexto) -> Veredito:
    return _so_medida(ctx.cme_n_artigo)


def metodo_cme_codigo(ctx: Contexto) -> Veredito:
    return _so_medida(ctx.cme_n_codigo)


def metodo_cne(ctx: Contexto) -> Veredito:
    return _so_medida(ctx.cne)


# ---------------------------------------------------------------------------
# Bretas et al. 2017, p. 213, passos 3 a 6
# ---------------------------------------------------------------------------


def _bretas2017(ctx: Contexto, cme_n: np.ndarray) -> Veredito:
    """Texto literal (EPSR 149, p. 213):

    (3) lista decrescente das medidas por CME^N;
    (4) injecoes i e j com CME^N muito alto (> 10) e NENHUM fluxo i-j / j-i
        (P ou Q) na lista => topologia no ramo i-j;
    (5) fluxos i-j e j-i E injecoes i e j com CME^N acima do limiar na lista
        => parametro no ramo i-j (corrige pela medida de maior CME^N);
    (6) medida isolada acima do limiar => medida.

    "Na lista" = |CME^N| > beta = 3 (caracteristica (1) da mesma pagina). Se
    nada passa do limiar, o passo 6 fica com a de maior CME^N (so
    identificacao: o erro existe por construcao do caso).
    """

    a = np.abs(cme_n)
    inj: dict[int, float] = {}
    flu: dict[tuple[int, str], float] = {}
    for i, m in enumerate(ctx.meas):
        if m.kind in ("p_inj", "q_inj"):
            inj[int(m.element)] = max(inj.get(int(m.element), 0.0), a[i])
        elif m.kind in ("p_branch", "q_branch", "p_line", "q_line") and (m.branch_kind in (None, "line")):
            flu[(int(m.element), str(m.side))] = max(flu.get((int(m.element), str(m.side)), 0.0), a[i])
    net = ctx.net_model

    def fluxos_na_lista(l: int) -> tuple[bool, bool]:
        return flu.get((l, "from"), 0.0) > BETA, flu.get((l, "to"), 0.0) > BETA

    # passo 4
    cand4 = []
    for l in [int(x) for x in net.line.index]:
        i, j = int(net.line.at[l, "from_bus"]), int(net.line.at[l, "to_bus"])
        if inj.get(i, 0.0) > MUITO_ALTO and inj.get(j, 0.0) > MUITO_ALTO and not any(fluxos_na_lista(l)):
            cand4.append((min(inj[i], inj[j]), l))
    if cand4:
        return Veredito("topology", linha=max(cand4)[1])
    # passo 5
    cand5 = []
    for l in [int(x) for x in net.line.index]:
        i, j = int(net.line.at[l, "from_bus"]), int(net.line.at[l, "to_bus"])
        f_ij, f_ji = fluxos_na_lista(l)
        if f_ij and f_ji and inj.get(i, 0.0) > BETA and inj.get(j, 0.0) > BETA:
            cand5.append((max(flu.get((l, "from"), 0.0), flu.get((l, "to"), 0.0), inj[i], inj[j]), l))
    if cand5:
        return Veredito("parameter", linha=max(cand5)[1])
    # passo 6
    return Veredito("measurement", medida=int(np.argmax(a)))


def metodo_bretas2017_artigo(ctx: Contexto) -> Veredito:
    return _bretas2017(ctx, ctx.cme_n_artigo)


def metodo_bretas2017_codigo(ctx: Contexto) -> Veredito:
    return _bretas2017(ctx, ctx.cme_n_codigo)


# ---------------------------------------------------------------------------
# Zhu & Abur 2006
# ---------------------------------------------------------------------------


def metodo_nlm(ctx: Contexto) -> Veredito:
    """Passo 2 (p. 588): o maior entre max r^N e max lambda^N (r, x, b_sh por linha)."""

    melhor_l, melhor = None, 0.0
    for l, S in ctx.libs.rx.items():
        for j in range(S.shape[1]):
            v = nlm(ctx, S[:, j])
            if v > melhor:
                melhor_l, melhor = l, v
    i = int(np.argmax(np.abs(ctx.r_N)))
    if melhor_l is not None and melhor > abs(ctx.r_N[i]):
        return Veredito("parameter", linha=melhor_l)
    return Veredito("measurement", medida=i)


# ---------------------------------------------------------------------------
# Kabiri & Amjady 2018
# ---------------------------------------------------------------------------


def _y_linha(net: Any, l: int) -> np.ndarray:
    """(G, B, Bcap) em siemens do ramo inteiro."""

    L = float(net.line.at[l, "length_km"])
    r = float(net.line.at[l, "r_ohm_per_km"]) * L
    x = float(net.line.at[l, "x_ohm_per_km"]) * L
    c = float(net.line.at[l, "c_nf_per_km"]) * L * 1e-9
    f = float(getattr(net, "f_hz", 50.0) or 50.0)
    d = r * r + x * x
    return np.array([r / d, -x / d, 2 * np.pi * f * c])


def _aumentado(ctx: Contexto, S: np.ndarray, net_de: Callable[[np.ndarray], Any], p0: np.ndarray,
               lo: float, hi: float, max_iter: int = 12, tol: float = 1e-4) -> np.ndarray:
    """Parametros re-estimados junto com o estado (estado aumentado por iteracao).

    `h` e afim nos parametros com o estado fixo (P1 da fundamentacao), entao a
    coluna absoluta e constante e o passo de Gauss-Newton nos parametros e
    `p <- p + coef`, com `coef` o ajuste das colunas `S` ao residuo do estado
    re-estimado com `p` atual (Zhu & Abur 2006 eq. 29; Kabiri estagio 2).

    Se a estimacao divergir (parametro mal condicionado, como G, B, Bcap juntos
    em rede radial, P3), o fluxo auxiliar do modelo deixa de convergir: para no
    ultimo valor valido, que e o que o metodo entrega na pratica.
    """

    p = p0.astype(float).copy()
    p_valido = p.copy()
    H, W, r, K, x = ctx.H, ctx.W, ctx.r, ctx.K, None
    for it in range(max_iter):
        if it > 0:
            try:
                _, x, H, W, r, _ = estimar(net_de(p), ctx.meas, x0=x)
            except Exception:
                return p_valido
            K = hat_matrix(H, W)
            p_valido = p.copy()
        coef, _, _ = fit_parameter_change(S, H, W, r, K=K)
        p = np.clip(p + coef, lo, hi)
        if np.max(np.abs(coef)) < tol:
            break
    return p


def metodo_kabiri(ctx: Contexto) -> Veredito:
    net = ctx.net_model
    gbs = ctx.libs.gbs
    # estagio 1-2: mu^N de status por ramo; suspeitos mu^N > 3, do maior para o menor
    mu = {}
    for l, S in gbs.items():
        mu[l] = nlm(ctx, S[:, 0] if S.shape[1] == 1 else S @ np.ones(S.shape[1]))
    for l in sorted((l for l in mu if mu[l] > 3.0), key=mu.get, reverse=True)[:3]:
        if gbs[l].shape[1] == 3:  # em servico: G, B, Bcap no estado; eq. 41
            y_s = _y_linha(net, l)
            t = _aumentado(ctx, gbs[l],
                           lambda p, l=l: inject_parameter_error_unbalanced(
                               net, l, dg_pct=p[0], db_pct=p[1], dbsh_pct=p[2])[0],
                           np.zeros(3), -0.99, 5.0)
            ys, ye = np.linalg.norm(y_s), np.linalg.norm(y_s * (1.0 + t))
            if (ys - ye) / ys >= 1.0 - EPS_TH:
                return Veredito("topology", linha=l, t_est=float(ye / ys - 1.0))
        else:  # fora de servico: fator k do ramo fechado; eq. 42
            net_on = deepcopy(net)
            net_on.line.at[l, "in_service"] = True
            k = _aumentado(ctx, gbs[l],
                           lambda p, l=l, n=net_on: inject_parameter_error_unbalanced(
                               n, l, dg_pct=p[0] - 1, db_pct=p[0] - 1, dbsh_pct=p[0] - 1)[0],
                           np.zeros(1), 0.01, 3.0)
            if float(k[0]) >= 1.0 - EPS_TH:
                return Veredito("topology", linha=l, t_est=float(k[0]))
    # estagio 3: gamma^N por G, B, Bcap contra r^N; o maior e a fonte
    melhor_l, melhor = None, 0.0
    for l, S in gbs.items():
        if S.shape[1] != 3:
            continue
        for j in range(3):
            v = nlm(ctx, S[:, j])
            if v > melhor:
                melhor_l, melhor = l, v
    i = int(np.argmax(np.abs(ctx.r_N)))
    if melhor_l is not None and melhor > abs(ctx.r_N[i]):
        y_s = _y_linha(net, melhor_l)
        t = _aumentado(ctx, gbs[melhor_l],
                       lambda p: inject_parameter_error_unbalanced(
                           net, melhor_l, dg_pct=p[0], db_pct=p[1], dbsh_pct=p[2])[0],
                       np.zeros(3), -0.99, 5.0)
        return Veredito("parameter", linha=melhor_l,
                        t_est=float(np.linalg.norm(y_s * (1.0 + t)) / np.linalg.norm(y_s) - 1.0))
    return Veredito("measurement", medida=i)


# ---------------------------------------------------------------------------
# Nosso
# ---------------------------------------------------------------------------


def _glrt(ctx: Contexto, delta: dict[int, float] | None) -> Veredito:
    tipo, linha, diag = classify_by_glrt(ctx.libs.gbs, ctx.H, ctx.W, ctx.r, ctx.r_N, delta=delta)
    t = diag.get("t_hat")
    return Veredito(tipo, linha=linha, medida=int(diag["measurement_idx"]),
                    t_est=float(t) if t is not None and np.isfinite(t) else None)


def metodo_glrt_antigo(ctx: Contexto) -> Veredito:
    return _glrt(ctx, None)


def metodo_glrt_t_hat(ctx: Contexto) -> Veredito:
    return _glrt(ctx, ctx.libs.delta)


METODOS: dict[str, Callable[[Contexto], Veredito]] = {
    "lnr": metodo_lnr,
    "cme_artigo": metodo_cme_artigo,
    "cme_codigo": metodo_cme_codigo,
    "cne": metodo_cne,
    "bretas2017_artigo": metodo_bretas2017_artigo,
    "bretas2017_codigo": metodo_bretas2017_codigo,
    "nlm": metodo_nlm,
    "kabiri": metodo_kabiri,
    "glrt_antigo": metodo_glrt_antigo,
    "glrt_t_hat": metodo_glrt_t_hat,
}


# Nome de cada metodo em figura, deck e tabela (um lugar so, em ingles: o deck e em ingles).
NOMES = {
    "lnr": "LNR",
    "cme_artigo": "CME (Bretas 2013)",
    "cme_codigo": "CME (old code)",
    "cne": "CNE (Bretas 2013)",
    "bretas2017_artigo": "Bretas 2017",
    "bretas2017_codigo": "Bretas 2017 (old CME)",
    "nlm": "Zhu & Abur 2006",
    "kabiri": "Kabiri & Amjady 2018",
    "glrt_antigo": "GLRT (old)",
    "glrt_t_hat": "GLRT + t̂ (ours)",
}


def avaliar(v: Veredito, tipo_real: str, linha_real: int | None, medida_real: int | None) -> str:
    """'certo' (tipo e elemento), 'elemento_errado', 'tipo_errado' ou 'inconclusivo'."""

    if v.tipo == "inconclusive":
        return "inconclusivo"
    if v.tipo != tipo_real:
        return "tipo_errado"
    if tipo_real == "measurement":
        return "certo" if v.medida == medida_real else "elemento_errado"
    return "certo" if v.linha == linha_real else "elemento_errado"
