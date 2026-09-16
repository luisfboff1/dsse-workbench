import { useCallback, useMemo, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Progress } from '@/components/ui/progress'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { TableCard } from '@/components/TableCard'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ChartContainer, ChartTooltip, ChartTooltipContent, ChartLegend, ChartLegendContent, type ChartConfig } from '@/components/ui/chart'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts'
import { ArrowsClockwise, CheckCircle, Lightning, Play, Warning, Table as TableIcon, ChartBar } from '@phosphor-icons/react'
import type { PowerFlowMethod, PowerFlowResult, Topology } from '@/lib/types'
import type { CompareRow } from '@/lib/api'
import { comparePowerFlow, runPowerFlow, saveScenario } from '@/lib/api'
import { MethodInfoBadge } from '@/components/MethodInfo'
import { getMethodInfo, POWERFLOW_METHODS, type MethodColorToken } from '@/lib/methodInfo'
import { checkRadial } from '@/lib/networkTopology'
import { CopyDataButton } from '@/components/CopyDataButton'
import { VirtualTableBody, RESULT_ROW_HEIGHT } from '@/components/VirtualTableBody'

// Classes literais completas, não interpoladas — ver DESIGN_SYSTEM.md.
const METHOD_TEXT_CLASS: Record<MethodColorToken, string> = {
  'method-ac': 'text-method-ac',
  'method-dc': 'text-method-dc',
  'method-ldf': 'text-method-ldf',
}
const METHOD_DOT_CLASS: Record<MethodColorToken, string> = {
  'method-ac': 'bg-method-ac',
  'method-dc': 'bg-method-dc',
  'method-ldf': 'bg-method-ldf',
}

// Bus Results, Branch Flows, and the comparison table all pass the same
// maxHeight to TableCard so they scroll the same way and never end up with
// mismatched heights.
const STICKY_HEAD = 'sticky top-0 z-10 bg-background'


const deltaVChartConfig = {
  'ΔV DC (%)': { label: 'ΔV DC (%)', color: 'var(--color-method-dc)' },
  'ΔV LDF (%)': { label: 'ΔV LDF (%)', color: 'var(--color-method-ldf)' },
} satisfies ChartConfig

// ChartTooltipContent's `formatter` fully replaces the row (indicator + name
// + value) when passed — returning just the formatted number, as a naive
// formatter does, silently drops the series name and leaves the tooltip
// showing bare numbers with no way to tell DC from LDF apart. Rebuild the
// same row layout the default renderer uses, indicator dot included.
function percentTooltipFormatter(value: unknown, name: unknown, item: { color?: string }) {
  return (
    <>
      <div
        className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
        style={{ backgroundColor: item.color }}
      />
      <div className="flex flex-1 items-center justify-between leading-none">
        <span className="text-muted-foreground">{String(name)}</span>
        <span className="text-foreground font-mono font-medium tabular-nums">
          {Number(value).toFixed(2)}%
        </span>
      </div>
    </>
  )
}

const deltaThetaChartConfig = {
  'Δθ DC (%)': { label: 'Δθ DC (%)', color: 'var(--color-method-dc)' },
  'Δθ LDF (%)': { label: 'Δθ LDF (%)', color: 'var(--color-method-ldf)' },
} satisfies ChartConfig

// mapeia o id do método -> chave usada na resposta de /powerflow/compare
const COMPARE_KEY: Record<PowerFlowMethod, 'ac' | 'dc' | 'ldf'> = {
  'pandapower-ac': 'ac',
  'pandapower-dc': 'dc',
  lindistflow: 'ldf',
}

// Formata número com segurança — evita que um método novo que não preencha
// todo campo (ex. Q gen no LinDistFlow) derrube a tela inteira com
// "Cannot read properties of undefined" sem error boundary por perto.
function fmt(n: number | null | undefined, decimals = 4): string {
  return typeof n === 'number' && Number.isFinite(n) ? n.toFixed(decimals) : '—'
}

interface PowerFlowTabProps {
  topology: Topology
}

function StatBox({ label, value, tone = 'default' }: { label: string; value: string; tone?: 'default' | 'ok' | 'warn' }) {
  const color = tone === 'ok' ? 'text-status-good' : tone === 'warn' ? 'text-destructive' : 'text-foreground'
  return (
    <div className="rounded-md border bg-card px-3 py-2">
      <div className="text-[10px] sm:text-xs text-muted-foreground">{label}</div>
      <div className={`mono mt-0.5 text-sm font-bold ${color}`}>{value}</div>
    </div>
  )
}

