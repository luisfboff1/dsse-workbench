import { useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Progress } from '@/components/ui/progress'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Play, CheckCircle, Warning, Terminal } from '@phosphor-icons/react'
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { TableCard } from '@/components/TableCard'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ReferenceLine, LineChart, Line } from 'recharts'
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart'
import type { Topology, ExecutionTrace } from '@/lib/types'
import { runEstimation, type EstimationGroundTruth, type EstimationMethod, type EstimationResult } from '@/lib/api'
import { MeasurementsSummaryCard } from '@/components/MeasurementsSummaryCard'
import { MEASUREMENT_KIND_INFO, QUANTITY_LABEL } from '@/lib/measurements'
import { ColumnInfoBadge } from '@/components/ColumnInfo'
import { ExecutionPanel } from '@/components/ExecutionPanel'
import { CopyDataButton } from '@/components/CopyDataButton'

const jHistoryChartConfig = {
  J: { label: 'J (objective)', color: 'var(--color-accent)' },
} satisfies ChartConfig

const residualChartConfig = {
  residual_normalized: { label: '|r_N|', color: 'var(--color-accent)' },
} satisfies ChartConfig

const ESTIMATION_METHODS: { id: EstimationMethod; label: string; shortLabel: string; tagline: string }[] = [
  {
    id: 'dc-wls',
    label: 'DC-WLS (linear)',
    shortLabel: 'DC-WLS',
    tagline: 'Angles only, one-shot linear solve — fast, matches the classic DC state estimation notebook.',
  },
  {
    id: 'ac-gn-wls',
    label: 'AC Gauss-Newton WLS (nonlinear)',
    shortLabel: 'AC-GN-WLS',
    tagline: 'Angles + voltage magnitudes, iterative — closer to what a real DSSE runs, needs a converged AC ground truth.',
  },
]

const GROUND_TRUTH_OPTIONS: { id: EstimationGroundTruth; label: string; tagline: string }[] = [
  {
    id: 'ac',
    label: 'AC (Newton-Raphson)',
    tagline: 'z_true = H·θ_AC + c — solves a fresh AC power flow (NR, Iwamoto fallback) for θ; the topology itself never stores solved angles.',
  },
  {
    id: 'dc',
    label: 'DC (rundcpp)',
    tagline: 'z_true straight from the DC power flow solution.',
  },
]

interface StateEstimationTabProps {
  topology: Topology
}

