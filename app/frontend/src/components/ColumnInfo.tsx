/**
 * (i) badge for table column headers — "where did this value come from".
 * Same split as MethodInfo.tsx: ColumnInfoContent is the pure content (reusable
 * in a future Help tab), ColumnInfoBadge wraps it in a HoverCard trigger.
 */
import { Info } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { BlockMath } from '@/components/Math'
import { COLUMN_INFO, type ColumnInfoKey } from '@/lib/columnInfo'

export function ColumnInfoContent({ columnKey }: { columnKey: ColumnInfoKey }) {
  const info = COLUMN_INFO[columnKey]

  return (
    <div className="space-y-2.5">
      <div className="mono text-sm font-bold">{info.label}</div>
      <p className="text-xs leading-relaxed">{info.description}</p>

      {info.equations && info.equations.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] font-semibold text-muted-foreground">
            {info.equations.length > 1 ? 'CASES' : 'FORMULA'}
          </div>
          <div className="space-y-1 rounded-md bg-muted/50 p-2">
            {info.equations.map((eq, i) => (
              <BlockMath key={i} math={eq} />
            ))}
          </div>
        </div>
      )}

      <div className="space-y-1 text-[11px]">
        <div>
          <span className="font-semibold text-muted-foreground">Source — </span>
          <span className="mono">{info.source}</span>
        </div>
        {info.units && (
          <div>
            <span className="font-semibold text-muted-foreground">Units — </span>
            {info.units}
          </div>
        )}
      </div>
    </div>
  )
}

export function ColumnInfoBadge({ columnKey, className }: { columnKey: ColumnInfoKey; className?: string }) {
  return (
    <HoverCard openDelay={150} closeDelay={100}>
      <HoverCardTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className={`size-4 rounded-full text-muted-foreground hover:text-accent ${className ?? ''}`}
          aria-label={`How ${COLUMN_INFO[columnKey].label} is computed`}
        >
          <Info weight="bold" className="size-3" />
        </Button>
      </HoverCardTrigger>
      <HoverCardContent className="w-[min(90vw,26rem)]" side="top" align="start">
        <ColumnInfoContent columnKey={columnKey} />
      </HoverCardContent>
    </HoverCard>
  )
}
