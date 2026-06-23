# M-GCECDL con regularizador de grafo experto

Este documento presenta un flujo general para incorporar un grafo experto entre variables como regularizador adicional del entrenamiento de M-GCECDL.

---

## 1. Flujo general

$$
\begin{array}{c}
\mathbf{X}_B
\\[4pt]
\downarrow
\\[4pt]
\text{M-GCECDL}
\\[4pt]
\downarrow
\\[4pt]
\text{salida fusionada}
\end{array}
\qquad
\begin{array}{c}
\hat{y}_b \quad \text{(regresion)}
\\[4pt]
\text{o}
\\[4pt]
\mathbf{p}^{fused}_b \quad \text{(clasificacion)}
\end{array}
$$

La funcion de costo original se calcula con la salida fusionada:

$$
\mathcal{L}_{base}
=
\begin{cases}
\mathcal{L}_{reg}, & \text{si la tarea es regresion} \\
\mathcal{L}_{cls}, & \text{si la tarea es clasificacion}
\end{cases}
$$

El nuevo bloque usa el grafo experto para regularizar la sensibilidad del modelo respecto a las variables de entrada:

$$
\begin{array}{ccccc}
\mathbf{x}_b
& \longrightarrow &
f_{\theta}(\mathbf{x}_b)
& \longrightarrow &
\mathbf{a}_b
\\
\text{variables}
&&
\text{prediccion}
&&
\text{sensibilidad por variable}
\end{array}
$$

Luego la sensibilidad $\mathbf{a}_b$ se compara con la estructura del grafo experto:

$$
\begin{array}{c}
\mathbf{a}_b
\\[4pt]
\downarrow
\\[4pt]
\mathcal{L}_{graph}
\end{array}
\qquad
\text{usando}
\qquad
\mathbf{A}^{*}
$$

La perdida total queda:

$$
\boxed{
\mathcal{L}_{total}
=
\mathcal{L}_{base}
+
\lambda_{graph}\mathcal{L}_{graph}
}
$$

---

## 2. Grafo experto

Sea:

$$
\mathbf{A}^{*} \in \mathbb{R}^{d \times d}
$$

la matriz de adyacencia experta entre variables, donde $d$ es el numero total de variables de entrada.

Cada entrada:

$$
A^{*}_{ij}
$$

representa la relacion experta entre la variable $i$ y la variable $j$.

El grado de cada variable se define como:

$$
D^{*}_{ii}
=
\sum_{j=1}^{d}
A^{*}_{ij}
$$

y el Laplaciano experto como:

$$
\mathbf{L}^{*}
=
\mathbf{D}^{*}
-
\mathbf{A}^{*}
$$

---

## 3. Sensibilidad del modelo

Para regresion, sea:

$$
f_{\theta}(\mathbf{x}_b)
=
\hat{y}_b
$$

La sensibilidad de la prediccion respecto a las variables se define como:

$$
\mathbf{a}_b
=
\left|
\nabla_{\mathbf{x}_b}
\hat{y}_b
\right|
$$

Es decir:

$$
a_{b,i}
=
\left|
\frac{\partial \hat{y}_b}{\partial x_{b,i}}
\right|
$$

Para clasificacion, una opcion natural es usar la probabilidad fusionada de la clase verdadera:

$$
f_{\theta}(\mathbf{x}_b)
=
p^{fused}_{b,y_b}
$$

y entonces:

$$
\mathbf{a}_b
=
\left|
\nabla_{\mathbf{x}_b}
p^{fused}_{b,y_b}
\right|
$$

Es decir:

$$
a_{b,i}
=
\left|
\frac{
\partial p^{fused}_{b,y_b}
}{
\partial x_{b,i}
}
\right|
$$

---

## 4. Regularizador de grafo experto

La idea del regularizador es que variables conectadas por el grafo experto tengan sensibilidades compatibles.

Una forma usando el Laplaciano es:

$$
\mathcal{L}_{graph}
=
\frac{1}{B}
\sum_{b=1}^{B}
\mathbf{a}_b^{\top}
\mathbf{L}^{*}
\mathbf{a}_b
$$

Forma equivalente:

$$
\mathcal{L}_{graph}
=
\frac{1}{2B}
\sum_{b=1}^{B}
\sum_{i=1}^{d}
\sum_{j=1}^{d}
A^{*}_{ij}
\left(
a_{b,i}
-
a_{b,j}
\right)^2
$$

Interpretacion:

$$
A^{*}_{ij} \text{ alto}
\quad \Rightarrow \quad
a_{b,i} \approx a_{b,j}
$$

Es decir, si dos variables estan relacionadas segun la experticia del area, el modelo es penalizado cuando responde de forma muy diferente ante ellas.

---

## 5. Perdida total para regresion

Para regresion:

$$
\mathcal{L}_{total}^{reg}
=
\mathcal{L}_{reg}
+
\lambda_{graph}
\mathcal{L}_{graph}
$$

donde:

$$
\mathcal{L}_{reg}
=
\mathcal{L}_{fused}
+
\gamma_{sup}\mathcal{L}_{modality}
+
\gamma_{agr}\mathcal{L}_{disagreement}
+
\gamma_{reg}\mathcal{L}_{KL}
$$

---

## 6. Perdida total para clasificacion

Para clasificacion:

$$
\mathcal{L}_{total}^{cls}
=
\mathcal{L}_{cls}
+
\lambda_{graph}
\mathcal{L}_{graph}
$$

donde:

$$
\mathcal{L}_{cls}
=
\mathcal{L}_{fused}
+
\gamma_{sup}\mathcal{L}_{modality}
+
\gamma_{agr}\mathcal{L}_{agreement}
+
\gamma_{reg}\mathcal{L}_{regularization}
$$

