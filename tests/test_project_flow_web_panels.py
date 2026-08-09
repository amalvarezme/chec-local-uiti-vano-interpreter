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


# Every board reads the CSV through pyarrow's incremental reader.
BLOCK_READER_BOARDS = sorted(BOARDS)


@pytest.mark.parametrize("board", BLOCK_READER_BOARDS)
def test_board_reads_the_csv_in_blocks_not_all_at_once(sources, board):
    """`pd.read_csv` filters `usecols` AFTER parsing the whole 566 MB file.

    Measured peak RSS for the read alone: 826 MB (4 columns) / 1172 MB (106 columns) against
    109 MB / 437 MB through `pyarrow.csv.open_csv`. End to end the boards went 1244->638 MB
    (`03`), 1332->648 MB (`04`), 2036->1371 MB (`01`) and 1382->514 MB (`02`, which reads the
    file twice, once per unit of analysis). The board payloads hash identical either way, so a
    revert to `pd.read_csv` looks harmless in review and silently multiplies the memory
    ceiling -- which is what decides whether the notebook survives a serverless job.
    """
    src = sources[board]
    assert "pacsv.open_csv(" in src, "the CSV must be read incrementally"
    assert "include_columns=" in src
    # `usecols=` is the fingerprint of the whole-file path, and unlike "engine='pyarrow'"
    # it does not appear in the prose explaining why that path was dropped. `01` still calls
    # `pd.read_csv(..., nrows=0)` to probe the header, which reads no rows and is fine.
    assert "usecols=" not in src, "the pandas whole-file path must not come back"


def test_board_01_paints_the_uiti_layer_at_full_opacity():
    """Half-tinted, the layer stops showing the panel's thresholded colours.

    At `opacity=0.5` over carto-positron's light background, `Alto` -- rgb(103,0,13), a
    near-black red -- painted as rgb(172,121,128), a washed pink, and `Bajo` sat one step from
    the background. Worse, over the black 1.5 px structure core the SAME class composited to a
    different colour again (rgb(52,0,6) for `Alto`), so one vano showed two tones and neither
    matched the swatch the panel prints in its legend. Verified opaque in MapLibre itself via
    `getPaintProperty`: the four line layers report the palette colours at width 7, opacity 1.
    """
    src = _source(BOARDS["01"])
    assert "OPACIDAD_UITI = 1.0" in src
    assert "OPACIDAD_UITI == 1.0" in src, "the in-notebook assertion must pin it too"
    assert "ANCHO_MAPA = 7.0" in src, "the layer must stay thicker than the 1.5 px structure"


def test_board_02_circuits_sheet_names_its_risk_band_and_drops_the_derived_sum():
    """`02`'s vanos board exports an .xlsx with a Vanos sheet and a Circuitos sheet.

    Two fixes pinned here, both verified by downloading the real workbook from the browser
    and reading it with openpyxl:

    1. `grupo_ranking` used to be the band number 1..4. It now carries the band NAME, as
       BAJO / MEDIO / MEDIO-ALTO / ALTO.
    2. `vanos_medio_alto_mas_alto` is gone. It was exactly the sum of the two columns
       immediately before it, so it added nothing the sheet did not already hold.

    Note the workbook deliberately carries TWO four-level scales that share their words. The
    Vanos sheet's `etiqueta` is the K-Means group of each vano; the Circuits sheet's
    `grupo_ranking` is a percentile band (P50/P75/P97) of how many critical vanos a circuit
    has -- a different question about a different unit. What tells them apart in the file is
    the sheet and the column name, not the value. The ranking CHART keeps the "Riesgo "
    prefix on those same bands, because there both scales are on screen at once.
    """
    src = _source(BOARDS["02"])
    assert "rangoPorCirc[conAlto[i]] = NOMBRE_RANGO_EXCEL[seg];" in src, (
        "the circuits sheet must carry the band name, not its number"
    )
    assert "var NOMBRE_RANGO_EXCEL = ['BAJO', 'MEDIO', 'MEDIO-ALTO', 'ALTO'];" in src
    assert "'vanos_medio_alto_mas_alto'" not in src, "the derived sum column must be gone"
    # The chart keeps its own prefixed names; the two must not be collapsed into one list.
    assert ("var NOMBRE_RIESGO = ['Riesgo Bajo', 'Riesgo Medio', 'Riesgo Medio-Alto', "
            "'Riesgo Alto'];") in src


