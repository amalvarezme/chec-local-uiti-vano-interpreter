# Local UITI_VANO Interpreter

Agent-native local interpreter for `UITI_VANO` in the CHEC wide dataset. It loads one wide
structured dataset, filters by circuits and dates, detects relevant points in the daily
`UITI_VANO` series, builds a structured context package, and has five coding-agent-native LLM
roles explain the behavior in Spanish and compare it against expert PDF reports — all with
**zero external LLM API key**: the invoking coding agent (Claude Code or OpenCode) does the
reasoning itself, never a Python call to Gemini/OpenAI. `/reporte <circuito>` is the primary
end-to-end entry point. See `AGENTS.md` and `docs/agents-guide.md` for the full architecture.

## Página del proyecto

La página pública del proyecto se puede abrir desde GitHub Pages:

https://amalvarezme.github.io/chec-local-uiti-vano-interpreter/

La versión publicada corresponde a la rama:
`main`

## Scope

Circuit/vano selection, deterministic critical-point detection, and semantic diagnosis
(`historical`), MGCECDL/SHAP predictive interpretation (`inference`), expert-PDF alignment
(`expert-alignment`), automatic min/max sensitivity discussion (`auto-simulator`), and
PDF-discussion-table extraction (`pdf-discussion-extraction`) are all in scope and implemented.
Does not use Databricks, Dash, FastAPI, RAG, or vector stores. The workflow stays local and
lightweight.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure

```bash
cp .env.example .env
```

Place a CSV, Parquet, or Excel dataset under `data/`, or set `DATA_PATH`. The default is
`data/Indicadores_vano_v3.csv` resolved from the project root.

Required columns:

- `CIRCUITO`
- `FECHA`
- `UITI_VANO`

Optional columns are used when available and recorded as unavailable when absent.

## Run

`/reporte <circuito> [fecha_inicio fecha_fin]` is the primary end-to-end entry point. It is
**not** a Python CLI you run directly — it is a Claude Code / OpenCode slash-command Skill
(`.claude/skills/reporte/SKILL.md`), orchestrated by
`src/chec_local_interpreter/report_pipeline.py`. Invoke it from Claude Code or OpenCode:

```
/reporte <circuito>
/reporte <circuito> <fecha_inicio> <fecha_fin>
```

- `circuito` is required and must exist in the dataset.
- `fecha_inicio`/`fecha_fin` are optional **as a pair**: both omitted default to the circuit's
  full available date range; both given are used as-is; giving exactly one is a usage error.

The Skill validates the circuit and date window, confirms once with the user, runs deterministic
critical-point detection plus the MGCECDL/SHAP and automatic min/max simulators, dispatches the
`historical`/`inference`/`auto-simulator` agents in parallel, runs `expert-alignment`, and renders
a single local HTML report. See `.claude/skills/reporte/SKILL.md` for the full contract
(arguments, run sequence, error handling).

Notebook groups (support/exploration, not part of the `/reporte` flow):

- `notebooks/core/`: `03_geo_network_exploration.ipynb` (GEO layer exploration and per-circuit
  mapping) and `04_simulador.ipynb` (interactive what-if simulator, no LLM involved —
  `simulate_feature_values`/`simulate_feature_class_transitions`).
- `notebooks/inference/`: MGCECDL training, evaluation, SHAP, and document-replication notebooks
  (`01` through `06`).
- `notebooks/web/`: `graph_preserved_connections_uiti_vano.ipynb`, expert graph build for the web
  page.

### Tabla base de discusiones desde PDFs

La tabla base de discusiones técnicas verificables se genera con el runbook agente-nativo por
lotes: `chec_local_interpreter.pdf_discussion_pipeline` (Python determinista: conversión de PDF a
Markdown, selección de secciones candidatas, ensamblado del Excel final) junto con el Skill/agente
`pdf-discussion-extraction` (`.claude/skills/pdf-discussion-extraction/`), que clasifica, en un
único turno por PDF, qué secciones candidatas se convierten en fila. Por defecto lee PDFs desde
`reports/analysis-documents/` y guarda allí el Excel final (`tabla_pdfs_intervalo_*.xlsx`). Debe
ejecutarse cada vez que se agreguen, eliminen o cambien PDFs en esa carpeta.

Esta versión no usa embeddings, FAISS, Chroma ni bases vectoriales. Extrae texto de los PDFs,
segmenta secciones candidatas y usa un LLM como skill/agente extractor para decidir si una
discusión debe convertirse en fila. Solo se agregan discusiones con circuito, fecha o intervalo
válido, análisis técnico breve y evidencia textual verificable. Si no hay fecha o evidencia
suficiente, no se agrega la fila.

El Excel resultante contiene exactamente estas columnas y queda como insumo para análisis
posteriores:

- `Circuito`
- `Fecha inicio`
- `Fecha fin`
- `Análisis`
- `Evidencia`

### Flujo de cinco agentes LLM

