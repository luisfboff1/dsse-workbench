/**
 * Flowchart SVG genérico para uma sequência linear de passos, com um loop-back
 * opcional (ex.: "repita até convergir"). Não depende de mermaid — a maioria
 * dos algoritmos deste app é uma cadeia simples de passos, então um SVG leve
 * desenhado à mão evita puxar um runtime de grafo inteiro para isso.
 *
 * Reutilizável fora do contexto de power-flow: qualquer sequência de passos
 * (ex. o pipeline de detecção de bad data) pode usar este mesmo componente.
 */
import { useId } from 'react'

export interface StepFlowchartProps {
  steps: string[]
  /** Índice (0-based) do passo para onde o último passo volta, se houver loop. */
  loopBackTo?: number
  /** Classe de cor de fundo das caixas, ex. 'bg-method-ac/10'. */
  boxBgClass?: string
  /** Classe de cor da borda das caixas, ex. 'border-method-ac/40'. */
  boxBorderClass?: string
}

const BOX_WIDTH = 280
const BOX_HEIGHT = 44
const GAP = 28
const PAD = 8
const LOOP_MARGIN = 46

export function StepFlowchart({
  steps,
  loopBackTo,
  boxBgClass = 'bg-muted',
  boxBorderClass = 'border-border',
}: StepFlowchartProps) {
  const uid = useId().replace(/[:]/g, '')
  const hasLoop = loopBackTo != null && loopBackTo >= 0 && loopBackTo < steps.length

  const boxY = (i: number) => PAD + i * (BOX_HEIGHT + GAP)
  const width = BOX_WIDTH + PAD * 2 + (hasLoop ? LOOP_MARGIN : 0)
  const height = PAD * 2 + steps.length * BOX_HEIGHT + (steps.length - 1) * GAP

  const arrowId = `arrow-${uid}`

  return (
    // maxWidth caps the SVG at its natural (design) pixel size — width="100%" alone
    // would stretch it to fill any wider container, blowing up the box/text ratio.
    // It still shrinks freely below that cap on narrow screens.
    <div style={{ maxWidth: width }} className="mx-auto">
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      <defs>
        <marker
          id={arrowId}
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--color-muted-foreground)" />
        </marker>
      </defs>

      {steps.map((step, i) => (
        <g key={i}>
          <foreignObject x={PAD} y={boxY(i)} width={BOX_WIDTH} height={BOX_HEIGHT}>
            <div
              className={`flex h-full w-full items-center rounded-md border px-3 text-center text-[11px] leading-tight ${boxBgClass} ${boxBorderClass}`}
            >
              <span className="w-full">{step}</span>
            </div>
          </foreignObject>

          {i < steps.length - 1 && (
            <line
              x1={PAD + BOX_WIDTH / 2}
              y1={boxY(i) + BOX_HEIGHT}
              x2={PAD + BOX_WIDTH / 2}
              y2={boxY(i + 1)}
              stroke="var(--color-muted-foreground)"
              strokeWidth={1.5}
              markerEnd={`url(#${arrowId})`}
            />
          )}
        </g>
      ))}

      {hasLoop && (
        <path
          d={[
            `M ${PAD + BOX_WIDTH} ${boxY(steps.length - 1) + BOX_HEIGHT / 2}`,
            `L ${PAD + BOX_WIDTH + LOOP_MARGIN - 8} ${boxY(steps.length - 1) + BOX_HEIGHT / 2}`,
            `L ${PAD + BOX_WIDTH + LOOP_MARGIN - 8} ${boxY(loopBackTo!) + BOX_HEIGHT / 2}`,
            `L ${PAD + BOX_WIDTH} ${boxY(loopBackTo!) + BOX_HEIGHT / 2}`,
          ].join(' ')}
          fill="none"
          stroke="var(--color-muted-foreground)"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          markerEnd={`url(#${arrowId})`}
        />
      )}
    </svg>
    </div>
  )
}
