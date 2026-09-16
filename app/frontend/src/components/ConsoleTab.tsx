/**
 * ConsoleTab — the operator-facing view of the operational chain.
 *
 * The Pipeline tab is an engineering view: every knob, every table, one block
 * per layer. This is the same run seen the way a control room sees it, because
 * the audience that decides whether this research gets funded (an RTE or an
 * Enedis) reads an HMI, not a debugger.
 *
 * What is deliberately borrowed from a real ADMS/SCADA console:
 *
 * - a **status band** across the top, carrying the one thing the operator asks
 *   first ("can I act on this?") as a hero, with an alarm-count summary beside it;
 * - an **alarm list** as a first-class panel — chronological, priority-coded,
 *   with a source column naming the equipment;
 * - a **single-line diagram** as the spatial anchor;
 * - a **telemetry point list** with quality flags and data age, in the SCADA
 *   vocabulary (point ID, equipment, quality, age) rather than in ours.
 *
 * What is deliberately NOT borrowed: the density of a real HMI, which assumes
 * weeks of training. The layout stays legible to someone seeing it for the
 * first time.
 *
 * And one thing a real console does not have, which is the whole point of the
 * research: the **process mimic of the chain itself**. An operator today sees
 * the estimate; they cannot see that it was built from a snapshot spanning
 * four seconds, over a topology reconstructed from two inconclusive contacts.
 * That strip is the contribution, and it is placed where a mimic diagram would
 * normally go.
 *
 * Scenario presets exist for the same reason: a visitor should be able to see
 * a topology attack propagate to a control decision in one click, without
 * knowing what a 52b contact is.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { TableCard } from '@/components/TableCard'
import { TopologyDiagram } from '@/components/TopologyDiagram'
import {
  Play, Spinner, Warning, CheckCircle, XCircle, Info, Bell,
  Lightning, Radio, WifiHigh, Database, TreeStructure, ChartLine, Crosshair,
  SlidersHorizontal, Cpu,
} from '@phosphor-icons/react'
import { toast } from 'sonner'
import { runPipeline, type PipelineRequest, type PipelineResult } from '@/lib/api'
import type { Topology } from '@/lib/types'

interface ConsoleTabProps {
  topology: Topology
  /** A stored case is still being fetched, so `topology` is the placeholder
   *  default rather than the network the user will actually be looking at. */
  restoring?: boolean
}

// ─── Scenario presets ────────────────────────────────────────────────────────

/** Named situations, so the chain can be demonstrated without knowing the
 *  vocabulary. Each is a full request override — the console never asks the
 *  visitor to assemble an attack. */
interface Scenario {
  id: string
  label: string
  blurb: string
  overrides: Partial<PipelineRequest>
}

const SCENARIOS: Scenario[] = [
  {
    id: 'normal',
    label: 'Normal operation',
    blurb: 'Healthy links, coherent breaker status. The reference every other scenario is read against.',
    overrides: {},
  },
  {
    id: 'comms',
    label: 'Degraded link on one RTU',
    blurb:
      'Every measurement is legitimate and correct. One RTU’s traffic is delayed, so the snapshot the estimator receives mixes two different instants of the network.',
    overrides: {
      attacks: [{ attack_id: 'delay_attack', target: 'RTU-1', params: { delay_ms: 9000 } }],
      stale_after_s: 4,
    },
  },
  {
    id: 'loss',
    label: 'Packet loss on the network',
    blurb: 'A third of the telemetry never arrives. Redundancy falls; observability is what is at stake, not data quality.',
    overrides: { channel: { base_delay_ms: 50, jitter_ms: 20, drop_probability: 0.3 } },
  },
  {
    id: 'topology',
    label: 'Falsified breaker status',
    blurb:
      'No analogue measurement is wrong. One breaker reports the opposite position, coherently, so the status looks perfect and describes another network. The estimator then solves the wrong problem correctly.',
    overrides: { attacks: [{ attack_id: 'breaker_status_falsification', target: '1' }] },
  },
  {
    id: 'desync',
    label: 'Breaker contacts disagree',
    blurb:
      'The breaker reports both contacts closed — an impossible position. The status is not a lie, the certainty is gone, and the resolution falls to policy. This is where an agent can act.',
    overrides: {
      attacks: [{ attack_id: 'contact_desync', target: '1', params: { mode: 'both_on' } }],
      unreliable_policy: 'flow_inference',
    },
  },
  {
    id: 'rtu',
    label: 'Compromised RTU',
    blurb:
      'A whole remote unit reports biased values. The error is correlated inside one physical block, which is what a real intrusion looks like — and it leaves a spread signature, not an isolated outlier.',
    overrides: {
      attacks: [{ attack_id: 'rtu_compromise', target: 'RTU-1', params: { magnitude_sigma: 20 } }],
    },
  },
]

