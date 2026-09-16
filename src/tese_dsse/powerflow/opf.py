"""OPF sobre o estado ESTIMADO -- a ultima camada da cadeia operacional.

O ponto desta camada nao e resolver um OPF (o pandapower ja faz). E que o
operador **nunca** resolve o OPF sobre a rede real: resolve sobre o modelo que
o processador de topologia reconstruiu e sobre o estado que o estimador
entregou. Os setpoints saem desse modelo e sao aplicados na rede de verdade.

Quando o modelo esta certo, os dois coincidem e nao ha nada a estudar. Quando
um ataque ou uma falha corrompeu alguma camada acima, aparecem duas coisas que
nenhuma metrica de estimador captura:

1. **Erro de controle** -- a diferenca entre os setpoints que o operador
   despachou e os que teria despachado com informacao perfeita. E o custo real
   do ataque, medido em MW, nao em residuo.
2. **Violacao oculta** -- uma restricao que e violada na REDE REAL depois de
   aplicar os setpoints, mas que o OPF do operador considerou satisfeita, porque
   o modelo dele dizia outra coisa. O operador nao ve alarme nenhum.

A violacao oculta e o argumento que interessa a um operador de verdade: nao
"o resíduo subiu", e sim "voce teria deixado a barra 4 abaixo de 0,95 pu sem
receber um unico alarme".

`opf_under_uncertainty()` executa exatamente essa comparacao de tres pontas:
OPF no modelo do operador, OPF no modelo verdadeiro, e o resultado fisico de
aplicar o primeiro na rede verdadeira.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ControlAssessment",
    "OPFLimits",
    "OPFResult",
    "Setpoint",
    "Violation",
    "apply_setpoints",
    "check_violations",
    "diagnose_infeasibility",
    "opf_under_uncertainty",
    "prepare_opf_net",
    "run_opf",
]


@dataclass(frozen=True)
class OPFLimits:
    """Restricoes e custos do despacho.

    Os custos sao **relativos**, nao valores de mercado: o que importa e a
    ordem de merito. O default coloca a rede de montante (`ext_grid`) como a
    fonte mais cara e a geracao distribuida como a mais barata, que e o
    enquadramento tipico de uma distribuidora -- importar energia tem preco,
    o DER local ja esta la. Com essa ordem, o despacho otimo depende de a rede
    aguentar o fluxo do DER, ou seja, **depende do modelo** -- e e por isso que
    um erro de topologia muda a resposta. Com a ordem invertida, o OPF
    responderia "traga tudo do ext_grid" e o modelo quase nao importaria.
    """

    vm_min_pu: float = 0.95
    vm_max_pu: float = 1.05
    max_loading_percent: float = 100.0
    ext_grid_cost: float = 60.0
    gen_cost: float = 20.0
    sgen_cost: float = 5.0
    """Curtailment de DER: `sgen` vira controlavel entre 0 e a potencia
    disponivel. Custo baixo = despachar tudo que couber; o que sobra e
    curtailment forcado por restricao de rede."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "vm_min_pu": self.vm_min_pu,
            "vm_max_pu": self.vm_max_pu,
            "max_loading_percent": self.max_loading_percent,
            "ext_grid_cost": self.ext_grid_cost,
            "gen_cost": self.gen_cost,
            "sgen_cost": self.sgen_cost,
        }


@dataclass(frozen=True)
class Setpoint:
    """Uma ordem de despacho para um equipamento controlavel."""

    element: str
    """'ext_grid', 'gen' ou 'sgen'."""
    index: int
    bus: int
    p_mw: float
    q_mvar: float

    @property
    def key(self) -> tuple[str, int]:
        return (self.element, self.index)

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "index": self.index,
            "bus": self.bus,
            "p_mw": round(float(self.p_mw), 6),
            "q_mvar": round(float(self.q_mvar), 6),
        }


@dataclass(frozen=True)
class Violation:
    """Uma restricao violada, com quanto foi ultrapassada."""

    kind: str
    """'undervoltage', 'overvoltage' ou 'overload'."""
    element: str
    index: int
    value: float
    limit: float

    @property
    def margin(self) -> float:
        """Quanto passou do limite (sempre positivo)."""
        return abs(float(self.value) - float(self.limit))

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.kind, self.element, self.index)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "element": self.element,
            "index": self.index,
            "value": round(float(self.value), 6),
            "limit": round(float(self.limit), 6),
            "margin": round(self.margin, 6),
        }


