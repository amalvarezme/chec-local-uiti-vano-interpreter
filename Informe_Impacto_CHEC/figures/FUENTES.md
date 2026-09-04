# De donde sale cada figura

Las capturas de este informe no se rehacen a mano: proceden del sitio publico del
repositorio o de una captura reproducible de un visor HTML del propio proyecto.

## Copiadas de `site/assets/site/`

| Archivo en `figures/` | Origen |
|---|---|
| `informe/logo_unal_transparente.png` | `logos/logo_unal_transparente.png` |
| `informe/checlogo.png` | `logos/checlogo.png` |
| `informe/logo_labIA.png` | `logos/logo_labIA.png` |
| `cuadernos/tablero_clima.png` | `results/tablero-clima.png` |
| `cuadernos/tablero_agrupamiento.png` | `results/tablero-agrupamiento.png` |
| `cuadernos/ranking_circuitos.png` | `results/ranking-circuitos.png` |
| `cuadernos/tablero_tray_circuitos.png` | `results/tablero-trayectorias-circuitos.png` |
| `cuadernos/tablero_tray_vanos.png` | `results/tablero-trayectorias-vanos.png` |
| `cuadernos/simulador_mapas.png` | `results/simulador-mapas.png` |
| `cuadernos/simulador_resultados.png` | `results/simulador-resultados.png` |
| `cuadernos/simulador_guardar.png` | `results/simulador-guardar.png` |

## Capturadas de un visor HTML

Las dos se obtienen con Chrome sin interfaz. El `--virtual-time-budget` no es opcional:
sin el, la simulacion de fisica de la red no ha convergido cuando se toma la foto.

```
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
R=site/assets/site/results

"$CH" --headless --disable-gpu --no-sandbox --hide-scrollbars \
  --enable-unsafe-swiftshader --use-gl=swiftshader --window-size=1800,1150 \
  --virtual-time-budget=20000 \
  --screenshot=figures/informe/grafo_fijo_mil.png "file://$PWD/$R/grafo-fijo-mil.html"

"$CH" --headless --disable-gpu --no-sandbox --hide-scrollbars \
  --enable-unsafe-swiftshader --use-gl=swiftshader --window-size=1700,1200 \
  --virtual-time-budget=60000 \
  --screenshot=figures/informe/grafo_proyecto.png "file://$PWD/$R/grafo-proyecto.html"
```

## Dibujadas en el propio documento

Los seis diagramas de bloques -- arquitectura, cadena de bandas, modelo por bolsas,
flujo de simulacion, costos por actividad y flujo de `/report` -- son TikZ dentro de
`informe_tecnico.tex`. No hay archivo que regenerar: se editan en el `.tex`.

## Como compilar

```
pdflatex -output-directory=build informe_tecnico.tex   # dos veces, por el indice
cp build/informe_tecnico.pdf informe_tecnico.pdf
```

## Generadas a partir de una medicion propia (2026-09-03)

Los guiones que las producen quedan en `Informe_Impacto_CHEC/scripts/`, junto con los
datos crudos que consumen. Ninguno escribe en `data/models/`.

| Archivo en `figures/` | Guion | Dato de entrada |
|---|---|---|
| `informe/curvas_entrenamiento.png` | `scripts/fig_train.py` | `scripts/fold_history.json`, producido por `scripts/run_fold.py` |
| `informe/curvas_roc.png` | `scripts/fig_roc.py` | `scripts/roc.json`, derivado de `data/derived/oof_mil_full_film_clase1.0.npz` |

`run_fold.py` ejecuta las celdas 0 a 44 de `notebooks/05_mil_vano_ventana.ipynb` con
`mode="full"` y `EJECUCION="entrenamiento"`, y luego ajusta **un solo pliegue** con
`entrenar_mil(..., verbose=True)` para quedarse con el historial por epoca, que el
cuaderno produce pero no persiste. Se detiene antes de la celda 64, que es la unica que
sobreescribe el artefacto entrenado.

La matriz de confusion de la Tabla 12 no se recalcula: se lee de
`metadatos["desglose_por_clase"]["modelo"]["matriz_confusion"]` dentro de
`data/models/mil_vano_ventana_v1.pt`.

## Medicion del rendimiento por dispositivo (2026-09-04)

La Tabla 20 (`tab:formalote`) y el parrafo que explica por que la GPU integrada resulta mas
lenta NO son estimaciones. Los cuatro guiones estan en `Informe_Impacto_CHEC/scripts/` y
leen `data/derived/bolsas_mil_full.joblib` mas `data/models/mil_vano_ventana_v1.pt`; ninguno
escribe nada.

| Guion | Que mide | Cifra que sostiene |
|---|---|---|
| `bench_device.py` | Las cuatro etapas de un paso, por separado, en CPU y MPS | 0,80 ms de transferencia y 0,23 ms de armado contra 172 ms del paso |
| `bench_size.py` | Una MLP equivalente, escalando el lote de 664 a 169.984 instancias | 0,90 ms en MPS contra 1,21 ms en CPU: el tamano del modelo NO es el factor |
| `bench_shape.py` | El mismo lote repetido contra 32 lotes distintos | 15,12 ms (1,5x) contra 106,27 ms (11,8x) |
| `bench_mem.py` | Memoria reservada por el driver en ambos regimenes | 62,9 MB contra 129,6 MB con ~24 MB de tensores vivos en los dos |

La explicacion anterior del informe ---"el modelo es demasiado pequeno para amortizar el
traslado de cada lote"--- quedo **refutada** por `bench_device.py` y `bench_size.py`, y se
sustituyo por la causa medida: las bolsas tienen cardinalidad variable, cada lote cambia de
forma (560 a 793 filas, 34 valores distintos en 40 lotes) y MPS recompila sus nucleos por
forma.
