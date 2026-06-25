"""4-node bilinear quadrilateral (Q4) with 2x2 Gauss integration.

Ported from viga_rilem.py (shape_functions_Q4, B_matrix_Q4, gauss_points_Q4)
and kept numerically identical.
"""

from __future__ import annotations

import numpy as np

N_GP = 4
N_NODES = 4
N_DOF = 8


def gauss_points():
    g = 1.0 / np.sqrt(3.0)
    return [(-g, -g, 1.0), (g, -g, 1.0), (g, g, 1.0), (-g, g, 1.0)]


def shape_derivatives(xi, eta):
    dN_dxi = 0.25 * np.array([-(1.0 - eta), (1.0 - eta), (1.0 + eta), -(1.0 + eta)])
    dN_deta = 0.25 * np.array([-(1.0 - xi), -(1.0 + xi), (1.0 + xi), (1.0 - xi)])
    return dN_dxi, dN_deta


def b_matrix(coords_elem, xi, eta):
    """Return (B [3x8], detJ) for a Q4 element at natural coords (xi, eta)."""
    dN_dxi, dN_deta = shape_derivatives(xi, eta)

    J = np.zeros((2, 2))
    for i in range(4):
        J[0, 0] += dN_dxi[i] * coords_elem[i, 0]
        J[0, 1] += dN_deta[i] * coords_elem[i, 0]
        J[1, 0] += dN_dxi[i] * coords_elem[i, 1]
        J[1, 1] += dN_deta[i] * coords_elem[i, 1]

    detJ = np.linalg.det(J)
    if detJ <= 0:
        raise ValueError("Q4 element with non-positive Jacobian.")
    invJ = np.linalg.inv(J)

    B = np.zeros((3, 8))
    for i in range(4):
        grad_xy = invJ @ np.array([dN_dxi[i], dN_deta[i]])
        dN_dx, dN_dy = grad_xy
        B[0, 2 * i] = dN_dx
        B[1, 2 * i + 1] = dN_dy
        B[2, 2 * i] = dN_dy
        B[2, 2 * i + 1] = dN_dx
    return B, detJ


def element_area(coords_elem):
    x = coords_elem[:, 0]
    y = coords_elem[:, 1]
    area = 0.0
    for i in range(4):
        j = (i + 1) % 4
        area += x[i] * y[j] - x[j] * y[i]
    return abs(area) / 2.0


def characteristic_length(coords_elem):
    return np.sqrt(element_area(coords_elem))
