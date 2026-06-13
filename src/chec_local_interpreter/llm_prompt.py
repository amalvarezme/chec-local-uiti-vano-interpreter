from __future__ import annotations

import json
from typing import Any

from chec_local_interpreter.llm_contracts import render_prompt


def build_llm_prompt(context_package: dict[str, Any], output_schema: dict[str, Any] | None = None) -> str:
    schema = output_schema or {}
    return render_prompt(
        context_json=json.dumps(context_package, ensure_ascii=False, indent=2),
        output_schema_json=json.dumps(schema, ensure_ascii=False, indent=2),
    )
