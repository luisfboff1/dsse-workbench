/**
 * WorkbenchTab - block-diagram simulation panel.
 * Runs multiple blocks in sequence and compares results side by side.
 */
import { useMemo, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Play, CheckCircle, Warning, Spinner, ArrowRight, Table as TableIcon, ChartBar } from '@phosphor-icons/react'
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { TableCard } from '@/components/TableCard'
import { VirtualTableBody, RESULT_ROW_HEIGHT } from '@/components/VirtualTableBody'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ReferenceLine } from 'recharts'
import { ChartContainer, ChartTooltip, ChartTooltipContent, ChartLegend, ChartLegendContent, type ChartConfig } from '@/components/ui/chart'
import type { Topology } from '@/lib/types'

const angleCompareChartConfig = {
  'θ AC': { label: 'θ AC', color: 'var(--color-method-ac)' },
  'θ DC': { label: 'θ DC', color: 'var(--color-method-dc)' },
} satisfies ChartConfig

const wlsResidualChartConfig = {
  residual_normalized: { label: '|r_N|', color: 'var(--color-accent)' },
} satisfies ChartConfig
import {
  runPowerFlow,
  runEstimation,
  runBadDataDetection,
  type EstimationResult,
  type BadDataResult,
} from '@/lib/api'

interface WorkbenchTabProps {
  topology: Topology
}

type BlockStatus = 'idle' | 'running' | 'done' | 'error'

interface BlockState<T> {
  status: BlockStatus
  result?: T
  error?: string
  elapsed?: number
}

const DETECTION_COMBOS = [
  { label: 'Residual + LNR + Remove', detection: 'residual', identification: 'lnr', correction: 'remove' },
  { label: 'Residual + LNR + Correct (z_true)', detection: 'residual', identification: 'lnr', correction: 'ztrue' },
  { label: 'Residual + CME + Remove', detection: 'residual', identification: 'cme', correction: 'remove' },
  { label: 'CME + LNR + Remove', detection: 'cme', identification: 'lnr', correction: 'remove' },
  { label: 'CME + CME + Remove', detection: 'cme', identification: 'cme', correction: 'remove' },
  { label: 'CME + CME + Correct (z_true)', detection: 'cme', identification: 'cme', correction: 'ztrue' },
]

function BlockCard({ title, description, status, onRun, disabled, children }: {
  title: string
  description: string
  status: BlockStatus
  onRun: () => void
  disabled?: boolean
  children?: React.ReactNode
}) {
  const statusColor = {
    idle: 'border-muted',
    running: 'border-accent animate-pulse',
    done: 'border-status-good/50',
    error: 'border-destructive/50',
  }[status]

  return (
    <Card className={`border-2 ${statusColor} transition-colors`}>
      <CardHeader className="p-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <CardTitle className="text-sm">{title}</CardTitle>
            <CardDescription className="text-xs mt-0.5">{description}</CardDescription>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {status === 'done' && <CheckCircle weight="fill" className="text-status-good w-4 h-4" />}
            {status === 'error' && <Warning weight="fill" className="text-destructive w-4 h-4" />}
            {status === 'running' && <Spinner className="animate-spin w-4 h-4 text-accent" />}
            <Button size="sm" onClick={onRun} disabled={disabled || status === 'running'} variant="outline">
              <Play weight="fill" className="w-3 h-3 mr-1" />Run
            </Button>
          </div>
        </div>
      </CardHeader>
      {children && <CardContent className="px-4 pb-4 pt-0">{children}</CardContent>}
    </Card>
  )
}

/** Most bars the AC-vs-DC comparison chart will draw; see comparisonData. */
const MAX_COMPARISON_BARS = 300

/** How far apart the two methods put this bus, for picking which bars to keep. */
function angleGap(row: { 'θ AC': number | null; 'θ DC': number | null }): number {
  const ac = row['θ AC']
  const dc = row['θ DC']
  return ac == null || dc == null ? -1 : Math.abs(ac - dc)
}

