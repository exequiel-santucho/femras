# PRD — femras: Herramienta FEM 2D para Hormigón con RAS/ASR

**Repositorio:** https://github.com/exequiel-santucho/femras  
**Licencia:** MIT  
**Versión del documento:** 2026-06-12  
**Estado:** Desarrollo activo

---

## 1. Descripción general

**femras** es una herramienta de elementos finitos 2D, libre y de código abierto, para el análisis de estructuras de hormigón afectadas por la **Reacción Álcali-Sílice (RAS/ASR)**. Combina un modelo de daño escalar de tracción regularizado por energía de fractura con la expansión impuesta y la degradación de propiedades mecánicas producida por la RAS.

### Audiencia objetivo

Ingenieros civiles e investigadores que necesiten:
- Evaluar el comportamiento de estructuras de hormigón con RAS (presas, vigas, muros).
- Reproducir o extender los resultados de scripts de análisis existentes.
- Integrar el modelo en flujos de trabajo de investigación o inspección estructural.

### Principios de diseño

- **Código abierto y reproducible**: todo el pipeline (datos → malla → análisis → resultados) es trazable y auditable.
- **Bilingual ES/EN**: documentación, mensajes de la app web y CLI en español e inglés.
- **Dos interfaces equivalentes**: CLI (ficha YAML) y app web local (canvas + JSON). Dibujar en el canvas o editar el YAML produce el mismo análisis.
- **Sin instalación de servidor**: la app web corre localmente (`uvicorn`), sin dependencias de nube.
- **Validada contra legado**: toda refactorización debe reproducir las dos referencias históricas (`viga_rilem.py`, `presa_ras.py`) a precisión numérica.

---

## 2. Modelo físico-matemático

### 2.1 Cinemática y tensiones

El modelo resuelve en 2D (estado plano) el sistema acoplado:

$$\boldsymbol{\varepsilon}_\text{mec} = \boldsymbol{\varepsilon}_\text{total} - \boldsymbol{\varepsilon}_\text{RAS}$$

$$\boldsymbol{\sigma} = (1-d)\,\mathbf{C}(E_\text{eff},\nu)\,\boldsymbol{\varepsilon}_\text{mec}$$

donde:
- $\boldsymbol{\varepsilon}_\text{RAS} = \xi\,\varepsilon_\text{RAS}^\infty\,[1,\,1,\,0]^\top$ — expansión isótropa impuesta por la RAS.
- $d \in [0, 1]$ — variable de daño escalar de tracción.
- $E_\text{eff} = E_0 \cdot (1 - \beta_E \cdot \text{activity}(\xi))$ — módulo degradado por la RAS.
- $\mathbf{C}(E_\text{eff},\nu)$ — matriz de rigidez elástica estándar 2D.

### 2.2 Ley de daño de tracción

Criterio de daño en deformación principal equivalente $\tilde\varepsilon$ (mayores valores propios de $\boldsymbol{\varepsilon}_\text{mec}$):

$$d = 1 - \frac{\varepsilon_0}{\kappa}\exp\!\left(-\frac{\kappa - \varepsilon_0}{\varepsilon_f - \varepsilon_0}\right)$$

con $\varepsilon_0 = f_t/E$, $\varepsilon_f = G_f/(f_t\,h_e)$ (regularización por tamaño de elemento para objetividad de malla). Leyes disponibles: **exponencial** (viga) y **lineal** (presa).

Daño de compresión: opcional (`enable_compression_damage`).

### 2.3 Modelo RAS

La reacción se describe mediante la variable de avance $\xi(t) \in [0, 1]$. Tres modos:

| Modo | Descripción |
|---|---|
| `imposed` | $\xi$ fijo, impuesto por el usuario |
| `larive` | Sigmoid de Larive: $\xi = f(\tau_\text{lat}, \tau_\text{ch})$ |
| `simple_exp` | Exponencial simple: $\xi = 1 - e^{-t/\tau}$ |

