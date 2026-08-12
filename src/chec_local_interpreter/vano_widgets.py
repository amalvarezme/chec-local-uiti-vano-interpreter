"""Widget constructor for notebook 01.5's risk simulator (PR2a).

The only place that imports `ipywidgets` for the Knob catalog -- and it
imports it lazily, INSIDE `widget_for_knob`, so importing this module (or
`vano_controls`) never requires ipywidgets to be installed. Every decision
this module makes was already made by `vano_controls.build_knobs`; this is
a thin three-branch constructor with nothing left to test beyond "does it
build the right widget type from the right Knob fields".

See:
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (section B)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chec_local_interpreter.vano_controls import Knob


def widget_for_knob(knob: "Knob"):
    """Build the ipywidgets control for `knob`: `FloatSlider` for numeric,
    `Dropdown` for categorical, disabled `FloatText` for constant."""
    import ipywidgets as widgets

    if knob.kind == "categorical":
        options = list(knob.categories or ())
        value = knob.default if knob.default in options else (options[0] if options else None)
        return widgets.Dropdown(options=options, value=value, description=knob.label)

    if knob.kind == "numeric":
        lo, hi = knob.bounds
        value = lo if knob.default is None else float(knob.default)
        step = knob.step or max((hi - lo) / 100.0, 1e-6)
        return widgets.FloatSlider(
            value=value,
            min=lo,
            max=hi,
            step=step,
            description=knob.label,
            continuous_update=False,
            readout_format=".4g",
        )

    # kind == "constant": nothing to vary, show the value but disable input.
    value = knob.default if isinstance(knob.default, (int, float)) else 0.0
    return widgets.FloatText(value=float(value), description=knob.label, disabled=True)


# --- Selector por casillas (vanos, y variables del simulador) ---------------
# 01.4 marks vanos with CHECKBOXES and lets a map click toggle the very same
# checkbox. A `SelectMultiple` cannot do that: it has no per-item handle to
# flip from a click callback, and ctrl-clicking to keep a selection is a
# well-known way to lose it -- one plain click wipes everything already
# picked. That second reason applies just as much to the simulator's variable
# list, so ONE parameterised class serves both; only the option shape differs
# (a fid is its own label, a knob shows "Precipitacion (12 lags)" and yields
# `clima:prep`). The class is built lazily, inside a function, for the same
# reason `widget_for_knob` imports ipywidgets lazily: importing this module
# must never require ipywidgets to be installed.

_CLASE_SELECTOR = None


def _pares_de_opciones(opciones):
    """`(etiqueta, clave)` per option. A 2-tuple is taken as the pair itself;
    anything else is a scalar that labels itself (the vano case, where the
    label IS the fid)."""
    for opcion in opciones:
        if isinstance(opcion, tuple) and len(opcion) == 2:
            etiqueta, clave = opcion
        else:
            etiqueta = clave = opcion
        yield str(etiqueta), str(clave)


def _clase_selector():
    global _CLASE_SELECTOR
    if _CLASE_SELECTOR is not None:
        return _CLASE_SELECTOR

    import ipywidgets as widgets
    import traitlets

    class SelectorCasillas(widgets.VBox):
        """A scrollable checkbox list whose `value` trait is the tuple of
        ticked keys. Downstream cells keep using `observe(names='value')`
        and never learn there are checkboxes behind it."""

        value = traitlets.Tuple()

        def __init__(self, opciones=(), *, titulo="", alto="132px",
                     ancho_casilla="96px", maximo=None, columnas=None,
                     tooltips=None, info=None, **kwargs):
            super().__init__(**kwargs)
            self.casillas = {}
            # `clave -> texto` que el navegador muestra al posar el mouse sobre la
            # casilla. Vive en el selector y no en las opciones porque `poblar` se
            # vuelve a llamar al cambiar de circuito: colgado de la lista de
            # opciones, el tooltip se perderia en el primer cambio.
            self.tooltips = dict(tooltips or {})
            # `clave -> texto` del boton "i". La casilla lleva el precio y el nombre;
            # el boton contesta QUE es. Con 142 actividades y nombres de hasta 153
            # caracteres, meter tipo, unidad, codigo y descripcion en la etiqueta deja
            # la lista sin recorrer. `None` = sin botones, que es lo que heredan los
            # selectores de vanos y de items que no lo usan: no pueden pagar 142
            # widgets extra ni cambiar de aspecto.
            self.info = dict(info or {}) if info is not None else None
            self.botones_info: dict = {}
            self.panel_info = (
                widgets.HTML('<span style="font-size:12px;color:#5b4a48;">'
                             'Pulsa <b>i</b> en cualquier renglon para ver su detalle.'
                             '</span>')
                if info is not None else None
            )
            self._silencio = False
            # Corta la reentrada cuando el observer de `value` reescribe `value` para
            # dejarlo en el orden y el tope de las casillas.
            self._normalizando = False
            self._ancho_casilla = ancho_casilla
            # `maximo` acota cuantas claves pueden quedar marcadas a la vez.
            # Notebook 06 lo usa: cada vano seleccionado recibe su propia COLUMNA
            # de controles, y una rejilla de 26 variables por 20 vanos no se lee
            # ni se llena. `None` = sin tope, que es lo que heredan 01.4 y sus
            # hermanos, donde marcar cientos de vanos es el caso normal.
            self.maximo = maximo
            # UN solo Layout y UN solo Style para todas las casillas, y otro par para
            # todos los botones. Cada widget de ipywidgets manda al frontend su propio
            # `LayoutModel` y su propio `StyleModel` ademas de si mismo: en el tablero
            # del 06 eran 592 layouts y 377 estilos de 1.587 modelos -- el 61% --, y
            # todos decian exactamente lo mismo. Compartir la instancia los colapsa a
            # uno por familia sin cambiar un pixel, y es estado que el visor ya no
            # tiene que montar. Se crean aqui y no en `poblar` para que la rebaja
            # sobreviva a los cambios de circuito.
            self._estilo_casilla = widgets.Checkbox.style.klass()
            self._layout_casilla = widgets.Layout(width=ancho_casilla,
                                                  margin="0 8px 0 0")
            self._layout_casilla_columna = widgets.Layout(width=ancho_casilla,
                                                          margin="0 0 0 0")
            self._estilo_boton = widgets.ButtonStyle()
            self._layout_boton = widgets.Layout(width="26px", min_width="26px",
                                                margin="0 6px 0 0")
            self._layout_renglon = widgets.Layout(align_items="center",
                                                  margin="0 8px 0 0")
            self.caja = widgets.Box(
                layout=widgets.Layout(
                    # `overflow` y no `overflow_y`: ipywidgets 8 saco los ejes
                    # sueltos de Layout y los ignora con un DeprecationWarning.
                    max_height=alto, overflow="auto", display="flex",
                    flex_flow="row wrap", align_items="flex-start",
                    border="1px solid #e4c4c0", padding="4px 6px",
                ),
            )
            encabezado = [widgets.HTML(f"<b>{titulo}</b>")] if titulo else []
            pie = [self.panel_info] if self.panel_info is not None else []
            self.children = [*encabezado, self.caja, *pie]
            if columnas is not None:
                self.poblar_columnas(columnas)
            else:
                self.poblar(opciones)

        def _con_boton(self, clave, casilla):
            """La casilla y su boton "i", en un renglon.

            El boton escribe en UN panel compartido debajo de la lista, y no abre un
            emergente por actividad: 142 emergentes son 142 sitios donde mirar, y el
            panel unico deja el detalle siempre en el mismo lugar de la pantalla.
            """
            boton = widgets.Button(
                description="i", tooltip="Ver el detalle de este renglon",
                layout=self._layout_boton, style=self._estilo_boton,
            )
            boton.on_click(lambda _b, c=clave: self._mostrar_info(c))
            self.botones_info[clave] = boton
            return widgets.HBox([boton, casilla], layout=self._layout_renglon)

        def _cerrar(self, widget):
            """Cierra un widget y todo lo que cuelgue de el.

            `Widget.widgets` guarda referencias FUERTES, asi que lo que `poblar`
            reemplaza sigue vivo y sigue viajando en el estado que el visor monta,
            aunque ya nadie lo vea. Un cambio de circuito no puede dejar residuo.

            Baja por `children` y no por `layout` ni `style`: esos se COMPARTEN entre
            todas las casillas, y cerrarlos con la primera dejaria mudas a las demas.
            """
            for hijo in getattr(widget, "children", ()):
                self._cerrar(hijo)
            if getattr(widget, "comm", None) is not None:
                widget.close()

        def _soltar_lo_anterior(self, hijos_previos):
            for hijo in hijos_previos:
                self._cerrar(hijo)

        def _mostrar_info(self, clave):
            # Un panel en blanco se lee como que el boton no funciona; se dice que no
            # hay detalle en vez de dejarlo vacio.
            texto = (self.info or {}).get(clave) or (
                f"Sin detalle registrado para <b>{clave}</b>.")
            self.panel_info.value = (
                '<div style="font-size:12px;color:#2b2b2b;background:#fdf7f6;'
                'border:1px solid #e4c4c0;border-left:4px solid rgb(203,24,29);'
                'border-radius:4px;padding:6px 10px;margin-top:4px;">'
                f'{texto}</div>')

        def poblar(self, opciones):
            """Rebuilds the list for a new option set (a new circuit, in the
            vano case). The previous selection is DROPPED on purpose: keeping
            it would leave keys ticked that the new option set does not have."""
            self._silencio = True
            try:
                hijos_previos = tuple(self.caja.children)
                self.botones_info = {}
                self.casillas = {
                    clave: widgets.Checkbox(
                        value=False, description=etiqueta, indent=False,
                        tooltip=self.tooltips.get(clave, ""),
                        # Ancho explicito y no via CSS: el `layout` viaja como estilo
                        # inline y le gana a cualquier hoja de estilos sin `!important`,
                        # asi que mezclar los dos deja columnas impredecibles. 96 px es
                        # el fid de 8 digitos a 12 px mas su casilla, como en 01.4; una
                        # variable con nombre largo pide su propio ancho.
                        layout=self._layout_casilla, style=self._estilo_casilla,
                    )
                    for etiqueta, clave in _pares_de_opciones(opciones)
                }
                for caja in self.casillas.values():
                    caja.observe(self._al_cambiar_casilla, names="value")
                self.caja.children = (
                    tuple(self._con_boton(c, w) for c, w in self.casillas.items())
                    if self.info is not None else tuple(self.casillas.values()))
                self._soltar_lo_anterior(hijos_previos)
            finally:
                self._silencio = False
            self.value = ()
            # Sin esto un circuito nuevo arrancaria con las casillas que el
            # anterior dejo deshabilitadas por el tope, y bloqueado de entrada.
            self._aplicar_tope()

        def poblar_columnas(self, columnas):
            """Las mismas casillas, repartidas en COLUMNAS con titulo.

            Es lo que pide la lista de variables del simulador: dos columnas para lo
            que se puede hacer y dos para lo que se quiere anticipar. Una lista
            corrida obliga a recordar el veredicto de cada variable para saber a cual
            de las dos preguntas pertenece; en columnas lo dice la posicion.

            Una columna VACIA se dibuja igual, con su titulo solo: si desapareciera,
            las demas se corririan de sitio cada vez que cambia el catalogo.

            `value` sigue saliendo de las casillas y en el orden en que las columnas
            las declaran, que es el que usan la rejilla de controles y el resumen.
            """
            self._silencio = True
            try:
                hijos_previos = tuple(self.caja.children)
                self.casillas = {}
                self.botones_info = {}
                cajas = []
                for titulo_columna, opciones in columnas:
                    de_la_columna = []
                    for etiqueta, clave in _pares_de_opciones(opciones):
                        caja = widgets.Checkbox(
                            value=False, description=etiqueta, indent=False,
                            tooltip=self.tooltips.get(clave, ""),
                            layout=self._layout_casilla_columna,
                            style=self._estilo_casilla,
                        )
                        caja.observe(self._al_cambiar_casilla, names="value")
                        self.casillas[clave] = caja
                        # Mismo boton "i" que la lista plana. Sin esto, el selector de
                        # VARIABLES -- que es el unico que usa columnas -- se queda sin
                        # botones, y es justo donde hacen falta: la sigla no dice nada.
                        de_la_columna.append(
                            self._con_boton(clave, caja) if self.info is not None
                            else caja)
                    cabecera = widgets.HTML(
                        f'<span style="font-weight:600;font-size:12px;'
                        f'border-bottom:1px solid #e4c4c0;display:block;'
                        f'margin-bottom:3px;">{titulo_columna}</span>'
                    )
                    cajas.append(widgets.VBox(
                        [cabecera, *de_la_columna],
                        layout=widgets.Layout(align_items="flex-start",
                                              margin="0 12px 0 0"),
                    ))
                self.caja.children = tuple(cajas)
                self._soltar_lo_anterior(hijos_previos)
                # Las columnas mandan el ancho; el `flex_flow` de fila corrida las
                # apilaria de a una por renglon en cuanto la celda se estreche.
                self.caja.layout.flex_flow = "row nowrap"
            finally:
                self._silencio = False
            self.value = ()
            self._aplicar_tope()

        def _aplicar_tope(self):
            """Con el cupo lleno, las casillas SIN marcar se deshabilitan. Se
            deshabilitan en vez de aceptar el clic y revertirlo: un clic que se
            deshace solo se lee como un fallo del tablero. Las ya marcadas quedan
            habilitadas, o no habria forma de soltar una para tomar otra."""
            if self.maximo is None:
                return
            lleno = sum(1 for c in self.casillas.values() if c.value) >= self.maximo
            for caja in self.casillas.values():
                caja.disabled = lleno and not caja.value

        def marcar_todos(self):
            """01.4's "Marcar todos" button. Con tope marca los primeros y para:
            pasarse dejaria el estado en un tamano que el panel no puede dibujar."""
            self._fijar_todas(True)

        def desmarcar_todos(self):
            """01.4's "Desmarcar" button."""
            self._fijar_todas(False)

        def _fijar_todas(self, marcado):
            """Flips every checkbox behind `_silencio` and emits ONE `value`
            change at the end. Letting each checkbox notify on its own would
            fire one map repaint per vano -- hundreds on a real circuit, each
            one re-grouping the whole geometry."""
            self._silencio = True
            try:
                cupo = len(self.casillas) if self.maximo is None else self.maximo
                for i, caja in enumerate(self.casillas.values()):
                    caja.value = marcado and i < cupo
            finally:
                self._silencio = False
            self.value = tuple(
                clave for clave, caja in self.casillas.items() if caja.value
            )
            self._aplicar_tope()

        def alternar(self, clave):
            """The map-click entry point. Flips the checkbox and lets its own
            handler recompute `value`, so a click and a tick cannot diverge.
            An unknown key -- the circuit's geometry has tramos that never had
            an event -- is ignored, never turned into a phantom checkbox.

            El tope se comprueba AQUI y no solo en la interfaz: el clic del mapa
            entra por este camino sin pasar por la casilla, asi que confiar solo
            en `disabled` dejaria al mapa como puerta trasera para el sexto vano.
            """
            caja = self.casillas.get(str(clave))
            if caja is None:
                return
            if not caja.value and self._cupo_lleno():
                return
            caja.value = not caja.value

        def _cupo_lleno(self):
            if self.maximo is None:
                return False
            return sum(1 for c in self.casillas.values() if c.value) >= self.maximo

        def _al_cambiar_casilla(self, _cambio):
            if self._silencio:
                return
            # Derived from the checkboxes, never accumulated separately: the
            # checkboxes ARE the state. Order follows the option list so the
            # legend and the ranking do not reshuffle between repaints.
            self.value = tuple(
                clave for clave, caja in self.casillas.items() if caja.value
            )
            self._aplicar_tope()

        @traitlets.observe("value")
        def _al_fijar_value(self, cambio):
            """Marcar POR CODIGO tambien tiene que mover las casillas.

            `value` es la puerta que usa el diagnostico del cuaderno 06 para marcar
            los vanos que identifico. Sin esto el trait decia diez y la lista se veia
            vacia -- el mapa si los resaltaba, porque lee `value` --, y como
            `_al_cambiar_casilla` recalcula `value` DESDE las casillas, tocar una
            sola a mano borraba en silencio todo lo que el diagnostico habia puesto.

            Se normaliza ademas lo que se asigno: se descartan las claves que este
            selector no tiene -- un fid de otro circuito no puede quedar afirmado en
            `value` sin casilla que lo muestre --, se respeta el tope y el orden pasa
            a ser el de las opciones. Asi `value` nunca describe algo distinto de lo
            que hay en pantalla.
            """
            if self._silencio or self._normalizando:
                return
            cupo = len(self.casillas) if self.maximo is None else self.maximo
            elegidas, vistas = [], set()
            for clave in cambio["new"]:
                clave = str(clave)
                if clave in self.casillas and clave not in vistas:
                    vistas.add(clave)
                    elegidas.append(clave)
            elegidas = set(elegidas[:cupo])
            self._silencio = True
            try:
                for clave, caja in self.casillas.items():
                    caja.value = clave in elegidas
            finally:
                self._silencio = False
            ordenado = tuple(c for c in self.casillas if c in elegidas)
            if ordenado != tuple(cambio["new"]):
                # `_normalizando` corta la reentrada: la segunda pasada ya llegaria al
                # mismo resultado, pero dejarla correr encadena un observer por cada
                # marcado por codigo.
                self._normalizando = True
                try:
                    self.value = ordenado
                finally:
                    self._normalizando = False
            self._aplicar_tope()

    _CLASE_SELECTOR = SelectorCasillas
    return _CLASE_SELECTOR


