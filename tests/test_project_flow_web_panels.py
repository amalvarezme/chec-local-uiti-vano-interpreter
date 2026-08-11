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

    At `opacity=0.5` over carto-positron's light background, `Alto` -- rgb(198,40,40) --
    painted as rgb(220,140,137), a washed pink, and `Bajo` sat one step from
    the background. Worse, over the black 1.5 px structure core the SAME class composited to a
    different colour again (rgb(99,20,20) for `Alto`), so one vano showed two tones and neither
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


# --- `04`'s selection: what the board opens on, and what marks a vano -------------------
# The three behaviours below are one story: the board must land on a circuit already
# showing something, the window must bring its own subject, and a marked vano must be
# findable on the map. All three are JS in the panel, so they are pinned against the
# source rather than executed.

def _notebook_source(name: str) -> str:
    return _source(name)


@pytest.mark.parametrize("board", ["03", "04"])
def test_board_opens_on_the_first_circuit(sources, board):
    """`(ninguno)` is still an option, but no longer the one the board starts in.

    Opening on `(ninguno)` means opening on a board with no map and an empty vano list:
    the first thing anyone has to do is pick a circuit before seeing anything at all. The
    first circuit is as good a starting point as any, and `03` already worked this way --
    `04` was the odd one out.
    """
    src = sources[board]
    assert '" selected" if i == 0 else ""' in src, (
        "the first circuit must carry `selected` in the option markup")
    assert "for i, c in enumerate(CIRCUITOS)" in src, (
        "the index has to come from enumerate, not from a second pass over the list")
    assert "SIN_SELECCION" in src, "the `(ninguno)` option itself must survive"


def test_board_04_auto_marks_the_vanos_with_events_of_the_moving_window(sources):
    """Moving the window re-marks the vanos that registered events IN it.

    Without this the slider changes the window but not the subject: the map, the series
    and the split keep describing vanos that in the new window have no cell at all, and
    re-picking them by hand at every step is the work the board exists to save.

    It is a REPLACEMENT and not an addition -- `checked` is assigned from the lookup for
    every box, so a vano that stops having events also stops being marked -- and it runs
    BEFORE the map is drawn, or the first frame of every window would show the previous
    window's selection.
    """
    src = sources["04"]
    assert "function autoseleccionar()" in src
    assert "cajas[i].checked = uiti[cajas[i].value] !== undefined;" in src, (
        "the mark must be an assignment over every box, not an OR that only ever adds")
    # Both entry points: the slider, and repopulating the list on a circuit change.
    assert re.search(r"autoseleccionar\(\);\s*\n\s*dibujarMapa\(gd,", src), (
        "the slider must mark before drawing the map")
    assert re.search(r"poblarLista\(circuito\);\s*\n\s*autoseleccionar\(\);", src), (
        "a circuit change repopulates the list, which leaves every box unchecked")
    # The window now brings a different SELECTION, so the debounced tail has to redo the
    # quotas, the legend, the evolution series and the arrows -- not just the split and the
    # opacities, which was enough while the selection survived a window change.
    assert "refrescarReparto(gd, geoActual(), circ, cuposDe(elegidos()));" not in src, (
        "the partial refresh is not enough once the window changes the selection")


def test_board_04_boxes_the_marked_vano_exactly_like_board_06():
    """The yellow box of `04` is the box of `06`: same size, same colour, same bearing.

    `06` marks a vano with a translucent rectangle TURNED to the vano's own direction,
    drawn as a `layout.map.layers` fill under the traces. `04` marked its vanos with a
    thicker line and a halo only, which on a circuit of hundreds of segments is not enough
    to find the one under study.

    The four numbers are compared across the two notebooks rather than asserted as
    literals here: what matters is not the value, it is that the two boards cannot drift
    apart. Two highlights of different size over the same vano read as two different
    things.
    """
    src04 = _notebook_source(BOARDS["04"])
    src06 = _notebook_source("06_uiti_vano_explicabilidad_simulador")

    for constante in ("COLOR_CAJA_SELECCION", "OPACIDAD_CAJA_SELECCION",
                      "LADO_MINIMO_CAJA", "MARGEN_CAJA"):
        patron = rf"^{constante} = (.+?)(?:\s+#.*)?$"
        en04 = re.search(patron, src04, re.MULTILINE)
        en06 = re.search(patron, src06, re.MULTILINE)
        assert en04 and en06, f"{constante} must be declared in both notebooks"
        assert en04.group(1).strip() == en06.group(1).strip(), (
            f"{constante} drifted: 04 says {en04.group(1)!r}, 06 says {en06.group(1)!r}")

    # The layer, not a trace: a filled trace on top would eat the very click that toggles
    # the selection, and would tint the class colour of the vano it is pointing at.
    assert "sourcetype='geojson', type='fill', below='traces'," in src04
    assert "layers=[CAPA_CAJA_SELECCION]" in src04
    assert "assert fig.layout.map.layers[0].below == 'traces'" in src04

    # The JS port of `cajas_seleccion`: the rectangle turns with the vano (`u` along it,
    # `v` across it), opens about its centre, and closes its ring.
    assert "function cajasSeleccion(circuito, sel)" in src04
    assert "var v = [-u[1], u[0]];" in src04, "the cross axis must be `u` turned 90 degrees"
    assert "anillo.push(anillo[0]);" in src04, (
        "MapLibre silently drops an open ring and draws no box at all")
    assert "'map.layers[0].source': cajasSeleccion(circuito, sel)" in src04, (
        "the box must be repainted by writing the source of the layer that already exists")
    # Drawn from the geometry and repainted with the map, so it survives a window change
    # and disappears the moment the vano is unmarked -- by its box or by clicking it again.
    assert re.search(r"pintarCajas\(gd, circuito, sel\);", src04)


