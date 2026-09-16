import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef } from 'react'
import * as d3 from 'd3'
import type { PowerFlowResult } from '@/lib/types'
import { MEASUREMENT_KIND_INFO } from '@/lib/measurements'
import {
  elbowPoints,
  layoutBounds,
  type LayoutLink,
  type LayoutNode,
  type TopologyLayout,
  type TreeOrientation,
} from '@/lib/topologyLayout'

/**
 * Canvas renderer for the network diagram.
 *
 * The SVG renderer in TopologyDiagram builds one <g> per bus (circle, id,
 * name, meter badge, G/L/DG glyphs) and up to three elements per line — call
 * it 6-10 nodes per bus. A few-thousand-bus feeder therefore lands ~60-100k
 * live SVG elements in the document, and the browser pays for all of them on
 * every paint, hit-test and style recalc whether or not anything moved. That
 * is the ceiling this component exists to get past: one <canvas>, a handful
 * of batched paths, and hit-testing done in JS against the layout arrays.
 *
 * The SVG path is still the one used for small networks, where its per-element
 * niceties (native tooltips, DOM-anchored popovers, crisp text at any zoom)
 * are free. See DIAGRAM_RENDERER in TopologyDiagram.
 */

/** Cursor-relative click, in container coordinates — what the meter popovers
 *  anchor to. */
export interface CanvasHit {
  x: number
  y: number
}

export interface TopologyCanvasHandle {
  fit: () => void
}

interface TopologyCanvasViewProps {
  layout: TopologyLayout
  viewMode: 'spatial' | 'tree'
  orientation: TreeOrientation
  width: number
  height: number
  result?: PowerFlowResult | null
  voltageLimits: { min: number; max: number }
  /** Draw per-node text and badges. Off on large networks: at the zoom level
   *  where a 3000-bus feeder fits on screen the labels overlap into noise
   *  anyway, and text is by far the most expensive thing to rasterize. */
  detailed: boolean
  onBusClick?: (busId: number, hit: CanvasHit) => void
  onLineClick?: (lineId: number, hit: CanvasHit) => void
  onSwitchToggle?: (switchId: number, closed: boolean) => void
  /** Persist a dragged bus position so a later redraw resumes from it. */
  onNodeMoved?: (busId: number, x: number, y: number) => void
  /** Changes whenever the layout should be re-fitted to the viewport
   *  (structure, size, view mode). A redraw from a meter toggle keeps the
   *  pan/zoom the user already set. */
  fitKey: string
}

/** Canvas can't read `var(--color-…)`, so resolve the palette to concrete
 *  colors once per theme. Cheap, but getComputedStyle forces a style recalc,
 *  so it must not happen inside the draw loop. */
const PALETTE_VARS = [
  'card',
  'primary',
  'primary-foreground',
  'accent',
  'muted',
  'muted-foreground',
  'foreground',
  'border',
  'destructive',
  'status-good',
  'status-warn',
  'status-info',
  'method-ldf',
  'method-dc',
] as const

type PaletteKey = (typeof PALETTE_VARS)[number]
type Palette = Record<PaletteKey, string>

function readPalette(): Palette {
  const style = getComputedStyle(document.documentElement)
  const out = {} as Palette
  for (const key of PALETTE_VARS) {
    out[key] = style.getPropertyValue(`--color-${key}`).trim() || style.getPropertyValue(`--${key}`).trim() || '#888'
  }
  return out
}

/** Squared distance from point (px,py) to segment (ax,ay)-(bx,by). */
function distToSegmentSq(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax
  const dy = by - ay
  const lenSq = dx * dx + dy * dy
  let t = lenSq === 0 ? 0 : ((px - ax) * dx + (py - ay) * dy) / lenSq
  t = t < 0 ? 0 : t > 1 ? 1 : t
  const cx = ax + t * dx
  const cy = ay + t * dy
  return (px - cx) ** 2 + (py - cy) ** 2
}

function nodeRadius(node: LayoutNode): number {
  if (node.type === 'slack') return 22
  if (node.type === 'pv') return 18
  return 15
}

