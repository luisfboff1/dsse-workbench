/**
 * Camada de API — todas as chamadas ao backend FastAPI passam por aqui.
 * O Vite proxy redireciona /api/* → http://localhost:8000/api/*
 */

import type { Topology, PowerFlowResult, ExecutionTrace } from './types'

const BASE = '/api'

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Normalizes topology: renames `from` to `from_bus` on lines */
function normalizeTopo(topology: Topology) {
  return {
    ...topology,
    lines: topology.lines.map((l: any) => ({
      ...l,
      from_bus: l.from ?? l.from_bus,
      to_bus: l.to ?? l.to_bus,
    })),
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`API ${path} → ${res.status}: ${err}`)
  }
  return res.json() as Promise<T>
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`API ${path} → ${res.status}: ${err}`)
  }
  return res.json() as Promise<T>
}

// ─── Topologias Pandapower ────────────────────────────────────────────────────

export type PandapowerVoltageClass = 'transmission' | 'distribution' | 'lv'

export interface PandapowerCaseInfo {
  name: string
  voltageClass: PandapowerVoltageClass
  buses?: number
  lines?: number
  trafos?: number
  sn_mva?: number
}

export interface ScenarioSummary {
  id: string
  name: string
  kind: 'topology' | 'powerflow' | 'state_estimation' | 'bad_data' | 'workbench'
  topologyName?: string
  createdAt?: string
  updatedAt?: string
}

export interface ScenarioPayload {
  name: string
  kind: ScenarioSummary['kind']
  topology: Topology
  settings?: Record<string, unknown>
  result?: Record<string, unknown> | null
  notes?: string
}

export async function listScenarios(): Promise<ScenarioSummary[]> {
  return get<ScenarioSummary[]>('/scenarios/')
}

export async function loadScenario(id: string) {
  return get<any>(`/scenarios/${id}`)
}

export async function saveScenario(payload: ScenarioPayload): Promise<{ id: string; path: string }> {
  return post('/scenarios/', payload)
}

export async function getPandapowerCases(): Promise<PandapowerCaseInfo[]> {
  return get<PandapowerCaseInfo[]>('/topologies/pandapower/list')
}

export async function loadPandapowerCase(caseName: string): Promise<Topology> {
  return get<Topology>(`/topologies/pandapower/${caseName}`)
}

// ─── Power Flow ───────────────────────────────────────────────────────────────

export interface PowerFlowRequest {
  topology: Topology
  method: 'pandapower-ac' | 'pandapower-dc' | 'lindistflow'
  maxIterations?: number
  tolerance?: number
}

export async function runPowerFlow(req: PowerFlowRequest): Promise<PowerFlowResult & { method: string }> {
  return post('/powerflow/run', { ...req, topology: normalizeTopo(req.topology) })
}

export interface CompareRow {
  busId: number
  ac_voltage: number | null
  dc_voltage: number | null
  ldf_voltage: number | null
  dc_voltage_err_pct: number | null
  ldf_voltage_err_pct: number | null
  ac_angle: number | null
  dc_angle: number | null
  ldf_angle: number | null
  dc_angle_err: number | null
  ldf_angle_err: number | null
  dc_angle_err_pct: number | null
  ldf_angle_err_pct: number | null
}

export async function comparePowerFlow(topology: Topology) {
  return post<{
    ac: PowerFlowResult
    dc: PowerFlowResult
    ldf: PowerFlowResult & { error?: string }
    ldf_error: string | null
    comparison: CompareRow[]
  }>('/powerflow/compare', { topology: normalizeTopo(topology) })
}

// ─── State Estimation ─────────────────────────────────────────────────────────

export type EstimationGroundTruth = 'ac' | 'dc'
export type EstimationMethod = 'dc-wls' | 'ac-gn-wls'

export interface EstimationRequest {
  topology: Topology
  ground_truth?: EstimationGroundTruth
  estimation_method?: EstimationMethod
  noise_level?: number
  sigma_min?: number
  seed?: number | null
  trace?: boolean
}

