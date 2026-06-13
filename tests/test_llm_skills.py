from __future__ import annotations

from chec_local_interpreter.llm_skills import assemble_skill_bundle, list_available_skills, verify_required_skills


def test_all_required_skill_files_exist():
    assert verify_required_skills() == []


def test_skill_bundle_loads():
    bundle = assemble_skill_bundle()
    assert "Structured Context Builder" in bundle
    assert "LLM Output Validator" in bundle
    assert len(list_available_skills()) == 5
