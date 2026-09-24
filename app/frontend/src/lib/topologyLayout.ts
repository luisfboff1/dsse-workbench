/**
 * Pure geometry for the network diagram — turns a Topology into node/link
 * coordinates, with no DOM and no d3 selection involved.
 *
 * Split out of TopologyDiagram so the SVG renderer and the canvas renderer
 * draw exactly the same picture: the layout is computed once here, and each
 * renderer only decides how to paint it. It also makes the expensive part
 * (the force simulation) something we can run *headless* — see
 * computeSpatialLayout.
 */
import * as d3 from 'd3'
import type { Bus, Line, MeasurementKind, Switch, Topology } from './types'
import { buildMeasurementIndex, type MeasurementIndex } from './measurements'
import { buildTopologyTree, type TopologyTreeNode } from './networkTopology'

export type TreeOrientation = 'vertical' | 'horizontal'

export interface LayoutNode {
  id: number
  name: string
  type: string
  pGen: number
  qGen: number
  pLoad: number
  qLoad: number
  pGenDG: number
  measurementKind?: MeasurementKind
  x: number
  y: number
  /** Pinned position (geo coords, or a bus the user dragged) — the force
   *  simulation treats these as fixed. */
  fx?: number | null
  fy?: number | null
  /** True for buses the BFS never reached from the slack (tree mode only) —
   *  drawn in their own row with a "disconnected" tooltip. */
  orphan?: boolean
}

export interface LayoutLink {
  id: number
  from: number
  to: number
  lineMeasurementKind?: MeasurementKind
}

/** A dashed, non-load-carrying connection: an open switch, or a loop-closing
 *  line the BFS spanning tree didn't use. */
export interface LayoutDashedLink {
  from: number
  to: number
  label: string
}

export interface TopologyLayout {
  nodes: LayoutNode[]
  nodeById: Map<number, LayoutNode>
  links: LayoutLink[]
  /** Open switches (spatial) plus loop lines (tree) — drawn dashed. */
  switchLinks: LayoutDashedLink[]
  extraLinks: LayoutDashedLink[]
  /** Switches that get a drawn glyph. Not every entry of getTopologySwitches:
   *  see pickGlyphSwitches. */
  glyphSwitches: Switch[]
  measurementIndex: MeasurementIndex
}

/** Above this many buses the renderers drop per-node text, badges and
 *  per-line glyphs, and the diagram defaults to the canvas renderer. Tuned
 *  so the standard IEEE test feeders (up to 123 buses) keep every bit of
 *  the detailed SVG rendering they have today. */
export const LARGE_NETWORK_BUSES = 500

function toLayoutNode(bus: Bus, kind: MeasurementKind | undefined, x: number, y: number): LayoutNode {
  return {
    id: bus.id,
    name: bus.name,
    type: bus.type,
    pGen: bus.pGen,
    qGen: bus.qGen,
    pLoad: bus.pLoad,
    qLoad: bus.qLoad,
    pGenDG: bus.pGenDG ?? 0,
    measurementKind: kind,
    x,
    y,
  }
}

/**
 * Which switches deserve a drawn glyph.
 *
 * getTopologySwitches() returns one entry per *line* (every closed branch is
 * reported as a closed switch) so the Switches panel can toggle any branch.
 * Drawing all of them costs ~7 shapes per line, which on a few-thousand-line
 * feeder is tens of thousands of elements that carry almost no information —
 * a closed switch on every single branch. Above the size threshold we keep
 * only the ones that actually say something.
 */
export function pickGlyphSwitches(all: Switch[], detailed: boolean): Switch[] {
  if (detailed) return all
  // Only the open ones. A closed switch adds nothing a large diagram doesn't
  // already show — the branch itself is drawn — while an open one is the
  // whole point (it's what makes the feeder configuration what it is). The
  // Switches side panel still lists every branch, so nothing becomes
  // untoggleable; it just stops being painted.
  return all.filter((sw) => !sw.closed)
}

/**
 * Spatial layout: geo coordinates when the case carries them, otherwise a
 * force-directed layout.
 *
 * The simulation runs to completion *synchronously* here rather than being
 * animated tick by tick. Animating it meant re-writing the position of every
 * node, link, hit area and badge ~300 times, once per frame — on a large
 * feeder that is the single biggest source of the freeze, and the settling
 * animation was never load-bearing information. Ticking headless does the
 * same math with no layout or paint in between, then the renderer draws the
 * settled result once.
 */
