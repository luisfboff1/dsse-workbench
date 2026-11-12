import { Fragment, type ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Crosshair } from '@phosphor-icons/react'
import type { Bus, Line, MeasurementKind, PowerFlowResult, Topology } from '@/lib/types'
import { MEASUREMENT_KINDS, MEASUREMENT_KIND_INFO, buildMeasurementIndex } from '@/lib/measurements'
import { selectOnly, type TopologySelection } from '@/lib/selection'

interface ElementInspectorProps {
  topology: Topology
  selection: TopologySelection
  onSelectionChange: (selection: TopologySelection) => void
  onSetBusMeter: (busId: number, kind: MeasurementKind | 'none') => void
  onSetLineMeter: (lineId: number, kind: MeasurementKind | 'none') => void
  result?: PowerFlowResult | null
}

const TYPE_LABEL: Record<Bus['type'], string> = {
  slack: 'Slack (reference / external grid)',
  pv: 'PV (generator, voltage-controlled)',
  pq: 'PQ (load bus)',
}

/** A value in per unit, plus the physical unit when the network's base MVA is
 *  known (`meta.sn_mva`, set by pandapower imports). */
function pu(value: number | undefined | null, base?: number, unit?: 'MW' | 'MVAr' | 'MVA'): string {
  if (value == null || !Number.isFinite(value)) return '—'
  const p = `${Number(value.toFixed(5))} pu`
  if (base && unit) return `${p} · ${Number((value * base).toFixed(4))} ${unit}`
  return p
}

