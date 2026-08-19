"""RED/GREEN tests for notebook 01.5's `ventanas_015` module.

PR1 covers `cargar_clases_criticidad`, which composes
`verificar_sha1_geometrias` -> `cargar_geometria_014` -> `asignar_clase`
(design section F) over the tracked geometry artifact
(`data/geometria_kmeans_014_v1.json`). No KMeans fitting happens here --
01.4's own nearest-centroid geometry is replayed.

PR3 covers the window builder and the row-1-col-1 (historical map) support
functions: `construir_ventanas` (01.4's own month + shifted-15 cut list,
design section E cell 7), `construir_tabla_vano_ventana` (per-vano x
ventana `num_eventos`/`uiti_acumulado`, 01.4 cell 3's aggregation),
`construir_mask_cache` / `construir_hist_class_cache` (design section A's
`mask_cache` and `hist_class_cache`) and `capas_mapa_historico` (the pure
grouping logic behind row 1 col 1's map traces -- the only piece of that
cell's logic worth testing outside a live kernel, per the Strict TDD rule
that notebook cells only call already-tested functions).

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domains `vano-explainability-panel`)
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (sections A, E, F)
  - retirement of the notebook-04-extraction fallback:
    `sdd/retire-base-apps-notebooks/design` (D3)

Retired (`sdd/retire-base-apps-notebooks`): `cargar_clases_desde_014` used to
lazily extract the geometry from a notebook via
`scripts/extract_geometrias_014.py` on a cold cache. That fallback and its
notebook fixture round-trips are gone; `_geometria_tamperada` below tampers a
COPY of the tracked artifact directly, computing its own sha1 the same way
the retired extraction script used to (canonical, sorted-key JSON), so a
sha1 mismatch can still be exercised without touching the committed file.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from chec_impacto.models.criticality_assignment import (
    CLAVE_ESPACIO_CANONICO,
    GEOMETRIAS_SHA1_ESPERADO,
)
from chec_local_interpreter import ventanas_015
from chec_local_interpreter.ventanas_015 import (
    bounds_de_fids,
    cajas_por_cambio_de_grupo,
    cajas_seleccion,
    cajas_seleccion_por_clase,
    cargar_clases_criticidad,
    capas_mapa_historico,
    construir_hist_class_cache,
    construir_mask_cache,
    construir_tabla_vano_ventana,
    construir_ventanas,
    nube_fondo,
    nube_seleccion,
    perfil_uiti_por_vano,
    clases_de_series,
    top_vanos_de_ventana,
    ventanas_sin_traslape,
)

RUTA_GEOMETRIA_REAL = Path(__file__).resolve().parents[1] / "data" / "geometria_kmeans_014_v1.json"

# Raw (n_obs, u) pairs that invert EXACTLY onto each of the four centroids of
# the canonical space -- copied from `tests/test_criticality_assignment.py`'s
# own `_PUNTOS_EN_CENTROIDE`, verified independently there against the same
# geometry values, so the expected class for each is unambiguous.
_PUNTOS_EN_CENTROIDE = [
    (1.577035, 1.0497337983054202, 0),
    (2.1565, 17.862954277049855, 1),
    (2.096785, 281.1720793193615, 2),
    (11.68552, 593.2019276116357, 3),
]


def _sha1_de_geometrias(geometrias: dict) -> str:
    """Same canonicalization the retired `extract_geometrias_014.py` used:
    sorted-key, no-whitespace JSON over the `geometrias` block only."""
    canonical = json.dumps(geometrias, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _geometria_tamperada(tmp_path: Path) -> Path:
    """A copy of the tracked geometry artifact with one centroid nudged and
    its stored `geometrias_sha1` recomputed from the mutated block --
    simulates the artifact being hand-edited without re-pinning, which is
    exactly what `verificar_sha1_geometrias` exists to catch."""
    payload = json.loads(RUTA_GEOMETRIA_REAL.read_text(encoding="utf-8"))
    payload["geometrias"][CLAVE_ESPACIO_CANONICO]["centroides"][0][0] += 1.0
    payload["geometrias_sha1"] = _sha1_de_geometrias(payload["geometrias"])

    destino = tmp_path / "geometria_tamperada.json"
    destino.write_text(json.dumps(payload), encoding="utf-8")
    return destino


# --- 1.1: sha1 mismatch hard-raises ----------------------------------------


def test_cargar_clases_criticidad_raises_on_sha1_mismatch_against_tampered_geometria(tmp_path):
    geometrias_tamperadas = _geometria_tamperada(tmp_path)

    with pytest.raises(RuntimeError) as exc_info:
        cargar_clases_criticidad(
            n_obs=np.array([1.577035]),
            u=np.array([1.0497337983054202]),
            geometrias_path=geometrias_tamperadas,
        )

    payload = json.loads(geometrias_tamperadas.read_text(encoding="utf-8"))
    sha1_real = payload["geometrias_sha1"]
    assert sha1_real != GEOMETRIAS_SHA1_ESPERADO

    mensaje = str(exc_info.value)
    assert GEOMETRIAS_SHA1_ESPERADO in mensaje
    assert sha1_real in mensaje


def test_cargar_clases_criticidad_raises_when_esperado_override_mismatches_real_geometria():
    """Triangulates the mismatch path with the real, untampered geometry
    artifact and a deliberately wrong `esperado` override, so the
    RuntimeError is proven to come from a real digest comparison, not from
    special-casing a tampered fixture."""
    esperado_incorrecto = "0" * 40

    with pytest.raises(RuntimeError) as exc_info:
        cargar_clases_criticidad(
            n_obs=np.array([1.577035]),
            u=np.array([1.0497337983054202]),
            esperado=esperado_incorrecto,
        )

    mensaje = str(exc_info.value)
    assert esperado_incorrecto in mensaje
    assert GEOMETRIAS_SHA1_ESPERADO in mensaje


# --- 1.2: missing artifact raises, cold-cache regression scenario ----------


def test_cargar_clases_criticidad_raises_file_not_found_when_geometrias_path_missing(tmp_path):
    geometrias_inexistente = tmp_path / "no_existe.json"

    with pytest.raises(FileNotFoundError):
        cargar_clases_criticidad(
            n_obs=np.array([1.0]),
            u=np.array([1.0]),
            geometrias_path=geometrias_inexistente,
        )


def test_cargar_clases_criticidad_cold_cache_never_touches_notebook_04_or_extraction_script():
    """Spec's cold-cache regression scenario: deleting
    `data/derived/geometrias_014.json` (the old, gitignored cache) must not
    make this function fall back to reading notebook 04 or
    `scripts/extract_geometrias_014.py` -- neither exists as an attribute on
    this module anymore, and the default `geometrias_path` never points at
    `data/derived/` in the first place."""
    assert not hasattr(ventanas_015, "extraer_geometrias_014")
    assert "derived" not in str(ventanas_015.RUTA_GEOMETRIA)

    clase, n_clamped = cargar_clases_criticidad(
        n_obs=np.array([1.577035]), u=np.array([1.0497337983054202]),
    )
    assert clase[0] == 0
    assert n_clamped == 0


# --- 1.3/1.4: GREEN -- matches 01.4's own class assignment -----------------


@pytest.mark.parametrize("n_obs, u, clase_esperada", _PUNTOS_EN_CENTROIDE)
def test_cargar_clases_criticidad_matches_committed_geometry_for_known_points(
    n_obs, u, clase_esperada
):
    clase, n_clamped = cargar_clases_criticidad(
        n_obs=np.array([n_obs]),
        u=np.array([u]),
    )

    assert clase[0] == clase_esperada
    assert n_clamped == 0


# --- 3.1: construir_ventanas reproduces 01.4's month + shifted-15 cut list -


def test_construir_ventanas_reproduces_01_4_cut_list_for_a_two_month_range():
    """Hand-computed against 01.4's own algorithm (cell 2): each calendar
    month contributes its full span plus the 15th-to-15th crossover into
    the next month; sorted and filtered to the fixed [min, max] range."""
    fechas = pd.to_datetime(["2025-01-05", "2025-01-20", "2025-02-10", "2025-02-25"])

    ventanas = construir_ventanas(fechas)

    assert [v["periodo"] for v in ventanas] == [
        "2025-01-01 a 2025-01-31",
        "2025-01-15 a 2025-02-14",
        "2025-02-01 a 2025-02-28",
    ]
    assert [v["etiqueta"] for v in ventanas] == ["V1", "V2", "V3"]
    assert [v["i"] for v in ventanas] == [0, 1, 2]


def test_construir_ventanas_hasta_excl_is_the_exclusive_upper_bound():
    fechas = pd.to_datetime(["2025-01-05", "2025-02-25"])

    primera = construir_ventanas(fechas)[0]

    assert primera["desde"] == pd.Timestamp("2025-01-01")
    assert primera["hasta_excl"] == pd.Timestamp("2025-02-01")


# --- 3.2: per-(vano, ventana) num_eventos / uiti_acumulado ----------------


def test_construir_tabla_vano_ventana_aggregates_events_per_vano_and_window():
    """Same shape as 01.4 cell 3's `TABLA`: one row per (CIRCUITO,
    FID_VANO, ventana_i) with events, `uiti_acumulado` rounded to 3
    decimals, zero-UITI rows dropped."""
    df = pd.DataFrame({
        "CIRCUITO": ["C1", "C1", "C2"],
        "FID_VANO": ["VA", "VA", "VB"],
        "UITI_VANO": [1.0, 2.0, 0.5],
        # Jan-03 falls only in window 0; Feb-25 falls only in window 2;
        # Jan-10 falls only in window 0 too (window 1 starts Jan-15).
        "FECHA": pd.to_datetime(["2025-01-03", "2025-02-25", "2025-01-10"]),
    })
    ventanas = construir_ventanas(df["FECHA"])

    tabla = construir_tabla_vano_ventana(df, ventanas)

    fila_va_v0 = tabla[(tabla["FID_VANO"] == "VA") & (tabla["ventana_i"] == 0)].iloc[0]
    assert fila_va_v0["num_eventos"] == 1
    assert fila_va_v0["uiti_acumulado"] == 1.0

    fila_va_v2 = tabla[(tabla["FID_VANO"] == "VA") & (tabla["ventana_i"] == 2)].iloc[0]
    assert fila_va_v2["num_eventos"] == 1
    assert fila_va_v2["uiti_acumulado"] == 2.0

    assert tabla[(tabla["FID_VANO"] == "VA") & (tabla["ventana_i"] == 1)].empty
    assert (tabla["uiti_acumulado"] > 0).all()


# --- Perfil del circuito: UITI acumulado de TODA la serie, por vano --------
#
# `construir_ventanas` interleaves each calendar month with the 15th-to-15th
# crossover into the next one, so the windows OVERLAP and
# `construir_tabla_vano_ventana`'s own docstring warns they "cannot simply be
# summed". The circuit profile needs a total over the whole series, so it has
# to add up a set of windows that tiles the period exactly once -- which is
# what `ventanas_sin_traslape` picks and `perfil_uiti_por_vano` consumes.
#
# Measured on the real 111.231-cell table: summing ALL windows inflates a
# vano's total by a factor between 1,00 and 2,09 (median 2,0). Because the
# factor is NOT constant it does not cancel out in a ranking -- 74 of the 208
# circuits get a different top 15 depending on which sum is used.


def test_ventanas_sin_traslape_toma_los_meses_y_embaldosa_el_periodo():
    """Los meses calendario cubren el periodo entero sin huecos ni traslapes.

    Es la propiedad de la que depende `perfil_uiti_por_vano`: si el conjunto
    elegido dejara un hueco, el total de un vano perderia sus eventos; si se
    traslapara, los contaria dos veces.
    """
    ventanas = construir_ventanas(pd.to_datetime(["2025-11-03", "2026-04-20"]))

    indices = ventanas_sin_traslape(ventanas)

    elegidas = [ventanas[i] for i in indices]
    assert [v["etiqueta"] for v in elegidas] == ["V1", "V3", "V5", "V7", "V9", "V11"]
    # Sin huecos ni traslapes: cada ventana empieza donde termina la anterior.
    assert all(elegidas[k]["hasta_excl"] == elegidas[k + 1]["desde"]
               for k in range(len(elegidas) - 1))
    # Y entre todas cubren exactamente lo que cubren las once.
    assert elegidas[0]["desde"] == min(v["desde"] for v in ventanas)
    assert elegidas[-1]["hasta_excl"] == max(v["hasta_excl"] for v in ventanas)


def test_perfil_uiti_por_vano_no_cuenta_dos_veces_el_evento_de_la_zona_traslapada():
    """Un evento del 20 de noviembre cae en V1 (el mes) y en V2 (el corte del
    15 al 15). El total del vano lo cuenta UNA vez.

    Este es el test que separa la implementacion correcta de la obvia: un
    `groupby(FID_VANO).uiti_acumulado.sum()` sobre la tabla entera devolveria
    20,0 para VA en vez de 10,0.
    """
    # El rango llega hasta diciembre a proposito: `construir_ventanas` descarta
    # el corte del 15 al 15 que se sale del periodo, asi que con un solo mes no
    # habria traslape que probar.
    df = pd.DataFrame({
        "CIRCUITO": ["C1", "C1"],
        "FID_VANO": ["VA", "VB"],
        "UITI_VANO": [10.0, 3.0],
        # Nov-20 cae en V1 (nov) y en V2 (15-nov a 15-dic): zona de traslape.
        # Dic-05 cae SOLO en V3 (dic).
        "FECHA": pd.to_datetime(["2025-11-20", "2025-12-05"]),
    })
    ventanas = construir_ventanas(df["FECHA"])
    tabla = construir_tabla_vano_ventana(df, ventanas)
    # La tabla SI trae el evento repetido en las dos ventanas: es el dato del
    # que parte el perfil, no un error de la tabla.
    assert len(tabla[tabla["FID_VANO"] == "VA"]) == 2

    perfil = perfil_uiti_por_vano(tabla, "C1", ventanas=ventanas)

    assert perfil.set_index("FID_VANO")["uiti_total"].to_dict() == {"VA": 10.0, "VB": 3.0}
    assert perfil.set_index("FID_VANO")["num_eventos"].to_dict() == {"VA": 1, "VB": 1}


def test_perfil_uiti_por_vano_ordena_de_mayor_a_menor_y_recorta_al_top():
    """El panel muestra los mas criticos primero, y solo `top` de ellos."""
    df = pd.DataFrame({
        "CIRCUITO": ["C1"] * 4,
        "FID_VANO": ["VA", "VB", "VC", "VD"],
        "UITI_VANO": [1.0, 30.0, 20.0, 2.0],
        "FECHA": pd.to_datetime(["2025-11-05"] * 4),
    })
    ventanas = construir_ventanas(df["FECHA"])
    tabla = construir_tabla_vano_ventana(df, ventanas)

    perfil = perfil_uiti_por_vano(tabla, "C1", ventanas=ventanas, top=2)

    assert perfil["FID_VANO"].tolist() == ["VB", "VC"]
    assert perfil["uiti_total"].tolist() == [30.0, 20.0]


def test_perfil_uiti_por_vano_reparte_la_participacion_sobre_el_circuito_entero():
    """`participacion` es la fraccion del UITI del CIRCUITO, no la del top.

    Es lo que contesta la pregunta del panel -- cuanto del circuito se
    concentra en unos pocos vanos --, y calcularla sobre los vanos mostrados
    daria siempre 100% por construccion.
    """
    df = pd.DataFrame({
        "CIRCUITO": ["C1"] * 4,
        "FID_VANO": ["VA", "VB", "VC", "VD"],
        "UITI_VANO": [50.0, 30.0, 15.0, 5.0],
        "FECHA": pd.to_datetime(["2025-11-05"] * 4),
    })
    ventanas = construir_ventanas(df["FECHA"])
    tabla = construir_tabla_vano_ventana(df, ventanas)

    perfil = perfil_uiti_por_vano(tabla, "C1", ventanas=ventanas, top=2)

    assert perfil["participacion"].tolist() == [0.5, 0.3]


def test_perfil_uiti_por_vano_cuenta_en_cuantas_ventanas_del_periodo_aparece():
    """`n_ventanas` distingue al vano que fallo una vez del que falla mes a
    mes -- con el mismo UITI total, no son la misma obra."""
    df = pd.DataFrame({
        "CIRCUITO": ["C1", "C1", "C1"],
        "FID_VANO": ["VA", "VA", "VB"],
        "UITI_VANO": [5.0, 5.0, 10.0],
        # VA en dos meses distintos; VB todo en uno.
        "FECHA": pd.to_datetime(["2025-11-05", "2025-12-05", "2025-11-05"]),
    })
    ventanas = construir_ventanas(df["FECHA"])
    tabla = construir_tabla_vano_ventana(df, ventanas)

    perfil = perfil_uiti_por_vano(tabla, "C1", ventanas=ventanas)

    por_vano = perfil.set_index("FID_VANO")
    assert por_vano.loc["VA", "uiti_total"] == 10.0
    assert por_vano.loc["VA", "n_ventanas"] == 2
    assert por_vano.loc["VB", "n_ventanas"] == 1


def test_perfil_uiti_por_vano_solo_mira_el_circuito_pedido():
    df = pd.DataFrame({
        "CIRCUITO": ["C1", "C2"],
        "FID_VANO": ["VA", "VB"],
        "UITI_VANO": [1.0, 99.0],
        "FECHA": pd.to_datetime(["2025-11-05", "2025-11-05"]),
    })
    ventanas = construir_ventanas(df["FECHA"])
    tabla = construir_tabla_vano_ventana(df, ventanas)

    perfil = perfil_uiti_por_vano(tabla, "C1", ventanas=ventanas)

    assert perfil["FID_VANO"].tolist() == ["VA"]


def test_perfil_uiti_por_vano_devuelve_vacio_con_columnas_para_un_circuito_sin_celdas():
    """El panel repinta con lo que reciba: un DataFrame vacio SIN columnas lo
    haria fallar al leerlas, en vez de dibujar un panel vacio."""
    df = pd.DataFrame({
        "CIRCUITO": ["C1"],
        "FID_VANO": ["VA"],
        "UITI_VANO": [1.0],
        "FECHA": pd.to_datetime(["2025-11-05"]),
    })
    ventanas = construir_ventanas(df["FECHA"])
    tabla = construir_tabla_vano_ventana(df, ventanas)

    perfil = perfil_uiti_por_vano(tabla, "NO_EXISTE", ventanas=ventanas)

    assert perfil.empty
    assert list(perfil.columns) == ["FID_VANO", "uiti_total", "num_eventos",
                                    "n_ventanas", "participacion"]


def test_perfil_uiti_por_vano_devuelve_el_fid_como_texto():
    """El selector de vanos, el mapa y el hover trabajan con el fid en TEXTO
    (`_vanos_marcables` devuelve `str`). Un fid entero aqui no cruzaria con
    ellos y el panel quedaria desconectado del resto del tablero."""
    df = pd.DataFrame({
        "CIRCUITO": ["C1"],
        "FID_VANO": [20130472],
        "UITI_VANO": [1.0],
        "FECHA": pd.to_datetime(["2025-11-05"]),
    })
    ventanas = construir_ventanas(df["FECHA"])
    tabla = construir_tabla_vano_ventana(df, ventanas)

    perfil = perfil_uiti_por_vano(tabla, "C1", ventanas=ventanas)

    assert perfil["FID_VANO"].tolist() == ["20130472"]


# --- Top de la VENTANA: a quien se le marca la casilla al mover el deslizador -
#
# `perfil_uiti_por_vano` contesta "donde esta el riesgo del circuito en TODO el
# periodo" y es lo que se auto-marca al aterrizar en un circuito. Al mover el
# deslizador la pregunta cambia de sujeto: cual es el riesgo de ESTA ventana. Y
# ahi no hay traslape que corregir -- una ventana es una ventana --, asi que es
# un orden directo sobre sus celdas y no una suma sobre un subconjunto.
#
# Los dos tableros (04 y 06) tienen que auto-marcar EXACTAMENTE los mismos
# vanos, o el mismo circuito en el mismo periodo se lee como dos circuitos. Por
# eso el criterio vive aqui y no escrito dos veces, una en Python y otra en el
# JavaScript del panel de 04.


def _tabla_de_ventana():
    """Dos circuitos, dos ventanas y UITI deliberadamente desordenado respecto
    del fid, para que un orden por fid no pueda pasar por un orden por UITI."""
    return pd.DataFrame({
        "CIRCUITO": ["C1", "C1", "C1", "C1", "C2"],
        "FID_VANO": ["VA", "VB", "VC", "VB", "VZ"],
        "ventana_i": [0, 0, 0, 1, 0],
        "uiti_acumulado": [5.0, 9.0, 1.0, 40.0, 99.0],
        "num_eventos": [2, 3, 1, 4, 7],
    })


def test_top_vanos_de_ventana_ordena_por_uiti_de_esa_ventana():
    """De mayor a menor UITI EN ESA VENTANA. Es lo que decide a quien se le
    marca la casilla sola, y por tanto quien entra a la serie de tiempo."""
    assert top_vanos_de_ventana(_tabla_de_ventana(), "C1", 0) == ["VB", "VA", "VC"]


def test_top_vanos_de_ventana_solo_mira_esa_ventana_y_ese_circuito():
    """VB acumula 40 en la ventana 1 y 9 en la 0. Preguntar por la 0 no puede
    traer el 40, ni el 99 de VZ, que es de otro circuito."""
    tabla = _tabla_de_ventana()

    assert top_vanos_de_ventana(tabla, "C1", 1) == ["VB"]
    assert top_vanos_de_ventana(tabla, "C2", 0) == ["VZ"]


def test_top_vanos_de_ventana_recorta_al_tope_pedido():
    """Mas de quince vanos con eventos en la ventana se recortan a los quince de
    mayor UITI: es el tope de la auto-marca que pide el panel."""
    assert top_vanos_de_ventana(_tabla_de_ventana(), "C1", 0, top=2) == ["VB", "VA"]


def test_top_vanos_de_ventana_desempata_por_fid_para_ser_reproducible():
    """Dos vanos con el mismo UITI tienen que salir SIEMPRE en el mismo orden.

    Sin desempate, el orden lo decidiria el de las filas de la tabla y el mismo
    circuito auto-marcaria vanos distintos en el cuaderno y en la aplicacion, que
    congela la tabla en un parquet reordenado.
    """
    tabla = pd.DataFrame({
        "CIRCUITO": ["C1", "C1", "C1"],
        "FID_VANO": ["VC", "VA", "VB"],
        "ventana_i": [0, 0, 0],
        "uiti_acumulado": [7.0, 7.0, 7.0],
        "num_eventos": [1, 1, 1],
    })

    assert top_vanos_de_ventana(tabla, "C1", 0) == ["VA", "VB", "VC"]


def test_top_vanos_de_ventana_devuelve_lista_vacia_sin_celdas():
    """Una ventana sin un solo evento no auto-marca nada. Devolver `None` o
    fallar obligaria a cada llamador a envolverlo."""
    assert top_vanos_de_ventana(_tabla_de_ventana(), "C1", 9) == []
    assert top_vanos_de_ventana(_tabla_de_ventana(), "NO_EXISTE", 0) == []


def test_top_vanos_de_ventana_devuelve_el_fid_como_texto():
    """El selector de vanos y el mapa trabajan con el fid en TEXTO. Un entero
    aqui no cruzaria con las casillas y la auto-marca no marcaria ninguna."""
    tabla = pd.DataFrame({
        "CIRCUITO": ["C1"],
        "FID_VANO": [20130472],
        "ventana_i": [0],
        "uiti_acumulado": [1.0],
        "num_eventos": [1],
    })

    assert top_vanos_de_ventana(tabla, "C1", 0) == ["20130472"]


# --- 3.2: mask_cache (LRU 64) ----------------------------------------------


def test_construir_mask_cache_returns_boolean_mask_matching_circuito_y_ventana():
    tabla = pd.DataFrame({
        "CIRCUITO": ["C1", "C1", "C2"],
        "FID_VANO": ["VA", "VB", "VC"],
        "ventana_i": [0, 1, 0],
        "num_eventos": [1, 1, 1],
        "uiti_acumulado": [1.0, 1.0, 1.0],
    })
    mask_para = construir_mask_cache(tabla)

    mask = mask_para("C1", 0)

    assert mask.tolist() == [True, False, False]
    # Same key returns the SAME cached array object -- proves this is
    # actually `lru_cache`-backed, not recomputing every call.
    assert mask_para("C1", 0) is mask


# --- 3.2: hist_class_cache --------------------------------------------------


def test_construir_hist_class_cache_returns_empty_dict_when_window_has_no_rows():
    tabla = pd.DataFrame({
        "CIRCUITO": ["C1"], "FID_VANO": ["VA"], "ventana_i": [0],
        "num_eventos": [1], "uiti_acumulado": [1.0],
    })
    mask_para = construir_mask_cache(tabla)
    clases_para = construir_hist_class_cache(tabla, mask_para)

    assert clases_para("C1", 1) == {}


def test_construir_hist_class_cache_maps_fid_to_class_via_injected_classifier():
    """`cargar_clases` is injectable so this stays a fast, model/file-free
    unit test -- the real `cargar_clases_desde_014` default is already
    covered end-to-end by the PR1 tests above."""
    tabla = pd.DataFrame({
        "CIRCUITO": ["C1", "C1"], "FID_VANO": ["VA", "VB"], "ventana_i": [0, 0],
        "num_eventos": [1, 5], "uiti_acumulado": [1.0, 9.0],
    })
    mask_para = construir_mask_cache(tabla)
    llamadas = []

    def _clasificador_falso(n_obs, u, **kwargs):
        llamadas.append((tuple(n_obs), tuple(u)))
        return np.where(np.asarray(u) > 5, 3, 0), 0

    clases_para = construir_hist_class_cache(tabla, mask_para, cargar_clases=_clasificador_falso)

    assert clases_para("C1", 0) == {"VA": 0, "VB": 3}
    assert len(llamadas) == 1
    # Cached: a second call with the same key does not invoke the
    # classifier again.
    clases_para("C1", 0)
    assert len(llamadas) == 1


def test_construir_hist_class_cache_keys_by_str_even_when_fid_vano_is_numeric():
    """The REAL `TABLA` has `FID_VANO` as int64 (it is aggregated straight off
    the CSV), while the map's `GEO_POR_CIRCUITO['fids']` are strings -- the
    shapefile ids go through `str()`. `capas_mapa_historico` looks each geo fid
    up in this dict, so int keys mean EVERY vano misses its class and the whole
    historical map paints "Sin dato". Both this function's annotation and its
    docstring already promise `dict[str, int]`; the fixtures above only ever
    used string fids, so nothing enforced it."""
    tabla = pd.DataFrame({
        "CIRCUITO": ["C1", "C1"], "FID_VANO": [20130434, 20130436], "ventana_i": [0, 0],
        "num_eventos": [1, 5], "uiti_acumulado": [1.0, 9.0],
    })
    assert tabla["FID_VANO"].dtype == "int64"  # como en el cuaderno
    mask_para = construir_mask_cache(tabla)

    clases_para = construir_hist_class_cache(
        tabla, mask_para, cargar_clases=lambda n_obs, u, **kw: (np.where(np.asarray(u) > 5, 3, 0), 0)
    )
    clases = clases_para("C1", 0)

    assert clases == {"20130434": 0, "20130436": 3}
    assert all(isinstance(k, str) for k in clases)


# --- row 1 col 1: capas_mapa_historico --------------------------------------


def test_capas_mapa_historico_groups_by_class_marks_sin_dato_and_halo():
    """The pure layer-grouping logic behind row 1 col 1's map traces
    (design section G, idx 0-5): every vano lands in exactly one class
    layer or `sin_dato`, and marked vanos additionally land in `marcados`
    -- the halo layer. Every returned lat/lon list ends with `None` so
    Plotly draws each vano's segments separately within one trace."""
    geo_circuito = {
        "fids": ["VA", "VB", "VC"],
        "lat": [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1]],
        "lon": [[-75.0, -75.1], [-76.0, -76.1], [-77.0, -77.1]],
    }
    clases_por_fid = {"VA": 0, "VB": 3}  # VC absent from the window -> sin_dato

    capas = capas_mapa_historico(geo_circuito, clases_por_fid, marcados=["VB"])

    assert capas["clases"][0]["lat"] == [1.0, 1.1, None]
    assert capas["clases"][3]["lon"] == [-76.0, -76.1, None]
    # Una capa sin vanos queda vacia en sus CUATRO columnas (lat/lon mas las
    # dos que PR6 agrego: hovertext y el customdata que resuelve el clic).
    assert capas["clases"][1] == {"lat": [], "lon": [], "hovertext": [], "customdata": []}
    assert capas["sin_dato"]["lat"] == [3.0, 3.1, None]
    assert capas["marcados"]["lon"] == [-76.0, -76.1, None]


