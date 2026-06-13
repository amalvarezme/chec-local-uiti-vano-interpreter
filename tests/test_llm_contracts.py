from __future__ import annotations

import json

from chec_local_interpreter.llm_contracts import PROMPT_VERSION, load_output_schema, render_prompt


def test_prompt_rendering_includes_context_schema_and_version():
    context = {"selected_context": {"circuitos": ["C1"]}, "critical_points": []}
    schema = load_output_schema()
    prompt = render_prompt(
        context_json=json.dumps(context),
        output_schema_json=json.dumps(schema),
    )
    assert '"C1"' in prompt
    assert "uiti_vano_explanation.output_schema.v1" in prompt
    assert PROMPT_VERSION in prompt
