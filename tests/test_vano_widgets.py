"""RED/GREEN tests for PR2a of notebook 01.5 (widget constructor).

Covers `chec_local_interpreter.vano_widgets.widget_for_knob`, the ONLY
place `ipywidgets` is imported for the Knob catalog -- and it is imported
lazily, inside the function, so `vano_controls` (tested in
`tests/test_vano_controls.py`) never needs ipywidgets installed.

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domain `vano-risk-simulation`, requirement "Control type follows
    variable kind")
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (section B)
"""

from __future__ import annotations

import pytest

pytest.importorskip("ipywidgets")

from chec_local_interpreter.vano_controls import Knob
from chec_local_interpreter.vano_widgets import (
    MAX_VANOS_ANALISIS,
    VANOS_POR_PAGINA,
    widget_for_knob,
)


def _numeric_knob(**overrides) -> Knob:
    fields = dict(
        id="LONGITUD",
        label="LONGITUD",
        kind="numeric",
        feature_names=("LONGITUD",),
        bounds=(0.0, 10.0),
        categories=None,
        default=5.0,
        step=0.1,
    )
    fields.update(overrides)
    return Knob(**fields)


def _categorical_knob(**overrides) -> Knob:
    fields = dict(
        id="TIPO",
        label="TIPO",
        kind="categorical",
        feature_names=("TIPO",),
        bounds=None,
        categories=("A", "B", "C"),
        default="B",
        step=None,
    )
    fields.update(overrides)
    return Knob(**fields)


def _constant_knob(**overrides) -> Knob:
    fields = dict(
        id="CNT_FASES",
        label="CNT_FASES",
        kind="constant",
        feature_names=("CNT_FASES",),
        bounds=(3.0, 3.0),
        categories=None,
        default=3.0,
        step=None,
    )
    fields.update(overrides)
    return Knob(**fields)


def test_widget_for_numeric_knob_returns_float_slider():
    import ipywidgets as widgets

    widget = widget_for_knob(_numeric_knob())

    assert isinstance(widget, widgets.FloatSlider)
    assert widget.min == 0.0
    assert widget.max == 10.0
    assert widget.step == pytest.approx(0.1)
    assert widget.value == pytest.approx(5.0)
    assert widget.disabled is False


def test_widget_for_categorical_knob_returns_dropdown():
    import ipywidgets as widgets

    widget = widget_for_knob(_categorical_knob())

    assert isinstance(widget, widgets.Dropdown)
    assert tuple(widget.options) == ("A", "B", "C")
    assert widget.value == "B"


def test_widget_for_constant_knob_returns_disabled_float_text():
    import ipywidgets as widgets

    widget = widget_for_knob(_constant_knob())

    assert isinstance(widget, widgets.FloatText)
    assert widget.disabled is True
    assert widget.value == pytest.approx(3.0)


def test_widget_for_numeric_knob_falls_back_to_bounds_when_default_missing():
    import ipywidgets as widgets

    widget = widget_for_knob(_numeric_knob(default=None))

    assert isinstance(widget, widgets.FloatSlider)
    assert widget.value == pytest.approx(0.0)


def test_widget_for_categorical_knob_falls_back_to_first_option_when_default_missing():
    widget = widget_for_knob(_categorical_knob(default=None))

    assert widget.value == "A"


# --- PR6: selector de vanos por casilla (reemplaza el SelectMultiple) -------


def test_selector_vanos_exposes_a_value_trait_and_one_checkbox_per_vano():
    """01.4 marca vanos con CASILLAS, no con una lista de seleccion
    multiple. El selector expone `value` como trait para que las celdas de
    figura/ranking/simulacion sigan usando `observe(names='value')` sin
    saber que hay casillas detras."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB", "VC"])

    assert selector.value == ()
    assert list(selector.casillas) == ["VA", "VB", "VC"]
    assert all(caja.value is False for caja in selector.casillas.values())


def test_selector_vanos_checkbox_and_click_share_one_state():
    """Alternar la casilla y alternar por clic en el mapa tienen que llegar
    al MISMO `value`: si llevaran registros separados, la lista, el mapa y
    el ranking podrian contar cosas distintas (01.4, `marcarPorFid`)."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB", "VC"])
    vistos = []
    selector.observe(lambda cambio: vistos.append(cambio["new"]), names="value")

    selector.casillas["VB"].value = True          # por casilla
    assert selector.value == ("VB",)

    selector.alternar("VA")                        # por clic en el mapa
    assert selector.value == ("VA", "VB")

    selector.alternar("VB")                        # el clic tambien desmarca
    assert selector.value == ("VA",)
    assert selector.casillas["VB"].value is False
    assert vistos == [("VB",), ("VA", "VB"), ("VA",)]


