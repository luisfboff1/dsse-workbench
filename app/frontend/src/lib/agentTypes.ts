/**
 * Type definitions for the Multi-Agent Framework (AgentFrameworkTab and
 * related components). Matches the shapes produced by the backend routes
 * /api/agents/partition, /api/agents/simulate and /api/agents/plugins.
 *
 * Previously this file was empty (left blank during initial scaffolding),
 * causing TS2305 errors in all Agent* components — restored 2026-08-24.
 */

// --- Cluster / Partition ------------------------------------------------------

export interface ClusterEstimationResult {
  execution_time_ms: number
  matrix_dim?: [number, number]
  rmse_v_pu?: number
  rmse_theta_deg?: number
}

export interface ClusterBadDataResult {
  has_bad_data: boolean
  flagged_buses?: number[]
  flagged_lines?: number[]
}

export interface AgentClusterData {
  cluster_id: number
  name: string
  bus_ids: number[]
  boundary_bus_ids: number[]
  enabled_agent_kinds: string[]
  estimation?: ClusterEstimationResult
  bad_data?: ClusterBadDataResult
  [key: string]: unknown
}

// --- Plugin -------------------------------------------------------------------

export interface AgentPluginData {
  plugin_id: string
  name: string
  description: string
  version: string
  enabled: boolean
  category: string
  author: string
  parameters: Record<string, unknown>
  agent_kind?: string
  tags?: string[]
}

// --- Event Log ----------------------------------------------------------------

export interface AgentEventLogItem {
  agent_id: string
  cluster_id: number
  kind: string
  level: string
  message: string
  timestamp?: string
}

// --- Benchmark ----------------------------------------------------------------

export interface CentralizedBenchmark {
  execution_time_ms: number
  matrix_dimension: string
  scalability_status: string
  rmse_v_pu: number
  rmse_theta_deg: number
}

export interface DistributedBenchmark {
  execution_time_ms: number
  num_clusters: number
  communication_messages: number
  communication_bytes: number
  max_local_matrix_size?: number
  scalability_status: string
  rmse_v_pu: number
  rmse_theta_deg: number
  engineer_cries_triggered?: number
}

export interface AgentSimulationBenchmark {
  centralized: CentralizedBenchmark
  distributed_multiagent: DistributedBenchmark
  speedup_factor: number
  communication_bandwidth_saved_pct: number
}

// --- Simulation Result --------------------------------------------------------

export interface AgentSimulationResult {
  benchmark: AgentSimulationBenchmark
  event_log: AgentEventLogItem[]
  /** Keyed by string cluster_id (e.g. "0", "1", ...). */
  clusters: Record<string, Partial<AgentClusterData>>
  estimated_v_pu?: Record<string, number>
  estimated_theta_deg?: Record<string, number>
}
