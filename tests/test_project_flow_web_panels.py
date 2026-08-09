"""Contract tests for the four `project_flow` dashboard notebooks (01-04).

These notebooks are the project's user-facing boards. They share one contract
that is easy to break with an innocent-looking edit and expensive to notice --
the failure mode is a board that still renders but collapses to a narrow column,
or a map that centres on the right circuit while clipping it top and bottom.

The contract, verified here against the committed notebook sources (no
execution, so this stays fast):

  1. Every board writes the SAME self-contained HTML it renders inline to
     `reports/paneles/` and opens it in the browser, behind `ABRIR_EN_NAVEGADOR`.
  2. The figure carries NO fixed `width`, `to_html` is called with
     `default_width='100%'` and `config={'responsive': True}`, and the control
     panel is not pinned to a pixel width either. All three are required: with
     any one missing the board stops following the viewport.
  3. `03`/`04` frame their map with a real Web Mercator `fitBounds` measured on
     the live canvas, and redo it on `resize`. The old zoom-from-degrees formula
     assumed a fixed-width map and clipped circuits once the figure went fluid.
  4. `03`/`04` expose no CSV download control.
  5. No notebook carries regional Spanish or stale `01.x` cross-references; the
     prose is meant to read as neutral, simple Spanish.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

NOTEBOOK_DIR = Path(__file__).resolve().parents[1] / "notebooks" / "project_flow"

# `05` and `06` are deliberately excluded: they are ipywidgets/simulator
# notebooks, not static HTML+JS boards, and do not share this contract.
BOARDS = {
    "01": "01_uiti_vano_clima",
    "02": "02_uiti_vano_kmeans",
    "03": "03_uiti_vano_trayectorias_circuitos",
    "04": "04_uiti_vano_trayectorias_vano",
}
# Boards carrying a geographic map, which must frame it against the live canvas.
MAP_BOARDS = ["01", "03", "04"]
# Boards the CSV download control was removed from. `02` deliberately keeps its own.
NO_CSV_BOARDS = ["03", "04"]


def _source(name: str) -> str:
    notebook = json.loads((NOTEBOOK_DIR / f"{name}.ipynb").read_text(encoding="utf-8"))
    return "\n".join("".join(cell["source"]) for cell in notebook["cells"])


@pytest.fixture(scope="module")
def sources() -> dict[str, str]:
    return {key: _source(name) for key, name in BOARDS.items()}


@pytest.mark.parametrize("board", sorted(BOARDS))
def test_board_exports_itself_to_reports_paneles_and_opens_a_browser(sources, board):
    src = sources[board]
    assert "ABRIR_EN_NAVEGADOR" in src, "the browser export must stay switchable"
    assert "webbrowser.open(" in src
    assert f"'reports' / 'paneles' / '{BOARDS[board]}.html'" in src or (
        f"'reports' / 'paneles' / '{BOARDS[board]}.html'".replace("'", '"') in src
    )


@pytest.mark.parametrize("board", sorted(BOARDS))
def test_board_figure_is_fluid_not_pinned_to_pixels(sources, board):
    src = sources[board]
    assert "default_width='100%'" in src, "to_html must let the div decide the width"
    assert "config={'responsive': True}" in src, "the figure must follow window resizes"
    # A `width=` inside `update_layout` overrides `default_width` and silently
    # freezes the board at that pixel count.
    assert not re.search(r"^\s+height=\d+,\s*width=\d+", src, re.MULTILINE), (
        "the figure layout must not declare a fixed width"
    )
    # The control panel sits directly above the figure; pinning it to
    # `fig.layout.width` px both breaks alignment and crashes once `width` is gone.
    assert "{fig.layout.width}px" not in src


@pytest.mark.parametrize("board", MAP_BOARDS)
def test_map_boards_frame_with_web_mercator_fitbounds(sources, board):
    src = sources[board]
    assert "function mercatorY(" in src, "framing must project latitude, not use degrees"
    assert "function encuadrarCircuito(" in src
    # The zoom has to come from the canvas actually on screen, not from a constant.
    assert "maplibregl-map" in src and "getBoundingClientRect()" in src
    assert "window.addEventListener('resize'" in src, "a resize must re-frame the map"
    # The superseded formula: zoom from the larger span in DEGREES.
    assert "Math.log(360 / span)" not in src


@pytest.mark.parametrize("board", MAP_BOARDS)
def test_map_boards_zoom_ceiling_is_high_enough_to_never_bind(sources, board):
    """The ceiling guards the degenerate case; it must not quietly re-freeze the zoom.

    Measured over the 208 circuits with geometry, the tightest framing any of them asks for
    is zoom 16.9, so 17 only ever catches a null extent. At 15 -- the value first shipped --
    the ceiling bound for 22% of `01`'s circuits on a 2560 px screen (its map is 842 px tall,
    twice `03`/`04`'s, so it saturates far sooner) and 2% of `03`/`04`'s. Saturating means
    falling back to a fixed zoom, which is exactly what this framing replaced, and it does so
    on the SMALL circuits that most need to zoom in.
    """
    src = sources[board]
    assert "Math.min(17, Math.max(3," in src, "the fitBounds ceiling must be 17, not 15"


@pytest.mark.parametrize("board", NO_CSV_BOARDS)
def test_boards_have_no_csv_download_control(sources, board):
    src = sources[board]
    lowered = src.lower()
    assert "descargar tabla (csv)" not in lowered
    assert "createobjecturl" not in lowered, "no Blob download path may remain"
    assert "-csv\"" not in lowered and "-csv'" not in lowered


# Regional wording and the notebooks' former `01.x` names. `tira` is intentionally
# absent from this list: it is legitimate Spanish for the legend's colour strip.
REGIONALISMS = {
    "aca": r"\baca\b",
    "alla": r"\balla\b",
    "voseo (elegi/podes)": r"\b(Elegi|elegi|podes|Podes)\b",
    "ojo": r"\bOjo\b",
    "saltear": r"\bsalte[ao]\w*\b",
    "un pelo": r"\bun pelo\b",
    "stale 01.x notebook names": r"\b01\.[234]\b",
}


@pytest.mark.parametrize("board", sorted(BOARDS))
@pytest.mark.parametrize("label,pattern", sorted(REGIONALISMS.items()))
def test_board_prose_stays_neutral_spanish(sources, board, label, pattern):
    hits = re.findall(pattern, sources[board])
    assert not hits, f"{BOARDS[board]} still contains {label}: {hits[:5]}"


# --- the Databricks app commands shim these notebooks by literal replacement ----------
#
# `/app-trayectorias-circuitos` and `/app-trayectorias-vanos` publish `03`/`04` by staging a
# copy and swapping exact lines in it. A replacement whose target no longer exists does not
# error loudly -- it just leaves the notebook unshimmed, and the job then reads the CSV from
# a local path that does not exist on the Volume, or opens a browser inside a container.
# These anchors must therefore stay verbatim in both places.

COMMAND_DIR = Path(__file__).resolve().parents[1] / ".claude" / "commands"
SHIM_ANCHORS = {
    "03": (
        "app-trayectorias-circuitos.md",
        [
            '# %pip install -q pandas numpy pyarrow "plotly>=6" geopandas scikit-learn',
            "REPO_ROOT = find_repo_root()",
            "ABRIR_EN_NAVEGADOR = True",
            "display(HTML(PANEL_COMPLETO))",
            "RUTA_PANEL = exportar_y_abrir(PANEL_COMPLETO, abrir=ABRIR_EN_NAVEGADOR)",
        ],
    ),
    "04": (
        "app-trayectorias-vanos.md",
        [
            '# %pip install -q pandas numpy pyarrow "plotly>=6" geopandas scikit-learn',
            "REPO_ROOT = find_repo_root()",
            "ABRIR_EN_NAVEGADOR = True",
            "display(HTML(PANEL_COMPLETO))",
            "RUTA_PANEL = exportar_y_abrir(PANEL_COMPLETO, abrir=ABRIR_EN_NAVEGADOR)",
        ],
    ),
}


@pytest.mark.parametrize("board", sorted(SHIM_ANCHORS))
def test_databricks_command_shim_anchors_still_exist_in_the_notebook(sources, board):
    command_name, anchors = SHIM_ANCHORS[board]
    command = (COMMAND_DIR / command_name).read_text(encoding="utf-8")
    for anchor in anchors:
        assert anchor in sources[board], (
            f"{BOARDS[board]} no longer contains {anchor!r}, which /{command_name[:-3]} "
            f"replaces when staging the Databricks copy"
        )
        assert anchor in command, (
            f"{command_name} no longer mentions {anchor!r}; the shim would miss it"
        )


def test_board_04_keeps_its_rendered_output_because_the_pipeline_reads_it():
    """`04`'s cell-7 `text/html` output is an INPUT, not a leftover.

    `scripts/extract_geometrias_014.py` pulls the K-Means `geometrias` and `grupos` blocks
    straight out of that stored output and caches them as `data/derived/geometrias_014.json`,
    which `chec_impacto.models.criticality_assignment` then loads and checks against a pinned
    sha1. Clearing the output -- an obvious-looking way to shrink a 12 MB notebook, and the
    right call for `01`/`02`/`03`, whose outputs nothing reads -- breaks that chain with a
    `ValueError: No se encontró la clave 'geometrias'`, far from the notebook that caused it.
    """
    notebook = json.loads(
        (NOTEBOOK_DIR / f"{BOARDS['04']}.ipynb").read_text(encoding="utf-8"))
    outputs = notebook["cells"][7]["outputs"]
    html = [o for o in outputs
            if o.get("output_type") == "display_data" and "text/html" in o.get("data", {})]
    assert html, "cell 7 must keep a display_data output carrying text/html"
    payload = "".join(html[0]["data"]["text/html"])
    assert '"geometrias":' in payload, "the K-Means geometry block must survive in the output"
    assert '"grupos":' in payload


@pytest.mark.parametrize("board", sorted(SHIM_ANCHORS))
def test_databricks_command_names_the_notebooks_own_div_variable(board):
    """The generated document needs a `width: 100%` rule on the figure's real div id.

    Hard-coding the id string instead would drift silently the day the notebook renames it,
    leaving the board rendered into a collapsed container.
    """
    command_name, _ = SHIM_ANCHORS[board]
    command = (COMMAND_DIR / command_name).read_text(encoding="utf-8")
    variable = "DIV_FIGURA" if board == "03" else "DIV"
    assert f"#{{{variable}}} {{{{ width: 100%; }}}}" in command
    assert "{PANEL_COMPLETO}" in command, "the document must embed the notebook's own block"
