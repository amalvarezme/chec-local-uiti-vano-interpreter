from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMCallResult:
    called: bool
    output_text: str | None = None
    message: str = ""


def call_llm(
    prompt: str,
    *,
    provider: str = "google",
    model: str | None = "gemini-2.5-flash-lite",
    call_enabled: bool = False,
) -> LLMCallResult:
    if not call_enabled:
        return LLMCallResult(called=False, message="CALL_LLM=false; prompt saved without calling the model.")
    
    if provider.lower() not in ["google", "openai", "ollama"]:
        return LLMCallResult(called=False, message=f"Unsupported LLM provider for local v1: {provider}")
        
    if provider.lower() == "google":
        api_key = os.getenv("GOOGLE_API_KEY")
        base_url = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
        if not api_key:
            return LLMCallResult(called=False, message="GOOGLE_API_KEY is not configured; prompt saved for manual use.")
    elif provider.lower() == "ollama":
        api_key = "ollama"  # Dummy key required by OpenAI client
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        if not api_key:
            return LLMCallResult(called=False, message="OPENAI_API_KEY is not configured; prompt saved for manual use.")
    try:
        from openai import OpenAI
    except ImportError:
        return LLMCallResult(called=False, message="openai package is not installed; prompt saved for manual use.")

    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    selected_model = model or os.getenv("LLM_MODEL", "gemini-2.5-flash-lite")
    
    try:
        response = client.chat.completions.create(
            model=selected_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        output_text = response.choices[0].message.content
        
        # Strip CoT <think> blocks if present so downstream JSON parsers don't fail
        if output_text:
            output_text = re.sub(r'<think>.*?</think>\s*', '', output_text, flags=re.DOTALL | re.IGNORECASE)
            
        return LLMCallResult(called=True, output_text=output_text, message="LLM call completed.")
    except Exception as e:
        return LLMCallResult(called=True, output_text=None, message=f"LLM call failed: {str(e)}")
