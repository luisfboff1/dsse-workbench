"""Offline temporal runs. A returned trajectory is immutable and self-contained."""

from __future__ import annotations

import time
from threading import BoundedSemaphore
from typing import Literal
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.stats import chi2

from ..paths import ensure_src_on_path
from ..services.dc_measurement_model import (
    build_configured_ac_measurements,
    kind_by_pp_bus,
    kind_by_pp_line,
)
from ..services.network_builder import build_net_from_frontend, line_id_map_from_topology
from .powerflow import TopologyInput, _topology_to_dict

ensure_src_on_path()
from tese_dsse.sistemas_dinamicos.temporal import TemporalAttack, run_temporal_study

router = APIRouter()
_capacity = BoundedSemaphore(1)


class BiasInput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    channel: int = Field(ge=0, le=599)
    start_hour: float = Field(ge=0)
    end_hour: float = Field(gt=0)
    bias_sigma: float = Field(default=8, ge=-100, le=100)


class LoadEventInput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    bus_id: int
    start_hour: float = Field(ge=0)
    end_hour: float = Field(gt=0)
    factor: float = Field(default=1.3, ge=0, le=3)


class TemporalRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    topology: TopologyInput
    profile: Literal["constant", "daily", "solar"] = "daily"
    duration_hours: float = Field(default=24, ge=1, le=48)
    step_minutes: int = Field(default=60, ge=15, le=240)
    load_scale: float = Field(default=1, ge=0, le=3)
    dg_scale: float = Field(default=1, ge=0, le=3)
    noise_level: float = Field(default=0.01, ge=0, le=0.2)
    sigma_min: float = Field(default=0.005, ge=1e-6, le=0.1)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    angle_process_std: float = Field(default=0.005, gt=0, le=0.2)
    voltage_process_std: float = Field(default=0.005, gt=0, le=0.2)
    attack: BiasInput | None = None
    load_event: LoadEventInput | None = None

    @model_validator(mode="after")
    def limits(self):
        n = len(self.topology.buses)
        steps = self.duration_hours * 60 / self.step_minutes
        if not 2 <= n <= 64 or steps > 96 or n * n * (int(np.ceil(steps)) + 1) > 120_000:
            raise ValueError(
                "Interactive limit: 2–64 buses, at most 97 frames and 120000 bus² × frames. Increase the step or reduce duration/network size."
            )
        if len(self.topology.lines) > 200 or len(self.topology.line_measurements) > 100:
            raise ValueError("Interactive limit: 200 branches and 100 branch meters.")
        if len({b.id for b in self.topology.buses}) != n or len(
            {l.id for l in self.topology.lines}
        ) != len(self.topology.lines):
            raise ValueError("Bus and line IDs must be unique.")
        if sum(b.type == "slack" for b in self.topology.buses) != 1:
            raise ValueError("Temporal AC study requires exactly one slack bus.")
        if not self.topology.measurements and not self.topology.line_measurements:
            raise ValueError("Configure meters in Topology before running a temporal study.")
        bus_ids = {b.id for b in self.topology.buses}
        line_ids = {l.id for l in self.topology.lines}
        if any(l.from_bus not in bus_ids or l.to_bus not in bus_ids for l in self.topology.lines):
            raise ValueError("Branch endpoints must reference existing buses.")
        if any(m.busId not in bus_ids for m in self.topology.measurements) or any(
            m.lineId not in line_ids for m in self.topology.line_measurements
        ):
            raise ValueError("Meter targets must reference existing buses/branches.")
        for event in (self.attack, self.load_event):
            if event and not 0 <= event.start_hour < event.end_hour <= self.duration_hours:
                raise ValueError(
                    "Event window must satisfy 0 ≤ start < end ≤ duration (end exclusive)."
                )
        if self.load_event and self.load_event.bus_id not in bus_ids:
            raise ValueError("Load-event bus does not exist.")
        if self.load_event and not any(
            b.id == self.load_event.bus_id and (b.pLoad or b.qLoad) for b in self.topology.buses
        ):
            raise ValueError("Place the physical load event on a bus with an existing load.")
        return self


@router.post("/run")
def run_temporal(req: TemporalRequest) -> dict:
    if not _capacity.acquire(blocking=False):
        raise HTTPException(
            429, "A temporal study is already calculating. Retry after it finishes."
        )
    try:
        return _compute_temporal(req)
    finally:
        _capacity.release()


