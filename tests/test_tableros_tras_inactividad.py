"""Los cuatro tableros estaticos despues de irse a otra cosa y volver.

## Lo que se reporto

"Al abrir los tableros y dejar de tener actividad, o abrir otros programas en el pc,
y volver al navegador de los tableros, ya no tienen funcionalidad."

El reporte no distingue entre los cinco, asi que hay que preguntarselo a los cinco.
Estos cuatro son un HTML congelado: toda su interactividad la resuelve el navegador
con los datos que ya bajo, sin nadie al otro lado. La hipotesis era, por tanto, que
aguantan; pero "deberia aguantar" no es una medicion, y el simulador -- que si tiene
un kernel detras -- se comprueba en `test_simulador_tras_inactividad.py`.

## Los tres gestos, y por que no se pueden escribir en JavaScript

  * **La pestania de fondo.** Chrome CONGELA las pestanias que quedan detras. No es
    una pausa del JavaScript: cierra el WebSocket, y por eso hace falta el estado de
    verdad del navegador (`Page.setWebLifecycleState`) y no un `setTimeout`.
  * **Quedarse sin red.** La tapa del portatil, el wifi que cambia de red: la pagina
    sigue montada y sus sockets se caen.
  * **La pestania descartada.** Cuando falta memoria, el navegador DESCARTA una
    pestania de fondo y la vuelve a cargar al volver a ella.

## Que se afirma

Que la figura RESPONDE, no que el DOM acepte el evento. Un `select` al que ya no
escucha nadie tambien cambia de valor, y un tablero muerto se ve identico a uno vivo:
sigue dibujado, con sus controles en su sitio. Lo unico que lo separa es que al
moverle algo no cambia nada. Por eso se compara lo dibujado antes y despues.

Son lentas -- levantan el tablero, Chrome, y se pasan un minuto congeladas -- asi que
van detras de una variable de entorno:

    TABLEROS_VIVOS=1 pytest tests/test_tableros_tras_inactividad.py -v
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

import ayudas_navegador as N
import ayudas_paneles as P

APAGADAS = os.environ.get("TABLEROS_VIVOS", "") not in ("1", "true", "si")

# Pedirlas y que se salten todas en silencio es la forma de creer que se corrieron.
# Es la misma regla que `test_simulador_flujo_vivo.py`, y esta ahi por un paso real:
# una prueba afirmo durante semanas un titulo que ya no existia, y nadie se entero
# porque `pytest -q` solo decia "20 skipped".
if not APAGADAS:
    _faltas = [m for m in (P.motivo_para_saltar(p) for p in P.PANELES) if m]
    if _faltas:
        raise RuntimeError(
            f"TABLEROS_VIVOS esta puesto pero {_faltas[0]}. Instala el entorno de la "
            "aplicacion con su `instalar-en-terminal.command` y construye su panel "
            "abriendola una vez.")

pytestmark = pytest.mark.skipif(APAGADAS, reason="TABLEROS_VIVOS no esta puesto")

# Cuanto se deja la pestania congelada. Por encima de los 30 s que Chrome tarda en
# congelar una de fondo, y por encima del minuto que cuesta ir a otro programa y
# volver.
CONGELADA = 60.0

# Cuanto se deja sin red. Corto a proposito: en estos cuatro no hay nada al otro lado
# que se pueda perder, asi que lo que se comprueba es que la caida no rompa lo que ya
# estaba cargado.
SIN_RED = 30.0


@pytest.fixture(scope="module", params=P.PANELES, ids=lambda p: p.carpeta)
def tablero(request):
    """Un tablero servido en su propio puerto, con su Chrome, para todo el modulo.

    Uno por tablero y no uno por prueba: levantar el servidor y el navegador cuesta
    mas que todas las pruebas juntas, y lo que se persigue aqui es precisamente lo
    que le pasa a UNA sesion larga.
    """
    panel = request.param
    servido = P.Servido(panel).arrancar()
    carpeta = Path(tempfile.mkdtemp(prefix=f"chrome-{panel.carpeta}-"))
    nav = N.Navegador(carpeta, ancho=1600, alto=1100)
    P.cargar(nav, servido)
    N.espiar_consola(nav)
    yield servido, nav
    nav.cerrar()
    servido.apagar()


def _responde(nav, panel, cuando: str) -> None:
    r = P.mover(nav, panel)
    assert r["responde"], (
        f"{panel.carpeta}: {cuando}, mover {panel.control} no cambio la figura "
        f"({r['gesto']}; antes {r['antes']}, despues {r['despues']})")


def test_recien_abierto_responde(tablero):
    """La linea base. Sin esto, lo que digan las demas no significa nada."""
    servido, nav = tablero
    _responde(nav, servido.panel, "recien abierto")


def test_sigue_respondiendo_tras_dejar_la_pestania_de_fondo(tablero):
    """Irse a otro programa un minuto. Chrome congela la pestania mientras tanto."""
    servido, nav = tablero
    N.congelar(nav, CONGELADA)
    _responde(nav, servido.panel, f"tras {CONGELADA:.0f} s con la pestania congelada")


def test_sigue_respondiendo_tras_quedarse_sin_red(tablero):
    """La tapa del portatil, el wifi. El tablero ya tiene sus datos: no depende de eso."""
    servido, nav = tablero
    N.sin_red(nav, SIN_RED, gracia=5.0)
    _responde(nav, servido.panel, f"tras {SIN_RED:.0f} s sin red")


def test_sigue_respondiendo_si_el_navegador_descarta_la_pestania(tablero):
    """Sin memoria, el navegador descarta la pestania de fondo y la recarga al volver.

    Es el unico de los tres gestos en el que el tablero se vuelve a bajar entero, asi
    que tambien comprueba que el servidor sigue sirviendo despues de un rato quieto.
    """
    servido, nav = tablero
    nav.cmd("Page.navigate", url="about:blank")
    P.cargar(nav, servido)
    N.espiar_consola(nav)
    _responde(nav, servido.panel, "tras descartar y recargar la pestania")


def test_se_cierra_por_su_boton_y_se_vuelve_a_abrir(tablero):
    """Cerrar el tablero y volverlo a abrir, que es lo que hace quien lo ve mudo.

    Va la ultima del modulo a proposito: deja el tablero recien levantado, que es
    como lo encontro la primera.
    """
    servido, nav = tablero
    servido.apagar_por_su_puerta()
    assert not servido.sirve(), (
        f"{servido.panel.carpeta}: sigue servido despues de pulsar su boton de cerrar")

    servido.apagar()
    servido.arrancar()
    P.cargar(nav, servido)
    N.espiar_consola(nav)
    _responde(nav, servido.panel, "tras cerrarlo y volverlo a abrir")
