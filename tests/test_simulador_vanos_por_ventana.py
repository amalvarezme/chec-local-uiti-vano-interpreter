"""Contract tests: la lista de vanos del cuaderno 06 es la del DATASET; la
ventana mueve la SELECCION.

Historia de las tres versiones de este contrato, porque las tres se tomaron por
buenas y las dos primeras fallaban en silencio:

  1. La lista era la union de lo que el mapa dibuja y lo que la tabla de bolsas
     trae. Medido sobre 30 circuitos, solo el 21% de esas casillas tenia eventos
     en una ventana dada: marcar cinco vanos, pulsar "Simular" y no ver aparecer
     nada era el caso NORMAL.
  2. La lista se recorto a los vanos con eventos en la ventana activa y se
     repoblaba en cada paso del deslizador. Eso arreglo lo anterior y trajo lo
     suyo: las casillas cambiaban de sitio bajo la mano, un vano que se venia
     siguiendo desaparecia al avanzar un mes, y el tope de quince deshabilitaba
     las casillas sin marcar en cuanto la auto-marca llenaba el cupo -- con lo
     que agregar un vano tocandolo en el mapa era imposible sin desmarcar otro.
  3. La de ahora: la lista es el circuito COMPLETO -- sus vanos con eventos en
     todo el periodo, la misma que ofrece el tablero de 04 -- y lo que el
     deslizador mueve es quien esta marcado. La lista es el universo; la ventana
     es el foco.

Lo que la version 2 protegia -- pulsar "Simular" sin nada que puntuar -- lo dice
ahora `_actualizar_aviso_vanos`, y decirlo es mejor que impedirlo: un vano sin
eventos en marzo sigue siendo el vano que interesa, y su serie de tiempo es
justo donde se ve que en febrero si los tuvo.

Se fija contra la FUENTE del cuaderno (sin ejecutarlo, para que siga siendo
rapido). La mecanica del selector -- marcar por codigo, emitir un solo cambio de
`value`, dibujar el mensaje de lista vacia -- se prueba de verdad, con widgets
vivos, en `tests/test_vano_widgets.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import ayudas_tableros
import pytest

RAIZ = Path(__file__).resolve().parents[1]
TABLERO = "06_uiti_vano_explicabilidad_simulador"


# El codigo del tablero salio del cuaderno a `src/chec_tableros/simulador/`
# (fase 2 de `sdd/retire-base-apps-notebooks`). Lo que se afirma aqui son
# invariantes del TABLERO y no del formato en que se guardaba, asi que la fuente
# se pide al ayudante y las afirmaciones no cambian.
@pytest.fixture(scope="module")
def fuente() -> str:
    return ayudas_tableros.fuente_de_tablero(TABLERO)


# ------------------------------------------------------- la lista es el circuito


def test_the_markable_vanos_do_not_depend_on_the_active_window(fuente):
    """Sin la ventana como argumento la lista NO PUEDE recortarse a ella, que es
    justo la propiedad que se busca: la caja de casillas se queda quieta mientras
    el deslizador se mueve."""
    assert "def _vanos_marcables(circuito):" in fuente
    assert "def _vanos_marcables(circuito, ventana_i):" not in fuente


def test_the_markable_vanos_are_the_circuit_vanos_with_events_in_the_dataset(fuente):
    """Salen de `VANOS_POR_CIRCUITO`, que se deriva de `TABLA`.

    No de `clases_para`, que es la ventana; ni de `GEO_POR_CIRCUITO`, que trae
    tambien los tramos que nunca tuvieron un evento y no son marcables en ningun
    periodo. Es la MISMA fuente que usa el tablero de 04, y ese es el punto: dos
    tableros sobre el mismo circuito no pueden ofrecer dos listas distintas.
    """
    cuerpo = ayudas_tableros.cuerpo_de_funcion(fuente, "_vanos_marcables")
    assert "VANOS_POR_CIRCUITO.get(circuito" in cuerpo
    assert "clases_para(" not in cuerpo
    assert "GEO_POR_CIRCUITO" not in cuerpo


def test_the_vano_selector_has_no_cap(fuente):
    """Sin `maximo`, y eso es lo que permite dos cosas que el usuario pidio: que
    un clic en el mapa AGREGUE un vano aunque la auto-marca ya haya puesto
    quince, y que las casillas sin marcar no se deshabiliten solas.

    El tope protegia la rejilla de controles -- una columna por vano --, y eso lo
    resuelve hoy la paginacion (`VANOS_POR_PAGINA`).
    """
    llamada = fuente[fuente.index("vano_widget = construir_selector_vanos("):]
    llamada = llamada[: llamada.index("\n\n")]
    assert "maximo=" not in llamada


def test_an_empty_circuit_says_so_in_the_panel(fuente):
    """Es el texto que el usuario ve dentro de la caja de vanos cuando el
    circuito no registro un solo evento en todo el periodo. Una caja vacia y muda
    se lee como que el tablero se rompio."""
    assert "mensaje_vacio=" in fuente
    assert "Circuito sin eventos" in fuente


# --------------------------------------------------- la ventana mueve la seleccion


def test_moving_the_window_reselects_the_top_of_that_window(fuente):
    """El deslizador marca los vanos de mayor UITI EN ESA VENTANA y descarta la
    marca anterior. Es un reemplazo: acumular ventanas dejaria marcado todo lo
    que alguna vez tuvo un evento, y el deslizador no diria nada."""
    assert "def _on_ventana_change(" in fuente
    assert "ventana_widget.observe(_on_ventana_change, names='value')" in fuente
    cuerpo = fuente[fuente.index("def _on_ventana_change("):]
    cuerpo = cuerpo[: cuerpo.index("def _on_circuito_change(")]
    assert "_auto_seleccion_ventana(circuito, ventana_i)" in cuerpo
    # Y ya NO repuebla la lista: el universo no cambia con la ventana.
    assert "poblar(" not in cuerpo


def test_the_window_autoselection_uses_the_shared_ranking(fuente):
    """El criterio vive en `top_vanos_de_ventana` (probado con datos en
    `tests/test_ventanas_015.py`) y no escrito aqui: el tablero de 04 auto-marca
    con la misma regla, y dos reglas escritas por separado se separan."""
    cuerpo = fuente[fuente.index("def _auto_seleccion_ventana("):]
    cuerpo = cuerpo[: cuerpo.index("def _auto_seleccion_circuito(")]
    assert "top_vanos_de_ventana(TABLA, circuito, ventana_i, top=TOP_VANOS_VENTANA)" in cuerpo


def test_choosing_a_circuit_selects_the_top_of_the_whole_period(fuente):
    """Al aterrizar en un circuito se marcan los vanos de mayor UITI del PERIODO
    -- las mismas quince barras del perfil de la fila 3 --, no los de la ventana
    inicial. Es lo que deja al perfil de arriba y a la serie de tiempo de abajo
    hablando del mismo conjunto."""
    cuerpo = fuente[fuente.index("def _auto_seleccion_circuito("):]
    cuerpo = cuerpo[: cuerpo.index("def _fijar_seleccion(")]
    assert "perfil_uiti_por_vano(TABLA, circuito, ventanas=VENTANAS," in cuerpo
    assert "top=TOP_VANOS_PERFIL" in cuerpo

    manejador = fuente[fuente.index("def _on_circuito_change("):]
    manejador = manejador[: manejador.index("def _al_hacer_clic(")]
    assert "vano_widget.value = tuple(_auto_seleccion_circuito(circuito))" in manejador


def test_the_dashboard_opens_with_that_same_selection(fuente):
    """Abrir el tablero y cambiar de circuito tienen que dejar el MISMO estado.
    Sin esto, uno abre vacio y el otro con el top marcado."""
    assert "_fijar_seleccion(_auto_seleccion_circuito(circuito_widget.value))" in fuente


def test_changing_circuit_drops_the_selection_whole(fuente):
    """El universo de vanos es otro: conservar ahi dejaria marcados fids del
    circuito anterior."""
    cuerpo = fuente[fuente.index("def _on_circuito_change("):]
    cuerpo = cuerpo[: cuerpo.index("def _al_hacer_clic(")]
    assert "conservar=" not in cuerpo
    # La ventana se resuelve ANTES de repoblar: asignar `options` reajusta `value`
    # a la primera opcion, y leerlo despues perdia la ventana en cada cambio.
    assert cuerpo.index("ventana_widget.value =") < cuerpo.index("vano_widget.poblar(")


def test_a_map_click_adds_beyond_the_autoselection(fuente):
    """El clic entra por `alternar`, que sin tope en el selector ya no rechaza
    nada. Y entra a la serie de tiempo por el mismo camino que todo lo demas: la
    serie sale de los marcados."""
    cuerpo = fuente[fuente.index("def _al_hacer_clic("):]
    cuerpo = cuerpo[: cuerpo.index("# SOLO el mapa base.")]
    assert "vano_widget.alternar(fid)" in cuerpo


def test_the_time_series_pool_is_sized_from_the_data(fuente):
    """El pozo ya no es una constante: son tantas ranuras como vanos tiene el
    circuito MAS grande, que es el techo de lo que el usuario puede llegar a marcar
    -- las casillas solo ofrecen vanos de un circuito.

    Un numero fijo no podia servir. Valia treinta, de cuando la seleccion la ponia
    una auto-marca de quince; con un boton por grupo de criticidad un circuito marca
    cientos, y de esos el panel dibujaba treinta. Que de verdad los dibuje TODOS lo
    prueba pulsando
    `test_simulador_derivacion.py::test_la_serie_de_tiempo_dibuja_todos_los_vanos_marcados`;
    aqui se pincha el mecanismo, que es lo que el fuente si puede decir."""
    assert "MAX_VANOS_SERIE = max((len(v) for v in VANOS_POR_CIRCUITO.values())" in fuente
    assert "[:MAX_VANOS_SERIE]" not in fuente     # el recorte de la serie se retiro
    assert "2 * MAX_VANOS_SERIE" in fuente        # la asercion del inventario de trazas


def test_the_repaint_only_touches_the_slots_in_use(fuente):
    """Con el pozo dimensionado al circuito mas grande, recorrerlo entero en cada
    repintado cobraba el mismo peaje con cero vanos marcados que con todos: medido,
    189 ms por clic sin nada marcado contra 64 ms con el pozo viejo de treinta. Se
    recorren las ranuras en uso mas las que hay que vaciar, asi que el costo lo pone
    la seleccion y no el tamanio del pozo."""
    cuerpo = fuente[fuente.index("_tam_uiti, _tam_eventos = _tamanos_ventana_activa"):][:3000]
    assert "for _cupo in range(max(len(series), _CUPOS_EN_USO)):" in cuerpo
    assert "_CUPOS_EN_USO = len(series)" in cuerpo


def test_the_overflow_notice_is_gone_because_overflow_is_impossible(fuente):
    """El aviso de 'su serie de tiempo no se dibuja' describia un limite retirado.
    Dejarlo era prosa prometiendo un recorte que ya no ocurre, que es peor que no
    decir nada: el usuario buscaria en el panel unos vanos que si estan."""
    cuerpo = fuente[fuente.index("def _actualizar_aviso_vanos("):]
    cuerpo = cuerpo[: cuerpo.index("# Cambiar de circuito o mover la ventana")]
    assert "sobran" not in cuerpo
    assert "su serie de tiempo no " not in cuerpo
    # Lo que SI sigue diciendo: cuantos de los marcados tienen celda en la ventana.
    assert "tienen eventos en la ventana" in cuerpo


# ------------------------------------------------ el encuadre sigue a la ventana


def test_moving_the_window_reframes_the_base_map(fuente):
    """Mover el deslizador tiene que MOVER el mapa, no solo repintarlo.

    Medido en el navegador antes de este cambio: pasar de V11 a V1 en AGU23L12
    redistribuia las capas de clase (`0,51,30,0,828` -> `42,213,0,0,654`) y
    cambiaba la leyenda, pero dejaba `center` y `zoom` identicos. Como el 86% del
    dibujo es la linea negra de "sin evento", lo unico que se movia era el color
    de unos pocos tramos cortos, y el tablero se leia como que no habia pasado
    nada.
    """
    assert "def _encuadrar_ventana(" in fuente
    cuerpo = fuente[fuente.index("def _on_ventana_change("):]
    cuerpo = cuerpo[: cuerpo.index("def _on_circuito_change(")]
    assert "_encuadrar_ventana(" in cuerpo, (
        "el deslizador reselecciona y repinta pero no reencuadra")


def test_the_window_frame_covers_the_vanos_with_events(fuente):
    """El encuadre sale de los vanos CON eventos en esa ventana -- los mismos que
    la auto-marca elige entre -- y no de la geometria entera del circuito:
    encuadrar sobre todo el circuito es exactamente la vista que ya habia y que
    no se movia."""
    cuerpo = fuente[fuente.index("def _encuadrar_ventana("):]
    cuerpo = cuerpo[: cuerpo.index("# Cuantas ventanas hacen falta")]
    assert "clases_para(circuito, ventana_i)" in cuerpo
    assert "bounds_de_fids(" in cuerpo
    # Y una ventana sin un solo evento no puede dejar el mapa sobre un punto
    # inventado: se cae a la vista del circuito, que es la que ya existia.
    assert "_vista_del_circuito(circuito)" in cuerpo


def test_only_the_window_reframes_the_base_map(fuente):
    """Marcar un vano NO puede mover el mapa.

    `_redibujar_mapa_historico` corre en cada clic sobre el mapa y en cada
    casilla. Reencuadrar ahi movería el dibujo bajo la mano del usuario justo
    mientras esta marcando, que es peor que no moverse. El reencuadre pertenece
    al deslizador y a nadie mas; para lo demas esta el boton "Centrar mapa base".
    """
    cuerpo = fuente[fuente.index("def _redibujar_mapa_historico("):]
    cuerpo = cuerpo[: cuerpo.index("def _alto_del_mapa_px(")]
    assert "_encuadrar_ventana(" not in cuerpo
    assert "_aplicar_vista(" not in cuerpo
