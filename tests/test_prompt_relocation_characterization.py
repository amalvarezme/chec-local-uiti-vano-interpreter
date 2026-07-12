"""Golden-snapshot characterization tests pinning the CURRENT, unmoved `llm/`
prompt-source tree (`sdd/retire-llm-directory`, Phase A1).

This is the safety net Phase A2 re-runs, unchanged, immediately after
relocating `llm/skills/` -> `.claude/skills/historical/prompt/` and
`llm/skills_inference/` -> `.claude/skills/inference/prompt/` (plus the
shared prompt/schema assets) to prove the move was byte-identical. NO file
relocation happens in this batch — every assertion here runs against the
pre-move `llm/` tree exactly as it exists today.

Mirrors `tests/test_provenance_characterization.py`'s convention of asserting
the FULL value (never a substring/`in` check), except here the pinned value
is large (KB-scale) prompt text, so it is pinned via committed golden files
under `tests/golden/retire_llm_directory/` rather than inline string
literals, per the design's golden-snapshot mechanism.

Two layers of coverage:
1. Design-mandated bundle/render checks (`assemble_skill_bundle` for both
   profiles + `render_prompt`) — the minimum gate named in
   `sdd/retire-llm-directory/tasks` (A1.1/A1.2) and
   `sdd/retire-llm-directory/design`.
2. Full `agent_tools.historical.build_context()` /
   `agent_tools.inference.build_context()` `prompt` field, pinned against
   representative fixture payloads — the explicit spec requirement
   (`sdd/retire-llm-directory/spec`, Slice A: "Golden-snapshot baseline
   before rewire").
"""

from __future__ import annotations

import json
from pathlib import Path

from chec_impacto.interpretability.circuit_analysis import construir_prompt_inferencia
from chec_local_interpreter.agent_tools.historical import build_context as historical_build_context
from chec_local_interpreter.agent_tools.inference import build_context as inference_build_context
from chec_local_interpreter.llm_contracts import load_output_schema, render_prompt
from chec_local_interpreter.llm_skills import assemble_skill_bundle

GOLDEN_DIR = Path(__file__).parent / "golden" / "retire_llm_directory"


def _read_golden(name: str) -> str:
    path = GOLDEN_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Golden fixture not found: {path}. Run the golden-generation step "
            "against the CURRENT unmoved llm/ tree before relocating anything."
        )
    return path.read_text(encoding="utf-8")


# --- Fixtures: historical (base profile) --------------------------------


def _historical_basic_context() -> dict:
    return {
        "analysis_name": "local_uiti_vano_interpretability",
        "metadata": {
            "v": "test",
            "schema": "test",
            "ts": "2026-01-01T00:00",
            "circuitos": ["DON23L13"],
            "start": "2026-01-01",
            "end": "2026-01-03",
            "unavailable_cols": [],
        },
        "selected_context": {"circuitos": ["DON23L13"], "indicator": "UITI_VANO"},
        "summary": {"events": 2, "nonzero_days": 2, "total_uv": 15.0},
        "daily": [
            {"d": "2026-01-01", "uv": 5.0, "n": 1, "dur": 1.0},
            {"d": "2026-01-02", "uv": 10.0, "n": 1, "dur": 2.0},
        ],
        "critical_points": [
            {
                "critical_point_id": "cp-2026-01-02",
                "fecha_dia": "2026-01-02",
                "rank": 1,
                "score": 2.0,
                "types": ["top_contribution_day"],
                "selection_reason": "El dia aporta una fraccion alta del UITI_VANO total.",
                "metrics": {"UITI_VANO": 10.0},
                "daily_aggregates": {"events": 1},
            }
        ],
        "critical_periods": [],
        "domain": {
            "variable_groups": {
                "Entorno/Riesgo": {"variables": ["NR_T", "DDT"]},
                "Evento/Impacto": {"variables": ["UITI_VANO", "CNT_TRF"]},
            },
            "relationship_rules": [],
        },
        "graph_knowledge": "Grafo no disponible en pruebas.",
    }


def _historical_gaps_context() -> dict:
    """Edge-case variant: multiple circuits, unavailable columns, a critical
    period present (exercises a different branch of the same templates)."""
    context = _historical_basic_context()
    context["metadata"]["circuitos"] = ["DON23L13", "DON23L14"]
    context["metadata"]["unavailable_cols"] = ["NR_T"]
    context["critical_periods"] = [
        {
            "critical_period_id": "period-2026-01-01-2026-01-02",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
            "selection_reason": "Periodo sostenido de UITI_VANO elevado.",
        }
    ]
    return context


# --- Fixtures: inference (inferencia profile) ----------------------------

_ESCENARIO_NOMBRE = "Top P97 por UITI_VANO — período completo"


