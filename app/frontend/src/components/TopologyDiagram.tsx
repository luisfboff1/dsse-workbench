import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as d3 from 'd3'
import type { MeasurementKind, PowerFlowResult, Topology } from '@/lib/types'
import { buildTopologyTree, getTopologySwitches, type TopologyTreeNode } from '@/lib/networkTopology'
import { MEASUREMENT_KINDS, MEASUREMENT_KIND_INFO, buildMeasurementIndex, getMeasurement, getLineMeasurement } from '@/lib/measurements'
import {
  LARGE_NETWORK_BUSES,
  computeRadialLayout,
  computeSpatialLayout,
  computeTreeLayout,
  pickGlyphSwitches,
} from '@/lib/topologyLayout'
import { TopologyCanvasView, type TopologyCanvasHandle } from '@/components/TopologyCanvasView'
import { useVirtualRows } from '@/hooks/useVirtualRows'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverAnchor, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Network, TreeStructure, ArrowsOut, ArrowsDownUp, ArrowsLeftRight, Gauge, List, X, ToggleRight, ArrowCounterClockwise, Lightning, Sparkle, Atom } from '@phosphor-icons/react'
import type { Switch as SwitchType } from '@/lib/types'

interface TopologyDiagramProps {
  topology: Topology
  result?: PowerFlowResult | null
  voltageLimits?: { min: number; max: number }
  compact?: boolean
  /** Omit to render read-only (no click-to-assign popover, no meter badges). */
  onMeasurementKindChange?: (busId: number, kind: MeasurementKind | 'none') => void
  /** Same convention, for a line-flow (branch) meter instead of a bus meter.
   *  Works in both spatial and tree view (tree edges resolve their real
   *  topology.lines id via TopologyTreeNode.parentLine — see
   *  buildTopologyTree in networkTopology.ts). Omit to render without line
   *  click-to-assign. */
  onLineMeasurementKindChange?: (lineId: number, kind: MeasurementKind | 'none') => void
  /** Apply a single meter kind to all buses, all lines, or both at once.
   *  Exposed by the "Apply to all" bar at the top of the Meters panel. */
  onApplyMeterToAll?: (kind: MeasurementKind, target: 'buses' | 'lines' | 'both') => void
  /** Open (false) or close (true) a switch identified by its id.
   *  Closing means closed=true, opening means closed=false. */
  onSwitchToggle?: (switchId: number, closed: boolean) => void
  /** Reset all switches to the default configuration (e.g. pristine pandapower case). */
  onResetSwitches?: () => void
}

type ViewMode = 'spatial' | 'tree'
type TreeOrientation = 'vertical' | 'horizontal'

interface Node extends d3.SimulationNodeDatum {
  id: number
  name: string
  type: string
  pGen: number
  qGen: number
  pLoad: number
  qLoad: number
  pGenDG?: number
  measurementKind?: MeasurementKind
  x?: number
  y?: number
  fx?: number | null
  fy?: number | null
}

interface Link {
  id: number
  from: number
  to: number
  lineMeasurementKind?: MeasurementKind
}

const TREE_PADDING = 44
// [sibling spacing, level spacing] for d3.tree().nodeSize — tuned for the
// bus-bar tick + id label + load arrow stacked around each node, see
// drawBusBars below.
const TREE_NODE_SIZE: [number, number] = [46, 90]
const TREE_TICK_HALF = 9
const LOAD_ARROW_MARKER_ID = 'topology-tree-load-arrow'
// Fixed row heights for the windowed side-panel lists — useVirtualRows needs
// them to map scrollTop onto a row range without measuring the DOM.
const METER_ROW_HEIGHT = 24
const SWITCH_ROW_HEIGHT = 46

