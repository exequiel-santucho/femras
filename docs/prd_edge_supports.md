# PRD — Apoyos sobre aristas completas del polígono

**Proyecto:** femras — herramienta FEM 2D para hormigón con RAS/ASR  
**Repositorio:** https://github.com/exequiel-santucho/femras  
**Fecha:** 2026-06-12  
**Estado:** ✅ Implementado (2026-06-25)

> **Nota de implementación (2026-06-25).** Este PRD se implementó completo y,
> además, se extendió el alcance con **cargas variables en el tiempo**:
> - `config.EdgeSupportCfg` + `Config.edge_supports`, y `mesh.polygon.nodes_on_segment`
>   tal como se especifica abajo.
> - La resolución de apoyos para polígonos se centralizó en
>   `run._resolve_polygon_support_dofs` (aristas → si vacío, fallback `base_nodes`;
>   luego apoyos puntuales `Config.supports`), usada por `_run_dam` y por el nuevo
>   driver `_run_time_history`.
> - **Más allá del PRD original:** `EdgeLoadCfg` (tracción distribuida normal+tangencial),
>   `NodalLoadCfg` (fuerza puntual por nodo más cercano), `TimeFunctionCfg` (multiplicador
>   λ(t) por tabla `[t,valor]` o expresión segura tipo `10*sin(2*pi*t)`) y el modo de
>   carga `TimeHistoryLoad` (`mode: time_history`). Ver el manual de usuario § 7.4b y § 7.5.
> - El canvas web ganó las herramientas **Apoyo en arista (G)** y **Carga en arista (B)**,
>   el editor de carga nodal con λ(t), y exporta `supports`, `edge_supports` y
>   `time_history` (antes la herramienta de carga era solo visual).
> - Cobertura: `tests/test_edge_loads.py` (10 tests); suite total **22 tests** en verde.

---

## 1. Contexto y motivación

### Estado actual

femras permite resolver dos tipos de análisis:

| Tipo | Geometría | Condiciones de borde actuales |
|---|---|---|
| Viga RILEM | `BeamGeometry` (Q4) | 2 nodos de apoyo calculados automáticamente a partir de `support_span` |
| Presa de gravedad | `PolygonGeometry` (T3) | **Todos** los nodos con y = 0 empotrados, calculado automáticamente en `_run_dam` |

En ambos casos las condiciones de borde están **hardcodeadas** en los drivers de `run.py` y no provienen del config ni del canvas. El campo `supports: List[SupportCfg]` definido en el schema de `Config` existe pero **no es utilizado** por ningún driver.

El canvas web sí permite colocar apoyos sobre **vértices** del polígono, pero esa información (`_canvas_supports`) tampoco se usa en el backend.

### Problema

Para un polígono arbitrario dibujado por el usuario en el canvas, las condiciones de borde son específicas de cada problema y no pueden inferirse automáticamente de la geometría. El usuario necesita poder designar **aristas completas** del polígono como zonas de apoyo, de modo que todos los nodos de la malla que caigan sobre esa arista reciban la misma condición de borde.

Esto es análogo a la funcionalidad de **cara hidráulica** (ya implementada): el usuario selecciona una arista del polígono y el backend encuentra todos los nodos de la malla sobre esa arista usando `face_boundary_edges`.

---

## 2. Objetivo

Permitir que el usuario defina condiciones de contorno de desplazamiento (apoyos) sobre **aristas completas** del polígono, tanto desde el canvas web como desde el archivo de configuración YAML/JSON. Todos los nodos de la malla que pertenezcan a la arista designada recibirán la misma condición de borde.

---

## 3. Requisitos funcionales

### 3.1 Interfaz de usuario — Canvas web

#### Herramienta de apoyo sobre aristas

