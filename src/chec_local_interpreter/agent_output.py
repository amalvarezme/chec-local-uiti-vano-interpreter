"""Shared helper for loading validated per-agent run artifacts.

Extracted out of `report_pipeline.py` (task 1.3, prior-report reuse design)
so `expert_alignment.py` can reuse the SAME validated-output loader for
prior-run discovery/normalization (`seleccionar_reporte_previo_mas_reciente`,
`normalizar_reporte_previo_como_matches`) without creating a circular
import: `report_pipeline.py` imports names FROM `expert_alignment.py` at
module load time, so `expert_alignment.py` importing back from
`report_pipeline.py` would be circular. Both modules import from here
instead -- a single, dependency-free leaf module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ReportPipelineError(ValueError):
    """Raised when the report pipeline cannot proceed for a given circuit or run_dir.

    Subclasses `ValueError` so existing `except ValueError` handling upstream
    keeps working, while giving callers/tests a specific type to catch.
    """


def load_validated_agent_output(run_dir: Path, agent_name: str) -> dict[str, Any]:
    """Read `{agent_name}.out.json` and require the combined L1 `validate()`
    success shape `{"ok": true, "data": {...}}`.

    Raises `ReportPipelineError` if the file is absent (the Skill never
    produced a validated output — e.g. retries exhausted), present but not
    a successful envelope (`ok` missing/false, or malformed JSON shape), or
    the envelope is otherwise valid but its `data` payload is not itself a
    dict (e.g. a list, from a partial/buggy write — Judgment Day Round 2
    CRITICAL fix: a schema-invalid-but-JSON-valid prior output must never
    reach callers as if it were a usable record, since every caller
    immediately does dict-shaped access like `data.get(...)`).
    """
    path = run_dir / f"{agent_name}.out.json"
    if not path.exists():
        raise ReportPipelineError(
            f"Missing validated output for agent '{agent_name}' at {path} "
            "(the Skill has not produced a passing validate() result yet, "
            "or validation retries were exhausted without success)."
        )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("ok") is not True or "data" not in payload:
        raise ReportPipelineError(
            f"Validated output for agent '{agent_name}' at {path} is not a "
            "successful envelope (expected {'ok': true, 'data': ...})."
        )
    data = payload["data"]
    if not isinstance(data, dict):
        raise ReportPipelineError(
            f"Validated output for agent '{agent_name}' at {path} has a "
            f"non-dict 'data' payload (expected an object, got {type(data).__name__})."
        )
    return data