@dataclass
class OPFResult:
    converged: bool
    objective: float | None = None
    setpoints: list[Setpoint] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    vm_pu: dict[int, float] = field(default_factory=dict)
    loading_percent: dict[int, float] = field(default_factory=dict)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "converged": self.converged,
            "objective": None if self.objective is None else round(float(self.objective), 6),
            "setpoints": [s.to_dict() for s in self.setpoints],
            "violations": [v.to_dict() for v in self.violations],
            "n_violations": len(self.violations),
            "vm_pu": {str(k): round(float(v), 6) for k, v in sorted(self.vm_pu.items())},
            "loading_percent": {
                str(k): round(float(v), 3) for k, v in sorted(self.loading_percent.items())
            },
            "reason": self.reason,
        }


def prepare_opf_net(net: Any, limits: OPFLimits) -> Any:
    """Copia a rede e instala limites e custos para o OPF.

    As redes que o app monta (`build_net_from_frontend`) nao trazem limite
    nenhum -- sao feitas para power flow e estimacao. Sem limites o OPF e um
    despacho puramente economico e o modelo de rede quase nao entra na conta;
    com eles, a topologia passa a decidir o resultado, que e o efeito que a
    cadeia existe para estudar.

    `sgen` vira controlavel entre 0 e a potencia disponivel: e assim que se
    modela curtailment de geracao distribuida, a acao de controle mais comum
    numa distribuidora com DER.
    """
    import pandapower as pp

    out = copy.deepcopy(net)

    out.bus["min_vm_pu"] = limits.vm_min_pu
    out.bus["max_vm_pu"] = limits.vm_max_pu
    if len(out.line):
        out.line["max_loading_percent"] = limits.max_loading_percent
    if hasattr(out, "trafo") and len(out.trafo):
        out.trafo["max_loading_percent"] = limits.max_loading_percent

    total_load = float(out.load.p_mw.sum()) if len(out.load) else 1.0
    headroom = max(abs(total_load) * 10.0, 1.0)

    # Zera custos preexistentes: chamar prepare duas vezes na mesma rede
    # duplicaria os poly_cost e o objetivo sairia dobrado sem erro nenhum.
    if hasattr(out, "poly_cost") and len(out.poly_cost):
        out.poly_cost = out.poly_cost.iloc[0:0]

    for idx in out.ext_grid.index:
        out.ext_grid.at[idx, "min_p_mw"] = -headroom
        out.ext_grid.at[idx, "max_p_mw"] = headroom
        out.ext_grid.at[idx, "min_q_mvar"] = -headroom
        out.ext_grid.at[idx, "max_q_mvar"] = headroom
        pp.create_poly_cost(out, int(idx), "ext_grid", cp1_eur_per_mw=limits.ext_grid_cost)

    for idx in out.gen.index:
        # Teto = 1,5x o despacho atual. As redes do app nao trazem placa
        # (`build_net_from_frontend` cria `gen` so com `p_mw`), entao algum
        # numero precisa ser inventado; amarra-lo ao despacho atual mantem a
        # ordem de grandeza fisica da maquina. Um teto solto (uma fracao do
        # `headroom`) deixaria um gerador de 0,4 MW despachar 10 MW e o OPF
        # deixaria de ser limitado pela rede -- que e justamente o que se quer
        # observar.
        available = float(out.gen.at[idx, "p_mw"])
        out.gen.at[idx, "min_p_mw"] = 0.0
        out.gen.at[idx, "max_p_mw"] = max(available * 1.5, 1e-3)
        out.gen.at[idx, "min_q_mvar"] = -headroom
        out.gen.at[idx, "max_q_mvar"] = headroom
        out.gen.at[idx, "controllable"] = True
        pp.create_poly_cost(out, int(idx), "gen", cp1_eur_per_mw=limits.gen_cost)

    for idx in out.sgen.index:
        available = float(out.sgen.at[idx, "p_mw"])
        out.sgen.at[idx, "min_p_mw"] = 0.0
        out.sgen.at[idx, "max_p_mw"] = max(available, 0.0)
        out.sgen.at[idx, "min_q_mvar"] = -abs(available)
        out.sgen.at[idx, "max_q_mvar"] = abs(available)
        out.sgen.at[idx, "controllable"] = True
        pp.create_poly_cost(out, int(idx), "sgen", cp1_eur_per_mw=limits.sgen_cost)

    return out


