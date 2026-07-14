from __future__ import annotations

import json
from typing import Any

from chec_local_interpreter.config import PROMPT_VERSION
from chec_local_interpreter.llm.contracts import render_prompt
from chec_local_interpreter.llm.skills import load_skill_markdown



def compact_base_context(
    context_package: dict[str, Any],
    *,
    max_critical_points: int = 5,
    top_rows_limit: int = 3,
    critical_periods_limit: int = 5,
    relationship_rules_limit: int = 12,
) -> dict[str, Any]:
    """Return a focused base-agent context for JSON repair attempts."""
    critical_points_minimos = [
        {
            "critical_point_id": item.get("critical_point_id"),
            "fecha_dia": item.get("fecha_dia"),
            "metrics": item.get("metrics", {}),
            "selection_reason": item.get("selection_reason"),
            "top_rows": item.get("top_rows", [])[:top_rows_limit],
            "attribution_summary": item.get("attribution_summary", {}),
        }
        for item in context_package.get("critical_points", [])[:max_critical_points]
        if isinstance(item, dict)
    ]
    domain_minimo = context_package.get("domain", {})
    if isinstance(domain_minimo, dict):
        domain_minimo = {
            "variable_groups": domain_minimo.get("variable_groups", {}),
            "relationship_rules": domain_minimo.get("relationship_rules", [])[:relationship_rules_limit],
        }
    return {
        "metadata": context_package.get("metadata", {}),
        "selected_context": context_package.get("selected_context", {}),
        "summary": context_package.get("summary", {}),
        "critical_points": critical_points_minimos,
        "critical_periods": context_package.get("critical_periods", [])[:critical_periods_limit],
        "domain": domain_minimo,
    }


def render_base_repair_prompt(
    context_package: dict[str, Any],
    *,
    prompt_version: str = PROMPT_VERSION,
    top_vanos_percentile: float | int = 97,
    max_critical_points: int = 5,
) -> str:
    """Render the base-agent repair prompt from its dedicated skill."""
    context = compact_base_context(
        context_package,
        max_critical_points=max_critical_points,
    )
    skill = load_skill_markdown("base_06_base_repair.md", profile="base")
    return (
        skill
        .replace("{{CONTEXT_JSON}}", json.dumps(context, ensure_ascii=False, indent=2))
        .replace("{{PROMPT_VERSION}}", str(prompt_version))
        .replace("{{TOP_VANOS_PERCENTILE}}", str(top_vanos_percentile))
    )


def render_compact_base_repair_prompt(
    context_package: dict[str, Any],
    *,
    prompt_version: str = PROMPT_VERSION,
    top_vanos_percentile: float | int = 97,
    max_critical_points: int = 5,
) -> str:
    """Backward-compatible alias for existing notebook/test imports."""
    return render_base_repair_prompt(
        context_package,
        prompt_version=prompt_version,
        top_vanos_percentile=top_vanos_percentile,
        max_critical_points=max_critical_points,
    )
