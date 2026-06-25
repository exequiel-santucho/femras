"""Unit tests for the constitutive building blocks."""

import numpy as np

from femras.materials import MaterialDamage, elastic_matrix, elastic_matrix_unit
from femras.ras import RASModel, xi_larive
from femras.elements import q4, t3


def test_elastic_split():
    nu = 0.2
    E = 30000.0
    assert np.allclose(elastic_matrix(E, nu, "plane_stress"),
                       E * elastic_matrix_unit(nu, "plane_stress"))


def test_xi_larive_bounds():
    assert xi_larive(0.0, 188.83, 161.89) >= 0.0
    assert xi_larive(1e6, 188.83, 161.89) <= 1.0 + 1e-9
    # monotonic increasing in time
    t = np.linspace(0, 2000, 50)
    xi = xi_larive(t, 188.83, 161.89)
    assert np.all(np.diff(xi) >= -1e-12)


def test_degradation_floors_and_monotonic():
    mat = MaterialDamage()
    ras = RASModel(enabled=True, beta_E=0.25, beta_ft=0.45, beta_Gf=0.55)
    E0, ft0, *_ = ras.degraded_properties(mat, 0.0)
    E1, ft1, *_ = ras.degraded_properties(mat, 1.0)
    assert np.isclose(E0, mat.E0)
    assert E1 < E0 and ft1 < ft0
    assert E1 >= mat.E0 * ras.E_min_factor - 1e-9


def test_t3_b_matrix_area():
    coords = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    B, area = t3.b_matrix(coords)
    assert np.isclose(area, 0.5)
    assert B.shape == (3, 6)


def test_q4_unit_square_jacobian():
    coords = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0]])
    B, detJ = q4.b_matrix(coords, 0.0, 0.0)
    assert np.isclose(detJ, 1.0)        # area 4 -> detJ = 4 / 4 = 1
    assert B.shape == (3, 8)