def check_violations(net: Any, limits: OPFLimits) -> list[Violation]:
    """Restricoes violadas nos resultados JA calculados de `net`.

    Le `res_bus`/`res_line`; nao resolve nada. Serve tanto para o pos-OPF
    quanto para o power flow que aplica setpoints na rede verdadeira -- e
    justamente por ser a mesma funcao nos dois casos que a comparacao entre
    "o que o operador viu" e "o que aconteceu" e legitima.
    """
    out: list[Violation] = []

    if hasattr(net, "res_bus") and len(net.res_bus):
        for idx, row in net.res_bus.iterrows():
            vm = float(row.vm_pu)
            if vm < limits.vm_min_pu:
                out.append(Violation("undervoltage", "bus", int(idx), vm, limits.vm_min_pu))
            elif vm > limits.vm_max_pu:
                out.append(Violation("overvoltage", "bus", int(idx), vm, limits.vm_max_pu))

    if hasattr(net, "res_line") and len(net.res_line):
        for idx, row in net.res_line.iterrows():
            loading = float(row.loading_percent)
            if loading > limits.max_loading_percent:
                out.append(
                    Violation("overload", "line", int(idx), loading, limits.max_loading_percent)
                )

    return out


def _collect_setpoints(net: Any) -> list[Setpoint]:
    out: list[Setpoint] = []
    for element, table, res in (
        ("ext_grid", net.ext_grid, getattr(net, "res_ext_grid", None)),
        ("gen", net.gen, getattr(net, "res_gen", None)),
        ("sgen", net.sgen, getattr(net, "res_sgen", None)),
    ):
        if res is None or not len(table):
            continue
        for idx in table.index:
            if idx not in res.index:
                continue
            out.append(
                Setpoint(
                    element=element,
                    index=int(idx),
                    bus=int(table.at[idx, "bus"]),
                    p_mw=float(res.at[idx, "p_mw"]),
                    q_mvar=float(res.at[idx, "q_mvar"]),
                )
            )
    return out


def diagnose_infeasibility(net: Any, limits: OPFLimits) -> str | None:
    """Separa "conjunto factivel vazio" de "o solver falhou".

    `runopp` levanta a mesma `OPFNotConverged` para as duas coisas, e a
    diferenca decide o que fazer: falha numerica se ataca trocando de solver ou
    de ponto de partida; conjunto factivel vazio nao se ataca de jeito nenhum,
    so mudando o problema (afrouxar limite ou dar um recurso controlavel a
    rede). Sem esta separacao a tela mostra uma excecao crua e sugere que a
    ferramenta quebrou, quando na verdade ela esta respondendo certo.

    A separacao e barata: um power flow simples da o ponto de operacao natural
    da rede, e comparar esse ponto com a banda de tensao diz se havia alguma
    chance. O caso que motivou isto e o `case33bw`: alimentador radial cujo
    perfil natural chega a 0,913 pu no fim do tronco, contra um `vm_min_pu` de
    0,95, e sem um unico `gen`/`sgen` capaz de levantar a tensao. O OPF esta
    correto ao nao convergir -- nao existe ponto que satisfaca as restricoes.

    So e chamada no caminho de falha, entao o power flow extra nunca entra no
    custo da corrida normal. Devolve `None` quando nem o power flow resolve, que
    ja e diagnostico por si (o modelo nem sequer e resolvivel).
    """
    import pandapower as pp

    probe = copy.deepcopy(net)
    try:
        pp.runpp(probe, algorithm="nr", max_iteration=50, numba=False)
    except Exception as exc:
        return (
            "A plain power flow does not solve on this model either "
            f"({type(exc).__name__}), so the OPF was handed a network that is "
            "not physically consistent to begin with."
        )

    vm = probe.res_bus.vm_pu.dropna()
    if vm.empty:
        return None

    under = vm[vm < limits.vm_min_pu]
    over = vm[vm > limits.vm_max_pu]
    n_ctrl = len(probe.gen) + len(probe.sgen)

    if under.empty and over.empty:
        return (
            "The unconstrained operating point respects the voltage band "
            f"({vm.min():.4f}-{vm.max():.4f} pu), so this looks like a solver "
            "failure rather than infeasible limits."
        )

    parts = []
    if not under.empty:
        parts.append(
            f"{len(under)} of {len(vm)} buses sit at {under.min():.4f} pu, below "
            f"the {limits.vm_min_pu:.3f} pu floor"
        )
    if not over.empty:
        parts.append(
            f"{len(over)} of {len(vm)} buses sit at {over.max():.4f} pu, above "
            f"the {limits.vm_max_pu:.3f} pu ceiling"
        )

    detail = (
        "Infeasible limits, not a solver failure: with no constraints at all, "
        + " and ".join(parts)
        + ". "
    )
    if n_ctrl == 0:
        detail += (
            "The network has no controllable generation (0 gen, 0 sgen), so "
            "nothing in the model can move that voltage: the feasible set is "
            "empty before the optimiser starts. Either widen the voltage band "
            "or give the feeder a controllable resource."
        )
    else:
        detail += (
            f"The {n_ctrl} controllable unit(s) in the model were not enough to "
            "bring the network inside the band."
        )
    return detail