def test_selector_vanos_repopulating_clears_the_previous_selection():
    """Cambiar de circuito cambia el universo de vanos: conservar la
    seleccion anterior dejaria marcados fids que ya no existen en el mapa."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB"])
    selector.alternar("VA")
    assert selector.value == ("VA",)

    selector.poblar(["VX", "VY"])
    assert selector.value == ()
    assert list(selector.casillas) == ["VX", "VY"]


def test_selector_vanos_exposes_its_inner_box_as_a_public_attribute():
    """`caja` is the seam notebook 01.5's panel cell reaches for
    (`vano_widget.caja.add_class('lista-vanos')`). It was renamed once from
    `_caja` and nothing in this suite noticed -- the breakage only surfaced in a
    live kernel, twice. Pinning it here turns a rename into a RED test."""
    import ipywidgets as widgets

    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB"])

    assert isinstance(selector.caja, widgets.Box)
    assert selector.caja in selector.children
    assert tuple(selector.caja.children) == tuple(selector.casillas.values())

    selector.caja.add_class("lista-vanos")  # exactly what the notebook cell does
    assert "lista-vanos" in selector.caja._dom_classes


def test_selector_marcar_todos_ticks_everything_with_a_single_value_event():
    """"Marcar todos" (paridad 01.4) tiene que emitir UN solo cambio de `value`.
    Dejar que cada casilla notifique por su cuenta significaria un repintado del
    mapa por vano -- cientos en un circuito grande."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB", "VC"])
    eventos = []
    selector.observe(lambda cambio: eventos.append(cambio["new"]), names="value")

    selector.marcar_todos()

    assert selector.value == ("VA", "VB", "VC")
    assert all(caja.value is True for caja in selector.casillas.values())
    assert eventos == [("VA", "VB", "VC")]


def test_selector_desmarcar_todos_clears_everything_with_a_single_value_event():
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB", "VC"])
    selector.marcar_todos()
    eventos = []
    selector.observe(lambda cambio: eventos.append(cambio["new"]), names="value")

    selector.desmarcar_todos()

    assert selector.value == ()
    assert all(caja.value is False for caja in selector.casillas.values())
    assert eventos == [()]


def test_selector_casillas_accepts_label_value_pairs():
    """El selector de variables del simulador necesita rotulo != clave: la casilla
    muestra "Precipitacion (12 lags)" y `value` devuelve el knob id `clima:prep`.
    El selector de vanos no lo necesitaba porque ahi el rotulo ES el fid."""
    from chec_local_interpreter.vano_widgets import construir_selector_casillas

    selector = construir_selector_casillas(
        [("Precipitacion (12 lags)", "clima:prep"), ("CNT_TRF", "CNT_TRF")],
        titulo="Variables",
    )

    assert list(selector.casillas) == ["clima:prep", "CNT_TRF"]
    assert selector.casillas["clima:prep"].description == "Precipitacion (12 lags)"

    selector.casillas["clima:prep"].value = True
    selector.casillas["CNT_TRF"].value = True

    assert selector.value == ("clima:prep", "CNT_TRF")  # varias a la vez, en orden de opcion


def test_selector_casillas_unticking_leaves_the_other_selections_alone():
    """Es la razon de ser del cambio: con un `SelectMultiple` marcar una variable
    sin ctrl borraba las demas. Con casillas, cada una es independiente."""
    from chec_local_interpreter.vano_widgets import construir_selector_casillas

    selector = construir_selector_casillas([("A", "a"), ("B", "b"), ("C", "c")])
    for clave in ("a", "b", "c"):
        selector.casillas[clave].value = True
    assert selector.value == ("a", "b", "c")

    selector.casillas["b"].value = False

    assert selector.value == ("a", "c")


