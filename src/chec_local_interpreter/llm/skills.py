from __future__ import annotations

from pathlib import Path

from chec_local_interpreter.config import llm_root

SHARED_REQUIRED_SKILLS = (
    "shared_01_json_output_safety.md",
    "shared_02_chec_domain_language.md",
    "shared_03_model_graph_guardrails.md",
)

REQUIRED_SKILLS = (
    "base_01_structured_context_builder.md",
    "base_02_critical_point_interpreter.md",
    "base_03_uiti_vano_behavior_explainer.md",
    "base_04_domain_grounding_guardrails.md",
    "base_05_llm_output_validator.md",
    "base_06_base_repair.md",
    "base_07_base_output_contract.md",
)

INFERENCE_REQUIRED_SKILLS = (
    "inference_01_structured_context_builder.md",
    "inference_02_circuit_scenario_interpreter.md",
    "inference_03_uiti_vano_behavior_explainer.md",
    "inference_04_graph_connectivity_guardrails.md",
    "inference_05_llm_output_validator.md",
    "inference_06_inference_output_contract.md",
)

EXPERT_ALIGNMENT_REQUIRED_SKILLS = (
    "expert_alignment_01_pdf_report_comparison.md",
    "expert_alignment_02_predictive_variable_prioritization.md",
    "expert_alignment_03_graph_context_for_alignment.md",
)

AUTO_SIMULATOR_REQUIRED_SKILLS = (
    "auto_simulator_01_auto_minmax_sensitivity_context.md",
    "auto_simulator_02_auto_minmax_sensitivity_output_contract.md",
)


def _required_skills(profile: str = "base") -> tuple[str, ...]:
    if profile == "base":
        return REQUIRED_SKILLS
    if profile == "inferencia":
        return INFERENCE_REQUIRED_SKILLS
    if profile in {"expert_alignment", "pdf_report_comparison"}:
        return EXPERT_ALIGNMENT_REQUIRED_SKILLS
    if profile in {"auto_simulator", "simulador_automatico"}:
        return AUTO_SIMULATOR_REQUIRED_SKILLS
    raise ValueError("profile debe ser 'base', 'inferencia', 'expert_alignment' o 'auto_simulator'.")


def skills_dir(base_dir: str | Path | None = None, *, profile: str = "base") -> Path:
    if base_dir is not None:
        return Path(base_dir)
    return llm_root() / "skills"


def list_available_skills(base_dir: str | Path | None = None, *, profile: str = "base") -> list[str]:
    directory = skills_dir(base_dir, profile=profile)
    if not directory.exists():
        return []
    return sorted(path.name for path in directory.glob(f"{_profile_prefix(profile)}_*.md"))


def _profile_prefix(profile: str) -> str:
    if profile == "base":
        return "base"
    if profile == "inferencia":
        return "inference"
    if profile in {"expert_alignment", "pdf_report_comparison"}:
        return "expert_alignment"
    if profile in {"auto_simulator", "simulador_automatico"}:
        return "auto_simulator"
    raise ValueError("profile debe ser 'base', 'inferencia', 'expert_alignment' o 'auto_simulator'.")


def verify_required_skills(base_dir: str | Path | None = None, *, profile: str = "base") -> list[str]:
    directory = skills_dir(base_dir, profile=profile)
    missing = [name for name in _required_skills(profile) if not (directory / name).exists()]
    if base_dir is None:
        missing.extend(name for name in SHARED_REQUIRED_SKILLS if not (directory / name).exists())
    return missing


def load_skill_markdown(name: str, base_dir: str | Path | None = None, *, profile: str = "base") -> str:
    path = skills_dir(base_dir, profile=profile) / name
    if not path.exists():
        raise FileNotFoundError(f"Skill file not found: {path}")
    return path.read_text(encoding="utf-8")


def assemble_skill_bundle(base_dir: str | Path | None = None, *, profile: str = "base") -> str:
    missing = verify_required_skills(base_dir, profile=profile)
    if missing:
        raise FileNotFoundError(f"Missing required skill files: {', '.join(missing)}")
    parts = []
    if base_dir is None:
        for name in SHARED_REQUIRED_SKILLS:
            parts.append(f"# Shared Skill: {name}\n\n{load_skill_markdown(name, base_dir, profile=profile).strip()}")
    for name in _required_skills(profile):
        parts.append(f"# Skill: {name}\n\n{load_skill_markdown(name, base_dir, profile=profile).strip()}")
    return "\n\n---\n\n".join(parts)