def _inference_basic_context() -> dict:
    return {
        "circuito_interes": "DON23L13",
        "fecha_inicio": "2026-01-01",
        "fecha_fin": "2026-01-31",
        "fechas_interes": ["2026-01-10"],
        "top_n_vanos": 20,
        "top_vanos_percentile": None,
        "top_k_vars": 20,
        "filtro_uiti_max": None,
        "ventana_climatica_horas": 12,
        "modelo": "mgcecdl_clasificacion",
        "modelo_tipo": "mgcecdl_clasificacion",
        "n_eventos": 10,
        "n_vanos": 5,
        "n_features": 2,
        "features": ["NR_T", "DDT"],
        "graph_feature_order": ["NR_T", "DDT"],
        "estimated_graph_source": "reconstruccion_mgcecdl_rbf",
        "estimated_graph_rbf_sigma": 1.0,
        "graph_html_paths": [
            {
                "escenario": _ESCENARIO_NOMBRE,
                "path": "top_uiti_periodo.html",
                "fuente": "reconstruccion_mgcecdl_rbf",
                "pesos": "normalizados_0_1_por_maximo",
            }
        ],
        "escenarios": [
            {
                "nombre": _ESCENARIO_NOMBRE,
                "criterio": "UITI_VANO_PROM",
                "fechas_interes": [],
                "n_eventos": 10,
                "n_vanos_efectivo": 5,
                "top_k_vars": 20,
                "ventana_climatica_horas": 12,
                "top_variables": [{"nombre": "NR_T", "score_normalizado": 0.9}],
                "modos": [{"nombre": "Entorno, riesgo y clima", "score_normalizado": 0.5}],
                "tabla_top_vanos": [],
                "grafo": {
                    "path": "top_uiti_periodo.html",
                    "fuente": "reconstruccion_mgcecdl_rbf",
                    "pesos": "normalizados_0_1_por_maximo",
                },
            }
        ],
        "metadata": {
            "uiti_vano_es_objetivo": True,
            "features_no_incluyen_objetivo": True,
            "grafo_estimado_desde_reconstruccion": True,
        },
    }


def _inference_multi_scenario_context() -> dict:
    """Edge-case variant: two scenarios, no graph paths, a percentile filter
    set (exercises a different branch of the same compaction/render logic)."""
    context = _inference_basic_context()
    context["top_vanos_percentile"] = 0.97
    context["graph_html_paths"] = []
    context["escenarios"] = context["escenarios"] + [
        {
            "nombre": "Ventana climatica extendida",
            "criterio": "UITI_VANO_MAX",
            "fechas_interes": ["2026-01-15"],
            "n_eventos": 4,
            "n_vanos_efectivo": 2,
            "top_k_vars": 10,
            "ventana_climatica_horas": 24,
            "top_variables": [{"nombre": "DDT", "score_normalizado": 0.7}],
            "modos": [{"nombre": "Evento, impacto", "score_normalizado": 0.4}],
            "tabla_top_vanos": [],
            "grafo": {"path": None, "fuente": None, "pesos": None},
        }
    ]
    return context


# --- Design-mandated checks: assemble_skill_bundle + render_prompt ------


def test_char_base_bundle_matches_golden():
    bundle = assemble_skill_bundle(profile="base")
    assert bundle == _read_golden("base_bundle.md")


def test_char_inference_bundle_matches_golden():
    bundle = assemble_skill_bundle(profile="inferencia")
    assert bundle == _read_golden("inference_bundle.md")


def test_char_base_render_prompt_matches_golden():
    context = _historical_basic_context()
    schema = load_output_schema()
    prompt = render_prompt(
        context_json=json.dumps(context, ensure_ascii=False),
        output_schema_json=json.dumps(schema, ensure_ascii=False),
    )
    assert prompt == _read_golden("base_render_prompt.md")


# --- Spec-mandated checks: build_context() prompt field, per agent ------


def test_char_historical_build_context_prompt_basic():
    envelope = historical_build_context(_historical_basic_context())
    assert envelope["prompt"] == _read_golden("historical_build_context_basic.md")


def test_char_historical_build_context_prompt_gaps():
    envelope = historical_build_context(_historical_gaps_context())
    assert envelope["prompt"] == _read_golden("historical_build_context_gaps.md")


def test_char_inference_build_context_prompt_basic():
    envelope = inference_build_context(_inference_basic_context())
    assert envelope["prompt"] == _read_golden("inference_build_context_basic.md")


def test_char_inference_build_context_prompt_multi_scenario():
    envelope = inference_build_context(_inference_multi_scenario_context())
    assert envelope["prompt"] == _read_golden("inference_build_context_multi_scenario.md")


def test_char_inference_prompt_derivation_matches_construir_prompt_inferencia_directly():
    """Cross-check: `agent_tools.inference.build_context` derives `prompt` via
    `construir_prompt_inferencia(context, assemble_skill_bundle(profile="inferencia"))`
    with no extra transformation — pinning this relationship (not just the
    final string) so a future refactor of the internal call can't silently
    drift `build_context`'s output away from the underlying renderer."""
    context = _inference_basic_context()
    envelope = inference_build_context(context)
    directly_rendered = construir_prompt_inferencia(context, assemble_skill_bundle(profile="inferencia"))
    assert envelope["prompt"] == directly_rendered