Degradación de propiedades con $\xi$:
$$P = P_0 \cdot \max\!\bigl(1 - \beta_P\,\xi^q,\; P_{\min\,\text{factor}}\bigr)$$

Las propiedades degradadas son: $E$, $f_t$, $f_c$, $G_f$ (con factores independientes $\beta_E$, $\beta_{f_t}$, $\beta_{f_c}$, $\beta_{G_f}$).

### 2.4 Shear convention

La deformación principal equivalente se calcula con un factor de corte configurable (`strain_shear_factor`):
- **Viga (Q4):** `strain_shear_factor = 1.0` — deformación de ingeniería directa.
- **Presa (T3):** `strain_shear_factor = 0.5` — deformación tensorial ($\gamma/2$).

Este parámetro reproduce exactamente las dos convenciones de los scripts legados.

---

## 3. Arquitectura técnica

### 3.1 Estructura del paquete

```
femras/                     ← raíz del repositorio
├── femras/                 ← paquete Python principal
│   ├── config.py           ← schema Pydantic (ficha de datos)
│   ├── run.py              ← orquestador (config → resultado)
│   ├── analysis.py         ← drivers incrementales adaptativos
│   ├── assembly.py         ← ensamblador vectorizado
│   ├── solver.py           ← Newton-Raphson + line search
│   ├── damage.py           ← modelo constitutivo + GPState
│   ├── materials.py        ← MatDamage, matriz elástica
│   ├── ras.py              ← modelo RAS (xi, expansión, degradación)
│   ├── loads.py            ← cargas externas (hidráulica, puntual)
│   ├── stages.py           ← expansión libre inicial, make_constitutive
│   ├── postprocess.py      ← figuras, tablas, resumen JSON
│   ├── cli.py              ← interfaz línea de comandos (Click)
│   ├── backend.py          ← selector NumPy/Numba/GPU
│   ├── elements/
│   │   ├── base.py         ← precompute(), coordenadas Gauss, B-matrices
│   │   ├── q4.py           ← elemento cuadrilátero bilineal
│   │   └── t3.py           ← elemento triangular lineal
│   └── mesh/
│       ├── structured.py   ← malla rectilínea para la viga (Q4)
│       └── polygon.py      ← malla Delaunay T3 para polígonos arbitrarios
├── api/
│   └── main.py             ← servidor FastAPI (web local)
├── web/
│   ├── index.html          ← SPA (Single Page Application)
│   ├── app.js              ← modo Texto + i18n + Plotly
│   ├── editor.js           ← preprocesador gráfico (canvas SVG)
│   └── style.css           ← sistema de diseño (dark theme, CSS variables)
├── examples/
│   ├── viga_rilem.yaml     ← caso de referencia: viga entallada
│   └── presa_ras.yaml      ← caso de referencia: presa de gravedad
├── examples/legacy/        ← scripts originales (referencia de validación)
├── tests/                  ← suite pytest (11 tests)
└── docs/
    ├── teoria_modelo.md    ← teoría del modelo (ES)
    ├── manual_usuario_es.md
    └── manual_usuario_en.md
```

### 3.2 Stack tecnológico

| Capa | Tecnología |
|---|---|
| Núcleo numérico | Python 3.10+, NumPy (vectorizado sobre puntos Gauss) |
| Malla T3 | `triangle` (Delaunay conformante vía `meshpy`) |
| Aceleración CPU | Numba JIT (opcional, `pip install -e ".[numba]"`) |
  Aceleración GPU | CuPy + CUDA 12 (opcional, `pip install -e ".[gpu]"`, activación automática ≥ 50 000 DOF) |
| Schema / validación | Pydantic v2 |
| Serialización | YAML (PyYAML) + JSON |
| API web | FastAPI + Uvicorn |
| Frontend | HTML/CSS/JS vanilla + Plotly (sin frameworks) |
| CLI | Click |
| Tests | pytest |

