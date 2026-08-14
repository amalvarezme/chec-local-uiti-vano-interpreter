"""Smoke test for the relocated offline LLM eval script.

`sdd/retire-llm-directory` (Phase A2) moves `llm/evals/run_llm_eval.py` to
`evals/run_llm_eval.py`. This test exercises the new load path inside
`pytest -q` itself (the design's accepted-gap mitigation for the manual
`python evals/run_llm_eval.py` invocation), without requiring a live LLM
call — the script's `main()` only renders prompts and validates synthetic,
already-known-good responses.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_SCRIPT = PROJECT_ROOT / "evals" / "run_llm_eval.py"


def _load_run_llm_eval_module():
    spec = importlib.util.spec_from_file_location("run_llm_eval", EVAL_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_eval_runs_from_new_location():
    module = _load_run_llm_eval_module()
    assert module.main() == 0


# --- Cobertura por rol: los tres que el informe despacha ---------------------------


def test_every_agent_role_of_the_report_has_a_fixture():
    """La eval cubria `historical` y `expert-alignment` pero no `inference`, que es el
    rol que interpreta el modelo MIL -- la parte mas nueva del flujo y la unica con
    guardas propias (metrica, escenario citable, ventana citable). Sin fixture, un
    cambio en `inference_validation` no rompia nada aqui y la compuerta pasaba igual.

    Se comprueba la PRESENCIA del fixture por su glob, que es como `main()` los
    encuentra: un archivo con otro nombre existe pero no se ejecuta nunca.
    """
    fixtures = PROJECT_ROOT / "evals" / "fixtures"
    for glob in ("synthetic_historical_context_*.json",
                 "synthetic_expert_alignment_context_*.json",
                 "synthetic_inference_context_*.json"):
        assert sorted(fixtures.glob(glob)), f"sin fixture para {glob}"


def test_the_inference_fixture_declares_the_mil_contract():
    """El contexto de inferencia de HOY lo arma `construir_contexto_inferencia_mil`, y
    declara explicitamente modelo, unidad y metrica. Un fixture que no las traiga estaria
    validando el contrato de MGCECDL, que es el que se retiro."""
    import json

    fixture = next((PROJECT_ROOT / "evals" / "fixtures").glob("synthetic_inference_context_*.json"))
    context = json.loads(fixture.read_text(encoding="utf-8"))

    assert context["modelo_tipo"] == "mil_bolsas"
    assert context["metrica"] == "uiti_acumulado"
    assert context["unidad"] == "bolsa (vano, ventana)"
    # El escenario ES una ventana desde el port al MIL: sin `ventanas` declaradas el
    # agente no puede nombrar la ventana de la que habla sin salirse del universo.
    assert context["ventanas"]
    assert {e["ventana"] for e in context["escenarios"]} <= set(context["ventanas"])
    # Y nada del contrato viejo: el grafo se reconstruye de las compuertas del propio
    # MIL, no de una aproximacion RBF sobre otro modelo.
    assert "estimated_graph_rbf_sigma" not in context


def test_the_inference_response_passes_both_stages():
    """Las dos etapas, como las corre el verbo `validate` del agente: esquema+guardas
    primero, provenance despues. La eval fallaria en silencio si solo corriera la
    primera."""
    import json

    from chec_local_interpreter.inference_validation import (
        validar_provenance_inferencia,
        validar_respuesta_inferencia_strict,
    )

    module = _load_run_llm_eval_module()
    fixture = next((PROJECT_ROOT / "evals" / "fixtures").glob("synthetic_inference_context_*.json"))
    context = json.loads(fixture.read_text(encoding="utf-8"))

    respuesta = json.dumps(module._valid_inference_output(context), ensure_ascii=False)
    esquema = validar_respuesta_inferencia_strict(respuesta, context)
    assert esquema["ok"], esquema["errors"]

    provenance = validar_provenance_inferencia(esquema["data"], context)
    assert provenance["ok"], provenance["errors"]


def test_the_inference_response_carries_provenance_on_both_sections():
    """`validar_provenance_inferencia` mira `escenarios` y `discusion_grafos`, y la
    provenance es OPCIONAL por item: una respuesta sin ella pasa sin ejercer nada. Que
    la traigan las dos secciones es lo que convierte a la eval en una compuerta real."""
    import json

    module = _load_run_llm_eval_module()
    fixture = next((PROJECT_ROOT / "evals" / "fixtures").glob("synthetic_inference_context_*.json"))
    context = json.loads(fixture.read_text(encoding="utf-8"))

    salida = module._valid_inference_output(context)
    for seccion in ("escenarios", "discusion_grafos"):
        assert any("provenance" in item for item in salida[seccion]), seccion
