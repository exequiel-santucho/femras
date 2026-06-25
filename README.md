# rasfem — FEM para hormigón con Reacción Álcali-Sílice (RAS / ASR)

> Herramienta MEF 2D, libre y gratuita, para estructuras de hormigón afectadas
> por la **Reacción Álcali-Sílice**. Daño escalar de tracción + expansión RAS +
> degradación de propiedades. Validada contra dos casos de referencia.

**[Español](#español)** · **[English](#english)**

---

## Español

### ¿Qué hace?

`rasfem` resuelve en 2D (estado plano) el modelo acoplado:

$$\boldsymbol{\varepsilon}_\text{mec} = \boldsymbol{\varepsilon}_\text{total} - \boldsymbol{\varepsilon}_\text{RAS}$$

$$
\boldsymbol{\sigma} = (1-d)\,\mathbf{C}(E_\text{eff},\nu)\,\boldsymbol{\varepsilon}_\text{mec}
$$

- $\boldsymbol{\varepsilon}_\text{RAS} = \xi\,\varepsilon_\text{RAS}^\infty\,[1,1,0]^\top$ — expansión impuesta por la RAS.
- $d$ — daño de tracción regularizado por energía de fractura $G_f$ y tamaño de elemento $h_e$ (objetividad de malla).
- $E$, $f_t$, $f_c$, $G_f$ se degradan con el grado de reacción $\xi(t) \in [0,1]$.

Dos casos de referencia validados numéricamente:
- **Viga entallada tipo RILEM** (Q4, tensión plana, control por desplazamiento).
- **Presa de gravedad** (T3, deformación plana, control por nivel de agua, con
  etapa opcional de 16 años de servicio RAS).

### Instalación rápida

**Paso 1 — Descargar el código**

```bash
# Con Git (recomendado):
git clone https://github.com/exequiel-santucho/femras.git
cd femras

# O descargar el ZIP desde GitHub → Code → Download ZIP
# y descomprimir en una carpeta.
```

**Paso 2 — Instalar Python 3.10+** (si no lo tenés):
https://www.python.org/downloads/ — en Windows, marcá *"Add Python to PATH"*.

**Paso 3 — Instalar el paquete**

```bash
pip install -e .                    # núcleo
pip install -e ".[web]"             # + app web local
pip install -e ".[numba]"           # + aceleración CPU con Numba JIT (opcional)
pip install -e ".[gpu]"             # + solver GPU con CuPy (opcional, ver nota)
```

> **GPU:** Requiere GPU NVIDIA con CUDA 12. Primero instalá los drivers desde
> [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx) y verificá con
> `nvidia-smi`. Después `pip install -e ".[gpu]"` instala `cupy-cuda12x`
> automáticamente. El backend GPU solo se activa automáticamente con mallas
> grandes (≥ 50 000 grados de libertad); para mallas pequeñas no hay ganancia.

**Paso 4 — Verificar**

```bash
rasfem --help
```

### Primeros pasos

```bash
# Copiar los ejemplos a una carpeta de trabajo:
rasfem examples mis_ejemplos

# Correr la viga entallada (rápido, ~10 s):
rasfem run mis_ejemplos/viga_rilem.yaml

# Correr la presa de gravedad (más lento, ~10–15 min con 16 años de RAS):
rasfem run mis_ejemplos/presa_ras.yaml
```

Los resultados (curvas, mapas de daño, tablas, JSON de resumen) se guardan en
`resultados_rasfem/<nombre>/`.

### App web local

```bash
# Requiere haber instalado: pip install -e ".[web]"
uvicorn api.main:app --reload
# Abrir en el navegador: http://127.0.0.1:8000
```

La app tiene dos modos:
- **Texto**: editá la ficha de datos como JSON y calculá.
- **Canvas**: preprocesador gráfico — dibujás la geometría (polígono o viga),
  colocás **apoyos** (en vértices o en aristas completas) y **cargas** (puntuales,
  o tracción distribuida sobre aristas) con herramientas, generás la malla
  visualmente y exportás la ficha. Las cargas pueden ser **variables en el tiempo**
  con un multiplicador λ(t) definido por tabla `(t, valor)` o por una función
  (`10*sin(2*pi*t)`). Plantillas listas: *Presa* y *Viga*.

### Resultados validados

| Caso | Magnitud | Valor (rasfem) | Valor (script legado) |
|---|---|---|---|
| Viga sana, P_max | 1511 N | ✓ | `viga_rilem.py` |
| Presa sana, nivel de fallo | ~112.5 m | ✓ | `presa_ras.py` ANIOS=0 |
| Presa RAS 16 años, nivel de fallo | ~108.8 m | < sana ✓ | `presa_ras.py` ANIOS=16 |

### Tests

```bash
pip install pytest
pytest tests/ -v          # 22 tests, ~15 s
```

22 tests cubren: equivalencia constitutiva punto-a-punto con ambos scripts
legados, regresión estructural de viga y presa, unitarios de elementos y leyes
RAS, y apoyos/cargas en aristas + cargas variables en el tiempo (`test_edge_loads.py`).
Ver [docs/manual_usuario_es.md § 12](docs/manual_usuario_es.md#12-tests-de-verificación)
para la descripción detallada de cada test.

### Documentación

- **Manual de usuario (ES)**: [`docs/manual_usuario_es.md`](docs/manual_usuario_es.md)
  — instalación desde cero, instrucciones paso a paso, app web, fichas de datos,
  casos prácticos, interpretación de resultados, tests.
- **Teoría del modelo**: [`docs/teoria_modelo.md`](docs/teoria_modelo.md)
- **User manual (EN)**: [`docs/manual_usuario_en.md`](docs/manual_usuario_en.md)

---

## English

### What it does

`rasfem` solves the coupled ASR damage model in 2D (plane problems):

$$\boldsymbol{\varepsilon}_\text{mec} = \boldsymbol{\varepsilon}_\text{total} - \boldsymbol{\varepsilon}_\text{ASR}$$

$$
\boldsymbol{\sigma} = (1-d)\,\mathbf{C}(E_\text{eff},\nu)\,\boldsymbol{\varepsilon}_\text{mec}
$$

- ASR expansion, scalar tensile damage (fracture-energy regularised), and
  property degradation with the reaction extent $\xi$.

Two numerically validated reference cases:
- **Notched RILEM beam** (Q4, plane stress, displacement control).
- **Gravity dam overtopping** (T3, plane strain, water-level control, optional
  16-year ASR service stage).

### Quick install

```bash
git clone https://github.com/exequiel-santucho/femras.git
cd femras
pip install -e .
pip install -e ".[web]"       # local web app
pip install -e ".[numba]"     # optional CPU JIT (Numba)
pip install -e ".[gpu]"       # optional GPU solver (see note)
```

> **GPU:** Requires an NVIDIA GPU with CUDA 12. First install the drivers from
> [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx) and verify
> with `nvidia-smi`. Then `pip install -e ".[gpu]"` installs `cupy-cuda12x`
> automatically. The GPU backend activates automatically only for large meshes
> (≥ 50 000 DOF); there is no benefit for small meshes.

Python 3.10+ required. On Windows, tick *"Add Python to PATH"* during install.

### Quickstart

```bash
rasfem examples my_examples
rasfem run my_examples/viga_rilem.yaml    # beam (~10 s)
rasfem run my_examples/presa_ras.yaml     # dam  (~10–15 min with RAS service)
```

### Local web app

```bash
uvicorn api.main:app --reload
# Open http://127.0.0.1:8000
```

Two modes: **Text** (edit config as JSON, run) and **Canvas** (graphical
geometry editor — draw polygon or beam, place supports (on vertices or whole
edges) and loads (point, or distributed edge traction), preview mesh, export to
config). Loads can be **time-variable** via a λ(t) multiplier given by a
`(t, value)` table or a function (`10*sin(2*pi*t)`). Starter templates: *Dam* and
*Beam*.

### Tests

```bash
pytest tests/ -v     # 22 tests, ~15 s
```

See [docs/manual_usuario_en.md](docs/manual_usuario_en.md) for full documentation.

---

## License

MIT — see [`LICENSE`](LICENSE) for the full text.

> **Disclaimer:** This software is provided as-is for research and educational
> purposes. The authors and contributors accept no liability for any results
> produced by the tool or for decisions made on their basis. All responsibility
> rests with the user. See [`LICENSE`](LICENSE) for the complete disclaimer in
> English and Spanish.
