import { TableCard } from '@/components/TableCard'
import { MatrixViewer } from '@/components/MatrixViewer'
import { StepFlowchart } from '@/components/StepFlowchart'
import { BlockMath, InlineMath } from '@/components/Math'
import { TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Grupo } from './Primitivos'
import { LINHAS_LONGAS, MATRIZ_B, PASSOS_GAUSS_NEWTON, REDE_5_BARRAS, ROTULOS_BARRAS } from '../exemplos'

function Cabecalho() {
  return (
    <TableHeader>
      <TableRow>
        <TableHead className="mono text-xs">Bus</TableHead>
        <TableHead className="mono text-right text-xs">|V| pu</TableHead>
        <TableHead className="mono text-right text-xs">θ (deg)</TableHead>
      </TableRow>
    </TableHeader>
  )
}

export function Componentes() {
  return (
    <div className="space-y-10">
      <Grupo titulo="TableCard: poucas linhas (sem limite de altura, sem botão de expandir)">
        <TableCard label="Buses">
          <TableHeader>
            <TableRow>
              <TableHead className="mono text-xs">Bus</TableHead>
              <TableHead className="mono text-xs">Tipo</TableHead>
              <TableHead className="mono text-right text-xs">P load</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {REDE_5_BARRAS.buses.map(b => (
              <TableRow key={b.id}>
                <TableCell className="mono text-xs">{b.name}</TableCell>
                <TableCell className="mono text-xs">{b.type}</TableCell>
                <TableCell className="mono text-right text-xs">{b.pLoad.toFixed(2)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </TableCard>
      </Grupo>

      <Grupo titulo="TableCard: muitas linhas (maxHeight + expandir)">
        <TableCard label="Bus Results" maxHeight="16rem">
          <Cabecalho />
          <TableBody>
            {LINHAS_LONGAS.map(r => (
              <TableRow key={r.bus}>
                <TableCell className="mono text-xs">{r.bus}</TableCell>
                <TableCell className="mono text-right text-xs">{r.v.toFixed(4)}</TableCell>
                <TableCell className="mono text-right text-xs">{r.theta.toFixed(2)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </TableCard>
      </Grupo>

      <Grupo titulo="TableCard: vazio">
        <TableCard label="Vazio">
          <Cabecalho />
          <TableBody>
            <TableRow>
              <TableCell colSpan={3} className="text-center text-xs text-muted-foreground">Sem dados</TableCell>
            </TableRow>
          </TableBody>
        </TableCard>
      </Grupo>

      <Grupo titulo="MatrixViewer: matriz B do fluxo DC (5 barras, calculada das reatâncias)">
        <MatrixViewer data={MATRIZ_B} rowLabels={ROTULOS_BARRAS} colLabels={ROTULOS_BARRAS} />
      </Grupo>

      <Grupo titulo="MatrixViewer: vetor 1D">
        <MatrixViewer data={[1.06, 1.0, 0.99, 0.965, 0.94]} colLabels={ROTULOS_BARRAS} is1D />
      </Grupo>

      <Grupo titulo="StepFlowchart: com loop-back">
        <StepFlowchart
          steps={PASSOS_GAUSS_NEWTON}
          loopBackTo={1}
          boxBgClass="bg-method-ac/10"
          boxBorderClass="border-method-ac/40"
        />
      </Grupo>

      <Grupo titulo="Math (KaTeX)">
        <div className="space-y-2 text-sm">
          <p>Inline: resíduo <InlineMath math="r = z - h(\hat{x})" /> ponderado por <InlineMath math="W = R^{-1}" />.</p>
          <BlockMath math="\Delta x = \left(H^\top W H\right)^{-1} H^\top W \left[z - h(x)\right]" />
        </div>
      </Grupo>
    </div>
  )
}