def test_capas_mapa_historico_splits_marked_vanos_by_class_and_paints_the_classless_black():
    """Paridad 01.4: un vano MARCADO se dibuja con el color de su clase KMeans, no
    con un color plano de "seleccionado". Un color plano encima de la clase congela
    lo que se ve: mover la ventana cambia la clase por debajo y el vano marcado sigue
    igual en pantalla. El marcado que NO tiene celda en la ventana (sin eventos, o
    ausente de la tabla) va a su propia capa, que el cuaderno pinta de NEGRO -- la
    ausencia de dato no es la clase mas baja."""
    geo_circuito = {
        "fids": ["VA", "VB", "VC"],
        "lat": [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1]],
        "lon": [[-75.0, -75.1], [-76.0, -76.1], [-77.0, -77.1]],
    }
    clases_por_fid = {"VA": 0, "VB": 3}  # VC no tiene celda en la ventana

    capas = capas_mapa_historico(geo_circuito, clases_por_fid, marcados=["VB", "VC"])

    assert capas["marcados_por_clase"][3]["lat"] == [2.0, 2.1, None]
    assert capas["marcados_por_clase"][0]["lat"] == []  # VA tiene clase 0 pero no esta marcado
    assert capas["marcados_sin_dato"]["lat"] == [3.0, 3.1, None]
    # El halo sigue llevando TODOS los marcados: es lo que va debajo, en blanco.
    assert capas["marcados"]["lat"] == [2.0, 2.1, None, 3.0, 3.1, None]
    assert capas["marcados_por_clase"][3]["customdata"] == ["VB", "VB", "VB"]


