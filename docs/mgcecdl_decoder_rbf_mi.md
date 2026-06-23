# MGCECDL: decoders, RBF e informacion mutua

Cada modo reconstruye sus predictores estandarizados mediante un decoder propio.
Las reconstrucciones se reordenan segun `features` para formar
`X_hat` de dimension `B x d`.

La perdida de reconstruccion es:

$$
\mathcal{L}_{rec}
=
\frac{1}{Bd}
\sum_{b=1}^{B}\sum_{i=1}^{d}
(\widehat{\widetilde X}_{bi}-\widetilde X_{bi})^2.
$$

Cada variable se representa por su reconstruccion a traves del batch. El kernel
RBF entre variables produce una matriz `d x d`:

$$
K^{rec}_{ij}
=
\exp\left(
-\frac{\|\widehat{\mathbf{x}}_i-\widehat{\mathbf{x}}_j\|_2^2}
{2B\sigma^2}
\right).
$$

La adyacencia dirigida experta se convierte en perfiles de entrada y salida:

$$
\mathbf{g}_i=[A^*_{i,:},A^*_{:,i}],
$$

y luego en un kernel RBF simetrico `K_graph`. Su ancho se calcula con la
mediana de las distancias positivas entre perfiles.

Para orden dos:

$$
H_2(K)=-\log\left(\operatorname{tr}(\bar K^T\bar K)+\epsilon\right),
\qquad
\bar K=\frac{K}{\operatorname{tr}(K)+\epsilon}.
$$

$$
I_2(K^{rec};K^{graph})
=H_2(K^{rec})+H_2(K^{graph})
-H_2(K^{rec}\odot K^{graph}).
$$

Para que todos los terminos entren a la funcion de costo en una escala comparable,
la informacion mutua se normaliza con el maximo teorico usado para el grafo de
variables:

$$
\widetilde{I}_2
=
\operatorname{clip}\left(\frac{I_2}{\log(d)},0,1\right).
$$

Como el entrenamiento minimiza, el termino se codifica como una perdida positiva:

$$
\widetilde{\mathcal{L}}_{MI}
=
1-\widetilde{I}_2.
$$

Las perdidas totales usan coeficientes independientes y terminos normalizados:

$$
\mathcal{L}^{reg}_{total}
=\widetilde{\mathcal{L}}_{fused}
+\gamma_{sup}\widetilde{\mathcal{L}}_{modality}
+\gamma_{agr}\widetilde{\mathcal{L}}_{disagreement}
+\gamma_{reg}\widetilde{\mathcal{L}}_{KL}
+\lambda_{rec}\widetilde{\mathcal{L}}_{rec}
+\lambda_{MI}\widetilde{\mathcal{L}}_{MI},
$$

$$
\mathcal{L}^{cls}_{total}
=\widetilde{\mathcal{L}}_{fused}
+\gamma_{sup}\widetilde{\mathcal{L}}_{modality}
+\gamma_{agr}\widetilde{\mathcal{L}}_{agreement}
+\gamma_{reg}\widetilde{\mathcal{L}}_{regularization}
+\lambda_{rec}\widetilde{\mathcal{L}}_{rec}
+\lambda_{MI}\widetilde{\mathcal{L}}_{MI}.
$$

Optuna conserva los hiperparametros propios del modelo y de cada tarea, y busca
ademas en ambas tareas:

- `gamma_sup`: `0.05` a `0.75`.
- `gamma_agr`: `0.01` a `0.50`.
- `gamma_reg`: `0.0001` a `0.10`, escala logaritmica.
- `rbf_sigma`: `0.01` a `10`, escala logaritmica.
- `lambda_reconstruction`: `0.0001` a `0.5`, escala logaritmica.
- `lambda_mutual_information`: `0.0001` a `0.75`, escala logaritmica.
- `batch_size`: `256`, `512` o `1024`.

Las medias y desviaciones de reconstruccion se calculan exclusivamente con
`X_train`. La matriz experta debe estar alineada con el orden de `features`.
