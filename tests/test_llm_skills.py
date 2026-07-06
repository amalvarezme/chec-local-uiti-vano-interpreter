from __future__ import annotations

from chec_impacto.interpretability.circuit_analysis import construir_prompt_inferencia
from chec_local_interpreter.llm_skills import assemble_skill_bundle, list_available_skills, verify_required_skills


def test_all_required_skill_files_exist():
    assert verify_required_skills() == []


def test_skill_bundle_loads():
    bundle = assemble_skill_bundle()
    assert "Constructor de Contexto Estructurado" in bundle
    assert "Validador de Salida del LLM" in bundle
    assert "Reparación Base" in bundle
    assert "Contrato de Salida Base" in bundle
    assert len(list_available_skills()) == 7


def test_inference_skill_bundle_loads():
    assert verify_required_skills(profile="inferencia") == []
    bundle = assemble_skill_bundle(profile="inferencia")
    assert "Contrato de Salida de Inferencia" in bundle
    assert len(list_available_skills(profile="inferencia")) == 6


def test_inference_prompt_uses_skill_contract():
    bundle = assemble_skill_bundle(profile="inferencia")
    prompt = construir_prompt_inferencia(
        {"contexto": {"circuito": "C1"}, "escenarios": [{"nombre": "Escenario A"}]},
        bundle,
    )
    assert "Contrato de Salida de Inferencia" in prompt
    assert '"Escenario A"' in prompt
    assert "## Contrato de salida" not in prompt
    assert "discusion_grafos` debe ser siempre un arreglo/lista de objetos" in prompt


def test_auto_simulator_skill_bundle_loads():
    assert verify_required_skills(profile="auto_simulator") == []
    bundle = assemble_skill_bundle(profile="auto_simulator")
    assert "Contexto del Simulador Automático Mínimo/Máximo" in bundle
    assert "Contrato de Salida del Agente de Simulación Automática" in bundle
    assert len(list_available_skills(profile="auto_simulator")) == 2
