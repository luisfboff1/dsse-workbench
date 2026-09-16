/**
 * Conteúdo de "como o método funciona" para os solvers de power flow.
 * MethodInfoContent é a peça reutilizável — hoje ela roda dentro do
 * HoverCard acionado por MethodInfoBadge, e é o que a futura aba de
 * Ajuda deve renderizar direto numa página, sem popover.
 */
import { Info } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { InlineMath, BlockMath } from '@/components/Math'
import { StepFlowchart } from '@/components/StepFlowchart'
import { getMethodInfo, type MethodColorToken, type PowerFlowMethodId } from '@/lib/methodInfo'

// Classes completas e literais (não interpoladas) para o scanner do Tailwind conseguir encontrá-las.
const COLOR_CLASSES: Record<
  MethodColorToken,
  { text: string; dot: string; border: string; bg: string; hoverText: string }
> = {
  'method-ac': {
    text: 'text-method-ac',
    dot: 'bg-method-ac',
    border: 'border-method-ac/40',
    bg: 'bg-method-ac/10',
    hoverText: 'hover:text-method-ac',
  },
  'method-dc': {
    text: 'text-method-dc',
    dot: 'bg-method-dc',
    border: 'border-method-dc/40',
    bg: 'bg-method-dc/10',
    hoverText: 'hover:text-method-dc',
  },
  'method-ldf': {
    text: 'text-method-ldf',
    dot: 'bg-method-ldf',
    border: 'border-method-ldf/40',
    bg: 'bg-method-ldf/10',
    hoverText: 'hover:text-method-ldf',
  },
}

export function MethodInfoContent({ methodId }: { methodId: PowerFlowMethodId }) {
  const info = getMethodInfo(methodId)
  const c = COLOR_CLASSES[info.color]

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 shrink-0 rounded-full ${c.dot}`} />
        <span className="mono text-sm font-bold">{info.label}</span>
      </div>
      <p className="text-xs text-muted-foreground">{info.tagline}</p>
      <p className="text-xs leading-relaxed">{info.summary}</p>

      <div>
        <div className="mb-1 text-[10px] font-semibold text-muted-foreground">STATE VECTOR</div>
        <div className={`overflow-x-auto rounded-md border px-2 py-1.5 text-sm ${c.border} ${c.bg}`}>
          <InlineMath math={info.state} />
        </div>
      </div>

      <div>
        <div className="mb-1 text-[10px] font-semibold text-muted-foreground">EQUATIONS</div>
        <div className="space-y-1.5 overflow-x-auto rounded-md bg-muted/50 p-2">
          {info.equations.map((eq, i) => (
            <BlockMath key={i} math={eq} />
          ))}
        </div>
      </div>

      <div>
        <div className="mb-1.5 text-[10px] font-semibold text-muted-foreground">ALGORITHM</div>
        <StepFlowchart steps={info.steps} loopBackTo={info.loopBackTo} boxBgClass={c.bg} boxBorderClass={c.border} />
      </div>

      <div className="space-y-1 text-xs">
        <div>
          <span className="font-semibold text-status-good">Good for — </span>
          {info.goodFor}
        </div>
        <div>
          <span className="font-semibold text-destructive">Limitations — </span>
          {info.limitations}
        </div>
      </div>
    </div>
  )
}

export function MethodInfoBadge({ methodId, className }: { methodId: PowerFlowMethodId; className?: string }) {
  const info = getMethodInfo(methodId)
  const c = COLOR_CLASSES[info.color]

  return (
    <HoverCard openDelay={150} closeDelay={100}>
      <HoverCardTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className={`size-6 rounded-full text-muted-foreground ${c.hoverText} ${className ?? ''}`}
          aria-label={`How ${info.label} works`}
        >
          <Info weight="bold" className="size-4" />
        </Button>
      </HoverCardTrigger>
      <HoverCardContent className="w-[min(92vw,32rem)]" side="right" align="start">
        <MethodInfoContent methodId={methodId} />
      </HoverCardContent>
    </HoverCard>
  )
}
