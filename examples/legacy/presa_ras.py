import numpy as np
import os
import json
import argparse
from pathlib import Path
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection, LineCollection
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve, MatrixRankWarning
from scipy.spatial import Delaunay
import warnings


# =============================================================================
# PRESA DE GRAVEDAD - OVERTOPPING 0 AÑOS - MALLA T3 CONFORME
#
# VERSION RECOMENDADA
# Base: v6_dos_curvas_tabla.
# Motivo: fue la configuración que llegó más lejos en las pruebas del usuario
# manteniendo buena velocidad y una curva aceptable.
# =============================================================================
#
# Esta versión deja todos los parámetros principales en un solo bloque.
#
# Incluye:
# - malla triangular T3 que copia los bordes inclinados del polígono
# - presión hidrostática triangular / trapezoidal según nivel de agua
# - matriz global sparse
# - precomputación de B, área, he y dofs
# - daño escalar simple en tracción
# - opciones de tangente: elastic / secant / numerical / numerical_hybrid / strain_numerical / strain_numerical_hybrid
# - pasos de carga adaptativos con reducción de dH si no converge
# - al final abre una sola ventana con todos los gráficos
# - por defecto NO guarda archivos
#
# =============================================================================


# =============================================================================
# BLOQUE UNICO DE PARAMETROS FACILES DE TOCAR
# =============================================================================

PARAM = {
    # -------------------------------------------------------------------------
    # Selector del ensayo
    # -------------------------------------------------------------------------
    # 0  -> reproduce el overtopping de la presa sana, como en la versión validada.
    # 16 -> simula 16 años con nivel variable + RAS y luego hace overtopping.
    "ANIOS_RAS": 16,

    # -------------------------------------------------------------------------
    # Control general
    # -------------------------------------------------------------------------
    "SHOW_WINDOWS_AT_END": False,      # para corridas de reporte conviene no abrir ventanas
    "SAVE_RESULTS": True,              # guarda tablas, metadatos y figuras
    "RESULT_PREFIX": "presa_T3",
    "OUTPUT_ROOT": "salida_reporte_RAS",
    "SAVE_FIG_DPI": 220,

    # -------------------------------------------------------------------------
    # Geometría en metros
    # Puntos en sentido antihorario desde el inferior izquierdo
    # -------------------------------------------------------------------------
    "POLYGON_M": np.array([
        [0.00,    0.00],    # P1
        [70.00,   0.00],    # P2
        [19.20,  66.00],    # P3
        [14.80, 103.00],    # P4
        [0.00,  103.00],    # P5
    ], dtype=float),

    "H_DAM_M": 103.0,

    # -------------------------------------------------------------------------
    # Malla
    # -------------------------------------------------------------------------
    "MESH_SIZE_M": 2.0,                # tamaño medio de elemento en m

    # -------------------------------------------------------------------------
    # Material
    # -------------------------------------------------------------------------
    "E": 22000.0,                      # MPa
    "NU": 0.20,
    "FT": 2.10,                        # MPa

    # IMPORTANTE:
    # para control de carga y elementos de 2 m, Gf = 0.080 resultó muy frágil.
    # Por eso se deja 0.300 para suavizar el inicio del daño.
    "GF": 0.300,                       # N/mm

    "DAMAGE_MAX": 0.9995,
    "MIN_STIFF_FACTOR": 1e-6,

    # -------------------------------------------------------------------------
    # Pesos específicos
    # -------------------------------------------------------------------------
    "GAMMA_C": 2.40e-5,                # N/mm3 hormigón
    "GAMMA_W": 9.81e-6,                # N/mm3 agua

    # espesor fuera del plano
    "THICKNESS": 1000.0,               # mm = 1 m

    # -------------------------------------------------------------------------
    # Modelo no lineal
    # -------------------------------------------------------------------------
    "USE_DAMAGE": True,                # True: con daño; False: elástico

    # Recomendación actual:
    # strain_numerical_hybrid usa tangente numérica 3x3 solo en elementos dañados.
    # Es más estable que secant y mucho más barato que numerical sobre los 6 GL.
    "TANGENT_MODE": "strain_numerical_hybrid",          # elastic / secant / numerical / numerical_hybrid

    # -------------------------------------------------------------------------
    # Newton / equilibrio
    # -------------------------------------------------------------------------
    "MAX_ITER": 30,
    "TOL_ABS": 1e-3,
    "TOL_REL": 1e-5,

    # line search
    "LINE_SEARCH_REDUCTION": 0.5,
    "LINE_SEARCH_MIN": 1e-4,
    "USE_LINE_SEARCH": False,            # False es más rápido; True es más robusto

    # -------------------------------------------------------------------------
    # Carga hidráulica
    # -------------------------------------------------------------------------
    "H_START_M": 92.0,                 # nivel desde donde interesa el overtopping
    "H_TARGET_M": 120.0,               # nivel objetivo final

    # Rampa inicial:
    # si True, sube de 0 a H_START en varios pasos antes del overtopping.
    "RAMP_INITIAL_LEVEL": False,
    "H_RAMP_INITIAL_STEP_M": 12.0,     # primer paso de rampa hasta 92 m
    "H_RAMP_STEP_MAX_M": 2.0,          # paso máximo durante rampa inicial

    # Paso adaptativo para overtopping desde H_START hasta H_TARGET
    "DH_INITIAL_M": 0.50,
    "DH_MIN_M": 0.020,
    "DH_MAX_M": 0.50,

    # criterio de crecimiento/reducción de paso
    "ITER_GOOD": 5,
    "ITER_BAD": 22,
    "SHRINK_ON_HIGH_ITER_ACCEPTED": False,
    "GROW_AFTER_ACCEPTED_STREAK": 6,
    "GROW_EVEN_WITH_HIGH_ITER": True,
    "PRINT_EVERY": 10,
    "PRINT_ALL_UNTIL_STEP": 60,
    "PRINT_TABLE_AT_END": True,
    "PRINT_LAST_N_TABLE": 30,
    "STEP_GROWTH": 1.20,
    "STEP_REDUCTION": 0.50,

    # -------------------------------------------------------------------------
    # RAS - parámetros del ejemplo de presa del documento 1111111.pdf
    # -------------------------------------------------------------------------
    "RAS_ENABLED": True,
    "RAS_SERVICE_YEARS": 16,

    # Paso temporal de servicio. Con 10 días se hacen 584 pasos en 16 años.
    # Si querés más detalle todavía, usar 5.0 días.
    "RAS_DT_DAYS": 3.0,

    # Nivel anual de agua en servicio: máximo invierno, mínimo verano.
    "H_SERVICE_MAX_M": 92.0,
    "H_SERVICE_MIN_M": 37.0,

    # Parámetros químicos del cuadro del ejemplo de presa.
    "RAS_TAU_L_DAYS": 130.0,
    "RAS_TAU_C_DAYS": 66.0,
    "RAS_EPS_INF": 0.00289,
    "RAS_S": 0.0873,
    "RAS_TEMP_PARAM": 9400.0,
    "RAS_UL": 38.0,
    "RAS_UC": 5400.0,

    # Parámetros térmicos del cuadro del ejemplo.
    "KT": 3.0,
    "CT": 2327500.0,

    # Modelo mecánico simplificado para la etapa RAS.
    # Estos factores controlan degradación de propiedades con xi.
    "RAS_BETA_E": 0.200143,
    "RAS_BETA_FT": 0.200429,
    "RAS_BETA_GF": 0.071429,
    "RAS_E_MIN_FACTOR": 0.70,
    "RAS_FT_MIN_FACTOR": 0.65,
    "RAS_GF_MIN_FACTOR": 0.95,

    # Temperatura anual simplificada para aproximar el campo térmico:
    # agua: 0 a 20 °C, aire: 0 a 8 °C, base: 6 °C.
    "TEMP_BASE_C": 6.0,
    "TEMP_WATER_MAX_C": 20.0,
    "TEMP_AIR_MAX_C": 8.0,

    # Control numérico de la etapa de servicio RAS
    # Salida en pantalla de la etapa RAS:
    # se imprime cada RAS_PRINT_EVERY_DAYS, pero se calcula cada RAS_DT_DAYS.
    "RAS_PRINT_EVERY_DAYS": 30.0,
    "RAS_SAVE_SNAPSHOTS_EVERY_YEARS": 2,
    # Mapas/deformadas durante un ciclo representativo de servicio.
    # Se guardan en años 15.00, 15.25, 15.50, 15.75 y 16.00.
    "SERVICE_SNAPSHOT_YEARS": [15.00, 15.25, 15.50, 15.75, 16.00],

    # Control de agresividad de RAS.
    # eps_inf se interpreta de forma conservadora como expansión volumétrica;
    # la deformación lineal usada en 2D se toma como eps_inf / RAS_LINEAR_DIVISOR.
    "RAS_LINEAR_DIVISOR": 3.0,
    "RAS_ACTIVITY_MIN": 0.00,
    "RAS_ACTIVITY_POWER": 2.0,

    # En esta versión se activa una expansión RAS muy suave.
    # eps_ras = RAS_EXPANSION_SCALE * RAS_EPS_INF / RAS_LINEAR_DIVISOR * xi.
    # Con los valores adoptados, al final de 16 años:
    # eps_ras ~= 0.03 * 0.00289 / 3 * 0.70 = 2.02e-5.
    # Es decir: hay expansión, pero su efecto queda controlado.
    "RAS_EXPANSION_SCALE": 0.03,
    "RAS_USE_EXPANSION_STRAIN": True,

    # RAS uniforme para toda la presa.
    # xi(t) crece suavemente hasta este valor al final de los 16 años.
    # Se fija alto para mostrar que a los 16 años la reacción avanzó bastante.
    # El efecto mecánico se mantiene controlado bajando los beta de degradación.
    "RAS_UNIFORM_XI_TARGET_16Y": 0.70,
    "RAS_UNIFORM_RATE": 3.0,

    # Para el caso con RAS, las curvas de overtopping usan desplazamiento
    # incremental respecto del estado final de los 16 años.
    "PLOT_OVERTOPPING_INCREMENTAL_FROM_RAS": True,

    # -------------------------------------------------------------------------
    # Gráficos
    # -------------------------------------------------------------------------
    # Si True, la curva principal muestra solo desde H_START.
    # Si False, muestra toda la rampa desde niveles bajos.
    "PLOT_ONLY_OVERTOPPING": True,
    "LOAD_GRAPH_MODE": "base_reaction",   # base_reaction o water_level

    # escala automática para deformada:
    # la deformada tendrá aprox este porcentaje de la altura de la presa
    "DEFORMED_REL_SCALE": 0.10,
}


# =============================================================================
# DERIVADOS DE PARAMETROS
# =============================================================================

MM = 1000.0

ANIOS_RAS = int(PARAM["ANIOS_RAS"])

SHOW_WINDOWS_AT_END = PARAM["SHOW_WINDOWS_AT_END"]
SAVE_RESULTS = PARAM["SAVE_RESULTS"]
RESULT_PREFIX = PARAM["RESULT_PREFIX"]
OUTPUT_ROOT = PARAM["OUTPUT_ROOT"]
SAVE_FIG_DPI = PARAM["SAVE_FIG_DPI"]

polygon_m = PARAM["POLYGON_M"]
polygon = polygon_m * MM
H_DAM = PARAM["H_DAM_M"] * MM

mesh_size = PARAM["MESH_SIZE_M"] * MM

E = PARAM["E"]
nu = PARAM["NU"]
ft = PARAM["FT"]
Gf = PARAM["GF"]

damage_max = PARAM["DAMAGE_MAX"]
min_stiff_factor = PARAM["MIN_STIFF_FACTOR"]

gamma_c = PARAM["GAMMA_C"]
gamma_w = PARAM["GAMMA_W"]
thickness = PARAM["THICKNESS"]

USE_DAMAGE = PARAM["USE_DAMAGE"]
TANGENT_MODE = PARAM["TANGENT_MODE"]

