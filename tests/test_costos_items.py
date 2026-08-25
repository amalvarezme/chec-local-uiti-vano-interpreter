"""RED/GREEN tests for `costos_items`, the activity catalogue behind notebook
06's intervention cost.

The simulator answers what happens to a vano's criticality if this variable
changes. That is half of a maintenance decision: the other half is what the
change COSTS. `data/Actividades_mantenimiento_costos_2026.xlsx` is CHEC's own contract price
list, and joining it to the marked vanos turns "the risk drops one group" into
"the risk drops one group for 283.472 pesos", which is the sentence a work
order is actually approved on.

The file is a PIVOT TABLE export, and two of its properties will silently
corrupt the total if they are not handled here, once, with tests:

  1. Its last row is `Total general` -- the pivot's own footer. Offered as an
     activity it looks like any other, and its "unit cost" is the average of
     everything: picking it would add 254.388 pesos of pure artefact.
  2. Twelve rows carry NO unit cost. An activity that cannot be priced cannot
     enter a total; it is kept aside and NAMED, because a list that quietly
     drops twelve entries reads as a shorter catalogue, not as a decision.

There is no item code in the file, so the NAME is the key. That is the third
reason this module exists: one name arrives mojibake'd (`CONDUCCIÃ“N`, UTF-8
read as Latin-1), and a key nobody can read is a key nobody can pick.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import ayudas_tableros
import pytest

from chec_local_interpreter.costos_items import (
    SIN_DESCRIPCION,
    COLUMNA_COSTO,
    COLUMNA_ITEM,
    FILA_TOTAL,
    MAX_REPETICIONES,
    CatalogoCostos,
    ItemCosto,
    costos_de_intervencion,
    leer_catalogo_costos,
    reparar_texto,
)

LIBRO_REAL = Path(__file__).resolve().parents[1] / "data" / "Actividades_mantenimiento_costos_2026.xlsx"


def _libro(tmp_path, filas):
    ruta = tmp_path / "costos.xlsx"
    pd.DataFrame(filas, columns=[COLUMNA_ITEM, COLUMNA_COSTO]).to_excel(ruta, index=False)
    return ruta


def _catalogo(items, sin_costo=()):
    return CatalogoCostos(
        items=tuple(ItemCosto(nombre=n, costo=c) for n, c in items),
        sin_costo=tuple(sin_costo),
    )


# --- leer el catalogo ------------------------------------------------------------------


def test_the_pivot_footer_is_not_an_activity(tmp_path):
    """`Total general` es el pie de la tabla dinamica, no algo que una cuadrilla
    pueda hacer. Ofrecido en la lista se ve igual que los demas y su "costo
    unitario" es el promedio de todo el catalogo: elegirlo agrega 254 mil pesos
    de puro artefacto al presupuesto."""
    ruta = _libro(tmp_path, [("PODA", 100.0), (FILA_TOTAL, 999.0)])

    catalogo = leer_catalogo_costos(ruta)

    assert [i.nombre for i in catalogo.items] == ["PODA"]


def test_an_activity_without_a_unit_cost_is_set_aside_and_named(tmp_path):
    """No se puede costear lo que no tiene precio, pero tampoco se puede hacer
    desaparecer: doce filas menos sin explicacion se leen como un catalogo mas
    corto y no como una decision. Salen de la lista y quedan nombradas para que
    el panel pueda decirlo."""
    ruta = _libro(tmp_path, [("PODA", 100.0), ("SERVICIO DE REVISION", None)])

    catalogo = leer_catalogo_costos(ruta)

    assert [i.nombre for i in catalogo.items] == ["PODA"]
    assert catalogo.sin_costo == ("SERVICIO DE REVISION",)


def test_a_mojibaked_name_is_repaired(tmp_path):
    """El nombre ES la clave -- el archivo no trae codigo de item --, asi que un
    nombre ilegible es una actividad que nadie va a marcar. `CONDUCCIÃ“N` es
    UTF-8 leido como Latin-1."""
    ruta = _libro(tmp_path, [("CONDUCCIÃ“N DE VEHICULO", 100.0)])

    catalogo = leer_catalogo_costos(ruta)

    assert catalogo.items[0].nombre == "CONDUCCIÓN DE VEHICULO"


def test_repairing_leaves_text_that_was_never_broken_alone():
    """La reparacion tiene que ser idempotente y no tocar lo sano: aplicada a
    ciegas sobre un nombre correcto con tilde lo rompe en la direccion
    contraria."""
    assert reparar_texto("PODA EN REDES URBANAS") == "PODA EN REDES URBANAS"
    assert reparar_texto("CONDUCCIÓN") == "CONDUCCIÓN"
    assert reparar_texto(reparar_texto("CONDUCCIÃ“N")) == "CONDUCCIÓN"


def test_the_catalogue_keeps_the_file_order(tmp_path):
    """El orden del archivo es alfabetico y es el que hace encontrable una lista
    de 125 casillas. Reordenar por costo pondria "PODA EN REDES URBANAS" al lado
    de una reubicacion de poste solo porque valen parecido."""
    ruta = _libro(tmp_path, [("A", 3.0), ("B", 1.0), ("C", 2.0)])

    assert [i.nombre for i in leer_catalogo_costos(ruta).items] == ["A", "B", "C"]


def test_the_real_workbook_yields_the_measured_catalogue():
    """Contra el libro real de 2026: 142 actividades, TODAS costeables.

    El anterior era una exportacion de tabla dinamica y traia dos trampas -- su pie
    `Total general` y doce filas sin costo unitario. Este no: 142 filas, cero costos
    faltantes, cero duplicados y sin pie. Lo que si trae son 52 actividades sin
    descripcion, y esas se NOMBRAN en vez de salir en blanco.

    Si el archivo cambia, esto avisa aqui en vez de dejar el presupuesto moverse en
    silencio.
    """
    catalogo = leer_catalogo_costos(LIBRO_REAL)

    assert len(catalogo.items) == 142
    assert len(catalogo.sin_costo) == 0
    assert all(i.costo > 0 for i in catalogo.items)
    assert len({i.nombre for i in catalogo.items}) == 142, "el nombre es la clave"

    # Lo que el boton de informacion muestra tiene que venir completo.
    assert all(i.tipo for i in catalogo.items), "toda actividad declara su tipo"
    assert all(i.unidad for i in catalogo.items), "toda actividad declara su unidad"
    assert all(i.codigo_maximo.isdigit() for i in catalogo.items), (
        "el codigo va como texto: formateado como numero pierde ceros a la izquierda"
    )
    sin_desc = [i for i in catalogo.items if i.descripcion == SIN_DESCRIPCION]
    assert len(sin_desc) == 52, "las que no traen descripcion lo dicen, no salen vacias"


# --- costear la intervencion -----------------------------------------------------------


def test_the_cost_of_a_vano_is_the_sum_of_its_activities():
    """Costo unitario por repeticiones, sumado. Es toda la aritmetica, y por eso
    mismo tiene que estar en un solo sitio con pruebas: repartida por el cuaderno
    se vuelve imposible saber cual de las dos sumas es la buena."""
    catalogo = _catalogo([("PODA", 100.0), ("TALA", 50.0)])

    costos = costos_de_intervencion({"V1": {"PODA": 2, "TALA": 1}}, catalogo)

    assert costos["por_vano"]["V1"]["total"] == pytest.approx(250.0)
    assert costos["total"] == pytest.approx(250.0)


def test_the_total_adds_up_every_vano():
    """El costo total de la intervencion es el de la orden de trabajo completa,
    no el del vano que se este mirando."""
    catalogo = _catalogo([("PODA", 100.0)])

    costos = costos_de_intervencion({"V1": {"PODA": 1}, "V2": {"PODA": 3}}, catalogo)

    assert costos["por_vano"]["V1"]["total"] == pytest.approx(100.0)
    assert costos["por_vano"]["V2"]["total"] == pytest.approx(300.0)
    assert costos["total"] == pytest.approx(400.0)


def test_the_breakdown_travels_with_the_total():
    """El total contesta cuanto; el detalle contesta por que. Sin el, un vano
    caro obliga a volver a abrir el panel para saber que actividad lo encarecio,
    y el hover de la barra existe justamente para no tener que hacerlo."""
    catalogo = _catalogo([("PODA", 100.0), ("TALA", 50.0)])

    renglones = costos_de_intervencion({"V1": {"PODA": 2, "TALA": 1}},
                                       catalogo)["por_vano"]["V1"]["renglones"]

    assert renglones == [
        {"item": "PODA", "costo_unitario": 100.0, "repeticiones": 2, "subtotal": 200.0},
        {"item": "TALA", "costo_unitario": 50.0, "repeticiones": 1, "subtotal": 50.0},
    ]


def test_the_breakdown_is_ordered_by_what_costs_the_most():
    """De mayor a menor subtotal: la primera linea del detalle es la que hay que
    negociar. En el orden en que se marcaron las casillas, la que manda queda
    donde caiga."""
    catalogo = _catalogo([("BARATA", 10.0), ("CARA", 900.0)])

    renglones = costos_de_intervencion({"V1": {"BARATA": 3, "CARA": 1}},
                                       catalogo)["por_vano"]["V1"]["renglones"]

    assert [r["item"] for r in renglones] == ["CARA", "BARATA"]


def test_a_vano_without_activities_costs_zero_and_still_appears():
    """Un vano marcado sin actividades cuesta cero, y ese cero es un dato: dice
    que la simulacion movio su riesgo sin obra asociada. Sacarlo del resultado
    lo borraria de la grafica de barras, donde se leeria como que no se estudio."""
    costos = costos_de_intervencion({"V1": {}}, _catalogo([("PODA", 100.0)]))

    assert costos["por_vano"]["V1"] == {"total": 0.0, "renglones": []}
    assert costos["total"] == 0.0


def test_an_unknown_activity_raises_instead_of_costing_nothing():
    """Un nombre que no esta en el catalogo no puede valer cero: el presupuesto
    saldria mas barato de lo que es y nada en pantalla lo diria. Como el NOMBRE
    es la clave, un cambio del archivo se manifiesta exactamente asi."""
    with pytest.raises(KeyError, match="INVENTADA"):
        costos_de_intervencion({"V1": {"INVENTADA": 1}}, _catalogo([("PODA", 100.0)]))


@pytest.mark.parametrize("repeticiones", [-1, MAX_REPETICIONES + 1])
def test_repetitions_outside_the_offered_range_raise(repeticiones):
    """El desplegable ofrece de 0 a 5, asi que un valor fuera de ahi es un error
    de programa y no una eleccion del usuario. Se levanta en vez de recortarse:
    recortar en silencio devuelve un numero de pesos que nadie pidio, y en un
    presupuesto eso es peor que caerse."""
    with pytest.raises(ValueError):
        costos_de_intervencion({"V1": {"PODA": repeticiones}},
                               _catalogo([("PODA", 100.0)]))


def test_zero_repetitions_excludes_the_activity_from_that_vano():
    """El cero es lo que hace que la lista compartida no obligue a darle la misma
    obra a todos los vanos: se marca la poda una vez arriba y se pone en cero en
    los vanos donde no va. Sin el, marcar una actividad la imponia sobre los cinco
    vanos marcados."""
    catalogo = _catalogo([("PODA", 100.0), ("TALA", 50.0)])

    costos = costos_de_intervencion({"V1": {"PODA": 2, "TALA": 0}}, catalogo)

    assert costos["por_vano"]["V1"]["total"] == pytest.approx(200.0)
    assert [r["item"] for r in costos["por_vano"]["V1"]["renglones"]] == ["PODA"]


def test_a_vano_with_every_activity_at_zero_costs_nothing_but_still_appears():
    """Poner todo en cero es decir "a este vano no le hago nada", que es una
    respuesta y no una ausencia: su barra en cero dice que se estudio y se decidio
    no intervenirlo. Distinto de un vano que nunca se marco."""
    costos = costos_de_intervencion({"V1": {"PODA": 0}}, _catalogo([("PODA", 100.0)]))

    assert costos["por_vano"]["V1"] == {"total": 0.0, "renglones": []}


def test_an_empty_selection_costs_nothing():
    """Sin vanos marcados no hay intervencion que costear. Devuelve la misma
    forma y no None, para que el repintado de la barra sea siempre la misma
    escritura."""
    assert costos_de_intervencion({}, _catalogo([("PODA", 100.0)])) == {
        "por_vano": {},
        "total": 0.0,
    }


# --- El cableado del cuaderno ----------------------------------------------------------
#
# La aritmetica ya esta cubierta arriba. Lo que estas pruebas miran es lo que ninguna
# prueba unitaria puede ver: si el tablero llega hasta esa aritmetica, y si lo hace en el
# momento correcto.

import json  # noqa: E402
import re  # noqa: E402

TABLERO_06 = "06_uiti_vano_explicabilidad_simulador"


# El codigo del tablero salio del cuaderno a `src/chec_tableros/simulador/tablero.py`
# (fase 2 de `sdd/retire-base-apps-notebooks`). Lo que se afirma abajo son invariantes
# del TABLERO y no del formato en que se guardaba, asi que solo cambia de donde se lee.
@pytest.fixture(scope="module")
def fuente() -> str:
    return ayudas_tableros.fuente_de_tablero(TABLERO_06)


def test_the_cost_is_computed_inside_the_simulate_job(fuente):
    """El tablero tiene UN solo disparador. Un costo que se recalculara al marcar una
    casilla, mientras el mapa de al lado sigue mostrando la corrida anterior, dejaria
    dos planes distintos en pantalla al mismo tiempo -- que es la misma confusion que
    separa a las dos filas de mapas."""
    cuerpo = fuente[fuente.index("def _simular(epoca_job)"):]
    cuerpo = cuerpo[: cuerpo.index("def _programar_simulacion")]
    assert "costos = costos_de_intervencion(" in cuerpo
    assert "_pintar_costos(costos)" in cuerpo


def test_only_the_vanos_the_model_scored_are_costed(fuente):
    """Costear un vano que la simulacion no puntuo pondria un precio al lado de un
    riesgo que nadie estimo. Es el mismo criterio que ya rige al recuadro y al encuadre
    del mapa simulado."""
    assert "_puntuados = set(resultado['FID_VANO'].astype(str))" in fuente
    assert "for fid, actividades in _costos_por_vano.items() if fid in _puntuados" in fuente


def test_changing_circuit_or_window_clears_the_cost_row(fuente):
    """El costo pertenece a una seleccion concreta. Sobrevivir a un cambio de ventana lo
    dejaria describiendo una intervencion sobre otros vanos."""
    # La funcion ENTERA y no sus primeros 1.200 caracteres. Ese recorte a ojo ya dio
    # un falso rojo: un comentario nuevo dentro de la funcion empujo la llamada fuera
    # de la ventana y la prueba afirmo que el costo sobrevivia al cambio de ventana.
    desde = fuente.index("def _limpiar_resultado_simulacion")
    limpiar = fuente[desde:fuente.index("\n    def ", desde + 1)]
    assert "_pintar_costos(None)" in limpiar


def test_the_quantity_dropdown_offers_zero_through_five(fuente):
    """De 0 a 5. El cero no sobra por tener casilla: la casilla elige que actividades
    entran al PLAN, y el cero dice en cuales de los vanos marcados NO se ejecuta esa
    actividad. Sin el, una lista compartida obligaria a darle la misma obra a los cinco
    vanos. El tope sale de la constante del modulo y no de un literal, que es lo que
    mantiene al panel y al costeo de acuerdo sobre que es un valor valido."""
    assert "options=[(str(n), n) for n in range(0, MAX_REPETICIONES + 1)]" in fuente


def test_the_cost_row_splits_the_vanos_from_the_accumulated_total(fuente):
    """Los vanos en las columnas 1-3 y el costo acumulado en la 4, cada panel con su
    propio eje. Es la misma particion que ya rige a la fila del UITI y por la misma
    razon: el total es la SUMA de los vanos, asi que compartiendo eje es siempre la
    barra mas alta y aplasta contra la base a las de los vanos, que es donde se decide
    la obra. Ahi se lee cuanto cuesta CADA vano; en el panel de al lado, cuanto cuesta
    el plan entero.

    La traza de los vanos conserva el color como ARREGLO aunque ya no lleve el total:
    el repintado escribe un color por vano, y un escalar habria que volver a partirlo
    el dia que un vano tenga que destacarse."""
    assert "IDX['costos'] = _agregar(go.Bar(" in fuente
    assert "IDX['costo_total'] = _agregar(go.Bar(" in fuente
    assert "assert isinstance(_fig.data[IDX['costos']].marker.color, (list, tuple))" in fuente
    assert re.search(r"\), 5, 1\)\n", fuente), "las barras por vano van en la fila 5, columna 1"
    assert re.search(r"\), 5, 4\)\n", fuente), "el costo acumulado va en la fila 5, columna 4"


def test_the_accumulated_cost_is_painted_into_its_own_trace(fuente):
    """El repintado tiene que dejar de anexar el TOTAL a la lista de los vanos: si lo
    sigue anexando, la particion de la figura queda a medias -- un panel con el total
    mezclado y otro vacio -- y el fallo no se ve hasta que alguien simula."""
    cuerpo = fuente[fuente.index("def _pintar_costos(costos)"):]
    cuerpo = cuerpo[: cuerpo.index("_pintar_top_por_vano(TOP_VACIO)")]
    assert "_x = [*_por_vano, ETIQUETA_TOTAL]" not in cuerpo
    assert "IDX['costo_total']" in cuerpo
    # El panel vacio: los DOS paneles se limpian, o el acumulado se queda describiendo
    # la corrida anterior mientras el de los vanos ya se borro.
    vacio = cuerpo[: cuerpo.index("_por_vano = costos['por_vano']")]
    assert vacio.count("IDX['costos']") == 1 and "IDX['costo_total']" in vacio


def test_the_activity_list_is_shared_and_the_rows_are_per_vano(fuente):
    """Una sola lista de 125 casillas arriba, y una fila por actividad bajo CADA vano
    marcado. Repetir el catalogo por vano serian 625 casillas para elegir tres."""
    assert fuente.count("item_selector_widget = construir_selector_casillas(") == 1
    assert "_costos_por_vano[fid] = controles" in fuente
    assert "*_bloque_de_costos(fid)" in fuente


def test_the_uncosted_activities_are_named_and_not_just_dropped(fuente):
    """Doce actividades ausentes sin explicacion se leen como que el contrato no las
    incluye. Mismo criterio que las variables no simulables."""
    assert "AVISO_SIN_COSTO = widgets.HTML(" in fuente
    assert "CATALOGO_COSTOS.sin_costo" in fuente


# --- El libro de 2026: una actividad es mas que su precio ---------------------------------


def _libro_2026(tmp_path):
    import pandas as pd

    ruta = tmp_path / "Actividades_mantenimiento_costos_2026.xlsx"
    pd.DataFrame({
        "TIPO_ACTIVIDAD": ["MANTENIMIENTO_FORESTAL", "MANTENIMIENTO_ELECTROMECÁNICO"],
        "Codigo Maximo": [290027, 301466],
        "Actividad": ["Poda en redes urbanas", "Cambio de aislador"],
        "UM": ["Km", "Und"],
        "Descripción de la actividad": ["Consiste en podar la vegetacion.", None],
        "Item anterior contratación": [1, None],
        "COSTO": [5131579.0, 166112.0],
    }).to_excel(ruta, index=False)
    return ruta


def test_the_2026_catalogue_carries_what_the_info_button_shows(tmp_path):
    """El panel ofrece la actividad y su precio; el boton de informacion contesta QUE
    es esa actividad. Tipo, unidad, codigo maximo y descripcion viven en el libro, y
    leerlos aqui evita que el cuaderno los vuelva a abrir por su cuenta."""
    catalogo = leer_catalogo_costos(_libro_2026(tmp_path))

    primero = catalogo.items[0]
    assert primero.nombre == "Poda en redes urbanas"
    assert primero.costo == 5131579.0
    assert primero.tipo == "MANTENIMIENTO_FORESTAL"
    assert primero.unidad == "Km"
    assert primero.codigo_maximo == "290027"
    assert "podar la vegetacion" in primero.descripcion


def test_the_columns_are_read_by_name_not_by_position(tmp_path):
    """El lector anterior renombraba las dos primeras columnas por POSICION. Con siete
    columnas eso toma `TIPO_ACTIVIDAD` como nombre de la actividad y el codigo como su
    precio, sin fallar: el panel saldria con dos tipos y precios de seis cifras que son
    codigos."""
    import pandas as pd

    ruta = tmp_path / "revuelto.xlsx"
    pd.DataFrame({
        "COSTO": [1000.0],
        "Actividad": ["Poda"],
        "UM": ["Km"],
        "TIPO_ACTIVIDAD": ["FORESTAL"],
        "Codigo Maximo": [7],
        "Descripción de la actividad": ["x"],
    }).to_excel(ruta, index=False)

    item = leer_catalogo_costos(ruta).items[0]

    assert item.nombre == "Poda" and item.costo == 1000.0


def test_an_activity_without_description_says_so_instead_of_showing_blank(tmp_path):
    """52 de las 142 actividades del libro real no traen descripcion. Un panel de
    informacion en blanco se lee como que la consulta fallo; decirlo lo distingue."""
    catalogo = leer_catalogo_costos(_libro_2026(tmp_path))

    sin_desc = catalogo.items[1]
    assert sin_desc.descripcion, "no puede quedar vacia"
    assert "sin descripcion" in sin_desc.descripcion.lower()


# --- El detalle que muestra el boton "i" -----------------------------------------


def test_el_detalle_respeta_los_parrafos_de_la_descripcion():
    """42 de las 142 actividades traen saltos de linea, hasta siete.

    En HTML un `\\n` colapsa a un espacio, asi que esos parrafos salian pegados en un
    solo bloque. La descripcion mas larga mide 1.166 caracteres: sin cortes es un muro
    que nadie lee, y el boton "i" existe justo para que se lea.
    """
    from chec_local_interpreter.costos_items import ItemCosto, detalle_html_de_item

    item = ItemCosto(nombre="Poda", costo=1000.0, tipo="FORESTAL", unidad="Km",
                     codigo_maximo="290027",
                     descripcion="Primer parrafo.\nSegundo parrafo.\nTercero.")

    html = detalle_html_de_item(item)

    assert html.count("<br>") >= 4, "los dos saltos de la descripcion no llegaron"
    assert "\n" not in html.split("</b>", 1)[1], "quedo un salto literal, que colapsa"
    assert "Primer parrafo.<br>Segundo parrafo.<br>Tercero." in html


def test_el_detalle_escapa_lo_que_venga_del_libro():
    """El libro lo edita una persona. Un `<` en una descripcion rompe el panel entero,
    y un `&` deja una entidad a medias."""
    from chec_local_interpreter.costos_items import ItemCosto, detalle_html_de_item

    item = ItemCosto(nombre="Poda <A> & B", costo=1.0, tipo="T", unidad="U",
                     codigo_maximo="1", descripcion="Retiro de ramas < 3 m & similares")

    html = detalle_html_de_item(item)

    assert "&lt;A&gt;" in html and "&amp;" in html
    assert "<A>" not in html
    # y las etiquetas que pone el propio panel siguen vivas
    assert html.startswith("<b>")


def test_una_actividad_sin_descripcion_lo_dice_en_vez_de_dejar_el_hueco():
    """Un panel que se abre con el encabezado y nada debajo se lee como que el boton
    fallo a la mitad."""
    from chec_local_interpreter.costos_items import ItemCosto, detalle_html_de_item

    item = ItemCosto(nombre="Poda", costo=1.0, tipo="T", unidad="U",
                     codigo_maximo="1", descripcion="   ")

    html = detalle_html_de_item(item)

    assert "sin descripción" in html.lower()


def test_los_campos_ausentes_se_nombran_y_no_salen_vacios():
    from chec_local_interpreter.costos_items import ItemCosto, detalle_html_de_item

    item = ItemCosto(nombre="Poda", costo=1.0, tipo="", unidad=None,
                     codigo_maximo="", descripcion="Algo")

    html = detalle_html_de_item(item)

    assert "sin tipo" in html and "sin unidad" in html and "sin código" in html


def test_el_libro_real_reparte_sus_142_detalles_como_esta_medido():
    """Contra las 142 de verdad, no contra un doble.

    **90 traen descripcion y 52 no.** Las 52 tienen que DECIRLO -- un panel que se abre
    con el encabezado y nada debajo se lee como que el boton fallo a la mitad --, y de
    las 90 hay **42 con saltos de linea**, que son las que se aplastaban en un bloque.

    La descripcion mas larga mide 1.166 caracteres y la mediana 357: aqui el corte de
    parrafo no es un detalle de estilo, es la diferencia entre un texto y un muro.
    """
    from pathlib import Path

    from chec_local_interpreter.costos_items import (
        detalle_html_de_item,
        leer_catalogo_costos,
    )

    libro = Path(__file__).resolve().parents[1] / "data" / \
        "Actividades_mantenimiento_costos_2026.xlsx"
    if not libro.exists():
        import pytest as _pytest
        _pytest.skip("el libro de costos no esta en esta copia")

    catalogo = leer_catalogo_costos(libro)
    assert len(catalogo.items) == 142

    detalles = {i.nombre: detalle_html_de_item(i) for i in catalogo.items}
    sin_descripcion = [n for n, h in detalles.items() if "sin descripción" in h.lower()]
    # Solo los `<br>` de DENTRO de la descripcion: el encabezado ya trae dos suyos.
    con_parrafos = [n for n, h in detalles.items()
                    if h.rsplit('color:#4b5563;">', 1)[1].count("<br>") > 0]

    assert len(sin_descripcion) == 52
    assert len(con_parrafos) == 42, (
        "cambio cuantas descripciones tienen parrafos; si el libro se edito, actualiza "
        "el numero, y si no, algo dejo de convertir los saltos de linea")
    for html in detalles.values():
        # Ni un salto literal sobreviviente: en HTML colapsa y pega los parrafos.
        assert "\n" not in html
