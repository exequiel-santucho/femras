import numpy as np
import matplotlib.pyplot as plt
import csv
import json

from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from copy import deepcopy
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


# ============================================================
# MEF 2D - VIGA ENTALLADA
# DAÑO ESCALAR MECANICO + RAS SEGUN MODELO SIMPLIFICADO DEFINIDO
#
# Modelo constitutivo:
#   sigma = (1-dm) D(E(xi),nu) (eps_total - eps_RAS)
#   eps_RAS = eps_RAS_inf * xi * [1,1,0]
#
# La RAS:
#   - introduce deformacion expansiva inicial
#   - degrada E, ft, fc y Gf
# El daño mecanico se calcula con eps_mec = eps_total - eps_RAS.
# ============================================================


@dataclass
class MaterialDamage:
    # Valores por defecto elegidos para R4:
    # Del paper: G=15875 MPa, nu=0.20 -> E=2G(1+nu)=38100 MPa
    E0: float = 38100.0
    nu: float = 0.20
    ft0: float = 4.0
    fc0: float = 51.2
    Gf0: float = 0.10
    Gc0: float = 10.0
    damage_max: float = 0.99999
    enable_compression_damage: bool = False


@dataclass
class GPState:
    # Variables de daño mecanico
    kappa_t: float = 0.0
    kappa_c: float = 0.0
    damage_t: float = 0.0
    damage_c: float = 0.0
    damage: float = 0.0

    # Variables mecanicas
    stress: np.ndarray = None
    strain: np.ndarray = None        # deformacion total
    strain_mec: np.ndarray = None    # deformacion mecanica = strain - eps_ras

    # Variables RAS y propiedades degradadas
    xi_ras: float = 0.0
    eps_ras: np.ndarray = None
    E_eff: float = 0.0
    ft_eff: float = 0.0
    fc_eff: float = 0.0
    Gf_eff: float = 0.0


@dataclass
class SolverOptions:
    """
    Opciones numéricas principales.

    tangent_mode:
        "numerical_hybrid"  -> por defecto. Usa D0 si el punto está sano y
                               tangente numérica cuando aparece daño.
        "numerical"         -> tangente numérica siempre. Más caro.
        "secant"            -> matriz secante (1-d)D0. Más rápido, menos robusto.
        "elastic"           -> matriz D0. Útil solo como prueba.

    step_control:
        "adaptive" -> por defecto. Si un paso falla, lo reduce y reintenta.
        "fixed"    -> pasos fijos. Puede activar substepping si falla.
    """
    tangent_mode: str = "numerical_hybrid"
    min_stiff_factor: float = 1.0e-8
    numerical_tangent_rel_step: float = 1.0e-7
    numerical_tangent_abs_step: float = 1.0e-10

    step_control: str = "adaptive"
    fixed_n_steps: int = 120
    fixed_allow_substepping: bool = True

    delta_target: float = -0.30
    delta_step_initial: float = -0.0010
    delta_step_min: float = -0.000025
    delta_step_max: float = -0.0020
    grow_factor: float = 1.15
    shrink_factor: float = 0.5
    max_accepted_steps: int = 500

    max_iter: int = 40
    tol_res_abs: float = 1.0e-4
    tol_res_rel: float = 1.0e-6
    tol_du: float = 1.0e-8

    stop_if_damage_exceeds: bool = False
    damage_limit_to_stop: float = 0.99999

    load_patch_mode: str = "three_nodes_centered"
    line_search_alphas: tuple = (1.0, 0.5, 0.25, 0.10, 0.05, 0.025, 0.01, 0.005)
    line_search_max_worsening: float = 5.0


@dataclass
class RASOptions:
    """
    Opciones del modelo RAS definido por nosotros.

    enabled:
        Si False, xi=0 y eps_RAS=0.

    mode:
        "imposed_xi" -> usa xi_final directamente.
        "time_law"   -> calcula xi segun edad y ley temporal.

    time_law:
        "larive"     -> ley con tau_lat y tau_ch.
        "simple_exp" -> xi = 1 - exp(-t/tau).
    """
    enabled: bool = True
    mode: str = "time_law"
    time_law: str = "larive"

    # Hormigon/edad a ensayar. Por defecto R4 a 485 dias.
    concrete_name: str = "R4"
    age_days: float = 485.0
    xi_final: float = 0.0

    # Parametros cineticos R4 del paper
    tau_lat: float = 188.83
    tau_ch: float = 161.89
    tau: float = 200.0

    # eps_inf_vol del paper para R4. En nuestro modelo 2D se usa eps_inf_vol/3.
    eps_inf_vol: float = 0.0042

    # Degradacion de propiedades del modelo simplificado. Calibrables.
    beta_E: float = 0.15
    beta_ft: float = 0.25
    beta_fc: float = 0.10
    beta_Gf: float = 0.20

    # Pisos numericos
    E_min_factor: float = 0.20
    ft_min_factor: float = 0.10
    fc_min_factor: float = 0.20
    Gf_min_factor: float = 0.10

    # Para esta primera version integrada se ensaya con xi congelado.
    evolve_during_flexion: bool = False

    @property
    def eps_ras_inf(self):
        return self.eps_inf_vol / 3.0


# ============================================================
# MATRIZ ELASTICA
# ============================================================

def elastic_matrix(E, nu, problem_type="plane_stress"):
    if problem_type == "plane_stress":
        c = E / (1.0 - nu**2)
        return c * np.array([
            [1.0, nu, 0.0],
            [nu, 1.0, 0.0],
            [0.0, 0.0, (1.0 - nu) / 2.0]
        ])

    if problem_type == "plane_strain":
        c = E / ((1.0 + nu) * (1.0 - 2.0 * nu))
        return c * np.array([
            [1.0 - nu, nu, 0.0],
            [nu, 1.0 - nu, 0.0],
            [0.0, 0.0, (1.0 - 2.0 * nu) / 2.0]
        ])

    raise ValueError("problem_type debe ser plane_stress o plane_strain")


# ============================================================
# FUNCIONES RAS
# ============================================================

def xi_larive(t_days, tau_lat, tau_ch):
    t = np.asarray(t_days, dtype=float)
    num = 1.0 - np.exp(-t / tau_ch)
    den = 1.0 + np.exp(-(t - tau_lat) / tau_ch)
    return np.clip(num / den, 0.0, 1.0)


def xi_from_ras_options(ras_options):
    if not ras_options.enabled:
        return 0.0

    mode = ras_options.mode.lower().strip()

    if mode == "imposed_xi":
        return float(np.clip(ras_options.xi_final, 0.0, 1.0))

    if mode == "time_law":
        law = ras_options.time_law.lower().strip()
        t = ras_options.age_days

        if law == "simple_exp":
            xi = 1.0 - np.exp(-t / ras_options.tau)
        elif law == "larive":
            xi = xi_larive(t, ras_options.tau_lat, ras_options.tau_ch)
        else:
            raise ValueError("time_law debe ser 'larive' o 'simple_exp'")

        return float(np.clip(xi, 0.0, 1.0))

    raise ValueError("RAS mode debe ser 'imposed_xi' o 'time_law'")


def degraded_properties(material, ras_options, xi):
    if not ras_options.enabled:
        xi = 0.0

    E_eff = material.E0 * (1.0 - ras_options.beta_E * xi)
    ft_eff = material.ft0 * (1.0 - ras_options.beta_ft * xi)
    fc_eff = material.fc0 * (1.0 - ras_options.beta_fc * xi)
    Gf_eff = material.Gf0 * (1.0 - ras_options.beta_Gf * xi)

    E_eff = max(E_eff, material.E0 * ras_options.E_min_factor)
    ft_eff = max(ft_eff, material.ft0 * ras_options.ft_min_factor)
    fc_eff = max(fc_eff, material.fc0 * ras_options.fc_min_factor)
    Gf_eff = max(Gf_eff, material.Gf0 * ras_options.Gf_min_factor)

    return E_eff, ft_eff, fc_eff, Gf_eff


def set_uniform_xi_in_gp_states(gp_states, xi):
    for elem_states in gp_states:
        for gp in elem_states:
            gp.xi_ras = float(np.clip(xi, 0.0, 1.0))
    return gp_states


# ============================================================
# MODELO DE DAÑO
# ============================================================

def principal_values_2d(vec):
    xx = vec[0]
    yy = vec[1]
    xy = vec[2]

    avg = 0.5 * (xx + yy)
    rad = np.sqrt((0.5 * (xx - yy))**2 + xy**2)

    return avg + rad, avg - rad


def equivalent_tensile_strain(strain):
    e1, e2 = principal_values_2d(strain)
    return np.sqrt(max(e1, 0.0)**2 + max(e2, 0.0)**2)


def equivalent_compressive_strain(strain):
    e1, e2 = principal_values_2d(strain)
    return max(-e1, -e2, 0.0)