def test_selector_vanos_keeps_scalar_options_labelled_by_their_own_fid():
    """Regresion: generalizar el selector a pares (rotulo, clave) no debe romper la
    forma escalar que usa el selector de vanos."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos([20130434, "VB"])

    assert list(selector.casillas) == ["20130434", "VB"]
    assert selector.casillas["20130434"].description == "20130434"


def test_selector_vanos_ignores_a_click_on_an_unknown_fid():
    """Un clic puede caer sobre un tramo cuyo fid no esta en la lista (el
    mapa dibuja la geometria del circuito, que no siempre coincide con los
    vanos con eventos). No debe crear una casilla fantasma ni fallar."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA"])
    selector.alternar("DESCONOCIDO")
    assert selector.value == ()
    assert list(selector.casillas) == ["VA"]


# --- Tope de vanos analizables (cuaderno 06) -----------------------------------------


from chec_local_interpreter.vano_widgets import construir_selector_vanos


def test_selector_stops_accepting_ticks_once_the_cap_is_reached():
    """El cuaderno 06 simula hasta 5 vanos: cada uno recibe su propia columna de
    controles, y una rejilla de 26 variables por 20 vanos no se lee ni se llena.
    Al llegar al tope las casillas SIN marcar se deshabilitan, en vez de aceptar
    el clic y revertirlo -- un clic que se deshace solo parece un fallo."""
    selector = construir_selector_vanos(["A", "B", "C"], maximo=2)

    selector.casillas["A"].value = True
    selector.casillas["B"].value = True

    assert selector.value == ("A", "B")
    assert selector.casillas["C"].disabled is True
    # Las marcadas siguen habilitadas: hay que poder soltar una para tomar otra.
    assert selector.casillas["A"].disabled is False


def test_freeing_a_slot_re_enables_the_rest():
    selector = construir_selector_vanos(["A", "B", "C"], maximo=2)
    selector.casillas["A"].value = True
    selector.casillas["B"].value = True

    selector.casillas["A"].value = False

    assert selector.value == ("B",)
    assert selector.casillas["C"].disabled is False


def test_a_map_click_cannot_get_past_the_cap_either():
    """El clic en el mapa entra por `alternar`, no por la casilla, asi que el
    tope tiene que vivir en el estado y no en la interfaz: si no, el mapa seria
    una puerta trasera para marcar el sexto vano."""
    selector = construir_selector_vanos(["A", "B", "C"], maximo=2)
    selector.alternar("A")
    selector.alternar("B")

    selector.alternar("C")

    assert selector.value == ("A", "B")
    assert selector.casillas["C"].value is False


def test_marcar_todos_respects_the_cap_and_takes_the_first_ones():
    """`marcar_todos` sigue existiendo para los cuadernos sin tope. Con tope no
    puede pasarse: marca los primeros y para."""
    selector = construir_selector_vanos(["A", "B", "C", "D"], maximo=2)

    selector.marcar_todos()

    assert selector.value == ("A", "B")


def test_without_a_cap_nothing_changes_for_the_other_notebooks():
    """01.4 y sus hermanos marcan cientos de vanos a la vez y no pueden heredar
    un tope que nadie les puso."""
    selector = construir_selector_vanos(["A", "B", "C"])

    selector.marcar_todos()

    assert selector.value == ("A", "B", "C")
    assert all(not c.disabled for c in selector.casillas.values())


def test_repopulating_clears_the_selection_and_re_enables_every_checkbox():
    """Cambiar de circuito suelta la seleccion; si las casillas quedaran
    deshabilitadas del circuito anterior, el nuevo arrancaria bloqueado."""
    selector = construir_selector_vanos(["A", "B", "C"], maximo=2)
    selector.casillas["A"].value = True
    selector.casillas["B"].value = True

    selector.poblar(["X", "Y", "Z"])

    assert selector.value == ()
    assert all(not c.disabled for c in selector.casillas.values())


# --- Selector por COLUMNAS (las variables del simulador, cuaderno 06) ------------------