def construir_selector_casillas(opciones=(), **kwargs):
    """Builds a checkbox list from `opciones`, each either a scalar (it labels
    itself) or an `(etiqueta, clave)` pair. `value` is the tuple of ticked
    keys, in option order."""
    return _clase_selector()(opciones, **kwargs)


def construir_selector_vanos(opciones=(), **kwargs):
    """The vano selector (01.4 parity: checkbox OR map click, one shared
    state) -- `construir_selector_casillas` with the vano's own heading and
    the 8-digit-fid column width."""
    kwargs.setdefault("titulo", "Vanos")
    kwargs.setdefault("ancho_casilla", "96px")
    return construir_selector_casillas(opciones, **kwargs)


MAX_VANOS_ANALISIS = 10
"""Cuantos vanos puede analizar a la vez el simulador del cuaderno 06.

Diez y no cinco: el diagnostico del circuito estudia los diez vanos mas criticos
y ofrece aplicarles la sugerencia de golpe, asi que un tope de cinco dejaria la
mitad del diagnostico sin poder ejecutarse.

Lo que cinco protegia era la REJILLA -- cada vano recibe su propia columna de
controles, y diez columnas de veintiseis controles no se leen ni se llenan --, y
eso ahora lo resuelve la paginacion: se muestran `VANOS_POR_PAGINA` a la vez y se
avanza. Los controles de los vanos que no estan en pantalla siguen existiendo y
conservando su valor, asi que la simulacion los aplica igual.
"""