export const TopologyCanvasView = forwardRef<TopologyCanvasHandle, TopologyCanvasViewProps>(
  function TopologyCanvasView(
    {
      layout,
      viewMode,
      orientation,
      width,
      height,
      result,
      voltageLimits,
      detailed,
      onBusClick,
      onLineClick,
      onSwitchToggle,
      onNodeMoved,
      fitKey,
    },
    ref
  ) {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const transformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity)
    const zoomRef = useRef<d3.ZoomBehavior<HTMLCanvasElement, unknown> | null>(null)
    const paletteRef = useRef<Palette | null>(null)
    const frameRef = useRef<number | null>(null)
    const lastFitKeyRef = useRef<string | null>(null)
    // Live layout — mutated in place by a drag so the redraw sees the new
    // position without a React state round-trip per pointer move.
    const layoutRef = useRef(layout)
    layoutRef.current = layout
    // Spatial index over bus positions, rebuilt when the layout changes (and
    // after a drag settles). Hover fires on every frame the pointer moves, so
    // hit-testing has to stay off the O(buses) path.
    const quadtreeRef = useRef<d3.Quadtree<LayoutNode> | null>(null)
    const rebuildQuadtree = useCallback(() => {
      quadtreeRef.current = d3
        .quadtree<LayoutNode>()
        .x((d) => d.x)
        .y((d) => d.y)
        .addAll(layoutRef.current.nodes)
    }, [])

    const busResults = useMemo(
      () => new Map((result?.buses ?? []).map((bus) => [bus.id, bus])),
      [result]
    )
    const lineResults = useMemo(
      () => new Map((result?.lines ?? []).map((line) => [line.id, line])),
      [result]
    )
    const maxAbsFlow = useMemo(() => {
      let max = 0.0001
      for (const line of layout.links) {
        const flow = Math.abs(lineResults.get(line.id)?.pFrom ?? 0)
        if (flow > max) max = flow
      }
      return max
    }, [layout.links, lineResults])

    const drawStateRef = useRef({
      viewMode,
      orientation,
      result,
      voltageLimits,
      detailed,
      busResults,
      lineResults,
      maxAbsFlow,
      width,
      height,
    })
    drawStateRef.current = {
      viewMode,
      orientation,
      result,
      voltageLimits,
      detailed,
      busResults,
      lineResults,
      maxAbsFlow,
      width,
      height,
    }

    const draw = useCallback(() => {
      frameRef.current = null
      const canvas = canvasRef.current
      if (!canvas) return
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      if (!paletteRef.current) paletteRef.current = readPalette()
      const c = paletteRef.current
      const {
        viewMode: mode,
        orientation: orient,
        result: res,
        voltageLimits: limits,
        detailed: showDetail,
        busResults: busRes,
        lineResults: lineRes,
        maxAbsFlow: maxFlow,
        width: w,
        height: h,
      } = drawStateRef.current
      const { nodes, nodeById, links, switchLinks, extraLinks, glyphSwitches } = layoutRef.current
      const t = transformRef.current

      const dpr = window.devicePixelRatio || 1
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.scale(dpr, dpr)
      ctx.translate(t.x, t.y)
      ctx.scale(t.k, t.k)

      // Viewport in layout coordinates — everything outside is skipped
      // before it reaches the rasterizer.
      const viewMinX = -t.x / t.k
      const viewMinY = -t.y / t.k
      const viewMaxX = viewMinX + w / t.k
      const viewMaxY = viewMinY + h / t.k
      const cullPad = 60
      const visible = (x: number, y: number) =>
        x >= viewMinX - cullPad && x <= viewMaxX + cullPad && y >= viewMinY - cullPad && y <= viewMaxY + cullPad
      const segmentVisible = (ax: number, ay: number, bx: number, by: number) =>
        Math.max(ax, bx) >= viewMinX - cullPad &&
        Math.min(ax, bx) <= viewMaxX + cullPad &&
        Math.max(ay, by) >= viewMinY - cullPad &&
        Math.min(ay, by) <= viewMaxY + cullPad

      // Everything below is drawn in layout coordinates with the context
      // scaled by t.k, so at the zoom where a 3000-bus network fits on screen
      // (k ~ 0.03) a 2px stroke rasterizes to 0.05px and the whole diagram
      // washes out to almost nothing. These floors keep every stroke and node
      // at least about a pixel wide on screen, whatever the zoom.
      const minStroke = 0.9 / t.k
      const minRadius = 1.8 / t.k

      const voltageColor = (voltage?: number) => {
        if (voltage == null) return c.muted
        if (voltage < limits.min) return c['status-info']
        if (voltage > limits.max) return c.destructive
        return c['status-good']
      }

      // ── Branches ──────────────────────────────────────────────────────
      // Batched by (color, width) so the whole feeder is a handful of
      // beginPath/stroke pairs instead of one per line. Widths are bucketed
      // to 0.5px because a stroke width difference finer than that is not
      // visible but would split the batch.
      const strokeLine = (link: LayoutLink, path: Map<string, Path2D>, baseWidth: number, flowScale: number) => {
        const from = nodeById.get(link.from)
        const to = nodeById.get(link.to)
        if (!from || !to) return
        const solved = lineRes.get(link.id)
        const color = mode === 'tree'
          ? (solved ? c['status-warn'] : c.foreground)
          : (solved ? c['status-warn'] : c.accent)
        const flow = Math.abs(solved?.pFrom ?? 0)
        const wide = Math.max(res ? 1.5 + flowScale * (flow / maxFlow) : baseWidth, minStroke)
        const bucket = Math.round(wide * 2) / 2
        const key = `${color}|${bucket}`
        let p = path.get(key)
        if (!p) {
          p = new Path2D()
          path.set(key, p)
        }
        if (mode === 'tree') {
          const pts = elbowPoints(from, to, orient)
          if (!segmentVisible(from.x, from.y, to.x, to.y)) return
          p.moveTo(pts[0][0], pts[0][1])
          for (let i = 1; i < pts.length; i++) p.lineTo(pts[i][0], pts[i][1])
        } else {
          if (!segmentVisible(from.x, from.y, to.x, to.y)) return
          p.moveTo(from.x, from.y)
          p.lineTo(to.x, to.y)
        }
      }

      const linePaths = new Map<string, Path2D>()
      for (const link of links) {
        strokeLine(link, linePaths, mode === 'tree' ? 1.75 : 2, mode === 'tree' ? 4 : 5)
      }
      // Zoomed far out the branches overlap heavily; the low alpha that keeps
      // a small diagram airy turns a large one into a faint smudge.
      const linkAlpha = showDetail ? (res ? 0.78 : 0.6) : 0.85
      ctx.globalAlpha = mode === 'tree' ? (res ? 0.85 : 0.75) : linkAlpha
      ctx.lineCap = 'round'
      for (const [key, path] of linePaths) {
        const [color, bucket] = key.split('|')
        ctx.strokeStyle = color
        ctx.lineWidth = Number(bucket)
        ctx.stroke(path)
      }
      ctx.globalAlpha = 1

      // ── Dashed connections: open switches, and loop lines the spanning
      // tree didn't use ─────────────────────────────────────────────────
      const drawDashed = (items: { from: number; to: number }[], color: string) => {
        if (!items.length) return
        const path = new Path2D()
        let any = false
        for (const item of items) {
          const from = nodeById.get(item.from)
          const to = nodeById.get(item.to)
          if (!from || !to || !segmentVisible(from.x, from.y, to.x, to.y)) continue
          path.moveTo(from.x, from.y)
          path.lineTo(to.x, to.y)
          any = true
        }
        if (!any) return
        ctx.save()
        ctx.setLineDash([5 / t.k, 4 / t.k])
        ctx.strokeStyle = color
        ctx.lineWidth = Math.max(1.5, minStroke)
        ctx.globalAlpha = 0.6
        ctx.stroke(path)
        ctx.restore()
      }
      drawDashed(extraLinks, c['status-warn'])
      drawDashed(switchLinks, c['muted-foreground'])

      // ── Switch glyphs ─────────────────────────────────────────────────
      for (const sw of glyphSwitches) {
        const from = nodeById.get(sw.from)
        const to = nodeById.get(sw.to)
        if (!from || !to) continue
        const mx = (from.x + to.x) / 2
        const my = (from.y + to.y) / 2
        if (!visible(mx, my)) continue
        const angle = Math.atan2(to.y - from.y, to.x - from.x)
        ctx.save()
        ctx.translate(mx, my)
        ctx.rotate(angle)
        if (!sw.closed) {
          // Mask the dashed line under the gap, so the blade reads as open.
          ctx.fillStyle = c.card
          ctx.fillRect(-6, -6, 12, 12)
        }
        ctx.fillStyle = c.foreground
        ctx.beginPath()
        ctx.arc(-4.5, 0, 1.8, 0, Math.PI * 2)
        ctx.fill()
        ctx.beginPath()
        ctx.arc(4.5, 0, 1.8, 0, Math.PI * 2)
        ctx.fill()
        ctx.strokeStyle = c.foreground
        ctx.lineWidth = 1.5
        ctx.beginPath()
        ctx.moveTo(-4.5, 0)
        if (sw.closed) ctx.lineTo(4.5, 0)
        else ctx.lineTo(1, -4.5)
        ctx.stroke()
        ctx.restore()
      }

      // ── Buses ─────────────────────────────────────────────────────────
      if (mode === 'tree') {
        drawTreeBuses(ctx, nodes, c, showDetail, res, busRes, voltageColor, orient, visible, minStroke)
      } else {
        drawSpatialBuses(ctx, nodes, c, showDetail, res, busRes, voltageColor, limits, visible, minStroke, minRadius)
      }

      // ── Labels — only in detailed mode. Text is the single most expensive
      // thing on a canvas, and at the zoom where a large feeder fits it is
      // unreadable overlap regardless. ──────────────────────────────────
      if (showDetail) {
        ctx.textAlign = 'center'
        ctx.textBaseline = 'alphabetic'
        ctx.fillStyle = c['muted-foreground']
        ctx.font = `${mode === 'tree' ? 10 : 9.5}px Inter, sans-serif`
        const near = mode === 'tree' ? 0.28 : 0.2
        for (const link of links) {
          const from = nodeById.get(link.from)
          const to = nodeById.get(link.to)
          if (!from || !to) continue
          const lx = from.x * near + to.x * (1 - near)
          const ly = from.y * near + to.y * (1 - near) - 6
          if (!visible(lx, ly)) continue
          const solved = lineRes.get(link.id)
          ctx.fillText(solved ? `L${link.id} ${Math.abs(solved.pFrom).toFixed(2)} pu` : `L${link.id}`, lx, ly)
        }
      }

      // ── Meter badges ──────────────────────────────────────────────────
      if (showDetail) {
        const badgeAt = (x: number, y: number, kind: string, radius: number, fontSize: number) => {
          if (!visible(x, y)) return
          const info = MEASUREMENT_KIND_INFO[kind as keyof typeof MEASUREMENT_KIND_INFO]
          const color = paletteColor(c, info.colorVar)
          ctx.beginPath()
          ctx.arc(x, y, radius, 0, Math.PI * 2)
          ctx.fillStyle = c.card
          ctx.fill()
          ctx.strokeStyle = color
          ctx.lineWidth = radius > 6 ? 2 : 1.75
          ctx.stroke()
          ctx.fillStyle = color
          ctx.font = `700 ${fontSize}px Inter, sans-serif`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(info.shortLabel[0], x, y)
        }
        for (const node of nodes) {
          if (!node.measurementKind) continue
          const [dx, dy] = mode === 'tree'
            ? node.type === 'slack' ? [46, 0] : [-14, -5]
            : [15, 17]
          badgeAt(node.x + dx, node.y + dy, node.measurementKind, 8, 9)
        }
        for (const link of links) {
          if (!link.lineMeasurementKind) continue
          const from = nodeById.get(link.from)
          const to = nodeById.get(link.to)
          if (!from || !to) continue
          badgeAt(from.x * 0.8 + to.x * 0.2, from.y * 0.8 + to.y * 0.2, link.lineMeasurementKind, 6, 7.5)
        }
      } else {
        // Compact stand-in: a filled dot in the meter's color, no glyph. Keeps
        // "where are my meters" readable on a large feeder for one arc each.
        for (const node of nodes) {
          if (!node.measurementKind || !visible(node.x, node.y)) continue
          ctx.beginPath()
          ctx.arc(node.x + nodeRadius(node) * 0.75, node.y - nodeRadius(node) * 0.75, 3.5, 0, Math.PI * 2)
          ctx.fillStyle = paletteColor(c, MEASUREMENT_KIND_INFO[node.measurementKind].colorVar)
          ctx.fill()
        }
      }
    }, [])

    const scheduleDraw = useCallback(() => {
      if (frameRef.current != null) return
      frameRef.current = requestAnimationFrame(draw)
    }, [draw])

    /** Fit the whole layout into the viewport. Computed from the layout
     *  arrays, not getBBox() — no DOM to measure, and no forced reflow. */
    const fit = useCallback(() => {
      const canvas = canvasRef.current
      const zoom = zoomRef.current
      if (!canvas || !zoom) return
      const bounds = layoutBounds(layoutRef.current.nodes, 48)
      if (!bounds.width || !bounds.height) return
      const { width: w, height: h } = drawStateRef.current
      const scale = Math.max(Math.min(w / bounds.width, h / bounds.height, 1.5), 0.02)
      const tx = w / 2 - scale * (bounds.x + bounds.width / 2)
      const ty = h / 2 - scale * (bounds.y + bounds.height / 2)
      // Applied instantly, not as a transition: animating the transform
      // repaints the entire canvas every frame for no information gain, and
      // on a large network that is exactly the stutter we're removing.
      d3.select(canvas).call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale))
    }, [])

    useImperativeHandle(ref, () => ({ fit }), [fit])

    // ── Zoom / pan ──────────────────────────────────────────────────────
    useEffect(() => {
      const canvas = canvasRef.current
      if (!canvas) return
      const zoom = d3
        .zoom<HTMLCanvasElement, unknown>()
        .scaleExtent([0.02, 4])
        .on('zoom', (event) => {
          transformRef.current = event.transform
          scheduleDraw()
        })
      d3.select(canvas).call(zoom)
      zoomRef.current = zoom
      return () => {
        d3.select(canvas).on('.zoom', null)
      }
    }, [scheduleDraw])

    // ── Drag a bus ──────────────────────────────────────────────────────
    // Moves the one bus under the cursor. The SVG version restarted the
    // force simulation on drag, which re-solved and repainted the whole
    // network on every pointer move; on a large feeder that is unusable, and
    // "nudge this bus somewhere readable" is what the gesture is actually
    // for.
    useEffect(() => {
      const canvas = canvasRef.current
      if (!canvas || viewMode !== 'spatial') return
      let dragging: LayoutNode | null = null
      const toLayoutCoords = (event: { x: number; y: number }) => transformRef.current.invert([event.x, event.y])

      const drag = d3
        .drag<HTMLCanvasElement, unknown>()
        .subject((event) => {
          const [lx, ly] = transformRef.current.invert([event.x, event.y])
          return findNode(quadtreeRef.current, lx, ly, 24 / transformRef.current.k) ?? null
        })
        .on('start', (event) => {
          dragging = event.subject as LayoutNode | null
        })
        .on('drag', (event) => {
          if (!dragging) return
          const [lx, ly] = toLayoutCoords(event)
          dragging.x = lx
          dragging.y = ly
          dragging.fx = lx
          dragging.fy = ly
          scheduleDraw()
        })
        .on('end', () => {
          if (dragging) {
            onNodeMoved?.(dragging.id, dragging.x, dragging.y)
            rebuildQuadtree()
          }
          dragging = null
        })
        // Only start a drag when the pointer is actually on a bus, so an
        // empty-space drag still pans via the zoom behavior.
        .filter((event) => {
          if ((event as MouseEvent).button != null && (event as MouseEvent).button !== 0) return false
          const rect = canvas.getBoundingClientRect()
          const e = event as MouseEvent
          const [lx, ly] = transformRef.current.invert([e.clientX - rect.left, e.clientY - rect.top])
          return !!findNode(quadtreeRef.current, lx, ly, 24 / transformRef.current.k)
        })

      d3.select(canvas).call(drag)
      return () => {
        d3.select(canvas).on('.drag', null)
      }
    }, [viewMode, onNodeMoved, scheduleDraw, rebuildQuadtree])

    // ── Click: bus > switch > line ──────────────────────────────────────
    useEffect(() => {
      const canvas = canvasRef.current
      if (!canvas) return
      const onClick = (event: MouseEvent) => {
        const rect = canvas.getBoundingClientRect()
        const px = event.clientX - rect.left
        const py = event.clientY - rect.top
        const [lx, ly] = transformRef.current.invert([px, py])
        const k = transformRef.current.k
        const { nodeById, links, glyphSwitches } = layoutRef.current

        const node = findNode(quadtreeRef.current, lx, ly, 24 / k)
        if (node && onBusClick) {
          onBusClick(node.id, { x: px, y: py })
          return
        }
        // Switch glyphs are small; give them the same forgiving radius the
        // SVG hit rect had (20x16 around the midpoint).
        const swTol = 12 / k
        for (const sw of glyphSwitches) {
          const from = nodeById.get(sw.from)
          const to = nodeById.get(sw.to)
          if (!from || !to) continue
          const mx = (from.x + to.x) / 2
          const my = (from.y + to.y) / 2
          if ((lx - mx) ** 2 + (ly - my) ** 2 <= swTol * swTol) {
            onSwitchToggle?.(sw.id, !sw.closed)
            return
          }
        }
        if (!onLineClick) return
        const lineTol = 7 / k
        const link = findLink(links, nodeById, lx, ly, lineTol, viewMode === 'tree' ? orientation : null)
        if (link) onLineClick(link.id, { x: px, y: py })
      }
      canvas.addEventListener('click', onClick)
      return () => canvas.removeEventListener('click', onClick)
    }, [onBusClick, onLineClick, onSwitchToggle, viewMode, orientation])

    // ── Cursor feedback ─────────────────────────────────────────────────
    useEffect(() => {
      const canvas = canvasRef.current
      if (!canvas) return
      let pending = false
      const onMove = (event: MouseEvent) => {
        if (pending) return
        pending = true
        requestAnimationFrame(() => {
          pending = false
          const rect = canvas.getBoundingClientRect()
          const [lx, ly] = transformRef.current.invert([event.clientX - rect.left, event.clientY - rect.top])
          const k = transformRef.current.k
          const { nodeById, links } = layoutRef.current
          const over =
            (!!onBusClick && !!findNode(quadtreeRef.current, lx, ly, 24 / k)) ||
            (!!onLineClick && !!findLink(links, nodeById, lx, ly, 7 / k, viewMode === 'tree' ? orientation : null))
          canvas.style.cursor = over ? 'pointer' : 'grab'
        })
      }
      canvas.addEventListener('mousemove', onMove)
      return () => canvas.removeEventListener('mousemove', onMove)
    }, [onBusClick, onLineClick, viewMode, orientation])

    // ── Size the backing store to the device pixel ratio ─────────────────
    useEffect(() => {
      const canvas = canvasRef.current
      if (!canvas) return
      const dpr = window.devicePixelRatio || 1
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      scheduleDraw()
    }, [width, height, scheduleDraw])

    // ── Redraw / refit ──────────────────────────────────────────────────
    useEffect(() => {
      paletteRef.current = null
      rebuildQuadtree()
      if (lastFitKeyRef.current !== fitKey) {
        lastFitKeyRef.current = fitKey
        fit()
      }
      scheduleDraw()
    }, [layout, result, detailed, viewMode, orientation, voltageLimits, fitKey, fit, scheduleDraw, rebuildQuadtree])

    // Clearing the ref matters as much as cancelling the frame: scheduleDraw
    // treats a non-null frameRef as "a draw is already queued" and bails.
    // StrictMode's mount/unmount/mount left a stale id behind, so the second
    // mount never scheduled anything and the canvas stayed blank.
    useEffect(
      () => () => {
        if (frameRef.current != null) {
          cancelAnimationFrame(frameRef.current)
          frameRef.current = null
        }
      },
      []
    )

    return <canvas ref={canvasRef} className="block touch-none" style={{ cursor: 'grab' }} />
  }
)

