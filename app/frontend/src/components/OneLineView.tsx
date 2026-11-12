import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import * as d3 from 'd3'
import type { PowerFlowResult, Topology } from '@/lib/types'
import type { TopologySelection } from '@/lib/selection'
import { MEASUREMENT_KIND_INFO, buildMeasurementIndex } from '@/lib/measurements'
import { BAR_HEIGHT, computeOneLineLayout, type OneLineLayout } from '@/lib/oneLineLayout'
import { getElk } from '@/lib/elk'
import { Button } from '@/components/ui/button'
import { CircleNotch } from '@phosphor-icons/react'

export interface OneLineHit {
  x: number
  y: number
  additive: boolean
}

export interface OneLineHandle {
  fit: () => void
}

interface OneLineViewProps {
  topology: Topology
  result?: PowerFlowResult | null
  voltageLimits?: { min: number; max: number }
  selection?: TopologySelection
  /** Normally-open switches, drawn as dashed ties with an open-switch glyph. */
  openTies: { from: number; to: number }[]
  width: number
  height: number
  onBusClick?: (busId: number, hit: OneLineHit) => void
  onLineClick?: (lineId: number, hit: OneLineHit) => void
  /** Optional temporal overlay; independent of layout and pan/zoom. */
  animateFlows?: boolean
  showFlowDirection?: boolean
}

// A layered layout of thousands of buses is both slow to compute and, as a
// picture, unreadable — the Tree/Map views are the right tools there.
const AUTO_LAYOUT_MAX_BUSES = 800

/** One colour per nominal voltage level, highest first — the convention in
 *  single-line diagrams (HV / MV / LV read as different colours). */
const LEVEL_TOKENS = ['destructive', 'method-dc', 'status-good', 'method-ldf', 'status-warn', 'status-info']

const ARROW_ID = 'oneline-load-arrow'