### 3.3 Flujo de datos

```
YAML/JSON (ficha de datos)
    │
    ▼ Config.model_validate()
Config (Pydantic)
    │
    ▼ run_config()
    ├── _run_beam()      → malla Q4 + control por desplazamiento
    └── _run_dam()       → malla T3 + control por nivel de agua
            │
            ▼
    run_displacement_control() / run_load_control()
    (stepping adaptativo + Newton-Raphson por paso)
            │
            ▼
    AnalysisResult (curva carga-desplazamiento, mapa de daño, tabla)
            │
            ▼
    postprocess.save_*()  → figuras PNG, tablas CSV, resumen JSON
```

---

## 4. Ficha de datos (schema de configuración)

La ficha es un archivo YAML o JSON validado por Pydantic. Toda la información para una corrida está contenida en la ficha.

### 4.1 Sección `problem`

```yaml
problem:
  element_type: q4          # "q4" (viga) | "t3" (polígono/presa)
  problem_type: plane_stress # "plane_stress" | "plane_strain"
  thickness: 75.0            # espesor para estado plano (mm)
  strain_shear_factor: 1.0   # 1.0 (viga) | 0.5 (presa, conv. tensorial)
```

### 4.2 Sección `material`

```yaml
material:
  E0: 38100.0                # módulo de Young inicial (MPa)
  nu: 0.20                   # coeficiente de Poisson
  ft0: 4.0                   # resistencia a tracción inicial (MPa)
  fc0: 51.2                  # resistencia a compresión inicial (MPa)
  Gf0: 0.10                  # energía de fractura inicial (N/mm)
  Gc0: 10.0                  # energía de fractura a compresión (N/mm)
  damage_max: 0.99999        # daño máximo permitido
  enable_compression_damage: false
  softening_law: exponential  # "exponential" | "linear"
```

### 4.3 Sección `ras`

```yaml
ras:
  enabled: true
  mode: larive               # "imposed" | "larive" | "simple_exp"
  xi_imposed: 0.0            # xi fijo (solo si mode=imposed)
  age_days: 300.0            # edad del hormigón (días, para mode=larive)
  tau_lat: 188.83            # Larive: tiempo de latencia (días)
  tau_ch: 161.89             # Larive: tiempo característico (días)
  tau: 200.0                 # simple_exp: constante de tiempo (días)
  eps_inf_vol: 0.0042        # expansión volumétrica última
  linear_divisor: 3.0        # eps_lin = eps_inf_vol / linear_divisor
  expansion_scale: 1.0       # escala adicional (usada por presa)
  activity_power: 1.0        # activity(xi) = xi^power
  beta_E: 0.25               # degradación del módulo
  beta_ft: 0.45              # degradación de ft
  beta_fc: 0.15              # degradación de fc
  beta_Gf: 0.55              # degradación de Gf
  E_min_factor: 0.20         # piso de E/E0
  ft_min_factor: 0.10        # piso de ft/ft0
  fc_min_factor: 0.20        # piso de fc/fc0
  Gf_min_factor: 0.10        # piso de Gf/Gf0
```

### 4.4 Sección `geometry`

**Viga (Q4, malla estructurada):**

```yaml
geometry:
  kind: beam
  L: 430.0          # longitud total (mm)
  H: 105.0          # altura (mm)
  nx: 86            # divisiones en X
  ny: 21            # divisiones en Y
  notch_width: 3.0  # ancho de entalla central (mm)
  notch_height: 52.5 # altura de entalla (mm)
  support_span: 400.0 # distancia entre apoyos (mm)
```

**Polígono arbitrario (T3, malla Delaunay):**

