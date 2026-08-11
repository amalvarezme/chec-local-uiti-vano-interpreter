"""RED/GREEN tests for the relayout guard of notebook 06's map panel.

Panning or zooming a `map` (MapLibre) subplot inside a `FigureWidget` makes the
browser send back a relayout payload that carries `map._derived` next to
`map.center` and `map.zoom`. `_derived` is plotly's OWN internal bookkeeping --
the corner coordinates MapLibre computed -- and it is not a settable layout
property, so `plotly_relayout` refuses it:

    ValueError: Invalid property path 'map._derived' for layout

Reproduced against plotly 6.8.0: `basewidget._handler_js2py_relayout` strips
`lastInputTime` from that payload but nothing else, so the exception surfaces on
EVERY drag of either map. It lands in the output of the cell that displays the
widget -- cells above the dashboard -- which is why it reads as if an earlier
cell had broken.

The guard drops the keys the frontend is only reporting back, and lets the real
ones through, so the pan still moves the map.
"""

from __future__ import annotations

import plotly.graph_objects as go
import pytest

from chec_local_interpreter.vano_widgets import (
    figura_de_mapas,
    sin_claves_derivadas,
)


def test_sin_claves_derivadas_drops_the_frontends_own_bookkeeping():
    """`map._derived` es lo que MapLibre CALCULO, no lo que el usuario pidio.
    Reenviarlo a `plotly_relayout` es pedirle a plotly que fije una propiedad
    que no existe."""
    limpio = sin_claves_derivadas({
        "map.center": {"lon": -75.1, "lat": 5.1},
        "map.zoom": 11.2,
        "map._derived": {"coordinates": [[-75.2, 5.2]]},
    })

    assert limpio == {"map.center": {"lon": -75.1, "lat": 5.1}, "map.zoom": 11.2}


def test_sin_claves_derivadas_only_looks_at_the_last_component():
    """Se mira el ULTIMO tramo de la ruta y no la cadena entera: `map2._derived`
    tiene que caer igual que `map._derived`, y una propiedad real nunca empieza
    por guion bajo."""
    limpio = sin_claves_derivadas({
        "map2._derived": {},
        "map2.zoom": 9.0,
        "_derived": {},
    })

    assert limpio == {"map2.zoom": 9.0}


def test_sin_claves_derivadas_leaves_an_ordinary_payload_alone():
    """El caso normal no se toca: si el guardia recortara de mas, arrastrar el
    mapa dejaria de moverlo y el sintoma seria peor que el error."""
    payload = {"map.center": {"lon": -75.0, "lat": 5.0}, "map.zoom": 10.0}

    assert sin_claves_derivadas(payload) == payload


def _figura():
    fig = figura_de_mapas()
    fig.add_trace(go.Scattermap(lat=[5.0], lon=[-75.0]))
    fig.update_layout(map=dict(center=dict(lat=5.0, lon=-75.0), zoom=10.0))
    return fig


def test_la_figura_sobrevive_al_arrastre_de_un_mapa():
    """El payload EXACTO que manda el navegador al arrastrar un mapa MapLibre.
    Con `go.FigureWidget` esto lanza `ValueError`; aqui tiene que aplicar el
    encuadre nuevo y seguir."""
    fig = _figura()

    fig.plotly_relayout({
        "map.center": {"lon": -75.1, "lat": 5.1},
        "map.zoom": 11.2,
        "map._derived": {"coordinates": [[-75.2, 5.2], [-75.0, 5.0]]},
    })

    assert fig.layout.map.zoom == 11.2
    assert (fig.layout.map.center.lat, fig.layout.map.center.lon) == (5.1, -75.1)


def test_go_figurewidget_sin_el_guardia_si_lanza():
    """Se fija el fallo de plotly que motiva la subclase. Si una version futura
    lo arregla, esta prueba cae y el guardia se puede retirar en vez de quedarse
    para siempre por si acaso."""
    fig = go.FigureWidget()
    fig.add_trace(go.Scattermap(lat=[5.0], lon=[-75.0]))

    with pytest.raises(ValueError, match=r"map\._derived"):
        fig.plotly_relayout({"map.zoom": 11.2, "map._derived": {}})


def test_un_payload_que_solo_traia_claves_internas_no_toca_la_figura():
    """Al soltar el arrastre el navegador manda a veces SOLO `_derived`. Vaciado,
    el payload no puede ir a `plotly_relayout`: con un dict vacio plotly no tiene
    nada que cambiar y el zoom debe quedarse donde estaba."""
    fig = _figura()

    fig.plotly_relayout({"map._derived": {"coordinates": []}})

    assert fig.layout.map.zoom == 10.0
