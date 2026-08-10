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
                     ancho_casilla="96px", maximo=None, columnas=None, **kwargs):
            super().__init__(**kwargs)
            self.casillas = {}
            self._silencio = False
            self._ancho_casilla = ancho_casilla
            # `maximo` acota cuantas claves pueden quedar marcadas a la vez.
            # Notebook 06 lo usa: cada vano seleccionado recibe su propia COLUMNA
            # de controles, y una rejilla de 26 variables por 20 vanos no se lee
            # ni se llena. `None` = sin tope, que es lo que heredan 01.4 y sus
            # hermanos, donde marcar cientos de vanos es el caso normal.
            self.maximo = maximo
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
            self.children = [*encabezado, self.caja]
            if columnas is not None:
                self.poblar_columnas(columnas)
            else:
                self.poblar(opciones)

        def poblar(self, opciones):
            """Rebuilds the list for a new option set (a new circuit, in the
            vano case). The previous selection is DROPPED on purpose: keeping
            it would leave keys ticked that the new option set does not have."""
            self._silencio = True
            try:
                self.casillas = {
                    clave: widgets.Checkbox(
                        value=False, description=etiqueta, indent=False,
                        # Ancho explicito y no via CSS: el `layout` viaja como estilo
                        # inline y le gana a cualquier hoja de estilos sin `!important`,
                        # asi que mezclar los dos deja columnas impredecibles. 96 px es
                        # el fid de 8 digitos a 12 px mas su casilla, como en 01.4; una
                        # variable con nombre largo pide su propio ancho.
                        layout=widgets.Layout(width=self._ancho_casilla,
                                              margin="0 8px 0 0"),
                    )
                    for etiqueta, clave in _pares_de_opciones(opciones)
                }
                for caja in self.casillas.values():
                    caja.observe(self._al_cambiar_casilla, names="value")
                self.caja.children = tuple(self.casillas.values())
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
                self.casillas = {}
                cajas = []
                for titulo_columna, opciones in columnas:
                    de_la_columna = []
                    for etiqueta, clave in _pares_de_opciones(opciones):
                        caja = widgets.Checkbox(
                            value=False, description=etiqueta, indent=False,
                            layout=widgets.Layout(width=self._ancho_casilla,
                                                  margin="0 0 0 0"),
                        )
                        caja.observe(self._al_cambiar_casilla, names="value")
                        self.casillas[clave] = caja
                        de_la_columna.append(caja)
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
