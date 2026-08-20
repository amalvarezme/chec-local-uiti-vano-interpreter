"""Los tres shapefiles del mapa se leen UNA vez por corrida, no una por mapa.

Medido en esta maquina:

    MVLINSEC.shp            0,67 s    60.053 filas    37,1 MB
    GDBCHEC_TRANSFOR.shp    0,29 s    21.659 filas    18,5 MB
    SWITCHES.shp            0,12 s    10.263 filas     7,3 MB
                            ----                      ----
                            1,08 s                    62,9 MB

`plot_circuit_map_folium` los leia ENTEROS en cada llamada y despues se quedaba con
las filas de un solo circuito. Con tres mapas por informe eran 4,3 s y cuatro veces
esos 63 MB reservados y tirados. Al pasar el deslizador a las once ventanas del
circuito serian 13 s y doce veces la misma basura, por leer doce veces exactamente
los mismos bytes.

Se cachea la lectura CRUDA, no el resultado filtrado: el filtro depende del circuito
y el recorte ya devuelve una copia propia, asi que ningun llamador puede escribir
sobre el marco compartido. Cachear el resultado filtrado ademas no serviria para lo
que duele -- once mapas del MISMO circuito -- solo por casualidad.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chec_local_interpreter import plotting


@pytest.fixture
def geo_contadas(monkeypatch):
    """Cuenta las lecturas de disco y devuelve marcos falsos con la forma minima."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import LineString, Point

    lecturas: list[str] = []

    lineas = gpd.GeoDataFrame(
        {"CIRCUITO": ["C1", "C2"], "G3E_FID": ["10", "20"]},
        geometry=[LineString([(-75.5, 5.0), (-75.4, 5.1)]),
                  LineString([(-75.3, 5.2), (-75.2, 5.3)])],
        crs="EPSG:4326",
    )
    puntos = gpd.GeoDataFrame(
        {"CIRCUITO": ["C1", "C2"], "G3E_FID": ["30", "40"], "CODIGO": ["a", "b"]},
        geometry=[Point(-75.5, 5.0), Point(-75.3, 5.2)],
        crs="EPSG:4326",
    )

    def _falso(ruta, *a, **k):
        # `Path.name` y no `rsplit("/")`: lo que llega es una ruta del sistema, y en
        # Windows separa con barra invertida -- alli el corte por "/" devolvia la ruta
        # entera, con lo que ni el registro de lecturas ni el reparto de abajo entre
        # lineas y puntos acertaban una.
        nombre = Path(ruta).name
        lecturas.append(nombre)
        return lineas.copy() if nombre == "MVLINSEC.shp" else puntos.copy()

    monkeypatch.setattr(gpd, "read_file", _falso)
    monkeypatch.setattr(plotting.Path, "exists", lambda self: True)
    plotting.leer_geo_crudo.cache_clear()
    yield lecturas
    plotting.leer_geo_crudo.cache_clear()


def test_once_mapas_del_mismo_circuito_leen_el_disco_una_sola_vez(geo_contadas):
    """El deslizador dibuja once ventanas del mismo circuito, y la geometria de un
    circuito no cambia entre marzo y abril."""
    for _ in range(11):
        plotting._load_geo_vanos_for_circuit("C1")

    assert geo_contadas == ["MVLINSEC.shp"]


def test_cada_shapefile_se_lee_por_separado(geo_contadas):
    """Tres archivos distintos, tres entradas de cache: una clave sola los pisaria."""
    plotting._load_geo_vanos_for_circuit("C1")
    plotting._load_geo_points_for_circuit("C1", "GDBCHEC_TRANSFOR.shp", "FID_TRAFO_GEO")
    plotting._load_geo_points_for_circuit("C1", "SWITCHES.shp", "FID_SWITCH_GEO")
    plotting._load_geo_points_for_circuit("C1", "SWITCHES.shp", "FID_SWITCH_GEO")

    assert geo_contadas == ["MVLINSEC.shp", "GDBCHEC_TRANSFOR.shp", "SWITCHES.shp"]


def test_dos_circuitos_distintos_siguen_saliendo_del_mismo_marco(geo_contadas):
    """Se cachea la lectura CRUDA, no la filtrada: `/reporte-lote` recorre decenas de
    circuitos y con la filtrada cada uno volveria a leer el disco entero."""
    uno = plotting._load_geo_vanos_for_circuit("C1")
    otro = plotting._load_geo_vanos_for_circuit("C2")

    assert geo_contadas == ["MVLINSEC.shp"]
    assert list(uno["CIRCUITO"]) == ["C1"]
    assert list(otro["CIRCUITO"]) == ["C2"]


def test_el_marco_cacheado_no_se_puede_ensuciar_desde_un_llamador(geo_contadas):
    """Cada llamada devuelve su propia copia. Sin eso, una columna escrita por el mapa
    de una ventana aparece en el de la siguiente, y el defecto viaja entre circuitos
    dentro de un lote."""
    primero = plotting._load_geo_vanos_for_circuit("C1")
    primero["COLUMNA_INTRUSA"] = 1

    segundo = plotting._load_geo_vanos_for_circuit("C1")

    assert "COLUMNA_INTRUSA" not in segundo.columns
