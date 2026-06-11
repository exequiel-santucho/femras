"""High-level incremental drivers (adaptive stepping).

``run_displacement_control`` reproduces the beam test (impose a vertical
displacement on a top patch, recover the equivalent load from the reaction).
``run_load_control`` reproduces the dam overtopping (scale an external force,
e.g. the hydraulic load, by a control level).

Both wrap :func:`rasfem.solver.solve_step_newton` and carry the GPState arrays.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .assembly import Assembler
from .damage import ConstitutiveModel, GPState
from .solver import SolverOptions, solve_step_newton


@dataclass
class SteppingOptions:
    target: float = -0.20
    step_initial: float = -0.0010
    step_min: float = -0.000010
    step_max: float = -0.0015
    grow_factor: float = 1.10
    shrink_factor: float = 0.5
    max_accepted_steps: int = 600
    iter_grow_below: int = 4
    iter_shrink_above: int = 15
    stop_if_damage_exceeds: bool = False
    damage_limit: float = 0.99999


@dataclass
class AnalysisResult:
    control: np.ndarray            # imposed control parameter per accepted step
    load: np.ndarray              # recovered load / reaction per step
    max_damage: np.ndarray
    U_final: np.ndarray
    state: GPState
    accepted: int
    rejected: int
    step_table: list = field(default_factory=list)


def _toward(current, step, target):
    """Clamp the next control value so it does not overshoot the target."""
    if (current + step - target) * np.sign(target - current) > 0:
        return target, target - current
    return current + step, step


def run_displacement_control(assembler: Assembler, model: ConstitutiveModel,
                             state0: GPState, U0: np.ndarray,
                             support_dofs: dict, load_dofs: list,
                             load_base: float, stepping: SteppingOptions,
                             solver_opts: SolverOptions, progress=None) -> AnalysisResult:
    state = state0.copy()
    U_current = U0.copy()
    U_final = U0.copy()
    control, load, dmax_hist, table = [], [], [], []
    accepted = rejected = 0
    delta = 0.0
    step = stepping.step_initial

    while abs(delta) < abs(stepping.target) and accepted < stepping.max_accepted_steps:
        delta_try, step_try = _toward(delta, step, stepping.target)
        prescribed = dict(support_dofs)
        for d in load_dofs:
            prescribed[d] = load_base + delta_try

        res = solve_step_newton(assembler, model, state, U_current, prescribed,
                                solver_opts)

        if not res.converged:
            rejected += 1
            table.append(dict(step=accepted + 1, attempt=rejected, control=delta_try,
                              load=0.0, dmax=None, iters=res.iters,
                              norm_R=res.norm_R, conv=False))
            new_step = step_try * stepping.shrink_factor
            if abs(new_step) < abs(stepping.step_min):
                break
            step = new_step
            continue

        state = res.state
        U_current = res.U.copy()
        U_final = res.U.copy()
        delta = delta_try
        accepted += 1

        R_load = sum(res.Fint[d] for d in load_dofs)
        P = -R_load
        dmax = float(_element_max_damage(state))
        control.append(delta)
        load.append(P)
        dmax_hist.append(dmax)
        table.append(dict(step=accepted, attempt=rejected, control=delta, load=P,
                          dmax=dmax, iters=res.iters, norm_R=res.norm_R, conv=True))
        if progress:
            progress(accepted, delta, P, dmax)

        if res.iters <= stepping.iter_grow_below:
            step = max(step * stepping.grow_factor, stepping.step_max) if step < 0 \
                else min(step * stepping.grow_factor, stepping.step_max)
        elif res.iters >= stepping.iter_shrink_above:
            step = step * stepping.shrink_factor
        if abs(step) < abs(stepping.step_min):
            step = stepping.step_min

        if stepping.stop_if_damage_exceeds and dmax >= stepping.damage_limit:
            break

    return AnalysisResult(np.array(control), np.array(load), np.array(dmax_hist),
                          U_final, state, accepted, rejected, table)


@dataclass
class LevelStepping:
    h_start: float = 92.0
    h_target: float = 120.0
    dh_initial: float = 0.50
    dh_min: float = 0.020
    dh_max: float = 0.50
    grow_factor: float = 1.20
    shrink_factor: float = 0.50
    max_accepted_steps: int = 600
    iter_grow_below: int = 5
    iter_shrink_above: int = 22


def run_load_control(assembler: Assembler, model: ConstitutiveModel,
                     state0: GPState, U0: np.ndarray, support_dofs: dict,
                     build_fext, output_fn, stepping: LevelStepping,
                     solver_opts: SolverOptions, progress=None) -> AnalysisResult:
    """Increment an external load parameter (e.g. water level) until failure.

    ``build_fext(level)`` returns the external force vector at a given control
    level; ``output_fn(U, Fint)`` returns the scalar recorded as ``load`` (e.g.
    crest displacement). Under load control the solver cannot pass the peak, so
    the last converged level is the failure/overtopping level.
    """
    state = state0.copy()
    U_current = U0.copy()
    U_final = U0.copy()
    control, load, dmax_hist, table = [], [], [], []
    accepted = rejected = 0
    level = stepping.h_start
    dh = stepping.dh_initial
    reached = False

    while not reached and accepted < stepping.max_accepted_steps:
        level_try = level + dh
        if level_try >= stepping.h_target:
            level_try = stepping.h_target
            reached_try = True
        else:
            reached_try = False

        fext = build_fext(level_try)
        res = solve_step_newton(assembler, model, state, U_current,
                                dict(support_dofs), solver_opts, fext=fext)

        if not res.converged:
            rejected += 1
            table.append(dict(step=accepted + 1, attempt=rejected, control=level_try,
                              load=0.0, dmax=None, iters=res.iters,
                              norm_R=res.norm_R, conv=False))
            dh *= stepping.shrink_factor
            if dh < stepping.dh_min:
                break
            continue

        state = res.state
        U_current = res.U.copy()
        U_final = res.U.copy()
        level = level_try
        accepted += 1
        reached = reached_try

        out = float(output_fn(res.U, res.Fint))
        dmax = float(_element_max_damage(state))
        control.append(level)
        load.append(out)
        dmax_hist.append(dmax)
        table.append(dict(step=accepted, attempt=rejected, control=level, load=out,
                          dmax=dmax, iters=res.iters, norm_R=res.norm_R, conv=True))
        if progress:
            progress(accepted, level, out, dmax)

        if res.iters <= stepping.iter_grow_below:
            dh = min(dh * stepping.grow_factor, stepping.dh_max)
        elif res.iters >= stepping.iter_shrink_above:
            dh = max(dh * stepping.shrink_factor, stepping.dh_min)

    return AnalysisResult(np.array(control), np.array(load), np.array(dmax_hist),
                          U_final, state, accepted, rejected, table)


def _element_max_damage(state: GPState) -> float:
    if state.damage_t.size == 0:
        return 0.0
    d = 1.0 - (1.0 - state.damage_t) * (1.0 - state.damage_c)
    return float(d.max())
