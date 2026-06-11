"""External forces: self weight and hydrostatic pressure on a vertical face.

Ported from presa_ras.py (element_body_force, hydro_edge_force,
assemble_external_force). Used by the load-controlled (overtopping) driver,
where the control parameter is the water level ``Hwater``.
"""

from __future__ import annotations

import numpy as np


def body_force_t3(elem_area, thickness, gamma_c):
    """Equivalent nodal self-weight (downward) for a T3 element -> (6,)."""
    fnode = (thickness * elem_area / 3.0) * np.array([0.0, -gamma_c])
    fe = np.zeros(6)
    fe[0:2] = fe[2:4] = fe[4:6] = fnode
    return fe


def hydro_edge_force(p1, p2, Hwater, gamma_w, thickness, x_face_tol=1e-7):
    """Hydrostatic nodal force on a vertical edge (pressure toward +x) -> (4,)."""
    x1, y1 = p1
    x2, y2 = p2
    if abs(x1) > x_face_tol or abs(x2) > x_face_tol:
        return np.zeros(4)
    ylow, yhigh = min(y1, y2), max(y1, y2)
    if Hwater <= ylow:
        return np.zeros(4)
    ysub1, ysub2 = ylow, min(yhigh, Hwater)
    if ysub2 <= ysub1:
        return np.zeros(4)
    Lsub = ysub2 - ysub1
    fe = np.zeros(4)
    for s, w in [(-1.0 / np.sqrt(3.0), 1.0), (1.0 / np.sqrt(3.0), 1.0)]:
        y = 0.5 * (1.0 - s) * ysub1 + 0.5 * (1.0 + s) * ysub2
        p = gamma_w * max(Hwater - y, 0.0)
        N1, N2 = 0.5 * (1.0 - s), 0.5 * (1.0 + s)
        Nmat = np.array([[N1, 0.0, N2, 0.0], [0.0, N1, 0.0, N2]])
        fe += (Nmat.T @ np.array([p, 0.0])) * thickness * (Lsub / 2.0) * w
    return fe


def assemble_external_force(nodes, elem, up_edges, Hwater, *, gamma_c, gamma_w,
                            thickness):
    """Global external force = self weight + hydrostatic thrust at level Hwater."""
    n_dof = 2 * len(nodes)
    F = np.zeros(n_dof)
    # self weight (constant)
    for e in range(elem.dofs.shape[0]):
        fe = body_force_t3(elem.area[e], thickness, gamma_c)
        F[elem.dofs[e]] += fe
    # hydrostatic thrust on the upstream face
    for i, j in up_edges:
        fe = hydro_edge_force(nodes[i], nodes[j], Hwater, gamma_w, thickness)
        dofs = np.array([2 * i, 2 * i + 1, 2 * j, 2 * j + 1], dtype=int)
        F[dofs] += fe
    return F
