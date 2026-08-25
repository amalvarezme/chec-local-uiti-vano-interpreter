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