def run_opf(net: Any, limits: OPFLimits | None = None, *, prepared: bool = False) -> OPFResult:
    """Resolve o OPF AC. `prepared=True` pula `prepare_opf_net`.

    Nao convergir e um resultado, nao um bug: uma rede reconstruida a partir de
    status telemetrado errado pode ser fisicamente impossivel, e o OPF nao
    convergir e exatamente o que o operador veria. `reason` diz o que houve.
    """
    import pandapower as pp

    limits = limits or OPFLimits()
    work = net if prepared else prepare_opf_net(net, limits)

    try:
        pp.runopp(work, numba=False)
    except Exception as exc:
        reason = f"OPF did not converge: {type(exc).__name__}: {exc}"
        diagnosis = diagnose_infeasibility(work, limits)
        if diagnosis:
            reason = f"{reason}\n{diagnosis}"
        return OPFResult(converged=False, reason=reason)

    return OPFResult(
        converged=True,
        objective=float(work.res_cost),
        setpoints=_collect_setpoints(work),
        violations=check_violations(work, limits),
        vm_pu={int(i): float(r.vm_pu) for i, r in work.res_bus.iterrows()},
        loading_percent=(
            {int(i): float(r.loading_percent) for i, r in work.res_line.iterrows()}
            if len(work.res_line) else {}
        ),
    )


def apply_setpoints(net: Any, setpoints: list[Setpoint]) -> Any:
    """Aplica setpoints numa copia da rede e resolve o power flow.

    E o passo que fecha o ciclo: a ordem de controle sai do modelo do operador
    e cai na rede fisica. O `ext_grid` fica de fora porque nao e despachavel na
    pratica -- e a barra de folga, absorve o desbalanco que sobrar.
    """
    import pandapower as pp

    out = copy.deepcopy(net)
    for sp in setpoints:
        if sp.element == "ext_grid":
            continue
        table = getattr(out, sp.element, None)
        if table is None or sp.index not in table.index:
            continue
        table.at[sp.index, "p_mw"] = float(sp.p_mw)
        if sp.element == "sgen":
            table.at[sp.index, "q_mvar"] = float(sp.q_mvar)

    try:
        pp.runpp(out, algorithm="nr", max_iteration=50, numba=False)
    except Exception:
        pp.runpp(out, algorithm="iwamoto_nr", max_iteration=100, numba=False)
    return out


@dataclass
class ControlAssessment:
    """O que o OPF do operador custou, comparado ao que ele teria feito sabendo."""

    operator: OPFResult
    """OPF sobre o modelo que o operador acredita (topologia reconstruida)."""
    ideal: OPFResult
    """OPF sobre o modelo verdadeiro -- o contrafactual."""
    reality_violations: list[Violation] = field(default_factory=list)
    """Violacoes na rede REAL depois de aplicar os setpoints do operador."""
    baseline_violations: list[Violation] = field(default_factory=list)
    """Violacoes na rede real aplicando os setpoints IDEAIS. E o contrafactual
    necessario: o `ext_grid` e barra de folga e absorve o desbalanco, entao a
    rede realizada nunca reproduz o ponto do OPF exatamente, nem com modelo
    perfeito. Sem descontar esta linha de base, esse residuo de modelagem
    apareceria como 'violacao oculta' toda vez -- foi o que aconteceu na
    primeira versao desta funcao."""
    hidden_violations: list[Violation] = field(default_factory=list)
    """Violacoes que (a) o OPF do operador nao previu E (b) nao teriam
    acontecido com informacao perfeita. Ou seja: causadas pelo modelo errado e
    invisiveis para quem despachou. O numero que interessa a um operador."""
    setpoint_deltas: list[dict[str, Any]] = field(default_factory=list)
    max_setpoint_error_mw: float = 0.0
    total_setpoint_error_mw: float = 0.0
    cost_gap: float | None = None
    reason: str | None = None

    @property
    def safe(self) -> bool:
        return not self.hidden_violations and self.operator.converged

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator.to_dict(),
            "ideal": self.ideal.to_dict(),
            "reality_violations": [v.to_dict() for v in self.reality_violations],
            "baseline_violations": [v.to_dict() for v in self.baseline_violations],
            "hidden_violations": [v.to_dict() for v in self.hidden_violations],
            "n_hidden_violations": len(self.hidden_violations),
            "setpoint_deltas": self.setpoint_deltas,
            "max_setpoint_error_mw": round(float(self.max_setpoint_error_mw), 6),
            "total_setpoint_error_mw": round(float(self.total_setpoint_error_mw), 6),
            "cost_gap": None if self.cost_gap is None else round(float(self.cost_gap), 6),
            "safe": self.safe,
            "reason": self.reason,
        }


