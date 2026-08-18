# Inventario de lo suelto — archivos, funciones y planos fuera del flujo

> Medido el 2026-08-18 sobre `main` en `b9fe934`, con el grafo de `graphify-out/` recién
> reconstruido (9.289 nodos, 15.132 aristas, 1.002 comunidades).
>
> Audiencia: quien decida qué se borra. Este documento **no borra nada**: nombra, mide y separa
> lo que de verdad está suelto de lo que solo lo parece.

## Qué se midió, y por qué así

Un analizador de AST sobre los **273 módulos Python** del árbol (`src/`, `scripts/`, `evals/`,
`tests/`, `aplicaciones/`) construye el grafo de importaciones y luego pregunta dos cosas
distintas:

1. **¿Alguien importa este módulo?** — descontando las pruebas, que no son consumidores: una
   prueba puede mantener vivo en verde un módulo que ya no llama nadie.
2. **¿Alguien usa este símbolo público, fuera del archivo que lo define?**

La primera pasada dio 17 módulos huérfanos y 65 símbolos sin consumidor. **Doce de esos 17 eran
falsos positivos**, y encontrarlos es la mitad del valor de este documento: están en la sección
"Lo que parece suelto y no lo está". Las cifras de abajo son las que quedaron después de
verificar cada una contra el código que supuestamente la deja huérfana.

## A. Módulos sin ningún consumidor en producción

Tres. Los tres tienen pruebas, y **las 38 pruebas pasan**: están verdes y no las llama nadie.

| Módulo | Líneas | Su prueba | Último cambio | Por qué quedó suelto |
|---|---:|---:|---|---|
| `src/chec_local_interpreter/graph_view_builder.py` | 264 | 586 | 2026-07-25 | Existía solo para el **paso 2.5 de `/informe-gerencial`**, retirado el 2026-08-18 junto con la sección "Patrones cross-circuito (grafo)" que lo consumía |
| `src/chec_local_interpreter/relevancia_lote.py` | 408 | 363 | 2026-08-10 | Era del cuaderno `07_relevancia_lote_por_vano`, **borrado el 2026-08-14** con los ocho del pipeline MGCECDL |
| `src/chec_local_interpreter/web_export.py` | 46 | 27 | 2026-08-16 | Puente manual hacia la página Astro. `report/SKILL.md` lo declara explícitamente opcional: *"call `web_export.export_latest_interpretability_report(html_path)` yourself when you actually…"* |

**Los tres no son el mismo caso, y no merecen la misma decisión.**

- `graph_view_builder.py` es **código muerto declarado**. El propio
  `.claude/skills/informe-gerencial/SKILL.md:535` lo dice con todas las letras: *"is NO LONGER
  invoked by this flow… nothing calls them — treat it as dead code pending a decision"*. Esta es
  esa decisión pendiente. Son 850 líneas entre módulo y prueba.
- `relevancia_lote.py` perdió a su consumidor hace cuatro días y **nadie lo ha reclamado**. Su
  prueba es lo único que lo importa.
- `web_export.py` **no está muerto: está fuera del automatismo a propósito.** Publicar en la
  página web es un canal de divulgación, no una pieza del análisis, y `flujo-detallado.md` ya lo
  deja fuera explícitamente. Borrarlo cortaría el único puente que existe hacia `site/`.

## B. Funciones sin una sola referencia en todo el árbol

Dos, las dos en `src/chec_impacto/interpretability/circuit_analysis.py` (893 líneas en total):

| Función | Línea | Por qué quedó suelta |
|---|---:|---|
| `puntaje_borda_ponderado_eventos` | 126 | Variante superada de `agregar_borda`, que sí se usa unas líneas más arriba en el mismo archivo |
| `estimar_matriz_grafo_mgcecdl` | 164 | Reconstruye una matriz variable-variable desde **el decodificador de MGCECDL**, el clasificador retirado en `2cf942b` |

`estimar_matriz_grafo_mgcecdl` importa `torch` dentro de su propio cuerpo — el archivo documenta
que lo hace porque es *"la única función de este módulo que lo usa"*. Borrarla deja a
`circuit_analysis.py` sin ninguna dependencia de `torch`, que es exactamente el motivo por el que
`interpretability/__init__.py` resuelve sus exportaciones tarde.

Las otras 48 funciones y clases que la primera pasada marcó **no están muertas**: son públicas de
nombre pero internas de hecho, usadas dentro de su propio módulo entre 1 y 11 veces
(`ReportRequest` 11 veces, `ClusteringRequest` 8, los `cmd_*` de `bitacora_despliegue.py` una vez
cada uno desde `construir_parser`). Renombrarlas con `_` sería un cambio de estilo, no una
limpieza.

## C. Planos completos que no tocan el flujo de análisis

No son basura: son otros proyectos que comparten repositorio. Se listan para que nadie los
confunda con el flujo ni los borre por error.