MAX_ITER = PARAM["MAX_ITER"]
TOL_ABS = PARAM["TOL_ABS"]
TOL_REL = PARAM["TOL_REL"]
LINE_SEARCH_REDUCTION = PARAM["LINE_SEARCH_REDUCTION"]
LINE_SEARCH_MIN = PARAM["LINE_SEARCH_MIN"]
USE_LINE_SEARCH = PARAM["USE_LINE_SEARCH"]

H_start = PARAM["H_START_M"] * MM
H_target = PARAM["H_TARGET_M"] * MM

RAMP_INITIAL_LEVEL = PARAM["RAMP_INITIAL_LEVEL"]
H_ramp_initial_step = PARAM["H_RAMP_INITIAL_STEP_M"] * MM
H_ramp_step_max = PARAM["H_RAMP_STEP_MAX_M"] * MM

dH_initial = PARAM["DH_INITIAL_M"] * MM
dH_min = PARAM["DH_MIN_M"] * MM
dH_max = PARAM["DH_MAX_M"] * MM

ITER_GOOD = PARAM["ITER_GOOD"]
ITER_BAD = PARAM["ITER_BAD"]
SHRINK_ON_HIGH_ITER_ACCEPTED = PARAM["SHRINK_ON_HIGH_ITER_ACCEPTED"]
GROW_AFTER_ACCEPTED_STREAK = PARAM["GROW_AFTER_ACCEPTED_STREAK"]
GROW_EVEN_WITH_HIGH_ITER = PARAM["GROW_EVEN_WITH_HIGH_ITER"]
PRINT_EVERY = PARAM["PRINT_EVERY"]
PRINT_ALL_UNTIL_STEP = PARAM["PRINT_ALL_UNTIL_STEP"]
PRINT_TABLE_AT_END = PARAM["PRINT_TABLE_AT_END"]
PRINT_LAST_N_TABLE = PARAM["PRINT_LAST_N_TABLE"]
STEP_GROWTH = PARAM["STEP_GROWTH"]
STEP_REDUCTION = PARAM["STEP_REDUCTION"]

PLOT_ONLY_OVERTOPPING = PARAM["PLOT_ONLY_OVERTOPPING"]
LOAD_GRAPH_MODE = PARAM["LOAD_GRAPH_MODE"]
DEFORMED_REL_SCALE = PARAM["DEFORMED_REL_SCALE"]

# RAS
RAS_ENABLED = PARAM["RAS_ENABLED"]
RAS_SERVICE_YEARS = PARAM["RAS_SERVICE_YEARS"]
RAS_DT_DAYS = PARAM["RAS_DT_DAYS"]
H_SERVICE_MAX = PARAM["H_SERVICE_MAX_M"] * MM
H_SERVICE_MIN = PARAM["H_SERVICE_MIN_M"] * MM

RAS_TAU_L_DAYS = PARAM["RAS_TAU_L_DAYS"]
RAS_TAU_C_DAYS = PARAM["RAS_TAU_C_DAYS"]
RAS_EPS_INF = PARAM["RAS_EPS_INF"]
RAS_S = PARAM["RAS_S"]
RAS_TEMP_PARAM = PARAM["RAS_TEMP_PARAM"]
RAS_UL = PARAM["RAS_UL"]
RAS_UC = PARAM["RAS_UC"]

KT = PARAM["KT"]
CT = PARAM["CT"]

RAS_BETA_E = PARAM["RAS_BETA_E"]
RAS_BETA_FT = PARAM["RAS_BETA_FT"]
RAS_BETA_GF = PARAM["RAS_BETA_GF"]
RAS_E_MIN_FACTOR = PARAM["RAS_E_MIN_FACTOR"]
RAS_FT_MIN_FACTOR = PARAM["RAS_FT_MIN_FACTOR"]
RAS_GF_MIN_FACTOR = PARAM["RAS_GF_MIN_FACTOR"]

TEMP_BASE_C = PARAM["TEMP_BASE_C"]
TEMP_WATER_MAX_C = PARAM["TEMP_WATER_MAX_C"]
TEMP_AIR_MAX_C = PARAM["TEMP_AIR_MAX_C"]

RAS_PRINT_EVERY_DAYS = PARAM["RAS_PRINT_EVERY_DAYS"]
RAS_SAVE_SNAPSHOTS_EVERY_YEARS = PARAM["RAS_SAVE_SNAPSHOTS_EVERY_YEARS"]
SERVICE_SNAPSHOT_YEARS = PARAM["SERVICE_SNAPSHOT_YEARS"]

RAS_LINEAR_DIVISOR = PARAM["RAS_LINEAR_DIVISOR"]
RAS_ACTIVITY_MIN = PARAM["RAS_ACTIVITY_MIN"]
RAS_ACTIVITY_POWER = PARAM["RAS_ACTIVITY_POWER"]
RAS_EXPANSION_SCALE = PARAM["RAS_EXPANSION_SCALE"]
RAS_USE_EXPANSION_STRAIN = PARAM["RAS_USE_EXPANSION_STRAIN"]
RAS_UNIFORM_XI_TARGET_16Y = PARAM["RAS_UNIFORM_XI_TARGET_16Y"]
RAS_UNIFORM_RATE = PARAM["RAS_UNIFORM_RATE"]
PLOT_OVERTOPPING_INCREMENTAL_FROM_RAS = PARAM["PLOT_OVERTOPPING_INCREMENTAL_FROM_RAS"]

# Campos globales actualizados por la etapa RAS.
# Para ANIOS_RAS = 0 quedan en cero y el código reproduce el ensayo validado.
CURRENT_XI = None
CURRENT_EPS_RAS = None
CURRENT_E_FACTOR = None
CURRENT_FT_FACTOR = None
CURRENT_GF_FACTOR = None

# Historias de la etapa de servicio RAS.
# Se inicializan siempre para que el caso ANIOS_RAS = 0 también pueda guardar salida.
SERVICE_TIME_DAYS_HIST = []
SERVICE_TIME_YEARS_HIST = []
SERVICE_UX_P5_HIST = []
SERVICE_H_WATER_HIST = []
SERVICE_XI_MAX_HIST = []
SERVICE_DMAX_HIST = []



# =============================================================================
# UTILIDADES DE SALIDA / REPORTE
# =============================================================================

RUN_OUTPUT_DIR = None