def update_damage_material(material, ras_options, old_state, strain, h_e, problem_type):
    """
    Actualizacion constitutiva RAS + daño mecanico.

    Modelo:
        sigma = (1-dm) D(E(xi),nu) (eps_total - eps_RAS)

    El daño se calcula con eps_mec = eps_total - eps_RAS.
    """
    state = deepcopy(old_state)

    if state.stress is None:
        state.stress = np.zeros(3)

    if state.strain is None:
        state.strain = np.zeros(3)

    strain = np.array(strain, dtype=float)

    xi = float(np.clip(state.xi_ras, 0.0, 1.0))
    E_eff, ft_eff, fc_eff, Gf_eff = degraded_properties(material, ras_options, xi)
    D_eff = elastic_matrix(E_eff, material.nu, problem_type)

    eps_ras_value = ras_options.eps_ras_inf * xi if ras_options.enabled else 0.0
    eps_ras = np.array([eps_ras_value, eps_ras_value, 0.0], dtype=float)
    strain_mec = strain - eps_ras

    sigma_trial = D_eff @ strain_mec
    s1, s2 = principal_values_2d(sigma_trial)

    # --------------------------------------------------------
    # Daño mecanico de traccion, calculado con deformacion mecanica
    # --------------------------------------------------------

    eps_eq_t = equivalent_tensile_strain(strain_mec)
    activate_tension = (eps_eq_t > state.kappa_t) and (s1 > 0.0)

    if activate_tension:
        state.kappa_t = eps_eq_t

    eps0_t = ft_eff / E_eff
    eps_f_t = Gf_eff / (ft_eff * h_e)

    if eps_f_t <= eps0_t:
        eps_f_t = 1.05 * eps0_t

    if state.kappa_t > eps0_t:
        A_t = 1.0 / (eps_f_t - eps0_t)
        d_t = 1.0 - (eps0_t / state.kappa_t) * np.exp(
            -A_t * (state.kappa_t - eps0_t)
        )
        state.damage_t = max(state.damage_t, d_t)

    # --------------------------------------------------------
    # Daño mecanico de compresion opcional, tambien con strain_mec
    # --------------------------------------------------------

    if material.enable_compression_damage:
        eps_eq_c = equivalent_compressive_strain(strain_mec)
        activate_compression = (eps_eq_c > state.kappa_c) and (s2 < 0.0)

        if activate_compression:
            state.kappa_c = eps_eq_c

        eps0_c = fc_eff / E_eff
        eps_f_c = material.Gc0 / (fc_eff * h_e)

        if eps_f_c <= eps0_c:
            eps_f_c = 1.05 * eps0_c

        if state.kappa_c > eps0_c:
            A_c = 1.0 / (eps_f_c - eps0_c)
            d_c = 1.0 - (eps0_c / state.kappa_c) * np.exp(
                -A_c * (state.kappa_c - eps0_c)
            )
            state.damage_c = max(state.damage_c, d_c)

    state.damage_t = min(max(state.damage_t, 0.0), material.damage_max)
    state.damage_c = min(max(state.damage_c, 0.0), material.damage_max)

    state.damage = 1.0 - (1.0 - state.damage_t) * (1.0 - state.damage_c)
    state.damage = min(max(state.damage, 0.0), material.damage_max)

    state.strain = strain
    state.strain_mec = strain_mec
    state.eps_ras = eps_ras
    state.E_eff = E_eff
    state.ft_eff = ft_eff
    state.fc_eff = fc_eff
    state.Gf_eff = Gf_eff
    state.stress = (1.0 - state.damage) * (D_eff @ strain_mec)

    return state, D_eff


def material_response(material, ras_options, old_state, strain, h_e, problem_type, options):
    """
    Respuesta material local y matriz usada por Newton.

    tangent_mode:
        numerical_hybrid -> D_eff si el punto esta sano; tangente numerica si hay daño.
        numerical        -> tangente numerica siempre.
        secant           -> Ct=(1-d)D_eff.
        elastic          -> Ct=D_eff.
    """

    base_state, D_eff = update_damage_material(
        material=material,
        ras_options=ras_options,
        old_state=old_state,
        strain=strain,
        h_e=h_e,
        problem_type=problem_type
    )

    sigma0 = base_state.stress.copy()
    mode = options.tangent_mode.lower().strip()

    if mode == "elastic":
        Ct = D_eff.copy()
        return sigma0, Ct, base_state

    if mode == "secant":
        Ct = (1.0 - base_state.damage) * D_eff
        Ct = Ct + options.min_stiff_factor * D_eff
        return sigma0, Ct, base_state

    if mode == "numerical_hybrid":
        if old_state.damage < 1.0e-12 and base_state.damage < 1.0e-12:
            return sigma0, D_eff.copy(), base_state

    if mode not in ["numerical", "numerical_hybrid"]:
        raise ValueError(
            "tangent_mode debe ser 'numerical_hybrid', 'numerical', 'secant' o 'elastic'"
        )

    Ct = np.zeros((3, 3))

    norm_eps = max(np.linalg.norm(strain), 1.0e-8)
    h = max(options.numerical_tangent_rel_step * norm_eps,
            options.numerical_tangent_abs_step)

    for j in range(3):
        strain_p = strain.copy()
        strain_p[j] += h

        pert_state, _ = update_damage_material(
            material=material,
            ras_options=ras_options,
            old_state=old_state,
            strain=strain_p,
            h_e=h_e,
            problem_type=problem_type
        )

        sigma_p = pert_state.stress.copy()
        Ct[:, j] = (sigma_p - sigma0) / h

    Ct = Ct + options.min_stiff_factor * D_eff

    return sigma0, Ct, base_state


# ============================================================
# ELEMENTO Q4
# ============================================================

def shape_functions_Q4(xi, eta):
    N = 0.25 * np.array([
        (1.0 - xi) * (1.0 - eta),
        (1.0 + xi) * (1.0 - eta),
        (1.0 + xi) * (1.0 + eta),
        (1.0 - xi) * (1.0 + eta)
    ])

    dN_dxi = 0.25 * np.array([
        -(1.0 - eta),
         (1.0 - eta),
         (1.0 + eta),
        -(1.0 + eta)
    ])

    dN_deta = 0.25 * np.array([
        -(1.0 - xi),
        -(1.0 + xi),
         (1.0 + xi),
         (1.0 - xi)
    ])

    return N, dN_dxi, dN_deta


def B_matrix_Q4(coords_elem, xi, eta):
    _, dN_dxi, dN_deta = shape_functions_Q4(xi, eta)

    J = np.zeros((2, 2))

    for i in range(4):
        x_i = coords_elem[i, 0]
        y_i = coords_elem[i, 1]

        J[0, 0] += dN_dxi[i] * x_i
        J[0, 1] += dN_deta[i] * x_i
        J[1, 0] += dN_dxi[i] * y_i
        J[1, 1] += dN_deta[i] * y_i

    detJ = np.linalg.det(J)

    if detJ <= 0:
        raise ValueError("Elemento con Jacobiano negativo o nulo.")

    invJ = np.linalg.inv(J)

    dN_dx = np.zeros(4)
    dN_dy = np.zeros(4)

    for i in range(4):
        grad_nat = np.array([dN_dxi[i], dN_deta[i]])
        grad_xy = invJ @ grad_nat

        dN_dx[i] = grad_xy[0]
        dN_dy[i] = grad_xy[1]

    B = np.zeros((3, 8))

    for i in range(4):
        B[0, 2 * i] = dN_dx[i]
        B[1, 2 * i + 1] = dN_dy[i]
        B[2, 2 * i] = dN_dy[i]
        B[2, 2 * i + 1] = dN_dx[i]

    return B, detJ


def gauss_points_Q4():
    gp = 1.0 / np.sqrt(3.0)
    return [
        (-gp, -gp, 1.0),
        ( gp, -gp, 1.0),
        ( gp,  gp, 1.0),
        (-gp,  gp, 1.0)
    ]


# ============================================================
# MALLA
# ============================================================

def generate_notched_beam_mesh(L, H, nx, ny, notch_width, notch_height):
    nodes = []

    for j in range(ny + 1):
        y = H * j / ny
        for i in range(nx + 1):
            x = L * i / nx
            nodes.append([x, y])

    nodes = np.array(nodes, dtype=float)

    elements_raw = []

    x_notch_min = L / 2.0 - notch_width / 2.0
    x_notch_max = L / 2.0 + notch_width / 2.0
    y_notch_min = 0.0
    y_notch_max = notch_height

    removed = 0

    for j in range(ny):
        for i in range(nx):
            n1 = j * (nx + 1) + i
            n2 = n1 + 1
            n4 = n1 + (nx + 1)
            n3 = n4 + 1

            elem = [n1, n2, n3, n4]
            coords = nodes[elem, :]

            x_min_elem = np.min(coords[:, 0])
            x_max_elem = np.max(coords[:, 0])
            y_min_elem = np.min(coords[:, 1])
            y_max_elem = np.max(coords[:, 1])

            overlap_x = (x_max_elem > x_notch_min) and (x_min_elem < x_notch_max)
            overlap_y = (y_max_elem > y_notch_min) and (y_min_elem < y_notch_max)

            inside_notch = overlap_x and overlap_y

            if inside_notch:
                removed += 1
            else:
                elements_raw.append(elem)

    elements_raw = np.array(elements_raw, dtype=int)

    used_nodes = np.unique(elements_raw.flatten())
    old_to_new = {old: new for new, old in enumerate(used_nodes)}

    nodes_new = nodes[used_nodes, :]

    elements_new = []

    for elem in elements_raw:
        elements_new.append([old_to_new[n] for n in elem])

    elements_new = np.array(elements_new, dtype=int)

    return nodes_new, elements_new, removed


