"""Compute-backend abstraction for the linear solve and optional JIT.

The expensive parts of an implicit damage analysis are (1) the per-element
constitutive/assembly work and (2) the sparse linear solve. The core is already
vectorised with NumPy, which is the main CPU win over the legacy scripts. This
module adds optional accelerators that degrade gracefully when not installed:

* ``numba``  -> JIT for hot scalar kernels (detected, used where it helps).
* ``cupy``   -> GPU sparse solve, switched on automatically only for large
                systems where transferring to the GPU actually pays off.

Select with ``solver.backend = auto | numpy | numba | gpu`` in the config.
"""

from __future__ import annotations

import numpy as np
from scipy.sparse.linalg import spsolve

# Threshold (number of free DOFs) above which the GPU solve is worthwhile.
GPU_MIN_DOF = 50_000


def has_numba() -> bool:
    try:
        import numba  # noqa: F401
        return True
    except Exception:
        return False


def has_cupy() -> bool:
    try:
        import cupy  # noqa: F401
        return True
    except Exception:
        return False


def resolve_backend(name: str, n_free: int) -> str:
    """Map the requested backend to an effective one given availability/size."""
    name = (name or "auto").lower()
    if name == "gpu":
        return "gpu" if has_cupy() else "numpy"
    if name == "numba":
        return "numba" if has_numba() else "numpy"
    if name == "auto":
        if n_free >= GPU_MIN_DOF and has_cupy():
            return "gpu"
        return "numpy"
    return "numpy"


def linsolve(K, b, backend="numpy"):
    """Solve ``K x = b`` for a CSR matrix ``K`` using the chosen backend."""
    if backend == "gpu":
        return _linsolve_gpu(K, b)
    return spsolve(K, b)


def _linsolve_gpu(K, b):
    import cupy as cp
    from cupyx.scipy.sparse import csr_matrix as cp_csr
    from cupyx.scipy.sparse.linalg import spsolve as cp_spsolve

    Kg = cp_csr(K)
    bg = cp.asarray(b)
    xg = cp_spsolve(Kg, bg)
    return cp.asnumpy(xg)


# ── Numba JIT kernels for assembly hot loops (optional) ─────────────────────
#
# Activated only when ``solver.backend = numba`` is set in the config AND the
# ``numba`` optional dependency is installed (``pip install femras[numba]``).
# Fall back to NumPy einsum silently if not available.
#
# Both kernels parallelise over the element axis (prange) and fuse the
# intermediate BtC product to avoid allocating a large temporary array.
# cache=True means the compiled code is stored in __pycache__ and reused across
# runs, so the one-time JIT cost (~1-3 s) only occurs the first time.

_NUMBA_KERNELS: bool = False
_ke_numba = None
_fe_numba = None

try:
    from numba import njit, prange as _prange

    @njit(parallel=True, cache=True, fastmath=True)
    def _ke_numba_impl(Bt, B, Ct, w):
        """Ke[e] = Σ_gp w[e,gp] * Bt[e,gp] @ Ct[e,gp] @ B[e,gp]  (parallel over e)."""
        ne = Bt.shape[0]
        ng = Bt.shape[1]
        nd = Bt.shape[2]
        Ke = np.zeros((ne, nd, nd))
        for e in _prange(ne):
            for gp in range(ng):
                wgp = w[e, gp]
                for i in range(nd):
                    for k in range(3):
                        Bt_ik = Bt[e, gp, i, k]
                        for kl in range(3):
                            c = Bt_ik * Ct[e, gp, k, kl] * wgp
                            for j in range(nd):
                                Ke[e, i, j] += c * B[e, gp, kl, j]
        return Ke

    @njit(parallel=True, cache=True, fastmath=True)
    def _fe_numba_impl(Bt, sigma, w):
        """Fe[e] = Σ_gp w[e,gp] * Bt[e,gp] @ sigma[e,gp]  (parallel over e)."""
        ne = Bt.shape[0]
        ng = Bt.shape[1]
        nd = Bt.shape[2]
        Fe = np.zeros((ne, nd))
        for e in _prange(ne):
            for gp in range(ng):
                wgp = w[e, gp]
                for i in range(nd):
                    s = 0.0
                    for k in range(3):
                        s += Bt[e, gp, i, k] * sigma[e, gp, k]
                    Fe[e, i] += s * wgp
        return Fe

    _ke_numba = _ke_numba_impl
    _fe_numba = _fe_numba_impl
    _NUMBA_KERNELS = True
except Exception:
    pass
