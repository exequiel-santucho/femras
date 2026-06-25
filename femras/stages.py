"""Analysis stages and the helpers that build a per-stage constitutive model.

A *stage* freezes a reaction-extent field ``xi`` (uniform here, per-element in
the dam's service stage) and the ASR-degraded effective properties, then runs a
mechanical test under either displacement or load control.
"""

from __future__ import annotations

import numpy as np

from .damage import ConstitutiveModel
from .materials import MaterialDamage
from .ras import RASModel


def make_constitutive(material: MaterialDamage, ras: RASModel, xi_field, h_e,
                      problem_type: str, *, strain_shear_factor=1.0,
                      min_stiff_factor=1.0e-8) -> ConstitutiveModel:
    """Build a vectorised constitutive model for a frozen xi field.

    ``xi_field`` is a scalar or a per-element array. The ASR linear strain and
    the degraded E/ft/fc/Gf are evaluated once for the whole mesh.
    """
    n_elem = len(h_e)
    xi = np.full(n_elem, float(xi_field)) if np.ndim(xi_field) == 0 else np.asarray(xi_field, float)
    E_eff, ft_eff, fc_eff, Gf_eff = ras.degraded_properties(material, xi)
    eps_ras = np.asarray(ras.eps_ras_lin(xi), dtype=float) * np.ones(n_elem)
    return ConstitutiveModel(
        nu=material.nu,
        problem_type=problem_type,
        h_e=np.asarray(h_e, float),
        E_eff=np.asarray(E_eff, float) * np.ones(n_elem),
        ft_eff=np.asarray(ft_eff, float) * np.ones(n_elem),
        fc_eff=np.asarray(fc_eff, float) * np.ones(n_elem),
        Gf_eff=np.asarray(Gf_eff, float) * np.ones(n_elem),
        Gc0=material.Gc0,
        eps_ras_lin=eps_ras,
        damage_max=material.damage_max,
        enable_compression_damage=material.enable_compression_damage,
        strain_shear_factor=strain_shear_factor,
        min_stiff_factor=min_stiff_factor,
        softening_law=material.softening_law,
    )


def free_expansion_displacement(nodes, eps_ras_value, x_ref, y_ref=0.0):
    """Displacement field of an unconstrained uniform ASR expansion.

    ``u = eps_ras * (x - x_ref, y - y_ref)`` so that eps_total ~= eps_RAS and the
    mechanical strain (hence the stress) starts at zero. Ported from viga.
    """
    U = np.zeros(2 * nodes.shape[0])
    U[0::2] = eps_ras_value * (nodes[:, 0] - x_ref)
    U[1::2] = eps_ras_value * (nodes[:, 1] - y_ref)
    return U
