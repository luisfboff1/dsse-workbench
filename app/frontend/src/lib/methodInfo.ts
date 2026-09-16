/**
 * Registro central dos solvers de power flow — texto, LaTeX e cor de
 * identidade de cada método. Consumido hoje pelo HoverCard de (i) ao lado
 * do seletor de método; a ideia é que a futura aba de Ajuda renderize o
 * mesmo conteúdo em formato de página em vez de popover.
 */

export type PowerFlowMethodId = 'pandapower-ac' | 'pandapower-dc' | 'lindistflow'
export type MethodColorToken = 'method-ac' | 'method-dc' | 'method-ldf'

export interface MethodInfo {
  id: PowerFlowMethodId
  label: string
  shortLabel: string
  color: MethodColorToken
  tagline: string
  summary: string
  /** LaTeX (renderizado com KaTeX), ex. '\\mathbf{x} = [\\boldsymbol{\\theta}, |\\mathbf{V}|]' */
  state: string
  /** cada item é uma equação LaTeX renderizada em modo bloco */
  equations: string[]
  steps: string[]
  /** índice (0-based) em `steps` para onde o último passo volta, se houver iteração */
  loopBackTo?: number
  goodFor: string
  limitations: string
}

export const POWERFLOW_METHODS: MethodInfo[] = [
  {
    id: 'pandapower-ac',
    label: 'AC — Newton-Raphson',
    shortLabel: 'AC · NR',
    color: 'method-ac',
    tagline: 'Full nonlinear power flow — used as the operational ground truth.',
    summary:
      'Solves the exact AC power-flow equations by Newton-Raphson iteration (pandapower). Every other method in this app is compared against this one.',
    state: '\\mathbf{x} = [\\boldsymbol{\\theta},\\ |\\mathbf{V}|]',
    equations: [
      'P_i = |V_i| \\sum_j |V_j| \\left(G_{ij}\\cos\\theta_{ij} + B_{ij}\\sin\\theta_{ij}\\right)',
      'Q_i = |V_i| \\sum_j |V_j| \\left(G_{ij}\\sin\\theta_{ij} - B_{ij}\\cos\\theta_{ij}\\right)',
      '\\mathbf{J}\\,\\Delta\\mathbf{x} = -f(\\mathbf{x})',
    ],
    steps: [
      'Flat start: x⁽⁰⁾ = [θ=0, |V|=1 pu]',
      'Mismatch f(x) = z − h(x)',
      'Jacobian J = ∂h/∂x',
      'Solve JΔx = f(x), update x ← x + Δx',
      'Repeat until ‖Δx‖∞ < tolerance',
    ],
    loopBackTo: 1,
    goodFor: 'Any topology, any X/R ratio — this is the reference solver.',
    limitations:
      'Full-step Newton can fail near voltage collapse or far from the flat start (see case11_iwamoto). Falls back to Iwamoto step-size control automatically.',
  },
  {
    id: 'pandapower-dc',
    label: 'DC — Linear',
    shortLabel: 'DC',
    color: 'method-dc',
    tagline: 'Linearized, lossless approximation — one linear solve, no iteration.',
    summary:
      'Assumes |V| ≡ 1 pu everywhere, small angles (sinθ≈θ), and R→0. Valid when the network is inductive (X ≫ R), which is why it targets transmission.',
    state: '\\mathbf{x} = \\boldsymbol{\\theta}\\quad (|\\mathbf{V}| \\equiv 1\\ \\text{pu})',
    equations: [
      'P_{kl} \\approx \\dfrac{\\theta_k - \\theta_l}{X_{kl}}',
      "\\boldsymbol{\\theta} = B'^{-1}\\,\\mathbf{P}",
    ],
    steps: ["Build B' (susceptance matrix, R ignored)", 'Solve B′θ = P for non-slack buses', 'Done — no iteration'],
    goodFor: 'Transmission networks with X/R ≥ 5, where V is regulated and losses are negligible.',
    limitations:
      'No |V| estimate, no losses, no Q. Systematically biased once X/R drops below ~2 — see the X/R badge on the Topology tab.',
  },
  {
    id: 'lindistflow',
    label: 'DistFlow — Iterative',
    shortLabel: 'LinDist',
    color: 'method-ldf',
    tagline: 'Radial backward-forward sweep with losses — built for distribution (R≈X).',
    summary:
      'Baran & Wu (1989) DistFlow, iterated backward-forward including the (R²+X²)ℓ loss term until |ΔV²| converges. Requires a loop-free (radial) network.',
    state: '\\mathbf{x} = |\\mathbf{V}|\\quad (\\theta\\ \\text{from a 1st-order correction})',
    equations: [
      'V_j^2 = V_i^2 - 2\\left(R\\,P_{ij} + X\\,Q_{ij}\\right) + \\left(R^2+X^2\\right)\\ell_{ij}',
      '\\ell_{ij} = \\dfrac{P_{ij}^2 + Q_{ij}^2}{V_i^2}',
      '\\theta_j = \\theta_i - \\dfrac{X\\,P_{ij} - R\\,Q_{ij}}{V_i}',
    ],
    steps: [
      'Backward sweep: accumulate P, Q leaf → root',
      'Forward sweep: propagate V² root → leaf, with losses',
      'Recompute ℓ from the updated P, Q, V',
      'Repeat until max|ΔV²| < tolerance (usually 3–10 iterations)',
    ],
    loopBackTo: 0,
    goodFor: 'Radial distribution feeders with X/R < 2, where V (not θ) carries most of the state information.',
    limitations: 'Fails on meshed networks — check the radial/meshed badge above the solver before comparing.',
  },
]

export function getMethodInfo(id: string): MethodInfo {
  return POWERFLOW_METHODS.find((m) => m.id === id) ?? POWERFLOW_METHODS[0]
}