export function WorkbenchTab({ topology }: WorkbenchTabProps) {
  // Shared settings
  const [noiseLevel, setNoiseLevel] = useState(0.01)
  const [badDataMag, setBadDataMag] = useState(5.0)
  const [seed, setSeed] = useState('42')
  const [selectedCombo, setSelectedCombo] = useState('0')

  // Block states
  const [acFlow, setAcFlow] = useState<BlockState<any>>({ status: 'idle' })
  const [dcFlow, setDcFlow] = useState<BlockState<any>>({ status: 'idle' })
  const [wls, setWls] = useState<BlockState<EstimationResult>>({ status: 'idle' })
  const [badData, setBadData] = useState<BlockState<BadDataResult>>({ status: 'idle' })
  const [allCombos, setAllCombos] = useState<BlockState<BadDataResult[]>>({ status: 'idle' })

  const seedNum = seed.trim() !== '' ? parseInt(seed) : null

  // ── Runners ──────────────────────────────────────────────────────────────

  async function runAC() {
    setAcFlow({ status: 'running' })
    try {
      const t0 = performance.now()
      const res = await runPowerFlow({ topology, method: 'pandapower-ac' })
      setAcFlow({ status: 'done', result: res, elapsed: performance.now() - t0 })
    } catch (e: any) {
      setAcFlow({ status: 'error', error: e.message })
    }
  }

  async function runDC() {
    setDcFlow({ status: 'running' })
    try {
      const t0 = performance.now()
      const res = await runPowerFlow({ topology, method: 'pandapower-dc' })
      setDcFlow({ status: 'done', result: res, elapsed: performance.now() - t0 })
    } catch (e: any) {
      setDcFlow({ status: 'error', error: e.message })
    }
  }

  async function runWLS() {
    setWls({ status: 'running' })
    try {
      const t0 = performance.now()
      const res = await runEstimation({ topology, noise_level: noiseLevel, seed: seedNum })
      setWls({ status: 'done', result: res, elapsed: performance.now() - t0 })
    } catch (e: any) {
      setWls({ status: 'error', error: e.message })
    }
  }

  async function runBadData() {
    setBadData({ status: 'running' })
    const combo = DETECTION_COMBOS[parseInt(selectedCombo)]
    try {
      const t0 = performance.now()
      const res = await runBadDataDetection({
        topology,
        noise_level: noiseLevel,
        seed: seedNum,
        inject_bad_data: true,
        bad_data_magnitude: badDataMag,
        detection: combo.detection as any,
        identification: combo.identification as any,
        correction: combo.correction as any,
      })
      setBadData({ status: 'done', result: res, elapsed: performance.now() - t0 })
    } catch (e: any) {
      setBadData({ status: 'error', error: e.message })
    }
  }

  async function runAllCombos() {
    setAllCombos({ status: 'running' })
    try {
      const t0 = performance.now()
      const results = await Promise.all(
        DETECTION_COMBOS.map((combo) =>
          runBadDataDetection({
            topology,
            noise_level: noiseLevel,
            seed: seedNum,
            inject_bad_data: true,
            bad_data_magnitude: badDataMag,
            detection: combo.detection as any,
            identification: combo.identification as any,
            correction: combo.correction as any,
          })
        )
      )
      setAllCombos({ status: 'done', result: results, elapsed: performance.now() - t0 })
    } catch (e: any) {
      setAllCombos({ status: 'error', error: e.message })
    }
  }

  async function runAll() {
    await Promise.all([runAC(), runDC(), runWLS()])
  }

  // ── Render ────────────────────────────────────────────────────────────────

  const hasCompare = acFlow.status === 'done' && dcFlow.status === 'done'
  const acBuses: Record<number, any> = {}
  const dcBuses: Record<number, any> = {}
  if (acFlow.result?.buses) acFlow.result.buses.forEach((b: any) => (acBuses[b.id] = b))
  if (dcFlow.result?.buses) dcFlow.result.buses.forEach((b: any) => (dcBuses[b.id] = b))

  // Capped: Recharts draws one element per bar per series, and past a few
  // hundred bars in a chart this wide each one is sub-pixel anyway. The
  // interesting buses for an AC-vs-DC comparison are the ones where the two
  // disagree most, so that is what survives the cut — then put back in bus
  // order so the x-axis still reads as "by bus".
  const comparisonData = useMemo(() => {
    const rows = topology.buses.map((b, order) => ({
      order,
      name: `B${b.id}`,
      'θ AC': acBuses[b.id]?.angle ?? null,
      'θ DC': dcBuses[b.id]?.angle ?? null,
      '|V AC|': acBuses[b.id]?.voltage ?? null,
    }))
    if (rows.length <= MAX_COMPARISON_BARS) return rows
    return rows
      .slice()
      .sort((a, b) => angleGap(b) - angleGap(a))
      .slice(0, MAX_COMPARISON_BARS)
      .sort((a, b) => a.order - b.order)
  }, [topology.buses, acFlow.result, dcFlow.result])

  return (
    <div className="space-y-4">
      {/* Header + shared config */}
      <Card>
        <CardHeader className="p-4 pb-0">
          <CardTitle className="text-base flex items-center gap-2">
            <TableIcon weight="fill" className="text-accent" />
            Simulation Workbench — Block Diagram
          </CardTitle>
          <CardDescription className="text-xs">
            Run blocks independently or in sequence. Compare AC, DC, WLS, and Bad Data side by side.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="space-y-1">
              <Label className="text-xs">Noise σ (rel.)</Label>
              <Input type="number" value={noiseLevel} step={0.005} min={0.001} max={0.5}
                onChange={(e) => setNoiseLevel(parseFloat(e.target.value))} className="h-8 text-xs" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Bad Data Magnitude (×σ)</Label>
              <Input type="number" value={badDataMag} step={1} min={1}
                onChange={(e) => setBadDataMag(parseFloat(e.target.value))} className="h-8 text-xs" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Seed</Label>
              <Input value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="42" className="h-8 text-xs" />
            </div>
            <div className="flex items-end">
              <Button onClick={runAll} size="sm" className="w-full">
                <Play weight="fill" className="mr-1 w-3 h-3" />Run AC + DC + WLS
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Block row 1: Power Flow */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <BlockCard title="Pandapower AC (Newton-Raphson)" description="Power flow AC completo com controle Q"
          status={acFlow.status} onRun={runAC}>
          {acFlow.error && <p className="text-xs text-destructive mono">{acFlow.error}</p>}
          {acFlow.result && (
            <div className="grid grid-cols-3 gap-2 text-xs mono">
              <div><span className="text-muted-foreground">Status </span>
                <Badge variant={acFlow.result.converged ? 'default' : 'destructive'} className="text-[10px]">
                  {acFlow.result.converged ? 'OK' : 'FAIL'}
                </Badge>
              </div>
              <div><span className="text-muted-foreground">Time </span>{acFlow.result.executionTime?.toFixed(1)} ms</div>
              <div><span className="text-muted-foreground">Buses </span>{acFlow.result.buses?.length}</div>
            </div>
          )}
        </BlockCard>

        <BlockCard title="Pandapower DC (linear)" description="Linear DC power flow - angles only"
          status={dcFlow.status} onRun={runDC}>
          {dcFlow.error && <p className="text-xs text-destructive mono">{dcFlow.error}</p>}
          {dcFlow.result && (
            <div className="grid grid-cols-3 gap-2 text-xs mono">
              <div><span className="text-muted-foreground">Status </span>
                <Badge variant="default" className="text-[10px]">OK</Badge>
              </div>
              <div><span className="text-muted-foreground">Time </span>{dcFlow.result.executionTime?.toFixed(1)} ms</div>
              <div><span className="text-muted-foreground">Buses </span>{dcFlow.result.buses?.length}</div>
            </div>
          )}
        </BlockCard>
      </div>

      {/* AC vs DC comparison chart */}
      {hasCompare && (
        <Card>
          <CardHeader className="p-4 pb-0">
            <CardTitle className="text-sm flex items-center gap-2">
              <ChartBar weight="fill" className="text-accent" />
              AC vs DC Angle Comparison
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            <ChartContainer config={angleCompareChartConfig} className="aspect-auto h-52 w-full">
              <BarChart data={comparisonData} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} unit="°" />
                <ChartTooltip content={<ChartTooltipContent formatter={(v) => `${Number(v).toFixed(3)}°`} />} />
                <ChartLegend content={<ChartLegendContent />} />
                <Bar dataKey="θ AC" fill="var(--color-method-ac)" radius={[2, 2, 0, 0]} />
                <Bar dataKey="θ DC" fill="var(--color-method-dc)" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ChartContainer>
            <div className="mt-3">
              <TableCard
                label="AC vs DC Angle Comparison"
                maxHeight="16rem"
                expandedMaxHeight="80vh"
                exportData={() => ({
                  headers: ['Bus', 'theta AC (deg)', 'theta DC (deg)', '|d theta| (deg)', 'V AC (pu)'],
                  rows: topology.buses.map((b) => {
                    const ac = acBuses[b.id]
                    const dc = dcBuses[b.id]
                    const diff = ac && dc ? Math.abs(ac.angle - dc.angle) : null
                    return [
                      `${b.id} - ${b.name}`,
                      ac?.angle?.toFixed(3) ?? '',
                      dc?.angle?.toFixed(3) ?? '',
                      diff?.toFixed(4) ?? '',
                      ac?.voltage?.toFixed(4) ?? '',
                    ]
                  }),
                })}
              >
                <TableHeader>
                  <TableRow>
                    <TableHead className="mono text-xs">Bus</TableHead>
                    <TableHead className="mono text-right text-xs">θ AC (°)</TableHead>
                    <TableHead className="mono text-right text-xs">θ DC (°)</TableHead>
                    <TableHead className="mono text-right text-xs">|Δθ| (°)</TableHead>
                    <TableHead className="mono text-right text-xs">V AC (pu)</TableHead>
                  </TableRow>
                </TableHeader>
                <VirtualTableBody
                  items={topology.buses}
                  renderRow={(b) => {
                    const ac = acBuses[b.id]
                    const dc = dcBuses[b.id]
                    const diff = ac && dc ? Math.abs(ac.angle - dc.angle) : null
                    return (
                      <TableRow key={b.id} style={{ height: RESULT_ROW_HEIGHT }} className={diff && diff > 1.0 ? 'bg-destructive/5' : ''}>
                        <TableCell className="text-xs font-medium">{b.id} — {b.name}</TableCell>
                        <TableCell className="text-right mono text-xs">{ac?.angle?.toFixed(3) ?? '—'}</TableCell>
                        <TableCell className="text-right mono text-xs">{dc?.angle?.toFixed(3) ?? '—'}</TableCell>
                        <TableCell className={`text-right mono text-xs ${diff && diff > 1.0 ? 'text-destructive font-bold' : ''}`}>
                          {diff?.toFixed(4) ?? '—'}
                        </TableCell>
                        <TableCell className="text-right mono text-xs">{ac?.voltage?.toFixed(4) ?? '—'}</TableCell>
                      </TableRow>
                    )
                  }}
                />
              </TableCard>
            </div>
          </CardContent>
        </Card>
      )}

      <Separator />

      {/* Block row 2: State Estimation */}
      <BlockCard title="WLS DC State Estimation" description="Gauss-Newton WLS with simulated Gaussian noise"
        status={wls.status} onRun={runWLS}>
        {wls.error && <Alert variant="destructive"><AlertDescription className="text-xs">{wls.error}</AlertDescription></Alert>}
        {wls.result && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs mono">
              <div><span className="text-muted-foreground">J = </span>
                <span className="font-bold">{wls.result.J.toFixed(3)}</span>
              </div>
              <div><span className="text-muted-foreground">DoF = </span>{wls.result.dof}</div>
              <div><span className="text-muted-foreground">m = </span>{wls.result.nMeasurements}</div>
              <div><span className="text-muted-foreground">Time </span>{wls.result.executionTime.toFixed(1)} ms</div>
            </div>
            <ChartContainer config={wlsResidualChartConfig} className="aspect-auto h-36 w-full">
              <BarChart data={wls.result.residuals} margin={{ top: 3, right: 5, left: -25, bottom: 30 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                <XAxis dataKey="label" tick={{ fontSize: 8 }} angle={-35} textAnchor="end" height={40} />
                <YAxis tick={{ fontSize: 8 }} />
                <ChartTooltip content={<ChartTooltipContent formatter={(v) => Number(v).toFixed(3)} />} />
                <ReferenceLine y={3} stroke="var(--color-destructive)" strokeDasharray="3 2" />
                <Bar dataKey="residual_normalized" fill="var(--color-accent)" radius={[2,2,0,0]} />
              </BarChart>
            </ChartContainer>
          </div>
        )}
      </BlockCard>

      <Separator />

      {/* Block row 3: Bad Data */}
      <Card className={`border-2 transition-colors ${badData.status === 'done' ? 'border-status-warn/50' : badData.status === 'error' ? 'border-destructive/50' : 'border-muted'}`}>
        <CardHeader className="p-4 pb-2">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div>
              <CardTitle className="text-sm">Bad Data Detection Pipeline</CardTitle>
              <CardDescription className="text-xs">Detection + Identification + Correction (Bretas 2013/2018)</CardDescription>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <Select value={selectedCombo} onValueChange={setSelectedCombo}>
                <SelectTrigger className="h-8 text-xs w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DETECTION_COMBOS.map((c, i) => (
                    <SelectItem key={i} value={String(i)} className="text-xs">{c.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button size="sm" onClick={runBadData} disabled={badData.status === 'running'} variant="outline">
                <Play weight="fill" className="w-3 h-3 mr-1" />Run
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-4 pt-2">
          {badData.error && <Alert variant="destructive"><AlertDescription className="text-xs">{badData.error}</AlertDescription></Alert>}
          {badData.result && (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-3 text-xs mono">
                <span>J_final = <strong>{badData.result.pipeline.J_final.toFixed(3)}</strong></span>
                <span>threshold = <strong>{badData.result.pipeline.threshold.toFixed(3)}</strong></span>
                <Badge variant={badData.result.pipeline.detected ? 'destructive' : 'default'} className="text-[10px]">
                  {badData.result.pipeline.detected ? 'Bad Data DETECTED' : 'Clean'}
                </Badge>
                <span>Flagged idx: <strong>{badData.result.pipeline.flaggedIndices.join(', ') || '—'}</strong></span>
                <span>Action: <strong>{badData.result.pipeline.actions.join(', ') || '—'}</strong></span>
              </div>

              <TableCard
                label="Bad Data Detection Pipeline"
                maxHeight="14rem"
                expandedMaxHeight="80vh"
                exportData={() => ({
                  headers: ['Label', 'z', 'r', '|r_N|', '|CME_N|', 'UI', 'Status'],
                  rows: badData.result!.measurements.map((m) => [
                    m.label, m.z_noisy.toFixed(4), m.residual.toFixed(4),
                    Math.abs(m.r_N).toFixed(2), Math.abs(m.CME_N).toFixed(2), m.UI.toFixed(3),
                    [m.isBadData ? 'injected' : '', m.isFlagged ? 'flagged' : ''].filter(Boolean).join(' '),
                  ]),
                })}
              >
                  <TableHeader>
                    <TableRow>
                      <TableHead className="mono text-xs">Meas.</TableHead>
                      <TableHead className="mono text-right text-xs">z_noisy</TableHead>
                      <TableHead className="mono text-right text-xs">r</TableHead>
                      <TableHead className="mono text-right text-xs">|r_N|</TableHead>
                      <TableHead className="mono text-right text-xs">|CME_N|</TableHead>
                      <TableHead className="mono text-right text-xs">UI</TableHead>
                      <TableHead className="mono text-xs">Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <VirtualTableBody
                    items={badData.result.measurements}
                    renderRow={(m) => (
                      <TableRow key={m.idx} style={{ height: RESULT_ROW_HEIGHT }}
                        className={m.isBadData ? 'bg-status-warn/10' : m.isFlagged ? 'bg-destructive/10' : ''}>
                        <TableCell className="text-xs mono">{m.label}</TableCell>
                        <TableCell className="text-right mono text-xs">{m.z_noisy.toFixed(4)}</TableCell>
                        <TableCell className="text-right mono text-xs">{m.residual.toFixed(4)}</TableCell>
                        <TableCell className={`text-right mono text-xs font-bold ${Math.abs(m.r_N) > 3 ? 'text-destructive' : ''}`}>
                          {Math.abs(m.r_N).toFixed(2)}
                        </TableCell>
                        <TableCell className={`text-right mono text-xs font-bold ${Math.abs(m.CME_N) > 3 ? 'text-status-warn' : ''}`}>
                          {Math.abs(m.CME_N).toFixed(2)}
                        </TableCell>
                        <TableCell className="text-right mono text-xs">{m.UI.toFixed(3)}</TableCell>
                        <TableCell className="text-xs">
                          {m.isBadData && <Badge variant="outline" className="text-[9px] border-status-warn text-status-warn">injected</Badge>}
                          {m.isFlagged && <Badge variant="destructive" className="text-[9px]">flagged</Badge>}
                        </TableCell>
                      </TableRow>
                    )}
                  />
              </TableCard>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Run all 6 combos */}
      <Card>
        <CardHeader className="p-4 pb-2">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-sm">Compare All 6 Pipeline Combinations</CardTitle>
              <CardDescription className="text-xs">Runs the 8 Detection x Identification x Correction combinations in parallel</CardDescription>
            </div>
            <Button size="sm" onClick={runAllCombos} disabled={allCombos.status === 'running'} variant="secondary">
              <ArrowRight weight="bold" className="mr-1 w-3 h-3" />Run All
            </Button>
          </div>
        </CardHeader>
        {allCombos.status !== 'idle' && (
          <CardContent className="p-4 pt-0">
            {allCombos.error && <p className="text-xs text-destructive">{allCombos.error}</p>}
            {allCombos.result && (
              <TableCard label="Compare All 6 Pipeline Combinations">
                  <TableHeader>
                    <TableRow>
                      <TableHead className="mono text-xs">Combination</TableHead>
                      <TableHead className="mono text-right text-xs">Detected?</TableHead>
                      <TableHead className="mono text-right text-xs">J_final</TableHead>
                      <TableHead className="mono text-right text-xs">Threshold</TableHead>
                      <TableHead className="mono text-right text-xs">Flagged</TableHead>
                      <TableHead className="mono text-right text-xs">Action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {DETECTION_COMBOS.map((combo, i) => {
                      const r = allCombos.result![i]
                      return (
                        <TableRow key={i} className={r.pipeline.detected ? 'bg-status-good/10' : 'bg-destructive/10'}>
                          <TableCell className="text-xs mono">{combo.label}</TableCell>
                          <TableCell className="text-right text-xs">
                            <Badge variant={r.pipeline.detected ? 'default' : 'destructive'} className="text-[9px]">
                              {r.pipeline.detected ? 'YES' : 'NO'}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right mono text-xs">{r.pipeline.J_final.toFixed(3)}</TableCell>
                          <TableCell className="text-right mono text-xs">{r.pipeline.threshold.toFixed(3)}</TableCell>
                          <TableCell className="text-right mono text-xs">{r.pipeline.flaggedIndices.join(',') || '—'}</TableCell>
                          <TableCell className="text-right mono text-xs">{r.pipeline.actions.join(',') || '—'}</TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
              </TableCard>
            )}
          </CardContent>
        )}
      </Card>
    </div>
  )
}