/** MEASUREMENT_KIND_INFO stores colors as `var(--color-…)` for the SVG/CSS
 *  side; map those back onto the resolved palette. */
function paletteColor(palette: Palette, cssVar: string): string {
  const match = /var\(--color-([a-z-]+)\)/.exec(cssVar)
  if (match) {
    const key = match[1] as PaletteKey
    if (palette[key]) return palette[key]
  }
  return cssVar
}

/** Nearest bus within `tolerance`, via the quadtree so a hover on a
 *  few-thousand-bus feeder doesn't scan the whole array on every frame. */
function findNode(
  tree: d3.Quadtree<LayoutNode> | null,
  x: number,
  y: number,
  tolerance: number
): LayoutNode | null {
  if (!tree) return null
  // MAX_NODE_RADIUS keeps a click just outside a big slack circle's centre
  // but still inside the circle from missing it.
  const found = tree.find(x, y, Math.max(tolerance, MAX_NODE_RADIUS))
  if (!found) return null
  const reach = Math.max(nodeRadius(found), tolerance)
  return (found.x - x) ** 2 + (found.y - y) ** 2 <= reach * reach ? found : null
}

const MAX_NODE_RADIUS = 22

function findLink(
  links: LayoutLink[],
  nodeById: Map<number, LayoutNode>,
  x: number,
  y: number,
  tolerance: number,
  elbowOrientation: TreeOrientation | null
): LayoutLink | null {
  const tolSq = Math.max(tolerance, 4) ** 2
  let best: LayoutLink | null = null
  let bestDist = Infinity
  for (const link of links) {
    const from = nodeById.get(link.from)
    const to = nodeById.get(link.to)
    if (!from || !to) continue
    // Cheap reject before the segment math — a bounding-box test skips the
    // overwhelming majority of branches on a large feeder.
    const pad = Math.sqrt(tolSq)
    if (x < Math.min(from.x, to.x) - pad || x > Math.max(from.x, to.x) + pad) continue
    if (y < Math.min(from.y, to.y) - pad || y > Math.max(from.y, to.y) + pad) continue
    let d: number
    if (elbowOrientation) {
      const pts = elbowPoints(from, to, elbowOrientation)
      d = Infinity
      for (let i = 1; i < pts.length; i++) {
        const seg = distToSegmentSq(x, y, pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1])
        if (seg < d) d = seg
      }
    } else {
      d = distToSegmentSq(x, y, from.x, from.y, to.x, to.y)
    }
    if (d <= tolSq && d < bestDist) {
      bestDist = d
      best = link
    }
  }
  return best
}

