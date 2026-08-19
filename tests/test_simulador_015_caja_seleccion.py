"""Contract tests for notebook 06's selection box.

Clicking a vano on the base map (row 1) marks it, and a marked vano is
enclosed in a translucent red box -- turned to the vano's own inclination
-- so it stays findable on a circuit of hundreds of segments. The geometry of
that box is
`ventanas_015.cajas_seleccion`, covered by unit tests in
`tests/test_ventanas_015.py`. What those unit tests cannot see is the WIRING:
whether the notebook actually reaches that geometry, and whether it puts the
result where it belongs. These tests pin it against the committed notebook
source (no execution, so this stays fast), because each failure is silent:

  1. The box is a `layout.map.layers` fill with `below='traces'`, NOT a
     trace. A filled trace on top would swallow the map click -- which is
     the very thing that toggles the selection -- and would tint over the
     vano's own class colour.
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

import ast
import json
import re
from pathlib import Path

import ayudas_tableros
import pytest

TABLERO = "06_uiti_vano_explicabilidad_simulador"


# El codigo del tablero salio del cuaderno a `src/chec_tableros/simulador/`
# (fase 2 de `sdd/retire-base-apps-notebooks`). Lo que se afirma aqui son
# invariantes del TABLERO y no del formato en que se guardaba, asi que la fuente
# se pide al ayudante y las afirmaciones no cambian.
@pytest.fixture(scope="module")
def fuente() -> str:
    return ayudas_tableros.fuente_de_tablero(TABLERO)


def _tiene(fuente: str, fragmento: str) -> bool:
    """`fragmento` aparece en `fuente`, mirando el codigo y no su sangria.

    El tablero paso de ser celdas de nivel 0 a ser el cuerpo de `construir()`, asi
    que cada linea gano cuatro espacios y las continuaciones de una expresion
    multilinea ganaron los suyos. Lo que estas pruebas afirman es que una expresion
    ESTA, no con cuanta sangria: compararla al pie de la letra convertia la
    migracion en fallos que no dicen nada de lo que se quiere proteger.
    """
    aplanar = lambda texto: re.sub(r"\s+", " ", texto).strip()  # noqa: E731
    return aplanar(fragmento) in aplanar(fuente)


_cuerpo = ayudas_tableros.cuerpo_de_funcion


def test_the_box_is_a_map_layer_below_the_traces_and_not_a_trace(fuente):
    """A filled `Scattermap` trace drawn on top would eat the click that
    toggles the selection, and would paint over the class colour of the very
    vano it is pointing at. `below='traces'` is what keeps both working."""
    assert "CAPAS_CAJA_SELECCION = [" in fuente
    capa = fuente[fuente.index("CAPAS_CAJA_SELECCION = [") :][:500]
    assert "sourcetype='geojson'" in capa
    assert "type='fill'" in capa
    assert "below='traces'" in capa
    assert "color=COLOR_CAJA_POR_CLASE[_clase]" in capa
    assert "opacity=OPACIDAD_CAJA_SELECCION" in capa
    # Si alguien la convierte en traza, deja de estar en el layout y esto avisa.
    assert "fig.layout.map.layers[IDX_CAPA_CLASE[_clase]].source = _coleccion" in fuente


def test_the_base_map_has_one_box_layer_per_kmeans_group(fuente):
    """El relleno del recuadro lleva el color del GRUPO KMeans del vano, al 50%,
    y no un rojo de acento propio.

    "Cual estoy mirando" ya lo contestan el halo blanco y el trazo un 40% mas
    ancho. Con el color del grupo, el recuadro contesta ademas en que nivel cayo
    -- la misma lectura que su linea, pero en una mancha que se sigue viendo al
    zoom en que la linea deja de distinguirse de sus vecinas.

    Son CINCO capas porque una entrada de `layout.map.layers` pinta con UN color:
    los cuatro grupos mas la del vano marcado sin celda en la ventana, que no
    tiene grupo -- y eso no es el grupo mas bajo, es la ausencia del dato.
    """
    assert "CLASES_CAJA = (0, 1, 2, 3, None)" in fuente
    assert fuente.count("layers=CAPAS_CAJA_SELECCION") == 1
    assert "assert len(_fig.layout.map.layers) == len(CLASES_CAJA) == 5" in fuente
    assert "assert len(_fig.layout.map2.layers) == len(CAMBIOS)" in fuente
    # El relleno y la linea del mismo grupo tienen que salir del MISMO color, o el
    # vano queda encerrado en un color y trazado en otro.
    assert "COLORES_CAJA_SELECCION = list(COLORES_GRUPOS)" in fuente
    assert "COLOR_CAJA_SIN_CLASE = COLOR_SIN_GRUPO" in fuente
    assert _tiene(fuente, (
        "assert [_fig.layout.map.layers[IDX_CAPA_CLASE[_c]].color for _c in range(4)] \\\n"
        "    == [_fig.data[_i].line.color for _i in IDX['clases']] == COLORES_GRUPOS"
    ))


def test_deselecting_a_vano_only_removes_its_box(fuente):
    """Desmarcar quita el recuadro y NO el color ni el grosor de la linea.

    Es lo que separa las dos capas: el color y el ancho salen de
    `clases_por_fid` -- el grupo KMeans de esa ventana --, y el recuadro sale de
    `marcados`. Si el reparto por clase mirara la seleccion para decidir el
    COLOR de la linea, desmarcar devolveria el vano al negro de "sin eventos" y
    el tablero afirmaria que no hubo eventos donde si los hubo.
    """
    cuerpo = fuente[fuente.index("def _redibujar_mapa_historico("):]
    cuerpo = cuerpo[: cuerpo.index("def _alto_del_mapa_px(")]
    # Las capas de clase se alimentan de `capas['clases']`, que `capas_mapa_historico`
    # construye para TODO vano con celda, este marcado o no.
    assert "_volcar_capa(fig.data[IDX['clases'][_clase]], capas['clases'][_clase]," in cuerpo
    assert "cajas_seleccion_por_clase(" in cuerpo
    assert "marcados=_marcados" in cuerpo


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
    # El "no cambio" ya NO se hereda de la caja de seleccion. Esa paso a ROJA -- el rojo
    # del tablero, "esto es lo que estoy mirando" --, y heredarla dejaria a "se quedo
    # igual" del mismo color que "subio de grupo", que es la lectura contraria. Los tres
    # desenlaces tienen que seguir siendo tres colores distintos entre si.
    assert "COLOR_CAJA_IGUAL = COLOR_CAJA_SELECCION" not in fuente, (
        "atar el amarillo de 'no cambio' a la caja de seleccion lo vuelve rojo"
    )
    colores = {
        nombre: re.search(rf"^{nombre} = (.+?)(?:\s+#.*)?$", fuente, re.MULTILINE)
        for nombre in ("COLOR_CAJA_MEJORA", "COLOR_CAJA_IGUAL", "COLOR_CAJA_EMPEORA")
    }
    assert all(colores.values()), "los tres desenlaces tienen que declarar su color"
    valores = [m.group(1).strip() for m in colores.values()]
    assert len(set(valores)) == 3, f"dos desenlaces comparten color: {valores}"
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
    assert "cajas_seleccion_por_clase," in fuente  # importada en la celda de arranque
    llamada = re.search(
        r"_cajas = cajas_seleccion_por_clase\((.*?)\)\n",
        fuente,
        re.S,
    )
    assert llamada is not None
    argumentos = llamada.group(1)
    assert "GEO_POR_CIRCUITO" in argumentos
    assert "marcados=_marcados" in argumentos
    assert "lado_minimo=LADO_MINIMO_CAJA" in argumentos
    assert "margen=MARGEN_CAJA" in argumentos
    # La CLASE decide de que color se pinta, y sale de la ventana activa. La
    # geometria del rectangulo no: por eso el recuadro sigue puesto -- en gris --
    # sobre un vano marcado que en esta ventana no tiene ni un evento.
    assert "clases_por_fid" in argumentos


def test_the_minimum_side_is_wider_than_zero_so_a_north_south_vano_is_visible(fuente):
    """Across the trace the box starts at zero width -- a line has no thickness
    -- and zero pixels wide is nothing at all on the map. With the box turned to
    the vano this is the band's width on EVERY vano, not only on the ones that
    happened to run along an axis."""
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
    assert "_OPCIONES_INICIALES = _opciones_de_ventana(circuito_widget.value)" in fuente
    assert "options=_OPCIONES_INICIALES" in fuente
    assert "ventana_widget.options = _opciones" in fuente


def test_the_current_window_is_read_before_options_are_reassigned(fuente):
    """Asignar `options` reajusta `value` a la primera opcion de INMEDIATO. Leerlo
    despues devuelve siempre esa primera, asi que la ventana vigente se perdia en cada
    cambio de circuito -- medido: pasar a un circuito que SI tiene la ventana 10 la
    dejaba en la 0. El orden de estas dos lineas es todo el arreglo."""
    cuerpo = fuente[fuente.index("def _on_circuito_change"):][:1600]
    assert cuerpo.index("_vigente = ventana_widget.value") < cuerpo.index(
        "ventana_widget.options = _opciones"), (
        "la ventana vigente se lee DESPUES de reescribir options: se pierde siempre")
    # El respaldo es la ULTIMA que si tiene, igual que el arranque del deslizador.
    assert "_vigente if _vigente in _disponibles else _disponibles[-1]" in cuerpo


def test_a_circuit_without_windows_still_gets_one_option(fuente):
    """Un `SelectionSlider` sin opciones lanza al construirse, y eso dejaria el panel
    entero sin arrancar por un circuito vacio."""
    assert "VENTANAS_POR_CIRCUITO.get(circuito) or [0]" in fuente


# --- Los dos botones nuevos -------------------------------------------------------------


def test_the_circuit_diagnostic_has_its_own_trigger(fuente):
    """Contesta otra pregunta -- por donde empiezo en este circuito --, no depende de
    lo que este marcado ni de las variables fijadas, y colgarlo de "Simular" obligaria
    a recalcularlo en cada escenario que no lo cambia."""
    assert "boton_diagnostico = widgets.Button(" in fuente
    assert "boton_diagnostico.on_click(_al_pedir_diagnostico)" in fuente
    # Y se OLVIDA al cambiar de circuito o de ventana: describe UNO de cada uno, y
    # dejarlo en pantalla seria describir otra seleccion. Se borra el texto Y el
    # diagnostico guardado, o los botones de aplicar seguirian ofreciendo los vanos
    # del circuito anterior.
    assert "circuito_widget.observe(_olvidar_diagnostico, names='value')" in fuente
    assert "ventana_widget.observe(_olvidar_diagnostico, names='value')" in fuente
    cuerpo = fuente[fuente.index("def _olvidar_diagnostico"):][:400]
    assert "_ULTIMO_DIAGNOSTICO = None" in cuerpo


def test_the_diagnostic_reports_the_two_halves_separately(fuente):
    """Lo que se HACE es lo que se cotiza y lo que se ANTICIPA dice bajo que
    condiciones rinde. Mezcladas en una sola lista, el clima la copa -- medido: en los
    diez peores vanos de un circuito real, el escenario saca cuarenta veces a la
    intervencion."""
    assert "_mejores('Intervencion', TOP_INTERVENCION_CIRCUITO)" in fuente
    assert "_mejores('Escenario', TOP_ESCENARIO_CIRCUITO)" in fuente


def test_the_diagnostic_delegates_which_vanos_it_studies(fuente):
    """QUE se diagnostica es una decision de negocio y no cableado de widgets: vive en
    `ventanas_015.vanos_para_diagnostico`, que se prueba con datos (incluida la
    coercion a texto de los fid, que `DATOS_VENTANA` necesita). La celda solo conecta
    las dos fuentes -- las celdas de la ventana y los vanos del circuito -- con lo que
    el usuario marco."""
    assert "    vanos_para_diagnostico,\n" in fuente  # importada en la celda de arranque
    cuerpo = fuente[fuente.index("def _diagnostico_del_circuito"):][:2600]
    assert "elegidos = vanos_para_diagnostico(" in cuerpo
    assert "DATOS_VENTANA[ventana_i], VANOS_POR_CIRCUITO.get(circuito, [])" in cuerpo
    assert "marcados=marcados, maximo=TOP_VANOS_CIRCUITO" in cuerpo


def test_the_diagnostic_only_studies_what_was_marked(fuente):
    """Marcar vanos ACOTA la pregunta: la celda pide el diagnostico de lo marcado y no
    lo completa. La regla vive en `vanos_para_diagnostico` y se prueba con datos; lo
    que se pincha aqui es que la celda no vuelva a hablar de relleno, porque los avisos
    y el titulo del panel se escriben a partir de esa lectura."""
    cuerpo = fuente[fuente.index("def _diagnostico_del_circuito"):][:2600]
    assert "completado con" not in cuerpo


def test_the_diagnostic_copy_does_not_still_promise_the_fill(fuente):
    """La copia visible es la que el usuario lee ANTES de pulsar, asi que una promesa
    vieja no se corrige sola al cambiar la regla: prometeria completar la lista y
    entregaria solo lo marcado. El tooltip del boton y su parrafo de ayuda son los dos
    sitios donde el tablero explica el criterio."""
    for aguja in ("tooltip='Estudia los vanos que ", "<b>Diagnostico</b> "):
        copia = fuente[fuente.index(aguja):][:420]
        assert "completa con los de mayor UITI" not in copia


def test_the_diagnostic_tells_an_empty_circuit_from_an_empty_selection(fuente):
    """Sin relleno hay DOS maneras de quedarse sin vanos, y decirlas igual miente en
    una de las dos: que el circuito no registro nada en la ventana, o que el circuito si
    registro pero no en los vanos que el usuario marco. La segunda tiene salida -- marcar
    otros, o ninguno -- y el texto tiene que darla."""
    cuerpo = fuente[fuente.index("def _texto_del_diagnostico"):][:2200]
    assert "_sel_vacia['con_eventos']" in cuerpo
    assert "vanos que marcaste" in cuerpo


def test_the_framing_buttons_compute_the_view_at_click_time(fuente):
    """Un `updatemenu` de plotly lleva argumentos FIJOS calculados al dibujar: entre el
    dibujo y el clic pueden haber cambiado los vanos marcados, y el boton llevaria a
    donde estaba la seleccion antes."""
    assert "def _centrar_mapa(nombre_mapa):" in fuente
    cuerpo = fuente[fuente.index("def _centrar_mapa(nombre_mapa):"):][:1400]
    assert "_seleccion_actual()" in cuerpo
    assert "bounds_de_fids(geo, marcados)" in cuerpo
    assert "or _vista_del_circuito(circuito)" in cuerpo
    # Uno por mapa, y los dos en la misma columna que la figura: cada boton se posa
    # sobre SU mapa, asi que separarlos de ella lo dejaria apuntando a otro sitio. Desde
    # que el tablero va en dos columnas, esa columna es `COLUMNA_FIGURAS`.
    assert "_boton_encuadre('map', 'Centrar mapa base')" in fuente
    assert "_boton_encuadre('map2', 'Centrar mapa simulado')" in fuente
    assert _tiene(fuente, "COLUMNA_FIGURAS = widgets.VBox(\n    [ENCUADRES, fig]")


def test_the_selection_panel_has_one_button_per_criticality_group(fuente):
    """La fila de botones es Desmarcar + un boton por grupo, en el orden en que se lee la
    urgencia: Alto primero. El grupo sale de `clases_para`, o sea de la VENTANA ACTIVA:
    un vano no es Alto, es Alto en marzo, y marcarlo desde el periodo entero seria otra
    pregunta."""
    assert "    vanos_de_grupo,\n" in fuente
    # El rotulo se DERIVA de `NOMBRES_GRUPOS` en vez de escribirse cuatro veces: es lo
    # que impide que el boton diga "Medio" y marque otra clase al renombrar un grupo.
    assert "NOMBRES_GRUPOS = ['Bajo', 'Medio', 'Medio-Alto', 'Alto']" in fuente
    assert _tiene(fuente, "description=f'G. {NOMBRES_GRUPOS[clase]}'")
    assert _tiene(fuente, "BOTONES_GRUPO = [_boton_de_grupo(c) for c in (3, 2, 1, 0)]")
    cuerpo = fuente[fuente.index("def _marcar_grupo"):][:2600]
    assert "clases_para(circuito, ventana_i)" in cuerpo
    assert "datos_ventana=DATOS_VENTANA[ventana_i]" in cuerpo
    # El orden de la fila, que es el de la urgencia y no el del enum. Y la fila ENVUELVE:
    # cinco botones legibles no caben en una de 379 px, medido. Que de verdad ninguno se
    # salga del panel lo prueba en el navegador
    # `test_simulador_flujo_vivo.py::test_los_botones_de_seleccion_caben_en_su_panel`.
    assert _tiene(fuente, "[boton_desmarcar, *BOTONES_GRUPO],")
    assert "flex_flow='row wrap'" in fuente[fuente.index("FILA_BOTONES_VANO = "):][:400]


def test_the_window_top_button_is_gone(fuente):
    """Se retiro con los botones de grupo: la fila enumera lo que hay. La auto-marca del
    deslizador NO se fue con el -- sigue en `_on_ventana_change` --, y esa es la
    diferencia entre retirar un atajo y retirar el comportamiento."""
    assert "boton_top_ventana" not in fuente
    assert "Top de la ventana" not in fuente
    assert "_auto_seleccion_ventana(circuito, ventana_i)" in fuente  # la auto-marca sigue


def test_the_group_button_always_reports_and_an_empty_group_marks_nothing(fuente):
    """Las dos ramas hablan. La llena la pulsa de verdad
    `test_simulador_derivacion.py::test_los_botones_de_grupo_suman_y_solo_desmarcar_quita`;
    lo que se pincha aqui es la vacia, que no se puede provocar a voluntad contra el
    paquete congelado: no marca NADA -- un boton que marca el grupo de al lado produce
    una seleccion perfectamente plausible que el usuario descubre al simular -- y nombra
    el grupo con la fecha de la ventana, porque 'no hay vanos en grupo Alto' a secas se
    lee como una propiedad del circuito."""
    cuerpo = fuente[fuente.index("def _marcar_grupo"):][:3400]
    assert "No hay '" in cuerpo and "vanos {donde}" in cuerpo
    assert 'VENTANAS[ventana_i]["periodo"]' in cuerpo
    # La rama vacia sale ANTES de tocar la seleccion, y sale de verdad.
    vacia = cuerpo[:cuerpo.index("vano_widget.value = tuple(")]
    assert "if not elegidos:" in vacia
    assert "return" in vacia
    # Y la rama llena tambien deja aviso: callar cuando SI hay vanos deja al usuario
    # contando casillas, y con el boton sumando esa cuenta ya no es la seleccion entera.
    llena = cuerpo[cuerpo.index("vano_widget.value = tuple("):]
    assert "AVISO_GRUPO.value = (f'<span" in llena


def test_the_empty_group_notice_dies_with_its_window(fuente):
    """El aviso nombra UNA ventana y UN circuito. Al cambiar cualquiera de los dos deja de
    corresponder, y dejarlo en pantalla afirma sobre una ventana que ya no es la que se
    esta mirando."""
    assert fuente.count("AVISO_GRUPO.value = ''") >= 2


def test_the_diagnostic_and_its_apply_buttons_cover_every_marked_vano(fuente):
    """Los tres pasos hablan de la MISMA lista. El diagnostico recortaba a quince al
    devolver los vanos marcados, y los dos botones de aplicar recortaban otra vez al
    escribir los valores: con los botones de grupo marcando cientos, el usuario veia un
    diagnostico de quince sobre una seleccion de cuatrocientos y una intervencion
    aplicada a quince columnas de una rejilla de cuatrocientas. Ninguno de los dos
    recortes se anunciaba."""
    assert "MAX_VANOS_ANALISIS" not in fuente, (
        "quedo un recorte del diagnostico o de los botones de aplicar")
    cuerpo = fuente[fuente.index("def _aplicar_sugerencia"):][:3000]
    assert "fids = [f for f, _u, _n in diag['vanos']]\n" in cuerpo


def test_the_diagnostic_starts_from_what_the_user_marked(fuente):
    """Lo marcado es LA pregunta del diagnostico: si el usuario ya toco tres vanos en el
    mapa, esos tres son la orden de trabajo que tiene en la mano y el boton contesta por
    ellos y por ninguno mas. El tope solo gobierna el modo sin marcar, y el tope del
    selector no puede quedar por debajo del del diagnostico o la escritura se recortaria
    sola."""
    assert "TOP_VANOS_CIRCUITO = 15" in fuente
    assert "GRUPOS_DIAGNOSTICO" not in fuente  # ya no se filtra por grupo de criticidad
    cuerpo = fuente[fuente.index("def _diagnostico_del_circuito"):][:2600]
    assert "circuito, ventana_i, marcados = _seleccion_actual()" in cuerpo
    assert "marcados=marcados" in cuerpo


def test_a_capped_diagnostic_says_how_many_vanos_it_left_out(fuente):
    """Una lista de quince sobre un circuito con sesenta vanos con eventos se lee como
    que el circuito tiene quince. El panel dice cuantos quedaron fuera y como llegar a
    ellos -- marcandolos -- en vez de recortar en silencio."""
    assert "pero quedan otros " in fuente
    assert '<b>{_sel["restantes"]}</b> vanos con eventos en esta ventana' in fuente
    # Y de donde salio la lista. Con vanos marcados el aviso importa MAS que antes, no
    # menos: la lista ya no se completa, asi que "quedan otros N" es lo unico que separa
    # "marcaste dos" de "el circuito tiene dos". Y "los 15 de mayor UITI" sobre una lista
    # marcada seria falso -- los suyos pueden ser los de MENOR UITI de la ventana.
    assert "que marcaste, y solo esos" in fuente
    assert "de mayor UITI de la ventana" in fuente


def test_a_short_diagnostic_says_how_many_it_found(fuente):
    """Sin el aviso, una lista de cuatro vanos se lee como que el circuito tiene cuatro
    criticos, cuando lo que pasa es que no hay mas con eventos en esa ventana."""
    assert "Se identificaron " in fuente
    assert "no tiene mas con eventos en esta ventana" in fuente
    # El caso sin NINGUNO tiene su propio mensaje, que dice que no es un fallo.
    assert "no hay ningun vano con " in fuente
    assert "No hay diagnostico que dar" in fuente
    # Y un vano marcado SIN eventos se nombra en vez de desaparecer: el modelo no lo
    # puede puntuar, y callarlo se lee como que el boton lo ignoro.
    assert "Fuera del diagnostico: " in fuente
    assert "marcados, pero sin " in fuente


def test_the_apply_buttons_use_each_vano_own_value_and_not_the_average(fuente):
    """El promedio ORDENA la lista, pero lo que baja a un vano concreto es su propio
    optimo. Aplicar el promedio simularia un escenario que no es el de ninguno."""
    assert "'ranking': ranking," in fuente
    cuerpo = fuente[fuente.index("def _aplicar_sugerencia"):][:3200]
    assert "diag['ranking'].get(fid, {}).get('filas', [])" in cuerpo


def test_the_diagnosis_marks_the_vanos_it_identified(fuente):
    """Marcarlos es parte de la respuesta y no un paso aparte: sin marcarlos hay que
    buscarlos a mano en la lista de casillas y otra vez en el mapa, que es justo el
    trabajo que el boton venia a ahorrar.

    Los marca TODOS. Devolver una rebanada de lo que acaba de estudiar desmarca en
    silencio lo que el usuario habia marcado, y con los botones de grupo esa lista es de
    cientos.

    Al marcarlos, `vano_widget.observe(_redibujar_mapa_historico)` encierra cada uno
    en su recuadro sobre el mapa base. Verificado en vivo: 10 vanos marcados y 10
    recuadros."""
    cuerpo = fuente[fuente.index("def _al_pedir_diagnostico"):][:2200]
    assert "vano_widget.value = tuple(f for f, _u, _n in _ULTIMO_DIAGNOSTICO['vanos'])" in cuerpo
    # Las VARIABLES no se tocan aqui: que vanos mirar y que moverles son dos
    # decisiones, y los botones de aplicar responden la segunda.
    assert "knob_selector_widget.value" not in cuerpo


def test_each_apply_button_only_brings_in_its_own_half(fuente):
    """Un clic en intervencion deja EXACTAMENTE variables de intervencion. Si
    quedaran ademas las de escenario de una vuelta anterior, la simulacion mezclaria
    obra y clima y no se sabria cual de los dos movio el UITI.

    Los dos botones juntos si suman, porque presionar los dos es una decision del
    usuario y no un residuo. Verificado en vivo sobre AGU23L14: intervencion sola da
    5/0, escenario solo 0/3, y los dos 5/3."""
    cuerpo = fuente[fuente.index("def _aplicar_sugerencia"):][:3200]
    assert "GRUPOS_SUGERIDOS = ('intervencion', 'escenario')" in fuente
    # La seleccion se REEMPLAZA por los grupos aplicados, no se acumula sobre lo que
    # hubiera antes: eso es lo que hace que "solo lo aplicado" sea cierto.
    assert "knob_selector_widget.value = tuple(dict.fromkeys(ids_sugeridos))" in cuerpo
    assert "for g in GRUPOS_SUGERIDOS if g in _GRUPOS_APLICADOS" in cuerpo
    assert "if clave not in _GRUPOS_APLICADOS:" in cuerpo


def test_a_new_diagnosis_forgets_which_halves_were_applied(fuente):
    """Los grupos aplicados describen a los vanos del diagnostico VIGENTE. Al pedir
    otro -- o al cambiar de circuito o de ventana --, arrastrarlos haria que el primer
    clic marcara las dos mitades sin que nadie lo pidiera."""
    for ancla in ("def _al_pedir_diagnostico", "def _olvidar_diagnostico"):
        cuerpo = fuente[fuente.index(ancla):][:1600]
        assert "_GRUPOS_APLICADOS = []" in cuerpo, ancla


def test_the_figure_survives_dragging_a_map(fuente):
    """Con plotly 6.8.0, arrastrar un mapa MapLibre devuelve `map._derived` y
    `plotly_relayout` lo rechaza, asi que el tablero lanzaba en CADA arrastre. El
    error salia en la salida de la celda que muestra el widget -- por encima del
    tablero --, que es lo que lo hacia parecer un fallo de una celda anterior."""
    assert "fig = figura_de_mapas(_fig)" in fuente
    assert "fig = go.FigureWidget(_fig)" not in fuente
    assert "    figura_de_mapas," in fuente  # importada en la celda de arranque


def test_the_grid_pages_and_keeps_the_hidden_controls_alive(fuente):
    """Paginar no puede ser una forma silenciosa de descartar lo que se fijo: los
    controles de los vanos que no estan en pantalla siguen existiendo y entran igual a
    la simulacion. Verificado: 10 columnas y 50 controles vivos tras avanzar."""
    assert "def _mostrar_pagina():" in fuente
    assert "_COLUMNAS_VANO[desde:desde + VANOS_POR_PAGINA]" in fuente
    assert "boton_pagina_anterior.on_click(lambda _b: _mover_pagina(-1))" in fuente
    assert "boton_pagina_siguiente.on_click(lambda _b: _mover_pagina(1))" in fuente
    # La navegacion solo aparece si HAY mas de una pagina.
    assert "if paginas > 1 else []" in fuente


# --- Presentacion y arranque del cuaderno ---------------------------------------------


def test_the_window_slider_opens_on_the_most_recent_window(fuente):
    """Arranca en la ULTIMA ventana con eventos del circuito y no en la primera: es el
    periodo mas reciente, que es la pregunta con la que se abre el tablero. La primera
    es historia y se alcanza moviendo el deslizador.

    El respaldo al cambiar de circuito tambien cae en la ultima, por el mismo motivo.
    Lo que NO cambia es que una ventana elegida a mano se conserve cuando el circuito
    nuevo la tiene: eso es una eleccion del usuario, no un valor por defecto."""
    assert "value=_OPCIONES_INICIALES[-1][1]" in fuente
    assert "ventana_widget.value = _vigente if _vigente in _disponibles else _disponibles[-1]" in fuente


# Aqui vivian dos pruebas del cuaderno COMO DOCUMENTO: que toda celda de codigo
# estuviera plegada con `jupyter.source_hidden` y la etiqueta `hide-input`, y que un
# titulo de markdown ("## El tablero", con sus pasos) precediera a la celda del panel.
# Eran correctas y utiles: sin ellas, quien abria el `.ipynb` en JupyterLab se topaba
# con catorce celdas de codigo y nada que dijera cual ejecutar.
#
# Su sujeto desaparecio el 2026-08-16 con el propio cuaderno. Lo que las sustituye no es
# otra prueba sino el hecho de que no hay documento que leer: la aplicacion sirve un
# cuaderno generado de UNA celda, y la explicacion que aquel titulo daba -- por donde
# empezar, que hace cada boton -- se conservo en el README de la aplicacion
# (`tests/test_tableros_migrados.py::test_la_narrativa_del_cuaderno_sobrevivio_...`).


# El arranque dejo de vivir en las celdas del cuaderno y vive en
# `chec_tableros.simulador.derivacion`. Las tres pruebas de abajo protegen invariantes
# de MEMORIA, no de ubicacion, asi que siguen valiendo: solo cambia donde miran.
FUENTE_DERIVACION = (
    Path(__file__).resolve().parents[1]
    / "src" / "chec_tableros" / "simulador" / "derivacion.py"
).read_text(encoding="utf-8")


def test_the_startup_does_not_keep_a_second_copy_of_the_dataset():
    """Medido: `datos` sostenia la matriz cruda y los dos DataFrame mientras el arranque
    guardaba ademas un `.copy()` de cada uno -- 506 MB duplicados. Se suelta en la misma
    funcion que lo creo."""
    assert 'xdf = datos["Xdata"].reset_index(drop=True)' in FUENTE_DERIVACION
    assert 'context_df = datos["df_original_copy"].reset_index(drop=True)' in FUENTE_DERIVACION
    assert ".copy().reset_index(drop=True)" not in FUENTE_DERIVACION
    assert "del datos" in FUENTE_DERIVACION
    # `X_raw_model` eran 44,7 MB que solo alimentaban un `len()`: ya no se construye.
    assert "X_raw_model = " not in FUENTE_DERIVACION
    assert 'n_filas_x = len(datos["X"])' in FUENTE_DERIVACION


def test_the_instance_matrix_is_float32_like_the_model_weights():
    """Los pesos del MIL son float32, asi que la conversion ya ocurria en cada llamada.
    Medido sobre 523 bolsas de 3 circuitos con un override aplicado: clase simulada y
    UITI IDENTICOS BIT A BIT, y la matriz baja de 184,7 a 92,4 MB."""
    assert 'x_inst = np.asarray(bolsas["X"], dtype=np.float32)' in FUENTE_DERIVACION
    # Sin soltar el dict del artefacto, el ahorro seria un tercer juego de la matriz.
    assert "del bolsas" in FUENTE_DERIVACION


def test_the_raw_shapefile_is_released_after_the_geometry_is_built():
    """76 MB entre las dos tablas del shapefile, muertas en cuanto `GEO_POR_CIRCUITO`
    esta armado.

    En el cuaderno esto exigia un `del _lineas, _utiles` explicito, porque una celda
    comparte el espacio de nombres global y lo que se lee ahi no se muere nunca. Al
    pasar a una funcion la liberacion es del lenguaje: `lineas` y `utiles` son locales
    de `_geometria_de_vanos` y desaparecen al volver. Lo que se comprueba, entonces, es
    que NO se hayan vuelto globales por el camino -- que es la unica forma de perder la
    propiedad al moverla aqui.
    """
    assert "def _geometria_de_vanos(" in FUENTE_DERIVACION
    for local in ("    lineas = gpd.read_file(ruta)", "    utiles = lineas["):
        assert local in FUENTE_DERIVACION, local
    assert "\nlineas = " not in FUENTE_DERIVACION
    assert "\nutiles = " not in FUENTE_DERIVACION


def test_the_diagnosis_button_is_called_just_diagnostico(fuente):
    """El rotulo largo no cabia en el boton y se leia recortado, que es peor que
    corto: un boton que dice "Diagnostico circ..." no dice nada."""
    assert "boton_diagnostico = widgets.Button(description='Diagnostico'," in fuente
    assert "Diagnostico del circuito" not in fuente


# --- La figura de siete filas ----------------------------------------------------------


def test_the_figure_has_seven_rows_with_the_graph_in_its_own(fuente):
    """Fila 3 partida en dos: el perfil del circuito a la izquierda y el grafo a la
    derecha. Filas 5 y 6 partidas 3+1 -- las barras de UITI y las de costo, cada una
    con su acumulado en la ultima columna.

    El grafo tenia una septima fila para el solo, centrado y a media fila: un disco con
    dos franjas blancas a los lados y otra debajo -- 243 px de vacio en el mejor caso
    medido. Compartir la fila con el perfil llena las cuatro columnas y ahorra una fila
    entera; el circulo conserva su diametro porque la fila hereda el alto que tenia la
    del grafo.

    El reparto de alturas se comprueba por su INVARIANTE y no por sus cifras: clavar los
    seis numeros hacia fallar el test cada vez que se reajusta el grafo, que es justo lo
    que se quiere poder hacer. El invariante es que la fila del grafo siga siendo la mas
    alta -- es lo que fija el diametro del circulo --, y ahora esa fila es la 3.
    """
    assert "rows=7, cols=4," in fuente
    # El perfil y el grafo, cada uno en media fila de la misma fila.
    # El perfil a la izquierda y la SERIE de UITI a su derecha. Compartia esta fila el
    # grafo, que se fue a su propia figura debajo del panel de control: alli su ancho es el
    # del panel, que es donde se pidio. Con el grafo fuera la fila bajo a la mitad de alto,
    # que era lo unico que el diametro del circulo justificaba.
    assert _tiene(fuente, "[{'type': 'xy', 'colspan': 2}, None,\n"
                          "            {'type': 'xy', 'colspan': 2, 'secondary_y': True}, None]")
    # El grafo vuelve a tener fila para el solo -- la 7, bajo el costo --, y ocupa las
    # columnas 2-3: a media anchura, porque el anillo lo acota la dimension MENOR del panel
    # y de ancho completo solo apareceria franja blanca a los lados.
    assert "[None, {'type': 'xy', 'colspan': 2}, None, None]" in fuente
    # Las barras de UITI y las de costo: los vanos en las columnas 1-3 y el acumulado en
    # la 4. Juntos, el total -- la suma de todos los vanos -- aplastaba contra la base a
    # los grupos por vano, que es donde se decide la obra. Son DOS filas con el mismo
    # reparto, y esto es lo que impide que vuelvan a ocupar las cuatro columnas.
    assert fuente.count("[{'type': 'xy', 'colspan': 3}, None, None, {'type': 'xy'}]") == 2
    # UNA sola fila de ancho completo, y es la del top de variables: se quedo con las
    # cuatro columnas cuando la serie de UITI subio a compartir fila con el perfil.
    #
    # La regla no es "ninguna fila entera" -- eso era cierto mientras no habia ninguna que
    # la mereciera --, sino que las de UITI y costo NO lo sean, que es lo que fija la
    # asercion de arriba: con las cuatro columnas, el total aplasta contra la base a los
    # grupos por vano, que es donde se decide la obra.
    assert fuente.count("'colspan': 4") == 1, (
        "hay mas de una fila de ancho completo; solo el top de variables lo justifica")

    alturas = re.search(r"row_heights=\[([\d.,\s]+)\]", fuente)
    assert alturas, "la figura tiene que repartir el alto explicitamente"
    fracciones = [float(v) for v in alturas.group(1).split(",")]
    assert len(fracciones) == 7
    assert abs(sum(fracciones) - 1.0) < 1e-3, f"las fracciones no suman 1: {fracciones}"
    # El invariante no cambia: la fila del GRAFO es la mas alta, porque es su diametro lo
    # que la fija. Lo que cambio es cual: era la 3 cuando compartia con el perfil, y ahora
    # es la 7, la suya propia bajo el costo.
    assert fracciones[6] == max(fracciones), (
        f"la fila del grafo tiene que ser la mas alta: {fracciones}")

    # Los violines ya no existen: los reemplazan dos barras por vano.
    assert "go.Violin(" not in fuente
    assert "IDX['barra_observada']" in fuente
    assert "IDX['barra_simulada']" in fuente
    assert "IDX['barra_total_observada']" in fuente
    assert "IDX['barra_total_simulada']" in fuente


def test_el_perfil_del_circuito_no_suma_ventanas_que_se_traslapan(fuente):
    """El total de cada vano sale de `perfil_uiti_por_vano` y NUNCA de sumar
    `uiti_acumulado` sobre la tabla entera.

    Es la simplificacion que este panel invita a hacer y que estaria mal: las once
    ventanas se traslapan -- seis son meses y cinco son cortes del 15 al 15 --, asi que
    casi todo evento cae en dos y esa suma lo cuenta dos veces.
    `construir_tabla_vano_ventana` ya lo advierte en su docstring ("they cannot simply be
    summed"), y `perfil_uiti_por_vano` suma solo sobre las ventanas que embaldosan el
    periodo una vez.

    Medido sobre las 111.231 celdas reales: la suma ingenua infla el total de un vano
    entre 1,00 y 2,09 veces. Como el factor NO es constante tampoco se cancela al
    ordenar, que es el error silencioso: 74 de los 208 circuitos cambian su top 15. El
    panel seguiria dibujando quince barras plausibles, solo que de los vanos equivocados.
    """
    assert "IDX['perfil_circuito']" in fuente
    assert "perfil_uiti_por_vano(TABLA, circuito, ventanas=VENTANAS" in fuente
    codigo = [l for l in fuente.splitlines() if not l.strip().startswith("#")]
    prohibido = [l for l in codigo
                 if "uiti_acumulado" in l and ("groupby" in l or ".sum()" in l)]
    assert not prohibido, (
        f"el total del perfil no puede salir de una suma sobre TABLA: {prohibido}")


def test_el_perfil_del_circuito_solo_se_repinta_al_cambiar_de_circuito(fuente):
    """El perfil mira la serie COMPLETA, asi que ni la ventana ni los vanos marcados lo
    cambian. Se repinta desde `_pintar_circuito` -- lo que depende del circuito y nada
    mas -- y no desde `_redibujar_mapa_historico`, que corre en cada casilla y en cada
    clic sobre el mapa.

    No es solo higiene: un restyle de plotly cuesta lo suyo aunque lleve poco dato, y
    colgarlo del repintado del mapa lo pagaria en cada uno de los quince vanos que se
    pueden marcar, para volver a dibujar exactamente las mismas quince barras.
    """
    assert "_pintar_perfil_del_circuito(circuito)" in _cuerpo(fuente, "_pintar_circuito")
    assert "_pintar_perfil_del_circuito" not in _cuerpo(fuente, "_redibujar_mapa_historico")


def test_no_axis_of_the_dashboard_is_logarithmic(fuente):
    """La unica escala log era la del UITI de la serie, y era incompatible con dibujar
    las ventanas sin eventos: valen CERO, y `log(0)` no existe, asi que Plotly las
    descartaba en silencio y la secuencia completa de ventanas no se veia.

    Se miran solo las lineas de CODIGO: el comentario que explica por que se quito la
    escala nombra `type='log'`, y una busqueda sobre el texto entero lo confundiria con
    un eje logaritmico vivo."""
    codigo = [l for l in fuente.splitlines() if not l.strip().startswith("#")]
    assert not [l for l in codigo if "type='log'" in l or '"log"' in l]


def test_the_circular_graph_keeps_its_aspect_at_any_screen_width(fuente):
    """Sin `scaleanchor` el panel es mucho mas ancho que alto y el circulo se dibujaba
    como una elipse aplastada 2,93 veces -- medido --, lo que ademas descuadra el giro
    radial de cada rotulo respecto de la direccion que se ve.

    El rango va JUSTO a lo que ocupan los rotulos, y por eso se DERIVA del mas largo en
    vez de escribirse a ojo: es el numero que reparte el panel entre el anillo y sus
    nombres. Cuanto menor, mayor el circulo -- y en cuanto se queda corto los nombres se
    salen del panel y se montan sobre el anillo, que es como se veia con fuente 14.
    """
    # (7,2): el grafo volvio a la figura grande, en una fila propia bajo el costo y a
    # media anchura. Lo que la prueba persigue no ha cambiado -- los dos ejes atados y con
    # el mismo rango --, solo la casilla en la que vive.
    assert "scaleanchor=_EJE_X_GRAFO, scaleratio=1.0, row=7, col=2" in fuente
    assert fuente.count("range=[-RANGO_GRAFO, RANGO_GRAFO]") == 2, (
        "los dos ejes del grafo tienen que llevar el MISMO rango")
    rango = re.search(r"^\s*RANGO_GRAFO = ([\d.]+)$", fuente, re.MULTILINE)
    assert rango, "el rango del grafo tiene que ser una constante con su justificacion"
    # Cota inferior: por debajo de `RADIO_ROTULO_GRAFO` el rango caeria DENTRO del anillo
    # y no habria sitio ni para empezar a escribir los nombres.
    assert float(rango.group(1)) > 1.05


def test_the_node_labels_are_rotated_annotations_and_not_trace_text(fuente):
    """Un `Scatter` no puede girar su texto -- comprobado contra plotly 6.8.0, solo `Bar`
    y las anotaciones llevan `textangle` --, asi que los nombres van como anotaciones.

    La reserva es FIJA y las que sobran quedan invisibles: quitar anotaciones correria
    los indices de los avisos del grafo, de los costos y del mapa simulado, que se
    guardan por posicion."""
    assert "MAX_NODOS_GRAFO = len(FEATURES_MIL)" in fuente
    assert "IDX_ANOTACIONES_NODOS" in fuente
    assert "_anotacion.textangle = _giro" in fuente
    cuerpo = fuente[fuente.index("IDX['grafo_nodos'] = ["):][:600]
    assert "mode='markers'," in cuerpo and "markers+text" not in cuerpo


def test_the_graph_panel_shows_what_the_simulation_moved(fuente):
    """`|grafo_base - grafo_simulado|`. Los dos comparten los pesos fijos del experto y
    solo difieren por las compuertas, asi que puestos uno al lado del otro se ven iguales
    y el efecto de la intervencion se pierde.

    Las features simuladas salen de la metadata y no se rearman en el cuaderno: repetir
    ahi la expansion de overrides es la forma segura de que el grafo acabe describiendo
    un escenario distinto del que puntuo el mapa."""
    assert "grafo_diferencia(gates_base, gates_simuladas" in fuente
    assert "metadata['X_simulado']" in fuente
    # Una matriz toda en cero es un RESULTADO y se dice, no se deja como panel vacio.
    #
    # Se compara SIN TILDES a proposito. Lo que este guardian defiende es que el caso
    # vacio tenga mensaje, no como se escriba: fijar la ortografia exacta convertia una
    # correccion de acentos -- que es justo lo que este texto necesitaba, porque se ve en
    # pantalla -- en una prueba en rojo.
    import unicodedata
    plano = unicodedata.normalize("NFKD", fuente).encode("ascii", "ignore").decode("ascii")
    assert "La simulacion no movio ninguna relacion del grafo." in plano


def test_the_bars_headline_carries_the_models_own_offset(fuente):
    """El titulo publica la reduccion con su `+-`. La barra medida y la simulada son
    cantidades de naturaleza distinta -- medido sobre 599 bolsas, el modelo correlaciona
    0,950 con lo observado pero su nivel corre +34% --, asi que la resta desnuda de las
    dos barras lleva el error del modelo. El `+-` es exactamente lo que lo cubre."""
    assert "def _titulo_de_barras(barras):" in fuente
    assert "IDX_TITULO_BARRAS" in fuente
    # El indice se BUSCA por el texto: los titulos de subplot dependen de la rejilla.
    assert "if (_a.text or '').startswith('UITI acumulado: medido')" in fuente
