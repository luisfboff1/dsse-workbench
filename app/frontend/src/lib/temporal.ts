import type { PowerFlowResult, Topology } from './types'
const TEMPORAL_VIEWS = new Set(['console', 'topology', 'powerflow', 'estimation', 'baddata'])
export function isTemporalView(view: string) { return TEMPORAL_VIEWS.has(view) }

export interface TemporalConfig {
  profile: 'constant' | 'daily' | 'solar'
  duration_hours: number
  step_minutes: number
  load_scale: number
  dg_scale: number
  noise_level: number
  seed: number
  angle_process_std: number
  voltage_process_std: number
  attack: { channel: number; start_hour: number; end_hour: number; bias_sigma: number } | null
  load_event: { bus_id: number; start_hour: number; end_hour: number; factor: number } | null
}

export interface TemporalEstimate {
  states: Array<{ busId: number; voltage: number; angle: number; voltageStd: number | null; angleStd: number | null }>
  predicted: number[]
  residualSigma: number[]
  J: number
  converged?: boolean
  iterations?: number
  chi2Threshold?: number | null
  chi2Passed?: boolean | null
  maxInnovation?: number | null
  initializedFromWls?: boolean
}

export interface TemporalRun {
  runId: string
  topologyId: string
  elapsedMs: number
  config: TemporalConfig
  model: string
  warnings: string[]
  nStates: number
  channels: Array<{ index: number; label: string; quantity: string; meterKind: string; busId: number | null; lineId: number | null; unit: string }>
  frames: Array<{
    hour: number
    loadFactor: number
    dgFactor: number
    physical: PowerFlowResult
    truth: number[]
    observed: number[]
    sigma: number[]
    attacked: boolean[]
    wls: TemporalEstimate
    ekf: TemporalEstimate
    events: Array<{ type: string; action: string; channel?: number; bus?: number; max_abs_lambda?: number }>
  }>
}

export const DEFAULT_TEMPORAL_CONFIG: TemporalConfig = {
  profile: 'daily', duration_hours: 24, step_minutes: 60,
  load_scale: 1, dg_scale: 1, noise_level: 0.01, seed: 42,
  angle_process_std: 0.005, voltage_process_std: 0.005,
  attack: null, load_event: null,
}

export async function runTemporal(topology: Topology, config: TemporalConfig, signal?: AbortSignal): Promise<TemporalRun> {
  const response = await fetch('/api/temporal/run', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topology, ...config }), signal,
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail))
  }
  return response.json()
}

export function hourLabel(hour: number): string {
  const minutes = Math.round(hour * 60)
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
}