def nearest_node(nodes, x_target, y_target):
    dist = np.sqrt((nodes[:, 0] - x_target)**2 + (nodes[:, 1] - y_target)**2)
    return int(np.argmin(dist))


def find_top_load_patch_nodes(nodes, x_center, y_top, mode="three_nodes_centered"):
    top_nodes = np.where(np.isclose(nodes[:, 1], y_top))[0]
    top_nodes = top_nodes[np.argsort(nodes[top_nodes, 0])]
    x_top = nodes[top_nodes, 0]

    center_idx_local = int(np.argmin(np.abs(x_top - x_center)))

    if mode == "one_node":
        return [int(top_nodes[center_idx_local])]

    if mode == "two_nodes_element":
        best_i = 0
        best_dist = 1.0e30

        for i in range(len(top_nodes) - 1):
            xm = 0.5 * (x_top[i] + x_top[i + 1])
            dist = abs(xm - x_center)

            if dist < best_dist:
                best_dist = dist
                best_i = i

        return [int(top_nodes[best_i]), int(top_nodes[best_i + 1])]

    if mode == "three_nodes_centered":
        i0 = max(center_idx_local - 1, 0)
        i1 = center_idx_local
        i2 = min(center_idx_local + 1, len(top_nodes) - 1)

        return list(dict.fromkeys([
            int(top_nodes[i0]),
            int(top_nodes[i1]),
            int(top_nodes[i2])
        ]))

    raise ValueError("mode no reconocido.")


def element_area(coords_elem):
    x = coords_elem[:, 0]
    y = coords_elem[:, 1]

    area = 0.0

    for i in range(4):
        j = (i + 1) % 4
        area += x[i] * y[j] - x[j] * y[i]

    return abs(area) / 2.0


# ============================================================
# PRECOMPUTACION
# ============================================================

def precompute_element_data(nodes, elements):
    gps = gauss_points_Q4()
    elem_data = []

    for elem in elements:
        coords_elem = nodes[elem, :]

        dofs = []

        for n in elem:
            dofs.extend([2 * n, 2 * n + 1])

        dofs = np.array(dofs, dtype=int)

        area = element_area(coords_elem)
        h_e = np.sqrt(area)

        B_list = []
        detJ_list = []
        weight_list = []

        for xi, eta, w in gps:
            B, detJ = B_matrix_Q4(coords_elem, xi, eta)
            B_list.append(B)
            detJ_list.append(detJ)
            weight_list.append(w)

        elem_data.append({
            "elem": elem,
            "dofs": dofs,
            "area": area,
            "h_e": h_e,
            "B": B_list,
            "detJ": detJ_list,
            "w": weight_list
        })

    return elem_data


def initialize_gp_states(n_elements):
    states = []

    for _ in range(n_elements):
        elem_states = []

        for _ in range(4):
            elem_states.append(GPState())

        states.append(elem_states)

    return states


# ============================================================
# GDL
# ============================================================

def get_free_prescribed_dofs(n_dof, prescribed):
    prescribed_dofs = np.array(sorted(prescribed.keys()), dtype=int)
    prescribed_values = np.array([prescribed[dof] for dof in prescribed_dofs], dtype=float)

    all_dofs = np.arange(n_dof)
    free_dofs = np.setdiff1d(all_dofs, prescribed_dofs)

    return free_dofs, prescribed_dofs, prescribed_values


# ============================================================
# ENSAMBLAJE NEWTON
# ============================================================

def assemble_tangent_and_internal_force(
    n_dof,
    elem_data,
    material,
    ras_options,
    old_states_step,
    thickness,
    U,
    problem_type,
    options
):
    rows = []
    cols = []
    vals = []

    Fint = np.zeros(n_dof)
    new_states = deepcopy(old_states_step)

    for e, data in enumerate(elem_data):
        dofs = data["dofs"]
        Ue = U[dofs]

        Ke = np.zeros((8, 8))
        Fe = np.zeros(8)

        h_e = data["h_e"]

        for igp in range(4):
            B = data["B"][igp]
            detJ = data["detJ"][igp]
            w = data["w"][igp]

            strain = B @ Ue
            old_gp = old_states_step[e][igp]

            sigma, Ct, updated_gp = material_response(
                material=material,
                ras_options=ras_options,
                old_state=old_gp,
                strain=strain,
                h_e=h_e,
                problem_type=problem_type,
                options=options
            )

            weight = detJ * w * thickness

            Ke += B.T @ Ct @ B * weight
            Fe += B.T @ sigma * weight

            new_states[e][igp] = updated_gp

        rr, cc = np.meshgrid(dofs, dofs, indexing="ij")

        rows.extend(rr.ravel())
        cols.extend(cc.ravel())
        vals.extend(Ke.ravel())

        Fint[dofs] += Fe

    Kt = coo_matrix((vals, (rows, cols)), shape=(n_dof, n_dof)).tocsr()

    return Kt, Fint, new_states


# ============================================================
# NEWTON DE UN PASO
# ============================================================

def solve_step_newton(
    n_dof,
    elem_data,
    material,
    ras_options,
    old_states_step,
    thickness,
    U_start,
    prescribed,
    problem_type,
    options
):
    free_dofs, prescribed_dofs, prescribed_values = get_free_prescribed_dofs(
        n_dof,
        prescribed
    )

    U = U_start.copy()
    U[prescribed_dofs] = prescribed_values

    converged = False
    accepted_states = deepcopy(old_states_step)

    alpha_values = list(options.line_search_alphas)

    norm0 = None
    norm_R = None
    rel_R = None
    Fint = None

    for it in range(1, options.max_iter + 1):
        Kt, Fint, trial_states = assemble_tangent_and_internal_force(
            n_dof=n_dof,
            elem_data=elem_data,
            material=material,
            ras_options=ras_options,
            old_states_step=old_states_step,
            thickness=thickness,
            U=U,
            problem_type=problem_type,
            options=options
        )

        R_free = Fint[free_dofs]
        norm_R = np.linalg.norm(R_free)

        if norm0 is None:
            norm0 = max(norm_R, 1.0)

        rel_R = norm_R / norm0

        if norm_R < options.tol_res_abs or rel_R < options.tol_res_rel:
            converged = True
            accepted_states = trial_states
            break

        Kff = Kt[free_dofs, :][:, free_dofs]

        try:
            du_free = spsolve(Kff, -R_free)
        except Exception:
            accepted_states = trial_states
            return U, Fint, accepted_states, it, False, norm_R, rel_R

        norm_du = np.linalg.norm(du_free)
        norm_U = max(np.linalg.norm(U[free_dofs]), 1.0)

        if norm_du / norm_U < options.tol_du and rel_R < 1.0e-4:
            converged = True
            accepted_states = trial_states
            break

        best_U = None
        best_states = None
        best_Fint = None
        best_norm = np.inf

        for alpha in alpha_values:
            U_candidate = U.copy()
            U_candidate[free_dofs] += alpha * du_free
            U_candidate[prescribed_dofs] = prescribed_values

            _, Fint_candidate, states_candidate = assemble_tangent_and_internal_force(
                n_dof=n_dof,
                elem_data=elem_data,
                material=material,
                ras_options=ras_options,
                old_states_step=old_states_step,
                thickness=thickness,
                U=U_candidate,
                problem_type=problem_type,
                options=options
            )

            norm_candidate = np.linalg.norm(Fint_candidate[free_dofs])

            if norm_candidate < best_norm:
                best_norm = norm_candidate
                best_U = U_candidate
                best_states = states_candidate
                best_Fint = Fint_candidate

        if best_U is None:
            accepted_states = trial_states
            return U, Fint, accepted_states, it, False, norm_R, rel_R

        # Más permisivo que antes. Si empeora muchísimo, se rechaza el paso.
        if best_norm > options.line_search_max_worsening * norm_R:
            accepted_states = trial_states
            return U, Fint, accepted_states, it, False, norm_R, rel_R

        U = best_U
        accepted_states = best_states
        Fint = best_Fint

    Kt, Fint, accepted_states = assemble_tangent_and_internal_force(
        n_dof=n_dof,
        elem_data=elem_data,
        material=material,
        ras_options=ras_options,
        old_states_step=old_states_step,
        thickness=thickness,
        U=U,
        problem_type=problem_type,
        options=options
    )

    R_free = Fint[free_dofs]
    norm_R = np.linalg.norm(R_free)
    rel_R = norm_R / max(norm0, 1.0)

    if norm_R < options.tol_res_abs or rel_R < options.tol_res_rel:
        converged = True

    return U, Fint, accepted_states, it, converged, norm_R, rel_R


