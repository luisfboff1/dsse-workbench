import { useEffect, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { TableCard } from '@/components/TableCard'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Cell, ReferenceLine } from 'recharts'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Gauge, Table as TableIcon, ChartBar, Warning } from '@phosphor-icons/react'
import type { Topology } from '@/lib/types'
import { previewMeasurements, type EstimationGroundTruth, type EstimationMethod, type MeasurementPreviewRow } from '@/lib/api'
import { MEASUREMENT_KIND_INFO, QUANTITY_LABEL } from '@/lib/measurements'
import { ColumnInfoBadge } from '@/components/ColumnInfo'
import { CopyDataButton } from '@/components/CopyDataButton'

interface MeasurementsSummaryCardProps {
  topology: Topology
  estimationMethod?: EstimationMethod
  groundTruth?: EstimationGroundTruth
  noiseLevel: number
  /** Matches the backend's own default (see EstimationRequest.sigma_min). */
  sigmaMin?: number
  /** Same seed as the Run panel — with it set, the noisy sample shown here
   *  is bit-for-bit what Run will actually use (same rng call shape). */
  seed?: number | null
}

/**
 * "What's actually observable right now, and how uncertain is it" — a live
 * preview (POST /estimation/preview, no noise/no solve) of what
 * topology.measurements resolves to: true value + sigma per meter, given
 * the currently-selected method/ground-truth/noise settings. Shown before
 * running Bad Data / State Estimation, so a sparse or noisy meter placement
 * is visible up front instead of only showing up in a post-run table.
 */