```yaml
geometry:
  kind: polygon
  vertices:          # lista de vértices [x, y] en mm, sentido antihorario
    - [0, 0]
    - [75000, 0]
    - [8000, 103000]
  mesh_size: 2000.0  # tamaño objetivo de elementos (mm)
  height: 103000.0   # altura de referencia (para localizar nodo de cresta)
```

### 4.5 Sección `supports`

Lista de apoyos puntuales (por nodo más cercano):

```yaml
supports:
  - {x: 0.0, y: 0.0, fix_x: true, fix_y: true}
  - {x: 430.0, y: 0.0, fix_x: false, fix_y: true}
```

> **Nota:** este campo existe en el schema pero actualmente **no es utilizado** por los drivers `_run_beam` ni `_run_dam`, que hardcodean sus condiciones de borde. Ver sección 9 (pendientes).

### 4.6 Sección `loading`

**Control por desplazamiento (viga):**

```yaml
loading:
  mode: displacement
  x_center: 215.0     # posición X del parche de carga (mm)
  y_top: 105.0        # posición Y del parche (mm)
  patch: three_nodes_centered  # "one_node" | "three_nodes_centered"
  target: -0.20       # desplazamiento objetivo del parche (mm)
  step_initial: -0.0010
  step_min: -0.000010
  step_max: -0.0015
  grow_factor: 1.10
  shrink_factor: 0.5
  max_accepted_steps: 600
  history: []         # secuencia de targets (carga cíclica/multi-segmento).
                      # Si vacío → [target]. Ejemplo: [-0.10, 0.0, -0.20]
```

**Control por nivel de agua (presa):**

```yaml
loading:
  mode: hydraulic
  gamma_c: 2.40e-5    # peso específico del hormigón (N/mm³)
  gamma_w: 9.81e-6    # peso específico del agua (N/mm³)
  h_start: 92000.0    # nivel de agua inicial (mm)
  h_target: 120000.0  # nivel de agua objetivo (mm)
  dh_initial: 500.0   # incremento inicial (mm)
  dh_min: 20.0        # incremento mínimo (mm)
  dh_max: 500.0       # incremento máximo (mm)
  max_accepted_steps: 600
  face_vertices: null  # [[x1,y1],[x2,y2]] de la cara hidráulica.
                       # null → backward-compat: cara vertical en x=0
  history: []          # secuencia de niveles objetivo (multi-segmento)
```

### 4.7 Sección `solver`

```yaml
solver:
  tangent_mode: numerical_hybrid  # "numerical_hybrid" | "numerical" | "secant" | "elastic"
  max_iter: 60
  tol_res_abs: 1.0e-4
  tol_res_rel: 1.0e-5
  tol_du: 1.0e-8
  use_line_search: true
  min_stiff_factor: 1.0e-8
  backend: auto          # "auto" | "numpy" | "numba" | "gpu"
```

### 4.8 Sección `service` (etapa de servicio RAS para la presa)

```yaml
service:
  service_years: 16      # 0 = presa sana; 16 = con RAS
  dt_days: 3.0           # paso de tiempo durante el servicio (días)
  h_service_max: 92000.0 # nivel máximo durante el servicio (mm)
  h_service_min: 37000.0 # nivel mínimo durante el servicio (mm)
  xi_target: 0.70        # xi al final del período de servicio
  xi_rate: 3.0           # parámetro de crecimiento exponencial de xi
```

### 4.9 Sección `output`

```yaml
output:
  dir: resultados_femras   # directorio de salida
  dpi: 200
  save_figures: true
  save_tables: true
```

---

## 5. Análisis implementados

### 5.1 Control por desplazamiento — Viga RILEM

**Geometría:** viga prismática entallada (Q4, tensión plana).  
**Condiciones de borde (hardcodeadas):** dos apoyos puntuales separados `support_span` mm, simétricamente. El izquierdo fija X e Y; el derecho fija solo Y.  
**Carga:** desplazamiento vertical impuesto en un parche de 1 o 3 nodos en la parte superior.  
**Salida:** curva fuerza–desplazamiento (P–δ), mapa de daño, tabla de pasos.