def test_board_02_workbook_writes_both_label_columns_in_upper_case():
    """Both label columns of the workbook read as BAJO / MEDIO / MEDIO-ALTO / ALTO.

    The two scales live on different sheets -- `etiqueta` (K-Means group of a vano) on
    Vanos, `grupo_ranking` (percentile band of a circuit) on Circuitos -- and they used to
    be written differently: the circuit band in sustained caps, the vano label in title case
    ('Medio-Alto'), because the vano label was taken straight from the chart legend. Read in
    Excel, one file with two spellings of the same four words looks like two vocabularies,
    and filtering the sheets side by side needs a case fold that nobody expects to need.

    The label is derived from `CTX.grupos`, not written out again: the chart legend stays
    the single source of the four names, and the sheet only changes their case. A hardcoded
    second list would let the two drift apart silently.

    The CHARTS keep title case (and the ranking chart its "Riesgo " prefix), because on
    screen both scales are visible at once and the case is what makes them readable.
    """
    src = _source(BOARDS["02"])
    assert "CTX.grupos[f.g].toUpperCase()" in src, (
        "the vanos sheet must uppercase the K-Means label it takes from the legend"
    )
    assert "NOMBRES_GRUPOS = ['Bajo', 'Medio', 'Medio-Alto', 'Alto']" in src, (
        "the chart legend must keep title case"
    )


def test_board_02_vanos_panel_notice_drops_the_per_group_split():
    """The vanos panel notice stops repeating the split the bar chart already draws.

    It read '... vanos con eventos en el periodo -- reparto 812 / 402 / 96 / 31.', four bare
    numbers with no names attached, in the panel directly above a bar chart that draws those
    same four counts labelled and to scale. The notice keeps what the chart cannot show: the
    effective range and how many vanos of the total had events at all.
    """
    src = _source(BOARDS["02"])
    assert "' vanos con eventos en el periodo.'" in src
    assert "reparto ' + conteos.join" not in src, "the split must be gone from the notice"


def test_board_01_day_slider_declares_how_many_days_the_circuit_has():
    """A circuit with a single day of events must not look like a broken slider.

    Day counts are per circuit and range from 1 to 79 (median 14). Twelve of the 208 have
    exactly one -- DOR23L12, for instance, is 26 rows all dated 2025-11-03 -- and 39 have
    three or fewer. Left enabled, the control simply does not move and the time series draws
    a single point, which reads as a broken board right after a circuit with 42 days. It was
    reported as exactly that. The panel already disables the HOUR slider for static
    variables "en vez de quedar mintiendo que mueve algo"; the day slider now follows the
    same rule and its label carries the count.
    """
    src = _source(BOARDS["01"])
    assert 'id="cl-dia-lbl"' in src, "the day label needs an id so it can be rewritten"
    assert "sliderD.disabled = nDias <= 1" in src
    assert "registra eventos en un solo dia" in src, "the single-day case must say so"
    assert "' con eventos)'" in src, "the label must carry the day count"


def test_board_01_draws_the_uiti_layer_above_the_cloud():
    """Trace order IS layer order in MapLibre, and the cloud was burying the UITI layer.

    The cloud is one Scattermap of 78 px markers. Each is faint on its own, but they overlap
    heavily between neighbouring vanos, so a dozen of them stack into full coverage. With the
    cloud added AFTER the four class traces, a screenshot of DON23L13's map contained ZERO
    pixels of the four palette colours; hiding the cloud brought back 1514. The data, the
    widths and the paint properties were all correct the whole time -- only the order was
    wrong, which is why it looked like the layer was never drawn.

    `01` pins this in the notebook too (`IDX['nube'] < min(IDX['mapaClases'])`), so a reorder
    fails at generation rather than silently in the browser. This test guards the ordering of
    the `add_trace` calls that the index is derived from.
    """
    src = _source(BOARDS["01"])
    assert "assert IDX['nube'] < min(IDX['mapaClases'])" in src
    posicion_nube = src.index("name='Nube por vano (variable seleccionable)'")
    posicion_clases = src.index("for _clase, _color in zip(CLASES_MAPA, COLORES_MAPA):")
    assert posicion_nube < posicion_clases, (
        "the cloud trace must be added BEFORE the UITI class traces, or it covers them"
    )


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


# Boards whose clustering space stopped being a control. `01` never had one.
FIXED_SPACE_BOARDS = {"02": ("ag", "va"), "03": ("tr",), "04": ("v4",)}


