"""C1 — Batch de fluxo de potencia ao longo de uma janela temporal.

Reproduz o pipeline que Michel ja usa no laboratorio: itera sobre uma grade
de timestamps, escala cargas por uma `LoadShape` por carga, roda
`pp.runpp` e armazena o estado eletrico completo (tensoes nodais, fluxos
de linha e trafo, injecoes Sbus calculadas via Ybus) em DataFrames "long".

O resultado e o "ground truth" denso usado pela camada de medicoes (C2).
Para o estimador WLS atual, cada timestamp deve ser lido como um snapshot
independente, nao como um estado dinamico acoplado ao timestamp seguinte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd
import pandapower as pp

from .load_shapes import LoadShape, build_default_shape_per_load


@dataclass(frozen=True)
class GroundTruthSchema:
    """Nomes de coluna documentados para os DataFrames de saida."""

    bus_columns: tuple[str, ...] = (
        "timestamp",
        "bus",
        "vm_pu",
        "va_degree",
        "p_inj_mw",
        "q_inj_mvar",
    )
    branch_columns: tuple[str, ...] = (
        "timestamp",
        "branch_kind",
        "branch_id",
        "from_bus",
        "to_bus",
        "p_from_mw",
        "q_from_mvar",
        "p_to_mw",
        "q_to_mvar",
        "i_from_ka",
        "i_to_ka",
    )


@dataclass
class BatchPowerFlowResult:
    """Retorno do batch.

    - `buses` (T*n_bus, 6) — DataFrame `long` com timestamp + tensoes + injecoes.
    - `branches` (T*n_branch, 11) — DataFrame `long` com fluxos de cada ramo.
    - `meta` — dicionario com config (timestep, qtde de timestamps, seed, etc).
    """

    buses: pd.DataFrame
    branches: pd.DataFrame
    meta: dict = field(default_factory=dict)


def _save_load_baseline(net) -> tuple[np.ndarray, np.ndarray]:
    return (
        net.load["p_mw"].to_numpy(dtype=float).copy(),
        net.load["q_mvar"].to_numpy(dtype=float).copy(),
    )


def _apply_load_scaling(net, p0: np.ndarray, q0: np.ndarray, scaling: np.ndarray) -> None:
    net.load.loc[net.load.index, "p_mw"] = p0 * scaling
    net.load.loc[net.load.index, "q_mvar"] = q0 * scaling


def _bus_injections_from_ybus(net) -> pd.Series:
    """Calcula `S_inj = V * conj(Ybus * V)` no ponto operacional atual."""
    ppc = net._ppc
    Ybus = ppc["internal"]["Ybus"]
    V = ppc["internal"]["V"]
    base = float(ppc["baseMVA"])
    S_inj_pu = V * np.conj(np.asarray(Ybus @ V).reshape(-1))
    bus_to_ppc = net._pd2ppc_lookups["bus"]
    p = pd.Series(index=net.bus.index, dtype=float)
    q = pd.Series(index=net.bus.index, dtype=float)
    for bus in net.bus.index:
        ppc_idx = int(bus_to_ppc[bus])
        s = S_inj_pu[ppc_idx] * base
        p.at[bus] = float(np.real(s))
        q.at[bus] = float(np.imag(s))
    return pd.DataFrame({"p_inj_mw": p, "q_inj_mvar": q})


def _line_records(timestamp, net) -> list[dict]:
    if len(net.line) == 0:
        return []
    rec = []
    for line_id in net.line.index:
        if not bool(net.line.at[line_id, "in_service"]):
            continue
        rec.append(
            {
                "timestamp": timestamp,
                "branch_kind": "line",
                "branch_id": int(line_id),
                "from_bus": int(net.line.at[line_id, "from_bus"]),
                "to_bus": int(net.line.at[line_id, "to_bus"]),
                "p_from_mw": float(net.res_line.at[line_id, "p_from_mw"]),
                "q_from_mvar": float(net.res_line.at[line_id, "q_from_mvar"]),
                "p_to_mw": float(net.res_line.at[line_id, "p_to_mw"]),
                "q_to_mvar": float(net.res_line.at[line_id, "q_to_mvar"]),
                "i_from_ka": float(net.res_line.at[line_id, "i_from_ka"]),
                "i_to_ka": float(net.res_line.at[line_id, "i_to_ka"]),
            }
        )
    return rec


def _trafo_records(timestamp, net) -> list[dict]:
    if not hasattr(net, "trafo") or len(net.trafo) == 0:
        return []
    rec = []
    for trafo_id in net.trafo.index:
        if not bool(net.trafo.at[trafo_id, "in_service"]):
            continue
        rec.append(
            {
                "timestamp": timestamp,
                "branch_kind": "trafo",
                "branch_id": int(trafo_id),
                "from_bus": int(net.trafo.at[trafo_id, "hv_bus"]),
                "to_bus": int(net.trafo.at[trafo_id, "lv_bus"]),
                "p_from_mw": float(net.res_trafo.at[trafo_id, "p_hv_mw"]),
                "q_from_mvar": float(net.res_trafo.at[trafo_id, "q_hv_mvar"]),
                "p_to_mw": float(net.res_trafo.at[trafo_id, "p_lv_mw"]),
                "q_to_mvar": float(net.res_trafo.at[trafo_id, "q_lv_mvar"]),
                "i_from_ka": float(net.res_trafo.at[trafo_id, "i_hv_ka"]),
                "i_to_ka": float(net.res_trafo.at[trafo_id, "i_lv_ka"]),
            }
        )
    return rec


def run_batch_powerflow(
    net,
    *,
    start: str = "2026-01-01 00:00:00",
    duration_hours: float = 48.0,
    step_seconds: float = 4.0,
    load_shapes: Iterable[LoadShape] | None = None,
    seed: int = 0,
    progress_every: int = 1000,
) -> BatchPowerFlowResult:
    """Roda fluxo de potencia para cada timestamp da grade temporal.

    O termo `timestamp` aqui e um rotulo operacional da amostra. Ele permite
    organizar muitas rodadas de fluxo de potencia em um unico dataset, mas cada
    rodada continua sendo um snapshot estatico que pode alimentar o WLS
    separadamente.

    Parametros:
        net: rede pandapower (sera modificada in-place a cada passo;
            valores originais de `p_mw`/`q_mvar` sao restaurados no fim).
        start: timestamp inicial em formato ISO.
        duration_hours: duracao total em horas.
        step_seconds: passo temporal (4 s = SCADA mais fino).
        load_shapes: lista de `LoadShape`, uma por carga em ordem
            `net.load.index`. Se None, gera shapes senoidais com seed.
        seed: usado quando `load_shapes` e None.
        progress_every: imprime progresso a cada N passos.

    Retorna:
        `BatchPowerFlowResult` com DataFrames de barras e ramos.
    """

    timestamps = pd.date_range(
        start=start,
        periods=int(round(duration_hours * 3600.0 / step_seconds)),
        freq=pd.Timedelta(seconds=step_seconds),
    )

    if load_shapes is None:
        shapes = build_default_shape_per_load(len(net.load), rng_seed=seed)
    else:
        shapes = list(load_shapes)
    if len(shapes) != len(net.load):
        raise ValueError(
            f"Esperava {len(net.load)} shapes (uma por carga), recebi {len(shapes)}."
        )

    scaling_matrix = np.column_stack(
        [shape.values_at(timestamps) for shape in shapes]
    )  # (T, n_loads)

    p0, q0 = _save_load_baseline(net)
    bus_records: list[pd.DataFrame] = []
    branch_records: list[dict] = []

    try:
        for t_idx, timestamp in enumerate(timestamps):
            _apply_load_scaling(net, p0, q0, scaling_matrix[t_idx])
            pp.runpp(net, calculate_voltage_angles=True, init="results")

            # Bus snapshot
            bus_inj = _bus_injections_from_ybus(net)
            bus_df = pd.DataFrame(
                {
                    "timestamp": timestamp,
                    "bus": net.bus.index,
                    "vm_pu": net.res_bus.vm_pu.to_numpy(),
                    "va_degree": net.res_bus.va_degree.to_numpy(),
                    "p_inj_mw": bus_inj["p_inj_mw"].to_numpy(),
                    "q_inj_mvar": bus_inj["q_inj_mvar"].to_numpy(),
                }
            )
            bus_records.append(bus_df)

            # Branch snapshot
            branch_records.extend(_line_records(timestamp, net))
            branch_records.extend(_trafo_records(timestamp, net))

            if (t_idx + 1) % progress_every == 0 or t_idx + 1 == len(timestamps):
                done = t_idx + 1
                pct = 100.0 * done / len(timestamps)
                print(f"  [{done}/{len(timestamps)}] {pct:.1f}% — t={timestamp}")
    finally:
        _apply_load_scaling(net, p0, q0, np.ones_like(p0))

    buses_df = pd.concat(bus_records, ignore_index=True)
    branches_df = pd.DataFrame(branch_records, columns=GroundTruthSchema().branch_columns)

    meta = {
        "start": str(timestamps[0]),
        "end": str(timestamps[-1]),
        "step_seconds": float(step_seconds),
        "n_timestamps": int(len(timestamps)),
        "n_loads": int(len(net.load)),
        "n_buses": int(len(net.bus)),
        "n_lines": int(len(net.line)),
        "n_trafos": int(len(net.trafo)) if hasattr(net, "trafo") else 0,
        "seed": int(seed),
    }
    return BatchPowerFlowResult(buses=buses_df, branches=branches_df, meta=meta)
