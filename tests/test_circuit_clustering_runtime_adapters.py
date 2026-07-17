from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ADAPTERS = {
    "claude": PROJECT_ROOT / ".claude" / "skills" / "agrupamiento-circuitos" / "SKILL.md",
    "opencode": PROJECT_ROOT / ".opencode" / "agent" / "agrupamiento-circuitos.md",
    "pi": PROJECT_ROOT / ".pi" / "skills" / "agrupamiento-circuitos" / "SKILL.md",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_runtime_adapter_files_exist():
    for path in ADAPTERS.values():
        assert path.exists()


def test_runtime_invocation_is_explicit_and_uses_date_pair():
    assert "/agrupamiento-circuitos [fecha_inicio fecha_fin]" in _read(ADAPTERS["claude"])
    assert "@agrupamiento-circuitos [fecha_inicio fecha_fin]" in _read(ADAPTERS["opencode"])
    assert "/skill:agrupamiento-circuitos [fecha_inicio fecha_fin]" in _read(ADAPTERS["pi"])


def test_runtime_adapters_point_to_shared_contract_and_confirmation_step():
    for runtime, path in ADAPTERS.items():
        content = _read(path)
        assert "circuit_clustering_contract" in content, runtime
        assert "plot_interactive_circuit_clustering" in content, runtime
        assert "ask" in content.lower() and "confirm" in content.lower(), runtime
        assert "full dataset range" in content, runtime


def test_runtime_adapters_keep_workflow_local_only():
    for runtime, path in ADAPTERS.items():
        normalized = " ".join(_read(path).lower().split())
        assert "local-only" in normalized or "local only" in normalized, runtime
        assert "publish" in normalized, runtime
        assert "external llm" in normalized or "no llm" in normalized, runtime


def test_agents_guide_mentions_new_cross_runtime_skill():
    guide = _read(PROJECT_ROOT / "docs" / "agents-guide.md")

    assert "agrupamiento-circuitos" in guide
    assert "/agrupamiento-circuitos [fecha_inicio fecha_fin]" in guide
    assert "@agrupamiento-circuitos [fecha_inicio fecha_fin]" in guide
    assert "/skill:agrupamiento-circuitos [fecha_inicio fecha_fin]" in guide
