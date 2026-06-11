# Modelo / Model — RAS + daño escalar

*(ES y EN en el mismo documento.)*

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
- Elementos lineales: cuadrilátero **Q4** (2×2 Gauss) o triángulo **T3** (1 Gauss).
- **Daño escalar isótropo**, principalmente de tracción. Daño de compresión
  opcional (desactivado por defecto).
- Pequeñas deformaciones.

## 3. Ley constitutiva / Constitutive law

La deformación total se descompone en parte mecánica y parte de RAS:

$$\boldsymbol{\varepsilon}_\text{total} = \boldsymbol{\varepsilon}_\text{mec} + \boldsymbol{\varepsilon}_\text{RAS}, \qquad \boldsymbol{\varepsilon}_\text{mec} = \boldsymbol{\varepsilon}_\text{total} - \boldsymbol{\varepsilon}_\text{RAS}$$

La tensión se calcula **solo** con la deformación mecánica y un escalar de daño
$d \in [0,1]$:

$$\boldsymbol{\sigma} = (1-d)\,\mathbf{C}(E_\text{eff},\nu)\,\boldsymbol{\varepsilon}_\text{mec}$$

donde $\mathbf{C}$ es la matriz elástica lineal (tensión o deformación plana) y
$E_\text{eff}$ el módulo degradado por la RAS (sección 5).

## 4. Expansión por RAS / ASR expansion

La RAS introduce una deformación impuesta isótropa en el plano, análoga a una
deformación térmica:

$$\boldsymbol{\varepsilon}_\text{RAS} = \xi\,\varepsilon_\text{RAS}^\infty\begin{bmatrix}1\\1\\0\end{bmatrix}$$

- $\xi(t) \in [0,1]$ es el **grado de avance** de la reacción.
- $\varepsilon_\text{RAS}^\infty$ es la deformación lineal última, calculada como
  `expansion_scale × eps_inf_vol / linear_divisor` (por hipótesis isótropa,
  `linear_divisor = 3`).

### Ley temporal de $\xi$ / temporal law

**Larive (sigmoide):**

$$\xi(t) = \frac{1 - \exp(-t/\tau_\text{ch})}{1 + \exp\left(-\dfrac{t - \tau_\text{lat}}{\tau_\text{ch}}\right)}$$

con $\tau_\text{lat}$ (tiempo de latencia) y $\tau_\text{ch}$ (tiempo característico).

**Exponencial simple:** $\xi(t) = 1 - \exp(-t/\tau)$.

También puede **imponerse** $\xi$ directamente (`mode: imposed`).

## 5. Degradación de propiedades / Property degradation

Las propiedades evolucionan con la actividad $a(\xi) = \xi^p$ (por defecto $p=1$):

$$\begin{aligned}
E_\text{eff} &= \max\bigl(E_0\,(1-\beta_E\,a),\; E_0\,f_{E,\min}\bigr) \\
f_{t,\text{eff}} &= \max\bigl(f_{t0}\,(1-\beta_{ft}\,a),\; f_{t0}\,f_{ft,\min}\bigr) \\
f_{c,\text{eff}} &= \max\bigl(f_{c0}\,(1-\beta_{fc}\,a),\; f_{c0}\,f_{fc,\min}\bigr) \\
G_{f,\text{eff}} &= \max\bigl(G_{f0}\,(1-\beta_{Gf}\,a),\; G_{f0}\,f_{Gf,\min}\bigr)
\end{aligned}$$

Los coeficientes $\beta_E, \beta_{ft}, \beta_{fc}, \beta_{Gf}$ son **calibrables**;
los pisos $f_{E,\min}, f_{ft,\min}, \ldots$ evitan valores no físicos.

## 6. Daño y regularización / Damage and regularisation

Daño de tracción exponencial gobernado por una variable de historia $\kappa$
(deformación equivalente de tracción máxima alcanzada):

$$\begin{aligned}
\varepsilon_0 &= \frac{f_{t,\text{eff}}}{E_\text{eff}} \\
\varepsilon_f &= \frac{G_{f,\text{eff}}}{f_{t,\text{eff}}\,h_e} \\
d &= 1 - \frac{\varepsilon_0}{\kappa}\exp\left(-\frac{\kappa - \varepsilon_0}{\varepsilon_f - \varepsilon_0}\right), \qquad \kappa > \varepsilon_0
\end{aligned}$$

La presencia de $h_e$ (longitud característica del elemento) en $\varepsilon_f$ es la
**regularización por energía de fractura**: hace que la energía disipada sea
aproximadamente independiente del tamaño de malla (objetividad de malla). El daño
es **irreversible** ($d$ no decrece).

La deformación equivalente de tracción se obtiene de las deformaciones
principales $e_1, e_2$:

$$\tilde{\varepsilon}_t = \sqrt{\langle e_1\rangle^2 + \langle e_2\rangle^2}, \qquad \langle x\rangle = \max(x,0)$$

## 7. Expansión libre inicial / Initial free expansion (vigas)

Para una RAS uniforme en una pieza no restringida (viga), se inicia el análisis
con un campo de desplazamientos de **expansión libre**:

$$u_x = \varepsilon_\text{RAS}\,(x - x_\text{ref}), \qquad u_y = \varepsilon_\text{RAS}\,(y - y_\text{ref})$$

de modo que $\boldsymbol{\varepsilon}_\text{mec} \approx \mathbf{0}$ y **no aparecen tensiones artificiales** al
comenzar el ensayo mecánico. En sólidos restringidos (presa, base empotrada) la
expansión se equilibra contra la coacción y genera tensiones reales, por lo que
no se usa este truco.

## 8. Solución no lineal / Nonlinear solution

- **Newton-Raphson** por paso, con matriz tangente:
  `numerical_hybrid` (elástica donde está sano, numérica donde hay daño),
  `numerical`, `secant` o `elastic`.
- **Line search** opcional para robustez.
- **Paso adaptativo**: crece si la convergencia es buena, se reduce y reintenta
  si falla.
- **Control**:
  - *desplazamiento* (viga): se impone $u$ y se recupera la carga $P$ de la
    reacción; permite capturar la rama de ablandamiento post-pico.
  - *carga / nivel de agua* (presa): se escala la fuerza externa (peso propio +
    empuje hidrostático); bajo control de carga la solución **no puede pasar el
    pico**, por lo que el último nivel convergido es el nivel de fallo.

## 9. Referencias del repositorio / Repository references

- Scripts originales validados: `examples/legacy/viga_rilem.py`,
  `examples/legacy/presa_ras.py`.
- Documento base del modelo: `referencias/Desarrollo de un Modelo MEF ... (RAS).pdf`.
