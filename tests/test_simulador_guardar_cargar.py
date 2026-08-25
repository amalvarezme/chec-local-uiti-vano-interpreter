"""El ciclo guardar -> limpiar -> cargar, sobre el tablero DE VERDAD.

No es una prueba de texto sobre `tablero.py`. Construye el tablero con el paquete
congelado de la aplicacion, pulsa los botones y mira lo que queda en los widgets.
Cuesta ~7 s y se salta sola donde el paquete no esta construido, y ese precio se
paga porque el defecto que motivo el modulo no se ve de ninguna otra forma:

`ipywidgets` 8.1.8 **no selecciona la primera opcion cuando un `Dropdown` pasa de
la lista VACIA a una poblada** -- `index` se queda en `None` -- mientras que
repoblar una lista que ya tenia opciones SI reinicia el indice a 0. El desplegable
de simulaciones nace vacio, asi que la primera simulacion guardada de la sesion
aparecia en la lista y "Cargar" contestaba *"elige una simulación"*. Ninguna
prueba sobre el codigo fuente ve eso: la linea que faltaba no existia.

Lo que se conduce aqui son los widgets, no el navegador. Un `on_click` de
ipywidgets se dispara desde Python, y eso ahorra los ~700 MB del kernel de Voila y
separa "el boton no hace lo que dice" de "el navegador no habla con el kernel",
que es lo que cubre `test_simulador_flujo_vivo.py`.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PAQUETE = RAIZ / "aplicaciones" / "06_simulador" / "paquete"


def _falta_el_paquete() -> str | None:
    for pieza in ("manifiesto.json", "tabla.parquet", "X_inst.npy",
                  "mil_vano_ventana_v1.pt", "geo.json"):
        if not (PAQUETE / pieza).is_file():
            return f"el paquete del simulador no esta construido (falta {pieza})"
    return None


pytestmark = pytest.mark.skipif(_falta_el_paquete() is not None,
                                reason=_falta_el_paquete() or "")


# --------------------------------------------------------------------- el arnes


def _caminar(widget, vistos=None):
    """Todos los widgets del arbol, sin repetir. Los `Box` de ipywidgets pueden
    compartir hijos, y sin el conjunto de vistos el recorrido se dobla."""
    vistos = set() if vistos is None else vistos
    if id(widget) in vistos:
        return
    vistos.add(id(widget))
    yield widget
    for hijo in getattr(widget, "children", ()) or ():
        yield from _caminar(hijo, vistos)


def _pulsar(boton):
    """Dispara el `on_click` como lo haria el navegador."""
    for callback in boton._click_handlers.callbacks:
        callback(boton)


def _correr_pendientes():
    """`Simular` no corre en el clic: deja una corutina con `DEBOUNCE_SEGUNDOS` de
    rebote. Sin vaciar el bucle, la prueba miraria el tablero antes de que el modelo
    hubiera contestado -- que es exactamente el falso negativo que hace parecer que
    `Simular` no funciona fuera del navegador."""
    bucle = asyncio.get_event_loop()
    tareas = list(asyncio.all_tasks(bucle))
    if tareas:
        bucle.run_until_complete(asyncio.gather(*tareas))


class _Tablero:
    """El tablero construido, con sus piezas ya localizadas."""

    def __init__(self, app):
        import ipywidgets as widgets

        self.app = app
        self.piezas = list(_caminar(app))
        self.botones = {b.description: b for b in self.piezas
                        if isinstance(b, widgets.Button)}
        self.circuito = next(d for d in self.piezas
                             if isinstance(d, widgets.Dropdown)
                             and d.description == "Circuito")
        self.ventana = next(s for s in self.piezas
                            if isinstance(s, widgets.SelectionSlider))
        selectores = [s for s in self.piezas
                      if type(s).__name__ == "SelectorCasillas"]
        self.vanos, self.knobs, self.items = selectores[0], selectores[1], selectores[2]
        self.guardadas = next(
            d for d in self.piezas
            if isinstance(d, widgets.Dropdown) and d is not self.circuito
            and d.description == "" and d.layout.width == "330px")

    def repeticiones(self):
        """Los desplegables de "cuantas veces va esta actividad en este vano". Se
        reconocen por su primera opcion y no por su posicion: la rejilla se rehace
        entera en cada cambio de seleccion."""
        import ipywidgets as widgets

        return [d for d in _caminar(self.app)
                if isinstance(d, widgets.Dropdown)
                and list(getattr(d, "options", ())) and d.options[0] == ("0", 0)]

    def avisos(self):
        import ipywidgets as widgets

        return " ".join(h.value or "" for h in _caminar(self.app)
                        if isinstance(h, widgets.HTML))


@pytest.fixture(scope="module")
def carpeta(tmp_path_factory):
    return tmp_path_factory.mktemp("simulaciones")


@pytest.fixture(scope="module")
def tablero(carpeta):
    """UN solo tablero para todo el modulo: construirlo cuesta ~5 s y las pruebas de
    abajo son los pasos SUCESIVOS de un mismo ciclo, no casos independientes."""
    os.environ["SIMULACIONES_LOCAL"] = str(carpeta)
    os.environ["RUTA_VARIABLES_SIMULAR"] = str(PAQUETE / "Variables_simular.xlsx")
    from chec_tableros.simulador import derivacion
    from chec_tableros.simulador import tablero as modulo

    app = modulo.construir(
        derivacion.cargar(PAQUETE),
        costos=PAQUETE / "Actividades_mantenimiento_costos_2026.xlsx",
        variables_seleccion=RAIZ / "data" / "Variables_seleccion.xlsx",
    )
    return _Tablero(app)


# ------------------------------------------------------------- los botones existen


def test_el_panel_ofrece_guardar_y_cargar(tablero):
    assert "Guardar" in tablero.botones
    assert "Cargar" in tablero.botones
    assert "Actualizar lista" in tablero.botones


def test_guardar_arranca_deshabilitado(tablero):
    """Guardar antes de simular escribiria un informe de un tablero vacio. Un boton
    deshabilitado con su `tooltip` lo dice antes del clic; uno que acepta el clic y
    contesta "primero simula" gasta el viaje."""
    assert tablero.botones["Guardar"].disabled


def test_cargar_arranca_deshabilitado_con_la_carpeta_vacia(tablero):
    assert tablero.botones["Cargar"].disabled


# --------------------------------------------------------------- guardar de verdad


# Va DESPUES de las tres de arriba y depende de ello: comparte el tablero del modulo
# y lo deja simulado. pytest ejecuta en orden de definicion dentro de un archivo, que
# es la garantia que esto usa -- no hay `pytest-order` en el proyecto y meterlo por
# una prueba seria una dependencia por un problema que el orden del archivo ya resuelve.
def test_el_ciclo_completo_guarda_repone_y_vuelve_a_simular(tablero, carpeta):
    """Un solo caso y no seis, a proposito: son los pasos de UN ciclo y cada uno
    depende del estado que dejo el anterior. Partirlos en pruebas independientes
    obligaria a reconstruir el tablero seis veces -- 30 s -- o a un orden implicito
    entre pruebas, que es peor que un caso largo y honesto."""
    import ipywidgets as widgets

    # --- se monta un escenario: variables y actividades sobre los vanos marcados ---
    # Los 15 vanos que el tablero automarca son los de mayor UITI de la ventana, o
    # sea los que SI tienen bolsas. Recortarlos al azar deja la seleccion sin nada
    # que puntuar la mitad de las veces, y la prueba fallaria por eso y no por el
    # ciclo de guardado.
    assert tablero.vanos.value, "el tablero abre sin vanos marcados"
    tablero.knobs.value = tuple(list(tablero.knobs.casillas)[:3])
    tablero.items.value = tuple(list(tablero.items.casillas)[:2])
    repeticiones = tablero.repeticiones()
    assert repeticiones, "la rejilla no abrio filas de actividad"
    for i, control in enumerate(repeticiones):
        control.value = 1 + i % 3
    puestas = [c.value for c in repeticiones]

    # --- simular ------------------------------------------------------------------
    _pulsar(tablero.botones["Simular"])
    _correr_pendientes()
    assert not tablero.botones["Guardar"].disabled, (
        "Guardar sigue deshabilitado despues de simular")

    # --- guardar ------------------------------------------------------------------
    _pulsar(tablero.botones["Guardar"])
    registros = [p for p in carpeta.iterdir() if p.name.endswith(".simchec.json.gz")]
    informes = [p for p in carpeta.iterdir() if p.name.endswith(".html")]
    assert len(registros) == 1 and len(informes) == 1
    assert registros[0].name[: -len(".simchec.json.gz")] == informes[0].stem, (
        "el registro y su informe tienen que compartir nombre base")

    registro = json.loads(gzip.decompress(registros[0].read_bytes()).decode("utf-8"))
    assert registro["seleccion"]["circuito"] == tablero.circuito.value
    assert registro["seleccion"]["ventana_i"] == tablero.ventana.value
    assert registro["variables"], "no se guardo ninguna variable del panel"
    assert registro["actividades"], "no se guardo ninguna actividad del contrato"
    assert registro["uiti"], "no se guardo el contraste de UITI"
    # El informe es un HTML completo con las figuras dentro, no un esqueleto.
    texto = informes[0].read_text("utf-8")
    assert texto.lstrip().lower().startswith("<!doctype html>")
    assert "Vanos y variables simuladas" in texto
    assert "Actividades de contrato por vano" in texto
    assert "UITI medido contra UITI simulado" in texto
    assert "plotly" in texto.lower(), "las figuras no viajaron dentro del informe"
    # El registro es lo que justifica el formato: kilobytes contra los megabytes del
    # informe. Si algun dia empieza a llevar las figuras, esta linea lo dice.
    assert registros[0].stat().st_size < 64 * 1024
    assert informes[0].stat().st_size > registros[0].stat().st_size

    # --- la trampa de ipywidgets --------------------------------------------------
    # Con la lista recien poblada desde VACIA, `value` se quedaba en `None` y
    # "Cargar" contestaba "elige una simulación" sobre un desplegable que mostraba
    # una. Se comprueba el `value`, no la longitud de las opciones.
    assert tablero.guardadas.value == registros[0].name

    # --- limpiar ------------------------------------------------------------------
    _pulsar(tablero.botones["Limpiar"])
    _correr_pendientes()
    assert tablero.vanos.value == ()
    assert tablero.knobs.value == ()
    assert tablero.botones["Guardar"].disabled, (
        "Limpiar tiene que soltar tambien la corrida guardable")
    # La LISTA de guardadas describe el disco, no la corrida: limpiar el tablero no
    # puede vaciarla.
    assert not tablero.botones["Cargar"].disabled

    # --- cargar -------------------------------------------------------------------
    _pulsar(tablero.botones["Cargar"])
    _correr_pendientes()
    assert sorted(tablero.vanos.value) == sorted(registro["seleccion"]["vanos"])
    assert set(tablero.knobs.value) == {v["knob_id"] for v in registro["variables"]}
    assert set(tablero.items.value) == {a["actividad"] for a in registro["actividades"]}
    assert [c.value for c in tablero.repeticiones()] == puestas, (
        "las repeticiones por actividad no volvieron como se guardaron")
    assert "Simulación cargada" in tablero.avisos()


# -------------------------------------------------- el contrato de ipywidgets

def test_un_dropdown_de_ipywidgets_no_se_autoselecciona_al_salir_de_vacio():
    """Fija la asimetria que obliga a escribir `index` a mano en el tablero.

    Si una version futura de ipywidgets la corrige, ESTA prueba se pone roja y dice
    que la linea del tablero ya no hace falta -- que es mejor que dejarla ahi para
    siempre sin que nadie recuerde contra que protegia.
    """
    import ipywidgets as widgets

    desde_vacio = widgets.Dropdown(options=[])
    desde_vacio.options = [("rotulo", "clave")]
    assert desde_vacio.value is None, (
        "ipywidgets ya autoselecciona al salir de vacio: revisa `_refrescar_guardadas`")

    repoblado = widgets.Dropdown(options=[("a", "A"), ("b", "B")])
    repoblado.value = "B"
    repoblado.options = [("a", "A"), ("b", "B"), ("c", "C")]
    assert repoblado.value == "A", (
        "ipywidgets ya conserva el valor al repoblar: revisa `_refrescar_guardadas`")


# ------------------------------------------ el panel y el informe dicen lo mismo


def test_el_titulo_del_panel_no_publica_una_bajada_negativa():
    """`reduccion` es `medido - simulado` y sale NEGATIVA cuando el escenario empeora
    esos vanos. El titulo decia "baja -59,4", que se lee como una errata y esconde el
    desenlace. El informe que escribe "Guardar" ya elige el verbo por el signo, y
    tenerlos distintos haria que el panel y el archivo de la MISMA corrida dijeran
    cosas distintas.

    Es una prueba sobre el codigo fuente y no sobre el tablero vivo porque
    `_titulo_de_barras` es un cierre dentro de `construir()`: no hay forma de llamarlo
    desde fuera sin extraerlo, y extraerlo por una prueba moveria una funcion que solo
    ese panel usa.
    """
    fuente = (RAIZ / "src" / "chec_tableros" / "simulador" / "tablero.py").read_text("utf-8")
    cuerpo = fuente[fuente.index("def _titulo_de_barras"):]
    cuerpo = cuerpo[: cuerpo.index("\n    def ")]
    assert "abs(" in cuerpo, "el titulo sigue publicando el numero con su signo"
    assert "'sube'" in cuerpo or '"sube"' in cuerpo, (
        "el titulo no tiene verbo para el caso en que la simulacion empeora")
