from __future__ import annotations

from pathlib import Path

from chec_local_interpreter.config import agent_prompt_dir

REQUIRED_SKILLS = (
    "01_structured_context_builder.md",
    "02_critical_point_interpreter.md",
    "03_uiti_vano_behavior_explainer.md",
    "04_domain_grounding_guardrails.md",
    "05_llm_output_validator.md",
    "06_base_repair.md",
    "07_base_output_contract.md",
)

INFERENCE_REQUIRED_SKILLS = (
    "01_structured_context_builder.md",
    "02_circuit_scenario_interpreter.md",
    "03_uiti_vano_behavior_explainer.md",
    "04_graph_connectivity_guardrails.md",
    "05_llm_output_validator.md",
    "06_inference_output_contract.md",
)

EXPERT_ALIGNMENT_REQUIRED_SKILLS = (
    "01_pdf_report_comparison.md",
    "02_predictive_variable_prioritization.md",
    "03_graph_context_for_alignment.md",
    "04_prior_report_continuity.md",
)

AUTO_SIMULATOR_REQUIRED_SKILLS = (
    "01_auto_minmax_sensitivity_context.md",
    "02_auto_minmax_sensitivity_output_contract.md",
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
    # All profiles (sdd/retire-llm-directory, per-profile incremental
    # repoint, design D3): base/historical, inferencia/inference,
    # expert_alignment/pdf_report_comparison, and
    # auto_simulator/simulador_automatico resolve to their code-owned
    # `.claude/skills/<agent>/prompt/` home. The repo-root `llm/` tree and its
    # resolver were removed from `config.py` in Slice E.
    if profile == "base":
        return agent_prompt_dir("historical")
    if profile == "inferencia":
        return agent_prompt_dir("inference")
    if profile in {"expert_alignment", "pdf_report_comparison"}:
        return agent_prompt_dir("expert-alignment")
    if profile in {"auto_simulator", "simulador_automatico"}:
        return agent_prompt_dir("auto-simulator")
    raise ValueError("profile debe ser 'base', 'inferencia', 'expert_alignment' o 'auto_simulator'.")


def list_available_skills(base_dir: str | Path | None = None, *, profile: str = "base") -> list[str]:
    directory = skills_dir(base_dir, profile=profile)
    if not directory.exists():
        return []
    return sorted(path.name for path in directory.glob("*.md"))


def verify_required_skills(base_dir: str | Path | None = None, *, profile: str = "base") -> list[str]:
    directory = skills_dir(base_dir, profile=profile)
    return [name for name in _required_skills(profile) if not (directory / name).exists()]


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
    for name in _required_skills(profile):
        parts.append(f"# Skill: {name}\n\n{load_skill_markdown(name, base_dir, profile=profile).strip()}")
    return "\n\n---\n\n".join(parts)