type VoltageColorFn = (voltage?: number) => string
type VisibleFn = (x: number, y: number) => boolean
type BusResultMap = Map<number, NonNullable<PowerFlowResult['buses']>[number]>

/** Spatial mode: buses as circles, coloured by voltage once a power flow has
 *  been solved. Mirrors drawNodes() in TopologyDiagram. */
function drawSpatialBuses(
  ctx: CanvasRenderingContext2D,
  nodes: LayoutNode[],
  c: Palette,
  detailed: boolean,
  result: PowerFlowResult | null | undefined,
  busResults: BusResultMap,
  voltageColor: VoltageColorFn,
  limits: { min: number; max: number },
  visible: VisibleFn,
  minStroke: number,
  minRadius: number
) {
  // Batched by fill colour: on a solved network almost every bus lands in
  // one of three voltage buckets, so this collapses thousands of fills into
  // three. The outline is a second pass for the same reason.
  const byFill = new Map<string, Path2D>()
  const outline = new Path2D()
  for (const node of nodes) {
    if (!visible(node.x, node.y)) continue
    const r = Math.max(nodeRadius(node), minRadius)
    const solved = busResults.get(node.id)?.voltage
    const fill =
      result && solved != null
        ? voltageColor(solved)
        : node.type === 'slack'
          ? c.primary
          : node.type === 'pv'
            ? c.accent
            : c.muted
    let path = byFill.get(fill)
    if (!path) {
      path = new Path2D()
      byFill.set(fill, path)
    }
    path.moveTo(node.x + r, node.y)
    path.arc(node.x, node.y, r, 0, Math.PI * 2)
    outline.moveTo(node.x + r, node.y)
    outline.arc(node.x, node.y, r, 0, Math.PI * 2)
  }
  for (const [fill, path] of byFill) {
    ctx.fillStyle = fill
    ctx.fill(path)
  }
  // The outline is what makes a PQ bus (near-white fill) readable against the
  // near-white background, so it is always drawn — just widened to survive
  // the zoom, like every other stroke.
  ctx.strokeStyle = c.foreground
  ctx.lineWidth = Math.max(2, minStroke)
  ctx.stroke(outline)

  if (!detailed) return

  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  for (const node of nodes) {
    if (!visible(node.x, node.y)) continue
    const solved = busResults.get(node.id)
    ctx.font = '600 10.5px Inter, sans-serif'
    ctx.fillStyle =
      result && solved && solved.voltage >= limits.min && solved.voltage <= limits.max
        ? c['primary-foreground']
        : node.type === 'pq'
          ? c.foreground
          : c['primary-foreground']
    ctx.fillText(String(node.id), node.x, node.y)

    if (result && solved) {
      ctx.font = '700 9px Inter, sans-serif'
      ctx.fillStyle = c.foreground
      ctx.fillText(`${solved.voltage.toFixed(3)} pu`, node.x, node.y - 28)
    }
    ctx.font = '10px Inter, sans-serif'
    ctx.fillStyle = c.foreground
    ctx.fillText(node.name, node.x, node.y + 32)

    if (node.pGen > 0) drawChip(ctx, node.x + 15, node.y - 15, 'G', c['status-good'], c['primary-foreground'], c.foreground, 6.5, false)
    if (node.pLoad > 0) drawChip(ctx, node.x - 15, node.y - 15, 'L', c.destructive, c['primary-foreground'], c.foreground, 5, true)
    if (node.pGenDG !== 0) drawChip(ctx, node.x - 15, node.y + 15, 'DG', c['method-ldf'], c['primary-foreground'], c.foreground, 7.5, false)
  }
}

