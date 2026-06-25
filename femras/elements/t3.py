"""3-node constant-strain triangle (T3) with 1-point integration.

Ported from presa_ras.py (precompute_t3_data) and kept numerically identical.
The single Gauss point has weight 1 and the integration weight is the area.
"""

from __future__ import annotations

import numpy as np

N_GP = 1
N_NODES = 3
N_DOF = 6


def signed_area(coords):
    x1, y1 = coords[0]
    x2, y2 = coords[1]
    x3, y3 = coords[2]
    return 0.5 * ((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1))


def b_matrix(coords_elem):
    """Return (B [3x6], area). B is constant over the element."""
    A_signed = signed_area(coords_elem)
    A = abs(A_signed)
    if A <= 1e-12:
        raise ValueError("T3 element with non-positive area.")
    if A_signed < 0.0:
        raise ValueError("T3 element with inverted node ordering.")

    (x1, y1), (x2, y2), (x3, y3) = coords_elem
    b1, b2, b3 = y2 - y3, y3 - y1, y1 - y2
    c1, c2, c3 = x3 - x2, x1 - x3, x2 - x1
    B = (1.0 / (2.0 * A_signed)) * np.array([
        [b1, 0.0, b2, 0.0, b3, 0.0],
        [0.0, c1, 0.0, c2, 0.0, c3],
        [c1, b1, c2, b2, c3, b3],
    ])
    return B, A


def characteristic_length(coords_elem):
    return np.sqrt(abs(signed_area(coords_elem)))