VANOS_POR_PAGINA = 5
"""Cuantas columnas de controles se muestran a la vez en la rejilla del 06.

Cinco es lo que cabe legible a lo ancho del panel. Por encima, las columnas se
estrechan hasta que el nombre de la variable y su deslizador dejan de caber en la
misma linea, y la rejilla se vuelve un muro.
"""


# --- El guardia del relayout: arrastrar un mapa no puede tumbar el tablero -----------


def sin_claves_derivadas(relayout_data):
    """El payload de relayout del navegador, sin las claves que plotly se manda a
    si mismo.

    Se descarta todo tramo final que empieza por guion bajo. Ninguna propiedad
    real del layout empieza asi; `_derived` es la que manda MapLibre con las
    esquinas que acaba de calcular, y no es algo que se pueda FIJAR.
    """
    return {clave: valor for clave, valor in relayout_data.items()
            if not clave.split(".")[-1].startswith("_")}


def figura_de_mapas(*args, **kwargs):
    """Un `go.FigureWidget` que sobrevive a que el usuario arrastre o haga zoom
    sobre un mapa. Toma los mismos argumentos que `go.FigureWidget`.

    Con plotly 6.8.0, mover un subplot `map` (MapLibre) dentro de un
    `FigureWidget` devuelve `map._derived` junto a `map.center` y `map.zoom`, y
    `plotly_relayout` lo rechaza con `Invalid property path 'map._derived' for
    layout`. `basewidget._handler_js2py_relayout` limpia `lastInputTime` de ese
    mismo payload pero nada mas, asi que la excepcion salta en CADA arrastre.

    Aparece en la salida de la celda que muestra el widget -- por encima del
    tablero --, que es lo que hace que se lea como si una celda anterior se
    hubiera roto, y no como lo que es: un mapa que se movio.

    Se corrige en `plotly_relayout` y no en el manejador privado del widget
    porque es el punto publico por el que pasa todo lo que llega del navegador,
    y no depende de como plotly nombre sus internos manana.

    Es una funcion y no una clase de modulo porque plotly se importa AL
    CONSTRUIR: `vano_widgets` se importa desde codigo que no dibuja nada, y
    seguir la misma regla que `widget_for_knob` con ipywidgets deja el modulo
    importable sin las dependencias de dibujo.
    """
    import plotly.graph_objects as go

    class FiguraDeMapas(go.FigureWidget):
        def plotly_relayout(self, relayout_data, **kwargs):
            limpio = sin_claves_derivadas(relayout_data)
            # Un payload que SOLO traia claves internas no llega a plotly: no
            # queda nada que cambiar, y `plotly_relayout({})` haria trabajo y
            # avisos por una interaccion que no movio nada.
            if not limpio:
                return None
            return super().plotly_relayout(limpio, **kwargs)

    return FiguraDeMapas(*args, **kwargs)
