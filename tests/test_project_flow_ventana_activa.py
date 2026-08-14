"""Contract tests for the active-window highlight shared by boards 03 and 04.

Two behaviours, both driven by the window slider, both verified in a real
browser against the generated panels before these tests were written:

  1. The dual-axis time series marks the ACTIVE window with a point drawn at
     triple size, and that point travels with the slider. This is board 01's
     idiom -- `marker.size` is an ARRAY, so enlarging one point never means
     splitting the series into a second trace, and moving the slider only
     rewrites eleven numbers.
  2. The clustering cloud paints the circuit-of-interest-in-the-window-of-
     interest at full opacity and everything else at 0.3. Two levels, not the
     old three-level focus cascade: a point IS a (circuit, window) pair, so
     "which one am I looking at" has a single answer and nothing to grade.

Both are pinned against the committed notebook sources (no execution, so
this stays fast). The logic lives in the browser, which pytest cannot run --
these tests guard the wiring that makes it reachable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

NOTEBOOK_DIR = Path(__file__).resolve().parents[1] / "notebooks" / "base_apps"
TABLEROS = {
    "03": "03_uiti_vano_trayectorias_circuitos",
    "04": "04_uiti_vano_trayectorias_vano",
}
# El deslizador de cada tablero, para comprobar que el punto activo va en su camino
# INMEDIATO y no en el diferido.
SLIDER = {"03": "tr-ventana", "04": "v4-ventana"}


def _fuente(nombre: str) -> str:
    celdas = json.loads((NOTEBOOK_DIR / f"{nombre}.ipynb").read_text(encoding="utf-8"))
    return "\n".join("".join(celda["source"]) for celda in celdas["cells"])


@pytest.fixture(scope="module")
def fuentes() -> dict[str, str]:
    return {clave: _fuente(nombre) for clave, nombre in TABLEROS.items()}


@pytest.mark.parametrize("tablero", sorted(TABLEROS))
def test_the_active_window_point_is_drawn_at_triple_size(fuentes, tablero):
    """`marker.size` has to be an ARRAY. A scalar would force a second trace to
    carry the enlarged point, and that trace would then need its own colour,
    hover and legend handling for a single marker."""
    fuente = fuentes[tablero]
    assert re.search(r"^SERIE_TAM_UITI = \d+$", fuente, re.M)
    assert re.search(r"^SERIE_TAM_EVENTOS = \d+$", fuente, re.M)
    factor = re.search(r"^FACTOR_PUNTO_ACTIVO = (\d+)$", fuente, re.M)
    assert factor and int(factor.group(1)) == 3
    assert "marker.size debe ser un array" in fuente
    assert "'serieTamUiti': SERIE_TAM_UITI" in fuente
    assert "'factorPuntoActivo': FACTOR_PUNTO_ACTIVO" in fuente
    assert "function pintarPuntoActivo(gd) {" in fuente
    assert "base * CTX.factorPuntoActivo" in fuente


@pytest.mark.parametrize("tablero", sorted(TABLEROS))
def test_the_active_point_follows_the_slider_without_the_debounce(fuentes, tablero):
    """The expensive repaints -- cloud opacity and the group breakdown -- are
    deliberately debounced 140 ms, so during a drag they only settle once the
    drag stops. The enlarged point must NOT sit behind that timer, or it would
    stand still while the slider moves, which is the whole thing being asked
    for. It is eleven numbers per series; it rides with the map instead."""
    fuente = fuentes[tablero]
    manejador = fuente[fuente.index(f"d.getElementById('{SLIDER[tablero]}')") :]
    manejador = manejador[: manejador.index("if (pendiente) { clearTimeout(pendiente); }")]
    assert "pintarPuntoActivo(gd);" in manejador, (
        "el punto activo tiene que repintarse en el camino inmediato del deslizador"
    )


@pytest.mark.parametrize("tablero", sorted(TABLEROS))
def test_the_cloud_has_exactly_two_opacity_levels(fuentes, tablero):
    """The three-level cascade is gone on purpose. Its middle tone existed to
    rank cloud / circuit / marked vanos, and once the subject is a single
    (circuit, window) pair there is nothing left to rank -- marked vanos are
    still told apart by size and by their coloured ring."""
    fuente = fuentes[tablero]
    foco = re.search(r"^OPACIDAD_FOCO = ([0-9.]+)$", fuente, re.M)
    fondo = re.search(r"^OPACIDAD_FONDO = ([0-9.]+)$", fuente, re.M)
    assert foco and float(foco.group(1)) == 1.0
    assert fondo and float(fondo.group(1)) == 0.30
    # Las constantes de la cascada vieja no pueden sobrevivir a medias: una sola que
    # quede referenciada deja dos reglas de opacidad compitiendo en la misma figura.
    for muerta in ("OPACIDAD_NUBE", "OPACIDAD_NUBE_ATENUADA", "OPACIDAD_FUERA_VENTANA",
                   "OPACIDAD_RESALTADO_FUERA", "opacidadNube", "opacidadNubeAtenuada",
                   "opacidadFueraVentana", "opacidadResaltadoFuera"):
        assert not re.search(r"\b" + muerta + r"\b", fuente), muerta
    assert "'opacidadFoco': OPACIDAD_FOCO" in fuente
    assert "'opacidadFondo': OPACIDAD_FONDO" in fuente


def test_board_03_needs_the_circuit_of_each_cloud_point(fuentes):
    """In 03 a cloud point is a (circuit, window) pair and the two coordinates
    are cached separately so that moving the slider repaints opacities instead
    of rebuilding 1.738 points. The window alone cannot answer the new
    question, so the circuit has to be cached alongside it."""
    fuente = fuentes["03"]
    assert "var VENTANA_PUNTO = [[], [], [], []], CIRCUITO_PUNTO = [[], [], [], []];" in fuente
    assert "CIRCUITO_PUNTO[g].push(ci);" in fuente
    assert "col[i] === w && (sinCircuito || circ[i] === CIRCUITO_FOCO)" in fuente


def test_board_04_never_lights_up_another_circuit(fuentes):
    """In 04 the buckets are already split by circuit: `nube` holds the OTHER
    circuits and can never be the circuit of interest, while `circuito`,
    `elegidos` and `otros` are all built by filtering on the active one. The
    only exception is having no circuit selected, where everything falls into
    `nube` and the window has to rule alone -- otherwise the whole cloud would
    go uniformly grey and the slider would say nothing."""
    fuente = fuentes["04"]
    assert "function opsDe(ventanas, w, delCircuito) {" in fuente
    assert "(delCircuito && ventanas[i] === w) ? CTX.opacidadFoco : CTX.opacidadFondo" in fuente
    assert "ops.push(opsDe(VENT_NUBE[g], w, SIN_CIRCUITO));" in fuente
    assert "ops.push(opsDe(VENT_CIRC[g], w, true));" in fuente
    assert "SIN_CIRCUITO = ciSel < 0;" in fuente


@pytest.mark.parametrize("tablero", sorted(TABLEROS))
def test_the_cloud_starts_at_the_background_level(fuentes, tablero):
    """The traces are born with the background opacity, not the old cloud one.
    The browser overwrites it with a per-point array on the first repaint, but
    a figure rendered before that -- or read straight out of the notebook --
    must already obey the same rule instead of showing a third value."""
    assert "opacity=OPACIDAD_FONDO)" in fuentes[tablero]
