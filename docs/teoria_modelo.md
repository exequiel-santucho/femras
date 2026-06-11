# Modelo / Model — RAS + daño escalar

*(ES y EN en el mismo documento. Las ecuaciones usan notación ASCII.)*

## 1. Objetivo / Purpose

**ES.** Representar el comportamiento mecánico de estructuras de hormigón
afectadas por la **Reacción Álcali-Sílice (RAS)** mediante el Método de los
Elementos Finitos en 2D, considerando: expansión inducida por la RAS,
degradación progresiva de propiedades, daño escalar distribuido y fractura en
modo I regularizada por energía de fractura.

**EN.** Model the mechanical behaviour of concrete structures affected by the
**Alkali-Silica Reaction (ASR/RAS)** with a 2D finite-element method, accounting
for ASR-induced expansion, progressive property degradation, distributed scalar
damage and fracture-energy-regularised mode-I fracture.

El objetivo no es ajustar exactamente un ensayo, sino ofrecer una **plataforma
numérica consistente, libre y accesible** que reproduzca las tendencias
observadas y sea fácil de usar y de extender.

## 2. Hipótesis / Assumptions

- Problema bidimensional: **tensión plana** (vigas) o **deformación plana**
  (presas / sólidos masivos).
- Elementos lineales: cuadrilátero **Q4** (2x2 Gauss) o triángulo **T3** (1 Gauss).
- **Daño escalar isótropo**, principalmente de tracción. Daño de compresión
  opcional (desactivado por defecto).
- Pequeñas deformaciones.

## 3. Ley constitutiva / Constitutive law

La deformación total se descompone en parte mecánica y parte de RAS:

```
eps_total = eps_mec + eps_RAS
eps_mec   = eps_total - eps_RAS
```

La tensión se calcula **solo** con la deformación mecánica y un escalar de daño
`d in [0,1]`:

```
sigma = (1 - d) * C(E_eff, nu) * eps_mec
```

donde `C` es la matriz elástica lineal (tensión o deformación plana) y `E_eff`
el módulo degradado por la RAS (sección 5).

## 4. Expansión por RAS / ASR expansion

La RAS introduce una deformación impuesta isótropa en el plano, análoga a una
deformación térmica:

```
eps_RAS = xi * eps_RAS_inf * [1, 1, 0]
```

- `xi(t) in [0,1]` es el **grado de avance** de la reacción.
- `eps_RAS_inf = expansion_scale * eps_inf_vol / linear_divisor` es la
  deformación lineal última (por hipótesis isótropa, `linear_divisor = 3`).

### Ley temporal de `xi` / temporal law

**Larive (sigmoide):**
```
xi(t) = (1 - exp(-t/tau_ch)) / (1 + exp(-(t - tau_lat)/tau_ch))
```
con `tau_lat` (tiempo de latencia) y `tau_ch` (tiempo característico).

**Exponencial simple:** `xi(t) = 1 - exp(-t/tau)`.

También puede **imponerse** `xi` directamente (`mode: imposed`).

## 5. Degradación de propiedades / Property degradation

Las propiedades evolucionan con la actividad `a(xi) = xi^p` (por defecto `p=1`):

```
E_eff  = max( E0  * (1 - beta_E  * a),  E0  * E_min_factor )
ft_eff = max( ft0 * (1 - beta_ft * a),  ft0 * ft_min_factor )
fc_eff = max( fc0 * (1 - beta_fc * a),  fc0 * fc_min_factor )
Gf_eff = max( Gf0 * (1 - beta_Gf * a),  Gf0 * Gf_min_factor )
```

Los `beta_*` son **calibrables**; los pisos (`*_min_factor`) evitan valores no
físicos.

## 6. Daño y regularización / Damage and regularisation

Daño de tracción exponencial gobernado por una variable de historia `kappa`
(deformación equivalente de tracción máxima alcanzada):

```
eps0 = ft_eff / E_eff                      (umbral de inicio)
epsf = Gf_eff / (ft_eff * h_e)             (controla la rama de ablandamiento)
d    = 1 - (eps0/kappa) * exp(-(kappa - eps0)/(epsf - eps0))   para kappa > eps0
```

La presencia de `h_e` (longitud característica del elemento) en `epsf` es la
**regularización por energía de fractura**: hace que la energía disipada sea
aproximadamente independiente del tamaño de malla (objetividad de malla). El daño
es **irreversible** (`d` no decrece).

La deformación equivalente de tracción se obtiene de las deformaciones
principales `e1, e2`:
```
eps_eq_t = sqrt( <e1>^2 + <e2>^2 ),   <x> = max(x, 0)
```

## 7. Expansión libre inicial / Initial free expansion (vigas)

Para una RAS uniforme en una pieza no restringida (viga), se inicia el análisis
con un campo de desplazamientos de **expansión libre**:
```
u_x = eps_RAS * (x - x_ref),   u_y = eps_RAS * (y - y_ref)
```
de modo que `eps_mec ~= 0` y **no aparecen tensiones artificiales** al comenzar
el ensayo mecánico. En sólidos restringidos (presa, base empotrada) la expansión
se equilibra contra la coacción y genera tensiones reales, por lo que no se usa
este truco.

## 8. Solución no lineal / Nonlinear solution

- **Newton-Raphson** por paso, con matriz tangente:
  `numerical_hybrid` (elástica donde está sano, numérica donde hay daño),
  `numerical`, `secant` o `elastic`.
- **Line search** opcional para robustez.
- **Paso adaptativo**: crece si la convergencia es buena, se reduce y reintenta
  si falla.
- **Control**:
  - *desplazamiento* (viga): se impone `u` y se recupera la carga `P` de la
    reacción; permite capturar la rama de ablandamiento post-pico.
  - *carga / nivel de agua* (presa): se escala la fuerza externa (peso propio +
    empuje hidrostático); bajo control de carga la solución **no puede pasar el
    pico**, por lo que el último nivel convergido es el nivel de fallo.

## 9. Referencias del repositorio / Repository references

- Scripts originales validados: `examples/legacy/viga_rilem.py`,
  `examples/legacy/presa_ras.py`.
- Documento base del modelo: `referencias/Desarrollo de un Modelo MEF ... (RAS).pdf`.