export interface EstimationResult {
  converged: boolean
  method: string
  groundTruth: EstimationGroundTruth
  iterations: number
  J: number
  dof: number
  /** Real chi2.ppf(0.05, dof) (alpha=0.05, ~95%) from the backend — same
   *  chi2_limit() the Bad Data tab and the reference notebook use. Null when
   *  dof<=0 (chi2 undefined). */
  chi2Threshold: number | null
  executionTime: number
  states: Array<{
    busId: number
    angleTrue_deg: number
    angleEst_deg: number
    error_deg: number
    /** Only present for estimation_method='ac-gn-wls' — DC-WLS is angles-only. */
    vTrue_pu?: number
    vEst_pu?: number
    vError_pu?: number
    /** A-priori uncertainty of the estimate: sqrt(diag((HᵀWH)⁻¹)), i.e. the
     *  standard deviation of the estimated state itself — NOT the residual.
     *  Depends only on topology, operating point and meter placement, never on
     *  z, so unlike error_deg it is computable without ground truth. It is also
     *  statistically independent of J/chi²: under Gaussian noise
     *  Cov(x̂ − x, r) = 0, so a passing chi² test says nothing about how
     *  trustworthy a given bus estimate is. 0 on the slack (fixed reference);
     *  null if the gain matrix is singular. */
    angleStd_deg?: number | null
    angleCi95_deg?: number | null
    vStd_pu?: number | null
    vCi95_pu?: number | null
  }>
  residuals: Array<{
    idx: number
    label: string
    meterKind: string
    quantity: string
    busId: number | null
    lineId: number | null
    z_true: number
    z_noisy: number
    z_hat: number
    sigma: number
    residual: number
    residual_normalized: number
  }>
  iterationHistory: Array<{ iteration: number; J: number; stepNormInf?: number }>
  noiseLevel: number
  nMeasurements: number
  nStates: number
  execution_trace?: ExecutionTrace | null
}

export async function runEstimation(req: EstimationRequest): Promise<EstimationResult> {
  return post('/estimation/run', { ...req, topology: normalizeTopo(req.topology) })
}

export interface MeasurementPreviewRow {
  label: string
  meterKind: string
  quantity: string
  busId: number | null
  lineId: number | null
  value: number
  /** One noisy sample, z_true + N(0,sigma) — same rng call shape (seed +
   *  sigma array, same row order) as /run, so with the same seed this is
   *  exactly the z_noisy an actual Run would use. */
  valueNoisy: number
  sigma: number
  /** Relative sigma as a percentage of |value| — null when |value| is ~0 (undefined %). */
  sigmaPct: number | null
}

export interface MeasurementPreviewResult {
  measurements: MeasurementPreviewRow[]
  nMeasurements: number
  nStates: number
}

/** What topology.measurements would actually measure right now — true value
 *  + one noisy sample + sigma per meter, nothing solved. Used to preview
 *  the measurement set before running Run. */
export async function previewMeasurements(req: EstimationRequest): Promise<MeasurementPreviewResult> {
  return post('/estimation/preview', { ...req, topology: normalizeTopo(req.topology) })
}

// ─── Bad Data ─────────────────────────────────────────────────────────────────

export interface BadDataRequest {
  topology: Topology
  /** 'dc': DC-linear, P injection only, H fixed across pipeline iterations.
   *  'ac': full AC set (P, Q, |V|, θ for PMU), nonlinear Gauss-Newton
   *  re-solved from scratch every pipeline iteration — the only mode that
   *  supports attack_target='parameter'/'both'. Ignores z_true_method.
   *  Default 'dc'. */
  method?: 'dc' | 'ac'
  noise_level?: number
  sigma_min?: number
  seed?: number | null
  /** If false, z = z_true exactly (no random noise sampled) — sigma is
   *  still used as the WLS weight/threshold unit. Default true matches
   *  Bretas et al. (2017)'s own practice ("random noise was added to the
   *  set of measurements... vary up to ±2σᵢ" in every simulation) and the
   *  standard bad-data validation protocol. Set to false to isolate a
   *  specific injected effect (e.g. a pure parameter error) from noise
   *  variance, or to reproduce a notebook case exactly. */
  add_noise?: boolean
  /** What gets attacked. 'parameter'/'both' require method='ac' — see
   *  docs/estudos/estimacao_estado/literatura/bretas2017_malicious_data_innovation.md. */
  attack_target?: 'measurement' | 'parameter' | 'both'
  inject_bad_data?: boolean
  bad_data_index?: number | null
  bad_data_magnitude?: number
  /** Frontend line id to attack — required when attack_target is 'parameter' or 'both'. */
  attack_line_id?: number | null
  /** Assumed relative uncertainty ("sigma") of a line parameter — the
   *  article only defines k·sigma for measurement error (eq. 18-19), not
   *  for a parameter, so this is an explicit assumption. Default 1%. */
  attack_param_sigma_pct?: number
  /** Parameter error magnitude, in multiples of attack_param_sigma_pct. */
  attack_param_n_sigmas?: number
  /** If true (default), distorts r, x AND c by the same factor; if false, only r and x. */
  attack_param_symmetric?: boolean
  detection?: 'residual' | 'cme'
  /** 'by_line' groups measurements by line (own flow + terminal-bus
   *  injections above threshold) — AC only, matches the parameter-attack
   *  signature described on p. 213 of Bretas et al. 2017. */
  identification?: 'lnr' | 'cme' | 'by_line'
  /** 'by_parameter' corrects the line's r/x/c via eq. 16 instead of
   *  touching a measurement — AC only, requires identification='by_line'. */
  correction?: 'remove' | 'ztrue' | 'by_parameter'
  alpha?: number
  /** DC only — ignored when method is 'ac'. */
  z_true_method?: 'topology_angles' | 'rundcpp'
}

