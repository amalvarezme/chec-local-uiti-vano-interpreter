"""Export Python pipeline outputs to the integrated Astro web page."""
from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _REPO_ROOT / "src" / "assets" / "site" / "results"
_DATA_DIR = _REPO_ROOT / "src" / "data"


def _inline_lib_script(html: str, lib_root: Path) -> str:
    """Replace <script src="lib/..."> with inlined script content."""
    def replacer(m: re.Match) -> str:
        rel = m.group(1)
        candidate = lib_root / rel
        if candidate.exists():
            return f"<script>\n{candidate.read_text(encoding='utf-8')}\n</script>"
        return m.group(0)

    return re.sub(r'<script src="(lib/[^"]+)"></script>', replacer, html)


def export_circuit_graph(graph_html_path: Path, *, lib_root: Path | None = None) -> Path:
    """Copy and self-contain a pyvis graph HTML into the Astro results assets folder.

    Returns the destination path.
    """
    src = Path(graph_html_path)
    if not src.exists():
        raise FileNotFoundError(src)

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _RESULTS_DIR / "grafo_circuito.html"

    html = src.read_text(encoding="utf-8")
    # lib_root is the repo root (parent of lib/), so lib/bindings/utils.js resolves correctly
    resolved_lib = lib_root if lib_root is not None else _REPO_ROOT
    html = _inline_lib_script(html, resolved_lib)

    dest.write_text(html, encoding="utf-8")
    return dest


def export_llm_analysis(analysis: dict) -> Path:
    """Write the LLM analysis result to the Astro data folder.

    The dict must match uiti_vano_explanation.output_schema.json.
    Returns the destination path.
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest = _DATA_DIR / "interpretabilidad.json"
    payload = {"disponible": True, "analisis": analysis}
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def export_all(
    *,
    graph_html_path: Path | None = None,
    analysis: dict | None = None,
    lib_root: Path | None = None,
) -> dict[str, Path | None]:
    """Run all exports. Silently skips any step whose source is None or missing."""
    results: dict[str, Path | None] = {"graph": None, "analysis": None}

    if graph_html_path is not None:
        try:
            resolved_lib = lib_root or _REPO_ROOT
            results["graph"] = export_circuit_graph(graph_html_path, lib_root=resolved_lib)
        except FileNotFoundError:
            pass

    if analysis is not None:
        results["analysis"] = export_llm_analysis(analysis)

    return results