export function computeSpatialLayout(
  topology: Topology,
  width: number,
  height: number,
  previousPositions?: Map<number, { x: number; y: number }>,
  useForce = false
): TopologyLayout {
  const measurementIndex = buildMeasurementIndex(topology)
  const geoBuses = topology.buses.filter(
    (b) =>
      b.geoX !== undefined &&
      b.geoY !== undefined &&
      (Math.abs(b.geoX) > 1e-4 || Math.abs(b.geoY) > 1e-4)
  )
  const hasGeoCoords = geoBuses.length > 0

  let minGeoX = Number.POSITIVE_INFINITY
  let maxGeoX = Number.NEGATIVE_INFINITY
  let minGeoY = Number.POSITIVE_INFINITY
  let maxGeoY = Number.NEGATIVE_INFINITY
  for (const b of geoBuses) {
    if (b.geoX! < minGeoX) minGeoX = b.geoX!
    if (b.geoX! > maxGeoX) maxGeoX = b.geoX!
    if (b.geoY! < minGeoY) minGeoY = b.geoY!
    if (b.geoY! > maxGeoY) maxGeoY = b.geoY!
  }
  const padding = 50
  const rawSpanX = maxGeoX - minGeoX
  const rawSpanY = maxGeoY - minGeoY
  const spanX = rawSpanX > 1e-7 ? rawSpanX : 1
  const spanY = rawSpanY > 1e-7 ? rawSpanY : 1

  // Mercator aspect ratio correction: 1 deg lon is cos(lat) * 1 deg lat
  const midLatRad = ((minGeoY + maxGeoY) / 2) * (Math.PI / 180)
  const aspectCorrection =
    Math.abs(minGeoY) < 90 && Math.abs(maxGeoY) < 90 && Math.abs(Math.cos(midLatRad)) > 0.1
      ? Math.cos(midLatRad)
      : 1.0

  const physicalSpanX = spanX * aspectCorrection
  const physicalSpanY = spanY

  const availW = Math.max(100, width - 2 * padding)
  const availH = Math.max(100, height - 2 * padding)
  const scale = Math.min(availW / physicalSpanX, availH / physicalSpanY)
  const offsetX = padding + (availW - physicalSpanX * scale) / 2
  const offsetY = padding + (availH - physicalSpanY * scale) / 2

  // Computed up front so both the force path (as its starting positions) and
  // the default path (as the layout itself) can use it.
  const radial = hasGeoCoords ? null : computeRadialLayout(topology, width, height)

  const nodes: LayoutNode[] = topology.buses.map((bus) => {
    const kind = measurementIndex.busKind.get(bus.id)
    if (hasGeoCoords && bus.geoX !== undefined && bus.geoY !== undefined) {
      const x = offsetX + (bus.geoX - minGeoX) * aspectCorrection * scale
      // North-up: higher latitude (geoY) goes towards the top of the canvas (smaller Y)
      const y = offsetY + (maxGeoY - bus.geoY) * scale
      const node = toLayoutNode(bus, kind, x, y)
      node.fx = x
      node.fy = y
      return node
    }
    // Resume from where this bus last settled instead of starting over —
    // otherwise a meter toggle or any other redraw makes every node jump.
    const prev = previousPositions?.get(bus.id) ?? radial?.get(bus.id)
    return toLayoutNode(bus, kind, prev?.x ?? Number.NaN, prev?.y ?? Number.NaN)
  })
  // d3 seeds x/y itself when they are NaN/undefined; hand it undefined so it
  // uses its phyllotaxis start rather than reading NaN as a real coordinate.
  for (const n of nodes) {
    if (Number.isNaN(n.x)) {
      delete (n as Partial<LayoutNode>).x
      delete (n as Partial<LayoutNode>).y
    }
  }

  const nodeById = new Map(nodes.map((n) => [n.id, n]))
  const links: LayoutLink[] = topology.lines.map((line) => ({
    id: line.id,
    from: line.from,
    to: line.to,
    lineMeasurementKind: measurementIndex.lineKind.get(line.id),
  }))

  if (!hasGeoCoords && useForce) {
    runForceSimulation(nodes, links, width, height)
  }
  for (const n of nodes) {
    n.x = n.x ?? 0
    n.y = n.y ?? 0
  }

  return {
    nodes,
    nodeById,
    links,
    switchLinks: [],
    extraLinks: [],
    glyphSwitches: [],
    measurementIndex,
  }
}

