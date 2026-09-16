/**
 * PipelineTab — the operational chain, field to estimator.
 *
 * Eight blocks in a row, one per layer. Click a block to inspect that layer's
 * own table; the strip stays visible so the chain never leaves the screen.
 * The point of the tab is propagation: inject a fault in one layer, watch what
 * the next ones make of it.
 *
 * The trace panel is the other half. Pick a sensor and its whole life shows up
 * across layers — meter reading, RTU point, packet, SCADA record, z-vector
 * entry. Without it an attack injected in the channel reads as "a large
 * residual" and nothing more.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { TableCard } from '@/components/TableCard'
import { VirtualTableBody, RESULT_ROW_HEIGHT } from '@/components/VirtualTableBody'
import {
  Play, Spinner, Warning, CheckCircle, XCircle, Plus, Trash, Path,
  Lightning, Radio, WifiHigh, Database, TreeStructure, ChartLine, Crosshair,
  SlidersHorizontal, Cpu, ShieldWarning, ArrowRight,
} from '@phosphor-icons/react'
import { toast } from 'sonner'
import {
  listPipelineAttacks, runPipeline,
  type AttackInput, type AttackSpec, type PipelineResult, type TraceEvent,
  type AgentFinding, type AgentSeverity,
} from '@/lib/api'
import type { Topology } from '@/lib/types'

interface PipelineTabProps {
  topology: Topology
}

type LayerKey = 'physical' | 'measurement' | 'rtu' | 'channel' | 'rtdb' | 'topology' | 'estimation' | 'opf' | 'agents'

const LAYER_META: Array<{ key: LayerKey; label: string; sub: string; icon: React.ElementType }> = [
  { key: 'physical', label: 'True State', sub: 'power flow', icon: Lightning },
  { key: 'measurement', label: 'Meters', sub: 'field readings', icon: Crosshair },
  { key: 'rtu', label: 'RTU / IED', sub: 'point mapping', icon: Radio },
  { key: 'channel', label: 'Comms', sub: 'delay & loss', icon: WifiHigh },
  { key: 'rtdb', label: 'SCADA RTDB', sub: 'quality & age', icon: Database },
  { key: 'topology', label: 'Topology', sub: 'switch 0/1/2/3', icon: TreeStructure },
  { key: 'estimation', label: 'State Est.', sub: 'WLS', icon: ChartLine },
  { key: 'opf', label: 'OPF / Control', sub: 'setpoints', icon: SlidersHorizontal },
  { key: 'agents', label: 'Agents', sub: 'cross-layer', icon: Cpu },
]

/** Semantic color per DNP3 double-bit / IEC 61850 Dbpos code. Codes 1 and 2
 *  are conclusive readings, 0 and 3 are not — the split that matters is
 *  "conclusive vs not", not "open vs closed", so it has to read at a glance. */
const STATUS_COLOR: Record<number, string> = {
  0: 'text-status-warn',   // Intermediate
  1: 'text-status-info',   // Determined OFF (open)
  2: 'text-status-good',   // Determined ON (closed)
  3: 'text-destructive',   // Indeterminate
}

const QUALITY_COLOR: Record<string, string> = {
  good: 'text-status-good',
  suspect: 'text-status-warn',
  bad: 'text-destructive',
}

const SEVERITY_COLOR: Record<AgentSeverity, string> = {
  ok: 'text-status-good',
  info: 'text-muted-foreground',
  warning: 'text-status-warn',
  critical: 'text-destructive',
}

/** The control agent's verdict. Deliberately coarse: an operator does not act
 *  on a probability, they act on "I can, I can with limits, or I cannot". */
const RECOMMENDATION_META: Record<string, { label: string; className: string; blurb: string }> = {
  dispatch: {
    label: 'DISPATCH',
    className: 'border-status-good/50 bg-status-good/5 text-status-good',
    blurb: 'No layer raised a concern — control action released.',
  },
  derate: {
    label: 'DERATE',
    className: 'border-status-warn/60 bg-status-warn/5 text-status-warn',
    blurb: 'Upstream layers flagged something — conservative action only, no switching.',
  },
  block: {
    label: 'BLOCK',
    className: 'border-destructive/60 bg-destructive/5 text-destructive',
    blurb: 'The delivered state does not support a control action.',
  },
}

const LEVEL_COLOR: Record<string, string> = {
  info: 'text-muted-foreground',
  warning: 'text-status-warn',
  error: 'text-destructive',
}

function num(v: number | null | undefined, digits = 4): string {
  return v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(digits)
}