function voltageTone(v: number, min: number, max: number) {
  if (v < min) return 'text-status-info font-bold'
  if (v > max) return 'text-destructive font-bold'
  return 'text-status-good font-semibold'
}

export function PowerFlowTab({ topology }: PowerFlowTabProps) {
  const [method, setMethod] = useState<PowerFlowMethod>('pandapower-ac')
  const [maxIterations, setMaxIterations] = useState(50)
  const [tolerance, setTolerance] = useState(0.0001)
  const [vMin, setVMin] = useState(0.95)
  const [vMax, setVMax] = useState(1.05)
  const [isCalculating, setIsCalculating] = useState(false)
  const [result, setResult] = useState<(PowerFlowResult & { method?: string; algorithm?: string }) | null>(null)
  const [compareResult, setCompareResult] = useState<any>(null)
  // Qual método exibir em Bus Results / Branch Flows quando o resultado veio do Compare.
  const [viewMethod, setViewMethod] = useState<PowerFlowMethod>('pandapower-ac')
  const [error, setError] = useState<string | null>(null)
  const [scenarioName, setScenarioName] = useState(`${topology.name} power flow`)
  const [isSaving, setIsSaving] = useState(false)
  const [savedPath, setSavedPath] = useState<string | null>(null)

  const handleCalculate = async () => {
    setIsCalculating(true)
    setResult(null)
    setCompareResult(null)
    setError(null)
    try {
      const res = await runPowerFlow({ topology, method, maxIterations, tolerance })
      setResult(res)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setIsCalculating(false)
    }
  }

  const handleCompare = async () => {
    setIsCalculating(true)
    setResult(null)
    setCompareResult(null)
    setViewMethod('pandapower-ac')
    setError(null)
    try {
      const res = await comparePowerFlow(topology)
      setCompareResult(res)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setIsCalculating(false)
    }
  }

  const handleSaveScenario = async () => {
    if (!activeResult) return
    setIsSaving(true)
    setSavedPath(null)
    setError(null)
    try {
      const saved = await saveScenario({
        name: scenarioName.trim() || `${topology.name} power flow`,
        kind: 'powerflow',
        topology,
        settings: { method, maxIterations, tolerance, voltageLimits: { min: vMin, max: vMax } },
        result: activeResult as unknown as Record<string, unknown>,
      })
      setSavedPath(saved.path)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setIsSaving(false)
    }
  }

  // Annotated rather than inferred. Inferred, this came out as a union of two
  // structurally identical object types (the compare response types `ldf` as
  // `PowerFlowResult & { error?: string }`), which TypeScript does not collapse
  // — so `activeResult.buses` was a union of array types and generic inference
  // over it produced `unknown` at every call site that took the rows.
  const activeResult: (PowerFlowResult & { method?: PowerFlowMethod; error?: string }) | null = useMemo(() => {
    if (compareResult) {
      const data = compareResult[COMPARE_KEY[viewMethod]]
      return data ? { ...data, method: viewMethod } : null
    }
    return result
  }, [compareResult, result, viewMethod])

  // TableCard's Copy reads the rendered cells out of the DOM; with windowed
  // rows that is only a slice, so both tables hand it the full contents.
  const exportBusResults = useCallback(
    () => ({
      headers: ['Bus', '|V| pu', 'theta (deg)', 'P gen', 'Q gen', 'P load', 'Q load'],
      rows: (activeResult?.buses ?? []).map((bus) => [
        String(bus.id),
        fmt(bus.voltage, 4),
        fmt(bus.angle, 3),
        fmt(bus.pGen, 4),
        fmt(bus.qGen, 4),
        fmt(bus.pLoad, 4),
        fmt(bus.qLoad, 4),
      ]),
    }),
    [activeResult]
  )
  const exportLineResults = useCallback(
    () => ({
      headers: ['Line', 'From', 'To', 'P from', 'Q from', 'P to', 'Loss'],
      rows: (activeResult?.lines ?? []).map((line) => [
        `L${line.id}`,
        String(line.from ?? '-'),
        String(line.to ?? '-'),
        fmt(line.pFrom, 4),
        fmt(line.qFrom, 4),
        fmt(line.pTo, 4),
        fmt(line.loss, 5),
      ]),
    }),
    [activeResult]
  )

  const stats = useMemo(() => {
    if (!activeResult) return null
    // Loop rather than Math.min(...array): the spread form passes one argument
    // per element, which a big enough case turns into a stack overflow.
    let vLo = Infinity
    let vHi = -Infinity
    for (const bus of activeResult.buses) {
      if (bus.voltage < vLo) vLo = bus.voltage
      if (bus.voltage > vHi) vHi = bus.voltage
    }
    const totalLoss = activeResult.lines.reduce((sum, line) => sum + Math.abs(line.loss ?? 0), 0)
    const voltageViolations = activeResult.buses.filter((bus) => bus.voltage < vMin || bus.voltage > vMax)
    return {
      vRange: activeResult.buses.length ? `${vLo.toFixed(3)}-${vHi.toFixed(3)}` : '-',
      totalLoss,
      voltageViolations,
    }
  }, [activeResult, vMin, vMax])

  const compareChartData = useMemo(() => {
    const rows: CompareRow[] = compareResult?.comparison ?? []
    return rows.map((row) => ({
      name: String(row.busId),
      'ΔV DC (%)': row.dc_voltage_err_pct ?? null,
      'ΔV LDF (%)': row.ldf_voltage_err_pct ?? null,
      'Δθ DC (%)': row.dc_angle_err_pct ?? null,
      'Δθ LDF (%)': row.ldf_angle_err_pct ?? null,
    }))
  }, [compareResult])

  const methodLabel = getMethodInfo(method).shortLabel
  const radialCheck = checkRadial(topology)
  const isMeshed = radialCheck.status !== 'radial'

  // Same display values as the charts below, so what CopyDataButton exports
  // matches what's on screen (tables copy via TableCard, which reads the
  // rendered cells directly instead of needing this).
  const compareChartHeaders = ['Bus', 'ΔV DC (%)', 'ΔV LDF (%)', 'Δθ DC (%)', 'Δθ LDF (%)']
  const compareChartRows: (string | number)[][] = compareChartData.map((d) => [
    d.name, d['ΔV DC (%)'] ?? '—', d['ΔV LDF (%)'] ?? '—', d['Δθ DC (%)'] ?? '—', d['Δθ LDF (%)'] ?? '—',
  ])

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <p className="text-sm text-muted-foreground">
          AC, DC, and LinDistFlow compared on the active topology.
        </p>
        <Badge variant={isMeshed ? 'secondary' : 'outline'} className="mono w-fit">
          {radialCheck.status === 'radial' && 'radial: DistFlow recommended'}
          {radialCheck.status === 'meshed' && `meshed (${radialCheck.nLines} lines, ${radialCheck.nExpectedRadial} expected): DistFlow will fail`}
          {radialCheck.status === 'disconnected' && `too few lines (${radialCheck.nLines} of ${radialCheck.nExpectedRadial}): network may be disconnected`}
        </Badge>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[330px_1fr]">
        <aside className="space-y-4 xl:sticky xl:top-28 xl:self-start">
          <Card>
            <CardHeader className="px-4 py-4">
              <CardTitle className="text-base">Solver Configuration</CardTitle>
              <CardDescription className="text-xs">pandapower + backend Python</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 px-4 pb-4">
              <div className="space-y-2">
                <Label>Method</Label>
                <div className="flex items-center gap-2">
                  <Select value={method} onValueChange={(v) => setMethod(v as PowerFlowMethod)}>
                    <SelectTrigger className="flex-1 mono">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {POWERFLOW_METHODS.map((m) => (
                        <SelectItem key={m.id} value={m.id} className="mono">
                          <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${METHOD_DOT_CLASS[m.color]}`} />
                          {m.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <MethodInfoBadge methodId={method} />
                </div>
                <p className="text-xs text-muted-foreground">{getMethodInfo(method).tagline}</p>
              </div>

              <Separator />

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>Max iterations</Label>
                  <Input
                    type="number"
                    value={maxIterations}
                    onChange={(e) => setMaxIterations(parseInt(e.target.value))}
                    min={1}
                    max={500}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Tolerance</Label>
                  <Input
                    type="number"
                    value={tolerance}
                    onChange={(e) => setTolerance(parseFloat(e.target.value))}
                    step={0.00001}
                    min={1e-7}
                  />
                </div>
              </div>

              <div className="rounded-md border bg-muted/30 p-3">
                <div className="mono mb-2 text-xs font-bold text-primary">Voltage limits</div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label className="text-xs">V min</Label>
                    <Input type="number" value={vMin} onChange={(e) => setVMin(parseFloat(e.target.value))} step={0.01} />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">V max</Label>
                    <Input type="number" value={vMax} onChange={(e) => setVMax(parseFloat(e.target.value))} step={0.01} />
                  </div>
                </div>
              </div>

              <Button onClick={handleCalculate} disabled={isCalculating} className="w-full" size="lg">
                {isCalculating ? 'Running...' : <><Play className="mr-2" weight="fill" />Run {methodLabel}</>}
              </Button>
              <Button onClick={handleCompare} disabled={isCalculating} variant="outline" className="w-full">
                {isCalculating ? 'Comparing...' : <><ArrowsClockwise className="mr-2" />Compare AC/DC/LinDist</>}
              </Button>
              {isCalculating && <Progress value={50} className="w-full animate-pulse" />}

              {activeResult && (
                <>
                  <Separator />
                  <div className="space-y-2">
                    <Label>Scenario name</Label>
                    <Input value={scenarioName} onChange={(e) => setScenarioName(e.target.value)} />
                    <Button onClick={handleSaveScenario} disabled={isSaving} variant="secondary" className="w-full">
                      {isSaving ? 'Saving...' : 'Save Power Flow Scenario'}
                    </Button>
                    {savedPath && (
                      <p className="mono text-[10px] text-muted-foreground break-all">
                        Saved at {savedPath}
                      </p>
                    )}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </aside>

        <div className="space-y-4 min-w-0">
          {error && (
            <Alert variant="destructive">
              <Warning weight="fill" />
              <AlertDescription className="mono text-xs break-all">{error}</AlertDescription>
            </Alert>
          )}

          {activeResult && stats ? (
            <section className="grid grid-cols-2 gap-2 md:grid-cols-6">
              <StatBox label="Status" value={activeResult.converged ? 'Converged' : 'Diverged'} tone={activeResult.converged ? 'ok' : 'warn'} />
              <StatBox label="Iterations" value={String(activeResult.iterations ?? '-')} />
              <StatBox label="Exec time" value={`${activeResult.executionTime.toFixed(1)} ms`} />
              <StatBox label="Active losses" value={`${stats.totalLoss.toFixed(4)} pu`} />
              <StatBox label="|V| range" value={`${stats.vRange} pu`} />
              <StatBox label="Violations" value={String(stats.voltageViolations.length)} tone={stats.voltageViolations.length ? 'warn' : 'ok'} />
            </section>
          ) : (
            <div className="rounded-md border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
              Configure the solver and run a power flow to see metrics, overlay, and tables.
            </div>
          )}

          {compareResult && (
            <Card>
              <CardHeader className="px-4 py-4">
                <CardTitle className="text-base flex items-center gap-2">
                  <Lightning weight="fill" className="text-accent" />
                  AC vs DC vs LinDistFlow
                </CardTitle>
                <CardDescription className="text-xs">
                  Errors are computed against AC. LinDistFlow may fail on meshed networks.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 px-4 pb-4">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {[
                    { label: 'AC ground truth', data: compareResult.ac, methodId: 'pandapower-ac' as const, color: 'text-method-ac' },
                    { label: 'DC linear', data: compareResult.dc, methodId: 'pandapower-dc' as const, color: 'text-method-dc' },
                    { label: 'LinDistFlow', data: compareResult.ldf, methodId: 'lindistflow' as const, color: 'text-method-ldf' },
                  ].map(({ label, data, methodId, color }) => (
                    <div key={label} className="rounded-md border bg-card px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <span className={`text-xs font-bold ${color}`}>{label}</span>
                        <MethodInfoBadge methodId={methodId} />
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <Badge variant={data?.converged ? 'default' : 'destructive'} className="text-[10px]">
                          {data?.converged ? 'OK' : 'Fail'}
                        </Badge>
                        {data?.algorithm && <span className="mono text-[10px] text-muted-foreground">{data.algorithm}</span>}
                        <span className="mono text-[10px] text-muted-foreground">{data?.executionTime?.toFixed?.(1) ?? '-'} ms</span>
                      </div>
                    </div>
                  ))}
                </div>

                {compareResult.ldf_error && (
                  <Alert variant="destructive">
                    <Warning weight="fill" />
                    <AlertDescription className="mono text-xs">LinDistFlow: {compareResult.ldf_error}</AlertDescription>
                  </Alert>
                )}

                <Tabs defaultValue="table">
                  <TabsList>
                    <TabsTrigger value="table" className="text-xs">
                      <TableIcon className="w-3.5 h-3.5" /> Table
                    </TabsTrigger>
                    <TabsTrigger value="charts" className="text-xs">
                      <ChartBar className="w-3.5 h-3.5" /> Charts
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="table">
                    <TableCard label="AC vs DC vs LinDistFlow" maxHeight="420px">
                        <TableHeader>
                          <TableRow>
                            <TableHead className={`mono text-xs sticky left-0 ${STICKY_HEAD}`}>Bus</TableHead>
                            <TableHead className={`mono text-right text-xs text-method-ac ${STICKY_HEAD}`}>V AC</TableHead>
                            <TableHead className={`mono text-right text-xs text-method-dc ${STICKY_HEAD}`}>V DC</TableHead>
                            <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>ΔV DC (%)</TableHead>
                            <TableHead className={`mono text-right text-xs text-method-ldf ${STICKY_HEAD}`}>V LDF</TableHead>
                            <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>ΔV LDF (%)</TableHead>
                            <TableHead className={`mono text-right text-xs text-method-ac ${STICKY_HEAD}`}>θ AC</TableHead>
                            <TableHead className={`mono text-right text-xs text-method-dc ${STICKY_HEAD}`}>θ DC</TableHead>
                            <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>Δθ DC (%)</TableHead>
                            <TableHead className={`mono text-right text-xs text-method-ldf ${STICKY_HEAD}`}>θ LDF</TableHead>
                            <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>Δθ LDF (%)</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {compareResult.comparison?.map((row: CompareRow) => (
                            <TableRow key={row.busId}>
                              <TableCell className="font-medium text-xs sticky left-0 bg-background">{row.busId}</TableCell>
                              <TableCell className="text-right mono text-xs">{row.ac_voltage?.toFixed(4) ?? '-'}</TableCell>
                              <TableCell className="text-right mono text-xs">{row.dc_voltage?.toFixed(4) ?? '-'}</TableCell>
                              <TableCell className={`text-right mono text-xs ${(row.dc_voltage_err_pct ?? 0) > 1 ? 'text-destructive font-bold' : 'text-muted-foreground'}`}>
                                {row.dc_voltage_err_pct != null ? `${row.dc_voltage_err_pct.toFixed(2)}%` : '-'}
                              </TableCell>
                              <TableCell className="text-right mono text-xs">{row.ldf_voltage?.toFixed(4) ?? '-'}</TableCell>
                              <TableCell className={`text-right mono text-xs ${(row.ldf_voltage_err_pct ?? 0) > 1 ? 'text-destructive font-bold' : 'text-muted-foreground'}`}>
                                {row.ldf_voltage_err_pct != null ? `${row.ldf_voltage_err_pct.toFixed(2)}%` : '-'}
                              </TableCell>
                              <TableCell className="text-right mono text-xs">{row.ac_angle?.toFixed(3) ?? '-'}</TableCell>
                              <TableCell className="text-right mono text-xs">{row.dc_angle?.toFixed(3) ?? '-'}</TableCell>
                              <TableCell className={`text-right mono text-xs ${(row.dc_angle_err_pct ?? 0) > 10 ? 'text-destructive font-bold' : 'text-muted-foreground'}`}>
                                {row.dc_angle_err_pct != null ? `${row.dc_angle_err_pct.toFixed(2)}%` : '-'}
                              </TableCell>
                              <TableCell className="text-right mono text-xs">{row.ldf_angle?.toFixed(3) ?? '-'}</TableCell>
                              <TableCell className={`text-right mono text-xs ${(row.ldf_angle_err_pct ?? 0) > 10 ? 'text-destructive font-bold' : 'text-muted-foreground'}`}>
                                {row.ldf_angle_err_pct != null ? `${row.ldf_angle_err_pct.toFixed(2)}%` : '-'}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                    </TableCard>
                  </TabsContent>

                  <TabsContent value="charts" className="space-y-4">
                    <div>
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <p className="mono text-xs text-muted-foreground">
                          ΔV vs AC, by bus — separate axes: DC error is typically much larger than LDF
                        </p>
                        <CopyDataButton headers={compareChartHeaders} rows={compareChartRows} label="ΔV/Δθ vs AC" className="shrink-0" />
                      </div>
                      <ChartContainer config={deltaVChartConfig} className="aspect-auto h-52 w-full">
                        <BarChart data={compareChartData} margin={{ top: 5, right: 5, left: -15, bottom: 5 }}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                          <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                          <YAxis yAxisId="dc" tick={{ fontSize: 10, fill: 'var(--color-method-dc)' }} unit="%" />
                          <YAxis yAxisId="ldf" orientation="right" tick={{ fontSize: 10, fill: 'var(--color-method-ldf)' }} unit="%" />
                          <ChartTooltip content={<ChartTooltipContent formatter={percentTooltipFormatter} />} />
                          <ChartLegend content={<ChartLegendContent />} />
                          <Bar yAxisId="dc" dataKey="ΔV DC (%)" fill="var(--color-method-dc)" radius={[2, 2, 0, 0]} />
                          <Bar yAxisId="ldf" dataKey="ΔV LDF (%)" fill="var(--color-method-ldf)" radius={[2, 2, 0, 0]} />
                        </BarChart>
                      </ChartContainer>
                    </div>
                    <div>
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <p className="mono text-xs text-muted-foreground">
                          Δθ vs AC, by bus — separate axes: DC error blows up near the slack angle (≈0°)
                        </p>
                        <CopyDataButton headers={compareChartHeaders} rows={compareChartRows} label="ΔV/Δθ vs AC" className="shrink-0" />
                      </div>
                      <ChartContainer config={deltaThetaChartConfig} className="aspect-auto h-52 w-full">
                        <BarChart data={compareChartData} margin={{ top: 5, right: 5, left: -15, bottom: 5 }}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                          <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                          <YAxis yAxisId="dc" tick={{ fontSize: 10, fill: 'var(--color-method-dc)' }} unit="%" />
                          <YAxis yAxisId="ldf" orientation="right" tick={{ fontSize: 10, fill: 'var(--color-method-ldf)' }} unit="%" />
                          <ChartTooltip content={<ChartTooltipContent formatter={percentTooltipFormatter} />} />
                          <ChartLegend content={<ChartLegendContent />} />
                          <Bar yAxisId="dc" dataKey="Δθ DC (%)" fill="var(--color-method-dc)" radius={[2, 2, 0, 0]} />
                          <Bar yAxisId="ldf" dataKey="Δθ LDF (%)" fill="var(--color-method-ldf)" radius={[2, 2, 0, 0]} />
                        </BarChart>
                      </ChartContainer>
                    </div>
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>
          )}

          {activeResult && (
            <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_0.9fr]">
              {compareResult && (
                <div className="xl:col-span-2 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-muted-foreground">Showing results for:</span>
                  {POWERFLOW_METHODS.map((m) => {
                    const data = compareResult[COMPARE_KEY[m.id]]
                    const isActive = viewMethod === m.id
                    return (
                      <Button
                        key={m.id}
                        type="button"
                        size="sm"
                        variant={isActive ? 'default' : 'outline'}
                        disabled={!data}
                        onClick={() => setViewMethod(m.id)}
                        className="h-7 mono text-xs"
                      >
                        <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${isActive ? '' : METHOD_DOT_CLASS[m.color]}`} />
                        {m.shortLabel}
                      </Button>
                    )
                  })}
                </div>
              )}
              <Card>
                <CardHeader className="px-4 py-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <CardTitle className="text-base flex items-center gap-2">
                        Bus Results
                        {compareResult && (
                          <span className={`mono text-xs font-normal ${METHOD_TEXT_CLASS[getMethodInfo(viewMethod).color]}`}>
                            — {getMethodInfo(viewMethod).label}
                          </span>
                        )}
                      </CardTitle>
                      <CardDescription className="text-xs">Voltages and power balance by bus</CardDescription>
                    </div>
                    <Badge variant={activeResult.converged ? 'default' : 'destructive'}>
                      {activeResult.converged ? <><CheckCircle className="mr-1 w-3 h-3" weight="fill" />OK</> : 'Fail'}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="px-4 pb-4">
                  <TableCard
                    label="Bus Results"
                    maxHeight="420px"
                    expandedMaxHeight="80vh"
                    exportData={exportBusResults}
                  >
                      <TableHeader>
                        <TableRow>
                          <TableHead className={`mono text-xs ${STICKY_HEAD}`}>Bus</TableHead>
                          <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>|V| pu</TableHead>
                          <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>θ (deg)</TableHead>
                          <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>P gen</TableHead>
                          <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>Q gen</TableHead>
                          <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>P load</TableHead>
                          <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>Q load</TableHead>
                        </TableRow>
                      </TableHeader>
                      {/* Windowed: one row per bus is thousands of rows on a
                          real feeder. See VirtualTableBody. */}
                      <VirtualTableBody
                        items={activeResult.buses}
                        renderRow={(bus) => (
                          <TableRow key={bus.id} style={{ height: RESULT_ROW_HEIGHT }} className={bus.voltage < vMin || bus.voltage > vMax ? 'bg-destructive/5' : ''}>
                            <TableCell className="font-medium text-xs">{bus.id}</TableCell>
                            <TableCell className={`text-right mono text-xs ${voltageTone(bus.voltage, vMin, vMax)}`}>{fmt(bus.voltage, 4)}</TableCell>
                            <TableCell className="text-right mono text-xs">{fmt(bus.angle, 3)}</TableCell>
                            <TableCell className="text-right mono text-xs">{fmt(bus.pGen, 4)}</TableCell>
                            <TableCell className="text-right mono text-xs">{fmt(bus.qGen, 4)}</TableCell>
                            <TableCell className="text-right mono text-xs">{fmt(bus.pLoad, 4)}</TableCell>
                            <TableCell className="text-right mono text-xs">{fmt(bus.qLoad, 4)}</TableCell>
                          </TableRow>
                        )}
                      />
                  </TableCard>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="px-4 py-4">
                  <CardTitle className="text-base flex items-center gap-2">
                    Branch Flows
                    {compareResult && (
                      <span className={`mono text-xs font-normal ${METHOD_TEXT_CLASS[getMethodInfo(viewMethod).color]}`}>
                        — {getMethodInfo(viewMethod).label}
                      </span>
                    )}
                  </CardTitle>
                  <CardDescription className="text-xs">Branch flows and active losses</CardDescription>
                </CardHeader>
                <CardContent className="px-4 pb-4">
                  <TableCard
                    label="Branch Flows"
                    maxHeight="420px"
                    expandedMaxHeight="80vh"
                    exportData={exportLineResults}
                  >
                      <TableHeader>
                        <TableRow>
                          <TableHead className={`mono text-xs ${STICKY_HEAD}`}>Line</TableHead>
                          <TableHead className={`mono text-xs ${STICKY_HEAD}`}>From</TableHead>
                          <TableHead className={`mono text-xs ${STICKY_HEAD}`}>To</TableHead>
                          <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>P from</TableHead>
                          <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>Q from</TableHead>
                          <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>P to</TableHead>
                          <TableHead className={`mono text-right text-xs ${STICKY_HEAD}`}>Loss</TableHead>
                        </TableRow>
                      </TableHeader>
                      {/* Windowed — same reasoning as Bus Results above. */}
                      <VirtualTableBody
                        items={activeResult.lines}
                        renderRow={(line) => (
                          <TableRow key={line.id} style={{ height: RESULT_ROW_HEIGHT }}>
                            <TableCell className="font-medium text-xs">L{line.id}</TableCell>
                            <TableCell className="mono text-xs">{line.from ?? '-'}</TableCell>
                            <TableCell className="mono text-xs">{line.to ?? '-'}</TableCell>
                            <TableCell className="text-right mono text-xs">{fmt(line.pFrom, 4)}</TableCell>
                            <TableCell className="text-right mono text-xs">{fmt(line.qFrom, 4)}</TableCell>
                            <TableCell className="text-right mono text-xs">{fmt(line.pTo, 4)}</TableCell>
                            <TableCell className="text-right mono text-xs">{fmt(line.loss, 5)}</TableCell>
                          </TableRow>
                        )}
                      />
                  </TableCard>
                </CardContent>
              </Card>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
