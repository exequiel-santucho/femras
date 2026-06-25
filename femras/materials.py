"""Linear-elastic constitutive matrices and the base damage material.

The elastic matrix is split as ``C(E, nu) = E * Chat(nu)`` so that, when the
Young modulus varies element by element (because of ASR degradation), the
stress can be obtained with a single fixed 3x3 matrix and a per-element scalar
multiplication. This is what makes the vectorised constitutive update cheap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def elastic_matrix_unit(nu: float, problem_type: str = "plane_stress") -> np.ndarray:
    """Elastic matrix for ``E = 1``. Multiply by E to get the real one.

    Matches ``elastic_matrix`` in the legacy scripts when scaled by E.
    """
    if problem_type == "plane_stress":
        c = 1.0 / (1.0 - nu**2)
        return c * np.array([
            [1.0, nu, 0.0],
            [nu, 1.0, 0.0],
            [0.0, 0.0, (1.0 - nu) / 2.0],
        ])
    if problem_type == "plane_strain":
        c = 1.0 / ((1.0 + nu) * (1.0 - 2.0 * nu))
        return c * np.array([
            [1.0 - nu, nu, 0.0],
            [nu, 1.0 - nu, 0.0],
            [0.0, 0.0, (1.0 - 2.0 * nu) / 2.0],
        ])
    raise ValueError("problem_type must be 'plane_stress' or 'plane_strain'")


def elastic_matrix(E: float, nu: float, problem_type: str = "plane_stress") -> np.ndarray:
    """Full elastic matrix ``C(E, nu)`` (kept for tests / readability)."""
    return E * elastic_matrix_unit(nu, problem_type)


@dataclass
class MaterialDamage:
    """Base (undamaged, ASR-free) material properties.

    Units follow the legacy examples: stresses/moduli in MPa, energies in N/mm,
    lengths in mm.
    """

    E0: float = 38100.0
    nu: float = 0.20
    ft0: float = 4.0
    fc0: float = 51.2
    Gf0: float = 0.10
    Gc0: float = 10.0
    damage_max: float = 0.99999
    enable_compression_damage: bool = False
    softening_law: str = "exponential"  # "exponential" (beam) or "linear" (dam)
