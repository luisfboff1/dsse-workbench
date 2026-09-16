"""Modelos de dados para o trace de execução dos algoritmos de estimação.

Usado por routes/estimation.py para capturar estados intermediários (matrizes,
vetores, escalares) a cada etapa do DC-WLS e do AC Gauss-Newton WLS, retornando
um ExecutionTrace junto com o resultado normal quando trace=True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# Matrizes com mais de MAX_MATRIX_ELEMENTS elementos são truncadas a 20×20.
MAX_MATRIX_ELEMENTS = 625  # 25×25 cobre IEEE 14-bus inteiro


@dataclass
class TraceVariable:
    name: str          # ex: "H", "x_k", "J"
    label: str         # nome legível
    value: Any         # numpy array, float, int, str, list…
    description: str = ""

    def to_dict(self) -> dict:
        v = self.value

        if isinstance(v, np.ndarray):
            if v.ndim == 2:
                rows, cols = v.shape
                truncated = rows * cols > MAX_MATRIX_ELEMENTS
                data = v.tolist()
                if truncated:
                    data = [row[:20] for row in data[:20]]
                return {
                    "name": self.name,
                    "label": self.label,
                    "type": "matrix",
                    "shape": [rows, cols],
                    "data": data,
                    "truncated": truncated,
                    "description": self.description,
                }
            else:  # 1-D vector
                return {
                    "name": self.name,
                    "label": self.label,
                    "type": "vector",
                    "shape": [int(v.shape[0])],
                    "data": v.tolist(),
                    "description": self.description,
                }

        # scalar / string / bool
        scalar_val: Any
        if isinstance(v, (np.floating, np.complexfloating)):
            scalar_val = float(np.real(v))
        elif isinstance(v, np.integer):
            scalar_val = int(v)
        elif isinstance(v, bool):
            scalar_val = v
        else:
            scalar_val = v

        return {
            "name": self.name,
            "label": self.label,
            "type": "scalar",
            "value": scalar_val,
            "description": self.description,
        }


@dataclass
class TraceStep:
    name: str
    category: str          # "setup" | "iteration" | "result" | "convergence"
    elapsed_ms: float = 0.0
    variables: list[TraceVariable] = field(default_factory=list)
    log: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "variables": [v.to_dict() for v in self.variables],
            "log": self.log,
        }


@dataclass
class ExecutionTrace:
    algorithm: str       # "dc-wls" | "ac-gn-wls"
    total_ms: float = 0.0
    converged: bool = True
    steps: list[TraceStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "algorithm": self.algorithm,
            "total_ms": round(self.total_ms, 2),
            "converged": self.converged,
            "steps": [s.to_dict() for s in self.steps],
        }


# ─── Builders de trace para cada algoritmo ────────────────────────────────────

def build_dc_wls_trace(
    *,
    H_final: np.ndarray,
    c_final: np.ndarray,
    sigma_final: np.ndarray,
    z_true_final: np.ndarray,
    z_noisy: np.ndarray,
    labels_final: list[str],
    result: dict,          # dict retornado por solve_dc_pure
    dof: int,
    chi2_threshold: float | None,
    elapsed_ms: float,
) -> ExecutionTrace:
    """Constrói o ExecutionTrace para o DC-WLS (one-shot, 4 etapas fixas)."""

    m, n = H_final.shape
    W_diag = 1.0 / np.square(sigma_final)  # diagonal de W, mais compacto que m×m

    step1 = TraceStep(
        name="Build DC model",
        category="setup",
        variables=[
            TraceVariable("H", "Jacobian H", H_final,
                          description="Measurement matrix — maps angles θ to measurements z = Hθ + c"),
            TraceVariable("c", "Affine offset c", c_final,
                          description="Constant offset (base angles/injections from DC power flow)"),
            TraceVariable("W_diag", "Weight diagonal diag(W)", W_diag,
                          description="W = diag(1/σ²) — precision of each measurement"),
            TraceVariable("m", "Measurements m", int(m), description="Number of measurements"),
            TraceVariable("n", "Unknowns n", int(n), description="Number of state variables (angles)"),
        ],
    )

    step2 = TraceStep(
        name="Inject noise",
        category="setup",
        variables=[
            TraceVariable("z_true", "True measurements z_true", z_true_final,
                          description="z_true = Hθ_true + c (noiseless)"),
            TraceVariable("z_noisy", "Noisy measurements z", z_noisy,
                          description="z = z_true + ε,  ε ~ N(0, σ²)"),
            TraceVariable("sigma", "Uncertainties σ", sigma_final,
                          description="Standard deviation per measurement (depends on meter class)"),
        ],
        log=f"Labels: {', '.join(labels_final)}",
    )

    theta_hat = np.asarray(result["theta_hat"])
    z_hat = np.asarray(result["z_hat"])
    residual = np.asarray(result["residual"])
    J = float(result["J"])
    G = H_final.T @ np.diag(W_diag) @ H_final

    step3 = TraceStep(
        name="Solve WLS",
        category="result",
        variables=[
            TraceVariable("G", "Gain matrix G = HᵀWH", G,
                          description="Normal equations matrix — solve Gθ̂ = HᵀW(z-c)"),
            TraceVariable("theta_hat", "Estimated angles θ̂ (rad)", theta_hat,
                          description="Solution of the WLS problem"),
            TraceVariable("z_hat", "Predicted measurements ẑ = Hθ̂ + c", z_hat,
                          description="Reconstructed measurements from state estimate"),
            TraceVariable("r", "Residuals r = z − ẑ", residual,
                          description="Difference between noisy measurements and predicted"),
            TraceVariable("J", "Objective J = rᵀWr", J,
                          description="Weighted sum of squared residuals (chi-squared statistic)"),
        ],
    )

    passed = chi2_threshold is not None and J <= chi2_threshold
    step4 = TraceStep(
        name="Chi-squared test",
        category="result",
        variables=[
            TraceVariable("J", "Chi-squared statistic J", J,
                          description="rᵀWr — follows χ²(dof) under H₀ (no bad data)"),
            TraceVariable("threshold", "Chi-squared threshold χ²(0.05, dof)", chi2_threshold,
                          description="chi2.ppf(0.95, dof) — reject if J > threshold"),
            TraceVariable("dof", "Degrees of freedom dof = m − n", int(dof),
                          description="m measurements minus n unknowns"),
            TraceVariable("passed", "Test passed", passed,
                          description="True if J ≤ threshold (no bad data detected at 95% confidence)"),
        ],
        log="PASSED ✓" if passed else "FAILED — possible bad data detected",
    )

    return ExecutionTrace(
        algorithm="dc-wls",
        total_ms=elapsed_ms,
        converged=True,
        steps=[step1, step2, step3, step4],
    )


def build_ac_gn_wls_trace(
    *,
    result: Any,           # WLSResult from gauss_newton_wls.py
    model: Any,            # ACYbusModel (has .num_states, .flat_start())
    z_true: np.ndarray,
    z_noisy: np.ndarray,
    sigma: np.ndarray,
    dof: int,
    chi2_threshold: float | None,
    elapsed_ms: float,
) -> ExecutionTrace:
    """Constrói o ExecutionTrace para o AC Gauss-Newton WLS (iterativo)."""

    n_states = model.num_states
    m_meas = len(z_true)
    x0 = model.flat_start()

    step_setup_z = TraceStep(
        name="Build AC model",
        category="setup",
        variables=[
            TraceVariable("n_states", "State dimension n", int(n_states),
                          description="(n_buses − 1) angles + n_buses voltage magnitudes"),
            TraceVariable("m_meas", "Measurements m", int(m_meas),
                          description="Total configured measurements"),
            TraceVariable("z_true", "True measurements z_true", z_true,
                          description="Ground truth from AC power flow solve"),
            TraceVariable("z_noisy", "Noisy measurements z", z_noisy,
                          description="z = z_true + ε,  ε ~ N(0, σ²)"),
            TraceVariable("sigma", "Uncertainties σ", sigma,
                          description="Standard deviation per measurement"),
        ],
    )

    step_flat = TraceStep(
        name="Flat start x0",
        category="setup",
        variables=[
            TraceVariable("x0", "Initial state x₀", x0,
                          description="Flat start: angles = 0 rad, voltages = 1 pu"),
        ],
        log=f"x0 shape: {x0.shape[0]} (angles: {n_states - (n_states + 1) // 2}, voltages: {(n_states + 1) // 2})",
    )

    # Índices de iterações para as quais capturamos jacobiano e gain
    # (vetores/escalares em todas; matrizes só em algumas para economizar payload)
    n_iters = len(result.iterations)
    heavy_indices = set()
    if n_iters > 0:
        heavy_indices.add(0)
        heavy_indices.add(n_iters - 1)
        if n_iters > 2:
            heavy_indices.add(n_iters // 2)

    iteration_steps = []
    for it in result.iterations:
        k = it.iteration
        include_heavy = k in heavy_indices
        vars_ = [
            TraceVariable("x_k", f"State x_k (iter {k})", np.asarray(it.x),
                          description="Current state estimate θ (rad) + |V| (pu)"),
            TraceVariable("r_k", f"Residuals r_k (iter {k})", np.asarray(it.residual),
                          description="z − h(x_k)"),
            TraceVariable("J_k", f"Objective J (iter {k})", float(it.objective),
                          description="rᵀWr at current iterate"),
            TraceVariable("delta_x", f"Correction Δx (iter {k})", np.asarray(it.delta_x),
                          description="Newton step — (HᵀWH)Δx = HᵀWr"),
            TraceVariable("step_norm", f"‖Δx‖∞ (iter {k})", float(it.step_norm_inf),
                          description="Convergence criterion — stop when < tol"),
        ]
        if include_heavy:
            vars_.insert(2, TraceVariable(
                "H_k", f"Jacobian H (iter {k})", np.asarray(it.jacobian),
                description="∂h/∂x evaluated at x_k",
            ))
            vars_.insert(3, TraceVariable(
                "G_k", f"Gain matrix G = HᵀWH (iter {k})", np.asarray(it.gain),
                description="Normal equations matrix at x_k",
            ))
        iteration_steps.append(TraceStep(
            name=f"GN Iteration {k + 1}",
            category="iteration",
            variables=vars_,
            log=f"‖Δx‖∞ = {it.step_norm_inf:.2e}  |  J = {it.objective:.4f}",
        ))

    x_final = np.asarray(result.x)
    J_final = float(result.objective)
    step_conv = TraceStep(
        name="Convergence",
        category="convergence",
        variables=[
            TraceVariable("x_final", "Final state x̂", x_final,
                          description="Converged state estimate"),
            TraceVariable("iterations", "Iterations", int(n_iters)),
            TraceVariable("J_final", "Final objective J", J_final,
                          description="rᵀWr at convergence"),
            TraceVariable("converged", "Converged", bool(result.converged)),
        ],
        log="Converged ✓" if result.converged else "Max iterations reached (not converged)",
    )

    passed = chi2_threshold is not None and J_final <= chi2_threshold
    step_chi2 = TraceStep(
        name="Chi-squared test",
        category="result",
        variables=[
            TraceVariable("J", "Chi-squared statistic J", J_final,
                          description="rᵀWr — follows χ²(dof) under H₀"),
            TraceVariable("threshold", "Threshold χ²(0.05, dof)", chi2_threshold,
                          description="chi2.ppf(0.95, dof)"),
            TraceVariable("dof", "Degrees of freedom dof = m − n", int(dof)),
            TraceVariable("passed", "Test passed", passed,
                          description="True if J ≤ threshold"),
        ],
        log="PASSED ✓" if passed else "FAILED — possible bad data detected",
    )

    return ExecutionTrace(
        algorithm="ac-gn-wls",
        total_ms=elapsed_ms,
        converged=bool(result.converged),
        steps=[step_setup_z, step_flat, *iteration_steps, step_conv, step_chi2],
    )
