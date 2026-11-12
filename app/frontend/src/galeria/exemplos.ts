/** Fixed sample data for the gallery. Typed with the app's real types, so a
 *  change in a component's interface breaks `npm run typecheck` here instead
 *  of failing silently. The gallery never calls the backend. */
import { DEFAULT_TOPOLOGIES } from '@/lib/topologies'
import type { PowerFlowResult, Topology } from '@/lib/types'

/** Stagg & El-Abiad 5-bus, the same case the app ships with. */
export const REDE_5_BARRAS: Topology = DEFAULT_TOPOLOGIES[0]

/** ILLUSTRATIVE values, not a solved power flow: they only exist to show how
 *  the diagram paints voltage (node colour) and flow (edge width). Buses 1 and 5 sit
 *  outside 0.95-1.05 pu on purpose so the out-of-limits colours appear. */
export const RESULTADO_ILUSTRATIVO: PowerFlowResult = {
  converged: true,
  iterations: 4,
  buses: REDE_5_BARRAS.buses.map((b, i) => {
    const voltage = [1.06, 1.0, 0.99, 0.965, 0.94][i] ?? 1
    return { id: b.id, voltage, angle: -1.5 * i, pGen: b.pGen, qGen: b.qGen, pLoad: b.pLoad, qLoad: b.qLoad }
  }),
  lines: REDE_5_BARRAS.lines.map((l, i) => {
    const pFrom = [0.89, 0.41, 0.25, 0.28, 0.55, 0.19, 0.06][i] ?? 0.1
    return { id: l.id, from: l.from, to: l.to, pFrom, qFrom: 0.1 * pFrom, pTo: -0.97 * pFrom, qTo: -0.1 * pFrom, loss: 0.03 * pFrom }
  }),
  iterationHistory: [],
  executionTime: 0,
}

/** DC power flow B matrix of the 5-bus case (b_ij = -1/x_ij, b_ii = Σ 1/x_ij),
 *  computed from the line data: a real matrix for MatrixViewer. */
export const MATRIZ_B: number[][] = (() => {
  const ids = REDE_5_BARRAS.buses.map(b => b.id)
  const idx = new Map(ids.map((id, i) => [id, i]))
  const B = ids.map(() => ids.map(() => 0))
  for (const l of REDE_5_BARRAS.lines) {
    const i = idx.get(l.from)!, j = idx.get(l.to)!, y = 1 / l.reactance
    B[i][i] += y; B[j][j] += y; B[i][j] -= y; B[j][i] -= y
  }
  return B.map(row => row.map(v => Math.round(v * 100) / 100))
})()

export const ROTULOS_BARRAS = REDE_5_BARRAS.buses.map(b => b.name)

/** Many rows, to exercise TableCard's height cap and expand button. */
export const LINHAS_LONGAS = Array.from({ length: 40 }, (_, i) => ({
  bus: i + 1,
  v: 1.02 - 0.0015 * i,
  theta: -0.35 * i,
}))

export const PASSOS_GAUSS_NEWTON = [
  'Inicializar x⁰ (flat start)',
  'Calcular h(x) e H(x)',
  'G = Hᵀ W H',
  'Resolver G Δx = Hᵀ W [z − h(x)]',
  'x ← x + Δx',
  '‖Δx‖ < ε ?',
]