def json_safe(obj):
    """Convierte objetos numpy a tipos simples para guardar JSON."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def preparar_directorio_salida():
    global RUN_OUTPUT_DIR
    case_name = f"caso_{ANIOS_RAS:02d}_anios"
    RUN_OUTPUT_DIR = Path(OUTPUT_ROOT) / case_name
    (RUN_OUTPUT_DIR / "figuras" / "finales").mkdir(parents=True, exist_ok=True)
    (RUN_OUTPUT_DIR / "figuras" / "servicio").mkdir(parents=True, exist_ok=True)
    (RUN_OUTPUT_DIR / "datos").mkdir(parents=True, exist_ok=True)
    return RUN_OUTPUT_DIR


def ruta_figura(nombre, subcarpeta="finales"):
    if RUN_OUTPUT_DIR is None:
        preparar_directorio_salida()
    return RUN_OUTPUT_DIR / "figuras" / subcarpeta / nombre


def guardar_csv(path, header, arr):
    np.savetxt(path, arr, delimiter=",", header=header, comments="")


def save_current_figure(path):
    plt.tight_layout()
    plt.savefig(path, dpi=SAVE_FIG_DPI, bbox_inches="tight")
    plt.close()


def plot_curva_overtopping_individual(ux_hist, Hratio_hist, H_hist, Rx_hist, dmax_hist):
    ux_plot = np.array(ux_hist, dtype=float)
    hr_plot = np.array(Hratio_hist, dtype=float)
    H_plot = np.array(H_hist, dtype=float)
    Rx_plot = np.array(Rx_hist, dtype=float)
    dmax_plot = np.array(dmax_hist, dtype=float)

    mask = H_plot >= H_start - 1e-9
    ux_plot = ux_plot[mask]
    hr_plot = hr_plot[mask]
    Rx_plot = Rx_plot[mask]
    dmax_plot = dmax_plot[mask]

    plt.figure(figsize=(8, 5))
    plt.plot(ux_plot, hr_plot, marker="o", lw=1.5)
    plt.xlabel("Desplazamiento horizontal incremental P5 [mm]")
    plt.ylabel("H agua / 103 m")
    plt.title("Overtopping: altura relativa vs desplazamiento")
    plt.grid(True)
    save_current_figure(ruta_figura("01_curva_Hsobre103_vs_uxP5.png"))

    plt.figure(figsize=(8, 5))
    plt.plot(ux_plot, np.abs(Rx_plot) / 1000.0, marker="o", lw=1.5)
    plt.xlabel("Desplazamiento horizontal incremental P5 [mm]")
    plt.ylabel("Reacción horizontal total de base |Rx| [kN]")
    plt.title("Overtopping: reacción de base vs desplazamiento")
    plt.grid(True)
    save_current_figure(ruta_figura("02_curva_Rx_base_vs_uxP5.png"))

    plt.figure(figsize=(8, 5))
    plt.plot(hr_plot, dmax_plot, marker="o", lw=1.5)
    plt.xlabel("H agua / 103 m")
    plt.ylabel("dmax [-]")
    plt.title("Evolución del daño durante el overtopping")
    plt.grid(True)
    save_current_figure(ruta_figura("03_curva_dmax_vs_Hsobre103.png"))


def plot_mapa_elemental(nombre, titulo, nodes, elements, values, cmap="viridis"):
    fig, ax = plt.subplots(figsize=(7, 9))
    pc = make_poly_collection(nodes, elements, values, cmap=cmap)
    ax.add_collection(pc)
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.set_title(titulo)
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    fig.colorbar(pc, ax=ax, shrink=0.8)
    save_current_figure(ruta_figura(nombre))


def plot_deformada_individual(nombre, titulo, nodes, elements, U, node_p5=None, subcarpeta="finales"):
    fig, ax = plt.subplots(figsize=(7, 9))
    pc0 = make_poly_collection(nodes, elements, None)
    ax.add_collection(pc0)

    U_nodes = U.reshape((-1, 2))
    maxu = np.max(np.sqrt(U_nodes[:, 0]**2 + U_nodes[:, 1]**2))
    scale = DEFORMED_REL_SCALE * H_DAM / maxu if maxu > 0 else 1.0
    def_nodes = nodes + scale * U_nodes
    polys_def = [def_nodes[conn] / MM for conn in elements]
    pc1 = PolyCollection(polys_def, facecolors="none", edgecolors="blue", linewidths=0.25)
    ax.add_collection(pc1)

    if node_p5 is not None:
        p5 = nodes[node_p5] / MM
        p5d = def_nodes[node_p5] / MM
        ax.plot(p5[0], p5[1], "ko", markersize=3, label="P5 original")
        ax.plot(p5d[0], p5d[1], "ro", markersize=3, label="P5 deformado")
        ax.legend(loc="best")

    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.set_title(f"{titulo}\nEscala deformada = {scale:.1f}")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    save_current_figure(ruta_figura(nombre, subcarpeta=subcarpeta))


def plot_modelo_individual(nodes, elements, fixed, up_edges, node_p5):
    fig, ax = plt.subplots(figsize=(7, 9))
    pc = make_poly_collection(nodes, elements, None)
    ax.add_collection(pc)
    fixed_nodes = sorted(set([d // 2 for d in fixed]))
    pf = nodes[fixed_nodes] / MM
    ax.plot(pf[:, 0], pf[:, 1], "^", markersize=3, label="Base empotrada")
    segs = [[nodes[i] / MM, nodes[j] / MM] for i, j in up_edges]
    lc = LineCollection(segs, colors="red", linewidths=1.5, label="Paramento aguas arriba")
    ax.add_collection(lc)
    p5 = nodes[node_p5] / MM
    ax.plot(p5[0], p5[1], "bo", label="P5 control")
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.set_title("Malla, apoyos y borde hidráulico")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.legend(loc="best")
    save_current_figure(ruta_figura("00_modelo_malla_apoyos.png"))


def plot_ras_service_history_guardar():
    if len(globals().get('SERVICE_TIME_DAYS_HIST', [])) == 0:
        return
    t_years = np.array(SERVICE_TIME_YEARS_HIST, dtype=float)
    ux = np.array(SERVICE_UX_P5_HIST, dtype=float)
    Hm = np.array(SERVICE_H_WATER_HIST, dtype=float) / MM
    xi = np.array(SERVICE_XI_MAX_HIST, dtype=float)
    dmax = np.array(SERVICE_DMAX_HIST, dtype=float)

    fig, axs = plt.subplots(2, 2, figsize=(13, 8))
    axs = axs.ravel()
    axs[0].plot(t_years, ux, lw=1.8)
    axs[0].set_xlabel("Tiempo [años]")
    axs[0].set_ylabel("ux(P5) [mm]")
    axs[0].set_title("P5 durante servicio con RAS")
    axs[0].grid(True)
    axs[1].plot(t_years, Hm, lw=1.5)
    axs[1].set_xlabel("Tiempo [años]")
    axs[1].set_ylabel("Nivel de agua H [m]")
    axs[1].set_title("Ciclo anual del embalse")
    axs[1].grid(True)
    axs[2].plot(t_years, xi, lw=1.5)
    axs[2].set_xlabel("Tiempo [años]")
    axs[2].set_ylabel("xi max [-]")
    axs[2].set_title("Avance máximo de RAS")
    axs[2].grid(True)
    axs[3].plot(t_years, dmax, lw=1.5)
    axs[3].set_xlabel("Tiempo [años]")
    axs[3].set_ylabel("dmax [-]")
    axs[3].set_title("Daño máximo durante servicio")
    axs[3].grid(True)
    save_current_figure(ruta_figura("servicio_historia_P5_H_xi_dmax.png", subcarpeta="servicio"))


def guardar_resultados_completos(nodes, elements, fixed, up_edges, node_p5, U, U_ref_overtopping,
                                last_damage, last_sx, last_sy,
                                ux_hist, Hratio_hist, H_hist, dmax_hist, Rx_hist,
                                accepted, rejected, reason, ras_snapshots):
    outdir = preparar_directorio_salida()
    datos_dir = outdir / "datos"

    # Historia de overtopping
    arr = np.column_stack([
        np.arange(1, len(H_hist) + 1),
        np.array(H_hist) / MM,
        np.array(Hratio_hist),
        np.array(ux_hist),
        np.array(dmax_hist),
        np.array(Rx_hist) / 1000.0,
        np.abs(np.array(Rx_hist)) / 1000.0,
    ])
    guardar_csv(datos_dir / "overtopping_historia.csv",
                "paso,H_m,H_sobre_103,uxP5_mm,dmax,Rx_base_kN,abs_Rx_base_kN", arr)

    # Historia de servicio RAS
    if len(globals().get('SERVICE_TIME_DAYS_HIST', [])) > 0:
        arrs = np.column_stack([
            np.array(SERVICE_TIME_DAYS_HIST),
            np.array(SERVICE_TIME_YEARS_HIST),
            np.array(SERVICE_H_WATER_HIST) / MM,
            np.array(SERVICE_UX_P5_HIST),
            np.array(SERVICE_XI_MAX_HIST),
            np.array(SERVICE_DMAX_HIST),
        ])
        guardar_csv(datos_dir / "servicio_RAS_historia.csv",
                    "tiempo_dias,tiempo_anios,H_m,uxP5_mm,xi_max,dmax", arrs)

    # Arrays para reconstruir mapas si hiciera falta
    np.savez_compressed(
        datos_dir / "modelo_y_estado_final.npz",
        nodes=nodes, elements=elements, U=U, U_ref_overtopping=U_ref_overtopping,
        damage=last_damage, sigma_x=last_sx, sigma_y=last_sy,
        xi=CURRENT_XI if CURRENT_XI is not None else np.zeros(len(elements)),
        eps_ras=CURRENT_EPS_RAS if CURRENT_EPS_RAS is not None else np.zeros((len(elements), 3)),
    )

    # Metadatos / resumen
    if len(H_hist) > 0:
        final = {
            "H_final_m": float(H_hist[-1] / MM),
            "H_sobre_103_final": float(Hratio_hist[-1]),
            "uxP5_final_mm": float(ux_hist[-1]),
            "dmax_final": float(dmax_hist[-1]),
            "Rx_base_final_kN": float(Rx_hist[-1] / 1000.0),
        }
    else:
        final = {}

    if ANIOS_RAS > 0:
        xi_fin = RAS_UNIFORM_XI_TARGET_16Y
        ras_resumen = {
            "xi_final": float(xi_fin),
            "expansion_activada": bool(RAS_USE_EXPANSION_STRAIN),
            "eps_RAS_final_estimada": float(RAS_EXPANSION_SCALE * RAS_EPS_INF / RAS_LINEAR_DIVISOR * xi_fin),
            "factor_E_final": float(max(1.0 - RAS_BETA_E * xi_fin, RAS_E_MIN_FACTOR)),
            "factor_ft_final": float(max(1.0 - RAS_BETA_FT * xi_fin, RAS_FT_MIN_FACTOR)),
            "factor_Gf_final": float(max(1.0 - RAS_BETA_GF * xi_fin, RAS_GF_MIN_FACTOR)),
        }
    else:
        ras_resumen = {
            "xi_final": 0.0,
            "expansion_activada": False,
            "eps_RAS_final_estimada": 0.0,
            "factor_E_final": 1.0,
            "factor_ft_final": 1.0,
            "factor_Gf_final": 1.0,
        }

    metadata = {
        "fecha_corrida": datetime.now().isoformat(timespec="seconds"),
        "caso_anios_RAS": int(ANIOS_RAS),
        "directorio": str(outdir),
        "parametros": json_safe(PARAM),
        "geometria_m": json_safe(polygon_m),
        "malla": {"nodos": int(len(nodes)), "elementos_T3": int(len(elements)), "gl_totales": int(2 * len(nodes))},
        "nodo_control_P5": {"indice": int(node_p5), "coord_m": json_safe(nodes[node_p5] / MM)},
        "condiciones_borde": {"gl_fijos_base": int(len(fixed)), "aristas_aguas_arriba": int(len(up_edges))},
        "ras_resumen": ras_resumen,
        "control_pasos": {"aceptados": int(accepted), "rechazados": int(rejected), "motivo_parada": reason},
        "final": final,
    }
    with open(datos_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # Figuras finales individuales
    plot_modelo_individual(nodes, elements, fixed, up_edges, node_p5)
    plot_curva_overtopping_individual(ux_hist, Hratio_hist, H_hist, Rx_hist, dmax_hist)
    if last_damage is not None:
        plot_mapa_elemental("04_mapa_danio_final.png", "Daño final", nodes, elements, last_damage, cmap="inferno")
        plot_mapa_elemental("05_mapa_sigma_x_final.png", r"Tensión horizontal final $\sigma_x$ [MPa]", nodes, elements, last_sx, cmap="coolwarm")
        plot_mapa_elemental("06_mapa_sigma_y_final.png", r"Tensión vertical final $\sigma_y$ [MPa]", nodes, elements, last_sy, cmap="coolwarm")
        U_plot = (U - U_ref_overtopping) if (ANIOS_RAS > 0 and PLOT_OVERTOPPING_INCREMENTAL_FROM_RAS) else U
        plot_deformada_individual("07_deformada_final_incremental.png", "Deformada final del overtopping", nodes, elements, U_plot, node_p5)

    # Historia y snapshots de servicio
    if ANIOS_RAS > 0:
        plot_ras_service_history_guardar()
        for key, snap in ras_snapshots.items():
            U_snap = snap.get("U", None)
            if U_snap is None:
                continue
            year = snap.get("year", key)
            Hm = snap.get("H_m", np.nan)
            name = f"deformada_servicio_anio_{float(year):05.2f}.png" if isinstance(year, (int, float, np.floating)) else f"deformada_servicio_{key}.png"
            title = f"Deformada durante servicio RAS - año {float(year):.2f}, H={Hm:.2f} m" if isinstance(year, (int, float, np.floating)) else f"Deformada servicio RAS - {key}"
            plot_deformada_individual(name, title, nodes, elements, U_snap, node_p5, subcarpeta="servicio")

    print("\nSALIDA GUARDADA")
    print("--------------------------------------------------------------")
    print(f"Carpeta de resultados      = {outdir.resolve()}")
    print(f"Datos                      = {(outdir / 'datos').resolve()}")
    print(f"Figuras                    = {(outdir / 'figuras').resolve()}")


# =============================================================================
# GEOMETRIA / MALLA
# =============================================================================

def point_in_polygon(x, y, poly):
    inside = False
    n = len(poly)

    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]

        cond = ((y1 > y) != (y2 > y))
        if cond:
            xinters = (x2 - x1) * (y - y1) / (y2 - y1 + 1e-30) + x1
            if x < xinters:
                inside = not inside

    return inside


def points_on_segment(p1, p2, h):
    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)

    L = np.linalg.norm(p2 - p1)
    n = max(int(np.ceil(L / h)), 1)

    pts = []
    for i in range(n + 1):
        t = i / n
        pts.append((1.0 - t) * p1 + t * p2)

    return pts


def unique_points(points, tol=1e-7):
    seen = {}
    out = []

    for p in points:
        key = (round(p[0] / tol), round(p[1] / tol))
        if key not in seen:
            seen[key] = True
            out.append(p)

    return np.array(out, dtype=float)


def build_conforming_t3_mesh(poly, h):
    """
    Malla triangular que copia los bordes reales de la presa.

    Procedimiento:
    1) crea puntos sobre todos los lados del polígono;
    2) agrega puntos interiores;
    3) genera Delaunay;
    4) conserva solo triángulos cuyo centroide cae dentro del polígono.
    """
    xmin, ymin = np.min(poly, axis=0)
    xmax, ymax = np.max(poly, axis=0)

    pts = []

    # puntos de borde
    for i in range(len(poly)):
        p1 = poly[i]
        p2 = poly[(i + 1) % len(poly)]
        pts.extend(points_on_segment(p1, p2, h))

    # puntos interiores
    xs = np.arange(xmin + h, xmax, h)
    ys = np.arange(ymin + h, ymax, h)

    for x in xs:
        for y in ys:
            if point_in_polygon(x, y, poly):
                pts.append(np.array([x, y], dtype=float))

    pts = unique_points(pts)

    tri = Delaunay(pts)
    elements = []

    for simplex in tri.simplices:
        coords = pts[simplex]
        centroid = np.mean(coords, axis=0)

        if not point_in_polygon(centroid[0], centroid[1], poly):
            continue

        # filtra triángulos demasiado largos
        max_edge = 0.0
        for a, b in [(0, 1), (1, 2), (2, 0)]:
            max_edge = max(max_edge, np.linalg.norm(coords[a] - coords[b]))

        if max_edge > 2.75 * h:
            continue

        # orientación antihoraria
        A2 = (
            (coords[1, 0] - coords[0, 0]) * (coords[2, 1] - coords[0, 1])
            - (coords[2, 0] - coords[0, 0]) * (coords[1, 1] - coords[0, 1])
        )

        if abs(A2) < 1e-12:
            continue

        if A2 < 0.0:
            simplex = [simplex[0], simplex[2], simplex[1]]

        elements.append(simplex)

    elements = np.array(elements, dtype=int)

    # compacta nodos usados
    used = np.unique(elements.ravel())
    old_to_new = -np.ones(len(pts), dtype=int)
    old_to_new[used] = np.arange(len(used), dtype=int)

    nodes = pts[used].copy()
    elements = old_to_new[elements]

    return nodes, elements


def find_nearest_node(nodes, point):
    d2 = np.sum((nodes - point) ** 2, axis=1)
    return int(np.argmin(d2))


# =============================================================================
# MATERIAL Y ELEMENTO T3
# =============================================================================

def constitutive_plane_strain(E, nu):
    fac = E / ((1.0 + nu) * (1.0 - 2.0 * nu))

    D = fac * np.array([
        [1.0 - nu, nu, 0.0],
        [nu, 1.0 - nu, 0.0],
        [0.0, 0.0, 0.5 * (1.0 - 2.0 * nu)]
    ])

    return D


Dmat = constitutive_plane_strain(E, nu)


def triangle_area_signed(coords):
    x1, y1 = coords[0]
    x2, y2 = coords[1]
    x3, y3 = coords[2]

    return 0.5 * ((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1))


def precompute_t3_data(nodes, elements):
    """
    Precalcula:
    - matriz B
    - área
    - longitud característica he
    - grados de libertad
    - centroide
    """
    data = []

    for e, conn in enumerate(elements):
        coords = nodes[conn]

        A_signed = triangle_area_signed(coords)
        A = abs(A_signed)

        if A <= 1e-12:
            raise ValueError(f"Elemento {e} con área no positiva.")

        if A_signed < 0.0:
            raise ValueError(f"Elemento {e} invertido.")

        x1, y1 = coords[0]
        x2, y2 = coords[1]
        x3, y3 = coords[2]

        b1 = y2 - y3
        b2 = y3 - y1
        b3 = y1 - y2

        c1 = x3 - x2
        c2 = x1 - x3
        c3 = x2 - x1

        B = (1.0 / (2.0 * A_signed)) * np.array([
            [b1, 0.0, b2, 0.0, b3, 0.0],
            [0.0, c1, 0.0, c2, 0.0, c3],
            [c1, b1, c2, b2, c3, b3],
        ])

        dofs = np.array([
            2 * conn[0], 2 * conn[0] + 1,
            2 * conn[1], 2 * conn[1] + 1,
            2 * conn[2], 2 * conn[2] + 1,
        ], dtype=int)

        data.append({
            "id": e,
            "conn": conn,
            "coords": coords,
            "A": A,
            "B": B,
            "dofs": dofs,
            "he": np.sqrt(A),
            "centroid": np.mean(coords, axis=0),
        })

    return data


# =============================================================================
# DAÑO ESCALAR SIMPLE EN TRACCION
# =============================================================================

def principal_strains_from_vector(eps):
    ex, ey, gxy = eps
    exy = 0.5 * gxy

    mat = np.array([
        [ex, exy],
        [exy, ey]
    ])

    vals = np.linalg.eigvalsh(mat)

    return vals[0], vals[1]


def equivalent_strain_tension(eps):
    e1, e2 = principal_strains_from_vector(eps)

    return np.sqrt(max(e1, 0.0)**2 + max(e2, 0.0)**2)


def damage_from_kappa(kappa, E_loc, ft_loc, Gf_loc, he):
    if not USE_DAMAGE:
        return 0.0

    eps0 = ft_loc / E_loc

    if kappa <= eps0:
        return 0.0

    # Regularización por energía de fractura
    ef = eps0 + 2.0 * Gf_loc / (ft_loc * he)

    if ef <= eps0 * 1.0000001:
        ef = eps0 * 1.0001

    d = ef * (kappa - eps0) / (kappa * (ef - eps0))

    return max(0.0, min(d, damage_max))


def get_element_ras_data(elem):
    """
    Devuelve campos RAS actuales para el elemento.
    En ANIOS_RAS = 0 estos campos son cero / factor 1.
    """
    e = elem["id"]

    if CURRENT_XI is None:
        xi = 0.0
        eps_ras = np.zeros(3)
        fE = 1.0
        fFt = 1.0
        fGf = 1.0
    else:
        xi = float(CURRENT_XI[e])
        eps_ras = CURRENT_EPS_RAS[e]
        fE = float(CURRENT_E_FACTOR[e])
        fFt = float(CURRENT_FT_FACTOR[e])
        fGf = float(CURRENT_GF_FACTOR[e])

    return xi, eps_ras, fE, fFt, fGf


def material_response(Ue, elem, kappa_old):
    B = elem["B"]
    A = elem["A"]
    he = elem["he"]

    xi, eps_ras, fE, fFt, fGf = get_element_ras_data(elem)

    eps_total = B @ Ue
    eps_mec = eps_total - eps_ras

    E_loc = E * fE
    ft_loc = ft * fFt
    Gf_loc = Gf * fGf

    Dloc = fE * Dmat

    kappa_trial = max(kappa_old, equivalent_strain_tension(eps_mec))

    d = damage_from_kappa(kappa_trial, E_loc, ft_loc, Gf_loc, he)

    sigma_eff = Dloc @ eps_mec

    # Rigidez residual mínima para evitar tensiones exactamente nulas.
    fac_damage = max(1.0 - d, min_stiff_factor)
    sigma = fac_damage * sigma_eff

    fint = (B.T @ sigma) * thickness * A

    return sigma, fint, d, kappa_trial, eps_mec


def numerical_local_tangent(Ue, elem, kappa_old, fint_ref):
    Ke = np.zeros((6, 6))

    norm_u = max(np.linalg.norm(Ue), 1.0)
    h = 1e-8 * norm_u + 1e-9

    for j in range(6):
        du = np.zeros(6)
        du[j] = h

        _, fint_p, _, _, _ = material_response(Ue + du, elem, kappa_old)

        Ke[:, j] = (fint_p - fint_ref) / h

    Ke += 1e-8 * np.eye(6)

    return Ke


def material_response_from_mechanical_strain(eps_mec, elem, kappa_old):
    xi, eps_ras, fE, fFt, fGf = get_element_ras_data(elem)

    E_loc = E * fE
    ft_loc = ft * fFt
    Gf_loc = Gf * fGf

    Dloc = fE * Dmat

    kappa_trial = max(kappa_old, equivalent_strain_tension(eps_mec))
    d = damage_from_kappa(kappa_trial, E_loc, ft_loc, Gf_loc, elem["he"])

    sigma_eff = Dloc @ eps_mec
    fac_damage = max(1.0 - d, min_stiff_factor)
    sigma = fac_damage * sigma_eff

    return sigma, d, kappa_trial


def strain_numerical_tangent(eps_mec, elem, kappa_old, sigma_ref):
    """
    Tangente numérica local 3x3:
        C_ij = d sigma_i / d eps_mec_j
    """
    Ct = np.zeros((3, 3))

    norm_eps = max(np.linalg.norm(eps_mec), 1.0e-8)
    h = max(1.0e-7 * norm_eps, 1.0e-10)

    for j in range(3):
        eps_p = eps_mec.copy()
        eps_p[j] += h

        sigma_p, _, _ = material_response_from_mechanical_strain(eps_p, elem, kappa_old)
        Ct[:, j] = (sigma_p - sigma_ref) / h

    return Ct


def local_tangent(Ue, elem, kappa_old):
    sigma, fint, d, kappa_new, eps_mec = material_response(Ue, elem, kappa_old)

    B = elem["B"]
    A = elem["A"]

    _, _, fE, _, _ = get_element_ras_data(elem)
    Dloc = fE * Dmat

    if TANGENT_MODE == "elastic":
        Ke = (B.T @ Dloc @ B) * thickness * A

    elif TANGENT_MODE == "secant":
        fac = max(1.0 - d, min_stiff_factor)
        Ke = (B.T @ (fac * Dloc) @ B) * thickness * A

    elif TANGENT_MODE == "numerical":
        Ke = numerical_local_tangent(Ue, elem, kappa_old, fint)

    elif TANGENT_MODE == "numerical_hybrid":
        if d < 1e-10:
            Ke = (B.T @ Dloc @ B) * thickness * A
        elif d < 0.10:
            fac = max(1.0 - d, min_stiff_factor)
            Ke = (B.T @ (fac * Dloc) @ B) * thickness * A
        else:
            Ke = numerical_local_tangent(Ue, elem, kappa_old, fint)

    elif TANGENT_MODE == "strain_numerical":
        Ct = strain_numerical_tangent(eps_mec, elem, kappa_old, sigma)
        Ke = (B.T @ Ct @ B) * thickness * A

    elif TANGENT_MODE == "strain_numerical_hybrid":
        if d < 1e-10:
            Ke = (B.T @ Dloc @ B) * thickness * A
        elif d < 0.10:
            fac = max(1.0 - d, min_stiff_factor)
            Ke = (B.T @ (fac * Dloc) @ B) * thickness * A
        else:
            Ct = strain_numerical_tangent(eps_mec, elem, kappa_old, sigma)
            Ke = (B.T @ Ct @ B) * thickness * A

    else:
        raise ValueError(f"TANGENT_MODE no reconocido: {TANGENT_MODE}")

    return Ke, fint, d, kappa_new, sigma, eps_mec


# =============================================================================
# CARGAS
# =============================================================================

def element_body_force(elem):
    A = elem["A"]

    fe = np.zeros(6)

    fnode = (thickness * A / 3.0) * np.array([0.0, -gamma_c])

    fe[0:2] = fnode
    fe[2:4] = fnode
    fe[4:6] = fnode

    return fe


def extract_boundary_edges(elements):
    edge_dict = {}

    for e, conn in enumerate(elements):
        for a, b in [(0, 1), (1, 2), (2, 0)]:
            i = conn[a]
            j = conn[b]

            key = tuple(sorted((i, j)))

            edge_dict.setdefault(key, []).append(e)

    return edge_dict


def upstream_edges(nodes, elements, tol=1e-7):
    """
    Borde aguas arriba vertical x=0.
    """
    edge_dict = extract_boundary_edges(elements)

    edges = []

    for (i, j), owners in edge_dict.items():
        if len(owners) == 1:
            xi, yi = nodes[i]
            xj, yj = nodes[j]

            if abs(xi) < tol and abs(xj) < tol:
                edges.append((i, j))

    return sorted(edges, key=lambda ij: min(nodes[ij[0], 1], nodes[ij[1], 1]))


def hydro_edge_force(n1, n2, Hwater):
    """
    Fuerza nodal equivalente de presión hidrostática sobre una arista vertical.

    Para Hwater <= H_DAM:
    - presión triangular hasta la superficie libre.

    Para Hwater > H_DAM:
    - sobre el paramento vertical completo queda presión trapezoidal.
    """
    x1, y1 = n1
    x2, y2 = n2

    if abs(x1) > 1e-7 or abs(x2) > 1e-7:
        return np.zeros(4)

    ylow = min(y1, y2)
    yhigh = max(y1, y2)

    if Hwater <= ylow:
        return np.zeros(4)

    ysub1 = ylow
    ysub2 = min(yhigh, Hwater)

    if ysub2 <= ysub1:
        return np.zeros(4)

    Lsub = ysub2 - ysub1

    fe = np.zeros(4)

    for s, w in [(-1.0 / np.sqrt(3.0), 1.0), (1.0 / np.sqrt(3.0), 1.0)]:
        y = 0.5 * (1.0 - s) * ysub1 + 0.5 * (1.0 + s) * ysub2

        p = gamma_w * max(Hwater - y, 0.0)

        N1 = 0.5 * (1.0 - s)
        N2 = 0.5 * (1.0 + s)

        Nmat = np.array([
            [N1, 0.0, N2, 0.0],
            [0.0, N1, 0.0, N2],
        ])

        # Presión hacia +x
        t = np.array([p, 0.0])

        fe += (Nmat.T @ t) * thickness * (Lsub / 2.0) * w

    return fe


def assemble_external_force(nodes, elements, elem_data, up_edges, Hwater):
    ndof = 2 * len(nodes)

    F = np.zeros(ndof)

    # peso propio
    for elem in elem_data:
        fe = element_body_force(elem)
        F[elem["dofs"]] += fe

    # empuje hidrostático
    for i, j in up_edges:
        fe = hydro_edge_force(nodes[i], nodes[j], Hwater)

        dofs = np.array([
            2 * i, 2 * i + 1,
            2 * j, 2 * j + 1
        ], dtype=int)

        F[dofs] += fe

    return F


# =============================================================================
# ENSAMBLE GLOBAL
# =============================================================================

def assemble_global(elem_data, U, state_old):
    ndof = len(U)

    rows = []
    cols = []
    vals = []

    Fint = np.zeros(ndof)

    n_elem = len(elem_data)

    state_new = np.copy(state_old)

    elem_damage = np.zeros(n_elem)
    elem_sx = np.zeros(n_elem)
    elem_sy = np.zeros(n_elem)

    for e, elem in enumerate(elem_data):
        dofs = elem["dofs"]
        Ue = U[dofs]

        kappa_old = state_old[e]

        Ke, fint, d, kappa_new, sigma, eps = local_tangent(Ue, elem, kappa_old)

        Fint[dofs] += fint

        state_new[e] = kappa_new
        elem_damage[e] = d
        elem_sx[e] = sigma[0]
        elem_sy[e] = sigma[1]

        rr, cc = np.meshgrid(dofs, dofs, indexing="ij")

        rows.extend(rr.ravel())
        cols.extend(cc.ravel())
        vals.extend(Ke.ravel())

    K = coo_matrix((vals, (rows, cols)), shape=(ndof, ndof)).tocsr()

    return K, Fint, state_new, elem_damage, elem_sx, elem_sy


# =============================================================================
# CONDICIONES DE BORDE
# =============================================================================

def fixed_base_dofs(nodes, tol=1e-7):
    dofs = []

    for i, (x, y) in enumerate(nodes):
        if abs(y) < tol:
            dofs.extend([2 * i, 2 * i + 1])

    return np.array(sorted(set(dofs)), dtype=int)


def free_dofs(n_nodes, fixed):
    all_dofs = np.arange(2 * n_nodes, dtype=int)

    return np.setdiff1d(all_dofs, fixed)



# =============================================================================
# ETAPA RAS: NIVEL ANUAL, TEMPERATURA SIMPLIFICADA Y PROGRESO
# =============================================================================

def nivel_agua_anual(t_days):
    """
    Nivel de agua anual usado durante la etapa de servicio.
    Repite cada año la curva de la figura 6.37:
    máximo cerca de invierno y mínimo cerca de verano.
    """
    H_mean = 0.5 * (H_SERVICE_MAX + H_SERVICE_MIN)
    H_amp = 0.5 * (H_SERVICE_MAX - H_SERVICE_MIN)

    t_year = t_days % 365.0

    return H_mean + H_amp * np.cos(2.0 * np.pi * t_year / 365.0)


def temperatura_agua_anual(t_days):
    """
    Aproximación de la figura 6.36.
    Agua: 0 °C en invierno, máximo TEMP_WATER_MAX_C hacia mitad del año.
    """
    t_year = t_days % 365.0
    return 0.5 * TEMP_WATER_MAX_C * (1.0 - np.cos(2.0 * np.pi * t_year / 365.0))


def temperatura_aire_anual(t_days):
    """
    Aproximación de la figura 6.36.
    Aire: 0 °C en invierno, máximo TEMP_AIR_MAX_C hacia mitad del año.
    """
    t_year = t_days % 365.0
    return 0.5 * TEMP_AIR_MAX_C * (1.0 - np.cos(2.0 * np.pi * t_year / 365.0))


def distance_to_segment_point(p, a, b):
    ap = p - a
    ab = b - a
    den = np.dot(ab, ab)
    if den <= 1e-30:
        return np.linalg.norm(ap)
    t = np.clip(np.dot(ap, ab) / den, 0.0, 1.0)
    q = a + t * ab
    return np.linalg.norm(p - q)


def exposure_factor_for_ras(point):
    """
    Factor espacial simplificado.
    Busca representar que la RAS progresa primero en el espaldón y zona superior,
    como muestran los mapas del ejemplo de presa.
    """
    p = np.asarray(point, dtype=float)

    # Distancia a paramento aguas arriba, coronación y espaldón inclinado.
    d_up = abs(p[0] - 0.0)
    d_top = max(H_DAM - p[1], 0.0)

    p2 = polygon[1]
    p3 = polygon[2]
    p4 = polygon[3]

    d_down1 = distance_to_segment_point(p, p2, p3)
    d_down2 = distance_to_segment_point(p, p3, p4)
    d_down = min(d_down1, d_down2)

    # Influencias con longitudes características.
    f_top = np.exp(-d_top / (22.0 * MM))
    f_down = np.exp(-d_down / (15.0 * MM))
    f_up = np.exp(-d_up / (10.0 * MM))

    # El espaldón y la zona superior tienen mayor peso.
    f = 0.55 * f_down + 0.35 * f_top + 0.10 * f_up

    return float(np.clip(f, 0.0, 1.0))


def approximate_element_temperature(elem, t_days, Hwater):
    """
    Campo térmico simplificado para la etapa química.
    No resuelve la PDE térmica, pero usa:
    - temperatura anual de agua/aire;
    - base a 6 °C;
    - mayor influencia ambiental en bordes y zona delgada.
    """
    c = elem["centroid"]
    y = c[1]

    T_water = temperatura_agua_anual(t_days)
    T_air = temperatura_aire_anual(t_days)

    exposure = exposure_factor_for_ras(c)

    if y <= Hwater:
        T_boundary = T_water
    else:
        T_boundary = T_air

    # Interior masivo tiende hacia TEMP_BASE_C.
    T = TEMP_BASE_C + exposure * (T_boundary - TEMP_BASE_C)

    return float(T)


def ras_rate_temperature_factor(T_c):
    """
    Factor térmico equivalente simplificado.

    La figura 6.40 muestra que:
    - a 20 °C la RAS arranca temprano;
    - cerca de 6 °C arranca muy tarde;
    - cerca de 4.8 °C es todavía más lenta.

    Por eso se usa una función tipo Arrhenius/Q10 suavizada,
    deliberadamente lenta para temperaturas bajas.
    """
    q10 = 3.0
    fac = q10 ** ((T_c - 20.0) / 10.0)

    # Para evitar que toda la presa reaccione demasiado pronto,
    # se limita fuertemente la reacción a bajas temperaturas.
    if T_c < 6.0:
        fac *= 0.35
    elif T_c < 8.0:
        fac *= 0.55

    return float(np.clip(fac, 0.002, 1.10))


def ras_larive_xi(t_equiv_days):
    """
    Ley tipo Larive/Comi para el progreso xi.
    Usa tau_l y tau_c del cuadro de parámetros de la presa.
    """
    if t_equiv_days <= 0.0:
        return 0.0

    num = 1.0 - np.exp(-t_equiv_days / RAS_TAU_C_DAYS)
    den = 1.0 + np.exp(-(t_equiv_days - RAS_TAU_L_DAYS) / RAS_TAU_C_DAYS)

    xi = num / den

    return float(np.clip(xi, 0.0, 1.0))


def ras_uniform_xi(t_days):
    """
    Progreso RAS uniforme para toda la presa.

    No intenta resolver la difusión térmica del ejemplo original.
    Es una primera aproximación controlada:
    - xi = 0 al inicio
    - xi = RAS_UNIFORM_XI_TARGET_16Y al final de ANIOS_RAS años
    - crecimiento suave, sin salto inicial.
    """
    total_days = max(float(ANIOS_RAS) * 365.0, 1.0)
    s = np.clip(t_days / total_days, 0.0, 1.0)

    a = max(RAS_UNIFORM_RATE, 1.0e-6)
    xi = RAS_UNIFORM_XI_TARGET_16Y * (1.0 - np.exp(-a * s)) / (1.0 - np.exp(-a))

    return float(np.clip(xi, 0.0, RAS_UNIFORM_XI_TARGET_16Y))


def update_ras_fields(elem_data, xi_old, teq_old, t_days, dt_days, Hwater):
    """
    Actualiza campos RAS usando un único valor xi para toda la presa.

    Versión de diagnóstico:
    - RAS constante espacialmente.
    - degradación mecánica uniforme.
    - expansión RAS desactivada por defecto para evitar que una precompresión
      artificial aumente la capacidad de overtopping.
    """
    n = len(elem_data)

    xi_val = ras_uniform_xi(t_days)

    xi_new = np.full(n, xi_val, dtype=float)
    teq_new = teq_old + dt_days

    eps_ras = np.zeros((n, 3))
    fE = np.ones(n)
    fFt = np.ones(n)
    fGf = np.ones(n)
    temp_elem = np.zeros(n)

    # Se conserva una temperatura informativa para la tabla,
    # pero ya no controla xi porque xi es uniforme.
    for e, elem in enumerate(elem_data):
        temp_elem[e] = approximate_element_temperature(elem, t_days, Hwater)

    if RAS_USE_EXPANSION_STRAIN:
        eps_linear_inf = RAS_EXPANSION_SCALE * RAS_EPS_INF / RAS_LINEAR_DIVISOR
        eps = eps_linear_inf * xi_val
    else:
        eps = 0.0

    eps_ras[:, 0] = eps
    eps_ras[:, 1] = eps
    eps_ras[:, 2] = 0.0

    fE_val = max(1.0 - RAS_BETA_E * xi_val, RAS_E_MIN_FACTOR)
    fFt_val = max(1.0 - RAS_BETA_FT * xi_val, RAS_FT_MIN_FACTOR)
    fGf_val = max(1.0 - RAS_BETA_GF * xi_val, RAS_GF_MIN_FACTOR)

    fE[:] = fE_val
    fFt[:] = fFt_val
    fGf[:] = fGf_val

    return xi_new, teq_new, eps_ras, fE, fFt, fGf, temp_elem

def set_current_ras_fields(xi, eps_ras, fE, fFt, fGf):
    global CURRENT_XI, CURRENT_EPS_RAS, CURRENT_E_FACTOR, CURRENT_FT_FACTOR, CURRENT_GF_FACTOR

    CURRENT_XI = xi
    CURRENT_EPS_RAS = eps_ras
    CURRENT_E_FACTOR = fE
    CURRENT_FT_FACTOR = fFt
    CURRENT_GF_FACTOR = fGf


def reset_current_ras_fields(n_elem):
    xi = np.zeros(n_elem)
    eps_ras = np.zeros((n_elem, 3))
    fE = np.ones(n_elem)
    fFt = np.ones(n_elem)
    fGf = np.ones(n_elem)

    set_current_ras_fields(xi, eps_ras, fE, fFt, fGf)

    return xi, eps_ras, fE, fFt, fGf


def run_ras_service_stage(U, state, elem_data, free, nodes, elements, up_edges, fixed, node_p5):
    """
    Simulación previa de servicio con nivel de agua variable y RAS.

    El cálculo avanza cada RAS_DT_DAYS durante ANIOS_RAS años.
    Con RAS_DT_DAYS = 10:
        16 años -> 584 pasos
    El nivel de agua repite el ciclo anual:
        H = 92 m al inicio/final del año
        H = 37 m aproximadamente a mitad del año
    """
    global SERVICE_TIME_DAYS_HIST, SERVICE_TIME_YEARS_HIST
    global SERVICE_UX_P5_HIST, SERVICE_H_WATER_HIST
    global SERVICE_XI_MAX_HIST, SERVICE_DMAX_HIST

    SERVICE_TIME_DAYS_HIST = []
    SERVICE_TIME_YEARS_HIST = []
    SERVICE_UX_P5_HIST = []
    SERVICE_H_WATER_HIST = []
    SERVICE_XI_MAX_HIST = []
    SERVICE_DMAX_HIST = []

    n_elem = len(elem_data)
    xi = np.zeros(n_elem)
    teq = np.zeros(n_elem)
    eps_ras = np.zeros((n_elem, 3))
    fE = np.ones(n_elem)
    fFt = np.ones(n_elem)
    fGf = np.ones(n_elem)

    snapshots = {}

    set_current_ras_fields(xi, eps_ras, fE, fFt, fGf)

    service_years = ANIOS_RAS if ANIOS_RAS > 0 else RAS_SERVICE_YEARS
    total_days = service_years * 365.0
    dt_days = RAS_DT_DAYS
    n_steps = int(round(total_days / dt_days))

    # Ajuste para que el último paso caiga exactamente en 16 años.
    # Con dt=10 días ya coincide: 16*365/10 = 584.
    dt_days = total_days / n_steps

    print("\nETAPA DE SERVICIO CON RAS")
    print("--------------------------------------------------------------------------------------------------------------")
    print(f"Duración                  = {service_years:.2f} años")
    print(f"Paso temporal             = {dt_days:.3f} días")
    print(f"Número de pasos           = {n_steps}")
    print(f"Nivel anual               = {H_SERVICE_MIN/MM:.2f} m a {H_SERVICE_MAX/MM:.2f} m")
    print("--------------------------------------------------------------------------------------------------------------")
    print(f"{'paso':>6s} {'día':>9s} {'año':>8s} {'H [m]':>12s} {'Tmed [C]':>12s} {'xi_max':>10s} {'xi_med':>10s} {'dmax':>10s} {'ux P5 [mm]':>14s} {'conv':>8s}")
    print("--------------------------------------------------------------------------------------------------------------")

    last_print_day = -1.0e30
    sol = None

    for m in range(1, n_steps + 1):
        t_days = m * dt_days
        Hwater = nivel_agua_anual(t_days)

        xi, teq, eps_ras, fE, fFt, fGf, temp_elem = update_ras_fields(
            elem_data, xi, teq, t_days, dt_days, Hwater
        )

        set_current_ras_fields(xi, eps_ras, fE, fFt, fGf)

        sol = solve_one_step(
            Hwater,
            U,
            state,
            elem_data,
            free,
            nodes,
            elements,
            up_edges
        )

        if sol["converged"]:
            U = sol["U"]
            state = sol["state"]
            dmax = float(np.max(sol["elem_damage"]))
            ux = float(U[2 * node_p5])
            conv = True
        else:
            dmax = float(np.max(sol["elem_damage"]))
            ux = float(sol["U"][2 * node_p5])
            conv = False

        year = t_days / 365.0

        # Guarda historia temporal del punto monitoreado en la coronación
        # para revisar coherencia del desplazamiento horizontal durante los 16 años.
        SERVICE_TIME_DAYS_HIST.append(float(t_days))
        SERVICE_TIME_YEARS_HIST.append(float(year))
        SERVICE_UX_P5_HIST.append(float(ux))
        SERVICE_H_WATER_HIST.append(float(Hwater))
        SERVICE_XI_MAX_HIST.append(float(np.max(xi)))
        SERVICE_DMAX_HIST.append(float(dmax))

        should_print = (
            (t_days - last_print_day >= RAS_PRINT_EVERY_DAYS - 1e-9)
            or (m == 1)
            or (m == n_steps)
            or (not conv)
        )

        if should_print:
            print(
                f"{m:6d} {t_days:9.2f} {year:8.3f} "
                f"{Hwater/MM:12.4f} {np.mean(temp_elem):12.4f} "
                f"{np.max(xi):10.5f} {np.mean(xi):10.5f} "
                f"{dmax:10.5f} {ux:14.6f} {str(conv):>8s}"
            )
            last_print_day = t_days

        # Guarda mapas cada 2 años, o según parámetro.
        save_year = RAS_SAVE_SNAPSHOTS_EVERY_YEARS
        if save_year > 0:
            nearest = round(year / save_year) * save_year
            if abs(year - nearest) <= 0.5 * dt_days / 365.0:
                snapshots_year = int(round(nearest))
                if snapshots_year > 0:
                    if sol is not None:
                        snapshots[f"anio_{snapshots_year:02d}"] = {
                            "year": float(year),
                            "H_m": float(Hwater / MM),
                            "xi": xi.copy(),
                            "damage": sol["elem_damage"].copy(),
                            "eps_ras_vol": 2.0 * eps_ras[:, 0].copy(),
                            "U": U.copy(),
                        }

        # Guarda deformadas en años puntuales de un ciclo representativo.
        for target_year in SERVICE_SNAPSHOT_YEARS:
            key = f"ciclo_anio_{target_year:05.2f}"
            if key not in snapshots and abs(year - target_year) <= 0.5 * dt_days / 365.0:
                if sol is not None:
                    snapshots[key] = {
                        "year": float(year),
                        "H_m": float(Hwater / MM),
                        "xi": xi.copy(),
                        "damage": sol["elem_damage"].copy(),
                        "eps_ras_vol": 2.0 * eps_ras[:, 0].copy(),
                        "U": U.copy(),
                    }

        if not conv:
            print("La etapa RAS no convergió. Se continúa con el último estado aceptado.")
            break

    # Garantiza que el ciclo de servicio termine con el nivel alto.
    H_end_service = nivel_agua_anual(total_days)

    print("\nFIN ETAPA DE SERVICIO")
    print("--------------------------------------------------------------")
    print(f"t final [días]           = {total_days:.2f}")
    print(f"H final servicio [m]     = {H_end_service/MM:.5f}")
    print(f"xi max final             = {np.max(xi):.6f}")
    print(f"xi medio final           = {np.mean(xi):.6f}")

    # Al terminar 16 años, se deja el agua en H_start = 92 m para comenzar overtopping.
    H_end = H_start

    sol = solve_one_step(
        H_end,
        U,
        state,
        elem_data,
        free,
        nodes,
        elements,
        up_edges
    )

    if sol["converged"]:
        U = sol["U"]
        state = sol["state"]

    return U, state, xi, eps_ras, fE, fFt, fGf, snapshots


# =============================================================================
# SOLVER DE UN PASO
# =============================================================================

def solve_one_step(Hwater, U0, state0, elem_data, free, nodes, elements, up_edges):
    Fext = assemble_external_force(nodes, elements, elem_data, up_edges, Hwater)

    U_iter = U0.copy()

    normR0 = None

    last_info = None

    for it in range(1, MAX_ITER + 1):
        K, Fint, state_trial, elem_damage, elem_sx, elem_sy = assemble_global(
            elem_data, U_iter, state0
        )

        R = Fext - Fint
        Rf = R[free]

        normR = np.linalg.norm(Rf)

        if normR0 is None:
            normR0 = max(normR, 1.0)

        relR = normR / normR0

        last_info = {
            "U": U_iter.copy(),
            "state": state_trial.copy(),
            "elem_damage": elem_damage.copy(),
            "elem_sx": elem_sx.copy(),
            "elem_sy": elem_sy.copy(),
            "iter": it,
            "normR": normR,
            "relR": relR,
            "converged": False,
            "solver_error": "",
        }

        if normR < TOL_ABS or relR < TOL_REL:
            last_info["converged"] = True
            return last_info

        Kff = K[free][:, free]

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", MatrixRankWarning)
                dU = spsolve(Kff, Rf)

        except Exception as exc:
            last_info["solver_error"] = str(exc)
            return last_info

        if np.any(~np.isfinite(dU)):
            last_info["solver_error"] = "Incremento no finito."
            return last_info

        if USE_LINE_SEARCH:
            # line search simple. Más robusto, pero más costoso porque reensambla.
            alpha = 1.0
            accepted = False

            while alpha >= LINE_SEARCH_MIN:
                U_cand = U_iter.copy()
                U_cand[free] += alpha * dU

                _, Fint_cand, _, _, _, _ = assemble_global(elem_data, U_cand, state0)

                Rcand = Fext - Fint_cand
                norm_cand = np.linalg.norm(Rcand[free])

                if np.isfinite(norm_cand) and norm_cand <= normR:
                    U_iter = U_cand
                    accepted = True
                    break

                alpha *= LINE_SEARCH_REDUCTION

            if not accepted:
                U_iter[free] += LINE_SEARCH_MIN * dU
        else:
            # modo rápido
            U_iter[free] += dU

    return last_info



def compute_base_horizontal_reaction(nodes, elements, elem_data, up_edges, U, state, fixed, Hwater):
    """
    Calcula la reacción horizontal total en la base.

    Convención:
    - Fext contiene peso propio + presión hidrostática.
    - Fint contiene fuerzas internas.
    - En los GL restringidos, la reacción de apoyo se toma como:
          Rbase = Fint - Fext
    - Se suma la componente horizontal de todos los nodos de la base.
    """
    _, Fint, _, _, _, _ = assemble_global(elem_data, U, state)
    Fext = assemble_external_force(nodes, elements, elem_data, up_edges, Hwater)

    R = Fint - Fext

    fixed_x = [d for d in fixed if d % 2 == 0]
    Rx_total = float(np.sum(R[fixed_x]))

    return Rx_total


# =============================================================================
# GRAFICOS
# =============================================================================

def make_poly_collection(nodes, elements, values=None, cmap="viridis"):
    polys = [nodes[conn] / MM for conn in elements]

    if values is None:
        pc = PolyCollection(
            polys,
            facecolors="none",
            edgecolors="0.55",
            linewidths=0.25
        )
    else:
        pc = PolyCollection(
            polys,
            array=np.array(values),
            cmap=cmap,
            edgecolors="k",
            linewidths=0.12
        )

    return pc


def plot_all_results(nodes, elements, U, fixed, up_edges, node_p5,
                     ux_hist, Hratio_hist, H_hist, Rx_hist,
                     last_damage, last_sx, last_sy):
    fig, axs = plt.subplots(2, 4, figsize=(20, 9))

    axs = axs.ravel()

    # ---------------------------------------------------------
    # curva 1: altura de agua vs desplazamiento
    # ---------------------------------------------------------
    ax = axs[0]

    ux_plot = np.array(ux_hist)
    hr_plot = np.array(Hratio_hist)
    H_plot = np.array(H_hist)
    Rx_plot = np.array(Rx_hist)

    if PLOT_ONLY_OVERTOPPING:
        mask = H_plot >= H_start - 1e-9
        ux_plot = ux_plot[mask]
        hr_plot = hr_plot[mask]
        Rx_plot = Rx_plot[mask]

    ax.plot(ux_plot, hr_plot, marker="o", linewidth=1.5)
    ax.set_xlabel("Desplazamiento horizontal P5 [mm]")
    ax.set_ylabel("H agua / 103 m")

    if PLOT_ONLY_OVERTOPPING:
        ax.set_title("Altura relativa vs desplazamiento")
    else:
        ax.set_title("Curva completa H/103 vs ux(P5)")

    ax.grid(True)

    # ---------------------------------------------------------
    # curva 2: reacción horizontal de base vs desplazamiento
    # ---------------------------------------------------------
    ax = axs[1]

    ax.plot(ux_plot, np.abs(Rx_plot) / 1000.0, marker="o", linewidth=1.5)
    ax.set_xlabel("Desplazamiento horizontal P5 [mm]")
    ax.set_ylabel("Reacción horizontal total de base |Rx| [kN]")
    ax.set_title("Carga horizontal de base vs desplazamiento")
    ax.grid(True)

    # ---------------------------------------------------------
    # daño
    # ---------------------------------------------------------
    ax = axs[2]

    pc = make_poly_collection(nodes, elements, last_damage, cmap="inferno")
    ax.add_collection(pc)
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.set_title("Daño final")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    fig.colorbar(pc, ax=ax, shrink=0.8)

    # ---------------------------------------------------------
    # sigma x
    # ---------------------------------------------------------
    ax = axs[3]

    pc = make_poly_collection(nodes, elements, last_sx, cmap="coolwarm")
    ax.add_collection(pc)
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.set_title(r"Tensión horizontal $\sigma_x$ [MPa]")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    fig.colorbar(pc, ax=ax, shrink=0.8)

    # ---------------------------------------------------------
    # sigma y
    # ---------------------------------------------------------
    ax = axs[4]

    pc = make_poly_collection(nodes, elements, last_sy, cmap="coolwarm")
    ax.add_collection(pc)
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.set_title(r"Tensión vertical $\sigma_y$ [MPa]")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    fig.colorbar(pc, ax=ax, shrink=0.8)

    # ---------------------------------------------------------
    # deformada
    # ---------------------------------------------------------
    ax = axs[5]

    pc0 = make_poly_collection(nodes, elements, None)
    ax.add_collection(pc0)

    U_nodes = U.reshape((-1, 2))

    maxu = np.max(np.sqrt(U_nodes[:, 0]**2 + U_nodes[:, 1]**2))

    if maxu > 0.0:
        scale = DEFORMED_REL_SCALE * H_DAM / maxu
    else:
        scale = 1.0

    def_nodes = nodes + scale * U_nodes

    polys_def = [def_nodes[conn] / MM for conn in elements]

    pc1 = PolyCollection(
        polys_def,
        facecolors="none",
        edgecolors="blue",
        linewidths=0.25
    )

    ax.add_collection(pc1)
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.set_title(f"Deformada final. Escala = {scale:.1f}")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")

    # ---------------------------------------------------------
    # modelo
    # ---------------------------------------------------------
    ax = axs[6]

    pc = make_poly_collection(nodes, elements, None)
    ax.add_collection(pc)

    fixed_nodes = sorted(set([d // 2 for d in fixed]))

    pf = nodes[fixed_nodes] / MM

    ax.plot(
        pf[:, 0],
        pf[:, 1],
        "^",
        markersize=3,
        label="Base empotrada"
    )

    segs = [[nodes[i] / MM, nodes[j] / MM] for i, j in up_edges]

    lc = LineCollection(
        segs,
        colors="red",
        linewidths=1.5,
        label="Paramento aguas arriba"
    )

    ax.add_collection(lc)

    p5 = nodes[node_p5] / MM
    ax.plot(p5[0], p5[1], "bo", label="P5 control")

    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.set_title("Malla, apoyos y borde hidráulico")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.legend(loc="best")

    axs[7].axis("off")

    plt.tight_layout()
    plt.show()



def print_results_table(H_hist, Hratio_hist, ux_hist, dmax_hist, Rx_hist):
    """
    Imprime una tabla resumida al final con la reacción horizontal de base.
    Para no llenar demasiado la terminal, imprime los últimos N pasos.
    """
    n = len(H_hist)
    if n == 0:
        return

    start = max(0, n - PRINT_LAST_N_TABLE)

    print("\nTABLA RESUMEN DE RESULTADOS")
    print("----------------------------------------------------------------------------------------------------")
    print(f"{'paso':>6s} {'H [m]':>12s} {'H/103':>12s} {'ux P5 [mm]':>14s} {'Rx base [kN]':>16s} {'|Rx| [kN]':>14s} {'dmax':>10s}")
    print("----------------------------------------------------------------------------------------------------")

    for i in range(start, n):
        print(
            f"{i+1:6d} "
            f"{H_hist[i]/MM:12.5f} "
            f"{Hratio_hist[i]:12.6f} "
            f"{ux_hist[i]:14.6f} "
            f"{Rx_hist[i]/1000.0:16.3f} "
            f"{abs(Rx_hist[i])/1000.0:14.3f} "
            f"{dmax_hist[i]:10.5f}"
        )

    if start > 0:
        print(f"... se muestran solo los últimos {PRINT_LAST_N_TABLE} pasos de {n}.")
        print("Para ver más, aumentá PRINT_LAST_N_TABLE en el bloque PARAM.")


# =============================================================================
# GUARDADO OPCIONAL
# =============================================================================

def save_results_table(H_hist, Hratio_hist, ux_hist, dmax_hist, Rx_hist):
    arr = np.column_stack([
        np.arange(1, len(H_hist) + 1),
        np.array(H_hist) / MM,
        np.array(Hratio_hist),
        np.array(ux_hist),
        np.array(dmax_hist),
        np.array(Rx_hist) / 1000.0,
    ])

    header = "paso,H_m,H_sobre_103,uxP5_mm,dmax,Rx_base_kN"

    np.savetxt(
        RESULT_PREFIX + "_tabla.csv",
        arr,
        delimiter=",",
        header=header,
        comments=""
    )



def should_print_step(step_id, attempt, converged):
    if not converged:
        return True
    if step_id <= PRINT_ALL_UNTIL_STEP:
        return True
    if PRINT_EVERY <= 1:
        return True
    return (step_id % PRINT_EVERY) == 0


def plot_ras_service_history():
    """
    Gráfico del desplazamiento horizontal del punto P5 durante la etapa de servicio con RAS.
    Se muestra al final para revisar si la evolución temporal es coherente.
    """
    if len(globals().get('SERVICE_TIME_DAYS_HIST', [])) == 0:
        return

    t_years = np.array(SERVICE_TIME_YEARS_HIST, dtype=float)
    ux = np.array(SERVICE_UX_P5_HIST, dtype=float)
    Hm = np.array(SERVICE_H_WATER_HIST, dtype=float) / MM
    xi = np.array(SERVICE_XI_MAX_HIST, dtype=float)
    dmax = np.array(SERVICE_DMAX_HIST, dtype=float)

    fig, axs = plt.subplots(2, 2, figsize=(13, 8))
    axs = axs.ravel()

    axs[0].plot(t_years, ux, lw=1.8)
    axs[0].set_xlabel("Tiempo [años]")
    axs[0].set_ylabel("ux(P5) [mm]")
    axs[0].set_title("Desplazamiento horizontal de P5 durante la etapa RAS")
    axs[0].grid(True)

    axs[1].plot(t_years, Hm, lw=1.5)
    axs[1].set_xlabel("Tiempo [años]")
    axs[1].set_ylabel("Nivel de agua H [m]")
    axs[1].set_title("Nivel de agua durante la etapa RAS")
    axs[1].grid(True)

    axs[2].plot(t_years, xi, lw=1.5)
    axs[2].set_xlabel("Tiempo [años]")
    axs[2].set_ylabel("xi max [-]")
    axs[2].set_title("Avance máximo de RAS")
    axs[2].grid(True)

    axs[3].plot(t_years, dmax, lw=1.5)
    axs[3].set_xlabel("Tiempo [años]")
    axs[3].set_ylabel("dmax [-]")
    axs[3].set_title("Daño máximo durante la etapa de servicio")
    axs[3].grid(True)

    plt.tight_layout()



# =============================================================================
# MAIN
# =============================================================================

def main():
    global ANIOS_RAS, SHOW_WINDOWS_AT_END, SAVE_RESULTS, OUTPUT_ROOT, RESULT_PREFIX

    parser = argparse.ArgumentParser(description="Presa de gravedad con RAS + overtopping y guardado de resultados.")
    parser.add_argument("--anios", type=int, default=ANIOS_RAS, help="Años de RAS: 0 para presa sana, 16 para caso envejecido.")
    parser.add_argument("--outroot", type=str, default=OUTPUT_ROOT, help="Carpeta raíz de salida.")
    parser.add_argument("--show", action="store_true", help="Muestra ventanas al final además de guardar figuras.")
    args = parser.parse_args()

    ANIOS_RAS = int(args.anios)
    OUTPUT_ROOT = args.outroot
    SHOW_WINDOWS_AT_END = bool(args.show)
    SAVE_RESULTS = True
    RESULT_PREFIX = f"presa_T3_{ANIOS_RAS:02d}anios"
    preparar_directorio_salida()

    print("\n======================================================================")
    print("PRESA DE GRAVEDAD - RAS + OVERTOPPING - T3 CONFORME")
    print("======================================================================")

    nodes, elements = build_conforming_t3_mesh(polygon, mesh_size)

    elem_data = precompute_t3_data(nodes, elements)

    n_nodes = len(nodes)
    n_elem = len(elements)
    ndof = 2 * n_nodes

    p5_exact = np.array([0.0, H_DAM])
    node_p5 = find_nearest_node(nodes, p5_exact)

    up_edges = upstream_edges(nodes, elements)

    fixed = fixed_base_dofs(nodes)
    free = free_dofs(n_nodes, fixed)

    print("\nPARAMETROS PRINCIPALES")
    print("--------------------------------------------------------------")
    print(f"ANIOS_RAS               = {ANIOS_RAS}")
    print(f"USE_DAMAGE              = {USE_DAMAGE}")
    print(f"TANGENT_MODE            = {TANGENT_MODE}")
    print(f"USE_LINE_SEARCH         = {USE_LINE_SEARCH}")
    print(f"E                       = {E:.3f} MPa")
    print(f"nu                      = {nu:.4f}")
    print(f"ft                      = {ft:.4f} MPa")
    print(f"Gf                      = {Gf:.5f} N/mm")
    print(f"mesh_size               = {mesh_size / MM:.3f} m")
    print(f"H_start                 = {H_start / MM:.3f} m")
    print(f"RAMP_INITIAL_LEVEL      = {RAMP_INITIAL_LEVEL}")
    if ANIOS_RAS > 0:
        print(f"RAS_SERVICE_YEARS       = {RAS_SERVICE_YEARS}")
        print(f"RAS_DT_DAYS             = {RAS_DT_DAYS}")
        print(f"RAS uniforme            = True")
        print(f"RAS_XI_TARGET_16Y       = {RAS_UNIFORM_XI_TARGET_16Y}")
        print(f"RAS_USE_EXPANSION       = {RAS_USE_EXPANSION_STRAIN}")
        print(f"RAS_LINEAR_DIVISOR      = {RAS_LINEAR_DIVISOR}")
        print(f"RAS_EXPANSION_SCALE     = {RAS_EXPANSION_SCALE}")
        print(f"RAS_BETA_E/FT/GF        = {RAS_BETA_E:.3f} / {RAS_BETA_FT:.3f} / {RAS_BETA_GF:.3f}")
        eps_ras_final_est = RAS_EXPANSION_SCALE * RAS_EPS_INF / RAS_LINEAR_DIVISOR * RAS_UNIFORM_XI_TARGET_16Y
        print(f"eps_RAS final estimada  = {eps_ras_final_est:.6e}")
        print("Comentario               = RAS uniforme xi=0.70, expansión suave y degradación objetivo E/ft/Gf.")
    print(f"LOAD_GRAPH_MODE         = {LOAD_GRAPH_MODE}")
    print(f"H_target                = {H_target / MM:.3f} m")
    print(f"dH_initial              = {dH_initial / MM:.5f} m")
    print(f"dH_min                  = {dH_min / MM:.5f} m")
    print(f"dH_max                  = {dH_max / MM:.5f} m")
    print(f"shrink high iter accept = {SHRINK_ON_HIGH_ITER_ACCEPTED}")
    print(f"grow accepted streak    = {GROW_AFTER_ACCEPTED_STREAK}")

    print("\nGEOMETRIA")
    print("--------------------------------------------------------------")
    for i, p in enumerate(polygon_m, start=1):
        print(f"P{i} = ({p[0]:8.3f}, {p[1]:8.3f}) m")
    print(f"Altura presa H          = {H_DAM / MM:.3f} m")

    print("\nMALLA T3 CONFORME")
    print("--------------------------------------------------------------")
    print(f"Nodos                   = {n_nodes}")
    print(f"Elementos T3            = {n_elem}")
    print(f"GL totales              = {ndof}")

    print("\nNODO DE CONTROL")
    print("--------------------------------------------------------------")
    print(f"P5 teórico              = ({p5_exact[0] / MM:.3f}, {p5_exact[1] / MM:.3f}) m")
    print(f"Nodo más cercano        = {node_p5}")
    print(f"Coord nodo              = ({nodes[node_p5,0] / MM:.3f}, {nodes[node_p5,1] / MM:.3f}) m")

    print("\nCONDICIONES DE BORDE")
    print("--------------------------------------------------------------")
    print(f"Aristas aguas arriba    = {len(up_edges)}")
    print(f"GL fijos base           = {len(fixed)}")
    print(f"GL libres               = {len(free)}")

    print("\nACLARACION SOBRE PASOS DE CARGA")
    print("--------------------------------------------------------------")
    print("El nivel de agua H es el parámetro de carga.")
    print("Cada paso resuelve el equilibrio con la carga TOTAL correspondiente a H.")
    print("Si un nivel no converge, el programa reduce dH y reintenta desde el último estado convergido.")
    print("Si dH llega al mínimo, se detiene y muestra el último estado convergido.")
    print("Nota: por velocidad, no siempre se imprimen todos los pasos aceptados intermedios.")

    U = np.zeros(ndof)
    state = np.zeros(n_elem)

    # Campos RAS iniciales.
    xi_ras, eps_ras, fE_ras, fFt_ras, fGf_ras = reset_current_ras_fields(n_elem)
    ras_snapshots = {}

    ux_hist = []
    Hratio_hist = []
    H_hist = []
    dmax_hist = []
    Rx_hist = []

    # Referencia para graficar el overtopping luego de RAS.
    # Si ANIOS_RAS = 0, queda en cero.
    U_ref_overtopping = np.zeros_like(U)

    last_damage = None
    last_sx = None
    last_sy = None

    accepted = 0
    rejected = 0
    accepted_streak = 0

    print("\nANALISIS INCREMENTAL")
    print("----------------------------------------------------------------------------------------------------------------")
    print(f"{'paso':>5s} {'intento':>8s} {'H [m]':>12s} {'dH [m]':>12s} {'ux P5 [mm]':>14s} {'Rx base [kN]':>14s} {'dmax':>10s} {'iter':>8s} {'||R||':>12s} {'relR':>10s} {'conv':>8s}")
    print("----------------------------------------------------------------------------------------------------------------")

    reason = "Finalización normal."

    try:
        # ---------------------------------------------------------------------
        # FASE 0: servicio con RAS si ANIOS_RAS > 0
        # ---------------------------------------------------------------------
        if ANIOS_RAS > 0:
            U, state, xi_ras, eps_ras, fE_ras, fFt_ras, fGf_ras, ras_snapshots = run_ras_service_stage(
                U, state, elem_data, free, nodes, elements, up_edges, fixed, node_p5
            )

            set_current_ras_fields(xi_ras, eps_ras, fE_ras, fFt_ras, fGf_ras)

            # Estado inicial del overtopping: final de los años de servicio, a H_start.
            H_current = H_start

            if PLOT_OVERTOPPING_INCREMENTAL_FROM_RAS:
                U_ref_overtopping = U.copy()

            K, Fint, state_tmp, last_damage, last_sx, last_sy = assemble_global(
                elem_data, U, state
            )

            # no se actualiza state aquí: ya viene del último equilibrio aceptado.
            ux_total = U[2 * node_p5]
            ux = ux_total - U_ref_overtopping[2 * node_p5]
            dmax = np.max(last_damage)
            Rx_base = compute_base_horizontal_reaction(
                nodes, elements, elem_data, up_edges, U, state, fixed, H_current
            )

            accepted += 1
            ux_hist.append(ux)
            Hratio_hist.append(H_current / H_DAM)
            H_hist.append(H_current)
            dmax_hist.append(dmax)
            Rx_hist.append(Rx_base)

            print("\nESTADO INICIAL DEL OVERTOPPING LUEGO DE RAS")
            print("--------------------------------------------------------------")
            print(f"H inicial [m]             = {H_current / MM:.5f}")
            print(f"xi max                    = {np.max(xi_ras):.6f}")
            print(f"xi medio                  = {np.mean(xi_ras):.6f}")
            print(f"dmax inicial              = {dmax:.6f}")
            print(f"ux P5 total inicial [mm]  = {ux_total:.6f}")
            print(f"ux P5 curva overtop [mm]  = {ux:.6f}")
            print(f"Rx base inicial [kN]      = {Rx_base/1000.0:.6f}")

        else:
            # -----------------------------------------------------------------
            # FASE 1: rampa desde H = 0 hasta H_start
            # -----------------------------------------------------------------
            if RAMP_INITIAL_LEVEL:
                H_current = 0.0
                dH_current = min(H_ramp_initial_step, H_ramp_step_max)
                H_first_target = H_start
            else:
                H_current = 0.0
                dH_current = H_start
                H_first_target = H_start

            while H_current < H_first_target - 1e-12:
                success = False
                attempt = 0

                while not success:
                    attempt += 1

                    H_next = min(H_current + dH_current, H_first_target)

                    sol = solve_one_step(
                        H_next,
                        U,
                        state,
                        elem_data,
                        free,
                        nodes,
                        elements,
                        up_edges
                    )

                    if sol["converged"]:
                        success = True
                        accepted += 1

                        U = sol["U"]
                        state = sol["state"]

                        last_damage = sol["elem_damage"]
                        last_sx = sol["elem_sx"]
                        last_sy = sol["elem_sy"]

                        H_current = H_next

                        ux = U[2 * node_p5]
                        dmax = np.max(last_damage)
                        Rx_base = compute_base_horizontal_reaction(
                            nodes, elements, elem_data, up_edges, U, state, fixed, H_current
                        )

                        ux_hist.append(ux)
                        Hratio_hist.append(H_current / H_DAM)
                        H_hist.append(H_current)
                        dmax_hist.append(dmax)
                        Rx_hist.append(Rx_base)

                        accepted_streak += 1

                        if should_print_step(accepted, attempt, True):
                            print(f"{accepted:5d} {attempt:8d} {H_current/MM:12.5f} {dH_current/MM:12.5f} {ux:14.6f} {Rx_base/1000.0:14.3f} {dmax:10.5f} {sol['iter']:8d} {sol['normR']:12.3e} {sol['relR']:10.2e} {str(True):>8s}")

                        # ajuste del paso durante rampa
                        if sol["iter"] <= ITER_GOOD:
                            dH_current = min(dH_current * STEP_GROWTH, H_ramp_step_max)
                        elif sol["iter"] >= ITER_BAD and SHRINK_ON_HIGH_ITER_ACCEPTED:
                            dH_current = max(dH_current * STEP_REDUCTION, dH_min)

                    else:
                        rejected += 1
                        accepted_streak = 0

                        print(f"{accepted+1:5d} {attempt:8d} {H_next/MM:12.5f} {dH_current/MM:12.5f} {'---':>14s} {'---':>14s} {'---':>10s} {sol['iter']:8d} {sol['normR']:12.3e} {sol['relR']:10.2e} {str(False):>8s}")

                        dH_current *= STEP_REDUCTION

                        if dH_current < dH_min:
                            reason = "No converge durante la rampa inicial y dH llegó al mínimo."
                            raise RuntimeError(reason)

        # ---------------------------------------------------------------------
        # FASE 2: overtopping desde H_start hasta H_target
        # ---------------------------------------------------------------------
        dH_current = dH_initial

        while H_current < H_target - 1e-12:
            success = False
            attempt = 0

            while not success:
                attempt += 1

                H_next = min(H_current + dH_current, H_target)

                sol = solve_one_step(
                    H_next,
                    U,
                    state,
                    elem_data,
                    free,
                    nodes,
                    elements,
                    up_edges
                )

                if sol["converged"]:
                    success = True
                    accepted += 1

                    U = sol["U"]
                    state = sol["state"]

                    last_damage = sol["elem_damage"]
                    last_sx = sol["elem_sx"]
                    last_sy = sol["elem_sy"]

                    H_current = H_next

                    ux = U[2 * node_p5] - U_ref_overtopping[2 * node_p5]
                    dmax = np.max(last_damage)
                    Rx_base = compute_base_horizontal_reaction(
                        nodes, elements, elem_data, up_edges, U, state, fixed, H_current
                    )

                    ux_hist.append(ux)
                    Hratio_hist.append(H_current / H_DAM)
                    H_hist.append(H_current)
                    dmax_hist.append(dmax)
                    Rx_hist.append(Rx_base)

                    accepted_streak += 1

                    if should_print_step(accepted, attempt, True):
                        print(f"{accepted:5d} {attempt:8d} {H_current/MM:12.5f} {dH_current/MM:12.5f} {ux:14.6f} {Rx_base/1000.0:14.3f} {dmax:10.5f} {sol['iter']:8d} {sol['normR']:12.3e} {sol['relR']:10.2e} {str(True):>8s}")

                    if sol["iter"] <= ITER_GOOD:
                        dH_current = min(dH_current * STEP_GROWTH, dH_max)
                    elif sol["iter"] >= ITER_BAD and SHRINK_ON_HIGH_ITER_ACCEPTED:
                        dH_current = max(dH_current * STEP_REDUCTION, dH_min)

                    if GROW_EVEN_WITH_HIGH_ITER and accepted_streak >= GROW_AFTER_ACCEPTED_STREAK:
                        dH_current = min(dH_current * STEP_GROWTH, dH_max)
                        accepted_streak = 0

                else:
                    rejected += 1
                    accepted_streak = 0

                    print(f"{accepted+1:5d} {attempt:8d} {H_next/MM:12.5f} {dH_current/MM:12.5f} {'---':>14s} {'---':>14s} {'---':>10s} {sol['iter']:8d} {sol['normR']:12.3e} {sol['relR']:10.2e} {str(False):>8s}")

                    dH_current *= STEP_REDUCTION

                    if dH_current < dH_min:
                        reason = "No converge y dH llegó al mínimo. Se muestra el último estado convergido."
                        raise RuntimeError(reason)

        reason = "Se alcanzó el nivel objetivo."

    except KeyboardInterrupt:
        reason = "Corrida detenida manualmente con Ctrl+C."

    except RuntimeError as exc:
        reason = str(exc)

    print("\nCONTROL DE PASOS")
    print("--------------------------------------------------------------")
    print(f"Pasos aceptados             = {accepted}")
    print(f"Pasos rechazados            = {rejected}")

    if len(H_hist) > 0:
        print(f"H final aceptada [m]        = {H_hist[-1] / MM:.5f}")
        print(f"H/103 final                 = {Hratio_hist[-1]:.6f}")
        print(f"ux final P5 [mm]            = {ux_hist[-1]:.6f}")
        print(f"dmax final                  = {dmax_hist[-1]:.6f}")
        print(f"Rx base final [kN]          = {Rx_hist[-1] / 1000.0:.6f}")

    if ANIOS_RAS > 0 and CURRENT_XI is not None:
        print(f"xi RAS max final            = {np.max(CURRENT_XI):.6f}")
        print(f"xi RAS medio final          = {np.mean(CURRENT_XI):.6f}")
    print(f"Motivo de parada            = {reason}")
    print("Gráficos finales            = H/103 vs ux(P5) y |Rx base| vs ux(P5), además de mapas.")

    if PRINT_TABLE_AT_END and len(H_hist) > 0:
        print_results_table(H_hist, Hratio_hist, ux_hist, dmax_hist, Rx_hist)

    if SAVE_RESULTS and len(H_hist) > 0:
        guardar_resultados_completos(
            nodes=nodes,
            elements=elements,
            fixed=fixed,
            up_edges=up_edges,
            node_p5=node_p5,
            U=U,
            U_ref_overtopping=U_ref_overtopping,
            last_damage=last_damage,
            last_sx=last_sx,
            last_sy=last_sy,
            ux_hist=np.array(ux_hist),
            Hratio_hist=np.array(Hratio_hist),
            H_hist=np.array(H_hist),
            dmax_hist=np.array(dmax_hist),
            Rx_hist=np.array(Rx_hist),
            accepted=accepted,
            rejected=rejected,
            reason=reason,
            ras_snapshots=ras_snapshots,
        )

    if SHOW_WINDOWS_AT_END and len(H_hist) > 0 and last_damage is not None:
        plot_all_results(
            nodes=nodes,
            elements=elements,
            U=(U - U_ref_overtopping) if (ANIOS_RAS > 0 and PLOT_OVERTOPPING_INCREMENTAL_FROM_RAS) else U,
            fixed=fixed,
            up_edges=up_edges,
            node_p5=node_p5,
            ux_hist=np.array(ux_hist),
            Hratio_hist=np.array(Hratio_hist),
            H_hist=np.array(H_hist),
            Rx_hist=np.array(Rx_hist),
            last_damage=last_damage,
            last_sx=last_sx,
            last_sy=last_sy,
        )

    elif len(H_hist) == 0:
        print("No hay estado convergido para graficar.")


if __name__ == "__main__":
    main()