`/reporte <circuito>` integra cinco roles agente-nativos, cada uno un Skill de Claude Code /
agente de OpenCode con su propio CLI determinista `build-context`/`validate` (nunca una llamada
Python a un proveedor LLM externo):

1. **`pdf-discussion-extraction`**: decide, PDF por PDF, qué secciones candidatas de los reportes
   técnicos expertos se convierten en filas de la tabla de discusión (circuito, fecha/intervalo,
   análisis, evidencia). Corre por separado, antes de `/reporte`, cuando se agregan o cambian PDFs
   en `reports/analysis-documents/` — ver la sección anterior.
2. **`historical`**: diagnóstico base/descriptivo del comportamiento de `UITI_VANO` a partir del
   contexto estructurado y los puntos críticos detectados.
3. **`inference`**: interpreta las señales predictivas MGCECDL/SHAP (importancia de variables y
   modos por escenario, coherencia del grafo estimado, hipótesis predictivas cautelosas).
4. **`auto-simulator`**: interpreta la tabla automática de sensibilidad mínimo/máximo (escenarios
   base vs. mínimo/máximo observado por variable) que `prepare()` calcula como efecto colateral;
   es la única etapa que puede degradarse y omitirse sin detener la ejecución.
5. **`expert-alignment`**: compara los hallazgos de `historical` + `inference` contra la tabla de
   discusión ya extraída de los PDFs expertos, citando coincidencias, diferencias y variables que
   merecen más atención.

`historical`, `inference` y `auto-simulator` se despachan en paralelo cuando el runtime lo
permite (obligatorio en Claude Code); `expert-alignment` corre después, una vez que `historical` e
`inference` terminaron. El reporte HTML final (`render()`) fusiona los cuatro roles anteriores en
un único archivo: el diagnóstico base y de inferencia con sus figuras/grafos, la discusión
automática mínimo/máximo (cuando el simulador tuvo modelo entrenado y eventos suficientes), y la
comparación con reportes expertos. Ver `.claude/skills/reporte/SKILL.md` para la secuencia
completa paso a paso.

## Flujo del proyecto

Diagrama de flujo end-to-end vigente, desde la ingesta de datos hasta la publicación en GitHub
Pages. A diferencia de `docs/project-workflow-analysis.md` (snapshot histórico fechado
2026-07-08, congelado como artefacto de análisis), este diagrama refleja el estado actual: el
skill `/reporte` (`report_pipeline.py`) es el punto de entrada principal ya establecido — no una
introducción reciente — para el flujo checkpoint único de usuario → `prepare()` (contexto +
simuladores MGCECDL/SHAP y mínimo/máximo) → `historical`/`inference`/`auto-simulator` en paralelo
→ `expert-alignment` → `render()`, que produce un único reporte HTML local. El cuaderno
interactivo `core/02_local_uiti_vano_interpretability_v3.ipynb` fue eliminado una vez que este
flujo cubrió por completo sus responsabilidades, incluida su antigua discusión automática
mínimo/máximo de las fases 9-11 (hoy la etapa `auto-simulator`). Fuente Mermaid:
`docs/project-workflow.mmd`.

