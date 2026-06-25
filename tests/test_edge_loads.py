"""Unit + smoke tests for edge supports and time-variable edge loads."""

import numpy as np
import pytest

from femras.timefunc import make_time_multiplier
from femras.loads import edge_traction_force
from femras.mesh.polygon import conforming_t3_mesh, nodes_on_segment
from femras.config import (
    Config, ProblemCfg, MaterialCfg, RASCfg, PolygonGeometry,
    EdgeSupportCfg, EdgeLoadCfg, NodalLoadCfg, TimeFunctionCfg,
    TimeHistoryLoad, OutputCfg,
)
from femras.run import run_config


# ─── timefunc ────────────────────────────────────────────────────────────────

def test_timefunc_default_is_unit():
    lam = make_time_multiplier()
    assert lam(0.0) == 1.0 and lam(3.7) == 1.0


def test_timefunc_table_interpolates_and_clamps():
    lam = make_time_multiplier(points=[[0.0, 0.0], [1.0, 10.0]])
    assert np.isclose(lam(0.5), 5.0)
    assert np.isclose(lam(-1.0), 0.0)    # clamps to first point
    assert np.isclose(lam(2.0), 10.0)    # clamps to last point


def test_timefunc_expr_evaluates_math():
    lam = make_time_multiplier(expr="10*sin(2*pi*t)")
    assert np.isclose(lam(0.0), 0.0, atol=1e-9)
    assert np.isclose(lam(0.25), 10.0, atol=1e-9)


def test_timefunc_expr_rejects_unsafe_names():
    with pytest.raises(ValueError):
        make_time_multiplier(expr="__import__('os').system('echo hi')")


def test_timefunc_expr_takes_precedence_over_points():
    lam = make_time_multiplier(points=[[0, 99]], expr="t")
    assert np.isclose(lam(2.0), 2.0)


# ─── edge_traction_force ──────────────────────────────────────────────────────

def test_edge_traction_normal_splits_equally():
    # Horizontal edge of length 2, inward normal (0,1), unit normal pressure.
    fe = edge_traction_force([0, 0], [2, 0], p_normal=1.0, p_tangential=0.0,
                             thickness=1.0, face_normal=[0.0, 1.0])
    # total force = p * thickness * L = 2, all in +y, split half/half
    assert np.allclose(fe, [0.0, 1.0, 0.0, 1.0])


def test_edge_traction_tangential_along_edge():
    fe = edge_traction_force([0, 0], [4, 0], p_normal=0.0, p_tangential=3.0,
                             thickness=2.0, face_normal=[0.0, 1.0])
    # total tangential force = 3 * 2 * 4 = 24 in +x, split half/half
    assert np.allclose(fe, [12.0, 0.0, 12.0, 0.0])


def test_edge_traction_zero_length():
    fe = edge_traction_force([1, 1], [1, 1], 5.0, 5.0, 1.0, [1.0, 0.0])
    assert np.allclose(fe, np.zeros(4))


# ─── nodes_on_segment ─────────────────────────────────────────────────────────

def test_nodes_on_segment_bottom_edge():
    poly = np.array([[0, 0], [1000, 0], [1000, 1000], [0, 1000]], float)
    nodes, elements = conforming_t3_mesh(poly, 250.0)
    idx = nodes_on_segment(nodes, elements, [0, 0], [1000, 0])
    assert idx.size >= 2
    assert np.allclose(nodes[idx, 1], 0.0, atol=1e-6)


# ─── time_history smoke test ──────────────────────────────────────────────────

def _square_time_history_cfg():
    return Config(
        name="th_smoke",
        problem=ProblemCfg(element_type="t3", problem_type="plane_strain",
                           thickness=1000.0, strain_shear_factor=0.5),
        material=MaterialCfg(E0=22000.0, nu=0.20, ft0=2.10, fc0=21.0,
                             Gf0=0.30, softening_law="linear"),
        ras=RASCfg(enabled=False, mode="imposed", xi_imposed=0.0),
        geometry=PolygonGeometry(kind="polygon",
                                 vertices=[[0, 0], [1000, 0], [1000, 1000], [0, 1000]],
                                 mesh_size=250.0, height=1000.0),
        edge_supports=[EdgeSupportCfg(vertices=[[0, 0], [1000, 0]],
                                      fix_x=True, fix_y=True)],
        loading=TimeHistoryLoad(
            mode="time_history", t_start=0.0, t_end=1.0,
            dt_initial=0.25, dt_min=0.05, dt_max=0.5, max_accepted_steps=50,
            edge_loads=[EdgeLoadCfg(vertices=[[0, 1000], [1000, 1000]],
                                    p_normal=0.001,
                                    multiplier=TimeFunctionCfg(expr="t"))]),
        output=OutputCfg(save_figures=False, save_tables=False),
    )


def test_time_history_runs_and_loads_grow(tmp_path):
    cfg = _square_time_history_cfg()
    res = run_config(cfg, out_dir=str(tmp_path))
    result = res["result"]
    assert result.accepted > 0
    assert np.all(np.isfinite(result.control))
    assert np.all(np.isfinite(result.load))
    # multiplier = t increasing -> response magnitude should be non-decreasing
    assert result.load[-1] >= result.load[0] - 1e-12


def test_time_history_nodal_point_load(tmp_path):
    # Same square, base fixed, single downward point force at the top-mid corner.
    cfg = Config(
        name="th_nodal",
        problem=ProblemCfg(element_type="t3", problem_type="plane_strain",
                           thickness=1000.0, strain_shear_factor=0.5),
        material=MaterialCfg(E0=22000.0, softening_law="linear"),
        ras=RASCfg(enabled=False, mode="imposed", xi_imposed=0.0),
        geometry=PolygonGeometry(kind="polygon",
                                 vertices=[[0, 0], [1000, 0], [1000, 1000], [0, 1000]],
                                 mesh_size=250.0, height=1000.0),
        edge_supports=[EdgeSupportCfg(vertices=[[0, 0], [1000, 0]])],
        loading=TimeHistoryLoad(
            mode="time_history", t_start=0.0, t_end=1.0,
            dt_initial=0.25, dt_min=0.05, dt_max=0.5, max_accepted_steps=50,
            point_loads=[NodalLoadCfg(x=1000.0, y=1000.0, fx=0.0, fy=-100.0,
                                      multiplier=TimeFunctionCfg(expr="t"))]),
        output=OutputCfg(save_figures=False, save_tables=False),
    )
    res = run_config(cfg, out_dir=str(tmp_path))
    result = res["result"]
    assert result.accepted > 0
    assert np.all(np.isfinite(result.load))
    assert result.load[-1] > 0.0   # a nonzero displacement develops under the force
