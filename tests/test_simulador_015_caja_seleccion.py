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


def test_only_the_base_map_carries_the_yellow_selection_box(fuente):
    """Row 2 is the model's OUTPUT, not a control: marking there would mix
    "what I chose" with "what the model predicted" on the same surface. Row 2
    has boxes of its own, but they answer a different question -- see below."""
    assert fuente.count("layers=[CAPA_CAJA_SELECCION]") == 1
    assert "assert len(_fig.layout.map.layers) == 1" in fuente
    assert "assert len(_fig.layout.map2.layers) == len(CAMBIOS)" in fuente


def test_the_simulated_map_has_one_box_layer_per_outcome(fuente):
    """El recuadro de la derecha no dice cual vano elegi -- eso ya lo dice el de
    la izquierda, sobre el mismo vano -- sino QUE LE PASO: verde si bajo de
    grupo, amarillo si se quedo igual, rojo si subio. Son TRES capas porque una
    capa de `layout.map.layers` pinta con UN color, y se crean todas al armar la
    figura para que el repintado sea una escritura de `source` por capa: quitar y
    poner capas reordena en MapLibre lo que hay debajo."""
    assert "CAPAS_CAJA_SIMULADA = [" in fuente
    capas = fuente[fuente.index("CAPAS_CAJA_SIMULADA = [") :][:600]
    assert "below='traces'" in capas
    assert "for _cambio in CAMBIOS" in capas
    assert "layers=CAPAS_CAJA_SIMULADA" in fuente
    # El "no cambio" reusa el amarillo del mapa base: es justo el estado en que
    # los dos mapas dicen lo mismo, y un cuarto color inventaria una diferencia.
    assert "COLOR_CAJA_IGUAL = COLOR_CAJA_SELECCION" in fuente
    assert "fig.layout.map2.layers[_i_capa].source = _cajas[_cambio]" in fuente


def test_the_box_and_the_framing_follow_only_the_vanos_that_were_simulated(fuente):
    """Marcar un vano DESPUES de simular no lo mete en el resultado. Si la caja o
    el encuadre lo siguieran, el mapa se acercaria a un vano que el modelo nunca
    puntuo y el recuadro afirmaria un desenlace que nadie calculo."""
    assert "_simulados = set(_ultimo_resultado_simulacion['FID_VANO'].astype(str))" in fuente
    assert "_marcados_simulados = [f for f in _marcados if f in _simulados]" in fuente
    assert "marcados=_marcados_simulados" in fuente
    assert "bounds_de_fids(geo, _marcados_simulados)" in fuente
    # Sin nada marcado que se haya simulado, vuelve al encuadre del circuito en
    # vez de quedarse en el de la seleccion anterior.
    assert "or _vista_del_circuito(circuito)" in fuente


def test_the_simulated_tooltip_carries_both_groups(fuente):
    """El grupo base viaja por PUNTO y no en la plantilla de la traza: dentro de
    una traza -- que es UNA clase simulada -- el grupo base cambia de vano a
    vano. Sin los dos en la misma etiqueta, saber si el vano mejoro obliga a
    cruzar al mapa de al lado y acordarse del color."""
    assert "plantilla_extra='<br>Criticidad base: %{customdata[3]}'" in fuente
    assert "clases_base = clases_por_fid_para_estado(_ultimo_resultado_simulacion, ESTADO_BASE)" in fuente
    # La columna extra viaja para TODOS los fids: dentro de una traza customdata
    # tiene que medir siempre lo mismo o `%{customdata[3]}` lee el hueco vecino.
    assert "extra_por_fid.get(fid, ('sin dato',))" in fuente


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


# --- El deslizador de ventana recorre solo lo que el circuito tiene --------------------


def test_the_window_slider_is_repopulated_per_circuit(fuente):
    """No son las once ventanas para todos: medido, 121 de los 208 circuitos tienen
    menos, y uno tiene UNA sola. Antes el deslizador los llevaba igual a una ventana
    sin celdas -- un mapa sin un solo tramo de color, que se lee como que el tablero se
    rompio y no como que no hubo eventos."""
    assert "VENTANAS_POR_CIRCUITO = {" in fuente
    assert "def _opciones_de_ventana(circuito):" in fuente
    assert "options=_opciones_de_ventana(circuito_widget.value)" in fuente
    assert "ventana_widget.options = _opciones" in fuente


def test_the_current_window_is_read_before_options_are_reassigned(fuente):
    """Asignar `options` reajusta `value` a la primera opcion de INMEDIATO. Leerlo
    despues devuelve siempre esa primera, asi que la ventana vigente se perdia en cada
    cambio de circuito -- medido: pasar a un circuito que SI tiene la ventana 10 la
    dejaba en la 0. El orden de estas dos lineas es todo el arreglo."""
    cuerpo = fuente[fuente.index("def _on_circuito_change"):][:1200]
    assert cuerpo.index("_vigente = ventana_widget.value") < cuerpo.index(
        "ventana_widget.options = _opciones"), (
        "la ventana vigente se lee DESPUES de reescribir options: se pierde siempre")
    assert "_vigente if _vigente in _disponibles else _disponibles[0]" in cuerpo


def test_a_circuit_without_windows_still_gets_one_option(fuente):
    """Un `SelectionSlider` sin opciones lanza al construirse, y eso dejaria el panel
    entero sin arrancar por un circuito vacio."""
    assert "VENTANAS_POR_CIRCUITO.get(circuito) or [0]" in fuente