@pytest.mark.parametrize("board", sorted(FIXED_SPACE_BOARDS))
def test_kmeans_space_is_fixed_and_no_longer_a_control(sources, board):
    """The axis-scale checkboxes and the preprocessing select are gone from every board.

    They were not cosmetic: the scale and the scaler are applied BEFORE K-Means, so each of
    the eight combinations was a different partition, and a group called `Alto` meant a
    different thing depending on which one the board happened to be left in. Fixing the space
    -- linear x, `log10` y, `minmax` -- is what makes two readings comparable, and it also
    drops the precomputed spaces from 8 to 1 (in `02`, the embedded combinations from 168 to
    21, and one K-Means fit per board instead of eight).

    `ESPACIOS` deliberately survives as a ONE-element list rather than disappearing: every
    consumer downstream indexes by space, and the JS looks its geometry up by that key. What
    this test pins is that the list holds exactly the fixed triple and that no control can
    reintroduce a second one.
    """
    src = sources[board]
    assert "LOG_X, LOG_Y, PREPROCESO = False, True, 'minmax'" in src, (
        "the fixed space must be declared once, as named constants")
    assert "ESPACIOS = [(LOG_X, LOG_Y, PREPROCESO)]" in src, (
        "ESPACIOS must hold exactly the one fixed space")
    assert "IDX_ESPACIO_DEFECTO = 0" in src
    for prefix in FIXED_SPACE_BOARDS[board]:
        for control in ("logx", "logy", "prep"):
            assert f"{prefix}-{control}" not in src, (
                f"{prefix}-{control} is back: the space must not be selectable again")


@pytest.mark.parametrize("board", sorted(FIXED_SPACE_BOARDS))
def test_space_keyed_lookups_use_the_literal_key_not_a_dead_variable(sources, board):
    """`String(e)` outliving the `var e` that fed it is a silent, board-wide failure.

    It happened: removing the control loop deleted the declaration while one
    `CTX.geometrias[String(e)]` further down still referenced it. The board still mounted, at
    the right size, with every panel check green -- the ReferenceError only fires inside
    `aplicar()`, so the figure renders once and then never reacts. What gave it away was the
    trajectory coming up empty. Every space-keyed lookup must now name the only key there is.
    """
    src = sources[board]
    for container in ("geometrias", "gruposPorEspacio"):
        assert f"CTX.{container}[String(" not in src, (
            f"CTX.{container} must be indexed by the literal '0', not a computed key")


def test_board_04_stored_output_carries_the_fixed_space_too():
    """`04`'s cell-7 output is preserved, so a stale one keeps the old controls alive.

    Unlike the other three boards, `04`'s rendered output is an input to the geometry
    pipeline and is never cleared, which means the source can be right while the output the
    Databricks command publishes still ships the removed checkboxes. The two must agree.
    """
    notebook = json.loads(
        (NOTEBOOK_DIR / f"{BOARDS['04']}.ipynb").read_text(encoding="utf-8"))
    payload = "".join(
        "".join(o["data"]["text/html"])
        for o in notebook["cells"][7]["outputs"]
        if o.get("output_type") == "display_data" and "text/html" in o.get("data", {}))
    assert payload, "cell 7 must keep its rendered output"
    for control in ("v4-logx", "v4-logy", "v4-prep"):
        assert control not in payload, f"{control} survives in the stored output: re-run 04"


def test_board_02_exports_the_same_space_it_draws():
    """`02`'s two Python exports used to default to a space the board could not show.

    Both `tabla_etiquetas` and `tabla_etiquetas_vano` carried `log_y=False`, while the panel
    started with `Log eje Y` checked -- so the CSV written by the kernel and the one the
    button downloaded came from two different partitions, and the file name was the only
    thing that said so. With a single space the divergence has nowhere to hide: the defaults
    now read from the same constants the board does, and the suffix follows them.
    """
    src = _source(BOARDS["02"])
    assert "def tabla_etiquetas(desde=None, hasta=None, log_x=LOG_X, log_y=LOG_Y," in src
    assert "log_x=LOG_X, log_y=LOG_Y," in src.replace("\n", " ")
    assert "prep=PREPROCESO" in src
    assert "_xlin_ylin_minmax.csv" not in src, (
        "the hard-coded suffix must follow the fixed space, not a frozen guess")


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
