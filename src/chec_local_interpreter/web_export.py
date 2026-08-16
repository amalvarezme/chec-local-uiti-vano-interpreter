"""Export Python pipeline outputs to the integrated Astro web page."""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from urllib.parse import unquote

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _REPO_ROOT / "site" / "assets" / "site" / "results"
_DATA_DIR = _REPO_ROOT / "site" / "data"


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