# --- One map style across every board ---------------------------------------------------
# `01` is the reference: it is the board whose map was measured and tuned (equipment went
# from 6/5 to 14/12 px and the vano layer from 3.5 to 7.0 when its figure doubled in
# height). `03`, `04` and `06` draw the SAME objects over the SAME geography, so a
# transformer or a vano that measures one thing here and another there makes the same
# circuit read as two different circuits when you move between notebooks.
MAP_STYLE_NOTEBOOKS = {
    "01": BOARDS["01"],
    "03": BOARDS["03"],
    "04": BOARDS["04"],
    # `06` is not an HTML board -- it is the ipywidgets simulator -- but its two maps are
    # the same map, so it shares this contract even though it shares no other.
    "06": "06_uiti_vano_explicabilidad_simulador",
}
# value: the reference reading, taken from `01`.
MAP_STYLE_CONSTANTS = {
    "TAM_TRAFO": "14",
    "TAM_SWITCH": "12",
    "ANCHO_MAPA": "7.0",
    "ANCHO_SIN_EVENTOS": "1.5",
    "COLOR_SIN_EVENTO": "'rgb(0,0,0)'",
    "COLOR_TRAFO": "'#f59e0b'",
    "COLOR_SWITCH": "'#7c3aed'",
}
GROUP_PALETTE = "['rgb(26,150,65)', 'rgb(242,194,0)', 'rgb(239,108,0)', 'rgb(198,40,40)']"


def _constant(src: str, name: str) -> str | None:
    """The right-hand side of `NAME = ...`, with any trailing comment dropped."""
    found = re.search(rf"^{name} = (.+?)(?:\s+#.*)?$", src, re.MULTILINE)
    return found.group(1).strip() if found else None


@pytest.mark.parametrize("notebook", sorted(MAP_STYLE_NOTEBOOKS))
@pytest.mark.parametrize("constant", sorted(MAP_STYLE_CONSTANTS))
def test_every_map_shares_board_01s_style(notebook, constant):
    """Equipment size, vano widths and map colours are one value across all four maps."""
    valor = _constant(_source(MAP_STYLE_NOTEBOOKS[notebook]), constant)
    assert valor is not None, (
        f"{notebook} must declare {constant}; the map style is not allowed to be implicit")
    assert valor == MAP_STYLE_CONSTANTS[constant], (
        f"{notebook} says {constant} = {valor}, board 01 says {MAP_STYLE_CONSTANTS[constant]}")


@pytest.mark.parametrize("notebook", sorted(MAP_STYLE_NOTEBOOKS))
def test_every_map_shares_the_same_four_group_colours(notebook):
    """The four class colours are the traffic light, spelled the same way everywhere.

    Same list, same `rgb(...)` form: the fill of the violins and contours comes from
    `.replace('rgb', 'rgba')`, which over a hex finds nothing and silently leaves the fill
    unapplied. So the notation is part of the contract, not a style preference.
    """
    src = _source(MAP_STYLE_NOTEBOOKS[notebook])
    nombre = "COLORES_MAPA" if notebook == "01" else "COLORES_GRUPOS"
    assert _constant(src, nombre) == GROUP_PALETTE, (
        f"{notebook}'s {nombre} drifted from board 01's palette")


@pytest.mark.parametrize("notebook", ["03", "04", "06"])
def test_no_map_hard_codes_a_style_the_constants_are_supposed_to_own(notebook):
    """The equipment sizes used to be literals inside the `add_trace` loop.

    That is how `03`, `04` and `06` all ended up at 6/5 px while `01` moved to 14/12: a
    literal in a trace definition is invisible from the constants block, so aligning the
    boards looks done when it is not.
    """
    src = _source(MAP_STYLE_NOTEBOOKS[notebook])
    assert "COLOR_TRAFO, 6)" not in src and "COLOR_SWITCH, 5)" not in src, (
        "equipment size must come from TAM_TRAFO/TAM_SWITCH, not from a literal")
    assert "COLOR_SWITCH), (6, 5))" not in src.replace(" ", "").replace("\n", ""), (
        "equipment size must come from TAM_TRAFO/TAM_SWITCH, not from a literal tuple")
    # A marked vano is a wider version of the same line, never a loose second number.
    for derivado in ("ANCHO_MAPA_RESALTE", "ANCHO_MAPA_MARCADO", "ANCHO_HALO"):
        valor = _constant(src, derivado)
        if valor is not None:
            assert "round(" in valor and "ANCHO_" in valor, (
                f"{derivado} must be derived from ANCHO_MAPA, not written as a literal")


def test_board_06_draws_the_vano_without_events_as_structure_not_as_data():
    """`06` used to draw a vano with no cell in the window as wide as one with events.

    Only the colour changed, so absence of data competed in visual weight with the data
    itself -- the opposite of what it means. Both maps (historical and simulated) now use
    board 01's 1.5 px structure line for it.
    """
    src = _source(MAP_STYLE_NOTEBOOKS["06"])
    assert src.count("line=dict(width=ANCHO_SIN_EVENTOS, color=COLOR_SIN_EVENTO)") == 2, (
        "both the historical `sin_dato` layer and the simulated `pred_sin_dato` one")
    assert "== ANCHO_SIN_EVENTOS == 1.5)" in src, (
        "the notebook must assert it too, where the traces are built")
