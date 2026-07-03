# Normalizacion de la funcion de costo M-GCECDL

Este ajuste mantiene la estructura original de la propuesta M-GCECDL, pero acota los
terminos que entran a la funcion de costo en el intervalo `[0, 1]`, con `0` como
mejor valor. La intencion es que Optuna pueda ponderar perdidas comparables sin que
un termino domine solo por escala numerica.

## Regresion

La funcion total conserva los mismos terminos:

```math
\mathcal{L}_{reg}^{total}
=
\widetilde{\mathcal{L}}_{fused}
+\gamma_{sup}\widetilde{\mathcal{L}}_{modality}
+\gamma_{agr}\widetilde{\mathcal{L}}_{disagreement}
+\gamma_{reg}\widetilde{\mathcal{L}}_{KL}
+\lambda_{rec}\widetilde{\mathcal{L}}_{rec}
+\lambda_{MI}\widetilde{\mathcal{L}}_{MI}
```

Los terminos con tilde son las versiones normalizadas.

- `fused` y `modality`: se calcula la Huber loss original y se divide por una
  escala de referencia calculada solo con `y_train`. Esa escala corresponde a la
  Huber loss de un predictor constante igual a la media de entrenamiento. Despues
  se aplica `clip(., 0, 1)`.
- `disagreement`: se divide por la varianza de `y_train`, usada como escala
  natural del objetivo, y se aplica `clip(., 0, 1)`.
- `KL`: se divide por `log(M)`, donde `M` es el numero de modalidades activas del
  modelo, y se aplica `clip(., 0, 1)`.
- `reconstruction`: la reconstruccion se mide como MSE sobre predictores
  estandarizados. Se usa `clip(MSE, 0, 1)`, donde `1` representa el orden de error
  de una reconstruccion sin informacion util en escala estandar.
- `MI`: se transforma en una perdida positiva:

```math
\widetilde{I}_2
=
\operatorname{clip}\left(\frac{I_2}{\log(d)}, 0, 1\right)
```

```math
\widetilde{\mathcal{L}}_{MI}
=
1 - \widetilde{I}_2
```

Aqui `d` es el numero de predictores del grafo `d x d`. Con esta forma,
maximizar informacion mutua equivale a minimizar una perdida entre `0` y `1`.
El mejor caso es `0`.

## Clasificacion

La funcion total conserva la misma estructura:

```math
\mathcal{L}_{cls}^{total}
=
\widetilde{\mathcal{L}}_{fused}
+\gamma_{sup}\widetilde{\mathcal{L}}_{modality}
+\gamma_{agr}\widetilde{\mathcal{L}}_{agreement}
+\gamma_{reg}\widetilde{\mathcal{L}}_{regularization}
+\lambda_{rec}\widetilde{\mathcal{L}}_{rec}
+\lambda_{MI}\widetilde{\mathcal{L}}_{MI}
```

- `fused`: la Generalized Cross Entropy tiene maximo teorico `1/q`. Por eso se
  normaliza como `clip(q * GCE, 0, 1)`.
- `modality`: se aplica el mismo criterio con `q_d`, es decir
  `clip(q_d * GCE_d, 0, 1)`.
- `agreement`: la divergencia GJS se divide por `log(C)`, donde `C` es el numero
  de clases, y se aplica `clip(., 0, 1)`.
- `KL`: se divide por `log(M)`, donde `M` es el numero de modalidades.
- `entropy`: se divide por `log(C)`.
- `regularization`: se calcula como promedio ponderado normalizado:

```math
\widetilde{\mathcal{L}}_{regularization}
=
\frac{\tau \widetilde{\mathcal{L}}_{KL}
+\alpha \widetilde{\mathcal{L}}_{entropy}}
{\tau + \alpha}
```

- `reconstruction` y `MI` usan exactamente la misma normalizacion definida para
  regresion.

## Parametros que sigue buscando Optuna

La normalizacion no elimina los pesos sintonizables. Optuna sigue buscando:

- `gamma_sup`
- `gamma_agr`
- `gamma_reg`
- `rbf_sigma`
- `lambda_reconstruction`
- `lambda_mutual_information`
- `batch_size`

En regresion tambien siguen `fused_delta` y `modality_delta`, porque controlan la
forma de la Huber loss antes de normalizarla.

## Interpretacion practica

El entrenamiento sigue minimizando una suma ponderada de los mismos criterios de
la propuesta, pero ahora todos los bloques que entran al total comparten una
escala comun. En particular, el termino de informacion mutua ya no entra como
`-I_2`; entra como una perdida positiva `1 - I_norm`, por lo que `0` significa
maxima alineacion normalizada entre el kernel reconstruido y el kernel del grafo.
