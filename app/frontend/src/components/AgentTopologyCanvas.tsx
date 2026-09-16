import { useMemo, useState, useEffect } from 'react'
import * as d3 from 'd3'
import type { Topology } from '@/lib/types'
import type { AgentClusterData } from '@/lib/agentTypes'
import { buildTopologyTree, type TopologyTreeNode } from '@/lib/networkTopology'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Network, TreeStructure } from '@phosphor-icons/react'

interface AgentTopologyCanvasProps {
  topology: Topology
  clusters: AgentClusterData[]
  estimatedV?: Record<string, number>
  estimatedTheta?: Record<string, number>
  selectedClusterId?: number | null
  onSelectCluster?: (clusterId: number | null) => void
  initialViewMode?: 'spatial' | 'tree'
}

const CLUSTER_COLORS = [
  { stroke: '#3b82f6', fill: 'rgba(59, 130, 246, 0.15)', name: 'Blue Island' },
  { stroke: '#10b981', fill: 'rgba(16, 185, 129, 0.15)', name: 'Emerald Island' },
  { stroke: '#8b5cf6', fill: 'rgba(139, 92, 246, 0.15)', name: 'Purple Island' },
  { stroke: '#0ea5e9', fill: 'rgba(14, 165, 233, 0.15)', name: 'Cyan Island' },
  { stroke: '#ec4899', fill: 'rgba(236, 72, 153, 0.15)', name: 'Rose Island' },
]

const BOUNDARY_COLOR = '#6366f1' // Refined Indigo for boundary tie-lines and interfaces