def _compute_temporal(req: TemporalRequest) -> dict:
    started = time.perf_counter()
    topo = _topology_to_dict(req.topology)
    # The network schema used by snapshot endpoints is retained unchanged.
    values = [
        v
        for b in req.topology.buses
        for v in (b.voltage, b.angle, b.pGen, b.qGen, b.pLoad, b.qLoad, b.pGenDG, b.qGenDG)
    ]
    values += [v for l in req.topology.lines for v in (l.resistance, l.reactance, l.susceptance)]
    if (
        not all(np.isfinite(v) for v in values)
        or not np.isfinite(req.topology.frequency_hz)
        or req.topology.frequency_hz <= 0
    ):
        raise HTTPException(422, "Network parameters must be finite and frequency positive.")
    net, bus_map = build_net_from_frontend(topo)
    pp_to_bus = {v: k for k, v in bus_map.items()}
    line_map = line_id_map_from_topology(topo)
    pp_to_line = {v: k for k, v in line_map.items()}
    # Temporal placement is explicit: an empty bus-meter list must not invoke
    # the legacy snapshot fallback that silently creates SCADA on every bus.
    bus_kinds = kind_by_pp_bus(topo, bus_map) if req.topology.measurements else {}
    line_kinds = kind_by_pp_line(topo, line_map)
    meta: list[dict] = []

    def factory(current):
        measurements, metadata = build_configured_ac_measurements(
            current,
            bus_kinds,
            req.noise_level,
            req.sigma_min,
            int(current.ext_grid.bus.iloc[0]),
            pp_to_bus,
            line_kinds,
            pp_to_line,
        )
        if len(measurements) > 600:
            raise ValueError("Interactive limit: 600 scalar measurements.")
        meta[:] = metadata
        return measurements

    count = int(np.floor(req.duration_hours * 60 / req.step_minutes))
    hours = np.arange(count + 1) * req.step_minutes / 60
    # Include a final partial step so the requested horizon is always represented.
    if hours[-1] < req.duration_hours - 1e-9:
        hours = np.r_[hours, req.duration_hours]
    if len(hours) > 97:
        raise HTTPException(422, "Interactive limit: 97 frames including the end of the horizon.")
    load_profile = np.ones_like(hours)
    dg_profile = np.ones_like(hours)
    if req.profile in ("daily", "solar"):
        load_profile = 0.85 + 0.2 * np.cos(2 * np.pi * (hours - 19) / 24)
    if req.profile == "solar":
        dg_profile = np.maximum(0, np.sin(np.pi * ((hours % 24) - 6) / 12))
    event = req.load_event
    try:
        model, frames = run_temporal_study(
            net,
            measurement_factory=factory,
            hours=hours,
            load_factors=load_profile * req.load_scale,
            dg_factors=dg_profile * req.dg_scale,
            seed=req.seed,
            attack=TemporalAttack(**req.attack.model_dump()) if req.attack else None,
            load_event_bus=bus_map[event.bus_id] if event else None,
            load_event_start=event.start_hour if event else 0,
            load_event_end=event.end_hour if event else 0,
            load_event_factor=event.factor if event else 1,
            angle_process_std=req.angle_process_std,
            voltage_process_std=req.voltage_process_std,
        )
    except (ValueError, np.linalg.LinAlgError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        # pandapower convergence/network failures are reviewable study errors.
        raise HTTPException(422, f"Temporal AC study failed: {exc}") from exc

    def channel_label(measurement, metadata):
        if metadata["busId"] is not None:
            quantity = {
                "v_bus": "|V|",
                "va_bus": "Angle",
                "p_inj": "P injection",
                "q_inj": "Q injection",
            }[measurement.kind]
            return f"{quantity} · B{metadata['busId']}"
        line = req.topology.lines[measurement.element]
        source, target = line.from_bus, line.to_bus
        if measurement.side == "to":
            source, target = target, source
        return f"{'P' if measurement.kind == 'p_branch' else 'Q'} · L{metadata['lineId']} · B{source} → B{target}"

    channels = [
        {
            "index": i,
            "label": channel_label(m, meta[i]),
            **meta[i],
            "unit": "pu"
            if m.kind == "v_bus"
            else "deg"
            if m.kind == "va_bus"
            else "MW"
            if m.kind.startswith("p_")
            else "MVAr",
        }
        for i, m in enumerate(frames[0].measurements)
    ]
    dof = len(channels) - model.num_states
    threshold = float(chi2.ppf(0.95, dof)) if dof > 0 else None

    def estimate(state, covariance, observed, sigma):
        table = model.state_to_table(state)
        states = []
        for pos, bus in enumerate(model.bus_order):
            vm_idx = model.vm_state_offset + pos
            angle_idx = model.angle_state_index.get(bus)
            states.append(
                {
                    "busId": pp_to_bus[bus],
                    "voltage": float(table.vm_pu[pos]),
                    "angle": float(table.va_degree[pos]),
                    "voltageStd": float(np.sqrt(max(0, covariance[vm_idx, vm_idx])))
                    if covariance is not None
                    else None,
                    "angleStd": float(np.rad2deg(np.sqrt(max(0, covariance[angle_idx, angle_idx]))))
                    if covariance is not None and angle_idx is not None
                    else 0
                    if angle_idx is None
                    else None,
                }
            )
        predicted = model.h(state)
        residual = (observed - predicted) / sigma
        return {
            "states": states,
            "predicted": predicted.tolist(),
            "residualSigma": residual.tolist(),
            "J": float(residual @ residual),
        }

    output = []
    for frame in frames:
        sigma = np.array([m.sigma for m in frame.measurements])
        wls = estimate(frame.wls_state, frame.wls_covariance, frame.observed, sigma)
        ekf = estimate(frame.ekf_state, frame.ekf_covariance, frame.observed, sigma)
        wls.update(
            converged=frame.wls_converged,
            iterations=frame.wls_iterations,
            chi2Threshold=threshold,
            chi2Passed=frame.wls_objective <= threshold
            if threshold is not None and frame.wls_converged
            else None,
        )
        ekf.update(maxInnovation=frame.innovation, initializedFromWls=frame.hour == 0)
        physical_buses = []
        for row in frame.physical_buses:
            bus = req.topology.buses[list(bus_map.values()).index(row["index"])]
            multiplier = frame.load_factor
            if event and bus.id == event.bus_id and event.start_hour <= frame.hour < event.end_hour:
                multiplier *= event.factor
            physical_buses.append(
                {
                    "id": bus.id,
                    "voltage": row["vm_pu"],
                    "angle": row["va_degree"],
                    "pLoad": bus.pLoad * multiplier,
                    "qLoad": bus.qLoad * multiplier,
                    "pGen": bus.pLoad * multiplier - row["p_mw"],
                    "qGen": bus.qLoad * multiplier - row["q_mvar"],
                }
            )
        physical_lines = [
            {
                "id": pp_to_line[row["index"]],
                "from": req.topology.lines[row["index"]].from_bus,
                "to": req.topology.lines[row["index"]].to_bus,
                "pFrom": row["p_from_mw"],
                "pTo": row["p_to_mw"],
                "qFrom": row["q_from_mvar"],
                "qTo": row["q_to_mvar"],
                "loss": row["pl_mw"],
            }
            for row in frame.physical_lines
        ]
        output.append(
            {
                "hour": frame.hour,
                "loadFactor": frame.load_factor,
                "dgFactor": frame.dg_factor,
                "physical": {
                    "converged": True,
                    "buses": physical_buses,
                    "lines": physical_lines,
                    "iterations": 0,
                    "iterationHistory": [],
                    "executionTime": 0,
                },
                "observed": frame.observed.tolist(),
                "truth": frame.truth.tolist(),
                "sigma": sigma.tolist(),
                "attacked": frame.attacked.tolist(),
                "wls": wls,
                "ekf": ekf,
                "events": [
                    {**e, **({"bus": pp_to_bus[e["bus"]]} if "bus" in e else {})}
                    for e in frame.events
                ],
            }
        )
    return {
        "runId": str(uuid4()),
        "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
        "config": req.model_dump(exclude={"topology"}),
        "topologyId": req.topology.id,
        "channels": channels,
        "nStates": model.num_states,
        "frames": output,
        "model": "Balanced AC QSTS on the app's 1 MVA equivalent base; synchronized meters; random-walk EKF with manual Q rates; offline replay.",
        "warnings": (
            ["Solar profile scales existing DG only; this network has no distributed generation."]
            if req.profile == "solar" and not len(net.sgen)
            else []
        )
        + (["No residual chi-square test: zero measurement redundancy."] if dof == 0 else []),
    }
