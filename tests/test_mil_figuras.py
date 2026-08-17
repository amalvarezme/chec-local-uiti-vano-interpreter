"""RED/GREEN tests for `mil_figuras`: the four panels the report shows per scenario.

The report used to carry SHAP bar/radar pairs. Those went with MGCECDL; what the MIL
model can actually show is different, and each panel answers a question the others
cannot:

- the window series of each identified vano — is this chronic or did it start last
  month? A vano seen only in the window where it turned critical cannot tell you;
- the relevance bars — which lever moves this vano, and how far;
- measured vs simulated UITI with the criticality group of each — a drop in UITI that
  does not change the group is not a work order;
- the difference graph — what the intervention moved in the reconstructed expert graph.
  The graph itself is mostly fixed expert weights, so before/after look identical side
  by side; only the difference isolates the effect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chec_local_interpreter.mil_figuras import figuras_de_escenario


def _escenario():
    return {
        "nombre": "C1 -- ventana V1",
        "circuito": "C1",
        "ventana": "V1",
        "relevancia": {
            "vanos": {
                "V2": {
                    "u_base": 3.0,
                    "clase_base": 3,
                    "variables": [
                        {"knob_id": "NR_T", "label": "NR_T", "caida": 1.2,
                         "u_min": 1.8, "u_base": 3.0, "grupo": "Intervencion"},
                        {"knob_id": "ALTURA", "label": "ALTURA", "caida": 0.4,
                         "u_min": 2.6, "u_base": 3.0, "grupo": "Intervencion"},
                    ],
                }
            }
        },
        "vanos_criticos": [{"fid": "V2", "clase_base": 3, "u_base": 3.0,
                            "u_final": 1.0, "clase_final": 1, "alcanza": False,
                            "pasos": [{"knob_id": "NR_T", "valor": 0.0}]}],
        "simulacion": {
            "solo_intervencion": True,
            "knobs_usados": ["NR_T"],
            "vanos": [{"fid": "V2", "u_base": 3.0, "u_simulado": 1.0,
                       "clase_base": 3, "clase_simulada": 1, "delta_grupo": -2,
                       "pasos": []}],
            "grafo_diferencia": {"voided": False,
                                 "matriz": [[0.0, 0.5], [0.5, 0.0]]},
        },
    }


def _series():
    return [{"fid": "V2", "w": ["V1", "V2", "V3"], "uv": [3.0, 0.0, 1.0],
             "n": [2, 0, 1]}]


def test_the_four_panels_are_written_as_png_files(tmp_path):
    activos = figuras_de_escenario(_escenario(), series=_series(), destino=tmp_path)

    esperadas = {"serie_png", "relevancia_png", "uiti_png", "grafo_png"}
    assert esperadas <= set(activos)
    for clave in esperadas:
        ruta = tmp_path / activos[clave]
        assert ruta.exists() and ruta.stat().st_size > 0, f"{clave} vacio"
        assert not Path(activos[clave]).is_absolute(), (
            f"{clave} tiene que ser relativo a run_dir, o el sidecar deja de ser portable"
        )


def test_a_voided_difference_graph_produces_no_panel_instead_of_an_empty_one(tmp_path):
    """El grafo se anula por diseño bajo tres vanos. Dibujar un panel vacio se lee
    como que la intervencion no movio nada, que es lo contrario de "no hay suficientes
    vanos para reconstruirlo"."""
    escenario = _escenario()
    escenario["simulacion"]["grafo_diferencia"] = {"voided": True, "matriz": None}

    activos = figuras_de_escenario(escenario, series=_series(), destino=tmp_path)

    assert activos.get("grafo_png") is None
    assert activos["grafo_motivo"], "tiene que decir POR QUE falta"