export const OneLineView = forwardRef<OneLineHandle, OneLineViewProps>(function OneLineView(
  { topology, result, voltageLimits, selection, openTies, width, height, onBusClick, onLineClick, animateFlows = false, showFlowDirection = false },
  ref
) {
  const svgRef = useRef<SVGSVGElement>(null)
  const rootRef = useRef<SVGGElement>(null)
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null)
  const layoutRef = useRef<OneLineLayout | null>(null)
  const [layout, setLayout] = useState<OneLineLayout | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [force, setForce] = useState(false)

  const tooBig = topology.buses.length > AUTO_LAYOUT_MAX_BUSES && !force

  // Only structure moves nodes: a meter change or a new power-flow result
  // must not trigger a re-layout.
  const structureKey = useMemo(
    () =>
      [
        topology.id,
        topology.buses.map((b) => `${b.id}${b.type === 'slack' ? 's' : ''}`).join(','),
        topology.lines.map((l) => `${l.id}:${l.from}-${l.to}`).join(','),
        openTies.map((t) => `${t.from}-${t.to}`).join(','),
      ].join('|'),
    [topology.id, topology.buses, topology.lines, openTies]
  )

  useEffect(() => {
    if (tooBig) return
    let cancelled = false
    setBusy(true)
    setError(null)
    computeOneLineLayout(getElk(), topology, openTies)
      .then((result) => {
        if (cancelled) return
        layoutRef.current = result
        setLayout(result)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setBusy(false)
      })
    return () => {
      cancelled = true
    }
    // structureKey covers exactly the inputs the layout depends on
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [structureKey, tooBig])

  const fit = useCallback(() => {
    const svg = svgRef.current
    const zoom = zoomRef.current
    const l = layoutRef.current
    if (!svg || !zoom || !l || !l.bounds.width || !l.bounds.height) return
    const { x: bx, y: by, width: bw, height: bh } = l.bounds
    const pad = 40
    const scale = Math.max(Math.min((width - pad * 2) / bw, (height - pad * 2) / bh, 1.6), 0.02)
    const tx = (width - bw * scale) / 2 - bx * scale
    const ty = (height - bh * scale) / 2 - by * scale
    d3.select(svg).call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale))
  }, [width, height])
  useImperativeHandle(ref, () => ({ fit }), [fit])

  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.02, 8])
      .on('zoom', (event) => {
        rootRef.current?.setAttribute('transform', event.transform.toString())
      })
    d3.select(svg).call(zoom).on('dblclick.zoom', null)
    zoomRef.current = zoom
    return () => {
      d3.select(svg).on('.zoom', null)
    }
  }, [])

  // Re-fit when a new layout lands or the panel is resized (the table dock
  // opening shrinks the diagram), not on every re-render.
  useEffect(() => {
    if (layoutRef.current) fit()
  }, [layout, fit])

  const index = useMemo(() => buildMeasurementIndex(topology), [topology])
  const busById = useMemo(() => new Map(topology.buses.map((b) => [b.id, b])), [topology.buses])
  const busResults = useMemo(() => new Map((result?.buses ?? []).map((b) => [b.id, b])), [result])
  const lineResults = useMemo(() => new Map((result?.lines ?? []).map((l) => [l.id, l])), [result])
  const maxFlow = useMemo(
    () => Math.max(0.0001, ...(result?.lines ?? []).map((l) => Math.abs(l.pFrom))),
    [result]
  )
  const vMin = voltageLimits?.min ?? 0.95
  const vMax = voltageLimits?.max ?? 1.05

  const levels = useMemo(() => {
    const kv = [...new Set(topology.buses.map((b) => b.nominal_voltage_kv).filter((v): v is number => typeof v === 'number'))]
    return kv.sort((a, b) => b - a)
  }, [topology.buses])
  const hasUnknownLevel = useMemo(
    () => levels.length > 0 && topology.buses.some((b) => b.nominal_voltage_kv == null),
    [levels, topology.buses]
  )
  const levelColor = (kv?: number) => {
    if (levels.length === 0 || (levels.length < 2 && !hasUnknownLevel)) return 'var(--color-foreground)'
    if (kv == null) return 'var(--color-muted-foreground)'
    return `var(--color-${LEVEL_TOKENS[Math.min(levels.indexOf(kv), LEVEL_TOKENS.length - 1)]})`
  }
  const barColor = (busId: number) => {
    const solved = busResults.get(busId)
    if (result && solved) {
      if (solved.voltage < vMin) return 'var(--color-status-info)'
      if (solved.voltage > vMax) return 'var(--color-destructive)'
      return 'var(--color-status-good)'
    }
    return levelColor(busById.get(busId)?.nominal_voltage_kv)
  }

  const hitFrom = (event: React.MouseEvent): OneLineHit => {
    const rect = svgRef.current?.getBoundingClientRect()
    return {
      x: event.clientX - (rect?.left ?? 0),
      y: event.clientY - (rect?.top ?? 0),
      additive: event.ctrlKey || event.metaKey || event.shiftKey,
    }
  }

  return (
    <div className="relative bg-background" style={{ width, height }}>
      <svg ref={svgRef} width={width} height={height} className="touch-none" style={{ cursor: 'grab' }}>
        <defs>
          <marker id={ARROW_ID} viewBox="0 0 10 10" refX="5" refY="9" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L5,10 L10,0 z" fill="var(--color-destructive)" />
          </marker>
        </defs>
        <g ref={rootRef}>
          {layout && (
            <>
              {/* Branches */}
              {layout.edges.map((e) => {
                const d = 'M' + e.points.map((p) => p.join(',')).join(' L')
                const selected = e.lineId != null && selection?.lines.has(e.lineId)
                const solved = e.lineId != null ? lineResults.get(e.lineId) : undefined
                const thickness = solved ? 1.5 + 4 * (Math.abs(solved.pFrom) / maxFlow) : 2
                const mid = e.points[Math.floor((e.points.length - 1) / 2)]
                const next = e.points[Math.floor((e.points.length - 1) / 2) + 1] ?? mid
                const lx = (mid[0] + next[0]) / 2
                const ly = (mid[1] + next[1]) / 2
                const flowAngle = Math.atan2(next[1] - mid[1], next[0] - mid[0]) * 180 / Math.PI + ((solved?.pFrom ?? 0) < 0 ? 180 : 0)
                return (
                  <g key={e.key}>
                    <title>{solved ? `L${e.lineId}: P from ${e.from} to ${e.to} = ${solved.pFrom.toFixed(4)} pu` : e.key}</title>
                    <path
                      d={d}
                      fill="none"
                      stroke={selected ? 'var(--color-selection)' : e.open ? 'var(--color-muted-foreground)' : solved ? 'var(--color-status-warn)' : levelColor(busById.get(e.from)?.nominal_voltage_kv)}
                      strokeWidth={selected ? 4 : thickness}
                      strokeDasharray={e.open ? '6 4' : undefined}
                      strokeOpacity={e.open ? 0.8 : 0.9}
                      strokeLinejoin="round"
                    />
                    {showFlowDirection && solved && !e.open && Math.abs(solved.pFrom) > 1e-7 && (
                      <>
                        <path d="M-5,-4 L5,0 L-5,4" transform={`translate(${lx},${ly}) rotate(${flowAngle})`} fill="none" stroke="var(--color-status-warn)" strokeWidth={2} style={{ pointerEvents: 'none' }} />
                        {animateFlows && <path d={d} fill="none" stroke="var(--color-status-info)" strokeWidth={2} strokeDasharray="3 12" className="temporal-flow-motion" style={{ animationDirection: solved.pFrom < 0 ? 'reverse' : 'normal', pointerEvents: 'none' }} />}
                      </>
                    )}
                    {e.lineId != null && (
                      <path
                        d={d}
                        fill="none"
                        stroke="transparent"
                        strokeWidth={14}
                        style={{ cursor: 'pointer' }}
                        onClick={(ev) => {
                          ev.stopPropagation()
                          onLineClick?.(e.lineId!, hitFrom(ev))
                        }}
                      />
                    )}
                    {e.open && (
                      <g transform={`translate(${lx},${ly})`} style={{ pointerEvents: 'none' }}>
                        <rect x={-6} y={-6} width={12} height={12} fill="var(--color-background)" />
                        <circle cx={-4.5} r={1.8} fill="var(--color-foreground)" />
                        <circle cx={4.5} r={1.8} fill="var(--color-foreground)" />
                        <line x1={-4.5} y1={0} x2={1} y2={-4.5} stroke="var(--color-foreground)" strokeWidth={1.5} strokeLinecap="round" />
                      </g>
                    )}
                    {e.lineId != null && (
                      <text
                        x={lx + 5}
                        y={ly - 3}
                        fontSize={9}
                        fill="var(--color-muted-foreground)"
                        style={{ pointerEvents: 'none' }}
                      >
                        {solved ? `L${e.lineId}  ${Math.abs(solved.pFrom).toFixed(2)} pu` : `L${e.lineId}`}
                      </text>
                    )}
                  </g>
                )
              })}

              {/* Buses: a bar, with generator above and load/DG below */}
              {layout.nodes.map((n) => {
                const bus = busById.get(n.id)
                if (!bus) return null
                const selected = selection?.buses.has(n.id)
                const color = barColor(n.id)
                const solved = busResults.get(n.id)
                const meter = index.busKind.get(n.id)
                const generator = bus.type !== 'pq' || bus.pGen > 0
                return (
                  <g
                    key={n.id}
                    style={{ cursor: 'pointer' }}
                    onClick={(ev) => {
                      ev.stopPropagation()
                      onBusClick?.(n.id, hitFrom(ev))
                    }}
                  >
                    <title>{`${bus.name || `Bus ${bus.id}`} (${bus.type.toUpperCase()})${bus.nominal_voltage_kv ? ` · ${bus.nominal_voltage_kv} kV` : ''}`}</title>
                    {/* generous invisible hit area around a thin bar */}
                    <rect x={n.x - 6} y={n.y - 16} width={n.w + 12} height={n.h + 32} fill="transparent" />
                    {selected && (
                      <rect
                        x={n.x - 4}
                        y={n.y - 4}
                        width={n.w + 8}
                        height={n.h + 8}
                        rx={4}
                        fill="none"
                        stroke="var(--color-selection)"
                        strokeWidth={3}
                      />
                    )}
                    <rect x={n.x} y={n.y} width={n.w} height={BAR_HEIGHT} rx={2} fill={color} />
                    <text x={n.x} y={n.y - 5} fontSize={10.5} fontWeight={600} fill="var(--color-foreground)" style={{ pointerEvents: 'none' }}>
                      {bus.name || `Bus ${bus.id}`}
                    </text>
                    {solved && (
                      <text x={n.x + n.w} y={n.y - 5} fontSize={9} textAnchor="end" fontWeight={700} fill="var(--color-foreground)" style={{ pointerEvents: 'none' }}>
                        {solved.voltage.toFixed(3)} pu
                      </text>
                    )}
                    {generator && (
                      <g transform={`translate(${n.x + n.w - 14},${n.y + BAR_HEIGHT + 22})`} style={{ pointerEvents: 'none' }}>
                        <line x1={0} y1={-22} x2={0} y2={-11} stroke="var(--color-foreground)" strokeWidth={1.5} />
                        <circle r={11} fill={bus.type === 'slack' ? 'var(--color-primary)' : 'var(--color-card)'} stroke="var(--color-foreground)" strokeWidth={1.5} />
                        <text textAnchor="middle" dy={3.5} fontSize={10} fontWeight={700} fill={bus.type === 'slack' ? 'var(--color-primary-foreground)' : 'var(--color-foreground)'}>
                          {bus.type === 'slack' ? '~' : 'G'}
                        </text>
                      </g>
                    )}
                    {bus.pLoad > 0 && (
                      <line
                        x1={n.x + 12}
                        y1={n.y + BAR_HEIGHT}
                        x2={n.x + 12}
                        y2={n.y + BAR_HEIGHT + 22}
                        stroke="var(--color-destructive)"
                        strokeWidth={2}
                        markerEnd={`url(#${ARROW_ID})`}
                        style={{ pointerEvents: 'none' }}
                      />
                    )}
                    {(bus.pGenDG ?? 0) !== 0 && (
                      <g transform={`translate(${n.x + n.w - 14},${n.y + BAR_HEIGHT + 18})`} style={{ pointerEvents: 'none' }}>
                        <line x1={0} y1={-10} x2={0} y2={-8} stroke="var(--color-foreground)" strokeWidth={1.5} />
                        <circle r={8} fill="var(--color-method-ldf)" stroke="var(--color-foreground)" strokeWidth={1} />
                        <text textAnchor="middle" dy={2.5} fontSize={6.5} fontWeight={700} fill="var(--color-primary-foreground)">
                          DG
                        </text>
                      </g>
                    )}
                    {meter && (
                      <g transform={`translate(${n.x - 10},${n.y + BAR_HEIGHT / 2})`} style={{ pointerEvents: 'none' }}>
                        <circle r={7} fill="var(--color-card)" stroke={MEASUREMENT_KIND_INFO[meter].colorVar} strokeWidth={1.8} />
                        <text textAnchor="middle" dy={2.8} fontSize={7.5} fontWeight={700} fill={MEASUREMENT_KIND_INFO[meter].colorVar}>
                          {MEASUREMENT_KIND_INFO[meter].shortLabel[0]}
                        </text>
                      </g>
                    )}
                  </g>
                )
              })}
            </>
          )}
        </g>
      </svg>

      {(levels.length > 1 || hasUnknownLevel) && !result && (
        <div className="absolute left-2 bottom-2 rounded-md border bg-card/95 px-2 py-1 text-[11px] shadow">
          <div className="mb-0.5 font-semibold text-muted-foreground">Voltage level</div>
          {levels.map((kv) => (
            <div key={kv} className="flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-5 rounded-sm" style={{ background: levelColor(kv) }} />
              {kv} kV
            </div>
          ))}
          {hasUnknownLevel && (
            <div className="flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-5 rounded-sm" style={{ background: levelColor(undefined) }} />
              unknown
            </div>
          )}
        </div>
      )}
      {result && (
        <div className="absolute left-2 bottom-2 rounded-md border bg-card/95 px-2 py-1 text-[11px] shadow">
          <div className="mb-0.5 font-semibold text-muted-foreground">Voltage (pu)</div>
          <div className="flex items-center gap-1.5"><span className="inline-block h-1.5 w-5 rounded-sm bg-status-info" />below {vMin}</div>
          <div className="flex items-center gap-1.5"><span className="inline-block h-1.5 w-5 rounded-sm bg-status-good" />within limits</div>
          <div className="flex items-center gap-1.5"><span className="inline-block h-1.5 w-5 rounded-sm bg-destructive" />above {vMax}</div>
        </div>
      )}
      {busy && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/60 text-sm text-muted-foreground">
          <CircleNotch className="mr-2 h-4 w-4 animate-spin" /> Laying out the one-line diagram…
        </div>
      )}
      {error && (
        <div className="absolute inset-x-0 top-3 mx-auto w-fit max-w-md rounded-md border border-destructive bg-card p-2 text-xs text-destructive shadow">
          Could not lay out the diagram: {error}
        </div>
      )}
      {tooBig && (
        <div className="absolute inset-x-0 top-1/3 mx-auto w-fit max-w-md rounded-lg border bg-card p-4 text-center text-xs shadow">
          <p className="mb-2">
            {topology.buses.length} buses is too many for a readable one-line diagram. Use the Map or Tree view — or lay it out anyway (may take a few seconds and look dense).
          </p>
          <Button type="button" size="sm" className="h-7 text-xs" onClick={() => setForce(true)}>
            Lay out anyway
          </Button>
        </div>
      )}
    </div>
  )
})