- El usuario activa el modo apoyo (herramienta `SUPPORT`) y hace clic en una **arista** del polígono (no en un vértice).
- Al pasar el cursor sobre una arista (hover), ésta se resalta con el color de apoyos (`--support-col`, amarillo).
- Al hacer clic, la arista queda marcada como zona de apoyo con el tipo activo (`fixed`, `roller_x`, `roller_y`).
- El canvas renderiza símbolos de apoyo **a lo largo de toda la arista** (no solo en los extremos).
- Si se hace clic nuevamente sobre la misma arista con el mismo tipo, el apoyo se elimina (toggle).
- Una arista puede tener a lo más un tipo de apoyo. Reasignar un tipo diferente reemplaza el anterior.

#### Coexistencia con apoyos en vértices

- Los apoyos en vértices individuales (comportamiento existente) se conservan.
- Si una arista tiene apoyo y además alguno de sus vértices tiene apoyo individual, prevalece el más restrictivo (la condición más fija).
- En la práctica, se recomienda usar uno u otro modo, no ambos sobre el mismo vértice.

#### Inspector de propiedades

- Al seleccionar una arista con apoyo, el inspector muestra: longitud, tipo de apoyo, número estimado de nodos afectados.

#### Exportación a JSON

La arista de apoyo se exporta como un nuevo campo `edge_supports` en `loading` del JSON (ver sección 3.3).

### 3.2 Backend — Schema de configuración (`femras/config.py`)

Agregar el modelo:

```python
class EdgeSupportCfg(BaseModel):
    """Condición de borde aplicada a todos los nodos sobre el segmento [p1, p2]."""
    vertices: List[List[float]]   # [[x1, y1], [x2, y2]]
    fix_x: bool = True
    fix_y: bool = True
    # Equivalencias semánticas:
    #   fix_x=True,  fix_y=True  → empotrado (fixed)
    #   fix_x=False, fix_y=True  → rodillo en X libre (roller_x)
    #   fix_x=True,  fix_y=False → rodillo en Y libre (roller_y)
```

Extender `Config`:

```python
class Config(BaseModel):
    ...
    supports:      List[SupportCfg]     = Field(default_factory=list)  # nodos puntuales (existente)
    edge_supports: List[EdgeSupportCfg] = Field(default_factory=list)  # aristas (nuevo)
```

### 3.3 Backend — Driver `_run_dam` (`femras/run.py`)

**Lógica de resolución de condiciones de borde para `PolygonGeometry`:**

```
Si cfg.edge_supports no está vacío:
    Para cada EdgeSupportCfg:
        nodos = face_boundary_edges(nodes, elements, p1, p2)  # nodos en la arista
        Aplicar fix_x y fix_y a todos esos nodos

    (NO aplicar base_nodes automáticamente)

Si cfg.edge_supports está vacío:
    Comportamiento actual: base_nodes(nodes, y_base=0.0) → todos empotrados
    (compatibilidad con ejemplos existentes: viga_rilem.yaml, presa_ras.yaml)
```

**Nodos puntuales adicionales** (campo `supports` existente):

```
Para cada SupportCfg en cfg.supports:
    nodo = nearest_node(nodes, [x, y])
    Aplicar fix_x y fix_y a ese nodo
```

Los apoyos puntuales se procesan **después** de los de arista, pudiendo sobreescribir DOFs individuales.

### 3.4 Backend — Función auxiliar de nodos sobre arista

Usar la función `face_boundary_edges` ya existente (`femras/mesh/polygon.py`) para encontrar los nodos de la malla sobre cada arista. Los nodos relevantes son los endpoints únicos de las aristas de contorno sobre el segmento.

```python
def nodes_on_segment(nodes, elements, p1, p2, tol=None) -> np.ndarray:
    """Índices únicos de nodos de la malla que caen sobre el segmento [p1, p2]."""
    edges = face_boundary_edges(nodes, elements, p1, p2, tol)
    if not edges:
        return np.array([], dtype=int)
    return np.unique(np.array(edges).ravel())
```

### 3.5 Compatibilidad hacia atrás

- Los archivos YAML existentes (`presa_ras.yaml`, `viga_rilem.yaml`) **no tienen** `edge_supports`, por lo que el comportamiento actual se mantiene sin cambios.
- Los tests de regresión (11 tests) deben seguir pasando sin modificación.

---

## 4. Requisitos no funcionales

