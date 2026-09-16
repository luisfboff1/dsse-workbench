import { useCallback, useState, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { TableCard } from '@/components/TableCard'
import { Network, Plus, Trash, CircleNotch } from '@phosphor-icons/react'
import type { Topology, Bus, Line, MeasurementKind, OpenSwitch } from '@/lib/types'
import { DEFAULT_TOPOLOGIES } from '@/lib/topologies'
import { TopologyDiagram } from '@/components/TopologyDiagram'
import { toast } from 'sonner'
import { getPandapowerCases, loadPandapowerCase, type PandapowerCaseInfo, type PandapowerVoltageClass } from '@/lib/api'
import { checkRadial, getTopologySwitches } from '@/lib/networkTopology'
import { ensureMeasurements } from '@/lib/measurements'
import { NUM_INPUT_CLASS } from '@/lib/utils'
import { VirtualTableBody } from '@/components/VirtualTableBody'

const VOLTAGE_CLASS_LABEL: Record<PandapowerVoltageClass, string> = {
  distribution: 'Distribution (MV)',
  transmission: 'Transmission',
  lv: 'LV (BT)',
}

interface TopologyTabProps {
  topology: Topology
  onTopologyChange: (topology: Topology) => void
}

// Shared with any other editable numeric table — see NUM_INPUT_CLASS in
// lib/utils.ts for what it does and why.
const NUM_INPUT = NUM_INPUT_CLASS

// The Bus/Line data tables render a windowed slice of their rows, which needs
// a fixed row height and a scroll container to window against. Both tables
// used to grow unbounded down the page; a pandapower case with a few thousand
// buses turned that into tens of thousands of controlled inputs.
const DATA_ROW_HEIGHT = 45
const DATA_TABLE_MAX_HEIGHT = '32rem'
const DATA_TABLE_EXPANDED_MAX_HEIGHT = '80vh'

// Which bus fields are real solver inputs vs. outputs only known after solving
// (see network_builder.py — PQ buses never read voltage/angle, PV never reads
// angle, and qGen is never read for any bus type: it's always what "floats").
function isBusFieldEditable(type: string, field: 'voltage' | 'angle' | 'pGen' | 'qGen'): boolean {
  switch (field) {
    case 'voltage': return type === 'slack' || type === 'pv'
    case 'angle': return type === 'slack'
    case 'pGen': return type === 'pv'
    case 'qGen': return false
  }
}

const NON_EDITABLE_TITLE = 'Not a solver input — this value is only known after running Power Flow / State Estimation.'

export function TopologyTab({ topology, onTopologyChange }: TopologyTabProps) {
  const [ppCases, setPpCases] = useState<PandapowerCaseInfo[]>([])
  const [ppListLoading, setPpListLoading] = useState(true)   // loading the case-name list
  const [ppListError, setPpListError] = useState<string | null>(null)
  const [ppLoading, setPpLoading] = useState(false)          // loading a specific case
  // Defaults to distribution — the thesis's actual domain. LV stays a click
  // away instead of cluttering the default list (25 of 60 cases are LV).
  const [ppVoltageClass, setPpVoltageClass] = useState<PandapowerVoltageClass>('distribution')
  const [hoveredLineId, setHoveredLineId] = useState<number | null>(null)

  // TableCard's Copy normally reads the rendered cells back out of the DOM,
  // which is what keeps an export matching what's on screen. With windowed
  // rows the DOM only holds a slice, so both tables hand it the full contents
  // instead — same columns, same formatting as the cells above.
  const exportBusData = useCallback(
    () => ({
      headers: ['ID', 'Name', 'Type', 'V (pu)', 'θ (°)', 'P Gen', 'Q Gen', 'P Load', 'Q Load', 'P DG', 'Q DG'],
      rows: topology.buses.map((bus) => [
        String(bus.id),
        bus.name,
        bus.type.toUpperCase(),
        isBusFieldEditable(bus.type, 'voltage') ? String(bus.voltage) : '',
        isBusFieldEditable(bus.type, 'angle') ? String(bus.angle) : '',
        isBusFieldEditable(bus.type, 'pGen') ? String(bus.pGen) : '',
        '',
        String(bus.pLoad),
        String(bus.qLoad),
        String(bus.pGenDG ?? 0),
        String(bus.qGenDG ?? 0),
      ]),
    }),
    [topology.buses]
  )
  const exportLineData = useCallback(
    () => ({
      headers: ['ID', 'From', 'To', 'R (pu)', 'X (pu)', 'B (pu)', 'X/R'],
      rows: topology.lines.map((line) => [
        String(line.id),
        String(line.from),
        String(line.to),
        String(line.resistance),
        String(line.reactance),
        String(line.susceptance),
        line.resistance > 0 ? (line.reactance / line.resistance).toFixed(2) : '—',
      ]),
    }),
    [topology.lines]
  )

  // Fetching the pandapower case list used to end in `.catch(() => {})`, so a
  // failure left the dropdown holding only the built-in templates, forever,
  // with nothing on screen saying why. That is not a rare path: uvicorn takes
  // a while to import pandapower, so anyone who opens the front end right
  // after starting the backend hits it. Now it retries once on its own (for
  // exactly that case) and then says so, with a button.
  const loadCaseList = useCallback(async (attempt = 0) => {
    setPpListLoading(true)
    setPpListError(null)
    try {
      setPpCases(await getPandapowerCases())
    } catch (err) {
      if (attempt === 0) {
        // Most likely the backend is still starting up. Try again shortly
        // before bothering anyone about it.
        setTimeout(() => void loadCaseList(1), 2500)
        return
      }
      setPpListError(err instanceof Error ? err.message : String(err))
    } finally {
      setPpListLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadCaseList()
  }, [loadCaseList])

  const loadTemplate = (value: string) => {
    if (value.startsWith('pp:')) {
      const caseName = value.slice(3)
      setPpLoading(true)
      loadPandapowerCase(caseName)
        .then((topo) => onTopologyChange(ensureMeasurements(topo)))
        .catch((err) => toast.error(`Could not load ${caseName}: ${err instanceof Error ? err.message : err}`))
        .finally(() => setPpLoading(false))
      return
    }
    const template = DEFAULT_TOPOLOGIES.find((t) => t.id === value)
    if (template) onTopologyChange(ensureMeasurements({ ...template }))
  }

  const updateBus = (busId: number, field: keyof Bus, value: string | number) => {
    const updatedBuses = topology.buses.map((bus) =>
      bus.id === busId ? { ...bus, [field]: value } : bus
    )
    onTopologyChange({ ...topology, buses: updatedBuses })
  }

  const updateLine = (lineId: number, field: keyof Line, value: string | number) => {
    const updatedLines = topology.lines.map((line) =>
      line.id === lineId ? { ...line, [field]: value } : line
    )
    onTopologyChange({ ...topology, lines: updatedLines })
  }

  const addBus = () => {
    const newBus: Bus = {
      id: topology.buses.length + 1,
      name: `Bus ${topology.buses.length + 1}`,
      type: 'pq',
      voltage: 1.0,
      angle: 0,
      pGen: 0,
      qGen: 0,
      pLoad: 0,
      qLoad: 0,
      pGenDG: 0,
      qGenDG: 0,
    }
    onTopologyChange({
      ...topology,
      buses: [...topology.buses, newBus],
      measurements: [...(topology.measurements ?? []), { busId: newBus.id, kind: 'scada' }],
    })
  }

  // 'none' removes the bus's meter entirely (simulates a genuinely
  // unobserved bus) — every other value upserts it. Used by the diagram's
  // click-to-assign popover.
  const setMeasurementKind = (busId: number, kind: MeasurementKind | 'none') => {
    const withoutBus = (topology.measurements ?? []).filter((m) => m.busId !== busId)
    const measurements = kind === 'none' ? withoutBus : [...withoutBus, { busId, kind }]
    onTopologyChange({ ...topology, measurements })
  }

  // Same 'none' convention as setMeasurementKind, for a line meter instead
  // of a bus meter — used by the diagram's click-on-line popover.
  const setLineMeasurementKind = (lineId: number, kind: MeasurementKind | 'none') => {
    const withoutLine = (topology.line_measurements ?? []).filter((m) => m.lineId !== lineId)
    const line_measurements = kind === 'none' ? withoutLine : [...withoutLine, { lineId, kind }]
    onTopologyChange({ ...topology, line_measurements })
  }

  // ── Batch meter placement ────────────────────────────────────────────────
  // Overwrites all bus and/or line measurements in one shot. Used by the
  // "Apply to all" bar at the top of the Meters side panel in TopologyDiagram.
  const applyMeterToAll = (kind: MeasurementKind, target: 'buses' | 'lines' | 'both') => {
    let next = { ...topology }
    if (target === 'buses' || target === 'both') {
      next = { ...next, measurements: topology.buses.map((b) => ({ busId: b.id, kind })) }
    }
    if (target === 'lines' || target === 'both') {
      next = { ...next, line_measurements: topology.lines.map((l) => ({ lineId: l.id, kind })) }
    }
    onTopologyChange(next)
  }

  const toggleSwitch = (switchId: number, closed: boolean) => {
    const currentSwitches = getTopologySwitches(topology)
    const switchIndex = currentSwitches.findIndex((s) => s.id === switchId)
    if (switchIndex === -1) return
    
    const sw = currentSwitches[switchIndex]
    if (sw.closed === closed) return // already in desired state

    const newSwitches = [...currentSwitches]
    newSwitches[switchIndex] = { ...sw, closed }
    
    // We also keep openSwitches in sync for legacy components (like D3 diagram before it updates)
    const newOpenSwitches = newSwitches.filter(s => !s.closed)

    const newLines = [...topology.lines]
    
    if (closed) {
      const newLineId = Math.max(0, ...topology.lines.map((l) => l.id)) + 1
      const newLine: Line = {
        id: newLineId,
        from: sw.from,
        to: sw.to,
        resistance: sw.r_pu ?? 0.001,
        reactance: sw.x_pu ?? 0.001,
        susceptance: sw.b_pu ?? 0,
      }
      newLines.push(newLine)

      const check = checkRadial({ ...topology, lines: newLines })
      if (check.status === 'meshed') {
        toast.warning(`Closing ${sw.name ?? `SW-${switchId}`} creates a loop. Open another switch to maintain radial topology.`)
      } else if (check.status === 'radial') {
        toast.success(`Network is radial (${newLines.length} branches for ${topology.buses.length} buses).`)
      }
    } else {
      const r_target = sw.r_pu ?? 0.001
      const x_target = sw.x_pu ?? 0.001
      let lineIndex = newLines.findIndex(
        (l) => 
          ((l.from === sw.from && l.to === sw.to) || (l.from === sw.to && l.to === sw.from)) &&
          Math.abs(l.resistance - r_target) < 1e-4 &&
          Math.abs(l.reactance - x_target) < 1e-4
      )
      if (lineIndex === -1) {
        lineIndex = newLines.findIndex(
          (l) => (l.from === sw.from && l.to === sw.to) || (l.from === sw.to && l.to === sw.from)
        )
      }
      
      if (lineIndex !== -1) {
        newLines.splice(lineIndex, 1)
      }

      const check = checkRadial({ ...topology, lines: newLines })
      if (check.status === 'radial') {
        toast.success(`Network is now radial (${newLines.length} branches for ${topology.buses.length} buses).`)
      } else if (check.status === 'disconnected') {
        toast.info(`Opening ${sw.name ?? `SW-${switchId}`} created a radial island. Close another switch to re-energize all buses.`)
      }
    }

    onTopologyChange({
      ...topology,
      lines: newLines,
      switches: newSwitches,
      openSwitches: newOpenSwitches,
    })
  }

  const resetSwitchesToDefault = async () => {
    if (topology.id?.startsWith('pp_')) {
      const caseName = topology.id.slice(3)
      try {
        setPpLoading(true)
        const pristine = await loadPandapowerCase(caseName)
        onTopologyChange(ensureMeasurements(pristine))
        toast.success(`Switches reset to default for ${caseName}.`)
        return
      } catch (err: any) {
        toast.error(`Failed to reset: ${err.message}`)
      } finally {
        setPpLoading(false)
      }
    }

    const defaultTopo = DEFAULT_TOPOLOGIES.find((t) => t.id === topology.id)
    if (defaultTopo) {
      onTopologyChange(ensureMeasurements({ ...defaultTopo }))
      toast.success('Switches reset to default topology.')
      return
    }

    const all = getTopologySwitches(topology)
    const openSet = new Set((topology.openSwitches ?? []).map((s) => `${Math.min(s.from, s.to)}-${Math.max(s.from, s.to)}`))
    const pristineSwitches = all.map((s) => ({
      ...s,
      closed: !openSet.has(`${Math.min(s.from, s.to)}-${Math.max(s.from, s.to)}`),
    }))

    const pristineLines: Line[] = pristineSwitches
      .filter((s) => s.closed)
      .map((s, idx) => ({
        id: idx + 1,
        from: s.from,
        to: s.to,
        resistance: s.r_pu ?? 0.001,
        reactance: s.x_pu ?? 0.001,
        susceptance: s.b_pu ?? 0,
      }))

    onTopologyChange({
      ...topology,
      lines: pristineLines,
      switches: pristineSwitches,
      openSwitches: pristineSwitches.filter((s) => !s.closed),
    })
    toast.success('Switches reset to default.')
  }

  const addLine = () => {
    const newLine: Line = {
      id: topology.lines.length + 1,
      from: 1,
      to: topology.buses.length > 1 ? 2 : 1,
      resistance: 0.01,
      reactance: 0.03,
      susceptance: 0.01,
    }
    onTopologyChange({ ...topology, lines: [...topology.lines, newLine] })
  }

  const removeBus = (busId: number) => {
    const updatedBuses = topology.buses.filter((bus) => bus.id !== busId)
    const updatedLines = topology.lines.filter((line) => line.from !== busId && line.to !== busId)
    const removedLineIds = new Set(
      topology.lines.filter((line) => line.from === busId || line.to === busId).map((line) => line.id)
    )
    const updatedMeasurements = (topology.measurements ?? []).filter((m) => m.busId !== busId)
    const updatedLineMeasurements = (topology.line_measurements ?? []).filter((m) => !removedLineIds.has(m.lineId))
    onTopologyChange({
      ...topology,
      buses: updatedBuses,
      lines: updatedLines,
      measurements: updatedMeasurements,
      line_measurements: updatedLineMeasurements,
    })
  }

  const removeLine = (lineId: number) => {
    const updatedLines = topology.lines.filter((line) => line.id !== lineId)
    const updatedLineMeasurements = (topology.line_measurements ?? []).filter((m) => m.lineId !== lineId)
    onTopologyChange({ ...topology, lines: updatedLines, line_measurements: updatedLineMeasurements })
  }

  const getBusTypeBadgeVariant = (type: string) => {
    switch (type) {
      case 'slack': return 'default'
      case 'pv': return 'secondary'
      case 'pq': return 'outline'
      default: return 'outline'
    }
  }

  return (
    <div className="space-y-3 sm:space-y-4">
      <TopologyDiagram
        topology={topology}
        onMeasurementKindChange={setMeasurementKind}
        onLineMeasurementKindChange={setLineMeasurementKind}
        onApplyMeterToAll={applyMeterToAll}
        onSwitchToggle={toggleSwitch}
        onResetSwitches={resetSwitchesToDefault}
      />

      <Card>
        <CardHeader className="px-4 sm:px-6 py-4 sm:py-6">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base sm:text-lg">
                <Network weight="fill" className="w-4 h-4 sm:w-5 sm:h-5" />
                Topology Configuration
              </CardTitle>
              <CardDescription className="text-xs sm:text-sm">Define network structure and parameters</CardDescription>
            </div>
            <div className="flex flex-col gap-2 items-stretch sm:items-end w-full sm:w-auto">
              <div className="flex gap-1 justify-end">
                {(['distribution', 'transmission', 'lv'] as PandapowerVoltageClass[]).map((vc) => {
                  const count = ppCases.filter((c) => c.voltageClass === vc).length
                  return (
                    <Button
                      key={vc}
                      type="button"
                      size="sm"
                      variant={ppVoltageClass === vc ? 'default' : 'outline'}
                      onClick={() => setPpVoltageClass(vc)}
                      className="h-7 mono text-xs"
                    >
                      {VOLTAGE_CLASS_LABEL[vc]}{count > 0 ? ` (${count})` : ''}
                    </Button>
                  )
                })}
              </div>
              <Select value={topology.id} onValueChange={loadTemplate}>
                <SelectTrigger className="w-full sm:w-65" disabled={ppListLoading || ppLoading}>
                  {ppLoading
                    ? <span className="flex items-center gap-1.5 text-muted-foreground"><CircleNotch className="animate-spin w-3 h-3" />Loading case…</span>
                    : ppListLoading
                      ? <span className="flex items-center gap-1.5 text-muted-foreground"><CircleNotch className="animate-spin w-3 h-3" />Loading list…</span>
                      : <SelectValue placeholder="Load template..." />}
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectLabel>Custom Templates</SelectLabel>
                    {DEFAULT_TOPOLOGIES.map((topo) => (
                      <SelectItem key={topo.id} value={topo.id}>
                        {topo.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                  {ppCases.filter((c) => c.voltageClass === ppVoltageClass).length > 0 && (
                    <>
                      <SelectSeparator />
                      <SelectGroup>
                        <SelectLabel>pandapower · {VOLTAGE_CLASS_LABEL[ppVoltageClass]}</SelectLabel>
                        {ppCases.filter((c) => c.voltageClass === ppVoltageClass).map((c) => (
                          <SelectItem key={c.name} value={`pp:${c.name}`}>
                            <span className="font-mono">{c.name}</span>
                            <span className="ml-2 text-muted-foreground text-[10px]">
                              {c.buses != null
                                ? `${c.buses}b · ${c.lines}L${c.trafos ? ` · ${c.trafos}T` : ''} · ${c.sn_mva}MVA`
                                : 'loads on selection'}
                          </span>
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </>
                )}
              </SelectContent>
            </Select>
            {ppListError && (
              <div className="flex items-center justify-end gap-2 text-xs text-destructive">
                <span className="truncate" title={ppListError}>
                  pandapower case list unavailable
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-6 px-2 text-xs"
                  onClick={() => void loadCaseList(1)}
                >
                  Retry
                </Button>
              </div>
            )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="px-4 sm:px-6 pb-4 sm:pb-6">
          <div className="flex flex-wrap items-center gap-2 text-xs sm:text-sm text-muted-foreground">
            <span>
              <strong>{topology.name}</strong> - {topology.buses.length} buses, {topology.lines.length} lines
            </span>
            {(() => {
              const radial = checkRadial(topology)
              if (radial.status === 'radial') {
                return <Badge variant="outline" className="mono text-[10px]">radial</Badge>
              }
              if (radial.status === 'meshed') {
                return (
                  <Badge variant="secondary" className="mono text-[10px]">
                    meshed ({radial.nLines} lines, {radial.nExpectedRadial} expected for radial)
                  </Badge>
                )
              }
              return (
                <Badge variant="secondary" className="mono text-[10px]">
                  disconnected? ({radial.nLines} of {radial.nExpectedRadial} lines)
                </Badge>
              )
            })()}
          </div>
        </CardContent>
      </Card>

      {/* auto-fit + minmax, not a fixed lg:grid-cols-2 breakpoint: each card
          needs ~700px of usable table width before it's worth sitting next
          to the other one, and that threshold depends on the actual window
          width, not a device-class guess — so let the grid measure it. */}
      <div className="grid grid-cols-[repeat(auto-fit,minmax(700px,1fr))] gap-3 sm:gap-4">
        <Card>
          <CardHeader className="px-4 sm:px-6 py-4 sm:py-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base sm:text-lg">Bus Data</CardTitle>
                <CardDescription className="text-xs sm:text-sm">
                  Configure bus voltages, generation, and loads — grayed fields are outputs (only known after Power Flow / State Estimation), not inputs
                </CardDescription>
              </div>
              <Button onClick={addBus} size="sm" variant="outline" className="w-full sm:w-auto">
                <Plus className="mr-1 w-4 h-4" />Add Bus
              </Button>
            </div>
          </CardHeader>
          <CardContent className="px-4 sm:px-6 pb-4 sm:pb-6">
            <TableCard
              label="Bus Data"
              maxHeight={DATA_TABLE_MAX_HEIGHT}
              expandedMaxHeight={DATA_TABLE_EXPANDED_MAX_HEIGHT}
              exportData={exportBusData}
            >
                <TableHeader>
                  <TableRow>
                    <TableHead className="mono text-xs whitespace-nowrap">ID</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">Name</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">Type</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">V (pu)</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">θ (°)</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">P Gen</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">Q Gen</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">P Load</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">Q Load</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">P DG</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">Q DG</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                {/* Windowed rows: each bus row carries nine controlled
                    <Input>s, and React re-renders every mounted one whenever
                    `topology` changes identity — i.e. on every keystroke.
                    Mounting only what fits keeps a thousand-bus case
                    typeable. */}
                <VirtualTableBody
                  items={topology.buses}
                  rowHeight={DATA_ROW_HEIGHT}
                  renderRow={(bus) => (
                    <TableRow key={bus.id} style={{ height: DATA_ROW_HEIGHT }}>
                      <TableCell className="font-medium text-xs">{bus.id}</TableCell>
                      <TableCell>
                        <Input value={bus.name}
                          onChange={(e) => updateBus(bus.id, 'name', e.target.value)}
                          className="h-7 w-24 text-xs" />
                      </TableCell>
                      <TableCell>
                        <Badge variant={getBusTypeBadgeVariant(bus.type) as any} className="text-[10px]">
                          {bus.type.toUpperCase()}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Input type="number" step="0.01"
                          value={isBusFieldEditable(bus.type, 'voltage') ? bus.voltage : ''}
                          disabled={!isBusFieldEditable(bus.type, 'voltage')}
                          placeholder="—"
                          title={!isBusFieldEditable(bus.type, 'voltage') ? NON_EDITABLE_TITLE : undefined}
                          onChange={(e) => updateBus(bus.id, 'voltage', parseFloat(e.target.value))}
                          className={`h-7 min-w-12 max-w-24 ${NUM_INPUT}`} />
                      </TableCell>
                      <TableCell>
                        <Input type="number" step="0.1"
                          value={isBusFieldEditable(bus.type, 'angle') ? bus.angle : ''}
                          disabled={!isBusFieldEditable(bus.type, 'angle')}
                          placeholder="—"
                          title={!isBusFieldEditable(bus.type, 'angle') ? NON_EDITABLE_TITLE : undefined}
                          onChange={(e) => updateBus(bus.id, 'angle', parseFloat(e.target.value))}
                          className={`h-7 min-w-12 max-w-24 ${NUM_INPUT}`} />
                      </TableCell>
                      <TableCell>
                        <Input type="number" step="0.01"
                          value={isBusFieldEditable(bus.type, 'pGen') ? bus.pGen : ''}
                          disabled={!isBusFieldEditable(bus.type, 'pGen')}
                          placeholder="—"
                          title={!isBusFieldEditable(bus.type, 'pGen') ? NON_EDITABLE_TITLE : undefined}
                          onChange={(e) => updateBus(bus.id, 'pGen', parseFloat(e.target.value))}
                          className={`h-7 min-w-12 max-w-24 ${NUM_INPUT}`} />
                      </TableCell>
                      <TableCell>
                        <Input type="number" step="0.01"
                          value=""
                          disabled
                          placeholder="—"
                          title={NON_EDITABLE_TITLE}
                          onChange={() => {}}
                          className={`h-7 min-w-12 max-w-24 ${NUM_INPUT}`} />
                      </TableCell>
                      <TableCell>
                        <Input type="number" step="0.01" value={bus.pLoad}
                          onChange={(e) => updateBus(bus.id, 'pLoad', parseFloat(e.target.value))}
                          className={`h-7 min-w-12 max-w-24 ${NUM_INPUT}`} />
                      </TableCell>
                      <TableCell>
                        <Input type="number" step="0.01" value={bus.qLoad}
                          onChange={(e) => updateBus(bus.id, 'qLoad', parseFloat(e.target.value))}
                          className={`h-7 min-w-12 max-w-24 ${NUM_INPUT}`} />
                      </TableCell>
                      <TableCell>
                        <Input type="number" step="0.01" value={bus.pGenDG ?? 0}
                          title="Distributed generation (sgen) — fixed PQ, doesn't control voltage. See PV/wind DG on pandapower cases."
                          onChange={(e) => updateBus(bus.id, 'pGenDG', parseFloat(e.target.value))}
                          className={`h-7 min-w-12 max-w-24 ${NUM_INPUT} ${bus.pGenDG ? 'text-status-good' : ''}`} />
                      </TableCell>
                      <TableCell>
                        <Input type="number" step="0.01" value={bus.qGenDG ?? 0}
                          title="Distributed generation (sgen) — fixed PQ, doesn't control voltage. See PV/wind DG on pandapower cases."
                          onChange={(e) => updateBus(bus.id, 'qGenDG', parseFloat(e.target.value))}
                          className={`h-7 min-w-12 max-w-24 ${NUM_INPUT} ${bus.qGenDG ? 'text-status-good' : ''}`} />
                      </TableCell>
                      <TableCell>
                        <Button onClick={() => removeBus(bus.id)} size="sm" variant="ghost"
                          disabled={topology.buses.length === 1} className="h-7 w-7 p-0">
                          <Trash className="w-3 h-3" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  )}
                />
            </TableCard>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="px-4 sm:px-6 py-4 sm:py-6">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base sm:text-lg">Line Data</CardTitle>
                <CardDescription className="text-xs sm:text-sm">
                  {(() => {
                    const xrValues = topology.lines
                      .filter((l) => l.resistance > 0)
                      .map((l) => l.reactance / l.resistance)
                    if (xrValues.length === 0) return 'Configure line parameters (pu)'
                    const sorted = [...xrValues].sort((a, b) => a - b)
                    const median = sorted[Math.floor(sorted.length / 2)]
                    const kind = median >= 5 ? 'Transmission' : median >= 2 ? 'Mixed' : 'Distribution'
                    const color = median >= 5 ? 'text-method-dc' : median >= 2 ? 'text-status-warn' : 'text-method-ldf'
                    return (
                      <span>
                        Configure line parameters (pu) — median X/R:{' '}
                        <span className={`font-semibold mono ${color}`}>{median.toFixed(2)}</span>{' '}
                        <span className={`font-semibold ${color}`}>({kind})</span>
                        {kind === 'Distribution' && <span className="text-method-ldf"> → LinDistFlow recommended</span>}
                        {kind === 'Transmission' && <span className="text-method-dc"> → DC approximation valid</span>}
                      </span>
                    )
                  })()}
                </CardDescription>
              </div>
              <Button onClick={addLine} size="sm" variant="outline" className="w-full sm:w-auto">
                <Plus className="mr-1 w-4 h-4" />Add Line
              </Button>
            </div>
          </CardHeader>
          <CardContent className="px-4 sm:px-6 pb-4 sm:pb-6">
            <TableCard
              label="Line Data"
              maxHeight={DATA_TABLE_MAX_HEIGHT}
              expandedMaxHeight={DATA_TABLE_EXPANDED_MAX_HEIGHT}
              exportData={exportLineData}
            >
                <TableHeader>
                  <TableRow>
                    <TableHead className="mono text-xs whitespace-nowrap">ID</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">From</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">To</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">R (pu)</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">X (pu)</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">B (pu)</TableHead>
                    <TableHead className="mono text-xs whitespace-nowrap">X/R</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                {/* Windowed — same reasoning as the bus table above. */}
                <VirtualTableBody
                  items={topology.lines}
                  rowHeight={DATA_ROW_HEIGHT}
                  renderRow={(line) => {
                    const xr = line.resistance > 0 ? line.reactance / line.resistance : null
                    const xrColor = xr == null ? ''
                      : xr >= 5 ? 'text-method-dc'
                      : xr >= 2 ? 'text-status-warn'
                      : 'text-method-ldf'
                    return (
                      <TableRow key={line.id} style={{ height: DATA_ROW_HEIGHT }}>
                        <TableCell className="font-medium text-xs">{line.id}</TableCell>
                        <TableCell>
                          <Input type="number" value={line.from}
                            onChange={(e) => updateLine(line.id, 'from', parseInt(e.target.value))}
                            className={`h-7 min-w-10 max-w-16 ${NUM_INPUT}`} min={1} max={topology.buses.length} />
                        </TableCell>
                        <TableCell>
                          <Input type="number" value={line.to}
                            onChange={(e) => updateLine(line.id, 'to', parseInt(e.target.value))}
                            className={`h-7 min-w-10 max-w-16 ${NUM_INPUT}`} min={1} max={topology.buses.length} />
                        </TableCell>
                        <TableCell>
                          <Input type="number" step="0.001" value={line.resistance}
                            onChange={(e) => updateLine(line.id, 'resistance', parseFloat(e.target.value))}
                            className={`h-7 min-w-14 max-w-28 ${NUM_INPUT}`} />
                        </TableCell>
                        <TableCell>
                          <Input type="number" step="0.001" value={line.reactance}
                            onChange={(e) => updateLine(line.id, 'reactance', parseFloat(e.target.value))}
                            className={`h-7 min-w-14 max-w-28 ${NUM_INPUT}`} />
                        </TableCell>
                        <TableCell>
                          <Input type="number" step="0.001" value={line.susceptance}
                            onChange={(e) => updateLine(line.id, 'susceptance', parseFloat(e.target.value))}
                            className={`h-7 min-w-14 max-w-24 ${NUM_INPUT}`} />
                        </TableCell>
                        <TableCell className={`mono text-xs font-semibold whitespace-nowrap ${xrColor}`}>
                          {xr != null ? xr.toFixed(2) : '—'}
                        </TableCell>
                        <TableCell>
                          <Button onClick={() => removeLine(line.id)} size="sm" variant="ghost" className="h-7 w-7 p-0">
                            <Trash className="w-3 h-3" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    )
                  }}
                />
            </TableCard>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
