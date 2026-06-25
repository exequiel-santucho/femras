# User manual — femras (English)

> 2D FEM tool for concrete affected by the Alkali-Silica Reaction (ASR/RAS).
> Version 0.1.0 · MIT License · Free and open-source.

---

## Contents

1. [What does this tool do?](#1-what-does-this-tool-do)
2. [Prerequisites](#2-prerequisites)
3. [Downloading the code](#3-downloading-the-code)
4. [Installing Python and the package](#4-installing-python-and-the-package)
5. [First run — command line](#5-first-run--command-line)
6. [Local web app](#6-local-web-app)
7. [The data sheet (YAML file)](#7-the-data-sheet-yaml-file)
8. [Worked example 1 — Notched beam (RILEM)](#8-worked-example-1--notched-beam-rilem)
9. [Worked example 2 — Gravity dam (overtopping)](#9-worked-example-2--gravity-dam-overtopping)
10. [Interpreting results](#10-interpreting-results)
11. [Performance and compute backends](#11-performance-and-compute-backends)
12. [Verification tests](#12-verification-tests)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. What does this tool do?

`femras` solves 2D plane finite element problems for concrete structures affected
by the **Alkali-Silica Reaction (ASR)**. The model includes:

- **Imposed ASR expansion**:

$$
\boldsymbol{\varepsilon}_\text{ASR} = \xi\,\varepsilon_\text{ASR}^\infty\,[1,\,1,\,0]^\top
$$
- **Fracture-energy-regularised tensile damage** (mesh-objective).
- **Mechanical property degradation** (E, ft, fc, Gf) with reaction extent ξ.
- **Two numerically validated reference cases**: notched RILEM beam and gravity dam.

Results from femras numerically reproduce the original research scripts
(`viga_rilem.py` and `presa_ras.py`) and are covered by an automated test suite
(see [Section 12](#12-verification-tests)).

---

## 2. Prerequisites

### 2.1 Python

You need **Python 3.10 or newer**.

To check if it is already installed, open a terminal and type:

```
python --version
```

If it shows `Python 3.10.x` or higher, move to the next step.
If the command is not found or shows an older version, download the installer
from **https://www.python.org/downloads/**. On Windows, tick
**"Add Python to PATH"** before clicking *Install Now*.

> **How to open a terminal**
> - **Windows**: press `Win + R`, type `cmd`, press Enter. Or search "Command
>   Prompt" in the Start menu. VS Code's integrated terminal also works.
> - **macOS**: open the *Terminal* app (Spotlight: `Cmd + Space`, type "Terminal").
> - **Linux**: open *Terminal* from the application menu.

### 2.2 Git (optional but recommended)

Git lets you download the code and keep it up to date easily.
Check: `git --version`. Download from **https://git-scm.com/downloads** if needed.

If you prefer not to use Git, the [next section](#3-downloading-the-code)
explains how to download the code as a ZIP.

### 2.3 Internet connection (installation only)

An internet connection is needed to download the code and its dependencies.
Once installed, `femras` works completely offline.

---

## 3. Downloading the code

Choose the option that suits you best.

### Option A — Download as ZIP (no Git needed)

1. Open the repository in your browser:
   `https://github.com/exequiel-santucho/femras`
2. Click the green **"Code"** button → **"Download ZIP"**.
3. Extract the ZIP to a folder of your choice, for example:
   - Windows: `C:\femras\`
   - macOS/Linux: `~/femras/`
4. The extracted folder should contain `pyproject.toml`, `README.md`, and a
   `femras/` subfolder.

### Option B — Clone with Git (recommended)

Open a terminal, navigate to where you want to store the project, and run:

```bash
git clone https://github.com/exequiel-santucho/femras.git
cd femras
```

To update the code later:

```bash
git pull
```

---

## 4. Installing Python and the package

### 4.1 Navigate to the project folder

Open a terminal and navigate to the folder where you downloaded or cloned the code.
If you are new to terminal navigation:

```bash
# Windows (replace the path):
cd C:\femras

# macOS / Linux:
cd ~/femras
```

Verify you are in the right folder: run `dir` (Windows) or `ls` (macOS/Linux).
You should see `pyproject.toml` in the listing.

### 4.2 Create a virtual environment (recommended)

A virtual environment isolates `femras`'s dependencies from other Python
projects. It is optional but a good practice:

```bash
# Create the environment (one-time setup):
python -m venv .venv

# Activate it:
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
```

When the environment is active, the terminal prompt shows `(.venv)` at the
beginning. To deactivate: `deactivate`.

### 4.3 Install the core package

With the environment active (or without it if you prefer a system-wide install):

```bash
pip install -e .
```

This installs `femras` with its base dependencies: numpy, scipy, matplotlib,
pydantic, pyyaml.

Verify the installation:

```bash
femras --help
```

You should see:
```
usage: femras [-h] {run,examples,validate} ...
```

### 4.4 Optional extras

```bash
# CPU acceleration with Numba JIT (faster analyses):
pip install -e ".[numba]"

# Local web app (needed for the browser interface):
pip install -e ".[web]"

# GPU linear solver (only useful for very large meshes, requires NVIDIA GPU):
pip install -e ".[gpu]"

# Everything at once:
pip install -e ".[numba,web]"
```

---

## 5. First run — command line

Make sure you are in the `femras/` folder with the virtual environment active.

### 5.1 Copy the examples to a working folder

```bash
femras examples my_examples
```

This creates the `my_examples/` folder with the configuration files for both
reference cases.

### 5.2 Run the beam example

```bash
femras run my_examples/viga_rilem.yaml
```

During the analysis you will see progress in the terminal (step, control,
load, damage). When finished, results are saved to
`resultados_femras/viga_rilem/`:

```
resultados_femras/
  viga_rilem/
    resumen.json          <- peak load, max damage, analysis parameters
    curva.csv             <- step-by-step table (displacement, load)
    curva.png             <- load-displacement plot
    mapa_dano.png         <- damage map over the mesh
    mapa_sigma_x.png      <- horizontal stress by element
    tabla_incremental.csv <- convergence detail per step
```

### 5.3 Run the dam example

```bash
femras run my_examples/presa_ras.yaml
```

This analysis takes longer (larger mesh, RAS service stage).
Results go to `resultados_femras/presa_ras/`.

### 5.4 Validate a config without running

```bash
femras validate my_examples/viga_rilem.yaml
```

Prints all resolved parameters with their default values — useful to catch YAML
syntax errors before launching a long analysis.

### 5.5 Choosing the compute backend (numpy / numba / gpu)

The backend controls how the linear system is solved and the stiffness matrix
is assembled. It is set **inside the YAML file**, under the `solver` section:

```yaml
solver:
  backend: numpy    # options: numpy | numba | gpu | auto
```

| Backend | When to use | Extra requirement |
|---|---|---|
| `numpy` | Always available. For testing and small meshes. | None |
| `numba` | Long analyses on desktop CPUs (parallel JIT assembly). First run takes ~2 s extra to compile. | `pip install -e ".[numba]"` |
| `gpu` | Very large meshes (≥ 50 000 DOF). No benefit for small meshes. | NVIDIA GPU + CUDA 12, then `pip install -e ".[gpu]"` |
| `auto` | Automatically picks the best available (gpu if large mesh + CuPy, else numba, else numpy). | — |

**How to change the backend for an example without editing the original YAML?**

Copy the file and change only the backend line:

```bash
# Copy the beam example
copy my_examples\viga_rilem.yaml my_examples\beam_numba.yaml
```

Open `my_examples/beam_numba.yaml` in any text editor and add or change:

```yaml
solver:
  backend: numba
```

Then run as usual:

```bash
femras run my_examples/beam_numba.yaml
```

> **Tip:** `backend: auto` is the most practical choice for everyday use — it
> will use the best available backend without you having to remember what you
> installed.

---

## 6. Local web app

The web interface lets you configure and run analyses from a browser, without
writing code or using the terminal (except to start the server).

### 6.1 Requirements

Make sure you have installed the `[web]` extra:

```bash
pip install -e ".[web]"
```

### 6.2 Start the server

From the project folder, with the virtual environment active:

```bash
uvicorn api.main:app --reload
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [...]
```

### 6.3 Open in the browser

Open your browser (Chrome, Firefox, Edge) and go to:

```
http://127.0.0.1:8000
```

The femras interface will load.

### 6.4 Using the interface — Text mode

The default mode works as a data-sheet editor:

1. **Load an example**: click "Beam example" or "Dam example" to load the
   reference configuration as an editable JSON block.
2. **Preview the mesh**: click *Preview mesh* to see the geometry in the
   right panel before running.
3. **Run**: click *Calculate*. The analysis runs on the local server and the
   response curve appears as an interactive Plotly chart.

### 6.5 Using the interface — Canvas mode (graphical preprocessor)

Click the **Canvas** button (top-right header) to switch to the interactive
geometry editor. No YAML writing needed — you draw the model directly on screen.

#### Starter templates

Two ready-to-use templates are available in the left panel:

| Button | Model | Mesh type |
|---|---|---|
| **Dam** | 5-vertex polygon (70×103 m) | T3, plane strain |
| **Beam** | 430×105 mm form + notch | Q4, plane stress |

#### Polygon mode — free geometry drawing

With the **Dam** template (or on a blank canvas):

| Action | Result |
|---|---|
| **Single click** (Vertex ✦ tool) | Adds a new vertex at that position |
| **Double click** | Closes the polygon |
| **Drag** an existing vertex | Moves it |
| **Delete** key | Removes the selected vertex (red circle) |
| **Delete ✕ tool** + click | Removes the vertex under the cursor |

To add supports or loads, select the corresponding tool and click near the
target vertex:

| Tool | Icon | Key | Type |
|---|---|---|---|
| Fixed support | △ Fixed | F | Restrains ux and uy at the **vertex** |
| X roller | ⊿ Rol.X | X | Restrains ux at the vertex (free in X = `fix_x:false`) |
| Y roller | ◁ Rol.Y | Y | Restrains uy at the vertex |
| Point load | ↓ Load | L | Nodal force `(fx, fy)` with time multiplier λ(t) |
| Hydraulic face | 〜 H.Face | E | Marks an edge as the water-pressure face |
| Edge support | ⩒ Edge sup. | G | Restrains a **whole edge** (type chosen in the inspector) |
| Edge load | ⇊ Edge load | B | Distributed normal+tangential traction on an edge, with λ(t) |

> **Vertex vs. edge.** The `F/X/Y` support tools and the `L` load tool act on
> **vertices** (nearest node). **Edge support (G)** and **Edge load (B)** act on
> the **whole edge**: hovering highlights the edge and clicking applies the
> condition to every mesh node on it. Clicking again with the same type removes
> it (toggle).

#### Time-variable conditions — λ(t)

Both the **edge load** and the **point load** can vary in time through a
multiplier `λ(t)` that scales the reference load. When you select the load, the
inspector lets you define it two ways:

- **Function f(t)**: an expression, e.g. `10*sin(2*pi*t)` or `0.5*(1-cos(pi*t))`
  (allowed functions: `sin, cos, tan, exp, log, sqrt, abs, min, max, pow, floor,
  ceil`, plus constants `pi, e, tau`).
- **Points (t, value)**: a table, one pair per line (`0, 0` / `1, 10` …), with
  linear interpolation between points.

The inspector shows a **preview** of the λ(t) curve. The pseudo-time range and
step are set with the **t start / t end / Δt** fields in the geometry panel. The
presence of any load (edge or nodal) makes the config export with the
`time_history` mode (see § 7.5).

Adjustable parameters in the panel:

- **Mesh size (mm)**: T3 element size. Use 2000 to match the dam reference case.
- **Thickness (mm)**: out-of-plane dimension.
- **Problem type**: plane strain / plane stress.
- **Time (t start / t end / Δt)**: pseudo-time range and initial step for
  time-variable loads (`time_history`).
- **Hydraulic load**: enables water pressure on the upstream face (H.Face tool).

#### Beam mode — parametric form

With the **Beam** template, the form fields control the rectangular beam geometry:

- L, H: length and height (mm).
- nx, ny: Q4 mesh divisions.
- Notch width / height: central notch dimensions (mm).
- Support span: distance between the two supports (mm).

The schematic SVG preview updates in real time as you change the values.

#### Previewing the mesh and exporting

1. **Preview mesh**: calls the server and overlays the generated mesh (in green)
   on the canvas. Reports the number of nodes and elements.
2. **Export to Text**: converts the drawn model to JSON and loads it into the
   Text-mode textarea, ready to run with the *Calculate* button.

> **Note**: the JSON exported from the canvas uses reference material values
> (typical concrete, no ASR). You can edit them in the textarea before running
> to customise the analysis.

### 6.6 Stop the server

Go back to the terminal where you started `uvicorn` and press `Ctrl + C`.

> **Accessing from another computer on the same local network:**
> ```bash
> uvicorn api.main:app --host 0.0.0.0 --port 8000
> ```
> Access from the other machine with `http://<your-computer-IP>:8000`.

---

## 7. The data sheet (YAML file)

Each analysis is defined by **one YAML file** — the "data sheet". It is a
plain text file you can open and edit with any text editor (Notepad, VS Code,
Notepad++, etc.).

A minimal YAML file:

```yaml
name: my_case

problem:
  element_type: q4
  problem_type: plane_stress
  thickness: 75.0

material:
  E0: 38100.0     # MPa
  ft0: 4.0        # MPa
  Gf0: 0.10       # N/mm

ras:
  enabled: false  # healthy concrete

geometry:
  kind: beam
  L: 430.0
  H: 105.0
  nx: 86
  ny: 21

loading:
  mode: displacement
  target: -0.20
```

Omitted fields take their **default values** (those of the beam example).

### 7.1 `problem` section

| Parameter | Values | Description |
|---|---|---|
| `element_type` | `q4` / `t3` | Q4: 4-node quad. T3: 3-node triangle. |
| `problem_type` | `plane_stress` / `plane_strain` | Plane stress (beams) / plane strain (dams). |
| `thickness` | positive number (mm) | Out-of-plane thickness. |
| `strain_shear_factor` | `1.0` / `0.5` | 1.0 for beam (engineering shear), 0.5 for dam (tensorial). |

### 7.2 `material` section

| Parameter | Description | Units |
|---|---|---|
| `E0` | Initial Young's modulus (no ASR) | MPa |
| `nu` | Poisson's ratio | — |
| `ft0` | Tensile strength | MPa |
| `fc0` | Compressive strength | MPa |
| `Gf0` | Tensile fracture energy | N/mm |
| `Gc0` | Compressive fracture energy | N/mm |
| `damage_max` | Maximum allowed damage (0–1) | — |
| `enable_compression_damage` | `true` / `false` | Enable compressive damage |
| `softening_law` | `exponential` / `linear` | Post-peak softening law |

> `linear` reproduces the dam case (`presa_ras.py`).
> `exponential` reproduces the beam case (`viga_rilem.py`).

### 7.3 `ras` section

| Parameter | Description |
|---|---|
| `enabled` | `true` to activate ASR, `false` for healthy concrete |
| `mode` | `larive` (time law), `simple_exp`, `imposed` (direct xi) |
| `xi_imposed` | Fixed reaction extent (only with `mode: imposed`) |
| `age_days` | Concrete age in days (for `mode: larive`) |
| `eps_inf_vol` | Ultimate free volumetric expansion |
| `beta_E` | Degradation coefficient for Young's modulus |
| `beta_ft` | Degradation coefficient for tensile strength |
| `E_min_factor` | Minimum E as a fraction of E0 |

### 7.4 `geometry` section

**Rectangular beam** (Q4 or T3 elements):
```yaml
geometry:
  kind: beam
  L: 430.0
  H: 105.0
  nx: 86
  ny: 21
  notch_width: 3.0
  notch_height: 52.5
  support_span: 400.0
```

**Arbitrary polygon** (T3 elements, for dams and irregular shapes):
```yaml
geometry:
  kind: polygon
  vertices:
    - [0.0,      0.0]
    - [70000.0,  0.0]
    - [19200.0,  66000.0]
    - [14800.0, 103000.0]
    - [0.0,    103000.0]
  mesh_size: 2000.0   # approximate element size [mm]
  height: 103000.0    # reference height (crest) [mm]
```

Vertices are listed **counter-clockwise** starting from the bottom-left corner.

### 7.4b Boundary conditions — supports (`supports`, `edge_supports`)

For **polygon** geometries the supports are defined explicitly (the beam derives
them from `support_span`). There are two optional top-level fields:

**Point supports** — placed at the node nearest to `(x, y)`:

```yaml
supports:
  - {x: 0.0,     y: 0.0, fix_x: true,  fix_y: true}   # fixed
  - {x: 70000.0, y: 0.0, fix_x: false, fix_y: true}   # roller (free in X)
```

**Whole-edge supports** — applied to every mesh node on segment `[p1, p2]`:

```yaml
edge_supports:
  - vertices: [[0.0, 0.0], [70000.0, 0.0]]   # bottom edge
    fix_x: true
    fix_y: true
```

Equivalences: `fix_x:true, fix_y:true` → fixed; `fix_x:false, fix_y:true` →
roller free in X; `fix_x:true, fix_y:false` → roller free in Y.

> **Backward compatibility.** If `edge_supports` is empty or absent, the polygon
> uses the legacy behaviour: **all base nodes (y = 0) fixed** (so existing
> `presa_ras.yaml` examples are unchanged). Point `supports` are applied **after**
> and may override individual DOFs.

### 7.5 `loading` section

**Displacement control** (beam test):
```yaml
loading:
  mode: displacement
  x_center: 215.0     # load application point [mm]
  y_top: 105.0
  target: -0.20       # target displacement [mm] (negative = downward)
  step_initial: -0.0010
  step_min: -0.000010
  step_max: -0.0015
  grow_factor: 1.10
  shrink_factor: 0.5
  max_accepted_steps: 600
```

**Water-level control** (dam test):
```yaml
loading:
  mode: hydraulic
  gamma_c: 2.40e-5    # concrete unit weight [N/mm³]
  gamma_w: 9.81e-6    # water unit weight [N/mm³]
  h_start: 92000.0    # initial level [mm]
  h_target: 120000.0
  dh_initial: 500.0
  dh_min: 20.0
  dh_max: 500.0
  max_accepted_steps: 600
```

**Time history** (`time_history`) — distributed edge loads and/or nodal forces,
time-variable through a multiplier `λ(t)`. The control parameter is a pseudo-time
`t` advancing from `t_start` to `t_end`:

```yaml
loading:
  mode: time_history
  t_start: 0.0
  t_end:   1.0
  dt_initial: 0.05      # initial pseudo-time step
  dt_min: 0.0025
  dt_max: 0.10
  max_accepted_steps: 600
  self_weight: false    # include constant self-weight
  gamma_c: 2.40e-5      # concrete unit weight [N/mm³] (if self_weight)

  # Distributed edge tractions (normal + tangential)
  edge_loads:
    - vertices: [[0.0, 0.0], [0.0, 103000.0]]  # edge [p1, p2]
      p_normal: 0.01           # reference normal pressure (inward +)
      p_tangential: 0.0        # reference tangential traction
      multiplier: {expr: "0.5*(1-cos(pi*t))"}   # λ(t) by expression

  # Concentrated forces at the node nearest to (x, y)
  point_loads:
    - x: 35000.0
      y: 103000.0
      fx: 0.0
      fy: -100.0               # reference components [N]
      multiplier: {points: [[0, 0], [0.5, 1], [1, 0]]}   # λ(t) by table
```

`multiplier` accepts `{expr: "..."}` (an expression of `t`) or
`{points: [[t, value], ...]}` (a table with linear interpolation). If omitted it
is 1.0 (static reference load). Edge loads use **normal** pressure (positive
inward) and **tangential** traction (along `p1→p2`); nodal loads use global
components `(fx, fy)`.

> **This is NOT a dynamic analysis.** `λ(t)` is a *load factor* and the march is
> quasi-static (no inertia). It captures arbitrary load histories (ramps, cycles,
> …). It requires a `polygon` geometry, and supports come from
> `edge_supports`/`supports` (§ 7.4b).

### 7.6 `service` section (optional, dam only)

Simulates years of ASR service life before the overtopping test:

```yaml
service:
  service_years: 16      # 0 = healthy dam; >0 = years with active ASR
  dt_days: 3.0           # time step [days]
  h_service_max: 92000.0 # peak annual water level [mm]
  h_service_min: 37000.0 # minimum annual water level [mm]
  xi_target: 0.70        # reaction extent at end of service period
  xi_rate: 3.0           # shape parameter for the xi growth curve
```

### 7.7 `solver` section

```yaml
solver:
  tangent_mode: numerical_hybrid  # recommended
  max_iter: 30
  tol_res_abs: 1.0e-3
  tol_res_rel: 1.0e-5
  use_line_search: false
  min_stiff_factor: 1.0e-6
  backend: auto
```

`tangent_mode` options:
- `numerical_hybrid`: elastic tangent on undamaged elements, numerical
  finite-difference on damaged ones. **Recommended.**
- `numerical`: numerical tangent everywhere.
- `secant`: secant stiffness.
- `elastic`: elastic tangent always (more robust near snap-back).

---

## 8. Worked example 1 — Notched beam (RILEM)

### 8.1 Healthy beam — baseline

```bash
femras run examples/viga_rilem.yaml
```

Expected result: **P_max ≈ 1511 N** (healthy beam, Q4, 86×21 mesh).

### 8.2 Effect of ASR ageing

Create several files with different ages to study the reduction in load capacity:

```yaml
# beam_300d.yaml
name: beam_300d
ras:
  enabled: true
  mode: larive
  age_days: 300   # ~56% reaction completion
```

```bash
femras run beam_300d.yaml
```

Higher age → higher pre-existing damage → lower peak load.

---

## 9. Worked example 2 — Gravity dam (overtopping)

### 9.1 Healthy dam (no ASR)

```yaml
# dam_healthy.yaml
name: dam_healthy
ras:
  enabled: false
# omit the service section (or set service_years: 0)
```

Expected result: last converged level ≈ **112.5 m** (failure level).

### 9.2 Dam with 16 years of ASR

```bash
femras run examples/presa_ras.yaml
```

Expected result: last converged level ≈ **108.8 m** — lower than the healthy
dam, reflecting the capacity reduction due to ASR.

> **Computation time**: the 16-year service stage runs ~1950 Newton steps.
> With the 2 m mesh and the vectorised numpy backend this takes roughly
> **5–15 minutes** depending on the machine. With Numba installed
> (`pip install -e ".[numba]"`) the time is significantly reduced.

---

## 10. Interpreting results

### 10.1 Response curve (`curva.csv` / `curva.png`)

- **Beam**: X = imposed displacement δ (mm), Y = resultant load P (N). The peak
  (P_max) marks the onset of damage localisation.
- **Dam**: X = water level H (m), Y = crest horizontal displacement (mm). The
  curve stops when the solver can no longer converge (structural failure).

### 10.2 Damage map (`mapa_dano.png`)

Shows the damage variable $d \in [0,1]$ per element at the end of the analysis:
- $d \approx 0$: intact material.
- $d \approx 1$: fully damaged (open crack).

In the beam, damage localises at the notch tip. In the dam, at the heel
(upstream base).

### 10.3 JSON summary (`resumen.json`)

| Field | Description |
|---|---|
| `accepted` / `rejected` | Accepted and rejected steps by the solver |
| `load_max` | Peak load [N] (beam) |
| `failure_level` | Last converged level [mm] (dam) |
| `dmax_final` | Maximum damage in the last step |
| `xi` | Reaction extent used in the analysis |

---

## 11. Performance and compute backends

The `femras` core is **vectorised** with NumPy: all constitutive and assembly
operations work on arrays, with no Python loops per element. This is
**10×–50× faster** than the original scripts (which used `deepcopy` per
iteration and per-Gauss-point Python objects).

### 11.1 Available backends

| Backend | Install | When to use |
|---|---|---|
| `numpy` (default) | Included | Always available; start here |
| `numba` | `pip install -e ".[numba]"` | Long analyses on desktop CPUs |
| `gpu` | `pip install -e ".[gpu]"` | NVIDIA GPU, only useful for > ~50 000 DOF |
| `auto` | — | Auto-detects the best available |

Select the backend in the data sheet:
```yaml
solver:
  backend: numba   # or: numpy, gpu, auto
```

### 11.2 Numba JIT kernels (backend `numba`)

With `pip install -e ".[numba]"`, the global assembly is accelerated by two
kernels compiled at runtime (`@njit(parallel=True, cache=True)`):

- **`_ke_numba`**: computes element stiffness matrices
  $\mathbf{K}_e = \sum_\text{gp} \mathbf{B}^\top \mathbf{C}_t \mathbf{B}\,w_\text{gp}$
  in parallel over elements (`prange`), fusing the $\mathbf{B}^\top\mathbf{C}_t$ intermediate product.
- **`_fe_numba`**: computes element internal force vectors
  $\mathbf{f}_e = \sum_\text{gp} \mathbf{B}^\top \boldsymbol{\sigma}\,w_\text{gp}$ similarly in parallel.

The constitutive model (`damage.py`) is already NumPy-vectorised; its
bottleneck is the numerical tangent (3 extra evaluations per iteration),
which scales well without JIT.

**First run with Numba**: JIT compilation takes ~1–3 s the first time.
`cache=True` saves the compiled code to `__pycache__` so subsequent runs
start without delay. If `numba` is not installed, the code falls back to
NumPy silently.

### 11.3 Typical runtimes

| Case | Mesh | numpy backend | numba backend |
|---|---|---|---|
| RILEM beam (reference mesh) | 86×21 Q4 ≈ 1680 el. | ~10 s | ~3 s |
| Healthy dam (no service) | 2 m T3 ≈ 1600 el. | ~30 s | ~8 s |
| Dam 16-year ASR | same + ~1950 service steps | ~10–15 min | ~2–5 min |

---

## 12. Verification tests

`femras` includes an automated test suite that guarantees the refactored
engine reproduces the original research scripts to numerical precision.

### 12.1 Running the tests

From the project folder with the virtual environment active:

```bash
# Install pytest if needed:
pip install pytest

# Run all tests:
pytest tests/ -v
```

Expected output:
```
tests/test_legacy_equivalence.py::test_constitutive_matches_legacy   PASSED
tests/test_presa_regression.py::test_linear_softening_matches_legacy  PASSED
tests/test_presa_regression.py::test_dam_healthy_snapshot             PASSED
tests/test_presa_regression.py::test_dam_healthy_damage_monotonic     PASSED
tests/test_unit_model.py::test_elastic_split                          PASSED
tests/test_unit_model.py::test_xi_larive_bounds                       PASSED
tests/test_unit_model.py::test_degradation_floors_and_monotonic       PASSED
tests/test_unit_model.py::test_t3_b_matrix_area                       PASSED
tests/test_unit_model.py::test_q4_unit_square_jacobian                PASSED
tests/test_viga_regression.py::test_beam_snapshot                     PASSED
tests/test_viga_regression.py::test_beam_monotonic_damage             PASSED
tests/test_edge_loads.py::...  (10 tests)                             PASSED

22 passed in ~15 s
```

To run only the fast tests (skip the dam structural tests):

```bash
pytest tests/ -v -m "not slow"
```

### 12.2 Description of each test

#### `test_unit_model.py` — Component unit tests

| Test | What it verifies |
|---|---|
| `test_elastic_split` | Elastic matrix `C(E,ν)` is proportional to the unit form `E·Ĉ(ν)`. Catches factorisation errors in the elastic stiffness matrix. |
| `test_xi_larive_bounds` | Larive's law $\xi(t)$ returns values in $[0,1]$ and is monotonically increasing in time for any input. |
| `test_degradation_floors_and_monotonic` | With ASR active: properties at ξ=0 equal the originals; at ξ=1 they are degraded but never below the minimum floor (`E_min_factor`, etc.). |
| `test_t3_b_matrix_area` | T3 element B-matrix has shape (3×6) and the area of a reference triangle is exactly 0.5. |
| `test_q4_unit_square_jacobian` | Q4 Jacobian at the centre of a 2×2 square equals 1.0. |

#### `test_legacy_equivalence.py` — Constitutive equivalence with the beam script

| Test | What it verifies |
|---|---|
| `test_constitutive_matches_legacy` | **2000 random Gauss-point states**: the vectorised `ConstitutiveModel` of `femras` produces exactly the same stress tensor and damage as `update_damage_material()` from the original `viga_rilem.py` script, with error $< 10^{-9}$ (machine precision). This proves the refactor did not alter the beam physics. |

#### `test_presa_regression.py` — Dam regression tests

| Test | What it verifies | Mark |
|---|---|---|
| `test_linear_softening_matches_legacy` | **103 values of kappa**: the linear softening law in femras ($d = \varepsilon_f(\kappa-\varepsilon_0)\,/\,[\kappa(\varepsilon_f-\varepsilon_0)]$) matches `damage_from_kappa()` from `presa_ras.py`, including edge cases (below $\varepsilon_0$, in the softening zone, beyond $\varepsilon_f$). Error < $10^{-9}$. | fast |
| `test_dam_healthy_snapshot` | Full FEM analysis of the **healthy dam** loaded to H=100 m: crest displacement (ux ≈ 13.50 mm) and maximum damage (dmax ≈ 0.784) match values validated against `presa_ras.py` (ANIOS_RAS=0). Tolerance: ±0.6 mm in ux, ±0.06 in dmax. | `slow` |
| `test_dam_healthy_damage_monotonic` | In the healthy-dam run to H=98 m, damage is **irreversible**: it never decreases at any load step. Verifies the damage memory mechanism. | `slow` |

#### `test_viga_regression.py` — Beam regression tests

| Test | What it verifies | Reference |
|---|---|---|
| `test_beam_snapshot` | Full FEM analysis of the **notched beam** (reduced 40×10 mesh): accepted step count (41), peak load (~1600 N ±5), final damage in [0.85, 0.95]. Catches any global change in beam behaviour. | Deterministic snapshot |
| `test_beam_monotonic_damage` | Beam damage is non-decreasing in every step (irreversibility). | — |

#### `test_edge_loads.py` — Edge supports/loads and time-variable loads

| Test | What it checks |
|---|---|
| `test_timefunc_*` (5) | The λ(t) multiplier: constant by default, table interpolation with end **clamping**, expression evaluation (`10*sin(2*pi*t)`), **rejection of disallowed names** (sandbox: `__import__` raises), and `expr` taking precedence over `points`. |
| `test_edge_traction_*` (3) | Consistent nodal force of `edge_traction_force`: **normal** component split half/half, **tangential** component along the edge tangent, and zero-length edge → zero force. |
| `test_nodes_on_segment_bottom_edge` | `nodes_on_segment` finds ≥2 nodes on a square's bottom edge, all with y ≈ 0 (same tolerance as `face_boundary_edges`). |
| `test_time_history_runs_and_loads_grow` | Full `time_history` run (base edge support + top-edge pressure with λ(t)=t): accepted steps > 0, finite values, non-decreasing response. |
| `test_time_history_nodal_point_load` | Nodal point force with λ(t)=t on a base-fixed square: the run converges and develops a nonzero displacement. |

### 12.3 What the reference values mean

The numerical reference values (beam P_max, dam ux and dmax at 100 m) were
extracted from direct runs of the original scripts `viga_rilem.py` and
`presa_ras.py` (kept in `examples/legacy/`) and cross-checked against the
project reference reports.

---

## 13. Troubleshooting

### `femras: command not found`

The package is not installed or the virtual environment is not active.
- Activate: `.venv\Scripts\activate` (Windows) / `source .venv/bin/activate` (macOS/Linux).
- Reinstall: `pip install -e .`

### `ModuleNotFoundError: No module named 'femras'`

You are running Python from a different environment. Check with `pip show femras`.

### The analysis ends immediately without results

Check for YAML indentation errors (YAML is whitespace-sensitive). Use
`femras validate my_case.yaml` to catch them.

### Solver convergence errors

If the solver fails (many consecutive rejections), try:
- Increasing `max_iter` (e.g. to 60).
- Switching `tangent_mode` to `elastic` or `numerical`.
- Reducing `step_initial` and `step_max`.
- Enabling `use_line_search: true`.

### `uvicorn: command not found`

You did not install the `web` extra. Run `pip install -e ".[web]"`.

### The web page does not load

- Check that the server is running (the terminal must show the Uvicorn message
  without errors).
- Make sure to navigate to exactly `http://127.0.0.1:8000` (with `http://`,
  not `https://`).
- If port 8000 is in use by another program:
  `uvicorn api.main:app --port 8001` and open `http://127.0.0.1:8001`.

---

*For the model theory (equations, parameters, constitutive laws), see
[`teoria_modelo.md`](teoria_modelo.md).*

*Para la versión en español de este manual, ver [`manual_usuario_es.md`](manual_usuario_es.md).*
