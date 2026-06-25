"""Constitutive equivalence against the legacy beam script.

Validates that the vectorised ConstitutiveModel reproduces the per-Gauss-point
``update_damage_material`` of examples/legacy/viga_rilem.py to machine precision
over many random strain states. This is the fast, rigorous proof that the
refactor preserves the physics (the global response then follows from the
identical mesh and assembly). Skipped if the legacy script cannot be imported.
"""

import os
import sys

import numpy as np
import pytest

LEGACY = os.path.join(os.path.dirname(__file__), "..", "examples", "legacy")
sys.path.insert(0, os.path.abspath(LEGACY))

legacy = pytest.importorskip("viga_rilem")

from femras.damage import GPState
from femras.materials import MaterialDamage
from femras.ras import RASModel
from femras.stages import make_constitutive


def test_constitutive_matches_legacy():
    Lmat = legacy.MaterialDamage(E0=38100, nu=0.20, ft0=4.0, fc0=51.2,
                                 Gf0=0.10, Gc0=10.0, enable_compression_damage=False)
    Lras = legacy.RASOptions(enabled=True, mode="time_law", time_law="larive",
                             age_days=300.0, tau_lat=188.83, tau_ch=161.89,
                             eps_inf_vol=0.0042, beta_E=0.25, beta_ft=0.45,
                             beta_fc=0.15, beta_Gf=0.55)
    xi = legacy.xi_from_ras_options(Lras)
    he, pt = 5.0, "plane_stress"

    mat = MaterialDamage(E0=38100, nu=0.20, ft0=4.0, fc0=51.2, Gf0=0.10, Gc0=10.0,
                         enable_compression_damage=False)
    ras = RASModel(enabled=True, mode="larive", age_days=300.0, tau_lat=188.83,
                   tau_ch=161.89, eps_inf_vol=0.0042, linear_divisor=3.0,
                   expansion_scale=1.0, activity_power=1.0, beta_E=0.25,
                   beta_ft=0.45, beta_fc=0.15, beta_Gf=0.55)
    model = make_constitutive(mat, ras, xi, np.array([he]), pt, strain_shear_factor=1.0)

    rng = np.random.default_rng(0)
    max_err = 0.0
    for _ in range(2000):
        eps = rng.standard_normal(3) * rng.choice([1e-5, 1e-4, 1e-3, 3e-3])
        st = legacy.GPState()
        st.xi_ras = xi
        new, _D = legacy.update_damage_material(Lmat, Lras, st, eps, he, pt)
        sig, dmg, _ns = model.evaluate(eps.reshape(1, 1, 3), GPState.zeros(1, 1))
        err = max(np.max(np.abs(new.stress - sig[0, 0])), abs(new.damage - dmg[0, 0]))
        max_err = max(max_err, err)
    assert max_err < 1e-9, f"max constitutive error {max_err:.2e}"