# ============================================================
# POSTPROCESO
# ============================================================

def collect_element_damage(gp_states):
    damage = []
    damage_t = []
    damage_c = []

    for elem_states in gp_states:
        damage.append(max(gp.damage for gp in elem_states))
        damage_t.append(max(gp.damage_t for gp in elem_states))
        damage_c.append(max(gp.damage_c for gp in elem_states))

    return np.array(damage), np.array(damage_t), np.array(damage_c)


def collect_element_stress(gp_states):
    stress = []

    for elem_states in gp_states:
        sigs = []

        for gp in elem_states:
            if gp.stress is None:
                sigs.append(np.zeros(3))
            else:
                sigs.append(gp.stress)

        stress.append(np.mean(np.array(sigs), axis=0))

    return np.array(stress)


def plot_load_displacement(displacements, loads):
    plt.figure()
    plt.plot(np.abs(displacements), loads, "o-", linewidth=1.5, markersize=3)
    plt.xlabel("Desplazamiento impuesto |delta| [mm]")
    plt.ylabel("Carga equivalente P [N]")
    plt.title("Curva carga-desplazamiento")
    plt.grid(True)
    plt.tight_layout()


def plot_damage_history(displacements, max_damages):
    plt.figure()
    plt.plot(np.abs(displacements), max_damages, "o-", linewidth=1.5, markersize=3)
    plt.xlabel("Desplazamiento impuesto |delta| [mm]")
    plt.ylabel("Daño máximo")
    plt.title("Evolución del daño máximo")
    plt.grid(True)
    plt.tight_layout()


def plot_deformed_mesh(nodes, elements, U, scale=1.0):
    U_nodes = U.reshape((-1, 2))
    nodes_def = nodes + scale * U_nodes

    fig, ax = plt.subplots()

    for elem in elements:
        xy = nodes[elem, :]
        xy_closed = np.vstack([xy, xy[0]])
        ax.plot(xy_closed[:, 0], xy_closed[:, 1], "k--", linewidth=0.20)

        xy_def = nodes_def[elem, :]
        xy_def_closed = np.vstack([xy_def, xy_def[0]])
        ax.plot(xy_def_closed[:, 0], xy_def_closed[:, 1], "r-", linewidth=0.35)

    ax.axis("equal")
    ax.set_xlabel("x [mm]")
    ax.set_ylabel("y [mm]")
    ax.set_title(f"Deformada final - factor {scale:.1f}")
    ax.grid(True)
    fig.tight_layout()


def plot_element_field(nodes, elements, values, title, label):
    fig, ax = plt.subplots()

    vmin = values.min()
    vmax = values.max()

    for e, elem in enumerate(elements):
        xy = nodes[elem, :]

        if abs(vmax - vmin) < 1e-15:
            cval = 0.5
        else:
            cval = (values[e] - vmin) / (vmax - vmin)

        ax.fill(
            xy[:, 0],
            xy[:, 1],
            color=plt.cm.viridis(cval),
            edgecolor="k",
            linewidth=0.10
        )

    sm = plt.cm.ScalarMappable(cmap="viridis")
    sm.set_array(values)
    sm.set_clim(vmin, vmax)
    fig.colorbar(sm, ax=ax, label=label)

    ax.axis("equal")
    ax.set_xlabel("x [mm]")
    ax.set_ylabel("y [mm]")
    ax.set_title(title)
    fig.tight_layout()


def plot_boundary_conditions(nodes, elements, support_left, support_right, load_patch_nodes):
    fig, ax = plt.subplots()

    for elem in elements:
        xy = nodes[elem, :]
        xy_closed = np.vstack([xy, xy[0]])
        ax.plot(xy_closed[:, 0], xy_closed[:, 1], "k-", linewidth=0.20)

    ax.scatter(
        nodes[support_left, 0],
        nodes[support_left, 1],
        marker="^",
        s=120,
        label="Apoyo izquierdo ux=uy=0"
    )

    ax.scatter(
        nodes[support_right, 0],
        nodes[support_right, 1],
        marker="^",
        s=120,
        label="Apoyo derecho uy=0"
    )

    load_xy = nodes[load_patch_nodes, :]
    ax.scatter(
        load_xy[:, 0],
        load_xy[:, 1],
        marker="v",
        s=100,
        label="Desplazamiento impuesto"
    )

    for n in load_patch_nodes:
        ax.text(nodes[n, 0], nodes[n, 1] + 3.0, str(n), fontsize=8, ha="center")

    ax.text(nodes[support_left, 0], nodes[support_left, 1] - 6.0, str(support_left), fontsize=8, ha="center")
    ax.text(nodes[support_right, 0], nodes[support_right, 1] - 6.0, str(support_right), fontsize=8, ha="center")

    ax.axis("equal")
    ax.set_xlabel("x [mm]")
    ax.set_ylabel("y [mm]")
    ax.set_title("Mapa de apoyos y desplazamiento impuesto")
    ax.grid(True)
    ax.legend()
    fig.tight_layout()



# ============================================================
# GUARDADO DE RESULTADOS
# ============================================================

