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
        from IPython.display import display, Markdown, clear_output, HTML

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
        clear_output(wait=True)
        display(Markdown("⏳ **Iniciando conexión con LLM...**"))
        
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
                    
                    status_md = f"⏱️ **Procesando...** | 🧩 Tokens: {tokens} | 🚀 Vel: {tps:.1f} t/s | ⏳ ETA ref: ~{remaining:.1f}s\n\n---\n\n"
                    
                    clear_output(wait=True)
                    display(Markdown(status_md))
                    
                    # Format <think> blocks using HTML to avoid Markdown sanitizer stripping details tag
                    parts = output_text.split("<think>")
                    if len(parts) > 1:
                        pre = parts[0]
                        if pre.strip():
                            display(Markdown(pre))
                            
                        rest = parts[1]
                        think_parts = rest.split("</think>")
                        think_content = think_parts[0]
                        
                        formatted_think = f'''
<details style="border: 1px solid #cbd5e1; border-radius: 6px; margin-bottom: 15px; padding: 5px; background-color: #f8fafc;">
<summary style="cursor: pointer; font-weight: bold; padding: 5px; color: #334155; list-style-type: '\\25BC  ';">🤔 Cadena de Pensamiento (CoT)</summary>
<div style="padding: 10px; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 4px; font-family: monospace; font-size: 0.85em; white-space: pre-wrap; max-height: 400px; overflow-y: auto; color: #475569;">
{think_content}
</div>
</details>
'''
                        display(HTML(formatted_think))
                        
                        if len(think_parts) > 1:
                            post = think_parts[1]
                            display(Markdown("🎯 **Respuesta Final:**\n\n" + post))
                    else:
                        display(Markdown(output_text))

        elapsed = time.time() - start_time
        tps = tokens / elapsed if elapsed > 0 else 0
        
        status_md = f"✅ **LLM Completado en {elapsed:.1f}s** | 🧩 Total tokens: {tokens} | 🚀 Velocidad media: {tps:.1f} t/s\n\n---\n\n"
        clear_output(wait=True)
        display(Markdown(status_md))
        
        parts = output_text.split("<think>")
        if len(parts) > 1:
            pre = parts[0]
            if pre.strip():
                display(Markdown(pre))
                
            rest = parts[1]
            think_parts = rest.split("</think>")
            think_content = think_parts[0]
            formatted_think = f'''
<details style="border: 1px solid #cbd5e1; border-radius: 6px; margin-bottom: 15px; padding: 5px; background-color: #f8fafc;">
<summary style="cursor: pointer; font-weight: bold; padding: 5px; color: #334155; list-style-type: '\\25BC  ';">🤔 Cadena de Pensamiento (CoT)</summary>
<div style="padding: 10px; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 4px; font-family: monospace; font-size: 0.85em; white-space: pre-wrap; max-height: 400px; overflow-y: auto; color: #475569;">
{think_content}
</div>
</details>
'''
            display(HTML(formatted_think))
            if len(think_parts) > 1:
                display(Markdown("🎯 **Respuesta Final:**\n\n" + think_parts[1]))
        else:
            display(Markdown(output_text))
        
        # Strip CoT <think> blocks if present so downstream JSON parsers don't fail
        clean_output = output_text
        if clean_output:
            clean_output = re.sub(r'<think>.*?</think>\s*', '', clean_output, flags=re.DOTALL | re.IGNORECASE)
            
        return LLMCallResult(called=True, output_text=clean_output, message="LLM call completed successfully.")
    except Exception as e:
        return LLMCallResult(called=True, output_text=None, message=f"LLM call failed: {str(e)}")