def test_the_selector_can_lay_its_checkboxes_out_in_titled_columns():
    """Dieciocho casillas en una lista corrida obligan a recordar el veredicto de
    cada variable para saber a cual de las dos preguntas pertenece. En columnas
    eso lo dice la posicion, y el titulo lo confirma."""
    from chec_local_interpreter.vano_widgets import construir_selector_casillas

    selector = construir_selector_casillas(
        columnas=[("Intervencion", [("Altura", "ALTURA"), ("Poda", "NR_T")]),
                  ("Escenario", [("Lluvia", "clima:prep")])],
    )

    assert list(selector.casillas) == ["ALTURA", "NR_T", "clima:prep"]
    # Una caja por columna, cada una con su titulo mas sus casillas.
    assert len(selector.caja.children) == 2
    assert len(selector.caja.children[0].children) == 3   # titulo + 2 casillas
    assert len(selector.caja.children[1].children) == 2   # titulo + 1 casilla


def test_the_value_of_a_column_selector_follows_the_declared_order():
    """El orden importa: es el que usan la rejilla de controles y el resumen, y si
    cambiara entre repintados las columnas se barajarian bajo la mano."""
    from chec_local_interpreter.vano_widgets import construir_selector_casillas

    selector = construir_selector_casillas(
        columnas=[("A", [("uno", "1"), ("dos", "2")]), ("B", [("tres", "3")])],
    )

    selector.casillas["3"].value = True
    selector.casillas["1"].value = True

    assert selector.value == ("1", "3")


def test_an_empty_column_still_renders_so_the_others_keep_their_place():
    """Cuatro huecos fijos. Una columna que aparece y desaparece corre a las demas
    de sitio cada vez que cambia el catalogo."""
    from chec_local_interpreter.vano_widgets import construir_selector_casillas

    selector = construir_selector_casillas(
        columnas=[("Llena", [("uno", "1")]), ("Vacia", [])],
    )

    assert len(selector.caja.children) == 2
    assert len(selector.caja.children[1].children) == 1   # solo su titulo


def test_the_flat_option_list_keeps_working_for_the_vano_selector():
    """Los vanos siguen siendo una lista corrida con scroll: son cientos y no
    tienen grupos."""
    from chec_local_interpreter.vano_widgets import construir_selector_vanos

    selector = construir_selector_vanos(["VA", "VB"])

    assert list(selector.casillas) == ["VA", "VB"]
    assert len(selector.caja.children) == 2   # las dos casillas, sin columnas


def test_the_analysis_cap_leaves_room_for_the_whole_circuit_diagnostic():
    """El diagnostico del circuito estudia los diez vanos mas criticos y ofrece
    aplicarles la sugerencia de golpe. Con el tope en cinco, la mitad del
    diagnostico quedaba sin poder ejecutarse."""
    assert MAX_VANOS_ANALISIS >= 10


def test_the_grid_pages_at_fewer_vanos_than_the_cap():
    """Lo que el tope de cinco protegia era la REJILLA, no la seleccion: diez
    columnas de veintiseis controles no se leen ni se llenan. Eso lo resuelve la
    paginacion, no un tope mas bajo."""
    assert VANOS_POR_PAGINA < MAX_VANOS_ANALISIS


# --- Marcar por codigo: el diagnostico del 06 escribe `value` directamente -------------


def test_setting_value_ticks_the_checkboxes():
    """El diagnostico del cuaderno 06 marca sus vanos asignando `value`. Sin
    sincronizar las casillas, el trait decia diez y la lista se veia vacia: el mapa
    los resaltaba -- lee `value` -- y el panel de seleccion manual no."""
    selector = construir_selector_vanos(["A", "B", "C"])

    selector.value = ("A", "C")

    assert [c for c, caja in selector.casillas.items() if caja.value] == ["A", "C"]
    assert selector.value == ("A", "C")


def test_a_manual_tick_after_setting_value_does_not_wipe_the_selection():
    """El fallo que hacia esto urgente: `_al_cambiar_casilla` recalcula `value`
    DESDE las casillas. Con las casillas sin marcar, tocar una sola borraba en
    silencio todo lo que el diagnostico habia puesto."""
    selector = construir_selector_vanos(["A", "B", "C"])
    selector.value = ("A", "C")

    selector.casillas["B"].value = True

    assert set(selector.value) == {"A", "B", "C"}


