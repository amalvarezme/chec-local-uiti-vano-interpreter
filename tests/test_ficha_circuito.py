"""La ficha de cabecera del informe por circuito.

El revisor pidio abrir el informe con los valores generales del circuito -- aporte
UITI, vanos probables de causa de falla, longitud total/urbana/rural y numero de
transformadores -- y con la clasificacion de criticidad en TABLA, no solo en la barra
de 208 rotulos de 8 px que nadie puede leer.

Todo sale de fuentes que el informe YA tiene: `ranking_circuitos` para lo comparativo
y los shapefiles de `data/GEO` para lo fisico. Ningun numero nuevo se inventa aqui.
"""

from __future__ import annotations

import pandas as pd
import pytest

from chec_local_interpreter.ficha_circuito import (
    ficha_general,
    medidas_fisicas,
    tabla_clasificacion_html,
    tabla_ficha_html,
    tabla_ventanas_html,
    vanos_de_mayor_impacto,
)


@pytest.fixture
def flota():
    """Tres circuitos con vanos suficientes para que el ranking agrupe."""
    filas = []
    for circuito, vanos, golpes in (("C1", 12, 5), ("C2", 6, 2), ("C3", 3, 1)):
        for v in range(vanos):
            for g in range(golpes):
                filas.append({
                    "CIRCUITO": circuito,
                    "FID_VANO": f"{circuito}-V{v}",
                    "UITI_VANO": 10.0 * (v + 1) + g,
                    "FECHA": f"2026-01-{(g % 28) + 1:02d}",
                })
    return pd.DataFrame(filas)


# --------------------------------------------------------------------- ficha general


def test_la_ficha_trae_el_puesto_y_el_total_de_circuitos(flota):
    ficha = ficha_general(flota, "C1")
    assert ficha["circuitos_totales"] == 3
    assert 1 <= ficha["posicion"] <= 3
    assert ficha["rango"].startswith("Riesgo ")


def test_la_ficha_separa_el_uiti_del_circuito_del_uiti_de_todos_los_circuitos(flota):
    ficha = ficha_general(flota, "C1")
    assert ficha["uiti_circuito"] > 0
    assert ficha["uiti_total"] >= ficha["uiti_circuito"]
    # El aporte del circuito al total, que es la lectura que el revisor pidio en el
    # resumen ejecutivo: "UiTi acumulado del circuito" contra "UiTi acumulado total".
    assert 0 < ficha["aporte_uiti_pct"] <= 100


def test_vanos_probables_de_causa_de_falla_no_es_el_conteo_de_eventos(flota):
    """El revisor pidio llamar a las cosas por su nombre.

    Un vano probable de causa de falla es un VANO que aparece en registros de
    interrupcion. `registros_vano_evento` cuenta FILAS: el mismo vano golpeado cinco
    veces son cinco registros y un solo vano. Confundirlos es como el informe termina
    diciendo que un circuito tiene 235 vanos cuando tiene 12.
    """
    ficha = ficha_general(flota, "C1")
    assert ficha["vanos_probables"] == 12
    assert ficha["registros_vano_evento"] == 60
    assert ficha["vanos_probables"] != ficha["registros_vano_evento"]


def test_la_ficha_de_un_circuito_ausente_no_revienta(flota):
    assert ficha_general(flota, "NO-EXISTE") == {}


def test_la_ficha_sin_datos_devuelve_vacio():
    assert ficha_general(pd.DataFrame(), "C1") == {}


# ------------------------------------------------------------------- medidas fisicas


def test_las_medidas_fisicas_faltantes_devuelven_vacio_en_vez_de_romper():
    """Sin `data/GEO` el informe pierde la longitud, no la cabecera entera."""
    assert medidas_fisicas("CIRCUITO-QUE-NO-ESTA-EN-NINGUN-SHAPEFILE") == {}


# ------------------------------------------------------------------------ tabla ficha


def test_la_tabla_de_la_ficha_nombra_los_vanos_probables_de_causa_de_falla(flota):
    html = tabla_ficha_html(ficha_general(flota, "C1"))
    assert "Vanos probables de causa de falla" in html
    assert "UITI acumulado del circuito" in html
    assert "<table" in html


def test_la_tabla_de_la_ficha_vacia_no_dibuja_nada():
    assert tabla_ficha_html({}) == ""


# ----------------------------------------------------------------- tabla clasificacion


def test_la_tabla_de_clasificacion_numera_la_ubicacion_de_cada_circuito(flota):
    html = tabla_clasificacion_html(flota, "C1")
    # El numero de ubicacion, que es lo que el revisor pidio ver en la tabla Y en la
    # grafica para poder cruzar las dos.
    assert "Ubicación" in html
    for circuito in ("C1", "C2", "C3"):
        assert circuito in html


def test_la_tabla_de_clasificacion_marca_el_circuito_del_informe(flota):
    html = tabla_clasificacion_html(flota, "C2")
    assert "fila-destacada" in html


def test_la_tabla_de_clasificacion_sin_datos_no_dibuja_nada():
    assert tabla_clasificacion_html(pd.DataFrame(), "C1") == ""


# --------------------------------------------------------------------- tabla ventanas


def test_la_tabla_de_ventanas_trae_fechas_uiti_registros_y_vanos(flota):
    html = tabla_ventanas_html(flota, "C1")
    for encabezado in ("Ventana", "Desde", "Hasta", "UITI", "Registros", "Vanos"):
        assert encabezado in html


def test_la_tabla_de_ventanas_advierte_que_no_son_aditivas(flota):
    """Las once ventanas se traslapan quince dias: sumarlas cuenta dos veces.

    Es el error que ya cambio el top 15 de 74 circuitos una vez. La advertencia va
    PEGADA a la tabla, no en un parrafo tres secciones mas arriba.
    """
    html = tabla_ventanas_html(flota, "C1")
    assert "no son aditivos" in html or "no se suman" in html


def test_la_tabla_de_ventanas_sin_datos_no_dibuja_nada():
    assert tabla_ventanas_html(pd.DataFrame(), "C1") == ""


# ---------------------------------------------------------------------- vanos impacto


def test_los_vanos_de_mayor_impacto_separan_uiti_de_apariciones(flota):
    """Dos criterios distintos y su interseccion, que es lo que el revisor pidio.

    Un vano puede concentrar UITI en una sola salida grande y otro puede aparecer en
    todas las ventanas con poco. Los que estan en las DOS listas son los que no
    dependen de cual criterio se eligio.
    """
    resultado = vanos_de_mayor_impacto(flota, "C1", tope=5)
    assert len(resultado["por_uiti"]) == 5
    assert len(resultado["por_apariciones"]) == 5
    assert set(resultado["coincidentes"]) <= (
        {v["fid"] for v in resultado["por_uiti"]}
        & {v["fid"] for v in resultado["por_apariciones"]}
    )


def test_los_vanos_de_mayor_impacto_sin_datos_devuelven_listas_vacias():
    resultado = vanos_de_mayor_impacto(pd.DataFrame(), "C1")
    assert resultado == {"por_uiti": [], "por_apariciones": [], "coincidentes": []}