def opf_under_uncertainty(
    net_true: Any,
    net_believed: Any,
    limits: OPFLimits | None = None,
) -> ControlAssessment:
    """A comparacao de tres pontas descrita no topo do modulo.

    1. OPF em `net_believed` -> os setpoints que o operador realmente despacha.
    2. OPF em `net_true` -> o que ele teria despachado sabendo de tudo.
    3. Os setpoints de (1) aplicados a `net_true` -> o que acontece de fato.

    A violacao oculta sai de (3) menos o que (1) previu. `net_believed` e a
    rede reconstruida pelo processador de topologia; `net_true` e a rede
    fisica, que so o simulador conhece.
    """
    limits = limits or OPFLimits()

    operator = run_opf(net_believed, limits)
    ideal = run_opf(net_true, limits)

    assessment = ControlAssessment(operator=operator, ideal=ideal)

    if not operator.converged:
        assessment.reason = (
            "The operator's OPF did not converge on the reconstructed model, so no setpoints "
            "were dispatched. That is itself the outcome: the model handed to the optimiser "
            "is infeasible."
        )
        return assessment

    if operator.converged and ideal.converged and ideal.objective is not None:
        assessment.cost_gap = float(operator.objective or 0.0) - float(ideal.objective)

    # (3) o que realmente acontece com o despacho do operador
    try:
        realised = apply_setpoints(net_true, operator.setpoints)
        assessment.reality_violations = check_violations(realised, limits)
    except Exception as exc:
        assessment.reason = (
            f"The dispatched setpoints do not produce a solvable power flow on the real "
            f"network: {type(exc).__name__}: {exc}"
        )
        return assessment

    # (3b) o contrafactual: o mesmo, com os setpoints ideais. Ver o docstring
    # de `baseline_violations` -- sem isto, o residuo de folga do slack conta
    # como violacao oculta mesmo quando o modelo do operador esta correto.
    if ideal.converged:
        try:
            baseline = apply_setpoints(net_true, ideal.setpoints)
            assessment.baseline_violations = check_violations(baseline, limits)
        except Exception:
            assessment.baseline_violations = []

    seen = {v.key for v in operator.violations}
    unavoidable = {v.key for v in assessment.baseline_violations}
    assessment.hidden_violations = [
        v for v in assessment.reality_violations
        if v.key not in seen and v.key not in unavoidable
    ]

    # erro de controle, setpoint a setpoint
    ideal_by_key = {s.key: s for s in ideal.setpoints}
    deltas: list[dict[str, Any]] = []
    max_err = 0.0
    total_err = 0.0
    for sp in operator.setpoints:
        ref = ideal_by_key.get(sp.key)
        if ref is None:
            continue
        d_p = float(sp.p_mw) - float(ref.p_mw)
        d_q = float(sp.q_mvar) - float(ref.q_mvar)
        max_err = max(max_err, abs(d_p))
        total_err += abs(d_p)
        deltas.append({
            "element": sp.element,
            "index": sp.index,
            "bus": sp.bus,
            "p_dispatched": round(float(sp.p_mw), 6),
            "p_ideal": round(float(ref.p_mw), 6),
            "delta_p_mw": round(d_p, 6),
            "delta_q_mvar": round(d_q, 6),
        })

    assessment.setpoint_deltas = deltas
    assessment.max_setpoint_error_mw = max_err
    assessment.total_setpoint_error_mw = total_err
    return assessment
