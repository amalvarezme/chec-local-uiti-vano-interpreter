"""Smoke test for the relocated offline LLM eval script.

`sdd/retire-llm-directory` (Phase A2) moves `llm/evals/run_llm_eval.py` to
`evals/run_llm_eval.py`. This test exercises the new load path inside
`pytest -q` itself (the design's accepted-gap mitigation for the manual
`python evals/run_llm_eval.py` invocation), without requiring a live LLM
call — the script's `main()` only renders prompts and validates synthetic,
already-known-good responses.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_SCRIPT = PROJECT_ROOT / "evals" / "run_llm_eval.py"


def _load_run_llm_eval_module():
    spec = importlib.util.spec_from_file_location("run_llm_eval", EVAL_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_eval_runs_from_new_location():
    module = _load_run_llm_eval_module()
    assert module.main() == 0
