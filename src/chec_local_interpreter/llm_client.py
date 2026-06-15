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
        import time
        import uuid
        from IPython.display import display, update_display, Markdown

        response = client.chat.completions.create(
            model=selected_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            stream=True,
        )
        
        start_time = time.time()
        output_text = ""
        tokens = 0
        
        # Display handle for dynamic updates
        d_id = str(uuid.uuid4())
        display(Markdown("⏳ **Iniciando conexión con LLM...**"), display_id=d_id)
        
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = delta.content if hasattr(delta, 'content') else ""
            if content:
                output_text += content
                tokens += 1
                
                # Update UI periodically to avoid overwhelming the notebook frontend
                if tokens % 8 == 0:
                    elapsed = time.time() - start_time
                    tps = tokens / elapsed if elapsed > 0 else 0
                    
                    # Assume an average response size of 3000 tokens for ETA
                    assumed_total = 3000
                    if tokens > assumed_total:
                        assumed_total = tokens + 1000
                        
                    remaining = (assumed_total - tokens) / tps if tps > 0 else 0
                    
                    # Format <think> blocks nicely for markdown
                    parts = output_text.split("<think>")
                    if len(parts) > 1:
                        pre = parts[0]
                        rest = parts[1]
                        think_parts = rest.split("</think>")
                        think_content = think_parts[0]
                        
                        formatted_think = "\n\n🤔 **Cadena de Pensamiento (CoT):**\n```text\n" + think_content + "\n```\n\n"
                        
                        if len(think_parts) > 1:
                            post = think_parts[1]
                            display_text = pre + formatted_think + "🎯 **Respuesta Final:**\n" + post
                        else:
                            display_text = pre + formatted_think
                    else:
                        display_text = output_text
                    
                    status = f"⏱️ **Procesando...** | 🧩 Tokens: {tokens} | 🚀 Vel: {tps:.1f} t/s | ⏳ ETA ref: ~{remaining:.1f}s\n\n---\n\n"
                    update_display(Markdown(status + display_text), display_id=d_id)

        elapsed = time.time() - start_time
        tps = tokens / elapsed if elapsed > 0 else 0
        
        parts = output_text.split("<think>")
        if len(parts) > 1:
            pre = parts[0]
            rest = parts[1]
            think_parts = rest.split("</think>")
            think_content = think_parts[0]
            formatted_think = "\n\n🤔 **Cadena de Pensamiento (CoT):**\n```text\n" + think_content + "\n```\n\n"
            if len(think_parts) > 1:
                final_display_text = pre + formatted_think + "🎯 **Respuesta Final:**\n" + think_parts[1]
            else:
                final_display_text = pre + formatted_think
        else:
            final_display_text = output_text
            
        update_display(Markdown(f"✅ **LLM Completado en {elapsed:.1f}s** | 🧩 Total tokens: {tokens} | 🚀 Velocidad media: {tps:.1f} t/s\n\n---\n\n" + final_display_text), display_id=d_id)
        
        # Strip CoT <think> blocks if present so downstream JSON parsers don't fail
        clean_output = output_text
        if clean_output:
            clean_output = re.sub(r'<think>.*?</think>\s*', '', clean_output, flags=re.DOTALL | re.IGNORECASE)
            
        return LLMCallResult(called=True, output_text=clean_output, message="LLM call completed successfully.")
    except Exception as e:
        return LLMCallResult(called=True, output_text=None, message=f"LLM call failed: {str(e)}")
