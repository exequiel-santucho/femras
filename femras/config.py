"""Declarative configuration (the "ficha de datos").

A whole run is one YAML/JSON file validated by pydantic. Defaults reproduce the
beam example, so a minimal file is enough. The same schema is what the web
graphical editor serialises, so drawing <-> YAML <-> CLI are equivalent.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Optional

import numpy as np
import yaml
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

class ProblemCfg(BaseModel):
    element_type: Literal["q4", "t3"] = "q4"
    problem_type: Literal["plane_stress", "plane_strain"] = "plane_stress"
    thickness: float = 75.0
    # legacy beam uses shear_factor 1.0; the dam (tensorial strain) uses 0.5
    strain_shear_factor: float = 1.0


class MaterialCfg(BaseModel):
    E0: float = 38100.0
    nu: float = 0.20
    ft0: float = 4.0
    fc0: float = 51.2
    Gf0: float = 0.10
    Gc0: float = 10.0
    damage_max: float = 0.99999
    enable_compression_damage: bool = False
    # "exponential" (beam, default) or "linear" (dam, presa_ras legacy)
    softening_law: Literal["exponential", "linear"] = "exponential"


class RASCfg(BaseModel):
    enabled: bool = True
    mode: Literal["imposed", "larive", "simple_exp"] = "larive"
    xi_imposed: float = 0.0
    age_days: float = 300.0
    tau_lat: float = 188.83
    tau_ch: float = 161.89
    tau: float = 200.0
    eps_inf_vol: float = 0.0042
    linear_divisor: float = 3.0
    expansion_scale: float = 1.0
    activity_power: float = 1.0
    beta_E: float = 0.25
    beta_ft: float = 0.45
    beta_fc: float = 0.15
    beta_Gf: float = 0.55
    E_min_factor: float = 0.20
    ft_min_factor: float = 0.10
    fc_min_factor: float = 0.20
    Gf_min_factor: float = 0.10


class BeamGeometry(BaseModel):
    kind: Literal["beam"] = "beam"
    L: float = 430.0
    H: float = 105.0
    nx: int = 86
    ny: int = 21
    notch_width: float = 3.0
    notch_height: float = 52.5
    support_span: float = 400.0


class PolygonGeometry(BaseModel):
    kind: Literal["polygon"] = "polygon"
    vertices: List[List[float]]
    mesh_size: float = 2000.0
    height: float = 103000.0


class SupportCfg(BaseModel):
    # locate by nearest node to (x, y); fix selected components
    x: float
    y: float
    fix_x: bool = True
    fix_y: bool = True


class EdgeSupportCfg(BaseModel):
    """Displacement BC applied to every mesh node on the segment [p1, p2].

    Semantic equivalences:
        fix_x=True,  fix_y=True  -> fixed (empotrado)
        fix_x=False, fix_y=True  -> roller free in X (roller_x)
        fix_x=True,  fix_y=False -> roller free in Y (roller_y)
    """
    vertices: List[List[float]]   # [[x1, y1], [x2, y2]]
    fix_x: bool = True
    fix_y: bool = True


class TimeFunctionCfg(BaseModel):
    """Time multiplier lambda(t) for an edge load.

    Either a piecewise-linear table of [t, value] points or an expression
    string (e.g. "10*sin(2*pi*t)"). ``expr`` takes precedence over ``points``;
    if both are empty the multiplier is the constant 1.0.
    """
    points: List[List[float]] = Field(default_factory=list)   # [[t, value], ...]
    expr: Optional[str] = None

    def multiplier(self):
        from .timefunc import make_time_multiplier
        return make_time_multiplier(points=self.points or None, expr=self.expr)


class EdgeLoadCfg(BaseModel):
    """Distributed traction on the polygon edge [p1, p2], scaled by ``multiplier``.

    ``p_normal`` acts along the inward face normal (positive pushes into the
    body); ``p_tangential`` acts along the edge tangent (p1 -> p2). Both are
    reference magnitudes (force per unit area) multiplied by lambda(t).
    """
    vertices: List[List[float]]   # [[x1, y1], [x2, y2]]
    p_normal: float = 0.0
    p_tangential: float = 0.0
    multiplier: TimeFunctionCfg = Field(default_factory=TimeFunctionCfg)


class NodalLoadCfg(BaseModel):
    """Concentrated force applied at the mesh node nearest to (x, y).

    ``fx``/``fy`` are reference components (global axes) scaled by lambda(t).
    """
    x: float
    y: float
    fx: float = 0.0
    fy: float = 0.0
    multiplier: TimeFunctionCfg = Field(default_factory=TimeFunctionCfg)


class DisplacementLoad(BaseModel):
    mode: Literal["displacement"] = "displacement"
    # imposed on a top patch near x_center at y_top, vertical DOF
    x_center: float = 215.0
    y_top: float = 105.0
    patch: Literal["one_node", "three_nodes_centered"] = "three_nodes_centered"
    target: float = -0.20
    step_initial: float = -0.0010
    step_min: float = -0.000010
    step_max: float = -0.0015
    grow_factor: float = 1.10
    shrink_factor: float = 0.5
    max_accepted_steps: int = 600
    # Ordered sequence of displacement targets (cyclic/multi-segment loading).
    # If empty, falls back to [target]. Direction is inferred per segment.
    history: List[float] = Field(default_factory=list)


class HydraulicLoad(BaseModel):
    mode: Literal["hydraulic"] = "hydraulic"
    gamma_c: float = 2.40e-5
    gamma_w: float = 9.81e-6
    h_start: float = 92.0
    h_target: float = 120.0
    dh_initial: float = 0.50
    dh_min: float = 0.020
    dh_max: float = 0.50
    max_accepted_steps: int = 600
    # Two vertices [[x1,y1],[x2,y2]] defining the hydraulic face on the polygon.
    # None → backward-compatible: vertical face at x=0.
    face_vertices: Optional[List[List[float]]] = None
    # Ordered sequence of water-level targets for multi-segment loading.
    # If empty, falls back to [h_target].
    history: List[float] = Field(default_factory=list)


class TimeHistoryLoad(BaseModel):
    """Pseudo-time march applying time-variable distributed edge loads.

    The control parameter is the pseudo-time ``t`` advancing from ``t_start`` to
    ``t_end`` with adaptive stepping. At each step the external force is the
    (optional) self-weight plus, for every edge load, its reference traction
    scaled by its time multiplier lambda(t).
    """
    mode: Literal["time_history"] = "time_history"
    t_start: float = 0.0
    t_end: float = 1.0
    dt_initial: float = 0.05
    dt_min: float = 0.001
    dt_max: float = 0.10
    max_accepted_steps: int = 600
    self_weight: bool = False
    gamma_c: float = 2.40e-5
    edge_loads: List[EdgeLoadCfg] = Field(default_factory=list)
    point_loads: List[NodalLoadCfg] = Field(default_factory=list)


class SolverCfg(BaseModel):
    tangent_mode: Literal["numerical_hybrid", "numerical", "secant", "elastic"] = "numerical_hybrid"
    max_iter: int = 60
    tol_res_abs: float = 1.0e-4
    tol_res_rel: float = 1.0e-5
    tol_du: float = 1.0e-8
    use_line_search: bool = True
    min_stiff_factor: float = 1.0e-8
    backend: Literal["auto", "numpy", "numba", "gpu"] = "auto"


class OutputCfg(BaseModel):
    dir: str = "resultados_femras"
    dpi: int = 200
    save_figures: bool = True
    save_tables: bool = True


class ServiceStageCfg(BaseModel):
    """16-year RAS service stage (uniform xi, no thermal field).

    Mirrors the ``run_ras_service_stage`` function in the legacy presa_ras.py.
    ``service_years=0`` disables the stage (healthy dam).
    """
    service_years: int = 0            # 0 = healthy; 16 = RAS case
    dt_days: float = 3.0              # time step (days)
    h_service_max: float = 92000.0    # peak water level during service (mm)
    h_service_min: float = 37000.0    # minimum water level during service (mm)
    xi_target: float = 0.70           # xi at end of service period
    xi_rate: float = 3.0              # exponential growth rate parameter


class Config(BaseModel):
    name: str = "caso_femras"
    problem: ProblemCfg = Field(default_factory=ProblemCfg)
    material: MaterialCfg = Field(default_factory=MaterialCfg)
    ras: RASCfg = Field(default_factory=RASCfg)
    geometry: BeamGeometry | PolygonGeometry = Field(default_factory=BeamGeometry, discriminator="kind")
    supports: List[SupportCfg] = Field(default_factory=list)        # nodos puntuales
    edge_supports: List[EdgeSupportCfg] = Field(default_factory=list)  # aristas completas
    loading: DisplacementLoad | HydraulicLoad | TimeHistoryLoad = Field(
        default_factory=DisplacementLoad, discriminator="mode")
    solver: SolverCfg = Field(default_factory=SolverCfg)
    output: OutputCfg = Field(default_factory=OutputCfg)
    service: Optional[ServiceStageCfg] = None

    # ---- builders mapping the config to core dataclasses -----------------
    def material_model(self):
        from .materials import MaterialDamage
        m = self.material
        return MaterialDamage(m.E0, m.nu, m.ft0, m.fc0, m.Gf0, m.Gc0,
                              m.damage_max, m.enable_compression_damage,
                              m.softening_law)

    def ras_model(self):
        from .ras import RASModel
        return RASModel(**self.ras.model_dump())

    def solver_options(self):
        from .solver import SolverOptions
        s = self.solver
        return SolverOptions(tangent_mode=s.tangent_mode, max_iter=s.max_iter,
                             tol_res_abs=s.tol_res_abs, tol_res_rel=s.tol_res_rel,
                             tol_du=s.tol_du, use_line_search=s.use_line_search,
                             backend=s.backend)


def load_config(path: str | Path) -> Config:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Config.model_validate(data or {})


def save_config(cfg: Config, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg.model_dump(), f, sort_keys=False, allow_unicode=True)