```mermaid
%% Project workflow — current state
%% Regenerate/verify against: notebooks/, src/chec_local_interpreter/, src/chec_impacto/,
%% .claude/skills/, .claude/agents/ (see README.md "Flujo del proyecto" for context).
flowchart TD
    START([Start]) --> LANE1

    %% ===== Lane: Data ingestion =====
    subgraph LANE1[Data ingestion]
        PDF[(Expert PDFs<br/>reports/analysis-documents)] --> P0[Batch PDF-discussion runbook<br/>pdf_discussion_pipeline.py<br/>skill: pdf-discussion-extraction]
        P0 --> XLSX[(tabla_pdfs_intervalo_*.xlsx)]
        CSV[(Indicadores_vano CSV<br/>data/Indicadores_vano_v3.csv)]
        MET[Open-Meteo API] --> P1[Climate enrichment<br/>inference/01_climate.ipynb]
        CSV --> P1
    end

    %% ===== Lane: ML modeling (chec_impacto) =====
    subgraph LANE2[ML modeling — M-GCECDL]
        P1 --> P2[Optuna hyperparameter search<br/>inference/02_mgcecdl_optuna_classification_search.ipynb]
        VARS[(variables.json /<br/>Variables_seleccion.xlsx)] --> P7[Expert graph build<br/>web/graph_preserved_connections_uiti_vano.ipynb]
        P7 --> ADJ[(adjacency matrix + edges)]
        P2 --> P3[Training on Colab GPU<br/>inference/03_mgcecdl_training.ipynb]
        ADJ --> P3
        P3 --> MODEL[(mgcecdl_classifier_best.zip)]
        MODEL --> P4[Performance evaluation<br/>inference/04_mgcecdl_performance.ipynb]
        MODEL --> P5[Per-circuit SHAP analysis<br/>inference/05_mgcecdl_circuit_analysis.ipynb]
        MODEL --> P6[Document replication<br/>inference/06_mgcecdl_document_replication.ipynb]
    end

    %% ===== Lane: Local interpretation / agents =====
    subgraph LANE3[Local interpretation — agents]
        CSV --> D1[Critical point detection<br/>critical_points.py]
        D1 --> D2[Structured context builder<br/>context_builder.py]
        D2 --> CHK{"Resolve circuito + fecha window<br/>alert+stop if invalid<br/>single confirmation with user"}
        CHK -- "not found / zero events" --> STOP0([Alert + stop, no run_dir created])

        subgraph REPORTE["/reporte skill — primary entry point<br/>report_pipeline.py"]
            direction TB
            CHK -- "confirmed once" --> RP0["prepare()<br/>critical points + context +<br/>MGCECDL/SHAP scenario simulator +<br/>automatic min/max sensitivity simulator"]
            MODEL --> RP0
            RP0 --> FORK{{"fork — mandatory parallel dispatch<br/>historical / inference / auto-simulator"}}
            FORK --> A1[Agent: historical<br/>.claude/skills/historical]
            FORK --> A2[Agent: inference<br/>.claude/skills/inference]
            FORK --> A4[Agent: auto-simulator<br/>.claude/skills/auto-simulator<br/>skipped if bc.json absent;<br/>only stage allowed to degrade/skip]

            A1 --> G1{"Schema + provenance<br/>valid? (historical + inference)"}
            A2 --> G1
            G1 -- "no, retries left<br/>(max 2)" --> RET[Revise response]
            RET --> G1
            G1 -- "no, retries exhausted" --> STOP1([Stop this circuit's run])

            A4 --> G3{"validate() ok?<br/>(auto-simulator)"}
            G3 -- "no, retries left<br/>(max 2)" --> RET3[Revise response]
            RET3 --> G3
            G3 -- "no, exhausted" --> SKIP3["Skip auto-simulator<br/>(degrade, never blocks run)"]

            G1 -- yes --> JOIN{{"join<br/>(auto-simulator optional)"}}
            G3 -- yes --> JOIN
            SKIP3 --> JOIN

            JOIN --> RP1["prepare_expert_alignment()"]
            XLSX --> RP1
            RP1 --> A3[Agent: expert-alignment<br/>.claude/skills/expert-alignment]
            A3 --> G2{Schema + provenance<br/>valid?}
            G2 -- "no, retries left<br/>(max 2)" --> RET2[Revise response]
            RET2 --> G2
            G2 -- "no, retries exhausted" --> STOP2([Stop this circuit's run])
            G2 -- yes --> RP2["render()<br/>plotting.render_llm_analysis<br/>merges historical + inference +<br/>auto-simulator (when available) +<br/>expert-alignment comparison"]
        end
        RP2 --> HTML1[(HTML report<br/>run_dir, single merged output)]

        MODEL --> SIM4["What-if simulator (interactive, no LLM)<br/>core/04_simulador.ipynb<br/>simulate_feature_values() /<br/>simulate_feature_class_transitions()"]
    end

    %% ===== Lane: Publication =====
    subgraph LANE4[Publication]
        P4 --> WE[Web export<br/>web_export.py<br/>export_latest_interpretability_report]
        WE --> SITE[(site/assets/site/results +<br/>Astro pages site/pages)]
        SITE --> CI[GitHub Actions<br/>.github/workflows/deploy-pages.yml]
        CI --> PAGES([GitHub Pages site])
    end

    HTML1 -.->|"manual publish only (by design)"| WE
    PAGES --> END([End])
```

Versión renderizada para lectores sin soporte Mermaid: [`docs/project-workflow.svg`](docs/project-workflow.svg).

### Diagrama BPMN

Vista de proceso de negocio (BPMN 2.0) del mismo flujo, con carriles por responsable (ingesta de
datos, modelado M-GCECDL, agentes LLM, publicación). Es una vista de nivel de fase — para el
detalle técnico módulo por módulo, usar el diagrama Mermaid anterior.

![Diagrama BPMN del flujo del proyecto](docs/project-workflow-bpmn.svg)

Fuente BPMN 2.0 XML (abrible en [bpmn.io](https://bpmn.io) o Camunda Modeler):
[`docs/project-workflow.bpmn`](docs/project-workflow.bpmn).

## Outputs

Structured outputs from the local interpreter are saved under
`reports/interpretability/artifacts/`:

- `structured_context_<timestamp>.json`
- `llm_prompt_<timestamp>.md`
- `critical_points_<timestamp>.csv`
- `uiti_vano_timeseries_<timestamp>.png`
- optional `llm_analysis_<timestamp>.json`
- optional `inference_llm_analysis_<timestamp>.json`
- optional `expert_alignment_context_<timestamp>.json`
- optional `expert_alignment_analysis_<timestamp>.json`
- optional `expert_alignment_pdf_matches_<timestamp>.xlsx`

HTML reports generated by `/reporte`'s `render()` step are saved under
`reports/interpretability/html/`.

Invalid LLM outputs are saved separately with validation errors and are not presented as final
analysis.

## Tests

```bash
pytest -q
python evals/run_llm_eval.py
```
