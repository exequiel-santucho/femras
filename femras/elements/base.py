"""Unified element pre-computation.

Both Q4 and T3 are reduced to the same packed arrays so the rest of the engine
is element-type agnostic and fully vectorisable:

    B        : (n_elem, n_gp, 3, ndof_e)   strain-displacement matrices
    weight   : (n_elem, n_gp)              detJ * gauss_weight * thickness
    dofs     : (n_elem, ndof_e) int        global DOF indices per element
    h_e      : (n_elem,)                    characteristic length per element
    area     : (n_elem,)                    element area (sum of detJ*w)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import q4, t3


@dataclass
class ElementData:
    element_type: str
    n_gp: int
    ndof_e: int
    n_dof: int
    B: np.ndarray
    weight: np.ndarray
    dofs: np.ndarray
    h_e: np.ndarray
    area: np.ndarray


def _dofs_from_conn(elements: np.ndarray, n_nodes_e: int) -> np.ndarray:
    dofs = np.empty((elements.shape[0], 2 * n_nodes_e), dtype=int)
    for k in range(n_nodes_e):
        dofs[:, 2 * k] = 2 * elements[:, k]
        dofs[:, 2 * k + 1] = 2 * elements[:, k] + 1
    return dofs


def precompute(nodes: np.ndarray, elements: np.ndarray, element_type: str,
               thickness: float = 1.0) -> ElementData:
    element_type = element_type.lower().strip()
    n_elem = elements.shape[0]
    n_dof = 2 * nodes.shape[0]

    if element_type == "q4":
        n_gp, ndof_e = q4.N_GP, q4.N_DOF
        gps = q4.gauss_points()
        B = np.zeros((n_elem, n_gp, 3, ndof_e))
        weight = np.zeros((n_elem, n_gp))
        h_e = np.zeros(n_elem)
        for e, conn in enumerate(elements):
            coords = nodes[conn, :]
            h_e[e] = q4.characteristic_length(coords)
            for g, (xi, eta, w) in enumerate(gps):
                Bg, detJ = q4.b_matrix(coords, xi, eta)
                B[e, g] = Bg
                weight[e, g] = detJ * w * thickness
        dofs = _dofs_from_conn(elements, q4.N_NODES)

    elif element_type == "t3":
        n_gp, ndof_e = t3.N_GP, t3.N_DOF
        B = np.zeros((n_elem, n_gp, 3, ndof_e))
        weight = np.zeros((n_elem, n_gp))
        h_e = np.zeros(n_elem)
        for e, conn in enumerate(elements):
            coords = nodes[conn, :]
            Bg, area = t3.b_matrix(coords)
            B[e, 0] = Bg
            weight[e, 0] = area * thickness
            h_e[e] = np.sqrt(area)
        dofs = _dofs_from_conn(elements, t3.N_NODES)

    else:
        raise ValueError("element_type must be 'q4' or 't3'")

    area = weight.sum(axis=1) / thickness
    return ElementData(element_type, n_gp, ndof_e, n_dof, B, weight, dofs, h_e, area)