# --- Caja de seleccion: el rectangulo amarillo del vano marcado --------------


def _geo_cajas():
    return {
        "fids": ["VA", "VB", "VC"],
        # VB es un vano exactamente NORTE-SUR: su longitud no varia, asi que su
        # ancho a traves del trazo es CERO. VC corre a 45 grados exactos, que es
        # donde una caja alineada a los ejes se separa mas de la direccion real.
        "lat": [[1.0, 1.2], [2.0, 2.4], [3.0, 3.1]],
        "lon": [[-75.0, -75.4], [-76.0, -76.0], [-77.0, -77.1]],
    }


def _lados(anillo):
    """Los cuatro lados del anillo como vectores (dlon, dlat)."""
    return [(anillo[i + 1][0] - anillo[i][0], anillo[i + 1][1] - anillo[i][1])
            for i in range(4)]


def _distancia_al_trazo(punto, lon, lat):
    """Distancia con signo del punto a la RECTA del vano, en grados."""
    dlon, dlat = lon[-1] - lon[0], lat[-1] - lat[0]
    largo = math.hypot(dlon, dlat)
    return ((punto[0] - lon[0]) * -dlat + (punto[1] - lat[0]) * dlon) / largo


def test_cajas_seleccion_returns_one_box_per_marked_vano():
    """El resaltado del vano seleccionado es un rectangulo, como un `Polygon`
    GeoJSON que la capa `layout.map.layers` pinta debajo de las trazas. Un
    anillo de GeoJSON se CIERRA -- el ultimo vertice repite el primero --; sin
    eso MapLibre descarta el poligono en silencio y no se dibuja ninguna caja."""
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VA"], lado_minimo=0.02)

    assert cajas["type"] == "FeatureCollection"
    (feature,) = cajas["features"]
    assert feature["properties"]["fid"] == "VA"
    anillo = feature["geometry"]["coordinates"][0]
    assert feature["geometry"]["type"] == "Polygon"
    assert len(anillo) == 5
    assert anillo[0] == anillo[-1]


def test_cajas_seleccion_gira_la_caja_hasta_la_direccion_del_vano():
    """La caja va INCLINADA como el vano y no alineada a los ejes.

    Sobre un vano diagonal, el rectangulo min/max se sale por las dos esquinas
    que el trazo no toca y encierra tramos vecinos que no son los marcados; el
    usuario termina mirando un cuadro que abarca mas de lo que eligio.

    La prueba dura es contar coordenadas distintas: una caja alineada a los ejes
    solo tiene DOS longitudes y DOS latitudes; una girada tiene cuatro de cada.
    """
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VC"], lado_minimo=0.02)

    esquinas = cajas["features"][0]["geometry"]["coordinates"][0][:4]
    assert len({round(lon, 9) for lon, _ in esquinas}) == 4
    assert len({round(lat, 9) for _, lat in esquinas}) == 4
    assert [[round(v, 9) for v in p] for p in esquinas] == [
        [-76.992928932, 3.007071068],
        [-77.092928932, 3.107071068],
        [-77.107071068, 3.092928932],
        [-77.007071068, 2.992928932],
    ]


def test_cajas_seleccion_deja_los_lados_paralelos_y_perpendiculares_al_trazo():
    """Dos lados corren CON el vano y dos lo cruzan en angulo recto: es lo que
    hace que la caja se lea como el resaltado de ese trazo y no como un cuadro
    puesto encima."""
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VA"], lado_minimo=0.02)

    anillo = cajas["features"][0]["geometry"]["coordinates"][0]
    dlon, dlat = -0.4, 0.2
    paralelos = [abs(a * dlat - b * dlon) for a, b in _lados(anillo)]
    perpendiculares = [abs(a * dlon + b * dlat) for a, b in _lados(anillo)]
    assert sum(v < 1e-12 for v in paralelos) == 2
    assert sum(v < 1e-12 for v in perpendiculares) == 2


