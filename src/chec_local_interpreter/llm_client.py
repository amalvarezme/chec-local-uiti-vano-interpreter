from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMCallResult:
    called: bool
    output_text: str | None = None
    think_content: str | None = None
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
        import html
        from IPython.display import display, HTML, clear_output

        sys_prompt = "INSTRUCCIÓN OBLIGATORIA: Siempre debes estructurar tu cadena de pensamiento (Chain of Thought) detallada paso a paso dentro de etiquetas <think> y </think> obligatoriamente, ANTES de generar la salida final en JSON."
        full_prompt = f"{sys_prompt}\n\n{prompt}"
        
        response = client.chat.completions.create(
            model=selected_model,
            messages=[
                {"role": "user", "content": full_prompt}
            ],
            temperature=0,
            stream=True,
        )
        
        start_time = time.time()
        output_text = ""
        tokens = 0
        in_tokens_est = int(len(full_prompt) / 3.5)
        
        # Display handle for dynamic updates
        clear_output(wait=True)
        display(HTML("<div>⏳ <b>Iniciando conexión con LLM...</b></div>"))
        
        def render_ui(tokens, tps, remaining, out_text, elapsed=None):
            if elapsed is None:
                status = f"<div style='margin-bottom: 10px; font-family: sans-serif;'>⏱️ <b>Procesando...</b> | 🧩 Tokens (In: ~{in_tokens_est} | Out: {tokens}) | 🚀 Vel: {tps:.1f} t/s | ⏳ ETA ref: ~{remaining:.1f}s</div><hr>"
            else:
                status = f"<div style='margin-bottom: 10px; font-family: sans-serif;'>✅ <b>LLM Completado en {elapsed:.1f}s</b> | 🧩 Tokens (In: ~{in_tokens_est} | Out: {tokens}) | 🚀 Velocidad media: {tps:.1f} t/s</div><hr>"
            
            parts = out_text.split("<think>")
            if len(parts) > 1:
                pre = html.escape(parts[0])
                rest = parts[1]
                think_parts = rest.split("</think>")
                think_content = html.escape(think_parts[0])
                
                details_html = f'''
<details style="border: 1px solid #cbd5e1; border-radius: 6px; margin-bottom: 15px; padding: 5px; background-color: #f8fafc; font-family: sans-serif;">
<summary style="cursor: pointer; font-weight: bold; padding: 5px; color: #334155;">🤔 Cadena de Pensamiento (CoT)</summary>
<div style="padding: 10px; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 4px; font-family: monospace; font-size: 0.85em; white-space: pre-wrap; max-height: 400px; overflow-y: auto; color: #475569;">
{think_content}
</div>
</details>
'''
                if len(think_parts) > 1:
                    post = html.escape(think_parts[1])
                    content_html = f"<div style='white-space: pre-wrap; font-family: monospace;'>{pre}</div>{details_html}<div style='font-family: sans-serif; margin-bottom: 5px;'>🎯 <b>Respuesta Final:</b></div><div style='white-space: pre-wrap; font-family: monospace;'>{post}</div>"
                else:
                    content_html = f"<div style='white-space: pre-wrap; font-family: monospace;'>{pre}</div>{details_html}"
            else:
                content_html = f"<div style='white-space: pre-wrap; font-family: monospace;'>{html.escape(out_text)}</div>"
                
            return status + content_html
        
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
                    
                    assumed_total = 3000
                    if tokens > assumed_total:
                        assumed_total = tokens + 1000
                        
                    remaining = (assumed_total - tokens) / tps if tps > 0 else 0
                    
                    ui_html = render_ui(tokens, tps, remaining, output_text)
                    clear_output(wait=True)
                    display(HTML(ui_html))

        elapsed = time.time() - start_time
        tps = tokens / elapsed if elapsed > 0 else 0
        
        final_ui = render_ui(tokens, tps, 0, output_text, elapsed=elapsed)
        clear_output(wait=True)
        display(HTML(final_ui))
        
        think_text = None
        if output_text:
            match = re.search(r'<think>(.*?)(?:</think>|$)', output_text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                think_text = match.group(1).strip()

        # Strip CoT <think> blocks if present so downstream JSON parsers don't fail
        clean_output = output_text
        if clean_output:
            clean_output = re.sub(r'<think>.*?(?:</think>|$)\s*', '', clean_output, flags=re.DOTALL | re.IGNORECASE)
            
        return LLMCallResult(called=True, output_text=clean_output, think_content=think_text, message="LLM call completed successfully.")
    except Exception as e:
        return LLMCallResult(called=True, output_text=None, message=f"LLM call failed: {str(e)}")

def save_cot_html_graph(think_content: str, filepath: Path | str, circuit_name: str = "Desconocido") -> Path:
    from pathlib import Path
    import html
    
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    nodes_html = []
    paragraphs = [p.strip() for p in think_content.split('\n\n') if p.strip()]
    for i, p in enumerate(paragraphs):
        if i > 0:
            nodes_html.append('<div class="arrow">⬇</div>')
        escaped_p = html.escape(p)
        nodes_html.append(f'<div class="node"><div class="node-text">{escaped_p}</div></div>')
        
    nodes_joined = "\n".join(nodes_html)
    
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Reporte Criticidad - Circuito: {circuit_name}</title>
    <style>
        body {{ font-family: sans-serif; background: #f8fafc; padding: 20px; }}
        .node {{ background: white; border: 2px solid #3b82f6; border-radius: 8px; padding: 15px; margin: 10px auto; max-width: 800px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); }}
        .arrow {{ text-align: center; font-size: 24px; color: #94a3b8; margin: 5px; }}
        .node-text {{ white-space: pre-wrap; color: #334155; }}
    </style>
</head>
<body>
    <h2 style="text-align: center; color: #1e293b;">Reporte Criticidad - Circuito: {circuit_name}</h2>
    {nodes_joined}
</body>
</html>"""

    filepath.write_text(html_content, encoding="utf-8")
    return filepath