def test_setting_value_respects_the_cap():
    """El tope existe porque cada vano marcado recibe su columna de controles.
    Escribir `value` no puede ser una puerta trasera para pasarselo, igual que no
    lo es el clic del mapa."""
    selector = construir_selector_vanos(["A", "B", "C", "D"], maximo=2)

    selector.value = ("A", "B", "C", "D")

    assert selector.value == ("A", "B")
    assert [c for c, caja in selector.casillas.items() if caja.value] == ["A", "B"]
    # Con el cupo lleno, las que quedaron fuera se deshabilitan.
    assert selector.casillas["C"].disabled is True


def test_setting_value_drops_keys_the_selector_does_not_have():
    """Un fid de OTRO circuito no tiene casilla aqui. Dejarlo dentro de `value`
    haria que el trait afirmara una seleccion que la lista no puede mostrar."""
    selector = construir_selector_vanos(["A", "B"])

    selector.value = ("A", "DE_OTRO_CIRCUITO")

    assert selector.value == ("A",)


def test_setting_value_follows_the_option_order_and_not_the_given_order():
    """El orden sale de las opciones, como en el resto del selector: asi la rejilla
    de controles y la leyenda no se barajan segun como llego la lista."""
    selector = construir_selector_vanos(["A", "B", "C"])

    selector.value = ("C", "A")

    assert selector.value == ("A", "C")


def test_clearing_value_unticks_everything():
    """El camino de vuelta tiene que funcionar igual: sin esto, `value = ()` dejaba
    las casillas marcadas y la lista contradecia al mapa."""
    selector = construir_selector_vanos(["A", "B"])
    selector.value = ("A", "B")

    selector.value = ()

    assert not any(caja.value for caja in selector.casillas.values())
    assert not any(caja.disabled for caja in selector.casillas.values())


# --- La definicion de cada variable, al pasar el mouse ------------------------------------


def test_the_checkbox_list_hangs_a_tooltip_on_each_key_that_has_one():
    """El panel del 06 ofrece 26 variables como casillas y en la casilla solo cabe
    el nombre. Sin el tooltip, saber que es `NR_T` obliga a subir a la tabla de la
    celda 8, que esta fuera de la pantalla cuando se esta eligiendo."""
    from chec_local_interpreter.vano_widgets import construir_selector_casillas

    selector = construir_selector_casillas(
        [("Vegetacion", "NR_T"), ("Precipitacion", "clima:prep")],
        tooltips={"NR_T": "Nivel de riesgo por vegetacion."},
    )

    assert selector.casillas["NR_T"].tooltip == "Nivel de riesgo por vegetacion."
    # Una clave sin definicion no inventa una: el tooltip vacio no muestra nada.
    assert not selector.casillas["clima:prep"].tooltip


def test_the_column_layout_carries_the_tooltips_too():
    """El selector de variables del 06 se construye por COLUMNAS, no como lista
    corrida, asi que un tooltip que solo funcione en la lista plana no llega al
    unico sitio donde hace falta."""
    from chec_local_interpreter.vano_widgets import construir_selector_casillas

    selector = construir_selector_casillas(
        columnas=[("Intervencion", [("Vegetacion", "NR_T")]),
                  ("Escenario", [("Precipitacion", "clima:prep")])],
        tooltips={"NR_T": "Es el plan de poda.", "clima:prep": "Lluvia acumulada."},
    )

    assert selector.casillas["NR_T"].tooltip == "Es el plan de poda."
    assert selector.casillas["clima:prep"].tooltip == "Lluvia acumulada."


def test_repopulating_keeps_the_tooltips():
    """`poblar` se vuelve a llamar al cambiar de circuito. Si los tooltips se
    perdieran ahi, funcionarian solo hasta el primer cambio -- que es peor que no
    tenerlos, porque nadie vuelve a probar algo que ya vio funcionar."""
    from chec_local_interpreter.vano_widgets import construir_selector_casillas

    selector = construir_selector_casillas(
        [("Vegetacion", "NR_T")], tooltips={"NR_T": "Es el plan de poda."})

    selector.poblar([("Vegetacion", "NR_T"), ("Otra", "OTRA")])

    assert selector.casillas["NR_T"].tooltip == "Es el plan de poda."
