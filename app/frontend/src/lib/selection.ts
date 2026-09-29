/** Elements picked by the user in the Topology tab. Shared by the attribute
 *  table, the diagram and (later) the map so a click in any of them lights up
 *  the same elements in the others. */
export interface TopologySelection {
  buses: ReadonlySet<number>
  lines: ReadonlySet<number>
}

export const EMPTY_SELECTION: TopologySelection = { buses: new Set(), lines: new Set() }

export function selectionSize(selection: TopologySelection): number {
  return selection.buses.size + selection.lines.size
}

/** Toggle one id in one of the two sets, returning a new selection. */
export function toggleInSelection(selection: TopologySelection, kind: 'bus' | 'line', id: number): TopologySelection {
  const key = kind === 'bus' ? 'buses' : 'lines'
  const next = new Set(selection[key])
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return { ...selection, [key]: next }
}

/** Replace the whole selection with a single element. */
export function selectOnly(kind: 'bus' | 'line', id: number): TopologySelection {
  return kind === 'bus'
    ? { buses: new Set([id]), lines: new Set() }
    : { buses: new Set(), lines: new Set([id]) }
}