def test_cajas_seleccion_abre_lado_minimo_a_lado_y_lado_del_trazo():
    """A traves del vano el ancho es CERO -- un trazo no tiene grosor -- y sobre
    el mapa eso es una franja invisible. `lado_minimo` lo abre de forma SIMETRICA,
    asi que el trazo queda en el eje de la caja y no pegado a un borde."""
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VC"], lado_minimo=0.02)

    esquinas = cajas["features"][0]["geometry"]["coordinates"][0][:4]
    distancias = sorted(round(_distancia_al_trazo(p, [-77.0, -77.1], [3.0, 3.1]), 9)
                        for p in esquinas)
    assert distancias == [-0.01, -0.01, 0.01, 0.01]


def test_cajas_seleccion_de_un_vano_norte_sur_no_cambia_con_el_giro():
    """Un vano exactamente norte-sur ya corria sobre un eje, asi que girar la
    caja a su direccion la deja donde estaba. Se fija para que el giro no se
    cuele como un cambio en los vanos que ya estaban bien."""
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VB"], lado_minimo=0.001)

    anillo = cajas["features"][0]["geometry"]["coordinates"][0]
    lons = sorted({round(lon, 6) for lon, _ in anillo})
    lats = sorted({round(lat, 6) for _, lat in anillo})
    assert lons == [-76.0005, -75.9995]          # abierta a 0.001 alrededor de -76.0
    assert lats == [2.0, 2.4]                    # el lado que ya medía mas no se toca


def test_cajas_seleccion_adds_the_margin_on_every_side():
    """El margen despega la caja del trazo: sin el, el borde del rectangulo cae
    justo encima de la linea del vano y no se distingue cual es cual. Se agrega
    en el marco DEL VANO, asi que separa lo mismo por los cuatro lados."""
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VC"], lado_minimo=0.02,
                            margen=0.005)

    esquinas = cajas["features"][0]["geometry"]["coordinates"][0][:4]
    distancias = sorted(round(_distancia_al_trazo(p, [-77.0, -77.1], [3.0, 3.1]), 9)
                        for p in esquinas)
    assert distancias == [-0.015, -0.015, 0.015, 0.015]
    # A lo largo el trazo mide 0.141421 grados y la caja lo desborda 0.005 por
    # cada punta, asi que la diagonal sale de 0.151421 por 0.03.
    diagonal = max(math.dist(a, b) for a in esquinas for b in esquinas)
    assert round(diagonal, 6) == round(math.hypot(math.hypot(0.1, 0.1) + 0.01, 0.03), 6)


def test_cajas_seleccion_de_un_vano_sin_largo_vuelve_a_los_ejes():
    """277 de los 60.053 tramos del shapefile tienen sus dos vertices en el MISMO
    punto: no tienen direccion que seguir. Ahi la caja vuelve a alinearse con los
    ejes en vez de fallar o de inventarse un rumbo, que es lo unico honesto que
    se puede dibujar sobre un vano que no apunta a ninguna parte."""
    geo = {"fids": ["VP"], "lat": [[4.0, 4.0]], "lon": [[-75.0, -75.0]]}

    cajas = cajas_seleccion(geo, marcados=["VP"], lado_minimo=0.02)

    anillo = cajas["features"][0]["geometry"]["coordinates"][0]
    assert sorted({round(lon, 9) for lon, _ in anillo}) == [-75.01, -74.99]
    assert sorted({round(lat, 9) for _, lat in anillo}) == [3.99, 4.01]


def test_cajas_seleccion_follows_the_geometry_order_and_ignores_foreign_fids():
    """Recorre la geometria del circuito y no la seleccion: un fid marcado en OTRO
    circuito no tiene coordenadas aqui y no puede producir una caja. Sin esto, la
    seleccion arrastrada de un circuito anterior dibujaria cajas fantasma."""
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VC", "VA", "DE_OTRO_CIRCUITO"])

    assert [f["properties"]["fid"] for f in cajas["features"]] == ["VA", "VC"]


def test_cajas_seleccion_without_marked_vanos_is_an_empty_collection():
    """Sin seleccion la capa sigue existiendo pero no pinta nada. Devolver una
    coleccion VACIA y no `None` es lo que deja que el repintado sea siempre la
    misma escritura, sin quitar y volver a poner la capa del mapa."""
    assert cajas_seleccion(_geo_cajas(), marcados=[]) == {
        "type": "FeatureCollection",
        "features": [],
    }


def test_cajas_seleccion_on_a_circuit_without_geometry_is_empty():
    cajas = cajas_seleccion({"fids": [], "lat": [], "lon": []}, marcados=["VA"])

    assert cajas["features"] == []


# --- La caja, repartida por GRUPO de criticidad -----------------------------
#
# La caja de seleccion pasa de tener un color propio ("esto es lo que estoy
# mirando") a llevar el color del GRUPO KMeans del vano al 50% de opacidad. El
# recuadro deja de decir solo cual elegi y dice ademas en que grupo cayo, que es
# lo mismo que ya dice su linea: dos canales sobre el mismo dato, y el relleno se
# lee a un zoom en el que la linea ya no se distingue de sus vecinas.
#
# Una capa de `layout.map.layers` pinta con UN color, asi que hacen falta CINCO
# colecciones -- una por grupo mas la del vano marcado que en esa ventana no
# tiene celda -- por el mismo motivo por el que el mapa simulado lleva tres.
# Siempre las cinco, vacias incluidas: el repintado es una escritura de `source`
# por capa y nunca un quitar y poner capas, que en MapLibre reordena lo que hay
# debajo.


def test_cajas_seleccion_por_clase_reparte_cada_marcado_en_la_capa_de_su_grupo():
    cajas = cajas_seleccion_por_clase(
        _geo_cajas(), {"VA": 3, "VB": 0}, marcados=["VA", "VB"], lado_minimo=0.02)

    assert [f["properties"]["fid"] for f in cajas[3]["features"]] == ["VA"]
    assert [f["properties"]["fid"] for f in cajas[0]["features"]] == ["VB"]
    assert cajas[1]["features"] == [] and cajas[2]["features"] == []


def test_cajas_seleccion_por_clase_siempre_devuelve_las_cinco_capas():
    """Las cuatro clases mas `None`, presentes aunque no haya ni un marcado. El
    repintado escribe `source` sobre capas que ya existen; una clave ausente lo
    obligaria a decidir si crea la capa, y crear capas reordena MapLibre."""
    cajas = cajas_seleccion_por_clase(_geo_cajas(), {}, marcados=[])

    assert set(cajas) == {0, 1, 2, 3, None}
    assert all(c == {"type": "FeatureCollection", "features": []}
               for c in cajas.values())


def test_cajas_seleccion_por_clase_pone_bajo_none_al_marcado_sin_celda():
    """Un vano marcado SIN eventos en la ventana activa no tiene grupo, y eso no
    es el grupo mas bajo: es la ausencia del dato. Va a su propia capa, que el
    tablero pinta gris, y NO a la del grupo `Bajo`."""
    cajas = cajas_seleccion_por_clase(
        _geo_cajas(), {"VA": 2}, marcados=["VA", "VB"], lado_minimo=0.02)

    assert [f["properties"]["fid"] for f in cajas[None]["features"]] == ["VB"]
    assert cajas[0]["features"] == []


def test_cajas_seleccion_por_clase_dibuja_el_mismo_rectangulo_que_cajas_seleccion():
    """El reparto por color no puede cambiar la FORMA del recuadro.

    Los dos mapas del simulador y el mapa de 04 encierran el mismo vano, y dos
    rectangulos de distinto tamanio sobre el mismo tramo se leen como dos vanos.
    Por eso esto reusa `cajas_seleccion` en vez de repetir la geometria, y el
    test lo comprueba vertice a vertice.
    """
    geo = _geo_cajas()
    esperado = cajas_seleccion(geo, marcados=["VC"], lado_minimo=0.02, margen=0.001)

    cajas = cajas_seleccion_por_clase(
        geo, {"VC": 1}, marcados=["VC"], lado_minimo=0.02, margen=0.001)

    assert cajas[1] == esperado


def test_cajas_seleccion_por_clase_no_dibuja_los_vanos_con_eventos_sin_marcar():
    """Un vano con eventos que el usuario DESMARCO conserva el color y el ancho
    de su grupo en la linea, pero pierde el recuadro. Es la mitad del contrato
    que este reparto no puede romper: la clase esta en `clases_por_fid` y aun asi
    no produce caja si el fid no esta marcado."""
    cajas = cajas_seleccion_por_clase(
        _geo_cajas(), {"VA": 3, "VB": 3, "VC": 3}, marcados=["VB"], lado_minimo=0.02)

    assert [f["properties"]["fid"] for f in cajas[3]["features"]] == ["VB"]


# --- Nube KMeans (fila 1 col 3 en 01.4): celdas vano x ventana ---------------


def _tabla_nube():
    return pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1", "C2"],
            "FID_VANO": ["VA", "VB", "VA", "VZ"],
            "ventana_i": [0, 0, 1, 0],
            "num_eventos": [1, 5, 9, 3],
            "uiti_acumulado": [0.5, 2.5, 7.5, 1.0],
        }
    )


def test_nube_fondo_groups_every_cell_by_its_class():
    """El fondo de la nube es TODO el dataset y no depende de la seleccion: en 01.4
    el KMeans se ajusta una sola vez y elegir circuito o vanos solo cambia que se
    resalta, nunca donde caen las fronteras."""
    tabla = _tabla_nube()

    capas = nube_fondo(tabla, np.array([0, 2, 3, 0]))

    assert len(capas) == 4
    assert capas[0]["x"] == [1, 3] and capas[0]["y"] == [0.5, 1.0]
    assert capas[2]["x"] == [5] and capas[2]["y"] == [2.5]
    assert capas[1] == {"x": [], "y": []}


def test_nube_seleccion_takes_only_the_marked_cells_of_the_active_window():
    tabla = _tabla_nube()
    mask_ventana = (tabla["CIRCUITO"] == "C1").to_numpy() & (tabla["ventana_i"] == 0).to_numpy()

    punto = nube_seleccion(tabla, np.array([0, 2, 3, 0]), mask_ventana=mask_ventana,
                           marcados=["VB"])

    assert punto == {"x": [5], "y": [2.5], "clase": [2], "fid": ["VB"]}


def test_nube_seleccion_without_marked_vanos_takes_the_whole_circuit_window():
    """Mismo criterio que el mapa simulado y el ranking: sin vanos marcados, el grano
    es el circuito completo en esa ventana, no un panel vacio."""
    tabla = _tabla_nube()
    mask_ventana = (tabla["CIRCUITO"] == "C1").to_numpy() & (tabla["ventana_i"] == 0).to_numpy()

    punto = nube_seleccion(tabla, np.array([0, 2, 3, 0]), mask_ventana=mask_ventana)

    assert punto["fid"] == ["VA", "VB"]
    assert punto["clase"] == [0, 2]


def test_nube_seleccion_ignores_a_marked_vano_with_no_cell_in_the_window():
    """El vano marcado sin celda en la ventana no tiene punto que dibujar en la nube
    (no existe la fila). Su señal es el NEGRO del mapa, no un punto inventado."""
    tabla = _tabla_nube()
    mask_ventana = (tabla["CIRCUITO"] == "C1").to_numpy() & (tabla["ventana_i"] == 0).to_numpy()

    punto = nube_seleccion(tabla, np.array([0, 2, 3, 0]), mask_ventana=mask_ventana,
                           marcados=["VB", "FANTASMA"])

    assert punto["fid"] == ["VB"]


