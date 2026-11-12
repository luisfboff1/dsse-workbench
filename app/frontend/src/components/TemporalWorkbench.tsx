import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowsOut, CircleNotch, Download, Play, FloppyDisk } from '@phosphor-icons/react'
import { OneLineView, type OneLineHandle } from '@/components/OneLineView'
import { TemporalPlayback } from '@/components/TemporalPlayback'
import { TableCard } from '@/components/TableCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { selectOnly } from '@/lib/selection'
import { QUANTITY_LABEL } from '@/lib/measurements'
import { DEFAULT_TEMPORAL_CONFIG, hourLabel, runTemporal, type TemporalConfig, type TemporalRun } from '@/lib/temporal'
import { listScenarios, loadScenario, saveScenario, type ScenarioSummary } from '@/lib/api'
import type { Topology } from '@/lib/types'
import { toast } from 'sonner'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div className="space-y-1"><Label className="text-xs">{label}</Label>{children}</div>
}
function NumberField({ label, value, onChange, min, max, step = 1, disabled }: {
  label: string; value: number; onChange: (v: number) => void; min: number; max: number; step?: number; disabled?: boolean
}) {
  return <Field label={label}><Input aria-label={label} className="h-7 mono text-xs" type="number" min={min} max={max} step={step} value={value} disabled={disabled} onChange={e => { const v = e.target.valueAsNumber; if (Number.isFinite(v)) onChange(v) }} /></Field>
}
function Choice({ label, value, onChange, options, disabled }: {
  label: string; value: string; onChange: (v: string) => void; options: Array<[string, string]>; disabled?: boolean
}) {
  return <Field label={label}><Select value={value} onValueChange={onChange} disabled={disabled}><SelectTrigger className="h-7 w-full text-xs" aria-label={label}><SelectValue /></SelectTrigger><SelectContent>{options.map(([v, text]) => <SelectItem value={v} key={v}>{text}</SelectItem>)}</SelectContent></Select></Field>
}
const fmt = (n: number | null | undefined, digits = 4) => n == null ? '—' : n.toFixed(digits)

/** Mounted once in App: navigation changes the lenses, never the study clock,
 * selection, diagram instance or its zoom. Draft settings do not relabel a run. */
