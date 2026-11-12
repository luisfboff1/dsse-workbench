import { TopologyDiagram } from '@/components/TopologyDiagram'
import { Grupo } from './Primitivos'
import { REDE_5_BARRAS, RESULTADO_ILUSTRATIVO } from '../exemplos'

/** Read-only renders (no callbacks), so no meter popover or switch toggles. */
export function Diagrama() {
  return (
    <div className="space-y-10">
      <Grupo titulo="TopologyDiagram: sem resultado (só topologia)">
        <TopologyDiagram topology={REDE_5_BARRAS} />
      </Grupo>

      <Grupo titulo="TopologyDiagram: com resultado ILUSTRATIVO (não é fluxo de carga resolvido)">
        <p className="mb-2 text-xs text-muted-foreground">
          Tensões e fluxos inventados só para mostrar a convenção: tensão como cor do nó,
          fluxo como espessura da linha. As barras 1 (acima de 1,05 pu) e 5 (abaixo de 0,95 pu) saem fora dos limites de propósito.
        </p>
        <TopologyDiagram
          topology={REDE_5_BARRAS}
          result={RESULTADO_ILUSTRATIVO}
          voltageLimits={{ min: 0.95, max: 1.05 }}
        />
      </Grupo>
    </div>
  )
}