export function PipelineTab({ topology }: PipelineTabProps) {
  const [catalog, setCatalog] = useState<AttackSpec[]>([])
  const [result, setResult] = useState<PipelineResult | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<LayerKey>('rtdb')
  const [subject, setSubject] = useState<string>('')

  // Chain config
  const [nRtus, setNRtus] = useState(0)
  const [baseDelay, setBaseDelay] = useState(50)
  const [jitter, setJitter] = useState(0)
  const [loss, setLoss] = useState(0)
  const [staleAfter, setStaleAfter] = useState(10)
  const [policy, setPolicy] = useState<'last_known' | 'assume_closed' | 'assume_open' | 'flow_inference'>('last_known')
  const [addNoise, setAddNoise] = useState(true)
  const [seed, setSeed] = useState(42)
  const [runOpf, setRunOpf] = useState(true)
  const [vmMin, setVmMin] = useState(0.95)
  const [maxLoading, setMaxLoading] = useState(100)

  // Attack builder
  const [attacks, setAttacks] = useState<AttackInput[]>([])
  const [draftId, setDraftId] = useState('')
  const [draftTarget, setDraftTarget] = useState('')
  const [draftParam, setDraftParam] = useState('')

  useEffect(() => {
    listPipelineAttacks()
      .then((d) => setCatalog(d.attacks))
      .catch(() => toast.error('Could not load the attack catalog — is the backend running?'))
  }, [])

  const draftSpec = catalog.find((a) => a.attack_id === draftId)
  const firstParamName = draftSpec ? Object.keys(draftSpec.params)[0] : undefined

  const run = useCallback(async () => {
    setRunning(true)
    setError(null)
    try {
      const res = await runPipeline({
        topology,
        seed,
        add_noise: addNoise,
        n_rtus: nRtus,
        channel: { base_delay_ms: baseDelay, jitter_ms: jitter, drop_probability: loss },
        stale_after_s: staleAfter,
        unreliable_policy: policy,
        attacks,
        run_opf: runOpf,
        opf_limits: {
          vm_min_pu: vmMin, vm_max_pu: 2 - vmMin,
          max_loading_percent: maxLoading,
          ext_grid_cost: 60, gen_cost: 20, sgen_cost: 5,
        },
      })
      setResult(res)
      setSubject(res.trace.subjects[0] ?? '')
      toast.success(`Chain ran in ${res.elapsed_ms.toFixed(0)} ms — run ${res.run_id}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
      toast.error('Pipeline failed')
    } finally {
      setRunning(false)
    }
  }, [topology, seed, addNoise, nRtus, baseDelay, jitter, loss, staleAfter, policy, attacks,
      runOpf, vmMin, maxLoading])

  function addAttack() {
    if (!draftSpec) return
    const params: Record<string, unknown> = {}
    if (firstParamName && draftParam !== '') {
      const asNum = Number(draftParam)
      params[firstParamName] = Number.isFinite(asNum) && draftParam.trim() !== '' ? asNum : draftParam
    }
    setAttacks((prev) => [...prev, { attack_id: draftSpec.attack_id, target: draftTarget, params }])
    setDraftTarget('')
    setDraftParam('')
  }

  /** One headline number per block — what the operator would glance at. */
  const metrics = useMemo((): Record<LayerKey, { value: string; bad: boolean }> => {
    const empty = { value: '—', bad: false }
    if (!result) {
      return Object.fromEntries(LAYER_META.map((l) => [l.key, empty])) as Record<LayerKey, { value: string; bad: boolean }>
    }
    const L = result.layers
    const est = L.estimation
    return {
      physical: { value: `${L.physical.buses.length} buses`, bad: !L.physical.converged },
      measurement: { value: `${L.measurement.n_measurements} meas.`, bad: false },
      rtu: { value: `${L.rtu.rtus.length} RTUs · ${L.rtu.points.length} pts`, bad: false },
      channel: {
        value: `${(L.channel.statistics.loss_rate * 100).toFixed(0)}% loss · ${L.channel.statistics.delay_ms_max.toFixed(0)} ms`,
        bad: L.channel.statistics.n_dropped > 0,
      },
      rtdb: {
        value: `spread ${L.rtdb.summary.timestamp_spread_s.toFixed(2)} s`,
        bad: L.rtdb.summary.n_stale > 0 || L.rtdb.summary.n_bad > 0,
      },
      topology: {
        value: L.topology.matches_reality ? 'matches reality' : `${L.topology.mismatched_switch_ids.length} wrong`,
        bad: !L.topology.matches_reality || L.topology.summary.n_unreliable > 0,
      },
      estimation: {
        value: est?.ran ? `J = ${num(est.J, 2)}` : 'not run',
        bad: !est?.ran || est?.chi2_passed === false,
      },
      opf: {
        value: L.opf
          ? (L.opf.error
            ? 'failed'
            : `Δ ${num(L.opf.max_setpoint_error_mw, 3)} MW · ${L.opf.n_hidden_violations} hidden`)
          : 'off',
        bad: Boolean(L.opf && !L.opf.error && (L.opf.n_hidden_violations > 0 || !L.opf.operator.converged)),
      },
      agents: {
        value: L.agents ? L.agents.recommendation.toUpperCase() : 'off',
        bad: Boolean(L.agents && L.agents.recommendation !== 'dispatch'),
      },
    }
  }, [result])

  const trail: TraceEvent[] = useMemo(() => {
    if (!result || !subject) return []
    const order = LAYER_META.map((l) => l.key as string)
    return result.trace.events
      .filter((e) => e.subject === subject)
      .sort((a, b) => order.indexOf(a.layer) - order.indexOf(b.layer) || a.timestamp_s - b.timestamp_s)
  }, [result, subject])

  return (
    <div className="space-y-4">
      {/* ── Config ─────────────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="p-4 pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Path weight="fill" className="h-4 w-4 text-accent" />
            Operational chain
          </CardTitle>
          <CardDescription className="text-xs">
            Meter → RTU → communication → SCADA RTDB → topology processor → state estimator.
            Every layer keeps its own table, so a fault injected in one is visible in the next.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 p-4 pt-0">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            <div className="space-y-1">
              <Label className="text-xs">RTUs (0 = auto)</Label>
              <Input type="number" min={0} max={64} value={nRtus} className="h-8 text-xs"
                onChange={(e) => setNRtus(Number(e.target.value))} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Delay (ms)</Label>
              <Input type="number" min={0} value={baseDelay} className="h-8 text-xs"
                onChange={(e) => setBaseDelay(Number(e.target.value))} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Jitter (ms)</Label>
              <Input type="number" min={0} value={jitter} className="h-8 text-xs"
                onChange={(e) => setJitter(Number(e.target.value))} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Packet loss</Label>
              <Input type="number" min={0} max={1} step={0.05} value={loss} className="h-8 text-xs"
                onChange={(e) => setLoss(Number(e.target.value))} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Stale after (s)</Label>
              <Input type="number" min={0} value={staleAfter} className="h-8 text-xs"
                onChange={(e) => setStaleAfter(Number(e.target.value))} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Seed</Label>
              <Input type="number" value={seed} className="h-8 text-xs"
                onChange={(e) => setSeed(Number(e.target.value))} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Code 0/3 policy</Label>
              <Select value={policy} onValueChange={(v) => setPolicy(v as typeof policy)}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="last_known">Last known state</SelectItem>
                  <SelectItem value="assume_closed">Assume closed</SelectItem>
                  <SelectItem value="assume_open">Assume open</SelectItem>
                  <SelectItem value="flow_inference">Infer from measured flow (agent)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <Switch id="pipeline-noise" checked={addNoise} onCheckedChange={setAddNoise} />
              <Label htmlFor="pipeline-noise" className="text-xs">
                Measurement noise
                <span className="ml-1 text-muted-foreground">(off = z equals z_true, isolates the attack)</span>
              </Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch id="pipeline-opf" checked={runOpf} onCheckedChange={setRunOpf} />
              <Label htmlFor="pipeline-opf" className="text-xs">
                Control layer (OPF)
                <span className="ml-1 text-muted-foreground">(slower)</span>
              </Label>
            </div>
            {runOpf && (
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground">V min</Label>
                <Input type="number" step={0.01} value={vmMin} className="h-7 w-20 text-xs"
                  onChange={(e) => setVmMin(Number(e.target.value))} />
                <Label className="text-xs text-muted-foreground">Load max %</Label>
                <Input type="number" step={5} value={maxLoading} className="h-7 w-20 text-xs"
                  onChange={(e) => setMaxLoading(Number(e.target.value))} />
              </div>
            )}
            <Button size="sm" className="ml-auto h-8 gap-1.5 text-xs" onClick={run} disabled={running}>
              {running ? <Spinner className="h-3.5 w-3.5 animate-spin" /> : <Play weight="fill" className="h-3.5 w-3.5" />}
              Run chain
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* ── Attacks ────────────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="p-4 pb-3">
          <CardTitle className="text-sm">Fault / attack injection</CardTitle>
          <CardDescription className="text-xs">
            Injected at the layer where the failure actually happens, not on the finished z vector —
            that is what makes the residual signature realistic instead of an isolated outlier.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 p-4 pt-0">
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-56 flex-1 space-y-1">
              <Label className="text-xs">Attack</Label>
              <Select value={draftId} onValueChange={setDraftId}>
                <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Pick an attack…" /></SelectTrigger>
                <SelectContent>
                  {(['measurement', 'rtu', 'channel', 'topology'] as const).map((layer) => {
                    const inLayer = catalog.filter((a) => a.layer === layer)
                    if (!inLayer.length) return null
                    return (
                      <div key={layer}>
                        <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {layer}
                        </div>
                        {inLayer.map((a) => (
                          <SelectItem key={a.attack_id} value={a.attack_id} className="text-xs">
                            {a.label}{a.stealthy ? ' · stealthy' : ''}
                          </SelectItem>
                        ))}
                      </div>
                    )
                  })}
                </SelectContent>
              </Select>
            </div>
            <div className="w-40 space-y-1">
              <Label className="text-xs">Target {draftSpec ? `(${draftSpec.target_kind})` : ''}</Label>
              <Input value={draftTarget} className="h-8 text-xs"
                placeholder={draftSpec?.target_kind === 'rtu_id' ? 'RTU-1' : draftSpec?.target_kind === 'switch_id' ? '1' : 'S1'}
                disabled={draftSpec?.target_kind === 'none'}
                onChange={(e) => setDraftTarget(e.target.value)} />
            </div>
            {firstParamName && (
              <div className="w-44 space-y-1">
                <Label className="text-xs">{firstParamName}</Label>
                <Input value={draftParam} className="h-8 text-xs"
                  placeholder={draftSpec?.params[firstParamName]?.slice(0, 28)}
                  onChange={(e) => setDraftParam(e.target.value)} />
              </div>
            )}
            <Button size="sm" variant="outline" className="h-8 gap-1 text-xs" onClick={addAttack} disabled={!draftSpec}>
              <Plus className="h-3.5 w-3.5" /> Add
            </Button>
          </div>

          {draftSpec && (
            <p className="rounded-md bg-muted/50 p-2 text-xs text-muted-foreground">{draftSpec.description}</p>
          )}

          {attacks.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {attacks.map((a, i) => (
                <Badge key={i} variant="secondary" className="gap-1.5 py-1 text-xs font-normal">
                  <span className="font-medium">{catalog.find((c) => c.attack_id === a.attack_id)?.label ?? a.attack_id}</span>
                  {a.target && <span className="text-muted-foreground">→ {a.target}</span>}
                  <button type="button" aria-label="Remove attack"
                    onClick={() => setAttacks((prev) => prev.filter((_, j) => j !== i))}>
                    <Trash className="h-3 w-3 hover:text-destructive" />
                  </button>
                </Badge>
              ))}
              <Button size="sm" variant="ghost" className="h-6 text-xs text-muted-foreground"
                onClick={() => setAttacks([])}>Clear all</Button>
            </div>
          )}
        </CardContent>
      </Card>

      {error && (
        <Alert variant="destructive">
          <Warning className="h-4 w-4" />
          <AlertDescription className="text-xs">{error}</AlertDescription>
        </Alert>
      )}

      {result && (
        <>
          {/* ── Verdict ────────────────────────────────────────────────── */}
          <AgentVerdict result={result} />
          <VerdictBanner result={result} />

          {/* ── Chain strip ────────────────────────────────────────────── */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
            {LAYER_META.map((layer) => {
              const m = metrics[layer.key]
              const active = selected === layer.key
              return (
                <button
                  key={layer.key}
                  type="button"
                  onClick={() => setSelected(layer.key)}
                  className={`rounded-md border-2 p-2.5 text-left transition-colors ${
                    active ? 'border-primary bg-primary/5' : m.bad ? 'border-status-warn/50' : 'border-border hover:border-muted-foreground/40'
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <layer.icon weight="fill" className={`h-3.5 w-3.5 ${m.bad ? 'text-status-warn' : 'text-muted-foreground'}`} />
                    <span className="truncate text-xs font-semibold">{layer.label}</span>
                  </div>
                  <div className="mt-0.5 truncate text-[10px] text-muted-foreground">{layer.sub}</div>
                  <div className={`mt-1 truncate text-xs font-medium ${m.bad ? 'text-status-warn' : ''}`}>{m.value}</div>
                </button>
              )
            })}
          </div>

          {/* ── Layer detail ───────────────────────────────────────────── */}
          <Card>
            <CardHeader className="p-4 pb-2">
              <CardTitle className="text-sm">{LAYER_META.find((l) => l.key === selected)?.label}</CardTitle>
            </CardHeader>
            <CardContent className="p-4 pt-0">
              <LayerDetail layer={selected} result={result} />
            </CardContent>
          </Card>

          {/* ── Trace ──────────────────────────────────────────────────── */}
          <Card>
            <CardHeader className="p-4 pb-3">
              <CardTitle className="text-sm">End-to-end trace</CardTitle>
              <CardDescription className="text-xs">
                One measurement's whole life across the chain — meter, RTU point, packet, SCADA
                record, z-vector entry. Pick a subject to follow it.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 p-4 pt-0">
              <Select value={subject} onValueChange={setSubject}>
                <SelectTrigger className="h-8 w-64 text-xs"><SelectValue placeholder="Pick a sensor…" /></SelectTrigger>
                <SelectContent className="max-h-72">
                  {result.trace.subjects.map((s) => (
                    <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {trail.length > 0 && (
                <ol className="space-y-1.5">
                  {trail.map((e, i) => (
                    <li key={i} className="flex gap-2 rounded-md border p-2 text-xs">
                      <Badge variant="outline" className="h-5 shrink-0 text-[10px] uppercase">{e.layer}</Badge>
                      <span className={`flex-1 ${LEVEL_COLOR[e.level]}`}>{e.message}</span>
                      <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                        t={e.timestamp_s.toFixed(3)}s
                      </span>
                    </li>
                  ))}
                </ol>
              )}

              {result.trace.problems.length > 0 && (
                <>
                  <Separator />
                  <div>
                    <p className="mb-1.5 text-xs font-semibold">
                      Problems flagged across the chain ({result.trace.problems.length})
                    </p>
                    <TableCard label="Chain problems" maxHeight="14rem">
                      <TableHeader>
                        <TableRow>
                          <TableHead className="text-xs">Layer</TableHead>
                          <TableHead className="text-xs">Subject</TableHead>
                          <TableHead className="text-xs">Message</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {result.trace.problems.map((p, i) => (
                          <TableRow key={i}>
                            <TableCell className="text-xs uppercase text-muted-foreground">{p.layer}</TableCell>
                            <TableCell className="font-mono text-xs">{p.subject}</TableCell>
                            <TableCell className={`text-xs ${LEVEL_COLOR[p.level]}`}>{p.message}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </TableCard>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

/** The agent team's verdict, and — when there is one — the causal chain that
 *  produced it. The chain is the point: no single agent reaches "block" on its
 *  own, and no fixed threshold would, because each layer stayed inside its own
 *  limit. */
function AgentVerdict({ result }: { result: PipelineResult }) {
  const agents = result.layers.agents
  if (!agents) return null

  const meta = RECOMMENDATION_META[agents.recommendation] ?? RECOMMENDATION_META.block
  const flagged = agents.findings.filter((f) => f.severity !== 'ok')

  return (
    <Card className={`border-2 ${meta.className.split(' ').slice(0, 2).join(' ')}`}>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className={`rounded-md border-2 px-3 py-1 text-sm font-bold ${meta.className}`}>
            {meta.label}
          </span>
          <span className="text-xs text-muted-foreground">{meta.blurb}</span>
          <span className="ml-auto text-xs text-muted-foreground">
            {agents.n_messages} inter-agent message{agents.n_messages === 1 ? '' : 's'} · {agents.total_bytes} B
          </span>
        </div>

        {agents.propagation.length > 0 && (
          <div className="rounded-md border bg-muted/40 p-2.5">
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold">
              <ShieldWarning weight="fill" className="h-3.5 w-3.5 text-status-warn" />
              Cross-layer propagation — decisions no agent reached on its own
            </p>
            <ol className="space-y-1">
              {agents.propagation.map((p, i) => (
                <li key={i} className="flex flex-wrap items-center gap-1.5 text-xs">
                  <Badge variant="outline" className="h-5 text-[10px] uppercase">{p.layer}</Badge>
                  <span className="font-medium">{p.agent.replace('Agent_', '')}</span>
                  <ArrowRight className="h-3 w-3 text-muted-foreground" />
                  <span className="text-muted-foreground">{p.title}</span>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    ← {p.caused_by.join(', ')}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {flagged.length > 0 && (
          <ul className="space-y-1">
            {flagged.map((f, i) => (
              <li key={i} className="flex gap-2 text-xs">
                <Badge variant="outline" className="h-5 shrink-0 text-[10px]">
                  {f.agent.replace('Agent_', '')}
                </Badge>
                <span>
                  <span className={`font-medium ${SEVERITY_COLOR[f.severity]}`}>{f.title}</span>
                  <span className="text-muted-foreground"> — {f.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

/** The two questions the chain exists to answer, above everything else:
 *  did the reconstructed model match reality, and did the estimator survive. */
function VerdictBanner({ result }: { result: PipelineResult }) {
  const topo = result.layers.topology
  const est = result.layers.estimation
  const rtdb = result.layers.rtdb.summary

  const items = [
    {
      ok: topo.matches_reality,
      label: topo.matches_reality
        ? 'Topology reconstructed correctly'
        : `Topology WRONG on switch ${topo.mismatched_switch_ids.join(', ')} — the estimator is solving the wrong problem`,
    },
    {
      ok: topo.summary.n_unreliable === 0,
      label: topo.summary.n_unreliable === 0
        ? 'All switch readings conclusive (codes 1/2)'
        : `${topo.summary.n_unreliable} switch(es) reading Intermediate/Indeterminate — resolved by policy "${topo.summary.policy}"`,
    },
    {
      ok: rtdb.timestamp_spread_s < 1.0 && rtdb.n_bad === 0,
      label: `SCADA snapshot spans ${rtdb.timestamp_spread_s.toFixed(3)} s across ${rtdb.n_usable} points`
        + (rtdb.n_bad ? ` · ${rtdb.n_bad} unusable` : ''),
    },
    {
      ok: Boolean(est?.ran && est.chi2_passed),
      label: est?.ran
        ? `WLS ${est.converged ? 'converged' : 'did NOT converge'} · J = ${num(est.J, 2)} vs limit ${num(est.chi2_limit, 2)} · max |ΔV| = ${num(est.max_vm_error, 5)} pu`
        : `Estimator did not run — ${est?.reason ?? 'unknown reason'}`,
    },
  ]

  return (
    <Card>
      <CardContent className="grid gap-1.5 p-3 sm:grid-cols-2">
        {items.map((it, i) => (
          <div key={i} className="flex items-start gap-1.5 text-xs">
            {it.ok
              ? <CheckCircle weight="fill" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-status-good" />
              : <XCircle weight="fill" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />}
            <span className={it.ok ? '' : 'font-medium'}>{it.label}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function LayerDetail({ layer, result }: { layer: LayerKey; result: PipelineResult }) {
  const L = result.layers

  if (layer === 'physical') {
    return (
      <TableCard
        label="True state"
        maxHeight="20rem"
        exportData={() => ({
          headers: ['Bus', '|V| (pu)', 'theta (deg)', 'P (MW)', 'Q (MVAr)'],
          rows: L.physical.buses.map((b) => [String(b.id), num(b.vm_pu, 5), num(b.va_degree, 3), num(b.p_mw, 4), num(b.q_mvar, 4)]),
        })}
      >
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs">Bus</TableHead>
            <TableHead className="text-xs">|V| (pu)</TableHead>
            <TableHead className="text-xs">θ (°)</TableHead>
            <TableHead className="text-xs">P (MW)</TableHead>
            <TableHead className="text-xs">Q (MVAr)</TableHead>
          </TableRow>
        </TableHeader>
        <VirtualTableBody
          items={L.physical.buses}
          renderRow={(b) => (
            <TableRow key={b.id} style={{ height: RESULT_ROW_HEIGHT }}>
              <TableCell className="text-xs font-medium">{b.id}</TableCell>
              <TableCell className="font-mono text-xs">{num(b.vm_pu, 5)}</TableCell>
              <TableCell className="font-mono text-xs">{num(b.va_degree, 3)}</TableCell>
              <TableCell className="font-mono text-xs">{num(b.p_mw, 4)}</TableCell>
              <TableCell className="font-mono text-xs">{num(b.q_mvar, 4)}</TableCell>
            </TableRow>
          )}
        />
      </TableCard>
    )
  }

  if (layer === 'measurement') {
    return (
      <TableCard
        label="Field measurements"
        maxHeight="20rem"
        exportData={() => ({
          headers: ['#', 'Quantity', 'Meter', 'Element', 'z_true', 'z_field', 'sigma'],
          rows: L.measurement.rows.map((r) => [
            String(r.index), r.quantity, r.meterKind,
            r.busId != null ? `bus ${r.busId}` : `line ${r.lineId}`,
            num(r.z_true, 5), num(r.z_field, 5), num(r.sigma, 6),
          ]),
        })}
      >
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs">#</TableHead>
            <TableHead className="text-xs">Quantity</TableHead>
            <TableHead className="text-xs">Meter</TableHead>
            <TableHead className="text-xs">Element</TableHead>
            <TableHead className="text-xs">z_true</TableHead>
            <TableHead className="text-xs">z_field</TableHead>
            <TableHead className="text-xs">σ</TableHead>
          </TableRow>
        </TableHeader>
        <VirtualTableBody
          items={L.measurement.rows}
          renderRow={(r) => (
            <TableRow key={r.index} style={{ height: RESULT_ROW_HEIGHT }}>
              <TableCell className="text-xs text-muted-foreground">{r.index}</TableCell>
              <TableCell className="font-mono text-xs">{r.quantity}</TableCell>
              <TableCell className="text-xs uppercase">{r.meterKind}</TableCell>
              <TableCell className="text-xs">{r.busId != null ? `bus ${r.busId}` : `line ${r.lineId}`}</TableCell>
              <TableCell className="font-mono text-xs">{num(r.z_true, 5)}</TableCell>
              <TableCell className="font-mono text-xs">{num(r.z_field, 5)}</TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground">{num(r.sigma, 6)}</TableCell>
            </TableRow>
          )}
        />
      </TableCard>
    )
  }

  if (layer === 'rtu') {
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap gap-1.5">
          {L.rtu.rtus.map((r) => (
            <Badge key={r.rtu_id} variant="outline" className="text-xs font-normal">
              <span className="font-semibold">{r.rtu_id}</span>
              <span className="ml-1.5 text-muted-foreground">
                {r.n_points} pts · scan {r.scan_period_s}s · buses {r.bus_ids.join(', ')}
              </span>
            </Badge>
          ))}
        </div>
        <TableCard label="RTU points" maxHeight="20rem">
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">Point ID</TableHead>
              <TableHead className="text-xs">Sensor</TableHead>
              <TableHead className="text-xs">RTU</TableHead>
              <TableHead className="text-xs">Equipment</TableHead>
              <TableHead className="text-xs">Value</TableHead>
              <TableHead className="text-xs">Source t (s)</TableHead>
              <TableHead className="text-xs">Quality</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {L.rtu.points.map((p) => (
              <TableRow key={p.point_id}>
                <TableCell className="font-mono text-xs font-medium">{p.point_id}</TableCell>
                <TableCell className="font-mono text-xs">{p.sensor_id}</TableCell>
                <TableCell className="text-xs">{p.rtu_id}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{p.equipment_id}</TableCell>
                <TableCell className="font-mono text-xs">{num(p.value, 5)}</TableCell>
                <TableCell className="font-mono text-xs">{num(p.source_timestamp_s, 3)}</TableCell>
                <TableCell className={`text-xs ${QUALITY_COLOR[p.quality]}`}>{p.quality}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </TableCard>
      </div>
    )
  }

  if (layer === 'channel') {
    const s = L.channel.statistics
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Packets" value={String(s.n_packets)} />
          <Stat label="Dropped" value={`${s.n_dropped} (${(s.loss_rate * 100).toFixed(1)}%)`} bad={s.n_dropped > 0} />
          <Stat label="Mean delay" value={`${s.delay_ms_mean.toFixed(1)} ms`} />
          <Stat label="Max delay" value={`${s.delay_ms_max.toFixed(1)} ms`} bad={s.delay_ms_max > 1000} />
        </div>
        <TableCard
          label="Packets"
          maxHeight="20rem"
          exportData={() => ({
            headers: ['Packet', 'Route', 'Point', 'Sent (s)', 'Received (s)', 'Delay (ms)', 'Status'],
            rows: L.channel.packets.map((p) => [
              String(p.packet_id), `${p.source} -> ${p.destination}`, p.point_id,
              num(p.send_time_s, 3),
              Number.isFinite(p.receive_time_s) ? num(p.receive_time_s, 3) : '',
              p.delay_ms.toFixed(1), p.dropped ? 'dropped' : 'delivered',
            ]),
          })}
        >
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">#</TableHead>
              <TableHead className="text-xs">From → To</TableHead>
              <TableHead className="text-xs">Point</TableHead>
              <TableHead className="text-xs">Send (s)</TableHead>
              <TableHead className="text-xs">Receive (s)</TableHead>
              <TableHead className="text-xs">Delay (ms)</TableHead>
              <TableHead className="text-xs">Status</TableHead>
            </TableRow>
          </TableHeader>
          <VirtualTableBody
            items={L.channel.packets}
            renderRow={(p) => (
              <TableRow key={p.packet_id} style={{ height: RESULT_ROW_HEIGHT }}>
                <TableCell className="text-xs text-muted-foreground">{p.packet_id}</TableCell>
                <TableCell className="text-xs">{p.source} → {p.destination}</TableCell>
                <TableCell className="font-mono text-xs">{p.point_id}</TableCell>
                <TableCell className="font-mono text-xs">{num(p.send_time_s, 3)}</TableCell>
                <TableCell className="font-mono text-xs">
                  {Number.isFinite(p.receive_time_s) ? num(p.receive_time_s, 3) : '—'}
                </TableCell>
                <TableCell className="font-mono text-xs">{p.delay_ms.toFixed(1)}</TableCell>
                <TableCell className={`text-xs ${p.dropped ? 'text-destructive' : 'text-status-good'}`}>
                  {p.dropped ? 'dropped' : 'delivered'}
                </TableCell>
              </TableRow>
            )}
          />
        </TableCard>
      </div>
    )
  }

  if (layer === 'rtdb') {
    const s = L.rtdb.summary
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <Stat label="Points" value={`${s.n_usable} / ${s.n_points} usable`} />
          <Stat label="Stale" value={String(s.n_stale)} bad={s.n_stale > 0} />
          <Stat label="Bad" value={String(s.n_bad)} bad={s.n_bad > 0} />
          <Stat label="Snapshot spread" value={`${s.timestamp_spread_s.toFixed(3)} s`} bad={s.timestamp_spread_s > 1} />
          <Stat label="Max age" value={`${s.max_age_s.toFixed(3)} s`} bad={s.max_age_s > s.stale_after_s} />
        </div>
        <p className="text-xs text-muted-foreground">
          Snapshot spread is the gap between the newest and the oldest reading the estimator is
          about to treat as simultaneous. It is never zero — RTUs scan their points in sequence.
        </p>
        <TableCard
          label="RTDB point database"
          maxHeight="20rem"
          exportData={() => ({
            headers: ['Point', 'RTU', 'Value', 'Source ts (s)', 'Received ts (s)', 'Age (s)', 'Quality'],
            rows: L.rtdb.records.map((r) => [
              r.point_id, r.rtu_id,
              r.never_received ? 'no data' : num(r.value, 5),
              num(r.source_timestamp_s, 3),
              r.receive_timestamp_s == null ? '' : num(r.receive_timestamp_s, 3),
              num(r.age_s, 3), `${r.quality}${r.stale ? ' - stale' : ''}`,
            ]),
          })}
        >
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">Point ID</TableHead>
              <TableHead className="text-xs">RTU</TableHead>
              <TableHead className="text-xs">Value</TableHead>
              <TableHead className="text-xs">Source t</TableHead>
              <TableHead className="text-xs">Recv t</TableHead>
              <TableHead className="text-xs">Age (s)</TableHead>
              <TableHead className="text-xs">Quality</TableHead>
            </TableRow>
          </TableHeader>
          <VirtualTableBody
            items={L.rtdb.records}
            renderRow={(r) => (
              <TableRow key={r.point_id} style={{ height: RESULT_ROW_HEIGHT }}>
                <TableCell className="font-mono text-xs font-medium">{r.point_id}</TableCell>
                <TableCell className="text-xs">{r.rtu_id}</TableCell>
                <TableCell className="font-mono text-xs">
                  {r.never_received ? <span className="text-destructive">no data</span> : num(r.value, 5)}
                </TableCell>
                <TableCell className="font-mono text-xs">{num(r.source_timestamp_s, 3)}</TableCell>
                <TableCell className="font-mono text-xs">
                  {r.receive_timestamp_s == null ? '—' : num(r.receive_timestamp_s, 3)}
                </TableCell>
                <TableCell className="font-mono text-xs">{num(r.age_s, 3)}</TableCell>
                <TableCell className={`text-xs ${QUALITY_COLOR[r.quality]}`}>
                  {r.quality}{r.stale ? ' · stale' : ''}
                </TableCell>
              </TableRow>
            )}
          />
        </TableCard>
      </div>
    )
  }

  if (layer === 'topology') {
    const s = L.topology.summary
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="0 — Intermediate (0,0)" value={String(s.status_counts['0'] ?? 0)} bad={(s.status_counts['0'] ?? 0) > 0} />
          <Stat label="1 — Determined OFF (0,1)" value={String(s.status_counts['1'] ?? 0)} />
          <Stat label="2 — Determined ON (1,0)" value={String(s.status_counts['2'] ?? 0)} />
          <Stat label="3 — Indeterminate (1,1)" value={String(s.status_counts['3'] ?? 0)} bad={(s.status_counts['3'] ?? 0) > 0} />
        </div>
        <p className="text-xs text-muted-foreground">
          Each breaker reports two auxiliary contacts — 52a (closes with the breaker) and 52b (opens
          with it) — packed as the 2-bit value <code>2·52a + 52b</code>. This is not our own
          convention: it is the DNP3 <em>Double-Bit Binary Input</em> (Object Group 3/4) and the
          IEC 61850 <code>Dbpos</code> carried in an XCBR <code>Pos.stVal</code>, the same object a
          real control centre already receives from the field. Only codes 1 and 2 are conclusive;
          0 and 3 leave the decision to the selected policy — which is exactly where an agent acts.
        </p>
        <TableCard
          label="Switch telemetry"
          maxHeight="20rem"
          exportData={() => ({
            headers: ['Switch', 'Buses', 'Contact A', 'Contact B', 'Status', 'Resolved', 'Reason'],
            rows: L.topology.switches.map((sw) => [
              sw.name, `${sw.from_bus} - ${sw.to_bus}`, String(sw.contact_a), String(sw.contact_b),
              `${sw.status_code} - ${sw.status_label}`,
              `${sw.resolved_closed ? 'closed' : 'open'}${L.topology.mismatched_switch_ids.includes(sw.switch_id) ? ' (wrong!)' : ''}`,
              sw.resolution_reason,
            ]),
          })}
        >
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">Switch</TableHead>
              <TableHead className="text-xs">Buses</TableHead>
              <TableHead className="text-xs">52a</TableHead>
              <TableHead className="text-xs">52b</TableHead>
              <TableHead className="text-xs">State</TableHead>
              <TableHead className="text-xs">Resolved</TableHead>
              <TableHead className="text-xs">Reason</TableHead>
            </TableRow>
          </TableHeader>
          <VirtualTableBody
            items={L.topology.switches}
            renderRow={(sw) => {
              const wrong = L.topology.mismatched_switch_ids.includes(sw.switch_id)
              return (
                <TableRow key={sw.switch_id} style={{ height: RESULT_ROW_HEIGHT }} className={wrong ? 'bg-destructive/5' : undefined}>
                  <TableCell className="text-xs font-medium">{sw.name}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{sw.from_bus} ↔ {sw.to_bus}</TableCell>
                  <TableCell className="font-mono text-xs">{sw.contact_a}</TableCell>
                  <TableCell className="font-mono text-xs">{sw.contact_b}</TableCell>
                  <TableCell className={`text-xs font-medium ${STATUS_COLOR[sw.status_code]}`}>
                    {sw.status_code} — {sw.status_label}
                  </TableCell>
                  <TableCell className="text-xs">
                    {sw.resolved_closed ? 'closed' : 'open'}
                    {wrong && <span className="ml-1 font-medium text-destructive">(wrong!)</span>}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{sw.resolution_reason}</TableCell>
                </TableRow>
              )
            }}
          />
        </TableCard>
      </div>
    )
  }

  if (layer === 'opf') {
    const opf = L.opf
    if (!opf) {
      return (
        <Alert>
          <Warning className="h-4 w-4" />
          <AlertDescription className="text-xs">
            The control layer is off. Turn on “Control layer (OPF)” above and run again — it
            answers what the operator would actually have dispatched from this state, and what
            that would have done to the real network.
          </AlertDescription>
        </Alert>
      )
    }
    if (opf.error) {
      return (
        <Alert variant="destructive">
          <Warning className="h-4 w-4" />
          <AlertDescription className="text-xs">{opf.error}</AlertDescription>
        </Alert>
      )
    }
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Operator OPF" value={opf.operator.converged ? 'converged' : 'failed'}
            bad={!opf.operator.converged} />
          <Stat label="Max setpoint error" value={`${num(opf.max_setpoint_error_mw, 4)} MW`}
            bad={opf.max_setpoint_error_mw > 0} />
          <Stat label="Cost gap" value={opf.cost_gap == null ? '—' : num(opf.cost_gap, 3)}
            bad={Boolean(opf.cost_gap && Math.abs(opf.cost_gap) > 0)} />
          <Stat label="Hidden violations" value={String(opf.n_hidden_violations)}
            bad={opf.n_hidden_violations > 0} />
        </div>

        <p className="text-xs text-muted-foreground">
          The operator never solves the OPF on the real network — only on the model the topology
          processor rebuilt. These setpoints are then applied for real. A <b>hidden violation</b> is
          a constraint breached in reality that the operator's own OPF considered satisfied: no
          alarm is raised anywhere. Violations that would happen even with perfect information are
          subtracted out first, so what is left is caused by the wrong model, not by slack-bus
          modelling residue.
        </p>

        {opf.reason && (
          <Alert>
            <Warning className="h-4 w-4" />
            <AlertDescription className="text-xs">{opf.reason}</AlertDescription>
          </Alert>
        )}

        {opf.hidden_violations.length > 0 && (
          <TableCard label="Hidden violations" maxHeight="12rem">
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Kind</TableHead>
                <TableHead className="text-xs">Element</TableHead>
                <TableHead className="text-xs">Value</TableHead>
                <TableHead className="text-xs">Limit</TableHead>
                <TableHead className="text-xs">Margin</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {opf.hidden_violations.map((v, i) => (
                <TableRow key={i} className="bg-destructive/5">
                  <TableCell className="text-xs font-medium text-destructive">{v.kind}</TableCell>
                  <TableCell className="text-xs">{v.element} {v.index}</TableCell>
                  <TableCell className="font-mono text-xs">{num(v.value, 5)}</TableCell>
                  <TableCell className="font-mono text-xs">{num(v.limit, 5)}</TableCell>
                  <TableCell className="font-mono text-xs">{num(v.margin, 5)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </TableCard>
        )}

        <TableCard label="Setpoints dispatched vs ideal" maxHeight="18rem">
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">Element</TableHead>
              <TableHead className="text-xs">Bus</TableHead>
              <TableHead className="text-xs">P dispatched</TableHead>
              <TableHead className="text-xs">P ideal</TableHead>
              <TableHead className="text-xs">ΔP (MW)</TableHead>
              <TableHead className="text-xs">ΔQ (MVAr)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {opf.setpoint_deltas.map((d, i) => (
              <TableRow key={i}>
                <TableCell className="text-xs font-medium">{d.element} {d.index}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{d.bus}</TableCell>
                <TableCell className="font-mono text-xs">{num(d.p_dispatched, 5)}</TableCell>
                <TableCell className="font-mono text-xs">{num(d.p_ideal, 5)}</TableCell>
                <TableCell className={`font-mono text-xs ${Math.abs(d.delta_p_mw) > 1e-6 ? 'text-status-warn' : ''}`}>
                  {num(d.delta_p_mw, 5)}
                </TableCell>
                <TableCell className="font-mono text-xs">{num(d.delta_q_mvar, 5)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </TableCard>
      </div>
    )
  }

  if (layer === 'agents') {
    const agents = L.agents
    if (!agents) {
      return (
        <Alert>
          <Warning className="h-4 w-4" />
          <AlertDescription className="text-xs">
            The agent layer was not run for this chain.
          </AlertDescription>
        </Alert>
      )
    }
    return (
      <div className="space-y-3">
        <p className="text-xs text-muted-foreground">
          One agent per layer, run in chain order. Each judges only its own layer, but its verdict
          becomes the next one's input — which is why the final recommendation is something no
          single agent, and no fixed threshold, would have reached alone. Agents never recompute
          anything: turning them off changes no number in the result.
        </p>

        <div className="space-y-2">
          {agents.findings.map((f, i) => <FindingCard key={i} finding={f} />)}
        </div>

        {agents.messages.length > 0 && (
          <TableCard label="Inter-agent messages" maxHeight="14rem">
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">From → To</TableHead>
                <TableHead className="text-xs">Type</TableHead>
                <TableHead className="text-xs">Priority</TableHead>
                <TableHead className="text-xs">Bytes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {agents.messages.map((m, i) => (
                <TableRow key={i}>
                  <TableCell className="text-xs">
                    {m.sender.replace('Agent_', '')} → {m.recipient.replace('Agent_', '')}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{m.type}</TableCell>
                  <TableCell className={`text-xs ${m.priority === 'CRITICAL' ? 'text-destructive' : ''}`}>
                    {m.priority}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{m.bytes}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </TableCard>
        )}
      </div>
    )
  }

  // estimation
  const est = L.estimation
  if (!est?.ran) {
    return (
      <Alert>
        <Warning className="h-4 w-4" />
        <AlertDescription className="text-xs">
          The estimator did not run: {est?.reason ?? 'unknown reason'}
        </AlertDescription>
      </Alert>
    )
  }
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Stat label="Converged" value={est.converged ? 'yes' : 'no'} bad={!est.converged} />
        <Stat label="Measurements" value={`${est.n_measurements} / ${est.n_states} states`} />
        <Stat label="J" value={num(est.J, 3)} bad={est.chi2_passed === false} />
        <Stat label="χ² limit (95%)" value={num(est.chi2_limit, 3)} />
        <Stat label="max |ΔV|" value={`${num(est.max_vm_error, 6)} pu`} />
      </div>
      {est.model_open_line_ids && est.model_open_line_ids.length > 0 && (
        <p className="text-xs text-status-warn">
          The estimator model treats line(s) {est.model_open_line_ids.join(', ')} as open,
          following the reconstructed topology.
        </p>
      )}
      <TableCard
        label="Estimated vs true state"
        maxHeight="20rem"
        exportData={() => ({
          headers: ['Bus', '|V| true', '|V| est', 'd|V|', 'theta true', 'theta est', 'd theta (deg)'],
          rows: (est.comparison ?? []).map((c) => [
            String(c.busId), num(c.vm_true, 5), num(c.vm_est, 5), num(c.vm_error, 5),
            num(c.va_true, 3), num(c.va_est, 3), num(c.va_error, 3),
          ]),
        })}
      >
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs">Bus</TableHead>
            <TableHead className="text-xs">|V| true</TableHead>
            <TableHead className="text-xs">|V| est</TableHead>
            <TableHead className="text-xs">Δ|V|</TableHead>
            <TableHead className="text-xs">θ true</TableHead>
            <TableHead className="text-xs">θ est</TableHead>
            <TableHead className="text-xs">Δθ (°)</TableHead>
          </TableRow>
        </TableHeader>
        <VirtualTableBody
          items={est.comparison ?? []}
          renderRow={(c) => (
            <TableRow key={c.busId} style={{ height: RESULT_ROW_HEIGHT }}>
              <TableCell className="text-xs font-medium">{c.busId}</TableCell>
              <TableCell className="font-mono text-xs">{num(c.vm_true, 5)}</TableCell>
              <TableCell className="font-mono text-xs">{num(c.vm_est, 5)}</TableCell>
              <TableCell className={`font-mono text-xs ${Math.abs(c.vm_error) > 0.01 ? 'text-destructive' : ''}`}>
                {num(c.vm_error, 5)}
              </TableCell>
              <TableCell className="font-mono text-xs">{num(c.va_true, 3)}</TableCell>
              <TableCell className="font-mono text-xs">{num(c.va_est, 3)}</TableCell>
              <TableCell className={`font-mono text-xs ${Math.abs(c.va_error) > 0.5 ? 'text-destructive' : ''}`}>
                {num(c.va_error, 3)}
              </TableCell>
            </TableRow>
          )}
        />
      </TableCard>
    </div>
  )
}

function FindingCard({ finding }: { finding: AgentFinding }) {
  const border = {
    ok: 'border-status-good/40',
    info: 'border-border',
    warning: 'border-status-warn/50',
    critical: 'border-destructive/50',
  }[finding.severity]

  return (
    <div className={`rounded-md border-2 p-2.5 ${border}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="h-5 text-[10px] uppercase">{finding.layer}</Badge>
        <span className="text-xs font-semibold">{finding.agent.replace('Agent_', '')}</span>
        <span className={`text-xs font-medium ${SEVERITY_COLOR[finding.severity]}`}>
          {finding.title}
        </span>
        {finding.caused_by.length > 0 && (
          <span className="ml-auto font-mono text-[10px] text-muted-foreground">
            ← {finding.caused_by.join(', ')}
          </span>
        )}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{finding.detail}</p>
    </div>
  )
}

function Stat({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="rounded-md border p-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`text-sm font-semibold ${bad ? 'text-status-warn' : ''}`}>{value}</div>
    </div>
  )
}