| Ruta | Versionado | En disco | Qué es |
|---|---:|---:|---|
| `site/` | 45 archivos | 20 MB | La página Astro de presentación. Su único puente con el análisis es `web_export.py` |
| `dist/` | 0 | 13 MB | Salida de `astro build`. La regenera `.github/workflows/deploy-pages.yml` en cada push a `main` |
| `node_modules/` | 0 | 148 MB | Dependencias npm de esa página |
| `lib/` | 0 | 748 KB | `vis-network` y `tom-select` servidos localmente |
| `public/` | 1 | 4 KB | Solo `.nojekyll` |
| `Informe_Impacto_CHEC/` | 2 | 6 MB | El informe técnico en LaTeX y su PDF |
| `evals/` | 8 | 88 KB | Arnés de evaluación de los agentes. `AGENTS.md:103` y `README.md:495` lo exigen antes de dar un cambio por terminado |
| `graphify-out/` | 0 |  43 MB | El grafo de conocimiento. Ignorado por git a propósito |

`site/`, `dist/`, `lib/`, `public/` y `node_modules/` son **un solo plano**, no cinco cosas
sueltas: la página web. Tiene su propio CI y su propio ciclo de vida. `flujo-detallado.md` la deja
fuera desde su primera línea, y este inventario coincide.

## D. Lo que parece suelto y no lo está

Doce falsos positivos, agrupados por el mecanismo que los esconde de un analizador estático. Vale
la pena leerlos antes de escribir el próximo analizador, porque cada grupo requiere una regla
distinta.

| Mecanismo | Módulos | Por qué el AST no lo ve |
|---|---|---|
| **Import por nombre pelado** tras manipular `sys.path` | `aplicaciones/_comun/{servidor,terminal,huellas,paleta,raiz,tableros,entorno,empaquetar}.py` | Los seis `app.py` hacen `import servidor`, no `from aplicaciones._comun import servidor`. El nombre del módulo en el grafo nunca coincide |
| **Import escrito por código generado** | `aplicaciones/06_simulador/cierre.py` | `preparar.py:337` emite el literal `"import cierre\n"` dentro de una celda del cuaderno que construye |
| **Punto de entrada declarado en YAML** | `aplicaciones/databricks/criticidad_chec/{app,catalogo,pagina}.py` | `app.yaml` dice `uvicorn app:app`. No hay ningún `import` en ningún `.py` |
| **Import perezoso por cadena (PEP 562)** | `chec_impacto/interpretability/mgcecdl.py`, `chec_impacto/models/mgcecdl_graph_search.py`, `chec_impacto/data/preprocessing.py` | Los `__init__.py` guardan `_ORIGEN = {"nombre": "submodulo"}` y resuelven en `__getattr__`. El destino es un *string*, no un `import` |
| **Consumidor fuera del árbol de código** | los 15 símbolos de `clima_engine.py` | Quien los llama es `.claude/skills/clima/assets/runbook.py`, que no está en `src/` ni en `tests/` |

El grupo de los imports perezosos es el más traicionero: se introdujo **a propósito** para que
tocar cualquier submódulo de `chec_impacto` no arrastrara `torch` (1,49 s → 0,03 s de arranque), y
el efecto colateral es que rompe la trazabilidad estática de todo el paquete.

## E. Documentación que quedó desfasada

Encontrado de paso, verificado contra el código:

- **`README.md:390` y `README.md:446`** siguen describiendo el **paso 2.5** de `/informe-gerencial`
  (*"graphify rebuild aislado + query temas recurrentes + graph_view_builder"*) como parte del
  flujo. Ese paso se retiró el 2026-08-18. El `SKILL.md` ya está corregido; el `README.md` no.
  Es, además, la única razón por la que el analizador no marcó `graph_view_builder.py` como
  huérfano en la primera pasada: la prosa obsoleta lo mantuvo vivo.

## Recomendación, en orden

1. **Borrar `graph_view_builder.py` y su prueba** (850 líneas). Es el único caso donde la decisión
   ya está documentada como pendiente por el propio proyecto, y donde no hay ninguna ambigüedad
   sobre quién lo llamaba.
2. **Corregir `README.md:390` y `:446`** en el mismo cambio. Sin eso, el próximo inventario vuelve
   a tropezar con la misma prosa.
3. **Borrar las dos funciones de `circuit_analysis.py`** (39 líneas) y comprobar que el archivo
   queda sin `torch`.
4. **Decidir sobre `relevancia_lote.py`** (771 líneas con su prueba). Perdió a su cuaderno el
   2026-08-14; si el barrido por lote va a volver, se queda; si no, se va al historial de git como
   se fueron los nueve cuadernos.
5. **No tocar `web_export.py`.** Está fuera del flujo por diseño, y es el único puente hacia
   `site/`.

Nada de esto es urgente y nada de esto rompe una prueba en verde hoy: las 38 pruebas de los tres
módulos huérfanos pasan. Ese es justamente el riesgo — una suite verde no distingue entre código
que funciona y código que además hace falta.