- **Tolerancia geométrica**: la función `nodes_on_segment` debe usar la misma tolerancia relativa que `face_boundary_edges` (1 × 10⁻⁴ × longitud de la arista, mínimo 1 × 10⁻⁷ mm), robusta frente a imprecisiones de la malla Delaunay.
- **Rendimiento**: la búsqueda de nodos sobre aristas es O(|aristas de contorno|) y no impacta perceptiblemente el tiempo total de análisis.
- **UX**: el hover sobre aristas debe distinguirse visualmente del hover sobre vértices para evitar ambigüedad.

---

## 5. Casos de uso ilustrativos

### Caso A — Presa con base empotrada (equivalente al comportamiento actual)

El usuario dibuja el polígono de la presa y selecciona la arista inferior (P1–P2, y = 0) con apoyo `fixed`. El backend empotra todos los nodos de la malla sobre esa arista. Resultado idéntico al driver actual.

### Caso B — Muro de contención con base y cara lateral empotradas

El usuario dibuja un rectángulo y selecciona:
- Arista inferior → `fixed`
- Arista izquierda → `fixed`

Los nodos en ambas aristas quedan empotrados. El resto del contorno está libre.

### Caso C — Estructura con rodillo en la base

El usuario selecciona la arista inferior con `roller_x` (fix_y = True, fix_x = False): todos los nodos de la base pueden desplazarse horizontalmente pero no verticalmente. Útil para modelar fricción nula o deslizamiento.

### Caso D — Combinación arista + vértice puntual

Una arista tiene `roller_x`. Un vértice en una esquina tiene apoyo `fixed` adicional (para eliminar el modo rígido de cuerpo en X). Los DOFs del vértice esquina quedan completamente fijos; el resto de la arista solo fija Y.

---

## 6. Archivos a modificar

| Archivo | Cambio |
|---|---|
| `femras/config.py` | Agregar `EdgeSupportCfg`; agregar `edge_supports` a `Config` |
| `femras/mesh/polygon.py` | Agregar `nodes_on_segment(nodes, elements, p1, p2)` |
| `femras/run.py` | Actualizar `_run_dam` para procesar `cfg.edge_supports`; mantener fallback `base_nodes` si vacío |
| `web/editor.js` | Extender `TOOL.SUPPORT` para detectar clic sobre arista; guardar `poly.edgeSupports = []`; renderizar símbolos sobre arista; exportar `edge_supports` en el JSON |
| `web/style.css` | Estilos para arista de apoyo resaltada (opcional, reusar colores existentes) |
| `web/index.html` | Sin cambios estructurales (la herramienta SUPPORT ya existe en la paleta) |

---

## 7. Criterios de aceptación

1. El usuario puede hacer clic sobre una arista del polígono en el canvas (no en un vértice) y asignarle un tipo de apoyo.
2. El canvas muestra símbolos de apoyo distribuidos a lo largo de la arista seleccionada.
3. El JSON exportado contiene `edge_supports` con las coordenadas exactas de los vértices de la arista y los flags `fix_x`, `fix_y`.
4. Al correr el análisis con ese JSON, todos los nodos de la malla sobre la arista tienen sus DOFs correspondientes fijos.
5. El switch de idioma (ES/EN) traduce correctamente los tooltips/labels de la herramienta de apoyo en arista.
6. Los 11 tests de regresión existentes pasan sin cambios.
7. El análisis de la presa con `edge_supports: []` (campo vacío o ausente) produce resultados idénticos a los actuales (fallback a `base_nodes`).

---

## 8. Fuera de alcance (para este PRD)

- Condiciones de contorno de **fuerza** sobre aristas (ya cubierto por la cara hidráulica y la herramienta de carga puntual).
- Apoyos con **resorte** (spring support), es decir, rigidez finita en lugar de desplazamiento impuesto cero.
- Apoyos **inclinados** (en una dirección oblicua que no sea X o Y).
- Soporte de apoyos en aristas para el modo `BeamGeometry` (la viga RILEM usa una formulación específica de tres puntos que no se modifica).
