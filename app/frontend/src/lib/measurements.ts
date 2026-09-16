/**
 * Meter placement — single source of truth for the default/fallback
 * ("every bus gets a SCADA meter") and the per-kind display metadata used by
 * TopologyDiagram, StateEstimationTab and BadDataAnalyticsTab. Mirrors
 * app/backend/services/measurement_kinds.py; keep both in sync if a kind is
 * added/renamed.
 */
import type { LineMeasurement, Measurement, MeasurementKind, Topology } from './types'

export const MEASUREMENT_KINDS: MeasurementKind[] = ['pmu', 'ami', 'scada', 'pseudo']

/** Physical quantity codes the backend returns on residual/preview rows
 *  ('p_inj', 'q_inj', 'v_bus', 'va_bus'/'theta', 'p_branch', 'q_branch') —
 *  human-readable labels. p_branch/q_branch are line-flow meters (P_ij/Q_ij
 *  at the line's "from" terminal), not bus injection. */
export const QUANTITY_LABEL: Record<string, string> = {
  p_inj: 'P inj',
  q_inj: 'Q inj',
  v_bus: '|V|',
  va_bus: 'θ (PMU)',
  theta: 'θ (PMU)',
  p_branch: 'P line',
  q_branch: 'Q line',
}

export interface MeasurementKindInfo {
  label: string
  shortLabel: string
  description: string
  /** Tailwind color class, e.g. 'text-status-good' — for plain React/JSX. */
  colorToken: string
  /** Same token as a raw CSS var(), e.g. 'var(--color-status-good)' — for
   *  D3/SVG contexts (TopologyDiagram), which don't go through Tailwind. */
  colorVar: string
}

export const MEASUREMENT_KIND_INFO: Record<MeasurementKind, MeasurementKindInfo> = {
  pmu: {
    label: 'PMU (synchrophasor)',
    shortLabel: 'PMU',
    description: '|V|, θ, P, Q at the bus — high precision, the only kind with a direct angle measurement.',
    colorToken: 'text-method-ldf',
    colorVar: 'var(--color-method-ldf)',
  },
  scada: {
    label: 'SCADA',
    shortLabel: 'SCADA',
    description: '|V|, P, Q at the bus — classic RTU-grade precision.',
    colorToken: 'text-method-dc',
    colorVar: 'var(--color-method-dc)',
  },
  ami: {
    label: 'AMI / smart meter',
    shortLabel: 'AMI',
    description: 'P, Q only — noisier, no voltage or angle (typical of a load-side smart meter).',
    colorToken: 'text-status-warn',
    colorVar: 'var(--color-status-warn)',
  },
  pseudo: {
    label: 'Pseudo-measurement',
    shortLabel: 'Pseudo',
    description: 'P, Q only — not a physical meter, a historical load-profile estimate. Highest uncertainty.',
    colorToken: 'text-muted-foreground',
    colorVar: 'var(--color-muted-foreground)',
  },
}

/** Fills in any bus without a configured meter as 'scada'. Called only at
 *  topology *load* points (initial state, template swap, pandapower case
 *  fetch, new bus added — see App.tsx and TopologyTab.tsx), never on every
 *  edit: a bus with no entry could mean "never configured" (should default)
 *  or "user explicitly removed its meter" (should stay empty), and those
 *  look identical in the data, so this can't safely run on every change.
 *  Mirrors default_measurements() in measurement_kinds.py, which the
 *  backend falls back to if it ever receives an empty list. */
export function ensureMeasurements(topology: Topology): Topology {
  const existing = new Map((topology.measurements ?? []).map((m) => [m.busId, m]))
  const busIds = new Set(topology.buses.map((b) => b.id))
  const measurements: Measurement[] = topology.buses.map(
    (bus) => existing.get(bus.id) ?? { busId: bus.id, kind: 'scada' }
  )
  // Drop meters pointing at buses that no longer exist (bus was removed).
  const filtered = measurements.filter((m) => busIds.has(m.busId))

  // Line meters are opt-in (no default fill) — just prune ones pointing at
  // lines that no longer exist (line removed, or a template/pandapower case
  // swap loaded a different topology entirely).
  const lineIds = new Set(topology.lines.map((l) => l.id))
  const line_measurements = (topology.line_measurements ?? []).filter((m) => lineIds.has(m.lineId))

  return { ...topology, measurements: filtered, line_measurements }
}

export function getMeasurement(topology: Topology, busId: number): Measurement | undefined {
  return topology.measurements?.find((m) => m.busId === busId)
}

export function getLineMeasurement(topology: Topology, lineId: number): LineMeasurement | undefined {
  return topology.line_measurements?.find((m) => m.lineId === lineId)
}

/** Meter kind per bus id and per line id, resolved once instead of scanning
 *  the measurement arrays per lookup.
 *
 *  getMeasurement/getLineMeasurement below are `.find()` over the whole
 *  array. That is fine for a one-off lookup, but the diagram and the meter
 *  panels call them once per bus *and* once per line, which turns into
 *  O(buses x measurements) — on a few-thousand-bus feeder that alone is
 *  millions of comparisons per redraw. Build this once per render and read
 *  from the maps in any loop over buses or lines. */
export interface MeasurementIndex {
  busKind: Map<number, MeasurementKind>
  lineKind: Map<number, MeasurementKind>
}

export function buildMeasurementIndex(topology: Topology): MeasurementIndex {
  const busKind = new Map<number, MeasurementKind>()
  for (const m of topology.measurements ?? []) busKind.set(m.busId, m.kind)
  const lineKind = new Map<number, MeasurementKind>()
  for (const m of topology.line_measurements ?? []) lineKind.set(m.lineId, m.kind)
  return { busKind, lineKind }
}
