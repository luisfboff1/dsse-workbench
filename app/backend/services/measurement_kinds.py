"""Reexporta a calibracao de sigma por tipo de medidor de
`tese_dsse.estimacao_estado.sensor_calibration` -- fonte unica
compartilhada com os notebooks de simulacao. Ver a docstring la para a
razao de existir (mudar um multiplicador muda notebook e app juntos) e
para o porque de `v_sigma_mult` do SCADA ser 0.2, nao 1.0.

Mantido como arquivo proprio (em vez de todo mundo importar direto de
`tese_dsse`) so para nao precisar tocar nos ~10 call sites que ja fazem
`from .measurement_kinds import ...` em `dc_measurement_model.py` e afins.
"""

from __future__ import annotations

from ..paths import ensure_src_on_path

ensure_src_on_path()

from tese_dsse.estimacao_estado.sensor_calibration import (  # noqa: F401,E402
    MEASUREMENT_KINDS,
    MEASUREMENT_KIND_SPECS,
    MeasurementKind,
    MeasurementKindSpec,
    p_sigma,
    v_sigma,
    va_sigma_deg,
)


def default_measurements(buses: list[dict]) -> list[dict]:
    """Toda barra com SCADA — usado quando a topologia não configurou nenhum
    medidor. O frontend já garante isso (ensureMeasurements em
    networkTopology.ts, aplicado sempre que a topologia muda), mas a rota
    fica correta mesmo chamada direto na API sem passar pelo frontend."""
    return [{"busId": int(b["id"]), "kind": "scada"} for b in buses]