# --- PR6: hover/customdata, recentrado y seleccion por clic -----------------


def test_capas_mapa_historico_carries_fid_and_label_on_every_point():
    """01.4 resolves a map click to a vano by reading the clicked point's
    `customdata`, never by point index -- the segments travel concatenated
    with a `None` separator, so that index shifts with the window. 01.5
    needs the same channel, which means `customdata` has to be exactly as
    long as lat/lon INCLUDING the separator slot, or Plotly misaligns the
    rest of the trace."""
    geo_circuito = {
        "fids": ["VA", "VB", "VC"],
        "lat": [[1.0, 1.1, 1.2], [2.0, 2.1], [3.0, 3.1]],
        "lon": [[-75.0, -75.1, -75.2], [-76.0, -76.1], [-77.0, -77.1]],
    }
    clases_por_fid = {"VA": 0, "VB": 3}

    capas = capas_mapa_historico(
        geo_circuito,
        clases_por_fid,
        marcados=["VB"],
        etiquetas_por_fid={"VA": "vano A", "VB": "vano B", "VC": "vano C"},
    )

    for capa in (capas["clases"][0], capas["clases"][3], capas["sin_dato"], capas["marcados"]):
        assert len(capa["customdata"]) == len(capa["lat"]) == len(capa["lon"])
        assert len(capa["hovertext"]) == len(capa["lat"])

    # Tres puntos mas el separador, y el fid viaja tambien en el separador.
    assert capas["clases"][0]["customdata"] == ["VA"] * 4
    # El separador NO lleva etiqueta: es un hueco, no un punto con hover.
    assert capas["clases"][0]["hovertext"] == ["vano A", "vano A", "vano A", ""]
    assert capas["sin_dato"]["customdata"] == ["VC"] * 3
    assert capas["marcados"]["customdata"] == ["VB"] * 3


def test_capas_mapa_historico_labels_default_to_empty_when_not_given():
    """`etiquetas_por_fid` es opcional: sin ella el hover queda vacio pero
    `customdata` sigue estando, porque el clic no depende del texto."""
    capas = capas_mapa_historico(
        {"fids": ["VA"], "lat": [[1.0, 1.1]], "lon": [[-75.0, -75.1]]}, {"VA": 2},
    )
    assert capas["clases"][2]["hovertext"] == ["", "", ""]
    assert capas["clases"][2]["customdata"] == ["VA"] * 3


def test_capas_mapa_historico_marks_both_ends_of_every_vano_with_a_horizontal_dash():
    """01's map draws a black horizontal dash on BOTH ends of every vano so the
    extent of each one is readable where two of them meet. It cannot be a marker:
    `marker.symbol` on Scattermap only accepts the map style's sprite icons and
    there is no horizontal-line glyph there. So the dash is two extra 2-point
    segments appended to the SAME layer, which inherit its colour and width."""
    geo_circuito = {"fids": ["VA"], "lat": [[1.0, 1.1]], "lon": [[-75.0, -75.1]]}

    capas = capas_mapa_historico(
        geo_circuito, {"VA": 0}, marca_extremos=0.001,
        etiquetas_por_fid={"VA": "vano A"},
    )

    capa = capas["clases"][0]
    # La polilinea y su separador, y despues un guion por extremo: mismo lat en
    # sus dos puntos (es horizontal), lon corrido media marca a cada lado.
    assert capa["lat"] == [1.0, 1.1, None, 1.0, 1.0, None, 1.1, 1.1, None]
    assert capa["lon"] == [
        -75.0, -75.1, None, -75.001, -74.999, None, -75.101, -75.099, None,
    ]
    # Las cuatro columnas siguen midiendo lo mismo, o Plotly desalinea la traza.
    assert len(capa["customdata"]) == len(capa["hovertext"]) == len(capa["lat"]) == 9
    assert capa["customdata"] == ["VA"] * 9


def test_capas_mapa_historico_dash_points_carry_no_hover_label():
    """El guion NO repite la etiqueta del vano. Medido sobre MVLINSEC: el peor
    circuito pasa de 4.131 a 12.393 puntos al marcar los extremos, y repetir ahi
    una etiqueta de ~130 caracteres agrega ~1 MB a una sola rafaga del comm del
    widget -- por encima del `iopub_data_rate_limit` de 1 MB/s de ipykernel, que
    descarta el mensaje y deja la figura en blanco. No se pierde nada: el vertice
    real del extremo esta en el centro del guion y si lleva la etiqueta."""
    capas = capas_mapa_historico(
        {"fids": ["VA"], "lat": [[1.0, 1.1]], "lon": [[-75.0, -75.1]]}, {"VA": 0},
        marca_extremos=0.001, etiquetas_por_fid={"VA": "vano A"},
    )

    assert capas["clases"][0]["hovertext"] == ["vano A", "vano A", "", *[""] * 6]


def test_capas_mapa_historico_marks_the_ends_of_vanos_without_events_too():
    """Los guiones van en TODOS los vanos, tengan o no eventos en la ventana: son
    la extension del vano, no una senial de su clase."""
    capas = capas_mapa_historico(
        {"fids": ["VA", "VB"], "lat": [[1.0, 1.1], [2.0, 2.1]],
         "lon": [[-75.0, -75.1], [-76.0, -76.1]]},
        {"VA": 0}, marcados=["VB"], marca_extremos=0.001,
    )

    for capa in (capas["clases"][0], capas["sin_dato"], capas["marcados"],
                 capas["marcados_sin_dato"]):
        assert len(capa["lat"]) == 9, capa


def test_capas_mapa_historico_without_marca_extremos_keeps_the_bare_polyline():
    """El parametro es opcional y su default no dibuja ningun guion: el panel web
    densifica y marca en el navegador, donde los puntos no viajan por el comm."""
    capas = capas_mapa_historico(
        {"fids": ["VA"], "lat": [[1.0, 1.1]], "lon": [[-75.0, -75.1]]}, {"VA": 0},
    )

    assert capas["clases"][0]["lat"] == [1.0, 1.1, None]


def test_capas_mapa_historico_densifies_so_hover_lands_anywhere_on_the_vano():
    """El hover de una traza de lineas en Scattermap se resuelve contra los
    VERTICES, no contra la linea: plotly mide la distancia del cursor a cada
    punto y descarta lo que quede a mas de `hoverdistance`. Los tramos de
    MVLINSEC traen EXACTAMENTE dos vertices, asi que a zoom alto el centro de
    un vano no tiene ninguno cerca -- no muestra etiqueta, y como plotly solo
    convierte un clic en evento donde hay hover, tampoco se puede marcar
    tocandolo ahi."""
    largo = 0.01  # ~1,1 km: a zoom 14, 30 px son 143 m, asi que hacen falta cortes
    geo_circuito = {"fids": ["VA"], "lat": [[1.0, 1.0]], "lon": [[-75.0, -75.0 + largo]]}

    capas = capas_mapa_historico(geo_circuito, {"VA": 0}, paso_densificado=0.00022)

    lats = [v for v in capas["clases"][0]["lat"] if v is not None]
    lons = [v for v in capas["clases"][0]["lon"] if v is not None]
    assert len(lons) > 40, len(lons)
    # Los extremos siguen siendo los originales: densificar interpola, no mueve.
    assert lons[0] == pytest.approx(-75.0) and lons[-1] == pytest.approx(-75.0 + largo)
    assert all(v == pytest.approx(1.0) for v in lats)
    # Y ningun hueco mayor al paso pedido, que es lo que da el hover continuo.
    saltos = [abs(b - a) for a, b in zip(lons, lons[1:])]
    assert max(saltos) <= 0.00022 + 1e-12, max(saltos)


def test_capas_mapa_historico_keeps_every_column_aligned_when_densifying():
    """Las cuatro columnas tienen que seguir midiendo lo mismo: si `customdata`
    se desfasa de lat/lon, Plotly desalinea el resto de la traza y el clic
    devuelve el vano equivocado."""
    capas = capas_mapa_historico(
        {"fids": ["VA", "VB"], "lat": [[1.0, 1.02], [2.0, 2.01]],
         "lon": [[-75.0, -75.0], [-76.0, -76.0]]},
        {"VA": 0}, marcados=["VB"], paso_densificado=0.005, marca_extremos=0.001,
    )

    for capa in (capas["clases"][0], capas["sin_dato"], capas["marcados"]):
        assert len(capa["lat"]) == len(capa["lon"]) == len(capa["customdata"]) == len(
            capa["hovertext"])


def test_capas_mapa_historico_carries_extra_columns_in_customdata():
    """Para que el tooltip no repita una etiqueta de ~130 caracteres en CADA
    punto, el hover pasa a `hovertemplate` y lo que viaja por punto son los
    datos crudos del vano. Medido sobre el peor circuito, eso baja la capa de
    2,40 MB a 0,66 MB, y es lo que hace que densificar salga mas barato que lo
    que se mandaba antes. El fid queda SIEMPRE primero: es el canal que
    convierte un clic en un vano."""
    capas = capas_mapa_historico(
        {"fids": ["VA"], "lat": [[1.0, 1.1]], "lon": [[-75.0, -75.1]]}, {"VA": 0},
        datos_por_fid={"VA": (12.5, 3)},
    )

    assert capas["clases"][0]["customdata"] == [["VA", 12.5, 3]] * 3


def test_capas_mapa_historico_without_extra_columns_keeps_the_bare_fid():
    """`datos_por_fid` es opcional: sin el, `customdata` sigue siendo el fid
    suelto, como lo esperan los llamadores que ya existian."""
    capas = capas_mapa_historico(
        {"fids": ["VA"], "lat": [[1.0, 1.1]], "lon": [[-75.0, -75.1]]}, {"VA": 0})

    assert capas["clases"][0]["customdata"] == ["VA", "VA", "VA"]


def test_fid_de_punto_reads_the_fid_from_a_customdata_row():
    """Con columnas extra, `customdata[i]` es una fila y no un escalar; el fid
    sigue siendo su primer elemento."""
    from chec_local_interpreter.ventanas_015 import fid_de_punto

    assert fid_de_punto([["VA", 1.0, 2], ["VB", 3.0, 4]], [1]) == "VB"
    assert fid_de_punto(["VA", "VB"], [0]) == "VA"


def _tamanio_proyectado(bounds, zoom, *, tile=512):
    """El bounding box del circuito, en pixeles, bajo la proyeccion Web Mercator
    que usa MapLibre (teselas de 512 px). Verificado contra el navegador: para
    DON23L13 a zoom 10.1553 predice 328,9 x 389,9 px y Chrome midio 329 x 390."""
    import math

    def merc_y(lat):
        r = math.radians(lat)
        return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2

    mundo = tile * 2 ** zoom
    return (abs(bounds[3] - bounds[2]) / 360 * mundo,
            abs(merc_y(bounds[0]) - merc_y(bounds[1])) * mundo)


