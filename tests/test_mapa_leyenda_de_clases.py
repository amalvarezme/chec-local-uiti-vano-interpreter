"""La leyenda del mapa del circuito nombra los CUATRO grupos del agrupamiento.

El mapa colorea cada vano por su grupo de criticidad -- el mismo semaforo de
`asignar_clase` (0=Bajo..3=Alto) que usan el tablero de agrupamiento, el ranking
de circuitos y la prosa del informe --. La leyenda tiene que decir esos cuatro
nombres y ninguno mas: una quinta entrada nombra un grupo que el agrupamiento no
define y que ningun vano puede tener, y ademas repite color con `Alto`.
"""

from __future__ import annotations

import pandas as pd
import pytest

from chec_local_interpreter import plotting

gpd = pytest.importorskip("geopandas")
pytest.importorskip("folium")
shapely_geometry = pytest.importorskip("shapely.geometry")


GRUPOS_DEL_AGRUPAMIENTO = ("Bajo", "Medio", "Medio-Alto", "Alto")


def _geo(fids):
    return gpd.GeoDataFrame(
        {
            "FID_VANO_GEO": list(fids),
            "CODIGO": [f"COD{i}" for i, _ in enumerate(fids)],
            "CIRCUITO": ["C1"] * len(fids),
            "geometry": [
                shapely_geometry.LineString(
                    [(-75.5 + i * 0.1, 5.0 + i * 0.1), (-75.4 + i * 0.1, 5.1 + i * 0.1)]
                )
                for i, _ in enumerate(fids)
            ],
        },
        crs="EPSG:4326",
    )


@pytest.fixture()
def dibujar(monkeypatch):
    """Dibuja el mapa de un circuito con las clases que se le pidan."""

    def construir(clases, *, fids=("V1", "V2"), eventos_por_vano=None):
        monkeypatch.setattr(
            plotting, "_load_geo_vanos_for_circuit", lambda *_a, **_k: _geo(fids)
        )
        monkeypatch.setattr(plotting, "_load_geo_points_for_circuit", lambda *_a, **_k: None)

        eventos_por_vano = eventos_por_vano or {f: 1 for f in fids}
        columna_fid = [f for f, n in eventos_por_vano.items() for _ in range(n)]
        df = pd.DataFrame(
            {
                "CIRCUITO": ["C1"] * len(columna_fid),
                "FECHA": [f"2026-01-{(i % 28) + 1:02d}" for i in range(len(columna_fid))],
                "UITI_VANO": [10.0] * len(columna_fid),
                "FID_VANO": columna_fid,
            }
        )
        fmap = plotting.plot_circuit_map_folium(
            df, "C1", metric_class_by_vano=clases, metric_class_column="clase"
        )
        return fmap.get_root().render()

    return construir


@pytest.fixture()
def mapa_de_un_circuito(dibujar):
    return lambda: dibujar({"V1": "Bajo", "V2": "Alto"})


def test_la_leyenda_nombra_los_cuatro_grupos(mapa_de_un_circuito):
    html = mapa_de_un_circuito()
    for grupo in GRUPOS_DEL_AGRUPAMIENTO:
        assert f">{grupo}</div>" in html, f"la leyenda no nombra el grupo {grupo!r}"


def test_la_leyenda_no_inventa_un_quinto_grupo(mapa_de_un_circuito):
    """`Muy alto` no existe en el agrupamiento de vanos.

    Sobrevivia en `class_colors` "por los caminos antiguos", pero ninguna ruta del
    repositorio la produce: `asignar_clase` devuelve 0..3. Como la leyenda se
    construye recorriendo ese mismo diccionario, la entrada salia dibujada en
    TODOS los mapas, vacia y con el rojo de `Alto`.
    """
    html = mapa_de_un_circuito()
    assert "Muy alto" not in html


# ---------------------------------------------------------------------------
# Un vano SIN clase en la ventana dibujada
#
# `metric_by_vano` se calcula sobre el PERIODO y `metric_class_by_vano` sobre
# UNA ventana, asi que un vano con eventos en el periodo pero no en la ventana
# llega con evento y sin clase. Caia a la escala continua `turbo`, cuyos colores
# invaden el semaforo: medido, un vano sin clase salia `#7a0402`, un rojo mas
# oscuro que el `#c62828` de `Alto` y a su lado en el mapa. La leyenda decia
# "Clase" y no nombraba esa situacion, asi que ese vano se contaba como Alto.
# ---------------------------------------------------------------------------

SEMAFORO = {"#1a9641", "#f2c200", "#ef6c00", "#c62828"}


def _colores_de_linea(html):
    import re

    return set(re.findall(r'"color": "(#[0-9a-fA-F]{6})"', html))


def test_un_vano_sin_eventos_no_toma_un_color_del_semaforo(dibujar):
    html = dibujar(
        {"V1": "Bajo", "V2": "Alto"},
        fids=("V1", "V2", "V3"),
        eventos_por_vano={"V1": 1, "V2": 1, "V3": 6},
    )
    assert "Sin eventos" in html, "el vano sin eventos en la ventana deberia quedar marcado"

    # Solo pueden aparecer los colores del semaforo realmente usados (Bajo y Alto),
    # el gris de los vanos sin evento y el color propio de `Sin clase`.
    colores = _colores_de_linea(html)
    inesperados = {c for c in colores if c in SEMAFORO} - {"#1a9641", "#c62828"}
    assert not inesperados, f"colores del semaforo sin grupo detras: {inesperados}"
    assert "#7a0402" not in colores, "el vano sin eventos sigue en la escala continua"


