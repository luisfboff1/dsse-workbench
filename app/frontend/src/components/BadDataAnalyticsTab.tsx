/**
 * BadDataAnalyticsTab - complete interactive Bad Data analysis.
 * Inspirado no notebook 5_BUS_IEEE_bad_data_analytics.ipynb (Bretas 2013/2018).
 *
 * Sections:
 *  1. Geometry Explorer  - analyzes K and UI for all measurements before attack
 *  2. Attack Config      - chooses target measurement, magnitude, and pipeline
 *  3. Results            — χ² detection, LNR, CME, scatter, tabela completa, hat matrix heatmap
 *  4. All-6 Comparison   — Tabela comparativa dos 6 pipelines
 */
import { Fragment, useMemo, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Slider } from '@/components/ui/slider'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { TableCard } from '@/components/TableCard'
import { VirtualTableBody } from '@/components/VirtualTableBody'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ReferenceLine,
  ScatterChart, Scatter, Cell,
} from 'recharts'
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart'
import {
  MagnifyingGlass, Play, Warning, CheckCircle, Spinner, Lightning,
  ChartBar, ArrowRight, Info
} from '@phosphor-icons/react'
import type { Topology } from '@/lib/types'
import {
  runBadDataGeometry, runBadDataDetection,
  type BadDataGeometryResult, type BadDataGeometryMeasurement, type BadDataResult,
} from '@/lib/api'
import { MeasurementsSummaryCard } from '@/components/MeasurementsSummaryCard'

const kiiChartConfig = {
  K_ii: { label: 'K_ii', color: 'var(--color-status-info)' },
} satisfies ChartConfig

const uiChartConfig = {
  UI: { label: 'UI', color: 'var(--color-status-info)' },
} satisfies ChartConfig

const jThresholdChartConfig = {
  value: { label: 'J', color: 'var(--color-status-info)' },
} satisfies ChartConfig

const lnrChartConfig = {
  '|r_N|': { label: '|r_N|', color: 'var(--color-status-info)' },
} satisfies ChartConfig

// Paired view: baseline (no attack, same seed — sample_noisy_measurement runs
// before the bad_data_magnitude injection in baddata.py, so both calls share
// the exact same noise draw and only the attacked measurement differs) next
// to the attacked run, so the jump is attributable to the injected error
// alone, not to a different noise realization.
const cmePairedChartConfig = {
  CME_N_before: { label: 'antes (sem ataque)', color: 'var(--color-muted-foreground)' },
  CME_N_after: { label: 'depois (com ataque)', color: 'var(--color-method-ldf)' },
} satisfies ChartConfig

const cmeDeltaChartConfig = {
  delta: { label: 'Δ CME_N', color: 'var(--color-method-ldf)' },
} satisfies ChartConfig

// ─── constants ────────────────────────────────────────────────────────────────

const COMBOS = [
  { label: 'Residual + LNR + Remove',   detection: 'residual', identification: 'lnr',  correction: 'remove' },
  { label: 'Residual + LNR + Correct',  detection: 'residual', identification: 'lnr',  correction: 'ztrue'  },
  { label: 'Residual + CME + Remove',   detection: 'residual', identification: 'cme',  correction: 'remove' },
  { label: 'Residual + CME + Correct',  detection: 'residual', identification: 'cme',  correction: 'ztrue'  },  // 2×2×2 = 8
  { label: 'CME + LNR + Remove',        detection: 'cme',      identification: 'lnr',  correction: 'remove' },
  { label: 'CME + LNR + Correct',       detection: 'cme',      identification: 'lnr',  correction: 'ztrue'  },  // 2×2×2 = 8
  { label: 'CME + CME + Remove',        detection: 'cme',      identification: 'cme',  correction: 'remove' },
  { label: 'CME + CME + Correct',       detection: 'cme',      identification: 'cme',  correction: 'ztrue'  },
] as const

const K_CROSSOVER = 0.618  // Bretas 2013 - critical masking crossover

// ─── helper colours ──────────────────────────────────────────────────────────
// 3-tier masking-risk palette, backed by theme tokens (index.css) so retuning
// the palette in one place updates every chart/badge/table cell below.

function kiiHex(k: number): string {
  if (k > K_CROSSOVER) return 'var(--color-destructive)'  // HIGH risk
  if (k > 0.5)         return 'var(--color-status-warn)'  // MED risk
  return 'var(--color-status-info)'                       // LOW risk
}

// Innovation Index (Bretas et al. 2013/2018): II_i = 1/sqrt(UI_i) =
// sqrt((1-K_ii)/K_ii), since UI_i = K_ii/(1-K_ii) = 1/II_i^2 — this exact
// relation is what bad_data.py's composed_normalized_error() and the
// extended-Gauss objective (1+1/II_i^2)=(1+UI_i) already use, cross-checked
// against docs/estudos/estimacao_estado/literatura/bretas2018_extended_gauss_cme.md
// and pipeline_bad_data_8_combinacoes.md — both state the same formula.
// Pure frontend derivation, no new API field needed (UI is already returned).
// II → 0 as K_ii → 1 (fully masked, the measurement carries no detectable
// new information about its own error); II grows unbounded as K_ii → 0
// (fully observable/high innovation). Arturo asked about this relation
// (2026-06-20 meeting) — his own verbal shorthand ("II=1/UI") was an
// informal simplification, not this precise formula.
function innovationIndex(UI: number): number {
  return UI > 0 ? 1 / Math.sqrt(UI) : Infinity
}

// ─── sub-components ──────────────────────────────────────────────────────────

// rgba() needs numeric r,g,b components for the opacity blend below, so these
// stay as raw triplets instead of var(--token) — they mirror the destructive
// (diagonal) and status-info (off-diagonal) hues from index.css.
const HEATMAP_DIAG_RGB = '231,76,60'
const HEATMAP_OFFDIAG_RGB = '75,139,190'