function num(value: number | undefined | null, digits = 5, unit = ''): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${Number(value.toFixed(digits))}${unit ? ` ${unit}` : ''}`
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</h4>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">{children}</dl>
    </div>
  )
}

function Row({ label, children, title }: { label: string; children: ReactNode; title?: string }) {
  return (
    <Fragment>
      <dt className="text-muted-foreground" title={title}>
        {label}
      </dt>
      <dd className="mono text-right">{children}</dd>
    </Fragment>
  )
}

function MeterPicker({
  current,
  onChange,
}: {
  current?: MeasurementKind
  onChange: (kind: MeasurementKind | 'none') => void
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1">
        {MEASUREMENT_KINDS.map((k) => (
          <Button
            key={k}
            type="button"
            size="sm"
            variant={current === k ? 'default' : 'outline'}
            className="h-6 px-2 text-[11px]"
            title={MEASUREMENT_KIND_INFO[k].description}
            onClick={() => onChange(k)}
          >
            {MEASUREMENT_KIND_INFO[k].shortLabel}
          </Button>
        ))}
        <Button
          type="button"
          size="sm"
          variant={current == null ? 'default' : 'outline'}
          className="h-6 px-2 text-[11px]"
          onClick={() => onChange('none')}
          title="Unobserved: no meter at all"
        >
          None
        </Button>
      </div>
      {current && <p className="text-[11px] text-muted-foreground">{MEASUREMENT_KIND_INFO[current].description}</p>}
    </div>
  )
}

/**
 * "Identify" panel: every stored attribute of the selected bus or line, in
 * per unit (with MW/MVAr/Ω alongside when the base MVA is known), plus the
 * meter assignment. Reads the same shared selection as the diagram, the map
 * and the attribute table — click anywhere, read it here.
 */
export function ElementInspector({
  topology,
  selection,
  onSelectionChange,
  onSetBusMeter,
  onSetLineMeter,
  result,
}: ElementInspectorProps) {
  const base = typeof topology.meta?.sn_mva === 'number' ? (topology.meta.sn_mva as number) : undefined
  const index = buildMeasurementIndex(topology)
  const busById = new Map(topology.buses.map((b) => [b.id, b]))
  const nBus = selection.buses.size
  const nLine = selection.lines.size

  const busLabel = (id: number) => {
    const b = busById.get(id)
    return b ? `${b.name || `Bus ${b.id}`} (#${b.id})` : `#${id}`
  }
  const goBus = (id: number) => onSelectionChange(selectOnly('bus', id))
  const goLine = (id: number) => onSelectionChange(selectOnly('line', id))

  if (nBus + nLine === 0) {
    return (
      <div className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
        <Crosshair className="mx-auto mb-2 h-6 w-6" />
        Click a bus or a line — on the diagram, the map or the table — to see all its data here.
      </div>
    )
  }

  // ── Several elements selected: an aggregate, not a detail view ───────────
  if (nBus + nLine > 1) {
    const buses = [...selection.buses].map((id) => busById.get(id)).filter((b): b is Bus => !!b)
    const sum = (f: (b: Bus) => number) => buses.reduce((acc, b) => acc + (f(b) || 0), 0)
    return (
      <div className="space-y-3 rounded-lg border p-3">
        <h3 className="text-sm font-semibold">
          {nBus} bus{nBus === 1 ? '' : 'es'} · {nLine} line{nLine === 1 ? '' : 's'} selected
        </h3>
        {buses.length > 0 && (
          <Section title="Totals over the selected buses">
            <Row label="P load">{pu(sum((b) => b.pLoad), base, 'MW')}</Row>
            <Row label="Q load">{pu(sum((b) => b.qLoad), base, 'MVAr')}</Row>
            <Row label="P generation">{pu(sum((b) => b.pGen), base, 'MW')}</Row>
            <Row label="P DG">{pu(sum((b) => b.pGenDG ?? 0), base, 'MW')}</Row>
          </Section>
        )}
        <p className="text-[11px] text-muted-foreground">
          Select a single element to see its full data. Use the Table tab to assign meters to the whole selection.
        </p>
      </div>
    )
  }

  // ── One line ─────────────────────────────────────────────────────────────
  if (nLine === 1) {
    const id = [...selection.lines][0]
    const line: Line | undefined = topology.lines.find((l) => l.id === id)
    if (!line) return null
    const fromKv = busById.get(line.from)?.nominal_voltage_kv
    const zBase = base && fromKv ? (fromKv * fromKv) / base : undefined
    const ohm = (v: number) => (zBase ? ` · ${Number((v * zBase).toFixed(4))} Ω` : '')
    const sw = topology.switches?.find(
      (s) => (s.from === line.from && s.to === line.to) || (s.from === line.to && s.to === line.from)
    )
    const solved = result?.lines.find((l) => l.id === id)
    return (
      <div className="space-y-3 rounded-lg border p-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Line {line.id}</h3>
          {sw && <Badge variant={sw.closed ? 'outline' : 'secondary'} className="mono text-[10px]">{sw.closed ? 'closed' : 'open'}</Badge>}
        </div>
        <Section title="Connection">
          <Row label="From">
            <button type="button" className="underline decoration-dotted hover:text-primary" onClick={() => goBus(line.from)}>
              {busLabel(line.from)}
            </button>
          </Row>
          <Row label="To">
            <button type="button" className="underline decoration-dotted hover:text-primary" onClick={() => goBus(line.to)}>
              {busLabel(line.to)}
            </button>
          </Row>
          {fromKv != null && <Row label="Nominal voltage">{num(fromKv, 4, 'kV')}</Row>}
        </Section>
        <Section title="Series impedance / shunt (per unit)">
          <Row label="R">{`${num(line.resistance)} pu${ohm(line.resistance)}`}</Row>
          <Row label="X">{`${num(line.reactance)} pu${ohm(line.reactance)}`}</Row>
          <Row label="B (shunt)" title="Total line charging susceptance">{num(line.susceptance)} pu</Row>
          <Row label="X/R">{line.resistance > 0 ? num(line.reactance / line.resistance, 3) : '—'}</Row>
          {line.tapRatio != null && line.tapRatio !== 1 && <Row label="Tap ratio">{num(line.tapRatio, 4)}</Row>}
        </Section>
        {solved && (
          <Section title="Power-flow result">
            <Row label="P from">{pu(solved.pFrom, base, 'MW')}</Row>
            <Row label="Q from">{pu(solved.qFrom, base, 'MVAr')}</Row>
            <Row label="P to">{pu(solved.pTo, base, 'MW')}</Row>
            <Row label="Q to">{pu(solved.qTo, base, 'MVAr')}</Row>
            <Row label="Loss">{pu(solved.loss, base, 'MW')}</Row>
          </Section>
        )}
        <Section title="Branch-flow meter">
          <div className="col-span-2">
            <MeterPicker current={index.lineKind.get(line.id)} onChange={(k) => onSetLineMeter(line.id, k)} />
          </div>
        </Section>
      </div>
    )
  }

  // ── One bus ──────────────────────────────────────────────────────────────
  const id = [...selection.buses][0]
  const bus = busById.get(id)
  if (!bus) return null
  const incident = topology.lines.filter((l) => l.from === bus.id || l.to === bus.id)
  const solved = result?.buses.find((b) => b.id === bus.id)
  const netP = (bus.pGen || 0) + (bus.pGenDG || 0) - (bus.pLoad || 0)
  const controlsVoltage = bus.type === 'slack' || bus.type === 'pv'
  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">{bus.name || `Bus ${bus.id}`}</h3>
          <p className="text-[11px] text-muted-foreground">Bus #{bus.id}</p>
        </div>
        <Badge variant={bus.type === 'slack' ? 'default' : 'outline'} className="mono text-[10px]">
          {bus.type.toUpperCase()}
        </Badge>
      </div>
      <Section title="Type & voltage">
        <Row label="Role">{TYPE_LABEL[bus.type]}</Row>
        {bus.nominal_voltage_kv != null && <Row label="Nominal voltage">{num(bus.nominal_voltage_kv, 4, 'kV')}</Row>}
        <Row label={controlsVoltage ? 'V setpoint' : 'V (initial guess)'} title={controlsVoltage ? 'Voltage magnitude this bus holds' : 'PQ buses do not hold voltage: this is only the solver starting point'}>
          {num(bus.voltage, 4, 'pu')}
        </Row>
        <Row label={bus.type === 'slack' ? 'Angle (reference)' : 'Angle (initial)'}>{num(bus.angle, 3, '°')}</Row>
      </Section>
      <Section title="Injections (per unit)">
        <Row label="P load">{pu(bus.pLoad, base, 'MW')}</Row>
        <Row label="Q load">{pu(bus.qLoad, base, 'MVAr')}</Row>
        {!!bus.qShunt && <Row label="Q shunt" title="Bus shunt at V = 1 pu (negative = capacitor bank)">{pu(bus.qShunt, base, 'MVAr')}</Row>}
        <Row label="P generation">{pu(bus.pGen, base, 'MW')}</Row>
        {(bus.qMin != null || bus.qMax != null) && (
          <Row label="Q limits">{`${num(bus.qMin, 3)} … ${num(bus.qMax, 3)} pu`}</Row>
        )}
        <Row label="P DG (sgen)" title="Distributed generation: fixed PQ, does not hold voltage">{pu(bus.pGenDG ?? 0, base, 'MW')}</Row>
        <Row label="Q DG (sgen)">{pu(bus.qGenDG ?? 0, base, 'MVAr')}</Row>
        <Row label="Net P (gen + DG − load)">{pu(netP, base, 'MW')}</Row>
      </Section>
      {solved && (
        <Section title="Power-flow result">
          <Row label="V">{num(solved.voltage, 4, 'pu')}</Row>
          <Row label="Angle">{num(solved.angle, 3, '°')}</Row>
          <Row label="P gen">{pu(solved.pGen, base, 'MW')}</Row>
          <Row label="Q gen">{pu(solved.qGen, base, 'MVAr')}</Row>
        </Section>
      )}
      <Section title={`Connected lines (${incident.length})`}>
        <div className="col-span-2 flex flex-wrap gap-1">
          {incident.map((l) => {
            const other = l.from === bus.id ? l.to : l.from
            return (
              <Button
                key={l.id}
                type="button"
                size="sm"
                variant="outline"
                className="h-6 px-2 text-[11px]"
                title={`Line ${l.id} to ${busLabel(other)}`}
                onClick={() => goLine(l.id)}
              >
                L{l.id} → {other}
              </Button>
            )
          })}
          {incident.length === 0 && <span className="text-muted-foreground">none</span>}
        </div>
      </Section>
      {bus.geoX != null && bus.geoY != null && (
        <Section title="Position">
          <Row label="X / lon">{num(bus.geoX, 6)}</Row>
          <Row label="Y / lat">{num(bus.geoY, 6)}</Row>
        </Section>
      )}
      <Section title="Meter">
        <div className="col-span-2">
          <MeterPicker current={index.busKind.get(bus.id)} onChange={(k) => onSetBusMeter(bus.id, k)} />
        </div>
      </Section>
    </div>
  )
}
