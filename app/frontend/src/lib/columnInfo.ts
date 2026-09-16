/**
 * Column-level "how was this computed" registry for the measurement/residual
 * tables in MeasurementsSummaryCard and StateEstimationTab. Same pattern as
 * methodInfo.ts — one place to describe a column (formula, source function,
 * inputs/outputs, units), reused everywhere that column appears instead of
 * duplicating explanations per table.
 */

export interface ColumnInfo {
  label: string
  description: string
  /** LaTeX (KaTeX BlockMath), one entry per line/case. Omit for non-formula columns. */
  equations?: string[]
  /** File::function where this value is actually computed. */
  source: string
  units?: string
}

export type ColumnInfoKey =
  | 'busId'
  | 'meterKind'
  | 'quantity'
  | 'zTrue'
  | 'sigma'
  | 'sigmaPct'
  | 'zNoisy'
  | 'zHat'
  | 'residual'
  | 'residualNormalized'

export const COLUMN_INFO: Record<ColumnInfoKey, ColumnInfo> = {
  busId: {
    label: 'Location',
    description:
      'The bus or line this meter is attached to. Bus meters (topology.measurements) read a quantity local to ' +
      'one bus — injection P/Q, |V|, θ for PMU. Line meters (topology.line_measurements, opt-in — click a line ' +
      'in the Topology diagram) read the branch flow P_ij/Q_ij at the line\'s "from" terminal instead. A row has ' +
      'exactly one of busId/lineId set.',
    source:
      'app/backend/services/measurement_kinds.py::default_measurements, MeasurementInput/LineMeasurementInput ' +
      'in powerflow.py',
  },
  meterKind: {
    label: 'Meter',
    description:
      'Configured per bus or line on the Topology tab\'s diagram (topology.measurements[].kind / ' +
      'topology.line_measurements[].kind). Each kind is a preset — label, which quantities it reads (bus only; ' +
      'line meters always read P_ij/Q_ij regardless of kind), and a sigma multiplier — not real datasheet values, ' +
      'just plausible relative proportions: PMU most precise, SCADA the baseline, AMI noisier (a billing meter, ' +
      'not a power-quality instrument), Pseudo the least certain (a historical load profile, not a physical meter ' +
      'at all).',
    source: 'app/backend/services/measurement_kinds.py::MEASUREMENT_KIND_SPECS',
  },
  quantity: {
    label: 'Quantity',
    description:
      'Which physical quantity this row reads. Bus meters: from the kind\'s has_voltage/has_angle flags — DC-WLS ' +
      'only ever uses P (the state is angles-only, so Q and |V| aren\'t part of the model at all); AC-GN-WLS uses ' +
      'the full subset — P, Q, |V| for every kind, plus θ but only for PMU (the only kind that measures angle ' +
      'directly). Line meters: always P_branch (DC) or P_branch + Q_branch (AC) — no has_voltage/has_angle ' +
      'gating, since a "line PMU" measures the same P_ij/Q_ij as any other kind, just with tighter σ (no extra ' +
      'state-linear quantity like a line has no voltage/angle of its own).',
    source:
      'app/backend/services/dc_measurement_model.py::configured_dc_rows (DC), ' +
      'build_configured_ac_measurements (AC)',
  },
  zTrue: {
    label: 'z_true',
    description:
      'Ground truth value of this quantity, read off a freshly solved power flow — never read from the topology\'s ' +
      'stored bus.angle, which is always flat-start (0°) regardless of what was last solved.',
    equations: ['z_{\\text{true}} = h(x_{\\text{true}})'],
    source:
      'app/backend/services/dc_measurement_model.py::solve_ac_ground_truth (AC: Newton-Raphson, Iwamoto fallback) ' +
      'or pandapower.rundcpp (DC)',
    units: 'pu for P/Q/|V| · degrees for θ',
  },
  sigma: {
    label: 'σ',
    description:
      'The noise MODEL for this meter — how much it is expected to be off by. This is a deterministic function of ' +
      '(meter kind, |z_true|, noise level), never a random draw, and never signed. A p_sigma_mult of 3.0 for AMI ' +
      'just means "3× as uncertain as SCADA at the same noise_level" — it is not calibrated to a real datasheet. ' +
      'σ_min is an absolute noise floor: without it, a measurement with z_true≈0 would get σ≈0, meaning the WLS ' +
      'would treat it as almost perfectly known — unrealistic (no real meter has zero absolute noise) and ' +
      'numerically dangerous (the 1/σ² weight would explode).',
    equations: [
      '\\sigma_{P,Q} = \\max(\\sigma_{\\min},\\ |z_{\\text{true}}| \\cdot \\text{noise\\_level} \\cdot \\text{mult})',
      '\\sigma_{|V|} = \\max(\\sigma_{\\min},\\ \\text{noise\\_level} \\cdot \\text{mult})',
      '\\sigma_{\\theta}^{\\text{PMU}} = \\max(0.02^{\\circ},\\ \\text{noise\\_level} \\cdot 2.0)',
    ],
    source: 'app/backend/services/measurement_kinds.py::p_sigma, v_sigma, va_sigma_deg',
    units: 'pu for P/Q/|V| · degrees for θ',
  },
  sigmaPct: {
    label: 'σ (%)',
    description:
      'σ expressed as a percentage of |z_true| — how uncertain this meter is, relative to what it\'s reading. Not ' +
      'the realized error (see the noise histogram below for that) — a deterministic ratio, always ≥0, undefined ' +
      '(shown as —) when |z_true| is too close to zero for the ratio to mean anything.',
    equations: ['\\sigma_{\\%} = \\dfrac{\\sigma}{|z_{\\text{true}}|} \\times 100'],
    source: 'app/backend/routes/estimation.py::preview_measurements',
    units: '%',
  },
  zNoisy: {
    label: 'z_noisy / Noisy sample',
    description:
      'One realized random draw — z_true plus Gaussian noise at the σ above. With a seed set, this uses the exact ' +
      'same rng call shape (seed + full sigma array, same row order) that an actual Run would use, so what\'s shown ' +
      'here is bit-for-bit what Run will feed the solver.',
    equations: ['z_{\\text{noisy}} = z_{\\text{true}} + e,\\quad e \\sim \\mathcal{N}(0,\\sigma)'],
    source: 'numpy.random.default_rng(seed).normal(0, sigma)',
    units: 'pu for P/Q/|V| · degrees for θ',
  },
  zHat: {
    label: 'z_hat',
    description:
      'The estimator\'s own prediction, evaluated at the converged/final state estimate — not the ground truth. ' +
      'This is what the WLS solver believes this measurement should read, given everything it has settled on.',
    equations: ['\\hat z = h(\\hat x)\\quad(\\text{DC: } \\hat z = H\\hat\\theta + c)'],
    source: 'src/tese_dsse/estimacao_estado/dc_linear.py::solve_dc_pure, gauss_newton_wls.py::solve_wls_gauss_newton',
    units: 'pu for P/Q/|V| · degrees for θ',
  },
  residual: {
    label: 'r',
    description: 'The WLS fit error — how far the noisy measurement actually fed to the solver ended up from what the converged estimate predicts for it.',
    equations: ['r = z_{\\text{noisy}} - \\hat z'],
    source: 'src/tese_dsse/estimacao_estado/dc_linear.py::solve_dc_pure (residual field)',
    units: 'pu for P/Q/|V| · degrees for θ',
  },
  residualNormalized: {
    label: '|r_N|',
    description:
      'r divided by σ — flagged past the dashed line at 3 (Handschin et al. 1975\'s classic rule of thumb for a ' +
      'single gross error). This is the simple normalization, dividing straight by the assigned σ — not the ' +
      'rigorous hat-matrix-corrected version (r / (σ·√(1−K_ii))) that the Bad Data tab\'s LNR test uses, which ' +
      'accounts for how much of a true error the WLS itself can absorb into the fit (masking, Bretas et al. 2013). ' +
      'A high-leverage measurement can look artificially "clean" here even when it wouldn\'t under the Bad Data ' +
      'tab\'s stricter test.',
    equations: ['r_N = \\dfrac{r}{\\sigma}'],
    source: 'src/tese_dsse/estimacao_estado/dc_linear.py::solve_dc_pure (residual_over_sigma field)',
    units: 'dimensionless',
  },
}
