import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { TableHead, TableHeader, TableRow, TableCell } from '@/components/ui/table'
import { TableCard } from '@/components/TableCard'
import { VirtualTableBody, RESULT_ROW_HEIGHT } from '@/components/VirtualTableBody'
import { Funnel, Table as TableIcon, X, ArrowUp, ArrowDown, WarningCircle } from '@phosphor-icons/react'
import type { MeasurementKind, Topology } from '@/lib/types'
import { MEASUREMENT_KINDS, MEASUREMENT_KIND_INFO, buildMeasurementIndex } from '@/lib/measurements'
import { compileExpression, type ExprRow } from '@/lib/expressionFilter'
import { selectionSize, type TopologySelection } from '@/lib/selection'

type Kind = 'bus' | 'line'

interface Column {
  key: string
  label: string
  numeric?: boolean
}

const BUS_COLUMNS: Column[] = [
  { key: 'id', label: 'ID', numeric: true },
  { key: 'name', label: 'Name' },
  { key: 'type', label: 'Type' },
  { key: 'voltage', label: 'V (pu)', numeric: true },
  { key: 'angle', label: 'θ (°)', numeric: true },
  { key: 'pGen', label: 'P Gen', numeric: true },
  { key: 'qGen', label: 'Q Gen', numeric: true },
  { key: 'pLoad', label: 'P Load', numeric: true },
  { key: 'qLoad', label: 'Q Load', numeric: true },
  { key: 'pGenDG', label: 'P DG', numeric: true },
  { key: 'qGenDG', label: 'Q DG', numeric: true },
  { key: 'meter', label: 'Meter' },
  { key: 'degree', label: 'Degree', numeric: true },
  { key: 'geoX', label: 'X / lon', numeric: true },
  { key: 'geoY', label: 'Y / lat', numeric: true },
]

const LINE_COLUMNS: Column[] = [
  { key: 'id', label: 'ID', numeric: true },
  { key: 'from', label: 'From', numeric: true },
  { key: 'to', label: 'To', numeric: true },
  { key: 'resistance', label: 'R (pu)', numeric: true },
  { key: 'reactance', label: 'X (pu)', numeric: true },
  { key: 'susceptance', label: 'B (pu)', numeric: true },
  { key: 'xr', label: 'X/R', numeric: true },
  { key: 'tapRatio', label: 'Tap', numeric: true },
  { key: 'meter', label: 'Meter' },
]

const EXAMPLES: Record<Kind, string[]> = {
  bus: ["type = 'pq' AND pLoad > 0.5", 'meter IS NULL', 'degree >= 3', "name LIKE 'Bus 1%'"],
  line: ['xr < 1', 'from = 1 OR to = 1', 'abs(reactance) > 0.05', 'meter IS NOT NULL'],
}

const HELP =
  'Fields: use the column names (id, type, pLoad, degree, meter…). Operators: = != < <= > >=, AND OR NOT, IN (…), LIKE \'a%\', IS [NOT] NULL, + - * /, abs() sqrt() round() min() max(). Text comparisons ignore case.'

function num(v: number | undefined | null): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function formatCell(v: ExprRow[string]): string {
  if (v == null) return '—'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(5)))
  return String(v)
}

interface AttributeExplorerProps {
  topology: Topology
  selection: TopologySelection
  onSelectionChange: (selection: TopologySelection) => void
  /** Assign (or, with 'none', remove) a meter on several buses/lines at once. */
  onSetMeterKind: (kind: Kind, ids: number[], meter: MeasurementKind | 'none') => void
}

/**
 * Attribute table for the topology, in the spirit of QGIS's attribute table:
 * filter with an expression, click to select (Ctrl/Cmd toggles, Shift
 * extends a range), and the same selection is highlighted on the diagram.
 * Read-only on purpose — the editable Bus/Line data tables below stay the
 * place to change values.
 */