export function TemporalWorkbench({ topology, view, visible, onTopologyChange }: { topology: Topology; view: string; visible: boolean; onTopologyChange: (topology: Topology) => void }) {
  const [config, setConfig] = useState<TemporalConfig>(DEFAULT_TEMPORAL_CONFIG)
  const [run, setRun] = useState<TemporalRun | null>(null)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<{ kind: 'bus' | 'line'; id: number }>({ kind: 'bus', id: topology.buses[0]?.id ?? 1 })
  const [estimator, setEstimator] = useState<'wls' | 'ekf'>('ekf')
  const [dockChoice, setDockChoice] = useState({ view: '', dock: 'trend' })
  const dock = dockChoice.view === view ? dockChoice.dock : view === 'baddata' ? 'measurements' : view === 'powerflow' ? 'results' : 'trend'
  const [metric, setMetric] = useState('voltage')
  const [channel, setChannel] = useState(0)
  const [animate, setAnimate] = useState(true)
  const [wide, setWide] = useState(() => window.matchMedia('(min-width: 1024px)').matches)
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const diagramHost = useRef<HTMLDivElement>(null)
  const diagram = useRef<OneLineHandle>(null)
  const [size, setSize] = useState({ width: 600, height: 355 })
  const abort = useRef<AbortController | null>(null)
  const requestVersion = useRef(0)
  const previousTopology = useRef(topology)
  const [runTopology, setRunTopology] = useState<Topology | null>(null)
  const [savedStudies, setSavedStudies] = useState<ScenarioSummary[]>([])
  const [savedId, setSavedId] = useState('')
  const topologyChanged = run !== null && runTopology !== topology
  const draftChanged = run !== null && (Object.keys(config) as Array<keyof TemporalConfig>).some(key => JSON.stringify(config[key]) !== JSON.stringify(run.config[key]))
  const dirty = topologyChanged || draftChanged

  useEffect(() => {
    const media = window.matchMedia('(min-width: 1024px)')
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setWide(media.matches)
    const updateMotion = () => setReducedMotion(motion.matches)
    media.addEventListener('change', update); motion.addEventListener('change', updateMotion)
    return () => { media.removeEventListener('change', update); motion.removeEventListener('change', updateMotion) }
  }, [])
  useEffect(() => {
    const host = diagramHost.current
    if (!host) return
    const observer = new ResizeObserver(entries => {
      const rect = entries[0].contentRect
      if (rect.width > 0 && rect.height > 0) setSize({ width: Math.floor(rect.width), height: Math.floor(rect.height) })
    })
    observer.observe(host)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    if (!visible || busy || topologyChanged) setPlaying(false)
  }, [visible, busy, topologyChanged])
  useEffect(() => {
    if (previousTopology.current !== topology) {
      previousTopology.current = topology
      requestVersion.current++
      abort.current?.abort()
      setBusy(false)
      setError(null)
    }
  }, [topology])
  useEffect(() => () => abort.current?.abort(), [])
  useEffect(() => { listScenarios().then(items => setSavedStudies(items.filter(s => s.temporal))).catch(() => { /* Optional library; Run remains available. */ }) }, [])
  useEffect(() => {
    if (!playing || !run) return
    const timer = window.setInterval(() => setIndex(current => {
      if (current >= run.frames.length - 1) { setPlaying(false); return current }
      return current + 1
    }), 1000 / speed)
    return () => window.clearInterval(timer)
  }, [playing, run, speed])

  const displayedTopology = runTopology ?? topology
  const frame = run?.frames[index]
  const selectedBus = displayedTopology.buses.find(b => selected.kind === 'bus' && b.id === selected.id)
  const selectedLine = displayedTopology.lines.find(l => selected.kind === 'line' && l.id === selected.id)
  const estimate = frame?.[estimator]
  const state = estimate?.states.find(b => b.busId === selected.id)
  const physicalBus = frame?.physical.buses.find(b => b.id === selected.id)
  const physicalLine = frame?.physical.lines.find(l => l.id === selected.id)
  const voltageChannel = run?.channels.find(c => selected.kind === 'bus' && c.busId === selected.id && c.quantity === 'v_bus')
  const selection = useMemo(() => selectOnly(selected.kind, selected.id), [selected])
  const openTies = useMemo(() => displayedTopology.switches?.filter(s => !s.closed) ?? displayedTopology.openSwitches ?? [], [displayedTopology])
  const hours = useMemo(() => run?.frames.map(f => f.hour) ?? [], [run])
  const events = useMemo(() => run?.frames.flatMap((f, i) => f.events.map(e => ({ ...e, index: i, hour: f.hour }))) ?? [], [run])
  const channelInfo = run?.channels[channel]
  const localChannels = run?.channels.filter(c => selected.kind === 'bus' ? c.busId === selected.id : c.lineId === selected.id) ?? []
  const trends = useMemo(() => run?.frames.map(f => {
    const truth = f.physical.buses.find(b => b.id === selected.id)
    const line = f.physical.lines.find(l => l.id === selected.id)
    const wls = f.wls.states.find(b => b.busId === selected.id)
    const ekf = f.ekf.states.find(b => b.busId === selected.id)
    const voltageChannel = run.channels.find(c => c.busId === selected.id && c.quantity === 'v_bus')?.index
    const angleChannel = run.channels.find(c => c.busId === selected.id && c.quantity === 'va_bus')?.index
    const active = f[estimator].states.find(b => b.busId === selected.id)
    const center = metric === 'angle' ? active?.angle : active?.voltage
    const std = metric === 'angle' ? active?.angleStd : active?.voltageStd
    return {
      hour: f.hour,
      truth: metric === 'measurement' ? f.truth[channel] : metric === 'flow' ? line?.pFrom : metric === 'angle' ? truth?.angle : truth?.voltage,
      observed: metric === 'measurement' ? f.observed[channel] : metric === 'angle' ? (angleChannel == null ? null : f.observed[angleChannel]) : metric === 'voltage' ? (voltageChannel == null ? null : f.observed[voltageChannel]) : null,
      wls: !f.wls.converged || metric === 'flow' ? null : metric === 'measurement' ? f.wls.predicted[channel] : metric === 'angle' ? wls?.angle : wls?.voltage,
      ekf: metric === 'flow' ? null : metric === 'measurement' ? f.ekf.predicted[channel] : metric === 'angle' ? ekf?.angle : ekf?.voltage,
      interval: metric !== 'measurement' && metric !== 'flow' && center != null && std != null && (estimator !== 'wls' || f.wls.converged) ? [center - 1.959964 * std, center + 1.959964 * std] : null,
    }
  }) ?? [], [run, selected, metric, channel, estimator])

  function pick(kind: 'bus' | 'line', id: number) {
    setSelected({ kind, id })
    if (kind !== selected.kind || metric === 'measurement') setMetric(kind === 'line' ? 'flow' : 'voltage')
    const match = run?.channels.find(c => kind === 'bus' ? c.busId === id : c.lineId === id)
    if (match) setChannel(match.index)
  }
  function update<K extends keyof TemporalConfig>(key: K, value: TemporalConfig[K]) { setConfig(c => ({ ...c, [key]: value })) }
  async function execute() {
    const version = ++requestVersion.current
    abort.current?.abort()
    const controller = new AbortController(); abort.current = controller
    setBusy(true); setPlaying(false); setError(null)
    try {
      const result = await runTemporal(topology, config, controller.signal)
      if (version !== requestVersion.current) return
      setRun(result); setRunTopology(topology); setIndex(0)
      const nextSelection = (selected.kind === 'bus' ? topology.buses : topology.lines).some(b => b.id === selected.id) ? selected : { kind: 'bus' as const, id: topology.buses[0].id }
      setSelected(nextSelection)
      const firstChannel = result.channels.find(c => nextSelection.kind === 'bus' ? c.busId === nextSelection.id : c.lineId === nextSelection.id)
      setChannel(firstChannel?.index ?? 0)
      if (metric === 'measurement' && !firstChannel) setMetric(nextSelection.kind === 'bus' ? 'voltage' : 'flow')
      toast.success(`${result.frames.length} AC frames calculated`)
    } catch (err) {
      if (version === requestVersion.current && !controller.signal.aborted) setError(err instanceof Error ? err.message : String(err))
    } finally { if (version === requestVersion.current) setBusy(false) }
  }
  function exportRun() {
    if (!run || !runTopology) return
    const url = URL.createObjectURL(new Blob([JSON.stringify({ schemaVersion: 1, topology: runTopology, ...run }, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `temporal-${run.runId}.json`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  async function saveStudy() {
    try {
      await saveScenario({ name: `${topology.name} · Temporal ${config.profile}`, kind: 'workbench', topology,
        settings: { temporal: config }, notes: 'Offline AC QSTS and paired WLS/EKF.' })
      setSavedStudies((await listScenarios()).filter(s => s.temporal))
      toast.success('Study settings saved in the temporal library')
    } catch (err) { toast.error(String(err)) }
  }
  async function loadStudy() {
    try {
      const saved = await loadScenario(savedId)
      if (!saved.settings?.temporal || !Array.isArray(saved.topology?.buses) || !saved.topology.buses.length) throw new Error('Invalid temporal study')
      const next = { ...DEFAULT_TEMPORAL_CONFIG, ...saved.settings.temporal } as TemporalConfig
      if (!['constant', 'daily', 'solar'].includes(next.profile) || [next.duration_hours, next.step_minutes, next.load_scale, next.dg_scale, next.noise_level, next.seed, next.angle_process_std, next.voltage_process_std].some(v => typeof v !== 'number' || !Number.isFinite(v))) throw new Error('Invalid saved temporal settings')
      setPlaying(false); setConfig(next); onTopologyChange(saved.topology)
      toast.success('Study loaded. Run study to calculate its trajectory.')
    } catch (err) { toast.error(String(err)) }
  }

  const unit = metric === 'flow' ? 'MW · base 1 MVA' : metric === 'measurement' ? channelInfo?.unit ?? '' : metric === 'angle' ? 'deg' : 'pu'
  const lensLabel = view === 'baddata' ? 'Innovation & measurement diagnostics' : view === 'estimation' ? 'WLS / EKF comparison' : view === 'powerflow' ? 'Physical AC power flow' : view === 'topology' ? 'Network at the selected instant' : 'Temporal console'
  const settings = <div className="h-full space-y-3 overflow-y-auto p-3">
    <div className="text-xs font-semibold">Study explorer</div>
    <p className="text-xs text-muted-foreground">{topology.name} · {topology.buses.length} buses</p>
    {savedStudies.length > 0 && <div className="space-y-2"><Choice label="Saved temporal study" value={savedId} onChange={setSavedId} options={savedStudies.map(s => [s.id, s.name])} disabled={busy} /><Button size="sm" variant="outline" disabled={!savedId || busy} onClick={loadStudy}>Load study</Button></div>}
    <fieldset className="space-y-3" disabled={busy}>
      <Choice label="Scenario profile" value={config.profile} onChange={v => update('profile', v as TemporalConfig['profile'])} options={[["constant", "Constant operating point"], ["daily", "Daily load cycle"], ["solar", "Daily load + solar DG"]]} />
      <div className="grid grid-cols-2 gap-2">
        <NumberField label="Horizon (h)" value={config.duration_hours} min={1} max={48} onChange={v => update('duration_hours', v)} />
        <Choice label="Step (min)" value={String(config.step_minutes)} onChange={v => update('step_minutes', Number(v))} options={[15, 30, 60, 120, 240].map(v => [String(v), String(v)])} />
        <NumberField label="Load scale" value={config.load_scale} min={0} max={3} step={0.05} onChange={v => update('load_scale', v)} />
        <NumberField label="Existing DG scale" value={config.dg_scale} min={0} max={3} step={0.05} onChange={v => update('dg_scale', v)} />
        <NumberField label="Sensor noise" value={config.noise_level} min={0} max={0.2} step={0.001} onChange={v => update('noise_level', v)} />
        <NumberField label="Random seed" value={config.seed} min={0} max={4294967295} onChange={v => update('seed', v)} />
      </div>
      <details><summary className="cursor-pointer text-xs font-medium">EKF process uncertainty</summary><div className="mt-2 space-y-2">
        <NumberField label="Angle σ (rad / √h)" value={config.angle_process_std} min={0.00001} max={0.2} step={0.001} onChange={v => update('angle_process_std', v)} />
        <NumberField label="Voltage σ (pu / √h)" value={config.voltage_process_std} min={0.00001} max={0.2} step={0.001} onChange={v => update('voltage_process_std', v)} />
        <p className="text-xs text-muted-foreground">Manual Q rates. No calibration from the evaluated trajectory. EKF initializes from measured frame-zero WLS.</p>
      </div></details>
      <details><summary className="cursor-pointer text-xs font-medium">Physical load event</summary><div className="mt-2 space-y-2">
        <label className="flex items-center gap-2 text-xs"><Checkbox aria-label="Enable load event" checked={!!config.load_event} onCheckedChange={v => update('load_event', v ? { bus_id: topology.buses.find(b => b.pLoad || b.qLoad)?.id ?? topology.buses[0].id, start_hour: Math.min(6, config.duration_hours / 2), end_hour: Math.min(8, config.duration_hours), factor: 1.3 } : null)} /> Enable load step</label>
        {config.load_event && <>
          <Choice label="Load-event bus" value={String(config.load_event.bus_id)} onChange={v => update('load_event', { ...config.load_event!, bus_id: Number(v) })} options={topology.buses.filter(b => b.pLoad || b.qLoad).map(b => [String(b.id), `B${b.id} · ${b.name}`])} />
          <NumberField label="Load-event start (h)" value={config.load_event.start_hour} min={0} max={config.duration_hours} step={0.25} onChange={v => update('load_event', { ...config.load_event!, start_hour: v })} />
          <NumberField label="Load-event end (h)" value={config.load_event.end_hour} min={0} max={config.duration_hours} step={0.25} onChange={v => update('load_event', { ...config.load_event!, end_hour: v })} />
          <NumberField label="Local load multiplier" value={config.load_event.factor} min={0} max={3} step={0.1} onChange={v => update('load_event', { ...config.load_event!, factor: v })} />
        </>}
      </div></details>
      <details open={view === 'baddata' || !!config.attack}><summary className="cursor-pointer text-xs font-medium">Scheduled sensor attack</summary><div className="mt-2 space-y-2">
        <label className="flex items-center gap-2 text-xs"><Checkbox aria-label="Enable sensor attack" checked={!!config.attack} onCheckedChange={v => update('attack', v ? { channel, start_hour: Math.min(10, config.duration_hours / 2), end_hour: Math.min(12, config.duration_hours), bias_sigma: 8 } : null)} /> Inject measurement bias</label>
        {config.attack && <>
          {run && !topologyChanged ? <Choice label="Attack channel" value={String(config.attack.channel)} onChange={v => update('attack', { ...config.attack!, channel: Number(v) })} options={run.channels.map(c => [String(c.index), `#${c.index} · ${c.label} · ${c.busId != null ? `B${c.busId}` : `L${c.lineId}`}`])} /> : <NumberField label="Attack channel index" value={config.attack.channel} min={0} max={599} onChange={v => update('attack', { ...config.attack!, channel: v })} />}
          <NumberField label="Attack start (h)" value={config.attack.start_hour} min={0} max={config.duration_hours} step={0.25} onChange={v => update('attack', { ...config.attack!, start_hour: v })} />
          <NumberField label="Attack end (h)" value={config.attack.end_hour} min={0} max={config.duration_hours} step={0.25} onChange={v => update('attack', { ...config.attack!, end_hour: v })} />
          <NumberField label="Bias (σ)" value={config.attack.bias_sigma} min={-100} max={100} onChange={v => update('attack', { ...config.attack!, bias_sigma: v })} />
        </>}
        <p className="text-xs text-muted-foreground">Windows are [start, end). Injection labels are simulation truth; EKF innovation events are separate diagnostics.</p>
      </div></details>
    </fieldset>
    <div className="border-t pt-2 text-xs font-semibold">Equipment</div>
    <div className="max-h-40 space-y-0.5 overflow-y-auto" aria-label="Equipment explorer">{displayedTopology.buses.map(b => <Button className="h-7 w-full justify-start text-xs" key={b.id} variant={selected.kind === 'bus' && selected.id === b.id ? 'secondary' : 'ghost'} onClick={() => pick('bus', b.id)}>B{b.id} · {b.name}</Button>)}{displayedTopology.lines.map(l => <Button className="h-7 w-full justify-start text-xs" key={`l${l.id}`} variant={selected.kind === 'line' && selected.id === l.id ? 'secondary' : 'ghost'} onClick={() => pick('line', l.id)}>L{l.id} · B{l.from} → B{l.to}</Button>)}</div>
  </div>

  return <section className={visible ? 'mx-3 my-3 overflow-hidden rounded-md border bg-background sm:mx-4' : 'hidden'} aria-label="Temporal engineering workspace">
    <div className="flex flex-wrap items-center gap-3 border-b px-3 py-2">
      <div className="mr-auto"><div className="text-sm font-semibold">{lensLabel}</div><div className="text-xs text-muted-foreground">AC time series · WLS / EKF · fixed topology</div></div>
      <Choice label="Inspect estimator" value={estimator} onChange={v => setEstimator(v as 'ekf' | 'wls')} options={[["ekf", "EKF"], ["wls", "AC WLS"]]} />
      <Button size="sm" variant="outline" onClick={saveStudy} disabled={busy}><FloppyDisk /> Save study</Button>
      <Button size="sm" variant="outline" onClick={exportRun} disabled={!run}><Download /> Export run</Button>
      <Button size="sm" onClick={execute} disabled={busy}>{busy ? <CircleNotch className="animate-spin" /> : <Play weight="fill" />}{busy ? 'Calculating…' : 'Run study'}</Button>
    </div>
    {error && <div role="alert" className="border-b bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}
    {dirty && <div role="status" className="border-b bg-status-warn/10 px-3 py-2 text-xs text-status-warn">{topologyChanged ? 'Network or meters changed. Displaying the previous run on its original network.' : 'Settings changed. Displaying the previous computed run.'} Run study to apply changes.</div>}
    {run?.warnings.map(w => <div className="border-b px-3 py-1 text-xs text-status-warn" key={w}>{w}</div>)}
    <ResizablePanelGroup direction={wide ? 'horizontal' : 'vertical'} className="min-w-0" style={{ height: wide ? 680 : 1250 }}>
      <ResizablePanel id="study-explorer" order={1} defaultSize={22} minSize={wide ? 16 : 20}>{settings}</ResizablePanel>
      <ResizableHandle withHandle />
      <ResizablePanel id="study-canvas" order={2} defaultSize={58} minSize={wide ? 35 : 35}>
        <ResizablePanelGroup direction="vertical">
          <ResizablePanel defaultSize={58} minSize={30}>
            <div className="flex h-full flex-col">
              <div className="flex flex-wrap items-center gap-2 border-b px-2 py-1 text-xs"><span className="mr-auto">{displayedTopology.name} · AC · {hourLabel(frame?.hour ?? 0)}</span><label className="flex items-center gap-1.5"><Checkbox checked={animate} onCheckedChange={v => setAnimate(v === true)} aria-label="Animate power flow" /> Flow motion</label><Button size="sm" variant="ghost" onClick={() => diagram.current?.fit()} aria-label="Fit network"><ArrowsOut /> Fit</Button></div>
              <div ref={diagramHost} className="relative min-h-0 flex-1 overflow-hidden">
                <OneLineView ref={diagram} topology={displayedTopology} result={frame?.physical} selection={selection} openTies={openTies} width={size.width} height={size.height} animateFlows={playing && animate && !reducedMotion && visible} showFlowDirection onBusClick={id => pick('bus', id)} onLineClick={id => pick('line', id)} />
                {!run && <div className="pointer-events-none absolute bottom-3 left-3 right-3 rounded border bg-background/95 p-2 text-xs text-muted-foreground">Configure the study and run to calculate AC flows, measurements and WLS/EKF trajectories.</div>}
              </div>
              <div className="border-t px-2 py-1 text-xs text-muted-foreground">Line width ∝ |P| · arrows follow signed P · P/Q base 1 MVA · voltage 0.95–1.05 pu</div>
            </div>
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={42} minSize={25}>
            <div className="h-full overflow-auto p-2">
              <Tabs value={dock} onValueChange={dock => setDockChoice({ view, dock })}><TabsList className="h-8"><TabsTrigger value="trend" className="text-xs">Trend</TabsTrigger><TabsTrigger value="measurements" className="text-xs">Measurements</TabsTrigger><TabsTrigger value="events" className="text-xs">Events ({events.length})</TabsTrigger><TabsTrigger value="results" className="text-xs">Bus results</TabsTrigger></TabsList></Tabs>
              {dock === 'trend' && <>
                <div className="my-2 flex flex-wrap items-end gap-2">
                  <Choice label="Trend quantity" value={metric} onChange={setMetric} options={[...(selected.kind === 'line' ? [["flow", "Active power"]] : [["voltage", "Voltage magnitude"], ["angle", "Voltage angle"]]), ...(localChannels.length ? [["measurement", "Sensor channel"]] : [])] as Array<[string, string]>} />
                  {metric === 'measurement' && <Choice label="Trend channel" value={String(channel)} onChange={v => setChannel(Number(v))} options={localChannels.map(c => [String(c.index), `#${c.index} · ${c.label}`])} disabled={!run} />}
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>{unit}</span>{(metric === 'flow' ? [['Physical AC', 'method-ac']] : [['Truth', 'method-ac'], ['Observed', 'status-warn'], ['WLS', 'method-dc'], ['EKF', 'method-ldf']]).map(([name, token]) => <span key={name} className="flex items-center gap-1"><span className="h-1.5 w-2.5 rounded-sm" style={{ background: `var(--color-${token})` }} />{name}</span>)}{(metric === 'voltage' || metric === 'angle') && <span>95% {estimator.toUpperCase()}</span>}</div>
                </div>
                {run ? <div style={{ height: 160 }}><ResponsiveContainer width="100%" height="100%"><ComposedChart data={trends} margin={{ top: 5, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" />
                  <XAxis dataKey="hour" type="number" domain={['dataMin', 'dataMax']} tickFormatter={hourLabel} tick={{ fontSize: 10 }} />
                  <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10 }} tickFormatter={v => fmt(Number(v), 3)} width={52} />
                  <Tooltip labelFormatter={v => hourLabel(Number(v))} formatter={(v: unknown) => Array.isArray(v) ? v.map(n => fmt(Number(n))).join(' – ') : fmt(Number(v))} contentStyle={{ background: 'var(--color-background)', borderColor: 'var(--color-border)', color: 'var(--color-foreground)', fontSize: 12 }} />
                  {run.config.attack && <ReferenceArea x1={run.config.attack.start_hour} x2={run.config.attack.end_hour} fill="var(--color-destructive)" fillOpacity={0.08} />}
                  <Area name="95% interval" dataKey="interval" stroke="none" fill="var(--color-method-ldf)" fillOpacity={0.15} isAnimationActive={false} />
                  <Line name="Truth" dataKey="truth" stroke="var(--color-method-ac)" dot={false} isAnimationActive={false} />
                  <Line name="Observed" dataKey="observed" stroke="var(--color-status-warn)" strokeWidth={0} dot={{ r: 2, fill: 'var(--color-status-warn)', stroke: 'var(--color-status-warn)' }} isAnimationActive={false} />
                  <Line name="WLS" dataKey="wls" stroke="var(--color-method-dc)" dot={false} isAnimationActive={false} />
                  <Line name="EKF" dataKey="ekf" stroke="var(--color-method-ldf)" dot={false} isAnimationActive={false} />
                  <ReferenceLine x={frame?.hour} stroke="var(--color-selection)" strokeDasharray="4 3" />
                </ComposedChart></ResponsiveContainer></div> : <p className="p-6 text-xs text-muted-foreground">Calculated trajectories will appear here.</p>}
              </>}
              {dock === 'measurements' && <TableCard label="Temporal measurements" maxHeight="16rem"><TableHeader><TableRow>{['Channel', 'Target', 'Quantity', 'Unit', 'True', 'Observed', 'Estimated', 'σ', 'r/σ', 'Injection'].map(h => <TableHead key={h} className="text-xs">{h}</TableHead>)}</TableRow></TableHeader><TableBody>{run?.channels.map(c => <TableRow key={c.index} className={channel === c.index ? 'bg-selection/10' : ''} onClick={() => { setChannel(c.index); if (c.busId != null) setSelected({ kind: 'bus', id: c.busId }); else if (c.lineId != null) setSelected({ kind: 'line', id: c.lineId }); setMetric('measurement') }} style={{ cursor: 'pointer' }}>
                <TableCell><Button size="sm" variant="ghost" className="mono text-xs" aria-label={`Inspect channel ${c.index}`}>#{c.index}</Button></TableCell><TableCell className="mono text-xs">{c.busId != null ? `B${c.busId}` : `L${c.lineId}`}</TableCell><TableCell className="text-xs">{QUANTITY_LABEL[c.quantity] ?? c.quantity}</TableCell><TableCell className="text-xs">{c.unit}</TableCell>{[frame?.truth[c.index], frame?.observed[c.index], estimate?.predicted[c.index], frame?.sigma[c.index], estimate?.residualSigma[c.index]].map((v, i) => <TableCell key={i} className="mono text-right text-xs">{fmt(v)}</TableCell>)}<TableCell className="text-xs">{frame?.attacked[c.index] ? 'Bias injected' : 'None'}</TableCell>
              </TableRow>)}</TableBody></TableCard>}
              {dock === 'events' && <TableCard label="Temporal events" maxHeight="16rem"><TableHeader><TableRow>{['Time', 'Event', 'Target', 'Action'].map(h => <TableHead key={h} className="text-xs">{h}</TableHead>)}</TableRow></TableHeader><TableBody>{events.map((e, i) => <TableRow key={i}><TableCell><Button variant="ghost" size="sm" className="mono text-xs" onClick={() => { setPlaying(false); setIndex(e.index); if (e.channel != null) { setChannel(e.channel); const c = run!.channels[e.channel]; if (c.busId != null) setSelected({ kind: 'bus', id: c.busId }); else if (c.lineId != null) setSelected({ kind: 'line', id: c.lineId }) } }}>{hourLabel(e.hour)}</Button></TableCell><TableCell className="text-xs">{e.type.replace(/_/g, ' ')}</TableCell><TableCell className="mono text-xs">{e.channel != null ? `#${e.channel}` : e.bus != null ? `B${e.bus}` : '—'}</TableCell><TableCell className="text-xs">{e.action.replace(/_/g, ' ')}</TableCell></TableRow>)}</TableBody></TableCard>}
              {dock === 'results' && <TableCard label="Temporal bus results" maxHeight="16rem"><TableHeader><TableRow>{['Bus', 'True |V| (pu)', 'WLS |V| (pu)', 'EKF |V| (pu)', '95% half-width (pu)', 'True θ (deg)'].map(h => <TableHead key={h} className="text-xs">{h}</TableHead>)}</TableRow></TableHeader><TableBody>{frame?.physical.buses.map((b, i) => <TableRow key={b.id} className={selected.kind === 'bus' && selected.id === b.id ? 'bg-selection/10' : ''}><TableCell><Button size="sm" variant="ghost" className="mono text-xs" onClick={() => pick('bus', b.id)}>B{b.id}</Button></TableCell>{[b.voltage, frame.wls.converged ? frame.wls.states[i]?.voltage : null, frame.ekf.states[i]?.voltage, estimate?.states[i]?.voltageStd == null ? null : 1.959964 * estimate.states[i].voltageStd!, b.angle].map((v, n) => <TableCell key={n} className="mono text-right text-xs">{fmt(v)}</TableCell>)}</TableRow>)}</TableBody></TableCard>}
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </ResizablePanel>
      <ResizableHandle withHandle />
      <ResizablePanel id="study-inspector" order={3} defaultSize={20} minSize={wide ? 16 : 16}>
        <div className="h-full space-y-3 overflow-y-auto p-3">
          <div className="text-xs font-semibold">Attribute inspector</div>
          <div className="text-sm font-semibold">{selectedBus ? `B${selectedBus.id} · ${selectedBus.name}` : selectedLine ? `L${selectedLine.id} · B${selectedLine.from} → B${selectedLine.to}` : 'Select equipment'}</div>
          <p className="text-xs text-muted-foreground">{hourLabel(frame?.hour ?? 0)} · {estimator.toUpperCase()}</p>
          <dl className="grid grid-cols-2 gap-x-2 gap-y-2 text-xs">
            {selected.kind === 'bus' ? <>
              <dt>True |V|</dt><dd className="mono text-right">{fmt(physicalBus?.voltage)} pu</dd>
              <dt>Observed |V|</dt><dd className="mono text-right">{fmt(voltageChannel == null ? null : frame?.observed[voltageChannel.index])} pu</dd>
              <dt>Estimated |V|</dt><dd className="mono text-right">{fmt(state?.voltage)} pu</dd>
              <dt>95% ±</dt><dd className="mono text-right">{fmt(state?.voltageStd == null ? null : 1.959964 * state.voltageStd)} pu</dd>
              <dt>True θ</dt><dd className="mono text-right">{fmt(physicalBus?.angle, 3)}°</dd>
              <dt>Estimated θ</dt><dd className="mono text-right">{fmt(state?.angle, 3)}°</dd>
              <dt>P load</dt><dd className="mono text-right">{fmt(physicalBus?.pLoad)} MW</dd>
              <dt>P generation</dt><dd className="mono text-right">{fmt(physicalBus?.pGen)} MW</dd>
            </> : <>
              <dt>P from</dt><dd className="mono text-right">{fmt(physicalLine?.pFrom)} MW</dd>
              <dt>Q from</dt><dd className="mono text-right">{fmt(physicalLine?.qFrom)} MVAr</dd>
              <dt>P to</dt><dd className="mono text-right">{fmt(physicalLine?.pTo)} MW</dd>
              <dt>Loss</dt><dd className="mono text-right">{fmt(physicalLine?.loss)} MW</dd>
            </>}
            <dt>Load factor</dt><dd className="mono text-right">{fmt(frame?.loadFactor, 2)}×</dd>
            <dt>DG factor</dt><dd className="mono text-right">{fmt(frame?.dgFactor, 2)}×</dd>
          </dl>
          <div className="space-y-2 border-t pt-3 text-xs">
            <div className="font-semibold">Estimation diagnostics</div>
            <p>WLS: {frame ? frame.wls.converged ? `converged · ${frame.wls.iterations} iterations` : 'did not converge' : 'not calculated'}</p>
            <p>WLS J: <span className="mono">{fmt(frame?.wls.J, 2)}</span> · χ²: {frame?.wls.chi2Passed == null ? 'unavailable' : frame.wls.chi2Passed ? 'pass' : 'alarm'}</p>
            <p>EKF max |innovation|: <span className="mono">{fmt(frame?.ekf.maxInnovation, 2)}</span>{frame?.ekf.initializedFromWls ? ' · WLS initialization' : ''}</p>
            <p>Measurements / states: <span className="mono">{run ? `${run.channels.length} / ${run.nStates}` : '—'}</span></p>
            <p className="text-muted-foreground">Innovation screening is a heuristic. An alarm does not prove an attack; a quiet residual does not prove safety.</p>
          </div>
          {run && <div className="space-y-2 border-t pt-3 text-xs text-muted-foreground"><p>{run.model}</p><p>Run <span className="mono">{run.runId.slice(0, 8)}</span> · seed {run.config.seed} · {(run.elapsedMs / 1000).toFixed(2)} s calculation</p><p>Profiles are synthetic scenarios. Existing DG only; no switching, EMT, live telemetry or sensor-rate alignment in this mode.</p></div>}
        </div>
      </ResizablePanel>
    </ResizablePanelGroup>
    <TemporalPlayback hours={hours} index={index} playing={playing} speed={speed} onIndex={setIndex} onPlaying={setPlaying} onSpeed={setSpeed} />
  </section>
}
