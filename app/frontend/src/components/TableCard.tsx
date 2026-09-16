import { createContext, useContext, useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Table } from '@/components/ui/table'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Copy, ArrowsOut, ArrowsIn } from '@phosphor-icons/react'
import { toCSV, toMarkdownTable, toJSON, type TableData } from '@/lib/exportData'

interface TableCardProps {
  /** <TableHeader>...</TableHeader> and <TableBody>...</TableBody>, exactly
   *  as any other <Table> usage — TableCard doesn't need to know the data
   *  shape. It reads the rendered cells back out at copy time, so the export
   *  always matches what's actually on screen (formatting, units, dashes for
   *  N/A included) without every table having to hand-build a headers/rows
   *  pair just for copying. */
  children: ReactNode
  /** Shown in the copy toast, e.g. "Bus Data" — distinguishes tables when
   *  several are on screen. */
  label: string
  /** Row-count cap as a CSS max-height (e.g. "16rem") — pass this for tables
   *  that can grow tall (result/measurement tables); omit it for small or
   *  wide-only tables (e.g. topology config) where only horizontal scroll
   *  ever matters — omitting also hides the Expand/Collapse button. */
  maxHeight?: string
  className?: string
  /** Handed the scrollable wrapper, so a caller that windows its own rows can
   *  hang a virtualizer off the element that actually scrolls. */
  scrollRef?: (node: HTMLElement | null) => void
  /** Height cap while expanded. Expand normally releases the cap entirely and
   *  lets the page scroll — fine for a few dozen rows, but a windowed table
   *  needs its own scroller to stay windowed (and a thousand-row table has no
   *  business being 45,000px tall either way). */
  expandedMaxHeight?: string
  /** Full table contents, for callers whose <TableBody> only renders the rows
   *  currently in view. Copy reads the DOM by default — which is exactly what
   *  keeps the export matching what's on screen — but with windowed rows the
   *  DOM holds a slice, so those callers must supply the whole thing here. */
  exportData?: () => TableData
}

/** The scroll container TableCard owns, published so a <VirtualTableBody>
 *  inside it can window against the element that actually scrolls without the
 *  caller having to thread a ref through. */
const TableScrollContext = createContext<HTMLElement | null>(null)

export function useTableScrollElement(): HTMLElement | null {
  return useContext(TableScrollContext)
}

function cellText(cell: Element): string {
  const input = cell.querySelector('input')
  if (input) return (input as HTMLInputElement).value || input.getAttribute('placeholder') || ''
  return cell.textContent?.trim() ?? ''
}

/** Reusable table shell — a scrollable/expandable container plus Copy
 *  (Markdown/CSV/JSON) built on top of the shared <Table> primitive. Wire
 *  this in once per table instead of a bespoke Expand button and a
 *  hand-built headers/rows array; a new table gets both for free just by
 *  using TableCard, and a design change to either only has to happen here. */
export function TableCard({ children, label, maxHeight, className, scrollRef, exportData, expandedMaxHeight }: TableCardProps) {
  const tableRef = useRef<HTMLTableElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [scrollEl, setScrollEl] = useState<HTMLElement | null>(null)

  function readTableData(): TableData {
    if (exportData) return exportData()
    const table = tableRef.current
    if (!table) return { headers: [], rows: [] }
    const headers = Array.from(table.querySelectorAll('thead th')).map(cellText)
    const rows = Array.from(table.querySelectorAll('tbody > tr')).map((tr) =>
      Array.from(tr.querySelectorAll('td')).map(cellText)
    )
    return { headers, rows }
  }

  const copy = async (format: 'markdown' | 'csv' | 'json') => {
    const data = readTableData()
    if (data.rows.length === 0) {
      toast.error(`Nothing to copy — ${label} is empty`)
      return
    }
    const text = format === 'markdown' ? toMarkdownTable(data) : format === 'csv' ? toCSV(data) : toJSON(data)
    try {
      await navigator.clipboard.writeText(text)
      toast.success(`Copied ${label} (${data.rows.length} row${data.rows.length === 1 ? '' : 's'}, ${format.toUpperCase()})`)
    } catch {
      toast.error('Copy failed — clipboard permission blocked?')
    }
  }

  return (
    <div>
      <div className="mb-1.5 flex justify-end gap-1.5">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button type="button" size="sm" variant="ghost" className="h-6 gap-1 text-xs text-muted-foreground" title={`Copy ${label}`}>
              <Copy className="w-3.5 h-3.5" /> Copy
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40">
            <DropdownMenuItem onClick={() => copy('markdown')}>Copy as Markdown</DropdownMenuItem>
            <DropdownMenuItem onClick={() => copy('csv')}>Copy as CSV</DropdownMenuItem>
            <DropdownMenuItem onClick={() => copy('json')}>Copy as JSON</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {maxHeight && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-6 gap-1 text-xs text-muted-foreground"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? <><ArrowsIn className="w-3.5 h-3.5" /> Collapse</> : <><ArrowsOut className="w-3.5 h-3.5" /> Expand</>}
          </Button>
        )}
      </div>
      {/* The height cap and the scroll live on the <Table>'s own container,
          not on this border box: see the note in ui/table.tsx for why putting
          them out here breaks the sticky header. */}
      <div className={`border rounded-md ${className ?? ''}`}>
        <TableScrollContext.Provider value={scrollEl}>
          <Table
            ref={tableRef}
            containerRef={(node) => {
              setScrollEl(node)
              scrollRef?.(node)
            }}
            containerStyle={
              expanded
                ? expandedMaxHeight
                  ? { maxHeight: expandedMaxHeight }
                  : undefined
                : maxHeight
                  ? { maxHeight }
                  : undefined
            }
            // A capped table scrolls, and a scrolling table whose header
            // scrolls away leaves you reading unlabelled columns. Applied here
            // rather than table by table: every table that scrolls wants this,
            // and a few had hand-rolled it already (see STICKY_HEAD in
            // PowerFlowTab) while the rest silently went without.
            className={maxHeight ? '[&_thead_th]:sticky [&_thead_th]:top-0 [&_thead_th]:z-10 [&_thead_th]:bg-background' : undefined}
          >
            {children}
          </Table>
        </TableScrollContext.Provider>
      </div>
    </div>
  )
}