export function AttributeExplorer({ topology, selection, onSelectionChange, onSetMeterKind }: AttributeExplorerProps) {
  const [kind, setKind] = useState<Kind>('bus')
  const [expressions, setExpressions] = useState<Record<Kind, string>>({ bus: '', line: '' })
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(null)
  const [selectedOnly, setSelectedOnly] = useState(false)
  const [scrollEl, setScrollEl] = useState<HTMLElement | null>(null)
  const anchorRef = useRef<number | null>(null)
  // Selection changes made by clicking in this table must not scroll it.
  const internalChangeRef = useRef(false)

  const columns = kind === 'bus' ? BUS_COLUMNS : LINE_COLUMNS
  const selectedIds = kind === 'bus' ? selection.buses : selection.lines
  const expression = expressions[kind]

  const rows: ExprRow[] = useMemo(() => {
    const index = buildMeasurementIndex(topology)
    if (kind === 'bus') {
      const degree = new Map<number, number>()
      for (const l of topology.lines) {
        degree.set(l.from, (degree.get(l.from) ?? 0) + 1)
        degree.set(l.to, (degree.get(l.to) ?? 0) + 1)
      }
      return topology.buses.map((b) => ({
        id: b.id,
        name: b.name,
        type: b.type,
        voltage: num(b.voltage),
        angle: num(b.angle),
        pGen: num(b.pGen),
        qGen: num(b.qGen),
        pLoad: num(b.pLoad),
        qLoad: num(b.qLoad),
        pGenDG: num(b.pGenDG ?? 0),
        qGenDG: num(b.qGenDG ?? 0),
        meter: index.busKind.get(b.id) ?? null,
        degree: degree.get(b.id) ?? 0,
        geoX: num(b.geoX),
        geoY: num(b.geoY),
      }))
    }
    return topology.lines.map((l) => ({
      id: l.id,
      from: l.from,
      to: l.to,
      resistance: num(l.resistance),
      reactance: num(l.reactance),
      susceptance: num(l.susceptance),
      xr: l.resistance > 0 ? num(l.reactance / l.resistance) : null,
      tapRatio: num(l.tapRatio),
      meter: index.lineKind.get(l.id) ?? null,
    }))
  }, [topology, kind])

  const hasGeo = useMemo(() => topology.buses.some((b) => b.geoX != null && b.geoY != null), [topology.buses])
  const visibleColumns = useMemo(
    () => columns.filter((c) => hasGeo || (c.key !== 'geoX' && c.key !== 'geoY')),
    [columns, hasGeo]
  )

  const compiled = useMemo(() => compileExpression(expression, columns.map((c) => c.key)), [expression, columns])

  const displayed = useMemo(() => {
    let out = compiled.ok ? rows.filter(compiled.test) : rows
    if (selectedOnly) out = out.filter((r) => selectedIds.has(r.id as number))
    if (sort) {
      const dir = sort.dir === 'asc' ? 1 : -1
      out = [...out].sort((a, b) => {
        const va = a[sort.key]
        const vb = b[sort.key]
        if (va == null && vb == null) return 0
        if (va == null) return 1
        if (vb == null) return -1
        if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
        return String(va).localeCompare(String(vb), undefined, { numeric: true }) * dir
      })
    }
    return out
  }, [rows, compiled, sort, selectedOnly, selectedIds])

  const commit = useCallback(
    (ids: Set<number>) => {
      internalChangeRef.current = true
      onSelectionChange(kind === 'bus' ? { ...selection, buses: ids } : { ...selection, lines: ids })
    },
    [kind, selection, onSelectionChange]
  )

  const handleRowClick = (event: ReactMouseEvent, id: number) => {
    if (event.shiftKey && anchorRef.current != null) {
      const ids = displayed.map((r) => r.id as number)
      const a = ids.indexOf(anchorRef.current)
      const b = ids.indexOf(id)
      if (a !== -1 && b !== -1) {
        const next = new Set(event.ctrlKey || event.metaKey ? selectedIds : [])
        for (const i of ids.slice(Math.min(a, b), Math.max(a, b) + 1)) next.add(i)
        commit(next)
        return
      }
    }
    anchorRef.current = id
    if (event.ctrlKey || event.metaKey) {
      const next = new Set(selectedIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      commit(next)
    } else {
      // Plain click replaces the whole selection (both kinds), like clicking
      // an element on the diagram does.
      internalChangeRef.current = true
      onSelectionChange(kind === 'bus' ? { buses: new Set([id]), lines: new Set() } : { buses: new Set(), lines: new Set([id]) })
    }
  }

  const selectShown = () => commit(new Set(displayed.map((r) => r.id as number)))
  const invertShown = () => {
    const next = new Set(selectedIds)
    for (const r of displayed) {
      const id = r.id as number
      if (next.has(id)) next.delete(id)
      else next.add(id)
    }
    commit(next)
  }
  const clearAll = () => {
    internalChangeRef.current = true
    onSelectionChange({ buses: new Set(), lines: new Set() })
  }

  // Bring the first selected row into view when the selection came from the
  // diagram (or anywhere else outside this table).
  useEffect(() => {
    if (internalChangeRef.current) {
      internalChangeRef.current = false
      return
    }
    if (!scrollEl || selectedIds.size === 0) return
    const first = displayed.findIndex((r) => selectedIds.has(r.id as number))
    if (first === -1) return
    const top = first * RESULT_ROW_HEIGHT
    if (top < scrollEl.scrollTop || top > scrollEl.scrollTop + scrollEl.clientHeight - RESULT_ROW_HEIGHT * 2) {
      scrollEl.scrollTop = Math.max(0, top - RESULT_ROW_HEIGHT * 3)
    }
    // Only react to the selection itself; re-running on every filter/sort
    // change would fight the user's scrolling.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection])

  const exportData = useCallback(
    () => ({
      headers: visibleColumns.map((c) => c.label),
      rows: displayed.map((r) => visibleColumns.map((c) => formatCell(r[c.key]))),
    }),
    [visibleColumns, displayed]
  )

  const toggleSort = (key: string) =>
    setSort((prev) => (prev?.key !== key ? { key, dir: 'asc' } : prev.dir === 'asc' ? { key, dir: 'desc' } : null))

  const total = rows.length
  const selectedHere = selectedIds.size

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 pr-8">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <TableIcon weight="fill" className="w-4 h-4" />
            Attribute Table
          </h3>
          <p className="text-[11px] text-muted-foreground">
            Click selects · Ctrl/Cmd toggles · Shift = range · highlighted on the diagram and map
          </p>
        </div>
        <Tabs value={kind} onValueChange={(v) => setKind(v as Kind)}>
          <TabsList>
            <TabsTrigger value="bus" className="text-xs">
              Buses ({topology.buses.length})
              {selection.buses.size > 0 && <Badge variant="secondary" className="ml-1.5 mono text-[10px]">{selection.buses.size}</Badge>}
            </TabsTrigger>
            <TabsTrigger value="line" className="text-xs">
              Lines ({topology.lines.length})
              {selection.lines.size > 0 && <Badge variant="secondary" className="ml-1.5 mono text-[10px]">{selection.lines.size}</Badge>}
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      <div className="space-y-3">
        <div className="space-y-1.5">
          <div className="relative">
            <Funnel className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              value={expression}
              onChange={(e) => setExpressions((prev) => ({ ...prev, [kind]: e.target.value }))}
              placeholder={`Filter ${kind === 'bus' ? 'buses' : 'lines'} — e.g. ${EXAMPLES[kind][0]}`}
              title={HELP}
              spellCheck={false}
              className="pl-8 pr-8 font-mono text-xs h-9"
              aria-invalid={!compiled.ok}
            />
            {expression && (
              <button
                type="button"
                onClick={() => setExpressions((prev) => ({ ...prev, [kind]: '' }))}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label="Clear filter"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
          {!compiled.ok ? (
            <p className="flex items-center gap-1 text-xs text-destructive">
              <WarningCircle className="w-3.5 h-3.5" /> {compiled.error}
            </p>
          ) : !expression ? (
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <span>Try:</span>
              {EXAMPLES[kind].map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => setExpressions((prev) => ({ ...prev, [kind]: ex }))}
                  className="mono rounded border px-1.5 py-0.5 hover:bg-muted"
                >
                  {ex}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground mono">
            {compiled.ok ? `${displayed.length} of ${total} shown` : `${total} rows`} · {selectedHere} selected
            {selectionSize(selection) > selectedHere && ` (+${selectionSize(selection) - selectedHere} other)`}
          </span>
          <div className="flex flex-wrap items-center gap-1.5 sm:ml-auto">
            <Button type="button" size="sm" variant="outline" className="h-7 text-xs" onClick={selectShown} disabled={displayed.length === 0}>
              Select shown
            </Button>
            <Button type="button" size="sm" variant="outline" className="h-7 text-xs" onClick={invertShown} disabled={displayed.length === 0}>
              Invert
            </Button>
            <Button
              type="button"
              size="sm"
              variant={selectedOnly ? 'default' : 'outline'}
              className="h-7 text-xs"
              onClick={() => setSelectedOnly((v) => !v)}
              title="Show only the selected rows"
            >
              Selected only
            </Button>
            <Button type="button" size="sm" variant="outline" className="h-7 text-xs" onClick={clearAll} disabled={selectionSize(selection) === 0}>
              Clear
            </Button>
            <Select
              value=""
              onValueChange={(v) => onSetMeterKind(kind, [...selectedIds], v as MeasurementKind | 'none')}
              disabled={selectedHere === 0}
            >
              <SelectTrigger className="h-7 w-44 text-xs" title="Assign a meter to every selected row">
                <SelectValue placeholder={`Set meter (${selectedHere})…`} />
              </SelectTrigger>
              <SelectContent>
                {MEASUREMENT_KINDS.map((k) => (
                  <SelectItem key={k} value={k}>
                    {MEASUREMENT_KIND_INFO[k].label}
                  </SelectItem>
                ))}
                <SelectItem value="none">No meter</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <TableCard
          key={kind}
          label={kind === 'bus' ? 'Bus attributes' : 'Line attributes'}
          maxHeight="22rem"
          expandedMaxHeight="80vh"
          scrollRef={setScrollEl}
          exportData={exportData}
        >
          <TableHeader>
            <TableRow>
              {visibleColumns.map((c) => (
                <TableHead
                  key={c.key}
                  onClick={() => toggleSort(c.key)}
                  className="mono text-xs whitespace-nowrap cursor-pointer select-none hover:text-foreground"
                >
                  <span className="inline-flex items-center gap-1">
                    {c.label}
                    {sort?.key === c.key && (sort.dir === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
                  </span>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <VirtualTableBody
            items={displayed}
            rowHeight={RESULT_ROW_HEIGHT}
            renderRow={(row) => {
              const id = row.id as number
              const isSelected = selectedIds.has(id)
              return (
                <TableRow
                  key={id}
                  onClick={(e) => handleRowClick(e, id)}
                  style={{ height: RESULT_ROW_HEIGHT }}
                  className={`cursor-pointer ${isSelected ? 'bg-selection/20 hover:bg-selection/25' : ''}`}
                >
                  {visibleColumns.map((c) => (
                    <TableCell key={c.key} className={`text-xs whitespace-nowrap ${c.numeric ? 'mono' : ''}`}>
                      {formatCell(row[c.key])}
                    </TableCell>
                  ))}
                </TableRow>
              )
            }}
          />
        </TableCard>
        {displayed.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-2">
            {selectedOnly && selectedHere === 0 ? 'Nothing selected yet.' : 'No rows match the filter.'}
          </p>
        )}
      </div>
    </div>
  )
}