**Caso de referencia validado:**
- Hormigón R4 sin RAS: P_max ≈ 1511 N. Reproducido con precisión punto a punto (`tests/test_legacy_equivalence.py`).

### 5.2 Control por nivel de agua — Presa de gravedad

**Geometría:** polígono triangular (T3, deformación plana), malla Delaunay conformante.  
**Condiciones de borde (hardcodeadas):** todos los nodos con y = 0 empotrados (ambas componentes).  
**Carga:** presión hidrostática en la cara aguas arriba. La presión en cada elemento de borde es función del nivel actual del agua H.  
**Cara hidráulica:** vertical en x = 0 por defecto; puede ser cualquier arista del polígono si `face_vertices` está definido.  
**Salida de control:** desplazamiento horizontal del nodo de cresta.

**Etapa de servicio RAS (opcional):** antes de la fase de sobrecarga hidráulica, se simula el período de servicio con xi creciente y nivel de agua sinusoidal anual.

**Casos de referencia:**
- Presa sana (ANIOS = 0): nivel de fallo ≈ 112.5 m. ✓
- Presa con 16 años de RAS: nivel de fallo ≈ 108.8 m < sana. ✓

### 5.3 Historia de carga multi-segmento

Ambos modos de análisis soportan una historia de carga arbitraria mediante el campo `history`:

- `history: []` → comportamiento estándar (un solo segmento hasta `target` o `h_target`).
- `history: [-0.10, 0.0, -0.20]` → tres segmentos: carga hasta -0.10, descarga hasta 0.0, carga hasta -0.20.

El estado de daño ($\kappa_t$, $\kappa_c$, $d_t$, $d_c$) y el campo de desplazamientos se encadenan entre segmentos. La dirección del stepping adaptativo se invierte automáticamente según el signo de (target − current).

---

## 6. Drivers incrementales y solver

### 6.1 Stepping adaptativo

Ambos drivers (desplazamiento y nivel de agua) usan stepping adaptativo:
- El incremento crece si la iteración de Newton converge en pocas iteraciones (`grow_factor`).
- El incremento se reduce si converge tardíamente o falla (`shrink_factor`).
- El incremento se clampea entre `step_min` y `step_max`.
- El paso se recorta exactamente al llegar al target del segmento.

### 6.2 Newton-Raphson con line search

Cada paso del stepping resuelve el sistema no lineal mediante Newton-Raphson:
- Modos de tangente: `numerical_hybrid` (defecto), `numerical`, `secant`, `elastic`.
- Line search activable para mejorar convergencia en estados con daño avanzado.
- Tolerancias duales: residuo absoluto + relativo + norma de desplazamiento incremental.
- En caso de no convergencia: el paso es rechazado y el incremento se reduce.

### 6.3 Backend numérico

- **NumPy (defecto):** vectorizado, sin dependencias extras.
- **Numba:** JIT del ensamblador y evaluación constitutiva. Hooks disponibles, kernels completos en desarrollo.
- **GPU (CuPy + CUDA 12):** activación automática para mallas ≥ 50 000 DOF. Sin beneficio para mallas pequeñas.

---

## 7. Interfaz de línea de comandos (CLI)

```bash
femras --help                     # ayuda
femras run config.yaml            # ejecutar análisis
femras examples [destino/]        # copiar ejemplos a directorio de trabajo
```

Salida en `resultados_femras/<nombre>/`:
- `summary.json` — resumen: P_max, δ_max, nivel de fallo, xi, n_nodos, n_elementos.
- `curve.csv` / `damage.csv` — tablas de la curva y del mapa de daño.
- `curve.png` / `damage.png` — figuras PNG (configurable DPI).

---

## 8. App web local

### 8.1 Inicio

```bash
uvicorn api.main:app --reload
# Abrir http://127.0.0.1:8000
```