export interface BadDataResult {
  converged: boolean
  injectedBadDataIdx: number | null
  m: number
  n: number
  DOF: number
  chi2_threshold: number           // chi2(alpha, m-n) - residual reference
  chi2_threshold_initial: number  // correct chi2 for the detection method (m-n or m)
  J_initial: number               // residual J (same for all combos with the same injection)
  J_detection_initial: number     // J used by detection (= J_initial for residual, J_CME for cme)
  K_matrix: number[][]
  pipeline: {
    J_final: number
    threshold: number
    detected: boolean
    nIterations: number
    nMeasurementsFinal: number
    flaggedIndices: number[]
    flaggedScores: number[]
    /** Line id (frontend) flagged at each iteration when identification='by_line'; null for lnr/cme or non-line iterations. AC only. */
    flaggedLines?: (number | null)[]
    actions: string[]
    history: Array<{ iter: number; J: number; threshold: number; detected: boolean; m: number; flagged_idx?: number; flagged_score?: number; flagged_line?: number | null }>
  }
  measurements: Array<{
    idx: number
    label: string
    meterKind: string
    quantity: string
    busId: number | null
    lineId: number | null
    z_true: number
    z_noisy: number
    residual: number
    r_N: number
    K_diag: number
    UI: number
    e_U: number
    CME: number
    CME_N: number
    /** Composed Normalized Error (eq. 20, Bretas & Bretas 2018) — subespaço do resíduo; base da correção z_true */
    CNE?: number
    sigma: number
    z_hat: number | null
    isBadData: boolean
    isFlagged: boolean
  }>
  executionTime: number
  config: {
    detection: string
    identification: string
    correction: string
    alpha: number
    attackTarget?: 'measurement' | 'parameter' | 'both'
  }
  /** Per-line diagnostic ranking (AC only) — fraction of each line's "own"
   *  measurements (flow + terminal-bus injections) above the CME_N
   *  threshold. Always computed when method='ac', regardless of attack
   *  type, so you can see whether a residual pattern "looks like" a
   *  parameter attack even when it wasn't one. */
  lineRanking?: Array<{
    lineId: number
    fromBus: number
    toBus: number
    nOwn: number
    nFlagged: number
    fractionFlagged: number
  }> | null
  /** Details of the injected parameter attack, when attack_target is 'parameter'/'both'. */
  parameterAttack?: {
    lineId: number
    fromBus: number
    toBus: number
    factor: number
    trueParams: { r: number; x: number; c: number }
    wrongParams: { r: number; x: number; c: number }
  } | null
  /** Result of an eq.-16 parameter correction, when correction='by_parameter' actually fired. */
  parameterCorrection?: {
    lineId: number
    /** The line's r/x/c right before this correction ran (self-contained —
     *  same as parameterAttack.wrongParams when the identified line is the
     *  one actually attacked, but not assumed to be). */
    wrongParams: { r: number; x: number; c: number }
    correctedParams: { r: number; x: number; c: number }
    trueParams: { r: number; x: number; c: number }
    /** CNE actually applied by eq. 16 (p_C = p_E·(1+CNE/100)), reconstructed from wrong→corrected r. */
    cneUsed: number | null
    residualErrorPct: number | null
  } | null
  /** Binary structural incidence matrix (m measurements × n_lines), AC only —
   *  measurement i belongs to line j's "own" set (flow on that line, or
   *  injection at either terminal bus). Purely structural (p. 213, Bretas
   *  et al. 2017) — always the same regardless of any attack having run. */
  structuralIncidence?: number[][] | null
  /** Column labels for structuralIncidence, e.g. "L1".."L6", same order as columns. */
  structuralIncidenceLines?: string[] | null
  /** RMSE(angle)/RMSE(|V|) vs. ground truth for 4 fixed reference scenarios —
   *  only computed when attack_target is 'parameter'/'both' (that's where
   *  "fix the reading" vs "fix the model" are genuinely different choices).
   *  x_true only exists here because this is a demo/validation comparison —
   *  not available in practice to DECIDE a correction, only to report one
   *  after the fact. See notebook section 12 ("lower RMSE ≠ correct fix"). */
  rmseComparison?: Array<{
    scenario: 'baseline' | 'no_correction' | 'best_measurement' | 'parameter_correction'
    label: string
    J: number
    detected: boolean
    rmseAngleDeg: number
    rmseVoltagePu: number
  }> | null
}