def build_output_dir(ras_options, xi_analysis):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    case_name = (
        f"{ras_options.concrete_name}_"
        f"{ras_options.age_days:.0f}d_"
        f"xi_{xi_analysis:.3f}_"
        f"bE_{ras_options.beta_E:.2f}_"
        f"bft_{ras_options.beta_ft:.2f}_"
        f"bGf_{ras_options.beta_Gf:.2f}_"
        f"{timestamp}"
    )
    output_dir = Path("resultados_RAS") / case_name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def save_incremental_table(output_dir, step_table):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "tabla_incremental.csv"
    txt_path = output_dir / "tabla_incremental.txt"

    fieldnames = [
        "paso", "intento", "delta_mm", "d_step_mm", "P_N", "dmax",
        "iter", "norm_R", "rel_R", "conv"
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in step_table:
            writer.writerow(row)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("ANÁLISIS INCREMENTAL\n")
        f.write("-" * 120 + "\n")
        f.write(
            f"{'paso':>5s} {'intento':>8s} {'delta [mm]':>16s} "
            f"{'d_step [mm]':>14s} {'P [N]':>12s} {'dmax':>8s} "
            f"{'iter':>5s} {'||R||':>10s} {'relR':>10s} {'conv':>8s}\n"
        )
        f.write("-" * 120 + "\n")

        for row in step_table:
            dmax_txt = "---" if row["dmax"] is None else f"{row['dmax']:.5f}"
            f.write(
                f"{int(row['paso']):5d} "
                f"{int(row['intento']):8d} "
                f"{row['delta_mm']:16.8e} "
                f"{row['d_step_mm']:14.6e} "
                f"{row['P_N']:12.4f} "
                f"{dmax_txt:>8s} "
                f"{int(row['iter']):5d} "
                f"{row['norm_R']:10.3e} "
                f"{row['rel_R']:10.2e} "
                f"{str(row['conv']):>8s}\n"
            )

    print(f"Tabla incremental guardada en: {csv_path}")
    print(f"Tabla incremental TXT guardada en: {txt_path}")


def save_summary_files(
    output_dir,
    material,
    ras_options,
    options,
    xi_analysis,
    eps_ras_initial,
    E_eff0,
    ft_eff0,
    fc_eff0,
    Gf_eff0,
    displacements,
    loads,
    max_damages,
    accepted_step,
    rejected_step,
    delta_current,
    nodes,
    elements,
    gp_states
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stress_elem = collect_element_stress(gp_states)
    damage_elem, damage_t_elem, damage_c_elem = collect_element_damage(gp_states)

    if len(loads) > 0:
        loads_arr = np.array(loads, dtype=float)
        disp_arr = np.array(displacements, dtype=float)
        peak_idx = int(np.argmax(loads_arr))
        Pmax = float(loads_arr[peak_idx])
        delta_Pmax = float(disp_arr[peak_idx])
        Pfinal = float(loads_arr[-1])
        delta_final = float(disp_arr[-1])
        rigidez_inicial = float(loads_arr[0] / abs(displacements[0])) if abs(displacements[0]) > 0 else None
    else:
        Pmax = delta_Pmax = Pfinal = delta_final = rigidez_inicial = None

    summary = {
        "concrete_name": ras_options.concrete_name,
        "age_days": ras_options.age_days,
        "xi": xi_analysis,
        "eps_ras_lineal": eps_ras_initial,
        "eps_inf_vol": ras_options.eps_inf_vol,
        "tau_lat_days": ras_options.tau_lat,
        "tau_ch_days": ras_options.tau_ch,
        "E0_MPa": material.E0,
        "nu": material.nu,
        "ft0_MPa": material.ft0,
        "fc0_MPa": material.fc0,
        "Gf0_N_mm": material.Gf0,
        "Gc0_N_mm": material.Gc0,
        "E_eff_MPa": E_eff0,
        "ft_eff_MPa": ft_eff0,
        "fc_eff_MPa": fc_eff0,
        "Gf_eff_N_mm": Gf_eff0,
        "beta_E": ras_options.beta_E,
        "beta_ft": ras_options.beta_ft,
        "beta_fc": ras_options.beta_fc,
        "beta_Gf": ras_options.beta_Gf,
        "delta_target_mm": options.delta_target,
        "delta_final_mm": delta_current,
        "accepted_steps": accepted_step,
        "rejected_steps": rejected_step,
        "Pmax_N": Pmax,
        "delta_Pmax_mm": delta_Pmax,
        "Pfinal_N": Pfinal,
        "delta_final_result_mm": delta_final,
        "rigidez_inicial_N_mm": rigidez_inicial,
        "dmax_final": float(np.max(damage_elem)),
        "dt_max_final": float(np.max(damage_t_elem)),
        "dc_max_final": float(np.max(damage_c_elem)),
        "sigma_x_min_MPa": float(np.min(stress_elem[:, 0])),
        "sigma_x_max_MPa": float(np.max(stress_elem[:, 0])),
        "sigma_y_min_MPa": float(np.min(stress_elem[:, 1])),
        "sigma_y_max_MPa": float(np.max(stress_elem[:, 1])),
        "tau_xy_min_MPa": float(np.min(stress_elem[:, 2])),
        "tau_xy_max_MPa": float(np.max(stress_elem[:, 2])),
        "tangent_mode": options.tangent_mode,
        "step_control": options.step_control,
        "delta_step_initial": options.delta_step_initial,
        "delta_step_min": options.delta_step_min,
        "delta_step_max": options.delta_step_max,
        "grow_factor": options.grow_factor,
        "shrink_factor": options.shrink_factor,
        "max_iter": options.max_iter,
        "tol_res_abs": options.tol_res_abs,
        "tol_res_rel": options.tol_res_rel,
        "min_stiff_factor": options.min_stiff_factor,
        "n_nodes": int(nodes.shape[0]),
        "n_elements": int(elements.shape[0]),
    }

    json_path = output_dir / "resumen_corrida.json"
    txt_path = output_dir / "resumen_corrida.txt"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4, ensure_ascii=False)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("RESUMEN DE CORRIDA\n")
        f.write("=" * 72 + "\n\n")
        f.write("CASO\n")
        f.write("-" * 72 + "\n")
        f.write(f"Hormigón                  = {ras_options.concrete_name}\n")
        f.write(f"Edad                      = {ras_options.age_days:.3f} días\n")
        f.write(f"xi                        = {xi_analysis:.8f}\n")
        f.write(f"eps_RAS lineal            = {eps_ras_initial:.8e}\n")
        f.write(f"tau_lat                   = {ras_options.tau_lat:.6f} días\n")
        f.write(f"tau_ch                    = {ras_options.tau_ch:.6f} días\n")
        f.write(f"eps_inf_vol               = {ras_options.eps_inf_vol:.8e}\n\n")

        f.write("PARÁMETROS MECÁNICOS BASE\n")
        f.write("-" * 72 + "\n")
        f.write(f"E0                        = {material.E0:.6f} MPa\n")
        f.write(f"nu                        = {material.nu:.6f}\n")
        f.write(f"ft0                       = {material.ft0:.6f} MPa\n")
        f.write(f"fc0                       = {material.fc0:.6f} MPa\n")
        f.write(f"Gf0                       = {material.Gf0:.8f} N/mm\n")
        f.write(f"Gc0                       = {material.Gc0:.8f} N/mm\n\n")

        f.write("PROPIEDADES DEGRADADAS AL INICIO DE LA FLEXIÓN\n")
        f.write("-" * 72 + "\n")
        f.write(f"E_eff                     = {E_eff0:.6f} MPa\n")
        f.write(f"ft_eff                    = {ft_eff0:.6f} MPa\n")
        f.write(f"fc_eff                    = {fc_eff0:.6f} MPa\n")
        f.write(f"Gf_eff                    = {Gf_eff0:.8f} N/mm\n\n")

        f.write("COEFICIENTES DE DEGRADACIÓN USADOS\n")
        f.write("-" * 72 + "\n")
        f.write(f"beta_E                    = {ras_options.beta_E:.6f}\n")
        f.write(f"beta_ft                   = {ras_options.beta_ft:.6f}\n")
        f.write(f"beta_fc                   = {ras_options.beta_fc:.6f}\n")
        f.write(f"beta_Gf                   = {ras_options.beta_Gf:.6f}\n\n")

        f.write("RESULTADOS PRINCIPALES\n")
        f.write("-" * 72 + "\n")
        f.write(f"Pasos aceptados            = {accepted_step}\n")
        f.write(f"Pasos rechazados           = {rejected_step}\n")
        f.write(f"Delta final aceptado       = {delta_current:.8e} mm\n")
        f.write(f"Delta objetivo             = {options.delta_target:.8e} mm\n")
        if Pmax is not None:
            f.write(f"Carga máxima               = {Pmax:.6f} N\n")
            f.write(f"Delta en carga máxima      = {delta_Pmax:.8e} mm\n")
            f.write(f"Carga final                = {Pfinal:.6f} N\n")
            f.write(f"Rigidez inicial            = {rigidez_inicial:.6f} N/mm\n")
        f.write(f"Daño máximo final          = {np.max(damage_elem):.6f}\n")
        f.write(f"Daño tracción máximo final = {np.max(damage_t_elem):.6f}\n")
        f.write(f"Daño compresión max final  = {np.max(damage_c_elem):.6f}\n\n")

        f.write("TENSIONES FINALES PROMEDIO POR ELEMENTO\n")
        f.write("-" * 72 + "\n")
        f.write(f"sigma_x min                = {np.min(stress_elem[:, 0]):.6e} MPa\n")
        f.write(f"sigma_x max                = {np.max(stress_elem[:, 0]):.6e} MPa\n")
        f.write(f"sigma_y min                = {np.min(stress_elem[:, 1]):.6e} MPa\n")
        f.write(f"sigma_y max                = {np.max(stress_elem[:, 1]):.6e} MPa\n")
        f.write(f"tau_xy min                 = {np.min(stress_elem[:, 2]):.6e} MPa\n")
        f.write(f"tau_xy max                 = {np.max(stress_elem[:, 2]):.6e} MPa\n")

    print(f"Resumen guardado en: {txt_path}")
    print(f"Resumen JSON guardado en: {json_path}")


def save_result_figures(
    output_dir,
    nodes,
    elements,
    U_final,
    gp_states,
    displacements,
    loads,
    max_damages,
    L,
    support_left,
    support_right,
    load_patch_nodes
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if U_final is None or len(loads) == 0:
        print("No hay resultados aceptados para guardar gráficos.")
        return

    displacements = np.array(displacements, dtype=float)
    loads = np.array(loads, dtype=float)
    max_damages = np.array(max_damages, dtype=float)

    stress_elem = collect_element_stress(gp_states)
    damage_elem, damage_t_elem, damage_c_elem = collect_element_damage(gp_states)

    # Curva P-delta
    fig, ax = plt.subplots()
    ax.plot(np.abs(displacements), loads, "o-", linewidth=1.5, markersize=3)
    ax.set_xlabel("Desplazamiento impuesto |delta| [mm]")
    ax.set_ylabel("Carga equivalente P [N]")
    ax.set_title("Curva carga-desplazamiento")
    ax.grid(True)
    fig.tight_layout()
    fig.savefig(output_dir / "curva_carga_desplazamiento.png", dpi=300)

    # Curva daño-delta
    fig, ax = plt.subplots()
    ax.plot(np.abs(displacements), max_damages, "o-", linewidth=1.5, markersize=3)
    ax.set_xlabel("Desplazamiento impuesto |delta| [mm]")
    ax.set_ylabel("Daño máximo")
    ax.set_title("Evolución del daño máximo")
    ax.grid(True)
    fig.tight_layout()
    fig.savefig(output_dir / "curva_dano_desplazamiento.png", dpi=300)

    # Deformada
    U_nodes_final = U_final.reshape((-1, 2))
    max_disp = np.max(np.sqrt(U_nodes_final[:, 0]**2 + U_nodes_final[:, 1]**2))
    scale = 0.10 * L / max_disp if max_disp > 0 else 1.0
    plot_deformed_mesh(nodes, elements, U_final, scale=scale)
    plt.gcf().savefig(output_dir / "deformada_final.png", dpi=300)

    # Mapas
    plot_element_field(nodes, elements, damage_elem, "Daño total final", "d")
    plt.gcf().savefig(output_dir / "mapa_dano_final.png", dpi=300)

    plot_element_field(nodes, elements, damage_t_elem, "Daño de tracción final", "d_t")
    plt.gcf().savefig(output_dir / "mapa_dano_traccion_final.png", dpi=300)

    plot_element_field(nodes, elements, stress_elem[:, 0], "Tensión sigma_x final", "sigma_x [MPa]")
    plt.gcf().savefig(output_dir / "mapa_sigma_x_final.png", dpi=300)

    plot_element_field(nodes, elements, stress_elem[:, 1], "Tensión sigma_y final", "sigma_y [MPa]")
    plt.gcf().savefig(output_dir / "mapa_sigma_y_final.png", dpi=300)

    plot_element_field(nodes, elements, stress_elem[:, 2], "Tensión tau_xy final", "tau_xy [MPa]")
    plt.gcf().savefig(output_dir / "mapa_tau_xy_final.png", dpi=300)

    plot_boundary_conditions(nodes, elements, support_left, support_right, load_patch_nodes)
    plt.gcf().savefig(output_dir / "mapa_apoyos.png", dpi=300)

    print(f"Gráficos guardados en: {output_dir}")

def show_results(
    nodes,
    elements,
    U_final,
    gp_states,
    displacements,
    loads,
    max_damages,
    L,
    support_left,
    support_right,
    load_patch_nodes
):
    if U_final is None or len(loads) == 0:
        print("\nNo hay resultados para graficar.")
        return

    displacements = np.array(displacements)
    loads = np.array(loads)
    max_damages = np.array(max_damages)

    stress_elem = collect_element_stress(gp_states)
    damage_elem, damage_t_elem, damage_c_elem = collect_element_damage(gp_states)

    U_nodes_final = U_final.reshape((-1, 2))

    peak_idx = int(np.argmax(loads))

    print("\nRESUMEN")
    print("----------------------------------------------")
    print(f"Pasos aceptados              = {len(loads)}")
    print(f"Delta último                 = {displacements[-1]:.6e} mm")
    print(f"Carga máxima                 = {loads[peak_idx]:.6e} N")
    print(f"Delta en carga máxima        = {displacements[peak_idx]:.6e} mm")
    print(f"Carga final                  = {loads[-1]:.6e} N")
    print(f"Rigidez inicial aprox        = {loads[0] / abs(displacements[0]):.6e} N/mm")
    print(f"Daño máximo final            = {np.max(damage_elem):.6f}")
    print(f"Daño tracción máximo final   = {np.max(damage_t_elem):.6f}")
    print(f"Daño compresión máximo final = {np.max(damage_c_elem):.6f}")

    print("\nTENSIONES FINALES PROMEDIO POR ELEMENTO")
    print("----------------------------------------------")
    print(f"sigma_x min = {np.min(stress_elem[:, 0]):.6e} MPa")
    print(f"sigma_x max = {np.max(stress_elem[:, 0]):.6e} MPa")
    print(f"sigma_y min = {np.min(stress_elem[:, 1]):.6e} MPa")
    print(f"sigma_y max = {np.max(stress_elem[:, 1]):.6e} MPa")
    print(f"tau_xy min  = {np.min(stress_elem[:, 2]):.6e} MPa")
    print(f"tau_xy max  = {np.max(stress_elem[:, 2]):.6e} MPa")

    plot_load_displacement(displacements, loads)
    plot_damage_history(displacements, max_damages)

    max_disp = np.max(np.sqrt(U_nodes_final[:, 0]**2 + U_nodes_final[:, 1]**2))
    scale = 0.10 * L / max_disp if max_disp > 0 else 1.0

    plot_deformed_mesh(nodes, elements, U_final, scale=scale)

    plot_element_field(nodes, elements, damage_elem, "Daño total final", "d")
    plot_element_field(nodes, elements, damage_t_elem, "Daño de tracción final", "d_t")
    plot_element_field(nodes, elements, stress_elem[:, 0], "Tensión sigma_x final", "sigma_x [MPa]")

    plot_boundary_conditions(
        nodes=nodes,
        elements=elements,
        support_left=support_left,
        support_right=support_right,
        load_patch_nodes=load_patch_nodes
    )

    plt.show()


# ============================================================
# AVANCE DE CARGA / DESPLAZAMIENTO
# ============================================================

def build_free_expansion_displacement(nodes, eps_ras_value, x_ref, y_ref=0.0):
    """
    Campo inicial compatible con expansion libre uniforme:

        u_x = eps_RAS * (x - x_ref)
        u_y = eps_RAS * (y - y_ref)

    Con x_ref igual al apoyo izquierdo, se cumple u_x=0 en el apoyo izquierdo.
    Con y_ref=0, se cumple u_y=0 en ambos apoyos inferiores.

    Este campo hace que eps_total ~= eps_RAS*[1,1,0], por lo tanto
    eps_mec ~= 0 y no aparecen tensiones artificiales al iniciar la flexion.
    """
    U = np.zeros(2 * nodes.shape[0])
    U[0::2] = eps_ras_value * (nodes[:, 0] - x_ref)
    U[1::2] = eps_ras_value * (nodes[:, 1] - y_ref)
    return U


def build_prescribed_dict(dof_support_left_x, dof_support_left_y,
                          dof_support_right_y, dof_load_y_list,
                          delta_flexion, load_y_base=0.0):
    """
    Condiciones impuestas para la etapa de flexion.

    delta_flexion es el desplazamiento mecánico adicional medido desde la
    configuración expandida libremente.

    Si hay RAS uniforme, los nodos superiores ya tienen un desplazamiento vertical
    inicial load_y_base = eps_RAS * H. Por eso la condición absoluta en el punto
    de carga debe ser:

        u_y_top = load_y_base + delta_flexion

    No hacerlo así equivale a forzar artificialmente que la viga pierda su
    expansión vertical antes del ensayo, generando un residuo enorme.
    """
    prescribed = {
        dof_support_left_x: 0.0,
        dof_support_left_y: 0.0,
        dof_support_right_y: 0.0
    }

    for dof_load_y in dof_load_y_list:
        prescribed[dof_load_y] = load_y_base + delta_flexion

    return prescribed


def try_one_step(n_dof, elem_data, material, ras_options, gp_states, thickness,
                 U_current, prescribed, problem_type, options):
    old_states_step = deepcopy(gp_states)
    U_start = U_current.copy()

    for dof, value in prescribed.items():
        U_start[dof] = value

    return solve_step_newton(
        n_dof=n_dof,
        elem_data=elem_data,
        material=material,
        ras_options=ras_options,
        old_states_step=old_states_step,
        thickness=thickness,
        U_start=U_start,
        prescribed=prescribed,
        problem_type=problem_type,
        options=options
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print("\n================================================================================")
    print("MEF 2D - VIGA ENTALLADA - DAÑO ESCALAR + RAS - VERSION INTEGRADA")
    print("================================================================================")

    # =====================================================================
    # OPCIONES PRINCIPALES DE USUARIO
    # =====================================================================

    options = SolverOptions(
        # Matriz para Newton:
        # "numerical_hybrid" | "numerical" | "secant" | "elastic"
        tangent_mode="numerical_hybrid",
        min_stiff_factor=1.0e-8,

        # Avance:
        # "adaptive" | "fixed"
        step_control="adaptive",
        fixed_n_steps=120,
        fixed_allow_substepping=True,

        # Configuración recomendada para corridas finales de ejemplo
        # Objetivo: llegar hasta 0.20 mm con pasos algo más conservadores.
        delta_target=-0.20,
        delta_step_initial=-0.0010,
        delta_step_min=-0.000010,
        delta_step_max=-0.0015,
        grow_factor=1.10,
        shrink_factor=0.5,
        max_accepted_steps=600,

        max_iter=60,
        tol_res_abs=1.0e-4,
        tol_res_rel=1.0e-5,
        tol_du=1.0e-8,

        stop_if_damage_exceeds=False,
        damage_limit_to_stop=0.99999,

        load_patch_mode="three_nodes_centered"
    )

    L = 430.0
    H = 105.0
    thickness = 75.0

    notch_width = 3.0
    notch_height = H / 2.0

    # Malla rápida
    nx = 86
    ny = 21

    # Malla más fina para comparar después
    # nx = 172
    # ny = 42

    # Hormigon R4 como primer caso de trabajo.
    # E0 se obtuvo desde G=15875 MPa y nu=0.20: E=2G(1+nu)=38100 MPa.
    material = MaterialDamage(
        E0=38100.0,
        nu=0.20,
        ft0=4.0,
        fc0=51.2,
        Gf0=0.10,
        Gc0=10.0,
        damage_max=0.99999,
        enable_compression_damage=False
    )

    # RAS por defecto: R4 a 0 dias para iniciar la secuencia de corridas.
    # Para las siguientes corridas cambiar solo age_days:
    #   0.0, 300.0, 600.0, 900.0
    # Se usan coeficientes de degradación algo más marcados para que el ejemplo
    # sea didáctico. No están ajustados experimentalmente.
    ras_options = RASOptions(
        enabled=True,
        mode="time_law",
        time_law="larive",
        concrete_name="R4",
        age_days=300.0,
        tau_lat=188.83,
        tau_ch=161.89,
        eps_inf_vol=0.0042,
        beta_E=0.25,
        beta_ft=0.45,
        beta_fc=0.15,
        beta_Gf=0.55
    )

    xi_analysis = xi_from_ras_options(ras_options)

    problem_type = "plane_stress"

    support_span = 400.0
    x_support_left = (L - support_span) / 2.0
    x_support_right = L - x_support_left

    x_load = L / 2.0
    y_load = H

    nodes, elements, removed = generate_notched_beam_mesh(
        L=L,
        H=H,
        nx=nx,
        ny=ny,
        notch_width=notch_width,
        notch_height=notch_height
    )

    n_nodes = nodes.shape[0]
    n_elements = elements.shape[0]
    n_dof = 2 * n_nodes

    support_left = nearest_node(nodes, x_support_left, 0.0)
    support_right = nearest_node(nodes, x_support_right, 0.0)

    load_patch_nodes = find_top_load_patch_nodes(
        nodes,
        x_center=x_load,
        y_top=y_load,
        mode=options.load_patch_mode
    )

    print("\nGEOMETRÍA")
    print("----------------------------------------------")
    print(f"Largo L                 = {L:.3f} mm")
    print(f"Alto H                  = {H:.3f} mm")
    print(f"Espesor                 = {thickness:.3f} mm")
    print(f"Entalla ancho real      = {notch_width:.3f} mm")
    print(f"Entalla profundidad     = {notch_height:.3f} mm")
    print(f"Luz entre apoyos        = {support_span:.3f} mm")

    print("\nMATERIAL")
    print("----------------------------------------------")
    print(f"E0                      = {material.E0:.3f} MPa")
    print(f"nu                      = {material.nu:.4f}")
    print(f"ft0                     = {material.ft0:.3f} MPa")
    print(f"fc0                     = {material.fc0:.3f} MPa")
    print(f"Gf0                     = {material.Gf0:.5f} N/mm")
    print(f"Gc0                     = {material.Gc0:.5f} N/mm")
    print(f"damage_max              = {material.damage_max:.8f}")
    print(f"Daño compresión activo  = {material.enable_compression_damage}")

    E_eff0, ft_eff0, fc_eff0, Gf_eff0 = degraded_properties(material, ras_options, xi_analysis)
    print("\nRAS")
    print("----------------------------------------------")
    print(f"RAS activa              = {ras_options.enabled}")
    print(f"Hormigón                = {ras_options.concrete_name}")
    print(f"modo RAS                = {ras_options.mode}")
    print(f"ley temporal            = {ras_options.time_law}")
    print(f"edad de ensayo          = {ras_options.age_days:.3f} dias")
    print(f"tau_lat                 = {ras_options.tau_lat:.3f} dias")
    print(f"tau_ch                  = {ras_options.tau_ch:.3f} dias")
    print(f"xi usado                = {xi_analysis:.6f}")
    print(f"eps_inf_vol             = {ras_options.eps_inf_vol:.6e}")
    print(f"eps_RAS_inf lineal      = {ras_options.eps_ras_inf:.6e}")
    print(f"eps_RAS lineal          = {ras_options.eps_ras_inf * xi_analysis:.6e}")
    print(f"beta_E, beta_ft         = {ras_options.beta_E:.3f}, {ras_options.beta_ft:.3f}")
    print(f"beta_fc, beta_Gf        = {ras_options.beta_fc:.3f}, {ras_options.beta_Gf:.3f}")
    print(f"E_eff inicial           = {E_eff0:.3f} MPa")
    print(f"ft_eff inicial          = {ft_eff0:.4f} MPa")
    print(f"fc_eff inicial          = {fc_eff0:.4f} MPa")
    print(f"Gf_eff inicial          = {Gf_eff0:.5f} N/mm")

    output_dir = build_output_dir(ras_options, xi_analysis)
    print("\nSALIDA")
    print("----------------------------------------------")
    print(f"Carpeta de resultados   = {output_dir}")

    print("\nOPCIONES NUMÉRICAS")
    print("----------------------------------------------")
    print(f"Matriz/tangente         = {options.tangent_mode}")
    print(f"Control de pasos        = {options.step_control}")
    print(f"delta_target            = {options.delta_target:.6f} mm")
    print(f"delta_step_initial      = {options.delta_step_initial:.6e} mm")
    print(f"delta_step_min          = {options.delta_step_min:.6e} mm")
    print(f"delta_step_max          = {options.delta_step_max:.6e} mm")
    print(f"min_stiff_factor        = {options.min_stiff_factor:.3e}")

    print("\nMALLA")
    print("----------------------------------------------")
    print(f"nx, ny                  = {nx}, {ny}")
    print(f"dx aprox                = {L / nx:.6f} mm")
    print(f"dy aprox                = {H / ny:.6f} mm")
    print(f"Nodos activos           = {n_nodes}")
    print(f"Elementos Q4 activos    = {n_elements}")
    print(f"Elementos eliminados    = {removed}")
    print(f"Grados de libertad      = {n_dof}")

    print("\nNODOS PRINCIPALES")
    print("----------------------------------------------")
    print(f"Apoyo izquierdo nodo    = {support_left}, coord = {nodes[support_left]}")
    print(f"Apoyo derecho nodo      = {support_right}, coord = {nodes[support_right]}")
    print(f"Modo parche carga       = {options.load_patch_mode}")
    print("Nodos desplazamiento    =")
    for nload in load_patch_nodes:
        print(f"    nodo {nload}, coord = {nodes[nload]}")

    print("\nPRECOMPUTANDO MATRICES B Y DATOS GEOMÉTRICOS...")
    elem_data = precompute_element_data(nodes, elements)
    print("Precomputación terminada.")

    dof_support_left_x = 2 * support_left
    dof_support_left_y = 2 * support_left + 1
    dof_support_right_y = 2 * support_right + 1
    dof_load_y_list = [2 * nload + 1 for nload in load_patch_nodes]

    gp_states = initialize_gp_states(n_elements)
    gp_states = set_uniform_xi_in_gp_states(gp_states, xi_analysis)

    # ------------------------------------------------------------
    # Estado inicial antes de la flexion
    # ------------------------------------------------------------
    # Para una RAS uniforme, la etapa de expansion libre genera un campo
    # de desplazamientos aproximadamente uniforme y sin tensiones:
    #     eps_total = eps_RAS
    #     eps_mec   = eps_total - eps_RAS = 0
    #
    # Si arrancamos la flexion desde U=0 con eps_RAS != 0, el solver ve
    # una deformacion mecanica inicial -eps_RAS en toda la viga y aparece
    # un residuo artificial muy grande. Por eso inicializamos U_current
    # con la expansion libre compatible con los apoyos.
    eps_ras_initial = ras_options.eps_ras_inf * xi_analysis if ras_options.enabled else 0.0
    U_current = build_free_expansion_displacement(
        nodes=nodes,
        eps_ras_value=eps_ras_initial,
        x_ref=nodes[support_left, 0],
        y_ref=0.0
    )
    load_y_base = eps_ras_initial * H

    print("\nESTADO INICIAL RAS LIBRE")
    print("----------------------------------------------")
    print(f"eps_RAS inicial          = {eps_ras_initial:.8e}")
    print(f"u_y base en carga        = {load_y_base:.8e} mm")
    print("El delta impreso en la tabla es el desplazamiento adicional de flexion.")

    U_final = None

    displacements = []
    loads = []
    max_damages = []
    step_table = []

    accepted_step = 0
    rejected_step = 0
    delta_current = 0.0
    delta_step = options.delta_step_initial

    print("\nANÁLISIS INCREMENTAL")
    print("----------------------------------------------------------------------------------------------------------------")
    print(" paso    intento       delta [mm]      d_step [mm]        P [N]       dmax    iter    ||R||       relR    conv")
    print("----------------------------------------------------------------------------------------------------------------")

    try:
        if options.step_control.lower() == "adaptive":
            while delta_current > options.delta_target and accepted_step < options.max_accepted_steps:
                if delta_current + delta_step < options.delta_target:
                    delta_try = options.delta_target
                    step_try = delta_try - delta_current
                else:
                    delta_try = delta_current + delta_step
                    step_try = delta_step

                prescribed = build_prescribed_dict(
                    dof_support_left_x,
                    dof_support_left_y,
                    dof_support_right_y,
                    dof_load_y_list,
                    delta_try,
                    load_y_base=load_y_base
                )

                U_step, Fint_step, step_states, it, converged, norm_R, rel_R = try_one_step(
                    n_dof=n_dof,
                    elem_data=elem_data,
                    material=material,
                    ras_options=ras_options,
                    gp_states=gp_states,
                    thickness=thickness,
                    U_current=U_current,
                    prescribed=prescribed,
                    problem_type=problem_type,
                    options=options
                )

                if not converged:
                    rejected_step += 1
                    print(
                        f"{accepted_step + 1:5d}  {rejected_step:8d}  {delta_try:16.8e}  {step_try:14.6e}  "
                        f"{0.0:12.4f}  {'---':>7}  {it:5d}  {norm_R:10.3e}  {rel_R:8.2e}   False"
                    )
                    step_table.append({
                        "paso": accepted_step + 1,
                        "intento": rejected_step,
                        "delta_mm": float(delta_try),
                        "d_step_mm": float(step_try),
                        "P_N": 0.0,
                        "dmax": None,
                        "iter": int(it),
                        "norm_R": float(norm_R),
                        "rel_R": float(rel_R),
                        "conv": False
                    })

                    new_step = step_try * options.shrink_factor

                    if abs(new_step) < abs(options.delta_step_min):
                        print("\nNo converge aun con el paso mínimo.")
                        print("Se detiene la corrida y se muestran resultados aceptados.")
                        break

                    delta_step = new_step
                    continue

                gp_states = step_states
                U_current = U_step.copy()
                U_final = U_step.copy()
                delta_current = delta_try
                accepted_step += 1

                R_load_y = sum(Fint_step[dof] for dof in dof_load_y_list)
                P_equiv = -R_load_y

                damage_elem, damage_t_elem, damage_c_elem = collect_element_damage(gp_states)
                dmax = np.max(damage_elem)

                displacements.append(delta_current)
                loads.append(P_equiv)
                max_damages.append(dmax)

                print(
                    f"{accepted_step:5d}  {rejected_step:8d}  {delta_current:16.8e}  {step_try:14.6e}  "
                    f"{P_equiv:12.4f}  {dmax:7.5f}  {it:5d}  {norm_R:10.3e}  {rel_R:8.2e}   True"
                )
                step_table.append({
                    "paso": accepted_step,
                    "intento": rejected_step,
                    "delta_mm": float(delta_current),
                    "d_step_mm": float(step_try),
                    "P_N": float(P_equiv),
                    "dmax": float(dmax),
                    "iter": int(it),
                    "norm_R": float(norm_R),
                    "rel_R": float(rel_R),
                    "conv": True
                })

                if it <= 4:
                    delta_step = max(delta_step * options.grow_factor, options.delta_step_max)
                elif it >= 15:
                    delta_step = delta_step * options.shrink_factor

                if abs(delta_step) < abs(options.delta_step_min):
                    delta_step = options.delta_step_min

                if options.stop_if_damage_exceeds and dmax >= options.damage_limit_to_stop:
                    print(f"\nSe detiene la corrida: daño máximo alcanzó {dmax:.5f}.")
                    break

        elif options.step_control.lower() == "fixed":
            # Pasos fijos: conserva la alternativa clásica.
            # Si fixed_allow_substepping=True, un paso fallido se subdivide localmente.
            base_step = options.delta_target / options.fixed_n_steps

            while delta_current > options.delta_target and accepted_step < options.max_accepted_steps:
                step_try = base_step
                if delta_current + step_try < options.delta_target:
                    step_try = options.delta_target - delta_current

                local_step = step_try
                local_converged = False

                while not local_converged:
                    delta_try = delta_current + local_step
                    prescribed = build_prescribed_dict(
                        dof_support_left_x,
                        dof_support_left_y,
                        dof_support_right_y,
                        dof_load_y_list,
                        delta_try,
                        load_y_base=load_y_base
                    )

                    U_step, Fint_step, step_states, it, converged, norm_R, rel_R = try_one_step(
                        n_dof=n_dof,
                        elem_data=elem_data,
                        material=material,
                        ras_options=ras_options,
                        gp_states=gp_states,
                        thickness=thickness,
                        U_current=U_current,
                        prescribed=prescribed,
                        problem_type=problem_type,
                        options=options
                    )

                    if not converged:
                        rejected_step += 1
                        print(
                            f"{accepted_step + 1:5d}  {rejected_step:8d}  {delta_try:16.8e}  {local_step:14.6e}  "
                            f"{0.0:12.4f}  {'---':>7}  {it:5d}  {norm_R:10.3e}  {rel_R:8.2e}   False"
                        )
                        step_table.append({
                            "paso": accepted_step + 1,
                            "intento": rejected_step,
                            "delta_mm": float(delta_try),
                            "d_step_mm": float(local_step),
                            "P_N": 0.0,
                            "dmax": None,
                            "iter": int(it),
                            "norm_R": float(norm_R),
                            "rel_R": float(rel_R),
                            "conv": False
                        })

                        if not options.fixed_allow_substepping:
                            print("\nPaso fijo no convergió y no se permite substepping.")
                            raise KeyboardInterrupt

                        new_step = local_step * options.shrink_factor
                        if abs(new_step) < abs(options.delta_step_min):
                            print("\nNo converge aun con subpaso mínimo.")
                            raise KeyboardInterrupt
                        local_step = new_step
                        continue

                    gp_states = step_states
                    U_current = U_step.copy()
                    U_final = U_step.copy()
                    delta_current = delta_try
                    accepted_step += 1
                    local_converged = True

                    R_load_y = sum(Fint_step[dof] for dof in dof_load_y_list)
                    P_equiv = -R_load_y
                    damage_elem, _, _ = collect_element_damage(gp_states)
                    dmax = np.max(damage_elem)

                    displacements.append(delta_current)
                    loads.append(P_equiv)
                    max_damages.append(dmax)

                    print(
                        f"{accepted_step:5d}  {rejected_step:8d}  {delta_current:16.8e}  {local_step:14.6e}  "
                        f"{P_equiv:12.4f}  {dmax:7.5f}  {it:5d}  {norm_R:10.3e}  {rel_R:8.2e}   True"
                    )
                    step_table.append({
                        "paso": accepted_step,
                        "intento": rejected_step,
                        "delta_mm": float(delta_current),
                        "d_step_mm": float(local_step),
                        "P_N": float(P_equiv),
                        "dmax": float(dmax),
                        "iter": int(it),
                        "norm_R": float(norm_R),
                        "rel_R": float(rel_R),
                        "conv": True
                    })

                    if options.stop_if_damage_exceeds and dmax >= options.damage_limit_to_stop:
                        print(f"\nSe detiene la corrida: daño máximo alcanzó {dmax:.5f}.")
                        raise KeyboardInterrupt

        else:
            raise ValueError("step_control debe ser 'adaptive' o 'fixed'")

    except KeyboardInterrupt:
        print("\nCorrida detenida manualmente o por condición de parada.")
        print("Se mostrarán los mapas con el último estado aceptado.")

    print("\nCONTROL DE PASOS")
    print("----------------------------------------------")
    print(f"Pasos aceptados             = {accepted_step}")
    print(f"Pasos rechazados            = {rejected_step}")
    print(f"Delta final aceptado        = {delta_current:.8e} mm")
    print(f"Delta objetivo              = {options.delta_target:.8e} mm")

    # ------------------------------------------------------------
    # Guardado automático de resultados, incluso si la corrida fue cortada.
    # ------------------------------------------------------------
    if len(step_table) > 0:
        save_incremental_table(output_dir, step_table)

    if U_final is not None and len(loads) > 0:
        save_summary_files(
            output_dir=output_dir,
            material=material,
            ras_options=ras_options,
            options=options,
            xi_analysis=xi_analysis,
            eps_ras_initial=eps_ras_initial,
            E_eff0=E_eff0,
            ft_eff0=ft_eff0,
            fc_eff0=fc_eff0,
            Gf_eff0=Gf_eff0,
            displacements=displacements,
            loads=loads,
            max_damages=max_damages,
            accepted_step=accepted_step,
            rejected_step=rejected_step,
            delta_current=delta_current,
            nodes=nodes,
            elements=elements,
            gp_states=gp_states
        )
        save_result_figures(
            output_dir=output_dir,
            nodes=nodes,
            elements=elements,
            U_final=U_final,
            gp_states=gp_states,
            displacements=displacements,
            loads=loads,
            max_damages=max_damages,
            L=L,
            support_left=support_left,
            support_right=support_right,
            load_patch_nodes=load_patch_nodes
        )
    else:
        print("No hay pasos aceptados: no se guardan resumen ni gráficos finales.")

    show_results(
        nodes=nodes,
        elements=elements,
        U_final=U_final,
        gp_states=gp_states,
        displacements=displacements,
        loads=loads,
        max_damages=max_damages,
        L=L,
        support_left=support_left,
        support_right=support_right,
        load_patch_nodes=load_patch_nodes
    )


if __name__ == "__main__":
    main()
