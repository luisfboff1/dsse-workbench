import { useState, useMemo } from 'react'
import { CopySimple } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'

interface MatrixViewerProps {
  data: number[] | number[][]
  rowLabels?: string[]
  colLabels?: string[]
  is1D?: boolean
  originalShape?: number[]
  truncated?: boolean
}

function heatColor(value: number, min: number, max: number): string {
  if (min === max) return 'hsl(220 14% 96%)'
  const t = (value - min) / (max - min)  // 0 = cold (blue), 1 = hot (orange)
  // interpolate: cold = hsl(210 80% 85%), hot = hsl(30 90% 60%)
  const h = 210 - t * 180
  const s = 80 + t * 10
  const l = 85 - t * 25
  return `hsl(${h.toFixed(0)} ${s.toFixed(0)}% ${l.toFixed(0)}%)`
}

export function MatrixViewer({
  data,
  rowLabels,
  colLabels,
  is1D = false,
  originalShape,
  truncated = false,
}: MatrixViewerProps) {
  const [copied, setCopied] = useState(false)

  // Normalize to 2D for uniform rendering
  const matrix: number[][] = is1D
    ? [(data as number[])]
    : (data as number[][])

  const rows = matrix.length
  const cols = matrix[0]?.length ?? 0

  // Compute min/max once — not on every cell render
  const { min, max } = useMemo(() => {
    let min = Infinity, max = -Infinity
    for (const row of matrix) {
      for (const val of row) {
        if (val < min) min = val
        if (val > max) max = val
      }
    }
    return { min, max }
  }, [matrix])

  const handleCopy = () => {
    navigator.clipboard.writeText(JSON.stringify(is1D ? data : matrix))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="space-y-1">
      {truncated && originalShape && (
        <p className="text-xs text-amber-600">
          Showing 20×20 of {originalShape[0]}×{originalShape[1]} — truncated
        </p>
      )}
      <div className="overflow-auto max-h-96 rounded border border-border text-xs">
        <table className="border-collapse min-w-full font-mono">
          {/* Column header */}
          {!is1D && cols > 1 && (
            <thead>
              <tr>
                <th className="sticky top-0 left-0 z-20 bg-muted px-1.5 py-0.5 text-muted-foreground border border-border min-w-6" />
                {Array.from({ length: cols }, (_, j) => (
                  <th
                    key={j}
                    className="sticky top-0 z-10 bg-muted px-1.5 py-0.5 text-center text-muted-foreground border border-border whitespace-nowrap"
                  >
                    {colLabels?.[j] ?? j}
                  </th>
                ))}
              </tr>
            </thead>
          )}
          <tbody>
            {matrix.map((row, i) => (
              <tr key={i}>
                {!is1D && (
                  <td className="sticky left-0 z-10 bg-muted px-1.5 py-0.5 text-muted-foreground border border-border font-semibold text-center whitespace-nowrap">
                    {rowLabels?.[i] ?? i}
                  </td>
                )}
                {row.map((val, j) => (
                  <td
                    key={j}
                    className="px-1.5 py-0.5 border border-border text-right whitespace-nowrap tabular-nums"
                    style={{ backgroundColor: heatColor(val, min, max) }}
                    title={`[${is1D ? j : i},${j}] = ${val}`}
                  >
                    {Math.abs(val) < 1e-10 ? '0' : val.toPrecision(4)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {is1D ? `[${cols}]` : `${rows}×${cols}`}
          {min !== max && (
            <span className="ml-2">
              min {min.toPrecision(3)} · max {max.toPrecision(3)}
            </span>
          )}
        </span>
        <Button variant="ghost" size="sm" className="h-6 px-2 text-xs gap-1" onClick={handleCopy}>
          <CopySimple size={12} />
          {copied ? 'Copied!' : 'Copy JSON'}
        </Button>
      </div>
    </div>
  )
}
