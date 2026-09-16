/**
 * Radial-vs-meshed detection — single source of truth shared by TopologyTab
 * (shown at load time) and PowerFlowTab (drives the LinDistFlow warning).
 * Mirrors the backend's edge-count check in
 * src/tese_dsse/powerflow/lindistflow.py::_build_tree.
 */
import type { Bus, Line, Switch, Topology } from './types'

export type RadialStatus = 'radial' | 'meshed' | 'disconnected'

export interface RadialCheck {
  status: RadialStatus
  nBuses: number
  nLines: number
  /** lines needed for a radial (loop-free) tree: nBuses - 1 */
  nExpectedRadial: number
}

export function checkRadial(topology: Topology): RadialCheck {
  const nBuses = topology.buses.length
  const nLines = topology.lines.length
  const nExpectedRadial = Math.max(0, nBuses - 1)
  const status: RadialStatus =
    nLines === nExpectedRadial ? 'radial' : nLines > nExpectedRadial ? 'meshed' : 'disconnected'
  return { status, nBuses, nLines, nExpectedRadial }
}

export interface TopologyTreeNode {
  bus: Bus
  children: TopologyTreeNode[]
  /** The real Line connecting this node to its parent (undefined for the
   *  root/slack, which has no parent edge) — lets consumers (e.g. line-meter
   *  click handling in TopologyDiagram) resolve the actual topology.lines
   *  id behind a tree edge, instead of only having (from, to) bus ids. */
  parentLine?: Line
}

export interface TopologyTree {
  root: TopologyTreeNode | null
  /** Lines whose endpoints are both reachable but that the BFS spanning tree
   *  didn't use — loops / parallel paths in a meshed network. Drawn as extra
   *  cross-links in the hierarchical diagram, not fed into the layout. */
  extraLines: Line[]
  /** Buses the BFS never reached from the slack — disconnected islands. */
  unreachable: Bus[]
}

/**
 * BFS spanning tree from the slack bus, for the hierarchical (top-down /
 * left-right) diagram. Same edge-counting idea as checkRadial, but walks the
 * graph instead of just counting: tolerant of meshed/disconnected input
 * (returns the leftover structure instead of throwing) because this is a
 * drawing aid, not the power-flow radiality gate — DistFlow's real go/no-go
 * check is _build_tree in lindistflow.py.
 */
export function buildTopologyTree(topology: Topology): TopologyTree {
  const busById = new Map(topology.buses.map((b) => [b.id, b]))
  const slack = topology.buses.find((b) => b.type === 'slack') ?? topology.buses[0]
  if (!slack) return { root: null, extraLines: [], unreachable: [] }

  const adjacency = new Map<number, { neighbor: number; line: Line }[]>()
  for (const line of topology.lines) {
    if (!adjacency.has(line.from)) adjacency.set(line.from, [])
    if (!adjacency.has(line.to)) adjacency.set(line.to, [])
    adjacency.get(line.from)!.push({ neighbor: line.to, line })
    adjacency.get(line.to)!.push({ neighbor: line.from, line })
  }

  const visited = new Set<number>([slack.id])
  const usedLineIds = new Set<number>()
  const nodeById = new Map<number, TopologyTreeNode>()
  const root: TopologyTreeNode = { bus: slack, children: [] }
  nodeById.set(slack.id, root)

  const queue: number[] = [slack.id]
  while (queue.length) {
    const current = queue.shift()!
    const currentNode = nodeById.get(current)!
    for (const { neighbor, line } of adjacency.get(current) ?? []) {
      if (visited.has(neighbor)) continue
      const bus = busById.get(neighbor)
      if (!bus) continue
      visited.add(neighbor)
      usedLineIds.add(line.id)
      const childNode: TopologyTreeNode = { bus, children: [], parentLine: line }
      nodeById.set(neighbor, childNode)
      currentNode.children.push(childNode)
      queue.push(neighbor)
    }
  }

  const extraLines = topology.lines.filter(
    (line) => !usedLineIds.has(line.id) && visited.has(line.from) && visited.has(line.to)
  )
  const unreachable = topology.buses.filter((b) => !visited.has(b.id))

  return { root, extraLines, unreachable }
}

/**
 * Returns the comprehensive list of switches for a topology.
 * Merges any explicit switches/openSwitches with all active lines in topology.lines,
 * ensuring every branch in the network is represented with its switch state.
 */
export function getTopologySwitches(topology: Topology): Switch[] {
  const result: Switch[] = []
  const coveredPairs = new Set<string>()
  let maxId = 0

  // 1. Explicit switches from topology.switches or topology.openSwitches
  const explicit: Switch[] =
    topology.switches && topology.switches.length > 0
      ? topology.switches
      : (topology.openSwitches ?? []).map((s, idx) => ({
          id: s.id ?? idx + 1,
          from: s.from,
          to: s.to,
          name: s.name ?? `SW ${s.id ?? idx + 1}`,
          closed: false,
          r_pu: s.r_pu,
          x_pu: s.x_pu,
          b_pu: s.b_pu,
        }))

  for (const sw of explicit) {
    result.push(sw)
    maxId = Math.max(maxId, sw.id)
    coveredPairs.add(`${Math.min(sw.from, sw.to)}-${Math.max(sw.from, sw.to)}`)
  }

  // 2. For every active line in topology.lines not yet represented by a switch:
  // Add it as an active (closed: true) switch!
  for (const line of topology.lines) {
    const pairKey = `${Math.min(line.from, line.to)}-${Math.max(line.from, line.to)}`
    if (coveredPairs.has(pairKey)) continue
    coveredPairs.add(pairKey)
    maxId++
    result.push({
      id: maxId,
      from: line.from,
      to: line.to,
      name: `L${line.id} (${line.from}↔${line.to})`,
      closed: true,
      r_pu: line.resistance,
      x_pu: line.reactance,
      b_pu: line.susceptance,
    })
  }

  return result
}
