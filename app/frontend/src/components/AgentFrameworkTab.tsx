import { useState, useEffect, useCallback, useRef } from 'react'
import type { Topology } from '@/lib/types'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { toast } from 'sonner'
import {
  Play,
  ShareNetwork,
  PlugsConnected,
  TreeStructure,
  ShieldWarning,
  Sparkle,
  Thermometer,
  ArrowsClockwise,
} from '@phosphor-icons/react'

import { AgentTopologyCanvas } from './AgentTopologyCanvas'
import { AgentClusterConfigCard } from './AgentClusterConfigCard'
import { AgentBenchmarkCard } from './AgentBenchmarkCard'
import { AgentEventLogCard } from './AgentEventLogCard'
import { AgentPluginManagerDialog } from './AgentPluginManagerDialog'

import type {
  AgentClusterData,
  AgentPluginData,
  AgentSimulationResult,
} from '@/lib/agentTypes'

interface AgentFrameworkTabProps {
  topology: Topology
}

export function AgentFrameworkTab({ topology }: AgentFrameworkTabProps) {
  const [kClusters, setKClusters] = useState<number>(2)
  const [partitionMethod, setPartitionMethod] = useState<'spectral' | 'radial_feeder'>('spectral')
  const [clusters, setClusters] = useState<AgentClusterData[]>([])
  const [plugins, setPlugins] = useState<AgentPluginData[]>([])
  const [pluginDialogOpen, setPluginDialogOpen] = useState<boolean>(false)

  // Simulation state & test scenarios
  const [scenario, setScenario] = useState<'normal' | 'rank_deficient' | 'cyber_attack' | 'heatwave'>('normal')
  const [simResult, setSimResult] = useState<AgentSimulationResult | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [isPartitioning, setIsPartitioning] = useState<boolean>(false)
  const [selectedClusterId, setSelectedClusterId] = useState<number | null>(null)

  // Fetch installed plugins on mount
  const fetchPlugins = useCallback(async () => {
    try {
      const res = await fetch('/api/agents/plugins')
      if (res.ok) {
        const data = await res.json()
        setPlugins(data.plugins || [])
      }
    } catch (err) {
      console.warn('Could not fetch plugins:', err)
    }
  }, [])

  useEffect(() => {
    fetchPlugins()
  }, [fetchPlugins])

  // Partition network
  const handlePartition = useCallback(
    async (k = kClusters, method = partitionMethod) => {
      setIsPartitioning(true)
      try {
        const res = await fetch('/api/agents/partition', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            topology,
            k_clusters: k,
            method,
          }),
        })

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}))
          throw new Error(errData.detail || `HTTP ${res.status}`)
        }
        const data = await res.json()
        setClusters(data.clusters || [])
        toast.success(`Network partitioned into ${data.k_clusters} islands (${method === 'radial_feeder' ? 'Radial Tree' : 'Spectral'})`)
      } catch (err: any) {
        toast.error(`Partition error: ${err.message}`)
      } finally {
        setIsPartitioning(false)
      }
    },
    [topology, kClusters, partitionMethod]
  )

  // Auto-partition when topology changes or method changes
  useEffect(() => {
    handlePartition(kClusters, partitionMethod)
  }, [topology.id, partitionMethod])

  // Toggle plugin in registry
  const handleTogglePlugin = async (pluginId: string, enabled: boolean) => {
    try {
      const res = await fetch(`/api/agents/plugins/${pluginId}/toggle?enabled=${enabled}`, {
        method: 'POST',
      })
      if (res.ok) {
        setPlugins((prev) =>
          prev.map((p) => (p.plugin_id === pluginId ? { ...p, enabled } : p))
        )
        toast.success(`Plugin ${pluginId} ${enabled ? 'enabled' : 'disabled'}`)
      }
    } catch (err) {
      toast.error('Failed to toggle plugin')
    }
  }

  // Run simulation
  const handleRunSimulation = async () => {
    setIsLoading(true)
    try {
      let missingBuses: number[] = []
      let attacks: any[] = []
      let ambientTemp = 25.0

      if (scenario === 'rank_deficient') {
        const candidateBus = topology.buses.find((b) => b.type === 'pq') || topology.buses[1]
        if (candidateBus) {
          missingBuses = [candidateBus.id]
        }
      } else if (scenario === 'cyber_attack') {
        attacks = [
          {
            element: topology.buses[1]?.id ?? 2,
            kind: 'cyber_attack_coordinated',
            severity: 12.0,
          },
        ]
      } else if (scenario === 'heatwave') {
        ambientTemp = 42.0
      }

      const enabledPluginIds = plugins.filter((p) => p.enabled).map((p) => p.plugin_id)

      const res = await fetch('/api/agents/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topology,
          clusters: clusters.length > 0 ? clusters : undefined,
          k_clusters: kClusters,
          partition_method: partitionMethod,
          missing_measurement_buses: missingBuses,
          injected_attacks: attacks,
          ambient_temperature_c: ambientTemp,
          enabled_plugins: enabledPluginIds,
        }),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || 'Simulation failed')
      }

      const data: AgentSimulationResult = await res.json()
      setSimResult(data)

      if (data.clusters) {
        setClusters((prev) =>
          prev.map((cl) => {
            const upd = data.clusters[String(cl.cluster_id)]
            return upd ? { ...cl, ...upd } : cl
          })
        )
      }

      const cries = data.benchmark.distributed_multiagent.engineer_cries_triggered ?? 0
      if (cries > 0) {
        toast.warning(`Simulation completed: ${cries} "Engineer Cry" assistance events handled!`)
      } else {
        toast.success(`Distributed DSSE solved in ${data.benchmark.distributed_multiagent.execution_time_ms} ms`)
      }
    } catch (err: any) {
      toast.error(`Agent simulation error: ${err.message}`)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Plugin Manager Dialog */}
      <AgentPluginManagerDialog
        open={pluginDialogOpen}
        onOpenChange={setPluginDialogOpen}
        plugins={plugins}
        onTogglePlugin={handleTogglePlugin}
      />

      {/* Top Toolbar / Configuration Bar */}
      <Card className="border-border shadow-xs">
        <CardContent className="p-3 sm:p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            {/* Left Controls: Partitioning & Clusters */}
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2">
                <TreeStructure className="h-4 w-4 text-primary shrink-0" />
                <span className="text-xs font-semibold text-foreground">Clusters (K):</span>
                <div className="w-24">
                  <Slider
                    value={[kClusters]}
                    min={1}
                    max={Math.min(5, topology.buses.length)}
                    step={1}
                    onValueChange={(val) => {
                      setKClusters(val[0])
                      handlePartition(val[0], partitionMethod)
                    }}
                  />
                </div>
                <Badge variant="secondary" className="text-xs font-mono px-1.5 py-0">
                  {kClusters}
                </Badge>
              </div>

              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Method:</span>
                <Select
                  value={partitionMethod}
                  onValueChange={(v: 'spectral' | 'radial_feeder') => {
                    setPartitionMethod(v)
                    handlePartition(kClusters, v)
                  }}
                >
                  <SelectTrigger className="h-7 text-xs w-[140px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="spectral">Spectral Graph</SelectItem>
                    <SelectItem value="radial_feeder">Radial Feeder Tree</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs gap-1.5"
                onClick={() => handlePartition()}
                disabled={isPartitioning}
              >
                <ArrowsClockwise className={`h-3 w-3 ${isPartitioning ? 'animate-spin' : ''}`} />
                Re-Partition
              </Button>
            </div>

            {/* Right Controls: Scenario, Run DSSE, Plugins */}
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Scenario:</span>
                <Select value={scenario} onValueChange={(v: any) => setScenario(v)}>
                  <SelectTrigger className="h-7 text-xs w-[170px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="normal">Normal Operation</SelectItem>
                    <SelectItem value="rank_deficient">Rank Loss ("Engineer Cry")</SelectItem>
                    <SelectItem value="cyber_attack">Cyber-Attack Signature</SelectItem>
                    <SelectItem value="heatwave">Heatwave (Dynamic R_line)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs gap-1.5"
                onClick={() => setPluginDialogOpen(true)}
              >
                <PlugsConnected className="h-3.5 w-3.5 text-primary" />
                Plugins ({plugins.filter((p) => p.enabled).length})
              </Button>

              <Button
                size="sm"
                className="h-7 text-xs gap-1.5 font-medium shadow-xs"
                onClick={handleRunSimulation}
                disabled={isLoading || clusters.length === 0}
              >
                <Play weight="fill" className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />
                {isLoading ? 'Simulating...' : 'Run Agentic DSSE'}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Main Grid: Visual Topology Canvas (with Spatial & Tree Views) & Cluster Config */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Visual Map / Radial Feeder Tree (7 cols on desktop) */}
        <div className="lg:col-span-7 space-y-3">
          <AgentTopologyCanvas
            topology={topology}
            clusters={clusters}
            estimatedV={simResult?.estimated_v_pu}
            estimatedTheta={simResult?.estimated_theta_deg}
            selectedClusterId={selectedClusterId}
            onSelectCluster={setSelectedClusterId}
            initialViewMode={partitionMethod === 'radial_feeder' ? 'tree' : 'spatial'}
          />
        </div>

        {/* Cluster Architecture & Active Agent Teams (5 cols on desktop) */}
        <div className="lg:col-span-5">
          <AgentClusterConfigCard clusters={clusters} />
        </div>
      </div>

      {/* Centralized vs. Distributed Scalability Benchmark */}
      <AgentBenchmarkCard benchmark={simResult?.benchmark ?? null} isLoading={isLoading} />

      {/* Agent Event Log & "Engineer Cry" Timeline */}
      <AgentEventLogCard events={simResult?.event_log ?? []} />
    </div>
  )
}