/**
 * Radial tree layout: BFS depth from the slack becomes the radius, and each
 * subtree gets an angular wedge sized by how many leaves it holds.
 *
 * This is the default for the spatial view. It is O(n), deterministic (the
 * same case always draws the same, so two runs are comparable), instant, and
 * it encodes something real — hops from the substation, with each feeder
 * fanning out into its own sector.
 *
 * The wedge is what makes it work on a radial feeder. Spreading each BFS layer
 * evenly around a full circle collapses a feeder into a straight line, since
 * its layers hold one or two buses each and 2*pi*i/k is then always 0 or pi.
 * Sizing by leaf count instead gives every branch room proportional to what
 * hangs off it.
 *
 * It replaced a force simulation that cost seconds of blocked main thread on a
 * few-thousand-bus network and settled into a hairball at the zoom where one
 * fits on screen. The simulation is still available behind the Force toggle.
 */
export function computeRadialLayout(
  topology: Topology,
  width: number,
  height: number
): Map<number, { x: number; y: number }> {
  const positions = new Map<number, { x: number; y: number }>()
  const root = topology.buses.find((b) => b.type === 'slack') ?? topology.buses[0]
  if (!root) return positions

  const adjacency = new Map<number, number[]>()
  for (const line of topology.lines) {
    if (!adjacency.has(line.from)) adjacency.set(line.from, [])
    if (!adjacency.has(line.to)) adjacency.set(line.to, [])
    adjacency.get(line.from)!.push(line.to)
    adjacency.get(line.to)!.push(line.from)
  }

  // BFS spanning tree. Buses no walk reaches (separate feeders behind their
  // own transformers, open switches) are collected for a final outer ring
  // rather than dropped.
  const children = new Map<number, number[]>()
  const depth = new Map<number, number>([[root.id, 0]])
  const seen = new Set<number>([root.id])
  const queue = [root.id]
  let maxDepth = 0
  for (let head = 0; head < queue.length; head++) {
    const id = queue[head]
    for (const neighbor of adjacency.get(id) ?? []) {
      if (seen.has(neighbor)) continue
      seen.add(neighbor)
      const d = (depth.get(id) ?? 0) + 1
      depth.set(neighbor, d)
      if (d > maxDepth) maxDepth = d
      if (!children.has(id)) children.set(id, [])
      children.get(id)!.push(neighbor)
      queue.push(neighbor)
    }
  }

  // Leaf counts, computed bottom-up over the BFS order so no recursion is
  // needed (a deep feeder would otherwise risk the call stack).
  const leaves = new Map<number, number>()
  for (let i = queue.length - 1; i >= 0; i--) {
    const id = queue[i]
    const kids = children.get(id)
    if (!kids || kids.length === 0) {
      leaves.set(id, 1)
      continue
    }
    let total = 0
    for (const kid of kids) total += leaves.get(kid) ?? 1
    leaves.set(id, total)
  }

  // Scale the rings so that at the outermost depth adjacent leaves sit about
  // minArc apart, with a floor so small networks don't come out cramped.
  const totalLeaves = leaves.get(root.id) ?? 1
  const minArc = 26
  const ringGap = Math.max(90, (totalLeaves * minArc) / (2 * Math.PI * Math.max(maxDepth, 1)))
  const cx = width / 2
  const cy = height / 2
  positions.set(root.id, { x: cx, y: cy })

  // Walk down assigning each node the centre of its wedge.
  const wedge = new Map<number, [number, number]>([[root.id, [0, 2 * Math.PI]]])
  for (const id of queue) {
    const kids = children.get(id)
    if (!kids || kids.length === 0) continue
    const [from, to] = wedge.get(id) ?? [0, 2 * Math.PI]
    const span = to - from
    const own = leaves.get(id) ?? 1
    let cursor = from
    for (const kid of kids) {
      const share = ((leaves.get(kid) ?? 1) / own) * span
      wedge.set(kid, [cursor, cursor + share])
      const angle = cursor + share / 2
      const radius = (depth.get(kid) ?? 1) * ringGap
      positions.set(kid, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) })
      cursor += share
    }
  }

  // Unreachable buses: one ring outside everything else.
  const unreached = topology.buses.filter((b) => !seen.has(b.id))
  if (unreached.length) {
    const radius = Math.max((maxDepth + 2) * ringGap, (unreached.length * minArc) / (2 * Math.PI))
    for (const [i, bus] of unreached.entries()) {
      const angle = (2 * Math.PI * i) / unreached.length
      positions.set(bus.id, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) })
    }
  }

  return positions
}