La app tiene dos modos, seleccionables en el header. El switch de idioma (ES/EN) afecta a ambos.

### 8.2 Modo Texto

- Textarea JSON para editar la ficha de datos directamente.
- Botones "Ejemplo viga" / "Ejemplo presa" para cargar las fichas de referencia.
- "Previsualizar malla": llama a `POST /api/mesh_preview` y dibuja la malla como SVG.
- "Calcular": llama a `POST /api/run` y muestra la curva carga-control con Plotly + resumen de resultados.

### 8.3 Modo Canvas (preprocesador gráfico)

Layout de 3 paneles:

```
┌──────────────────────────────────────────────────────────┐
│  Header: logo | [Texto] [Canvas] | spacer | [ES/EN]      │
├──────┬───────────────────────────────────┬───────────────┤
│Palet │                                   │ Panel derecho │
│ de   │      SVG interactivo              │  (acordeón)   │
│ her  │      (escala y-up)                │               │
│ ram  │                                   │               │
│      ├───────────────────────────────────┤               │
│      │ Barra de estado: coords | herram  │               │
└──────┴───────────────────────────────────┴───────────────┘
```

#### Herramientas (paleta izquierda)

| Icono | Tecla | Herramienta | Acción |
|---|---|---|---|
| ✦ | V | Vértice | Clic para agregar vértice al polígono; doble clic para cerrar |
| △ | F | Fijo | Clic en vértice: empotrado (ux=0, uy=0) |
| ⊿ | X | Rodillo X | Clic en vértice: uy=0 (libre en X) |
| ◁ | Y | Rodillo Y | Clic en vértice: ux=0 (libre en Y) |
| ↓ | L | Carga | Clic en vértice: carga puntual vertical |
| 〜 | E | Cara H. | Clic en arista: designa cara hidráulica |
| ✕ | D | Borrar | Clic en vértice: eliminar |

#### Panel derecho — secciones acordeón

1. **Propiedades (Inspector):** al seleccionar un vértice, muestra x e y editables; muestra tags de apoyo, carga y cara hidráulica.
2. **Historial de carga:** lista de segmentos (campo numérico por segmento) + botón "Agregar paso" + miniatura SVG de la historia de carga.
3. **Geometría:** campos de malla (tamaño, espesor, tipo de problema) para polígono; campos L/H/nx/ny/entalla/vano para viga.

#### Panel inferior (scroll)
- Plantillas: botones "Presa" y "Viga" que cargan geometrías predefinidas.
- "Ver malla": genera preview de la malla sobre el SVG.
- "Exportar a Texto": transfiere la ficha JSON al modo Texto para ejecutar.

#### Visualización del canvas

- SVG con transformación `scale(1,-1)` para coordenadas y-up (convenio ingeniería).
- Vértices: círculos rellenos color primario.
- Aristas del polígono: líneas con hover highlight.
- Apoyos en vértice: triángulos del color `--support-col` (amarillo).
- Cara hidráulica: arista resaltada en `--face-col` (azul) con label "≈".
- Hover en herramienta EDGE: arista candidata resaltada en amarillo.
- Overlay de malla: polígonos T3/Q4 en verde semitransparente (50% opacidad).
- Coordenadas en tiempo real en la barra de estado.

#### Exportación a JSON / Endpoints API

| Endpoint | Método | Descripción |
|---|---|---|
| `/` | GET | Sirve la SPA (index.html) |
| `/style.css` | GET | Hoja de estilos |
| `/app.js` | GET | Lógica modo Texto + i18n |
| `/editor.js` | GET | Lógica canvas |
| `/api/example/{name}` | GET | Retorna JSON de ejemplo (`beam` / `dam`) |
| `/api/run` | POST | Ejecuta análisis desde JSON de config → curva + resumen |
| `/api/mesh_preview` | POST | Retorna nodos/elementos para previsualización |

---

