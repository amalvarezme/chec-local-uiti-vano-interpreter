"""Contract tests for notebook 06's yellow selection box.

Clicking a vano on the base map (row 1) marks it, and a marked vano is
enclosed in a translucent yellow box -- turned to the vano's own inclination
-- so it stays findable on a circuit of hundreds of segments. The geometry of
that box is
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


def test_the_diagnostic_coerces_the_fid_to_text_before_looking_it_up(fuente):
    """`DATOS_VENTANA` esta indexado por TEXTO y `VANOS_POR_CIRCUITO` puede traer los
    fid como numero. Sin la coercion no coincide ninguno."""
    assert "if str(f) in datos" in fuente


def test_the_framing_buttons_compute_the_view_at_click_time(fuente):
    """Un `updatemenu` de plotly lleva argumentos FIJOS calculados al dibujar: entre el
    dibujo y el clic pueden haber cambiado los vanos marcados, y el boton llevaria a
    donde estaba la seleccion antes."""
    assert "def _centrar_mapa(nombre_mapa):" in fuente
    cuerpo = fuente[fuente.index("def _centrar_mapa(nombre_mapa):"):][:1400]
    assert "_seleccion_actual()" in cuerpo
    assert "bounds_de_fids(geo, marcados)" in cuerpo
    assert "or _vista_del_circuito(circuito)" in cuerpo
    # Uno por mapa, y los dos dentro del layout de la app.
    assert "_boton_encuadre('map', 'Centrar mapa base')" in fuente
    assert "_boton_encuadre('map2', 'Centrar mapa simulado')" in fuente
    assert "widgets.VBox([ESTILO, PANEL, ENCUADRES, fig]" in fuente


def test_the_diagnostic_takes_alto_first_and_completes_with_medio_alto(fuente):
    """La pregunta es por donde EMPEZAR, y un vano en Medio no es por donde se empieza
    mientras queden vanos en Alto sin atender. Dentro de cada grupo manda el UITI, que
    es lo que ordena la urgencia."""
    assert "GRUPOS_DIAGNOSTICO = [3, 2]" in fuente
    cuerpo = fuente[fuente.index("def _diagnostico_del_circuito"):][:2600]
    assert "clases.get(str(f)) == clase" in cuerpo
    assert "peores.extend(por_grupo[clase][:TOP_VANOS_CIRCUITO - len(peores)])" in cuerpo


def test_a_short_diagnostic_says_how_many_it_found(fuente):
    """Sin el aviso, una lista de cuatro vanos se lee como que el circuito tiene cuatro
    criticos, cuando lo que pasa es que no llegan a diez. Verificado sobre datos
    reales: un circuito con 3 en Medio-Alto y ninguno en Alto lo dice, y otro sin
    ninguno de los dos lo dice tambien."""
    assert "Se identificaron " in fuente
    assert "no tiene mas en Alto ni en Medio-Alto" in fuente
    # El caso sin NINGUNO tiene su propio mensaje, que dice que no es un fallo.
    assert "no hay ningun vano en " in fuente
    assert "No hay diagnostico que dar" in fuente


def test_the_apply_buttons_use_each_vano_own_value_and_not_the_average(fuente):
    """El promedio ORDENA la lista, pero lo que baja a un vano concreto es su propio
    optimo. Aplicar el promedio simularia un escenario que no es el de ninguno."""
    assert "'ranking': ranking," in fuente
    cuerpo = fuente[fuente.index("def _aplicar_sugerencia"):][:3200]
    assert "diag['ranking'].get(fid, {}).get('filas', [])" in cuerpo


def test_the_diagnosis_marks_the_vanos_it_identified(fuente):
    """Marcarlos es parte de la respuesta y no un paso aparte: el diagnostico nombra
    diez vanos, y sin marcarlos hay que buscarlos a mano en la lista de casillas y
    otra vez en el mapa, que es justo el trabajo que el boton venia a ahorrar.

    Al marcarlos, `vano_widget.observe(_redibujar_mapa_historico)` encierra cada uno
    en su recuadro sobre el mapa base. Verificado en vivo: 10 vanos marcados y 10
    recuadros."""
    cuerpo = fuente[fuente.index("def _al_pedir_diagnostico"):][:1600]
    assert "vano_widget.value = tuple(" in cuerpo
    assert "_ULTIMO_DIAGNOSTICO['vanos'][:MAX_VANOS_ANALISIS]" in cuerpo
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


def test_every_code_cell_is_collapsed_but_its_output_is_not():
    """El cuaderno se lee como documento: el texto y las SALIDAS a la vista -- el
    tablero es una salida -- y el codigo plegado. `jupyter.source_hidden` es lo que
    leen JupyterLab, Notebook 7 y el editor de VS Code; la etiqueta `hide-input` es
    para nbconvert, que no mira `source_hidden` y sin ella exportaria todo el codigo."""
    celdas = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    codigo = [c for c in celdas if c["cell_type"] == "code"]
    assert codigo, "el cuaderno perdio sus celdas de codigo"
    for celda in codigo:
        meta = celda.get("metadata", {})
        assert meta.get("jupyter", {}).get("source_hidden") is True
        assert "hide-input" in meta.get("tags", [])
        # La SALIDA no se pliega: es lo unico que queda para ver.
        assert meta.get("jupyter", {}).get("outputs_hidden") is not True


def test_a_markdown_title_introduces_the_dashboard():
    """Sin un titulo antes del tablero, la celda que lo muestra es una mas entre catorce
    plegadas y no hay nada que diga cual ejecutar ni en que orden se usa."""
    celdas = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    i_panel = next(i for i, c in enumerate(celdas) if c["cell_type"] == "code"
                   and "El panel, ARRIBA y del ancho de la figura" in "".join(c["source"]))
    anterior = celdas[i_panel - 1]
    assert anterior["cell_type"] == "markdown"
    texto = "".join(anterior["source"])
    assert "## El tablero" in texto
    # Nombra los pasos, que es lo que lo hace util y no decorativo.
    for paso in ("Diagnostico", "Aplicar intervencion", "Simular"):
        assert paso in texto


def test_the_startup_does_not_keep_a_second_copy_of_the_dataset(fuente):
    """Medido: `datos` sostenia la matriz cruda y los dos DataFrame mientras el cuaderno
    guardaba ademas un `.copy()` de cada uno -- 506 MB duplicados. Se suelta en la MISMA
    celda que lo creo, asi que la celda sigue siendo re-ejecutable."""
    assert "Xdf = datos['Xdata'].reset_index(drop=True)" in fuente
    assert "context_df = datos['df_original_copy'].reset_index(drop=True)" in fuente
    assert ".copy().reset_index(drop=True)" not in fuente
    assert "del datos" in fuente
    # `X_raw_model` eran 44,7 MB que solo alimentaban un `len()`: ya no se construye.
    assert "X_raw_model = " not in fuente
    assert "n_filas_x = len(datos['X'])" in fuente


def test_the_instance_matrix_is_float32_like_the_model_weights(fuente):
    """Los pesos del MIL son float32, asi que la conversion ya ocurria en cada llamada.
    Medido sobre 523 bolsas de 3 circuitos con un override aplicado: clase simulada y
    UITI IDENTICOS BIT A BIT, y la matriz baja de 184,7 a 92,4 MB."""
    assert "X_INST = np.asarray(BOLSAS['X'], dtype=np.float32)" in fuente
    # Sin soltar el dict del artefacto, el ahorro seria un tercer juego de la matriz.
    assert "del BOLSAS" in fuente


def test_the_raw_shapefile_is_released_after_the_geometry_is_built(fuente):
    """76 MB entre las dos tablas del shapefile, muertas en cuanto `GEO_POR_CIRCUITO`
    esta armado. Se sueltan en la misma celda que las leyo, que es lo que deja volver a
    correr esa celda sin un NameError."""
    assert "del _lineas, _utiles" in fuente


def test_the_diagnosis_button_is_called_just_diagnostico(fuente):
    """El rotulo largo no cabia en el boton y se leia recortado, que es peor que
    corto: un boton que dice "Diagnostico circ..." no dice nada."""
    assert "boton_diagnostico = widgets.Button(description='Diagnostico'," in fuente
    assert "Diagnostico del circuito" not in fuente