def test_centro_y_zoom_fits_the_circuit_inside_a_wide_short_viewport():
    """Con el tamanio del mapa en pixeles, el encuadre tiene que meter el circuito
    ENTERO adentro -- las dos dimensiones, no solo una.

    La formula anterior derivaba el zoom del span mayor en grados y no sabia nada
    del viewport. Al pasar la figura a ancho completo el mapa quedo en 1553 x 328
    px y medido en el navegador el circuito ocupaba el 21% del ancho y el 119% del
    alto: centrado, pero recortado arriba y abajo. Un grado de latitud y uno de
    longitud no miden lo mismo en pantalla, y menos en un viewport apaisado."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    ancho, alto = 1553, 328
    # DON23L13 y AGU23L15: los dos que se recortaban. bounds = [lat_min, lat_max,
    # lon_min, lon_max].
    for bounds in ([5.49022, 5.68869, -74.80587, -74.66823],
                   [5.02, 5.29, -75.72, -75.63]):
        vista = centro_y_zoom(bounds, ancho_px=ancho, alto_px=alto)

        ancho_circ, alto_circ = _tamanio_proyectado(bounds, vista["zoom"])
        assert ancho_circ <= ancho, (bounds, ancho_circ)
        assert alto_circ <= alto, (bounds, alto_circ)
        # Y que ENTRE no alcanza: tiene que LLENAR la dimension que manda, o el
        # circuito volveria a verse diminuto en el medio.
        assert max(ancho_circ / ancho, alto_circ / alto) > 0.8, (bounds, ancho_circ, alto_circ)


def test_centro_y_zoom_keeps_the_center_of_the_bounding_box():
    """El centro no depende del viewport: solo el zoom."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    bounds = [5.0, 5.2, -75.9, -75.7]
    con_px = centro_y_zoom(bounds, ancho_px=1553, alto_px=328)

    assert con_px["center"] == {"lat": 5.1, "lon": -75.80000000000001}


def test_centro_y_zoom_without_pixel_size_keeps_the_014_formula():
    """El tamanio del viewport es opcional: sin el, la formula historica de 01.4.
    El cuaderno no siempre lo conoce -- con `autosize` el ancho lo decide el
    navegador -- y adivinarlo seria peor que el encuadre aproximado de siempre."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    bounds = [5.0, 5.2, -75.9, -75.7]

    assert centro_y_zoom(bounds)["zoom"] == pytest.approx(10.4137, abs=1e-3)


def test_centro_y_zoom_can_frame_with_the_height_alone():
    """El widget del cuaderno sabe su alto exacto (`height` por el dominio del
    subplot) pero NO su ancho: con `autosize` lo decide el navegador. Encuadrar
    solo por el alto es lo que evita el recorte vertical, que era el defecto;
    que sobre mapa a los lados es el mal menor y ademas se puede paneár."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    bounds = [5.49022, 5.68869, -74.80587, -74.66823]
    alto = 452

    vista = centro_y_zoom(bounds, alto_px=alto)

    _ancho_circ, alto_circ = _tamanio_proyectado(bounds, vista["zoom"])
    assert alto_circ <= alto
    assert alto_circ / alto > 0.8


def test_centro_y_zoom_never_zooms_past_the_tile_limit():
    """Un circuito de un solo vano pediria un zoom sin fin: sigue acotado."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    vista = centro_y_zoom([5.10000, 5.10001, -75.5, -75.49999],
                          ancho_px=1553, alto_px=328)

    assert vista["zoom"] <= 15.0


def test_centro_y_zoom_frames_the_circuit_like_014():
    """Puerto exacto de la formula de 01.4 (celda 7, `map.center`/`map.zoom`):
    centro en el medio del bounding box y zoom por el span mayor, acotado a
    [9, 15]. Un circuito pequenio se acerca; uno enorme no pasa de 9."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    # bounds = [lat_min, lat_max, lon_min, lon_max]
    vista = centro_y_zoom([5.0, 5.2, -75.6, -75.2])
    assert vista["center"] == {"lat": 5.1, "lon": -75.4}
    assert 9.0 <= vista["zoom"] <= 15.0
    # 360/0.4 -> log2 ~= 9.81, menos 0.4 -> 9.41
    assert vista["zoom"] == pytest.approx(9.4139, abs=1e-3)

    # Un circuito diminuto se topa con el techo, no se va a zoom 30.
    assert centro_y_zoom([5.0, 5.00001, -75.0, -75.00001])["zoom"] == 15.0
    # Uno que cubre medio mundo se topa con el piso.
    assert centro_y_zoom([-40.0, 40.0, -100.0, 100.0])["zoom"] == 9.0


