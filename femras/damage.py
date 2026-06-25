"""Vectorised scalar-damage + ASR constitutive update.

This is the unified version of ``update_damage_material`` (viga_rilem.py) and
``material_response`` (presa_ras.py). All Gauss points are evaluated at once on
NumPy arrays, which removes the per-point Python objects and the per-iteration
``deepcopy`` that dominated the runtime of the legacy scripts.

Model (per Gauss point):
    eps_mec = eps_total - eps_RAS
    sigma   = (1 - d) * E_eff * Chat(nu) @ eps_mec
with ``d`` an exponential tensile-damage law regularised by fracture energy:
    eps0 = ft/E,   epsf = Gf/(ft*h_e),   d = 1 - (eps0/kappa) exp(-(kappa-eps0)/(epsf-eps0))

The ``strain_shear_factor`` reproduces the (different) conventions of the two
legacy examples: 1.0 for the beam, 0.5 for the dam (tensorial shear strain).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .materials import elastic_matrix_unit


@dataclass
class GPState:
    """Gauss-point history, packed as arrays of shape (n_elem, n_gp).

    Copying this state to accept/reject a Newton step is a handful of cheap
    ``ndarray.copy()`` calls -- not a ``deepcopy`` of thousands of objects.
    """

    kappa_t: np.ndarray
    kappa_c: np.ndarray
    damage_t: np.ndarray
    damage_c: np.ndarray

    @classmethod
    def zeros(cls, n_elem: int, n_gp: int) -> "GPState":
        z = lambda: np.zeros((n_elem, n_gp))
        return cls(z(), z(), z(), z())

    def copy(self) -> "GPState":
        return GPState(self.kappa_t.copy(), self.kappa_c.copy(),
                       self.damage_t.copy(), self.damage_c.copy())


def principal_values_2d(vec, shear_factor=1.0):
    """Principal values of a 2D symmetric tensor stored as [xx, yy, xy].

    ``shear_factor`` scales the off-diagonal term (1.0 for stress / beam-style
    strain, 0.5 for tensorial shear strain).
    """
    xx = vec[..., 0]
    yy = vec[..., 1]
    xy = shear_factor * vec[..., 2]
    avg = 0.5 * (xx + yy)
    rad = np.sqrt((0.5 * (xx - yy)) ** 2 + xy ** 2)
    return avg + rad, avg - rad


def _equivalent_tensile_strain(strain, shear_factor):
    e1, e2 = principal_values_2d(strain, shear_factor)
    return np.sqrt(np.maximum(e1, 0.0) ** 2 + np.maximum(e2, 0.0) ** 2)


def _equivalent_compressive_strain(strain, shear_factor):
    e1, e2 = principal_values_2d(strain, shear_factor)
    return np.maximum(np.maximum(-e1, -e2), 0.0)


@dataclass
class ConstitutiveModel:
    """Holds everything needed to evaluate stress/tangent over the whole mesh.

    Per-element effective ASR properties (E_eff, ft_eff, ...) and the linear ASR
    strain are precomputed once per analysis stage and broadcast over the Gauss
    points. ``nu`` and ``h_e`` complete the set.
    """

    nu: float
    problem_type: str
    h_e: np.ndarray            # (n_elem,)
    E_eff: np.ndarray          # (n_elem,)
    ft_eff: np.ndarray         # (n_elem,)
    fc_eff: np.ndarray         # (n_elem,)
    Gf_eff: np.ndarray         # (n_elem,)
    Gc0: float
    eps_ras_lin: np.ndarray    # (n_elem,)
    damage_max: float = 0.99999
    enable_compression_damage: bool = False
    strain_shear_factor: float = 1.0
    min_stiff_factor: float = 1.0e-8
    num_tangent_rel: float = 1.0e-7
    num_tangent_abs: float = 1.0e-10
    # "exponential" (beam/viga_rilem) or "linear" (dam/presa_ras)
    softening_law: str = "exponential"

    def __post_init__(self):
        self.Dhat = elastic_matrix_unit(self.nu, self.problem_type)  # (3,3)
        # column vectors for broadcasting over (n_elem, n_gp)
        self._E = self.E_eff[:, None]
        self._ft = self.ft_eff[:, None]
        self._fc = self.fc_eff[:, None]
        self._Gf = self.Gf_eff[:, None]
        self._he = self.h_e[:, None]
        eps = self.eps_ras_lin[:, None]
        self._eps_ras = np.stack([eps, eps, np.zeros_like(eps)], axis=-1)  # (ne,1,3)

    # -- stress and updated history ----------------------------------------
    def evaluate(self, strain, old: GPState):
        """Return (sigma, damage, new_state) for total strain (n_elem,n_gp,3)."""
        sf = self.strain_shear_factor
        strain_mec = strain - self._eps_ras
        sigma_eff = self._E[..., None] * np.einsum("ij,egj->egi", self.Dhat, strain_mec)
        s1, _s2 = principal_values_2d(sigma_eff, 1.0)

        # tension
        eps_eq_t = _equivalent_tensile_strain(strain_mec, sf)
        activate_t = (eps_eq_t > old.kappa_t) & (s1 > 0.0)
        kappa_t = np.where(activate_t, eps_eq_t, old.kappa_t)

        eps0_t = self._ft / self._E
        loading_t = kappa_t > eps0_t
        if self.softening_law == "linear":
            # Linear softening: d = ef*(kappa-eps0)/(kappa*(ef-eps0))
            # ef = eps0 + 2*Gf/(ft*he)  (factor 2 from triangle area under linear curve)
            ef_t = eps0_t + 2.0 * self._Gf / (self._ft * self._he)
            ef_t = np.where(ef_t <= eps0_t * 1.0000001, eps0_t * 1.0001, ef_t)
            with np.errstate(divide="ignore", invalid="ignore"):
                d_t = ef_t * (kappa_t - eps0_t) / (kappa_t * (ef_t - eps0_t))
            d_t = np.where(kappa_t >= ef_t, 1.0, d_t)  # fully damaged beyond ef
        else:
            # Exponential softening: d = 1 - (eps0/kappa)*exp(-A*(kappa-eps0))
            eps_f_t = self._Gf / (self._ft * self._he)
            eps_f_t = np.where(eps_f_t <= eps0_t, 1.05 * eps0_t, eps_f_t)
            with np.errstate(divide="ignore", invalid="ignore"):
                A_t = 1.0 / (eps_f_t - eps0_t)
                d_t = 1.0 - (eps0_t / kappa_t) * np.exp(-A_t * (kappa_t - eps0_t))
        d_t = np.where(loading_t, d_t, 0.0)
        damage_t = np.maximum(old.damage_t, d_t)

        # compression (optional)
        if self.enable_compression_damage:
            _s1c, s2c = principal_values_2d(sigma_eff, 1.0)
            eps_eq_c = _equivalent_compressive_strain(strain_mec, sf)
            activate_c = (eps_eq_c > old.kappa_c) & (s2c < 0.0)
            kappa_c = np.where(activate_c, eps_eq_c, old.kappa_c)
            eps0_c = self._fc / self._E
            eps_f_c = self.Gc0 / (self._fc * self._he)
            eps_f_c = np.where(eps_f_c <= eps0_c, 1.05 * eps0_c, eps_f_c)
            with np.errstate(divide="ignore", invalid="ignore"):
                A_c = 1.0 / (eps_f_c - eps0_c)
                d_c = 1.0 - (eps0_c / kappa_c) * np.exp(-A_c * (kappa_c - eps0_c))
            d_c = np.where(kappa_c > eps0_c, d_c, 0.0)
            damage_c = np.maximum(old.damage_c, d_c)
        else:
            kappa_c = old.kappa_c
            damage_c = old.damage_c

        damage_t = np.clip(damage_t, 0.0, self.damage_max)
        damage_c = np.clip(damage_c, 0.0, self.damage_max)
        damage = 1.0 - (1.0 - damage_t) * (1.0 - damage_c)
        damage = np.clip(damage, 0.0, self.damage_max)

        sigma = (1.0 - damage)[..., None] * sigma_eff
        new = GPState(kappa_t, kappa_c, damage_t, damage_c)
        return sigma, damage, new

    def _stress_only(self, strain, old: GPState):
        sigma, _d, _s = self.evaluate(strain, old)
        return sigma

    # -- stress + consistent-ish tangent -----------------------------------
    def evaluate_with_tangent(self, strain, old: GPState, tangent_mode="numerical_hybrid"):
        """Return (sigma, Ct, damage, new_state).

        ``Ct`` has shape (n_elem, n_gp, 3, 3). Modes:
            elastic            -> Ct = E_eff * Chat
            secant             -> Ct = (1-d) E_eff * Chat
            numerical          -> finite-difference tangent everywhere
            numerical_hybrid   -> elastic where undamaged, numerical elsewhere
        """
        sigma0, damage, new = self.evaluate(strain, old)
        ne, ng = damage.shape
        D_el = self._E[..., None, None] * self.Dhat[None, None]  # (ne,ng,3,3) via broadcast
        D_el = np.broadcast_to(D_el, (ne, ng, 3, 3))

        mode = tangent_mode.lower().strip()
        if mode == "elastic":
            return sigma0, D_el.copy(), damage, new
        if mode == "secant":
            Ct = (1.0 - damage)[..., None, None] * D_el + self.min_stiff_factor * D_el
            return sigma0, Ct, damage, new
        if mode not in ("numerical", "numerical_hybrid"):
            raise ValueError("tangent_mode must be elastic/secant/numerical/numerical_hybrid")

        # numerical tangent (finite differences on the 3 strain components)
        norm_eps = np.maximum(np.linalg.norm(strain, axis=-1), 1.0e-8)
        h = np.maximum(self.num_tangent_rel * norm_eps, self.num_tangent_abs)  # (ne,ng)
        Ct = np.empty((ne, ng, 3, 3))
        for j in range(3):
            strain_p = strain.copy()
            strain_p[..., j] += h
            sigma_p = self._stress_only(strain_p, old)
            Ct[..., :, j] = (sigma_p - sigma0) / h[..., None]
        Ct = Ct + self.min_stiff_factor * D_el

        if mode == "numerical_hybrid":
            healthy = (old.damage_t + old.damage_c <= 1.0e-12) & (damage <= 1.0e-12)
            Ct = np.where(healthy[..., None, None], D_el, Ct)
        return sigma0, Ct, damage, new
