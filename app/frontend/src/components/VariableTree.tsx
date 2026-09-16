import { useState } from 'react'
import { CaretRight, CaretDown } from '@phosphor-icons/react'
import { Badge } from '@/components/ui/badge'
import { MatrixViewer } from './MatrixViewer'
import type { TraceVariable } from '@/lib/types'

interface VariableRowProps {
  variable: TraceVariable
}

function ScalarRow({ variable }: VariableRowProps) {
  const val = variable.value
  const display =
    typeof val === 'number'
      ? Math.abs(val) < 1e-10
        ? '0'
        : Math.abs(val) > 1e4 || (Math.abs(val) < 1e-3 && val !== 0)
          ? val.toExponential(4)
          : val.toPrecision(6)
      : String(val)

  const badgeVariant =
    val === true ? 'default' : val === false ? 'destructive' : 'secondary'

  return (
    <div className="flex items-start justify-between gap-2 py-1.5 border-b border-border last:border-0">
      <div className="min-w-0">
        <span className="font-mono text-xs font-semibold text-foreground">{variable.name}</span>
        {variable.description && (
          <p className="text-xs text-muted-foreground mt-0.5 leading-snug">{variable.description}</p>
        )}
      </div>
      {typeof val === 'boolean' ? (
        <Badge variant={badgeVariant} className="shrink-0 text-xs">{display}</Badge>
      ) : (
        <span className="font-mono text-xs tabular-nums text-foreground shrink-0">{display}</span>
      )}
    </div>
  )
}

function CollapsibleRow({ variable }: VariableRowProps) {
  const [open, setOpen] = useState(false)
  const is1D = variable.type === 'vector'
  const data = variable.data as number[] | number[][]
  const shape = variable.shape ?? []
  const shapeStr = shape.join('×')

  return (
    <div className="border-b border-border last:border-0">
      <button
        className="w-full flex items-center justify-between gap-2 py-1.5 text-left hover:bg-muted/50 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-1.5 min-w-0">
          {open ? <CaretDown size={12} className="shrink-0 text-muted-foreground" /> : <CaretRight size={12} className="shrink-0 text-muted-foreground" />}
          <span className="font-mono text-xs font-semibold text-foreground">{variable.name}</span>
          {variable.description && (
            <span className="text-xs text-muted-foreground truncate hidden sm:block">{variable.description}</span>
          )}
        </div>
        <Badge variant="outline" className="shrink-0 text-xs font-mono">
          {is1D ? `[${shapeStr}]` : `${shapeStr}`}
          {variable.truncated && ' ⚠'}
        </Badge>
      </button>
      {open && (
        <div className="pb-2 px-1">
          {variable.description && (
            <p className="text-xs text-muted-foreground mb-1.5">{variable.description}</p>
          )}
          <MatrixViewer
            data={data}
            is1D={is1D}
            truncated={variable.truncated}
            originalShape={variable.truncated ? shape : undefined}
          />
        </div>
      )}
    </div>
  )
}

interface VariableTreeProps {
  variables: TraceVariable[]
}

export function VariableTree({ variables }: VariableTreeProps) {
  if (variables.length === 0) {
    return <p className="text-xs text-muted-foreground py-2">No variables captured.</p>
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 divide-y-0">
      {variables.map((v, i) => {
        if (v.type === 'scalar') return <ScalarRow key={i} variable={v} />
        return <div key={i} className="col-span-full"><CollapsibleRow variable={v} /></div>
      })}
    </div>
  )
}
