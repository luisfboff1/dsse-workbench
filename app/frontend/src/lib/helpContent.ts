/**
 * Help reference centre — all topics, equations, flowcharts and glossary
 * entries shown in the Help tab and the global search palette.
 *
 * Content is kept in TypeScript (no runtime file fetch needed).
 * LaTeX strings are rendered by the existing Math.tsx / KaTeX wrapper.
 */

// ─── Types ───────────────────────────────────────────────────────────────────

export interface GlossaryEntry {
  term: string
  definition: string
}

export interface HelpTable {
  headers: string[]
  rows: string[][]
}

export interface PipelineMethod {
  /** Short code like D1, I2, C1. */
  id: string
  name: string
  description: string
  /** LaTeX formula string rendered inline. */
  formula?: string
}

export interface PipelineStage {
  step: number
  label: string
  /** The yes/no question this stage answers. */
  question: string
  methods: PipelineMethod[]
}

/** Estimation paradigm — determines which filter tab shows this topic. */
export type Paradigm = 'static' | 'dynamic' | 'both'

export interface HelpTopic {
  /** Unique slug used as the navigation key. */
  id: string
  title: string
  /** One-sentence teaser shown in search results. */
  tagline: string
  /**
   * Estimation paradigm: 'static' (quasi-static WLS), 'dynamic' (Kalman/EKF),
   * or 'both' (sensors, glossary, data-gen — applies to either paradigm).
   * Defaults to 'both' when omitted.
   */
  paradigm?: Paradigm
  /** Full description paragraphs (plain text). */
  description: string[]
  /** LaTeX strings for block-mode equations (KaTeX). */
  equations?: { label: string; latex: string }[]
  /** Step-by-step algorithm, rendered by StepFlowchart. */
  steps?: string[]
  /** Index (0-based) for the loop-back arrow in StepFlowchart. */
  loopBackTo?: number
  /** Parallel pipeline stages rendered as side-by-side cards. */
  stages?: PipelineStage[]
  /** Source Python functions / modules that implement this topic. */
  relatedFunctions?: string[]
  /** Glossary entries defined in this topic's scope. */
  glossary?: GlossaryEntry[]
  /** Optional reference table (headers + rows), rendered before the glossary. */
  table?: HelpTable
}

export interface HelpCategory {
  id: string
  label: string
  /** Phosphor icon name (string) — resolved in UI via a lookup table. */
  icon: string
  /** Optional subtitle shown below the category label in the Help tab. */
  description?: string
  topics: HelpTopic[]
}

// ─── Categories & Topics ─────────────────────────────────────────────────────

