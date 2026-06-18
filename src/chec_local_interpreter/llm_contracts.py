from __future__ import annotations

import json
from pathlib import Path

from chec_local_interpreter.config import PROMPT_VERSION, SCHEMA_VERSION, llm_root

SYSTEM_PROMPT_FILE = "uiti_vano_explanation.system.md"
USER_PROMPT_FILE = "uiti_vano_explanation.user.md"
OUTPUT_SCHEMA_FILE = "uiti_vano_explanation.output_schema.json"


def prompts_dir(base_dir: str | Path | None = None) -> Path:
    return Path(base_dir) if base_dir is not None else llm_root() / "prompts"


def load_prompt_template(name: str, base_dir: str | Path | None = None) -> str:
    path = prompts_dir(base_dir) / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def load_output_schema(base_dir: str | Path | None = None) -> dict:
    path = prompts_dir(base_dir) / OUTPUT_SCHEMA_FILE
    if not path.exists():
        raise FileNotFoundError(f"Output schema not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def schema_for_prompt(output_schema_json: str) -> str:
    """Strip root JSON-Schema meta-keywords before showing the schema to the model.

    Embedding ``$schema``/``$id`` invites weaker models to copy them into the answer,
    which then fails validation under ``additionalProperties: false``. They are pure
    metadata, so dropping them from the prompt is safe and keeps the contract intact.
    Falls back to the original string if it is not parseable JSON.
    """
    try:
        schema = json.loads(output_schema_json)
    except (json.JSONDecodeError, TypeError):
        return output_schema_json
    if not isinstance(schema, dict):
        return output_schema_json
    cleaned = {key: value for key, value in schema.items() if not str(key).startswith("$")}
    return json.dumps(cleaned, ensure_ascii=False)


def render_prompt(
    *,
    context_json: str,
    output_schema_json: str,
    prompt_version: str = PROMPT_VERSION,
    base_dir: str | Path | None = None,
) -> str:
    system = load_prompt_template(SYSTEM_PROMPT_FILE, base_dir)
    user_template = load_prompt_template(USER_PROMPT_FILE, base_dir)
    user = user_template.format(
        context_json=context_json,
        output_schema_json=schema_for_prompt(output_schema_json),
        prompt_version=prompt_version,
    )
    return f"{system.strip()}\n\n---\n\n{user.strip()}\n"



def save_prompt_artifact(prompt: str, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(prompt, encoding="utf-8")
    return target


def save_schema_artifact(schema: dict, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
