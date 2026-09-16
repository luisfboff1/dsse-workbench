import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Lightning,
  Clock,
  Broadcast,
  TreeStructure,
  ShieldWarning,
  Scales,
} from '@phosphor-icons/react'
import type { AgentSimulationBenchmark } from '@/lib/agentTypes'

interface AgentBenchmarkCardProps {
  benchmark: AgentSimulationBenchmark | null
  isLoading?: boolean
}

export function AgentBenchmarkCard({ benchmark, isLoading }: AgentBenchmarkCardProps) {
  if (!benchmark) {
    return (
      <Card className="border-border">
        <CardHeader className="py-3 px-4">
          <CardTitle className="text-sm font-semibold flex items-center gap-2 text-muted-foreground">
            <Scales className="h-4 w-4" />
            Centralized vs. Multi-Agent Scalability Benchmark
          </CardTitle>
        </CardHeader>
        <CardContent className="py-6 text-center text-xs text-muted-foreground">
          Run the agentic simulation to generate real-time comparison metrics.
        </CardContent>
      </Card>
    )
  }

  const { centralized, distributed_multiagent, speedup_factor, communication_bandwidth_saved_pct } = benchmark

  return (
    <Card className="border-border shadow-xs">
      <CardHeader className="py-3 px-4 border-b">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Scales className="h-4 w-4 text-primary" />
            Scalability Benchmark — Centralized vs. Multi-Agent Architecture
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="text-xs gap-1">
              <Lightning className="h-3 w-3 text-amber-500" />
              Speedup: <span className="font-bold">{speedup_factor}x</span>
            </Badge>
            <Badge variant="outline" className="text-xs gap-1 text-emerald-600 dark:text-emerald-400 border-emerald-500/30">
              <Broadcast className="h-3 w-3" />
              Bandwidth Saved: <span className="font-bold">{communication_bandwidth_saved_pct}%</span>
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-4 space-y-4">
        {/* KPI Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="rounded-lg border bg-muted/20 p-3 space-y-1">
            <div className="text-[11px] font-medium text-muted-foreground flex items-center gap-1">
              <Clock className="h-3.5 w-3.5 text-primary" />
              Solve Time (Parallel)
            </div>
            <div className="text-base font-bold text-foreground">
              {distributed_multiagent.execution_time_ms} ms
            </div>
            <div className="text-[10px] text-muted-foreground">
              vs. {centralized.execution_time_ms} ms (Centralized)
            </div>
          </div>

          <div className="rounded-lg border bg-muted/20 p-3 space-y-1">
            <div className="text-[11px] font-medium text-muted-foreground flex items-center gap-1">
              <TreeStructure className="h-3.5 w-3.5 text-primary" />
              Partition Clusters
            </div>
            <div className="text-base font-bold text-foreground">
              {distributed_multiagent.num_clusters} Islands
            </div>
            <div className="text-[10px] text-muted-foreground">
              Decoupled sub-matrices
            </div>
          </div>

          <div className="rounded-lg border bg-muted/20 p-3 space-y-1">
            <div className="text-[11px] font-medium text-muted-foreground flex items-center gap-1">
              <Broadcast className="h-3.5 w-3.5 text-primary" />
              Comm. Messages
            </div>
            <div className="text-base font-bold text-foreground">
              {distributed_multiagent.communication_messages}
            </div>
            <div className="text-[10px] text-muted-foreground">
              On-demand only ({distributed_multiagent.communication_bytes} B)
            </div>
          </div>

          <div className="rounded-lg border bg-muted/20 p-3 space-y-1">
            <div className="text-[11px] font-medium text-muted-foreground flex items-center gap-1">
              <ShieldWarning className="h-3.5 w-3.5 text-amber-500" />
              "Engineer Cries"
            </div>
            <div className="text-base font-bold text-amber-600 dark:text-amber-400">
              {distributed_multiagent.engineer_cries_triggered ?? 0}
            </div>
            <div className="text-[10px] text-muted-foreground">
              Assistance requests fired
            </div>
          </div>
        </div>

        {/* Detailed Side-by-Side Comparison Table */}
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs text-left">
            <thead className="bg-muted/60 text-muted-foreground border-b uppercase text-[10px] tracking-wider">
              <tr>
                <th className="py-2 px-3 font-semibold">Evaluation Metric</th>
                <th className="py-2 px-3 font-semibold text-muted-foreground">Centralized EMS / Single Server</th>
                <th className="py-2 px-3 font-semibold text-primary">Distributed Multi-Agent Clusters</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              <tr>
                <td className="py-2 px-3 font-medium text-foreground">Matrix Inversion Scale</td>
                <td className="py-2 px-3 text-muted-foreground font-mono">{centralized.matrix_dimension}</td>
                <td className="py-2 px-3 text-foreground font-mono font-medium">
                  {distributed_multiagent.max_local_matrix_size ? `Max ${distributed_multiagent.max_local_matrix_size} elements (Local)` : 'Localized'}
                </td>
              </tr>
              <tr>
                <td className="py-2 px-3 font-medium text-foreground">Computation Bottleneck</td>
                <td className="py-2 px-3 text-destructive/90">{centralized.scalability_status}</td>
                <td className="py-2 px-3 text-emerald-600 dark:text-emerald-400 font-medium">
                  {distributed_multiagent.scalability_status}
                </td>
              </tr>
              <tr>
                <td className="py-2 px-3 font-medium text-foreground">Communication Pattern</td>
                <td className="py-2 px-3 text-muted-foreground">Continuous high-rate telemetry pushed to SCADA</td>
                <td className="py-2 px-3 text-foreground font-medium">
                  On-demand triggers only ("Engineer Cry" when rank drops)
                </td>
              </tr>
              <tr>
                <td className="py-2 px-3 font-medium text-foreground">Voltage Accuracy (RMSE V)</td>
                <td className="py-2 px-3 text-muted-foreground font-mono">{centralized.rmse_v_pu.toFixed(5)} pu</td>
                <td className="py-2 px-3 text-foreground font-mono font-medium">{distributed_multiagent.rmse_v_pu.toFixed(5)} pu</td>
              </tr>
              <tr>
                <td className="py-2 px-3 font-medium text-foreground">Angle Accuracy (RMSE θ)</td>
                <td className="py-2 px-3 text-muted-foreground font-mono">{centralized.rmse_theta_deg.toFixed(4)}°</td>
                <td className="py-2 px-3 text-foreground font-mono font-medium">{distributed_multiagent.rmse_theta_deg.toFixed(4)}°</td>
              </tr>
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

