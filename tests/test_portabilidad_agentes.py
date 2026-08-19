"""Los espejos de portabilidad se sostienen solos o no se sostienen.

El intento anterior (`.pi/`) eran espejos escritos a mano y sin verificar. Tres de
diez skills nunca llegaron a tener uno y nadie se entero. Estas pruebas existen
para que ese silencio no vuelva: un skill nuevo sin espejo, un espejo editado a
mano, o un espejo huerfano de un skill retirado ponen la suite en rojo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.portabilidad_agentes import (
    ARGUMENT_HINTS,
    RUNTIMES,
    build_mirrors,
    discover_units,
    verificar,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Marcadores de logica de negocio. Un espejo que los contenga dejo de ser un
# puntero y empezo a ser una segunda fuente de verdad, que es exactamente lo que
# la portabilidad no puede permitirse.
FORBIDDEN_BUSINESS_MARKERS = (
    "build_daily_series",
    "detect_critical_periods",
    "rank_critical_points",
    "render_llm_analysis(",
    "simulate_automatic_minmax_sensitivity(",
    "export_latest_interpretability_report",
)
# `site/assets/site/results` NO esta en la lista a proposito: los espejos lo nombran
# para prohibirlo. Que un espejo diga "no toques esta ruta" es lo contrario de
# duplicar la publicacion, y `test_mirrors_state_the_local_only_boundaries` ya cubre
# que la prohibicion siga ahi.

FORBIDDEN_DIRECT_IMPORTS = (
    "from chec_local_interpreter.critical_points",
    "from chec_local_interpreter.context_builder",
    "from chec_local_interpreter.simulator",
    "from chec_local_interpreter.plotting",
    "from chec_impacto.training",
    "from chec_impacto.interpretability",
)


def _mirror_texts() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in build_mirrors()}


def test_mirrors_on_disk_match_the_generator():
    """`verificar` es la prueba; esto solo la corre dentro de pytest."""

    assert verificar() == 0, (
        "los espejos quedaron desincronizados; corre "
        "`PYTHONPATH=src .venv/bin/python scripts/portabilidad_agentes.py generar`"
    )


def test_every_canonical_unit_has_a_mirror_in_every_runtime():
    units = discover_units()
    assert units, "no se descubrio ninguna unidad canonica en .claude/"

    mirrors = build_mirrors()
    for runtime in RUNTIMES:
        for unit in units:
            expected = (
                runtime.entry_path(unit.name)
                if unit.kind == "entry"
                else runtime.role_path(unit.name)
            )
            assert expected in mirrors, f"falta el espejo {runtime.key} de {unit.name}"
            assert expected.exists(), f"no existe en disco: {expected}"


def test_every_invocable_entry_declares_an_argument_hint():
    """Un skill nuevo obliga a decidir como se teclea, no a heredar el silencio."""

    entries = {unit.name for unit in discover_units() if unit.kind == "entry"}
    assert entries <= set(ARGUMENT_HINTS), sorted(entries - set(ARGUMENT_HINTS))


def test_shared_contract_commands_are_never_hidden_behind_a_bare_python():
    for path, content in _mirror_texts().items():
        assert "PYTHONPATH=src .venv/bin/python" in content, path
        assert "`python`/`python3`" in content, path


def test_mirrors_point_at_their_canonical_contract():
    units = {unit.name: unit for unit in discover_units()}
    for runtime in RUNTIMES:
        for unit in units.values():
            path = (
                runtime.entry_path(unit.name)
                if unit.kind == "entry"
                else runtime.role_path(unit.name)
            )
            assert unit.canonical in path.read_text(encoding="utf-8"), path


def test_mirrors_do_not_duplicate_business_logic():
    for path, content in _mirror_texts().items():
        for marker in FORBIDDEN_BUSINESS_MARKERS:
            assert marker not in content, f"{path} duplica logica de negocio: {marker}"
        for marker in FORBIDDEN_DIRECT_IMPORTS:
            assert marker not in content, f"{path} esquiva el contrato compartido: {marker}"


def test_report_family_mirrors_route_through_the_shared_contract():
    """report, reporte-lote e informe-gerencial hablan con el contrato, no con el dominio."""

    for runtime in RUNTIMES:
        for name in ("report", "reporte-lote", "informe-gerencial"):
            content = runtime.entry_path(name).read_text(encoding="utf-8")
            assert "report_contract" in content, (runtime.key, name)
            assert "report_pipeline.py" in content, (runtime.key, name)
            normalized = " ".join(content.split())
            assert (
                "python -m chec_local_interpreter.report_contract preflight" in normalized
            ), (runtime.key, name)
            assert f"--runtime {runtime.key}" in normalized, (runtime.key, name)


def test_report_mirrors_keep_the_dispatch_rules_that_were_learned_the_hard_way():
    for runtime in RUNTIMES:
        content = " ".join(runtime.entry_path("report").read_text(encoding="utf-8").split())
        assert "one explicit task per role" in content or "one explicit invocation per role" in content
        assert "Never launch several identical workers" in content or "Never dispatch several identical workers" in content
        assert all(rol in content for rol in ("historical", "inference", "expert-alignment"))
        assert "stalled" in content
        assert "record-usage" in content and "record-duration" in content
        assert "verify-usage" in content


def test_model_label_comes_from_declared_evidence_not_from_a_default():
    for runtime in RUNTIMES:
        content = " ".join(runtime.entry_path("report").read_text(encoding="utf-8").split())
        assert "CHEC_LLM_PROVIDER" in content and "CHEC_LLM_MODEL" in content
        assert "Desconocido" in content
        assert "--provider <provider> --model <model>" in content


def test_mirrors_state_the_local_only_boundaries():
    for path, content in _mirror_texts().items():
        normalized = " ".join(content.lower().split())
        assert "no external llm api call" in normalized, path
        assert "no automatic publishing" in normalized, path
        assert "no model training" in normalized, path


def test_opencode_config_points_at_the_project_invariants():
    config = json.loads((PROJECT_ROOT / "opencode.json").read_text(encoding="utf-8"))
    assert ".claude/agents/rules/invariants.md" in config["instructions"]
    assert (PROJECT_ROOT / ".claude/agents/rules/invariants.md").exists()


def test_copilot_repository_instructions_route_to_the_canonical_contract():
    content = (PROJECT_ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert ".github/prompts/" in content
    assert ".github/agents/" in content
    assert "scripts/portabilidad_agentes.py" in content
    assert "PYTHONPATH=src .venv/bin/python" in content


@pytest.mark.parametrize("retired", [".pi"])
def test_the_retired_runtime_tree_stays_retired(retired):
    """`.pi/` se retiro con su resolvedor de modelo; que no vuelva por la puerta de atras."""

    assert not (PROJECT_ROOT / retired).exists()
    contract = (PROJECT_ROOT / "src/chec_local_interpreter/report_contract.py").read_text(
        encoding="utf-8"
    )
    assert "_is_pi_runtime" not in contract
    assert "el-gentleman" not in contract
