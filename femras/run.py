"""Orchestrator: turn a validated :class:`~femras.config.Config` into a run.

Both the displacement-controlled beam and the hydraulic (load-controlled dam)
paths are implemented.  Multi-segment load history and an arbitrary hydraulic
face (not just x = 0) are supported.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .analysis import LevelStepping, SteppingOptions, AnalysisResult
from .analysis import run_displacement_control, run_load_control, _field_snapshot
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
    if cfg.loading.mode == "time_history":
        return _run_time_history(cfg, out_dir, progress)
    raise NotImplementedError(f"loading mode '{cfg.loading.mode}' not supported")


def _resolve_polygon_support_dofs(cfg: Config, nodes, elements) -> dict:
    """Displacement BCs for a polygon mesh from config (PRD edge_supports).

    * If ``cfg.edge_supports`` is non-empty, every mesh node on each edge gets
      its selected DOFs fixed.
    * Otherwise fall back to the legacy behaviour: all base nodes (y = 0) fixed,
      preserving the existing dam regression results.
    * Point ``cfg.supports`` (nearest node) are applied last and may override
      individual DOFs.
    """
    from .mesh.polygon import nodes_on_segment, base_nodes, nearest_node

    support_dofs: dict = {}
    if cfg.edge_supports:
        for es in cfg.edge_supports:
            p1 = np.asarray(es.vertices[0], float)
            p2 = np.asarray(es.vertices[1], float)
            for n in nodes_on_segment(nodes, elements, p1, p2):
                n = int(n)
                if es.fix_x:
                    support_dofs[2 * n] = 0.0
                if es.fix_y:
                    support_dofs[2 * n + 1] = 0.0
    else:
        for n in base_nodes(nodes, y_base=0.0):
            n = int(n)
            support_dofs[2 * n] = 0.0
            support_dofs[2 * n + 1] = 0.0

    for s in cfg.supports:
        n = nearest_node(nodes, [s.x, s.y])
        if s.fix_x:
            support_dofs[2 * n] = 0.0
        if s.fix_y:
            support_dofs[2 * n + 1] = 0.0
    return support_dofs


# ─── Beam (displacement control) ─────────────────────────────────────────────

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

    # Multi-segment history: if history is empty, use [target] (backward compat).
    targets = list(ld.history) if ld.history else [ld.target]

    all_control, all_load, all_dmax, all_table = [], [], [], []
    total_accepted = total_rejected = 0
    state = GPState.zeros(elements.shape[0], elem.n_gp)
    U = U0.copy()
    delta_curr = 0.0

    snapshots = [_field_snapshot(assembler, model, U, state, 0.0, 0.0)]
    snap_every = 5  # capture every 5 accepted steps; payload is downsampled

    for seg_target in targets:
        direction = 1.0 if seg_target >= delta_curr else -1.0
        step_mag = abs(ld.step_initial)

        stepping = SteppingOptions(
            target=seg_target,
            delta_start=delta_curr,
            step_initial=direction * step_mag,
            step_min=direction * abs(ld.step_min),
            step_max=direction * abs(ld.step_max),
            grow_factor=ld.grow_factor,
            shrink_factor=ld.shrink_factor,
            max_accepted_steps=ld.max_accepted_steps,
        )

        seg = run_displacement_control(
            assembler, model, state, U, support_dofs, load_dofs, load_base,
            stepping, cfg.solver_options(), progress=progress,
            snapshots=snapshots, snapshot_every=snap_every)

        all_control.extend(seg.control.tolist())
        all_load.extend(seg.load.tolist())
        all_dmax.extend(seg.max_damage.tolist())
        all_table.extend(seg.step_table)
        total_accepted += seg.accepted
        total_rejected += seg.rejected
        state = seg.state
        U = seg.U_final.copy()
        delta_curr = seg_target

    # Always capture the final state as the last snapshot
    if all_load:
        snapshots.append(_field_snapshot(assembler, model, U, state,
                                         all_control[-1], all_load[-1]))

    result = AnalysisResult(
        np.array(all_control), np.array(all_load), np.array(all_dmax),
        U, state, total_accepted, total_rejected, all_table, snapshots)

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
    fields = pp.save_fields(out, nodes, elements, result, assembler, model)
    return {"result": result, "summary": summary, "out_dir": str(out),
            "nodes": nodes, "elements": elements, "fields": fields}


# ─── Dam (hydraulic / load control) ──────────────────────────────────────────

def _face_inward_normal(p1, p2, poly_vertices):
    """Inward normal for the polygon face defined by [p1, p2].

    Returns the normal that points toward the polygon interior (centroid side).
    """
    p1 = np.asarray(p1, float)
    p2 = np.asarray(p2, float)
    t = p2 - p1
    t_len = float(np.linalg.norm(t))
    if t_len < 1e-15:
        return np.array([1.0, 0.0])
    t = t / t_len
    n_left = np.array([-t[1], t[0]])
    n_right = np.array([t[1], -t[0]])
    centroid = np.mean(np.asarray(poly_vertices, float), axis=0)
    mid = 0.5 * (p1 + p2)
    return n_left if float(np.dot(n_left, centroid - mid)) > 0 else n_right


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
                       ld, pt, cfg, service_cfg, face_normal=None, progress_service=None):
    """Simulate RAS service stage (uniform xi, annual water level, no thermal field).

    Returns (U_final, state_final, xi_final) ready for the overtopping analysis.
    Mirrors run_ras_service_stage in the legacy presa_ras.py.
    """
    from .loads import assemble_external_force
    from .solver import solve_step_newton

    if face_normal is None:
        face_normal = np.array([1.0, 0.0])

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

        model = make_constitutive(material, ras, xi_val, elem.h_e, pt,
                                  strain_shear_factor=cfg.problem.strain_shear_factor,
                                  min_stiff_factor=cfg.solver.min_stiff_factor)

        Hwater = _water_level_annual(t_days, service_cfg.h_service_max,
                                     service_cfg.h_service_min)
        fext = assemble_external_force(nodes, elem, up_edges, Hwater,
                                       gamma_c=ld.gamma_c, gamma_w=ld.gamma_w,
                                       thickness=cfg.problem.thickness,
                                       face_normal=face_normal)

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
                                         thickness=cfg.problem.thickness,
                                         face_normal=face_normal)
    res_end = solve_step_newton(assembler, model_end, state, U, dict(support_dofs),
                                opts, fext=fext_start)
    if res_end.converged:
        U = res_end.U
        state = res_end.state

    return U, state, xi_final


def _run_dam(cfg: Config, out_dir, progress) -> dict:
    from . import postprocess as pp
    from .loads import assemble_external_force
    from .mesh.polygon import (conforming_t3_mesh, nearest_node,
                               vertical_face_edges, face_boundary_edges)
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

    # Hydraulic face: use face_vertices if specified, else fall back to x = 0
    if ld.face_vertices is not None:
        fv = ld.face_vertices
        p1, p2 = np.asarray(fv[0], float), np.asarray(fv[1], float)
        up_edges = face_boundary_edges(nodes, elements, p1, p2)
        face_normal = _face_inward_normal(p1, p2, geo.vertices)
    else:
        up_edges = vertical_face_edges(nodes, elements, x_face=0.0)
        face_normal = np.array([1.0, 0.0])

    support_dofs = _resolve_polygon_support_dofs(cfg, nodes, elements)

    crest = nearest_node(nodes, [0.0, geo.height])
    crest_dof_x = 2 * crest

    def build_fext(level):
        return assemble_external_force(nodes, elem, up_edges, level,
                                       gamma_c=ld.gamma_c, gamma_w=ld.gamma_w,
                                       thickness=cfg.problem.thickness,
                                       face_normal=face_normal)

    def output_fn(U, Fint):
        return U[crest_dof_x]

    n_dof = 2 * nodes.shape[0]
    service_cfg = cfg.service

    if service_cfg is not None and service_cfg.service_years > 0:
        U0, state0, xi_final = _run_service_stage(
            assembler, material, ras, elem, nodes, up_edges, support_dofs,
            ld, pt, cfg, service_cfg, face_normal=face_normal)
    else:
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

    model = make_constitutive(material, ras, xi_final, elem.h_e, pt,
                              strain_shear_factor=cfg.problem.strain_shear_factor,
                              min_stiff_factor=cfg.solver.min_stiff_factor)

    # Multi-segment history
    targets = list(ld.history) if ld.history else [ld.h_target]

    all_control, all_load, all_dmax, all_table = [], [], [], []
    total_accepted = total_rejected = 0
    state = state0
    U = U0.copy()
    level_curr = ld.h_start

    snapshots = [_field_snapshot(assembler, model, U, state, ld.h_start,
                                 float(U[crest_dof_x]))]
    snap_every = 5  # capture every 5 accepted steps; payload is downsampled

    for seg_target in targets:
        stepping = LevelStepping(
            h_start=level_curr,
            h_target=seg_target,
            dh_initial=ld.dh_initial,
            dh_min=ld.dh_min,
            dh_max=ld.dh_max,
            max_accepted_steps=ld.max_accepted_steps,
        )

        seg = run_load_control(assembler, model, state, U, support_dofs,
                               build_fext, output_fn, stepping,
                               cfg.solver_options(), progress=progress,
                               snapshots=snapshots, snapshot_every=snap_every)

        all_control.extend(seg.control.tolist())
        all_load.extend(seg.load.tolist())
        all_dmax.extend(seg.max_damage.tolist())
        all_table.extend(seg.step_table)
        total_accepted += seg.accepted
        total_rejected += seg.rejected
        state = seg.state
        U = seg.U_final.copy()
        level_curr = float(seg.control[-1]) if seg.control.size else level_curr

    if all_load:
        snapshots.append(_field_snapshot(assembler, model, U, state,
                                         all_control[-1], all_load[-1]))

    result = AnalysisResult(
        np.array(all_control), np.array(all_load), np.array(all_dmax),
        U, state, total_accepted, total_rejected, all_table, snapshots)

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
    fields = pp.save_fields(out, nodes, elements, result, assembler, model)
    return {"result": result, "summary": summary, "out_dir": str(out),
            "nodes": nodes, "elements": elements, "fields": fields}


# ─── Time-history (distributed edge loads scaled by lambda(t)) ────────────────

def _run_time_history(cfg: Config, out_dir, progress) -> dict:
    from . import postprocess as pp
    from .analysis import LevelStepping, AnalysisResult, run_load_control
    from .loads import body_force_t3, edge_traction_force
    from .mesh.polygon import conforming_t3_mesh, face_boundary_edges, nearest_node

    geo = cfg.geometry
    if geo.kind != "polygon":
        raise ValueError("time_history loading expects a polygon geometry")

    material = cfg.material_model()
    ras = cfg.ras_model()
    pt = cfg.problem.problem_type
    ld = cfg.loading

    nodes, elements = conforming_t3_mesh(np.asarray(geo.vertices, float), geo.mesh_size)
    elem = precompute(nodes, elements, "t3", cfg.problem.thickness)
    assembler = Assembler(elem)

    support_dofs = _resolve_polygon_support_dofs(cfg, nodes, elements)

    # Precompute, per edge load: its boundary edges, inward normal and lambda(t).
    th = cfg.problem.thickness
    edge_data = []
    for el in ld.edge_loads:
        p1 = np.asarray(el.vertices[0], float)
        p2 = np.asarray(el.vertices[1], float)
        edges = face_boundary_edges(nodes, elements, p1, p2)
        fn = _face_inward_normal(p1, p2, geo.vertices)
        edge_data.append((edges, fn, el.p_normal, el.p_tangential,
                          el.multiplier.multiplier()))

    # Precompute, per nodal point load: its nearest node DOFs and lambda(t).
    point_data = []
    for pl in ld.point_loads:
        node = nearest_node(nodes, [pl.x, pl.y])
        point_data.append((2 * node, 2 * node + 1, pl.fx, pl.fy,
                           pl.multiplier.multiplier()))

    xi = ras.xi_at()
    model = make_constitutive(material, ras, xi, elem.h_e, pt,
                              strain_shear_factor=cfg.problem.strain_shear_factor,
                              min_stiff_factor=cfg.solver.min_stiff_factor)

    n_dof = 2 * nodes.shape[0]

    # Self-weight is constant; precompute it once.
    F_self = np.zeros(n_dof)
    if ld.self_weight:
        for e in range(elem.dofs.shape[0]):
            F_self[elem.dofs[e]] += body_force_t3(elem.area[e], th, ld.gamma_c)

    def build_fext(t):
        F = F_self.copy()
        for edges, fn, pn, ptg, lam in edge_data:
            scale = lam(t)
            if scale == 0.0:
                continue
            for i, j in edges:
                fe = edge_traction_force(nodes[i], nodes[j], pn * scale,
                                         ptg * scale, th, fn)
                dofs = np.array([2 * i, 2 * i + 1, 2 * j, 2 * j + 1], dtype=int)
                F[dofs] += fe
        for dx, dy, fx, fy, lam in point_data:
            scale = lam(t)
            F[dx] += fx * scale
            F[dy] += fy * scale
        return F

    def output_fn(U, Fint):
        return float(np.abs(U).max()) if U.size else 0.0

    stepping = LevelStepping(
        h_start=ld.t_start, h_target=ld.t_end,
        dh_initial=ld.dt_initial, dh_min=ld.dt_min, dh_max=ld.dt_max,
        max_accepted_steps=ld.max_accepted_steps,
    )
    state0 = GPState.zeros(elements.shape[0], elem.n_gp)
    U0 = np.zeros(n_dof)

    snapshots = [_field_snapshot(assembler, model, U0, state0, ld.t_start, 0.0)]
    snap_every = 5  # capture every 5 accepted steps; payload is downsampled

    seg = run_load_control(assembler, model, state0, U0, support_dofs,
                           build_fext, output_fn, stepping,
                           cfg.solver_options(), progress=progress,
                           snapshots=snapshots, snapshot_every=snap_every)

    if seg.load.size:
        snapshots.append(_field_snapshot(assembler, model, seg.U_final, seg.state,
                                         float(seg.control[-1]), float(seg.load[-1])))

    result = AnalysisResult(seg.control, seg.load, seg.max_damage, seg.U_final,
                            seg.state, seg.accepted, seg.rejected, seg.step_table,
                            snapshots)

    out = Path(out_dir or cfg.output.dir) / cfg.name
    summary = pp.save_summary(out, cfg, result,
                              extra={"xi": xi, "n_nodes": int(nodes.shape[0]),
                                     "n_elements": int(elements.shape[0]),
                                     "t_start": ld.t_start, "t_end": ld.t_end})
    if cfg.output.save_tables:
        pp.save_tables(out, result, "t", "max_abs_u")
    if cfg.output.save_figures:
        pp.save_figures(out, nodes, elements, result, assembler, model,
                        dpi=cfg.output.dpi, control_label="t", load_label="max|u| [mm]")
    fields = pp.save_fields(out, nodes, elements, result, assembler, model)
    return {"result": result, "summary": summary, "out_dir": str(out),
            "nodes": nodes, "elements": elements, "fields": fields}