export async function runBadDataDetection(req: BadDataRequest): Promise<BadDataResult> {
  return post('/baddata/detect', { ...req, topology: normalizeTopo(req.topology) })
}

// ─── Bad Data Geometry ───────────────────────────────────────────────────────

export interface BadDataGeometryMeasurement {
  idx: number
  label: string
  /** Meter kind (pmu/scada/ami/pseudo) — see MEASUREMENT_KIND_INFO in lib/measurements.ts. */
  meterKind: string
  /** Physical quantity — bus: 'p_inj'/'theta' (DC) or 'p_inj'/'q_inj'/'v_bus'/'va_bus' (AC);
   *  line: 'p_branch' (DC) or 'p_branch'/'q_branch' (AC). */
  quantity: string
  busId: number | null
  lineId: number | null
  z_true: number
  sigma: number
  K_diag: number
  UI: number
  sigma_r: number
  r_N_clean: number
}

export interface BadDataGeometryResult {
  m: number
  n: number
  DOF: number
  chi2_threshold: number
  J_baseline: number
  alpha: number
  measurements: BadDataGeometryMeasurement[]
  labels: string[]
  K_matrix: number[][]
  H_matrix: number[][]
  executionTime: number
  solver_info: {
    z_true_method: string
    z_true_formula: string
    operating_point: string
    dc_model: string
    noise_model: string
  }
}

export interface BadDataGeometryRequest {
  topology: Topology
  /** Same convention as BadDataRequest.method — see there. Default 'dc'. */
  method?: 'dc' | 'ac'
  noise_level?: number
  sigma_min?: number
  seed?: number | null
  alpha?: number
  /** DC only — ignored when method is 'ac'. */
  z_true_method?: 'topology_angles' | 'rundcpp'
}

export async function runBadDataGeometry(req: BadDataGeometryRequest): Promise<BadDataGeometryResult> {
  return post('/baddata/geometry', { ...req, topology: normalizeTopo(req.topology) })
}

// ─── Topologies ───────────────────────────────────────────────────────────────

export async function fetchTopologies() {
  return get<Array<{ id: string; name: string; n_buses: number; n_lines: number }>>('/topologies/')
}

export async function fetchTopology(id: string): Promise<Topology> {
  const data = await get<any>(`/topologies/${id}`)
  // Converte from_bus → from para compatibilidade com tipos do frontend
  return {
    ...data,
    lines: data.lines.map((l: any) => ({ ...l, from: l.from_bus ?? l.from })),
  }
}

// ─── Operational chain (Pipeline) ─────────────────────────────────────────────

export type PipelineLayer = 'physical' | 'measurement' | 'rtu' | 'channel' | 'rtdb' | 'topology' | 'estimation' | 'opf'

export interface AttackSpec {
  attack_id: string
  layer: 'measurement' | 'rtu' | 'channel' | 'topology'
  label: string
  description: string
  /** What `target` means for this attack: 'sensor_id' | 'rtu_id' | 'switch_id' | 'none'. */
  target_kind: string
  params: Record<string, string>
  /** True when the attack produces no out-of-range value — only cross-layer
   *  consistency analysis can catch it. Drives the "stealthy" badge. */
  stealthy: boolean
}

export interface AttackInput {
  attack_id: string
  target: string
  params?: Record<string, unknown>
}

