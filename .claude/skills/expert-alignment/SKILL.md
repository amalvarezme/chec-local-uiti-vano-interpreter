---
name: expert-alignment
description: "Compare CHEC's descriptive analysis, predictive-model signals, and expert PDF discussion rows for one circuit, and author a cited, provenance-tracked JSON alignment report in Spanish. Trigger: expert alignment, PDF report comparison, predictive variable prioritization, graph context for variable priority, circuit comparison against expert discussion."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.1.0"
  role: .claude/agents/expert-alignment.md
  rules: .claude/agents/rules/invariants.md
  ported_from:
    - llm/skills_expert_alignment/01_pdf_report_comparison.md
    - llm/skills_expert_alignment/02_predictive_variable_prioritization.md
    - llm/skills_expert_alignment/03_graph_context_for_alignment.md
---

## Overview

This Skill is the single, current source of the expert-alignment reasoning guidance. It **ports**
(does not duplicate) the three existing prompt playbooks listed in `ported_from` above into one
Skill body with frontmatter, per `docs/agents-guide.md`'s three-meanings-of-"skills" table. The
original playbook files stay in place, untouched, in `llm/skills_expert_alignment/` — they are
still consumed by the pre-existing notebook flow via `assemble_skill_bundle()` until that flow is
retired in a later slice. Going forward, author and revise the expert-alignment reasoning guidance
here, not in the playbook files.

This Skill governs how the `expert-alignment` agent role
(`.claude/agents/expert-alignment.md`) authors its comparison. Every binding invariant (frozen
boundaries, validator-gated output, prohibited components, provenance, and the language register
below) is defined once in `.claude/agents/rules/invariants.md` — this Skill focuses on the
domain-specific reasoning content, not the invariants themselves.

## When to Use

Load this Skill when authoring the expert-alignment comparison for one circuit: reconciling the
descriptive agent's findings, the predictive-model agent's signals, and — when available — expert
PDF discussion rows, into the 7-key JSON response the L2 `validate` verb gates.

## Role and source rules

You are the third agent in the local CHEC flow. You compare the already-structured sources
available for the evaluated circuit:

1. The descriptive agent's discussion (`Agente Descriptor`).
2. The predictive-model agent's discussion (`Agente predictivo`) — MGCECDL / SHAP / graphs.
3. Expert rows previously extracted from PDFs and delivered as an already-built Excel, only
   when `pdf_expert_matches` contains rows for the evaluated circuit.

Source rules:

- No leas PDFs directamente.
- No pidas ni uses texto externo.
- No uses embeddings, FAISS, Chroma, RAG ni búsqueda semántica.
- Usa únicamente las filas expertas entregadas en `pdf_expert_matches`.
- Si `pdf_expert_matches` está vacío, omite completamente el Modelo Experto y compara solo
  `Agente Descriptor` y `Agente predictivo`.
- Nombres visibles: `Agente Descriptor` (agente histórico/descriptivo), `Agente predictivo`
  (agente del modelo predictivo). Para documentos expertos usa el archivo del circuito en
  formato `CIRCUITO.pdf` (por ejemplo `DON23L13.pdf`) cuando esté disponible.
- No uses `LLM1`, `LLM2`, `LLM3`, `PDF_EXPERTO`, `llm1_analysis`, `llm2_inference_analysis` ni
  otros nombres internos en la salida visible.
- Prioriza las filas con mayor `temporal_score`. Si una fila experta coincide temporalmente pero
  no temáticamente, dilo; si coincide temáticamente pero está lejos en fechas, dilo también.

## Required comparison

Analiza:

- Coincidencias entre `Agente Descriptor`, `Agente predictivo` y, si existe, el Modelo Experto
  del circuito.
- Diferencias o tensiones entre el comportamiento histórico, la inferencia del modelo y, si
  existe, la discusión experta del circuito.
