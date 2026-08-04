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
                     ancho_casilla="96px", **kwargs):
            super().__init__(**kwargs)
            self.casillas = {}
            self._silencio = False
            self._ancho_casilla = ancho_casilla
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

        def marcar_todos(self):
            """01.4's "Marcar todos" button."""
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
                for caja in self.casillas.values():
                    caja.value = marcado
            finally:
                self._silencio = False
            self.value = tuple(
                clave for clave, caja in self.casillas.items() if caja.value
            )

        def alternar(self, clave):
            """The map-click entry point. Flips the checkbox and lets its own
            handler recompute `value`, so a click and a tick cannot diverge.
            An unknown key -- the circuit's geometry has tramos that never had
            an event -- is ignored, never turned into a phantom checkbox."""
            caja = self.casillas.get(str(clave))
            if caja is None:
                return
            caja.value = not caja.value

        def _al_cambiar_casilla(self, _cambio):
            if self._silencio:
                return
            # Derived from the checkboxes, never accumulated separately: the
            # checkboxes ARE the state. Order follows the option list so the
            # legend and the ranking do not reshuffle between repaints.
            self.value = tuple(
                clave for clave, caja in self.casillas.items() if caja.value
            )

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