export interface PipelineRequest {
  topology: Topology
  noise_level?: number
  sigma_min?: number
  seed?: number | null
  add_noise?: boolean
  n_rtus?: number
  channel?: { base_delay_ms: number; jitter_ms: number; drop_probability: number }
  stale_after_s?: number
  unreliable_policy?: 'last_known' | 'assume_closed' | 'assume_open' | 'flow_inference'
  attacks?: AttackInput[]
  run_estimation?: boolean
  /** Control layer. Off by default — runopp is markedly slower than the rest. */
  run_opf?: boolean
  opf_limits?: OPFLimits
  /** Cross-layer agents. On by default; they never recompute anything, so
   *  turning them off changes no number in the result. */
  run_agents?: boolean
}

export interface OPFLimits {
  vm_min_pu: number
  vm_max_pu: number
  max_loading_percent: number
  ext_grid_cost: number
  gen_cost: number
  sgen_cost: number
}

export interface Violation {
  kind: 'undervoltage' | 'overvoltage' | 'overload'
  element: string
  index: number
  value: number
  limit: number
  margin: number
}

export interface OPFLayerResult {
  operator: OPFRun
  ideal: OPFRun
  reality_violations: Violation[]
  /** Violations that happen even with perfect information — the slack-bus
   *  modelling residue. Subtracted out before calling anything "hidden". */
  baseline_violations: Violation[]
  hidden_violations: Violation[]
  n_hidden_violations: number
  setpoint_deltas: Array<{
    element: string; index: number; bus: number
    p_dispatched: number; p_ideal: number
    delta_p_mw: number; delta_q_mvar: number
  }>
  max_setpoint_error_mw: number
  total_setpoint_error_mw: number
  cost_gap: number | null
  safe: boolean
  reason: string | null
  limits: OPFLimits
  error?: string
}

export interface OPFRun {
  converged: boolean
  objective: number | null
  setpoints: Array<{ element: string; index: number; bus: number; p_mw: number; q_mvar: number }>
  violations: Violation[]
  n_violations: number
  vm_pu: Record<string, number>
  loading_percent: Record<string, number>
  reason: string | null
}

export type AgentSeverity = 'ok' | 'info' | 'warning' | 'critical'

export interface AgentFinding {
  agent: string
  layer: string
  severity: AgentSeverity
  title: string
  detail: string
  evidence: Record<string, unknown>
  /** Message types from upstream agents that led here. Empty means the agent
   *  reached this on its own, looking only at its own layer. */
  caused_by: string[]
}

export interface AgentsLayerResult {
  recommendation: 'dispatch' | 'derate' | 'block'
  worst_severity: AgentSeverity
  findings: AgentFinding[]
  messages: Array<{
    sender: string; recipient: string; type: string
    priority: string; payload: Record<string, unknown>; bytes: number
  }>
  n_messages: number
  total_bytes: number
  propagation: Array<{ agent: string; layer: string; title: string; caused_by: string[] }>
}

export interface TraceEvent {
  layer: PipelineLayer
  timestamp_s: number
  subject: string
  message: string
  level: 'info' | 'warning' | 'error'
  details: Record<string, unknown>
}

