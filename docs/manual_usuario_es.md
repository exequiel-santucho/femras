# Manual de usuario — rasfem (Español)

> Herramienta MEF 2D para hormigón afectado por Reacción Álcali-Sílice (RAS/ASR).
> Versión 0.1.0 · Licencia MIT · Gratuita y de código abierto.

---

## Contenido

1. [¿Qué hace esta herramienta?](#1-qué-hace-esta-herramienta)
2. [Requisitos previos](#2-requisitos-previos)
3. [Descargar el código](#3-descargar-el-código)
4. [Instalar Python y el paquete](#4-instalar-python-y-el-paquete)
5. [Primera corrida — línea de comandos](#5-primera-corrida--línea-de-comandos)
6. [App web local](#6-app-web-local)
7. [La ficha de datos (archivo YAML)](#7-la-ficha-de-datos-archivo-yaml)
8. [Caso práctico 1 — Viga entallada (RILEM)](#8-caso-práctico-1--viga-entallada-rilem)
9. [Caso práctico 2 — Presa de gravedad (overtopping)](#9-caso-práctico-2--presa-de-gravedad-overtopping)
10. [Interpretación de resultados](#10-interpretación-de-resultados)
11. [Rendimiento y backends de cómputo](#11-rendimiento-y-backends-de-cómputo)
12. [Tests de verificación](#12-tests-de-verificación)
13. [Resolución de problemas frecuentes](#13-resolución-de-problemas-frecuentes)

---

## 1. ¿Qué hace esta herramienta?

`rasfem` resuelve problemas planos de elementos finitos (MEF 2D) para estructuras
de hormigón afectadas por la **Reacción Álcali-Sílice (RAS)**. El modelo incluye:

- **Expansión impuesta** por la RAS: $\boldsymbol{\varepsilon}_\text{RAS} = \xi\,\varepsilon_\text{RAS}^\infty\,[1,\,1,\,0]^\top$
- **Daño de tracción** regularizado por energía de fractura (objetividad de malla).
- **Degradación de propiedades** mecánicas (E, ft, fc, Gf) con el grado de reacción ξ.
- **Dos casos de referencia validados**: viga entallada tipo RILEM y presa de gravedad.

Los resultados de rasfem reproducen numéricamente los scripts de investigación
originales (`viga_rilem.py` y `presa_ras.py`) y están cubiertos por una suite
de tests automáticos (ver [Sección 12](#12-tests-de-verificación)).

---

## 2. Requisitos previos

### 2.1 Python

Necesitás **Python 3.10 o más reciente**.

Para verificar si ya lo tenés instalado, abrí una terminal y escribí:

```
python --version
```

Si el resultado es `Python 3.10.x` o superior, seguí al paso siguiente.
Si dice "no se reconoce el comando" o muestra una versión menor a 3.10, descargá
el instalador desde **https://www.python.org/downloads/** (elegí la versión más
reciente estable). Durante la instalación en Windows, marcá la casilla
**"Add Python to PATH"** antes de hacer clic en *Install Now*.

> **¿Cómo abrir la terminal?**
> - **Windows**: presioná `Win + R`, escribí `cmd` y Enter. O buscá "Símbolo del
>   sistema" en el menú Inicio. También podés usar PowerShell o la terminal de
>   VS Code.
> - **macOS**: abrí la app *Terminal* (buscala con Spotlight: `Cmd + Espacio`,
>   escribí "Terminal").
> - **Linux**: buscá *Terminal* en el menú de aplicaciones.

### 2.2 Git (opcional pero recomendado)

Git te permite descargar el código y mantenerlo actualizado fácilmente.
Para verificar: `git --version`.
Si no lo tenés, descargalo desde **https://git-scm.com/downloads**.

Si preferís no usar Git, en la [Sección 3](#3-descargar-el-código) hay una
alternativa para descargar el código como archivo ZIP.

### 2.3 Conexión a internet (solo para la instalación)

Se necesita conexión para descargar el código y las dependencias. Una vez
instalado, `rasfem` funciona completamente sin internet.

---

## 3. Descargar el código

Hay dos formas de obtener el código. Elegí la que te resulte más cómoda.

### Opción A — Descargar como archivo ZIP (sin Git)

1. Abrí el repositorio en el navegador:
   `https://github.com/exequiel-santucho/rasfem`
2. Hacé clic en el botón verde **"Code"** → **"Download ZIP"**.
3. Descomprimí el archivo en una carpeta de tu elección, por ejemplo:
   - Windows: `C:\rasfem\`
   - macOS/Linux: `~/rasfem/`
4. La carpeta descomprimida debe contener archivos como `pyproject.toml`,
   `README.md` y una subcarpeta `rasfem/`.

### Opción B — Clonar con Git (recomendado)

Abrí una terminal, navegá a la carpeta donde querés guardar el proyecto y
ejecutá:

```bash
git clone https://github.com/exequiel-santucho/rasfem.git
cd rasfem
```

Con Git podés actualizar el código más adelante con un simple:

```bash
git pull
```

---

## 4. Instalar Python y el paquete

### 4.1 Navegar a la carpeta del proyecto

Abrí una terminal y entrá a la carpeta donde descargaste/clonaste el código.
Si no sabés navegar en la terminal:

```bash
# Windows (reemplazá la ruta):
cd C:\rasfem

# macOS/Linux:
cd ~/rasfem
```

Podés verificar que estás en la carpeta correcta ejecutando `dir` (Windows) o
`ls` (macOS/Linux). Deberías ver `pyproject.toml` en la lista.

### 4.2 Crear un entorno virtual (recomendado)

Un entorno virtual evita conflictos con otros paquetes Python en tu computadora.
Es opcional pero buena práctica:

```bash
# Crear el entorno (solo la primera vez):
python -m venv .venv

# Activarlo:
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
```

Cuando el entorno está activo, el prompt de la terminal muestra `(.venv)` al
principio. Para desactivarlo: `deactivate`.

### 4.3 Instalar el núcleo

Con el entorno activo (o sin él, si preferís instalar globalmente):

```bash
pip install -e .
```

Este comando instala `rasfem` con sus dependencias base: numpy, scipy,
matplotlib, pydantic, pyyaml.

Verificá que la instalación fue exitosa:

```bash
rasfem --help
```

Deberías ver algo como:
```
usage: rasfem [-h] {run,examples,validate} ...
```

### 4.4 Extras opcionales

```bash
# Aceleración CPU con Numba (JIT — análisis más rápidos):
pip install -e ".[numba]"

# App web local (necesaria para la interfaz gráfica):
pip install -e ".[web]"

# Solver lineal en GPU (solo útil con mallas muy grandes, requiere GPU NVIDIA):
pip install -e ".[gpu]"

# Todo junto:
pip install -e ".[numba,web,gpu]"
```

---

## 5. Primera corrida — línea de comandos

Asegurate de estar en la carpeta `rasfem/` con el entorno activo.

### 5.1 Copiar los ejemplos a una carpeta de trabajo

```bash
rasfem examples mis_ejemplos
```

Esto crea la carpeta `mis_ejemplos/` con los archivos de configuración de los
dos casos de referencia.

### 5.2 Correr el ejemplo de la viga

```bash
rasfem run mis_ejemplos/viga_rilem.yaml
```

Durante el análisis verás el progreso en pantalla (paso, control, carga, daño).
Al terminar, los resultados se guardan en `resultados_rasfem/viga_rilem/`:

```
resultados_rasfem/
  viga_rilem/
    resumen.json          <- pico de carga, daño máximo, parámetros del análisis
    curva.csv             <- tabla paso a paso (desplazamiento, carga)
    curva.png             <- gráfico carga-desplazamiento
    mapa_dano.png         <- mapa de daño sobre la malla
    mapa_sigma_x.png      <- tensión horizontal
    tabla_incremental.csv <- detalle de convergencia por paso
```

### 5.3 Correr el ejemplo de la presa

```bash
rasfem run mis_ejemplos/presa_ras.yaml
```

Este análisis es más largo (malla más grande, etapa de servicio RAS).
Los resultados quedan en `resultados_rasfem/presa_ras/`.

### 5.4 Validar una configuración sin correr

```bash
rasfem validate mis_ejemplos/viga_rilem.yaml
```

Imprime todos los parámetros del análisis resueltos con sus valores por defecto,
útil para verificar que el archivo YAML está bien escrito.

### 5.5 Elegir el backend de cómputo (numpy / numba / gpu)

El backend controla cómo se resuelve el sistema lineal y se ensambla la matriz
de rigidez. Se configura **dentro del archivo YAML**, en la sección `solver`:

```yaml
solver:
  backend: numpy    # opciones: numpy | numba | gpu | auto
```

| Backend | Cuándo usarlo | Requisito extra |
|---|---|---|
| `numpy` | Siempre disponible. Para pruebas y mallas pequeñas. | Ninguno |
| `numba` | Análisis largos en PC de escritorio (ensamblaje JIT paralelo). Primera corrida tarda ~2 s extra en compilar. | `pip install -e ".[numba]"` |
| `gpu` | Mallas muy grandes (≥ 50 000 GDL). Sin malla grande no hay ganancia. | GPU NVIDIA + CUDA 12, luego `pip install -e ".[gpu]"` |
| `auto` | Detecta automáticamente el mejor disponible (gpu si hay malla grande + CuPy, si no numba, si no numpy). | — |

**¿Cómo cambiar el backend de un ejemplo sin editar el YAML original?**

Copiá el archivo y modificá solo la línea del backend:

```bash
# Copiar el ejemplo de la viga
copy mis_ejemplos\viga_rilem.yaml mis_ejemplos\viga_numba.yaml
```

Abrí `mis_ejemplos/viga_numba.yaml` con cualquier editor de texto y cambiá o
agregá al final:

```yaml
solver:
  backend: numba
```

Luego corré normalmente:

```bash
rasfem run mis_ejemplos/viga_numba.yaml
```

> **Tip:** `backend: auto` es la opción más práctica para uso diario — usará
> lo mejor disponible sin que tengas que recordar qué instalaste.

---

## 6. App web local

La interfaz web permite configurar y ejecutar análisis desde el navegador,
sin escribir código ni usar la terminal (excepto para arrancarla).

### 6.1 Requisitos

Asegurate de haber instalado el extra `[web]`:

```bash
pip install -e ".[web]"
```

### 6.2 Levantar el servidor

Desde la carpeta del proyecto, con el entorno virtual activo:

```bash
uvicorn api.main:app --reload
```

Verás un mensaje como:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [...]
```

### 6.3 Abrir en el navegador

Abrí tu navegador (Chrome, Firefox, Edge) y entrá a:

```
http://127.0.0.1:8000
```

Se cargará la interfaz de rasfem.

### 6.4 Usar la interfaz — modo Texto

El modo por defecto funciona como editor de ficha de datos:

1. **Elegir un ejemplo**: usá los botones "Ejemplo viga" o "Ejemplo presa" para
   cargar la configuración de referencia como JSON editable.
2. **Previsualizar la malla**: clic en *Previsualizar malla* para ver la
   geometría en el panel derecho antes de calcular.
3. **Calcular**: clic en *Calcular*. El análisis corre en el servidor y la
   curva de respuesta aparece interactiva en Plotly.

### 6.5 Usar la interfaz — modo Canvas (preprocesador gráfico)

Hacé clic en el botón **Canvas** (cabecera superior derecha) para activar el
editor interactivo de geometría. No necesitás escribir ningún YAML: dibujás el
modelo directamente sobre la pantalla.

#### Plantillas de arranque

Hay dos plantillas listas para usar, accesibles desde el panel izquierdo:

| Botón | Modelo | Tipo de malla |
|---|---|---|
| **Presa** | Polígono de 5 vértices (70×103 m) | T3, deformación plana |
| **Viga** | Formulario 430×105 mm + entalla | Q4, tensión plana |

#### Modo Polígono — dibujar geometría libre

Con la plantilla **Presa** activa (o haciendo clic en el canvas vacío):

| Acción | Resultado |
|---|---|
| **Clic simple** (herramienta Vértice ✦) | Agrega un vértice nuevo en esa posición |
| **Doble clic** | Cierra el polígono |
| **Arrastrar** un vértice existente | Lo mueve |
| **Delete** (teclado) | Borra el vértice seleccionado (círculo rojo) |
| Herramienta **Borrar ✕** + clic | Borra el vértice bajo el cursor |

Para agregar apoyos o cargas, elegí la herramienta correspondiente en la
paleta y hacé clic cerca del vértice donde querés colocarlos:

| Herramienta | Ícono | Tipo |
|---|---|---|
| Apoyo fijo | △ Fijo | Restringe ux y uy |
| Rodillo X | ⊿ Rod.X | Restringe ux |
| Rodillo Y | ◁ Rod.Y | Restringe uy |
| Carga puntual | ↓ Carga | Flecha en -Y (editá fx/fy en el JSON exportado) |

Parámetros ajustables en el panel:

- **Tamaño malla (mm)**: tamaño de los elementos T3. Usar 2000 para reproducir
  el caso de referencia de la presa.
- **Espesor (mm)**: dimensión fuera del plano.
- **Tipo problema**: deformación plana / tensión plana.
- **Carga hidráulica**: activa la presión de agua sobre el paramento.

#### Modo Viga — formulario paramétrico

Con la plantilla **Viga** activa, los campos del formulario controlan la
geometría de la viga rectangular:

- L, H: largo y alto (mm).
- nx, ny: divisiones de la malla Q4.
- Entalla ancho / alto: dimensiones de la entalla central.
- Vano apoyos: distancia entre los dos apoyos (mm).

El esquema esquemático (SVG) se actualiza en tiempo real al cambiar los valores.

#### Previsualizar la malla y exportar

1. **Previsualizar malla**: llama al servidor y superpone la malla generada
   (en verde) sobre el canvas. Muestra la cantidad de nodos y elementos.
2. **Exportar a Texto**: convierte el modelo dibujado a JSON y lo carga en el
   textarea del modo Texto, listo para ejecutar con el botón *Calcular*.

> **Nota**: el JSON exportado desde el canvas usa valores de material de
> referencia (hormigón típico sin RAS). Podés editarlos en el textarea antes
> de calcular para personalizar el análisis.

### 6.6 Detener el servidor

Volvé a la terminal donde iniciaste `uvicorn` y presioná `Ctrl + C`.

> **Nota sobre el servidor en red local**: si querés acceder desde otra
> computadora en la misma red, usá:
> ```bash
> uvicorn api.main:app --host 0.0.0.0 --port 8000
> ```
> y accedé con `http://<IP-de-tu-computadora>:8000`.

---

## 7. La ficha de datos (archivo YAML)

Cada análisis se define con **un archivo YAML** — la "ficha de datos". Es un
archivo de texto plano que podés abrir y editar con cualquier editor de texto
(Bloc de notas, VS Code, Notepad++, etc.).

Un archivo YAML mínimo:

```yaml
name: mi_caso

problem:
  element_type: q4
  problem_type: plane_stress
  thickness: 75.0

material:
  E0: 38100.0     # MPa
  ft0: 4.0        # MPa
  Gf0: 0.10       # N/mm

ras:
  enabled: false  # hormigón sano

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

Los campos omitidos toman sus **valores por defecto** (los del ejemplo de viga).

### 7.1 Sección `problem`

| Parámetro | Valores posibles | Descripción |
|---|---|---|
| `element_type` | `q4` / `t3` | Q4: cuadrilátero 4 nodos. T3: triángulo 3 nodos. |
| `problem_type` | `plane_stress` / `plane_strain` | Tensión plana (vigas) / deformación plana (presas). |
| `thickness` | número positivo (mm) | Espesor fuera del plano. |
| `strain_shear_factor` | `1.0` / `0.5` | 1.0 para viga (deformación ingenieril), 0.5 para presa (tensorial). |

### 7.2 Sección `material`

| Parámetro | Descripción | Unidades |
|---|---|---|
| `E0` | Módulo de Young inicial (sin RAS) | MPa |
| `nu` | Coeficiente de Poisson | — |
| `ft0` | Resistencia a tracción | MPa |
| `fc0` | Resistencia a compresión | MPa |
| `Gf0` | Energía de fractura en tracción | N/mm |
| `Gc0` | Energía de fractura en compresión | N/mm |
| `damage_max` | Daño máximo permitido (0–1) | — |
| `enable_compression_damage` | `true` / `false` | Activar daño de compresión |
| `softening_law` | `exponential` / `linear` | Ley de ablandamiento post-pico |

> La ley `linear` reproduce el caso de la presa (script `presa_ras.py`).
> La ley `exponential` reproduce la viga (script `viga_rilem.py`).

### 7.3 Sección `ras`

| Parámetro | Descripción |
|---|---|
| `enabled` | `true` para activar RAS, `false` para hormigón sano |
| `mode` | `larive` (ley temporal), `simple_exp`, `imposed` (xi directo) |
| `xi_imposed` | Grado de reacción fijo (solo con `mode: imposed`) |
| `age_days` | Edad del hormigón en días (para `mode: larive`) |
| `eps_inf_vol` | Expansión volumétrica última libre |
| `beta_E` | Coeficiente de degradación del módulo E |
| `beta_ft` | Coeficiente de degradación de la resistencia a tracción |
| `E_min_factor` | Piso de E como fracción de E0 |

### 7.4 Sección `geometry`

**Viga rectangular** (elementos Q4 o T3):
```yaml
geometry:
  kind: beam
  L: 430.0        # largo [mm]
  H: 105.0        # alto [mm]
  nx: 86          # nodos en x (divisiones)
  ny: 21          # nodos en y
  notch_width: 3.0
  notch_height: 52.5
  support_span: 400.0
```

**Polígono arbitrario** (elementos T3, para presas y geometrías irregulares):
```yaml
geometry:
  kind: polygon
  vertices:
    - [0.0,      0.0]
    - [70000.0,  0.0]
    - [19200.0,  66000.0]
    - [14800.0, 103000.0]
    - [0.0,    103000.0]
  mesh_size: 2000.0   # tamaño aproximado de elemento [mm]
  height: 103000.0    # altura de referencia [mm]
```

Los vértices se listan en orden **antihorario** desde el inferior izquierdo.

### 7.5 Sección `loading`

**Control por desplazamiento** (ensayo de viga):
```yaml
loading:
  mode: displacement
  x_center: 215.0   # posición del punto de carga [mm]
  y_top: 105.0      # altura del punto de carga [mm]
  target: -0.20     # desplazamiento final [mm] (negativo = hacia abajo)
  step_initial: -0.0010
  step_min: -0.000010
  step_max: -0.0015
  grow_factor: 1.10
  shrink_factor: 0.5
  max_accepted_steps: 600
```

**Control por nivel de agua** (ensayo de presa):
```yaml
loading:
  mode: hydraulic
  gamma_c: 2.40e-5  # peso específico del hormigón [N/mm³]
  gamma_w: 9.81e-6  # peso específico del agua [N/mm³]
  h_start: 92000.0  # nivel inicial [mm]
  h_target: 120000.0
  dh_initial: 500.0
  dh_min: 20.0
  dh_max: 500.0
  max_accepted_steps: 600
```

### 7.6 Sección `service` (etapa de vida útil RAS, opcional)

Simula los años de servicio previos al ensayo de sobrecarga (solo para presas):

```yaml
service:
  service_years: 16      # 0 = presa sana; >0 = años con RAS activa
  dt_days: 3.0           # paso de tiempo [días]
  h_service_max: 92000.0 # nivel máximo anual [mm]
  h_service_min: 37000.0 # nivel mínimo anual [mm]
  xi_target: 0.70        # grado de reacción al final del período
  xi_rate: 3.0           # parámetro de forma de la curva de crecimiento de xi
```

### 7.7 Sección `solver`

```yaml
solver:
  tangent_mode: numerical_hybrid  # recomendado
  max_iter: 30
  tol_res_abs: 1.0e-3
  tol_res_rel: 1.0e-5
  use_line_search: false
  min_stiff_factor: 1.0e-6
  backend: auto
```

`tangent_mode`:
- `numerical_hybrid`: tangente elástica en elementos sin daño, numérica en
  los dañados. **Recomendado** (buena convergencia y eficiencia).
- `numerical`: tangente numérica en todos los elementos.
- `secant`: tangente secante (simple).
- `elastic`: tangente elástica siempre (más robusta, menos precisa cerca del pico).

### 7.8 Sección `output`

```yaml
output:
  dir: resultados_rasfem   # carpeta de salida
  dpi: 200                 # resolución de las figuras
  save_figures: true
  save_tables: true
```

---

## 8. Caso práctico 1 — Viga entallada (RILEM)

Este caso reproduce el ensayo de viga entallada de tres puntos descrito en la
referencia del modelo.

### 8.1 Presa sana — base de comparación

```bash
rasfem examples mis_casos
# editar mis_casos/viga_rilem.yaml: ras.enabled = false
rasfem run mis_casos/viga_rilem.yaml
```

O directamente desde la copia del ejemplo:
```bash
rasfem run examples/viga_rilem.yaml
```

Resultado esperado: carga máxima **P_max ≈ 1511 N** (viga sana con Q4, malla 86×21).

### 8.2 Efecto del envejecimiento RAS

Para estudiar cómo la RAS reduce la capacidad de la viga, podés crear varios
archivos con distintas edades:

```yaml
# viga_300dias.yaml
name: viga_300dias
ras:
  enabled: true
  mode: larive
  age_days: 300   # ~56% de reacción completada
```

```bash
rasfem run viga_300dias.yaml
```

A mayor edad (mayor ξ), mayor daño pre-existente y menor pico de carga.

### 8.3 Resultados

Los archivos generados en `resultados_rasfem/viga_rilem/`:

| Archivo | Contenido |
|---|---|
| `resumen.json` | xi, P_max, δ(P_max), dmax, nodos, elementos |
| `curva.csv` / `curva.png` | Curva P–δ completa |
| `mapa_dano.png` | Distribución espacial del daño |
| `mapa_sigma_x.png` | Tensión horizontal por elemento |

---

## 9. Caso práctico 2 — Presa de gravedad (overtopping)

Este caso reproduce la presa de gravedad del modelo de referencia. El análisis
consiste en:

1. **(Opcional) Etapa de servicio**: simula N años de vida útil con RAS
   activa y ciclos anuales de nivel de agua. El hormigón se degrada.
2. **Ensayo de sobrecarga**: desde el nivel de diseño (92 m), se sube el nivel
   del embalse hasta alcanzar el fallo estructural (overtopping).

### 9.1 Presa sana (sin RAS)

Editá el archivo para desactivar la RAS y la etapa de servicio:

```yaml
# presa_sana.yaml
name: presa_sana

ras:
  enabled: false

# service: no incluir esta sección (o poner service_years: 0)
```

O partí del ejemplo incluido y cambiá solo esas líneas.

```bash
rasfem run presa_sana.yaml
```

Resultado esperado: último nivel convergido ≈ **112.5 m** (nivel de fallo).

### 9.2 Presa con 16 años de RAS

```yaml
# presa_ras.yaml  (ya incluido en examples/)
service:
  service_years: 16
  xi_target: 0.70
```

```bash
rasfem run examples/presa_ras.yaml
```

Resultado esperado: último nivel convergido ≈ **108.8 m** — menor que la presa
sana, lo que refleja la reducción de capacidad por la RAS.

> **Tiempo de cómputo**: el análisis con 16 años de servicio ejecuta ~1950 pasos
> de Newton. Con la malla de 2 m y el backend numpy vectorizado, tarda
> del orden de **5–15 minutos** dependiendo de la PC. Con Numba instalado
> (`pip install -e ".[numba]"`) el tiempo se reduce considerablemente.

### 9.3 Parámetros clave de la presa

| Parámetro | Valor referencia | Descripción |
|---|---|---|
| `mesh_size` | 2000.0 mm | Tamaño de elemento (usar 2000 para coincidir con la referencia) |
| `softening_law` | `linear` | Ley de ablandamiento (obligatorio para la presa) |
| `strain_shear_factor` | 0.5 | Convención de corte tensorial |
| `problem_type` | `plane_strain` | Estado plano de deformaciones |
| `h_start` | 92000 mm | Nivel de embalse al inicio del ensayo |

---

## 10. Interpretación de resultados

### 10.1 Curva de respuesta (`curva.csv` / `curva.png`)

- **Viga**: eje X = desplazamiento impuesto δ (mm), eje Y = carga resultante P (N).
  El pico (P_max) marca el inicio de la localización de daño.
- **Presa**: eje X = nivel de agua H (m), eje Y = desplazamiento horizontal del
  coronamiento (mm). La curva se detiene cuando el solucionador no puede
  converger (fallo estructural).

### 10.2 Mapa de daño (`mapa_dano.png`)

Muestra la variable de daño $d \in [0,1]$ por elemento al final del análisis:
- $d \approx 0$: material intacto.
- $d \approx 1$: daño completo (fisura abierta).

En la viga, el daño debe localizarse en la punta de la entalla.
En la presa, en la zona del talón (pie aguas arriba).

### 10.3 Resumen JSON (`resumen.json`)

```json
{
  "name": "viga_rilem",
  "accepted": 55,
  "rejected": 12,
  "load_max": 1511.3,
  "control_at_load_max": -0.0672,
  "dmax_final": 0.9991,
  "xi": 0.5610,
  "n_nodes": 1827,
  "n_elements": 1680
}
```

Campos principales:

| Campo | Descripción |
|---|---|
| `accepted` / `rejected` | Pasos aceptados y rechazados por el solucionador |
| `load_max` | Carga máxima alcanzada [N] (viga) |
| `failure_level` | Último nivel convergido [mm] (presa) |
| `dmax_final` | Daño máximo en el último paso |
| `xi` | Grado de reacción RAS utilizado en el análisis |

---

## 11. Rendimiento y backends de cómputo

El núcleo de `rasfem` está **vectorizado** con NumPy: todas las operaciones de
constitutivo y ensamblaje se hacen sobre arrays, sin bucles Python por elemento.
Esto es entre **10× y 50× más rápido** que los scripts originales (que usaban
`deepcopy` por iteración y bucles por punto de Gauss).

### 11.1 Backends disponibles

| Backend | Instalación | Cuándo usar |
|---|---|---|
| `numpy` (default) | Incluido | Siempre disponible, recomendado para empezar |
| `numba` | `pip install -e ".[numba]"` | Para análisis largos en PC de escritorio |
| `gpu` | `pip install -e ".[gpu]"` | GPU NVIDIA, solo útil con > ~50 000 GDL |
| `auto` | — | Detecta automáticamente el mejor disponible |

Para seleccionar el backend, editá la ficha de datos:
```yaml
solver:
  backend: numba   # o: numpy, gpu, auto
```

### 11.2 Kernels Numba JIT (backend `numba`)

Con `pip install -e ".[numba]"`, el ensamblaje global se acelera con dos
kernels compilados en tiempo de ejecución (`@njit(parallel=True, cache=True)`):

- **`_ke_numba`**: calcula las matrices de rigidez elementales
  $\mathbf{K}_e = \sum_\text{gp} \mathbf{B}^\top \mathbf{C}_t \mathbf{B}\,w_\text{gp}$
  en paralelo sobre los elementos (`prange`), eliminando el array intermedio $\mathbf{B}^\top\mathbf{C}_t$.
- **`_fe_numba`**: calcula las fuerzas internas elementales
  $\mathbf{f}_e = \sum_\text{gp} \mathbf{B}^\top \boldsymbol{\sigma}\,w_\text{gp}$ ídem en paralelo.

El modelo constitutivo (`damage.py`) ya es NumPy vectorizado y no requiere
kernels adicionales — su cuello de botella es la tangente numérica (3
evaluaciones extra por iteración), que escala bien sin JIT.

**Primera ejecución con Numba**: la compilación JIT tarda ~1–3 segundos la
primera vez. Con `cache=True` el código compilado se guarda en `__pycache__`
y las ejecuciones siguientes arrancan sin demora.

Si `numba` no está instalado, el código cae silenciosamente a NumPy sin
ningún error.

### 11.3 Estimaciones de tiempo típicas

| Caso | Malla | Backend numpy | Backend numba |
|---|---|---|---|
| Viga RILEM (malla de referencia) | 86×21 Q4 ≈ 1680 elem. | ~10 s | ~3 s |
| Presa sana (sin servicio) | 2 m T3 ≈ 1600 elem. | ~30 s | ~8 s |
| Presa con 16 años RAS | ídem + ~1950 pasos servicio | ~10–15 min | ~2–5 min |

---

## 12. Tests de verificación

`rasfem` incluye una suite de tests automáticos que garantizan que los
resultados del núcleo refactorizado son idénticos (dentro de tolerancia
numérica) a los scripts originales de referencia.

### 12.1 Cómo correr los tests

Desde la carpeta del proyecto, con el entorno virtual activo:

```bash
# Instalar pytest (si no está):
pip install pytest

# Correr todos los tests:
pytest tests/ -v
```

Resultado esperado:
```
tests/test_legacy_equivalence.py::test_constitutive_matches_legacy  PASSED
tests/test_presa_regression.py::test_linear_softening_matches_legacy PASSED
tests/test_presa_regression.py::test_dam_healthy_snapshot           PASSED
tests/test_presa_regression.py::test_dam_healthy_damage_monotonic   PASSED
tests/test_unit_model.py::test_elastic_split                        PASSED
tests/test_unit_model.py::test_xi_larive_bounds                     PASSED
tests/test_unit_model.py::test_degradation_floors_and_monotonic     PASSED
tests/test_unit_model.py::test_t3_b_matrix_area                     PASSED
tests/test_unit_model.py::test_q4_unit_square_jacobian              PASSED
tests/test_viga_regression.py::test_beam_snapshot                   PASSED
tests/test_viga_regression.py::test_beam_monotonic_damage           PASSED

11 passed in ~15s
```

Para correr solo los tests rápidos (sin los de la presa, que tardan ~15 s):

```bash
pytest tests/ -v -m "not slow"
```

### 12.2 Descripción de cada test

#### Módulo `test_unit_model.py` — Tests unitarios de componentes

| Test | Qué verifica |
|---|---|
| `test_elastic_split` | La matriz elástica `C(E,ν)` es proporcional a la forma unitaria `E·Chat(ν)`. Detecta errores en la factorización de la matriz de rigidez elástica. |
| `test_xi_larive_bounds` | La ley de Larive $\xi(t)$ devuelve valores en $[0,1]$ y es monótona creciente en el tiempo para cualquier entrada. |
| `test_degradation_floors_and_monotonic` | Con RAS activa: a ξ=0 las propiedades son las originales; a ξ=1 están degradadas pero nunca por debajo del piso mínimo (`E_min_factor`, etc.). |
| `test_t3_b_matrix_area` | La matriz B del elemento T3 tiene forma (3×6) y el área calculada de un triángulo de referencia es 0.5 (exacto). |
| `test_q4_unit_square_jacobian` | El Jacobiano del elemento Q4 sobre un cuadrado 2×2 vale 1.0 en el punto central. |

#### Módulo `test_legacy_equivalence.py` — Equivalencia constitutiva con el script de la viga

| Test | Qué verifica |
|---|---|
| `test_constitutive_matches_legacy` | **2000 estados de punto de Gauss aleatorios**: el `ConstitutiveModel` vectorizado de `rasfem` produce exactamente el mismo tensor de tensiones y el mismo daño que la función `update_damage_material()` del script original `viga_rilem.py`, con error $< 10^{-9}$ (precisión de máquina). Esto garantiza que el refactor no alteró la física del modelo. |

#### Módulo `test_presa_regression.py` — Regresión de la presa

| Test | Qué verifica | Marca |
|---|---|---|
| `test_linear_softening_matches_legacy` | **103 valores de kappa**: la ley de ablandamiento lineal implementada en rasfem ($d = \varepsilon_f(\kappa-\varepsilon_0)\,/\,[\kappa(\varepsilon_f-\varepsilon_0)]$) coincide con la función `damage_from_kappa()` del script `presa_ras.py`, incluyendo los casos límite (por debajo de $\varepsilon_0$, en la zona de ablandamiento, y más allá de $\varepsilon_f$). Error < $10^{-9}$. | rápido |
| `test_dam_healthy_snapshot` | Análisis MEF completo de la **presa sana** cargada hasta H=100 m: el desplazamiento horizontal del coronamiento (ux ≈ 13.50 mm) y el daño máximo (dmax ≈ 0.784) coinciden con los valores validados del script `presa_ras.py` (ANIOS_RAS=0). Tolerancia: ±0.6 mm en ux, ±0.06 en dmax. | `slow` |
| `test_dam_healthy_damage_monotonic` | En el análisis de presa sana hasta H=98 m, el daño es **irreversible**: no disminuye en ningún paso de carga. Verifica que el mecanismo de "memoria" del daño funciona correctamente. | `slow` |

#### Módulo `test_viga_regression.py` — Regresión de la viga

| Test | Qué verifica | Referencia |
|---|---|---|
| `test_beam_snapshot` | Análisis MEF completo de la **viga entallada** (malla reducida 40×10): número de pasos aceptados (41), carga máxima (~1600 N ±5), y daño final en rango [0.85, 0.95]. Detecta cambios globales en el comportamiento de la viga. | Snapshot determinístico |
| `test_beam_monotonic_damage` | El daño en la viga es no decreciente en todos los pasos (irreversibilidad). | — |

### 12.3 Significado de los resultados de referencia validados

Los valores numéricos de referencia (P_max de la viga, ux y dmax de la presa a
100 m) fueron extraídos de corridas directas de los scripts originales
`viga_rilem.py` y `presa_ras.py` (incluidos en `examples/legacy/`) y verificados
contra los reportes de referencia del proyecto.

---

## 13. Resolución de problemas frecuentes

### `rasfem: command not found` / `rasfem no se reconoce`

El paquete no está instalado o el entorno virtual no está activo.
- Activá el entorno: `.venv\Scripts\activate` (Windows) / `source .venv/bin/activate` (macOS/Linux).
- Reinstalá: `pip install -e .`

### `ModuleNotFoundError: No module named 'rasfem'`

Estás corriendo Python desde fuera del entorno virtual, o instalaste rasfem en
otro entorno. Verificá con `pip show rasfem`.

### El análisis termina muy rápido sin resultados

Revisá que el archivo YAML no tenga errores de indentación (los YAML son
sensibles a los espacios). Usá `rasfem validate mi_caso.yaml` para detectarlos.

### Error de convergencia del solucionador

Si el solucionador no converge (muchos rechazos seguidos), probá:
- Aumentar `max_iter` (p.ej. a 60).
- Cambiar `tangent_mode` a `elastic` o `numerical`.
- Reducir `step_initial` y `step_max`.
- Activar `use_line_search: true`.

### `uvicorn: command not found` al levantar la web

No instalaste el extra `web`. Ejecutá `pip install -e ".[web]"`.

### La página web no carga en el navegador

- Verificá que el servidor esté corriendo (la terminal debe mostrar el mensaje
  de Uvicorn sin errores).
- Asegurate de entrar exactamente a `http://127.0.0.1:8000` (con `http://`, sin
  `s`).
- Si otro programa usa el puerto 8000, cambiá el puerto:
  `uvicorn api.main:app --port 8001` y accedé a `http://127.0.0.1:8001`.

---

*Para la teoría del modelo (ecuaciones, parámetros, leyes constitutivas), ver
[`teoria_modelo.md`](teoria_modelo.md).*

*Para la versión en inglés de este manual, ver [`manual_usuario_en.md`](manual_usuario_en.md).*
