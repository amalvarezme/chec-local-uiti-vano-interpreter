"""Contract tests for notebook 06's yellow selection box.

Clicking a vano on the base map (row 1) marks it, and a marked vano is
enclosed in a translucent yellow bounding box so it stays findable on a
circuit of hundreds of segments. The geometry of that box is
`ventanas_015.cajas_seleccion`, covered by unit tests in
`tests/test_ventanas_015.py`. What CANNOT be unit tested is its twin: the
self-contained web panel rebuilds the same boxes in JavaScript, in the
browser, from the same two constants. These tests pin the wiring of both
surfaces against the committed notebook source (no execution, so this stays
fast), because every one of them is a silent failure:

  1. The box is a `layout.map.layers` fill with `below='traces'`, NOT a
     trace. A filled trace on top would swallow the map click -- which is
     the very thing that toggles the selection -- and would tint the vano's
     own class colour yellow.
  2. Only row 1 carries it. Row 2 is the model's output, not a control.
  3. The box is built from the GEOMETRY, never from the window's cells.
     That is what makes the highlight survive moving the window slider,
     even over a vano with no events in the active window.
  4. The browser twin exists and is fed the same constants through `CTX`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

NOTEBOOK = (
    Path(__file__).resolve().parents[1]
    / "notebooks"
    / "project_flow"
    / "06_uiti_vano_explicabilidad_simulador.ipynb"
)


@pytest.fixture(scope="module")
def fuente() -> str:
    celdas = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    return "\n".join("".join(celda["source"]) for celda in celdas)


def test_the_box_is_a_map_layer_below_the_traces_and_not_a_trace(fuente):
    """A filled `Scattermap` trace drawn on top would eat the click that
    toggles the selection, and would paint over the class colour of the very
    vano it is pointing at. `below='traces'` is what keeps both working."""
    assert "CAPA_CAJA_SELECCION = dict(" in fuente
    capa = fuente[fuente.index("CAPA_CAJA_SELECCION = dict(") :][:400]
    assert "sourcetype='geojson'" in capa
    assert "type='fill'" in capa
    assert "below='traces'" in capa
    assert "color=COLOR_CAJA_SELECCION" in capa
    assert "opacity=OPACIDAD_CAJA_SELECCION" in capa
    # Si alguien la convierte en traza, el inventario congelado crece y esto avisa.
    assert "assert len(_fig.data) == 46" in fuente


def test_only_the_base_map_carries_the_selection_box(fuente):
    """Row 2 is the model's OUTPUT, not a control: marking there would mix
    "what I chose" with "what the model predicted" on the same surface."""
    assert fuente.count("layers=[CAPA_CAJA_SELECCION]") == 1
    assert "assert len(_fig.layout.map.layers) == 1 and not _fig.layout.map2.layers" in fuente
    assert "assert _fig.layout.map.layers[0].below == 'traces'" in fuente


def test_the_notebook_redraw_feeds_the_layer_from_the_geometry(fuente):
    """The box comes from `GEO_POR_CIRCUITO` and the marked set -- never from
    the window's cells. A marked vano with no events in the active window has
    no class, but it still has coordinates, so its box stays put while the
    window slider moves."""
    assert "cajas_seleccion," in fuente  # importada en la celda de arranque
    llamada = re.search(
        r"fig\.layout\.map\.layers\[0\]\.source = cajas_seleccion\((.*?)\)\n",
        fuente,
        re.S,
    )
    assert llamada is not None
    argumentos = llamada.group(1)
    assert "GEO_POR_CIRCUITO" in argumentos
    assert "marcados=_marcados" in argumentos
    assert "lado_minimo=LADO_MINIMO_CAJA" in argumentos
    assert "margen=MARGEN_CAJA" in argumentos


def test_the_minimum_side_is_wider_than_zero_so_a_north_south_vano_is_visible(fuente):
    """A vano that runs exactly north-south has a zero-width bounding box, and
    zero pixels wide is nothing at all on the map."""
    lado = re.search(r"^LADO_MINIMO_CAJA = ([0-9.]+)$", fuente, re.M)
    margen = re.search(r"^MARGEN_CAJA = ([0-9.]+)$", fuente, re.M)
    opacidad = re.search(r"^OPACIDAD_CAJA_SELECCION = ([0-9.]+)$", fuente, re.M)
    assert lado and margen and opacidad
    assert float(lado.group(1)) > 0.0
    assert float(margen.group(1)) > 0.0
    assert float(opacidad.group(1)) == 0.5


def test_the_web_panel_rebuilds_the_same_boxes_in_the_browser(fuente):
    """The self-contained HTML has no kernel: it recomputes the boxes in JS
    from the same two constants, which therefore have to travel in `CTX`. If
    one side's geometry changes and the other's does not, the notebook and the
    exported panel start highlighting different rectangles."""
    assert "function cajasSeleccion(geo) {" in fuente
    assert "'ladoMinimoCaja': LADO_MINIMO_CAJA," in fuente
    assert "'margenCaja': MARGEN_CAJA," in fuente
    cuerpo = fuente[fuente.index("function cajasSeleccion(geo) {") :][:1800]
    assert "CTX.ladoMinimoCaja" in cuerpo
    assert "CTX.margenCaja" in cuerpo
    assert "if (!MARCADOS[fid]) { continue; }" in cuerpo
    # El anillo CIERRA: uno abierto lo descarta MapLibre en silencio.
    assert cuerpo.count("[loMin, laMin]") == 2


def test_the_web_panel_repaints_the_layer_on_every_historical_redraw(fuente):
    """`dibujarMapaHistorico` is what runs on a click, on a checkbox, and on
    every move of the window slider. The box has to be rewritten there, or it
    would freeze on the selection that happened to be active when the panel
    loaded -- but only when it actually CHANGED, because a `relayout` is one
    more call on the thread that just restyled the map, and this board pays
    Plotly per call rather than per payload."""
    assert "Plotly.relayout(gd, {'map.layers[0].source': cajasSeleccion(geo)});" in fuente
    dibujo = fuente[fuente.index("function dibujarMapaHistorico(gd) {") :]
    dibujo = dibujo[: dibujo.index("\n  }\n")]
    assert "cajasSeleccion(geo)" in dibujo
    # La firma incluye el circuito: sin el, cambiar de circuito con la misma cantidad
    # de vanos marcados dejaria las cajas del circuito anterior.
    assert "var firmaCaja = CIRC + '|' + marcadosLista().sort().join(',');" in dibujo
    assert "if (firmaCaja !== CAJAS_PINTADAS) {" in dibujo


def test_the_deferred_repaint_also_repairs_the_box(fuente):
    """MapLibre mounts asynchronously and a repaint fired before it is ready is
    lost in silence -- which is why the panel repeats the drawing at 700 ms and
    2 s. The change guard must not exclude the box from that repair, or a box
    lost to a slow mount would never come back."""
    assert "CAJAS_PINTADAS = null;   // este repintado REPARA" in fuente