def test_a_scenario_with_no_simulated_vanos_still_draws_what_it_has(tmp_path):
    """Un circuito sin vanos criticos no tiene barras de UITI ni grafo, pero si serie
    y relevancia. Perder los cuatro paneles por falta de uno deja el informe sin la
    parte que si existe."""
    escenario = _escenario()
    escenario["vanos_criticos"] = []
    escenario["simulacion"] = {"solo_intervencion": True, "knobs_usados": [],
                               "vanos": [], "grafo_diferencia": None}

    activos = figuras_de_escenario(escenario, series=_series(), destino=tmp_path)

    assert activos["relevancia_png"] is not None
    assert activos["serie_png"] is not None
    assert activos.get("uiti_png") is None


# ---------------------------------------------------------------------------
# El grafo del informe es RADIAL, como el del simulador.
# ---------------------------------------------------------------------------


def _grafo_con_familias_de_rezagos():
    """Cuatro variables, dos de ellas familias de rezagos climaticos."""
    import numpy as np

    nombres = ["CONDUCTOR", "NR_T", "temp_0", "temp_1", "temp_2", "PREP_0", "PREP_1"]
    n = len(nombres)
    m = np.zeros((n, n))
    m[0, 2] = 0.9   # CONDUCTOR - temp_0
    m[1, 3] = 0.7   # NR_T      - temp_1
    m[0, 5] = 0.4   # CONDUCTOR - PREP_0
    m[2, 3] = 0.5   # temp_0    - temp_1  (DENTRO de la familia: se descarta al plegar)
    return {"voided": False, "matriz": m.tolist()}, nombres


def test_el_grafo_del_informe_pliega_las_familias_de_rezagos():
    """Sin plegar, los doce rezagos de cada variable de clima son 48 de los 66 nodos.

    Es la misma medida que gobierna el panel del simulador: con 64 aristas ese anillo
    es casi todo decoracion, 13,6 px de arco por nombre para una fuente de 10.
    """
    from chec_local_interpreter.mil_figuras import datos_grafo_radial

    grafo, nombres = _grafo_con_familias_de_rezagos()
    datos, motivo = datos_grafo_radial(grafo, nombres)

    assert motivo == ""
    etiquetas = datos["nodos"]["texto"]
    assert "temp" in etiquetas and "PREP" in etiquetas
    assert "temp_0" not in etiquetas and "temp_1" not in etiquetas
    assert etiquetas.count("temp") == 1, "la familia se dibujo mas de una vez"


def test_los_nodos_del_grafo_caen_sobre_una_circunferencia():
    """Radial, no barras. Un nodo fuera del anillo delata otra disposicion."""
    import math

    from chec_local_interpreter.mil_figuras import datos_grafo_radial

    grafo, nombres = _grafo_con_familias_de_rezagos()
    datos, _ = datos_grafo_radial(grafo, nombres)

    radios = [math.hypot(x, y)
              for x, y in zip(datos["nodos"]["x"], datos["nodos"]["y"])]
    assert radios, "el grafo salio sin nodos"
    assert all(abs(r - 1.0) < 1e-6 for r in radios), f"radios fuera del anillo: {radios}"


def test_el_grafo_rotula_variables_y_no_pares_de_variables():
    """Las barras de diferencia rotulaban PARES -- "CONDUCTOR - temp_0" --, una fila por
    arista. Un anillo rotula VARIABLES: cada nombre aparece una vez y las relaciones se
    leen en las lineas."""
    from chec_local_interpreter.mil_figuras import datos_grafo_radial

    grafo, nombres = _grafo_con_familias_de_rezagos()
    datos, _ = datos_grafo_radial(grafo, nombres)

    for etiqueta in datos["nodos"]["texto"]:
        assert " - " not in etiqueta and "—" not in etiqueta
    assert len(set(datos["nodos"]["texto"])) == len(datos["nodos"]["texto"])


def test_una_relacion_dentro_de_la_misma_familia_no_se_dibuja():
    """Plegada, seria un lazo de un nodo a si mismo: en un anillo, un punto."""
    from chec_local_interpreter.mil_figuras import datos_grafo_radial

    grafo, nombres = _grafo_con_familias_de_rezagos()
    datos, _ = datos_grafo_radial(grafo, nombres)

    # temp_0 - temp_1 era la unica arista interna; quedan las otras tres.
    assert len(datos["pesos"]["peso"]) == 3


