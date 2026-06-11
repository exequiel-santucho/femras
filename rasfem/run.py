"""Orchestrator: turn a validated :class:`~rasfem.config.Config` into a run.

Currently wires the displacement-controlled beam end to end. The hydraulic
(load-controlled dam) path is added together with the polygon mesh and ASR
service stage.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .analysis import SteppingOptions, run_displacement_control
from .assembly import Assembler
from .config import Config
from .damage import GPState
from .elements.base import precompute
from .mesh.structured import notched_beam_mesh, nearest_node, top_load_patch_nodes
from .stages import free_expansion_displacement, make_constitutive


def run_config(cfg: Config, out_dir: str | Path | None = None, progress=None) -> dict:
    if cfg.loading.mode == "displacement":
        return _run_beam(cfg, out_dir, progress)
    if cfg.loading.mode == "hydraulic":
        return _run_dam(cfg, out_dir, progress)
    raise NotImplementedError(f"loading mode '{cfg.loading.mode}' not supported")


def _run_beam(cfg: Config, out_dir, progress) -> dict:
    from . import postprocess as pp

    geo = cfg.geometry
    if geo.kind != "beam":
        raise ValueError("displacement loading currently expects a beam geometry")

    material = cfg.material_model()
    ras = cfg.ras_model()
    pt = cfg.problem.problem_type

    nodes, elements, removed = notched_beam_mesh(
        geo.L, geo.H, geo.nx, geo.ny, geo.notch_width, geo.notch_height)
    elem = precompute(nodes, elements, cfg.problem.element_type, cfg.problem.thickness)
    assembler = Assembler(elem)

    xL = (geo.L - geo.support_span) / 2.0
    sl = nearest_node(nodes, xL, 0.0)
    sr = nearest_node(nodes, geo.L - xL, 0.0)

    ld = cfg.loading
    load_nodes = top_load_patch_nodes(nodes, ld.x_center, ld.y_top, ld.patch)

    xi = ras.xi_at()
    model = make_constitutive(material, ras, xi, elem.h_e, pt,
                              strain_shear_factor=cfg.problem.strain_shear_factor,
                              min_stiff_factor=cfg.solver.min_stiff_factor)

    eps_ras0 = float(ras.eps_ras_lin(xi))
    U0 = free_expansion_displacement(nodes, eps_ras0, x_ref=nodes[sl, 0], y_ref=0.0)
    load_base = eps_ras0 * geo.H

    support_dofs = {2 * sl: 0.0, 2 * sl + 1: 0.0, 2 * sr + 1: 0.0}
    load_dofs = [2 * n + 1 for n in load_nodes]

    stepping = SteppingOptions(
        target=ld.target, step_initial=ld.step_initial, step_min=ld.step_min,
        step_max=ld.step_max, grow_factor=ld.grow_factor,
        shrink_factor=ld.shrink_factor, max_accepted_steps=ld.max_accepted_steps)
    state0 = GPState.zeros(elements.shape[0], elem.n_gp)

    result = run_displacement_control(
        assembler, model, state0, U0, support_dofs, load_dofs, load_base,
        stepping, cfg.solver_options(), progress=progress)

    out = Path(out_dir or cfg.output.dir) / cfg.name
    summary = pp.save_summary(out, cfg, result,
                              extra={"xi": xi, "eps_ras_lin": eps_ras0,
                                     "n_nodes": int(nodes.shape[0]),
                                     "n_elements": int(elements.shape[0])})
    if cfg.output.save_tables:
        pp.save_tables(out, result, "delta_mm", "P_N")
    if cfg.output.save_figures:
        pp.save_figures(out, nodes, elements, result, assembler, model,
                        dpi=cfg.output.dpi,
                        control_label="|delta| [mm]", load_label="P [N]")
    return {"result": result, "summary": summary, "out_dir": str(out),
            "nodes": nodes, "elements": elements}


def _xi_uniform(t_days, total_days, xi_target, rate):
    """Uniform xi growing from 0 to xi_target over total_days (legacy presa_ras.py)."""
    s = np.clip(t_days / max(total_days, 1.0), 0.0, 1.0)
    a = max(rate, 1.0e-6)
    return xi_target * (1.0 - np.exp(-a * s)) / (1.0 - np.exp(-a))


def _water_level_annual(t_days, h_max, h_min):
    """Annual sinusoidal water level cycle (cosine: max at t=0, min at mid-year)."""
    h_mean = 0.5 * (h_max + h_min)
    h_amp = 0.5 * (h_max - h_min)
    t_year = t_days % 365.0
    return h_mean + h_amp * np.cos(2.0 * np.pi * t_year / 365.0)


def _run_service_stage(assembler, material, ras, elem, nodes, up_edges, support_dofs,
                       ld, pt, cfg, service_cfg, progress_service=None):
    """Simulate RAS service stage (uniform xi, annual water level, no thermal field).

    Returns (U_final, state_final, xi_final) ready for the overtopping analysis.
    Mirrors run_ras_service_stage in the legacy presa_ras.py.
    """
    from .loads import assemble_external_force
    from .solver import solve_step_newton

    n_elem = elem.B.shape[0]
    n_dof = assembler.n_dof
    state = GPState.zeros(n_elem, elem.n_gp)
    U = np.zeros(n_dof)

    total_days = service_cfg.service_years * 365.0
    dt_days = service_cfg.dt_days
    n_steps = max(int(round(total_days / dt_days)), 1)
    dt_days = total_days / n_steps  # ensure last step lands exactly at end

    from .solver import SolverOptions
    opts = cfg.solver_options()
    solver_opts_service = SolverOptions(
        tangent_mode=opts.tangent_mode, max_iter=opts.max_iter,
        tol_res_abs=opts.tol_res_abs, tol_res_rel=opts.tol_res_rel,
        tol_du=opts.tol_du, use_line_search=opts.use_line_search,
        backend=opts.backend)

    xi_val = 0.0
    for m in range(1, n_steps + 1):
        t_days = m * dt_days
        xi_val = _xi_uniform(t_days, total_days, service_cfg.xi_target,
                             service_cfg.xi_rate)

        # Rebuild constitutive model with updated xi
        model = make_constitutive(material, ras, xi_val, elem.h_e, pt,
                                  strain_shear_factor=cfg.problem.strain_shear_factor,
                                  min_stiff_factor=cfg.solver.min_stiff_factor)

        Hwater = _water_level_annual(t_days, service_cfg.h_service_max,
                                     service_cfg.h_service_min)
        fext = assemble_external_force(nodes, elem, up_edges, Hwater,
                                       gamma_c=ld.gamma_c, gamma_w=ld.gamma_w,
                                       thickness=cfg.problem.thickness)

        res = solve_step_newton(assembler, model, state, U, dict(support_dofs),
                                solver_opts_service, fext=fext)
        if res.converged:
            U = res.U
            state = res.state

        if progress_service and m % 50 == 0:
            dmax = float((1.0 - (1.0 - state.damage_t) * (1.0 - state.damage_c)).max())
            progress_service(m, n_steps, t_days / 365.0, xi_val, Hwater, dmax)

    # End of service: ensure equilibrium at h_start before overtopping
    xi_final = xi_val
    model_end = make_constitutive(material, ras, xi_final, elem.h_e, pt,
                                  strain_shear_factor=cfg.problem.strain_shear_factor,
                                  min_stiff_factor=cfg.solver.min_stiff_factor)
    fext_start = assemble_external_force(nodes, elem, up_edges, ld.h_start,
                                         gamma_c=ld.gamma_c, gamma_w=ld.gamma_w,
                                         thickness=cfg.problem.thickness)
    res_end = solve_step_newton(assembler, model_end, state, U, dict(support_dofs),
                                opts, fext=fext_start)
    if res_end.converged:
        U = res_end.U
        state = res_end.state

    return U, state, xi_final


def _run_dam(cfg: Config, out_dir, progress) -> dict:
    from . import postprocess as pp
    from .analysis import LevelStepping, run_load_control
    from .loads import assemble_external_force
    from .mesh.polygon import conforming_t3_mesh, nearest_node, vertical_face_edges, base_nodes
    from .solver import solve_step_newton

    geo = cfg.geometry
    if geo.kind != "polygon":
        raise ValueError("hydraulic loading expects a polygon geometry")

    material = cfg.material_model()
    ras = cfg.ras_model()
    pt = cfg.problem.problem_type
    ld = cfg.loading

    nodes, elements = conforming_t3_mesh(np.asarray(geo.vertices, float), geo.mesh_size)
    elem = precompute(nodes, elements, "t3", cfg.problem.thickness)
    assembler = Assembler(elem)

    up_edges = vertical_face_edges(nodes, elements, x_face=0.0)
    base = base_nodes(nodes, y_base=0.0)
    support_dofs = {}
    for n in base:
        support_dofs[2 * n] = 0.0
        support_dofs[2 * n + 1] = 0.0

    # crest node = topmost upstream vertex
    crest = nearest_node(nodes, [0.0, geo.height])
    crest_dof_x = 2 * crest

    def build_fext(level):
        return assemble_external_force(nodes, elem, up_edges, level,
                                       gamma_c=ld.gamma_c, gamma_w=ld.gamma_w,
                                       thickness=cfg.problem.thickness)

    def output_fn(U, Fint):
        return U[crest_dof_x]

    n_dof = 2 * nodes.shape[0]
    service_cfg = cfg.service

    if service_cfg is not None and service_cfg.service_years > 0:
        # Run service stage (16 years of RAS + cycling water level)
        U0, state0, xi_final = _run_service_stage(
            assembler, material, ras, elem, nodes, up_edges, support_dofs,
            ld, pt, cfg, service_cfg)
    else:
        # No service stage: single equilibrium at h_start with constant xi
        xi_final = ras.xi_at()
        state0 = GPState.zeros(elements.shape[0], elem.n_gp)
        U0 = np.zeros(n_dof)
        res0 = solve_step_newton(assembler, make_constitutive(
            material, ras, xi_final, elem.h_e, pt,
            strain_shear_factor=cfg.problem.strain_shear_factor,
            min_stiff_factor=cfg.solver.min_stiff_factor),
            state0, U0, dict(support_dofs), cfg.solver_options(),
            fext=build_fext(ld.h_start))
        state0 = res0.state
        U0 = res0.U

    # Build overtopping model with the final xi
    model = make_constitutive(material, ras, xi_final, elem.h_e, pt,
                              strain_shear_factor=cfg.problem.strain_shear_factor,
                              min_stiff_factor=cfg.solver.min_stiff_factor)

    stepping = LevelStepping(h_start=ld.h_start, h_target=ld.h_target,
                             dh_initial=ld.dh_initial, dh_min=ld.dh_min,
                             dh_max=ld.dh_max, max_accepted_steps=ld.max_accepted_steps)

    result = run_load_control(assembler, model, state0, U0, support_dofs,
                              build_fext, output_fn, stepping,
                              cfg.solver_options(), progress=progress)

    out = Path(out_dir or cfg.output.dir) / cfg.name
    summary = pp.save_summary(out, cfg, result,
                              extra={"xi": xi_final, "n_nodes": int(nodes.shape[0]),
                                     "n_elements": int(elements.shape[0]),
                                     "crest_node": crest,
                                     "h_start": ld.h_start,
                                     "failure_level": float(result.control[-1]) if result.control.size else None})
    if cfg.output.save_tables:
        pp.save_tables(out, result, "H_m", "ux_crest")
    if cfg.output.save_figures:
        pp.save_figures(out, nodes, elements, result, assembler, model,
                        dpi=cfg.output.dpi, control_label="H [m]", load_label="ux crest")
    return {"result": result, "summary": summary, "out_dir": str(out),
            "nodes": nodes, "elements": elements}
