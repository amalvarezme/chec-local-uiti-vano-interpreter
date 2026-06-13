from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMCallResult:
    called: bool
    output_text: str | None = None
    message: str = ""


def call_llm(
    prompt: str,
    *,
    provider: str = "openai",
    model: str | None = None,
    call_enabled: bool = False,
) -> LLMCallResult:
    if not call_enabled:
        return LLMCallResult(called=False, message="CALL_LLM=false; prompt saved without calling the model.")
    if provider.lower() != "openai":
        return LLMCallResult(called=False, message=f"Unsupported LLM provider for local v1: {provider}")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return LLMCallResult(called=False, message="OPENAI_API_KEY is not configured; prompt saved for manual use.")
    try:
        from openai import OpenAI
    except ImportError:
        return LLMCallResult(called=False, message="openai package is not installed; prompt saved for manual use.")

    client = OpenAI(api_key=api_key)
    selected_model = model or os.getenv("LLM_MODEL", "gpt-4.1-mini")
    response = client.responses.create(
        model=selected_model,
        input=prompt,
        temperature=0,
    )
    return LLMCallResult(called=True, output_text=response.output_text, message="LLM call completed.")
