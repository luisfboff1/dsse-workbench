"""Perfis temporais de carga para o batch de fluxo de potencia.

Tres provedores estao disponiveis:

- `SinusoidalDailyShape`: senoide com pico no inicio da noite + ruido gaussiano.
  Reprodutivel via seed, totalmente sintetico, util para testes rapidos.
- `SimbenchShapeProvider`: usa perfis publicados pela base de dados SimBench
  (Meinecke et al., 2020 — IEEE Xplore 9211002). Mais realistas, com
  sazonalidade dia/semana/estacao. Requer `simbench` instalado.
- `LoadShape` (interface): qualquer callable `(timestamps) -> array de scaling`.

A `scaling` retornada e um multiplicador adimensional aplicado a `p_mw` e
`q_mvar` da carga. Tipico: 0.5 (mínimo) a 1.2 (pico).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd


class LoadShape(ABC):
    """Interface comum: dado um vetor de timestamps, retorna multiplicadores."""

    @abstractmethod
    def values_at(self, timestamps: pd.DatetimeIndex) -> np.ndarray:
        """Retorna array (T,) de scaling factors."""


@dataclass
class SinusoidalDailyShape(LoadShape):
    """Senoide com pico em `peak_hour`, ruido gaussiano.

    Modelo simples: `1.0 + amplitude * cos(2*pi*(hour - peak_hour)/24) + N(0, noise_std)`.
    Pico tipico em 19h. amplitude=0.3 -> 0.7..1.3 sem ruido.
    """

    amplitude: float = 0.3
    peak_hour: float = 19.0
    noise_std: float = 0.02
    seed: int = 0

    def values_at(self, timestamps: pd.DatetimeIndex) -> np.ndarray:
        ts = pd.DatetimeIndex(timestamps)
        hours = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
        cyclic = np.cos(2.0 * np.pi * (hours - self.peak_hour) / 24.0)
        rng = np.random.default_rng(self.seed)
        noise = rng.normal(0.0, self.noise_std, size=ts.size)
        return 1.0 + self.amplitude * cyclic + noise


@dataclass
class SimbenchShapeProvider:
    """Carrega perfis SimBench via `simbench.get_simbench_net`.

    SimBench publica perfis sazonais por tipo de carga (residential,
    commercial, industrial...) com resolucao 15 min. Aqui interpolamos para
    a granularidade desejada.

    Reference: Meinecke et al., "SimBench - A Benchmark Dataset of
    Electric Power Systems to Compare Innovative Solutions Based on Power
    Flow Analysis", IEEE Access, 2020.

    Esta classe e leve: apenas mantem um DataFrame de perfis indexado por
    tipo. Para cargas sem tipo correspondente cai para `fallback_shape`.
    """

    profile_table: pd.DataFrame  # index: timestamp; columns: profile_id
    profile_by_load_type: dict[str, str]
    fallback_shape: LoadShape

    @classmethod
    def from_simbench_code(
        cls,
        code: str = "1-LV-rural1--0-sw",
        fallback: LoadShape | None = None,
    ) -> "SimbenchShapeProvider":
        try:
            import simbench as sb  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "simbench nao esta instalado. Use SinusoidalDailyShape "
                "ou rode `pip install simbench`."
            ) from exc

        profiles = sb.get_absolute_values(
            sb.get_simbench_net(code), profiles_instead_of_study_cases=True
        )
        # `profiles` is a dict of DataFrames keyed by element type/column.
        # We use only the active power load profiles.
        load_p = profiles.get(("load", "p_mw"))
        if load_p is None or load_p.empty:
            raise RuntimeError(
                f"SimBench code {code} nao retornou perfis de load.p_mw"
            )

        if fallback is None:
            fallback = SinusoidalDailyShape()

        # Each column of load_p corresponds to a load index.  We turn the
        # absolute values into a normalized multiplier per column.
        normalised = load_p / load_p.mean(axis=0).replace(0.0, np.nan)
        normalised = normalised.fillna(1.0)

        return cls(
            profile_table=normalised,
            profile_by_load_type={},
            fallback_shape=fallback,
        )

    def shape_for_column(self, column: int | str) -> LoadShape:
        if column not in self.profile_table.columns:
            return self.fallback_shape
        series = self.profile_table[column]
        return _PrecomputedShape(series)


@dataclass
class _PrecomputedShape(LoadShape):
    """Helper interno: reamostra uma serie pre-computada para a grade pedida."""

    series: pd.Series

    def values_at(self, timestamps: pd.DatetimeIndex) -> np.ndarray:
        ts = pd.DatetimeIndex(timestamps)
        # Map our timestamps back to the SimBench domain by aligning the
        # time-of-week (SimBench profiles have weekly seasonality at 15 min).
        src = self.series.copy()
        if not isinstance(src.index, pd.DatetimeIndex):
            src.index = pd.to_datetime(src.index)
        src_period = src.index.to_series().diff().median()
        if src_period is None or pd.isna(src_period):
            src_period = pd.Timedelta("15min")

        anchor = src.index[0]
        offsets = (ts - anchor) % (src.index[-1] - anchor + src_period)
        sample_idx = anchor + offsets
        return src.reindex(src.index.union(sample_idx)).interpolate("time").loc[sample_idx].to_numpy()


def build_default_shape_per_load(
    n_loads: int,
    *,
    rng_seed: int = 0,
) -> list[LoadShape]:
    """Cria uma `LoadShape` distinta por carga, usando senoides com fases
    levemente diferentes para que as cargas nao oscilem em uniSono."""

    rng = np.random.default_rng(rng_seed)
    shapes: list[LoadShape] = []
    for i in range(n_loads):
        peak = 18.0 + rng.uniform(-2.0, 2.0)
        amp = float(rng.uniform(0.20, 0.35))
        noise = float(rng.uniform(0.01, 0.03))
        shapes.append(
            SinusoidalDailyShape(
                amplitude=amp,
                peak_hour=peak,
                noise_std=noise,
                seed=int(rng_seed + i + 1),
            )
        )
    return shapes
