/**
 * Help content panel — renders a selected HelpTopic:
 *   - title + tagline
 *   - description paragraphs
 *   - KaTeX equations (via existing Math.tsx)
 *   - StepFlowchart (via existing StepFlowchart.tsx)
 *   - Glossary cards
 *   - Related function badges
 */
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { BlockMath, InlineMath } from '@/components/Math'
import { StepFlowchart } from '@/components/StepFlowchart'
import { HELP_CATEGORIES } from '@/lib/helpContent'
import type { HelpTopic, HelpCategory, PipelineStage, HelpTable } from '@/lib/helpContent'
import {
  ArrowSquareOut,
  MathOperations,
  ListNumbers,
  BookOpen,
  Code,
  ArrowRight,
} from '@phosphor-icons/react'

interface HelpContentProps {
  categoryId: string | null
  topicId: string | null
}

function findTopic(categoryId: string, topicId: string): { category: HelpCategory; topic: HelpTopic } | null {
  const category = HELP_CATEGORIES.find((c) => c.id === categoryId)
  if (!category) return null
  const topic = category.topics.find((t) => t.id === topicId)
  if (!topic) return null
  return { category, topic }
}

// ─── Table renderer ───────────────────────────────────────────────────────────

function HelpTableSection({ table }: { table: HelpTable }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-max text-left text-sm">
        <thead>
          <tr className="border-b bg-muted/60">
            {table.headers.map((h) => (
              <th key={h} className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, ri) => (
            <tr key={ri} className="border-b last:border-0 hover:bg-muted/30">
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  className={`px-3 py-2 text-xs ${
                    ci === 0 ? 'font-semibold text-foreground' : 'text-muted-foreground'
                  }`}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Pipeline stages renderer ─────────────────────────────────────────────────

const STAGE_COLORS = [
  'border-blue-500/30 bg-blue-500/5',
  'border-amber-500/30 bg-amber-500/5',
  'border-emerald-500/30 bg-emerald-500/5',
] as const

const METHOD_COLORS = [
  'border-l-blue-400',
  'border-l-violet-400',
] as const

function PipelineStagesSection({ stages }: { stages: PipelineStage[] }) {
  return (
    <section className="space-y-4">
      <h2 className="flex items-center gap-2 text-base font-semibold">
        <ListNumbers weight="duotone" className="h-4 w-4 text-primary" />
        Pipeline Stages
      </h2>

      {/* Stage cards flow */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
        {stages.map((stage, si) => (
          <div key={stage.step} className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-start">
            {/* Arrow between stages */}
            {si > 0 && (
              <div className="hidden items-center self-center sm:flex">
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              </div>
            )}

            {/* Stage card */}
            <div className={`flex-1 rounded-xl border p-3 ${STAGE_COLORS[si % STAGE_COLORS.length]}`}>
              {/* Stage header */}
              <div className="mb-2 flex items-center gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-bold text-primary">
                  {stage.step}
                </span>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {stage.label}
                </p>
              </div>
              <p className="mb-2.5 text-xs italic text-muted-foreground">{stage.question}</p>

              {/* Method cards (vertical within stage) */}
              <div className="space-y-2">
                {stage.methods.map((method, mi) => (
                  <div
                    key={method.id}
                    className={`rounded-lg border border-l-4 bg-background/70 p-2.5 ${METHOD_COLORS[mi % METHOD_COLORS.length]}`}
                  >
                    <div className="mb-1 flex items-center gap-1.5">
                      <Badge variant="outline" className="text-[10px] font-mono px-1 py-0">
                        {method.id}
                      </Badge>
                      <span className="text-xs font-medium">{method.name}</span>
                    </div>
                    <p className="text-[11px] leading-snug text-muted-foreground">
                      {method.description}
                    </p>
                    {method.formula && (
                      <div className="mt-1.5 overflow-x-auto text-center text-[11px]">
                        <InlineMath math={method.formula} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Combinations note */}
      <p className="text-xs text-muted-foreground">
        <span className="font-medium">8 combinations:</span>{' '}
        {['D1','D2'].flatMap(d => ['I1','I2'].flatMap(i => ['C1','C2'].map(c => `${d}-${i}-${c}`))).join(', ')}
      </p>
    </section>
  )
}

// ─── Welcome screen ────────────────────────────────────────────────────────────

function WelcomeScreen() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10 text-primary">
        <BookOpen weight="duotone" className="h-8 w-8" />
      </div>
      <div className="max-w-sm space-y-2">
        <h2 className="text-xl font-semibold">DSSE Reference</h2>
        <p className="text-sm text-muted-foreground">
          Select a topic from the sidebar, or use the search bar to find algorithms,
          equations, glossary entries and more.
        </p>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-left sm:grid-cols-3">
        {HELP_CATEGORIES.map((cat) => (
          <div key={cat.id} className="rounded-lg border bg-muted/40 p-3">
            <p className="text-xs font-medium">{cat.label}</p>
            <p className="mt-0.5 text-[10px] text-muted-foreground">
              {cat.topics.length} {cat.topics.length === 1 ? 'topic' : 'topics'}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}

export function HelpContent({ categoryId, topicId }: HelpContentProps) {
  if (!categoryId || !topicId) return <WelcomeScreen />

  const found = findTopic(categoryId, topicId)
  if (!found) return <WelcomeScreen />

  const { category, topic } = found

  return (
    <ScrollArea className="h-full">
      <div className="mx-auto max-w-2xl space-y-8 p-6">
        {/* ── Breadcrumb ── */}
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span>{category.label}</span>
          <ArrowSquareOut className="h-3 w-3 rotate-90 opacity-50" />
          <span className="font-medium text-foreground">{topic.title}</span>
        </div>

        {/* ── Title ── */}
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-start gap-2">
            <h1 className="flex-1 text-2xl font-bold tracking-tight">{topic.title}</h1>
            {topic.paradigm && topic.paradigm !== 'both' && (
              <Badge
                variant="secondary"
                className={`mt-1 shrink-0 text-xs ${
                  topic.paradigm === 'dynamic'
                    ? 'border-amber-400/40 bg-amber-400/10 text-amber-700 dark:text-amber-400'
                    : 'border-blue-400/40 bg-blue-400/10 text-blue-700 dark:text-blue-400'
                }`}
              >
                {topic.paradigm === 'dynamic' ? 'Dynamic' : 'Static (Quasi-static)'}
              </Badge>
            )}
          </div>
          <p className="text-base text-muted-foreground">{topic.tagline}</p>
        </div>

        <Separator />

        {/* ── Description ── */}
        {topic.description && topic.description.length > 0 && (
          <div className="space-y-3">
            {topic.description.map((para, i) => (
              <p key={i} className="text-sm leading-relaxed text-foreground/90">
                {para}
              </p>
            ))}
          </div>
        )}

        {/* ── Reference Table ── */}
        {topic.table && <HelpTableSection table={topic.table} />}

        {/* ── Equations ── */}
        {topic.equations && topic.equations.length > 0 && (
          <section className="space-y-3">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <MathOperations weight="duotone" className="h-4 w-4 text-primary" />
              Equations
            </h2>
            <div className="space-y-3">
              {topic.equations.map((eq, i) => (
                <div key={i} className="rounded-lg border bg-muted/30 p-4">
                  <p className="mb-2 text-xs font-medium text-muted-foreground">{eq.label}</p>
                  <div className="overflow-x-auto">
                    <BlockMath math={eq.latex} />
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ── Algorithm Steps / Flowchart ── */}
        {topic.steps && topic.steps.length > 0 && (
          <section className="space-y-3">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <ListNumbers weight="duotone" className="h-4 w-4 text-primary" />
              Algorithm Steps
            </h2>
            <StepFlowchart
              steps={topic.steps}
              loopBackTo={topic.loopBackTo}
              boxBgClass="bg-primary/5"
              boxBorderClass="border-primary/20"
            />
          </section>
        )}

        {/* ── Pipeline stages (parallel cards) ── */}
        {topic.stages && topic.stages.length > 0 && (
          <PipelineStagesSection stages={topic.stages} />
        )}

        {/* ── Glossary ── */}
        {topic.glossary && topic.glossary.length > 0 && (
          <section className="space-y-3">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <BookOpen weight="duotone" className="h-4 w-4 text-primary" />
              Definitions
            </h2>
            <dl className="space-y-2">
              {topic.glossary.map((entry) => (
                <div key={entry.term} className="rounded-lg border bg-muted/20 p-3">
                  <dt className="text-sm font-semibold">{entry.term}</dt>
                  <dd className="mt-0.5 text-sm text-muted-foreground">{entry.definition}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        {/* ── Related Functions ── */}
        {topic.relatedFunctions && topic.relatedFunctions.length > 0 && (
          <section className="space-y-3">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <Code weight="duotone" className="h-4 w-4 text-primary" />
              Implementation
            </h2>
            <div className="flex flex-wrap gap-2">
              {topic.relatedFunctions.map((fn) => (
                <Badge key={fn} variant="secondary" className="font-mono text-xs">
                  {fn}
                </Badge>
              ))}
            </div>
          </section>
        )}
      </div>
    </ScrollArea>
  )
}
