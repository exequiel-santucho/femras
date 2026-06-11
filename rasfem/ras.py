"""Alkali-Silica Reaction (ASR/RAS) model.

Two coupled mechanisms, exactly as documented in the reference model:

A) Imposed expansion  ``eps_RAS = xi * eps_ras_lin * [1, 1, 0]``
B) Property degradation ``P = P0 * (1 - beta_P * activity(xi))`` with a floor.

``xi(t)`` in [0, 1] is the reaction-extent variable. It can be imposed directly
or computed from a temporal law (Larive's sigmoid or a simple exponential).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# --------------------------------------------------------------------------
# Temporal laws for the reaction extent xi(t)
# --------------------------------------------------------------------------

def xi_larive(t_days, tau_lat, tau_ch):
    """Larive sigmoid. Matches ``xi_larive`` in viga_rilem.py."""
    t = np.asarray(t_days, dtype=float)
    num = 1.0 - np.exp(-t / tau_ch)
    den = 1.0 + np.exp(-(t - tau_lat) / tau_ch)
    return np.clip(num / den, 0.0, 1.0)


def xi_simple_exp(t_days, tau):
    t = np.asarray(t_days, dtype=float)
    return np.clip(1.0 - np.exp(-t / tau), 0.0, 1.0)


@dataclass
class RASModel:
    """Configurable ASR model shared by every example.

    The defaults reproduce the frozen-xi beam case (R4 concrete). The dam case
    overrides ``expansion_scale``, ``linear_divisor``, the betas and the floors.
    """

    enabled: bool = True

    # How xi is obtained: "imposed" | "larive" | "simple_exp"
    mode: str = "larive"
    xi_imposed: float = 0.0
    age_days: float = 485.0
    tau_lat: float = 188.83
    tau_ch: float = 161.89
    tau: float = 200.0

    # Imposed expansion
    eps_inf_vol: float = 0.0042      # volumetric ultimate expansion
    linear_divisor: float = 3.0      # eps_lin = eps_inf_vol / divisor
    expansion_scale: float = 1.0     # extra knob used by the dam case
    activity_power: float = 1.0      # activity(xi) = xi**power

    # Degradation coefficients
    beta_E: float = 0.15
    beta_ft: float = 0.25
    beta_fc: float = 0.10
    beta_Gf: float = 0.20

    # Numerical floors (fraction of the base property)
    E_min_factor: float = 0.20
    ft_min_factor: float = 0.10
    fc_min_factor: float = 0.20
    Gf_min_factor: float = 0.10

    @property
    def eps_ras_lin_inf(self) -> float:
        """Ultimate linear ASR strain (one direction)."""
        return self.expansion_scale * self.eps_inf_vol / self.linear_divisor

    def xi_at(self, t_days: float | None = None) -> float:
        """Reaction extent. Uses ``age_days`` when ``t_days`` is None."""
        if not self.enabled:
            return 0.0
        mode = self.mode.lower().strip()
        if mode == "imposed":
            return float(np.clip(self.xi_imposed, 0.0, 1.0))
        t = self.age_days if t_days is None else t_days
        if mode == "larive":
            return float(xi_larive(t, self.tau_lat, self.tau_ch))
        if mode == "simple_exp":
            return float(xi_simple_exp(t, self.tau))
        raise ValueError("RAS mode must be 'imposed', 'larive' or 'simple_exp'")

    def eps_ras_lin(self, xi) -> np.ndarray | float:
        """Linear ASR strain for a given (scalar or array) xi."""
        if not self.enabled:
            return 0.0 * np.asarray(xi, dtype=float)
        return self.eps_ras_lin_inf * np.asarray(xi, dtype=float)

    def degraded_properties(self, material, xi):
        """Return (E_eff, ft_eff, fc_eff, Gf_eff) for scalar or array xi.

        Reproduces ``degraded_properties`` of the legacy beam script when
        ``activity_power == 1`` and ``expansion_scale == 1``.
        """
        xi = np.asarray(xi, dtype=float)
        if not self.enabled:
            xi = np.zeros_like(xi)
        act = np.power(np.clip(xi, 0.0, 1.0), self.activity_power)

        E = material.E0 * (1.0 - self.beta_E * act)
        ft = material.ft0 * (1.0 - self.beta_ft * act)
        fc = material.fc0 * (1.0 - self.beta_fc * act)
        Gf = material.Gf0 * (1.0 - self.beta_Gf * act)

        E = np.maximum(E, material.E0 * self.E_min_factor)
        ft = np.maximum(ft, material.ft0 * self.ft_min_factor)
        fc = np.maximum(fc, material.fc0 * self.fc_min_factor)
        Gf = np.maximum(Gf, material.Gf0 * self.Gf_min_factor)
        return E, ft, fc, Gf