/** Force layout, ticked to convergence without rendering in between.
 *  Exported so a node drag can re-settle the layout on demand. */
export function runForceSimulation(
  nodes: LayoutNode[],
  links: LayoutLink[],
  width: number,
  height: number,
  ticks?: number
): void {
  // Big graphs get a cheaper force model. Measured on case6495rte (6495 nodes,
  // 9019 links) the full model cost ~14.5 s of blocked main thread per run,
  // which is the freeze, not a slow frame. Three things buy that back:
  //
  //  - `distanceMax` lets the Barnes-Hut charge force prune whole branches of
  //    the quadtree. Without it every node is evaluated against the entire
  //    tree even though a repulsion of -550 is negligible half a screen away.
  //  - a coarser `theta` approximates more aggressively, which at this node
  //    count is invisible.
  //  - `forceCollide` is dropped. It is the most expensive force here (every
  //    node starts clustered, so nearly everything overlaps on the early
  //    ticks) and it only buys tidy spacing, which is meaningless at the zoom
  //    where a 6000-bus network fits on screen.
  const big = nodes.length > 1500
  const simLinks = links.map((l) => ({ ...l, source: l.from, target: l.to }))
  const simulation = d3
    .forceSimulation(nodes as d3.SimulationNodeDatum[])
    .force(
      'link',
      d3
        .forceLink(simLinks as unknown as d3.SimulationLinkDatum<d3.SimulationNodeDatum>[])
        .id((d) => (d as unknown as LayoutNode).id)
        .distance(110)
    )
    .force(
      'charge',
      big
        ? d3.forceManyBody().strength(-550).distanceMax(600).theta(1.5)
        : d3.forceManyBody().strength(-550)
    )
    .force('center', d3.forceCenter(width / 2, height / 2))
    .stop()
  if (!big) simulation.force('collision', d3.forceCollide().radius(38))

  // d3's own default: how many ticks it would have run before alpha decays
  // below alphaMin. Capped on large graphs — each tick is O(n log n) with
  // the Barnes-Hut charge force, and a layout this size is visually settled
  // long before alphaMin.
  const defaultTicks = Math.ceil(Math.log(simulation.alphaMin()) / Math.log(1 - simulation.alphaDecay()))
  const budget = ticks ?? (nodes.length > 3000 ? 60 : big ? 120 : nodes.length > 600 ? 200 : defaultTicks)
  simulation.tick(budget)
  simulation.stop()
}

/**
 * Tree layout: BFS spanning tree from the slack, laid out with d3.tree() —
 * the classic single-line feeder diagram. Deterministic and O(n), so it
 * stays cheap regardless of network size.
 */
