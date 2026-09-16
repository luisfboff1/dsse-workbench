import { useState, useEffect } from 'react'
import {
  Gear,
  ArrowsClockwise,
  CheckCircle,
  Flag,
  Warning,
  X,
} from '@phosphor-icons/react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { VariableTree } from './VariableTree'
import type { ExecutionTrace, TraceStep, TraceCategory } from '@/lib/types'

// ─── Category meta ────────────────────────────────────────────────────────────

const CATEGORY_ICON: Record<TraceCategory, React.ElementType> = {
  setup: Gear,
  iteration: ArrowsClockwise,
  result: CheckCircle,
  convergence: Flag,
}

const CATEGORY_COLOR: Record<TraceCategory, string> = {
  setup: 'text-blue-500',
  iteration: 'text-violet-500',
  result: 'text-emerald-600',
  convergence: 'text-amber-500',
}

// ─── Convergence sparkline ────────────────────────────────────────────────────

function ConvergenceChart({ steps }: { steps: TraceStep[] }) {
  const data = steps
    .filter(s => s.category === 'iteration')
    .map(s => {
      const J = s.variables.find(v => v.name === 'J_k')
      return { k: s.name.replace('GN Iteration ', ''), J: J?.value as number ?? 0 }
    })

  if (data.length < 2) return null

  return (
    <div>
      <p className="text-xs text-muted-foreground mb-1">J(x_k) convergence</p>
      <ResponsiveContainer width="100%" height={72}>
        <LineChart data={data} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
          <XAxis dataKey="k" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 10 }} width={44} />
          <Tooltip
            contentStyle={{ fontSize: 10, padding: '2px 8px' }}
            formatter={(v: number) => [v.toPrecision(4), 'J']}
          />
          <Line type="monotone" dataKey="J" dot={false} stroke="hsl(262 80% 60%)" strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─── Step list item ───────────────────────────────────────────────────────────

function StepItem({
  step,
  selected,
  onClick,
}: {
  step: TraceStep
  selected: boolean
  onClick: () => void
}) {
  const Icon = CATEGORY_ICON[step.category] ?? CheckCircle
  const color = CATEGORY_COLOR[step.category] ?? 'text-muted-foreground'

  return (
    <button
      className={`w-full text-left flex items-start gap-2 px-3 py-2.5 rounded-lg transition-colors ${
        selected
          ? 'bg-primary text-primary-foreground'
          : 'hover:bg-muted text-foreground'
      }`}
      onClick={onClick}
    >
      <Icon
        size={14}
        className={selected ? 'text-primary-foreground/80 mt-0.5 shrink-0' : `${color} mt-0.5 shrink-0`}
        weight="bold"
      />
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium leading-snug">{step.name}</p>
        {step.log && (
          <p className={`text-xs mt-0.5 leading-tight line-clamp-2 ${selected ? 'text-primary-foreground/60' : 'text-muted-foreground'}`}>
            {step.log}
          </p>
        )}
      </div>
    </button>
  )
}

// ─── Main panel ───────────────────────────────────────────────────────────────

interface ExecutionPanelProps {
  trace: ExecutionTrace | null
  open: boolean
  onClose: () => void
}

export function ExecutionPanel({ trace, open, onClose }: ExecutionPanelProps) {
  const [selectedIdx, setSelectedIdx] = useState(0)

  // Reset to first step whenever a new trace arrives
  useEffect(() => { setSelectedIdx(0) }, [trace])

  // Escape key closes the panel
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open || !trace) return null

  const selectedStep = trace.steps[Math.min(selectedIdx, trace.steps.length - 1)]
  const algoLabel = trace.algorithm === 'dc-wls' ? 'DC-WLS' : 'AC GN-WLS'
  const StepIcon = CATEGORY_ICON[selectedStep.category] ?? CheckCircle
  const stepColor = CATEGORY_COLOR[selectedStep.category] ?? 'text-muted-foreground'

  return (
    <>
      {/* Dimmed overlay — click to dismiss */}
      <div
        className="fixed inset-0 z-40 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Bottom drawer — custom, no shadcn Sheet */}
      <div
        className="fixed bottom-0 left-0 right-0 z-50 flex flex-col bg-background border-t border-border rounded-t-2xl shadow-2xl animate-in slide-in-from-bottom duration-250"
        style={{ height: '66vh', willChange: 'transform' }}
        role="dialog"
        aria-modal="true"
        aria-label="Execution Trace"
        onClick={e => e.stopPropagation()}
      >
        {/* Visual drag handle */}
        <div className="flex justify-center pt-2.5 pb-0.5 shrink-0">
          <div className="h-1 w-10 rounded-full bg-muted-foreground/30" />
        </div>

        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-5 py-2.5 border-b border-border shrink-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-sm font-bold">{algoLabel}</span>
            <Badge variant="outline" className="font-mono text-xs">
              {trace.total_ms.toFixed(1)} ms
            </Badge>
            {trace.converged ? (
              <Badge className="text-xs bg-emerald-600 hover:bg-emerald-600">
                <CheckCircle size={10} className="mr-1" weight="fill" />
                converged
              </Badge>
            ) : (
              <Badge variant="destructive" className="text-xs">
                <Warning size={10} className="mr-1" weight="fill" />
                not converged
              </Badge>
            )}
          </div>
          <button
            onClick={onClose}
            className="ml-4 rounded-md p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        {/* ── Body — two columns ──────────────────────────────────────────── */}
        {/*
          CRITICAL: both children need min-h-0 so flex doesn't expand them
          beyond the parent. Scroll is on plain overflow-y-auto divs, not
          ScrollArea, which requires explicit heights to work in flex.
        */}
        <div className="flex flex-1 min-h-0">

          {/* Left sidebar: step list */}
          <aside className="w-56 shrink-0 border-r border-border flex flex-col min-h-0">
            <p className="px-3 pt-3 pb-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-widest shrink-0">
              Steps · {trace.steps.length}
            </p>
            <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-3 space-y-0.5">
              {trace.steps.map((step, i) => (
                <StepItem
                  key={i}
                  step={step}
                  selected={selectedIdx === i}
                  onClick={() => setSelectedIdx(i)}
                />
              ))}
            </div>
          </aside>

          {/* Right: variables for selected step */}
          <div className="flex-1 min-w-0 flex flex-col min-h-0">
            {/* Step sub-header */}
            <div className="px-5 py-2.5 border-b border-border shrink-0 flex items-start gap-2.5">
              <StepIcon size={15} className={`${stepColor} mt-0.5 shrink-0`} weight="bold" />
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-semibold">{selectedStep.name}</span>
                  <Badge variant="secondary" className="text-xs capitalize">
                    {selectedStep.category}
                  </Badge>
                </div>
                {selectedStep.log && (
                  <p className="text-xs text-muted-foreground mt-0.5">{selectedStep.log}</p>
                )}
              </div>
            </div>

            {/* Scrollable variables area */}
            <div className="flex-1 min-h-0 overflow-y-auto">
              <div className="px-5 py-4 space-y-4 max-w-6xl">
                {selectedStep.category === 'iteration' && (
                  <>
                    <ConvergenceChart steps={trace.steps} />
                    <Separator />
                  </>
                )}
                <VariableTree variables={selectedStep.variables} />
              </div>
            </div>
          </div>

        </div>
      </div>
    </>
  )
}
