import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { TreeStructure, Eye, Sparkle, ChartLine, Bug, Thermometer, ShieldCheck, Warning } from '@phosphor-icons/react'
import type { AgentClusterData } from '@/lib/agentTypes'

interface AgentClusterConfigCardProps {
  clusters: AgentClusterData[]
  onToggleClusterAgent?: (clusterId: number, agentKind: string, enabled: boolean) => void
}

const AGENT_BADGE_INFO: Record<string, { label: string; icon: any; color: string }> = {
  observability: { label: 'Observability', icon: Eye, color: 'text-blue-500' },
  pseudo_measurement: { label: 'Pseudo (ML)', icon: Sparkle, color: 'text-purple-500' },
  estimator: { label: 'DSSE Estimator', icon: ChartLine, color: 'text-emerald-500' },
  bad_data: { label: 'Bad Data (CNE)', icon: Bug, color: 'text-amber-500' },
  thermal_environment: { label: 'Thermal Rating', icon: Thermometer, color: 'text-rose-500' },
}

export function AgentClusterConfigCard({ clusters, onToggleClusterAgent }: AgentClusterConfigCardProps) {
  return (
    <Card className="border-border shadow-xs">
      <CardHeader className="py-3 px-4 border-b">
        <CardTitle className="text-sm font-semibold flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TreeStructure className="h-4 w-4 text-primary" />
            Cluster & Agent Architecture Configuration
          </div>
          <Badge variant="outline" className="text-xs font-normal">
            {clusters.length} Islands Configured
          </Badge>
        </CardTitle>
      </CardHeader>

      <CardContent className="p-4 space-y-3">
        {clusters.length === 0 ? (
          <div className="py-6 text-center text-xs text-muted-foreground">
            No clusters partitioned yet. Select partitioning algorithm above and click "Partition".
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {clusters.map((cl) => {
              const estTime = cl.estimation?.execution_time_ms
              const matrixDim = cl.estimation?.matrix_dim
              const hasBadData = cl.bad_data?.has_bad_data

              return (
                <div key={cl.cluster_id} className="rounded-lg border bg-muted/20 p-3 space-y-2.5 flex flex-col justify-between">
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-xs text-foreground flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full bg-primary inline-block" />
                        {cl.name}
                      </span>
                      {hasBadData ? (
                        <Badge variant="destructive" className="text-[10px] py-0 px-1 gap-1">
                          <Warning className="h-3 w-3" />
                          Anomaly
                        </Badge>
                      ) : estTime ? (
                        <Badge variant="secondary" className="text-[10px] py-0 px-1 text-emerald-600 dark:text-emerald-400 gap-1">
                          <ShieldCheck className="h-3 w-3" />
                          {estTime.toFixed(1)} ms
                        </Badge>
                      ) : null}
                    </div>

                    <div className="text-[11px] text-muted-foreground space-y-0.5">
                      <div>
                        Buses ({cl.bus_ids.length}):{' '}
                        <span className="font-mono text-foreground">{cl.bus_ids.join(', ')}</span>
                      </div>
                      {cl.boundary_bus_ids.length > 0 && (
                        <div>
                          Boundary Nodes:{' '}
                          <span className="font-mono text-indigo-600 dark:text-indigo-400 font-medium">
                            {cl.boundary_bus_ids.join(', ')}
                          </span>
                        </div>
                      )}
                      {matrixDim && (
                        <div>
                          Matrix Size:{' '}
                          <span className="font-mono text-foreground">
                            {matrixDim[0]} x {matrixDim[1]} ({matrixDim[0] * matrixDim[1]} elements)
                          </span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Active Agents Badges */}
                  <div className="pt-2 border-t border-border/50 space-y-1">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Active Multi-Agent Team
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {cl.enabled_agent_kinds.map((k) => {
                        const info = AGENT_BADGE_INFO[k] || { label: k, icon: Eye, color: 'text-primary' }
                        const Icon = info.icon
                        return (
                          <Badge
                            key={k}
                            variant="outline"
                            className="text-[10px] py-0.5 px-1.5 gap-1 bg-background"
                          >
                            <Icon className={`h-3 w-3 ${info.color}`} />
                            {info.label}
                          </Badge>
                        )
                      })}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