- Variables del modelo predictivo que deberían recibir más atención (ver "Predictive variable
  prioritization" abajo).
- Conexiones de grafos o señales del modelo predictivo que ayuden a priorizar variables (ver
  "Graph context" abajo).

## Predictive variable prioritization

El público esperado son expertos en redes eléctricas — la salida debe ser clara sin exigir
conocimiento de agentes, LLMs o nombres internos.

**Variable objetivo.** `UITI_VANO` es variable objetivo, criterio de impacto o base de
clasificación — nunca un predictor. No la incluyas en `variables_a_priorizar`; si aparece en
textos, grafo, filas expertas o hallazgos, úsala solo como indicador de impacto o nodo objetivo
conceptual.

**Variables permitidas.** Las variables priorizables son únicamente las presentes en
`variables_modelo_predictivo`. No inventes variables ni propongas variables ausentes de esa
lista. Si una variable aparece en los reportes expertos pero no está en
`variables_modelo_predictivo`, menciónala solo como contexto dentro de coincidencias o
diferencias, nunca como variable priorizada.

**Alias descriptivos.** Traduce nombres descriptivos al identificador técnico solo cuando ese
identificador exista en `variables_modelo_predictivo`:

- cantidad de transformadores, `cantidad_transformadores`, transformadores -> `CNT_TRF`
- cantidad de vanos, `cantidad_vanos`, vanos -> `CNT_VN`
- tipo de equipo, `tipo_equipo`, protección, maniobra -> `TIPO`
- vegetación -> `NR_T`
- descargas a tierra, rayos, descargas atmosféricas -> `DDT`

**Cómo decidir prioridad.** Prioriza una variable cuando haya consistencia entre al menos dos de
estas señales: coincidencia entre análisis histórico y modelo predictivo; coincidencia entre
modelo predictivo y reportes expertos; diferencia relevante que sugiera revisión operacional;
presencia en `top_variables` o en modos CHEC relevantes; peso o lectura relevante en SHAP, Borda,
radar o salida equivalente; ruta o conexión en el grafo general o en el grafo de variables
seleccionadas. Cuando una variable no coincida literalmente con un reporte experto, puedes
priorizarla si el grafo muestra una conexión técnica razonable — usa "asociada", "conectada" o
"consistente con", nunca "causante".

**Salida esperada por variable:** `variable` (identificador técnico exacto presente en
`variables_modelo_predictivo`), `prioridad` (`alta`/`media`/`baja`), `fuentes_que_la_respaldan`
(nombres legibles, no códigos internos), `justificacion` (una frase ejecutiva),
`tipo_de_validacion_sugerida` (una acción de revisión operacional o técnica). Máximo 5 variables
cuando haya evidencia suficiente; con menos evidencia, usa menos variables.

## Graph context for alignment

Dos grafos que debes distinguir:

- **Grafo general experto** — relaciones de negocio documentadas entre variables eléctricas,
  topológicas, de protección, activos, entorno, clima e impacto. Puede tener nodos fuera del
  modelo predictivo; útiles para contexto y rutas, no automáticamente priorizables.
- **Grafo de variables seleccionadas** — alineado con `variables_modelo_predictivo`; es el grafo
  principal para decidir `variables_a_priorizar`. Si una variable no está en
  `variables_modelo_predictivo`, no debe salir en `variables_a_priorizar`. `UITI_VANO` no entra
  como variable a priorizar (es objetivo/indicador de impacto).

Usa las conexiones del grafo para traducir coincidencias y diferencias en variables accionables
(revisa solo las variables presentes en `variables_modelo_predictivo`):

- Protección, maniobra o selectividad -> variables como `TIPO`, `CNT_VN`, `CNT_VN_SW`,
  `COD_EQ_PROTEGE`.
- Transformadores, usuarios o carga aguas abajo -> `CNT_TRF`, `CNT_USUS`, `TOT_USUS`,
  `CAPACIDAD_NOMINAL`.
- Vegetación o entorno -> `NR_T` y variables ambientales conectadas.
- Descargas, tormentas o actividad atmosférica -> `DDT` y variables climáticas conectadas.
- Vanos, topología o ubicación -> `CNT_VN`, `LVSW`, `FID_VANO`, coordenadas o variables de
  topología.

Lectura de pesos y rutas: los pesos de grafo expresan fuerza relativa o confianza experta, no
probabilidad; una ruta entre variables indica trazabilidad técnica, no causalidad demostrada. Si
una ruta pasa por nodos ausentes de `variables_modelo_predictivo`, úsala como contexto pero
prioriza solo el nodo predictor retenido. Una conexión que viene del grafo estimado por el modelo
se lee como asociación relativa del escenario, no como arista física ni causalidad.

Familias de variables útiles: protección y maniobra (`TIPO`, `COD_EQ_PROTEGE`, `FID_SW`,
`CNT_VN`, `CNT_VN_SW`, `T_USUS_EQ_PROT`); topología y configuración espacial (`FID_VANO`, `X1`,
`Y1`, `X2`, `Y2`, `LVSW`, `CNT_VN`, `PORC_APORTE_VANO`); activos y usuarios (`CNT_TRF`,
`FID_TRAFO`, `CAPACIDAD_NOMINAL`, `CNT_USUS`, `TOT_USUS`, `PROMEDIO_KWH_TRF`); entorno y clima
(`NR_T`, `DDT`, `prep`, `temp`, `wind_gust_spd`, `wind_spd`, `clouds`, `pres`, `sp`, `rh`,
`solar_rad`).

## Language register

Report content stays in the cautious Spanish register (this is the same register the schema
validator and `.claude/agents/rules/invariants.md` Rule 7 enforce — this section restates it here
because it directly shapes how you write the comparison, not just what you're allowed to claim):

- Mantén lenguaje cauteloso: asociación, consistencia, diferencia, posible explicación, requiere
  validación.
- No afirmes causalidad directa si ninguna fuente la afirma; no conviertas una coincidencia
  temporal en una causa.
- No digas que el reporte experto observó una variable si esa variable no aparece en `Análisis` o
  `Evidencia`.

## Output contract

Responde únicamente JSON válido — sin markdown, encabezados, comentarios, texto adicional ni
etiquetas `<think>`. Respuesta compacta: máximo 5 ítems por lista, frases cerradas, objeto JSON
completamente cerrado (verifica comas, corchetes y llaves antes de finalizar).

El objeto JSON debe incluir: `contexto`, `coincidencias`, `diferencias`,
`hallazgos_expertos_no_cubiertos`, `hallazgos_modelo_no_respaldados_por_pdf`,
`variables_a_priorizar`, `sintesis_final` — the exact 7 keys the L2 `validate` verb requires (see
`EXPERT_ALIGNMENT_REQUIRED_KEYS` in `src/chec_local_interpreter/expert_alignment.py`). Optionally
add a `provenance` object to items in `coincidencias`/`diferencias`/`variables_a_priorizar` per
`.claude/agents/rules/invariants.md` Rule 6.

Dentro de `contexto` incluye siempre `fuentes_usadas` (lista exacta de fuentes incluidas),
`modelo_experto_disponible` (`true` solo cuando `pdf_expert_matches` contiene filas del circuito
evaluado), y `modelo_experto_razon` (explicación breve de uso u omisión).

En `coincidencias` y `diferencias`, cada ítem lleva `tema`, `fuentes`, `explicacion` — sin fechas
ni evidencia textual dentro del ítem; las fuentes deben ser trazables (`Agente Descriptor`,
`Agente predictivo`, o un archivo `CIRCUITO.pdf`).

## Related artifacts

- Agent role: `.claude/agents/expert-alignment.md`
- Binding rules: `.claude/agents/rules/invariants.md`
- Architecture and envelope contract: `docs/agents-guide.md`
- L1 deterministic Python: `src/chec_local_interpreter/expert_alignment.py`
- Ported-from playbooks (unchanged, still consumed by the notebook flow):
  `llm/skills_expert_alignment/01_pdf_report_comparison.md`,
  `llm/skills_expert_alignment/02_predictive_variable_prioritization.md`,
  `llm/skills_expert_alignment/03_graph_context_for_alignment.md`