export function StateEstimationTab({ topology }: StateEstimationTabProps) {
  const [groundTruth, setGroundTruth] = useState<EstimationGroundTruth>('ac')
  const [estimationMethod, setEstimationMethod] = useState<EstimationMethod>('dc-wls')
  const [noiseLevel, setNoiseLevel] = useState(0.01)
  const [seed, setSeed] = useState<string>('42')
  const [isRunning, setIsRunning] = useState(false)
  const [result, setResult] = useState<EstimationResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [traceEnabled, setTraceEnabled] = useState(false)
  const [executionTrace, setExecutionTrace] = useState<ExecutionTrace | null>(null)
  const [panelOpen, setPanelOpen] = useState(false)

  // ac-gn-wls always solves its own AC ground truth (needs a fresh runpp for
  // Ybus) — there's no meaningful "DC ground truth" for a voltage-magnitude
  // state, so the selector is locked to AC when that method is chosen.
  const effectiveGroundTruth: EstimationGroundTruth = estimationMethod === 'ac-gn-wls' ? 'ac' : groundTruth
  const methodInfo = ESTIMATION_METHODS.find((m) => m.id === estimationMethod)!
  const seedNum = seed.trim() !== '' ? parseInt(seed) : null

  const handleRun = async () => {
    setIsRunning(true)
    setResult(null)
    setError(null)
    try {
      const res = await runEstimation({
        topology,
        ground_truth: effectiveGroundTruth,
        estimation_method: estimationMethod,
        noise_level: noiseLevel,
        seed: seedNum,
        trace: traceEnabled,
      })
      setResult(res)
      if (res.execution_trace) setExecutionTrace(res.execution_trace)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setIsRunning(false)
    }
  }

  // Real chi2.ppf(0.05, dof) from the backend (chi2_limit — same test as the
  // Bad Data tab and the reference notebook), not a normal approximation.
  const chiSqThreshold = result?.chi2Threshold ?? null

  return (
    <div className="space-y-3 sm:space-y-4">
      <MeasurementsSummaryCard
        topology={topology}
        estimationMethod={estimationMethod}
        groundTruth={effectiveGroundTruth}
        noiseLevel={noiseLevel}
        seed={seedNum}
      />

      <div className="grid grid-cols-1 gap-3 sm:gap-4 xl:grid-cols-[300px_1fr]">
      {/* Config */}
      <Card>
        <CardHeader className="px-4 sm:px-6 py-4 sm:py-6">
          <CardTitle className="text-base sm:text-lg">State Estimation</CardTitle>
          <CardDescription className="text-xs sm:text-sm">
            {methodInfo.tagline} Python functions from <code className="text-xs">src/tese_dsse</code>.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 px-4 sm:px-6 pb-4 sm:pb-6">
          <div className="space-y-2">
            <Label>Estimation method</Label>
            <Select value={estimationMethod} onValueChange={(v) => setEstimationMethod(v as EstimationMethod)}>
              <SelectTrigger className="mono w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ESTIMATION_METHODS.map((m) => (
                  <SelectItem key={m.id} value={m.id} className="mono">
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Ground truth (z_true)</Label>
            <Select
              value={effectiveGroundTruth}
              onValueChange={(v) => setGroundTruth(v as EstimationGroundTruth)}
              disabled={estimationMethod === 'ac-gn-wls'}
            >
              <SelectTrigger className="mono w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {GROUND_TRUTH_OPTIONS.map((g) => (
                  <SelectItem key={g.id} value={g.id} className="mono">
                    {g.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {estimationMethod === 'ac-gn-wls'
                ? 'Locked to AC — ac-gn-wls solves its own AC power flow to build the Ybus measurement model, there\'s no DC equivalent for a voltage-magnitude state.'
                : GROUND_TRUTH_OPTIONS.find((g) => g.id === effectiveGroundTruth)?.tagline}
            </p>
          </div>

          <Separator />

          <div className="space-y-2">
            <Label>Noise Level (relative σ)</Label>
            <Input
              type="number"
              value={noiseLevel}
              onChange={(e) => setNoiseLevel(parseFloat(e.target.value))}
              step={0.005}
              min={0.001}
              max={0.5}
            />
            <p className="text-xs text-muted-foreground">
              Example: 0.01 = 1% Gaussian noise on each measurement
            </p>
          </div>
          <div className="space-y-2">
            <Label>Seed (empty = random)</Label>
            <Input
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder="42"
            />
          </div>
          <div className="flex items-center justify-between">
            <Label htmlFor="trace-toggle" className="cursor-pointer">
              Trace execution
            </Label>
            <Switch
              id="trace-toggle"
              checked={traceEnabled}
              onCheckedChange={setTraceEnabled}
            />
          </div>
          <Separator />
          <Button onClick={handleRun} disabled={isRunning} className="w-full" size="lg">
            {isRunning ? 'Running...' : <><Play className="mr-2" weight="fill" />Run {methodInfo.shortLabel}</>}
          </Button>
          {isRunning && <Progress value={60} className="animate-pulse" />}

          {result && (
            <div className="space-y-2 pt-2 border-t">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Measurements (m)</span>
                <span className="mono font-semibold">{result.nMeasurements}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">States (n)</span>
                <span className="mono font-semibold">{result.nStates}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">DoF (m−n)</span>
                <span className="mono font-semibold">{result.dof}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Iterations</span>
                <span className="mono font-semibold">{result.iterations}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">J (objective)</span>
                <span className={`mono font-bold ${chiSqThreshold && result.J > chiSqThreshold ? 'text-destructive' : 'text-status-good'}`}>
                  {result.J.toFixed(3)}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">χ² threshold (~95%)</span>
                <span className="mono">{chiSqThreshold?.toFixed(1)}</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Exec time</span>
                <span className="mono">{result.executionTime.toFixed(1)} ms</span>
              </div>
            </div>
          )}

          {executionTrace && (
            <Button
              variant="outline"
              size="sm"
              className="w-full gap-2 mt-2"
              onClick={() => setPanelOpen(true)}
            >
              <Terminal size={14} />
              View Execution Trace
            </Button>
          )}
        </CardContent>
      </Card>

      <ExecutionPanel
        trace={executionTrace}
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
      />

      {/* Results */}
      <Card className="min-w-0">
        <CardHeader className="px-4 sm:px-6 py-4 sm:py-6">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <CardTitle className="text-base sm:text-lg">Estimation Results</CardTitle>
              <CardDescription className="text-xs sm:text-sm">Estimated state vs. ground truth plus residuals</CardDescription>
            </div>
            {result && (
              <Badge variant={result.converged ? 'default' : 'destructive'} className="text-xs">
                {result.converged
                  ? <><CheckCircle className="mr-1 w-3 h-3" weight="fill" />Converged</>
                  : <><Warning className="mr-1 w-3 h-3" weight="fill" />Did not converge</>}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4 px-4 sm:px-6 pb-4 sm:pb-6">
          {error && (
            <Alert variant="destructive">
              <Warning weight="fill" />
              <AlertDescription className="mono text-xs break-all">{error}</AlertDescription>
            </Alert>
          )}

          {!result && !error && (
            <div className="text-center py-12 text-muted-foreground text-sm">
              Configure the method and noise level, then click Run {methodInfo.shortLabel}
            </div>
          )}

          {result && (
            <>
              {/* State estimates table */}
              <h4 className="font-semibold mono text-sm">
                Bus State Estimates{result.states[0]?.vTrue_pu != null ? ' (θ + |V|)' : ' (θ)'}
              </h4>
              <TableCard label="Bus State Estimates">
                  <TableHeader>
                    <TableRow>
                      <TableHead className="mono text-xs">Bus</TableHead>
                      <TableHead className="mono text-right text-xs">θ True (deg)</TableHead>
                      <TableHead className="mono text-right text-xs">θ Est (deg)</TableHead>
                      <TableHead className="mono text-right text-xs" title="A-priori 95% confidence half-width from sqrt(diag((HᵀWH)⁻¹)) — depends only on topology and meter placement, not on the measured values. This is the trustworthiness of the estimate; J/chi² is not.">θ ±95% (deg)</TableHead>
                      <TableHead className="mono text-right text-xs">|Error θ| (deg)</TableHead>
                      {result.states[0]?.vTrue_pu != null && (
                        <>
                          <TableHead className="mono text-right text-xs">|V| True (pu)</TableHead>
                          <TableHead className="mono text-right text-xs">|V| Est (pu)</TableHead>
                          <TableHead className="mono text-right text-xs" title="A-priori 95% confidence half-width of the voltage-magnitude estimate.">|V| ±95% (pu)</TableHead>
                          <TableHead className="mono text-right text-xs">|Error V| (pu)</TableHead>
                        </>
                      )}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {result.states.map((s) => {
                      // % of the true value — undefined near zero (e.g. the
                      // slack bus, or a lightly-loaded feeder tip) since the
                      // denominator blows the ratio up; same convention as
                      // sigmaPct in MeasurementsSummaryCard.
                      const angleErrPct = Math.abs(s.angleTrue_deg) > 0.01 ? (s.error_deg / Math.abs(s.angleTrue_deg)) * 100 : null
                      const vErrPct = s.vTrue_pu != null && s.vError_pu != null ? (s.vError_pu / s.vTrue_pu) * 100 : null
                      // Real error outside the a-priori 95% band is the honest
                      // red flag: the estimate is worse than the model claims it
                      // can be, which points at bad data / wrong parameters —
                      // and it can happen while J still passes the chi² test.
                      const angleOutOfBand = s.angleCi95_deg != null && s.angleCi95_deg > 0 && s.error_deg > s.angleCi95_deg
                      const vOutOfBand = s.vCi95_pu != null && s.vCi95_pu > 0 && (s.vError_pu ?? 0) > s.vCi95_pu
                      return (
                        <TableRow key={s.busId}>
                          <TableCell className="font-medium text-xs">{s.busId}</TableCell>
                          <TableCell className="text-right mono text-xs">{s.angleTrue_deg.toFixed(4)}</TableCell>
                          <TableCell className="text-right mono text-xs">{s.angleEst_deg.toFixed(4)}</TableCell>
                          <TableCell className="text-right mono text-xs text-muted-foreground">
                            {s.angleCi95_deg != null ? `±${s.angleCi95_deg.toFixed(4)}` : '—'}
                          </TableCell>
                          <TableCell className={`text-right mono text-xs ${angleOutOfBand ? 'text-destructive' : 'text-status-good'}`}>
                            {s.error_deg.toFixed(6)}
                            {angleErrPct != null && <span className="text-muted-foreground"> ({angleErrPct.toFixed(1)}%)</span>}
                            {angleOutOfBand && <span title="Real error exceeds the a-priori 95% band"> ⚠</span>}
                          </TableCell>
                          {s.vTrue_pu != null && (
                            <>
                              <TableCell className="text-right mono text-xs">{s.vTrue_pu.toFixed(5)}</TableCell>
                              <TableCell className="text-right mono text-xs">{s.vEst_pu?.toFixed(5)}</TableCell>
                              <TableCell className="text-right mono text-xs text-muted-foreground">
                                {s.vCi95_pu != null ? `±${s.vCi95_pu.toFixed(5)}` : '—'}
                              </TableCell>
                              <TableCell className={`text-right mono text-xs ${vOutOfBand ? 'text-destructive' : 'text-status-good'}`}>
                                {s.vError_pu?.toFixed(6)}
                                {vErrPct != null && <span className="text-muted-foreground"> ({vErrPct.toFixed(2)}%)</span>}
                                {vOutOfBand && <span title="Real error exceeds the a-priori 95% band"> ⚠</span>}
                              </TableCell>
                            </>
                          )}
                        </TableRow>
                      )
                    })}
                  </TableBody>
              </TableCard>

              <Separator />

              {/* Convergence history — only meaningful for the iterative
                  solver; dc-wls is a one-shot solve (single point). */}
              {result.iterationHistory.length > 1 && (
                <>
                  <div className="flex items-center justify-between gap-2">
                    <h4 className="font-semibold mono text-sm">J per Iteration (Gauss-Newton convergence)</h4>
                    <CopyDataButton
                      headers={['iteration', 'J']}
                      rows={result.iterationHistory.map((h) => [h.iteration, h.J])}
                      label="J per Iteration"
                    />
                  </div>
                  <ChartContainer config={jHistoryChartConfig} className="aspect-auto h-40 w-full">
                    <LineChart data={result.iterationHistory} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                      <XAxis dataKey="iteration" tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 10 }} />
                      <ChartTooltip content={<ChartTooltipContent formatter={(v) => Number(v).toFixed(4)} />} />
                      <Line type="monotone" dataKey="J" stroke="var(--color-accent)" strokeWidth={2} dot={{ r: 2 }} />
                    </LineChart>
                  </ChartContainer>
                  {!result.converged && (
                    <p className="text-xs text-status-warn">
                      J stabilized but the state kept moving without settling — a common sign that some part of the
                      network (often a subtree downstream of an unmeasured bus) is weakly observable with the current
                      meter placement, not necessarily a solver problem.
                    </p>
                  )}
                  <Separator />
                </>
              )}

              {/* Residuals chart */}
              <div className="flex items-center justify-between gap-2">
                <h4 className="font-semibold mono text-sm">Normalized Residuals |r_N|</h4>
                <CopyDataButton
                  headers={['label', 'residual_normalized']}
                  rows={result.residuals.map((r) => [r.label, r.residual_normalized.toFixed(3)])}
                  label="Normalized Residuals"
                />
              </div>
              <ChartContainer config={residualChartConfig} className="aspect-auto h-48 w-full">
                <BarChart data={result.residuals} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="label" tick={{ fontSize: 9 }} interval={0} angle={-40} textAnchor="end" height={50} />
                  <YAxis tick={{ fontSize: 9 }} />
                  <ChartTooltip content={<ChartTooltipContent formatter={(v) => Number(v).toFixed(3)} />} />
                  <ReferenceLine y={3} stroke="var(--color-destructive)" strokeDasharray="4 2" label={{ value: 'LNR=3', fontSize: 9 }} />
                  <Bar dataKey="residual_normalized" fill="var(--color-accent)" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ChartContainer>

              {/* Residuals table */}
              <h4 className="font-semibold mono text-sm">Measurement Residuals</h4>
              <TableCard label="Measurement Residuals" maxHeight="16rem">
                  <TableHeader>
                    <TableRow>
                      <TableHead className="mono text-xs">Meas.</TableHead>
                      <TableHead className="mono text-xs">
                        <span className="inline-flex items-center gap-1">Meter<ColumnInfoBadge columnKey="meterKind" /></span>
                      </TableHead>
                      <TableHead className="mono text-xs">
                        <span className="inline-flex items-center gap-1">Quantity<ColumnInfoBadge columnKey="quantity" /></span>
                      </TableHead>
                      <TableHead className="mono text-right text-xs">
                        <span className="inline-flex items-center gap-1 justify-end">z_true<ColumnInfoBadge columnKey="zTrue" /></span>
                      </TableHead>
                      <TableHead className="mono text-right text-xs">
                        <span className="inline-flex items-center gap-1 justify-end">σ<ColumnInfoBadge columnKey="sigma" /></span>
                      </TableHead>
                      <TableHead className="mono text-right text-xs">
                        <span className="inline-flex items-center gap-1 justify-end">z_noisy<ColumnInfoBadge columnKey="zNoisy" /></span>
                      </TableHead>
                      <TableHead className="mono text-right text-xs">
                        <span className="inline-flex items-center gap-1 justify-end">z_hat<ColumnInfoBadge columnKey="zHat" /></span>
                      </TableHead>
                      <TableHead className="mono text-right text-xs">
                        <span className="inline-flex items-center gap-1 justify-end">r<ColumnInfoBadge columnKey="residual" /></span>
                      </TableHead>
                      <TableHead className="mono text-right text-xs">
                        <span className="inline-flex items-center gap-1 justify-end">|r_N|<ColumnInfoBadge columnKey="residualNormalized" /></span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {result.residuals.map((r) => (
                      <TableRow key={r.idx}
                        className={Math.abs(r.residual_normalized) > 3 ? 'bg-destructive/10' : ''}>
                        <TableCell className="text-xs mono">{r.label}</TableCell>
                        <TableCell className="text-xs">
                          <span
                            className="mono font-semibold"
                            style={{ color: MEASUREMENT_KIND_INFO[r.meterKind as keyof typeof MEASUREMENT_KIND_INFO]?.colorVar }}
                          >
                            {MEASUREMENT_KIND_INFO[r.meterKind as keyof typeof MEASUREMENT_KIND_INFO]?.shortLabel ?? r.meterKind}
                          </span>
                        </TableCell>
                        <TableCell className="mono text-xs">{QUANTITY_LABEL[r.quantity] ?? r.quantity}</TableCell>
                        <TableCell className="text-right mono text-xs">{r.z_true.toFixed(4)}</TableCell>
                        <TableCell className="text-right mono text-xs text-muted-foreground">{r.sigma.toFixed(4)}</TableCell>
                        <TableCell className="text-right mono text-xs">{r.z_noisy.toFixed(4)}</TableCell>
                        <TableCell className="text-right mono text-xs">{r.z_hat.toFixed(4)}</TableCell>
                        <TableCell className="text-right mono text-xs">{r.residual.toFixed(4)}</TableCell>
                        <TableCell className={`text-right mono text-xs font-bold ${Math.abs(r.residual_normalized) > 3 ? 'text-destructive' : ''}`}>
                          {Math.abs(r.residual_normalized).toFixed(2)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
              </TableCard>
            </>
          )}
        </CardContent>
      </Card>
      </div>
    </div>
  )
}