/** Tree mode: IEEE-style single-line diagram — buses as tick marks, the
 *  slack as a labelled substation bar. Mirrors drawBusBars(). */
function drawTreeBuses(
  ctx: CanvasRenderingContext2D,
  nodes: LayoutNode[],
  c: Palette,
  detailed: boolean,
  result: PowerFlowResult | null | undefined,
  busResults: BusResultMap,
  voltageColor: VoltageColorFn,
  orientation: TreeOrientation,
  visible: VisibleFn,
  minStroke: number
) {
  const half = 9
  const byStroke = new Map<string, { path: Path2D; width: number }>()
  for (const node of nodes) {
    if (node.type === 'slack' || !visible(node.x, node.y)) continue
    const solved = busResults.get(node.id)?.voltage
    const color = result && solved != null ? voltageColor(solved) : node.type === 'pv' ? c.accent : c.foreground
    const lineWidth = Math.max(node.type === 'pv' ? 6 : 5, minStroke)
    const key = `${color}|${lineWidth}`
    let entry = byStroke.get(key)
    if (!entry) {
      entry = { path: new Path2D(), width: lineWidth }
      byStroke.set(key, entry)
    }
    if (orientation === 'vertical') {
      entry.path.moveTo(node.x - half, node.y)
      entry.path.lineTo(node.x + half, node.y)
    } else {
      entry.path.moveTo(node.x, node.y - half)
      entry.path.lineTo(node.x, node.y + half)
    }
  }
  ctx.lineCap = 'round'
  for (const [key, { path, width }] of byStroke) {
    ctx.strokeStyle = key.split('|')[0]
    ctx.lineWidth = width
    ctx.stroke(path)
  }

  // Loads: a short arrow pointing down, drawn regardless of orientation —
  // the convention in single-line feeder diagrams.
  const loadPath = new Path2D()
  let hasLoad = false
  for (const node of nodes) {
    if (node.pLoad <= 0 || node.type === 'slack' || !visible(node.x, node.y)) continue
    loadPath.moveTo(node.x, node.y + 9)
    loadPath.lineTo(node.x, node.y + 19)
    loadPath.moveTo(node.x - 3, node.y + 15)
    loadPath.lineTo(node.x, node.y + 19)
    loadPath.lineTo(node.x + 3, node.y + 15)
    hasLoad = true
  }
  if (hasLoad) {
    ctx.strokeStyle = c.destructive
    ctx.lineWidth = Math.max(2, minStroke)
    ctx.stroke(loadPath)
  }

  // Slack substation bar — always drawn, there is only ever one.
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  for (const node of nodes) {
    if (node.type !== 'slack') continue
    ctx.fillStyle = c.primary
    ctx.strokeStyle = c.foreground
    ctx.lineWidth = 2
    roundRect(ctx, node.x - 40, node.y - 16, 80, 32, 4)
    ctx.fill()
    ctx.stroke()
    ctx.fillStyle = c['primary-foreground']
    ctx.font = '700 12px Inter, sans-serif'
    ctx.fillText(node.name || `Bus ${node.id}`, node.x, node.y)
  }

  if (!detailed) return

  ctx.font = '700 12px Inter, sans-serif'
  ctx.fillStyle = c.foreground
  for (const node of nodes) {
    if (node.type === 'slack' || !visible(node.x, node.y)) continue
    ctx.fillText(String(node.id), node.x, node.y - 12)
    if (node.pGen > 0) drawChip(ctx, node.x + 14, node.y - 5, 'G', c['status-good'], c['primary-foreground'], c.foreground, 7, false)
    if (node.pGenDG !== 0) drawChip(ctx, node.x + 14, node.y + 12, 'DG', c['method-ldf'], c['primary-foreground'], c.foreground, 7, false)
    ctx.font = '700 12px Inter, sans-serif'
    ctx.fillStyle = c.foreground
  }
}

/** The small G / L / DG markers around a bus. */
function drawChip(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  label: string,
  fill: string,
  textColor: string,
  stroke: string,
  size: number,
  square: boolean
) {
  ctx.beginPath()
  if (square) ctx.rect(x - size, y - size, size * 2, size * 2)
  else ctx.arc(x, y, size, 0, Math.PI * 2)
  ctx.fillStyle = fill
  ctx.fill()
  ctx.strokeStyle = stroke
  ctx.lineWidth = 1
  ctx.stroke()
  ctx.fillStyle = textColor
  ctx.font = `600 ${label.length > 1 ? 6.5 : 8.5}px Inter, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(label, x, y)
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}