def test_centro_y_zoom_rejects_missing_bounds():
    """Sin bounds no hay a donde centrar: devuelve None en vez de inventar
    un centro, para que el llamador deje la vista como estaba."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    assert centro_y_zoom(None) is None
    assert centro_y_zoom([]) is None


def test_fid_de_punto_reads_customdata_not_the_index():
    """El clic devuelve indices de punto dentro de la traza; el fid sale de
    `customdata` en esa posicion. Fuera de rango o sin customdata devuelve
    None en vez de un fid equivocado."""
    from chec_local_interpreter.ventanas_015 import fid_de_punto

    assert fid_de_punto(["VA", "VA", "VA", "VB"], [3]) == "VB"
    assert fid_de_punto(["VA", "VA"], [0]) == "VA"
    assert fid_de_punto(["VA"], []) is None
    assert fid_de_punto(None, [0]) is None
    assert fid_de_punto(["VA"], [7]) is None


# --- Frontera KMeans (Voronoi), evolucion temporal y reparto por grupo -------


def test_frontera_kmeans_partitions_the_plane_by_nearest_centroid():
    """La frontera es el diagrama de Voronoi de los centroides: cada celda de la
    malla toma la clase del centroide mas cercano, con la MISMA funcion que
    clasifica a los vanos. Si se dibujara con otra regla, el contorno diria una
    cosa y los puntos encima otra."""
    from chec_impacto.models.criticality_assignment import Geometria
    from chec_local_interpreter.ventanas_015 import frontera_kmeans

    geometria = Geometria(
        logs=(False, False),
        offset=np.array([0.0, 0.0]),
        scale=np.array([1.0, 1.0]),
        centroides=np.array([[0.0, 0.0], [10.0, 10.0], [20.0, 20.0], [30.0, 30.0]]),
    )

    frontera = frontera_kmeans(geometria, x_min=0.0, x_max=30.0, y_min=0.0, y_max=30.0, n=4)

    assert len(frontera["x"]) == 4 and len(frontera["y"]) == 4
    assert np.asarray(frontera["z"]).shape == (4, 4)  # z[fila_y][columna_x]
    assert frontera["z"][0][0] == 0  # esquina (0,0) -> centroide 0
    assert frontera["z"][-1][-1] == 3  # esquina (30,30) -> centroide 3


def test_frontera_kmeans_spaces_a_logged_axis_geometrically():
    """Un eje logaritmico con malla lineal deja casi todos los puntos apretados en
    la ultima decada y la frontera sale escalonada donde mas se mira."""
    from chec_impacto.models.criticality_assignment import Geometria
    from chec_local_interpreter.ventanas_015 import frontera_kmeans

    geometria = Geometria(
        logs=(False, True),
        offset=np.array([0.0, 0.0]),
        scale=np.array([1.0, 1.0]),
        centroides=np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]),
    )

    frontera = frontera_kmeans(geometria, x_min=1.0, x_max=4.0, y_min=1.0, y_max=1000.0, n=4)

    assert frontera["y"] == pytest.approx([1.0, 10.0, 100.0, 1000.0])
    assert frontera["x"] == pytest.approx([1.0, 2.0, 3.0, 4.0])  # el eje lineal no


def _tabla_series():
    return pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1", "C2"],
            "FID_VANO": ["VA", "VA", "VB", "VZ"],
            "ventana_i": [0, 2, 0, 0],
            "num_eventos": [1, 5, 9, 3],
            "uiti_acumulado": [0.5, 2.5, 7.5, 1.0],
        }
    )


def test_series_temporal_vanos_fills_windows_without_a_cell_with_zero():
    """El vano VA no tiene celda en la ventana 1, y eso vale CERO, no un hueco.

    `TABLA` se arma agregando EVENTOS: un vano sin fila en una ventana no es un vano
    sin medir, es un vano sin eventos, y sin eventos el UITI acumulado de esa ventana
    es cero. Con `None` la linea se partia y la secuencia de ventanas se leia como si
    faltara informacion, cuando lo que hay es un cero."""
    from chec_local_interpreter.ventanas_015 import series_temporal_vanos

    series = series_temporal_vanos(_tabla_series(), circuito="C1", fids=["VA"], n_ventanas=3)

    assert len(series) == 1
    assert series[0]["fid"] == "VA"
    assert series[0]["x"] == [0, 1, 2]
    assert series[0]["uiti"] == [0.5, 0.0, 2.5]
    assert series[0]["eventos"] == [1, 0, 5]


def test_series_temporal_vanos_covers_every_window_even_with_no_cells_at_all():
    """La secuencia completa de ventanas se dibuja igual: un vano sin una sola celda
    da una linea en cero de punta a punta, que es lo que dice el dato."""
    from chec_local_interpreter.ventanas_015 import series_temporal_vanos

    series = series_temporal_vanos(_tabla_series(), circuito="C1",
                                   fids=["SIN_EVENTOS"], n_ventanas=4)

    assert series[0]["x"] == [0, 1, 2, 3]
    assert series[0]["uiti"] == [0.0, 0.0, 0.0, 0.0]
    assert series[0]["eventos"] == [0, 0, 0, 0]


def test_series_temporal_vanos_keeps_the_requested_order_and_ignores_other_circuits():
    from chec_local_interpreter.ventanas_015 import series_temporal_vanos

    series = series_temporal_vanos(_tabla_series(), circuito="C1", fids=["VB", "VA"],
                                   n_ventanas=1)

    assert [s["fid"] for s in series] == ["VB", "VA"]
    assert series[0]["uiti"] == [7.5]


def test_reparto_por_clase_describes_only_the_marked_vanos():
    """Regla de 01.4, citada: sin vanos marcados el reparto queda VACIO, no cae al
    circuito entero. Un reparto de miles de vanos y otro de tres se dibujan igual
    pero no dicen lo mismo, y nada en el violin los distingue."""
    from chec_local_interpreter.ventanas_015 import reparto_por_clase

    tabla = _tabla_series()
    mask_ventana = (tabla["CIRCUITO"] == "C1").to_numpy() & (tabla["ventana_i"] == 0).to_numpy()
    clases = np.array([0, 3, 2, 1])

    reparto = reparto_por_clase(tabla, clases, mask_ventana=mask_ventana, marcados=["VB"])
    assert reparto[2] == {"uiti": [7.5], "eventos": [9]}
    assert reparto[0] == {"uiti": [], "eventos": []}

    vacio = reparto_por_clase(tabla, clases, mask_ventana=mask_ventana, marcados=[])
    assert all(grupo == {"uiti": [], "eventos": []} for grupo in vacio)


def test_nube_fondo_subsamples_deterministically_above_the_cap():
    """111.231 celdas en un panel de ~400x300 px son puro sobredibujo, y cada punto
    viaja al navegador por el comm del widget -- 1,2 MB de coordenadas en una sola
    rafaga, por encima del `iopub_data_rate_limit` de 1 MB/s que ipykernel trae por
    defecto. Se submuestrea con semilla FIJA: dos corridas dibujan la misma nube."""
    tabla = pd.DataFrame(
        {
            "CIRCUITO": ["C1"] * 100,
            "FID_VANO": [f"V{i}" for i in range(100)],
            "ventana_i": [0] * 100,
            "num_eventos": list(range(100)),
            "uiti_acumulado": [float(i) for i in range(100)],
        }
    )
    clases = np.array([i % 4 for i in range(100)])

    capas = nube_fondo(tabla, clases, maximo=40)
    otra = nube_fondo(tabla, clases, maximo=40)

    assert sum(len(c["x"]) for c in capas) == 40
    assert [c["x"] for c in capas] == [c["x"] for c in otra]  # misma semilla, misma nube


def test_nube_fondo_draws_everything_below_the_cap():
    tabla = pd.DataFrame(
        {
            "CIRCUITO": ["C1"] * 4,
            "FID_VANO": ["VA", "VB", "VC", "VD"],
            "ventana_i": [0, 0, 0, 0],
            "num_eventos": [1, 2, 3, 4],
            "uiti_acumulado": [0.5, 1.5, 2.5, 3.5],
        }
    )

    capas = nube_fondo(tabla, np.array([0, 0, 1, 1]), maximo=40)

    assert sum(len(c["x"]) for c in capas) == 4
    assert capas[0]["x"] == [1, 2]








def _series_de_prueba():
    return [
        {"fid": "VA", "x": [0, 1, 2],
         "uiti": [1.0, None, 300.0], "eventos": [2, None, 3]},
        {"fid": "VB", "x": [0, 1, 2],
         "uiti": [None, None, None], "eventos": [None, None, None]},
    ]


def _clases_falsas(n_obs, u):
    """Una clase por punto, derivada del UITI para que el orden sea predecible."""
    clase = np.where(np.asarray(u) > 100.0, 3, 0)
    return clase, 0


def test_clases_de_series_gives_one_class_per_drawn_point():
    """El punto de la serie se pinta con el grupo de riesgo de ESE vano en ESA
    ventana, igual que en 03 y 04: la linea dice de que vano es la serie y el
    punto dice en que grupo cayo. Son dos codigos distintos sobre el mismo dato,
    y separarlos por canal -- trazo contra relleno -- es lo que los hace legibles
    a la vez."""
    clases = clases_de_series(_series_de_prueba(), cargar_clases=_clases_falsas)

    assert clases[0] == [0, None, 3]


def test_a_window_without_a_cell_has_no_class_at_all():
    """Sin celda no hay clase, y eso NO es el grupo mas bajo: es la ausencia del
    dato. El panel lo pinta gris, que es distinto del color del grupo 0."""
    clases = clases_de_series(_series_de_prueba(), cargar_clases=_clases_falsas)

    assert clases[0][1] is None
    assert clases[1] == [None, None, None]


def test_every_point_of_every_series_is_classified_in_a_single_call():
    """Con cinco vanos por once ventanas son cincuenta y cinco puntos: clasificarlos
    de a uno serian cincuenta y cinco llamadas a la geometria de 01.4 en cada
    repintado, y el repintado corre en cada clic del mapa."""
    llamadas = []

    def _contar(n_obs, u):
        llamadas.append(len(n_obs))
        return _clases_falsas(n_obs, u)

    clases_de_series(_series_de_prueba(), cargar_clases=_contar)

    assert llamadas == [2]   # los dos unicos puntos con celda, en UNA sola llamada


def test_no_cells_at_all_never_touches_the_geometry():
    """Sin ningun punto con celda no hay nada que clasificar, y llamar igual
    obligaria a la geometria a resolver un arreglo vacio."""
    llamadas = []

    def _contar(n_obs, u):
        llamadas.append(len(n_obs))
        return _clases_falsas(n_obs, u)

    clases = clases_de_series([_series_de_prueba()[1]], cargar_clases=_contar)

    assert llamadas == []
    assert clases == [[None, None, None]]


def test_an_empty_series_list_is_answered_without_work():
    assert clases_de_series([], cargar_clases=_clases_falsas) == []


# --- El recuadro del mapa SIMULADO: tres colores, uno por desenlace -------------------


def _tabla_simulada(filas):
    """La tabla que devuelve `simular_bolsas`, recortada a lo que la caja mira."""
    return pd.DataFrame(
        [{"FID_VANO": fid, "base_clase_idx": base, "simulado_clase_idx": sim,
          "delta_riesgo_ordinal": sim - base} for fid, base, sim in filas]
    )


def test_cajas_por_cambio_de_grupo_separates_the_three_outcomes():
    """El recuadro del mapa simulado ya no dice "este es el vano que elegi" --
    eso lo dice el del mapa base -- sino QUE LE PASO al vano: bajo de grupo,
    se quedo igual, o subio. Son tres capas y no una porque una capa de
    `layout.map.layers` lleva UN color: pintar tres desenlaces en la misma
    capa obligaria a elegir cual de los tres colores miente."""
    tabla = _tabla_simulada([("VA", 2, 0), ("VB", 1, 1), ("VC", 0, 3)])

    cajas = cajas_por_cambio_de_grupo(_geo_cajas(), tabla, marcados=["VA", "VB", "VC"])

    assert [f["properties"]["fid"] for f in cajas["mejora"]["features"]] == ["VA"]
    assert [f["properties"]["fid"] for f in cajas["igual"]["features"]] == ["VB"]
    assert [f["properties"]["fid"] for f in cajas["empeora"]["features"]] == ["VC"]


def test_cajas_por_cambio_de_grupo_only_boxes_the_marked_vanos():
    """La tabla trae una fila por bolsa de la seleccion simulada, pero el
    recuadro senala lo que el usuario ESTA estudiando. Un vano puntuado que no
    esta marcado no lleva caja: si la llevara, marcar un vano y simular todo el
    circuito llenaria el mapa de rectangulos."""
    tabla = _tabla_simulada([("VA", 2, 0), ("VB", 1, 1)])

    cajas = cajas_por_cambio_de_grupo(_geo_cajas(), tabla, marcados=["VA"])

    assert [f["properties"]["fid"] for f in cajas["mejora"]["features"]] == ["VA"]
    assert cajas["igual"]["features"] == []


def test_a_marked_vano_absent_from_the_table_gets_no_box_at_all():
    """Un vano marcado SIN celda en la ventana activa no lo puntuo la simulacion:
    no tiene grupo base ni grupo simulado, asi que no hay desenlace que pintar.
    Meterlo en "igual" seria afirmar que no cambio, que es justamente lo que
    nadie midio."""
    cajas = cajas_por_cambio_de_grupo(
        _geo_cajas(), _tabla_simulada([("VA", 1, 1)]), marcados=["VA", "VC"]
    )

    assert [f["properties"]["fid"] for f in cajas["igual"]["features"]] == ["VA"]
    assert all(
        "VC" not in [f["properties"]["fid"] for f in coleccion["features"]]
        for coleccion in cajas.values()
    )


def test_cajas_por_cambio_de_grupo_keeps_the_three_keys_when_empty():
    """Las tres capas se escriben SIEMPRE, tambien vacias: el repintado es una
    sola escritura por capa y no un quitar y poner capas del mapa, que en
    MapLibre reordena lo que hay debajo."""
    cajas = cajas_por_cambio_de_grupo(_geo_cajas(), _tabla_simulada([]), marcados=["VA"])

    assert sorted(cajas) == ["empeora", "igual", "mejora"]
    assert all(c["type"] == "FeatureCollection" and c["features"] == []
               for c in cajas.values())


def test_cajas_por_cambio_de_grupo_uses_the_same_geometry_as_the_base_box():
    """Mismo rectangulo que el del mapa base, INCLINACION incluida: los dos mapas
    comparten geometria, y dos cajas de forma distinta sobre el mismo vano se
    leerian como dos vanos.

    Se prueba sobre VC, que corre en diagonal, y no sobre un vano norte-sur: ahi
    el rectangulo min/max y el girado coinciden, asi que la prueba pasaria aunque
    el mapa simulado se hubiera quedado con la caja alineada a los ejes."""
    tabla = _tabla_simulada([("VC", 1, 1)])

    cajas = cajas_por_cambio_de_grupo(
        _geo_cajas(), tabla, marcados=["VC"], lado_minimo=0.02, margen=0.005
    )
    base = cajas_seleccion(_geo_cajas(), marcados=["VC"], lado_minimo=0.02, margen=0.005)

    assert cajas["igual"]["features"] == base["features"]
    esquinas = cajas["igual"]["features"][0]["geometry"]["coordinates"][0][:4]
    assert len({round(lon, 9) for lon, _ in esquinas}) == 4


# --- El encuadre del mapa simulado sobre los vanos elegidos ---------------------------


def test_bounds_de_fids_frames_only_the_given_vanos():
    """El mapa simulado se centra sobre los vanos que se estan estudiando y no
    sobre el circuito entero: despues de simular, la pregunta es que le paso a
    ESOS vanos, y buscarlos otra vez dentro del garabato completo es trabajo
    que el tablero puede ahorrar."""
    assert bounds_de_fids(_geo_cajas(), ["VA"]) == (1.0, 1.2, -75.4, -75.0)


def test_bounds_de_fids_covers_every_vano_of_the_selection():
    """Con varios vanos el encuadre los tiene que contener a TODOS: encuadrar
    sobre el primero dejaria los demas fuera de pantalla."""
    assert bounds_de_fids(_geo_cajas(), ["VA", "VC"]) == (1.0, 3.1, -77.1, -75.0)


def test_bounds_de_fids_without_coordinates_is_none():
    """Sin fids -- o con fids de otro circuito -- devuelve None para que el
    llamador deje el encuadre donde estaba, en vez de centrar en un punto
    inventado. Es el mismo contrato que `centro_y_zoom` con bounds vacios."""
    assert bounds_de_fids(_geo_cajas(), []) is None
    assert bounds_de_fids(_geo_cajas(), ["DE_OTRO_CIRCUITO"]) is None


def test_clases_de_series_gives_no_class_to_a_window_with_zero_events():
    """Cero eventos no es el grupo mas bajo: es la ausencia del dato. La geometria de
    01.4 vive en (n_obs, log10 u), y log10(0) no existe, asi que ese punto no se puede
    clasificar -- el panel lo pinta gris."""
    from chec_local_interpreter.ventanas_015 import clases_de_series

    series = [{"x": [0, 1], "uiti": [0.0, 2.5], "eventos": [0, 5]}]
    llamadas = []

    def _clases(n_obs, u, **kwargs):
        llamadas.append(len(n_obs))
        return np.zeros(len(n_obs), dtype=int), 0

    clases = clases_de_series(series, cargar_clases=_clases)

    assert clases == [[None, 0]]
    assert llamadas == [1]  # la ventana en cero no se manda a clasificar


# --- Que vanos entran al diagnostico del cuaderno 06 -----------------------------------
# El boton "Diagnostico" tiene DOS modos y no uno con relleno: sin nada marcado describe
# el top del circuito por UITI, y con algo marcado describe EXACTAMENTE eso, sin
# completar el cupo. La regla vive aqui y no en la celda del cuaderno porque es la
# decision de QUE se diagnostica, no cableado de widgets: se puede equivocar en silencio
# y por eso se prueba con datos, no leyendo el fuente.


def _datos_ventana():
    """UITI y eventos por vano en UNA ventana, como los arma `DATOS_VENTANA`."""
    return {
        "V1": (10.0, 3),
        "V2": (9.0, 2),
        "V3": (8.0, 5),
        "V4": (7.0, 1),
        "V5": (6.0, 4),
    }


def test_el_diagnostico_sin_marcados_toma_el_top_por_uiti_y_cuenta_lo_que_deja_fuera():
    """Sin nada marcado la pregunta es por donde empezar en el circuito, y la respuesta
    son los de mayor UITI. Lo que no cabe se CUENTA: una lista de tres sobre un circuito
    con cinco vanos con eventos se lee como que el circuito tiene tres."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    elegidos = vanos_para_diagnostico(
        _datos_ventana(), ["V1", "V2", "V3", "V4", "V5"], marcados=[], maximo=3)

    assert [f for f, _u, _n in elegidos["vanos"]] == ["V1", "V2", "V3"]
    assert elegidos["marcados"] == []
    assert elegidos["completados"] == ["V1", "V2", "V3"]
    assert elegidos["restantes"] == 2
    assert elegidos["con_eventos"] == 5