## 9. Tests y validación

11 tests en `tests/`, ejecutables con `pytest tests/ -v` (~15 s):

| Test | Descripción |
|---|---|
| `test_legacy_equivalence.py` | Equivalencia constitutiva punto a punto vs. `viga_rilem.py` y `presa_ras.py` (precisión 1e-13) |
| Tests de regresión estructural | Viga: curva P–δ completa; Presa: nivel de fallo sana vs. RAS |
| Tests unitarios de elementos | Q4 y T3: matrices B, rigidez, consistencia |
| Tests unitarios de leyes RAS | Larive, degradación de propiedades, expansión |
| Tests de malla | Polígono conformante T3, malla estructurada Q4 |

**Restricción de regresión:** cualquier cambio al núcleo numérico debe mantener los 11 tests pasando sin modificación de los tests ni de los archivos YAML de ejemplos.

---

## 10. Sistema de diseño (app web)

CSS con variables CSS (dark theme):

```css
--bg:          #0d1929   /* fondo principal */
--surface:     #132135   /* paneles */
--surface2:    #1a2d47   /* entradas, dropdowns */
--primary:     #3b82f6   /* botones, foco */
--accent:      #60a5fa   /* links, valores */
--support-col: #fbbf24   /* apoyos (amarillo) */
--load-col:    #f87171   /* cargas (rojo) */
--face-col:    #38bdf8   /* cara hidráulica (celeste) */
--success:     #34d399   /* malla, OK */
--danger:      #f87171   /* eliminar, error */
```

---

## 11. Estado de implementación

### Implementado y validado

- [x] Modelo constitutivo daño + RAS vectorizado (NumPy)
- [x] Elemento Q4 (viga, tensión plana)
- [x] Elemento T3 (presa, deformación plana)
- [x] Malla estructurada con entalla (viga)
- [x] Malla Delaunay conformante T3 (polígono arbitrario)
- [x] Driver por desplazamiento (stepping adaptativo, multi-segmento)
- [x] Driver por nivel de agua (stepping adaptativo, multi-segmento)
- [x] Cara hidráulica generalizada (`face_vertices` + `face_boundary_edges`)
- [x] Historia de carga cíclica (`history: List[float]`)
- [x] Etapa de servicio RAS (presa: xi creciente, nivel sinusoidal anual)
- [x] Postproceso: curvas, mapas de daño, tablas, resumen JSON
- [x] CLI (`femras run`, `femras examples`)
- [x] API FastAPI con endpoints de run + mesh_preview
- [x] App web: modo Texto (JSON + Plotly + SVG mesh)
- [x] App web: modo Canvas con 7 herramientas, 3 paneles, atajos de teclado
- [x] i18n ES/EN en ambos modos (evento `langchange`, `applyI18n()`)
- [x] Inspector de propiedades (edición de coordenadas de vértices)
- [x] Panel de historial de carga (segmentos + preview SVG)
- [x] Designación de cara hidráulica desde canvas (herramienta EDGE)
- [x] Sistema de diseño CSS completo (dark theme, variables, layout 3 paneles)
- [x] 11 tests; validación vs. legado
- [x] Documentación bilingüe (manual ES/EN, teoría del modelo, README)

### Implementado, pendiente de calibración

- [~] Presa con servicio RAS: el pipeline corre correctamente, pero la curva numérica no reproduce aún la tendencia sana vs. RAS del script legado. Requiere calibración de parámetros ($\beta_E$, $\beta_{G_f}$, ley lineal de daño, etc.) contra `presa_ras.py`.

### Disponible pero no conectado

- [ ] `cfg.supports`: el campo existe en el schema pero ningún driver lo usa. Los apoyos están hardcodeados (ver sección 12).
- [ ] Numba JIT: hooks de detección presentes; kernels completos no implementados.

---

## 12. Pendientes prioritarios

