export type BusType = 'slack' | 'pv' | 'pq'

export interface Bus {
  id: number
  name: string
  type: BusType
  voltage: number
  angle: number
  pGen: number
  qGen: number
  pLoad: number
  qLoad: number
  /** Distributed generation (pandapower `sgen`) — fixed PQ, does not control
   *  voltage (unlike pGen/gen). Typical of PV/wind DG on MV/LV feeders. */
  pGenDG?: number
  qGenDG?: number
  qMin?: number
  qMax?: number
  geoX?: number
  geoY?: number
}

export interface Line {
  id: number
  from: number
  to: number
  resistance: number
  reactance: number
  susceptance: number
  tapRatio?: number
}

export interface OpenSwitch {
  id: number
  from: number
  to: number
  name?: string
  /** Electrical parameters — present when the switch has a known line model
   *  (e.g. a tie-line with impedance). When absent, closing the switch creates
   *  a near-ideal line (R=X=0.001 pu, B=0) — a good approximation for DSSE. */
  r_pu?: number
  x_pu?: number
  b_pu?: number
}

/** Full switch model — replaces OpenSwitch for pandapower-loaded topologies.
 *  `closed=true` means the switch is active (part of the network).
 *  `closed=false` means normally-open (tie-switch, drawn dashed). */
export interface Switch {
  id: number
  from: number
  to: number
  name?: string
  closed: boolean
  r_pu?: number
  x_pu?: number
  b_pu?: number
}

/** One meter per bus max. See LineMeasurement below for the branch-flow
 *  counterpart (a meter attached to a line instead of a bus). */
export type MeasurementKind = 'pmu' | 'ami' | 'scada' | 'pseudo'

export interface Measurement {
  busId: number
  kind: MeasurementKind
}

/** Branch-flow meter (TC/TP at one line terminal — measures P_ij/Q_ij, not
 *  bus injection). Opt-in, unlike bus meters: no default, a line only gets
 *  one when the user clicks it and picks a kind (ensureMeasurements() only
 *  fills in bus defaults, never line ones). Same 4 kinds/σ-tiers as
 *  Measurement — see LineMeasurementInput in app/backend/routes/powerflow.py. */
export interface LineMeasurement {
  lineId: number
  kind: MeasurementKind
}

export interface Topology {
  id: string
  name: string
  buses: Bus[]
  lines: Line[]
  /** Full switch list — ALL switches (closed + open) with their state.
   *  Populated by pandapower-loaded topologies; absent on hand-built topologies
   *  that have no switch concept. When present, the UI shows all switches with
   *  toggle controls and uses this as the source of truth. */
  switches?: Switch[]
  /** Legacy/compat field — normally-open switches only (closed=false subset of
   *  `switches`). Kept for: (a) hand-built topologies that only know open
   *  switches, (b) older localStorage snapshots, (c) the D3 diagram which can
   *  derive open switches from `switches` directly. New code should prefer
   *  `switches` when available. */
  openSwitches?: OpenSwitch[]
  /** Meters placed on buses — drives what Bad Data / State Estimation can see.
   *  ensureMeasurements() in networkTopology.ts fills in gaps with 'scada' so
   *  this is never partially-populated in practice; still optional on the
   *  wire since older persisted topologies (localStorage, saved scenarios)
   *  predate this field. */
  measurements?: Measurement[]
  /** Meters placed on lines — always opt-in, empty by default (see
   *  LineMeasurement). */
  line_measurements?: LineMeasurement[]
  /** Network frequency — most pandapower cases are 50 Hz, but not all
   *  (case5/PJM is 60 Hz). Needed server-side to convert line.susceptance
   *  back to a shunt capacitance correctly; the frontend just carries it
   *  through untouched. Defaults to 50 if omitted (backend TopologyInput). */
  frequency_hz?: number
}

export type PowerFlowMethod = 'pandapower-ac' | 'pandapower-dc' | 'lindistflow'

export interface PowerFlowResult {
  converged: boolean
  iterations: number
  buses: Array<{
    id: number
    voltage: number
    angle: number
    pGen: number
    qGen: number
    pLoad: number
    qLoad: number
  }>
  lines: Array<{
    id: number
    from?: number
    to?: number
    pFrom: number
    qFrom: number
    pTo: number
    qTo: number
    loss: number
  }>
  iterationHistory: Array<{
    iteration: number
    maxMismatch: number
  }>
  executionTime: number
}

export interface CalculationSettings {
  maxIterations: number
  tolerance: number
}

// ─── Execution Trace ─────────────────────────────────────────────────────────

export type TraceVariableType = 'scalar' | 'vector' | 'matrix'

export interface TraceVariable {
  name: string
  label: string
  type: TraceVariableType
  description: string
  // scalar
  value?: number | boolean | string | null
  // vector (1-D) or matrix (2-D)
  shape?: number[]
  data?: number[] | number[][]
  truncated?: boolean
}

export type TraceCategory = 'setup' | 'iteration' | 'result' | 'convergence'

export interface TraceStep {
  name: string
  category: TraceCategory
  elapsed_ms: number
  variables: TraceVariable[]
  log: string
}

export interface ExecutionTrace {
  algorithm: string
  total_ms: number
  converged: boolean
  steps: TraceStep[]
}