export function AgentTopologyCanvas({
  topology,
  clusters,
  estimatedV = {},
  estimatedTheta = {},
  selectedClusterId,
  onSelectCluster,
  initialViewMode = 'spatial',
}: AgentTopologyCanvasProps) {
  const [viewMode, setViewMode] = useState<'spatial' | 'tree'>(initialViewMode)
  const [hoveredBus, setHoveredBus] = useState<any | null>(null)

  useEffect(() => {
    if (initialViewMode) {
      setViewMode(initialViewMode)
    }
  }, [initialViewMode])

  // Map bus ID to cluster info
  const busToCluster = useMemo(() => {
    const map = new Map<number | string, { cluster_id: number; isBoundary: boolean }>()
    clusters.forEach((cl) => {
      const boundarySet = new Set(cl.boundary_bus_ids.map(String))
      cl.bus_ids.forEach((bId) => {
        map.set(String(bId), {
          cluster_id: cl.cluster_id,
          isBoundary: boundarySet.has(String(bId)),
        })
      })
    })
    return map
  }, [clusters])

  // ── 1. Spatial Layout Calculation ───────────────────────────────────────────
  const spatialNodes = useMemo(() => {
    const minX = Math.min(...topology.buses.map((b) => b.geoX ?? 100))
    const maxX = Math.max(...topology.buses.map((b) => b.geoX ?? 500))
    const minY = Math.min(...topology.buses.map((b) => b.geoY ?? 100))
    const maxY = Math.max(...topology.buses.map((b) => b.geoY ?? 500))

    const width = 760
    const height = 340
    const pad = 44

    return topology.buses.map((b, idx) => {
      let x = b.geoX ?? 100 + idx * 50
      let y = b.geoY ?? 150 + (idx % 2) * 50

      if (maxX > minX && maxY > minY) {
        x = pad + ((x - minX) / (maxX - minX)) * (width - 2 * pad)
        y = pad + ((y - minY) / (maxY - minY)) * (height - 2 * pad)
      }

      const clusterInfo = busToCluster.get(String(b.id))
      return {
        ...b,
        cx: x,
        cy: y,
        clusterId: clusterInfo?.cluster_id ?? 0,
        isBoundary: clusterInfo?.isBoundary ?? false,
      }
    })
  }, [topology, busToCluster])

  const spatialNodeMap = useMemo(() => new Map(spatialNodes.map((n) => [n.id, n])), [spatialNodes])

  // ── 2. Radial Tree Layout Calculation via D3 Hierarchy ──────────────────────
  const { treeNodes, treeLinks, treeExtraLinks } = useMemo(() => {
    const treeData = buildTopologyTree(topology)
    if (!treeData.root) {
      return { treeNodes: [], treeLinks: [], treeExtraLinks: [] }
    }

    const width = 760
    const height = 340
    const padX = 50
    const padY = 50

    const hierarchyRoot = d3.hierarchy<TopologyTreeNode>(treeData.root, (d) => d.children)
    // Left-to-right tree layout: x is vertical span, y is depth span
    const treeLayout = d3.tree<TopologyTreeNode>().size([height - 2 * padY, width - 2 * padX])
    treeLayout(hierarchyRoot)

    const nodesList: any[] = []
    hierarchyRoot.each((d: any) => {
      const bus = d.data.bus
      const clusterInfo = busToCluster.get(String(bus.id))
      nodesList.push({
        ...bus,
        cx: padX + d.y, // swap x and y for horizontal left-to-right feeder flow
        cy: padY + d.x,
        clusterId: clusterInfo?.cluster_id ?? 0,
        isBoundary: clusterInfo?.isBoundary ?? false,
        depth: d.depth,
      })
    })

    const nodeCoordMap = new Map(nodesList.map((n) => [n.id, n]))

    // Tree hierarchy links
    const linksList: any[] = []
    hierarchyRoot.links().forEach((link: any) => {
      const sourceNode = nodeCoordMap.get(link.source.data.bus.id)
      const targetNode = nodeCoordMap.get(link.target.data.bus.id)
      if (sourceNode && targetNode) {
        const isCrossCluster = sourceNode.clusterId !== targetNode.clusterId
        linksList.push({
          source: sourceNode,
          target: targetNode,
          isCrossCluster,
          line: link.target.data.parentLine,
        })
      }
    })

    // Extra meshed links
    const extraList: any[] = []
    treeData.extraLines.forEach((l) => {
      const sourceNode = nodeCoordMap.get(l.from)
      const targetNode = nodeCoordMap.get(l.to)
      if (sourceNode && targetNode) {
        const isCrossCluster = sourceNode.clusterId !== targetNode.clusterId
        extraList.push({
          source: sourceNode,
          target: targetNode,
          isCrossCluster,
          line: l,
        })
      }
    })

    return { treeNodes: nodesList, treeLinks: linksList, treeExtraLinks: extraList }
  }, [topology, busToCluster])

  const activeNodes = viewMode === 'tree' ? treeNodes : spatialNodes

  return (
    <div className="relative w-full rounded-lg border bg-card/60 backdrop-blur-xs overflow-hidden">
      {/* Top Header: Cluster Filters + View Mode Toggle */}
      <div className="flex items-center justify-between p-2.5 border-b bg-muted/20 flex-wrap gap-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[11px] font-semibold text-muted-foreground mr-1">Islands:</span>
          {clusters.length === 0 ? (
            <span className="text-xs text-muted-foreground italic">No clusters yet</span>
          ) : (
            clusters.map((cl, idx) => {
              const col = CLUSTER_COLORS[idx % CLUSTER_COLORS.length]
              const isSelected = selectedClusterId === cl.cluster_id
              return (
                <button
                  key={cl.cluster_id}
                  onClick={() => onSelectCluster?.(isSelected ? null : cl.cluster_id)}
                  className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium border transition-all ${
                    isSelected
                      ? 'border-primary bg-primary/20 text-primary font-bold shadow-xs'
                      : 'border-border/80 bg-background/80 hover:bg-muted/80 text-foreground'
                  }`}
                >
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: col.stroke }} />
                  <span>{cl.name}</span>
                </button>
              )
            })
          )}
        </div>

        {/* View Mode Switcher */}
        <div className="flex items-center rounded-md border bg-background p-0.5 gap-0.5">
          <Button
            variant={viewMode === 'spatial' ? 'secondary' : 'ghost'}
            size="sm"
            className="h-6 text-[11px] px-2 gap-1"
            onClick={() => setViewMode('spatial')}
          >
            <Network className="h-3.5 w-3.5" />
            Spatial Map
          </Button>
          <Button
            variant={viewMode === 'tree' ? 'secondary' : 'ghost'}
            size="sm"
            className="h-6 text-[11px] px-2 gap-1 text-primary font-medium"
            onClick={() => setViewMode('tree')}
          >
            <TreeStructure className="h-3.5 w-3.5" />
            Radial Feeder Tree
          </Button>
        </div>
      </div>

      {/* SVG Canvas */}
      <svg viewBox="0 0 760 340" className="w-full h-auto max-h-[380px] select-none p-2">
        {viewMode === 'spatial' ? (
          // ── Spatial Rendering ─────────────────────────────────────────────
          <>
            {topology.lines.map((l) => {
              const fromNode = spatialNodeMap.get(l.from)
              const toNode = spatialNodeMap.get(l.to)
              if (!fromNode || !toNode) return null

              const isCrossCluster = fromNode.clusterId !== toNode.clusterId
              const strokeColor = isCrossCluster
                ? BOUNDARY_COLOR
                : CLUSTER_COLORS[fromNode.clusterId % CLUSTER_COLORS.length].stroke

              return (
                <g key={l.id}>
                  <line
                    x1={fromNode.cx}
                    y1={fromNode.cy}
                    x2={toNode.cx}
                    y2={toNode.cy}
                    stroke={strokeColor}
                    strokeWidth={isCrossCluster ? 2.5 : 2}
                    strokeDasharray={isCrossCluster ? '5 4' : undefined}
                    opacity={
                      selectedClusterId === null ||
                      fromNode.clusterId === selectedClusterId ||
                      toNode.clusterId === selectedClusterId
                        ? 0.9
                        : 0.25
                    }
                  />
                  {isCrossCluster && (
                    <circle
                      cx={(fromNode.cx + toNode.cx) / 2}
                      cy={(fromNode.cy + toNode.cy) / 2}
                      r={3.5}
                      fill={BOUNDARY_COLOR}
                    />
                  )}
                </g>
              )
            })}
          </>
        ) : (
          // ── Radial Tree Rendering ─────────────────────────────────────────
          <>
            {/* Tree Hierarchy Links */}
            {treeLinks.map((link, idx) => {
              const strokeColor = link.isCrossCluster
                ? BOUNDARY_COLOR
                : CLUSTER_COLORS[link.source.clusterId % CLUSTER_COLORS.length].stroke
              const pathD = `M ${link.source.cx} ${link.source.cy} C ${(link.source.cx + link.target.cx) / 2} ${link.source.cy}, ${(link.source.cx + link.target.cx) / 2} ${link.target.cy}, ${link.target.cx} ${link.target.cy}`

              return (
                <g key={`tree-link-${idx}`}>
                  <path
                    d={pathD}
                    fill="none"
                    stroke={strokeColor}
                    strokeWidth={link.isCrossCluster ? 2.5 : 2}
                    strokeDasharray={link.isCrossCluster ? '5 4' : undefined}
                    opacity={
                      selectedClusterId === null ||
                      link.source.clusterId === selectedClusterId ||
                      link.target.clusterId === selectedClusterId
                        ? 0.95
                        : 0.2
                    }
                  />
                  {link.isCrossCluster && (
                    <circle
                      cx={(link.source.cx + link.target.cx) / 2}
                      cy={(link.source.cy + link.target.cy) / 2}
                      r={3.5}
                      fill={BOUNDARY_COLOR}
                    />
                  )}
                </g>
              )
            })}

            {/* Extra Meshed Cross-Links (Dashed) */}
            {treeExtraLinks.map((link, idx) => {
              const strokeColor = link.isCrossCluster
                ? BOUNDARY_COLOR
                : CLUSTER_COLORS[link.source.clusterId % CLUSTER_COLORS.length].stroke
              const pathD = `M ${link.source.cx} ${link.source.cy} Q ${(link.source.cx + link.target.cx) / 2} ${Math.min(link.source.cy, link.target.cy) - 25} ${link.target.cx} ${link.target.cy}`

              return (
                <path
                  key={`extra-link-${idx}`}
                  d={pathD}
                  fill="none"
                  stroke={strokeColor}
                  strokeWidth={1.5}
                  strokeDasharray="3 3"
                  opacity={0.5}
                />
              )
            })}
          </>
        )}

        {/* Draw Nodes (shared for both views) */}
        {activeNodes.map((node) => {
          const col = CLUSTER_COLORS[node.clusterId % CLUSTER_COLORS.length]
          const isSelected = selectedClusterId === null || selectedClusterId === node.clusterId
          const isHovered = hoveredBus?.id === node.id

          return (
            <g
              key={node.id}
              className="cursor-pointer"
              onMouseEnter={() => setHoveredBus(node)}
              onMouseLeave={() => setHoveredBus(null)}
              opacity={isSelected ? 1 : 0.25}
            >
              {/* Boundary Bus Halo */}
              {node.isBoundary && (
                <circle
                  cx={node.cx}
                  cy={node.cy}
                  r={15}
                  fill="none"
                  stroke={BOUNDARY_COLOR}
                  strokeWidth={2}
                  strokeDasharray="3 3"
                />
              )}

              {/* Node Circle */}
              <circle
                cx={node.cx}
                cy={node.cy}
                r={isHovered ? 11 : 9}
                fill={col.stroke}
                stroke="#ffffff"
                strokeWidth={2}
                className="transition-all duration-150 shadow-md"
              />

              {/* Node Label */}
              <text
                x={node.cx}
                y={node.cy + 20}
                textAnchor="middle"
                className="text-[10px] font-mono font-medium fill-foreground"
              >
                {node.name || `B${node.id}`}
              </text>
            </g>
          )
        })}
      </svg>

      {/* Floating Hover Tooltip */}
      {hoveredBus && (
        <div className="absolute bottom-2 right-2 z-20 rounded-md border bg-background/95 p-2.5 shadow-md text-xs backdrop-blur-xs space-y-1 pointer-events-none">
          <div className="font-semibold flex items-center justify-between gap-3">
            <span>Bus {hoveredBus.name || hoveredBus.id}</span>
            <Badge variant="outline" className="text-[10px] py-0 px-1">
              Island {hoveredBus.clusterId}
            </Badge>
          </div>
          <div className="text-[11px] text-muted-foreground space-y-0.5 font-mono">
            {estimatedV[hoveredBus.id] !== undefined && (
              <div>V_est: {estimatedV[hoveredBus.id].toFixed(4)} pu</div>
            )}
            {estimatedTheta[hoveredBus.id] !== undefined && (
              <div>θ_est: {estimatedTheta[hoveredBus.id].toFixed(2)}°</div>
            )}
            {hoveredBus.isBoundary && (
              <div className="text-indigo-600 dark:text-indigo-400 font-semibold">Boundary Tie Node</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