// Shared meter-kind picker body — used both by the diagram's click-to-assign
// popovers (anchored to click coords) and by the side panel's per-row
// popovers (anchored to the row itself via PopoverTrigger).
function MeterKindMenu({
  activeKind,
  onSelect,
  noneLabel,
}: {
  activeKind?: MeasurementKind
  onSelect: (kind: MeasurementKind | 'none') => void
  noneLabel: string
}) {
  return (
    <div className="space-y-1">
      {MEASUREMENT_KINDS.map((kind) => (
        <button
          key={kind}
          type="button"
          onClick={() => onSelect(kind)}
          className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-muted ${activeKind === kind ? 'bg-muted font-semibold' : ''}`}
        >
          <Gauge weight="fill" className="h-3.5 w-3.5" style={{ color: MEASUREMENT_KIND_INFO[kind].colorVar }} />
          {MEASUREMENT_KIND_INFO[kind].shortLabel}
        </button>
      ))}
      <button
        type="button"
        onClick={() => onSelect('none')}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted"
      >
        {noneLabel}
      </button>
    </div>
  )
}

function elbowPath(source: Node, target: Node, orientation: TreeOrientation): string {
  const sx = source.x ?? 0
  const sy = source.y ?? 0
  const tx = target.x ?? 0
  const ty = target.y ?? 0
  if (orientation === 'vertical') {
    const midY = (sy + ty) / 2
    return `M${sx},${sy} L${sx},${midY} L${tx},${midY} L${tx},${ty}`
  }
  const midX = (sx + tx) / 2
  return `M${sx},${sy} L${midX},${sy} L${midX},${ty} L${tx},${ty}`
}

export function TopologyDiagram({ topology, result, voltageLimits, compact = false, onMeasurementKindChange, onLineMeasurementKindChange, onApplyMeterToAll, onSwitchToggle, onResetSwitches }: TopologyDiagramProps) {
  // Memoized: getTopologySwitches walks every line to synthesize a switch per
  // branch, and this used to re-run on every single React render (a hover, a
  // popover open) rather than only when the topology actually changed.
  const allSwitches = useMemo(() => getTopologySwitches(topology), [topology])
  const svgRef = useRef<SVGSVGElement>(null)
  const canvasHandleRef = useRef<TopologyCanvasHandle>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null)
  // Last settled force-layout position per bus id, carried across redraws —
  // without this, every redraw (e.g. just toggling a meter) rebuilds the
  // nodes array from scratch with no x/y, so d3 restarts the simulation from
  // its default layout and every node visually jumps.
  const positionsRef = useRef<Map<number, { x: number; y: number }>>(new Map())
  // Signature of everything that should re-fit the zoom/pan (structure,
  // panel size, view mode/orientation) — a redraw triggered by something
  // else (meter change, power-flow result) keeps whatever pan/zoom the user
  // already set instead of snapping back to fitToView.
  const structureKeyRef = useRef<string | null>(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 })
  const [viewMode, setViewMode] = useState<ViewMode>('spatial')
  // Left-right by default: this panel is wider than it is tall, so a
  // horizontal feeder trunk wastes less space than a top-down one.
  const [orientation, setOrientation] = useState<TreeOrientation>('horizontal')
  const [meterPopover, setMeterPopover] = useState<{ busId: number; x: number; y: number } | null>(null)
  const [lineMeterPopover, setLineMeterPopover] = useState<{ lineId: number; x: number; y: number } | null>(null)
  const [metersPanelOpen, setMetersPanelOpen] = useState(false)
  const [switchesPanelOpen, setSwitchesPanelOpen] = useState(false)
  // "Apply to all" bar local state — persists within the panel session
  const [applyKind, setApplyKind] = useState<MeasurementKind>('scada')
  const [applyTarget, setApplyTarget] = useState<'buses' | 'lines' | 'both'>('buses')

  // ── Which renderer draws the diagram ────────────────────────────────────
  // 'auto' switches to the canvas renderer past LARGE_NETWORK_BUSES. The SVG
  // renderer stays the default for small networks: at that size its per-node
  // niceties (native <title> tooltips, DOM-anchored popovers, text that stays
  // crisp at any zoom) cost nothing, and keeping it means the IEEE test
  // feeders look and behave exactly as they always have. Past the threshold
  // its element count — 6-10 SVG nodes per bus plus up to 3 per line — is
  // what makes the tab crawl, so the canvas takes over. Manual override is
  // exposed as the Fast/Detailed button.
  const [rendererPref, setRendererPref] = useState<'auto' | 'svg' | 'canvas'>('auto')
  // Off by default. The force simulation is a nicety, not information: it
  // costs seconds of blocked main thread on a few-thousand-bus network and
  // settles into a hairball at the zoom where one fits on screen. The default
  // is the concentric BFS-depth layout in computeRadialLayout, which is O(n),
  // deterministic, and actually encodes distance from the substation. Kept as
  // a toggle because on a small network it does read nicely.
  const [useForceLayout, setUseForceLayout] = useState(false)
  const isLargeNetwork = topology.buses.length > LARGE_NETWORK_BUSES
  const renderer = rendererPref === 'auto' ? (isLargeNetwork ? 'canvas' : 'svg') : rendererPref
  // Per-node text and badges. Tied to network size rather than to the
  // renderer, so forcing the canvas on a small network keeps its labels.
  const detailed = !isLargeNetwork

  const measurementIndex = useMemo(() => buildMeasurementIndex(topology), [topology])

  // Layout for the canvas renderer — pure geometry, no DOM. Recomputed only
  // when something that moves a node changes; a meter toggle re-runs it too
  // (measurement kinds live on the nodes) but that is O(n), not a re-layout,
  // because the force simulation resumes from the settled positions.
  const canvasLayout = useMemo(() => {
    if (renderer !== 'canvas') return null
    const base =
      viewMode === 'spatial'
        ? computeSpatialLayout(topology, dimensions.width, dimensions.height, positionsRef.current, useForceLayout)
        : computeTreeLayout(topology, orientation, TREE_NODE_SIZE, TREE_PADDING)
    for (const node of base.nodes) positionsRef.current.set(node.id, { x: node.x, y: node.y })
    const glyphSwitches = pickGlyphSwitches(allSwitches, detailed)
    const switchLinks = allSwitches
      .filter((sw) => !sw.closed && base.nodeById.has(sw.from) && base.nodeById.has(sw.to))
      .map((sw) => ({ from: sw.from, to: sw.to, label: '' }))
    return {
      ...base,
      switchLinks,
      glyphSwitches: glyphSwitches.filter((sw) => base.nodeById.has(sw.from) && base.nodeById.has(sw.to)),
    }
  }, [renderer, viewMode, orientation, topology, dimensions.width, dimensions.height, allSwitches, detailed, useForceLayout])

  // Same idea as structureKeyRef below, for the canvas: only a layout-
  // affecting change re-fits the view, so toggling a meter or landing a
  // power-flow result keeps the pan/zoom the user set.
  const canvasFitKey = useMemo(
    () =>
      [
        topology.id,
        topology.buses.length,
        topology.lines.length,
        allSwitches.filter((s) => !s.closed).length,
        dimensions.width,
        dimensions.height,
        viewMode,
        orientation,
      ].join('|'),
    [topology.id, topology.buses.length, topology.lines.length, allSwitches, dimensions, viewMode, orientation]
  )

  const handleCanvasBusClick = useCallback(
    (busId: number, hit: { x: number; y: number }) => setMeterPopover({ busId, x: hit.x, y: hit.y }),
    []
  )
  const handleCanvasLineClick = useCallback(
    (lineId: number, hit: { x: number; y: number }) => setLineMeterPopover({ lineId, x: hit.x, y: hit.y }),
    []
  )
  const handleCanvasNodeMoved = useCallback((busId: number, x: number, y: number) => {
    positionsRef.current.set(busId, { x, y })
  }, [])

  // ── Side panels ─────────────────────────────────────────────────────────
  // Windowed rows: see useVirtualRows. Row heights are fixed so the window
  // can be computed from scrollTop alone.
  const busMeterRows = useVirtualRows(topology.buses.length, METER_ROW_HEIGHT)
  const lineMeterRows = useVirtualRows(topology.lines.length, METER_ROW_HEIGHT)
  const switchRows = useVirtualRows(allSwitches.length, SWITCH_ROW_HEIGHT)

  // Panel rows reuse the diagram's single meter popover instead of each
  // mounting one of their own — anchored to the row, in container coords.
  const anchorFromRow = (element: HTMLElement) => {
    const container = containerRef.current?.getBoundingClientRect()
    if (!container) return null
    const row = element.getBoundingClientRect()
    return { x: row.left - container.left, y: row.top - container.top + row.height / 2 }
  }
  const openBusMeterPopover = (busId: number, element: HTMLElement) => {
    const anchor = anchorFromRow(element)
    if (anchor) setMeterPopover({ busId, ...anchor })
  }
  const openLineMeterPopover = (lineId: number, element: HTMLElement) => {
    const anchor = anchorFromRow(element)
    if (anchor) setLineMeterPopover({ lineId, ...anchor })
  }

  // Measured off containerRef, not the <svg>: with the canvas renderer active
  // there is no <svg> in the tree at all, and reading its parent left the
  // diagram stuck at the 800x600 default.
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const apply = () => {
      const width = container.clientWidth
      if (!width) return
      const height = Math.max(compact ? 420 : 500, Math.min(compact ? 520 : 600, width * 0.72))
      setDimensions((prev) => (prev.width === width && prev.height === height ? prev : { width, height }))
    }
    apply()
    const observer = new ResizeObserver(apply)
    observer.observe(container)
    return () => observer.disconnect()
  }, [compact])

  const fitToView = () => {
    if (renderer === 'canvas') {
      canvasHandleRef.current?.fit()
      return
    }
    if (!svgRef.current || !zoomRef.current) return
    const svg = d3.select(svgRef.current)
    const gNode = svg.select<SVGGElement>('g.diagram-root').node()
    if (!gNode) return
    const bounds = gNode.getBBox()
    if (!bounds.width || !bounds.height) return
    const { width, height } = dimensions
    const padding = 48
    // Capped well below the old 2.5x: a small topology (few buses, tight
    // force-simulation cluster) has a small bounding box, so a high cap just
    // blows the nodes up to fill whatever panel width is available instead
    // of rendering at a legible-but-compact size.
    const scale = Math.max(
      Math.min((width - padding * 2) / bounds.width, (height - padding * 2) / bounds.height, 1.5),
      0.05
    )
    const tx = width / 2 - scale * (bounds.x + bounds.width / 2)
    const ty = height / 2 - scale * (bounds.y + bounds.height / 2)
    svg
      .transition()
      .duration(400)
      .call(zoomRef.current.transform, d3.zoomIdentity.translate(tx, ty).scale(scale))
  }

  useEffect(() => {
    if (!svgRef.current || !topology.buses.length) return

    const { width, height } = dimensions
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    // The canvas renderer owns the drawing at this size — bail before
    // building tens of thousands of SVG elements nobody will look at.
    if (renderer === 'canvas') return

    // Only actual layout-affecting changes re-fit the view — a meter
    // toggle or a fresh power-flow result redraws in place.
    const structureKey = JSON.stringify({
      buses: topology.buses.map((b) => [b.id, b.geoX, b.geoY]),
      lines: topology.lines.map((l) => [l.id, l.from, l.to]),
      switches: allSwitches.filter(s => !s.closed).map((s) => [s.from, s.to]),
      width,
      height,
      viewMode,
      orientation,
    })
    const shouldFit = structureKeyRef.current !== structureKey
    structureKeyRef.current = structureKey

    const busResults = new Map((result?.buses ?? []).map((bus) => [bus.id, bus]))
    const lineResults = new Map((result?.lines ?? []).map((line) => [line.id, line]))
    const vMin = voltageLimits?.min ?? 0.95
    const vMax = voltageLimits?.max ?? 1.05

    const voltageColor = (voltage?: number) => {
      if (voltage == null) return 'var(--color-muted)'
      if (voltage < vMin) return 'var(--color-status-info)'
      if (voltage > vMax) return 'var(--color-destructive)'
      return 'var(--color-status-good)'
    }

    const g = svg.append('g').attr('class', 'diagram-root')
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.05, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform)
      })
    svg.call(zoom)
    zoomRef.current = zoom

    // Click a bus to open the meter-assignment popover — position is the
    // click's screen coords relative to the diagram's own container (not
    // the zoomed/panned SVG data space), since the popover itself is a
    // normal React overlay positioned with plain CSS, not an SVG element.
    function attachMeasurementClick(sel: d3.Selection<d3.BaseType, Node, SVGGElement, unknown>) {
      if (!onMeasurementKindChange) return
      sel
        .style('cursor', 'pointer')
        .on('click', (event: MouseEvent, d: Node) => {
          event.stopPropagation()
          const rect = containerRef.current?.getBoundingClientRect()
          if (!rect) return
          setMeterPopover({ busId: d.id, x: event.clientX - rect.left, y: event.clientY - rect.top })
        })
    }

    // Small colored badge showing the assigned meter kind — 'onNode' picks
    // where it sits (differs between the circle layout and the bus-bar tick
    // layout, both drawn elsewhere in this effect).
    function drawMeasurementBadge(sel: d3.Selection<d3.BaseType, Node, SVGGElement, unknown>, dx: number, dy: number) {
      if (!onMeasurementKindChange) return
      const badge = sel.filter((d: Node) => !!d.measurementKind).append('g').attr('transform', `translate(${dx}, ${dy})`)
      badge
        .append('circle')
        .attr('r', 8)
        .attr('fill', 'var(--color-card)')
        .attr('stroke', (d: Node) => (d.measurementKind ? MEASUREMENT_KIND_INFO[d.measurementKind].colorVar : 'var(--color-border)'))
        .attr('stroke-width', 2)
      badge
        .append('text')
        .attr('text-anchor', 'middle')
        .attr('dy', 3)
        .attr('font-size', 9)
        .attr('font-weight', 700)
        .attr('fill', (d: Node) => (d.measurementKind ? MEASUREMENT_KIND_INFO[d.measurementKind].colorVar : 'var(--color-foreground)'))
        .text((d: Node) => (d.measurementKind ? MEASUREMENT_KIND_INFO[d.measurementKind].shortLabel[0] : '?'))
    }

    // Click a line to open the same meter-assignment popover, for a
    // branch-flow meter instead of a bus one. A raw <line>/<path> stroke is
    // a thin, hard-to-click target, so this draws an invisible wider
    // "hit area" on top carrying the click handler, positioned identically
    // to the visible link — same idea as attachMeasurementClick above, just
    // needs its own overlay since links (unlike bus circles) have no real
    // click area otherwise.
    function attachLineMeasurementClick(
      parent: d3.Selection<SVGGElement, unknown, null, undefined>,
      links: Link[],
      pathFn: (d: Link) => string | null
    ) {
      if (!onLineMeasurementKindChange) return null
      const hit = parent
        .append('g')
        .selectAll('path')
        .data(links)
        .join('path')
        .attr('fill', 'none')
        .attr('stroke', 'transparent')
        .attr('stroke-width', 14)
        .style('cursor', 'pointer')
        .on('click', (event: MouseEvent, d: Link) => {
          event.stopPropagation()
          const rect = containerRef.current?.getBoundingClientRect()
          if (!rect) return
          setLineMeterPopover({ lineId: d.id, x: event.clientX - rect.left, y: event.clientY - rect.top })
        })
      const position = () => hit.attr('d', (d) => pathFn(d) ?? '')
      return { sel: hit, position }
    }

    // Small colored dot at the line's midpoint showing the assigned line
    // meter kind — mirrors drawMeasurementBadge's bus badge, positioned via
    // the same midpoint math each link's label already uses.
    function drawLineMeasurementBadge(
      parent: d3.Selection<SVGGElement, unknown, null, undefined>,
      links: Link[],
      nodeById: Map<number, Node>
    ) {
      if (!onLineMeasurementKindChange) return null
      const metered = links.filter((d) => d.lineMeasurementKind)
      const sel = parent
        .append('g')
        .attr('class', 'line-meter-badges')
        .selectAll('g')
        .data(metered)
        .join('g')
        .style('pointer-events', 'none')
      sel
        .append('circle')
        .attr('r', 6)
        .attr('fill', 'var(--color-card)')
        .attr('stroke', (d: Link) => MEASUREMENT_KIND_INFO[d.lineMeasurementKind!].colorVar)
        .attr('stroke-width', 1.75)
      sel
        .append('text')
        .attr('text-anchor', 'middle')
        .attr('dy', 2.5)
        .attr('font-size', 7.5)
        .attr('font-weight', 700)
        .attr('fill', (d: Link) => MEASUREMENT_KIND_INFO[d.lineMeasurementKind!].colorVar)
        .text((d: Link) => MEASUREMENT_KIND_INFO[d.lineMeasurementKind!].shortLabel[0])
      const position = () => {
        sel.attr('transform', (d) => {
          const from = nodeById.get(d.from)
          const to = nodeById.get(d.to)
          if (!from || !to) return ''
          // Positioned near sending bus (20% along the line)
          const fx = from.x ?? 0
          const fy = from.y ?? 0
          const tx = to.x ?? 0
          const ty = to.y ?? 0
          const x = fx * 0.8 + tx * 0.2
          const y = fy * 0.8 + ty * 0.2
          return `translate(${x},${y})`
        })
      }
      return { sel, position }
    }

    // ── Shared visual encoding — same node/link appearance regardless of how
    // x/y were computed (force simulation, fixed geo-coords, or tree layout).
    const maxAbsFlow = Math.max(
      0.0001,
      ...topology.lines.map((line) => Math.abs(lineResults.get(line.id)?.pFrom ?? 0))
    )

    function drawLinks(parent: d3.Selection<SVGGElement, unknown, null, undefined>, links: Link[], nodeById: Map<number, Node>) {
      const sel = parent
        .append('g')
        .selectAll('line')
        .data(links)
        .join('line')
        .attr('stroke', (d: Link) => (lineResults.has(d.id) ? 'var(--color-status-warn)' : 'var(--color-accent)'))
        .attr('stroke-width', (d: Link) => {
          const flow = Math.abs(lineResults.get(d.id)?.pFrom ?? 0)
          return result ? 1.5 + 5 * (flow / maxAbsFlow) : 2
        })
        .attr('stroke-opacity', result ? 0.78 : 0.6)

      const labels = parent
        .append('g')
        .selectAll('text')
        .data(links)
        .join('text')
        .attr('font-size', 9.5)
        .attr('fill', 'var(--color-muted-foreground)')
        .attr('text-anchor', 'middle')
        .text((d: Link) => {
          const solved = lineResults.get(d.id)
          return solved ? `L${d.id} ${Math.abs(solved.pFrom).toFixed(2)} pu` : `L${d.id}`
        })

      const position = () => {
        sel
          .attr('x1', (d) => nodeById.get(d.from)?.x ?? 0)
          .attr('y1', (d) => nodeById.get(d.from)?.y ?? 0)
          .attr('x2', (d) => nodeById.get(d.to)?.x ?? 0)
          .attr('y2', (d) => nodeById.get(d.to)?.y ?? 0)
        labels
          // Positioned near receiving bus (80% along the line)
          .attr('x', (d) => {
            const fx = nodeById.get(d.from)?.x ?? 0
            const tx = nodeById.get(d.to)?.x ?? 0
            return fx * 0.2 + tx * 0.8
          })
          .attr('y', (d) => {
            const fy = nodeById.get(d.from)?.y ?? 0
            const ty = nodeById.get(d.to)?.y ?? 0
            return fy * 0.2 + ty * 0.8 - 6
          })
      }
      return { sel, labels, position }
    }

    function drawDashedLinks(
      parent: d3.Selection<SVGGElement, unknown, null, undefined>,
      links: { from: number; to: number; label: string }[],
      nodeById: Map<number, Node>,
      color: string
    ) {
      const sel = parent
        .append('g')
        .selectAll('line')
        .data(links)
        .join('line')
        .attr('stroke', color)
        .attr('stroke-width', 1.5)
        .attr('stroke-dasharray', '5,4')
        .attr('stroke-opacity', 0.6)

      const labels = parent
        .append('g')
        .selectAll('text')
        .data(links.filter((d) => Boolean(d.label)))
        .join('text')
        .attr('font-size', 9)
        .attr('font-style', 'italic')
        .attr('fill', color)
        .attr('text-anchor', 'middle')
        .text((d) => d.label)

      const position = () => {
        sel
          .attr('x1', (d) => nodeById.get(d.from)?.x ?? 0)
          .attr('y1', (d) => nodeById.get(d.from)?.y ?? 0)
          .attr('x2', (d) => nodeById.get(d.to)?.x ?? 0)
          .attr('y2', (d) => nodeById.get(d.to)?.y ?? 0)
        labels
          .attr('x', (d) => ((nodeById.get(d.from)?.x ?? 0) + (nodeById.get(d.to)?.x ?? 0)) / 2)
          .attr('y', (d) => ((nodeById.get(d.from)?.y ?? 0) + (nodeById.get(d.to)?.y ?? 0)) / 2 - 6)
      }
      return { sel, labels, position }
    }

    function drawSwitchGlyphs(
      parent: d3.Selection<SVGGElement, unknown, null, undefined>,
      switchesList: SwitchType[],
      nodeById: Map<number, Node>,
      onToggle?: (id: number, closed: boolean) => void
    ) {
      const validSwitches = switchesList.filter(
        (sw) => nodeById.has(sw.from) && nodeById.has(sw.to)
      )
      const sel = parent
        .append('g')
        .attr('class', 'switch-glyphs')
        .selectAll('g')
        .data(validSwitches)
        .join('g')
        .style('cursor', onToggle ? 'pointer' : 'default')

      // Transparent hit area for easy clicking
      sel
        .append('rect')
        .attr('x', -10)
        .attr('y', -8)
        .attr('width', 20)
        .attr('height', 16)
        .attr('fill', 'transparent')

      // For open switches: mask the dashed line directly beneath the gap
      const openSel = sel.filter((d) => !d.closed)
      openSel
        .append('rect')
        .attr('x', -6)
        .attr('y', -6)
        .attr('width', 12)
        .attr('height', 12)
        .attr('fill', 'var(--color-card)')

      // Terminal 1 (dot)
      sel
        .append('circle')
        .attr('cx', -4.5)
        .attr('cy', 0)
        .attr('r', 1.8)
        .attr('fill', 'var(--color-foreground)')

      // Terminal 2 (dot)
      sel
        .append('circle')
        .attr('cx', 4.5)
        .attr('cy', 0)
        .attr('r', 1.8)
        .attr('fill', 'var(--color-foreground)')

      // Closed blade (connects straight: •—•)
      const closedSel = sel.filter((d) => Boolean(d.closed))
      closedSel
        .append('line')
        .attr('x1', -4.5)
        .attr('y1', 0)
        .attr('x2', 4.5)
        .attr('y2', 0)
        .attr('stroke', 'var(--color-foreground)')
        .attr('stroke-width', 1.5)

      // Open blade (angled open: • / •)
      openSel
        .append('line')
        .attr('x1', -4.5)
        .attr('y1', 0)
        .attr('x2', 1)
        .attr('y2', -4.5)
        .attr('stroke', 'var(--color-foreground)')
        .attr('stroke-width', 1.5)
        .attr('stroke-linecap', 'round')

      // Tooltip
      sel
        .append('title')
        .text(
          (d) =>
            `${d.name ?? `SW ${d.id}`} (${d.from}↔${d.to}) · ${d.closed ? 'Closed (click to open)' : 'Open (click to close)'}`
        )

      // Click handler
      if (onToggle) {
        sel.on('click', (event, d) => {
          event.stopPropagation()
          onToggle(d.id, !d.closed)
        })
      }

      const position = () => {
        sel.attr('transform', (d) => {
          const from = nodeById.get(d.from)
          const to = nodeById.get(d.to)
          if (!from || !to) return ''
          const fx = from.x ?? 0
          const fy = from.y ?? 0
          const tx = to.x ?? 0
          const ty = to.y ?? 0
          const mx = (fx + tx) / 2
          const my = (fy + ty) / 2
          const angle = (Math.atan2(ty - fy, tx - fx) * 180) / Math.PI
          return `translate(${mx},${my}) rotate(${angle})`
        })
      }

      return { sel, position }
    }

    function drawNodes(parent: d3.Selection<SVGGElement, unknown, null, undefined>, nodes: Node[]) {
      const sel = parent.append('g').selectAll('g').data(nodes).join('g')

      sel
        .append('circle')
        .attr('r', (d: Node) => {
          if (d.type === 'slack') return 22
          if (d.type === 'pv') return 18
          return 15
        })
        .attr('fill', (d: Node) => {
          const solvedVoltage = busResults.get(d.id)?.voltage
          if (result && solvedVoltage != null) return voltageColor(solvedVoltage)
          if (d.type === 'slack') return 'var(--color-primary)'
          if (d.type === 'pv') return 'var(--color-accent)'
          return 'var(--color-muted)'
        })
        .attr('stroke', 'var(--color-foreground)')
        .attr('stroke-width', 2)

      sel
        .append('text')
        .attr('text-anchor', 'middle')
        .attr('dy', 4)
        .attr('font-size', 10.5)
        .attr('font-weight', 600)
        .attr('fill', (d: Node) => {
          const solved = busResults.get(d.id)
          if (result && solved && solved.voltage >= vMin && solved.voltage <= vMax) return 'var(--color-primary-foreground)'
          return d.type === 'pq' ? 'var(--color-foreground)' : 'var(--color-primary-foreground)'
        })
        .text((d: Node) => d.id)

      if (result) {
        sel
          .append('text')
          .attr('text-anchor', 'middle')
          .attr('dy', -28)
          .attr('font-size', 9)
          .attr('font-weight', 700)
          .attr('fill', 'var(--color-foreground)')
          .text((d: Node) => {
            const solved = busResults.get(d.id)
            return solved ? `${solved.voltage.toFixed(3)} pu` : ''
          })
      }

      const genIndicator = sel.filter((d: Node) => d.pGen > 0).append('g').attr('transform', 'translate(15, -15)')
      genIndicator.append('circle').attr('r', 6.5).attr('fill', 'var(--color-status-good)').attr('stroke', 'var(--color-foreground)').attr('stroke-width', 1)
      genIndicator.append('text').attr('text-anchor', 'middle').attr('dy', 3.5).attr('font-size', 8.5).attr('font-weight', 600).attr('fill', 'var(--color-primary-foreground)').text('G')

      const loadIndicator = sel.filter((d: Node) => d.pLoad > 0).append('g').attr('transform', 'translate(-15, -15)')
      loadIndicator.append('rect').attr('x', -5).attr('y', -5).attr('width', 10).attr('height', 10).attr('fill', 'var(--color-destructive)').attr('stroke', 'var(--color-foreground)').attr('stroke-width', 1)
      loadIndicator.append('text').attr('text-anchor', 'middle').attr('dy', 3.5).attr('font-size', 8.5).attr('font-weight', 600).attr('fill', 'var(--color-primary-foreground)').text('L')

      const dgIndicator = sel.filter((d: Node) => (d.pGenDG ?? 0) !== 0).append('g').attr('transform', 'translate(-15, 15)')
      dgIndicator.append('circle').attr('r', 7.5).attr('fill', 'var(--color-method-ldf)').attr('stroke', 'var(--color-foreground)').attr('stroke-width', 1)
      dgIndicator.append('text').attr('text-anchor', 'middle').attr('dy', 3).attr('font-size', 6.5).attr('font-weight', 600).attr('fill', 'var(--color-primary-foreground)').text('DG')
      dgIndicator.append('title').text('Distributed generation (sgen) — fixed PQ, not voltage-controlled')

      sel
        .append('text')
        .attr('text-anchor', 'middle')
        .attr('dy', 32)
        .attr('font-size', 10)
        .attr('fill', 'var(--color-foreground)')
        .text((d: Node) => d.name)

      drawMeasurementBadge(sel, 15, 17)
      attachMeasurementClick(sel)

      const position = () => sel.attr('transform', (d) => `translate(${d.x},${d.y})`)
      return { sel, position }
    }

    // ── Tree-mode-only visuals: IEEE-style single-line diagram — buses drawn
    // as tick marks (not circles), edges routed with right-angle elbows, and
    // loads drawn as arrows pointing straight down regardless of orientation
    // (matching how these feeder diagrams are conventionally drawn).
    function drawElbowLinks(parent: d3.Selection<SVGGElement, unknown, null, undefined>, links: Link[], nodeById: Map<number, Node>) {
      const sel = parent
        .append('g')
        .selectAll('path')
        .data(links)
        .join('path')
        .attr('fill', 'none')
        .attr('stroke', (d: Link) => (lineResults.has(d.id) ? 'var(--color-status-warn)' : 'var(--color-foreground)'))
        .attr('stroke-width', (d: Link) => {
          const flow = Math.abs(lineResults.get(d.id)?.pFrom ?? 0)
          return result ? 1.5 + 4 * (flow / maxAbsFlow) : 1.75
        })
        .attr('stroke-opacity', result ? 0.85 : 0.75)

      const labels = parent
        .append('g')
        .selectAll('text')
        .data(links)
        .join('text')
        .attr('font-size', 10)
        .attr('fill', 'var(--color-muted-foreground)')
        .attr('text-anchor', 'middle')
        .text((d: Link) => {
          const solved = lineResults.get(d.id)
          return solved ? `L${d.id} ${Math.abs(solved.pFrom).toFixed(2)} pu` : `L${d.id}`
        })

      const position = () => {
        sel.attr('d', (d) => {
          const from = nodeById.get(d.from)
          const to = nodeById.get(d.to)
          if (!from || !to) return ''
          return elbowPath(from, to, orientation)
        })
        labels
          .attr('x', (d) => {
            const fx = nodeById.get(d.from)?.x ?? 0
            const tx = nodeById.get(d.to)?.x ?? 0
            return fx * 0.28 + tx * 0.72
          })
          .attr('y', (d) => {
            const fy = nodeById.get(d.from)?.y ?? 0
            const ty = nodeById.get(d.to)?.y ?? 0
            return fy * 0.28 + ty * 0.72 - 6
          })
      }
      return { sel, labels, position }
    }

    function drawBusBars(parent: d3.Selection<SVGGElement, unknown, null, undefined>, nodes: Node[]) {
      const sel = parent.append('g').selectAll('g').data(nodes).join('g')

      const slack = sel.filter((d: Node) => d.type === 'slack')
      slack
        .append('rect')
        .attr('x', -40)
        .attr('y', -16)
        .attr('width', 80)
        .attr('height', 32)
        .attr('rx', 4)
        .attr('fill', 'var(--color-primary)')
        .attr('stroke', 'var(--color-foreground)')
        .attr('stroke-width', 2)
      slack
        .append('text')
        .attr('text-anchor', 'middle')
        .attr('dy', 5)
        .attr('font-size', 12)
        .attr('font-weight', 700)
        .attr('fill', 'var(--color-primary-foreground)')
        .text((d: Node) => d.name || `Bus ${d.id}`)

      const bus = sel.filter((d: Node) => d.type !== 'slack')
      bus
        .append('line')
        .attr('x1', orientation === 'vertical' ? -TREE_TICK_HALF : 0)
        .attr('x2', orientation === 'vertical' ? TREE_TICK_HALF : 0)
        .attr('y1', orientation === 'vertical' ? 0 : -TREE_TICK_HALF)
        .attr('y2', orientation === 'vertical' ? 0 : TREE_TICK_HALF)
        .attr('stroke', (d: Node) => {
          const solvedVoltage = busResults.get(d.id)?.voltage
          if (result && solvedVoltage != null) return voltageColor(solvedVoltage)
          return d.type === 'pv' ? 'var(--color-accent)' : 'var(--color-foreground)'
        })
        .attr('stroke-width', (d: Node) => (d.type === 'pv' ? 6 : 5))
        .attr('stroke-linecap', 'round')
      bus
        .append('text')
        .attr('text-anchor', 'middle')
        .attr('dy', -12)
        .attr('font-size', 12)
        .attr('font-weight', 700)
        .attr('fill', 'var(--color-foreground)')
        .text((d: Node) => d.id)

      const genIndicator = sel.filter((d: Node) => d.pGen > 0 && d.type !== 'slack').append('g').attr('transform', 'translate(14, -5)')
      genIndicator.append('circle').attr('r', 7).attr('fill', 'var(--color-status-good)').attr('stroke', 'var(--color-foreground)').attr('stroke-width', 1)
      genIndicator.append('text').attr('text-anchor', 'middle').attr('dy', 3.5).attr('font-size', 9).attr('font-weight', 700).attr('fill', 'var(--color-primary-foreground)').text('G')

      const dgIndicator = sel.filter((d: Node) => (d.pGenDG ?? 0) !== 0 && d.type !== 'slack').append('g').attr('transform', 'translate(14, 12)')
      dgIndicator.append('circle').attr('r', 7).attr('fill', 'var(--color-method-ldf)').attr('stroke', 'var(--color-foreground)').attr('stroke-width', 1)
      dgIndicator.append('text').attr('text-anchor', 'middle').attr('dy', 3).attr('font-size', 7).attr('font-weight', 700).attr('fill', 'var(--color-primary-foreground)').text('DG')
      dgIndicator.append('title').text('Distributed generation (sgen) — fixed PQ, not voltage-controlled')

      sel
        .filter((d: Node) => d.pLoad > 0)
        .append('line')
        .attr('x1', 0)
        .attr('y1', 9)
        .attr('x2', 0)
        .attr('y2', 19)
        .attr('stroke', 'var(--color-destructive)')
        .attr('stroke-width', 2)
        .attr('marker-end', `url(#${LOAD_ARROW_MARKER_ID})`)

      // Mirrors the generator badge (translate(14,-5)) on the opposite side
      // of the tick — free space regardless of orientation.
      drawMeasurementBadge(bus, -14, -5)
      drawMeasurementBadge(slack, 46, 0)
      attachMeasurementClick(sel)

      const position = () => sel.attr('transform', (d) => `translate(${d.x},${d.y})`)
      return { sel, position }
    }

    if (viewMode === 'spatial') {
      const hasGeoCoords = topology.buses.some((bus) => bus.geoX !== undefined && bus.geoY !== undefined)
      const radialPositions = hasGeoCoords ? null : computeRadialLayout(topology, width, height)

      // Hoisted out of the per-bus loop below: recomputing the filter and both
      // maxima inside it made building the node array O(buses^2), and the
      // spread form (Math.max(...arr)) also blows the argument limit on a
      // large enough case.
      let maxGeoX = 0
      let maxGeoY = 0
      for (const b of topology.buses) {
        if (b.geoX !== undefined && b.geoX > maxGeoX) maxGeoX = b.geoX
        if (b.geoY !== undefined && b.geoY > maxGeoY) maxGeoY = b.geoY
      }
      const geoSpanX = maxGeoX || 1
      const geoSpanY = maxGeoY || 1

      const nodes: Node[] = topology.buses.map((bus) => {
        const node: Node = {
          id: bus.id,
          name: bus.name,
          type: bus.type,
          pGen: bus.pGen,
          qGen: bus.qGen,
          pLoad: bus.pLoad,
          qLoad: bus.qLoad,
          measurementKind: measurementIndex.busKind.get(bus.id),
        }
        if (hasGeoCoords && bus.geoX !== undefined && bus.geoY !== undefined) {
          const padding = 50
          node.x = (bus.geoX / geoSpanX) * (width - 2 * padding) + padding
          node.y = (bus.geoY / geoSpanY) * (height - 2 * padding) + padding
          node.fx = node.x
          node.fy = node.y
        } else {
          // Resume from where this bus last settled, else the concentric
          // layout — otherwise a meter toggle or any other redraw makes every
          // node jump. With the Force toggle off these positions are the
          // final layout, not a starting point.
          const prevPos = positionsRef.current.get(bus.id) ?? radialPositions?.get(bus.id)
          if (prevPos) {
            node.x = prevPos.x
            node.y = prevPos.y
          }
        }
        return node
      })
      const nodeById = new Map(nodes.map((n) => [n.id, n]))

      const links: Link[] = topology.lines.map((line) => ({
        id: line.id,
        from: line.from,
        to: line.to,
        lineMeasurementKind: measurementIndex.lineKind.get(line.id),
      }))

      const simLinks = links.map((l) => ({ ...l, source: l.from, target: l.to }))
      const simulation = hasGeoCoords
        ? d3
            .forceSimulation(nodes)
            .force('link', d3.forceLink(simLinks as any).id((d: any) => d.id).distance(150).strength(0.1))
            .alphaDecay(0.1)
        : d3
            .forceSimulation(nodes)
            .force('link', d3.forceLink(simLinks as any).id((d: any) => d.id).distance(110))
            .force('charge', d3.forceManyBody().strength(-550))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(38))

      // Settle the layout headless instead of animating it into place, and
      // only when the Force toggle asks for it. Ticking on a timer meant
      // rewriting the position of every node, link, hit area, badge and switch
      // glyph once per frame for several seconds; watching a layout converge
      // was never information. The tick handler wired up further down still
      // runs for interactive drags, which do want live feedback.
      simulation.stop()
      if (!hasGeoCoords && useForceLayout) {
        // With fixed geo coordinates every node is pinned via fx/fy, so the
        // forces have nothing to solve and ticking is pure cost.
        const decayTicks = Math.ceil(
          Math.log(simulation.alphaMin()) / Math.log(1 - simulation.alphaDecay())
        )
        simulation.tick(nodes.length > 600 ? 200 : decayTicks)
      }

      // Out-of-service lines/transformers (tie-switches, backup) — drawn dashed,
      // never fed into the force simulation or the power-flow model. See
      // load_pandapower_case() in topology.py.
      const switchLinks = allSwitches
        .filter((sw) => !sw.closed && nodeById.has(sw.from) && nodeById.has(sw.to))
        .map((sw) => ({ from: sw.from, to: sw.to, label: '' }))
      const switches = drawDashedLinks(g, switchLinks, nodeById, 'var(--color-muted-foreground)')
      const switchGlyphs = drawSwitchGlyphs(g, allSwitches, nodeById, onSwitchToggle)

      const linkDraw = drawLinks(g, links, nodeById)
      const linkHit = attachLineMeasurementClick(g, links, (d) => {
        const from = nodeById.get(d.from)
        const to = nodeById.get(d.to)
        if (!from || !to) return null
        return `M${from.x ?? 0},${from.y ?? 0} L${to.x ?? 0},${to.y ?? 0}`
      })
      const lineBadges = drawLineMeasurementBadge(g, links, nodeById)

      const node = drawNodes(g, nodes)
      node.sel.call(
        d3
          .drag<SVGGElement, Node>()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart()
            d.fx = d.x
            d.fy = d.y
          })
          .on('drag', (event, d) => {
            d.fx = event.x
            d.fy = event.y
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0)
            d.fx = hasGeoCoords ? d.x : null
            d.fy = hasGeoCoords ? d.y : null
          }) as any
      )

      const reposition = () => {
        linkDraw.position()
        linkHit?.position()
        lineBadges?.position()
        switches.position()
        switchGlyphs.position()
        node.position()
        for (const n of nodes) {
          if (n.x != null && n.y != null) positionsRef.current.set(n.id, { x: n.x, y: n.y })
        }
      }
      // Only drags restart the simulation now, so this handler is what keeps
      // a dragged node's neighbours following it.
      simulation.on('tick', reposition)
      reposition()
      if (shouldFit) fitToView()

      return () => {
        simulation.stop()
      }
    }

    // ── Tree mode: BFS spanning tree from the slack bus, laid out with
    // d3.tree() — the classic top-down/left-right single-line feeder diagram.
    // orient="auto" rotates the marker so its local +x axis follows the
    // path direction — the triangle tip must point along +x (10,5) for the
    // rotation to land the tip on the line's end, not perpendicular to it.
    svg
      .append('defs')
      .append('marker')
      .attr('id', LOAD_ARROW_MARKER_ID)
      .attr('viewBox', '0 0 10 10')
      .attr('refX', 9)
      .attr('refY', 5)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,0 L10,5 L0,10 Z')
      .attr('fill', 'var(--color-destructive)')

    const treeData = buildTopologyTree(topology)
    if (!treeData.root) return

    const hierarchyRoot = d3.hierarchy<TopologyTreeNode>(treeData.root, (d) => d.children)
    const treeLayout = d3.tree<TopologyTreeNode>().nodeSize(TREE_NODE_SIZE)
    treeLayout(hierarchyRoot)
    const points = hierarchyRoot.descendants() as d3.HierarchyPointNode<TopologyTreeNode>[]
    const minSibling = Math.min(...points.map((p) => p.x))

    const nodes: Node[] = points.map((p) => {
      const bus = p.data.bus
      const sib = p.x - minSibling + TREE_PADDING
      const depth = p.y + TREE_PADDING
      const [x, y] = orientation === 'vertical' ? [sib, depth] : [depth, sib]
      return { id: bus.id, name: bus.name, type: bus.type, pGen: bus.pGen, qGen: bus.qGen, pLoad: bus.pLoad, qLoad: bus.qLoad, pGenDG: bus.pGenDG ?? 0, measurementKind: measurementIndex.busKind.get(bus.id), x, y }
    })
    const nodeById = new Map(nodes.map((n) => [n.id, n]))

    // target.data.parentLine is the real topology.lines entry behind this
    // tree edge (see buildTopologyTree in networkTopology.ts) — falls back
    // to a synthetic negative id only if somehow missing (shouldn't happen:
    // every non-root tree node gets one from the BFS).
    const links: Link[] = hierarchyRoot.links().map((l, i) => ({
      id: l.target.data.parentLine?.id ?? -(i + 1),
      from: l.source.data.bus.id,
      to: l.target.data.bus.id,
      lineMeasurementKind: l.target.data.parentLine
        ? measurementIndex.lineKind.get(l.target.data.parentLine.id)
        : undefined,
    }))

    const linkDraw = drawElbowLinks(g, links, nodeById)
    linkDraw.position()
    const treeLinkHit = attachLineMeasurementClick(g, links, (d) => {
      const from = nodeById.get(d.from)
      const to = nodeById.get(d.to)
      if (!from || !to) return null
      return elbowPath(from, to, orientation)
    })
    treeLinkHit?.position()
    const treeLineBadges = drawLineMeasurementBadge(g, links, nodeById)
    treeLineBadges?.position()

    const extraLinks = treeData.extraLines
      .filter((line) => nodeById.has(line.from) && nodeById.has(line.to))
      .map((line) => ({ from: line.from, to: line.to, label: `loop: L${line.id}` }))
    const extras = drawDashedLinks(g, extraLinks, nodeById, 'var(--color-status-warn)')
    extras.position()

    const switchLinks = allSwitches
      .filter((sw) => !sw.closed && nodeById.has(sw.from) && nodeById.has(sw.to))
      .map((sw) => ({ from: sw.from, to: sw.to, label: '' }))
    const switches = drawDashedLinks(g, switchLinks, nodeById, 'var(--color-muted-foreground)')
    switches.position()
    const treeSwitchGlyphs = drawSwitchGlyphs(g, allSwitches, nodeById, onSwitchToggle)
    treeSwitchGlyphs.position()

    const node = drawBusBars(g, nodes)
    node.position()

    // Buses the BFS never reached (disconnected islands) — laid out in their
    // own row past the deepest tree level, unconnected, so they're still
    // visible instead of silently vanishing from the diagram.
    if (treeData.unreachable.length) {
      // Loop rather than Math.max(...array), and a grid rather than a single
      // row — see the matching block in computeTreeLayout for why.
      let maxDepth = -Infinity
      for (const p of points) if (p.y > maxDepth) maxDepth = p.y
      const orphanCols = Math.max(1, Math.ceil(Math.sqrt(treeData.unreachable.length)))
      const orphanNodes: Node[] = treeData.unreachable.map((bus, i) => {
        const sib = (i % orphanCols) * TREE_NODE_SIZE[0] + TREE_PADDING
        const depth =
          maxDepth + TREE_NODE_SIZE[1] + TREE_PADDING + Math.floor(i / orphanCols) * TREE_NODE_SIZE[1]
        const [x, y] = orientation === 'vertical' ? [sib, depth] : [depth, sib]
        return { id: bus.id, name: bus.name, type: bus.type, pGen: bus.pGen, qGen: bus.qGen, pLoad: bus.pLoad, qLoad: bus.qLoad, pGenDG: bus.pGenDG ?? 0, measurementKind: measurementIndex.busKind.get(bus.id), x, y }
      })
      const orphans = drawBusBars(g, orphanNodes)
      orphans.position()
      orphans.sel.append('title').text('Not reachable from the slack bus (disconnected)')
    }

    if (shouldFit) fitToView()

    return undefined
  }, [topology, dimensions, result, voltageLimits, viewMode, orientation, renderer, measurementIndex, useForceLayout])

  // Memoized: this runs a full BFS over the network. Unmemoized in the render
  // body it re-ran on every React render, including ones that only opened a
  // popover.
  const treeData = useMemo(
    () => (viewMode === 'tree' ? buildTopologyTree(topology) : null),
    [viewMode, topology]
  )

  return (
    <Card>
      <CardHeader className={compact ? 'px-4 py-3' : 'px-4 sm:px-6 py-4 sm:py-6'}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base sm:text-lg">
              <Network weight="fill" className="w-4 h-4 sm:w-5 sm:h-5" />
              {result ? 'One-line Diagram - Result Overlay' : 'Network Diagram'}
            </CardTitle>
            <CardDescription className="text-xs sm:text-sm">
              {result
                ? 'Voltage is encoded by bus color; active flow by branch thickness'
                : viewMode === 'spatial'
                  ? useForceLayout
                    ? 'Force-directed view - drag nodes to reposition them'
                    : 'Concentric view - rings are hops from the substation; drag nodes to reposition them'
                  : 'BFS spanning tree from the slack bus - loops and disconnected buses are flagged, not hidden'}
              {!result && onMeasurementKindChange && ' - click a bus to assign its meter'}
              {!result && onLineMeasurementKindChange && ', click a line to assign a branch-flow meter'}
              {isLargeNetwork && renderer === 'canvas' &&
                ` - ${topology.buses.length} buses: fast rendering, labels hidden (zoom to inspect)`}
            </CardDescription>
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <Button type="button" size="sm" variant={viewMode === 'spatial' ? 'default' : 'outline'} className="h-7 text-xs" onClick={() => setViewMode('spatial')}>
              <Network className="w-3.5 h-3.5" /> Spatial
            </Button>
            <Button type="button" size="sm" variant={viewMode === 'tree' ? 'default' : 'outline'} className="h-7 text-xs" onClick={() => setViewMode('tree')}>
              <TreeStructure className="w-3.5 h-3.5" /> Tree
            </Button>
            {viewMode === 'tree' && (
              <>
                <Button type="button" size="sm" variant={orientation === 'vertical' ? 'default' : 'outline'} className="h-7 text-xs" onClick={() => setOrientation('vertical')} title="Top-down">
                  <ArrowsDownUp className="w-3.5 h-3.5" />
                </Button>
                <Button type="button" size="sm" variant={orientation === 'horizontal' ? 'default' : 'outline'} className="h-7 text-xs" onClick={() => setOrientation('horizontal')} title="Left-right">
                  <ArrowsLeftRight className="w-3.5 h-3.5" />
                </Button>
              </>
            )}
            <Button type="button" size="sm" variant="outline" className="h-7 text-xs" onClick={fitToView} title="Fit to view">
              <ArrowsOut className="w-3.5 h-3.5" /> Fit
            </Button>
            {viewMode === 'spatial' && (
              <Button
                type="button"
                size="sm"
                variant={useForceLayout ? 'default' : 'outline'}
                className="h-7 text-xs"
                onClick={() => setUseForceLayout((v) => !v)}
                title={
                  useForceLayout
                    ? 'Force-directed layout is on. Turn it off for the concentric layout (by distance from the substation), which is instant.'
                    : `Concentric layout, by hops from the substation. Turn on the force-directed layout instead${isLargeNetwork ? ' - takes a few seconds at this size' : ''}.`
                }
              >
                <Atom className="w-3.5 h-3.5" /> Force
              </Button>
            )}
            {/* Segmented, not a single cycling button: which mode is active
                has to be readable at a glance — a lone button showing "Fast"
                is ambiguous about whether that is the current state or the
                thing it will switch to. Same pattern as Spatial/Tree above. */}
            <div className="flex items-center rounded-md border p-0.5">
              <Button
                type="button"
                size="sm"
                variant={renderer === 'canvas' ? 'default' : 'ghost'}
                className="h-6 px-2 text-xs"
                onClick={() => setRendererPref('canvas')}
                title="Fast rendering (canvas) - handles thousands of buses smoothly"
              >
                <Lightning className="w-3.5 h-3.5" /> Fast
              </Button>
              <Button
                type="button"
                size="sm"
                variant={renderer === 'svg' ? 'default' : 'ghost'}
                className="h-6 px-2 text-xs"
                onClick={() => setRendererPref('svg')}
                title={
                  isLargeNetwork
                    ? `Detailed rendering (SVG) - slow on this network (${topology.buses.length} buses)`
                    : 'Detailed rendering (SVG) - per-bus labels, badges and tooltips'
                }
              >
                <Sparkle className="w-3.5 h-3.5" /> Detailed
              </Button>
            </div>
            <Button
              type="button"
              size="sm"
              variant={metersPanelOpen ? 'default' : 'outline'}
              className="h-7 text-xs"
              onClick={() => {
                setMetersPanelOpen((v) => !v)
                setSwitchesPanelOpen(false)
              }}
              title="List all bus and line meters"
            >
              <List className="w-3.5 h-3.5" /> Meters
            </Button>
            {onSwitchToggle && allSwitches.length > 0 && (
              <Button
                type="button"
                size="sm"
                variant={switchesPanelOpen ? 'default' : 'outline'}
                className="h-7 text-xs"
                onClick={() => {
                  setSwitchesPanelOpen((v) => !v)
                  setMetersPanelOpen(false)
                }}
                title="Manage sectionalizing and tie switches"
              >
                <ToggleRight className="w-3.5 h-3.5" /> Switches ({allSwitches.filter(s => s.closed).length}/{allSwitches.filter(s => !s.closed).length})
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className={compact ? 'px-4 pb-4' : 'px-4 sm:px-6 pb-4 sm:pb-6'}>
        {treeData && (treeData.extraLines.length > 0 || treeData.unreachable.length > 0) && (
          <div className="mb-3 text-xs sm:text-sm text-status-warn">
            {treeData.extraLines.length > 0 &&
              `${treeData.extraLines.length} loop connection${treeData.extraLines.length > 1 ? 's' : ''} not shown by the tree (meshed network)`}
            {treeData.extraLines.length > 0 && treeData.unreachable.length > 0 && ' · '}
            {treeData.unreachable.length > 0 &&
              `${treeData.unreachable.length} bus${treeData.unreachable.length > 1 ? 'es' : ''} unreachable from the slack`}
          </div>
        )}
        <div ref={containerRef} className="relative border rounded-lg overflow-hidden bg-background">
          {renderer === 'canvas' && canvasLayout ? (
            <TopologyCanvasView
              ref={canvasHandleRef}
              layout={canvasLayout}
              viewMode={viewMode}
              orientation={orientation}
              width={dimensions.width}
              height={dimensions.height}
              result={result}
              voltageLimits={{ min: voltageLimits?.min ?? 0.95, max: voltageLimits?.max ?? 1.05 }}
              detailed={detailed}
              onBusClick={onMeasurementKindChange ? handleCanvasBusClick : undefined}
              onLineClick={onLineMeasurementKindChange ? handleCanvasLineClick : undefined}
              onSwitchToggle={onSwitchToggle}
              onNodeMoved={handleCanvasNodeMoved}
              fitKey={canvasFitKey}
            />
          ) : (
            <svg ref={svgRef} width={dimensions.width} height={dimensions.height} className="w-full touch-none" />
          )}
          {onMeasurementKindChange && (
            <Popover open={!!meterPopover} onOpenChange={(open) => !open && setMeterPopover(null)}>
              <PopoverAnchor asChild>
                <span
                  className="pointer-events-none absolute h-px w-px"
                  style={{ left: meterPopover?.x ?? 0, top: meterPopover?.y ?? 0 }}
                />
              </PopoverAnchor>
              <PopoverContent className="w-52 p-2" side="right" align="start">
                {meterPopover && (
                  <div className="space-y-1">
                    <p className="mono px-1 pb-1 text-xs font-semibold text-muted-foreground">Bus {meterPopover.busId} meter</p>
                    <MeterKindMenu
                      activeKind={getMeasurement(topology, meterPopover.busId)?.kind}
                      onSelect={(kind) => {
                        onMeasurementKindChange(meterPopover.busId, kind)
                        setMeterPopover(null)
                      }}
                      noneLabel="No meter (unobserved)"
                    />
                  </div>
                )}
              </PopoverContent>
            </Popover>
          )}
          {onLineMeasurementKindChange && (
            <Popover open={!!lineMeterPopover} onOpenChange={(open) => !open && setLineMeterPopover(null)}>
              <PopoverAnchor asChild>
                <span
                  className="pointer-events-none absolute h-px w-px"
                  style={{ left: lineMeterPopover?.x ?? 0, top: lineMeterPopover?.y ?? 0 }}
                />
              </PopoverAnchor>
              <PopoverContent className="w-56 p-2" side="right" align="start">
                {lineMeterPopover && (
                  <div className="space-y-1">
                    <p className="mono px-1 pb-1 text-xs font-semibold text-muted-foreground">Line {lineMeterPopover.lineId} branch-flow meter</p>
                    <MeterKindMenu
                      activeKind={getLineMeasurement(topology, lineMeterPopover.lineId)?.kind}
                      onSelect={(kind) => {
                        onLineMeasurementKindChange(lineMeterPopover.lineId, kind)
                        setLineMeterPopover(null)
                      }}
                      noneLabel="No meter (unmetered line)"
                    />
                  </div>
                )}
              </PopoverContent>
            </Popover>
          )}
          {metersPanelOpen && (
            <div className="absolute inset-y-0 right-0 z-30 flex w-60 flex-col border-l bg-background/97 backdrop-blur-sm shadow-lg">
              <div className="flex shrink-0 items-center justify-between border-b bg-background/97 px-2.5 py-2">
                <span className="text-xs font-semibold">Meters</span>
                <Button type="button" size="icon" variant="ghost" className="h-6 w-6" onClick={() => setMetersPanelOpen(false)} aria-label="Close meters panel">
                  <X className="w-3.5 h-3.5" />
                </Button>
              </div>

              {/* ── Apply to all ── */}
              {(onApplyMeterToAll) && (
                <div className="shrink-0 border-b px-2.5 py-2.5 space-y-2">
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">Apply to all</p>
                  <Select value={applyKind} onValueChange={(v) => setApplyKind(v as MeasurementKind)}>
                    <SelectTrigger className="h-7 text-xs w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {MEASUREMENT_KINDS.map((k) => (
                        <SelectItem key={k} value={k} className="text-xs">
                          <span style={{ color: MEASUREMENT_KIND_INFO[k].colorVar }} className="font-semibold mr-1">
                            {MEASUREMENT_KIND_INFO[k].shortLabel}
                          </span>
                          <span className="text-muted-foreground">{MEASUREMENT_KIND_INFO[k].label.split(' ')[0]}</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Select value={applyTarget} onValueChange={(v) => setApplyTarget(v as typeof applyTarget)}>
                    <SelectTrigger className="h-7 text-xs w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="buses" className="text-xs">Buses only</SelectItem>
                      <SelectItem value="lines" className="text-xs">Lines only</SelectItem>
                      <SelectItem value="both" className="text-xs">Buses + Lines</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    type="button"
                    size="sm"
                    className="h-7 w-full text-xs"
                    onClick={() => onApplyMeterToAll(applyKind, applyTarget)}
                  >
                    Apply to all
                  </Button>
                </div>
              )}

              {/* Both lists are windowed: a real distribution case has
                  thousands of buses and lines, and the previous version
                  mounted a Radix Popover per row — thousands of them, all
                  re-rendering whenever `topology` changed identity. Now each
                  list mounts only what fits, and every row shares the single
                  popover the diagram already uses. */}
              <div className="flex min-h-0 flex-1 flex-col gap-2 p-2.5">
                <div className="flex min-h-0 flex-1 flex-col">
                  <p className="mb-1 shrink-0 text-[10px] font-semibold text-muted-foreground">
                    Buses ({topology.buses.length})
                  </p>
                  <div ref={busMeterRows.scrollRef} className="min-h-0 flex-1 overflow-y-auto">
                    <div style={{ height: busMeterRows.totalHeight, position: 'relative' }}>
                      <div style={{ transform: `translateY(${busMeterRows.offsetY}px)` }}>
                        {topology.buses.slice(busMeterRows.start, busMeterRows.end).map((bus) => {
                          const kind = measurementIndex.busKind.get(bus.id)
                          return (
                            <button
                              key={bus.id}
                              type="button"
                              style={{ height: METER_ROW_HEIGHT }}
                              disabled={!onMeasurementKindChange}
                              onClick={(event) => openBusMeterPopover(bus.id, event.currentTarget)}
                              className="flex w-full items-center justify-between gap-2 rounded px-1 text-left text-xs enabled:hover:bg-muted disabled:cursor-default"
                            >
                              <span className="truncate">
                                Bus {bus.id} <span className="text-muted-foreground">({bus.name})</span>
                              </span>
                              {kind ? (
                                <span className="shrink-0 font-semibold" style={{ color: MEASUREMENT_KIND_INFO[kind].colorVar }}>
                                  {MEASUREMENT_KIND_INFO[kind].shortLabel}
                                </span>
                              ) : (
                                <span className="shrink-0 text-muted-foreground">&#8212;</span>
                              )}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                </div>
                <div className="flex min-h-0 flex-1 flex-col border-t pt-2">
                  <p className="mb-1 shrink-0 text-[10px] font-semibold text-muted-foreground">
                    Lines ({topology.lines.length})
                  </p>
                  <div ref={lineMeterRows.scrollRef} className="min-h-0 flex-1 overflow-y-auto">
                    <div style={{ height: lineMeterRows.totalHeight, position: 'relative' }}>
                      <div style={{ transform: `translateY(${lineMeterRows.offsetY}px)` }}>
                        {topology.lines.slice(lineMeterRows.start, lineMeterRows.end).map((line) => {
                          const kind = measurementIndex.lineKind.get(line.id)
                          return (
                            <button
                              key={line.id}
                              type="button"
                              style={{ height: METER_ROW_HEIGHT }}
                              disabled={!onLineMeasurementKindChange}
                              onClick={(event) => openLineMeterPopover(line.id, event.currentTarget)}
                              className="flex w-full items-center justify-between gap-2 rounded px-1 text-left text-xs enabled:hover:bg-muted disabled:cursor-default"
                            >
                              <span className="truncate">
                                L{line.id} <span className="text-muted-foreground">({line.from}&#8594;{line.to})</span>
                              </span>
                              {kind ? (
                                <span className="shrink-0 font-semibold" style={{ color: MEASUREMENT_KIND_INFO[kind].colorVar }}>
                                  {MEASUREMENT_KIND_INFO[kind].shortLabel}
                                </span>
                              ) : (
                                <span className="shrink-0 text-muted-foreground">&#8212;</span>
                              )}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── Switches Panel (Dedicated) ── */}
          {switchesPanelOpen && onSwitchToggle && (
            <div className="absolute inset-y-0 right-0 z-30 flex w-64 flex-col border-l bg-background/97 backdrop-blur-sm shadow-lg">
              <div className="flex shrink-0 items-center justify-between border-b bg-background/97 px-3 py-2.5">
                <div>
                  <span className="text-xs font-semibold">Switches</span>
                  <p className="text-[10px] text-muted-foreground">
                    <span className="text-status-good font-medium">{allSwitches.filter(s => s.closed).length} closed</span> · <span className="text-status-info font-medium">{allSwitches.filter(s => !s.closed).length} open</span>
                  </p>
                </div>
                <Button type="button" size="icon" variant="ghost" className="h-6 w-6" onClick={() => setSwitchesPanelOpen(false)} aria-label="Close switches panel">
                  <X className="w-3.5 h-3.5" />
                </Button>
              </div>

              <div className="flex min-h-0 flex-1 flex-col gap-2.5 p-3">
                {onResetSwitches && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 w-full shrink-0 gap-1.5 text-xs"
                    onClick={onResetSwitches}
                  >
                    <ArrowCounterClockwise className="w-3.5 h-3.5" />
                    Reset to default topology
                  </Button>
                )}
                <p className="shrink-0 text-[11px] text-muted-foreground leading-snug">
                  Toggle switches to open lines or close tie-lines. Reconfigures feeder topology in real time for power flow and DSSE.
                </p>

                {/* Windowed: getTopologySwitches reports one switch per
                    branch, so this list is as long as the line list — a Radix
                    Switch per row is far too many to mount on a real feeder. */}
                <div ref={switchRows.scrollRef} className="min-h-0 flex-1 overflow-y-auto">
                  <div style={{ height: switchRows.totalHeight, position: 'relative' }}>
                    <div style={{ transform: `translateY(${switchRows.offsetY}px)` }}>
                      {allSwitches.slice(switchRows.start, switchRows.end).map((sw) => (
                        <div
                          key={`sw-${sw.id}`}
                          style={{ height: SWITCH_ROW_HEIGHT }}
                          className="mb-1 flex items-center justify-between gap-2 rounded border border-border/40 px-2 hover:bg-muted/60"
                        >
                          <Label
                            htmlFor={`sw-${sw.id}`}
                            className="text-xs cursor-pointer leading-tight truncate flex-1 min-w-0"
                            title={`Bus ${sw.from} ↔ Bus ${sw.to}`}
                          >
                            <span className="block truncate font-medium">{sw.name ?? `SW ${sw.id}`}</span>
                            <span className="text-[10px] text-muted-foreground font-normal">
                              {sw.from}↔{sw.to} ·{' '}
                              <span className={sw.closed ? 'text-status-good font-semibold' : 'text-status-info font-semibold'}>
                                {sw.closed ? 'closed' : 'open'}
                              </span>
                            </span>
                          </Label>
                          <Switch
                            id={`sw-${sw.id}`}
                            checked={sw.closed || false}
                            onCheckedChange={(checked) => onSwitchToggle(sw.id, checked)}
                            aria-label={`Toggle switch ${sw.name ?? sw.id}`}
                            className="scale-75 origin-right shrink-0"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
        {result ? (
          <div className="mt-3 sm:mt-4 flex flex-wrap items-center gap-3 sm:gap-5 text-xs sm:text-sm">
            <div className="flex items-center gap-1.5">
              <div className="h-2 w-24 rounded-full bg-linear-to-r from-status-info via-status-good to-destructive" />
              <span className="text-muted-foreground">|V| low - nominal - high</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="h-1.5 w-8 rounded-full bg-status-warn" />
              <span className="text-muted-foreground">relative active flow</span>
            </div>
            {allSwitches.some(s => !s.closed) && (
              <div className="flex items-center gap-1.5">
                <div className="h-0 w-8 border-t-2 border-dashed border-muted-foreground" />
                <span className="text-muted-foreground">open switch ({allSwitches.filter(s => !s.closed).length})</span>
              </div>
            )}
          </div>
        ) : viewMode === 'tree' ? (
          <div className="mt-3 sm:mt-4 flex flex-wrap gap-3 sm:gap-6 text-xs sm:text-sm">
            <div className="flex items-center gap-1.5">
              <div className="w-6 h-3.5 rounded-sm bg-primary border border-foreground" />
              <span className="text-muted-foreground">Substation / Slack</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-1 h-4 rounded-full bg-foreground" />
              <span className="text-muted-foreground">Bus</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="h-0 w-8 border-t-[1.75px] border-foreground" />
              <span className="text-muted-foreground">Line</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-destructive text-base leading-none">&#8595;</span>
              <span className="text-muted-foreground">Load</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3.5 h-3.5 rounded-full bg-status-good border border-foreground flex items-center justify-center text-[9px] font-bold text-primary-foreground">G</div>
              <span className="text-muted-foreground">Generator</span>
            </div>
            {topology.buses.some((b) => (b.pGenDG ?? 0) !== 0) && (
              <div className="flex items-center gap-1.5">
                <div className="w-3.5 h-3.5 rounded-full bg-method-ldf border border-foreground flex items-center justify-center text-[7px] font-bold text-primary-foreground">DG</div>
                <span className="text-muted-foreground">Distributed gen. (sgen)</span>
              </div>
            )}
            {allSwitches.some(s => !s.closed) && (
              <div className="flex items-center gap-1.5">
                <div className="h-0 w-8 border-t-2 border-dashed border-muted-foreground" />
                <span className="text-muted-foreground">open switch ({allSwitches.filter(s => !s.closed).length})</span>
              </div>
            )}
            {!!treeData?.extraLines.length && (
              <div className="flex items-center gap-1.5">
                <div className="h-0 w-8 border-t-2 border-dashed border-status-warn" />
                <span className="text-muted-foreground">loop / extra connection (mesh)</span>
              </div>
            )}
          </div>
        ) : (
          <div className="mt-3 sm:mt-4 flex flex-wrap gap-3 sm:gap-6 text-xs sm:text-sm">
            <div className="flex items-center gap-1.5">
              <div className="w-5 h-5 rounded-full bg-primary border-2 border-foreground" />
              <span className="text-muted-foreground">Slack Bus</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-4 h-4 rounded-full bg-accent border-2 border-foreground" />
              <span className="text-muted-foreground">PV Bus</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3.5 h-3.5 rounded-full bg-muted border-2 border-foreground" />
              <span className="text-muted-foreground">PQ Bus</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3.5 h-3.5 bg-status-good border border-foreground flex items-center justify-center text-[9px] font-bold text-primary-foreground">G</div>
              <span className="text-muted-foreground">Generator</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3.5 h-3.5 bg-destructive border border-foreground flex items-center justify-center text-[9px] font-bold text-primary-foreground">L</div>
              <span className="text-muted-foreground">Load</span>
            </div>
            {topology.buses.some((b) => (b.pGenDG ?? 0) !== 0) && (
              <div className="flex items-center gap-1.5">
                <div className="w-3.5 h-3.5 rounded-full bg-method-ldf border border-foreground flex items-center justify-center text-[7px] font-bold text-primary-foreground">DG</div>
                <span className="text-muted-foreground">Distributed gen. (sgen)</span>
              </div>
            )}
            {!!topology.line_measurements?.length && (
              <div className="flex items-center gap-1.5">
                <div className="w-3.5 h-3.5 rounded-full bg-card border-2 border-method-dc flex items-center justify-center text-[7px] font-bold text-method-dc">S</div>
                <span className="text-muted-foreground">Branch-flow meter (P_ij/Q_ij)</span>
              </div>
            )}
            {allSwitches.some(s => !s.closed) && (
              <div className="flex items-center gap-1.5">
                <div className="h-0 w-8 border-t-2 border-dashed border-muted-foreground" />
                <span className="text-muted-foreground">open switch ({allSwitches.filter(s => !s.closed).length})</span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