export function computeTreeLayout(
  topology: Topology,
  orientation: TreeOrientation,
  treeNodeSize: [number, number],
  treePadding: number
): TopologyLayout & { extraLines: Line[]; unreachable: Bus[] } {
  const measurementIndex = buildMeasurementIndex(topology)
  const treeData = buildTopologyTree(topology)
  const empty = {
    nodes: [] as LayoutNode[],
    nodeById: new Map<number, LayoutNode>(),
    links: [] as LayoutLink[],
    switchLinks: [] as LayoutDashedLink[],
    extraLinks: [] as LayoutDashedLink[],
    glyphSwitches: [] as Switch[],
    measurementIndex,
    extraLines: treeData.extraLines,
    unreachable: treeData.unreachable,
  }
  if (!treeData.root) return empty

  const hierarchyRoot = d3.hierarchy<TopologyTreeNode>(treeData.root, (d) => d.children)
  d3.tree<TopologyTreeNode>().nodeSize(treeNodeSize)(hierarchyRoot)
  const points = hierarchyRoot.descendants() as d3.HierarchyPointNode<TopologyTreeNode>[]

  let minSibling = Infinity
  let maxDepth = -Infinity
  for (const p of points) {
    if (p.x < minSibling) minSibling = p.x
    if (p.y > maxDepth) maxDepth = p.y
  }

  const nodes: LayoutNode[] = points.map((p) => {
    const bus = p.data.bus
    const sib = p.x - minSibling + treePadding
    const depth = p.y + treePadding
    const [x, y] = orientation === 'vertical' ? [sib, depth] : [depth, sib]
    return toLayoutNode(bus, measurementIndex.busKind.get(bus.id), x, y)
  })

  // Buses the BFS never reached (disconnected islands) — laid out past the
  // deepest tree level, unconnected, so they stay visible instead of silently
  // vanishing from the diagram.
  //
  // In a grid, not a single row. A real LV case can be mostly unreachable from
  // one slack (lv_schutterwald: 2824 of 2940, since it is many separate feeders
  // behind their own transformers), and one row of those is ~130,000px wide —
  // the fit then squashes the whole diagram, tree included, into a vertical
  // smear a few pixels across. A roughly square block keeps the bounding box
  // proportional and the actual tree readable.
  const orphanCols = Math.max(1, Math.ceil(Math.sqrt(treeData.unreachable.length)))
  for (const [i, bus] of treeData.unreachable.entries()) {
    const sib = (i % orphanCols) * treeNodeSize[0] + treePadding
    const depth =
      maxDepth + treeNodeSize[1] + treePadding + Math.floor(i / orphanCols) * treeNodeSize[1]
    const [x, y] = orientation === 'vertical' ? [sib, depth] : [depth, sib]
    const node = toLayoutNode(bus, measurementIndex.busKind.get(bus.id), x, y)
    node.orphan = true
    nodes.push(node)
  }

  const nodeById = new Map(nodes.map((n) => [n.id, n]))

  // target.data.parentLine is the real topology.lines entry behind this tree
  // edge (see buildTopologyTree) — falls back to a synthetic negative id only
  // if somehow missing (shouldn't happen: every non-root tree node gets one).
  const links: LayoutLink[] = hierarchyRoot.links().map((l, i) => {
    const parentLine = (l.target as d3.HierarchyPointNode<TopologyTreeNode>).data.parentLine
    return {
      id: parentLine?.id ?? -(i + 1),
      from: l.source.data.bus.id,
      to: l.target.data.bus.id,
      lineMeasurementKind: parentLine ? measurementIndex.lineKind.get(parentLine.id) : undefined,
    }
  })

  const extraLinks: LayoutDashedLink[] = treeData.extraLines
    .filter((line) => nodeById.has(line.from) && nodeById.has(line.to))
    .map((line) => ({ from: line.from, to: line.to, label: `loop: L${line.id}` }))

  return {
    nodes,
    nodeById,
    links,
    switchLinks: [],
    extraLinks,
    glyphSwitches: [],
    measurementIndex,
    extraLines: treeData.extraLines,
    unreachable: treeData.unreachable,
  }
}

/** Right-angle elbow route between two tree nodes, as points — the
 *  conventional single-line feeder edge. The canvas renderer strokes these
 *  directly; the SVG renderer builds the equivalent path string itself. */
export function elbowPoints(
  source: LayoutNode,
  target: LayoutNode,
  orientation: TreeOrientation
): [number, number][] {
  const { x: sx, y: sy } = source
  const { x: tx, y: ty } = target
  if (orientation === 'vertical') {
    const midY = (sy + ty) / 2
    return [[sx, sy], [sx, midY], [tx, midY], [tx, ty]]
  }
  const midX = (sx + tx) / 2
  return [[sx, sy], [midX, sy], [midX, ty], [tx, ty]]
}

/** Bounding box of a set of nodes, with padding for the glyphs drawn around
 *  each one — used to fit the view without reading the DOM's getBBox(). */
export function layoutBounds(nodes: LayoutNode[], pad = 40) {
  if (!nodes.length) return { x: 0, y: 0, width: 0, height: 0 }
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const n of nodes) {
    if (n.x < minX) minX = n.x
    if (n.x > maxX) maxX = n.x
    if (n.y < minY) minY = n.y
    if (n.y > maxY) maxY = n.y
  }
  return { x: minX - pad, y: minY - pad, width: maxX - minX + 2 * pad, height: maxY - minY + 2 * pad }
}
