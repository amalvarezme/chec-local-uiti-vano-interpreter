"""La simulacion del tablero tiene que TENDER A BAJAR el UITI, y no mentir sobre ello.

Tres defectos medidos sobre el tablero de verdad, los tres invisibles desde el
codigo fuente porque los tres viven en el estado de los widgets:

1. **Costear borraba la obra.** `item_selector_widget` esta observado por
   `_reconstruir_controles_knob`, asi que marcar una actividad del contrato rehacia
   la rejilla entera y reabria cada control en el valor OBSERVADO. Lo aplicado se
   perdia y el aviso verde seguia diciendo que estaba puesto. La corrida que se
   publico en el sitio simulo los tres vanos SIN TOCAR: su UITI simulado (359,08)
   era exactamente el `u_base` del modelo.
2. **Los optimos marginales no componen.** El ranking calcula, para cada variable
   por separado, el valor que minimiza el u-hat con las DEMAS en su valor observado.
   Aplicarlas todas a la vez simula un punto que nadie evaluo. Medido en
   AGU23L12/V11: 359,07 base, 137,13 con los marginales y 86,25 con el plan goloso.
3. **Un resultado que empeora no se declaraba.** El titulo compara lo MEDIDO contra
   lo simulado -- dos cantidades de naturaleza distinta -- asi que el desfase del
   modelo se leia como el efecto de la obra. Que la obra empeore el vano es
   legitimo; publicarlo sin decirlo, no.

Se conducen los WIDGETS y no el navegador: un `on_click` de ipywidgets se dispara
desde Python, ahorra los ~700 MB del kernel de Voila y separa "el boton no hace lo
que dice" de "el navegador no habla con el kernel".
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PAQUETE = RAIZ / "aplicaciones" / "06_simulador" / "paquete"

#: La escena de las figuras publicadas: tres vanos de Medio-Alto en la ultima ventana.
CIRCUITO = "AGU23L12"


def _falta_el_paquete() -> str | None:
    for pieza in ("manifiesto.json", "tabla.parquet", "X_inst.npy",
                  "mil_vano_ventana_v1.pt", "geo.json"):
        if not (PAQUETE / pieza).is_file():
            return f"el paquete del simulador no esta construido (falta {pieza})"
    return None


pytestmark = pytest.mark.skipif(_falta_el_paquete() is not None,
                                reason=_falta_el_paquete() or "")


def _caminar(widget, vistos=None):
    vistos = set() if vistos is None else vistos
    if id(widget) in vistos:
        return
    vistos.add(id(widget))
    yield widget
    for hijo in getattr(widget, "children", ()) or ():
        yield from _caminar(hijo, vistos)


def _pulsar(boton):
    for callback in boton._click_handlers.callbacks:
        callback(boton)


def _correr_pendientes():
    bucle = asyncio.get_event_loop()
    tareas = list(asyncio.all_tasks(bucle))
    if tareas:
        bucle.run_until_complete(asyncio.gather(*tareas))


class _Tablero:
    def __init__(self, app):
        import ipywidgets as widgets

        self.app = app
        piezas = list(_caminar(app))
        self.botones = {b.description: b for b in piezas
                        if isinstance(b, widgets.Button)}
        self.circuito = next(d for d in piezas if isinstance(d, widgets.Dropdown)
                             and d.description == "Circuito")
        self.ventana = next(s for s in piezas
                            if isinstance(s, widgets.SelectionSlider))
        selectores = [s for s in piezas if type(s).__name__ == "SelectorCasillas"]
        self.vanos, self.knobs, self.items = selectores[0], selectores[1], selectores[2]
        self.guardadas = next(d for d in piezas if isinstance(d, widgets.Dropdown)
                              and d is not self.circuito and d.description == ""
                              and d.layout.width == "330px")

    def controles(self):
        """`{fid: {knob_id: valor}}` de la rejilla, tal y como la lee `Simular`.

        Se vuelve a recorrer el arbol en cada llamada a proposito: la rejilla se
        REHACE entera en cada cambio de seleccion, asi que una referencia guardada
        apuntaria a los widgets de la version anterior -- que es justo el defecto.
        """
        return self.app.estado_del_panel()['valores']

    def avisos(self):
        import ipywidgets as widgets

        return " ".join(h.value or "" for h in _caminar(self.app)
                        if isinstance(h, widgets.HTML))


@pytest.fixture(scope="module")
def tablero(tmp_path_factory):
    os.environ["SIMULACIONES_LOCAL"] = str(tmp_path_factory.mktemp("simulaciones"))
    os.environ["RUTA_VARIABLES_SIMULAR"] = str(PAQUETE / "Variables_simular.xlsx")
    from chec_tableros.simulador import derivacion
    from chec_tableros.simulador import tablero as modulo

    app = modulo.construir(
        derivacion.cargar(PAQUETE),
        costos=PAQUETE / "Actividades_mantenimiento_costos_2026.xlsx",
        variables_seleccion=RAIZ / "data" / "Variables_seleccion.xlsx",
    )
    t = _Tablero(app)
    t.circuito.value = CIRCUITO
    t.ventana.value = max(t.ventana.options, key=lambda o: o[1])[1] \
        if isinstance(t.ventana.options[0], tuple) else t.ventana.options[-1]
    _correr_pendientes()
    return t


def _diagnosticar_y_aplicar(tablero):
    _pulsar(tablero.botones["Desmarcar"])
    _pulsar(tablero.botones["G. Medio-Alto"])
    _correr_pendientes()
    assert tablero.vanos.value, f"{CIRCUITO} no tiene vanos Medio-Alto en esta ventana"
    _pulsar(tablero.botones["Diagnostico"])
    _correr_pendientes()
    _pulsar(tablero.botones["Aplicar intervencion sugerida"])
    _correr_pendientes()


# --- 1. Costear no puede borrar la obra --------------------------------------------------


def test_marcar_una_actividad_conserva_los_valores_aplicados(tablero):
    """Marcar una actividad del contrato NO puede deshacer la intervencion aplicada.

    Es la mitad de abajo de la misma columna: arriba que se le mueve al vano, abajo
    que obra se le cotiza. Que la segunda borre la primera deja al usuario costeando
    una obra y simulando el vano intacto, sin nada en pantalla que lo diga.
    """
    _diagnosticar_y_aplicar(tablero)
    antes = tablero.controles()
    assert antes, "la rejilla abrio vacia"

    tablero.items.value = tuple(list(tablero.items.casillas)[:1])
    _correr_pendientes()

    despues = tablero.controles()
    for fid, valores in antes.items():
        assert fid in despues, f"el vano {fid} perdio su columna al costear"
        for knob_id, valor in valores.items():
            assert despues[fid][knob_id] == valor, (
                f"{fid}/{knob_id}: costear lo devolvio de {valor!r} a "
                f"{despues[fid][knob_id]!r}")


# --- 2. Lo aplicado tiene que bajar el UITI ----------------------------------------------


def test_aplicar_la_intervencion_no_puede_subir_el_uiti_del_modelo(tablero):
    """El u-hat simulado no puede quedar por ENCIMA del u-hat base.

    Es el contrato del boton: aplicar la intervencion sugerida existe para bajar el
    UITI, y un valor sugerido que lo sube no es una sugerencia. La comparacion es
    modelo contra modelo -- `u_base` contra `u_simulado` de la misma bolsa -- y no
    medido contra simulado, que mezcla el desfase de nivel del modelo con el efecto
    de la obra.
    """
    _diagnosticar_y_aplicar(tablero)
    _pulsar(tablero.botones["Simular"])
    _correr_pendientes()

    tabla = tablero.app.estado_del_panel()['ultima_simulacion']
    assert tabla is not None and len(tabla), "la simulacion no dejo resultado"
    base = float(tabla["u_base"].sum())
    simulado = float(tabla["u_simulado"].sum())
    assert simulado <= base, (
        f"aplicar la intervencion SUBIO el UITI del modelo: {base:,.3f} -> "
        f"{simulado:,.3f}")


# --- 3. Y si sube, hay que decirlo -------------------------------------------------------


def test_el_panel_declara_si_la_obra_simulada_empeora_el_vano(tablero):
    """El panel tiene que publicar el contraste modelo-contra-modelo, en palabras.

    El titulo de las barras compara lo MEDIDO contra lo simulado, y esas dos son de
    naturaleza distinta: el desfase de nivel del modelo -- que en estos datos es del
    orden del propio cambio y cambia de signo con el circuito -- se leia como el
    efecto de la obra. Hace falta una frase que diga que hizo la obra SEGUN EL
    MODELO, que es la unica comparacion limpia que hay.
    """
    _diagnosticar_y_aplicar(tablero)
    _pulsar(tablero.botones["Simular"])
    _correr_pendientes()

    avisos = tablero.avisos().lower()
    assert "según el modelo" in avisos, (
        "el panel no publica el contraste modelo contra modelo")
    # Y con una cifra a cada lado, no solo la frase: "segun el modelo baja" sin los dos
    # numeros no deja comprobar nada.
    tabla = tablero.app.estado_del_panel()["ultima_simulacion"]
    assert f"{float(tabla['u_base'].sum()):,.1f}".lower() in avisos


# --- 4. Cada boton trae SOLO su mitad ----------------------------------------------------


def test_cada_boton_fija_solo_variables_de_su_mitad(tablero):
    """Un clic en intervencion deja EXACTAMENTE variables de intervencion.

    `test_simulador_015_caja_seleccion.py` fija el MECANISMO leyendo la fuente; esto
    comprueba el resultado sobre el tablero construido, que es donde se ve si la
    mitad aplicada es de verdad la del boton. Si quedaran ademas las de escenario de
    una vuelta anterior, la simulacion mezclaria obra y clima y no se sabria cual de
    los dos movio el UITI.
    """
    from chec_local_interpreter.simulador_variables import (
        catalogo_simulacion, grupo_por_knob)

    grupo = grupo_por_knob(catalogo_simulacion())
    _diagnosticar_y_aplicar(tablero)

    fijados = tablero.app.estado_del_panel()["fijados"]
    movidos = {k for vals in fijados.values() for k in vals}
    assert movidos, "el plan de intervencion no fijo ni un control"
    assert all(grupo.get(k) == "Intervencion" for k in movidos), (
        f"la mitad de intervencion trajo variables de otra: {sorted(movidos)}")

    # Y los dos botones juntos SI suman: presionar los dos es una decision del usuario.
    _pulsar(tablero.botones["Aplicar escenario sugerido"])
    _correr_pendientes()
    fijados = tablero.app.estado_del_panel()["fijados"]
    grupos = {grupo.get(k) for vals in fijados.values() for k in vals}
    assert "Escenario" in grupos, "el segundo boton no trajo su mitad"


# --- 5. Lo fijado no puede sobrevivir a un cambio de ventana -----------------------------


def test_cambiar_de_ventana_suelta_los_valores_fijados(tablero):
    """Un valor fijado describe UNA ventana, y al moverla deja de corresponder.

    Es la contrapartida de que lo aplicado sobreviva a la rejilla: el mismo
    diccionario que salva la obra de un reconstruido tiene que soltarla cuando el
    diagnostico que la produjo ya no describe la seleccion. El valor inicial de cada
    control es el del vano EN ESA VENTANA, asi que arrastrarlo mostraria el de otra
    -- y la simulacion correria sobre un valor que nadie eligio para esta.
    """
    _diagnosticar_y_aplicar(tablero)
    assert tablero.app.estado_del_panel()["fijados"], "no quedo nada fijado"

    ventanas = [v for _r, v in tablero.ventana.options] \
        if isinstance(tablero.ventana.options[0], tuple) else list(tablero.ventana.options)
    fijados_antes = tablero.app.estado_del_panel()["fijados"]
    otra = next(v for v in ventanas if v != tablero.ventana.value)
    tablero.ventana.value = otra
    _correr_pendientes()

    assert not tablero.app.estado_del_panel()["fijados"], (
        "los valores de la ventana anterior siguen fijados")

    del fijados_antes


def test_un_vano_de_dos_ventanas_no_arrastra_el_valor_de_la_otra(tablero):
    """El caso que la poda por vanos marcados NO cubre, y por el que hace falta atar
    lo fijado a su ventana.

    Soltar lo fijado quitando los vanos que ya no estan marcados basta mientras el
    cambio de ventana los cambie a todos. Un vano con celda en las DOS sigue marcado
    -- V10 y V11 de AGU23L12 comparten ocho --, y para el el valor de la ventana
    anterior sobrevivia: se simulaba con lo que se decidio para otra, sin nada en
    pantalla que lo distinguiera de su valor observado.

    Se edita a mano y no con el diagnostico, porque una edicion a mano tambien se
    recuerda y ademas deja el caso independiente de que el plan elija ese control.
    """
    etiqueta = {str(r): v for r, v in tablero.ventana.options} \
        if isinstance(tablero.ventana.options[0], tuple) else {}
    v10 = next(v for r, v in etiqueta.items() if "V10" in r)
    v11 = next(v for r, v in etiqueta.items() if "V11" in r)

    tablero.ventana.value = v10
    _correr_pendientes()
    compartidos = ["20130439", "20130454", "20130455", "20130456"]
    tablero.vanos.value = tuple(compartidos)
    tablero.knobs.value = ("CONDUCTOR",)
    _correr_pendientes()

    columnas = tablero.app.estado_del_panel()["valores"]
    fid = next(f for f in compartidos if f in columnas)
    control = next(c for c in _caminar(tablero.app)
                   if getattr(c, "options", None) and "CONDUCTOR" in str(getattr(c, "description", "")))
    otro = next(o for o in control.options if o != control.value)
    control.value = otro
    _correr_pendientes()
    assert tablero.app.estado_del_panel()["fijados"].get(fid, {}).get("CONDUCTOR") == otro

    tablero.ventana.value = v11
    _correr_pendientes()
    assert not tablero.app.estado_del_panel()["fijados"], (
        "el valor puesto en V10 sigue fijado despues de pasar a V11")


# --- 6. El total del circuito tiene que ser una SUMA de verdad ---------------------------


def test_la_barra_del_circuito_entero_suma_los_vanos_de_la_ventana(tablero):
    """`TODOS los vanos` no es un adorno: es la suma que dice cuanto pesa la obra.

    `barras_uiti_por_vano` esta probada como unidad, pero lo que ninguna prueba de esa
    funcion pura puede ver es el CABLEADO: que el tablero le pase el total del circuito
    en la ventana activa -- todos sus vanos con celda, no solo los marcados -- y los
    observados de los vanos que de verdad simulo. Un total armado sobre el conjunto
    equivocado sigue dibujando dos barras crecibles.

    Se comprueba contra la tabla del paquete, que es la fuente, y no contra otra cuenta
    del propio tablero.
    """
    import pandas as pd

    _diagnosticar_y_aplicar(tablero)
    _pulsar(tablero.botones["Simular"])
    _correr_pendientes()

    estado = tablero.app.estado_del_panel()
    barras = estado["ultima_corrida"]["barras"]
    tabla = estado["ultima_simulacion"]

    ventana = [r for r, v in tablero.ventana.options if v == tablero.ventana.value][0]
    etiqueta = ventana.split(":")[0].strip()
    celdas = pd.read_parquet(PAQUETE / "tabla.parquet")
    celdas = celdas[(celdas["CIRCUITO"].astype(str) == CIRCUITO)
                    & (celdas["ventana"] == etiqueta)]
    assert len(celdas), f"{CIRCUITO}/{etiqueta} no tiene celdas en la tabla"

    # La barra izquierda: el UITI medido de TODOS los vanos con celda en la ventana.
    assert barras["observado"][-1] == pytest.approx(float(celdas["uiti_acumulado"].sum()))

    # La derecha: los no simulados se quedan como estan y los simulados aportan lo suyo.
    simulados = {str(f) for f in tabla["FID_VANO"]}
    quietos = float(celdas[~celdas["FID_VANO"].astype(str).isin(simulados)]
                    ["uiti_acumulado"].sum())
    assert barras["simulado"][-1] == pytest.approx(quietos + sum(barras["simulado"][:-1]))

    # Y la cabecera es la diferencia de las dos, sobre los simulados.
    assert barras["reduccion"] == pytest.approx(
        sum(barras["observado"][:-1]) - sum(barras["simulado"][:-1]))


# --- 7. Guardar y cargar sigue siendo consistente ----------------------------------------


def test_el_ciclo_guardar_cargar_repone_el_plan_y_lo_conserva_al_costear(tablero):
    """Lo que se archiva y se repone es el PLAN, y sobrevive a seguir trabajando.

    Guardar y cargar ya tenian su ciclo probado, pero sobre una escena montada a mano.
    Lo que cambia aqui es de donde salen los valores -- el plan -- y que ahora existe
    un estado aparte de los widgets. Dos cosas que hay que comprobar juntas:

    1. el registro archiva EXACTAMENTE los valores que el plan fijo, y cargarlo los
       devuelve a los mismos controles;
    2. despues de cargar, marcar una actividad del contrato NO los borra. Es el mismo
       defecto que se arreglo para el camino de aplicar, y el de cargar escribe en los
       controles por su propia via -- `_escribir_en_control` --, asi que podria haber
       quedado fuera del arreglo.
    """
    import gzip
    import json

    _diagnosticar_y_aplicar(tablero)
    _pulsar(tablero.botones["Simular"])
    _correr_pendientes()
    puesto = {fid: dict(vals)
              for fid, vals in tablero.app.estado_del_panel()["fijados"].items()}
    assert puesto, "el plan no fijo nada que archivar"

    _pulsar(tablero.botones["Guardar"])
    carpeta = Path(os.environ["SIMULACIONES_LOCAL"])
    registros = sorted(carpeta.glob("*.simchec.json.gz"))
    assert registros, "Guardar no escribio el registro"
    guardado = json.loads(gzip.decompress(registros[-1].read_bytes()).decode("utf-8"))
    del_registro = {}
    for fila in guardado["variables"]:
        del_registro.setdefault(str(fila["vano"]), {})[fila["knob_id"]] = fila["valor"]
    assert del_registro == puesto, "el registro no archiva lo que el plan fijo"

    # Se ensucia el panel antes de cargar, para que reponer tenga algo que deshacer.
    _pulsar(tablero.botones["Limpiar"])
    _correr_pendientes()
    assert not tablero.app.estado_del_panel()["fijados"]

    tablero.guardadas.value = registros[-1].name
    _pulsar(tablero.botones["Cargar"])
    _correr_pendientes()
    assert tablero.app.estado_del_panel()["valores"] == puesto, (
        "cargar no repuso los valores del plan")

    # Y ahora lo que antes los borraba.
    tablero.items.value = tuple(list(tablero.items.casillas)[:2])
    _correr_pendientes()
    en_pantalla = tablero.app.estado_del_panel()["valores"]
    for fid, vals in puesto.items():
        for knob_id, valor in vals.items():
            assert en_pantalla[fid][knob_id] == valor, (
                f"{fid}/{knob_id}: costear tras cargar lo devolvio a "
                f"{en_pantalla[fid][knob_id]!r}")