export const HELP_CATEGORIES: HelpCategory[] = [
  // ── 1. Algorithms ──────────────────────────────────────────────────────────
  {
    id: 'algorithms',
    label: 'Algorithms',
    icon: 'Function',
    topics: [
      {
        id: 'wls-gauss-newton',
        title: 'WLS — Gauss-Newton State Estimator',
        tagline: 'Iterative weighted least-squares solver for AC state estimation.',
        paradigm: 'static',
        description: [
          'The Weighted Least Squares (WLS) estimator finds the state vector x̂ that minimises the weighted residual norm J(x) = [z − h(x)]ᵀ W [z − h(x)], where z is the measurement vector, h(x) the nonlinear measurement function, and W = R⁻¹ the inverse measurement covariance matrix.',
          'The Gauss-Newton method linearises h(x) at each iteration around the current estimate, solving the so-called normal equations for the correction Δx. Convergence is typically reached in 3–6 iterations for well-conditioned networks.',
          'The implementation in this app lives in gauss_newton_wls.py and is used by both the power-flow ground-truth solver and the state estimator itself.',
        ],
        equations: [
          { label: 'Objective function', latex: 'J(\\mathbf{x}) = [\\mathbf{z} - h(\\mathbf{x})]^\\top \\mathbf{W}\\,[\\mathbf{z} - h(\\mathbf{x})]' },
          { label: 'Normal (Gauss-Newton) equations', latex: '\\mathbf{G}(\\mathbf{x})\\,\\Delta\\mathbf{x} = \\mathbf{H}(\\mathbf{x})^\\top \\mathbf{W}\\,[\\mathbf{z} - h(\\mathbf{x})]' },
          { label: 'Gain matrix', latex: '\\mathbf{G}(\\mathbf{x}) = \\mathbf{H}(\\mathbf{x})^\\top\\,\\mathbf{W}\\,\\mathbf{H}(\\mathbf{x})' },
          { label: 'State update', latex: '\\mathbf{x}^{(k+1)} = \\mathbf{x}^{(k)} + \\Delta\\mathbf{x}^{(k)}' },
        ],
        steps: [
          'Flat start: x⁽⁰⁾ = [θ = 0, |V| = 1 pu]',
          'Compute measurement residuals r = z − h(x)',
          'Evaluate Jacobian H = ∂h/∂x',
          'Form gain matrix G = HᵀWH',
          'Solve GΔx = HᵀWr, update x ← x + Δx',
          'Repeat until ‖Δx‖∞ < ε (typically 1e-4)',
        ],
        loopBackTo: 1,
        relatedFunctions: [
          'gauss_newton_wls.solve_wls_gauss_newton()',
          'gauss_newton_wls.WLSResult',
          'gauss_newton_wls.WLSIteration',
        ],
      },
      {
        id: 'dc-linear',
        title: 'DC Linear Estimator',
        tagline: 'One-shot linear estimator for transmission networks (high X/R).',
        paradigm: 'static',
        description: [
          'The DC estimator replaces the full AC power-flow equations with a linear approximation: |V| ≡ 1 pu, angles are small (sin θ ≈ θ), and resistances are neglected (R → 0). These assumptions are valid in high-voltage transmission where X/R ≫ 1.',
          'Under these assumptions the power-angle equations become linear, collapsing the iterative Gauss-Newton loop into a single linear solve: θ̂ = (HᵀWH)⁻¹HᵀWz. No iteration is needed.',
          'A loss-correction variant (dc_linear.solve_dc_with_loss_correction) adds an iterative correction term to partially recover the resistive losses that the pure DC model ignores.',
        ],
        equations: [
          { label: 'DC branch flow', latex: 'P_{ij} \\approx \\dfrac{\\theta_i - \\theta_j}{X_{ij}}' },
          { label: 'Linear measurement model', latex: '\\mathbf{z} = \\mathbf{H}\\,\\boldsymbol{\\theta} + \\boldsymbol{\\varepsilon}' },
          { label: 'DC WLS solution', latex: '\\hat{\\boldsymbol{\\theta}} = (\\mathbf{H}^\\top\\mathbf{W}\\mathbf{H})^{-1}\\mathbf{H}^\\top\\mathbf{W}\\mathbf{z}' },
        ],
        steps: [
          "Build susceptance-based H from network B' matrix",
          'One linear solve: θ̂ = (HᵀWH)⁻¹HᵀWz',
          'Done — no iteration required',
        ],
        relatedFunctions: [
          'dc_linear.solve_dc_pure()',
          'dc_linear.solve_dc_with_loss_correction()',
          'dc_linear.chi2_limit()',
        ],
      },
      {
        id: 'ac-ybus',
        title: 'AC Ybus Measurement Layer',
        tagline: 'Maps full-nonlinear AC state to branch/bus measurements via the admittance matrix.',
        paradigm: 'static',
        description: [
          'The AC Ybus layer computes the full set of AC measurements — bus voltage magnitudes, active/reactive bus injections, and active/reactive branch flows — directly from the complex admittance matrix Y_bus and the complex voltage vector V = |V|∠θ.',
          'This is the h(x) function used by the Gauss-Newton WLS solver when running in AC mode. Two versions exist: v0 computes element-by-element, while v1 uses vectorised Ybus operations for speed.',
          'The Jacobian H = ∂h/∂x is computed analytically from the partial derivatives of the AC power equations with respect to bus angles θ and magnitudes |V|.',
        ],
        equations: [
          { label: 'Complex current injection', latex: '\\mathbf{I} = \\mathbf{Y}_{\\text{bus}}\\,\\mathbf{V}' },
          { label: 'Complex power injection', latex: 'S_i = V_i I_i^* = V_i \\sum_j Y_{ij}^* V_j^*' },
          { label: 'Active injection (P)', latex: 'P_i = |V_i|\\sum_j |V_j|\\left(G_{ij}\\cos\\theta_{ij} + B_{ij}\\sin\\theta_{ij}\\right)' },
          { label: 'Reactive injection (Q)', latex: 'Q_i = |V_i|\\sum_j |V_j|\\left(G_{ij}\\sin\\theta_{ij} - B_{ij}\\cos\\theta_{ij}\\right)' },
        ],
        relatedFunctions: [
          'ac_measurements.ACYbusMeasurementModel',
          'ac_measurements.ACPowerMeasurementModel',
        ],
      },
      {
        id: 'dynamic-kf-ekf',
        title: 'Dynamic State Estimation — KF / EKF',
        tagline: 'Recursive prediction and correction with causal process-noise calibration.',
        paradigm: 'dynamic',
        description: [
          'The dynamic estimator propagates the previous state and covariance before assimilating the next measurement snapshot. The linear KF uses a fixed H matrix; the EKF evaluates the nonlinear AC measurement function h(x) and its Jacobian at the predicted state.',
          'Process noise Q must be calibrated from a historical period that ends before the evaluated trajectory. Calibrating Q from x_true in the test period leaks ground truth and invalidates causal validation.',
          'The optional Chapter 8 adaptation monitors normalized innovations. A strongly skewed innovation vector is treated as a gross-measurement-error candidate; otherwise the method reports a state change and can restart from a static WLS solution. Thresholds must be calibrated for the measurement count and sensor mix.',
        ],
        equations: [
          { label: 'State prediction', latex: '\\hat{\\mathbf{x}}_{k|k-1}=\\mathbf{F}\\hat{\\mathbf{x}}_{k-1|k-1}' },
          { label: 'Covariance prediction', latex: '\\mathbf{P}_{k|k-1}=\\mathbf{F}\\mathbf{P}_{k-1|k-1}\\mathbf{F}^\\top+\\mathbf{Q}' },
          { label: 'Normalized innovation', latex: '\\lambda_i=\\dfrac{z_i-h_i(\\hat{\\mathbf{x}}_{k|k-1})}{\\sqrt{S_{ii}}}' },
          { label: 'Kalman correction', latex: '\\hat{\\mathbf{x}}_{k|k}=\\hat{\\mathbf{x}}_{k|k-1}+\\mathbf{K}_k\\boldsymbol{\\nu}_k' },
        ],
        steps: [
          'Calibrate Q from a separate historical trajectory',
          'Predict state and covariance with F and Q',
          'Compute h(x), H(x), innovation and innovation covariance S',
          'Optionally classify anomaly as gross error or state change',
          'Correct the state and update covariance in Joseph form',
        ],
        relatedFunctions: [
          'sistemas_dinamicos.calibrate_process_noise()',
          'sistemas_dinamicos.run_linear_kalman_filter()',
          'sistemas_dinamicos.run_extended_kalman_filter()',
          'sistemas_dinamicos.InnovationAdaptation',
        ],
      },
      {
        id: 'lindistflow',
        title: 'LinDistFlow — Iterative DistFlow',
        tagline: 'Radial backward-forward sweep with losses for distribution networks.',
        paradigm: 'static',
        description: [
          'The DistFlow method (Baran & Wu, 1989) is designed for radial (tree-shaped) distribution feeders where resistance and reactance have similar magnitudes (X/R ≈ 1). It propagates power flows backward from leaves to root, then computes voltages forward from root to leaves.',
          'Unlike the DC estimator, LinDistFlow retains the (R² + X²)ℓ loss term in the voltage update, making it accurate even when losses are significant. Convergence requires 3–10 iterations for typical distribution feeders.',
          'The method fails on meshed networks — always verify the radial/meshed badge in the Topology tab before selecting this solver.',
        ],
        equations: [
          { label: 'Voltage squared update', latex: 'V_j^2 = V_i^2 - 2\\left(R\\,P_{ij} + X\\,Q_{ij}\\right) + \\left(R^2 + X^2\\right)\\ell_{ij}' },
          { label: 'Branch current squared', latex: '\\ell_{ij} = \\dfrac{P_{ij}^2 + Q_{ij}^2}{V_i^2}' },
          { label: 'Angle correction', latex: '\\theta_j = \\theta_i - \\dfrac{X\\,P_{ij} - R\\,Q_{ij}}{V_i}' },
        ],
        steps: [
          'Backward sweep: sum P, Q from leaves toward root',
          'Forward sweep: propagate V² from root to leaves (with loss term)',
          'Recompute ℓ from updated P, Q, V',
          'Repeat until max|ΔV²| < ε (typically 3–10 iterations)',
        ],
        loopBackTo: 0,
        relatedFunctions: ['PowerFlowTab — LinDistFlow solver (pandapower backend)'],
      },
    ],
  },

  // ── 2. Key Equations ───────────────────────────────────────────────────────
  {
    id: 'equations',
    label: 'Key Equations',
    icon: 'Equation',
    topics: [
      {
        id: 'hat-matrix',
        title: 'Hat Matrix & Residual Covariance',
        tagline: 'Relates estimated residuals to the true measurement errors.',
        paradigm: 'static',
        description: [
          'The hat matrix (or influence matrix) K = I − H(HᵀWH)⁻¹HᵀW maps the true measurement errors e to the post-estimation residuals r̂ = Kε. Its diagonal entries kᵢᵢ ∈ [0,1] measure how much each measurement "influences" its own fitted value.',
          'The residual covariance matrix Ω = KR = K/W provides the denominator for all normalised residual tests. Measurements with kᵢᵢ ≈ 1 are critical (undetectable) — any single error in them cannot be identified by residual analysis.',
        ],
        equations: [
          { label: 'Sensitivity (hat) matrix', latex: '\\mathbf{K} = \\mathbf{I} - \\mathbf{H}(\\mathbf{H}^\\top\\mathbf{W}\\mathbf{H})^{-1}\\mathbf{H}^\\top\\mathbf{W}' },
          { label: 'Residual covariance', latex: '\\boldsymbol{\\Omega} = \\mathbf{K}\\,\\mathbf{R}' },
          { label: 'Normalised residual', latex: 'r_i^N = \\dfrac{|\\hat{r}_i|}{\\sqrt{\\Omega_{ii}}}' },
        ],
        relatedFunctions: ['bad_data.identify_lnr()', 'bad_data.detect_chi2()'],
      },
      {
        id: 'chi2-test',
        title: 'Chi-Square Global Bad Data Test',
        tagline: 'Detects the presence of bad data anywhere in the measurement set.',
        paradigm: 'both',
        description: [
          'The chi-square (χ²) test checks whether the overall weighted residual norm J(x̂) is consistent with a χ² distribution. The degrees of freedom is m − n, not m — because the WLS estimator consumes exactly n degrees of freedom fitting the state vector, leaving only m − n free residual dimensions.',
          'A threshold χ²(α, m−n) is computed for a chosen false-alarm probability α (typically 0.05 or 0.01). If J(x̂) > χ²threshold, the test flags the presence of bad data. This is a global test — it detects that bad data exists but does not identify which measurement is corrupted.',
          'Important distinction — CME_N global detection: The Bretas CME_N-based detection statistic operates in the full m-dimensional error space, before the WLS projection absorbs n degrees of freedom. Its threshold is therefore based on χ²(m) — not χ²(m − n). This makes CME_N sensitive to errors at leverage points that the classical chi-square test misses entirely.',
        ],
        equations: [
          { label: 'Test statistic', latex: 'J(\\hat{\\mathbf{x}}) = [\\mathbf{z} - h(\\hat{\\mathbf{x}})]^\\top\\mathbf{W}[\\mathbf{z} - h(\\hat{\\mathbf{x}})]' },
          { label: 'Degrees of freedom', latex: 'k = m - n \\quad (m = \\text{measurements},\\ n = \\text{state variables})' },
          { label: 'Null hypothesis', latex: 'H_0:\\; J(\\hat{\\mathbf{x}}) \\sim \\chi^2(m - n)' },
          { label: 'Detection condition', latex: 'J(\\hat{\\mathbf{x}}) > \\chi^2_{\\alpha,\\, m-n} \\implies \\text{bad data detected}' },
        ],
        relatedFunctions: ['bad_data.detect_chi2()', 'dc_linear.chi2_limit()'],
      },
      {
        id: 'lnr',
        title: 'Largest Normalised Residual (LNR)',
        tagline: 'Identifies the single most likely bad measurement after detection.',
        paradigm: 'static',
        description: [
          'Once the chi-square test flags bad data, the Largest Normalised Residual (LNR) method identifies which measurement is most likely corrupted. Each residual rᵢ is normalised by the square root of its residual covariance Ωᵢᵢ, and the measurement with the largest |rᵢᴺ| is declared bad.',
          'After removing or correcting the flagged measurement, the estimation is repeated and the chi-square test is applied again. This sequential process is called Identify-&-Remove (or Hypothesis Testing Identification, HTI). Its weakness is that it can be fooled by leverage points (measurements with kᵢᵢ ≈ 1) — see the CME/CNE methods for a more robust alternative.',
        ],
        equations: [
          { label: 'LNR score', latex: 'r_i^N = \\dfrac{|\\hat{r}_i|}{\\sqrt{\\Omega_{ii}}}' },
          { label: 'Identification', latex: 'i^* = \\arg\\max_i\\; r_i^N' },
          { label: 'LNR threshold (typical)', latex: 'r_i^N > 3.0 \\implies \\text{measurement } i \\text{ is bad}' },
        ],
        relatedFunctions: ['bad_data.identify_lnr()'],
      },
      {
        id: 'cme-cne',
        title: 'CME / CNE — Bretas Geometric Method',
        tagline: 'Leverage-point-robust bad data detection, identification and correction.',
        paradigm: 'static',
        description: [
          'The Composed Measurement Error (CME) and Composed Normalised Error (CNE) methods (Bretas 2013, 2018) address the fundamental weakness of LNR: leverage points. A leverage point is a measurement whose hat-matrix diagonal entry kᵢᵢ ≈ 1, meaning its residual is always near zero regardless of how large the actual error is — LNR cannot detect it.',
          'Geometric view: the sensitivity (hat) matrix K = I − H G⁻¹ HᵀW is an orthogonal projector — it satisfies K² = K and Kᵀ = K (in the W-weighted inner product). It projects the full error vector ε ∈ ℝᵐ onto the residual subspace, which is the orthogonal complement of the column space of WH. For a leverage point, the column of WH corresponding to that measurement is nearly in span(WH without that column), so almost all of εᵢ falls in the undetectable subspace and the residual r̂ᵢ = Kᵢᵢεᵢ ≈ 0.',
          'Residual decomposition (Bretas 2013): for any measurement i, the post-estimation residual r̂ᵢ is a linear combination of all errors: r̂ᵢ = kᵢᵢεᵢ + Σⱼ≠ᵢ kᵢⱼεⱼ. Dividing by kᵢᵢ gives the CME: an estimate of εᵢ that is non-zero even when kᵢᵢ → 1, because the sum Σⱼ≠ᵢ kᵢⱼεⱼ/kᵢᵢ remains finite.',
          'CNE (Bretas 2018) normalises CME by σᵢ to produce a dimensionless score. A high CNE score identifies the bad measurement; the CNE value itself provides the correction magnitude, allowing in-place correction instead of removal. This is critical for networks with low redundancy where removal would cause unobservability.',
          'Detection threshold: the CME_N global statistic uses χ²(m) (not χ²(m−n)) because it operates before the WLS projection. This is what gives it sensitivity to leverage-point errors that the standard chi-square test misses.',
          'Calibration caveat — heterogeneous measurement plans: the χ²(m) threshold assumes the m terms CME_N,ᵢ² have comparable variance. That holds when the meter classes have similar precision, but a plan that mixes pseudo-measurements (σ multiplier 10) with PMUs (0.1) makes the undetectability index heterogeneous and the nominal threshold wrong. Measured on 36 configurations (3 networks × 4 meter classes × 3 noise levels, no attack at all): the nominal CME_N test raised a false alarm in up to 100% of runs, while the classical residual test stayed at 0–7% on the same data.',
          'Fix — effective degrees of freedom (Satterthwaite): instead of assuming unit variance, compute cᵢ = Var(CME_N,ᵢ | H₀) = (1 − kᵢᵢ)(1 + uᵢ²) from H and W, which are known without any attack, and approximate the sum as J ~ g·χ²(h) with h = (Σcᵢ)²/Σcᵢ² and g = Σcᵢ²/Σcᵢ. This brings the false alarm back to 0–7%. It is a strict generalisation: when the plan is homogeneous, h = m and the threshold is identical to the nominal one.',
          'Practical guidance: use the residual test as the primary detector — it is the only one that matches the nominal α across the whole range (4–6% measured with 200 seeds). Use CME_N when you need its ability to recover masked errors that the residual cannot see, and in that case always select the Satterthwaite variant. Note that Satterthwaite runs slightly hot on well-conditioned plans (8–12% instead of 5%), because a two-moment approximation underestimates the upper tail.',
        ],
        equations: [
          { label: 'Residual decomposition per measurement', latex: '\\hat{r}_i = k_{ii}\\,\\varepsilon_i + \\sum_{j \\neq i} k_{ij}\\,\\varepsilon_j' },
          { label: 'Composed Measurement Error (CME)', latex: '\\text{CME}_i = \\dfrac{\\hat{r}_i}{k_{ii}} \\approx \\varepsilon_i \\quad \\text{(robust to leverage points)}' },
          { label: 'Undetectability index', latex: 'u_i = 1 - k_{ii} \\quad\\Rightarrow\\quad k_{ii} \\to 1 \\text{ (leverage point)}: u_i \\to 0' },
          { label: 'Composed Normalised Error (CNE)', latex: '\\text{CNE}_i = \\dfrac{\\text{CME}_i}{\\sigma_i}' },
          { label: 'Correction via CNE', latex: 'z_i^{\\text{corr}} = z_i - \\text{CNE}_{i^*} \\cdot \\sigma_{i^*}' },
          { label: 'K is an orthogonal projector (W-inner product)', latex: '\\mathbf{K}^2 = \\mathbf{K}, \\quad \\mathbf{K}^\\top\\mathbf{W} = \\mathbf{W}\\mathbf{K}' },
          { label: 'CME_N detection threshold', latex: '\\operatorname{CME}_N \\text{ global statistic} \\sim \\chi^2(m) \\quad (\\text{not } \\chi^2(m-n))' },
          { label: 'Variance of each CME_N term under H₀', latex: 'c_i = \\operatorname{Var}(\\operatorname{CME}_{N,i} \\mid H_0) = (1 - k_{ii})\\,(1 + u_i^2)' },
          { label: 'Effective degrees of freedom (Satterthwaite)', latex: 'h = \\dfrac{\\left(\\sum_i c_i\\right)^2}{\\sum_i c_i^2}, \\qquad g = \\dfrac{\\sum_i c_i^2}{\\sum_i c_i}' },
          { label: 'Corrected detection condition', latex: 'J_{\\text{CME}} > g \\cdot \\chi^2_{\\alpha,\\,h} \\implies \\text{bad data detected}' },
        ],
        relatedFunctions: [
          'bad_data.detect_chi2_cme()',
          'bad_data.detect_chi2_cme_satterthwaite()',
          'bad_data.identify_cme()',
          'bad_data.composed_normalized_error()',
        ],
        glossary: [
          { term: 'Leverage point', definition: 'Measurement with kᵢᵢ ≈ 1. Its residual is always near zero regardless of actual error — invisible to LNR.' },
          { term: 'Undetectability index uᵢ', definition: 'uᵢ = 1 − kᵢᵢ. When uᵢ → 0, measurement i is a leverage point and undetectable by LNR.' },
          { term: 'Orthogonal projector', definition: 'Matrix satisfying P² = P (idempotent) and Pᵀ = P (symmetric in the W-norm). K projects ε onto the residual subspace.' },
          { term: 'Residual subspace', definition: 'The subspace of ℝᵐ orthogonal to col(WH). Errors in this subspace produce non-zero residuals and are detectable. Errors in col(WH) produce zero residuals and are undetectable.' },
        ],
      },
    ],
  },

  // ── 3. Bad Data ────────────────────────────────────────────────────────────
  {
    id: 'bad-data',
    label: 'Bad Data',
    icon: 'Bug',
    topics: [
      {
        id: 'bad-data-pipeline',
        title: 'Bad Data Pipeline — 8 Combinations',
        tagline: 'Full detect → identify → correct pipeline with 8 method combinations.',
        paradigm: 'static',
        description: [
          'The pipeline chains three independent stages, each with two method choices, giving 2 × 2 × 2 = 8 combinations. All 8 are run in parallel on the same dataset so you can compare them side-by-side in the Bad Data tab.',
          'The 8 combinations are: D1-I1-C1, D1-I1-C2, D1-I2-C1, D1-I2-C2, D2-I1-C1, D2-I1-C2, D2-I2-C1, D2-I2-C2 — where D = detection, I = identification, C = correction.',
          'After the correction step the WLS is re-run and detection is applied again. If bad data is still flagged, the pipeline iterates (typically 1–2 iterations suffice). The final result includes the updated state estimate, residuals, and which measurements were flagged.',
        ],
        steps: [
          'Run initial WLS → get x̂, residuals r̂',
          'D1: J(x̂) > χ²(α, m−n)? or D2: max CME_N > τ?',
          'If neither flags bad data → stop (clean measurement set)',
          'I1: flag i* = argmax LNR, or I2: flag i* = argmax CME',
          'C1: remove zᵢ* and re-run WLS, or C2: correct zᵢ* via CNE',
          'Repeat from step 1 with updated z (iterate until clean)',
        ],
        loopBackTo: 0,
        stages: [
          {
            step: 1,
            label: 'Detection',
            question: 'Is there bad data?',
            methods: [
              {
                id: 'D1',
                name: 'Chi-square (D1)',
                description: 'Global weighted residual test. Threshold χ²(α, m−n). Blind to leverage-point errors.',
                formula: 'J(\\hat{\\mathbf{x}}) > \\chi^2_{\\alpha,\\,m-n}',
              },
              {
                id: 'D2',
                name: 'CME_N (D2)',
                description: 'Bretas composed normalised error. Threshold based on χ²(m). Detects leverage-point errors.',
                formula: '\\max_i\\;|\\mathrm{CME}_i / k_{ii}| > \\tau',
              },
            ],
          },
          {
            step: 2,
            label: 'Identification',
            question: 'Which measurement is bad?',
            methods: [
              {
                id: 'I1',
                name: 'LNR (I1)',
                description: 'Largest Normalised Residual. Fast, but fails silently on leverage points (kᵢᵢ ≈ 1).',
                formula: 'i^* = \\arg\\max_i\\;|\\hat{r}_i|/\\sqrt{\\Omega_{ii}}',
              },
              {
                id: 'I2',
                name: 'CME (I2)',
                description: 'Composed Measurement Error. Divides by kᵢᵢ to recover the true error — robust to leverage points.',
                formula: 'i^* = \\arg\\max_i\\;|\\hat{r}_i / k_{ii}|',
              },
            ],
          },
          {
            step: 3,
            label: 'Correction',
            question: 'How to handle zᵢ*?',
            methods: [
              {
                id: 'C1',
                name: 'Removal (C1)',
                description: 'Remove zᵢ* from the measurement set and re-run WLS. Simple, but reduces redundancy by 1.',
              },
              {
                id: 'C2',
                name: 'CNE Correction (C2)',
                description: 'Subtract the CNE-estimated error from zᵢ*. Preserves redundancy — preferred when m/n is already low.',
                formula: 'z_{i^*}^{\\text{corr}} = z_{i^*} - \\mathrm{CNE}_{i^*}\\cdot\\sigma_{i^*}',
              },
            ],
          },
        ],
        relatedFunctions: [
          'bad_data.run_bad_data_pipeline()',
          'bad_data.detect_chi2()',
          'bad_data.detect_chi2_cme()',
          'bad_data.identify_lnr()',
          'bad_data.identify_cme()',
          'bad_data.composed_normalized_error()',
        ],
      },
      {
        id: 'parameter-error-bad-data',
        title: 'Parameter-Error Attacks (Line r/x/c)',
        tagline: 'When the wrong thing is the model H, not the measurement z — Bretas et al. 2017.',
        paradigm: 'static',
        description: [
          'Every bad-data case so far corrupts a measurement: z is wrong, H stays correct. A parameter attack is the opposite — the measurements are clean, but the estimator\'s own model of a line (r, x, and/or the shunt c used to build H/h(x) from Ybus) is wrong, e.g. because someone tampered with the parameter database on the server (an "inside threat", as opposed to a measurement attack, which typically means tampering with SCADA/PMU packets in transit).',
          'The Attack target selector (Bad Data tab, method=AC) lets you inject a measurement error (classic), a line-parameter error, or both at once — Arturo Bretas specifically asked for the "both" case, since several measurements shifted at once can look a lot like a single parameter error.',
          'A parameter error on line i-j spreads across every equation that references that parameter: the P/Q flow on both sides of that specific line, plus the P/Q injections at its two terminal buses — 8 measurements total, called that line\'s "own" set. A genuine measurement error, in contrast, produces one isolated spike. Counting how many of a line\'s own measurements cross the CME_N threshold (fraction flagged) is therefore a direct, cheap identification test — it is exactly the criterion described on p. 213 of the article, and the "By line" identification method in the app implements it.',
          'A second, subtler effect (not in the article, found while validating this in the 5-bus AC notebook): the two endpoints of the attacked line do not propagate the error symmetrically to their other neighbours. The endpoint with higher hat-matrix leverage (kᵢᵢ) masks part of its own error into the re-estimated state, and that masked part leaks into the OTHER lines sharing that bus; the low-leverage endpoint keeps almost all of the error local to its own injection measurement instead. This only shows up after the WLS re-estimates the state — a one-shot linearization at a fixed operating point cannot reproduce it.',
          'The AC pipeline here is fully nonlinear Gauss-Newton, rebuilt from scratch every iteration (unlike the DC pipeline, which keeps H fixed) — necessary because removing/correcting a measurement, or correcting a line parameter, changes the operating point the next iteration linearizes around.',
          'The own-measurements signature (p. 213) is drawn directly as a heatmap in "Structural Incidence Matrix" — a binary measurement×line matrix, purely structural (no attack needed to compute it): row i, column j is 1 iff measurement i belongs to line j\'s own set. The aggregated "Line Signature Ranking" table right below it is this same matrix collapsed to a single fraction-flagged number per line, after an attack.',
          'For parameter attacks, a "Correction Strategy Comparison" panel reports RMSE(angle)/RMSE(|V|) against the true state for four fixed reference scenarios (baseline, no correction, best measurement correction, parameter correction via eq. 16) — this is the app version of the parameter-error notebook\'s final synthesis, and its headline finding: a lower RMSE does not mean a more correct fix. x_true only exists here because this is a demo/validation comparison; it is never used to decide which correction to apply.',
          'When correction="by_parameter" actually fires, a dedicated "Parameter Correction" panel walks through it explicitly: J/χ² before vs. after, the eq. 16 formula with the actual CNE plugged in, a true/wrong/corrected table for r, x and c, and a small bar chart per parameter — so the "one action fixes r, x and c together, no data discarded" story is visible, not just implied by a lower J.',
        ],
        equations: [
          { label: "Line's own measurements (identification signature, p. 213)", latex: '\\text{own}(i\\!-\\!j) = \\{P_{ij}, Q_{ij}, P_{ji}, Q_{ji}, P_i, Q_i, P_j, Q_j\\}' },
          { label: 'Parameter correction (eq. 16)', latex: 'p_i^{C} = p_i^{E}\\left(1 + \\dfrac{\\operatorname{CNE}_i}{100}\\right)' },
          { label: 'Measurement correction (eq. 17)', latex: 'z_i^{C} = z_i^{E} - \\operatorname{CNE}_i\\,\\sigma_i' },
          { label: 'Injected parameter error (this app\'s reading of "k·σ" for a parameter)', latex: 'p^{\\text{wrong}} = p^{\\text{real}}\\,(1 + n_\\sigma \\cdot \\sigma_{\\text{param}})' },
          { label: 'Innovation Index (Bretas et al. 2013/2018)', latex: 'II_i = \\dfrac{1}{\\sqrt{UI_i}} = \\sqrt{\\dfrac{1-k_{ii}}{k_{ii}}}, \\qquad UI_i = \\dfrac{k_{ii}}{1-k_{ii}} = \\dfrac{1}{II_i^{2}}' },
        ],
        stages: [
          {
            step: 1,
            label: 'Attack target',
            question: 'What is actually wrong?',
            methods: [
              { id: 'measurement', name: 'Measurement (z)', description: 'One z shifted by k×σ — classic gross error, all pipelines above apply.' },
              { id: 'parameter', name: 'Line parameter (H)', description: "r/x/c of one line wrong in the estimator's model; measurements stay clean. AC only." },
              { id: 'both', name: 'Both at once', description: "Arturo's ambiguity check — several shifted measurements can mimic a parameter error." },
            ],
          },
          {
            step: 2,
            label: 'Identification',
            question: 'Isolated measurement, or a whole line?',
            methods: [
              { id: 'lnr-cme', name: 'LNR / CME (per-measurement)', description: 'Same as the classic pipeline — best for a genuine isolated measurement attack.' },
              { id: 'by-line', name: 'By line (AC only)', description: "Ranks every line by the fraction of its own 8 measurements above the CME_N threshold — p. 213 of Bretas et al. 2017." },
            ],
          },
          {
            step: 3,
            label: 'Correction',
            question: 'Fix the reading, or fix the model?',
            methods: [
              { id: 'remove-ztrue', name: 'Remove / z_true (CNE)', description: 'Patches the measurement set — works even for a parameter error, but discards real data and never fixes the underlying wrong parameter.' },
              { id: 'by-parameter', name: 'By parameter (eq. 16)', description: "Corrects r/x/c directly, using the CNE of the line's highest-CME_N own measurement. Requires identification='by_line'. Fixes the root cause with a single action, no data discarded." },
            ],
          },
        ],
        table: {
          headers: ['Signature', 'Measurement attack', 'Parameter attack'],
          rows: [
            ['CME_N pattern', '1 isolated spike', '3-8 measurements above threshold, concentrated in one line\'s own set'],
            ['Best identification', 'LNR or CME (per-measurement)', 'By line (fraction of own measurements flagged)'],
            ['Root-cause fix', 'Remove / z_true', 'By parameter (eq. 16) — the only one that corrects the actual r/x/c'],
            ['Cost of "wrong" fix', 'n/a', 'Remove/z_true still lowers χ² below threshold, but discards real measurements and leaves the parameter database wrong for every future snapshot'],
          ],
        },
        glossary: [
          { term: 'σ_param (assumed)', definition: "Relative uncertainty assumed for a line parameter, used to express the attack magnitude as k·σ_param — the article only defines k·σ for measurement error (eq. 18-19); there is no standard value for a parameter, so this is an explicit, adjustable assumption in the app (default 1%)." },
          { term: 'Leverage asymmetry', definition: "The two endpoints of an attacked line don't leak the error to their other neighbours equally — the higher-kᵢᵢ endpoint masks (and redistributes) more of its own error via the re-estimated state; the lower-kᵢᵢ endpoint keeps most of the error local to itself. Only visible after re-estimation, not in a one-shot linearization." },
          { term: "Line's own measurements", definition: "The 8 measurements whose h(x) formula directly references a given line's r/x/c: P/Q flow on both sides of that line, plus P/Q injection at its two terminal buses. Purely structural — computable before running any estimation." },
          { term: 'Matched-filter sensitivity (research only)', definition: 'A precomputed measurement×line sensitivity matrix (∂h/∂parameter, evaluated at a reference operating point) can identify the attacked line by correlating its shape with the observed residual — validated in the notebook, but not exposed in the app: it needs a well-chosen non-degenerate reference point (flat start does not work) and gives only a marginal gain over the simple "by line" fraction-flagged method.' },
          { term: 'Add measurement noise (toggle)', definition: "On (default): z = z_true + N(0,σ) — matches Bretas et al. 2017's own stated practice (noise added in every one of their simulations) and general SE validation practice. Off: z = z_true exactly, σ still used as the WLS weight/χ² unit — a controlled ablation that isolates the injected parameter/measurement error from noise variance, and reproduces the parameter-error notebook (which uses no-noise deliberately, for that reason) numerically." },
          { term: 'Innovation Index (II)', definition: "II_i = 1/√UI_i — the 'new information' a measurement carries about its own error (Bretas et al. 2013/2018). II → 0 as a measurement becomes fully masked (kᵢᵢ → 1, a leverage/critical point); II grows unbounded as kᵢᵢ → 0 (fully observable). Shown alongside K_ii/UI in every measurement table — pure frontend derivation, the backend already returns UI." },
          { term: 'RMSE vs. ground truth (demo only)', definition: "The four-row comparison in 'Correction Strategy Comparison' uses x_true (the network's actual power flow solution) only to REPORT how close each correction strategy got — never to decide which one to apply. In production x_true is never available; the detection/identification/correction pipeline never touches it." },
        ],
        relatedFunctions: [
          'ac_bad_data.run_ac_bad_data_pipeline()',
          'ac_bad_data.inject_parameter_error()',
          'ac_bad_data.correct_parameter_eq16()',
          'ac_bad_data.identify_by_line()',
          'ac_bad_data.line_signature_score()',
          'ac_bad_data.rmse_against_truth()',
        ],
      },
      {
        id: 'attack-signature-classifier',
        title: 'Attack-Signature Classification (measurement × parameter × topology)',
        tagline: 'Deciding WHICH of the three things is wrong — the fixed threshold, where it fails, and the learned replacement.',
        paradigm: 'static',
        description: [
          'Three different things can be wrong, and each needs a different fix: the measurement z (remove or correct via CNE), the model H (correct r/x/c via eq. 16), or the switch status (topology — correction not implemented yet). Choosing the wrong one is worse than doing nothing: correcting a measurement when the real fault is a parameter leaves the parameter database wrong for every future snapshot, and the pipeline can drive J below the χ² threshold while never fixing the actual cause.',
          'The classical rule (classify_attack_signature) decides with ONE fixed threshold on ONE scalar: line_fraction_threshold = 0.5 applied to the fraction of the winning line\'s own measurements above |CME_N| > 3. If that fraction is below the threshold the verdict is "measurement" (an isolated spike); if it is above and the line has flow measurements in the set, "parameter"; if it is above but the line has NO flow measurements, "topology" (the flows vanished because the estimator does not know the line exists).',
          'A ground-truth sweep over the four factors — attacked line, error magnitude, noise level and number of attacked measurements — measures where that rule breaks. On the IEEE 5-bus (6150 scenarios) the overall type accuracy is ≈0.51. The failure is not evenly spread: false alarm on clean data is low (≈3%, close to the nominal α = 0.05), but the "parameter" class is recovered only ≈27% of the time and "topology" ≈24%, with most topology cases mislabelled as "parameter".',
          'Two distinct causes. (1) DETECTION, not classification: a parameter error of only a few percent on a lightly loaded line does not push the χ² test over the threshold at all, so the pipeline never reaches the classifier. (2) SIGNATURE COLLISION: an attacker who shifts several measurements at once produces the same spread-out pattern as a single parameter error. That collision is monotone in the number of attacked measurements — with 1 attacked measurement ≈16% are mislabelled "parameter", with 4 it reaches ≈69% when the attacker picks measurements from one line\'s own set, versus ≈42% for measurements picked at random.',
          'The natural objection is that 0.5 is simply the wrong number. It is not: because the rule is a deterministic function of three recorded quantities, the whole threshold sweep can be replayed offline. The best possible τ over [0,1] lifts accuracy only from 0.51 to ≈0.62 — the ceiling of ANY scalar cut on that statistic. The problem is the shape of the decision, not its calibration.',
          'The replacement keeps the same physics and changes only the decision layer: 54 dimensionless features extracted from the same one-iteration WLS solve, fed to a gradient-boosting classifier. Three levels are compared on purpose — the fixed threshold, a linear model on the same features (how much comes from using more information), and a nonlinear model (how much requires a curved boundary). On the leave-one-line-out split of the 5-bus (train on every line except L, test on L) the threshold gives 0.35, linear 0.78 and boosting 0.82. Note the first jump is larger than the second: most of the gain comes from using more information than one scalar, not from the curved boundary. A depth-4 decision tree, readable end to end, already reaches 0.79.',
          'In the operational setting — train on your own feeder, which is fully simulable, and run on it — the classifier reaches 0.906 (5-bus) and 0.872 (14-bus) against 0.491 and 0.390 for the fixed threshold, and identifies WHICH line carries the parameter error in 0.99+ of cases. Letting the agent abstain on the least confident 30% raises accuracy on what it does answer to ~0.99.',
          'The features do NOT transfer between networks, despite being dimensionless: training on the 5-bus and testing on the 14-bus gives 0.581 with the "none" recall collapsing to zero (a 100% false-alarm rate hidden behind a plausible-looking global accuracy), and the reverse direction gives 0.088 — worse than the threshold baseline. Train per network. When training on the target network is not possible, use the training-free stack instead: matched filter to rank lines, then physical verification of the top candidates.',
          'Matched filter: correlate the SHAPE of the observed −r_N against a per-line sensitivity signature ∂h/∂p precomputed once, offline, at a typical planning operating point (a flat start does not work). It needs no training and doubles line-identification accuracy: 0.35 → 0.64 on the 5-bus and 0.21 → 0.60 on the 14-bus, and it barely degrades with noise. Physical verification on top — apply eq. 16 to each of the top k candidates, re-solve the WLS, keep the lowest J — adds a further 0.64 → 0.83 on the 5-bus but only 0.60 → 0.65 on the 14-bus. Keep k small: exhaustive search over every line makes it WORSE in both networks (0.83 → 0.67 and 0.60 → 0.48), because J alone does not break the tie without the matched-filter prior restricting the search.',
          'The single most useful new feature is physical, not statistical: a parameter error on a line perturbs h(x) of that line\'s FLOWS and of its terminal injections together, whereas a measurement attack on the injection of a degree-2 bus flags exactly half of the line\'s own measurements while touching no flow at all — landing precisely on the 0.5 threshold. Separating "fraction of own BRANCH measurements flagged" from "fraction of own INJECTION measurements flagged" turns that ambiguity from a caveat into a discriminator.',
          'Operationally the learned model returns a probability distribution over the four types instead of a hard label. That is what removes the subjectivity: instead of a hand-picked line_fraction_threshold, the operator picks a confidence level, and below it the agent ABSTAINS rather than guessing — the "go and get more evidence" behaviour, not "apply the wrong correction and diverge".',
        ],
        equations: [
          { label: 'Baseline decision rule (what is being replaced)', latex: '\\text{tipo} = \\begin{cases} \\text{measurement}, & f^\\star < \\tau \\\\ \\text{topology}, & f^\\star \\geq \\tau \\;\\wedge\\; \\text{sem fluxo} \\\\ \\text{parameter}, & \\text{caso contrário} \\end{cases}' },
          { label: 'The scalar it thresholds', latex: 'f^\\star = \\max_{\\ell} \\dfrac{|\\{i \\in \\operatorname{own}(\\ell) : |\\operatorname{CME}_{N,i}| > 3\\}|}{|\\operatorname{own}(\\ell)|}' },
          { label: 'Concentration of the signature (IPR — isolated spike vs. spread hump)', latex: '\\operatorname{IPR} = \\sum_{i=1}^{m} p_i^2, \\qquad p_i = \\dfrac{\\operatorname{CME}_{N,i}^2}{\\sum_j \\operatorname{CME}_{N,j}^2}' },
          { label: 'Normalised entropy of the signature', latex: 'S = -\\dfrac{1}{\\ln m}\\sum_{i=1}^{m} p_i \\ln p_i' },
          { label: 'The physical discriminator (branch vs. injection response)', latex: '\\Delta = \\underbrace{\\overline{\\mathbb{1}[|\\operatorname{CME}_N| > 3]}\\big|_{\\text{fluxos de }\\ell}}_{\\text{alto só para parâmetro}} - \\overline{\\mathbb{1}[|\\operatorname{CME}_N| > 3]}\\big|_{\\text{injeções de }\\ell}' },
        ],
        steps: [
          'Solve the AC WLS once and compute the geometric diagnostics (K, UI, r_N, CME_N, CNE)',
          'χ² test on CME_N (dof = m) — if it does not fire, the verdict is "none"',
          'Extract the 54-feature signature vector (shape, geometry, detection, flagged-set composition, line ranking)',
          'Classify: fixed threshold on f* (baseline) OR learned model → probability over the 4 types',
          'If max probability < confidence level → ABSTAIN: run another diagnostic instead of correcting',
          'Otherwise apply the correction matching the winning type, re-solve and go back to the χ² test',
        ],
        loopBackTo: 0,
        table: {
          headers: ['True attack', 'CME_N pattern', 'Fails as', 'Why'],
          rows: [
            ['Measurement, 1 shifted z', 'one isolated spike', 'usually correct', 'best case for the fixed rule'],
            ['Measurement, 4 shifted z on one line\'s own set', 'spread over that line', '"parameter" (≈69%)', 'structurally indistinguishable from a parameter error on a single snapshot — §1.4 signature collision'],
            ['Measurement on a degree-2 bus injection (radial)', 'exactly 50% of two lines\' own sets', '"parameter"', 'lands exactly on the 0.5 comparator (>=), so it tips to parameter'],
            ['Parameter, small magnitude (2–5%)', 'below threshold', '"none"', 'detector never fires — a classification method cannot fix this'],
            ['Parameter, large magnitude', 'spread over the line', 'often correct', 'the case the article calibrated on'],
            ['Topology (line open, model thinks closed)', 'winning line may still have flows', '"parameter" (≈76%)', 'the has_flow test only fires when the WINNING line has no flow measurement; a neighbouring line often wins instead'],
          ],
        },
        glossary: [
          { term: 'Signature collision', definition: 'Several measurements attacked at once produce the same spread-out CME_N pattern as one parameter error. Measured here: monotone in the number of attacked measurements, and worse when the attacker picks targets from a single line\'s own set than at random.' },
          { term: 'Threshold ceiling', definition: 'The best accuracy achievable by ANY fixed cut on the fraction-flagged statistic, found by replaying the deterministic rule for every τ ∈ [0,1] on the recorded sweep. On the 5-bus it is ≈0.62 versus 0.51 at the default τ = 0.5 — the gap between the ceiling and the learned model is what justifies changing the shape of the decision, not its calibration.' },
          { term: 'Network-size-invariant feature', definition: 'A feature expressed only as a ratio, fraction, entropy or already-normalised score, so its value does not scale with the number of buses or measurements. Required for a model trained on one benchmark to transfer to another; verified by the cross-network split (train 5-bus, test 14-bus).' },
          { term: 'Leave-one-line-out', definition: 'Evaluation split where every scenario involving line L is held out and the model is trained on the rest. Stronger than a random split, because Monte Carlo trials of the same (line, magnitude, noise) cell are near-duplicates and a random split leaks them across train and test.' },
          { term: 'Abstention', definition: 'Returning "uncertain" instead of a type when the classifier\'s top probability falls below a chosen confidence level. Replaces the hand-picked line_fraction_threshold with an operator-chosen confidence, and is the point where an agent should seek more evidence rather than apply a correction that may diverge. Measured: abstaining on the least confident 30% raises accuracy on the answered cases to 0.988 (5-bus) and 0.991 (14-bus).' },
          { term: 'Optimal mimicking attack', definition: 'Shifting a line\'s own measurements by exactly d = h_wrong(x̂) − h_true(x̂) reproduces a parameter error almost exactly (30 of 51 features identical to 1e-6). Against it the fixed threshold scores 0.502 — a coin flip — and a learned classifier only 0.705, because the attacker controls z but NOT H: the residual discriminant is the change in hat-matrix geometry (UI, k_ii), which is second-order and line-dependent. This makes 100% accuracy on a single snapshot impossible against an informed adversary — an identifiability limit, not a model-capacity one.' },
          { term: 'Why time helps (and when it does not)', definition: 'A parameter error is a FIXED multiplicative error on r/x/c, whereas the equivalent measurement attack vector d depends on x̂ and therefore drifts with load. An attacker who replays a fixed d is exposed: |J_attack − J_parameter| grows from 0.05 to 9.29 across a daily load ramp. An attacker who recomputes d every snapshot is not: the J-vs-load correlation matches the real parameter error to three decimals. Time converts an identifiability problem into an attacker-capability problem. Separately: legitimate load variation is NOT confusable with an attack in a static estimator (0% false alarm over 0.75–1.15 pu) — the WLS simply re-estimates x. That confusion arises only in the dynamic estimator, where a load ramp produces a large Kalman innovation.' },
          { term: 'Event feature vs. identity feature', definition: 'A per-line feature must describe what HAPPENED to the line, never WHICH line it is. Including bus degree and line loading — identity fingerprints — lets the model memorise a per-line prior that inverts on an unseen line: leave-one-line-out accuracy drops from 0.563 to 0.237, while an in-sample evaluation shows almost no difference (0.998 vs 0.992) and hides the problem.' },
        ],
        relatedFunctions: [
          'ac_bad_data.classify_attack_signature()',
          'signature_sweep.signature_features()',
          'signature_sweep.run_sweep()',
          'signature_sweep.inject_measurement_attack()',
          'signature_sweep.inject_topology_outage()',
          'signature_sweep.build_line_signature_library()',
          'signature_sweep.identify_by_matched_filter()',
          'signature_sweep.line_level_features()',
          'signature_model.fit_signature_classifier()',
          'signature_model.leave_one_line_out()',
          'signature_model.cross_network()',
        ],
      },
      {
        id: 'state-covariance',
        title: 'State Covariance & Estimate Confidence',
        tagline: 'How trustworthy each bus estimate is — which J(x̂) does not tell you.',
        paradigm: 'both',
        description: [
          'The chi-square test answers "are my measurements mutually consistent with the model?" It does NOT answer "how accurate is my state estimate?" These are different questions living in different spaces: J(x̂) is a norm in the m-dimensional measurement space (specifically in the (m − n)-dimensional subspace orthogonal to the range of H), while the state error lives in the n-dimensional state space.',
          'Under Gaussian noise with no gross error the two are not merely weakly related — they are statistically independent. Since r = (I − K)e and x̂ − x = G⁻¹HᵀR⁻¹e are projections of the same noise vector onto orthogonal subspaces, Cov(x̂ − x, r) = G⁻¹Hᵀ − G⁻¹HᵀKᵀ = 0 exactly. A passing chi-square test carries literally zero information about the state error of that snapshot.',
          'What does answer the confidence question is the state covariance Cov(x̂) = G⁻¹ = (HᵀWH)⁻¹. Its diagonal gives a per-state standard deviation, so each bus gets its own error bar. Crucially it depends only on topology, operating point (through H) and meter placement (through W) — never on z — so unlike RMSE it is computable in real operation, where no ground truth exists.',
          'Detectability and impact are complementary, not correlated. For a single-measurement error of b sigmas at measurement i, exactly (1 − kᵢᵢ)·b² of the error energy lands in the residual (where the chi-square test can see it) and kᵢᵢ·b² lands in the state. The split sums to b²: the less detectable an attack, the more of it goes into the state. Weakly observed buses — feeder tips fed by pseudo-measurements — have kᵢᵢ → 1 and large diag(G⁻¹) simultaneously, so they are both the least detectable and the highest-impact place to be attacked. "Low power, end of line, so an undetected attack there is harmless" is exactly backwards.',
          'Practical reading in the app: the θ ±95% and |V| ±95% columns are 1.96·sqrt(diag(G⁻¹)). A real error larger than its own band (flagged ⚠) means the estimate is worse than the model claims it can be, which points at bad data or wrong parameters — and it can happen while J still passes the chi-square test.',
        ],
        equations: [
          { label: 'State covariance', latex: '\\mathrm{Cov}(\\hat{\\mathbf{x}}) = \\mathbf{G}^{-1} = (\\mathbf{H}^\\top\\mathbf{W}\\mathbf{H})^{-1}' },
          { label: 'Per-state uncertainty', latex: '\\sigma_{\\hat{x}_i} = \\sqrt{[\\mathbf{G}^{-1}]_{ii}}, \\qquad \\text{CI}_{95\\%} = \\hat{x}_i \\pm 1.96\\,\\sigma_{\\hat{x}_i}' },
          { label: 'Independence from the residual', latex: '\\mathrm{Cov}(\\hat{\\mathbf{x}} - \\mathbf{x},\\; \\mathbf{r}) = \\mathbf{G}^{-1}\\mathbf{H}^\\top(\\mathbf{I} - \\mathbf{K})^\\top = \\mathbf{0}' },
          { label: 'Zero-sum split of an error at measurement i', latex: '\\underbrace{(1 - k_{ii})b^2}_{\\text{visible to }\\chi^2} + \\underbrace{k_{ii}b^2}_{\\text{pushed into }\\hat{\\mathbf{x}}} = b^2' },
        ],
        glossary: [
          { term: 'Cov(x̂) = G⁻¹', definition: 'Covariance of the estimate. Diagonal = per-state variance. Independent of z, so usable without ground truth.' },
          { term: 'A-priori vs a-posteriori', definition: 'sqrt(diag(G⁻¹)) is a-priori (predicted accuracy, always available); RMSE vs truth is a-posteriori (only in simulation).' },
          { term: 'Why not J(x̂)', definition: 'J tests measurement/model consistency, not estimate accuracy. The two are independent under H₀.' },
        ],
        relatedFunctions: [
          'bad_data.state_covariance()',
          'bad_data.state_uncertainty()',
          'bad_data.residual_covariance()',
        ],
      },
      {
        id: 'critical-measurement',
        title: 'Critical Measurements & Observability',
        tagline: 'Measurements whose removal makes the network unobservable.',
        paradigm: 'both',
        description: [
          'A measurement is critical if its removal causes the state estimation to become unobservable — the gain matrix G = HᵀWH becomes singular and the system cannot be solved. Critical measurements are characterised by kᵢᵢ = 1 (hat matrix diagonal = 1), which also makes them perfect leverage points.',
          'A network is observable if and only if the rank of the Jacobian H equals the number of state variables n. Critical measurements are dangerous because they cannot be detected, identified, or corrected by residual-based methods.',
          'Strategies to mitigate: add redundant measurements (pseudo-measurements from load forecasts, AMI data), use PMUs which provide direct state observations with very high accuracy.',
        ],
        glossary: [
          { term: 'Observable network', definition: 'rank(H) = n — the state can be uniquely determined from the measurement set.' },
          { term: 'Critical measurement', definition: 'Removing it makes rank(H) < n. kᵢᵢ = 1, undetectable by LNR.' },
          { term: 'Redundancy index', definition: 'R = m/n. Rule of thumb: R ≥ 1.5 for reliable bad data detection.' },
        ],
      },
    ],
  },

  // ── 3b. Operational chain (Pipeline tab) ──────────────────────────────────
  {
    id: 'operational-chain',
    label: 'Operational Chain',
    icon: 'Path',
    description: 'Field to OPF — RTU, communication, SCADA RTDB and topology processing.',
    topics: [
      {
        id: 'operational-chain-overview',
        title: 'Operational Chain (Pipeline tab)',
        tagline: 'Meter → RTU → comms → SCADA RTDB → topology processor → estimator.',
        paradigm: 'static',
        description: [
          'Classic state-estimation studies start from a measurement vector z that is already assembled, already simultaneous, and attached to a network model assumed correct. Real operation does none of that. Measurements are grouped into RTUs, travel over a network that delays and drops them, land in a SCADA real-time database where each point has its own age and quality flag, and the network model itself is reconstructed from telemetered breaker status that can be wrong.',
          'The Pipeline tab runs that whole chain. Each layer keeps its own table and its own event log, so a fault injected in one layer can be followed as it propagates into the next — which is the difference between "the residual is large" and "the residual is large because RTU-3 was delayed by 5 s and the snapshot mixes two operating points".',
          'The measurements themselves are not rebuilt here: the chain reuses the exact same measurement construction as the State Estimation tab. With a perfect channel and no attack, the chain reproduces the direct estimator result — that equivalence is asserted by a test, and it is what makes any difference observed afterwards attributable to the chain rather than to the plumbing.',
        ],
        steps: [
          'AC power flow → true state (what the attacker cannot see)',
          'Measurement layer → field readings with σ per sensor class',
          'RTU layer → point mapping (P_BUS5), grouping, scan rate',
          'Communication → per-packet delay, jitter, loss',
          'SCADA RTDB → quality flags, stale detection, snapshot',
          'Topology processor → switch status 0/1/2/3 → active branches',
          'z vector assembled from the RTDB (not from the true state)',
          'WLS AC Gauss-Newton → estimated state vs true state',
        ],
        table: {
          headers: ['Layer', 'What it adds', 'Metric to watch'],
          rows: [
            ['True state', 'The reference nobody in the chain can see', 'convergence'],
            ['Meters', 'σ per sensor class, optional noise', 'number of measurements'],
            ['RTU', 'Point IDs, physical grouping, scan ageing', 'points per RTU'],
            ['Comms', 'Delay, jitter, packet loss', 'loss rate, max delay'],
            ['SCADA RTDB', 'Quality, staleness, last known value', 'snapshot spread (s)'],
            ['Topology', 'Network rebuilt from telemetry, not truth', 'matches reality?'],
            ['Estimator', 'WLS over what actually survived', 'J vs χ² limit, max |ΔV|'],
          ],
        },
        glossary: [
          { term: 'RTDB', definition: 'Real-Time Database — the SCADA point store holding the last known value of every telemetered point, each with its own timestamp and quality flag.' },
          { term: 'Snapshot spread', definition: 'Gap between the newest and oldest reading the estimator treats as simultaneous. Never zero: RTUs scan their points in sequence.' },
          { term: 'Stale', definition: 'A point whose age exceeds the configured limit. Stale points stay in the z vector (dropping every old reading would destroy observability on the first link failure) but are flagged suspect.' },
          { term: 'Point ID', definition: 'The canonical SCADA name of a measurement (P_BUS5, V_BUS3, PF_LINE2). Corrupting the mapping between point IDs and equipment is an attack in itself.' },
        ],
        relatedFunctions: [
          'cadeia_scada.build_points()',
          'cadeia_scada.transmit()',
          'cadeia_scada.RTDB.snapshot()',
          'cadeia_scada.process_topology()',
          'cadeia_scada.PipelineTrace.trail()',
        ],
      },
      {
        id: 'switch-status-four-states',
        title: 'Switch Status: the Double-Bit Object',
        tagline: 'DNP3 Double-Bit Binary Input / IEC 61850 Dbpos — four states, two conclusive.',
        paradigm: 'static',
        description: [
          'A breaker reports two auxiliary contacts: 52a, which closes together with the breaker, and 52b, which opens together with it. In normal operation they are complementary. Two bits give four combinations, packed as the value 2·52a + 52b.',
          'These four states are not a convention invented for this tool. They are a standard protocol object: the DNP3 Double-Bit Binary Input (Object Group 3 for static values, 4 for events) and the IEC 61850 Dbpos / double point status carried in the Pos.stVal of an XCBR (breaker) or XSWI (switch) logical node. Both use the same numbering. Following the standard rather than our own means the tool consumes the same object a real control centre already receives, so a future historian import or a live DNP3 / IEC 60870-5-104 link maps field for field, with no translator in between.',
          'Codes 0 and 3 are where the topology processor has to decide without knowing. That is precisely where an agent has a job: the "infer from measured flow" policy is the only one that reaches into another layer (the analogue measurements sitting in the RTDB) to resolve an ambiguity in the status layer. If current is flowing through the branch, the switch is closed, whatever the contacts claim.',
          'The reason this matters for security is that a topology attack touches no analogue measurement at all. Flipping a contact pair coherently leaves the reading conclusive while describing a different network. The processor rebuilds the wrong Ybus, and the estimator then solves the wrong problem correctly. The resulting residual is not an isolated outlier — it spreads across the measurements around that branch, exactly like the parameter error studied in the Bad Data tab. The two signatures collide, and that collision is what motivates non-linear pattern recognition instead of a fixed threshold.',
          'Crawford and Baran (IEEE Trans. Ind. Appl., 2023, DOI 10.1109/TIA.2023.3321029) make the operational case directly: distribution topology changes for many reasons and some changes are never reported to the control centre, which leaves DSSE running on an incorrect model. They also observe that the topology errors that matter most in practice are not only breaker falsification but unreported capacitor-bank failures and load-balancing reconfigurations — and, crucially, that topology is not itself a measured component.',
        ],
        table: {
          headers: ['Code', '(52a, 52b)', 'DNP3 / IEC 61850', 'Meaning', 'Conclusive'],
          rows: [
            ['0', '(0, 0)', 'Intermediate / intermediate-state', 'In transit, or a broken contact', 'no'],
            ['1', '(0, 1)', 'Determined OFF / off', 'Open', 'yes'],
            ['2', '(1, 0)', 'Determined ON / on', 'Closed', 'yes'],
            ['3', '(1, 1)', 'Indeterminate / bad-state', 'Physical contradiction', 'no'],
          ],
        },
        glossary: [
          { term: '52a', definition: 'Auxiliary contact that follows the breaker: closed when the breaker is closed. The high bit of the double-bit value.' },
          { term: '52b', definition: 'Auxiliary contact that opposes the breaker: closed when the breaker is open. The low bit.' },
          { term: 'Double-Bit Binary Input', definition: 'DNP3 Object Group 3 (static) and 4 (event) — the two-bit breaker position object, exactly these four states.' },
          { term: 'Dbpos', definition: 'IEC 61850 double point status, carried in Pos.stVal of an XCBR or XSWI logical node. Same four states, same numbering.' },
          { term: 'last_known', definition: 'Policy that keeps the last conclusive reading. Classic SCADA behaviour; fails when the switch actually operated during the telemetry failure.' },
          { term: 'flow_inference', definition: 'Policy that resolves an inconclusive switch from the measured branch flow — the cross-layer decision an agent makes.' },
          { term: 'Topology attack', definition: 'Falsifying breaker status while leaving every analogue measurement correct. Produces a wrong network model with no out-of-range value anywhere.' },
        ],
        relatedFunctions: [
          'processador_topologia.SwitchTelemetry.status_code',
          'processador_topologia.process_topology()',
          'ataques.apply_topology_attacks()',
        ],
      },
      {
        id: 'control-layer-opf',
        title: 'Control Layer: OPF on the Estimated State',
        tagline: 'The operator never optimises the real network — only the model they rebuilt.',
        paradigm: 'static',
        description: [
          'Running an OPF is not the point of this layer; pandapower already does that. The point is that the operator never solves it on the real network. They solve it on the model the topology processor reconstructed, over the state the estimator delivered. The setpoints come out of that model and are then applied to the real grid.',
          'When the model is right the two coincide and there is nothing to study. When something upstream is wrong, two things appear that no estimator metric captures. The first is the control error: the gap between what was dispatched and what would have been dispatched with perfect information, measured in MW rather than in residual. The second is the hidden violation: a constraint breached in reality after the setpoints land, which the operator\'s own OPF considered satisfied. No alarm is raised anywhere.',
          'The hidden violation is the argument that lands with a real operator. Not "the residual went up", but "you would have left bus 4 below 0.95 pu without receiving a single alarm".',
          'One subtlety matters for honesty: the external grid is a slack bus and absorbs whatever is left over, so the realised power flow never reproduces the OPF point exactly, even with a perfect model. That residue is measured separately (the baseline) and subtracted before anything is called hidden. Without that subtraction every run reports false hidden violations — which is exactly what the first version of this code did.',
          'Merit order is set so the upstream grid is dearer than local generation, the typical distribution framing: importing has a price, the local DER is already there. With that order the optimum depends on whether the network can carry the local injection — that is, on the model — which is what makes a topology error change the answer. Reversed, the OPF would just say "import everything" and the model would barely matter.',
          'When the OPF does not converge, that is a result rather than a crash, but the reason has to be distinguished, because the two possible reasons call for opposite responses. A solver failure is attacked by changing solver or starting point. An empty feasible set cannot be attacked at all: no algorithm converges to a point that does not exist, and the only ways out are to widen a limit or give the network a controllable resource. The diagnosis is cheap: a plain power flow gives the network\'s natural operating point, and comparing that point against the voltage band says whether there was ever a chance. It only runs after the OPF has already failed, so it costs nothing on a normal run.',
          'The concrete case is the IEEE 33-bus feeder. Its natural profile sags to 0.913 pu at the end of the trunk, against a 0.95 pu floor, with no controllable generation anywhere on the feeder — 21 of its 33 buses start outside the band before any attack is injected. The optimiser is right to fail. What was missing was saying so, instead of surfacing a raw exception that reads as a broken tool. Note that the fix is never to quietly give the benchmark some DER until the numbers look good: adding distributed generation is a legitimate study scenario, but an explicit one.',
        ],
        steps: [
          'OPF on the believed model → the setpoints actually dispatched',
          'OPF on the true model → what perfect information would have dispatched',
          'Apply the dispatched setpoints to the real network → what physically happens',
          'Apply the ideal setpoints to the real network → the unavoidable baseline',
          'Hidden violations = reality − predicted − baseline',
        ],
        table: {
          headers: ['Output', 'Meaning'],
          rows: [
            ['Max setpoint error', 'Largest |ΔP| between dispatched and ideal, in MW — the cost of the attack in physical units'],
            ['Cost gap', 'Objective difference between the operator\'s OPF and the ideal one'],
            ['Reality violations', 'Constraints breached after the dispatched setpoints land'],
            ['Baseline violations', 'Those that would happen anyway, with perfect information'],
            ['Hidden violations', 'Reality minus predicted minus baseline — caused by the wrong model and invisible'],
          ],
        },
        glossary: [
          { term: 'Hidden violation', definition: 'A constraint breached in reality that the operator\'s OPF thought was satisfied. The number that matters to a control centre.' },
          { term: 'Control error', definition: 'Difference between dispatched and ideal setpoints. Measures the attack in MW, not in residual.' },
          { term: 'Baseline', definition: 'Violations that occur even with a perfect model, from slack-bus absorption. Subtracted before anything counts as hidden.' },
          { term: 'DER curtailment', definition: 'sgen made controllable between zero and available power — the most common control action on a distribution feeder with DER.' },
          { term: 'Infeasible limits', definition: 'The network\'s natural operating point already sits outside the constraints and nothing in the model can move it. The feasible set is empty before the optimiser starts, so non-convergence is the correct answer, not a solver problem.' },
        ],
        relatedFunctions: [
          'opf.prepare_opf_net()',
          'opf.run_opf()',
          'opf.apply_setpoints()',
          'opf.opf_under_uncertainty()',
          'opf.check_violations()',
          'opf.diagnose_infeasibility()',
        ],
      },
      {
        id: 'cross-layer-agents',
        title: 'Cross-Layer Agents',
        tagline: 'One agent per layer; the verdict comes from the chain, not from any of them.',
        paradigm: 'static',
        description: [
          'The agents in the Agents tab are partitioned by island: each cluster of the network hosts an observability, an estimator and a bad-data agent, and the split is geographic. These are different. They are partitioned by layer of the operational chain, and what they produce is not an estimate but a judgement about how much the layer\'s output can be trusted. The two axes are orthogonal and coexist.',
          'Each agent on its own is a trivial check — the delay crossed a threshold, the residual crossed a threshold. What none of them does alone is explain why the state does not deserve confidence. That only appears when one agent\'s judgement becomes the next one\'s input: the communication agent sees an abnormal delay on RTU-3, the SCADA agent therefore downgrades that RTU\'s points to suspect (on its own it had no reason to — their timestamps and quality are fine), the estimation agent loses redundancy and raises its uncertainty, and the control agent refuses the aggressive action.',
          'That is the central argument of the multi-agent axis of the thesis: the decision not to act is taken by no single agent, and no fixed threshold would produce it, because every layer taken alone was inside its own limit.',
          'Thresholds are calibrated from the system rather than fixed. The snapshot-spread limit, for instance, derives from the slowest RTU scan cycle present in the run: a SCADA snapshot legitimately spans one scan cycle, so a fixed one-second limit made a perfectly healthy chain report an inconsistent snapshot and block every dispatch. A PMU-based system gets a limit in milliseconds from the same rule.',
          'The agents never recompute anything. They read the artefacts the layers already produced and emit messages. Turning the layer off changes no number in the chain result — which is what makes comparing "with" and "without" agents legitimate.',
          'One rule overrides the propagation: if the control layer itself returned no answer — the OPF did not converge — the verdict is BLOCK regardless of how clean every upstream layer looks. Without a dispatch there is nothing to release. This is worth stating because the obvious implementation gets it wrong: reading only the hidden-violation count yields zero on a run that never dispatched at all, and the console then announces CONTROL RELEASED directly beneath a high-priority alarm saying the optimiser failed. On a screen whose whole purpose is to answer "can I act on this?", no aggregate state may be more optimistic than the worst alarm the same screen is displaying.',
        ],
        steps: [
          'Field agent — physical plausibility of the raw readings',
          'Communication agent — delay, jitter and loss per RTU',
          'SCADA agent — freshness, quality, snapshot spread; escalates what comms reported',
          'Topology agent — conclusive vs inconclusive switch readings, and whether flow can resolve them',
          'Estimation agent — χ², redundancy, plus everything flagged upstream',
          'Control agent — dispatch, derate or block',
        ],
        table: {
          headers: ['Verdict', 'When', 'What it means'],
          rows: [
            ['DISPATCH', 'No layer raised a concern', 'Control action released'],
            ['DERATE', 'Upstream layers flagged something non-critical', 'Conservative action only, no switching'],
            ['BLOCK', 'A critical message reached the control agent', 'The delivered state does not support acting'],
          ],
        },
        glossary: [
          { term: 'DEGRADED_LINK', definition: 'Communication agent → SCADA agent: this RTU\'s traffic is abnormally delayed.' },
          { term: 'SUSPECT_POINTS', definition: 'SCADA agent → estimation agent: these points are downgraded because of the link, not because of anything in the data.' },
          { term: 'LOW_CONFIDENCE_STATE', definition: 'Estimation agent → control agent: the state does not support an aggressive action.' },
          { term: 'Propagation chain', definition: 'The findings that exist only because of another layer. The list of decisions no agent would have taken looking at its own layer alone.' },
        ],
        relatedFunctions: [
          'agentes_cadeia.ChainAgentTeam.run()',
          'agentes_cadeia.ChainAgentTeam._spread_threshold()',
          'agentes_cadeia.run_chain_agents()',
        ],
      },
      {
        id: 'chain-attacks',
        title: 'Attacks by Layer',
        tagline: 'Where the fault is injected changes the signature it leaves.',
        paradigm: 'static',
        description: [
          'The same numerical corruption produces very different evidence depending on where it enters. A bias added straight to z is an isolated outlier that LNR finds in one pass. The same bias applied through a compromised RTU corrupts a whole block of correlated measurements and leaves a spread-out signature that looks like a model error rather than bad data.',
          'Attacks marked stealthy produce no out-of-range value anywhere: every reading stays plausible, no point goes missing, no timestamp is old. Only consistency analysis across layers can catch them.',
        ],
        table: {
          headers: ['Layer', 'Attacks', 'What it breaks'],
          rows: [
            ['Measurement', 'bias, scaling, freeze, failure, FDI', 'The value of one reading'],
            ['RTU', 'RTU compromise, point mapping corruption, bad timestamp', 'A correlated block, or which equipment a value belongs to'],
            ['Communication', 'delay attack, packet loss', 'Simultaneity of the snapshot, or redundancy'],
            ['Topology', 'breaker status falsification, contact desync', 'The network model itself'],
          ],
        },
        glossary: [
          { term: 'RTU compromise', definition: 'Bias applied to every point of one remote unit. The error becomes correlated inside a physical block, which is what real intrusions look like.' },
          { term: 'Point mapping corruption', definition: 'Swapping the values of two SCADA points. Nothing is out of range; the estimator simply attributes bus A power to bus B.' },
          { term: 'Delay attack', definition: 'Selectively delaying one RTU. Every measurement stays legitimate and correct — what breaks is that they no longer describe the same instant.' },
          { term: 'Stealthy', definition: 'An attack producing no locally implausible value. Undetectable by range or freshness checks alone.' },
        ],
        relatedFunctions: [
          'ataques.ATTACK_CATALOG',
          'ataques.apply_sensor_attacks()',
          'ataques.apply_channel_attacks()',
          'ataques.apply_topology_attacks()',
        ],
      },
    ],
  },

  // ── 4. Sensors & Measurements ─────────────────────────────────────────────
  {
    id: 'sensors',
    label: 'Sensors & Measurements',
    icon: 'Gauge',
    topics: [
      {
        id: 'sensor-classes',
        title: 'Sensor Classes',
        tagline: 'PMU, SCADA, AMI and Smart Meter — rates, accuracy and placement.',
        paradigm: 'both',
        description: [
          'The app models four sensor classes. Each class has a different sampling rate, measurement accuracy (σ), and set of observable quantities. The weight matrix W = R⁻¹ used by the WLS estimator is built directly from these σ values — smaller σ = higher weight = more trusted measurement.',
        ],
        table: {
          headers: ['Sensor', 'Measures', 'Rate', 'σ (pu)', 'Typical use'],
          rows: [
            ['PMU', '|V|, θ, P, Q', '30–60 Hz', '0.001 (0.1%)', 'GPS-synchronised phasors — gold standard for observability'],
            ['SCADA', 'P, Q, |V|', '1–4 s', '0.02 (2%)', 'Transmission EMS backbone — most deployed sensor today'],
            ['AMI', 'P, Q', '15 min', '0.03 (3%)', 'Distribution observability at low cost (smart meter reads)'],
            ['Smart Meter', 'P (sometimes Q)', '15–60 min', '0.05 (5%)', 'Customer-level granularity — noisiest source'],
          ],
        },
        glossary: [
          { term: 'PMU', definition: 'Phasor Measurement Unit — GPS-synchronised, high-rate (30–60 Hz) voltage and current phasor measurements.' },
          { term: 'SCADA', definition: 'Supervisory Control and Data Acquisition — conventional power system telemetry, 1–4 s scan cycle.' },
          { term: 'AMI', definition: 'Advanced Metering Infrastructure — smart metering network with 15-min billing reads and remote disconnect.' },
          { term: 'σ (sigma)', definition: 'Measurement standard deviation — models sensor accuracy. Typical: PMU 0.1%, SCADA 1–3%, AMI 2%, Smart Meter 3–5%.' },
        ],
        relatedFunctions: [
          'measurement.SensorSpec',
          'measurement.Measurement',
          'measurement_layer.apply_measurement_layer()',
          'measurement_layer.subsample_by_sensor_class()',
          'sensor_placement.auto_place_sensors_transmission()',
          'sensor_placement.auto_place_sensors_distribution()',
        ],
      },
      {
        id: 'measurement-types',
        title: 'Measurement Types',
        tagline: 'Which physical quantity each measurement captures.',
        paradigm: 'both',
        description: [
          'The state estimator accepts six measurement types, each described by its nonlinear function hᵢ(x) in the Jacobian H = ∂h/∂x. The first two (|V|, θ) are direct state observations — their Jacobian rows are trivial unit vectors. The remaining four require the full AC Ybus equations.',
        ],
        table: {
          headers: ['Type', 'Symbol', 'Measured by', 'h_i(x) form'],
          rows: [
            ['Bus voltage magnitude', '|Vᵢ|', 'PMU / SCADA / AMI', 'Direct: |Vᵢ|'],
            ['Bus voltage angle', 'θᵢ', 'PMU only', 'Direct: θᵢ'],
            ['Bus active injection', 'Pᵢ', 'All sensors', 'Σⱼ |Vᵢ||Vⱼ|(Gᵢⱼ cosθᵢⱼ + Bᵢⱼ sinθᵢⱼ)'],
            ['Bus reactive injection', 'Qᵢ', 'All sensors', 'Σⱼ |Vᵢ||Vⱼ|(Gᵢⱼ sinθᵢⱼ − Bᵢⱼ cosθᵢⱼ)'],
            ['Branch active flow', 'Pᵢⱼ', 'SCADA / PMU', 'AC branch equations (nonlinear in |V|, θ)'],
            ['Branch reactive flow', 'Qᵢⱼ', 'SCADA / PMU', 'AC branch equations (nonlinear in |V|, θ)'],
          ],
        },
        equations: [
          { label: 'Measurement vector', latex: '\\mathbf{z} = [|V_i|,\\ \\theta_i,\\ P_i,\\ Q_i,\\ P_{ij},\\ Q_{ij}]^\\top + \\boldsymbol{\\varepsilon}' },
          { label: 'Error model', latex: '\\varepsilon_i \\sim \\mathcal{N}(0,\\,\\sigma_i^2)' },
        ],
      },
      {
        id: 'noise-model',
        title: 'Measurement Noise Model',
        tagline: 'How z_true, σ, R and W connect the physics to the estimator.',
        paradigm: 'both',
        description: [
          'Every measurement z in the app is the sum of the true (noise-free) value z_true and a Gaussian noise sample ε. The true value comes from running a reference power flow (Stage C1 of the synthetic pipeline); the noise is injected in Stage C2.',
          'The standard deviation σᵢ is assigned per sensor class and per measurement type. It encodes how accurate the sensor is — a smaller σ means a more reliable measurement. The weight matrix W = R⁻¹ (inverse measurement covariance) tells the WLS estimator how much to trust each measurement: high weight = small σ = reliable.',
          'The covariance matrix R is diagonal under the standard assumption that sensor errors are independent. If off-diagonal correlations exist (e.g., multiple readings from the same PMU), R must be the full covariance — the WLS normal equations are unaffected in form but G = HᵀWH uses the full R⁻¹.',
          'Sigma reference values by sensor class: PMU ≈ 0.001 pu (0.1%), SCADA ≈ 0.02 pu (2%), AMI ≈ 0.03 pu (3%), Smart Meter ≈ 0.05 pu (5%). These are relative to the system base (1 pu voltage, Sbase MW).',
        ],
        equations: [
          { label: 'True measurement (ground truth)', latex: 'z_i^{\\text{true}} = h_i(\\mathbf{x}^{\\text{true}})' },
          { label: 'Observed measurement with noise', latex: 'z_i = z_i^{\\text{true}} + \\varepsilon_i, \\quad \\varepsilon_i \\sim \\mathcal{N}(0,\\,\\sigma_i^2)' },
          { label: 'Measurement covariance (diagonal)', latex: '\\mathbf{R} = \\operatorname{diag}(\\sigma_1^2,\\,\\sigma_2^2,\\,\\ldots,\\,\\sigma_m^2)' },
          { label: 'Weight matrix', latex: '\\mathbf{W} = \\mathbf{R}^{-1} = \\operatorname{diag}(1/\\sigma_1^2,\\,\\ldots,\\,1/\\sigma_m^2)' },
          { label: 'Bad measurement model (additive gross error)', latex: 'z_k^{\\text{bad}} = z_k^{\\text{true}} + \\varepsilon_k + b_k, \\quad |b_k| \\gg 3\\sigma_k' },
        ],
        glossary: [
          { term: 'z_true', definition: 'The noise-free measurement computed directly from the true state via h(x_true). Not accessible in practice — only available in simulation.' },
          { term: 'z (observed)', definition: 'The actual measurement fed to the estimator: z = z_true + ε. Contains sensor noise and possibly gross errors.' },
          { term: 'ε (epsilon)', definition: 'Gaussian noise sample ε ~ N(0, σ²). Models random sensor uncertainty. Each sensor has its own σ.' },
          { term: 'σ (sigma)', definition: 'Standard deviation of the measurement noise for sensor i. Determines trust (weight): w_i = 1/σ_i².' },
          { term: 'R', definition: 'Measurement error covariance matrix, diagonal: R = diag(σ₁², …, σₘ²). Off-diagonal elements = 0 under independence.' },
          { term: 'W = R⁻¹', definition: 'Weight matrix. Diagonal elements wᵢ = 1/σᵢ². Larger weight → estimator trusts that measurement more.' },
          { term: 'b (gross error)', definition: 'Large additive error |b| ≫ 3σ injected into one measurement to simulate a bad measurement (meter fault, communication error, cyber attack).' },
        ],
        relatedFunctions: [
          'measurement_layer.apply_measurement_layer()',
          'measurement.SensorSpec',
          'batch_powerflow.run_batch_powerflow()',
        ],
      },
    ],
  },

  // ── 5. Glossary ────────────────────────────────────────────────────────────
  {
    id: 'glossary',
    label: 'Glossary',
    icon: 'BookOpen',
    topics: [
      {
        id: 'power-system-terms',
        title: 'Power System Terms',
        tagline: 'Network, topology and power-flow definitions.',
        paradigm: 'both',
        description: ['Core power system terminology used throughout the app.'],
        glossary: [
          { term: 'Bus (Bar)', definition: 'A node in the power network where generators, loads, or lines connect.' },
          { term: 'Branch', definition: 'An edge in the network — a transmission line or transformer between two buses.' },
          { term: 'Slack bus', definition: 'The reference bus (θ = 0, |V| = 1 pu) that balances the active power mismatch for the whole network.' },
          { term: 'PQ bus', definition: 'A load bus where P and Q injections are specified; |V| and θ are solved.' },
          { term: 'PV bus', definition: 'A generator bus where P and |V| are specified; Q and θ are solved.' },
          { term: 'Y-bus (Admittance matrix)', definition: 'The n×n complex matrix Y_bus encoding all network admittances. Y_bus V = I.' },
          { term: 'Flat start', definition: 'Initialising the iterative solver at θ = 0, |V| = 1 pu — the standard starting point.' },
          { term: 'Per unit (pu)', definition: 'Normalised system where base voltage = 1.0, base power = Sbase. Simplifies equations.' },
          { term: 'X/R ratio', definition: 'Reactance-to-resistance ratio. High X/R (≥5) → DC approximation valid. Low X/R (<2) → use DistFlow.' },
          { term: 'Radial network', definition: 'A tree-shaped network with no loops. Most distribution feeders are radial.' },
          { term: 'Meshed network', definition: 'A network with loops. Required for AC NR; LinDistFlow does not apply.' },
        ],
      },
      {
        id: 'estimation-terms',
        title: 'State Estimation Terms',
        tagline: 'WLS, residuals, and bad-data terminology.',
        paradigm: 'both',
        description: ['Estimation and statistics terminology used in the state estimator.'],
        glossary: [
          { term: 'State vector x', definition: 'The set of variables being estimated: bus voltage angles θ and magnitudes |V|.' },
          { term: 'Jacobian H', definition: 'The m×n matrix of partial derivatives H = ∂h/∂x evaluated at the current iterate.' },
          { term: 'Gain matrix G', definition: 'G = HᵀWH — the left-hand side of the normal equations. Must be non-singular for observability.' },
          { term: 'Residual r̂', definition: 'Post-estimation difference between measured and estimated values: r̂ = z − h(x̂).' },
          { term: 'Weight matrix W', definition: 'W = R⁻¹, diagonal matrix of inverse measurement variances. Higher weight = more trusted measurement.' },
          { term: 'Convergence', definition: 'The iterative solver has converged when max|Δx| < ε (typically 1×10⁻⁴ pu or rad).' },
          { term: 'Observability', definition: 'rank(H) = n — sufficient measurements exist to uniquely determine the state.' },
          { term: 'Redundancy', definition: 'Having more measurements than unknowns (m > n). Required for bad data detection.' },
          { term: 'Leverage point', definition: 'Measurement with hat matrix diagonal kᵢᵢ ≈ 1 — its residual is always near zero.' },
          { term: 'Masked error', definition: 'A real error that goes undetected because it is absorbed by the estimator via a leverage point.' },
        ],
      },
    ],
  },

  // ── 6. Case Studies ────────────────────────────────────────────────────────
  {
    id: 'case-studies',
    label: 'Case Studies',
    icon: 'Atom',
    topics: [
      {
        id: 'ieee-5-bus',
        title: 'Stagg & El-Abiad 5-Bus Test System',
        tagline: 'The classic small textbook network for algorithm validation.',
        paradigm: 'static',
        description: [
          'There is no official IEEE 5-bus test case. The IEEE-endorsed set (University of Washington archive, IEEE Common Data Format) contains the 14, 30, 57, 118 and 300-bus systems; no 5-bus system belongs to it. The name "IEEE 5-bus" circulates in the literature for two different networks, so this app names them explicitly.',
          'This built-in topology is the Stagg & El-Abiad 5-bus system, from Computer Methods in Power System Analysis (1968). It has 5 buses and 7 branches: 1-2, 1-3, 2-3, 2-4, 2-5, 3-4 and 4-5, with line impedances from 0.02 + j0.06 to 0.08 + j0.24 pu. One slack bus, two PV buses and two PQ buses. It is the classic textbook network for power flow and state estimation.',
          'The other network often called "IEEE 5-bus" is the PJM 5-bus, distributed as case5 in MATPOWER and pandapower. It has 6 branches and a different connectivity, and was built to illustrate optimal power flow and locational marginal pricing. It is available through the pandapower case library in the Topology tab, listed under its own name. The two are not interchangeable: their measurement geometry differs, and comparing results across them without noticing has already caused a wrong diagnosis in this project.',
          'With the standard measurement set (|V| at every bus, P and Q injections at every bus, and P and Q flows at both ends of every branch), this network yields 43 measurements for 9 states, a redundancy ratio of about 4.8.',
        ],
        glossary: [
          { term: 'Stagg & El-Abiad 5-bus', definition: '5 buses, 7 branches. Textbook network from Stagg & El-Abiad (1968). Built-in topology in this app. Often called "IEEE 5-bus", although no official IEEE 5-bus exists.' },
          { term: 'PJM 5-bus (case5)', definition: '5 buses, 6 branches. Distributed as case5 in MATPOWER and pandapower, designed for OPF and LMP studies. A different network from the one above, despite sharing the nickname.' },
        ],
      },
      {
        id: 'ieee-14-bus',
        title: 'IEEE 14-Bus Test System',
        tagline: 'Static and dynamic benchmark, including the Chapter 8 EKF reproduction.',
        paradigm: 'both',
        description: [
          'The IEEE 14-bus system represents a portion of the American Electric Power system in 1962. It has 14 buses, 20 branches, 5 generators and 11 load buses. It is the standard benchmark for bad data identification tests.',
          'The higher redundancy and larger state space make it suitable for testing the LNR vs. CME comparison: with 14 buses, there are more potential leverage points and the risk of masked errors is higher.',
          'The scripts/validar_estimador_ieee14.py script runs the static validation pipeline. The 14_BUS_IEEE_dynamic_AC.ipynb notebook tests the reusable EKF with a separately calibrated Q, injected branch-flow gross errors, a load step and static-WLS restart.',
          'This is currently a structural reproduction rather than an exact numerical replication of Bretas et al. Chapter 8. With 122 measurements, the original fixed thresholds produce false alarms and may briefly classify a real load step as gross data, so Monte Carlo threshold calibration remains necessary.',
        ],
        relatedFunctions: [
          'scripts/validar_estimador_ieee14.py',
          'notebooks/simulacao/14_BUS_IEEE_dynamic_AC.ipynb',
          'sistemas_dinamicos.run_extended_kalman_filter()',
        ],
      },
      {
        id: 'ieee-39-bus',
        title: 'IEEE 39-Bus (New England) System',
        tagline: 'Large transmission system for scalability and performance testing.',
        paradigm: 'static',
        description: [
          'The IEEE 39-bus system (New England Test System) has 39 buses, 46 branches and 10 generators. It is used for scalability testing of the state estimator and as the basis for the beamer presentations in this repository.',
          'At this scale, the difference in computation time between the DC linear (one linear solve) and AC Gauss-Newton (iterative) estimators becomes clearly visible. Bad data with multiple simultaneous errors can also cause more complex interactions.',
        ],
      },
    ],
  },

  // ── 7. Data Generation ─────────────────────────────────────────────────────
  // ── 7. Topologies & Formats ────────────────────────────────────────────────
  {
    id: 'topologies-io',
    label: 'Topologies & Formats',
    icon: 'Path',
    description: 'Network ingestion, export, open power system standards, and GIS integration.',
    topics: [
      {
        id: 'topology-import-export',
        title: 'Topology Import & Export (Open Standards & GIS)',
        tagline: 'Universal network I/O across pandapower, OpenDSS, MATPOWER, CIM, GeoJSON, and CSV.',
        paradigm: 'both',
        description: [
          'The DSSE Workbench supports seamless import, editing, and export of electrical networks across 10 open and commercial formats. Rather than locking users into fixed built-in benchmarks, researchers can import custom utility feeders, modify parameters in real time, and export back to disk.',
          'Format pivot architecture: all external formats are ingested through pandapowerNet as an intermediate pivot model. This normalises branch impedances, transformer short-circuit reactances, and bus injections into standard per-unit quantities (Sn = 1 MVA, Vn = 1 kV, Zbase = 1 Ω).',
          'Supported import formats: pandapower JSON (.json), pandapower Excel (.xlsx), MATPOWER (.m, .mat), OpenDSS (.dss, .zip), CIM CGMES (IEC 61970/61968 .xml, .zip), UCTE DEF (.ucte), GeoJSON (.geojson), CSV decoupled tables (ZIP or single with buses.csv and lines.csv), GraphML (.graphml for GNN/AI pipelines), and Workbench native JSON.',
          'Supported export formats: Workbench JSON (preserves meters and switch states), pandapower JSON, Excel (.xlsx), CSV table archive (.zip), and GraphML.',
          'GIS & Geographic Coordinates: when importing from GeoJSON, OpenDSS (BusCoords), pandapower (bus_geodata), or CSV (x_coord, y_coord), spatial coordinates (lon/lat WGS84 or projected plane) are extracted into geoX/geoY. The D3 Network Diagram prioritises these physical coordinates over graph-force layouts.',
          'Non-blocking validation: upon ingestion, an AC power flow is executed in the background. If parameters fail to converge, a non-blocking warning is displayed, allowing the engineer to inspect and correct parameters in the table instead of aborting the import.',
          'Scalability handling: networks with 500–2,000 buses show an operational notice; for networks exceeding 2,000 buses, graphical diagram rendering is automatically deferred to maintain optimal UI responsiveness.',
        ],
        table: {
          headers: ['Format', 'Extension', 'Type / Standard', 'Phases', 'Geo Coordinates'],
          rows: [
            ['pandapower JSON', '.json', 'Native tabular serialization', '1φ eq.', 'Yes (bus_geodata)'],
            ['OpenDSS', '.dss, .zip', 'EPRI declarative script', '3φ / 1φ eq.', 'Yes (BusCoords)'],
            ['MATPOWER', '.m, .mat', 'PSERC / Cornell matrices', '1φ eq.', 'No'],
            ['CIM CGMES', '.xml, .zip', 'IEC 61970 / IEC 61968 RDF/XML', 'Total (T&D)', 'Yes (GL profile)'],
            ['GeoJSON', '.geojson, .json', 'RFC 7946 geospatial features', 'Custom attributes', 'Yes (WGS84 lon/lat)'],
            ['CSV decoupled', '.csv, .zip', 'Relational tables (buses, lines)', 'Flexible', 'Optional columns'],
            ['GraphML', '.graphml', 'Attributed graph XML (GNNs)', 'Arbitrary', 'Attributes'],
            ['Workbench JSON', '.json', 'Native app state + meters', '1φ eq.', 'Yes (geoX, geoY)'],
          ],
        },
        relatedFunctions: [
          'app.backend.services.topology_io.import_file()',
          'app.backend.services.topology_io.export_topology()',
          'app.backend.services.topology_io.ppnet_to_topology()',
          'app.backend.routes.topology.import_topology()',
        ],
      },
    ],
  },

  // ── 8. Data Generation ─────────────────────────────────────────────────────
  {
    id: 'data-generation',
    label: 'Data Generation',
    icon: 'Database',
    topics: [
      {
        id: 'synthetic-pipeline',
        title: 'Synthetic Measurement Pipeline',
        tagline: 'Two-stage pipeline: ground-truth power flow → noisy measurements.',
        paradigm: 'both',
        description: [
          'The synthetic data pipeline generates realistic measurement datasets for state estimation research. It runs in two stages: C1 (ground truth) and C2 (measurement simulation).',
          'Stage C1 — Batch Power Flow: runs AC Newton-Raphson (pandapower) for each time step in a temporal scenario, producing ground-truth P, Q, |V|, θ at every bus and branch.',
          'Stage C2 — Measurement Layer: applies class-appropriate Gaussian noise to the ground-truth quantities, subsamples according to sensor sampling rates (PMU: every step; SCADA: every 10 steps; AMI: every 40 steps), and assembles the final measurement matrix.',
          'The result is a time-series dataset suitable for testing multi-rate fusion, Kalman filter estimators, or Monte Carlo bad-data studies.',
        ],
        steps: [
          'C1: Define load shape (sinusoidal daily, SimBench, or custom)',
          'C1: Run pandapower AC NR for each time step → store P, Q, |V|, θ',
          'C2: For each sensor class, apply σ-scaled Gaussian noise',
          'C2: Subsample to sensor rate (PMU 30 Hz, SCADA 4 s, AMI 15 min)',
          'C2: Assemble and save measurement matrix as CSV / HDF5',
        ],
        relatedFunctions: [
          'batch_powerflow.run_batch_powerflow()',
          'measurement_layer.apply_measurement_layer()',
          'load_shapes.SinusoidalDailyShape',
          'load_shapes.SimbenchShapeProvider',
          'sensor_placement.auto_place_sensors_distribution()',
        ],
      },
      {
        id: 'load-shapes',
        title: 'Load Shapes',
        tagline: 'Temporal load profiles driving the synthetic scenario.',
        paradigm: 'both',
        description: [
          'Load shapes define how bus power injections (P, Q) vary over time. The synthetic pipeline supports three shape providers.',
          'SinusoidalDailyShape: a simple 24-hour sinusoidal profile with configurable amplitude, phase, and noise level. Good for quick experiments.',
          'SimbenchShapeProvider: uses SimBench benchmark profiles (German low/medium voltage network loads) for realistic diversity across bus types (residential, commercial, industrial).',
          'Custom shapes: any callable f(t) → P_factor can be plugged in as a shape provider.',
        ],
        relatedFunctions: [
          'load_shapes.SinusoidalDailyShape',
          'load_shapes.SimbenchShapeProvider',
        ],
      },
    ],
  },
  {
    id: 'multiagent',
    label: 'Multi-Agent Framework',
    icon: 'Cpu',
    description: 'Distributed multi-layer state estimation, on-demand communication, and plug-in testbed.',
    topics: [
      {
        id: 'multiagent-dsse-architecture',
        title: 'Multi-Agent DSSE Architecture',
        tagline: 'Decoupling large distribution networks into autonomous, low-overhead agent clusters.',
        paradigm: 'both',
        description: [
          'Traditional centralized DSSE requires inverting global gain matrices (Hᵀ W H) of dimension 2N × 2N at every iteration. For feeders with thousands of buses, this becomes a severe computational bottleneck.',
          'The multi-agent framework partitions the grid into K localized clusters (islands) using Spectral Graph Partitioning or Radial Feeder Tree traversal.',
          'Each island runs a dedicated team of specialized agents: Observability, Pseudo-Measurement (ML), Estimator, Bad Data (CNE/Innovation), and Thermal Rating.',
        ],
        relatedFunctions: [
          'src.tese_dsse.agentes.clustering.partition_spectral',
          'src.tese_dsse.agentes.engine.MultiAgentSimulationEngine',
          'src.tese_dsse.agentes.tipos_agentes.EstimatorAgent',
        ],
      },
      {
        id: 'engineer-cry-protocol',
        title: 'On-Demand "Engineer Cry" Protocol',
        tagline: 'Low-cost, event-driven inter-agent communication.',
        paradigm: 'both',
        description: [
          'Continuous communication between all nodes and central SCADA inflates telecommunication costs and bandwidth usage, making it commercially unviable for DSOs.',
          'In this architecture, communication is strictly on-demand. An ObservabilityAgent continuously monitors local matrix rank and measurement redundancy.',
          'Only when rank loss occurs (or when bad data cannot be resolved locally), the agent fires an "Engineer Cry" request to boundary neighbors for assistance.',
        ],
        relatedFunctions: [
          'src.tese_dsse.agentes.tipos_agentes.ObservabilityAgent',
          'src.tese_dsse.agentes.base.AgentMessage',
        ],
      },
      {
        id: 'agent-plugins-ecosystem',
        title: 'Agent Extensibility & Plugin Hub',
        tagline: 'Open testbed for coupling ML pseudo-measurements and physical line ratings.',
        paradigm: 'both',
        description: [
          'The framework provides an open plugin registry allowing researchers to plug in external ML models (e.g. Namdi GNN/LSTM pseudo-generators), dynamic thermal line rating (Michel IEEE 738), or specialized Bad Data classifiers without altering core estimator code.',
        ],
        relatedFunctions: [
          'src.tese_dsse.agentes.plugins.registry.PluginRegistry',
          'src.tese_dsse.agentes.base.AgentPlugin',
        ],
      },
    ],
  },
]

// ─── Search index (flat list of all topics with category metadata) ─────────────

export interface HelpTopicFlat {
  categoryId: string
  categoryLabel: string
  topic: HelpTopic
}

export function buildHelpIndex(): HelpTopicFlat[] {
  return HELP_CATEGORIES.flatMap((cat) =>
    cat.topics.map((topic) => ({
      categoryId: cat.id,
      categoryLabel: cat.label,
      topic,
    }))
  )
}

export function searchHelp(query: string): HelpTopicFlat[] {
  const q = query.toLowerCase().trim()
  if (!q) return []
  const index = buildHelpIndex()
  return index.filter(({ topic, categoryLabel }) => {
    const haystack = [
      topic.title,
      topic.tagline,
      categoryLabel,
      ...(topic.description ?? []),
      ...(topic.glossary?.map((g) => `${g.term} ${g.definition}`) ?? []),
      ...(topic.relatedFunctions ?? []),
    ]
      .join(' ')
      .toLowerCase()
    return haystack.includes(q)
  })
}