### P1 — Condiciones de apoyo en aristas completas (Edge Supports)

**Problema:** los apoyos están hardcodeados en los drivers:
- Presa: `base_nodes(nodes, y_base=0.0)` empotra automáticamente toda la base.
- Viga: 2 nodos calculados desde `support_span`.

Para polígonos arbitrarios, el usuario necesita designar **aristas completas** como zonas de apoyo (fixed / roller_x / roller_y), de modo que todos los nodos de la malla sobre esa arista reciban la condición de borde.

Ver PRD detallado: [`docs/prd_edge_supports.md`](prd_edge_supports.md).

**Resumen de cambios requeridos:**

| Componente | Cambio |
|---|---|
| `config.py` | Nuevo modelo `EdgeSupportCfg`; campo `edge_supports: List[EdgeSupportCfg]` en `Config` |
| `mesh/polygon.py` | Nueva función `nodes_on_segment(nodes, elements, p1, p2)` |
| `run.py` | `_run_dam`: procesar `cfg.edge_supports`; fallback a `base_nodes` si vacío |
| `editor.js` | Extender herramienta SUPPORT para detectar clic en arista; `poly.edgeSupports`; exportar `edge_supports` |

### P2 — Calibración numérica del caso presa con RAS

La etapa de servicio RAS y la subsecuente sobrecarga hidráulica corren sin error, pero la curva no reproduce la tendencia del script legado. Requiere:
- Revisión de los parámetros de degradación ($\beta_E$, $\beta_{G_f}$, $\beta_{f_t}$, floors).
- Verificación de la ley de daño lineal (la presa usa `softening_law = "linear"`).
- Comparación paso a paso de tensiones y daño contra `presa_ras.py`.

### P3 — Numba JIT completo

El backend Numba tiene hooks de detección pero no kernels JIT implementados. Para mallas medianas (10 000–50 000 DOF) es el camino principal de aceleración antes de necesitar GPU.

---

## 13. Fuera de alcance (no goals)

- Análisis 3D o axisimétrico.
- Elementos de mayor orden (Q8, T6).
- Plasticidad (solo daño escalar de tracción + opcional de compresión).
- Campo de temperatura heterogéneo (solo xi uniforme en la etapa de servicio).
- Servidor de producción, autenticación, base de datos (la app es local y monousuario).
- Preprocesado de geometrías importadas desde CAD/BIM (solo canvas interactivo).
- Módulo de postproceso con mapa de desplazamientos (actualmente solo curva y mapa de daño).

---

## 14. Casos de uso principales

### CU-1: Análisis de viga RILEM con RAS

1. El usuario copia los ejemplos (`femras examples`).
2. Edita `viga_rilem.yaml`: cambia `ras.mode` a `larive`, `ras.age_days` a 485.
3. Ejecuta `femras run viga_rilem.yaml`.
4. Compara la curva P–δ resultante con la del hormigón sano para cuantificar la pérdida de capacidad por RAS.

### CU-2: Evaluación de presa de gravedad con servicio RAS

1. El usuario configura `presa_ras.yaml` con `service.service_years: 16`.
2. Ejecuta el análisis (~10–15 min).
3. Compara el nivel de fallo con el caso sano para estimar la reducción de seguridad.

### CU-3: Polígono arbitrario desde el canvas

1. El usuario abre la app web (`uvicorn api.main:app --reload`).
2. Activa el modo Canvas y dibuja el contorno del polígono.
3. Designa la cara hidráulica (herramienta EDGE).
4. Define la historia de carga (panel "Historial de carga").
5. Exporta la ficha al modo Texto y ejecuta el análisis.

### CU-4: Carga cíclica (multi-segmento)

1. El usuario define `history: [-0.10, 0.0, -0.20]` en `loading` de una viga.
2. El driver ejecuta tres segmentos encadenando el estado de daño.
3. La curva resultante muestra carga → descarga → recarga con daño acumulado.
