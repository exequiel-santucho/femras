"""Generic Newton-Raphson step with line search.

Unifies ``solve_step_newton`` (viga) and ``solve_one_step`` (presa). It supports
both control types through the same residual ``R = Fint - Fext``:

* displacement control -> ``Fext = 0`` and non-zero prescribed DOFs;
* load control (e.g. water level) -> prescribed DOFs are the supports and
  ``Fext`` is the external (hydraulic + body) force of the current level.

The state is carried as :class:`~femras.damage.GPState` arrays, so accepting or
rejecting a step is a cheap array copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .assembly import Assembler
from .backend import linsolve, resolve_backend
from .damage import ConstitutiveModel, GPState


@dataclass
class SolverOptions:
    tangent_mode: str = "numerical_hybrid"
    max_iter: int = 60
    tol_res_abs: float = 1.0e-4
    tol_res_rel: float = 1.0e-5
    tol_du: float = 1.0e-8
    line_search_alphas: tuple = (1.0, 0.5, 0.25, 0.10, 0.05, 0.025, 0.01, 0.005)
    line_search_max_worsening: float = 5.0
    use_line_search: bool = True
    backend: str = "auto"


@dataclass
class StepResult:
    U: np.ndarray
    Fint: np.ndarray
    state: GPState
    iters: int
    converged: bool
    norm_R: float
    rel_R: float


def get_free_prescribed(n_dof, prescribed):
    pd = np.array(sorted(prescribed.keys()), dtype=int)
    pv = np.array([prescribed[d] for d in pd], dtype=float)
    free = np.setdiff1d(np.arange(n_dof), pd)
    return free, pd, pv


def solve_step_newton(assembler: Assembler, model: ConstitutiveModel,
                      old_state: GPState, U_start: np.ndarray, prescribed: dict,
                      options: SolverOptions, fext: np.ndarray | None = None) -> StepResult:
    n_dof = assembler.n_dof
    free, pd, pv = get_free_prescribed(n_dof, prescribed)
    if fext is None:
        fext = np.zeros(n_dof)

    U = U_start.copy()
    U[pd] = pv
    converged = False
    accepted_state = old_state.copy()
    backend = resolve_backend(options.backend, free.size)
    assembler.backend = backend
    norm0 = None
    norm_R = rel_R = np.inf
    Fint = np.zeros(n_dof)
    it = 0

    for it in range(1, options.max_iter + 1):
        Kt, Fint, _d, trial_state = assembler.tangent_and_force(
            U, model, old_state, options.tangent_mode)
        R = Fint - fext
        R_free = R[free]
        norm_R = np.linalg.norm(R_free)
        if norm0 is None:
            norm0 = max(norm_R, 1.0)
        rel_R = norm_R / norm0

        if norm_R < options.tol_res_abs or rel_R < options.tol_res_rel:
            converged = True
            accepted_state = trial_state
            break

        Kff = Kt[free, :][:, free]
        try:
            du = linsolve(Kff, -R_free, backend)
        except Exception:
            return StepResult(U, Fint, trial_state, it, False, norm_R, rel_R)

        norm_du = np.linalg.norm(du)
        norm_U = max(np.linalg.norm(U[free]), 1.0)
        if norm_du / norm_U < options.tol_du and rel_R < 1.0e-4:
            converged = True
            accepted_state = trial_state
            break

        if options.use_line_search:
            best = _line_search(assembler, model, old_state, U, free, pd, pv, du,
                                fext, options, norm_R)
            if best is None:
                return StepResult(U, Fint, trial_state, it, False, norm_R, rel_R)
            U, accepted_state, Fint = best
        else:
            U[free] += du
            U[pd] = pv
            accepted_state = trial_state

    # final equilibrium check
    Kt, Fint, _d, accepted_state = assembler.tangent_and_force(
        U, model, old_state, options.tangent_mode)
    R_free = (Fint - fext)[free]
    norm_R = np.linalg.norm(R_free)
    rel_R = norm_R / max(norm0 or 1.0, 1.0)
    if norm_R < options.tol_res_abs or rel_R < options.tol_res_rel:
        converged = True
    return StepResult(U, Fint, accepted_state, it, converged, norm_R, rel_R)


def _line_search(assembler, model, old_state, U, free, pd, pv, du, fext, options, norm_R):
    best_U = best_state = best_Fint = None
    best_norm = np.inf
    for alpha in options.line_search_alphas:
        Uc = U.copy()
        Uc[free] += alpha * du
        Uc[pd] = pv
        Fint_c, _d, state_c = assembler.internal_force(Uc, model, old_state)
        norm_c = np.linalg.norm((Fint_c - fext)[free])
        if norm_c < best_norm:
            best_norm, best_U, best_state, best_Fint = norm_c, Uc, state_c, Fint_c
    if best_U is None or best_norm > options.line_search_max_worsening * norm_R:
        return None
    return best_U, best_state, best_Fint