// ─── Status vocabulary ───────────────────────────────────────────────────────

type Level = 'ok' | 'info' | 'warn' | 'alarm'

/** Status is never carried by colour alone: every level ships an icon and a
 *  word. Standard accessibility practice, and standard control-room practice —
 *  an alarm list is read as text first. */
const LEVEL: Record<Level, { icon: React.ElementType; word: string; text: string; ring: string; dot: string }> = {
  ok:    { icon: CheckCircle, word: 'NORMAL',  text: 'text-status-good',  ring: 'border-status-good/50',  dot: 'bg-status-good' },
  info:  { icon: Info,        word: 'INFO',    text: 'text-status-info',  ring: 'border-status-info/50',  dot: 'bg-status-info' },
  warn:  { icon: Warning,     word: 'WARNING', text: 'text-status-warn',  ring: 'border-status-warn/60',  dot: 'bg-status-warn' },
  alarm: { icon: XCircle,     word: 'ALARM',   text: 'text-destructive',  ring: 'border-destructive/60',  dot: 'bg-destructive' },
}

const RECOMMENDATION: Record<string, { level: Level; head: string; sub: string }> = {
  dispatch: { level: 'ok',    head: 'CONTROL RELEASED', sub: 'The delivered state supports acting on the network.' },
  derate:   { level: 'warn',  head: 'CONTROL LIMITED',  sub: 'Conservative action only — no switching.' },
  block:    { level: 'alarm', head: 'CONTROL BLOCKED',  sub: 'The delivered state does not support acting.' },
}

const STAGES: Array<{ key: string; label: string; icon: React.ElementType }> = [
  { key: 'physical', label: 'Field', icon: Lightning },
  { key: 'measurement', label: 'Meters', icon: Crosshair },
  { key: 'rtu', label: 'RTU', icon: Radio },
  { key: 'channel', label: 'Telecom', icon: WifiHigh },
  { key: 'rtdb', label: 'SCADA', icon: Database },
  { key: 'topology', label: 'Topology', icon: TreeStructure },
  { key: 'estimation', label: 'Estimator', icon: ChartLine },
  { key: 'opf', label: 'Dispatch', icon: SlidersHorizontal },
  { key: 'agents', label: 'Agents', icon: Cpu },
]

/**
 * What one stage of the mimic has to say when the operator opens it.
 *
 * The strip answers "is this stage healthy?". Opening a stage answers "on what
 * evidence?", which is the question that follows immediately and, before this,
 * had no answer anywhere on the console: the Pipeline tab had the per-layer
 * tables, but that is the engineering view, and sending a visitor there to find
 * out why Telecom is amber defeats the point of having a console at all.
 *
 * Kept to a handful of rows per stage on purpose. This is the operator's
 * vocabulary (points, scan period, quality, age), not a dump of the layer's
 * payload — the full artefact stays one tab away for whoever wants it.
 */
