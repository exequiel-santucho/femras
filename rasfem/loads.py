"""External forces: self weight and hydrostatic pressure on a polygon face.

Ported from presa_ras.py (element_body_force, hydro_edge_force,
assemble_external_force). Used by the load-controlled (overtopping) driver,
where the control parameter is the water level ``Hwater``.

The face normal (direction of pressure thrust) is passed explicitly, defaulting
to [1, 0] (historic +x direction for a vertical upstream face at x=0).
"""

from __future__ import annotations

import numpy as np


def body_force_t3(elem_area, thickness, gamma_c):
    """Equivalent nodal self-weight (downward) for a T3 element -> (6,)."""
    fnode = (thickness * elem_area / 3.0) * np.array([0.0, -gamma_c])
    fe = np.zeros(6)
    fe[0:2] = fe[2:4] = fe[4:6] = fnode
    return fe


def hydro_edge_force(p1, p2, Hwater, gamma_w, thickness, face_normal=None):
    """Hydrostatic nodal force on a boundary edge -> (4,).

    ``face_normal`` is the unit inward normal of the hydraulic face (direction
    the water pushes into the structure).  Defaults to [1, 0] for backward
    compatibility with a vertical upstream face at x = 0.
    The edge is assumed to already belong to the hydraulic face; no coordinate
    filtering is performed here.
    """
    if face_normal is None:
        face_normal = np.array([1.0, 0.0])
    face_normal = np.asarray(face_normal, float)
    y1, y2 = float(p1[1]), float(p2[1])
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
        fe += (Nmat.T @ (p * face_normal)) * thickness * (Lsub / 2.0) * w
    return fe


def assemble_external_force(nodes, elem, up_edges, Hwater, *, gamma_c, gamma_w,
                            thickness, face_normal=None):
    """Global external force = self weight + hydrostatic thrust at level Hwater."""
    if face_normal is None:
        face_normal = np.array([1.0, 0.0])
    n_dof = 2 * len(nodes)
    F = np.zeros(n_dof)
    for e in range(elem.dofs.shape[0]):
        fe = body_force_t3(elem.area[e], thickness, gamma_c)
        F[elem.dofs[e]] += fe
    for i, j in up_edges:
        fe = hydro_edge_force(nodes[i], nodes[j], Hwater, gamma_w, thickness, face_normal)
        dofs = np.array([2 * i, 2 * i + 1, 2 * j, 2 * j + 1], dtype=int)
        F[dofs] += fe
    return F
