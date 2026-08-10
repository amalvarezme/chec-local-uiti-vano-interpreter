"""Contract tests for notebook 06's yellow selection box.

Clicking a vano on the base map (row 1) marks it, and a marked vano is
enclosed in a translucent yellow bounding box so it stays findable on a
circuit of hundreds of segments. The geometry of that box is
`ventanas_015.cajas_seleccion`, covered by unit tests in
`tests/test_ventanas_015.py`. What those unit tests cannot see is the WIRING:
whether the notebook actually reaches that geometry, and whether it puts the
result where it belongs. These tests pin it against the committed notebook
source (no execution, so this stays fast), because each failure is silent:

  1. The box is a `layout.map.layers` fill with `below='traces'`, NOT a
     trace. A filled trace on top would swallow the map click -- which is
     the very thing that toggles the selection -- and would tint the vano's
     own class colour yellow.
  2. Only row 1 carries it. Row 2 is the model's output, not a control.
  3. The box is built from the GEOMETRY, never from the window's cells.
     That is what makes the highlight survive moving the window slider,
     even over a vano with no events in the active window.

The three checks that guarded the self-contained HTML panel were removed with
it: that panel was a full transcription of the model into JavaScript that had
to be kept in step with the Python by hand, and the notebook is now the only
interface.
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
    # Si alguien la convierte en traza, deja de estar en el layout y esto avisa.
    assert "fig.layout.map.layers[0].source = cajas_seleccion(" in fuente


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