function stageDetail(
  key: string,
  result: PipelineResult,
): { blurb: string; rows: Array<{ k: string; v: string }> } {
  const L = result.layers
  const rows: Array<{ k: string; v: string }> = []

  switch (key) {
    case 'physical': {
      const vms = L.physical.buses.map((b) => b.vm_pu)
      return {
        blurb: 'The true state of the network, known only to the simulator. Everything downstream is an attempt to recover it.',
        rows: [
          { k: 'Power flow', v: L.physical.converged ? 'converged' : 'did not converge' },
          { k: 'Buses', v: String(L.physical.buses.length) },
          { k: 'Branches', v: String(L.physical.lines.length) },
          { k: 'Voltage range', v: vms.length ? `${fmt(Math.min(...vms), 4)} – ${fmt(Math.max(...vms), 4)} pu` : '—' },
        ],
      }
    }
    case 'measurement': {
      const byKind: Record<string, number> = {}
      for (const r of L.measurement.rows) byKind[r.meterKind] = (byKind[r.meterKind] ?? 0) + 1
      for (const [kind, n] of Object.entries(byKind).sort()) rows.push({ k: kind, v: `${n} points` })
      return {
        blurb: 'What the meters in the field actually produced, before any of it was packetised or transmitted.',
        rows: [{ k: 'Measurements', v: String(L.measurement.n_measurements) }, ...rows],
      }
    }
    case 'rtu': {
      for (const r of L.rtu.rtus) {
        rows.push({ k: r.rtu_id, v: `${r.n_points} points · scan ${r.scan_period_s.toFixed(1)} s` })
      }
      return {
        blurb: 'Field measurements grouped into remote terminal units. The scan period is what sets the natural spread of a snapshot: a 4 s SCADA cycle cannot deliver a simultaneous picture.',
        rows: [{ k: 'RTUs', v: String(L.rtu.rtus.length) }, ...rows],
      }
    }
    case 'channel': {
      const s = L.channel.statistics
      for (const [rtu, ms] of Object.entries(s.delay_ms_by_rtu).sort()) {
        rows.push({ k: `Delay ${rtu}`, v: `${Number(ms).toFixed(0)} ms` })
      }
      return {
        blurb: 'The telecom link. A delayed measurement is still a correct measurement: what degrades here is not the value, it is the simultaneity of the snapshot built from it.',
        rows: [
          { k: 'Packets', v: String(s.n_packets) },
          { k: 'Dropped', v: `${s.n_dropped} (${(s.loss_rate * 100).toFixed(1)}%)` },
          { k: 'Delay mean / peak', v: `${s.delay_ms_mean.toFixed(0)} / ${s.delay_ms_max.toFixed(0)} ms` },
          ...rows,
        ],
      }
    }
    case 'rtdb': {
      const d = L.rtdb.summary
      return {
        blurb: 'The SCADA real-time database. Every point carries a quality flag and an age; the estimator only ever sees what is usable here.',
        rows: [
          { k: 'Points', v: `${d.n_usable} usable of ${d.n_points}` },
          { k: 'Stale', v: `${d.n_stale} (older than ${d.stale_after_s.toFixed(1)} s)` },
          { k: 'Bad / suspect', v: `${d.n_bad} / ${d.n_suspect}` },
          { k: 'Never received', v: String(d.n_never_received) },
          { k: 'Snapshot span', v: `${d.timestamp_spread_s.toFixed(3)} s` },
          { k: 'Oldest point', v: `${d.max_age_s.toFixed(2)} s` },
        ],
      }
    }
    case 'topology': {
      const t = L.topology.summary
      return {
        blurb: 'The network model rebuilt from breaker status. This is where a falsified status does its damage: the estimator then solves a correct problem on the wrong network.',
        rows: [
          { k: 'Switches', v: `${t.n_closed} closed · ${t.n_open} open` },
          { k: 'Inconclusive', v: `${t.n_unreliable}${t.n_unreliable ? ` (${t.unreliable_ids.join(', ')})` : ''}` },
          { k: 'Resolution policy', v: t.policy },
          { k: 'De-energised branches', v: t.open_line_ids.length ? t.open_line_ids.join(', ') : 'none' },
          {
            k: 'Matches reality',
            v: L.topology.matches_reality
              ? 'yes'
              : `no — switches ${L.topology.mismatched_switch_ids.join(', ')}`,
          },
        ],
      }
    }
    case 'estimation': {
      const e = L.estimation
      if (!e?.ran) return { blurb: 'The estimator did not run.', rows: [{ k: 'Reason', v: e?.reason ?? 'unknown' }] }
      const red = e.n_measurements && e.n_states ? e.n_measurements / e.n_states : null
      return {
        blurb: 'Weighted least squares over the reconstructed model. The chi-square test asks whether the residuals are consistent with the assumed measurement noise, nothing more.',
        rows: [
          { k: 'Converged', v: `${e.converged ? 'yes' : 'no'} in ${e.iterations ?? '—'} iterations` },
          { k: 'Measurements / states', v: `${e.n_measurements ?? '—'} / ${e.n_states ?? '—'}` },
          { k: 'Redundancy', v: red ? fmt(red, 2) : '—' },
          { k: 'J', v: `${fmt(e.J, 3)} against a ${fmt(e.chi2_limit, 3)} threshold` },
          { k: 'Chi-square', v: e.chi2_passed ? 'passed' : 'failed' },
          { k: 'Largest voltage error', v: `${fmt(e.max_vm_error, 5)} pu` },
        ],
      }
    }
    case 'opf': {
      const o = L.opf
      if (!o) return { blurb: 'The control layer was not run for this scenario.', rows: [] }
      if (o.error) return { blurb: 'The control layer failed.', rows: [{ k: 'Error', v: o.error }] }
      if (!o.operator.converged) {
        return {
          blurb: 'The optimiser found no dispatch on the model the operator reconstructed. That is a result, not a crash: the reason below says whether the limits were impossible or the solver failed.',
          rows: [{ k: 'Reason', v: o.reason ?? o.operator.reason ?? 'not reported' }],
        }
      }
      return {
        blurb: 'The dispatch the operator would issue, compared against the one they would have issued knowing everything. A hidden violation is a constraint broken in reality that their OPF believed was satisfied.',
        rows: [
          { k: 'Setpoints', v: String(o.operator.setpoints.length) },
          { k: 'Largest setpoint error', v: `${fmt(o.max_setpoint_error_mw, 4)} MW` },
          { k: 'Total setpoint error', v: `${fmt(o.total_setpoint_error_mw, 4)} MW` },
          { k: 'Hidden violations', v: String(o.n_hidden_violations) },
          { k: 'Cost gap', v: o.cost_gap == null ? '—' : fmt(o.cost_gap, 4) },
          { k: 'Voltage band', v: `${o.limits.vm_min_pu} – ${o.limits.vm_max_pu} pu` },
        ],
      }
    }
    case 'agents': {
      const a = L.agents
      if (!a) return { blurb: 'The agent layer was not run for this scenario.', rows: [] }
      for (const p of a.propagation) {
        rows.push({ k: p.agent.replace('Agent_', ''), v: `${p.title} ← ${p.caused_by.join(', ')}` })
      }
      return {
        blurb: 'Agents judge each layer and pass their judgement on. They recompute nothing: turning them off changes no number in the run, which is what makes "with" and "without" comparable.',
        rows: [
          { k: 'Verdict', v: a.recommendation.toUpperCase() },
          { k: 'Findings', v: `${a.findings.length} (worst: ${a.worst_severity})` },
          { k: 'Messages', v: `${a.n_messages} · ${a.total_bytes} bytes` },
          ...(rows.length ? rows : [{ k: 'Propagation', v: 'no finding was caused by another layer' }]),
        ],
      }
    }
    default:
      return { blurb: '', rows: [] }
  }
}

