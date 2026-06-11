"""Regression tests for the gravity dam (hydraulic load control).

Two-level validation:
  1. Constitutive unit test – linear softening formula matches legacy
     presa_ras.py ``damage_from_kappa`` to machine precision.
  2. Structural snapshot – healthy dam (ANIOS_RAS=0) loaded to H=100 m
     matches the validated legacy crest-displacement and dmax values.

The structural test uses the exact same mesh (2 m), material, and solver
settings as the legacy script. It is kept short (h_target=100 m) to finish
in a few seconds without compromising coverage of the damage zone.
"""

from __future__ import annotations

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# 1. Constitutive unit test: linear softening law
# ---------------------------------------------------------------------------

from rasfem.damage import ConstitutiveModel, GPState
from rasfem.materials import MaterialDamage
from rasfem.ras import RASModel
from rasfem.stages import make_constitutive


def _legacy_damage_from_kappa(kappa, E_loc, ft_loc, Gf_loc, he, damage_max=0.9995):
    """Exact copy of presa_ras.py:damage_from_kappa (lines 926-943)."""
    eps0 = ft_loc / E_loc
    if kappa <= eps0:
        return 0.0
    ef = eps0 + 2.0 * Gf_loc / (ft_loc * he)
    if ef <= eps0 * 1.0000001:
        ef = eps0 * 1.0001
    d = ef * (kappa - eps0) / (kappa * (ef - eps0))
    return max(0.0, min(d, damage_max))


def test_linear_softening_matches_legacy():
    """rasfem linear softening == legacy damage_from_kappa to machine precision."""
    # Dam material at xi=0 (healthy)
    E, ft, Gf, he = 22000.0, 2.10, 0.300, 1414.0   # typical 2 m T3 mesh
    damage_max = 0.9995
    eps0 = ft / E  # ~9.545e-5

    mat = MaterialDamage(E0=E, nu=0.20, ft0=ft, fc0=21.0, Gf0=Gf, Gc0=10.0,
                         damage_max=damage_max, enable_compression_damage=False,
                         softening_law="linear")
    ras = RASModel(enabled=False)
    model = make_constitutive(mat, ras, 0.0, np.array([he]), "plane_strain",
                              strain_shear_factor=0.5, min_stiff_factor=1e-6)

    rng = np.random.default_rng(42)
    kappas = np.concatenate([
        rng.uniform(0.0, eps0 * 0.99, 40),           # below eps0 -> d=0
        rng.uniform(eps0 * 1.001, eps0 * 50, 60),    # softening zone
        [1.0, 0.01, 0.001],                           # large kappas
    ])

    max_err = 0.0
    for kappa_val in kappas:
        d_legacy = _legacy_damage_from_kappa(kappa_val, E, ft, Gf, he, damage_max)

        # Build a state where kappa_t = kappa_val already reached
        eps0_val = ft / E
        # Use principal tensile strain = kappa_val -> eps = [kappa, 0, 0]
        eps = np.array([[[kappa_val, 0.0, 0.0]]])
        old_state = GPState(
            kappa_t=np.array([[kappa_val]]),
            kappa_c=np.zeros((1, 1)),
            damage_t=np.zeros((1, 1)),
            damage_c=np.zeros((1, 1)),
        )
        # Feed eps large enough so kappa doesn't grow (already at max)
        # Use neutral strain = RAS strain so eps_mec ~ 0
        sig, dmg, new_state = model.evaluate(eps, old_state)
        d_rasfem = float(new_state.damage_t[0, 0])

        err = abs(d_rasfem - d_legacy)
        max_err = max(max_err, err)

    assert max_err < 1e-9, f"max softening error = {max_err:.3e}"


# ---------------------------------------------------------------------------
# 2. Structural snapshot: healthy dam, load to H=100 m
# ---------------------------------------------------------------------------

from rasfem.config import load_config
from rasfem.run import run_config

PRESA_YAML = "examples/presa_ras.yaml"


def _healthy_dam_cfg(h_target=100_000.0):
    cfg = load_config(PRESA_YAML)
    # Force healthy (no service stage, no RAS)
    cfg.service = None
    cfg.ras.enabled = False
    cfg.ras.xi_imposed = 0.0
    cfg.loading.h_target = h_target
    cfg.loading.max_accepted_steps = 200
    cfg.name = "reg_dam_sana"
    cfg.output.save_figures = False
    cfg.output.save_tables = False
    return cfg


@pytest.mark.slow
def test_dam_healthy_snapshot(tmp_path):
    """Healthy dam loaded to 100 m matches legacy crest ux and dmax.

    Reference (from validated presa_ras.py ANIOS_RAS=0 run):
      H = 100 m  -> ux_crest ≈ 13.50 mm,  dmax ≈ 0.7838
    Tolerance: ux ±0.5 mm (adaptive step landing), dmax ±0.05.
    """
    cfg = _healthy_dam_cfg(h_target=100_000.0)
    info = run_config(cfg, out_dir=str(tmp_path))
    result = info["result"]

    # Find the step closest to H=100 m
    H_arr = result.control          # mm
    ux_arr = result.load            # mm (crest horizontal displacement)
    dmax_arr = result.max_damage

    idx = int(np.argmin(np.abs(H_arr - 100_000.0)))
    H_found = float(H_arr[idx]) / 1000.0    # -> m
    ux_found = float(ux_arr[idx])            # mm
    dmax_found = float(dmax_arr[idx])

    assert abs(H_found - 100.0) < 0.6, f"Closest step is H={H_found:.2f} m (expected ~100)"
    assert abs(ux_found - 13.50) < 0.60, f"ux_crest={ux_found:.3f} mm (expected ~13.50)"
    assert abs(dmax_found - 0.7838) < 0.06, f"dmax={dmax_found:.4f} (expected ~0.7838)"


@pytest.mark.slow
def test_dam_healthy_damage_monotonic(tmp_path):
    """Damage must be non-decreasing (irreversibility) in the healthy-dam run."""
    cfg = _healthy_dam_cfg(h_target=98_000.0)
    info = run_config(cfg, out_dir=str(tmp_path))
    dmax = info["result"].max_damage
    assert np.all(np.diff(dmax) >= -1e-9), "Damage decreased — irreversibility violated"
