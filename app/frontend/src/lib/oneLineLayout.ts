import type { Topology } from './types'

/** Minimal shape of an ELK instance — injected, so the layout stays testable
 *  outside the browser (the app passes a Web-Worker-backed one). */
export interface ElkLike {
  layout: (graph: any) => Promise<any>
}

export interface OneLineNode {
  id: number
  x: number
  y: number
  w: number
  h: number
}

export interface OneLineEdge {
  key: string
  /** Line id when this is a real branch; undefined for an open-switch tie. */
  lineId?: number
  from: number
  to: number
  /** Orthogonal route, already in the same coordinates as the nodes. */
  points: [number, number][]
  /** Normally-open tie (drawn dashed, with an open-switch glyph). */
  open: boolean
}

export interface OneLineLayout {
  nodes: OneLineNode[]
  edges: OneLineEdge[]
  /** Extent of everything drawn — what "fit to view" frames. */
  bounds: { x: number; y: number; width: number; height: number }
}

export const BAR_HEIGHT = 8

/** A bus bar is as long as it needs to be to land its connections: the more
 *  branches, the wider — the way a real single-line diagram draws it. */
export function barWidth(degree: number): number {
  return Math.min(260, Math.max(64, 40 + 18 * degree))
}

export interface OpenTie {
  from: number
  to: number
}

/**
 * Layered, orthogonally-routed single-line layout (ELK).
 *
 * Unlike the BFS tree, this handles meshed networks: every branch is routed,
 * loops included, with right-angle segments and as few crossings as the
 * algorithm can manage. The slack bus is pinned to the top layer so the
 * diagram reads from the source downward.
 */
export async function computeOneLineLayout(
  elk: ElkLike,
  topology: Topology,
  openTies: readonly OpenTie[] = []
): Promise<OneLineLayout> {
  const busIds = new Set(topology.buses.map((b) => b.id))
  const degree = new Map<number, number>()
  const bump = (id: number) => degree.set(id, (degree.get(id) ?? 0) + 1)
  const branches = topology.lines.filter((l) => busIds.has(l.from) && busIds.has(l.to) && l.from !== l.to)
  const ties = openTies.filter((t) => busIds.has(t.from) && busIds.has(t.to) && t.from !== t.to)
  for (const l of branches) {
    bump(l.from)
    bump(l.to)
  }
  for (const t of ties) {
    bump(t.from)
    bump(t.to)
  }

  const slack = topology.buses.find((b) => b.type === 'slack')
  const children = topology.buses.map((b) => ({
    id: `b${b.id}`,
    width: barWidth(degree.get(b.id) ?? 0),
    height: BAR_HEIGHT,
    layoutOptions:
      slack && b.id === slack.id ? { 'org.eclipse.elk.layered.layering.layerConstraint': 'FIRST' } : undefined,
  }))
  const edgeMeta = new Map<string, { lineId?: number; from: number; to: number; open: boolean }>()
  const edges = [
    ...branches.map((l) => {
      const key = `l${l.id}`
      edgeMeta.set(key, { lineId: l.id, from: l.from, to: l.to, open: false })
      return { id: key, sources: [`b${l.from}`], targets: [`b${l.to}`] }
    }),
    ...ties.map((t, i) => {
      const key = `t${i}`
      edgeMeta.set(key, { from: t.from, to: t.to, open: true })
      return { id: key, sources: [`b${t.from}`], targets: [`b${t.to}`] }
    }),
  ]

  const graph = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'DOWN',
      'elk.edgeRouting': 'ORTHOGONAL',
      'elk.layered.spacing.nodeNodeBetweenLayers': '90',
      'elk.spacing.nodeNode': '56',
      'elk.spacing.edgeEdge': '14',
      'elk.spacing.edgeNode': '24',
      'elk.layered.spacing.edgeEdgeBetweenLayers': '14',
      'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
      'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
      'elk.separateConnectedComponents': 'true',
    },
    children,
    edges,
  }

  const out = await elk.layout(graph)

  const nodes: OneLineNode[] = (out.children ?? []).map((c: any) => ({
    id: Number(String(c.id).slice(1)),
    x: c.x ?? 0,
    y: c.y ?? 0,
    w: c.width ?? 0,
    h: c.height ?? 0,
  }))
  const routed: OneLineEdge[] = []
  for (const e of out.edges ?? []) {
    const meta = edgeMeta.get(e.id)
    const section = e.sections?.[0]
    if (!meta || !section) continue
    const pts: [number, number][] = [
      [section.startPoint.x, section.startPoint.y],
      ...(section.bendPoints ?? []).map((p: any): [number, number] => [p.x, p.y]),
      [section.endPoint.x, section.endPoint.y],
    ]
    routed.push({ key: e.id, lineId: meta.lineId, from: meta.from, to: meta.to, points: pts, open: meta.open })
  }
  // ELK's reported size doesn't always cover the routed edges, so fit to the
  // real extent of everything that gets drawn.
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const n of nodes) {
    minX = Math.min(minX, n.x)
    minY = Math.min(minY, n.y - 16)
    maxX = Math.max(maxX, n.x + n.w)
    maxY = Math.max(maxY, n.y + n.h + 34)
  }
  for (const e of routed) {
    for (const [x, y] of e.points) {
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
    }
  }
  if (!Number.isFinite(minX)) minX = minY = maxX = maxY = 0
  return { nodes, edges: routed, bounds: { x: minX, y: minY, width: maxX - minX, height: maxY - minY } }
}