/** Double-bit code → what the operator reads. Codes 1 and 2 are the conclusive
 *  readings (DNP3 Determined OFF / ON, IEC 61850 Dbpos off / on). */
const SWITCH_CODE: Record<number, { label: string; level: Level }> = {
  0: { label: 'Intermediate', level: 'warn' },
  1: { label: 'Open', level: 'info' },
  2: { label: 'Closed', level: 'ok' },
  3: { label: 'Indeterminate', level: 'alarm' },
}

function fmt(v: number | null | undefined, d = 3): string {
  return v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d)
}

/** Simulation seconds → a wall-clock-looking stamp. Operators read times, not
 *  offsets; the chain has no real clock, so this is anchored at an arbitrary
 *  shift start and is only ever used for display. */
function stamp(seconds: number): string {
  const base = 6 * 3600 // 06:00:00, start of shift
  const t = Math.max(0, base + seconds)
  const h = Math.floor(t / 3600) % 24
  const m = Math.floor(t / 60) % 60
  const s = Math.floor(t) % 60
  const ms = Math.floor((t % 1) * 1000)
  const p = (n: number, w = 2) => String(n).padStart(w, '0')
  return `${p(h)}:${p(m)}:${p(s)}.${p(ms, 3)}`
}

interface Alarm {
  time: number
  level: Level
  priority: 'HIGH' | 'MED' | 'LOW'
  source: string
  message: string
  origin: string
}

/** Above this bus count the console waits to be told to run. Chosen to match
 *  LARGE_NETWORK_BUSES in topologyLayout.ts — the same "this is no longer a
 *  test feeder" line the diagram uses to switch renderers. */
const CONSOLE_AUTORUN_MAX_BUSES = 300