/** Heatmap da hat matrix K (m×m) */
function HatMatrixHeatmap({ K, labels }: { K: number[][]; labels: string[] }) {
  const m = K.length
  const cellSize = Math.max(32, Math.min(52, Math.floor(520 / m)))
  return (
    <div className="overflow-auto">
      <div style={{ display: 'grid', gridTemplateColumns: `80px repeat(${m}, ${cellSize}px)`, gap: 1, fontSize: 9 }}>
        {/* header row */}
        <div />
        {labels.map((l, j) => (
          <div key={j} style={{ textAlign: 'center', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', transform: 'rotate(-45deg)', transformOrigin: 'left bottom', height: 60, lineHeight: '60px' }}>
            {l}
          </div>
        ))}
        {/* data rows */}
        {K.map((row, i) => (
          <>
            <div key={`lbl-${i}`} style={{ textAlign: 'right', paddingRight: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', lineHeight: `${cellSize}px`, height: cellSize }}>
              {labels[i]}
            </div>
            {row.map((val, j) => {
              const v = Math.abs(val)
              const bg = `rgba(${i === j ? HEATMAP_DIAG_RGB : HEATMAP_OFFDIAG_RGB}, ${v.toFixed(2)})`
              return (
                <div key={j} style={{
                  width: cellSize, height: cellSize, background: bg,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: v > 0.5 ? 'var(--color-background)' : 'var(--color-foreground)', fontSize: Math.max(7, cellSize / 5),
                  border: i === j ? `1px solid rgba(${HEATMAP_DIAG_RGB},0.6)` : '1px solid rgba(0,0,0,0.05)',
                }}>
                  {v.toFixed(2)}
                </div>
              )
            })}
          </>
        ))}
      </div>
    </div>
  )
}

/** Binary incidence heatmap (m measurements × n_lines) — rectangular, unlike
 *  HatMatrixHeatmap's square K-matrix, and cells are 0/1 (no diagonal). */
function IncidenceHeatmap({
  matrix, rowLabels, colLabels,
}: {
  matrix: number[][]
  rowLabels: string[]
  colLabels: string[]
}) {
  const rowH = 20
  // One <div> per cell, so the element count is rows x columns. On the IEEE
  // test feeders that is a few hundred; on a real case it is measurements x
  // lines, i.e. tens of millions, which is not a slow render but a dead tab.
  // Show the top-left corner and say so, rather than refuse or hang.
  const rows = Math.min(matrix.length, MAX_HEATMAP_ROWS)
  const cols = Math.min(colLabels.length, MAX_HEATMAP_COLS)
  const truncated = rows < matrix.length || cols < colLabels.length
  const colW = Math.max(40, Math.min(64, Math.floor(480 / Math.max(cols, 1))))
  return (
    <div>
      {truncated && (
        <p className="mb-2 text-xs text-status-warn">
          Showing {rows} x {cols} of {matrix.length} x {colLabels.length}. The full matrix is one cell
          per measurement-line pair; use Copy on the results table for the underlying data.
        </p>
      )}
      <div className="overflow-auto">
        <div style={{ display: 'grid', gridTemplateColumns: `140px repeat(${cols}, ${colW}px)`, gap: 1, fontSize: 9 }}>
          <div />
          {colLabels.slice(0, cols).map((l, j) => (
            <div key={j} style={{ textAlign: 'center', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: 600 }}>
              {l}
            </div>
          ))}
          {matrix.slice(0, rows).map((row, i) => (
            <Fragment key={`row-${i}`}>
              <div style={{ textAlign: 'right', paddingRight: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', lineHeight: `${rowH}px`, height: rowH }}>
                {rowLabels[i]}
              </div>
              {row.slice(0, cols).map((val, j) => (
                <div key={j} style={{
                  width: colW, height: rowH, background: val ? 'var(--color-foreground)' : 'transparent',
                  border: '1px solid var(--color-border)',
                }} />
              ))}
            </Fragment>
          ))}
        </div>
      </div>
    </div>
  )
}

/** True / Wrong (attacked) / Corrected mini bar chart for one line parameter (r, x, or c). */
function ParamCompareChart({
  label, trueVal, wrongVal, correctedVal, decimals,
}: {
  label: string
  trueVal: number
  wrongVal: number
  correctedVal: number
  decimals: number
}) {
  const data = [
    { name: 'True', value: trueVal, fill: 'var(--color-status-good)' },
    { name: 'Wrong (attacked)', value: wrongVal, fill: 'var(--color-destructive)' },
    { name: 'Corrected', value: correctedVal, fill: 'var(--color-status-info)' },
  ]
  return (
    <div>
      <p className="text-xs mono text-muted-foreground mb-1">{label}</p>
      <ChartContainer config={{ value: { label } }} className="aspect-auto h-32 w-full">
        <BarChart data={data} margin={{ top: 4, right: 6, left: 0, bottom: 5 }} barCategoryGap="25%">
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis dataKey="name" tick={{ fontSize: 8 }} />
          <YAxis tick={{ fontSize: 8 }} domain={['auto', 'auto']} />
          <ChartTooltip content={<ChartTooltipContent formatter={(v) => Number(v).toFixed(decimals)} />} />
          <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={48}>
            {data.map((d, i) => <Cell key={i} fill={d.fill} />)}
          </Bar>
        </BarChart>
      </ChartContainer>
    </div>
  )
}

/** Measurement table - clickable target selection */
function MeasurementTable({
  measurements, selectedIdx, onSelect,
}: {
  measurements: BadDataGeometryMeasurement[]
  selectedIdx: number | null
  onSelect: (i: number) => void
}) {
  return (
    <TableCard label="Geometry Measurements" maxHeight="16rem">
        <TableHeader>
          <TableRow>
            <TableHead className="mono text-xs w-8">#</TableHead>
            <TableHead className="mono text-xs">Label</TableHead>
            <TableHead className="mono text-xs">Kind</TableHead>
            <TableHead className="mono text-right text-xs">z_true (pu)</TableHead>
            <TableHead className="mono text-right text-xs">σ (pu)</TableHead>
            <TableHead className="mono text-right text-xs">K_ii</TableHead>
            <TableHead className="mono text-right text-xs">UI</TableHead>
            <TableHead className="mono text-right text-xs" title="Innovation Index (Bretas et al. 2013/2018) — II = 1/√UI = √((1-K_ii)/K_ii). New information a measurement carries; → 0 when fully masked, unbounded when fully observable.">II</TableHead>
            <TableHead className="mono text-right text-xs">Risk</TableHead>
            <TableHead className="mono text-xs">Attack?</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {measurements.map((m) => {
            const risk = m.K_diag > K_CROSSOVER ? 'HIGH' : m.K_diag > 0.5 ? 'MED' : 'LOW'
            const riskClass = m.K_diag > K_CROSSOVER ? 'text-destructive font-bold' : m.K_diag > 0.5 ? 'text-status-warn font-semibold' : 'text-status-info'
            const isSelected = selectedIdx === m.idx
            const ii = innovationIndex(m.UI)
            return (
              <TableRow key={m.idx}
                className={`cursor-pointer transition-colors ${isSelected ? 'bg-accent/20 border-accent' : 'hover:bg-muted/50'}`}
                onClick={() => onSelect(m.idx)}>
                <TableCell className="text-xs mono text-muted-foreground">{m.idx}</TableCell>
                <TableCell className="text-xs mono font-medium">{m.label}</TableCell>
                <TableCell className="text-xs mono text-muted-foreground">{m.meterKind}</TableCell>
                <TableCell className="text-right text-xs mono">{m.z_true.toFixed(4)}</TableCell>
                <TableCell className="text-right text-xs mono">{m.sigma.toFixed(4)}</TableCell>
                <TableCell className="text-right text-xs mono">
                  <span style={{ color: kiiHex(m.K_diag) }} className="font-semibold">{m.K_diag.toFixed(4)}</span>
                </TableCell>
                <TableCell className="text-right text-xs mono">{m.UI.toFixed(4)}</TableCell>
                <TableCell className="text-right text-xs mono text-muted-foreground">{Number.isFinite(ii) ? ii.toFixed(3) : '∞'}</TableCell>
                <TableCell className={`text-xs mono ${riskClass}`}>{risk}</TableCell>
                <TableCell>
                  {isSelected && <Badge className="text-[9px] px-1 py-0">SELECTED</Badge>}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
    </TableCard>
  )
}

/** Cap for the structural incidence heat-map, which is one DOM node per
 *  matrix cell. */
const MAX_HEATMAP_ROWS = 120
const MAX_HEATMAP_COLS = 60

/** Most bars a measurement chart will draw. Past this the plot is both slow
 *  (Recharts is one SVG element per bar, plus a <Cell> each) and unreadable
 *  (sub-pixel bars), so the charts show the measurements that carry the signal
 *  and say how many they left out. */
const MAX_CHART_POINTS = 400

/**
 * Keep at most MAX_CHART_POINTS entries: everything `alwaysKeep` marks (the
 * injected/flagged measurements, the selected one — the whole reason someone
 * is looking at the chart), then the highest-scoring of the rest. The result
 * is put back in measurement order so the x-axis still reads as "by
 * measurement", not "sorted by magnitude".
 */
function capByRelevance<T extends { idx: number }>(
  rows: T[],
  score: (row: T) => number,
  alwaysKeep: (row: T) => boolean
): T[] {
  if (rows.length <= MAX_CHART_POINTS) return rows
  const kept = rows.filter(alwaysKeep)
  const keptIdx = new Set(kept.map((r) => r.idx))
  const rest = rows
    .filter((r) => !keptIdx.has(r.idx))
    .sort((a, b) => score(b) - score(a))
    .slice(0, Math.max(0, MAX_CHART_POINTS - kept.length))
  return [...kept, ...rest].sort((a, b) => a.idx - b.idx)
}

// The result table has 14 columns of dense monospace text plus a status badge;
// taller than the plain result rows elsewhere. VirtualTableBody needs it fixed.
const BADDATA_ROW_HEIGHT = 37

/** Full post-injection results table */
function ResultsMeasurementTable({ result, geo }: { result: BadDataResult; geo: BadDataGeometryResult | null }) {
  return (
    <TableCard
      label="Result Measurements"
      maxHeight="16rem"
      expandedMaxHeight="80vh"
      exportData={() => ({
        headers: ['#', 'Label', 'z_true', 'z_noisy', 'z_hat', 'r_i', '|r_N|', 'e_U', '|CME_N|', '|CNE|', 'K_ii', 'UI', 'II', 'Status'],
        rows: result.measurements.map((m) => {
          const ii = innovationIndex(m.UI)
          return [
            String(m.idx), m.label, m.z_true.toFixed(4), m.z_noisy.toFixed(4),
            m.z_hat?.toFixed(4) ?? '', m.residual.toFixed(4), Math.abs(m.r_N).toFixed(3),
            m.e_U.toFixed(4), Math.abs(m.CME_N).toFixed(3),
            m.CNE !== undefined ? Math.abs(m.CNE).toFixed(3) : '',
            m.K_diag.toFixed(4), m.UI.toFixed(4),
            Number.isFinite(ii) ? ii.toFixed(3) : 'inf',
            m.isBadData ? (m.isFlagged ? 'INJECTED+FLAGGED' : 'INJECTED') : m.isFlagged ? 'FLAGGED' : '',
          ]
        }),
      })}
    >
        <TableHeader>
          <TableRow>
            <TableHead className="mono text-xs w-6">#</TableHead>
            <TableHead className="mono text-xs">Label</TableHead>
            <TableHead className="mono text-right text-xs">z_true</TableHead>
            <TableHead className="mono text-right text-xs">z_noisy</TableHead>
            <TableHead className="mono text-right text-xs">ẑ (WLS)</TableHead>
            <TableHead className="mono text-right text-xs">r_i</TableHead>
            <TableHead className="mono text-right text-xs font-bold">|r_N|</TableHead>
            <TableHead className="mono text-right text-xs">e_U</TableHead>
            <TableHead className="mono text-right text-xs font-bold">|CME_N|</TableHead>
            <TableHead className="mono text-right text-xs" title="Composed Normalized Error (eq. 20, Bretas & Bretas 2018) — projeção do erro no subespaço do resíduo; usado na correção z_true (multiplicado por σ)">|CNE|</TableHead>
            <TableHead className="mono text-right text-xs">K_ii</TableHead>
            <TableHead className="mono text-right text-xs">UI</TableHead>
            <TableHead className="mono text-right text-xs" title="Innovation Index — II = 1/√UI = √((1-K_ii)/K_ii)">II</TableHead>
            <TableHead className="mono text-xs">Status</TableHead>
          </TableRow>
        </TableHeader>
        {/* Windowed: one row per measurement, and a real feeder has two per
            bus. See VirtualTableBody. */}
        <VirtualTableBody
          items={result.measurements}
          rowHeight={BADDATA_ROW_HEIGHT}
          renderRow={(m) => {
            const ii = innovationIndex(m.UI)
            // For a parameter attack there is no single "the" injected
            // measurement (isBadData stays false for all of them) — flag a
            // measurement as "line-consistent" instead of a false positive
            // when it belongs to the attacked line's own set (flow on that
            // line, or injection at either of its terminal buses).
            const attackedLine = result.parameterAttack
            const isOwnOfAttackedLine = !!attackedLine && (
              m.lineId === attackedLine.lineId ||
              (m.busId != null && (m.busId === attackedLine.fromBus || m.busId === attackedLine.toBus))
            )
            const rowCls = m.isBadData
              ? 'bg-destructive/10'
              : m.isFlagged
              ? (attackedLine ? (isOwnOfAttackedLine ? 'bg-status-good/10' : 'bg-status-warn/10') : 'bg-status-warn/10')
              : ''
            return (
              <TableRow key={m.idx} style={{ height: BADDATA_ROW_HEIGHT }} className={rowCls}>
                <TableCell className="text-xs mono text-muted-foreground">{m.idx}</TableCell>
                <TableCell className="text-xs mono font-medium">{m.label}</TableCell>
                <TableCell className="text-right text-xs mono">{m.z_true.toFixed(4)}</TableCell>
                <TableCell className={`text-right text-xs mono ${m.isBadData ? 'text-destructive font-bold' : ''}`}>
                  {m.z_noisy.toFixed(4)}
                </TableCell>
                <TableCell className="text-right text-xs mono">{m.z_hat?.toFixed(4) ?? '—'}</TableCell>
                <TableCell className="text-right text-xs mono">{m.residual.toFixed(4)}</TableCell>
                <TableCell className={`text-right text-xs mono font-semibold ${Math.abs(m.r_N) > 3 ? 'text-status-warn' : ''}`}>
                  {Math.abs(m.r_N).toFixed(3)}
                </TableCell>
                <TableCell className="text-right text-xs mono text-muted-foreground">{m.e_U.toFixed(4)}</TableCell>
                <TableCell className={`text-right text-xs mono font-semibold ${Math.abs(m.CME_N) > 3 ? 'text-method-ldf' : ''}`}>
                  {Math.abs(m.CME_N).toFixed(3)}
                </TableCell>
                <TableCell className="text-right text-xs mono text-muted-foreground">
                  {m.CNE !== undefined ? Math.abs(m.CNE).toFixed(3) : '—'}
                </TableCell>
                <TableCell className="text-right text-xs mono">
                  <span style={{ color: kiiHex(m.K_diag) }}>{m.K_diag.toFixed(4)}</span>
                </TableCell>
                <TableCell className="text-right text-xs mono">{m.UI.toFixed(4)}</TableCell>
                <TableCell className="text-right text-xs mono text-muted-foreground">{Number.isFinite(ii) ? ii.toFixed(3) : '∞'}</TableCell>
                <TableCell className="text-xs">
                  {m.isBadData && m.isFlagged && <Badge variant="destructive" className="text-[9px] px-1 py-0">INJECTED+FLAGGED</Badge>}
                  {m.isBadData && !m.isFlagged && <Badge variant="outline" className="text-[9px] px-1 py-0 border-destructive/60 text-destructive">INJECTED</Badge>}
                  {!m.isBadData && m.isFlagged && attackedLine && isOwnOfAttackedLine && (
                    <Badge className="text-[9px] px-1 py-0 bg-status-good">LINE-CONSISTENT</Badge>
                  )}
                  {!m.isBadData && m.isFlagged && (!attackedLine || !isOwnOfAttackedLine) && (
                    <Badge className="text-[9px] px-1 py-0 bg-status-warn">FALSE FLAG</Badge>
                  )}
                </TableCell>
              </TableRow>
            )
          }}
        />
    </TableCard>
  )
}

/** "Why was it not detected?" explainer */
function DetectionExplainer({ result }: { result: BadDataResult }) {
  const det = result.pipeline.detected                   // detected_final = still alarming in the last iteration
  const anyFlagged = result.pipeline.flaggedIndices.length > 0
  const converged = !det && anyFlagged                   // detectou, agiu, convergiu = SUCESSO
  const J = result.J_detection_initial
  const th = result.chi2_threshold_initial
  const J_resid = result.J_initial
  const dof_label = result.config.detection === 'cme' ? `m=${result.m}` : `m-n=${result.DOF}`
  const injIdx = result.injectedBadDataIdx
  const injLabel = injIdx != null ? result.measurements[injIdx]?.label : null
  const inj = injIdx != null ? result.measurements[injIdx] : null
  const kii = inj?.K_diag ?? 0
  const correctlyFixed = converged && injIdx != null && result.pipeline.flaggedIndices.includes(injIdx)

  const borderCls = det ? 'border-destructive/50 bg-destructive/5'
                  : converged ? 'border-status-good/50 bg-status-good/5'
                  : 'border-status-warn/50 bg-status-warn/5'

  return (
    <Alert className={`border ${borderCls}`}>
      <AlertDescription className="text-xs space-y-2 mono">
        <div className="font-semibold text-sm flex items-center gap-2">
          {det
            ? <><Warning weight="fill" className="text-destructive w-4 h-4" /> Bad Data ALARMING (did not converge)</>
            : converged
            ? <><CheckCircle weight="fill" className="text-status-good w-4 h-4" /> Bad Data DETECTED &amp; FIXED ✓</>
            : <><Warning weight="fill" className="text-status-warn w-4 h-4" /> Bad Data NOT detected</>}
        </div>
        <div>
          J_detection₀ = <strong>{J.toFixed(3)}</strong> &nbsp;|&nbsp;
          χ²(α={result.config.alpha}, df={dof_label}) = <strong>{th.toFixed(3)}</strong> &nbsp;|&nbsp;
          J {J > th ? '>' : '<'} threshold &nbsp;→ &nbsp;
          <strong>{J > th ? 'triggered' : 'did not trigger'}</strong>
          {result.config.detection === 'cme' && (
            <span className="text-muted-foreground ml-2 text-[10px]">(J_resid = {J_resid.toFixed(3)}, ref.)</span>
          )}
        </div>
        {converged && (
          <div className="text-status-good space-y-1">
            <div>✓ Pipeline {result.config.detection}+{result.config.identification}+{result.config.correction} detected, acted ({result.pipeline.actions.join('→')}), and converged (J_final={result.pipeline.J_final.toFixed(3)} &lt; threshold={result.pipeline.threshold.toFixed(3)}).</div>
            <div>Flagged index/indices: <strong>{result.pipeline.flaggedIndices.join(', ')}</strong>
              {correctlyFixed && ' — correct ✓'}
              {!correctlyFixed && injIdx != null && result.pipeline.flaggedIndices.length > 0 && ' — wrong index ✗'}
            </div>
          </div>
        )}
        {!det && !converged && injLabel && (
          <div className="text-status-warn space-y-1">
            <div>⚠ Did not trigger: J_detection ({J.toFixed(2)}) &lt; threshold ({th.toFixed(2)}).</div>
            <div>Attacked measurement: <strong>{injLabel}</strong> &nbsp;(K_ii = {kii.toFixed(4)},&nbsp; UI = {inj?.UI.toFixed(4)})</div>
            {kii > K_CROSSOVER && (
              <div className="text-destructive">⚠ K_ii &gt; {K_CROSSOVER} → error is masked in e_U. Use CME detection to overcome masking.</div>
            )}
            {kii > 0.5 && kii <= K_CROSSOVER && (
              <div>K_ii between 0.5 and {K_CROSSOVER} — medium risk. Try a larger magnitude or CME detection.</div>
            )}
            {kii <= 0.5 && (
              <div>Low K_ii — magnitude may be too small. Try ≥ 7×σ.</div>
            )}
          </div>
        )}
        {det && (
          <div className="text-destructive space-y-1">
            <div>⚠ Pipeline did not converge in {result.pipeline.nIterations} iterations. Flagged: <strong>{result.pipeline.flaggedIndices.join(', ') || '—'}</strong></div>
          </div>
        )}
      </AlertDescription>
    </Alert>
  )
}

// ─── main component ──────────────────────────────────────────────────────────

interface BadDataAnalyticsTabProps {
  topology: Topology
}

export function BadDataAnalyticsTab({ topology }: BadDataAnalyticsTabProps) {
  // ── config state ────────────────────────────────────────────────────────
  const [noiseLevel, setNoiseLevel] = useState(0.01)
  const [sigmaMin, setSigmaMin] = useState(0.001)   // mesmo que o notebook: SIGMA_MIN = 0.001
  // z = z_true + noise (default) vs z = z_true exactly. Default true matches
  // Bretas et al. (2017)'s own practice (noise added in every simulation) and
  // general SE validation practice; turn off to isolate one injected effect
  // (e.g. a pure parameter error) from noise variance, or to reproduce a
  // noise-free notebook case exactly — see BadDataRequest.add_noise in api.ts.
  const [addNoise, setAddNoise] = useState(true)
  const [seed, setSeed] = useState('42')
  const [alpha, setAlpha] = useState(0.05)
  const [zTrueMethod, setZTrueMethod] = useState<'topology_angles' | 'rundcpp'>('topology_angles')
  // 'dc': DC-linear, P injection only. 'ac': full AC set (P, Q, |V|, θ for
  // PMU) linearized at the true AC operating point — mirrors State
  // Estimation's dc-wls/ac-gn-wls choice. z_true_method is ignored when 'ac'.
  const [method, setMethod] = useState<'dc' | 'ac'>('dc')

  // ── geometry state ──────────────────────────────────────────────────────
  const [geo, setGeo] = useState<BadDataGeometryResult | null>(null)
  const [geoLoading, setGeoLoading] = useState(false)
  const [geoError, setGeoError] = useState<string | null>(null)

  // ── attack config ───────────────────────────────────────────────────────
  const [selectedMeasIdx, setSelectedMeasIdx] = useState<number | null>(null)
  const [badDataMag, setBadDataMag] = useState(7.0)  // × sigma
  // What gets attacked: a measurement (z), a line parameter (H/h(x)), or
  // both at once — 'parameter'/'both' need method='ac' (nonlinear pipeline,
  // rebuilt every iteration) — see ac_bad_data.run_ac_bad_data_pipeline() /
  // docs/estudos/estimacao_estado/literatura/bretas2017_malicious_data_innovation.md.
  const [attackTarget, setAttackTarget] = useState<'measurement' | 'parameter' | 'both'>('measurement')
  const [attackLineId, setAttackLineId] = useState<number | null>(topology.lines[0]?.id ?? null)
  // Assumed relative uncertainty ("sigma") of a line parameter — the article
  // (Bretas et al. 2017) only defines k·sigma for measurement error
  // (eq. 18-19), not for a parameter, so this is an explicit assumption.
  const [paramSigmaPct, setParamSigmaPct] = useState(0.01)
  const [paramNSigmas, setParamNSigmas] = useState(10.0)
  const [paramSymmetric, setParamSymmetric] = useState(true)
  const [detection, setDetection] = useState<'residual' | 'cme'>('residual')
  const [identification, setIdentification] = useState<'lnr' | 'cme' | 'by_line'>('lnr')
  const [correction, setCorrection] = useState<'remove' | 'ztrue' | 'by_parameter'>('remove')

  // ── results state ───────────────────────────────────────────────────────
  const [result, setResult] = useState<BadDataResult | null>(null)
  // Same request as `result` but attack_target forced to 'measurement' and
  // inject_bad_data:false — a genuinely clean run (no measurement AND no
  // parameter attack; the backend only gates the parameter attack on
  // attack_target, not on inject_bad_data — see baddata.py) with the same
  // seed, used as the "before" reference for the paired/delta CME_N chart.
  const [baseline, setBaseline] = useState<BadDataResult | null>(null)
  const [cmeView, setCmeView] = useState<'paired' | 'delta'>('paired')
  const [allResults, setAllResults] = useState<BadDataResult[] | null>(null)
  const [running, setRunning] = useState<'single' | 'all' | null>(null)
  const [runError, setRunError] = useState<string | null>(null)

  // ── view toggles ────────────────────────────────────────────────────────
  const [showHeatmap, setShowHeatmap] = useState(false)
  const [showIncidence, setShowIncidence] = useState(false)

  const seedNum = seed.trim() !== '' ? parseInt(seed) : null

  // ── actions ─────────────────────────────────────────────────────────────

  async function analyzeGeometry() {
    setGeoLoading(true)
    setGeoError(null)
    setGeo(null)
    setResult(null)
    setAllResults(null)
    try {
      const r = await runBadDataGeometry({ topology, method, noise_level: noiseLevel, sigma_min: sigmaMin, seed: seedNum, alpha, z_true_method: zTrueMethod })
      setGeo(r)
      // auto-select measurement with highest UI
      const maxUI = r.measurements.reduce((best, m) => m.UI > best.UI ? m : best, r.measurements[0])
      setSelectedMeasIdx(maxUI.idx)
    } catch (e: any) {
      setGeoError(e.message)
    } finally {
      setGeoLoading(false)
    }
  }

  const attackReady =
    (attackTarget === 'measurement' && selectedMeasIdx !== null) ||
    (attackTarget === 'parameter' && attackLineId !== null) ||
    (attackTarget === 'both' && selectedMeasIdx !== null && attackLineId !== null)

  async function runDetection() {
    if (!attackReady) return
    setRunning('single')
    setRunError(null)
    setResult(null)
    setBaseline(null)
    try {
      const sharedReq = {
        topology, method, noise_level: noiseLevel, sigma_min: sigmaMin, seed: seedNum,
        bad_data_index: selectedMeasIdx, bad_data_magnitude: badDataMag,
        attack_line_id: attackLineId, attack_param_sigma_pct: paramSigmaPct,
        attack_param_n_sigmas: paramNSigmas, attack_param_symmetric: paramSymmetric,
        detection, identification, correction, alpha, z_true_method: zTrueMethod,
        add_noise: addNoise,
      }
      const [r, b] = await Promise.all([
        runBadDataDetection({ ...sharedReq, attack_target: attackTarget, inject_bad_data: true }),
        // Clean reference run, same seed → same noise draw for every
        // measurement, just without either attack applied.
        runBadDataDetection({ ...sharedReq, attack_target: 'measurement', inject_bad_data: false }),
      ])
      setResult(r)
      setBaseline(b)
    } catch (e: any) {
      setRunError(e.message)
    } finally {
      setRunning(null)
    }
  }

  async function runAllCombos() {
    if (selectedMeasIdx === null) return
    setRunning('all')
    setRunError(null)
    setAllResults(null)
    setResult(null)
    setBaseline(null)
    try {
      const sharedReq = {
        topology, method, noise_level: noiseLevel, sigma_min: sigmaMin, seed: seedNum,
        attack_target: 'measurement' as const,
        bad_data_index: selectedMeasIdx, bad_data_magnitude: badDataMag,
        alpha, z_true_method: zTrueMethod, add_noise: addNoise,
      }
      const [results, b] = await Promise.all([
        Promise.all(
          COMBOS.map((c) => runBadDataDetection({
            ...sharedReq, inject_bad_data: true,
            detection: c.detection, identification: c.identification, correction: c.correction,
          }))
        ),
        // Same seed, no attack. CME_N/K_ii/r_N in `measurements[]` come from
        // the initial solve before the pipeline loop (baddata.py), so they're
        // identical across all 8 combos — one clean run pairs against any of
        // them, no need to repeat it 8×.
        runBadDataDetection({ ...sharedReq, inject_bad_data: false }),
      ])
      setAllResults(results)
      // Per-measurement geometry/CME_N is combo-invariant (see above); only
      // isFlagged (bar color) can differ by combo. Pick the first combo as
      // the representative so Step 3b's charts — including the new
      // paired/delta CME_N comparison — render for "Run All 8 Combos" too,
      // not just single "Run Pipeline".
      setResult(results[0])
      setBaseline(b)
    } catch (e: any) {
      setRunError(e.message)
    } finally {
      setRunning(null)
    }
  }

  // ── derived chart data ───────────────────────────────────────────────────

  // All four are memoized and capped. Recharts emits one SVG element per bar
  // (plus a <Cell> per bar for the per-point colour), so a case with two
  // meters per bus on a few-thousand-bus feeder asked it to lay out tens of
  // thousands of elements across five charts. It is also unreadable long
  // before it is slow: at 13k bars in an 800px plot each bar is well under a
  // tenth of a pixel.
  //
  // The cap keeps the measurements that carry the signal for each chart (worst
  // normalized residual, worst composed error, least redundant), then restores
  // the original measurement order, so the x-axis still reads as "by
  // measurement" rather than "sorted by magnitude".

  const kiiChartData = useMemo(
    () =>
      capByRelevance(
        (geo?.measurements ?? []).map((m) => ({
          idx: m.idx,
          label: m.label,
          K_ii: m.K_diag,
          UI: m.UI,
          fill: kiiHex(m.K_diag),
          isSelected: m.idx === selectedMeasIdx,
        })),
        // Least redundant first: a low K_ii is the critical measurement.
        (d) => -d.K_ii,
        (d) => d.isSelected
      ),
    [geo, selectedMeasIdx]
  )

  const lnrChartData = useMemo(
    () =>
      capByRelevance(
        (result?.measurements ?? []).map((m) => ({
          idx: m.idx,
          label: m.label,
          '|r_N|': Math.abs(m.r_N),
          isBadData: m.isBadData,
          isFlagged: m.isFlagged,
          // LNR series: destructive/warn/info palette (matches kiiHex risk tiers)
          fill: m.isBadData ? 'var(--color-destructive)' : m.isFlagged ? 'var(--color-status-warn)' : 'var(--color-status-info)',
        })),
        (d) => d['|r_N|'],
        (d) => d.isBadData || d.isFlagged
      ),
    [result]
  )

  const cmeChartData = useMemo(() => {
    const baselineCmeByIdx = new Map(baseline?.measurements.map((m) => [m.idx, Math.abs(m.CME_N)]) ?? [])
    return capByRelevance(
      (result?.measurements ?? []).map((m) => {
        const before = baselineCmeByIdx.get(m.idx) ?? 0
        const after = Math.abs(m.CME_N)
        return {
          idx: m.idx,
          label: m.label,
          CME_N_before: before,
          CME_N_after: after,
          delta: after - before,
          isBadData: m.isBadData,
          isFlagged: m.isFlagged,
          fill: m.isBadData ? 'var(--color-destructive)' : m.isFlagged ? 'var(--color-status-warn)' : 'var(--color-method-ldf)',
        }
      }),
      (d) => Math.max(d.CME_N_after, d.CME_N_before),
      (d) => d.isBadData || d.isFlagged
    )
  }, [result, baseline])

  const scatterData = useMemo(
    () =>
      capByRelevance(
        (result?.measurements ?? []).map((m) => ({
          idx: m.idx,
          label: m.label,
          rN: Math.abs(m.r_N),
          cmeN: Math.abs(m.CME_N),
          isBadData: m.isBadData,
          isFlagged: m.isFlagged,
        })),
        (d) => Math.max(d.rN, d.cmeN),
        (d) => d.isBadData || d.isFlagged
      ),
    [result]
  )

  // Loop, not Math.max(...array): the spread passes one argument per element.
  const scatterMax = scatterData.reduce((max, d) => Math.max(max, d.rN, d.cmeN), 0)

  // How many measurements the charts leave out, for the note under them.
  const chartOmitted = Math.max(0, (result?.measurements.length ?? 0) - lnrChartData.length)


  const pipelineHistory = result?.pipeline.history ?? []

  const selectedMeas = geo?.measurements.find((m) => m.idx === selectedMeasIdx)

  // ────────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">

      {/* ═══ CONFIG BAR ═══════════════════════════════════════════════════ */}
      <Card>
        <CardContent className="p-4 space-y-3">
          {/* Row 1: noise params + analyze button */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 items-end">
            <div className="space-y-1">
              <Label className="text-xs">Noise σ (relative)</Label>
              <Input type="number" value={noiseLevel} step={0.005} min={0.001} max={0.2}
                onChange={(e) => setNoiseLevel(parseFloat(e.target.value))} className="h-8 text-xs" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">σ_min (floor)</Label>
              <Input type="number" value={sigmaMin} step={0.0005} min={1e-6} max={0.1}
                onChange={(e) => setSigmaMin(parseFloat(e.target.value))} className="h-8 text-xs mono" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Seed</Label>
              <Input value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="42" className="h-8 text-xs" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">α (chi² detection)</Label>
              <Input type="number" value={alpha} step={0.01} min={0.001} max={0.2}
                onChange={(e) => setAlpha(parseFloat(e.target.value))} className="h-8 text-xs" />
            </div>
            <Button onClick={analyzeGeometry} disabled={geoLoading} className="w-full">
              {geoLoading
                ? <><Spinner className="animate-spin w-4 h-4 mr-1" />Analyzing…</>
                : <><MagnifyingGlass weight="fill" className="w-4 h-4 mr-1" />Step 1 — Analyze Geometry</>}
            </Button>
          </div>
          {/* Row 2: measurement model selector */}
          <div className="flex items-center gap-3 pt-1 border-t border-border">
            <Info className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            <Label className="text-xs text-muted-foreground shrink-0">Measurement model:</Label>
            <Select value={method} onValueChange={(v) => {
              setMethod(v as typeof method)
              if (v === 'dc') {
                // parameter attacks and by_line/by_parameter need the AC nonlinear pipeline
                setAttackTarget('measurement')
                if (identification === 'by_line') setIdentification('lnr')
                if (correction === 'by_parameter') setCorrection('remove')
              }
            }}>
              <SelectTrigger className="h-7 text-xs flex-1 max-w-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="dc">
                  <span className="font-medium">DC-linear</span>
                  <span className="text-muted-foreground text-[10px] ml-2">P injection only, one row per meter</span>
                </SelectItem>
                <SelectItem value="ac">
                  <span className="font-medium">AC (nonlinear Gauss-Newton)</span>
                  <span className="text-muted-foreground text-[10px] ml-2">P, Q, |V|, θ (PMU) — supports parameter attacks</span>
                </SelectItem>
              </SelectContent>
            </Select>
            <span className="text-[10px] text-muted-foreground hidden sm:block">
              {method === 'ac'
                ? 'Nonlinear WLS (Gauss-Newton), rebuilt from scratch every pipeline iteration — supports measurement and/or line-parameter attacks'
                : 'Bbus/Bf linear DC model — only P injection is observed, even at PMU/SCADA buses; measurement attacks only'}
            </span>
          </div>
          {/* Row 2b: z = z_true + noise vs z = z_true exactly. Default on — matches
              Bretas et al. (2017)'s own practice; turn off to isolate one injected
              effect from noise variance, or to reproduce a noise-free notebook case.
              Scope: only Step 2 (detection/identification/correction pipeline) reads
              this flag — see BadDataRequest.add_noise in api.ts. Step 1 — Analyze
              Geometry below (K_ii/UI/II) never reads it: those depend only on H and
              W=diag(1/σ²), never on z or noise (hat-matrix theory, Bretas et al.
              2013/2018), so toggling this checkbox is expected to leave Step 1's
              table/heatmaps completely unchanged. */}
          <div className="flex items-center gap-3 pt-1 border-t border-border">
            <Info className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            <label className="flex items-center gap-1.5 cursor-pointer text-xs">
              <input type="checkbox" checked={addNoise} onChange={(e) => setAddNoise(e.target.checked)} className="h-3.5 w-3.5" />
              Add measurement noise (z = z_true + N(0,σ))
            </label>
            <span className="text-[10px] text-muted-foreground hidden sm:block">
              {addNoise
                ? 'Standard practice — σ is used both as WLS weight and as the noise scale. Affects Step 2 (pipeline) only — Step 1 geometry (K_ii/UI/II) is noise-invariant by construction.'
                : 'z = z_true exactly — σ only enters as the WLS weight/threshold unit; isolates the injected attack effect. Affects Step 2 (pipeline) only — Step 1 geometry is unaffected either way.'}
            </span>
          </div>
          {/* Row 3: operating point selector — DC only, AC always solves its own fresh power flow */}
          <div className={`flex items-center gap-3 pt-1 border-t border-border ${method === 'ac' ? 'opacity-40 pointer-events-none' : ''}`}>
            <Info className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            <Label className="text-xs text-muted-foreground shrink-0">Operating point (z_true):</Label>
            <Select value={zTrueMethod} onValueChange={(v) => setZTrueMethod(v as typeof zTrueMethod)} disabled={method === 'ac'}>
              <SelectTrigger className="h-7 text-xs flex-1 max-w-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="topology_angles">
                  <span className="font-medium">AC → DC</span>
                  <span className="text-muted-foreground text-[10px] ml-2">z = H·θ_AC + c  (replica o notebook, runpp)</span>
                </SelectItem>
                <SelectItem value="rundcpp">
                  <span className="font-medium">DC self-consistent</span>
                  <span className="text-muted-foreground text-[10px] ml-2">z = DC flows (rundcpp residuals)</span>
                </SelectItem>
              </SelectContent>
            </Select>
            <span className="text-[10px] text-muted-foreground hidden sm:block">
              {method === 'ac'
                ? 'Ignored in AC mode — always a fresh AC power flow'
                : zTrueMethod === 'topology_angles'
                ? 'AC power-flow angles used in the linear DC model — exactly mirrors the notebook'
                : 'Pure DC operating point — self-consistent with the linear model'}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Rendered after the noise/σ_min/seed inputs above (not before) so cause
          precedes effect: this preview always draws one illustrative noisy
          sample from the noise σ/σ_min/seed set above, independent of the "Add
          measurement noise" checkbox (which only gates Step 2's actual run). */}
      <MeasurementsSummaryCard
        topology={topology}
        estimationMethod={method === 'ac' ? 'ac-gn-wls' : 'dc-wls'}
        groundTruth={method === 'ac' || zTrueMethod === 'topology_angles' ? 'ac' : 'dc'}
        noiseLevel={noiseLevel}
        sigmaMin={sigmaMin}
        seed={seedNum}
      />

      {geoError && (
        <Alert variant="destructive"><AlertDescription className="text-xs mono">{geoError}</AlertDescription></Alert>
      )}

      {/* ═══ STEP 1: GEOMETRY EXPLORER ════════════════════════════════════ */}
      {geo && (
        <Card>
          <CardHeader className="p-4 pb-2">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div>
                <CardTitle className="text-sm flex items-center gap-2">
                  <ChartBar weight="fill" className="text-accent" />
                  Step 1 — Measurement Geometry (Bretas 2013)
                </CardTitle>
                <CardDescription className="text-xs space-y-0.5">
                  <span className="block">
                    m={geo.m} measurements · n={geo.n} states · DoF={geo.DOF} &nbsp;|&nbsp;
                    χ²(α={geo.alpha}, df={geo.DOF}) = <strong>{geo.chi2_threshold}</strong> &nbsp;|&nbsp;
                    J_baseline = <strong>{geo.J_baseline}</strong>
                    {geo.J_baseline < geo.chi2_threshold && <span className="text-status-good ml-1">✓ clean</span>}
                  </span>
                  {geo.solver_info && (
                    <span className="block text-[10px] mono text-muted-foreground/80 border-l-2 border-accent/40 pl-2 mt-1">
                      <span className="font-semibold">Solver:</span> {geo.solver_info.z_true_formula}
                      &nbsp;·&nbsp;
                      <span className="font-semibold">Op.&nbsp;point:</span> {geo.solver_info.operating_point}
                      &nbsp;·&nbsp;
                      <span className="font-semibold">Noise:</span> {geo.solver_info.noise_model}
                    </span>
                  )}
                </CardDescription>
              </div>
              <div className="flex gap-2 text-xs mono">
                <Badge variant="outline" className="gap-1">
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: 'var(--color-status-info)', display: 'inline-block' }} />
                  LOW (K &lt; 0.5)
                </Badge>
                <Badge variant="outline" className="gap-1">
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: 'var(--color-status-warn)', display: 'inline-block' }} />
                  MED (0.5–0.618)
                </Badge>
                <Badge variant="outline" className="gap-1">
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: 'var(--color-destructive)', display: 'inline-block' }} />
                  HIGH (&gt;0.618)
                </Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-4 space-y-4">
            {/* K_ii + UI charts side by side */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <p className="text-xs mono text-muted-foreground mb-1">K_ii — influence of each measurement (hat-matrix diagonal)</p>
                <ChartContainer config={kiiChartConfig} className="aspect-auto h-44 w-full">
                  <BarChart data={kiiChartData} margin={{ top: 4, right: 6, left: -20, bottom: 40 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis dataKey="label" tick={{ fontSize: 8 }} angle={-35} textAnchor="end" height={50} />
                    <YAxis tick={{ fontSize: 8 }} domain={[0, 1]} />
                    <ChartTooltip content={<ChartTooltipContent formatter={(v) => Number(v).toFixed(4)} />} />
                    <ReferenceLine y={0.618} stroke="var(--color-destructive)" strokeDasharray="4 2" label={{ value: '0.618', fontSize: 8, fill: 'var(--color-destructive)' }} />
                    <ReferenceLine y={0.5} stroke="var(--color-status-warn)" strokeDasharray="4 2" label={{ value: '0.5', fontSize: 8, fill: 'var(--color-status-warn)' }} />
                    <Bar dataKey="K_ii" radius={[2, 2, 0, 0]}>
                      {kiiChartData.map((d, i) => (
                        <Cell key={i} fill={d.fill} opacity={d.isSelected ? 1 : 0.75} stroke={d.isSelected ? 'var(--color-background)' : 'none'} strokeWidth={2} />
                      ))}
                    </Bar>
                  </BarChart>
                </ChartContainer>
              </div>
              <div>
                <p className="text-xs mono text-muted-foreground mb-1">UI = K_ii / (1−K_ii) — Undetectability Index</p>
                <ChartContainer config={uiChartConfig} className="aspect-auto h-44 w-full">
                  <BarChart data={kiiChartData} margin={{ top: 4, right: 6, left: -20, bottom: 40 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis dataKey="label" tick={{ fontSize: 8 }} angle={-35} textAnchor="end" height={50} />
                    <YAxis tick={{ fontSize: 8 }} />
                    <ChartTooltip content={<ChartTooltipContent formatter={(v) => Number(v).toFixed(4)} />} />
                    <Bar dataKey="UI" radius={[2, 2, 0, 0]}>
                      {kiiChartData.map((d, i) => (
                        <Cell key={i} fill={d.fill} opacity={d.isSelected ? 1 : 0.75} stroke={d.isSelected ? 'var(--color-background)' : 'none'} strokeWidth={2} />
                      ))}
                    </Bar>
                  </BarChart>
                </ChartContainer>
              </div>
            </div>

            {/* Measurement table */}
            <div>
              <p className="text-xs mono text-muted-foreground mb-1">
                Click a row to select the measurement to attack
              </p>
              <MeasurementTable measurements={geo.measurements} selectedIdx={selectedMeasIdx} onSelect={setSelectedMeasIdx} />
            </div>

            {/* HAT matrix heatmap toggle */}
            <div>
              <Button variant="outline" size="sm" className="text-xs" onClick={() => setShowHeatmap(!showHeatmap)}>
                {showHeatmap ? '▼' : '▶'} HAT Matrix K (full heatmap)
              </Button>
              {showHeatmap && (
                <div className="mt-3 border rounded-md p-3">
                  <p className="text-xs mono text-muted-foreground mb-2">
                    |K[i,j]| — diagonal = K_ii (red); off-diagonal = coupling between measurements
                  </p>
                  <HatMatrixHeatmap K={geo.K_matrix} labels={geo.labels} />
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ═══ STEP 2: ATTACK CONFIG ════════════════════════════════════════ */}
      {geo && (
        <Card>
          <CardHeader className="p-4 pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Warning weight="fill" className="text-status-warn" />
              Step 2 — Attack Configuration
            </CardTitle>
            <CardDescription className="text-xs">
              Configure the injected error and detection pipeline
            </CardDescription>
          </CardHeader>
          <CardContent className="p-4 space-y-4">
            {/* Attack target selector */}
            <div className="flex items-center gap-3 flex-wrap">
              <Label className="text-xs shrink-0">Attack target:</Label>
              <Select value={attackTarget} onValueChange={(v) => setAttackTarget(v as typeof attackTarget)}>
                <SelectTrigger className="h-8 text-xs w-56"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="measurement" className="text-xs">Measurement (z)</SelectItem>
                  <SelectItem value="parameter" className="text-xs" disabled={method !== 'ac'}>Line parameter (H/h(x)) — AC only</SelectItem>
                  <SelectItem value="both" className="text-xs" disabled={method !== 'ac'}>Both — AC only</SelectItem>
                </SelectContent>
              </Select>
              <span className="text-[10px] text-muted-foreground">
                {attackTarget === 'measurement' && 'Classic gross error: one z shifted by k×σ.'}
                {attackTarget === 'parameter' && "r/x/c of a line wrong in the estimator's model, measurements stay clean — Bretas et al. 2017."}
                {attackTarget === 'both' && "Arturo's ambiguity check: several measurements shifted at once can look like a parameter error — compare here."}
              </span>
            </div>

            {/* Selected measurement info */}
            {attackTarget !== 'parameter' && (
              selectedMeas ? (
                <div className="flex flex-wrap gap-2 items-center p-2 rounded-md border border-dashed border-accent/50 bg-accent/5 text-xs mono">
                  <span className="font-semibold">Target:</span>
                  <Badge variant="default" className="text-xs">{selectedMeas.label}</Badge>
                  <span>K_ii = <strong style={{ color: kiiHex(selectedMeas.K_diag) }}>{selectedMeas.K_diag.toFixed(4)}</strong></span>
                  <span>UI = <strong>{selectedMeas.UI.toFixed(4)}</strong></span>
                  <span>II = <strong>{Number.isFinite(innovationIndex(selectedMeas.UI)) ? innovationIndex(selectedMeas.UI).toFixed(3) : '∞'}</strong></span>
                  <span>σ = {selectedMeas.sigma.toFixed(4)} pu</span>
                  <span>z_true = {selectedMeas.z_true.toFixed(4)} pu</span>
                  {selectedMeas.K_diag > K_CROSSOVER && (
                    <Badge variant="destructive" className="text-[10px]">⚠ HIGH MASKING RISK</Badge>
                  )}
                </div>
              ) : (
                <div className="text-xs text-muted-foreground italic">← select a measurement in the table above</div>
              )
            )}

            {/* Line selector for parameter attacks */}
            {attackTarget !== 'measurement' && (
              <div className="flex flex-wrap gap-2 items-center p-2 rounded-md border border-dashed border-status-warn/50 bg-status-warn/5 text-xs mono">
                <span className="font-semibold">Line:</span>
                <Select value={attackLineId?.toString() ?? ''} onValueChange={(v) => setAttackLineId(parseInt(v))}>
                  <SelectTrigger className="h-7 text-xs w-40"><SelectValue placeholder="select a line" /></SelectTrigger>
                  <SelectContent>
                    {topology.lines.map((l) => (
                      <SelectItem key={l.id} value={l.id.toString()} className="text-xs">
                        L{l.id} (bus {l.from} ↔ bus {l.to})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <label className="flex items-center gap-1 cursor-pointer">
                  <input type="checkbox" checked={paramSymmetric} onChange={(e) => setParamSymmetric(e.target.checked)} className="h-3 w-3" />
                  symmetric (r, x, c)
                </label>
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {/* Error magnitude — measurement */}
              {attackTarget !== 'parameter' && (
                <div className="space-y-2">
                  <Label className="text-xs">
                    Measurement error magnitude: <strong>{badDataMag.toFixed(1)}×σ</strong>
                    {selectedMeas && <span className="text-muted-foreground"> = {(badDataMag * selectedMeas.sigma).toFixed(4)} pu</span>}
                  </Label>
                  <Slider min={1} max={20} step={0.5} value={[badDataMag]}
                    onValueChange={([v]) => setBadDataMag(v)} className="w-full" />
                  <div className="flex justify-between text-xs text-muted-foreground mono">
                    <span>1×σ (small)</span><span>10×σ (large)</span><span>20×σ (extreme)</span>
                  </div>
                </div>
              )}

              {/* Parameter error magnitude */}
              {attackTarget !== 'measurement' && (
                <div className="space-y-2">
                  <Label className="text-xs">
                    Parameter error magnitude: <strong>{paramNSigmas.toFixed(1)}×σ_param</strong>
                    {' '}= <strong>{(paramNSigmas * paramSigmaPct * 100).toFixed(1)}%</strong> on r/x{paramSymmetric ? '/c' : ''}
                  </Label>
                  <Slider min={1} max={30} step={1} value={[paramNSigmas]}
                    onValueChange={([v]) => setParamNSigmas(v)} className="w-full" />
                  <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                    <span>σ_param (assumed line-parameter uncertainty):</span>
                    <Input type="number" value={paramSigmaPct} step={0.005} min={0.001} max={0.2}
                      onChange={(e) => setParamSigmaPct(parseFloat(e.target.value))} className="h-6 w-20 text-xs mono" />
                    <span>(no standard value in the article — Bretas et al. 2017 only defines k·σ for measurement error)</span>
                  </div>
                </div>
              )}

              {/* Pipeline selectors */}
              <div className={`space-y-2 ${attackTarget === 'both' ? 'sm:col-span-2' : ''}`}>
                <div className="grid grid-cols-3 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">Detection</Label>
                    <Select value={detection} onValueChange={(v) => setDetection(v as any)}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="residual" className="text-xs">χ² Residual</SelectItem>
                        <SelectItem value="cme" className="text-xs">χ² CME</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Identification</Label>
                    <Select value={identification} onValueChange={(v) => setIdentification(v as any)}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="lnr" className="text-xs">LNR</SelectItem>
                        <SelectItem value="cme" className="text-xs">CME_N</SelectItem>
                        <SelectItem value="by_line" className="text-xs" disabled={method !== 'ac'}>By line (AC) — p. 213</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Correction</Label>
                    <Select value={correction} onValueChange={(v) => setCorrection(v as any)}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="remove" className="text-xs">Remove</SelectItem>
                        <SelectItem value="ztrue" className="text-xs">Replace z_true (CNE)</SelectItem>
                        <SelectItem value="by_parameter" className="text-xs" disabled={identification !== 'by_line'}>By parameter (eq. 16)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                {correction === 'by_parameter' && identification !== 'by_line' && (
                  <p className="text-[10px] text-destructive">correction='by_parameter' requires identification='By line'.</p>
                )}
              </div>
            </div>

            {/* Run buttons */}
            <div className="flex gap-2 flex-wrap">
              <Button onClick={runDetection}
                disabled={!attackReady || running !== null}
                className="flex-1 sm:flex-none">
                {running === 'single'
                  ? <><Spinner className="animate-spin w-4 h-4 mr-1" />Running…</>
                  : <><Play weight="fill" className="w-4 h-4 mr-1" />Run Pipeline</>}
              </Button>
              <Button variant="outline" onClick={runAllCombos}
                disabled={attackTarget !== 'measurement' || selectedMeasIdx === null || running !== null}
                title={attackTarget !== 'measurement' ? 'The fixed 2×2×2 grid only compares measurement-attack combos' : undefined}
                className="flex-1 sm:flex-none">
                {running === 'all'
                  ? <><Spinner className="animate-spin w-4 h-4 mr-1" />Running all 8…</>
                  : <><Lightning weight="fill" className="w-4 h-4 mr-1" />Run All 8 Combos</>}
              </Button>
            </div>

            {runError && <Alert variant="destructive"><AlertDescription className="text-xs mono">{runError}</AlertDescription></Alert>}
          </CardContent>
        </Card>
      )}

      {/* ═══ STEP 3: SINGLE PIPELINE RESULTS ══════════════════════════════ */}
      {result && (
        <div className="space-y-4">

          {/* Detection explainer */}
          <Card>
            <CardHeader className="p-4 pb-2">
              <CardTitle className="text-sm">Step 3a — Detection Result (χ² Test)</CardTitle>
            </CardHeader>
            <CardContent className="p-4 space-y-3">
              <DetectionExplainer result={result} />

              {/* J vs threshold bar chart — capped width + explicit bar/gap sizing so
                  3 categories don't get stretched thin across the full card width */}
              <div className="max-w-xs mx-auto">
                <ChartContainer config={jThresholdChartConfig} className="aspect-auto h-40 w-full">
                  <BarChart
                    data={[
                      { name: 'J_detection₀', value: result.J_detection_initial, fill: result.J_detection_initial > result.chi2_threshold_initial ? 'var(--color-destructive)' : 'var(--color-status-info)' },
                      { name: 'J_final', value: result.pipeline.J_final, fill: result.pipeline.J_final > result.pipeline.threshold ? 'var(--color-destructive)' : 'var(--color-status-good)' },
                      { name: 'χ² threshold₀', value: result.chi2_threshold_initial, fill: 'var(--color-muted-foreground)' },
                    ]}
                    margin={{ top: 4, right: 10, left: -10, bottom: 5 }}
                    barCategoryGap="20%"
                  >
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <ChartTooltip content={<ChartTooltipContent formatter={(v) => Number(v).toFixed(3)} />} />
                    <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={56}>
                      {[result.J_detection_initial, result.pipeline.J_final, result.chi2_threshold_initial].map((_, i) => (
                        <Cell key={i} fill={i === 0 ? (result.J_detection_initial > result.chi2_threshold_initial ? 'var(--color-destructive)' : 'var(--color-status-info)') : i === 1 ? (result.pipeline.J_final > result.pipeline.threshold ? 'var(--color-destructive)' : 'var(--color-status-good)') : 'var(--color-muted-foreground)'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ChartContainer>
              </div>
            </CardContent>
          </Card>

          {/* Structural incidence matrix (AC only) — purely structural, same
              regardless of any attack; precedes the ranking below which
              aggregates it against the observed CME_N pattern. */}
          {result.structuralIncidence && result.structuralIncidenceLines && (
            <Card>
              <CardHeader className="p-4 pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <ChartBar weight="fill" className="text-accent" />
                  Step 3a1 — Structural Incidence Matrix (measurement × line)
                </CardTitle>
                <CardDescription className="text-xs">
                  Which measurements are "own" to each line (flow on both sides + injections at its two terminal buses) — purely structural, precomputable before running anything (p. 213, Bretas et al. 2017).
                </CardDescription>
              </CardHeader>
              <CardContent className="p-4">
                <Button variant="outline" size="sm" className="text-xs" onClick={() => setShowIncidence(!showIncidence)}>
                  {showIncidence ? '▼' : '▶'} Incidence matrix ({result.measurements.length}×{result.structuralIncidenceLines.length})
                </Button>
                {showIncidence && (
                  <div className="mt-3 border rounded-md p-3">
                    <IncidenceHeatmap
                      matrix={result.structuralIncidence}
                      rowLabels={result.measurements.map((m) => m.label)}
                      colLabels={result.structuralIncidenceLines}
                    />
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Parameter attack / correction summary + line ranking (AC only) */}
          {result.lineRanking && (
            <Card>
              <CardHeader className="p-4 pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Lightning weight="fill" className="text-status-warn" />
                  Step 3a2 — Line Signature Ranking (p. 213, Bretas et al. 2017)
                </CardTitle>
                <CardDescription className="text-xs">
                  Fraction of each line's "own" measurements (flow on both sides + injections on its two terminal buses) above the CME_N threshold — a parameter attack spreads across several of a line's own measurements, unlike an isolated measurement attack.
                </CardDescription>
              </CardHeader>
              <CardContent className="p-4 space-y-3">
                {result.parameterAttack && (
                  <Alert className="border-status-warn/50 bg-status-warn/5">
                    <AlertDescription className="text-xs mono space-y-1">
                      <div className="font-semibold">
                        Injected parameter attack — L{result.parameterAttack.lineId} (bus {result.parameterAttack.fromBus} ↔ bus {result.parameterAttack.toBus}), factor ×{result.parameterAttack.factor.toFixed(4)}
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        <span>r: {result.parameterAttack.trueParams.r.toFixed(5)} → <strong className="text-destructive">{result.parameterAttack.wrongParams.r.toFixed(5)}</strong></span>
                        <span>x: {result.parameterAttack.trueParams.x.toFixed(5)} → <strong className="text-destructive">{result.parameterAttack.wrongParams.x.toFixed(5)}</strong></span>
                        <span>c: {result.parameterAttack.trueParams.c.toFixed(3)} → <strong className="text-destructive">{result.parameterAttack.wrongParams.c.toFixed(3)}</strong></span>
                      </div>
                    </AlertDescription>
                  </Alert>
                )}
                <TableCard label="Line Signature Ranking" maxHeight="16rem">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="mono text-xs">Line</TableHead>
                        <TableHead className="mono text-xs">From ↔ To</TableHead>
                        <TableHead className="mono text-right text-xs">Own measurements</TableHead>
                        <TableHead className="mono text-right text-xs">Flagged (|CME_N|&gt;3)</TableHead>
                        <TableHead className="mono text-right text-xs">Fraction flagged</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {result.lineRanking.map((row) => {
                        const isAttacked = result.parameterAttack?.lineId === row.lineId
                        return (
                          <TableRow key={row.lineId} className={isAttacked ? 'bg-status-warn/10' : ''}>
                            <TableCell className="text-xs mono font-medium">
                              L{row.lineId}{isAttacked && <Badge variant="destructive" className="ml-2 text-[9px] px-1 py-0">ATTACKED</Badge>}
                            </TableCell>
                            <TableCell className="text-xs mono">{row.fromBus} ↔ {row.toBus}</TableCell>
                            <TableCell className="text-right text-xs mono">{row.nOwn}</TableCell>
                            <TableCell className="text-right text-xs mono">{row.nFlagged}</TableCell>
                            <TableCell className="text-right text-xs mono font-semibold" style={{ color: row.fractionFlagged > 0.5 ? 'var(--color-destructive)' : row.fractionFlagged > 0 ? 'var(--color-status-warn)' : undefined }}>
                              {(row.fractionFlagged * 100).toFixed(0)}%
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                </TableCard>
              </CardContent>
            </Card>
          )}

          {/* Parameter correction detail (AC only, only when correction='by_parameter'
              actually fired) — before → what we did → after, with the eq. 16 numbers
              plugged in and a before/after bar for each parameter. */}
          {result.parameterCorrection && (
            <Card>
              <CardHeader className="p-4 pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <CheckCircle weight="fill" className="text-status-good" />
                  Step 3a3 — Parameter Correction (eq. 16)
                </CardTitle>
                <CardDescription className="text-xs">
                  L{result.parameterCorrection.lineId} — was wrong, corrected in a single step, no measurement discarded.
                </CardDescription>
              </CardHeader>
              <CardContent className="p-4 space-y-4">
                <Alert className="border-status-good/50 bg-status-good/5">
                  <AlertDescription className="text-xs mono space-y-2">
                    <div>
                      Before: J = <strong className="text-destructive">{result.J_detection_initial.toFixed(3)}</strong>
                      {' '}({result.J_detection_initial > result.chi2_threshold_initial ? 'detected' : 'not detected'}, χ²={result.chi2_threshold_initial.toFixed(3)})
                      {' '}→ After: J = <strong className="text-status-good">{result.pipeline.J_final.toFixed(3)}</strong>
                      {' '}({result.pipeline.detected ? 'still detected' : 'not detected'}, χ²={result.pipeline.threshold.toFixed(3)})
                    </div>
                    <div>
                      Equation: <code>p_C = p_E · (1 + CNE/100)</code>, CNE = <strong>{result.parameterCorrection.cneUsed?.toFixed(3) ?? '—'}</strong>
                      {' '}→ x_C = {result.parameterCorrection.wrongParams.x.toFixed(5)} × (1 {(result.parameterCorrection.cneUsed ?? 0) >= 0 ? '+' : '-'} {Math.abs(result.parameterCorrection.cneUsed ?? 0).toFixed(3)}/100) = <strong>{result.parameterCorrection.correctedParams.x.toFixed(5)}</strong>
                    </div>
                    <div>Residual error vs. real, after correction: <strong>{result.parameterCorrection.residualErrorPct?.toFixed(3) ?? '—'}%</strong>
                      {' '}(was <strong>{((result.parameterCorrection.wrongParams.r / result.parameterCorrection.trueParams.r - 1) * 100).toFixed(1)}%</strong> before)
                    </div>
                  </AlertDescription>
                </Alert>

                <TableCard label="Parameter Correction">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="mono text-xs">Parameter</TableHead>
                        <TableHead className="mono text-right text-xs">True</TableHead>
                        <TableHead className="mono text-right text-xs text-destructive">Wrong (attacked)</TableHead>
                        <TableHead className="mono text-right text-xs text-status-good">Corrected (eq. 16)</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(['r', 'x', 'c'] as const).map((k) => (
                        <TableRow key={k}>
                          <TableCell className="text-xs mono font-medium">{k}</TableCell>
                          <TableCell className="text-right text-xs mono">{result.parameterCorrection!.trueParams[k].toFixed(k === 'c' ? 3 : 6)}</TableCell>
                          <TableCell className="text-right text-xs mono text-destructive">{result.parameterCorrection!.wrongParams[k].toFixed(k === 'c' ? 3 : 6)}</TableCell>
                          <TableCell className="text-right text-xs mono text-status-good font-semibold">{result.parameterCorrection!.correctedParams[k].toFixed(k === 'c' ? 3 : 6)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                </TableCard>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <ParamCompareChart label="r (Ω/km)" decimals={6}
                    trueVal={result.parameterCorrection.trueParams.r}
                    wrongVal={result.parameterCorrection.wrongParams.r}
                    correctedVal={result.parameterCorrection.correctedParams.r} />
                  <ParamCompareChart label="x (Ω/km)" decimals={6}
                    trueVal={result.parameterCorrection.trueParams.x}
                    wrongVal={result.parameterCorrection.wrongParams.x}
                    correctedVal={result.parameterCorrection.correctedParams.x} />
                  <ParamCompareChart label="c (nF/km)" decimals={2}
                    trueVal={result.parameterCorrection.trueParams.c}
                    wrongVal={result.parameterCorrection.wrongParams.c}
                    correctedVal={result.parameterCorrection.correctedParams.c} />
                </div>
              </CardContent>
            </Card>
          )}

          {/* LNR + CME charts */}
          <Card>
            <CardHeader className="p-4 pb-2">
              <CardTitle className="text-sm">Step 3b — LNR and CME_N per Measurement</CardTitle>
              <CardDescription className="text-xs">Red = attacked measurement · Orange = flagged by the pipeline · Dashed line = threshold 3</CardDescription>
            </CardHeader>
            <CardContent className="p-4 space-y-4">
              {chartOmitted > 0 && (
                <p className="text-xs text-status-warn">
                  {chartOmitted} of {result.measurements.length} measurements are not plotted. The charts
                  keep every injected and flagged measurement plus the most extreme of the rest — past a
                  few hundred bars a plot is neither readable nor fast. The full set is in the results
                  table above (and in its Copy).
                </p>
              )}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* LNR */}
                <div>
                  <p className="text-xs mono text-muted-foreground mb-1">|r_N| — Normalized Residual (LNR)</p>
                  <ChartContainer config={lnrChartConfig} className="aspect-auto h-44 w-full">
                    <BarChart data={lnrChartData} margin={{ top: 4, right: 6, left: -20, bottom: 40 }}>
                      <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                      <XAxis dataKey="label" tick={{ fontSize: 8 }} angle={-35} textAnchor="end" height={50} />
                      <YAxis tick={{ fontSize: 8 }} />
                      <ChartTooltip content={<ChartTooltipContent formatter={(v) => Number(v).toFixed(3)} />} />
                      <ReferenceLine y={3} stroke="var(--color-status-warn)" strokeDasharray="4 2" label={{ value: '3', fontSize: 8, fill: 'var(--color-status-warn)' }} />
                      <Bar dataKey="|r_N|" radius={[2, 2, 0, 0]}>
                        {lnrChartData.map((d, i) => (
                          <Cell key={i} fill={d.fill} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ChartContainer>
                </div>

                {/* CME_N — before (clean, same seed) vs after (attacked), paired or delta */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs mono text-muted-foreground">
                      |CME_N| — antes (sem ataque) × depois (com ataque), mesma seed
                    </p>
                    <div className="flex gap-1">
                      <Button type="button" size="sm" variant={cmeView === 'paired' ? 'default' : 'outline'} className="h-6 px-2 text-[10px]" onClick={() => setCmeView('paired')}>
                        Paired
                      </Button>
                      <Button type="button" size="sm" variant={cmeView === 'delta' ? 'default' : 'outline'} className="h-6 px-2 text-[10px]" onClick={() => setCmeView('delta')}>
                        Delta
                      </Button>
                    </div>
                  </div>
                  {cmeView === 'paired' ? (
                    <ChartContainer config={cmePairedChartConfig} className="aspect-auto h-44 w-full">
                      <BarChart data={cmeChartData} margin={{ top: 4, right: 6, left: -20, bottom: 40 }} barGap={1}>
                        <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                        <XAxis dataKey="label" tick={{ fontSize: 8 }} angle={-35} textAnchor="end" height={50} />
                        <YAxis tick={{ fontSize: 8 }} />
                        <ChartTooltip content={<ChartTooltipContent formatter={(v) => Number(v).toFixed(3)} />} />
                        <ReferenceLine y={3} stroke="var(--color-status-warn)" strokeDasharray="4 2" label={{ value: '3', fontSize: 8, fill: 'var(--color-status-warn)' }} />
                        <Bar dataKey="CME_N_before" fill="var(--color-muted-foreground)" opacity={0.5} radius={[2, 2, 0, 0]} />
                        <Bar dataKey="CME_N_after" radius={[2, 2, 0, 0]}>
                          {cmeChartData.map((d, i) => (
                            <Cell key={i} fill={d.fill} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ChartContainer>
                  ) : (
                    <ChartContainer config={cmeDeltaChartConfig} className="aspect-auto h-44 w-full">
                      <BarChart data={cmeChartData} margin={{ top: 4, right: 6, left: -20, bottom: 40 }}>
                        <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                        <XAxis dataKey="label" tick={{ fontSize: 8 }} angle={-35} textAnchor="end" height={50} />
                        <YAxis tick={{ fontSize: 8 }} />
                        <ChartTooltip content={<ChartTooltipContent formatter={(v) => Number(v).toFixed(3)} />} />
                        <ReferenceLine y={0} stroke="var(--color-border)" />
                        <Bar dataKey="delta" radius={[2, 2, 0, 0]}>
                          {cmeChartData.map((d, i) => (
                            <Cell key={i} fill={d.fill} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ChartContainer>
                  )}
                </div>
              </div>

              {/* LNR vs CME scatter */}
              <div>
                <p className="text-xs mono text-muted-foreground mb-1">|r_N| x |CME_N| - geometric consistency (both normalized by σ)</p>
                {/* Scatter payload is per-point (label, rN, cmeN), not a dataKey series, so
                    ChartTooltipContent's series-shaped API doesn't fit — kept a custom Tooltip
                    but restyled it to match ChartTooltipContent's own look for consistency. */}
                <ChartContainer config={{}} className="aspect-auto h-48 w-full">
                  <ScatterChart margin={{ top: 10, right: 20, left: -10, bottom: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis type="number" dataKey="rN" name="|r_N|" tick={{ fontSize: 9 }} label={{ value: '|r_N| (LNR)', position: 'insideBottom', offset: -5, fontSize: 10 }} />
                    <YAxis type="number" dataKey="cmeN" name="|CME_N|" tick={{ fontSize: 9 }} label={{ value: '|CME_N|', angle: -90, position: 'insideLeft', fontSize: 10 }} />
                    <ChartTooltip content={({ payload }) => {
                      if (!payload?.length) return null
                      const d = payload[0].payload
                      return (
                        <div className="border-border/50 bg-background grid min-w-32 gap-1 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl mono">
                          <div className="font-medium">{scatterData.find(x => x.rN === d.rN && x.cmeN === d.cmeN)?.label}</div>
                          <div className="text-muted-foreground">|r_N| = <span className="text-foreground">{d.rN?.toFixed(4)}</span></div>
                          <div className="text-muted-foreground">|CME_N| = <span className="text-foreground">{d.cmeN?.toFixed(4)}</span></div>
                        </div>
                      )
                    }} />
                    <Scatter data={scatterData} shape={(props: any) => {
                      const { cx, cy, payload } = props
                      const color = payload.isBadData ? 'var(--color-destructive)' : payload.isFlagged ? 'var(--color-status-warn)' : 'var(--color-method-ldf)'
                      return <circle cx={cx} cy={cy} r={6} fill={color} opacity={0.85} />
                    }} />
                    {/* Diagonal line y=x as reference */}
                    <ReferenceLine segment={[{ x: 0, y: 0 }, { x: scatterMax + 0.5, y: scatterMax + 0.5 }]} stroke="var(--color-muted-foreground)" strokeDasharray="4 2" />
                  </ScatterChart>
                </ChartContainer>
              </div>
            </CardContent>
          </Card>

          {/* Pipeline history */}
          {pipelineHistory.length > 0 && (
            <Card>
              <CardHeader className="p-4 pb-2">
                <CardTitle className="text-sm">Step 3c - Pipeline History (iterations)</CardTitle>
              </CardHeader>
              <CardContent className="p-4">
                <TableCard label="Pipeline History" maxHeight="16rem">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="mono text-xs">Iter</TableHead>
                        <TableHead className="mono text-right text-xs">J</TableHead>
                        <TableHead className="mono text-right text-xs">threshold</TableHead>
                        <TableHead className="mono text-xs">Detected?</TableHead>
                        <TableHead className="mono text-right text-xs">m</TableHead>
                        <TableHead className="mono text-right text-xs">flagged_idx</TableHead>
                        <TableHead className="mono text-right text-xs">score</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {pipelineHistory.map((h, i) => (
                        <TableRow key={i} className={h.detected ? 'bg-destructive/5' : ''}>
                          <TableCell className="text-xs mono">{h.iter}</TableCell>
                          <TableCell className={`text-right text-xs mono font-semibold ${h.J > h.threshold ? 'text-destructive' : 'text-status-good'}`}>
                            {h.J.toFixed(4)}
                          </TableCell>
                          <TableCell className="text-right text-xs mono">{h.threshold.toFixed(4)}</TableCell>
                          <TableCell className="text-xs">
                            <Badge variant={h.detected ? 'destructive' : 'outline'} className="text-[9px] px-1 py-0">
                              {h.detected ? 'YES' : 'no'}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right text-xs mono">{h.m}</TableCell>
                          <TableCell className="text-right text-xs mono">{h.flagged_idx ?? '—'}</TableCell>
                          <TableCell className="text-right text-xs mono">{h.flagged_score?.toFixed(3) ?? '—'}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                </TableCard>
                <div className="mt-2 text-xs mono text-muted-foreground space-y-0.5">
                  <div>Actions: <strong>{result.pipeline.actions.join(' → ') || 'none'}</strong></div>
                  <div>Flagged indices: <strong>{result.pipeline.flaggedIndices.join(', ') || '—'}</strong></div>
                  <div>Flagged scores: <strong>{result.pipeline.flaggedScores.map(s => s.toFixed(3)).join(', ') || '—'}</strong></div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Full measurement table */}
          <Card>
            <CardHeader className="p-4 pb-2">
              <CardTitle className="text-sm">Step 3d — Full Measurement Table</CardTitle>
              <CardDescription className="text-xs">
                Red = attacked measurement · Orange = false flag · |r_N| &gt; 3 in orange · |CME_N| &gt; 3 in purple
              </CardDescription>
            </CardHeader>
            <CardContent className="p-4">
              <ResultsMeasurementTable result={result} geo={geo} />
            </CardContent>
          </Card>

          {/* RMSE-vs-ground-truth comparison (parameter attacks only) —
              "lower RMSE ≠ correct fix": mirrors the parameter-error
              notebook's final synthesis (section 11/12). */}
          {result.rmseComparison && (
            <Card>
              <CardHeader className="p-4 pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <ChartBar weight="fill" className="text-accent" />
                  Step 3e — Correction Strategy Comparison (RMSE vs. Ground Truth)
                </CardTitle>
                <CardDescription className="text-xs">
                  x_true only exists here because this is a demo/validation comparison — not available in practice to <em>decide</em> a correction, only to report one after the fact. A lower RMSE does not mean a more correct fix: the best measurement correction can look numerically better while discarding real data and leaving the line's r/x/c permanently wrong.
                </CardDescription>
              </CardHeader>
              <CardContent className="p-4 space-y-4">
                <TableCard label="RMSE Comparison">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="mono text-xs">Scenario</TableHead>
                        <TableHead className="mono text-right text-xs">J</TableHead>
                        <TableHead className="mono text-xs">Detected?</TableHead>
                        <TableHead className="mono text-right text-xs">RMSE angle (°)</TableHead>
                        <TableHead className="mono text-right text-xs">RMSE |V| (pu)</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {result.rmseComparison.map((row) => (
                        <TableRow key={row.scenario} className={row.scenario === 'parameter_correction' ? 'bg-status-good/10' : ''}>
                          <TableCell className="text-xs mono font-medium">{row.label}</TableCell>
                          <TableCell className={`text-right text-xs mono ${row.detected ? 'text-destructive font-semibold' : ''}`}>{row.J.toFixed(4)}</TableCell>
                          <TableCell className="text-xs">
                            {row.detected
                              ? <Badge variant="destructive" className="text-[9px] px-1 py-0">alarming</Badge>
                              : <Badge className="text-[9px] px-1 py-0 bg-status-good">no</Badge>}
                          </TableCell>
                          <TableCell className="text-right text-xs mono font-semibold">{row.rmseAngleDeg.toFixed(4)}</TableCell>
                          <TableCell className="text-right text-xs mono">{row.rmseVoltagePu.toFixed(6)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                </TableCard>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs mono text-muted-foreground mb-1">RMSE angle (°) by scenario</p>
                    <ChartContainer config={{ rmseAngleDeg: { label: 'RMSE angle (°)', color: 'var(--color-status-info)' } }} className="aspect-auto h-44 w-full">
                      <BarChart data={result.rmseComparison} margin={{ top: 4, right: 6, left: 0, bottom: 40 }}>
                        <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                        <XAxis dataKey="label" tick={{ fontSize: 8 }} angle={-25} textAnchor="end" height={55} />
                        <YAxis tick={{ fontSize: 8 }} />
                        <ChartTooltip content={<ChartTooltipContent formatter={(v) => Number(v).toFixed(4)} />} />
                        <Bar dataKey="rmseAngleDeg" radius={[2, 2, 0, 0]}>
                          {result.rmseComparison.map((row, i) => (
                            <Cell key={i} fill={
                              row.scenario === 'baseline' ? 'var(--color-muted-foreground)'
                              : row.scenario === 'no_correction' ? 'var(--color-destructive)'
                              : row.scenario === 'parameter_correction' ? 'var(--color-status-good)'
                              : 'var(--color-status-warn)'
                            } />
                          ))}
                        </Bar>
                      </BarChart>
                    </ChartContainer>
                  </div>
                  <div>
                    <p className="text-xs mono text-muted-foreground mb-1">RMSE |V| (pu) by scenario</p>
                    <ChartContainer config={{ rmseVoltagePu: { label: 'RMSE |V| (pu)', color: 'var(--color-method-ldf)' } }} className="aspect-auto h-44 w-full">
                      <BarChart data={result.rmseComparison} margin={{ top: 4, right: 6, left: 0, bottom: 40 }}>
                        <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                        <XAxis dataKey="label" tick={{ fontSize: 8 }} angle={-25} textAnchor="end" height={55} />
                        <YAxis tick={{ fontSize: 8 }} />
                        <ChartTooltip content={<ChartTooltipContent formatter={(v) => Number(v).toFixed(6)} />} />
                        <Bar dataKey="rmseVoltagePu" radius={[2, 2, 0, 0]}>
                          {result.rmseComparison.map((row, i) => (
                            <Cell key={i} fill={
                              row.scenario === 'baseline' ? 'var(--color-muted-foreground)'
                              : row.scenario === 'no_correction' ? 'var(--color-destructive)'
                              : row.scenario === 'parameter_correction' ? 'var(--color-status-good)'
                              : 'var(--color-status-warn)'
                            } />
                          ))}
                        </Bar>
                      </BarChart>
                    </ChartContainer>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ═══ ALL-6 COMPARISON ══════════════════════════════════════════════ */}
      {allResults && (
        <Card>
          <CardHeader className="p-4 pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Lightning weight="fill" className="text-accent" />
              Step 4 — All 8 Pipelines Comparison (2×2×2)
            </CardTitle>
            <CardDescription className="text-xs">
              Same injection (#{selectedMeasIdx} — {geo?.labels[selectedMeasIdx!] ?? '?'}, {badDataMag}×σ) · initial J_resid is identical across pipelines (same z_noisy) · χ² threshold varies by method
            </CardDescription>
          </CardHeader>
          <CardContent className="p-4">
            <TableCard label="All 8 Pipelines Comparison">
                <TableHeader>
                  <TableRow>
                    <TableHead className="mono text-xs">Pipeline</TableHead>
                    <TableHead className="mono text-right text-xs" title="Residual J (= χ² WLS) — identical for all: same injection">J_resid₀</TableHead>
                    <TableHead className="mono text-right text-xs" title="Statistic used for detection (J_resid for residual, J_CME for CME)">J_detection₀</TableHead>
                    <TableHead className="mono text-right text-xs" title="χ²(α, m-n) for residual, χ²(α, m) for CME">χ² threshold₀</TableHead>
                    <TableHead className="mono text-right text-xs">J_final</TableHead>
                    <TableHead className="mono text-xs">Detected?</TableHead>
                    <TableHead className="mono text-xs">Flagged idx</TableHead>
                    <TableHead className="mono text-right text-xs">Score</TableHead>
                    <TableHead className="mono text-xs">Correct?</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {allResults.map((r, i) => {
                    // detected_final = still triggering in the last iteration
                    // anyFlagged = pipeline agiu em algum momento (detectou e removeu/corrigiu)
                    // If !detected_final && anyFlagged -> converged after correction = SUCCESS
                    const anyFlagged = r.pipeline.flaggedIndices.length > 0
                    const correct = anyFlagged && r.pipeline.flaggedIndices.includes(selectedMeasIdx!)
                    const converged = !r.pipeline.detected && anyFlagged  // detectou, corrigiu, parou
                    const rowCls = anyFlagged && correct
                      ? 'bg-status-good/10'
                      : anyFlagged && !correct
                      ? 'bg-status-warn/10'
                      : 'bg-destructive/5'
                    return (
                      <TableRow key={i} className={rowCls}>
                        <TableCell className="text-xs mono font-medium">{COMBOS[i].label}</TableCell>
                        <TableCell className="text-right text-xs mono text-muted-foreground">
                          {r.J_initial.toFixed(3)}
                        </TableCell>
                        <TableCell className={`text-right text-xs mono font-semibold ${r.J_detection_initial > r.chi2_threshold_initial ? 'text-destructive' : 'text-status-good'}`}>
                          {r.J_detection_initial.toFixed(3)}
                        </TableCell>
                        <TableCell className="text-right text-xs mono">{r.chi2_threshold_initial.toFixed(3)}</TableCell>
                        <TableCell className={`text-right text-xs mono ${r.pipeline.J_final > r.pipeline.threshold ? 'text-destructive font-semibold' : 'text-status-good'}`}>
                          {r.pipeline.J_final.toFixed(3)}
                        </TableCell>
                        <TableCell>
                          {r.pipeline.detected
                            ? <Badge variant="destructive" className="text-[9px] px-1 py-0">alarming</Badge>
                            : converged
                            ? <Badge className="text-[9px] px-1 py-0 bg-status-good">Fixed ✓</Badge>
                            : <Badge variant="outline" className="text-[9px] px-1 py-0">no</Badge>}
                        </TableCell>
                        <TableCell className="text-xs mono">{r.pipeline.flaggedIndices.join(', ') || '—'}</TableCell>
                        <TableCell className="text-right text-xs mono">{r.pipeline.flaggedScores.map(s => s.toFixed(3)).join(', ') || '—'}</TableCell>
                        <TableCell>
                          {anyFlagged && correct && <Badge className="text-[9px] px-1 py-0 bg-status-good">✓ CORRECT</Badge>}
                          {anyFlagged && !correct && <Badge className="text-[9px] px-1 py-0 bg-status-warn">✗ WRONG IDX</Badge>}
                          {!anyFlagged && <span className="text-xs text-muted-foreground">—</span>}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
            </TableCard>

            {/* Legenda das colunas */}
            <div className="mt-2 text-[10px] mono text-muted-foreground space-y-1">
              <div>
                <strong>J_resid₀</strong> = rᵀWr = Σᵢ(rᵢ/σᵢ)² — sum of squared normalized residuals.
                {' '}It is <em>identical for all pipelines</em> (same injection, z_noisy, and seed).
                {' '}Under H₀ (no bad data): J ~ χ²(m-n). With high K_ii (leverage point), r_i≈0 even with an error → J does not grow → <strong>masking</strong>.
              </div>
              <div><strong>J_detection₀</strong>: J_resid (Residual rows) or J_CME=Σ(CME_N)² (CME rows — includes masked error, under H₀: J_CME~χ²(m)) — this is compared against the threshold in the first iteration.</div>
              <div><strong>Correction z_true</strong>: uses <strong>CNE</strong> = (1+UI)·r_N (eq. 20, Bretas &amp; Bretas 2018 — residual subspace, ≠ CME_N): z_corrected = z − CNE·σ. Detection/identification keep using CME_N.</div>
              <div><strong>Detected?</strong>: <span className="text-status-good">Fixed ✓</span> = detected, acted, and converged (J_final &lt; threshold) · <span className="text-destructive">alarming</span> = did not converge · <span>no</span> = never triggered.</div>
            </div>

            {/* Summary: CME succeeded */}
            {allResults.some(r => r.pipeline.flaggedIndices.length > 0) && allResults.every(r => !r.pipeline.detected) && (
              <Alert className="mt-3 border-status-good/50 bg-status-good/5">
                <AlertDescription className="text-xs mono">
                  <div className="font-semibold flex items-center gap-2">
                    <CheckCircle weight="fill" className="text-status-good w-4 h-4" />
                    CME pipelines detected and corrected the error (converged)
                  </div>
                  <div className="mt-1 space-y-1">
                    <div>J_detection₀ (CME) = <strong>{allResults[4].J_detection_initial.toFixed(3)}</strong> &gt; CME threshold χ²(α,m={allResults[0].m}) = <strong>{allResults[4].chi2_threshold_initial.toFixed(3)}</strong> → triggered and acted</div>
                    <div>Residual pipelines did NOT trigger: J_resid₀ = <strong>{allResults[0].J_initial.toFixed(3)}</strong> &lt; threshold χ²(α,m-n={allResults[0].DOF}) = <strong>{allResults[0].chi2_threshold.toFixed(3)}</strong> — K_ii={geo?.measurements[selectedMeasIdx!]?.K_diag.toFixed(4)} &gt; {K_CROSSOVER} masked the residual error.</div>
                  </div>
                </AlertDescription>
              </Alert>
            )}

            {/* Summary: nothing at all detected */}
            {allResults.every(r => r.pipeline.flaggedIndices.length === 0) && (
              <Alert className="mt-3 border-status-warn/50 bg-status-warn/5">
                <AlertDescription className="text-xs mono">
                  <div className="font-semibold flex items-center gap-2">
                    <Warning weight="fill" className="text-status-warn w-4 h-4" />
                    None of the 8 pipelines detected bad data
                  </div>
                  <div className="mt-1 space-y-1">
                    <div>J_resid₀ = <strong>{allResults[0].J_initial.toFixed(3)}</strong> · residual threshold χ²(α,m-n) = <strong>{allResults[0].chi2_threshold.toFixed(3)}</strong> · CME threshold χ²(α,m) = <strong>{allResults[4].chi2_threshold_initial.toFixed(3)}</strong></div>
                    <div>Attacked measurement: <strong>{geo?.labels[selectedMeasIdx!]}</strong> &nbsp;K_ii = <strong style={{ color: kiiHex(geo?.measurements[selectedMeasIdx!]?.K_diag ?? 0) }}>{geo?.measurements[selectedMeasIdx!]?.K_diag.toFixed(4)}</strong>&nbsp; UI = <strong>{geo?.measurements[selectedMeasIdx!]?.UI.toFixed(4)}</strong></div>
                    {(geo?.measurements[selectedMeasIdx!]?.K_diag ?? 0) > K_CROSSOVER && (
                      <div className="text-destructive">⚠ K_ii &gt; {K_CROSSOVER}: error is MASKED in e_U. Increase the magnitude (try 15–20×σ) or choose a lower-UI measurement.</div>
                    )}
                    {(geo?.measurements[selectedMeasIdx!]?.K_diag ?? 0) <= K_CROSSOVER && (
                      <div>K_ii ≤ {K_CROSSOVER} — error magnitude may be too small ({badDataMag}×σ).</div>
                    )}
                  </div>
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