def test_el_grafo_anulado_dice_por_que_en_vez_de_dibujar_un_anillo_vacio():
    from chec_local_interpreter.mil_figuras import datos_grafo_radial

    datos, motivo = datos_grafo_radial({"voided": True, "matriz": None}, ["A", "B"])
    assert datos is None and "tres vanos" in motivo

    datos, motivo = datos_grafo_radial(None, ["A", "B"])
    assert datos is None and motivo

    import numpy as np
    datos, motivo = datos_grafo_radial(
        {"voided": False, "matriz": np.zeros((3, 3)).tolist()}, ["A", "B", "C"])
    assert datos is None and "no movió" in motivo


def test_una_matriz_mas_grande_que_la_lista_de_nombres_no_tumba_el_anillo():
    """Tolerancia heredada del dibujo anterior, que inventaba `f0`, `f1`...

    Se conserva a proposito: un anillo con dos nodos sin nombre sigue diciendo que
    esta conectado con que, y perderlo entero por una lista corta seria cambiar la
    estructura por nada. `test_the_four_panels_are_written_as_png_files` depende de
    esto sin declararlo -- no le pasa `features` --, asi que aqui queda dicho.
    """
    from chec_local_interpreter.mil_figuras import datos_grafo_radial

    datos, motivo = datos_grafo_radial(
        {"voided": False, "matriz": [[0.0, 0.5], [0.5, 0.0]]}, [])

    assert motivo == ""
    assert sorted(datos["nodos"]["texto"]) == ["f0", "f1"]


def test_el_anillo_no_lleva_titulo_propio():
    """El informe ya rotula la figura en su propio encabezado HTML.

    Un `set_title` dentro del PNG repetia ahi lo que la seccion ya dice, y ademas
    con otras palabras: dos rotulos para un solo dibujo obligan al lector a decidir
    cual manda.
    """
    import inspect

    from chec_local_interpreter import mil_figuras

    fuente = inspect.getsource(mil_figuras._panel_grafo)

    assert "set_title" not in fuente


# ---------------------------------------------------------------------------
# Las barras de UITI llevan el color del GRUPO de cada vano.
# ---------------------------------------------------------------------------


def test_cada_barra_toma_el_color_del_grupo_de_su_vano():
    """El color de la barra es el mismo semaforo del agrupamiento.

    Antes las dos barras iban en gris y azul, que distinguian las dos CORRIDAS. Pero
    el grupo es la unidad en la que se decide una obra, y tenerlo solo como texto
    encima obligaba a leer barra por barra para ver donde esta lo rojo.
    """
    from chec_local_interpreter.mil_figuras import COLORES_GRUPOS, colores_de_barras_uiti

    vanos = [
        {"fid": "A", "clase_base": 3, "clase_simulada": 1},
        {"fid": "B", "clase_base": 2, "clase_simulada": 0},
    ]

    medido, estimado = colores_de_barras_uiti(vanos)

    assert medido == [COLORES_GRUPOS[3], COLORES_GRUPOS[2]]
    assert estimado == [COLORES_GRUPOS[1], COLORES_GRUPOS[0]]


def test_una_clase_fuera_de_rango_no_tumba_el_panel():
    """Un artefacto viejo puede traer una clase que la paleta de cuatro no cubre.

    Perder el panel entero por una celda deja al informe sin las barras de todos los
    demas vanos, que si son legibles. Se pinta en gris neutro, que NO es un grupo del
    semaforo y por eso no se puede confundir con uno.
    """
    from chec_local_interpreter.mil_figuras import (
        COLOR_SIN_GRUPO,
        COLORES_GRUPOS,
        colores_de_barras_uiti,
    )

    medido, estimado = colores_de_barras_uiti(
        [{"fid": "A", "clase_base": 9, "clase_simulada": None}]
    )

    assert medido == [COLOR_SIN_GRUPO]
    assert estimado == [COLOR_SIN_GRUPO]
    assert COLOR_SIN_GRUPO not in COLORES_GRUPOS
