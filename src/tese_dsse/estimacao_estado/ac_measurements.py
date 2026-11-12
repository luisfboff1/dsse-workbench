"""Camada AC para usar o solver WLS em redes pandapower.

Duas formulacoes sao oferecidas:

- `ACPowerMeasurementModel` (v0): construida elemento a elemento (linhas com modelo
  pi). Cobre redes balanceadas, monofasicas equivalentes, sem transformadores.
  Util para didatica e para auditoria passo a passo.

- `ACYbusMeasurementModel` (v1): construida diretamente a partir das matrizes
  `Ybus`, `Yf` e `Yt` que o pandapower calcula em `runpp`. Suporta qualquer rede
  que o pandapower modele em positivo-equilibrado (incluindo trafos com tap,
  shunts, impedancias). Suporta medicoes de tensao, injecao P/Q em barras e
  fluxos P/Q em ramos (linha ou trafo).

A meta destas camadas e fechar o ciclo: pandapower -> medicoes -> h/H -> nosso
solver WLS -> comparacao com pandapower.estimation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
import scipy.sparse as sp

from ..auditoria import AuditTrail
from .gauss_newton_wls import WLSResult, solve_wls_gauss_newton

MeasurementKind = Literal[
    "v_bus",
    "va_bus",
    "p_line",
    "q_line",
    "p_inj",
    "q_inj",
    "p_branch",
    "q_branch",
]
LineSide = Literal["from", "to"]
BranchKind = Literal["line", "trafo"]


@dataclass(frozen=True)
class ACLine:
    """Modelo pi monofasico/balanceado de uma linha em p.u."""

    line_id: int
    from_bus: int
    to_bus: int
    y_series_pu: complex
    y_shunt_pu: complex


@dataclass(frozen=True)
class ACBranch:
    """Ramo (linha ou trafo) ja mapeado para o indice usado em Yf/Yt."""

    branch_id: int
    branch_kind: BranchKind
    ppc_index: int
    from_bus: int
    to_bus: int


@dataclass(frozen=True)
class ACMeasurement:
    """Medicao usada pelo estimador AC.

    Tipos suportados:

    - `v_bus`: magnitude de tensao em uma barra (`element` = id da barra).
    - `va_bus`: angulo de tensao em uma barra, em graus (`element` = id da
      barra). So um PMU sincronizado mede isso diretamente — nos demais
      medidores, theta so existe como saida do estimador, nunca como entrada.
      Suportado apenas por `ACYbusMeasurementModel` (v1).
    - `p_inj`, `q_inj`: injecao ativa/reativa nodal (`element` = id da barra,
      sinal positivo = potencia entrando na barra, convencao pandapower).
    - `p_line`, `q_line`: fluxo em linha (modelo v0, `element` = id da linha,
      `side` obrigatorio).
    - `p_branch`, `q_branch`: fluxo em ramo generico — linha ou trafo (modelo
      v1 baseado em Ybus). `element` = id pandapower, `side` obrigatorio,
      `branch_kind` obrigatorio.
    """

    kind: MeasurementKind
    element: int
    value: float
    sigma: float
    side: LineSide | None = None
    branch_kind: BranchKind | None = None


@dataclass(frozen=True)
class ACStateTable:
    """Estado eletrico estimado em formato tabular."""

    bus: np.ndarray
    vm_pu: np.ndarray
    va_degree: np.ndarray

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "bus": self.bus,
                "vm_pu": self.vm_pu,
                "va_degree": self.va_degree,
            }
        )


class ACPowerMeasurementModel:
    """Modelo de medicoes AC construido a partir de uma rede pandapower."""

    def __init__(
        self,
        *,
        bus_order: list[int],
        slack_bus: int,
        slack_va_degree: float,
        sn_mva: float,
        lines: list[ACLine],
        measurements: list[ACMeasurement],
    ) -> None:
        self.bus_order = list(bus_order)
        self.bus_lookup = {bus: position for position, bus in enumerate(bus_order)}
        self.slack_bus = int(slack_bus)
        self.slack_position = self.bus_lookup[self.slack_bus]
        self.slack_va_rad = float(np.deg2rad(slack_va_degree))
        self.sn_mva = float(sn_mva)
        self.lines = list(lines)
        self.line_lookup = {line.line_id: line for line in lines}
        self.measurements = list(measurements)

        self.angle_buses = [bus for bus in self.bus_order if bus != self.slack_bus]
        self.angle_state_index = {
            bus: index for index, bus in enumerate(self.angle_buses)
        }
        self.vm_state_offset = len(self.angle_buses)

    @property
    def num_buses(self) -> int:
        return len(self.bus_order)

    @property
    def num_states(self) -> int:
        return len(self.angle_buses) + self.num_buses

    @property
    def z(self) -> np.ndarray:
        return np.array(
            [measurement.value for measurement in self.measurements], dtype=float
        )

    @property
    def sigma(self) -> np.ndarray:
        return np.array(
            [measurement.sigma for measurement in self.measurements], dtype=float
        )

    def flat_start(self, vm_pu: float = 1.0) -> np.ndarray:
        """Cria chute inicial: angulos zero e magnitudes iguais a `vm_pu`."""

        angles = np.zeros(len(self.angle_buses), dtype=float)
        magnitudes = np.full(self.num_buses, vm_pu, dtype=float)
        return np.r_[angles, magnitudes]

    def state_from_results(
        self,
        vm_pu: pd.Series,
        va_degree: pd.Series,
    ) -> np.ndarray:
        """Converte resultados pandapower para o vetor de estados interno."""

        angles = [np.deg2rad(float(va_degree.at[bus])) for bus in self.angle_buses]
        magnitudes = [float(vm_pu.at[bus]) for bus in self.bus_order]
        return np.r_[np.array(angles, dtype=float), np.array(magnitudes, dtype=float)]

    def state_to_voltage(self, x: np.ndarray) -> np.ndarray:
        """Converte vetor de estado em fasores complexos de tensao em p.u."""

        x = np.asarray(x, dtype=float).reshape(-1)
        if x.size != self.num_states:
            raise ValueError(f"Estado deve ter tamanho {self.num_states}.")

        va_rad = np.empty(self.num_buses, dtype=float)
        va_rad[self.slack_position] = self.slack_va_rad
        for bus in self.angle_buses:
            va_rad[self.bus_lookup[bus]] = x[self.angle_state_index[bus]]

        vm_pu = x[self.vm_state_offset : self.vm_state_offset + self.num_buses]
        return vm_pu * np.exp(1j * va_rad)

    def state_to_table(self, x: np.ndarray) -> ACStateTable:
        voltage = self.state_to_voltage(x)
        return ACStateTable(
            bus=np.array(self.bus_order, dtype=int),
            vm_pu=np.abs(voltage),
            va_degree=np.rad2deg(np.angle(voltage)),
        )

    def line_power_flows(
        self, voltage: np.ndarray
    ) -> dict[tuple[int, LineSide], complex]:
        """Calcula fluxos complexos de linha em MVA."""

        flows: dict[tuple[int, LineSide], complex] = {}
        for line in self.lines:
            from_pos = self.bus_lookup[line.from_bus]
            to_pos = self.bus_lookup[line.to_bus]
            v_from = voltage[from_pos]
            v_to = voltage[to_pos]

            i_from = (v_from - v_to) * line.y_series_pu + v_from * line.y_shunt_pu / 2.0
            i_to = (v_to - v_from) * line.y_series_pu + v_to * line.y_shunt_pu / 2.0

            flows[(line.line_id, "from")] = self.sn_mva * v_from * np.conj(i_from)
            flows[(line.line_id, "to")] = self.sn_mva * v_to * np.conj(i_to)

        return flows

    def h(self, x: np.ndarray) -> np.ndarray:
        """Funcao de medicao: retorna medicoes previstas para o estado `x`."""

        voltage = self.state_to_voltage(x)
        line_flows = self.line_power_flows(voltage)
        predicted: list[float] = []

        for measurement in self.measurements:
            if measurement.kind == "v_bus":
                bus_pos = self.bus_lookup[measurement.element]
                predicted.append(float(abs(voltage[bus_pos])))
                continue

            if measurement.side is None:
                raise ValueError(
                    "Medicoes de linha precisam de side='from' ou side='to'."
                )

            flow = line_flows[(measurement.element, measurement.side)]
            if measurement.kind == "p_line":
                predicted.append(float(np.real(flow)))
            elif measurement.kind == "q_line":
                predicted.append(float(np.imag(flow)))
            else:
                raise ValueError(f"Tipo de medicao nao suportado: {measurement.kind}")

        return np.array(predicted, dtype=float)

    def jacobian_finite_difference(
        self, x: np.ndarray, step: float = 1e-6
    ) -> np.ndarray:
        """Calcula H(x) por diferencas finitas centrais."""

        x = np.asarray(x, dtype=float).reshape(-1)
        base_size = self.h(x).size
        jacobian = np.zeros((base_size, x.size), dtype=float)

        for column in range(x.size):
            dx = np.zeros_like(x)
            dx[column] = step
            jacobian[:, column] = (self.h(x + dx) - self.h(x - dx)) / (2.0 * step)

        return jacobian

    def solve(
        self,
        x0: np.ndarray | None = None,
        *,
        max_iter: int = 20,
        tol: float = 1e-8,
        verbose: bool = False,
        audit: AuditTrail | None = None,
    ) -> WLSResult:
        """Resolve o problema AC WLS usando o solver generico.

        Com ``verbose=True`` (ou uma trilha ``audit``), o solver registra cada
        iteracao do Gauss-Newton para auditoria.
        """

        if x0 is None:
            x0 = self.flat_start()
        return solve_wls_gauss_newton(
            z=self.z,
            sigma=self.sigma,
            h=self.h,
            jacobian=self.jacobian_finite_difference,
            x0=x0,
            max_iter=max_iter,
            tol=tol,
            verbose=verbose,
            audit=audit,
        )


def _line_to_ac_model(net, line_id: int, bus_lookup: dict[int, int]) -> ACLine:
    row = net.line.loc[line_id]
    from_bus = int(row.from_bus)
    to_bus = int(row.to_bus)

    if from_bus not in bus_lookup or to_bus not in bus_lookup:
        raise ValueError(f"Linha {line_id} referencia barra inexistente.")

    vn_from = float(net.bus.at[from_bus, "vn_kv"])
    vn_to = float(net.bus.at[to_bus, "vn_kv"])
    if not np.isclose(vn_from, vn_to, rtol=0.0, atol=1e-9):
        raise ValueError(
            "Esta versao inicial suporta apenas linhas cujas barras terminais "
            f"tem a mesma tensao base. Linha {line_id}: {vn_from} kV vs {vn_to} kV."
        )

    sn_mva = float(net.sn_mva)
    z_base_ohm = vn_from**2 / sn_mva
    frequency_hz = float(getattr(net, "f_hz", 50.0))
    length_km = float(row.length_km)
    parallel = (
        float(row.parallel) if "parallel" in row and not pd.isna(row.parallel) else 1.0
    )

    z_ohm = complex(
        float(row.r_ohm_per_km) * length_km / parallel,
        float(row.x_ohm_per_km) * length_km / parallel,
    )
    y_series_pu = z_base_ohm / z_ohm

    c_nf_per_km = (
        float(row.c_nf_per_km)
        if "c_nf_per_km" in row and not pd.isna(row.c_nf_per_km)
        else 0.0
    )
    g_us_per_km = (
        float(row.g_us_per_km)
        if "g_us_per_km" in row and not pd.isna(row.g_us_per_km)
        else 0.0
    )
    c_f = c_nf_per_km * 1e-9 * length_km * parallel
    g_siemens = g_us_per_km * 1e-6 * length_km * parallel
    y_shunt_si = complex(g_siemens, 2.0 * np.pi * frequency_hz * c_f)
    y_shunt_pu = y_shunt_si * z_base_ohm

    return ACLine(
        line_id=int(line_id),
        from_bus=from_bus,
        to_bus=to_bus,
        y_series_pu=y_series_pu,
        y_shunt_pu=y_shunt_pu,
    )


def build_ac_model_from_pandapower(
    net,
    measurements: list[ACMeasurement],
) -> ACPowerMeasurementModel:
    """Constroi modelo AC a partir de uma rede pandapower.

    Limitacao atual: a rede nao deve ter transformadores em servico. Isso deixa
    a primeira validacao clara e evita esconder taps/defasagens em uma versao
    ainda introdutoria.
    """

    if len(net.ext_grid) == 0:
        raise ValueError(
            "A rede precisa ter pelo menos uma barra slack em net.ext_grid."
        )
    if len(net.ext_grid) > 1:
        raise ValueError("Esta versao inicial suporta apenas uma barra slack.")

    if hasattr(net, "trafo") and len(net.trafo) > 0:
        in_service_trafo = net.trafo[net.trafo.in_service.astype(bool)]
        if len(in_service_trafo) > 0:
            raise ValueError("Esta versao inicial ainda nao suporta transformadores.")

    bus_order = [int(bus) for bus in net.bus.index]
    bus_lookup = {bus: position for position, bus in enumerate(bus_order)}
    slack_bus = int(net.ext_grid.bus.iloc[0])
    slack_va_degree = (
        float(net.ext_grid.va_degree.iloc[0]) if "va_degree" in net.ext_grid else 0.0
    )

    lines = [
        _line_to_ac_model(net, int(line_id), bus_lookup)
        for line_id, row in net.line.iterrows()
        if bool(row.in_service)
    ]

    return ACPowerMeasurementModel(
        bus_order=bus_order,
        slack_bus=slack_bus,
        slack_va_degree=slack_va_degree,
        sn_mva=float(net.sn_mva),
        lines=lines,
        measurements=measurements,
    )


def synthetic_line_measurements_from_results(
    net,
    *,
    voltage_sigma_pu: float = 0.002,
    power_sigma_mva_min: float = 0.01,
    power_sigma_relative: float = 0.01,
) -> list[ACMeasurement]:
    """Cria medicoes sinteticas a partir de `net.res_bus` e `net.res_line`.

    As unidades sao:

    - tensao: p.u.;
    - potencia ativa: MW;
    - potencia reativa: MVAr.
    """

    measurements: list[ACMeasurement] = []

    for bus in net.bus.index:
        measurements.append(
            ACMeasurement(
                kind="v_bus",
                element=int(bus),
                value=float(net.res_bus.vm_pu.at[bus]),
                sigma=voltage_sigma_pu,
            )
        )

    for line in net.line.index:
        for side in ("from", "to"):
            p_value = float(net.res_line.at[line, f"p_{side}_mw"])
            q_value = float(net.res_line.at[line, f"q_{side}_mvar"])
            measurements.append(
                ACMeasurement(
                    kind="p_line",
                    element=int(line),
                    side=side,  # type: ignore[arg-type]
                    value=p_value,
                    sigma=max(power_sigma_mva_min, abs(p_value) * power_sigma_relative),
                )
            )
            measurements.append(
                ACMeasurement(
                    kind="q_line",
                    element=int(line),
                    side=side,  # type: ignore[arg-type]
                    value=q_value,
                    sigma=max(power_sigma_mva_min, abs(q_value) * power_sigma_relative),
                )
            )

    return measurements


# ---------------------------------------------------------------------------
# v1: modelo AC baseado em Ybus do pandapower (suporta trafos, taps, shunts)
# ---------------------------------------------------------------------------


class ACYbusMeasurementModel:
    """Estimador AC baseado nas matrizes `Ybus`, `Yf`, `Yt`.

    O estado e o classico
    `x = [theta_i para i != slack ; vm_i para todas as barras]`. `solve` usa a
    Jacobiana analitica (`jacobian`), que cai em diferencas finitas para
    qualquer grupo de medicao sem derivada escrita -- ver decisao em
    `docs/governanca/decisoes_tecnicas.md` (desempenho em redes grandes).
    """

    def __init__(
        self,
        *,
        bus_order: list[int],
        slack_bus: int,
        slack_va_degree: float,
        sn_mva: float,
        Ybus,
        Yf,
        Yt,
        branches: list[ACBranch],
        measurements: list[ACMeasurement],
    ) -> None:
        self.bus_order = list(bus_order)
        self.bus_lookup = {bus: position for position, bus in enumerate(bus_order)}
        self.slack_bus = int(slack_bus)
        self.slack_position = self.bus_lookup[self.slack_bus]
        self.slack_va_rad = float(np.deg2rad(slack_va_degree))
        self.sn_mva = float(sn_mva)
        self.num_buses = len(self.bus_order)
        self.Ybus = Ybus
        self.Yf = Yf
        self.Yt = Yt
        self.branches = list(branches)
        self.branch_lookup = {
            (branch.branch_kind, branch.branch_id): branch for branch in branches
        }
        self.measurements = list(measurements)

        self.angle_buses = [bus for bus in self.bus_order if bus != self.slack_bus]
        self.angle_state_index = {
            bus: index for index, bus in enumerate(self.angle_buses)
        }
        self.vm_state_offset = len(self.angle_buses)

        # Indices pre-calculados: h(x) e H(x) viram operacoes vetoriais em vez
        # de um laco Python por medicao (antes, `branches.index` por medicao
        # deixava h em O(m * n_ramos)).
        self._from_idx = np.array(
            [self.bus_lookup[b.from_bus] for b in self.branches], dtype=int
        )
        self._to_idx = np.array(
            [self.bus_lookup[b.to_bus] for b in self.branches], dtype=int
        )
        branch_position = {
            (b.branch_kind, b.branch_id): i for i, b in enumerate(self.branches)
        }
        self._groups: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        rows: dict[str, list[int]] = {}
        positions: dict[str, list[int]] = {}
        for row, m in enumerate(self.measurements):
            if m.kind in ("v_bus", "va_bus", "p_inj", "q_inj"):
                group, position = m.kind, self.bus_lookup[m.element]
            elif m.kind in ("p_branch", "q_branch"):
                if m.side is None or m.branch_kind is None:
                    raise ValueError(
                        "p_branch/q_branch precisam de `side` e `branch_kind`."
                    )
                group = f"{m.kind}_{m.side}"
                position = branch_position[(m.branch_kind, m.element)]
            else:
                raise ValueError(
                    f"ACYbusMeasurementModel nao suporta o tipo de medicao {m.kind!r}."
                )
            rows.setdefault(group, []).append(row)
            positions.setdefault(group, []).append(position)
        for group in rows:
            self._groups[group] = (
                np.array(rows[group], dtype=int),
                np.array(positions[group], dtype=int),
            )

    @property
    def num_states(self) -> int:
        return len(self.angle_buses) + self.num_buses

    @property
    def z(self) -> np.ndarray:
        return np.array([m.value for m in self.measurements], dtype=float)

    @property
    def sigma(self) -> np.ndarray:
        return np.array([m.sigma for m in self.measurements], dtype=float)

    def flat_start(self, vm_pu: float = 1.0) -> np.ndarray:
        angles = np.zeros(len(self.angle_buses), dtype=float)
        magnitudes = np.full(self.num_buses, vm_pu, dtype=float)
        return np.r_[angles, magnitudes]

    def state_from_results(self, vm_pu, va_degree) -> np.ndarray:
        angles = [np.deg2rad(float(va_degree.at[bus])) for bus in self.angle_buses]
        magnitudes = [float(vm_pu.at[bus]) for bus in self.bus_order]
        return np.r_[np.array(angles, dtype=float), np.array(magnitudes, dtype=float)]

    def state_to_voltage(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=float).reshape(-1)
        if x.size != self.num_states:
            raise ValueError(f"Estado deve ter tamanho {self.num_states}.")
        va_rad = np.empty(self.num_buses, dtype=float)
        va_rad[self.slack_position] = self.slack_va_rad
        for bus in self.angle_buses:
            va_rad[self.bus_lookup[bus]] = x[self.angle_state_index[bus]]
        vm_pu = x[self.vm_state_offset : self.vm_state_offset + self.num_buses]
        return vm_pu * np.exp(1j * va_rad)

    def state_to_table(self, x: np.ndarray) -> ACStateTable:
        voltage = self.state_to_voltage(x)
        return ACStateTable(
            bus=np.array(self.bus_order, dtype=int),
            vm_pu=np.abs(voltage),
            va_degree=np.rad2deg(np.angle(voltage)),
        )

    def _powers(self, x: np.ndarray):
        """Retorna (S_inj_pu, S_from_pu, S_to_pu) para o estado `x`.

        Convencoes pandapower/PYPOWER:
        - injecao S_i positivo = potencia saindo da barra para a rede;
        - fluxo from/to positivo = potencia saindo da barra do respectivo lado.
        """
        V = self.state_to_voltage(x)
        Ibus = np.asarray(self.Ybus @ V).reshape(-1)
        S_inj = V * np.conj(Ibus)
        If = np.asarray(self.Yf @ V).reshape(-1)
        It = np.asarray(self.Yt @ V).reshape(-1)
        S_from = V[self._from_idx] * np.conj(If) if len(self.branches) else np.array([])
        S_to = V[self._to_idx] * np.conj(It) if len(self.branches) else np.array([])
        return V, S_inj, S_from, S_to

    def h(self, x: np.ndarray) -> np.ndarray:
        V, S_inj, S_from, S_to = self._powers(x)
        predicted = np.empty(len(self.measurements), dtype=float)
        values = {
            "v_bus": lambda p: np.abs(V[p]),
            "va_bus": lambda p: np.rad2deg(np.angle(V[p])),
            "p_inj": lambda p: np.real(S_inj[p]) * self.sn_mva,
            "q_inj": lambda p: np.imag(S_inj[p]) * self.sn_mva,
            "p_branch_from": lambda p: np.real(S_from[p]) * self.sn_mva,
            "q_branch_from": lambda p: np.imag(S_from[p]) * self.sn_mva,
            "p_branch_to": lambda p: np.real(S_to[p]) * self.sn_mva,
            "q_branch_to": lambda p: np.imag(S_to[p]) * self.sn_mva,
        }
        for group, (rows, positions) in self._groups.items():
            predicted[rows] = values[group](positions)
        return predicted

    def jacobian(self, x: np.ndarray, sparse: bool = False):
        """H(x) analitica (derivadas polares de MATPOWER `dSbus_dV`/`dSbr_dV`).

        Com ``sparse=True`` devolve ``scipy.sparse.csr_matrix`` (usado pelo
        `solve`); o padrao e ``ndarray`` denso, que e o que as rotinas de bad
        data esperam.

        Grupos de medicao sem derivada escrita aqui caem automaticamente em
        `jacobian_finite_difference` (so nas linhas deles), entao um tipo novo
        de medicao so precisa de `h(x)` para funcionar -- a derivada analitica
        e otimizacao, nao requisito. `tests/test_ac_jacobian_analytic.py`
        confere analitica x diferencas finitas.
        """
        derivs = self._analytic_derivs(x)
        angle_cols = np.delete(np.arange(self.num_buses), self.slack_position)
        blocks, block_rows, fallback_rows = [], [], []
        for group, (rows, positions) in self._groups.items():
            if group not in derivs:
                fallback_rows.append(rows)
                continue
            dVa, dVm = derivs[group]
            blocks.append(
                sp.hstack(
                    [
                        sp.csr_matrix(dVa)[positions][:, angle_cols],
                        sp.csr_matrix(dVm)[positions],
                    ]
                )
            )
            block_rows.append(rows)
        if fallback_rows:
            rows = np.concatenate(fallback_rows)
            blocks.append(sp.csr_matrix(self.jacobian_finite_difference(x)[rows]))
            block_rows.append(rows)
        if not blocks:
            H = sp.csr_matrix((0, self.num_states))
        else:
            order = np.concatenate(block_rows)
            inverse = np.empty_like(order)
            inverse[order] = np.arange(order.size)
            H = sp.vstack(blocks).tocsr()[inverse]
        return H if sparse else H.toarray()

    def _analytic_derivs(self, x: np.ndarray) -> dict:
        """``{grupo: (dh/dVa, dh/dVm)}`` por barra (nb colunas), unidades de h.

        Ponto de extensao: um grupo de medicao novo ganha derivada analitica
        adicionando uma entrada aqui; sem ela, `jacobian` usa diferencas
        finitas nas linhas desse grupo.
        """
        V = self.state_to_voltage(x)
        nb = self.num_buses
        Vnorm = V / np.abs(V)
        dV, dVn = sp.diags(V), sp.diags(Vnorm)
        Ibus = self.Ybus @ V
        dS_dVm = dV @ (self.Ybus @ dVn).conj() + sp.diags(np.conj(Ibus)) @ dVn
        dS_dVa = 1j * dV @ (sp.diags(Ibus) - self.Ybus @ dV).conj()

        branch_derivs = {}
        nbr = len(self.branches)
        for side, Ybr, idx in (
            ("from", self.Yf, self._from_idx),
            ("to", self.Yt, self._to_idx),
        ):
            if not nbr:
                break
            Ybr = sp.csr_matrix(Ybr)
            C = sp.csr_matrix((np.ones(nbr), (np.arange(nbr), idx)), shape=(nbr, nb))
            Ibr = Ybr @ V
            dIbr_c, dVbr = sp.diags(np.conj(Ibr)), sp.diags(V[idx])
            branch_derivs[side] = (
                dVbr @ (Ybr @ dVn).conj() + dIbr_c @ C @ dVn,  # dS/dVm
                1j * (dIbr_c @ C @ dV - dVbr @ (Ybr @ dV).conj()),  # dS/dVa
            )

        eye = sp.identity(nb, format="csr")
        zero = sp.csr_matrix((nb, nb))
        # (dh/dVa, dh/dVm) por grupo, nas unidades de h (graus, MW, MVAr).
        derivs = {
            "v_bus": (zero, eye),
            "va_bus": (eye * np.rad2deg(1.0), zero),
            "p_inj": (dS_dVa.real * self.sn_mva, dS_dVm.real * self.sn_mva),
            "q_inj": (dS_dVa.imag * self.sn_mva, dS_dVm.imag * self.sn_mva),
        }
        for side, (dVm, dVa) in branch_derivs.items():
            derivs[f"p_branch_{side}"] = (dVa.real * self.sn_mva, dVm.real * self.sn_mva)
            derivs[f"q_branch_{side}"] = (dVa.imag * self.sn_mva, dVm.imag * self.sn_mva)
        return derivs

    def jacobian_finite_difference(
        self, x: np.ndarray, step: float = 1e-6
    ) -> np.ndarray:
        x = np.asarray(x, dtype=float).reshape(-1)
        base_size = self.h(x).size
        jacobian = np.zeros((base_size, x.size), dtype=float)
        for column in range(x.size):
            dx = np.zeros_like(x)
            dx[column] = step
            jacobian[:, column] = (self.h(x + dx) - self.h(x - dx)) / (2.0 * step)
        return jacobian

    def solve(
        self,
        x0: np.ndarray | None = None,
        *,
        max_iter: int = 30,
        tol: float = 1e-8,
        verbose: bool = False,
        audit: AuditTrail | None = None,
    ) -> WLSResult:
        if x0 is None:
            x0 = self.flat_start()
        return solve_wls_gauss_newton(
            z=self.z,
            sigma=self.sigma,
            h=self.h,
            jacobian=lambda x: self.jacobian(x, sparse=True),
            x0=x0,
            max_iter=max_iter,
            tol=tol,
            verbose=verbose,
            audit=audit,
        )


def build_ac_ybus_model_from_pandapower(
    net,
    measurements: list[ACMeasurement],
) -> ACYbusMeasurementModel:
    """Constroi o modelo AC v1 (baseado em Ybus) a partir de uma rede pandapower
    que ja foi resolvida (i.e. `pp.runpp(net)` precisa ter sido chamado antes).
    """

    ppc = getattr(net, "_ppc", None)
    if ppc is None or "internal" not in ppc or "Ybus" not in ppc["internal"]:
        raise ValueError(
            "Rede ainda nao foi resolvida. Rode `pp.runpp(net)` antes de "
            "construir o modelo AC v1."
        )

    if len(net.ext_grid) == 0:
        raise ValueError("A rede precisa ter pelo menos uma ext_grid.")
    if len(net.ext_grid) > 1:
        raise ValueError("Esta versao suporta apenas uma barra slack.")

    branch_lookup = net._pd2ppc_lookups.get("branch", {}) or {}

    bus_order = [int(bus) for bus in net.bus.index]
    slack_bus = int(net.ext_grid.bus.iloc[0])
    slack_va_degree = (
        float(net.ext_grid.va_degree.iloc[0]) if "va_degree" in net.ext_grid else 0.0
    )

    branches: list[ACBranch] = []

    line_range = branch_lookup.get("line")
    if line_range is not None:
        start, _ = line_range
        in_service_lines = [
            int(line_id) for line_id, row in net.line.iterrows() if bool(row.in_service)
        ]
        for offset, line_id in enumerate(in_service_lines):
            row = net.line.loc[line_id]
            branches.append(
                ACBranch(
                    branch_id=line_id,
                    branch_kind="line",
                    ppc_index=int(start) + offset,
                    from_bus=int(row.from_bus),
                    to_bus=int(row.to_bus),
                )
            )

    trafo_range = branch_lookup.get("trafo")
    if trafo_range is not None:
        start, _ = trafo_range
        # `ppc["internal"]` so tem os ramos EM SERVICO, mas o lookup conta
        # todas as linhas: cada linha fora de servico antes dos trafos desloca
        # o inicio deles uma posicao para tras (sem isso, case14 com uma
        # linha aberta estoura o indice do ultimo trafo).
        if line_range is not None:
            start = int(start) - int((~net.line.in_service.astype(bool)).sum())
        in_service_trafos = [
            int(trafo_id)
            for trafo_id, row in net.trafo.iterrows()
            if bool(row.in_service)
        ]
        for offset, trafo_id in enumerate(in_service_trafos):
            row = net.trafo.loc[trafo_id]
            branches.append(
                ACBranch(
                    branch_id=trafo_id,
                    branch_kind="trafo",
                    ppc_index=int(start) + offset,
                    from_bus=int(row.hv_bus),
                    to_bus=int(row.lv_bus),
                )
            )

    branches.sort(key=lambda b: b.ppc_index)

    Ybus = ppc["internal"]["Ybus"]
    Yf_full = ppc["internal"]["Yf"]
    Yt_full = ppc["internal"]["Yt"]

    indices = np.array([b.ppc_index for b in branches], dtype=int)
    Yf = Yf_full[indices, :] if indices.size else Yf_full[:0, :]
    Yt = Yt_full[indices, :] if indices.size else Yt_full[:0, :]

    branches = [
        ACBranch(
            branch_id=b.branch_id,
            branch_kind=b.branch_kind,
            ppc_index=position,
            from_bus=b.from_bus,
            to_bus=b.to_bus,
        )
        for position, b in enumerate(branches)
    ]

    return ACYbusMeasurementModel(
        bus_order=bus_order,
        slack_bus=slack_bus,
        slack_va_degree=slack_va_degree,
        sn_mva=float(ppc["baseMVA"]),
        Ybus=Ybus,
        Yf=Yf,
        Yt=Yt,
        branches=branches,
        measurements=measurements,
    )


def network_power_scale(net) -> float:
    """|S| tipica da rede (MVA): mediana dos |S| de operacao de todas as
    injecoes e de todas as pontas de linha/trafo em servico. Base do piso de
    leitura quase nula (`sensor_calibration.meter_full_scale`). Depende so do
    ponto de operacao, nunca de `sn_mva`. Exige `pp.runpp(net)` antes."""

    from .sensor_calibration import typical_power_scale

    vals: list[float] = []
    ppc = getattr(net, "_ppc", None)
    if ppc is not None and "internal" in ppc and "Ybus" in ppc["internal"]:
        Ybus, V = ppc["internal"]["Ybus"], ppc["internal"]["V"]
        S = (V * np.conj(np.asarray(Ybus @ V).reshape(-1))) * float(ppc["baseMVA"])
        vals += list(np.abs(S))
    ln = net.res_line[net.line.in_service.astype(bool).reindex(net.res_line.index, fill_value=False)]
    for side in ("from", "to"):
        vals += list(np.hypot(ln[f"p_{side}_mw"], ln[f"q_{side}_mvar"]))
    if hasattr(net, "trafo") and len(net.trafo):
        tr = net.res_trafo[net.trafo.in_service.astype(bool).reindex(net.res_trafo.index, fill_value=False)]
        for side in ("hv", "lv"):
            vals += list(np.hypot(tr[f"p_{side}_mw"], tr[f"q_{side}_mvar"]))
    return typical_power_scale([v for v in vals if np.isfinite(v)])


def _pair_magnitudes(pq: list) -> list[float]:
    """|S| do medidor de cada medida P/Q: hypot do par (P, Q) do mesmo ponto
    (mesma barra, ou mesmo ramo e lado). Sem o par, |valor|."""

    val = {}
    for m in pq:
        val[(m.kind[0], m.kind[1:], m.element, m.side, m.branch_kind)] = m.value
    out = []
    for m in pq:
        other = ("q" if m.kind[0] == "p" else "p", m.kind[1:], m.element, m.side, m.branch_kind)
        out.append(float(np.hypot(m.value, val.get(other, 0.0))))
    return out


def bus_throughput(net) -> dict[int, float]:
    """{barra: maior |S| (MVA) entre as pontas de linha/trafo em servico
    ligadas a ela}. Fundo de escala do medidor de injecao numa barra de
    passagem (`sensor_calibration.meter_full_scale`)."""

    out: dict[int, float] = {int(b): 0.0 for b in net.bus.index}

    def _acc(bus, s):
        b = int(bus)
        if np.isfinite(s) and s > out.get(b, 0.0):
            out[b] = float(s)

    for l, row in net.line.iterrows():
        if not bool(row.in_service) or l not in net.res_line.index:
            continue
        r = net.res_line.loc[l]
        _acc(row.from_bus, np.hypot(r.p_from_mw, r.q_from_mvar))
        _acc(row.to_bus, np.hypot(r.p_to_mw, r.q_to_mvar))
    if hasattr(net, "trafo"):
        for t, row in net.trafo.iterrows():
            if not bool(row.in_service) or t not in net.res_trafo.index:
                continue
            r = net.res_trafo.loc[t]
            _acc(row.hv_bus, np.hypot(r.p_hv_mw, r.q_hv_mvar))
            _acc(row.lv_bus, np.hypot(r.p_lv_mw, r.q_lv_mvar))
    return out


def synthetic_full_measurements_from_results(
    net,
    *,
    voltage_sigma_pu: float = 0.002,
    power_sigma_mva_min: float = 0.01,
    power_sigma_relative: float = 0.01,
    include_injections: bool = True,
    include_branch_flows: bool = True,
    kind: str | None = None,
    noise_level: float | None = None,
    sigma_min: float | None = None,
) -> list[ACMeasurement]:
    """Cria medicoes sinteticas para o modelo v1 (Ybus).

    Inclui tensoes em todas as barras e (opcionalmente) injecoes nodais P/Q
    e fluxos P/Q em todos os ramos (linhas e trafos) em servico.

    Por padrao, o sigma vem dos parametros `voltage_sigma_pu`/
    `power_sigma_mva_min`/`power_sigma_relative` (constantes ad-hoc, uma
    por notebook). Se `kind` for informado (junto de `noise_level` e
    `sigma_min`), o sigma passa a vir da calibracao **compartilhada** em
    `sensor_calibration.py` — a mesma usada por
    `app/backend/services/measurement_kinds.py` — para que notebook e app
    rodem com exatamente o mesmo modelo de ruido/peso no mesmo caso (ver
    `temas/revisao_bibliografica/literatura/bretas2017_malicious_data_innovation.md`).
    """

    measurements: list[ACMeasurement] = []

    if kind is not None:
        if noise_level is None or sigma_min is None:
            raise ValueError("kind requer noise_level e sigma_min também.")
        from .sensor_calibration import (
            meter_full_scale as _fs,
            p_sigma as _p_sigma,
            relative_sigma as _rel,
            v_sigma as _v_sigma,
        )

        # Piso por medidor: fundo de escala = 2|S| do ponto medido (o par
        # P, Q da mesma barra/ponta), nunca `sn_mva` (11/11/2026).
        s_typ = network_power_scale(net)
        s_bus = bus_throughput(net)
        rel_power = _rel(kind, noise_level)  # type: ignore[arg-type]

        def power_sigma(value: float, p: float, q: float, s_local: float = 0.0) -> float:
            return _p_sigma(kind, value, noise_level, sigma_min, full_scale=_fs(p, q, s_typ, s_local))  # type: ignore[arg-type]

        voltage_sigma_pu = _v_sigma(kind, noise_level, sigma_min)  # type: ignore[arg-type]
    else:
        rel_power = power_sigma_relative

        s_bus = {}

        def power_sigma(value: float, p: float, q: float, s_local: float = 0.0) -> float:
            return max(power_sigma_mva_min, abs(value) * power_sigma_relative)

    for bus in net.bus.index:
        measurements.append(
            ACMeasurement(
                kind="v_bus",
                element=int(bus),
                value=float(net.res_bus.vm_pu.at[bus]),
                sigma=voltage_sigma_pu,
            )
        )

    if include_injections:
        # Convencao: p_inj/q_inj = injecao NET do no NA rede (positivo = gerador).
        # Calculamos via S_inj = V * conj(Ybus * V) para incluir shunts/trafos
        # corretamente — `res_bus.p_mw`/`q_mvar` nao inclui shunt isolado e por
        # isso geraria viés em redes com elementos shunt em barra.
        ppc = getattr(net, "_ppc", None)
        if ppc is not None and "internal" in ppc and "Ybus" in ppc["internal"]:
            Ybus = ppc["internal"]["Ybus"]
            V = ppc["internal"]["V"]
            base_mva = float(ppc["baseMVA"])
            S_inj = (V * np.conj(np.asarray(Ybus @ V).reshape(-1))) * base_mva
            bus_to_ppc = net._pd2ppc_lookups["bus"]
            for bus in net.bus.index:
                ppc_index = int(bus_to_ppc[bus])
                p_value = float(np.real(S_inj[ppc_index]))
                q_value = float(np.imag(S_inj[ppc_index]))
                measurements.append(
                    ACMeasurement(
                        kind="p_inj",
                        element=int(bus),
                        value=p_value,
                        sigma=power_sigma(p_value, p_value, q_value, s_bus.get(int(bus), 0.0)),
                    )
                )
                measurements.append(
                    ACMeasurement(
                        kind="q_inj",
                        element=int(bus),
                        value=q_value,
                        sigma=power_sigma(q_value, p_value, q_value, s_bus.get(int(bus), 0.0)),
                    )
                )
        else:
            raise ValueError(
                "Para gerar medicoes de injecao via Ybus, rode `pp.runpp(net)` antes."
            )

    if include_branch_flows:
        for line in net.line.index:
            if not bool(net.line.at[line, "in_service"]):
                continue
            for side in ("from", "to"):
                p_value = float(net.res_line.at[line, f"p_{side}_mw"])
                q_value = float(net.res_line.at[line, f"q_{side}_mvar"])
                measurements.append(
                    ACMeasurement(
                        kind="p_branch",
                        element=int(line),
                        side=side,  # type: ignore[arg-type]
                        branch_kind="line",
                        value=p_value,
                        sigma=power_sigma(p_value, p_value, q_value),
                    )
                )
                measurements.append(
                    ACMeasurement(
                        kind="q_branch",
                        element=int(line),
                        side=side,  # type: ignore[arg-type]
                        branch_kind="line",
                        value=q_value,
                        sigma=power_sigma(q_value, p_value, q_value),
                    )
                )

        if hasattr(net, "trafo") and len(net.trafo) > 0:
            for trafo in net.trafo.index:
                if not bool(net.trafo.at[trafo, "in_service"]):
                    continue
                for side in ("hv", "lv"):
                    p_value = float(net.res_trafo.at[trafo, f"p_{side}_mw"])
                    q_value = float(net.res_trafo.at[trafo, f"q_{side}_mvar"])
                    branch_side: LineSide = "from" if side == "hv" else "to"
                    measurements.append(
                        ACMeasurement(
                            kind="p_branch",
                            element=int(trafo),
                            side=branch_side,
                            branch_kind="trafo",
                            value=p_value,
                            sigma=power_sigma(p_value, p_value, q_value),
                        )
                    )
                    measurements.append(
                        ACMeasurement(
                            kind="q_branch",
                            element=int(trafo),
                            side=branch_side,
                            branch_kind="trafo",
                            value=q_value,
                            sigma=power_sigma(q_value, p_value, q_value),
                        )
                    )

    from .sensor_calibration import audit_power_sigmas

    pq = [m for m in measurements if m.kind in ("p_inj", "q_inj", "p_branch", "q_branch")]
    audit_power_sigmas(
        [m.value for m in pq], [m.sigma for m in pq], [rel_power] * len(pq),
        [f"{m.kind}:{m.element}{':' + m.side if m.side else ''}" for m in pq],
        magnitudes=_pair_magnitudes(pq), context="synthetic_full_measurements_from_results: ",
    )
    return measurements