def test_sin_eventos_se_nombra_en_la_leyenda_solo_cuando_ocurre(dibujar):
    con_sin_clase = dibujar(
        {"V1": "Bajo", "V2": "Alto"},
        fids=("V1", "V2", "V3"),
        eventos_por_vano={"V1": 1, "V2": 1, "V3": 6},
    )
    assert ">Sin eventos</div>" in con_sin_clase

    todos_con_clase = dibujar({"V1": "Bajo", "V2": "Alto"})
    assert ">Sin eventos</div>" not in todos_con_clase


# ---------------------------------------------------------------------------
# El mecanismo, no solo la asercion
#
# Que hoy la leyenda diga los cuatro nombres correctos no impide que manana
# alguien agregue un quinto color "por los caminos antiguos" -- que es
# exactamente como aparecio `Muy alto`. El vocabulario del mapa se cierra contra
# la definicion unica del agrupamiento, asi que separarlos rompe la prueba.
# ---------------------------------------------------------------------------


def test_el_mapa_cierra_su_vocabulario_contra_el_agrupamiento():
    from chec_local_interpreter.ranking_circuitos import NOMBRES_GRUPOS_VANO

    assert tuple(plotting.COLORES_CLASE_VANO) == NOMBRES_GRUPOS_VANO


def test_sin_eventos_no_es_un_grupo_del_semaforo():
    """La ausencia de dato no puede compartir color con un grupo real."""
    assert plotting.ETIQUETA_SIN_EVENTOS not in plotting.COLORES_CLASE_VANO
    assert plotting.COLOR_SIN_EVENTOS not in plotting.COLORES_CLASE_VANO.values()


# ---------------------------------------------------------------------------
# Una sola escala en toda la cadena del informe
#
# Cada modulo que dibuja declara su propia tupla de cuatro nombres y su propio
# semaforo. Hoy coinciden; el riesgo es que dejen de coincidir de a uno, que es
# como aparecieron los vocabularios paralelos que ya costaron dos arreglos. Esta
# prueba falla en cuanto uno se separe.
# ---------------------------------------------------------------------------


def test_todas_las_figuras_del_informe_usan_los_mismos_cuatro_grupos():
    from chec_local_interpreter import mil_figuras
    from chec_local_interpreter.ranking_circuitos import NOMBRES_GRUPOS_VANO

    assert tuple(mil_figuras.NOMBRES_GRUPOS) == NOMBRES_GRUPOS_VANO
    assert tuple(plotting.COLORES_CLASE_VANO) == NOMBRES_GRUPOS_VANO
    assert tuple(plotting.COLORES_CLASE_VANO.values()) == tuple(mil_figuras.COLORES_GRUPOS)
    # El gris de "sin grupo" tambien tiene que ser el mismo en el mapa y en las
    # figuras del MIL: dos grises distintos se leen como dos cosas distintas.
    assert plotting.COLOR_SIN_EVENTOS == mil_figuras.COLOR_SIN_GRUPO


def test_las_bandas_de_circuito_y_sus_slugs_no_se_pueden_separar():
    from chec_local_interpreter.batch_report_contract import GROUP_SLUGS, GROUP_SLUG_TO_LABEL
    from chec_local_interpreter.ranking_circuitos import NOMBRES_RANGO

    assert tuple(GROUP_SLUG_TO_LABEL[s] for s in GROUP_SLUGS) == NOMBRES_RANGO
    # Las bandas del CIRCUITO son las de vano con "Riesgo" delante: misma escala de
    # cuatro, sujeto distinto. Sin esa palabra las dos frases se leen como una sola.
    from chec_local_interpreter.ranking_circuitos import NOMBRES_GRUPOS_VANO

    assert NOMBRES_RANGO == tuple(f"Riesgo {g}" for g in NOMBRES_GRUPOS_VANO)


def test_un_solo_gris_para_todo_lo_que_no_tuvo_eventos(dibujar):
    """El vano sin eventos EN LA VENTANA y el que no los tuvo en todo el periodo.

    Los dos son "sin eventos" desde la ventana que el mapa dibuja, y la leyenda
    tiene una sola entrada. Con dos grises distintos -- `#9ca3af` y `#94a3b8`,
    indistinguibles a simple vista -- esa entrada rotulaba uno y callaba el otro,
    que es el mismo defecto de `Muy alto` al reves: un color en el mapa que la
    leyenda no explica.
    """
    html = dibujar(
        {"V1": "Bajo", "V2": "Alto"},
        # V4 no aparece en el marco de eventos: no tuvo ninguno en el periodo.
        fids=("V1", "V2", "V3", "V4"),
        eventos_por_vano={"V1": 1, "V2": 1, "V3": 6},
    )
    colores = _colores_de_linea(html)
    assert "#9ca3af" not in colores, "quedan dos grises distintos para la misma ausencia"
    assert plotting.COLOR_SIN_EVENTOS in colores


def test_la_leyenda_nombra_el_gris_tambien_cuando_solo_hay_vanos_sin_eventos(dibujar):
    """Todos los vanos con eventos tienen grupo, pero el circuito tiene mas vanos.

    La condicion miraba solo la columna de clase de los vanos CON evento, asi que
    este mapa dibujaba lineas grises y no las nombraba.
    """
    html = dibujar(
        {"V1": "Bajo", "V2": "Alto"},
        fids=("V1", "V2", "V3"),
        eventos_por_vano={"V1": 1, "V2": 1},
    )
    assert plotting.COLOR_SIN_EVENTOS in _colores_de_linea(html)
    assert ">Sin eventos</div>" in html
