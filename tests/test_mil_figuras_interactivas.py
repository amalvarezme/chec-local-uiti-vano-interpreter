"""Los tres paneles del informe, en Plotly y con el estilo del tablero del 06.

El informe los dibujaba en matplotlib y los embebia como PNG. Son los MISMOS tres
paneles que el simulador presenta vivos -- el top de variables, el UITI medido contra
el simulado y el grafo de relaciones --, y tenerlos en dos librerias distintas cuesta
dos cosas: quien lee el informe y despues abre el tablero ve dos dibujos que hay que
reconciliar, y en el informe se pierde el hover, que es donde vive el nombre completo
de cada variable y el desglose de cada barra.

Se comparten las funciones PURAS con el tablero -- `plegar_rezagos`, `trazas_grafo`,
`barras_uiti_por_vano`, `rotacion_radial` -- para que la coincidencia no dependa de
que nadie toque una de las dos copias.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _relevancia():
    return {
        "vanos": {
            "V1": {
                "u_base": 9.0, "clase_base": 3,
                "variables": [
                    {"knob_id": "NR_T", "label": "Riesgo por vegetación",
                     "caida": 1.2, "u_min": 1.8, "u_base": 9.0,
                     "grupo": "Intervencion", "valor_optimo": 0.0, "alcanza": True},
                    {"knob_id": "ALTURA", "label": "Altura del apoyo",
                     "caida": 0.4, "u_min": 6.0, "u_base": 9.0,
                     "grupo": "Intervencion", "valor_optimo": 18.0, "alcanza": False},
                ],
            },
            "V2": {
                "u_base": 4.0, "clase_base": 2,
                "variables": [
                    {"knob_id": "CANTIDAD_TIERRA", "label": "Puesta a tierra",
                     "caida": 0.9, "u_min": 1.0, "u_base": 4.0,
                     "grupo": "Intervencion", "valor_optimo": 1.0, "alcanza": False},
                ],
            },
        }
    }


def _simulacion():
    return {
        "solo_intervencion": True,
        "vanos": [
            {"fid": "V1", "u_base": 9.0, "u_simulado": 2.0, "u_observado": 7.5,
             "clase_base": 3, "clase_simulada": 1, "delta_grupo": -2, "pasos": []},
            {"fid": "V2", "u_base": 4.0, "u_simulado": 3.0, "u_observado": 4.4,
             "clase_base": 2, "clase_simulada": 2, "delta_grupo": 0, "pasos": []},
        ],
        "grafo_diferencia": {"voided": False, "matriz": [[0.0, 0.5], [0.5, 0.0]]},
    }


# --- Top de variables ----------------------------------------------------------


def test_el_top_nombra_la_variable_con_su_codigo_de_columna():
    """La misma lectura del panel: el nombre en palabras para entender, el codigo de
    columna para cruzar con la tabla de vanos."""
    from chec_local_interpreter.mil_figuras_interactivas import figura_top_variables

    fig = figura_top_variables(_relevancia())

    texto = json.dumps(fig.to_plotly_json(), ensure_ascii=False)
    assert "NR_T" in texto
    assert "Riesgo por vegetación" in texto


def test_la_barra_que_sola_alcanza_el_grupo_bajo_va_en_verde():
    """Mismo verde y mismo significado que en el tablero: esa sola variable basta.

    Sin esta distincion el ranking se lee como una lista ordenada por magnitud, y la
    pregunta operativa -- cual me cambia de grupo por si sola -- se pierde.
    """
    from chec_local_interpreter.mil_figuras_interactivas import (
        COLOR_ALCANZA,
        figura_top_variables,
    )

    fig = figura_top_variables(_relevancia())

    colores = [c for traza in fig.data for c in (traza.marker.color or ())]
    assert COLOR_ALCANZA in colores, "ninguna barra marca que alcanza sola"


def test_una_relevancia_sin_vanos_no_produce_figura():
    """Una figura vacia se lee como que no hay nada que mover; el informe ya sabe
    callar el panel cuando no hay dato."""
    from chec_local_interpreter.mil_figuras_interactivas import figura_top_variables

    assert figura_top_variables({"vanos": {}}) is None


# --- UITI medido contra simulado -----------------------------------------------


def test_el_uiti_compara_lo_MEDIDO_con_lo_simulado():
    """Como el tablero: la barra base es el UITI que dice la base de datos, no la base
    del modelo.

    Son cantidades de naturaleza distinta -- una medicion contra una prediccion -- y por
    eso la simulada lleva barra de error con el desfase del modelo en la base de ESE
    vano. Usar la base del modelo en las dos esconderia ese sesgo, que sobre 599 bolsas
    corre +34%.
    """
    from chec_local_interpreter.mil_figuras_interactivas import (
        figura_uiti_medido_vs_simulado,
    )

    fig = figura_uiti_medido_vs_simulado(_simulacion())

    medida = next(t for t in fig.data if "medido" in (t.name or "").lower())
    assert list(medida.y)[:2] == [7.5, 4.4], "no uso el UITI observado"
    simulada = next(t for t in fig.data if "simulado" in (t.name or "").lower())
    assert list(simulada.error_y.array)[:2] == pytest.approx([1.5, 0.4]), (
        "la barra de error no es el desfase del modelo en la base")


def test_cada_barra_lleva_el_color_de_su_grupo_y_la_simulada_su_trama():
    """La misma decision que ya se tomo en el informe y en el tablero: el color dice el
    GRUPO y la trama separa la medicion de la prediccion."""
    from chec_local_interpreter.mil_figuras_interactivas import (
        COLORES_GRUPOS,
        figura_uiti_medido_vs_simulado,
    )

    fig = figura_uiti_medido_vs_simulado(_simulacion())

    medida = next(t for t in fig.data if "medido" in (t.name or "").lower())
    simulada = next(t for t in fig.data if "simulado" in (t.name or "").lower())
    assert list(medida.marker.color)[:2] == [COLORES_GRUPOS[3], COLORES_GRUPOS[2]]
    assert list(simulada.marker.color)[:2] == [COLORES_GRUPOS[1], COLORES_GRUPOS[2]]
    assert simulada.marker.pattern.shape, "la simulada no se distingue de la medida"


def test_sin_vanos_simulados_no_hay_figura_de_uiti():
    from chec_local_interpreter.mil_figuras_interactivas import (
        figura_uiti_medido_vs_simulado,
    )

    assert figura_uiti_medido_vs_simulado({"vanos": []}) is None


# --- El grafo de relaciones ----------------------------------------------------


def test_el_grafo_es_el_MISMO_anillo_que_el_del_tablero():
    """Se comparten `plegar_rezagos` y `trazas_grafo`: quien lea el informe y despues
    abra el tablero ve un solo dibujo, no dos que hay que reconciliar."""
    from chec_local_interpreter.mil_figuras import datos_grafo_radial
    from chec_local_interpreter.mil_figuras_interactivas import figura_grafo_relaciones

    grafo = {"voided": False, "matriz": [[0.0, 0.5], [0.5, 0.0]]}
    trazas, _ = datos_grafo_radial(grafo, ["A", "B"])
    fig, motivo = figura_grafo_relaciones(grafo, ["A", "B"])

    assert motivo == ""
    nodos = next(t for t in fig.data if t.mode and "markers" in t.mode)
    assert list(nodos.x) == pytest.approx(list(trazas["nodos"]["x"]))
    assert list(nodos.y) == pytest.approx(list(trazas["nodos"]["y"]))


def test_un_grafo_anulado_dice_por_que_en_vez_de_dibujar_un_anillo_vacio():
    from chec_local_interpreter.mil_figuras_interactivas import figura_grafo_relaciones

    fig, motivo = figura_grafo_relaciones({"voided": True, "matriz": None}, ["A"])

    assert fig is None
    assert motivo


def test_los_rotulos_del_anillo_no_se_leen_al_reves():
    """La misma `rotacion_radial` del tablero: en la mitad izquierda el rotulo se gira
    media vuelta para seguir leyendose de izquierda a derecha."""
    from chec_local_interpreter.mil_figuras_interactivas import figura_grafo_relaciones

    fig, _ = figura_grafo_relaciones(
        {"voided": False, "matriz": [[0.0, 0.5], [0.5, 0.0]]}, ["A", "B"])

    angulos = [a.textangle for a in fig.layout.annotations]
    assert angulos, "el anillo salio sin rotulos"
    assert all(-90.0 <= a <= 90.0 for a in angulos), angulos


# --- El sidecar: se guardan como JSON de Plotly, no como PNG --------------------


def test_las_figuras_se_guardan_como_json_de_plotly(tmp_path):
    """Y con ruta RELATIVA, igual que los PNG: el sidecar deja de ser portable si la
    carpeta se copia con rutas absolutas dentro."""
    from chec_local_interpreter.mil_figuras_interactivas import (
        figuras_interactivas_de_escenario,
    )

    escenario = {"ventana": "V9", "relevancia": _relevancia(),
                 "simulacion": _simulacion()}

    activos = figuras_interactivas_de_escenario(
        escenario, destino=tmp_path, features=["A", "B"])

    for clave in ("top_json", "uiti_json", "grafo_json"):
        assert activos[clave], f"falta {clave}"
        assert not Path(activos[clave]).is_absolute()
        ruta = tmp_path / activos[clave]
        assert ruta.suffix == ".json"
        assert json.loads(ruta.read_text(encoding="utf-8"))["data"]


def test_un_escenario_sin_simulacion_conserva_los_paneles_que_si_tiene(tmp_path):
    from chec_local_interpreter.mil_figuras_interactivas import (
        figuras_interactivas_de_escenario,
    )

    activos = figuras_interactivas_de_escenario(
        {"ventana": "V9", "relevancia": _relevancia(), "simulacion": {"vanos": []}},
        destino=tmp_path, features=[])

    assert activos["top_json"]
    assert activos["uiti_json"] is None


# --- La serie por ventana ------------------------------------------------------


def _series():
    return [
        {"fid": "V1", "w": ["V8", "V9", "V10"], "uv": [0.0, 9.0, 3.0], "n": [0, 4, 2],
         "clase": [0, 3, 1]},
        {"fid": "V2", "w": ["V8", "V9", "V10"], "uv": [1.0, 4.0, 0.0], "n": [1, 2, 0]},
    ]


def test_la_serie_dibuja_una_linea_por_vano_con_su_color():
    """El color identifica AL VANO y no a su grupo, igual que en el tablero: la misma
    paleta y en el mismo orden, para que un vano azul alli siga siendo azul aqui."""
    from chec_local_interpreter.mil_figuras_interactivas import (
        COLORES_VANOS,
        figura_series_por_ventana,
    )

    fig = figura_series_por_ventana(_series(), ventana_activa="V9")

    lineas = [t for t in fig.data if t.mode == "lines+markers" and t.yaxis != "y2"]
    assert len(lineas) == 2
    assert lineas[0].line.color == COLORES_VANOS[0]
    assert lineas[1].line.color == COLORES_VANOS[1]


def test_el_punto_de_la_ventana_del_escenario_va_al_triple():
    """Como el punto de la ventana vigente del tablero. Cada panel del informe habla de
    UNA ventana, y sin la marca el lector tiene que buscar en el eje cual es."""
    from chec_local_interpreter.mil_figuras_interactivas import (
        FACTOR_PUNTO_ACTIVO,
        SERIE_TAM_UITI,
        figura_series_por_ventana,
    )

    fig = figura_series_por_ventana(_series(), ventana_activa="V9")

    tamanos = list(next(t for t in fig.data if t.mode == "lines+markers").marker.size)
    assert tamanos == [SERIE_TAM_UITI, SERIE_TAM_UITI * FACTOR_PUNTO_ACTIVO,
                       SERIE_TAM_UITI]


def test_los_eventos_van_en_su_propio_eje_y_punteados():
    """UITI y numero de eventos no comparten unidad: en un solo eje, el que tenga la
    escala grande aplasta al otro. Punteado y con marcador cuadrado, como el tablero."""
    from chec_local_interpreter.mil_figuras_interactivas import figura_series_por_ventana

    fig = figura_series_por_ventana(_series(), ventana_activa="V9")

    eventos = [t for t in fig.data if t.yaxis == "y2"]
    assert len(eventos) == 2
    assert eventos[0].line.dash == "dot"
    assert eventos[0].marker.symbol == "square"


def test_el_marcador_toma_el_color_del_grupo_de_esa_celda():
    """La linea dice de que vano es; el relleno del punto, en que grupo cayo ESA ventana.
    Sin clase declarada va en gris neutro, no en el grupo mas bajo."""
    from chec_local_interpreter.mil_figuras_interactivas import (
        COLOR_SIN_GRUPO,
        COLORES_GRUPOS,
        figura_series_por_ventana,
    )

    fig = figura_series_por_ventana(_series(), ventana_activa="V9")

    lineas = [t for t in fig.data if t.mode == "lines+markers" and t.yaxis != "y2"]
    assert list(lineas[0].marker.color) == [COLORES_GRUPOS[0], COLORES_GRUPOS[3],
                                            COLORES_GRUPOS[1]]
    assert list(lineas[1].marker.color) == [COLOR_SIN_GRUPO] * 3


def test_la_segunda_vuelta_de_la_paleta_se_separa_por_el_trazo():
    """Mismo recurso que el tablero: con mas vanos que colores, el patron de la linea es
    el canal que queda libre. Inventar tonos nuevos daria pares indistinguibles."""
    from chec_local_interpreter.mil_figuras_interactivas import (
        COLORES_VANOS,
        figura_series_por_ventana,
    )

    muchas = [{"fid": f"V{i}", "w": ["V9"], "uv": [1.0], "n": [1]}
              for i in range(len(COLORES_VANOS) + 2)]

    # `max_vanos` explicito: por defecto son diez -- el mismo tope que tenia el panel en
    # matplotlib -- y con diez no se llega a dar la segunda vuelta a la paleta.
    fig = figura_series_por_ventana(muchas, ventana_activa="V9",
                                    max_vanos=len(muchas))

    lineas = [t for t in fig.data if t.mode == "lines+markers" and t.yaxis != "y2"]
    assert lineas[0].line.dash == "solid"
    assert lineas[len(COLORES_VANOS)].line.dash == "dash"
    assert lineas[len(COLORES_VANOS)].line.color == COLORES_VANOS[0]


def test_sin_series_no_hay_figura():
    from chec_local_interpreter.mil_figuras_interactivas import figura_series_por_ventana

    assert figura_series_por_ventana([], ventana_activa="V9") is None


def test_la_serie_tambien_se_guarda_como_json(tmp_path):
    from chec_local_interpreter.mil_figuras_interactivas import (
        figuras_interactivas_de_escenario,
    )

    activos = figuras_interactivas_de_escenario(
        {"ventana": "V9", "relevancia": _relevancia(), "simulacion": _simulacion()},
        destino=tmp_path, features=["A", "B"], series=_series())

    assert activos["serie_json"], "la serie sigue saliendo solo como PNG"
    assert (tmp_path / activos["serie_json"]).suffix == ".json"
