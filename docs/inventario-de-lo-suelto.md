# Inventario de lo suelto — archivos, funciones y planos fuera del flujo

> Medido el 2026-08-18 sobre `main` en `b9fe934`, con el grafo de `graphify-out/` recién
> reconstruido (9.289 nodos, 15.132 aristas, 1.002 comunidades).
>
> Audiencia: quien decida qué se borra. El documento nombra, mide y separa lo que de verdad está
> suelto de lo que solo lo parece. Las **secciones B y E ya se ejecutaron** el mismo día, y de la
> **A** se fue el primero de los tres; lo demás sigue siendo propuesta y no se ha tocado.

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

Eran tres. Los tres tenían pruebas, y **las 38 pruebas pasaban**: verdes, y no los llamaba nadie.
Uno ya se fue.

| Módulo | Líneas | Su prueba | Último cambio | Por qué quedó suelto |
|---|---:|---:|---|---|
| ~~`src/chec_local_interpreter/graph_view_builder.py`~~ **BORRADO** | 264 | 586 | 2026-07-25 | Existía solo para el **paso 2.5 de `/informe-gerencial`**, retirado el 2026-08-18 junto con la sección "Patrones cross-circuito (grafo)" que lo consumía |
| `src/chec_local_interpreter/relevancia_lote.py` | 408 | 363 | 2026-08-10 | Era del cuaderno `07_relevancia_lote_por_vano`, **borrado el 2026-08-14** con los ocho del pipeline MGCECDL |
| `src/chec_local_interpreter/web_export.py` | 46 | 27 | 2026-08-16 | Puente manual hacia la página Astro. `report/SKILL.md` lo declara explícitamente opcional: *"call `web_export.export_latest_interpretability_report(html_path)` yourself when you actually…"* |

**Los tres no son el mismo caso, y no merecen la misma decisión.**

- `graph_view_builder.py` era **código muerto declarado**, y **se borró el 2026-08-18** — 850
  líneas entre módulo y prueba. Su propio `SKILL.md` lo llamaba *"dead code pending a decision"*;
  esta fue la decisión. En su lugar quedó
  `tests/test_graph_view_builder_retirado.py`, que impide las dos formas de volver: el archivo y la
  prosa que lo resucitaría. El grafo que el informe sí dibuja hoy lo construye
  `intervention_graph.py` desde los artefactos de corrida, sin tocar graphify.
- `relevancia_lote.py` perdió a su consumidor hace cuatro días y **nadie lo ha reclamado**. Su
  prueba es lo único que lo importa.
- `web_export.py` **no está muerto: está fuera del automatismo a propósito.** Publicar en la
  página web es un canal de divulgación, no una pieza del análisis, y `flujo-detallado.md` ya lo
  deja fuera explícitamente. Borrarlo cortaría el único puente que existe hacia `site/`.

## B. Funciones sin una sola referencia en todo el árbol — ✅ BORRADAS

Eran dos, las dos en `src/chec_impacto/interpretability/circuit_analysis.py`. **Se borraron el
2026-08-18**; el módulo pasó de 893 a 824 líneas.

| Función | Línea | Por qué quedó suelta |
|---|---:|---|
| `puntaje_borda_ponderado_eventos` | 126 | Variante superada de `agregar_borda`, que sí se usa unas líneas más arriba en el mismo archivo |
| `estimar_matriz_grafo_mgcecdl` | 164 | Reconstruía una matriz variable-variable desde **el decodificador de MGCECDL**, el clasificador retirado en `2cf942b` |

Ninguna de las dos estaba en el mapa de exportación perezosa `_ORIGEN` de
`interpretability/__init__.py`, así que la API del paquete no cambió.

`estimar_matriz_grafo_mgcecdl` importaba `torch` dentro de su propio cuerpo — el archivo
documentaba que lo hacía porque era *"la única función de este módulo que lo usa"*. Al irse, el
rodeo sobra: **el archivo entero quedó sin una sola mención a `torch`**, y eso está congelado por
`tests/test_costo_de_arranque.py::test_circuit_analysis_ya_no_nombra_torch`. Un import perezoso
solo se nota cuando alguien vuelve a poner uno normal arriba, y para entonces ya lo están pagando
las dos llamadas del rol `inference`.

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

## E. Documentación que quedó desfasada — ✅ CORREGIDA

Encontrado de paso, verificado contra el código, y arreglado el 2026-08-18 junto con el borrado:

- **`README.md`** describía el **paso 2.5** de `/informe-gerencial` (*"graphify rebuild aislado +
  query temas recurrentes"*) como parte del flujo, en la tabla de comandos y en el diagrama
  Mermaid. Ese paso se retiró; hoy el paso es el **2.6**, `intervention_graph`, que lee los
  artefactos de corrida y no invoca graphify.
- El mismo diagrama afirmaba que graphify se encadena **acotado a `reports/vault`**, que es la regla
  ANTERIOR y la que causaba 426 borrados fantasma. Se encadena desde la raíz, detrás de
  `graphify_guarda`.
- Esa prosa obsoleta fue, además, la única razón por la que el analizador no marcó
  `graph_view_builder.py` como huérfano en la primera pasada.

### El analizador se escuda a sí mismo

Al volver a correrlo después de borrar las dos funciones, la lista de módulos huérfanos salió
**vacía**. No porque se hayan resuelto: porque **este mismo documento los nombra**, y el
analizador perdona a cualquier módulo cuya ruta aparezca en un `.md`. Es exactamente la trampa del
`README` de arriba, reproducida por el inventario que la denuncia.

Un segundo caso, accidental y más divertido: la clase `Pieza` de
`aplicaciones/_comun/empaquetar.py` estuvo escondida durante meses porque `flujo-resumen.md`
titulaba sus secciones *"Pieza 1"*, *"Pieza 2"*… Al reescribir ese documento sobre los tres
pilares, la palabra desapareció y la clase salió a la luz. Tiene un uso interno real, así que no
es código muerto — pero mide bien lo frágil que es escudarse en el texto.

**Regla para el próximo analizador:** el corpus de prosa sirve para *no borrar por error*, nunca
para *dar por vivo*. Cuando algo sobreviva solo por una mención en texto, hay que mirar quién la
escribió y si sigue siendo verdad.

## Recomendación, en orden

- [x] **Borrar las dos funciones de `circuit_analysis.py`.** Hecho el 2026-08-18: 69 líneas fuera,
  `torch` fuera del archivo, y una prueba que lo congela. La suite pasó de 2.790 a 2.791.
- [x] **Borrar `graph_view_builder.py` y su prueba.** Hecho el 2026-08-18: 850 líneas fuera, más
  una guarda de retiro que cubre el archivo Y la prosa.
- [x] **Corregir `README.md`** en el mismo cambio, junto con el bloque del `SKILL.md` que decía
  que el módulo se dejaba en pie.
- [ ] **Decidir sobre `relevancia_lote.py`** (771 líneas con su prueba). Perdió a su cuaderno el
  2026-08-14; si el barrido por lote va a volver, se queda; si no, se va al historial de git como
  se fueron los nueve cuadernos.
- [x] **No tocar `web_export.py`.** Está fuera del flujo por diseño, y es el único puente hacia
  `site/`.

Lo que queda no es urgente y no rompe una prueba en verde hoy. Ese es justamente el riesgo — una
suite verde no distingue entre código que funciona y código que además hace falta.