export function MeasurementsSummaryCard({
  topology,
  estimationMethod = 'dc-wls',
  groundTruth = 'ac',
  noiseLevel,
  sigmaMin = 0.0001,
  seed,
}: MeasurementsSummaryCardProps) {
  const [rows, setRows] = useState<MeasurementPreviewRow[] | null>(null)
  const [nStates, setNStates] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    previewMeasurements({
      topology,
      estimation_method: estimationMethod,
      ground_truth: groundTruth,
      noise_level: noiseLevel,
      sigma_min: sigmaMin,
      seed,
    })
      .then((res) => {
        if (cancelled) return
        setRows(res.measurements)
        setNStates(res.nStates)
      })
      .catch((e: any) => {
        if (cancelled) return
        setRows(null)
        setError(e.message)
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [topology, estimationMethod, groundTruth, noiseLevel, sigmaMin, seed])

  const busesObserved = new Set((rows ?? []).filter((r) => r.busId != null).map((r) => r.busId)).size
  const nUnobserved = topology.buses.length - busesObserved

  // Natural/table order (not sorted by magnitude) — sorting by value turns an
  // otherwise-unremarkable deterministic sigma formula into what looks like a
  // suspicious staircase pattern. sigma is a model parameter (expected spread,
  // never signed, never random); it's supposed to repeat across measurements
  // of the same meter kind and similar magnitude.
  const chartData = (rows ?? []).map((r) => ({
    name: r.label,
    sigmaPct: r.sigmaPct ?? 0,
    color: MEASUREMENT_KIND_INFO[r.meterKind as keyof typeof MEASUREMENT_KIND_INFO]?.colorVar ?? 'var(--color-muted-foreground)',
  }))

  // Normalized noise e_i/sigma_i = (z_noisy - z_true)/sigma — the realized,
  // signed random sample (unlike sigma/sigma% above). Pooled across every
  // measurement this should look like a standard Gaussian N(0,1) if the noise
  // model is calibrated correctly; it's what J = sum((e_i/sigma_i)^2) tests.
  const BIN_WIDTH = 0.5
  const BIN_RANGE = 4
  const normResidualHist = (() => {
    const bins: { x: number; count: number }[] = []
    for (let b = -BIN_RANGE; b < BIN_RANGE; b += BIN_WIDTH) {
      bins.push({ x: Math.round((b + BIN_WIDTH / 2) * 100) / 100, count: 0 })
    }
    for (const r of rows ?? []) {
      if (!r.sigma) continue
      const e = (r.valueNoisy - r.value) / r.sigma
      const idx = Math.floor((e + BIN_RANGE) / BIN_WIDTH)
      if (idx >= 0 && idx < bins.length) bins[idx].count += 1
    }
    return bins
  })()

  // Same display values as the charts below, so what CopyDataButton exports
  // matches what's on screen (the table itself copies via TableCard, which
  // reads the rendered cells directly instead of needing this).
  const sigmaChartHeaders = ['Measurement', 'σ (%)']
  const sigmaChartRows: (string | number)[][] = chartData.map((d) => [d.name, d.sigmaPct.toFixed(2)])
  const residualChartHeaders = ['Bin center (e/σ)', 'Count']
  const residualChartRows: (string | number)[][] = normResidualHist.map((b) => [b.x, b.count])

  return (
    <Card>
      <CardHeader className="px-4 py-4">
        <CardTitle className="text-base flex items-center gap-2">
          <Gauge weight="fill" className="text-accent" />
          Measurements
        </CardTitle>
        <CardDescription className="text-xs">
          {rows && (
            <>
              {rows.length} measurement{rows.length === 1 ? '' : 's'} · {busesObserved} of {topology.buses.length} buses observed
              {nStates != null && ` · ${nStates} unknown${nStates === 1 ? '' : 's'} (DoF ${rows.length - nStates >= 0 ? '+' : ''}${rows.length - nStates})`}
              {nUnobserved > 0 && <span className="text-status-warn"> · {nUnobserved} unobserved</span>}
            </>
          )}
          {loading && !rows && 'Loading measurement preview…'}
          {' — configured on the Topology tab\'s diagram. '}
          Noisy sample always drawn from the σ/σ_min/seed set above, regardless of the
          "Add measurement noise" checkbox further down (that flag only gates Step 2's actual run).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 px-4 pb-4">
        {error && (
          <Alert variant="destructive">
            <Warning weight="fill" />
            <AlertDescription className="mono text-xs break-all">{error}</AlertDescription>
          </Alert>
        )}
        {rows && estimationMethod !== 'ac-gn-wls' && (
          <p className="text-xs text-muted-foreground">
            DC linear model — only P injection is part of the state equations (Q and |V| aren't modeled at all in DC
            power flow), so every meter kind reads the same quantity here and only differs in σ. A PMU/SCADA/AMI's
            full P/Q/V/θ reading only shows up under the AC Gauss-Newton estimator (State Estimation tab).
          </p>
        )}
        {rows && (
          <Tabs defaultValue="table">
            <TabsList>
              <TabsTrigger value="table" className="text-xs">
                <TableIcon className="w-3.5 h-3.5" /> Table
              </TabsTrigger>
              <TabsTrigger value="charts" className="text-xs">
                <ChartBar className="w-3.5 h-3.5" /> Chart
              </TabsTrigger>
            </TabsList>

            <TabsContent value="table">
              <TableCard label="Measurements" maxHeight="16rem">
                <TableHeader>
                    <TableRow>
                      <TableHead className="mono text-xs sticky top-0 z-10 bg-background">
                        <span className="inline-flex items-center gap-1">Location<ColumnInfoBadge columnKey="busId" /></span>
                      </TableHead>
                      <TableHead className="mono text-xs sticky top-0 z-10 bg-background">
                        <span className="inline-flex items-center gap-1">Meter<ColumnInfoBadge columnKey="meterKind" /></span>
                      </TableHead>
                      <TableHead className="mono text-xs sticky top-0 z-10 bg-background">
                        <span className="inline-flex items-center gap-1">Quantity<ColumnInfoBadge columnKey="quantity" /></span>
                      </TableHead>
                      <TableHead className="mono text-right text-xs sticky top-0 z-10 bg-background">
                        <span className="inline-flex items-center gap-1 justify-end">True value<ColumnInfoBadge columnKey="zTrue" /></span>
                      </TableHead>
                      <TableHead className="mono text-right text-xs sticky top-0 z-10 bg-background">
                        <span className="inline-flex items-center gap-1 justify-end">Noisy sample<ColumnInfoBadge columnKey="zNoisy" /></span>
                      </TableHead>
                      <TableHead className="mono text-right text-xs sticky top-0 z-10 bg-background">
                        <span className="inline-flex items-center gap-1 justify-end">σ<ColumnInfoBadge columnKey="sigma" /></span>
                      </TableHead>
                      <TableHead className="mono text-right text-xs sticky top-0 z-10 bg-background">
                        <span className="inline-flex items-center gap-1 justify-end">σ (%)<ColumnInfoBadge columnKey="sigmaPct" /></span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((r, i) => (
                      <TableRow key={i}>
                        <TableCell className="font-medium text-xs">
                          {r.busId != null ? (
                            `Bus ${r.busId}`
                          ) : (
                            <>
                              {`Line ${r.lineId}`}
                              <span className="text-muted-foreground font-normal ml-1">({r.label})</span>
                            </>
                          )}
                        </TableCell>
                        <TableCell className="text-xs">
                          <span
                            className="mono font-semibold"
                            style={{ color: MEASUREMENT_KIND_INFO[r.meterKind as keyof typeof MEASUREMENT_KIND_INFO]?.colorVar }}
                          >
                            {MEASUREMENT_KIND_INFO[r.meterKind as keyof typeof MEASUREMENT_KIND_INFO]?.shortLabel ?? r.meterKind}
                          </span>
                        </TableCell>
                        <TableCell className="mono text-xs">{QUANTITY_LABEL[r.quantity] ?? r.quantity}</TableCell>
                        <TableCell className="text-right mono text-xs">{r.value.toFixed(4)}</TableCell>
                        <TableCell className="text-right mono text-xs text-accent">{r.valueNoisy.toFixed(4)}</TableCell>
                        <TableCell className="text-right mono text-xs">{r.sigma.toFixed(4)}</TableCell>
                        <TableCell className="text-right mono text-xs text-muted-foreground">
                          {r.sigmaPct != null ? `${r.sigmaPct.toFixed(1)}%` : '—'}
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
                    σ as a percentage of the true value, per measurement (table order) — the expected spread, not a
                    random sample. Flat within a meter kind except where σ_min (the absolute noise floor) dominates
                    for near-zero true values.
                  </p>
                  <CopyDataButton headers={sigmaChartHeaders} rows={sigmaChartRows} label="σ% chart" className="shrink-0" />
                </div>
                <ChartContainer config={{}} className="aspect-auto h-48 w-full">
                  <BarChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 40 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis dataKey="name" tick={{ fontSize: 8 }} interval={0} angle={-45} textAnchor="end" height={60} />
                    <YAxis tick={{ fontSize: 10 }} unit="%" />
                    <ChartTooltip content={<ChartTooltipContent formatter={(v) => `${Number(v).toFixed(1)}%`} />} />
                    <Bar dataKey="sigmaPct" radius={[2, 2, 0, 0]}>
                      {chartData.map((d, i) => (
                        <Cell key={i} fill={d.color} />
                      ))}
                    </Bar>
                  </BarChart>
                </ChartContainer>
              </div>

              <div>
                <div className="flex items-start justify-between gap-2 mb-1">
                  <p className="mono text-xs text-muted-foreground">
                    Normalized noise (z_noisy − z_true) / σ, pooled across every measurement — the realized, signed
                    random sample. Should look like a standard Gaussian N(0,1) if the noise model is calibrated.
                  </p>
                  <CopyDataButton headers={residualChartHeaders} rows={residualChartRows} label="Normalized noise histogram" className="shrink-0" />
                </div>
                <ChartContainer config={{}} className="aspect-auto h-40 w-full">
                  <BarChart data={normResidualHist} margin={{ top: 5, right: 10, left: -20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis dataKey="x" tick={{ fontSize: 9 }} type="number" domain={[-BIN_RANGE, BIN_RANGE]} />
                    <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                    <ChartTooltip content={<ChartTooltipContent formatter={(v) => `${v} sample${v === 1 ? '' : 's'}`} />} />
                    <ReferenceLine x={0} stroke="var(--color-foreground)" strokeDasharray="3 2" />
                    <Bar dataKey="count" fill="var(--color-accent)" radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ChartContainer>
              </div>
            </TabsContent>
          </Tabs>
        )}
      </CardContent>
    </Card>
  )
}
