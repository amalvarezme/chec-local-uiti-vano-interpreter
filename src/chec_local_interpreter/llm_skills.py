from __future__ import annotations

from pathlib import Path

from chec_local_interpreter.config import llm_root

REQUIRED_SKILLS = (
    "01_structured_context_builder.md",
    "02_critical_point_interpreter.md",
    "03_uiti_vano_behavior_explainer.md",
    "04_domain_grounding_guardrails.md",
    "05_llm_output_validator.md",
)


def skills_dir(base_dir: str | Path | None = None) -> Path:
    return Path(base_dir) if base_dir is not None else llm_root() / "skills"


def list_available_skills(base_dir: str | Path | None = None) -> list[str]:
    directory = skills_dir(base_dir)
    if not directory.exists():
        return []
    return sorted(path.name for path in directory.glob("*.md"))


def verify_required_skills(base_dir: str | Path | None = None) -> list[str]:
    directory = skills_dir(base_dir)
    return [name for name in REQUIRED_SKILLS if not (directory / name).exists()]


def load_skill_markdown(name: str, base_dir: str | Path | None = None) -> str:
    path = skills_dir(base_dir) / name
    if not path.exists():
        raise FileNotFoundError(f"Skill file not found: {path}")
    return path.read_text(encoding="utf-8")


def assemble_skill_bundle(base_dir: str | Path | None = None) -> str:
    missing = verify_required_skills(base_dir)
    if missing:
        raise FileNotFoundError(f"Missing required skill files: {', '.join(missing)}")
    parts = []
    for name in REQUIRED_SKILLS:
        parts.append(f"# Skill: {name}\n\n{load_skill_markdown(name, base_dir).strip()}")
    return "\n\n---\n\n".join(parts)