export interface PipelineResult {
  run_id: string
  elapsed_ms: number
  config: {
    n_rtus: number
    channel: { base_delay_ms: number; jitter_ms: number; drop_probability: number; per_rtu_delay_ms: Record<string, number> }
    stale_after_s: number
    unreliable_policy: string
    add_noise: boolean
    seed: number | null
    attacks: AttackInput[]
  }
  layers: {
    physical: {
      converged: boolean
      buses: Array<{ id: number; vm_pu: number; va_degree: number; p_mw: number; q_mvar: number }>
      lines: Array<{ id: number; p_from_mw: number; q_from_mvar: number; p_to_mw: number; loading_percent: number }>
    }
    measurement: {
      n_measurements: number
      rows: Array<{
        index: number; quantity: string; meterKind: string
        busId: number | null; lineId: number | null
        z_true: number; z_field: number; sigma: number
      }>
    }
    rtu: {
      rtus: Array<{ rtu_id: string; bus_ids: number[]; n_points: number; scan_period_s: number; point_ids: string[] }>
      points: Array<{
        point_id: string; sensor_id: string; rtu_id: string; quantity: string
        equipment_id: string; phase: string; value: number; sigma: number
        source_timestamp_s: number; meter_kind: string; quality: string
        bus_id: number | null; line_id: number | null; measurement_index: number | null
      }>
    }
    channel: {
      statistics: {
        n_packets: number; n_dropped: number; loss_rate: number
        delay_ms_mean: number; delay_ms_max: number
        delay_ms_by_rtu: Record<string, number>
      }
      packets: Array<{
        packet_id: number; sequence: number; source: string; destination: string
        point_id: string; sensor_id: string; send_time_s: number
        receive_time_s: number; delay_ms: number
        dropped: boolean; reordered: boolean; replayed: boolean
      }>
    }
    rtdb: {
      summary: {
        now_s: number; stale_after_s: number; n_points: number; n_usable: number
        n_stale: number; n_bad: number; n_suspect: number; n_never_received: number
        timestamp_spread_s: number; max_age_s: number
      }
      records: Array<{
        point_id: string; rtu_id: string; quantity: string; equipment_id: string
        value: number; sigma: number; source_timestamp_s: number
        receive_timestamp_s: number | null; quality: string; stale: boolean
        age_s: number; sensor_id: string; packet_id: number | null
        meter_kind: string; bus_id: number | null; line_id: number | null
        measurement_index: number | null; never_received: boolean
      }>
    }
    topology: {
      summary: {
        version: number; policy: string; n_switches: number; n_closed: number
        n_open: number; n_unreliable: number; unreliable_ids: number[]
        status_counts: Record<string, number>
        active_line_ids: number[]; open_line_ids: number[]
      }
      switches: Array<{
        switch_id: number; name: string; from_bus: number; to_bus: number
        line_id: number | null; contact_a: number; contact_b: number
        status_code: number; status_label: string; reliable: boolean
        resolved_closed: boolean; resolution_reason: string
      }>
      mismatched_switch_ids: number[]
      matches_reality: boolean
    }
    estimation: {
      ran: boolean
      reason?: string
      converged?: boolean
      iterations?: number
      n_measurements?: number
      n_states?: number
      J?: number
      chi2_limit?: number
      chi2_passed?: boolean
      max_vm_error?: number | null
      max_va_error_deg?: number | null
      rmse_vm?: number | null
      model_open_line_ids?: number[]
      comparison?: Array<{
        busId: number
        vm_true: number; vm_est: number; vm_error: number
        va_true: number; va_est: number; va_error: number
      }>
    } | null
    opf: OPFLayerResult | null
    agents: AgentsLayerResult | null
  }
  trace: {
    events: TraceEvent[]
    n_events: number
    events_by_layer: Record<string, number>
    problems: TraceEvent[]
    subjects: string[]
  }
}

export async function listPipelineAttacks(): Promise<{ attacks: AttackSpec[]; layers: string[] }> {
  return get('/pipeline/attacks')
}

export async function runPipeline(req: PipelineRequest): Promise<PipelineResult> {
  return post('/pipeline/run', { ...req, topology: normalizeTopo(req.topology) })
}

export async function fetchPipelineTrace(runId: string, subject: string) {
  return get<{ run_id: string; subject: string; events: TraceEvent[]; n_events: number }>(
    `/pipeline/run/${runId}/trace/${encodeURIComponent(subject)}`
  )
}

// ─── Topology Import/Export ──────────────────────────────────────────────────

export interface ImportFormat {
  id: string
  name: string
  extensions: string[]
  description: string
  multiFile?: boolean
}

export interface ExportFormat {
  id: string
  name: string
  extension: string
  description: string
}

export async function getImportFormats(): Promise<ImportFormat[]> {
  return get<ImportFormat[]>('/topologies/import/formats')
}

export async function getExportFormats(): Promise<ExportFormat[]> {
  return get<ExportFormat[]>('/topologies/export/formats')
}

export async function importTopology(
  file: File,
  extraFiles?: File[]
): Promise<Topology & { meta?: { source: string; warnings?: string[]; size_warning?: string | null } }> {
  const formData = new FormData()
  formData.append('file', file)
  if (extraFiles) {
    for (const ef of extraFiles) {
      formData.append('extra_files', ef)
    }
  }
  const res = await fetch(`${BASE}/topologies/import`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err)
  }
  return res.json()
}

export async function exportTopology(
  topology: Topology,
  format: string
): Promise<Blob> {
  const res = await fetch(`${BASE}/topologies/export/${format}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(normalizeTopo(topology)),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err)
  }
  return res.blob()
}

export async function downloadCsvTemplate(): Promise<Blob> {
  const res = await fetch(`${BASE}/topologies/import/csv-template`)
  if (!res.ok) throw new Error('Failed to download CSV template')
  return res.blob()
}
