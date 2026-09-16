"""Solver generico WLS por Gauss-Newton.

Este modulo e propositalmente pequeno: ele implementa o nucleo numerico que
depois sera conectado as funcoes de medicao eletrica h(x) e H(x) vindas do
Ybus de uma rede pandapower ou OpenDSS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..auditoria import AuditTrail, resolve_audit

ArrayFunc = Callable[[np.ndarray], np.ndarray]


@dataclass(frozen=True)
class WLSIteration:
    """Registro de uma iteracao do metodo WLS/Gauss-Newton."""

    iteration: int
    x: np.ndarray
    h_x: np.ndarray
    residual: np.ndarray
    jacobian: np.ndarray
    gain: np.ndarray
    rhs: np.ndarray
    delta_x: np.ndarray
    objective: float
    step_norm_inf: float
    used_lstsq: bool


@dataclass(frozen=True)
class WLSResult:
    """Resultado final de um problema WLS."""

    x: np.ndarray
    converged: bool
    iterations: list[WLSIteration]
    objective: float


def solve_wls_gauss_newton(
    z: np.ndarray,
    sigma: np.ndarray,
    h: ArrayFunc,
    jacobian: ArrayFunc,
    x0: np.ndarray,
    *,
    max_iter: int = 20,
    tol: float = 1e-8,
    verbose: bool = False,
    audit: AuditTrail | None = None,
) -> WLSResult:
    """Resolve um problema WLS nao linear por Gauss-Newton.

    O problema resolvido e um snapshot estatico:

        z = h(x_true) + e
        e ~ N(0, R)
        R = diag(sigma^2)
        W = R^-1 = diag(1 / sigma^2)

        min_x (z - h(x))^T W (z - h(x))

    Se houver muitos timestamps no dataset, esta funcao deve ser chamada uma
    vez por timestamp/snapshot. Ela nao implementa dinamica temporal.

    Esta funcao e generica: ela nao sabe o que e uma barra eletrica, uma linha,
    um transformador ou um medidor SCADA. Ela so precisa receber a funcao de
    medicao `h(x)` e sua Jacobiana `H(x)`. Para virar um estimador eletrico AC,
    outra camada deve montar `h` e `jacobian` a partir de `Ybus`, da tabela de
    medicoes e da convencao do vetor de estados.

    Parameters
    ----------
    z:
        Vetor de medicoes reais. Exemplo em PSSE: tensoes, injecoes de potencia,
        fluxos de linha, correntes e pseudo-medicoes.
    sigma:
        Desvios padrao das medicoes, no mesmo ordenamento de `z`. Cada valor
        precisa ser positivo.
    h:
        Funcao de medicao nao linear. Recebe `x` e retorna o vetor de medicoes
        previstas `h(x)`, no mesmo tamanho e ordem de `z`.
    jacobian:
        Funcao que retorna `H(x) = dh/dx`. O formato deve ser
        `(numero_de_medicoes, numero_de_estados)`.
    x0:
        Chute inicial do vetor de estados. Em PSSE, normalmente e um flat start
        ou um resultado de fluxo de potencia anterior.
    max_iter:
        Numero maximo de iteracoes.
    tol:
        Criterio de parada em norma infinito de delta_x.
    verbose:
        Se ``True``, imprime e registra passo a passo cada iteracao (residuo,
        Jacobiana, matriz de ganho G = HᵀWH, lado direito, delta_x, objetivo e
        norma do passo) para auditoria. Mantem as celulas de notebook limpas.
    audit:
        Trilha ``AuditTrail`` existente para encadear esta funcao em uma
        auditoria maior. Quando fornecida, ``verbose`` e ignorado.

    Returns
    -------
    WLSResult
        Contem o estado final `x`, flag de convergencia, historico das iteracoes
        e valor final da funcao objetivo.

    Raises
    ------
    ValueError
        Se dimensoes de `z`, `sigma`, `h(x)` ou `H(x)` forem inconsistentes.

    Example
    -------
    >>> z = np.array([-0.48, -0.50])
    >>> sigma = np.array([0.02, 0.05])
    >>> h = lambda x: np.array([np.sin(x[0]), x[0]])
    >>> H = lambda x: np.array([[np.cos(x[0])], [1.0]])
    >>> result = solve_wls_gauss_newton(z, sigma, h, H, np.array([0.0]))
    >>> result.converged
    True
    """

    audit = resolve_audit(audit, verbose, title="WLS Gauss-Newton")

    z = np.asarray(z, dtype=float).reshape(-1)
    sigma = np.asarray(sigma, dtype=float).reshape(-1)
    x = np.asarray(x0, dtype=float).reshape(-1)

    if z.shape != sigma.shape:
        raise ValueError("z e sigma devem ter o mesmo tamanho.")
    if np.any(sigma <= 0.0):
        raise ValueError("Todos os desvios padrao em sigma devem ser positivos.")

    # `sigma` guarda desvios-padrao; a covariancia conceitual e
    # R = diag(sigma^2), logo a matriz de pesos WLS e R^-1.
    weight = np.diag(1.0 / np.square(sigma))
    audit.step("z (medicoes)", z, formula="z")
    audit.step("sigma (desvios)", sigma, formula="sigma")
    audit.step("W = diag(1/sigma^2)", weight, formula="W = R^-1")
    audit.step("x0 (estado inicial)", x, formula="x0")
    iterations: list[WLSIteration] = []
    converged = False

    for iteration in range(max_iter):
        with audit.section(f"iteracao {iteration}"):
            h_x = np.asarray(h(x), dtype=float).reshape(-1)
            residual = z - h_x
            h_matrix = np.asarray(jacobian(x), dtype=float)

            if h_x.shape != z.shape:
                raise ValueError("h(x) deve retornar vetor com o mesmo tamanho de z.")
            if h_matrix.shape != (z.size, x.size):
                raise ValueError("A Jacobiana deve ter formato (len(z), len(x)).")

            audit.step("h(x) (medicoes previstas)", h_x, formula="h(x)")
            audit.step("r = z - h(x) (residuo)", residual, formula="r = z - h(x)")
            audit.step("H = dh/dx (Jacobiana)", h_matrix, formula="H(x)")

            # Linearizacao de Taylor:
            # h(x + dx) ~= h(x) + H dx
            # (H^T W H) dx = H^T W (z - h(x))
            gain = h_matrix.T @ weight @ h_matrix
            rhs = h_matrix.T @ weight @ residual
            audit.step("G = HᵀWH (matriz de ganho)", gain, formula="G = HᵀWH")
            audit.step("b = HᵀWr (lado direito)", rhs, formula="b = HᵀWr")
            used_lstsq = False

            try:
                delta_x = np.linalg.solve(gain, rhs)
            except np.linalg.LinAlgError:
                delta_x = np.linalg.lstsq(gain, rhs, rcond=None)[0]
                used_lstsq = True
                audit.note("G singular: usando minimos quadrados (lstsq).")

            objective = float(residual.T @ weight @ residual)
            # ||delta_x||_inf = max_i |delta_x[i]|: maior passo individual entre
            # as componentes do estado. Se < tol, considera-se convergido.
            step_norm_inf = float(np.linalg.norm(delta_x, ord=np.inf))

            audit.step("delta_x (passo de Newton)", delta_x, formula="G delta_x = b")
            audit.step("J = rᵀWr (objetivo)", objective, formula="J(x)")
            audit.step("||delta_x||_inf", step_norm_inf, formula="max_i |delta_x[i]|")

            iterations.append(
                WLSIteration(
                    iteration=iteration,
                    x=x.copy(),
                    h_x=h_x.copy(),
                    residual=residual.copy(),
                    jacobian=h_matrix.copy(),
                    gain=gain.copy(),
                    rhs=rhs.copy(),
                    delta_x=delta_x.copy(),
                    objective=objective,
                    step_norm_inf=step_norm_inf,
                    used_lstsq=used_lstsq,
                )
            )

            x = x + delta_x
            audit.step("x <- x + delta_x (estado atualizado)", x, formula="x + delta_x")
            if step_norm_inf < tol:
                converged = True
                audit.note(
                    f"Convergiu: ||delta_x||_inf = {step_norm_inf:.2e} < tol = {tol:.2e}"
                )
                break

    final_residual = z - np.asarray(h(x), dtype=float).reshape(-1)
    final_objective = float(final_residual.T @ weight @ final_residual)
    audit.step("x_final (estado estimado)", x, formula="x*")
    audit.step("J_final = rᵀWr", final_objective, formula="J(x*)")
    audit.note(f"convergiu={converged} em {len(iterations)} iteracoes")
    return WLSResult(
        x=x,
        converged=converged,
        iterations=iterations,
        objective=final_objective,
    )