export function ConsoleTab({ topology, restoring = false }: ConsoleTabProps) {
  const [scenarioId, setScenarioId] = useState('normal')
  const [result, setResult] = useState<PipelineResult | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /** Which stage of the mimic is expanded, if any. Deliberately not reset when
   *  a new run finishes: an operator comparing scenarios wants to keep looking
   *  at the same stage across runs, the same reason the diagram keeps its pan
   *  and zoom when meters are toggled. */
  const [openStage, setOpenStage] = useState<string | null>(null)

  const scenario = SCENARIOS.find((s) => s.id === scenarioId) ?? SCENARIOS[0]

  const run = useCallback(async () => {
    setRunning(true)
    setError(null)
    try {
      const res = await runPipeline({
        topology,
        seed: 42,
        add_noise: true,
        channel: { base_delay_ms: 50, jitter_ms: 10, drop_probability: 0 },
        stale_after_s: 10,
        run_opf: true,
        run_agents: true,
        ...scenario.overrides,
      })
      setResult(res)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
      toast.error('Chain run failed')
    } finally {
      setRunning(false)
    }
  }, [topology, scenario])

  // Run once on mount so the console is never an empty screen — a control room
  // that shows nothing until you press a button reads as broken.
  //
  // Except on a large network, where the reasoning inverts. This posts the
  // whole topology and asks for power flow, measurements, DSSE, OPF and agents
  // in one go; on a few-thousand-bus case that is megabytes up, a long solve,
  // and megabytes back, none of it asked for. Console is the landing tab, so
  // with a large network restored from storage it fired on boot and the app
  // came up wedged on a spinner. Past the threshold we show the button and let
  // the operator decide — an explicit "press Run" reads as deliberate, a
  // ten-second freeze reads as broken.
  //
  // It also has to wait out a topology restore. Firing while the placeholder
  // default is on screen would solve the wrong network and leave a result
  // labelled with a feeder nobody asked about.
  const autoRuns = topology.buses.length <= CONSOLE_AUTORUN_MAX_BUSES
  const autoRanRef = useRef(false)
  useEffect(() => {
    if (restoring || autoRanRef.current || !autoRuns) return
    autoRanRef.current = true
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restoring, autoRuns])

  const alarms: Alarm[] = useMemo(() => {
    if (!result) return []
    const out: Alarm[] = []

    for (const p of result.trace.problems) {
      out.push({
        time: p.timestamp_s,
        level: p.level === 'error' ? 'alarm' : 'warn',
        priority: p.level === 'error' ? 'HIGH' : 'MED',
        source: p.subject,
        message: p.message,
        origin: p.layer,
      })
    }
    for (const f of result.layers.agents?.findings ?? []) {
      if (f.severity === 'ok') continue
      out.push({
        time: 0,
        level: f.severity === 'critical' ? 'alarm' : f.severity === 'warning' ? 'warn' : 'info',
        priority: f.severity === 'critical' ? 'HIGH' : f.severity === 'warning' ? 'MED' : 'LOW',
        source: f.agent.replace('Agent_', ''),
        message: `${f.title} — ${f.detail}`,
        origin: f.layer,
      })
    }

    const rank = { HIGH: 0, MED: 1, LOW: 2 }
    return out.sort((a, b) => rank[a.priority] - rank[b.priority] || b.time - a.time)
  }, [result])

  const counts = useMemo(() => ({
    high: alarms.filter((a) => a.priority === 'HIGH').length,
    med: alarms.filter((a) => a.priority === 'MED').length,
    low: alarms.filter((a) => a.priority === 'LOW').length,
  }), [alarms])

  const stageLevel = useMemo((): Record<string, { level: Level; value: string }> => {
    const blank = { level: 'info' as Level, value: '—' }
    if (!result) return Object.fromEntries(STAGES.map((s) => [s.key, blank]))
    const L = result.layers
    const est = L.estimation
    const ch = L.channel.statistics
    const db = L.rtdb.summary
    const tp = L.topology

    return {
      physical: { level: L.physical.converged ? 'ok' : 'alarm', value: `${L.physical.buses.length} buses` },
      measurement: { level: 'ok', value: `${L.measurement.n_measurements} points` },
      rtu: { level: 'ok', value: `${L.rtu.rtus.length} RTUs` },
      channel: {
        level: ch.n_dropped > 0 ? 'warn' : ch.delay_ms_max > 1000 ? 'warn' : 'ok',
        value: `${(ch.loss_rate * 100).toFixed(0)}% loss · ${ch.delay_ms_max.toFixed(0)} ms`,
      },
      rtdb: {
        level: db.n_bad > 0 ? 'alarm' : db.n_stale > 0 ? 'warn' : 'ok',
        value: `${db.n_usable}/${db.n_points} good · ${db.timestamp_spread_s.toFixed(1)} s span`,
      },
      topology: {
        level: !tp.matches_reality ? 'alarm' : tp.summary.n_unreliable > 0 ? 'warn' : 'ok',
        value: tp.summary.n_unreliable > 0
          ? `${tp.summary.n_unreliable} unreadable`
          : `${tp.summary.n_closed} closed · ${tp.summary.n_open} open`,
      },
      estimation: {
        level: !est?.ran ? 'alarm' : est.chi2_passed === false ? 'alarm' : 'ok',
        value: est?.ran ? `J = ${fmt(est.J, 1)}` : 'no state',
      },
      opf: {
        level: !L.opf ? 'info'
          : L.opf.error || !L.opf.operator.converged ? 'alarm'
          : L.opf.n_hidden_violations > 0 ? 'alarm'
          : L.opf.max_setpoint_error_mw > 0 ? 'warn' : 'ok',
        value: L.opf && !L.opf.error
          ? `Δ ${fmt(L.opf.max_setpoint_error_mw, 3)} MW`
          : L.opf?.error ? 'failed' : 'off',
      },
      agents: {
        level: !L.agents ? 'info'
          : L.agents.recommendation === 'dispatch' ? 'ok'
          : L.agents.recommendation === 'derate' ? 'warn' : 'alarm',
        value: L.agents ? L.agents.recommendation.toUpperCase() : 'off',
      },
    }
  }, [result])

  const rec = result?.layers.agents
    ? RECOMMENDATION[result.layers.agents.recommendation] ?? RECOMMENDATION.block
    : null
  const RecIcon = rec ? LEVEL[rec.level].icon : Info

  return (
    <div className="space-y-3">
      {/* ── Scenario bar ──────────────────────────────────────────────────── */}
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-3">
          <div className="min-w-64 flex-1 space-y-1">
            <Label className="text-xs">Situation</Label>
            <Select value={scenarioId} onValueChange={setScenarioId}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                {SCENARIOS.map((s) => (
                  <SelectItem key={s.id} value={s.id} className="text-xs">{s.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button size="sm" className="h-8 gap-1.5 text-xs" onClick={run} disabled={running}>
            {running ? <Spinner className="h-3.5 w-3.5 animate-spin" /> : <Play weight="fill" className="h-3.5 w-3.5" />}
            Run
          </Button>
          <p className="w-full text-xs text-muted-foreground">{scenario.blurb}</p>
          {restoring && (
            <p className="w-full text-xs text-status-warn">
              Restoring the saved network from the backend — the chain will not run until it is here.
            </p>
          )}
          {!restoring && !autoRuns && !result && !running && (
            <p className="w-full text-xs text-status-warn">
              {topology.buses.length} buses — the chain does not run on its own at this size.
              Press Run when you want it; a network this large takes a while to solve.
            </p>
          )}
        </CardContent>
      </Card>

      {error && (
        <Alert variant="destructive">
          <Warning className="h-4 w-4" />
          <AlertDescription className="text-xs">{error}</AlertDescription>
        </Alert>
      )}

      {result && rec && (
        <>
          {/* ── Status band ─────────────────────────────────────────────── */}
          <Card className={`border-2 ${LEVEL[rec.level].ring}`}>
            <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-3 p-4">
              <div className="flex items-center gap-3">
                <RecIcon weight="fill" className={`h-8 w-8 shrink-0 ${LEVEL[rec.level].text}`} />
                <div>
                  <div className={`text-lg font-bold leading-tight ${LEVEL[rec.level].text}`}>
                    {rec.head}
                  </div>
                  <div className="text-xs text-muted-foreground">{rec.sub}</div>
                </div>
              </div>

              <Separator orientation="vertical" className="hidden h-10 sm:block" />

              <div className="flex gap-4">
                <AlarmCount label="High" n={counts.high} level="alarm" />
                <AlarmCount label="Medium" n={counts.med} level="warn" />
                <AlarmCount label="Low" n={counts.low} level="info" />
              </div>

              <Separator orientation="vertical" className="hidden h-10 sm:block" />

              <div className="text-xs text-muted-foreground">
                <div><span className="font-medium text-foreground">{topology.name}</span></div>
                <div>
                  snapshot {stamp(result.layers.rtdb.summary.now_s)} · run {result.run_id} ·
                  {' '}{result.elapsed_ms.toFixed(0)} ms
                </div>
              </div>
            </CardContent>
          </Card>

          {/* ── Process mimic of the chain ──────────────────────────────── */}
          <Card>
            <CardContent className="p-3">
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Data path — field to control action
              </p>
              <div className="flex flex-wrap items-stretch gap-1">
                {STAGES.map((st, i) => {
                  const s = stageLevel[st.key]
                  const meta = LEVEL[s.level]
                  const open = openStage === st.key
                  return (
                    <div key={st.key} className="flex items-stretch">
                      <button
                        type="button"
                        disabled={!result}
                        aria-expanded={open}
                        aria-controls={open ? 'stage-detail' : undefined}
                        onClick={() => setOpenStage(open ? null : st.key)}
                        className={`min-w-28 flex-1 rounded-md border-2 p-2 text-left transition-colors ${meta.ring} ${
                          open ? 'ring-2 ring-ring ring-offset-1' : ''
                        } ${result ? 'cursor-pointer hover:bg-muted/50' : 'cursor-default opacity-90'}`}
                      >
                        <div className="flex items-center gap-1.5">
                          <span className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} aria-hidden />
                          <st.icon weight="fill" className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                          <span className="truncate text-xs font-semibold">{st.label}</span>
                        </div>
                        <div className={`mt-1 truncate text-xs ${meta.text}`}>{s.value}</div>
                        <div className="sr-only">
                          {meta.word}. {result ? 'Select to see the evidence for this stage.' : ''}
                        </div>
                      </button>
                      {i < STAGES.length - 1 && (
                        <div className="flex items-center px-0.5 text-muted-foreground" aria-hidden>›</div>
                      )}
                    </div>
                  )
                })}
              </div>
              {result && openStage && (() => {
                const st = STAGES.find((x) => x.key === openStage)
                const d = stageDetail(openStage, result)
                return (
                  <div id="stage-detail" className="mt-2 rounded-md border bg-muted/40 p-3">
                    <div className="mb-1.5 flex items-center gap-1.5">
                      {st && <st.icon weight="fill" className="h-4 w-4 shrink-0 text-muted-foreground" />}
                      <span className="text-xs font-semibold">{st?.label}</span>
                      <Button
                        size="sm" variant="ghost"
                        className="ml-auto h-6 px-2 text-xs"
                        onClick={() => setOpenStage(null)}
                      >
                        Close
                      </Button>
                    </div>
                    <p className="mb-2 text-xs text-muted-foreground">{d.blurb}</p>
                    <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2 xl:grid-cols-3">
                      {d.rows.map((r) => (
                        <div key={r.k} className="flex gap-2 text-xs">
                          <dt className="shrink-0 text-muted-foreground">{r.k}</dt>
                          <dd className="ml-auto text-right font-medium tabular-nums">{r.v}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                )
              })()}
              <p className="mt-2 text-xs text-muted-foreground">
                A control room today sees the last box. This strip is what the rest of the path did
                to the data before it got there. Select any stage to see the evidence behind it.
              </p>
            </CardContent>
          </Card>

          {/* ── Diagram + alarms ───────────────────────────────────────── */}
          <div className="grid gap-3 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            <div className="space-y-3">
              <TopologyDiagram topology={topology} compact />
              <SwitchStrip result={result} />
            </div>
            <AlarmPanel alarms={alarms} />
          </div>

          {/* ── Telemetry ──────────────────────────────────────────────── */}
          <TelemetryPanel result={result} />
        </>
      )}
    </div>
  )
}

function AlarmCount({ label, n, level }: { label: string; n: number; level: Level }) {
  const meta = LEVEL[level]
  return (
    <div className="text-center">
      <div className={`text-xl font-bold leading-none ${n > 0 ? meta.text : 'text-muted-foreground'}`}>
        {n}
      </div>
      <div className="mt-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  )
}

/** The alarm list, as close to a control-room one as is honest: newest and most
 *  severe first, priority as a word, source naming the equipment or the agent. */
function AlarmPanel({ alarms }: { alarms: Alarm[] }) {
  return (
    <Card className="flex flex-col">
      <CardContent className="flex min-h-0 flex-1 flex-col gap-2 p-3">
        <div className="flex items-center gap-1.5">
          <Bell weight="fill" className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Alarms and events
          </span>
          <Badge variant="secondary" className="ml-auto text-[10px]">{alarms.length}</Badge>
        </div>

        {alarms.length === 0 ? (
          <div className="flex flex-1 items-center justify-center gap-2 rounded-md border border-dashed p-6 text-xs text-status-good">
            <CheckCircle weight="fill" className="h-4 w-4" />
            No active alarms
          </div>
        ) : (
          <TableCard label="Alarm list" maxHeight="26rem">
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Time</TableHead>
                <TableHead className="text-xs">Pri</TableHead>
                <TableHead className="text-xs">Source</TableHead>
                <TableHead className="text-xs">Description</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {alarms.map((a, i) => {
                const meta = LEVEL[a.level]
                const Icon = meta.icon
                return (
                  <TableRow key={i}>
                    <TableCell className="whitespace-nowrap font-mono text-[11px] text-muted-foreground">
                      {stamp(a.time)}
                    </TableCell>
                    <TableCell>
                      <span className={`flex items-center gap-1 text-[11px] font-semibold ${meta.text}`}>
                        <Icon weight="fill" className="h-3 w-3 shrink-0" />
                        {a.priority}
                      </span>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-[11px]">
                      <span className="font-medium">{a.source}</span>
                      <span className="ml-1 uppercase text-muted-foreground">{a.origin}</span>
                    </TableCell>
                    <TableCell className="text-[11px]">{a.message}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </TableCard>
        )}
      </CardContent>
    </Card>
  )
}

/** Breaker positions in the operator's words, with the protocol code kept
 *  visible — it is what their own SCADA carries, and naming it is the point. */
function SwitchStrip({ result }: { result: PipelineResult }) {
  const sws = result.layers.topology.switches
  const wrong = result.layers.topology.mismatched_switch_ids

  return (
    <Card>
      <CardContent className="p-3">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          Breaker positions — DNP3 double-bit / IEC 61850 Dbpos
        </p>
        <div className="flex flex-wrap gap-1.5">
          {sws.map((sw) => {
            const code = SWITCH_CODE[sw.status_code] ?? SWITCH_CODE[0]
            const meta = LEVEL[code.level]
            const Icon = meta.icon
            const isWrong = wrong.includes(sw.switch_id)
            return (
              <div
                key={sw.switch_id}
                className={`rounded-md border-2 px-2 py-1 ${meta.ring} ${isWrong ? 'ring-2 ring-destructive/40' : ''}`}
                title={`${sw.name}: contacts (${sw.contact_a}, ${sw.contact_b}) → code ${sw.status_code} · ${sw.resolution_reason}`}
              >
                <div className="flex items-center gap-1">
                  <Icon weight="fill" className={`h-3 w-3 shrink-0 ${meta.text}`} />
                  <span className="text-[11px] font-semibold">{sw.name}</span>
                </div>
                <div className={`text-[10px] ${meta.text}`}>
                  {code.label} <span className="font-mono text-muted-foreground">({sw.status_code})</span>
                </div>
              </div>
            )
          })}
        </div>
        {wrong.length > 0 && (
          <p className="mt-2 flex items-start gap-1.5 text-xs text-destructive">
            <XCircle weight="fill" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              The reconstructed network disagrees with the field on {wrong.length} breaker(s).
              Outside a simulator this is invisible: no measurement would reveal it.
            </span>
          </p>
        )}
      </CardContent>
    </Card>
  )
}

/** The SCADA point list, in SCADA vocabulary. Sorted worst-quality first,
 *  because that is the row an operator is looking for. */
function TelemetryPanel({ result }: { result: PipelineResult }) {
  const [onlySuspect, setOnlySuspect] = useState(false)
  const records = result.layers.rtdb.records
  const rank: Record<string, number> = { bad: 0, suspect: 1, good: 2 }

  const rows = useMemo(() => {
    const r = onlySuspect ? records.filter((x) => x.quality !== 'good' || x.stale) : records
    return [...r].sort((a, b) => (rank[a.quality] ?? 3) - (rank[b.quality] ?? 3) || b.age_s - a.age_s)
  }, [records, onlySuspect])

  const qualityLevel = (q: string, stale: boolean): Level =>
    q === 'bad' ? 'alarm' : q === 'suspect' || stale ? 'warn' : 'ok'

  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Telemetry — SCADA point list
          </span>
          <span className="text-xs text-muted-foreground">
            {result.layers.rtdb.summary.n_usable} of {result.layers.rtdb.summary.n_points} usable ·
            oldest reading {fmt(result.layers.rtdb.summary.max_age_s, 2)} s
          </span>
          <Button size="sm" variant="outline" className="ml-auto h-6 text-[11px]"
            onClick={() => setOnlySuspect((v) => !v)}>
            {onlySuspect ? 'Show all points' : 'Show only degraded'}
          </Button>
        </div>

        <TableCard label="Telemetry" maxHeight="20rem">
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">Point</TableHead>
              <TableHead className="text-xs">Equipment</TableHead>
              <TableHead className="text-xs">RTU</TableHead>
              <TableHead className="text-xs">Value</TableHead>
              <TableHead className="text-xs">Quality</TableHead>
              <TableHead className="text-xs">Age (s)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => {
              const lvl = qualityLevel(r.quality, r.stale)
              const meta = LEVEL[lvl]
              const Icon = meta.icon
              return (
                <TableRow key={r.point_id}>
                  <TableCell className="font-mono text-[11px] font-medium">{r.point_id}</TableCell>
                  <TableCell className="text-[11px] text-muted-foreground">{r.equipment_id}</TableCell>
                  <TableCell className="text-[11px]">{r.rtu_id}</TableCell>
                  <TableCell className="font-mono text-[11px]">
                    {r.never_received ? <span className="text-destructive">no data</span> : fmt(r.value, 4)}
                  </TableCell>
                  <TableCell>
                    <span className={`flex items-center gap-1 text-[11px] ${meta.text}`}>
                      <Icon weight="fill" className="h-3 w-3 shrink-0" />
                      {r.quality}{r.stale ? ' · stale' : ''}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-[11px]">{fmt(r.age_s, 2)}</TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </TableCard>
      </CardContent>
    </Card>
  )
}
