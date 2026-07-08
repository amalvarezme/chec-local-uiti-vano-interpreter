"""Export Python pipeline outputs to the integrated Astro web page."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

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


def export_latest_interpretability_report(html_path: Path) -> Path:
    """Copy the latest generated analysis report into the Astro results assets."""
    src = Path(html_path)
    if not src.exists():
        raise FileNotFoundError(src)

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _RESULTS_DIR / "latest_interpretability_report.html"
    html = src.read_text(encoding="utf-8")
    html = _copy_report_graphs_and_rewrite_links(html)
    dest.write_text(html, encoding="utf-8")
    return dest


def _copy_report_graphs_and_rewrite_links(html: str) -> str:
    """Expose report graph iframes as site routes instead of local file:// URLs."""
    graph_url_re = re.compile(r"file://[^'\"\s<>]+/interactive_graphs/([^'\"\s<>/]+\.html)")

    def replacer(match: re.Match) -> str:
        url = match.group(0)
        graph_name = Path(match.group(1)).name
        route_name = f"report_graph_{graph_name}"
        src_path = Path(unquote(url.removeprefix("file://")))
        if not src_path.exists():
            fallback = _REPO_ROOT / "reports" / "mgcecdl-results" / "interactive_graphs" / graph_name
            src_path = fallback if fallback.exists() else src_path

        if src_path.exists():
            shutil.copyfile(src_path, _RESULTS_DIR / route_name)

        return f"./{route_name}"

    return graph_url_re.sub(replacer, html)


def export_plotly_figure_html(fig, filename: str, *, include_plotlyjs: str = "cdn") -> Path:
    """Write a Plotly figure as a reusable Astro result HTML artifact."""
    if not filename.endswith(".html"):
        raise ValueError("filename must end with .html")
    if fig is None:
        raise ValueError("fig must be a Plotly figure")

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _RESULTS_DIR / filename
    html = fig.to_html(full_html=True, include_plotlyjs=include_plotlyjs)
    dest.write_text(html, encoding="utf-8")
    return dest


def export_html_map(map_obj, filename: str) -> Path:
    """Write a Folium-like HTML map object as a reusable Astro result artifact."""
    if not filename.endswith(".html"):
        raise ValueError("filename must end with .html")
    if map_obj is None:
        raise ValueError("map_obj must be a map object with save()")
    if not hasattr(map_obj, "save"):
        raise TypeError("map_obj must expose a save(path) method")

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _RESULTS_DIR / filename
    map_obj.save(dest)
    return dest


def export_all(
    *,
    graph_html_path: Path | None = None,
    analysis: dict | None = None,
    latest_report_html_path: Path | None = None,
    lib_root: Path | None = None,
) -> dict[str, Path | None]:
    """Run all exports. Silently skips any step whose source is None or missing."""
    results: dict[str, Path | None] = {"graph": None, "analysis": None, "latest_report": None}

    if graph_html_path is not None:
        try:
            resolved_lib = lib_root or _REPO_ROOT
            results["graph"] = export_circuit_graph(graph_html_path, lib_root=resolved_lib)
        except FileNotFoundError:
            pass

    if analysis is not None:
        results["analysis"] = export_llm_analysis(analysis)

    if latest_report_html_path is not None:
        try:
            results["latest_report"] = export_latest_interpretability_report(latest_report_html_path)
        except FileNotFoundError:
            pass

    return results
