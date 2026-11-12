# -*- coding: utf-8 -*-
"""DSSE multiarea estatica com agentes de verdade (O5).

Diferente de `tipos_agentes.py` (mock da aba Agents do app: o estimador
inventa V e o bad data so repete o ataque injetado), aqui cada agente roda o
estimador AC real do pacote sobre a sua ilha.

Algoritmo: two-step multi-area (Muscas, Pau et al. 2014, Zotero `DU42IWJX`)
com o passo 2 feito como troca de mensagens na arvore de ilhas, **sob
demanda** (Arturo, 22/08/2026). Tres fases:

1. Local, em paralelo, sem mensagem: cada ilha estendida (barras proprias +
   a barra do outro lado de cada corte) roda observabilidade, WLS e bad data.
2. Subida (folhas -> raiz): a filha manda a mae a sua estimativa da barra
   ancora (V e sigma, vinda das medidas DELA). A mae funde como pseudo-medida
   e reestima. E aqui que a mae passa a usar a informacao das filhas -- sem
   esta fase o multiarea perdia para o centralizado. A diferenca entre as
   duas estimativas da ancora e o teste de consistencia de fronteira
   (pista horizontal do bad data).
3. Descida (raiz -> folhas): a mae manda V, theta e sigma da ancora, com a
   contribuicao da propria filha retirada (divisao gaussiana, como em
   propagacao de crenca), para nao contar a mesma informacao duas vezes.

Agentes sao funcoes (decisao de 09/10/2026: agentes de servico = funcoes,
agente de IA = orquestrador). O orquestrador aqui e uma regra fixa.

Ver `temas/framework_multiagente/plano_simulacao_estatica.md`.
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field
from typing import Callable, Literal

import networkx as nx
import numpy as np
import pandapower as pp
import pandas as pd
import scipy.sparse as sp
from scipy.sparse.linalg import splu
from scipy.stats import chi2

from ..estimacao_estado.ac_measurements import (
    ACMeasurement,
    ACYbusMeasurementModel,
    build_ac_ybus_model_from_pandapower,
    synthetic_full_measurements_from_results,
)
from ..estimacao_estado.bad_data import normalized_residual, state_covariance
from ..estimacao_estado.gauss_newton_wls import WLSResult
from .base import AgentMessage

__all__ = [
    "Ilha",
    "ilhas_por_corte",
    "rede_multialimentador",
    "rede_verdade",
    "montar_medidas",
    "pseudo_medidas_carga",
    "injetar_erro",
    "rodar_multiarea",
    "rodar_centralizado",
    "preparar_subredes",
    "ilha_unica",
    "bytes_medidas_ao_centro",
    "comparar_com_verdade",
    "ResultadoMultiarea",
]

Politica = Literal["nunca", "sob_demanda", "sempre"]
Estimador = Callable[[ACYbusMeasurementModel, "np.ndarray | None"], WLSResult]  # (modelo, x0)


# --------------------------------------------------------------------------
# Particao e redes
# --------------------------------------------------------------------------


@dataclass
class Ilha:
    """Escopo espacial de um time de agentes (narrativa §5.2: ilha = onde)."""

    nome: str
    barras: list[int]                 # barras proprias (dono do estado publicado)
    ancora: int | None = None         # barra da mae compartilhada; None = ilha da subestacao
    mae: str | None = None


def ilhas_por_corte(net, linhas_corte: list[int], nomes: list[str] | None = None) -> list[Ilha]:
    """Corta as linhas dadas e devolve as ilhas em ordem BFS (mae antes de filha).

    A ancora de cada filha e a ponta da linha de corte do lado da mae.
    """

    G = nx.Graph()
    G.add_nodes_from(int(b) for b in net.bus.index)
    em_servico = net.line[net.line.in_service.astype(bool)]
    corte = set(linhas_corte)
    for lid, row in em_servico.iterrows():
        if lid not in corte:
            G.add_edge(int(row.from_bus), int(row.to_bus))
    # transformadores nunca sao cortados: ficam dentro da ilha (ex.: UKGDS,
    # slack em 33 kV e alimentadores em 11 kV)
    for _, row in net.trafo[net.trafo.in_service.astype(bool)].iterrows():
        G.add_edge(int(row.hv_bus), int(row.lv_bus))
    comps = list(nx.connected_components(G))
    raiz = int(net.ext_grid.bus.iloc[0])
    comp_de = {b: i for i, c in enumerate(comps) for b in c}
    pontas = [(int(em_servico.at[l, "from_bus"]), int(em_servico.at[l, "to_bus"])) for l in linhas_corte]

    ordem, mae, ancora = [comp_de[raiz]], {comp_de[raiz]: None}, {comp_de[raiz]: None}
    for c in ordem:
        for a, b in pontas:
            for lado_mae, lado_filha in ((a, b), (b, a)):
                if comp_de[lado_mae] == c and comp_de[lado_filha] not in mae:
                    f = comp_de[lado_filha]
                    mae[f], ancora[f] = c, lado_mae
                    ordem.append(f)
    # A troca mae <-> filha so coordena as arestas da arvore. Corte entre duas
    # ilhas que nao sao mae e filha (ex.: chave fechada entre duas filhas) vira
    # ciclo no grafo das ilhas e fica sem coordenacao: no IEEE 33 com 18-33
    # fechada o erro de angulo dobrou. Malha DENTRO de uma ilha nao e problema.
    for a, b in pontas:
        ca, cb = comp_de[a], comp_de[b]
        if ca != cb and mae.get(ca) != cb and mae.get(cb) != ca:
            import warnings
            warnings.warn(f"cut line {a + 1}-{b + 1} links two islands that are not parent and child: the island graph "
                          f"has a cycle and this boundary is not coordinated. Keep this line inside one island.", stacklevel=2)
    if nomes is None:
        nomes = [chr(ord("A") + i) for i in range(len(ordem))] if len(ordem) <= 26 else [f"I{i}" for i in range(len(ordem))]
    nome_de = {c: nomes[i] for i, c in enumerate(ordem)}
    return [
        Ilha(nome_de[c], sorted(int(b) for b in comps[c]), ancora[c],
             None if mae[c] is None else nome_de[mae[c]])
        for c in ordem
    ]


def rede_multialimentador(n_alim: int, base=None):
    """Subestacao com `n_alim` copias do IEEE 33 saindo do mesmo barramento.

    E o cenario do argumento do CSI (07/10/2026): uma subestacao, varios
    alimentadores, milhares de nos. Barra 0 = subestacao; a barra b (1..32)
    do alimentador k vira `1 + 32k + (b-1)`; a linha j (so as 32 em servico)
    vira `32k + j`. As tie-switches abertas do case33bw nao sao copiadas.
    """

    import pandapower.networks as pn

    base = base if base is not None else pn.case33bw()
    linhas = base.line[base.line.in_service.astype(bool)]
    nb = len(base.bus) - 1
    net = pp.create_empty_network(sn_mva=float(base.sn_mva))
    vn = float(base.bus.vn_kv.iloc[0])
    se = pp.create_bus(net, vn_kv=vn, name="SE")
    pp.create_ext_grid(net, se, vm_pu=1.0)
    for k in range(n_alim):
        mapa = {0: se}
        for b in base.bus.index[1:]:
            mapa[int(b)] = pp.create_bus(net, vn_kv=vn, name=f"F{k}_{b}")
        for _, l in linhas.iterrows():
            pp.create_line_from_parameters(net, mapa[int(l.from_bus)], mapa[int(l.to_bus)], l.length_km,
                                           l.r_ohm_per_km, l.x_ohm_per_km, l.c_nf_per_km, l.max_i_ka)
        for _, ld in base.load.iterrows():
            pp.create_load(net, mapa[int(ld.bus)], p_mw=ld.p_mw, q_mvar=ld.q_mvar)
    assert len(net.bus) == 1 + n_alim * nb
    pp.runpp(net)
    return net


def rede_verdade(net, rng: np.random.Generator, variacao_carga: float = 0.3):
    """Copia a rede e sorteia a carga real em +-variacao em torno da nominal.

    Sem isso a pseudo-medida (que usa a nominal) seria a propria verdade.
    """

    v = copy.deepcopy(net)
    f = rng.uniform(1 - variacao_carga, 1 + variacao_carga, len(v.load))
    v.load["p_mw"] *= f
    v.load["q_mvar"] *= f
    pp.runpp(v)
    return v


# --------------------------------------------------------------------------
# Medidas
# --------------------------------------------------------------------------


def _chave(m: ACMeasurement):
    return (m.kind, m.element, m.side or "", m.branch_kind or "")


def montar_medidas(
    net_verdade,
    rng: np.random.Generator,
    *,
    v_barras: list[int],
    fluxo_linhas: list[int],
    inj_barras: list[int] = (),
    noise_level: float = 0.01,
    sigma_min: float = 0.005,
) -> list[ACMeasurement]:
    """Medidores reais com ruido gaussiano, em ordem deterministica.

    `fluxo_linhas` mede P e Q nas duas pontas. sigma vem da calibracao
    compartilhada (`sensor_calibration`, tipo scada).
    """

    todas = synthetic_full_measurements_from_results(
        net_verdade, kind="scada", noise_level=noise_level, sigma_min=sigma_min
    )
    v_barras, fluxo_linhas, inj_barras = set(v_barras), set(fluxo_linhas), set(inj_barras)
    sel = [
        m for m in todas
        if (m.kind == "v_bus" and m.element in v_barras)
        or (m.kind in ("p_inj", "q_inj") and m.element in inj_barras)
        or (m.kind in ("p_branch", "q_branch") and m.branch_kind == "line" and m.element in fluxo_linhas)
    ]
    sel.sort(key=_chave)
    ruido = rng.standard_normal(len(sel))
    return [
        ACMeasurement(m.kind, m.element, m.value + e * m.sigma, m.sigma, m.side, m.branch_kind)
        for m, e in zip(sel, ruido)
    ]


def pseudo_medidas_carga(net, sigma_rel: float = 0.3, piso_mva: float | None = None) -> dict[int, list[ACMeasurement]]:
    """Pseudo-medida de injecao por barra a partir da carga NOMINAL de `net`.

    sigma de 30% como em Crawford & Baran 2026. Barra sem carga recebe
    injecao zero com sigma no piso (barra de passagem: e quase certeza). O
    piso padrao e 1% da carga nominal tipica da rede (nao um valor em MVA).
    Barra de subestacao (ext_grid) nunca recebe: ela injeta o alimentador
    inteiro, "injecao zero" ali estraga o estimador (RMSE 10x pior).
    """

    p = net.load.groupby("bus").p_mw.sum()
    q = net.load.groupby("bus").q_mvar.sum()
    if piso_mva is None:
        # 1% da carga nominal tipica da rede: independe da unidade e da base
        # (11/11/2026; era 1e-3 MVA fixo, que vale 1% de uma carga do IEEE 33
        # mas e grande ou pequeno conforme a escala da rede)
        s_load = np.hypot(p, q)
        s_load = s_load[s_load > 0]
        piso_mva = 0.01 * float(np.median(s_load)) if len(s_load) else 1e-3
    fontes = set(int(b) for b in net.ext_grid.bus)
    out = {}
    for b in net.bus.index:
        b = int(b)
        if b in fontes:
            continue
        pv, qv = -float(p.get(b, 0.0)), -float(q.get(b, 0.0))
        out[b] = [
            ACMeasurement("p_inj", b, pv, max(abs(pv) * sigma_rel, piso_mva)),
            ACMeasurement("q_inj", b, qv, max(abs(qv) * sigma_rel, piso_mva)),
        ]
    return out


def injetar_erro(med: list[ACMeasurement], i: int, k_sigma: float) -> list[ACMeasurement]:
    """Erro grosseiro de `k_sigma` desvios na medida `i` (copia da lista)."""

    m = med[i]
    out = list(med)
    out[i] = ACMeasurement(m.kind, m.element, m.value + k_sigma * m.sigma, m.sigma, m.side, m.branch_kind)
    return out


# --------------------------------------------------------------------------
# Contexto de uma ilha (o que os agentes dela enxergam)
# --------------------------------------------------------------------------


@dataclass
class _Ctx:
    ilha: Ilha
    sub: object                                   # pandapowerNet local (ilha estendida)
    medidas: list[ACMeasurement]                  # reais + pseudo de carga
    pseudo_disponivel: dict[int, list[ACMeasurement]]
    internas: set[int] = field(default_factory=set)
    fronteira: dict[str, ACMeasurement] = field(default_factory=dict)  # pseudo vindas de vizinhas
    pseudo_usadas: list[int] = field(default_factory=list)
    removidas: list[ACMeasurement] = field(default_factory=list)
    va_ancora_deg: float = 0.0
    alinhada: bool = False
    modelo: ACYbusMeasurementModel | None = None
    res: WLSResult | None = None
    eventos: list[str] = field(default_factory=list)
    tempo: dict[str, float] = field(default_factory=dict)
    bd: dict = field(default_factory=dict)
    subiu: dict | None = None                     # o que mandou a mae na subida
    fase: str = "local"
    historico: list[dict] = field(default_factory=list)  # J por iteracao de cada solve
    segmentos: list[dict] = field(default_factory=list)  # (fase, etapa, ms) na ordem em que rodaram
    traco: list[dict] = field(default_factory=list)      # verbose: o que cada agente fez (lista compartilhada)
    fronteira_barras: list[int] = field(default_factory=list)  # barras que a ilha divide com vizinhas
    verbose: bool = False
    medidas_iniciais: list = field(default_factory=list)  # medidas reais que a ilha recebeu (antes de pseudo e remocao)
    conversa: str | None = None                   # motivo de conversar com a mae


def _subrede(net_modelo, ilha: Ilha):
    """Ilha estendida: barras proprias + a barra do outro lado de cada corte.

    Assim a linha de corte (e o fluxo medido nela) entra no modelo dos dois
    lados -- sem isso a mae nao sabe quanto a barra de corte exporta e o
    angulo dela fica solto (erro de ~9 graus medido no 33 barras).
    """

    proprias = set(ilha.barras)
    ln = net_modelo.line[net_modelo.line.in_service.astype(bool)]
    vizinhas = {int(t) for f, t in zip(ln.from_bus, ln.to_bus) if f in proprias and t not in proprias}
    vizinhas |= {int(f) for f, t in zip(ln.from_bus, ln.to_bus) if t in proprias and f not in proprias}
    sub = pp.select_subnet(net_modelo, sorted(proprias | vizinhas))
    if ilha.ancora is not None:
        sub.ext_grid.drop(sub.ext_grid.index, inplace=True)
        pp.create_ext_grid(sub, ilha.ancora, vm_pu=1.0)
    pp.runpp(sub)  # so para montar Ybus/Yf/Yt; o resultado nao e usado
    return sub


def preparar_subredes(net_modelo, ilhas: list[Ilha]) -> dict:
    """Subrede de cada ilha; depende so da topologia e dos parametros.

    Montar uma vez por topologia e passar a `rodar_multiarea(subredes=...)`
    em Monte Carlo (carga e ruido mudam, o modelo do operador nao).
    """

    return {i.nome: _subrede(net_modelo, i) for i in ilhas}


def _medidas_da_ilha(net_modelo, sub, ilha: Ilha, medidas: list[ACMeasurement]):
    """Medida entra na ilha se o modelo local consegue escreve-la inteira.

    Injecao so em barra propria com todos os ramos dentro da subrede. Com a
    ilha estendida, toda barra propria e interna; a barra vizinha (do outro
    lado do corte) nunca e, porque a carga a jusante dela nao esta no modelo.
    """

    linhas_sub = set(int(i) for i in sub.line.index[sub.line.in_service.astype(bool)])
    ln = net_modelo.line[net_modelo.line.in_service.astype(bool)]
    externas = set(int(b) for l, b in zip(ln.index, ln.from_bus) if int(l) not in linhas_sub)
    externas |= set(int(b) for l, b in zip(ln.index, ln.to_bus) if int(l) not in linhas_sub)
    internas = set(ilha.barras) - externas
    proprias = set(ilha.barras)
    return [
        m for m in medidas
        if (m.kind == "v_bus" and m.element in proprias)
        or (m.kind in ("p_branch", "q_branch") and m.element in linhas_sub)
        or (m.kind in ("p_inj", "q_inj") and m.element in internas)
    ], internas


def _modelo(ctx: _Ctx) -> ACYbusMeasurementModel:
    m = build_ac_ybus_model_from_pandapower(ctx.sub, ctx.medidas + list(ctx.fronteira.values()))
    m.slack_va_rad = float(np.deg2rad(ctx.va_ancora_deg))
    return m


def _msg(log, de, para, tipo, payload, prioridade="NORMAL"):
    log.append(AgentMessage(de, para, tipo, payload, prioridade))


# --------------------------------------------------------------------------
# Agentes (funcoes de servico)
# --------------------------------------------------------------------------


def _evento(ctx: _Ctx, tipo: str, texto: str, fim: bool = False, **vars) -> None:
    """Registra um passo do agente (e imprime se `verbose`).

    `seg` aponta a etapa cronometrada em que o passo aconteceu: dentro de uma
    funcao cronometrada e a proxima a ser gravada; `fim=True` (mensagem
    enviada depois dela) e a ultima ja gravada.
    """

    ctx.traco.append({"ilha": ctx.ilha.nome, "fase": ctx.fase, "seg": len(ctx.segmentos) - (1 if fim else 0),
                      "fim": fim, "tipo": tipo, "texto": texto, "vars": vars})
    if ctx.verbose:
        print(f"[{ctx.fase:<7}] {ctx.ilha.nome:>7} | {texto}")


def _v_theta(mod: ACYbusMeasurementModel, x: np.ndarray, barras: list[int]) -> dict:
    V = mod.state_to_voltage(x)
    if not barras:  # centralizado: mostra a pior tensao
        k = int(np.argmin(np.abs(V)))
        barras = [mod.bus_order[k]]
    return {b: (float(np.abs(V[mod.bus_lookup[b]])), float(np.rad2deg(np.angle(V[mod.bus_lookup[b]])))) for b in barras}


def _observavel(ctx: _Ctx) -> bool:
    """Observabilidade numerica: G = H'H na partida plana fatora sem pivo nulo.

    Esparso (splu), para valer em rede de milhares de barras; o posto denso
    por SVD custava segundos so no centralizado.
    """

    mod = _modelo(ctx)
    H = mod.jacobian(mod.flat_start(), sparse=True)
    if H.shape[0] < H.shape[1]:
        return False
    G = (H.T @ H).tocsc()
    try:
        d = np.abs(splu(G).U.diagonal())
    except RuntimeError:
        return False
    return bool(d.min() > 1e-10 * d.max())


def _posto(ctx: _Ctx) -> int | None:
    """Posto numerico de H na partida plana, so para o relatorio (SVD densa).

    A decisao usa `_observavel` (fatoracao esparsa); o numero exato so e
    calculado em problema pequeno, onde a SVD e barata.
    """

    mod = _modelo(ctx)
    if mod.num_states > 600:
        return None
    return int(np.linalg.matrix_rank(mod.jacobian(mod.flat_start())))


def agente_observabilidade(ctx: _Ctx, log: list[AgentMessage]) -> bool:
    """Se o posto nao fecha, acrescenta pseudo-injecao nas barras internas sem medida."""

    mod = _modelo(ctx)
    m0, n, r0 = len(mod.z), mod.num_states, _posto(ctx)
    if _observavel(ctx):
        _evento(ctx, "obs", f"observability: H is {m0} x {n}, full rank", m=m0, n=n, posto=r0)
        return True
    medidas_inj = {m.element for m in ctx.medidas if m.kind == "p_inj"}
    # so barra interna: a carga nominal de uma barra de corte nao e a injecao
    # dela no modelo local (ela exporta a carga das ilhas vizinhas)
    novas = [b for b in ctx.ilha.barras
             if b in ctx.internas and b not in medidas_inj and b in ctx.pseudo_disponivel]
    for b in novas:
        ctx.medidas = ctx.medidas + ctx.pseudo_disponivel[b]
    ctx.pseudo_usadas += novas
    _msg(log, f"Obs_{ctx.ilha.nome}", f"Pseudo_{ctx.ilha.nome}", "PSEUDO_REQUEST", {"barras": novas})
    ok = _observavel(ctx)
    r1 = _posto(ctx)
    ctx.eventos.append(f"obs: {len(novas)} pseudo-medidas" + ("" if ok else ", continua inobservavel"))
    sem = sorted(set(ctx.ilha.barras) - set(novas) - medidas_inj)
    _evento(ctx, "obs", f"observability: H is {m0} x {n}" + (f", rank {r0} of {n}" if r0 is not None else "")
            + f", rank deficient -> requests {len(novas)} load pseudo-measurements (sigma 30%) -> H {m0 + 2 * len(novas)} x {n}"
            + (f", rank {r1}" if r1 is not None else "") + (": full" if ok else ": still unobservable"),
            m=m0, n=n, posto=r0, m_depois=m0 + 2 * len(novas), posto_depois=r1, observavel=ok,
            pseudo=[[b + 1, ctx.pseudo_disponivel[b][0].value, ctx.pseudo_disponivel[b][1].value,
                     ctx.pseudo_disponivel[b][0].sigma, ctx.pseudo_disponivel[b][1].sigma] for b in novas],
            sem_pseudo=[b + 1 for b in sem])
    return ok


def agente_estimador(ctx: _Ctx, estimador: Estimador) -> None:
    ctx.modelo = _modelo(ctx)
    # partida quente: na reestimacao (bad data, subida, descida) parte do x anterior
    x0 = ctx.res.x if ctx.res is not None and ctx.res.converged and len(ctx.res.x) == ctx.modelo.num_states else None
    try:
        ctx.res = estimador(ctx.modelo, x0)
        ctx.historico.append({"fase": ctx.fase, "J": [float(it.objective) for it in ctx.res.iterations]})
        mod = ctx.modelo
        for k, it in enumerate(ctx.res.iterations):
            vt = _v_theta(mod, it.x, ctx.fronteira_barras)
            _evento(ctx, "wls", f"WLS it {k + 1}: J = {it.objective:.2f}, max|dx| = {it.step_norm_inf:.1e} | "
                    + ", ".join(f"V{b + 1} = {v:.5f} pu, th{b + 1} = {a:.4f} deg" for b, (v, a) in vt.items()),
                    it=k + 1, J=float(it.objective), dx=float(it.step_norm_inf),
                    barras={str(b + 1): [round(v, 6), round(a, 5)] for b, (v, a) in vt.items()})
        _evento(ctx, "res", f"result: {'converged' if ctx.res.converged else 'did NOT converge'} in {len(ctx.res.iterations)} "
                f"iterations, x-hat with {mod.num_states} states, {len(mod.z)} measurements", n=mod.num_states, m=len(mod.z))
    except np.linalg.LinAlgError:
        ctx.res = WLSResult(ctx.modelo.flat_start(), False, [], float("nan"))
    if not ctx.res.converged:
        ctx.eventos.append("est: WLS nao convergiu")


def _rn(ctx: _Ctx):
    mod, x = ctx.modelo, ctx.res.x
    H = mod.jacobian(x, sparse=True)
    W = 1.0 / mod.sigma**2
    r = mod.z - mod.h(x)
    rn, _ = normalized_residual(r, H, W, mod.sigma)
    J = float(np.sum(W * r**2))
    gl = len(mod.z) - mod.num_states
    return J, gl, rn, H, W


def agente_bad_data(ctx: _Ctx, estimador: Estimador, alpha: float, rn_lim: float = 3.0,
                    max_rodadas: int = 3) -> dict:
    """chi2 local -> LNR -> remove a pior medida -> reestima (laco classico).

    Pseudo-medida nunca e removida (erro dela e incerteza, nao bad data).
    Medida critica (sem ela a ilha fica cega) tambem nao.
    """

    if not ctx.res.converged:
        return {"J": float("nan"), "gl": 0, "p": float("nan"), "detectado": True}
    pseudo = {(m.kind, m.element) for b in ctx.pseudo_usadas for m in ctx.pseudo_disponivel[b]}
    detectado = False
    for _ in range(max_rodadas):
        J, gl, rn, _, _ = _rn(ctx)
        if gl <= 0:
            return {"J": J, "gl": gl, "p": float("nan"), "detectado": detectado}
        p = float(chi2.sf(J, gl))
        lim = float(chi2.ppf(1 - alpha, gl))
        if p >= alpha:
            _evento(ctx, "bd", f"bad data: J = {J:.2f} <= chi2({gl}; {1 - alpha:.0%}) = {lim:.2f} (p = {p:.3f}) -> no gross error",
                    J=J, gl=gl, lim=lim, p=p)
            return {"J": J, "gl": gl, "p": p, "detectado": detectado}
        detectado = True
        reais = [i for i, m in enumerate(ctx.medidas) if (m.kind, m.element) not in pseudo]
        i = max(reais, key=lambda k: abs(rn[k]))
        _evento(ctx, "bd", f"bad data: J = {J:.2f} > chi2({gl}; {1 - alpha:.0%}) = {lim:.2f} (p = {p:.1e}) -> detected; "
                f"LNR: largest |rN| = {abs(rn[i]):.1f} at {ctx.medidas[i].kind}[bus/line {ctx.medidas[i].element + 1}]",
                J=J, gl=gl, lim=lim, p=p, rn=float(abs(rn[i])))
        if abs(rn[i]) < rn_lim:
            ctx.eventos.append(f"bd: chi2 detecta (p={p:.3g}) mas max|rN|={abs(rn[i]):.2f} < {rn_lim}")
            return {"J": J, "gl": gl, "p": p, "detectado": True}
        m = ctx.medidas[i]
        nome = f"{m.kind}[{m.element}{'/' + m.side if m.side else ''}]"
        antes = ctx.medidas
        ctx.medidas = antes[:i] + antes[i + 1:]
        if not _observavel(ctx):
            ctx.medidas = antes
            ctx.eventos.append(f"bd: {nome} rN={rn[i]:.1f} e critica, nao removida")
            return {"J": J, "gl": gl, "p": p, "detectado": True}
        ctx.removidas.append(m)
        ctx.eventos.append(f"bd: remove {nome} rN={rn[i]:.1f}")
        _evento(ctx, "bd", f"bad data: removes {m.kind}[{m.element + 1}{'/' + m.side if m.side else ''}] (rN = {rn[i]:.1f}) and re-estimates",
                medida=nome, rn=float(rn[i]))
        agente_estimador(ctx, estimador)
        if not ctx.res.converged:
            return {"J": float("nan"), "gl": gl, "p": float("nan"), "detectado": True}
    J, gl, _, _, _ = _rn(ctx)
    return {"J": J, "gl": gl, "p": float(chi2.sf(J, gl)), "detectado": True}


def _estado_barra(ctx: _Ctx, barra: int) -> dict:
    """V, theta e sigmas de `barra` estimados pela ilha (sigma por G^-1)."""

    mod, x = ctx.modelo, ctx.res.x
    _, _, _, H, W = _rn(ctx)
    sig = np.sqrt(np.maximum(np.diag(state_covariance(H, W)), 0.0))
    pos = mod.bus_lookup[barra]
    iv = mod.vm_state_offset + pos
    ia = mod.angle_state_index.get(barra)
    return {
        "barra": barra,
        "vm": float(x[iv]), "sigma_vm": float(sig[iv]),
        "va_deg": float(np.rad2deg(np.angle(mod.state_to_voltage(x)[pos]))),
        "sigma_va_deg": float(np.rad2deg(sig[ia])) if ia is not None else 0.0,
    }


def _divide(mae: dict, filha: dict | None) -> tuple[float, float]:
    """Tira da estimativa da mae a contribuicao que veio da propria filha.

    Divisao de gaussianas (informacao = 1/sigma^2 se subtrai). Se sobra pouca
    informacao propria da mae, devolve um sigma grande (a mae nao sabe nada
    alem do que a filha ja sabia).
    """

    if filha is None:
        return mae["vm"], mae["sigma_vm"]
    im, if_ = mae["sigma_vm"] ** -2, filha["sigma_vm"] ** -2
    i = max(im - if_, 1e-3 * im)
    return (mae["vm"] * im - filha["vm"] * if_) / i, i ** -0.5


def _motivo(ctx: _Ctx, politica: Politica, obs: bool, limiar: float) -> str | None:
    if politica == "nunca":
        return None
    if politica == "sempre":
        return "politica_sempre"
    if not obs or not ctx.res.converged:
        return "inobservavel"
    s = _estado_barra(ctx, ctx.ilha.ancora)["sigma_vm"]
    if s > limiar:
        return f"sigma_vm_ancora={s:.4f}"
    if ctx.bd.get("detectado"):
        return "bad_data_local"
    return None


# --------------------------------------------------------------------------
# Orquestrador + coordenador
# --------------------------------------------------------------------------


@dataclass
class ResultadoMultiarea:
    estado: pd.DataFrame          # barra, ilha, vm, va_deg (referencia global)
    ilhas: pd.DataFrame           # resumo por ilha
    mensagens: list[AgentMessage]
    eventos: dict[str, list[str]]
    removidas: dict[str, list[ACMeasurement]]
    kpi: dict                     # tempos, tamanho do maior problema, bytes, alertas

    def mensagens_df(self) -> pd.DataFrame:
        return pd.DataFrame([
            {"de": m.sender_id, "para": m.recipient_id, "tipo": m.message_type,
             "prioridade": m.priority, "bytes": m.bytes_size} for m in self.mensagens
        ])


def _cronometra(ctx: _Ctx, fase: str, f, *a):
    t0 = time.perf_counter()
    ctx.fase = fase
    out = f(*a)
    ms = (time.perf_counter() - t0) * 1000.0
    ctx.tempo[fase] = ctx.tempo.get(fase, 0.0) + ms
    ctx.segmentos.append({"fase": fase, "etapa": f.__name__.removeprefix("agente_").removeprefix("_"), "ms": ms})
    return out


def rodar_multiarea(
    net_modelo,
    ilhas: list[Ilha],
    medidas: list[ACMeasurement],
    pseudo: dict[int, list[ACMeasurement]],
    *,
    politica: Politica = "sob_demanda",
    estimador: Estimador | None = None,
    alpha: float = 0.05,
    limiar_sigma_ancora_pu: float = 0.005,
    limiar_z_fronteira: float = 3.0,
    subredes: dict | None = None,
    verbose: bool = False,
) -> ResultadoMultiarea:
    """Roda os times de agentes nas tres fases (local, subida, descida).

    `net_modelo` e a rede que o operador ACHA que tem (cadastro); erro de
    parametro se injeta nela, nao na verdade. `politica` decide quando a
    filha conversa com a mae: "nunca" (so a fase 1), "sob_demanda" (regra de
    `_motivo`), "sempre" (baseline de custo para o M5.3).

    Tempo: cada fase cronometrada por ilha; o tempo paralelo e o caminho
    critico (max da fase 1 + soma, por profundidade da arvore, do max da
    subida e da descida). A construcao dos modelos (uma vez por topologia)
    fica fora. ponytail: latencia de rede nao entra; somar
    `n_niveis * 2 * latencia` quando houver um numero de telecom.
    """

    estimador = estimador or (lambda mod, x0: mod.solve(x0))
    log: list[AgentMessage] = []
    ctxs: dict[str, _Ctx] = {}
    prof = {}
    traco: list[dict] = []

    # fase 1: local, em paralelo
    for ilha in ilhas:
        sub = subredes[ilha.nome] if subredes else _subrede(net_modelo, ilha)
        med_ilha, internas = _medidas_da_ilha(net_modelo, sub, ilha, medidas)
        ctx = _Ctx(ilha, sub, med_ilha, pseudo, internas, alinhada=ilha.ancora is None,
                   traco=traco, verbose=verbose,
                   fronteira_barras=sorted(set(int(b) for b in sub.bus.index) - set(ilha.barras)),
                   medidas_iniciais=[_chave(m) for m in med_ilha])
        ctxs[ilha.nome] = ctx
        prof[ilha.nome] = 0 if ilha.mae is None else prof[ilha.mae] + 1
        obs = _cronometra(ctx, "local", agente_observabilidade, ctx, log)
        if obs:
            _cronometra(ctx, "local", agente_estimador, ctx, estimador)
            ctx.bd = _cronometra(ctx, "local", agente_bad_data, ctx, estimador, alpha)
        if ilha.mae is not None:
            ctx.conversa = _motivo(ctx, politica, obs, limiar_sigma_ancora_pu) if ctx.res is not None else "inobservavel"

    # fase 2: subida (folhas -> raiz)
    alertas = []
    for ilha in reversed(ilhas):
        ctx = ctxs[ilha.nome]
        if any(k.startswith("de_") for k in ctx.fronteira) and ctx.res is not None:
            _cronometra(ctx, "subida", agente_estimador, ctx, estimador)
        if ilha.mae is None or not ctx.conversa or ctx.res is None or not ctx.res.converged:
            continue
        mae = ctxs[ilha.mae]
        if mae.res is None or not mae.res.converged:
            continue
        sobe = _cronometra(ctx, "subida", _estado_barra, ctx, ilha.ancora)
        ctx.subiu = sobe
        _evento(ctx, "msg", f"SENDS to {mae.ilha.nome} (BOUNDARY_UP): V-hat{ilha.ancora + 1} = {sobe['vm']:.5f} pu, "
                f"sigma = {sobe['sigma_vm']:.5f} (from {ilha.nome}'s measurements only)", fim=True,
                para=mae.ilha.nome, barra=ilha.ancora + 1, vm=sobe["vm"], sigma=sobe["sigma_vm"])
        _msg(log, f"Est_{ilha.nome}", f"Est_{mae.ilha.nome}", "BOUNDARY_UP",
             {k: sobe[k] for k in ("barra", "vm", "sigma_vm")} | {"motivo": ctx.conversa})
        # consistencia de fronteira: duas estimativas independentes da mesma barra
        da_mae = _estado_barra(mae, ilha.ancora)
        z = (sobe["vm"] - da_mae["vm"]) / np.hypot(sobe["sigma_vm"], da_mae["sigma_vm"])
        _evento(ctx, "z", f"{mae.ilha.nome} compares: its own V{ilha.ancora + 1} = {da_mae['vm']:.5f} (sigma {da_mae['sigma_vm']:.5f}) "
                f"x {ilha.nome}'s = {sobe['vm']:.5f} -> z = {z:.2f} "
                + (f"> {limiar_z_fronteira:g}: ALERT to coordinator, not fused" if abs(z) > limiar_z_fronteira
                   else f"<= {limiar_z_fronteira:g}: consistent, {mae.ilha.nome} fuses it as a pseudo-measurement"),
                fim=True, z=float(z), vm_mae=da_mae["vm"], vm_filha=sobe["vm"])
        if abs(z) > limiar_z_fronteira:
            alertas.append({"filha": ilha.nome, "mae": mae.ilha.nome, "barra": ilha.ancora, "z": float(z)})
            _msg(log, f"BadData_{ilha.nome}", "Coordenador", "BOUNDARY_INCONSISTENT",
                 {"barra": ilha.ancora, "z": round(float(z), 2)}, "HIGH")
            ctx.eventos.append(f"bd: fronteira inconsistente com {mae.ilha.nome}, z={z:.1f}")
        else:
            mae.fronteira[f"de_{ilha.nome}"] = ACMeasurement(
                "v_bus", ilha.ancora, sobe["vm"], max(sobe["sigma_vm"], 1e-5))

    # fase 3: descida (raiz -> folhas)
    for ilha in ilhas:
        ctx = ctxs[ilha.nome]
        if ilha.mae is None or not ctx.conversa:
            continue
        mae = ctxs[ilha.mae]
        if mae.res is None or not mae.res.converged:
            continue
        info = _cronometra(ctx, "descida", _estado_barra, mae, ilha.ancora)
        usado = ctx.subiu if f"de_{ilha.nome}" in mae.fronteira else None
        vm, s = _divide(info, usado)
        _msg(log, f"Est_{mae.ilha.nome}", f"Est_{ilha.nome}", "BOUNDARY_DOWN",
             {"barra": ilha.ancora, "vm": vm, "sigma_vm": s, "va_deg": info["va_deg"]})
        ctx.va_ancora_deg, ctx.alinhada = info["va_deg"], True
        ctx.fronteira["da_mae"] = ACMeasurement("v_bus", ilha.ancora, vm, max(s, 1e-5))
        _evento(ctx, "msg", f"RECEIVES from {mae.ilha.nome} (BOUNDARY_DOWN): V{ilha.ancora + 1} = {vm:.5f} pu, "
                f"th{ilha.ancora + 1} = {info['va_deg']:.4f} deg, sigma = {s:.5f} (without {ilha.nome}'s share); "
                f"fixes the angle reference and re-estimates", fim=True, de=mae.ilha.nome, barra=ilha.ancora + 1,
                vm=vm, va=info["va_deg"], sigma=s, vm_mae=info["vm"], sigma_mae=info["sigma_vm"],
                vm_filha=usado["vm"] if usado else None, sigma_filha=usado["sigma_vm"] if usado else None)
        ctx.eventos.append(f"coord: conversou com {mae.ilha.nome} ({ctx.conversa})")
        if ctx.res is None:  # inobservavel sozinha: a ancora pode fechar o posto
            if not _cronometra(ctx, "descida", agente_observabilidade, ctx, log):
                continue
        _cronometra(ctx, "descida", agente_estimador, ctx, estimador)
        # bad data de novo: com a ancora da mae, medida que era critica na ilha
        # sozinha (|V| de fim de ramal) vira redundante e pode ser identificada
        bd2 = _cronometra(ctx, "descida", agente_bad_data, ctx, estimador, alpha)
        ctx.bd = {**bd2, "detectado": bool(ctx.bd.get("detectado")) or bd2["detectado"]}

    # coordenador: alinha angulos de quem nao conversou e monta o estado global
    linhas, resumo = [], []
    va_global: dict[int, float] = {}
    for ilha in ilhas:
        ctx = ctxs[ilha.nome]
        if ctx.res is None:
            continue
        ctx.fase = "publica"
        _evento(ctx, "msg", f"SENDS to coordinator (STATE_PUBLISH): x-hat with {ctx.modelo.num_states} states",
                fim=True, para="Coordenador", n=ctx.modelo.num_states)
        _msg(log, f"Est_{ilha.nome}", "Coordenador", "STATE_PUBLISH",
             {"x": [round(float(v), 6) for v in ctx.res.x]})
        V = ctx.modelo.state_to_voltage(ctx.res.x)
        va = np.rad2deg(np.angle(V))
        if not ctx.alinhada and ilha.ancora in va_global:
            va = va + (va_global[ilha.ancora] - ctx.va_ancora_deg)
        for b in ilha.barras:
            p = ctx.modelo.bus_lookup[b]
            va_global[b] = float(va[p])
            linhas.append({"barra": b, "ilha": ilha.nome, "vm": float(np.abs(V[p])), "va_deg": float(va[p])})
        J, gl, *_ = _rn(ctx) if ctx.res.converged else (float("nan"), 0)
        resumo.append({
            "ilha": ilha.nome, "mae": ilha.mae, "barras": len(ilha.barras), "ancora": ilha.ancora,
            "estados": ctx.modelo.num_states, "medidas": len(ctx.modelo.z),
            "pseudo": len(ctx.pseudo_usadas), "removidas": len(ctx.removidas),
            "bd_detectou": bool(ctx.bd.get("detectado", False)),
            "alerta_fronteira": any(a["filha"] == ilha.nome for a in alertas),
            "conversou": ctx.conversa, "J": J, "gl": gl,
            "p_chi2": float(chi2.sf(J, gl)) if gl > 0 else float("nan"),
            **{f"t_{k}_ms": round(v, 2) for k, v in ctx.tempo.items()},
            "convergiu": ctx.res.converged,
        })

    def caminho(fase):
        por_nivel = {}
        for n, c in ctxs.items():
            por_nivel[prof[n]] = max(por_nivel.get(prof[n], 0.0), c.tempo.get(fase, 0.0))
        return sum(por_nivel.values())

    entre = [m for m in log if m.message_type.startswith("BOUNDARY")]
    publ = [m for m in log if m.message_type == "STATE_PUBLISH"]
    kpi = {
        "n_ilhas": len(ilhas),
        "maior_ilha_estados": max(c.modelo.num_states for c in ctxs.values() if c.modelo is not None),
        "tempo_paralelo_ms": max(c.tempo.get("local", 0.0) for c in ctxs.values()) + caminho("subida") + caminho("descida"),
        "tempo_serial_ms": sum(sum(c.tempo.values()) for c in ctxs.values()),
        "mensagens_vizinhas": len(entre),
        "bytes_vizinhas": sum(m.bytes_size for m in entre),
        "bytes_ate_centro": sum(m.bytes_size for m in publ + [m for m in log if m.recipient_id == "Coordenador" and m.message_type != "STATE_PUBLISH"]),
        "alertas_fronteira": alertas,
    }
    return ResultadoMultiarea(
        pd.DataFrame(linhas).sort_values("barra").reset_index(drop=True),
        pd.DataFrame(resumo), log, {n: c.eventos for n, c in ctxs.items()},
        {n: c.removidas for n, c in ctxs.items()}, kpi | {"historico": {n: c.historico for n, c in ctxs.items()},
               "segmentos": {n: c.segmentos for n, c in ctxs.items()},
               "profundidade": prof, "traco": traco,
               "ilhas_info": {n: {"fronteira_barras": c.fronteira_barras, "internas": sorted(c.internas),
                               "pseudo_usadas": c.pseudo_usadas, "medidas_iniciais": c.medidas_iniciais} for n, c in ctxs.items()}},
    )


def bytes_medidas_ao_centro(medidas: list[ACMeasurement]) -> int:
    """Custo do centralizado: cada medida crua sobe ao centro (mesmo envelope)."""

    return sum(AgentMessage("RTU", "Centro", "MEASUREMENT",
                            {"k": m.kind, "e": m.element, "s": m.side, "v": round(m.value, 6)}).bytes_size
               for m in medidas)


def ilha_unica(net) -> list[Ilha]:
    return [Ilha("Central", sorted(int(b) for b in net.bus.index))]


def rodar_centralizado(net_modelo, medidas, pseudo, *, estimador: Estimador | None = None,
                       alpha: float = 0.05, subredes: dict | None = None,
                       verbose: bool = False) -> ResultadoMultiarea:
    """Baseline: a mesma maquinaria com uma ilha so (a rede inteira)."""

    r = rodar_multiarea(net_modelo, ilha_unica(net_modelo), medidas, pseudo, politica="nunca",
                        estimador=estimador, alpha=alpha, subredes=subredes, verbose=verbose)
    r.kpi["bytes_ate_centro"] = bytes_medidas_ao_centro(medidas)
    return r


def comparar_com_verdade(estado: pd.DataFrame, net_verdade) -> dict:
    v = net_verdade.res_bus.loc[estado.barra]
    dv = estado.vm.to_numpy() - v.vm_pu.to_numpy()
    da = estado.va_deg.to_numpy() - v.va_degree.to_numpy()
    return {
        "rmse_vm_pu": float(np.sqrt(np.mean(dv**2))),
        "max_dvm_pu": float(np.max(np.abs(dv))),
        "rmse_va_deg": float(np.sqrt(np.mean(da**2))),
    }


def _demo():
    """Autoteste: sem ruido e com plano completo, multiarea = verdade."""

    import pandapower.networks as pn

    rng = np.random.default_rng(0)
    net = pn.case33bw()
    pp.runpp(net)
    verdade = rede_verdade(net, rng)
    ilhas = ilhas_por_corte(net, [5, 24])
    assert [i.nome for i in ilhas] == ["A", "B", "C"]
    assert [len(i.barras) for i in ilhas] == [13, 12, 8], [len(i.barras) for i in ilhas]
    assert ilhas[1].ancora == 5 and ilhas[2].ancora == 5
    med = montar_medidas(verdade, rng, v_barras=list(net.bus.index), fluxo_linhas=list(net.line.index),
                         inj_barras=list(net.bus.index), noise_level=1e-9, sigma_min=1e-9)
    for pol in ("nunca", "sob_demanda", "sempre"):
        r = rodar_multiarea(verdade, ilhas, med, pseudo_medidas_carga(net), politica=pol)
        m = comparar_com_verdade(r.estado, verdade)
        assert m["max_dvm_pu"] < 1e-5 and m["rmse_va_deg"] < 1e-3, (pol, m)
    grande = rede_multialimentador(3)
    assert len(grande.bus) == 97 and abs(grande.res_bus.vm_pu.min() - net.res_bus.vm_pu.min()) < 1e-6
    print("ok", m)


if __name__ == "__main__":
    _demo()
