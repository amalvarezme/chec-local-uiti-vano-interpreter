from __future__ import annotations

from chec_impacto.interpretability.circuit_analysis import construir_prompt_inferencia
from chec_local_interpreter.llm_skills import assemble_skill_bundle, list_available_skills, verify_required_skills


def test_all_required_skill_files_exist():
    assert verify_required_skills() == []


def test_skill_bundle_loads():
    bundle = assemble_skill_bundle()
    assert "Structured Context Builder" in bundle
    assert "LLM Output Validator" in bundle
    assert "Base Repair" in bundle
    assert "Base Output Contract" in bundle
    assert len(list_available_skills()) == 7


def test_inference_skill_bundle_loads():
    assert verify_required_skills(profile="inferencia") == []
    bundle = assemble_skill_bundle(profile="inferencia")
    assert "Inference Output Contract" in bundle
    assert len(list_available_skills(profile="inferencia")) == 6


def test_inference_prompt_uses_skill_contract():
    bundle = assemble_skill_bundle(profile="inferencia")
    prompt = construir_prompt_inferencia(
        {"contexto": {"circuito": "C1"}, "escenarios": [{"nombre": "Escenario A"}]},
        bundle,
    )
    assert "Inference Output Contract" in prompt
    assert '"Escenario A"' in prompt
    assert "## Contrato de salida" not in prompt
    assert "discusion_grafos` debe ser siempre un arreglo/lista de objetos" in prompt