def test_el_diagnostico_no_recorta_cuando_el_circuito_tiene_menos_que_el_tope():
    """Con menos vanos con eventos que el tope no queda nada fuera, y `restantes` en
    cero es lo que apaga el aviso del panel."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    elegidos = vanos_para_diagnostico(_datos_ventana(), ["V1", "V2"], maximo=15)

    assert [f for f, _u, _n in elegidos["vanos"]] == ["V1", "V2"]
    assert elegidos["restantes"] == 0


def test_lo_marcado_manda_SOLO_y_el_cupo_que_sobra_no_se_rellena():
    """Marcar vanos es acotar la pregunta, no sembrarla. Si el usuario marco dos, el
    diagnostico habla de esos dos aunque queden cupos libres y aunque no sean los de
    mayor UITI: completar la lista le contestaria por otros vanos que no pidio, y en una
    tabla de quince los suyos se pierden."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    elegidos = vanos_para_diagnostico(
        _datos_ventana(), ["V1", "V2", "V3", "V4", "V5"], marcados=["V5", "V4"], maximo=4)

    assert [f for f, _u, _n in elegidos["vanos"]] == ["V4", "V5"]
    assert elegidos["marcados"] == ["V4", "V5"]      # los del usuario, por UITI
    assert elegidos["completados"] == []             # no hay relleno cuando se marco
    assert elegidos["restantes"] == 3                # V1, V2 y V3 con eventos y fuera


def test_un_vano_marcado_sin_eventos_se_nombra_y_no_lo_reemplaza_nadie():
    """Sin celda en la ventana el modelo no lo puede puntuar: entra a `sin_eventos` para
    que el panel lo diga. Su lugar NO lo ocupa otro vano -- sustituirlo por el siguiente
    del top responderia por un vano que el usuario nunca sennalo."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    elegidos = vanos_para_diagnostico(
        _datos_ventana(), ["V1", "V2", "V3", "V4", "V5", "V9"],
        marcados=["V9", "V5"], maximo=3)

    assert [f for f, _u, _n in elegidos["vanos"]] == ["V5"]
    assert elegidos["completados"] == []
    assert elegidos["sin_eventos"] == ["V9"]
    assert elegidos["con_eventos"] == 5


def test_marcar_solo_vanos_sin_eventos_no_cae_de_vuelta_al_top_del_circuito():
    """El caso que separa "acotar" de "sugerir": el usuario marco vanos que no tienen
    celda en esta ventana. La respuesta honesta es ninguna -- y el panel nombra cuales
    fueron --, no el top del circuito, que seria contestar por vanos que no pidio y
    ademas leerse como si los suyos si hubieran entrado."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    elegidos = vanos_para_diagnostico(
        _datos_ventana(), ["V1", "V2", "V3", "V4", "V5", "V8", "V9"],
        marcados=["V8", "V9"], maximo=15)

    assert elegidos["vanos"] == []
    assert elegidos["completados"] == []
    assert elegidos["sin_eventos"] == ["V8", "V9"]
    assert elegidos["con_eventos"] == 5     # el circuito SI tiene, pero no son los suyos
    assert elegidos["restantes"] == 5


def test_marcar_mas_que_el_tope_deja_los_de_mayor_uiti_de_lo_marcado():
    """El selector topa en el mismo numero, asi que este caso solo llega por codigo. Se
    resuelve como el resto: manda el UITI, y lo que se cae se cuenta."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    elegidos = vanos_para_diagnostico(
        _datos_ventana(), ["V1", "V2", "V3", "V4", "V5"],
        marcados=["V3", "V4", "V5"], maximo=2)

    assert [f for f, _u, _n in elegidos["vanos"]] == ["V3", "V4"]
    assert elegidos["completados"] == []
    assert elegidos["restantes"] == 3


def test_el_diagnostico_compara_los_fid_como_texto():
    """`DATOS_VENTANA` esta indexado por TEXTO y tanto `VANOS_POR_CIRCUITO` como las
    casillas pueden traer el fid como numero. Sin la coercion no coincide ninguno y el
    diagnostico sale vacio sin decir por que."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    datos = {"7001": (5.0, 2), "7002": (4.0, 1)}

    # Marcado: el fid llega como numero desde la casilla y tiene que reconocerse.
    marcado = vanos_para_diagnostico(datos, [7001, 7002], marcados=[7002], maximo=2)
    assert [f for f, _u, _n in marcado["vanos"]] == ["7002"]
    assert marcado["marcados"] == ["7002"]
    assert marcado["sin_eventos"] == []      # no es que no lo encuentre: es que si lo hallo

    # Sin marcar: el top tambien cruza `VANOS_POR_CIRCUITO` numerico contra datos de texto.
    top = vanos_para_diagnostico(datos, [7001, 7002], maximo=2)
    assert [f for f, _u, _n in top["vanos"]] == ["7001", "7002"]


# ---------------------------------------------------------------------------
# El desajuste que ninguna huella podia detectar: CSV nuevo con bolsas viejas
# ---------------------------------------------------------------------------
#
# `TABLA` (los eventos observados) sale del CSV; `X_inst`/`bag_index` (la criticidad
# simulada) salen de `bolsas_mil_full.joblib`, que produce el cuaderno 05. Los dos
# archivos se vigilan por separado y los dos disparan reconstruccion, pero la huella
# contesta "cambio algun insumo?" y no "siguen hablando del mismo mes?". Actualizar el
# CSV sin volver a correr el 05 reconstruye la aplicacion, muestra los eventos nuevos y
# los puntua con las bolsas anteriores: **las dos mitades del tablero hablan de meses
# distintos y nada falla**.
#
# Esto lo detecta comparando las CELDAS, sin metadatos nuevos -- o sea que vale tambien
# para los artefactos que ya existen en disco.


def _bolsas_de(filas):
    """Un `BagIndex` minimo a partir de (circuito, fid, ventana, uiti, eventos)."""
    from chec_impacto.data.bags import BagIndex

    counts = np.array([f[4] for f in filas], dtype=np.int64)
    n_inst = int(counts.sum())
    return BagIndex(
        keys=pd.DataFrame([(f[0], f[1], f[2]) for f in filas],
                          columns=["CIRCUITO", "FID_VANO", "VENTANA"]),
        instance_bag=np.repeat(np.arange(len(filas), dtype=np.int64), counts),
        offsets=np.concatenate([[0], np.cumsum(counts)]).astype(np.int64),
        counts=counts,
        y=np.array([f[3] for f in filas], dtype=np.float64),
        group=np.array([f"{f[0]}|{f[1]}" for f in filas], dtype=object),
        instance_rows=np.arange(n_inst, dtype=np.int64),
    )


def _tabla_de(filas):
    return pd.DataFrame(
        [{"CIRCUITO": f[0], "FID_VANO": f[1], "ventana": f[2],
          "uiti_acumulado": f[3], "num_eventos": f[4]} for f in filas])


_COHERENTES = [
    ("AGU23L12", 20130434, "V1", 15.515, 1),
    ("AGU23L12", 20130434, "V2", 15.515, 1),
    ("AGU23L12", 20130436, "V1", 16.436, 2),
]


def test_bolsas_al_dia_no_reportan_desajuste():
    assert ventanas_015.desajuste_bolsas_vs_tabla(
        _bolsas_de(_COHERENTES), _tabla_de(_COHERENTES)) is None


def test_una_celda_que_el_csv_trae_y_las_bolsas_no_es_el_desajuste_peligroso():
    """El caso real: llega un mes nuevo al CSV, nadie vuelve a correr el 05, y el
    tablero muestra eventos que el modelo no puede puntuar."""
    tabla = _tabla_de([*_COHERENTES, ("AGU23L12", 20130437, "V12", 9.0, 3)])

    motivo = ventanas_015.desajuste_bolsas_vs_tabla(_bolsas_de(_COHERENTES), tabla)

    assert motivo is not None
    # Nombra cuantas y da un ejemplo: sin eso hay que ir a buscarlas a mano.
    assert "1" in motivo and "V12" in motivo


def test_una_celda_que_solo_esta_en_las_bolsas_no_es_desajuste():
    """Al reves NO es sintoma, y confundirlo seria un falso positivo permanente.

    `construir_tabla_vano_ventana` redondea `uiti_acumulado` a 3 decimales y despues
    descarta las filas con valor <= 0, asi que una celda con UITI diminuto existe en las
    bolsas y no en la tabla. Medido sobre los artefactos reales: pasa en exactamente 2
    celdas de 111.233 -- VMA23L16/39520403 en V7 y V8, con y = 0,000333.
    """
    bolsas = _bolsas_de([*_COHERENTES, ("VMA23L16", 39520403, "V7", 0.000333, 1)])

    assert ventanas_015.desajuste_bolsas_vs_tabla(bolsas, _tabla_de(_COHERENTES)) is None


def test_un_conteo_de_eventos_distinto_delata_un_csv_corregido():
    """El caso que la comparacion de celdas sola no ve: el CSV cambia DENTRO de los
    meses que ya existian. `num_eventos` es un entero exacto -- no hay redondeo que lo
    excuse -- asi que basta con que uno no cuadre."""
    tabla = _tabla_de([
        ("AGU23L12", 20130434, "V1", 15.515, 1),
        ("AGU23L12", 20130434, "V2", 15.515, 1),
        ("AGU23L12", 20130436, "V1", 16.436, 5),      # eran 2
    ])

    motivo = ventanas_015.desajuste_bolsas_vs_tabla(_bolsas_de(_COHERENTES), tabla)

    assert motivo is not None and "20130436" in motivo


def test_un_uiti_distinto_tambien_delata():
    tabla = _tabla_de([
        ("AGU23L12", 20130434, "V1", 99.999, 1),      # eran 15.515
        ("AGU23L12", 20130434, "V2", 15.515, 1),
        ("AGU23L12", 20130436, "V1", 16.436, 2),
    ])

    assert ventanas_015.desajuste_bolsas_vs_tabla(_bolsas_de(_COHERENTES), tabla) is not None


def test_el_redondeo_a_tres_decimales_no_cuenta_como_desajuste():
    """`construir_tabla_vano_ventana` redondea a 3 decimales y las bolsas no, asi que
    hay siempre hasta 0,0005 de diferencia. Medido sobre los artefactos reales: el
    maximo es exactamente 0,0005 en las 111.231 celdas compartidas. Marcarlo seria
    declarar desajustado un par perfectamente al dia."""
    bolsas = _bolsas_de([("AGU23L12", 20130434, "V1", 15.5154999, 1)])
    tabla = _tabla_de([("AGU23L12", 20130434, "V1", 15.515, 1)])

    assert ventanas_015.desajuste_bolsas_vs_tabla(bolsas, tabla) is None


def test_el_fid_se_compara_como_texto_en_los_dos_lados():
    """En las bolsas `FID_VANO` es str y en la tabla int64 -- verificado sobre los
    artefactos reales. Sin coercion no casa NI UNA celda, y la comprobacion diria que
    las 111.231 faltan: un falso positivo total, que es peor que no comprobar."""
    bolsas = _bolsas_de([("AGU23L12", "20130434", "V1", 15.515, 1)])
    tabla = _tabla_de([("AGU23L12", 20130434, "V1", 15.515, 1)])

    assert ventanas_015.desajuste_bolsas_vs_tabla(bolsas, tabla) is None
