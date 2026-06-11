"""Vectorised global assembly.

The COO row/column index pattern depends only on the connectivity, so it is
built once. Every Newton iteration only recomputes the element matrices/forces
(via the vectorised constitutive) and the sparse ``vals``; the index arrays are
reused. The internal-force-only path is used by the line search, which does not
need the tangent.
"""

from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix

from .backend import _NUMBA_KERNELS, _fe_numba, _ke_numba
from .damage import ConstitutiveModel, GPState
from .elements.base import ElementData


class Assembler:
    def __init__(self, elem: ElementData, backend: str = "numpy"):
        self.elem = elem
        self.n_dof = elem.n_dof
        self.backend = backend
        # Precompute COO scatter indices for the element stiffness blocks.
        dofs = elem.dofs                                  # (ne, nd)
        ne, nd = dofs.shape
        rows = np.repeat(dofs, nd, axis=1).reshape(ne, nd, nd)
        cols = np.tile(dofs, (1, nd)).reshape(ne, nd, nd)
        self._rows = rows.ravel()
        self._cols = cols.ravel()
        # Transposed B for B^T (...) products: (ne, ng, nd, 3)
        self._Bt = np.ascontiguousarray(elem.B.transpose(0, 1, 3, 2))
        self._dofs_flat = dofs.ravel()

    def strains(self, U: np.ndarray) -> np.ndarray:
        """Total strain at every Gauss point: (n_elem, n_gp, 3)."""
        Ue = U[self.elem.dofs]                            # (ne, nd)
        return np.einsum("egij,ej->egi", self.elem.B, Ue)

    def internal_force(self, U, model: ConstitutiveModel, old: GPState,
                       tangent_mode=None):
        """Return (Fint, damage, new_state). No tangent (cheap, for line search)."""
        strain = self.strains(U)
        sigma, damage, new = model.evaluate(strain, old)
        w = self.elem.weight                              # (ne, ng)
        if self.backend == "numba" and _NUMBA_KERNELS:
            Fe = _fe_numba(self._Bt, sigma, w)
        else:
            Fe = np.einsum("egij,egj,eg->ei", self._Bt, sigma, w)
        Fint = np.zeros(self.n_dof)
        np.add.at(Fint, self._dofs_flat, Fe.ravel())
        return Fint, damage, new

    def tangent_and_force(self, U, model: ConstitutiveModel, old: GPState,
                          tangent_mode="numerical_hybrid"):
        """Return (Kt csr, Fint, damage, new_state)."""
        strain = self.strains(U)
        sigma, Ct, damage, new = model.evaluate_with_tangent(strain, old, tangent_mode)
        w = self.elem.weight
        if self.backend == "numba" and _NUMBA_KERNELS:
            Ke = _ke_numba(self._Bt, self.elem.B, Ct, w)
            Fe = _fe_numba(self._Bt, sigma, w)
        else:
            # Ke = sum_gp B^T Ct B * w
            BtC = np.einsum("egij,egjk->egik", self._Bt, Ct)        # (ne,ng,nd,3)
            Ke = np.einsum("egik,egkl,eg->eil", BtC, self.elem.B, w)  # (ne,nd,nd)
            Fe = np.einsum("egij,egj,eg->ei", self._Bt, sigma, w)
        Fint = np.zeros(self.n_dof)
        np.add.at(Fint, self._dofs_flat, Fe.ravel())
        Kt = csr_matrix((Ke.ravel(), (self._rows, self._cols)),
                        shape=(self.n_dof, self.n_dof))
        return Kt, Fint, damage, new
