import type { ReactNode } from 'react'
import { TableBody } from '@/components/ui/table'
import { useTableScrollElement } from '@/components/TableCard'
import { useVirtualRowsOn } from '@/hooks/useVirtualRows'

/** Default row height for the read-only result tables (text cells, `text-xs`,
 *  the shared TableCell padding). Editable tables whose cells hold inputs are
 *  taller and pass their own. */
export const RESULT_ROW_HEIGHT = 33

interface VirtualTableBodyProps<T> {
  items: T[]
  /** Must match the rendered row height, since the window is computed from
   *  scrollTop alone. Set the same value as `style={{ height }}` on the row. */
  rowHeight?: number
  /** A normal prop rather than children-as-function: TypeScript infers T from
   *  `items` reliably this way, whereas a generic render child came out as
   *  `unknown` at every call site. */
  renderRow: (item: T, index: number) => ReactNode
}

/**
 * `<TableBody>` that mounts only the rows currently scrolled into view.
 *
 * Drop-in for a `<TableBody>{items.map(...)}</TableBody>` inside a
 * `<TableCard maxHeight=...>`: it finds the card's scroll container through
 * context, and stands in for the off-screen rows with two spacer `<tr>`s so
 * the scrollbar still reflects the whole list.
 *
 * Two things the caller still has to do:
 *  - give each rendered row a fixed height matching `rowHeight`;
 *  - pass `exportData` to the TableCard. Its Copy reads the rendered cells
 *    back out of the DOM, which is normally the point (the export matches
 *    what's on screen) — but with windowed rows the DOM only holds a slice.
 */
export function VirtualTableBody<T>({ items, rowHeight = RESULT_ROW_HEIGHT, renderRow }: VirtualTableBodyProps<T>) {
  const scrollEl = useTableScrollElement()
  const rows = useVirtualRowsOn(scrollEl, items.length, rowHeight)
  return (
    <TableBody>
      {rows.offsetY > 0 && <tr aria-hidden style={{ height: rows.offsetY }} />}
      {items.slice(rows.start, rows.end).map((item, i) => renderRow(item, rows.start + i))}
      {rows.tailHeight > 0 && <tr aria-hidden style={{ height: rows.tailHeight }} />}
    </TableBody>
  )
}
