from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from chec_local_interpreter.context_builder import _compute_circuit_characterization, build_context_package, save_json_artifact, vano_series_records, window_series_records
from chec_local_interpreter.plotting import CRITICALITY_GROUP_LABELS
from chec_local_interpreter.ventanas_015 import construir_ventanas


def tmp_ruta() -> Path:
    return Path(tempfile.mkdtemp()) / "artefacto.json"


def test_context_package_includes_core_sections_and_missing_optional_columns():
    events = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1"],
            "FID_VANO": ["V1", "V1"],
            "FECHA": ["2026-01-01", "2026-01-02"],
            "UITI_VANO": [1.0, 10.0],
            "DESC_CAUSA": ["Vegetacion", "Vegetacion"],
        }
    )
    context = build_context_package(
        events_df=events,
        selected_circuitos=["C1"],
        start_date="2026-01-01",
        end_date="2026-01-02",
    )
    assert context["selected_context"]["circuitos"] == ["C1"]
    assert context["selected_context"]["indicator"] == "UITI_VANO"
    assert context["ventanas"]
    assert context["domain"]["variable_groups"]
    assert "NR_T" in context["metadata"]["unavailable_cols"]


def test_the_historian_context_no_longer_carries_critical_points_or_a_daily_series():
    """El informe se apoya en el ranking del cuaderno 02 y en el diagnostico y la
    simulacion del 06, y la unidad de los tres es la VENTANA. La deteccion de puntos
    criticos ponia al historiador a describir DIAS: dos rejillas distintas sobre el
    mismo periodo, que quien lee tiene que reconciliar de cabeza, y ninguna de las dos
    coincide con la bolsa (vano, ventana) que el modelo puntua.
    """
    events = pd.DataFrame({
        "CIRCUITO": ["C1", "C1"], "FID_VANO": ["V1", "V1"],
        "FECHA": ["2026-01-01", "2026-01-02"], "UITI_VANO": [1.0, 10.0],
    })

    context = build_context_package(
        events_df=events, selected_circuitos=["C1"],
        start_date="2026-01-01", end_date="2026-01-02",
    )

    assert "critical_points" not in context
    assert "critical_periods" not in context
    assert "daily" not in context


def test_missing_optional_columns_do_not_crash_context_generation():
    events = pd.DataFrame({"CIRCUITO": ["C1"], "FID_VANO": ["V1"],
                           "FECHA": ["2026-01-01"], "UITI_VANO": [1]})
    context = build_context_package(
        events_df=events,
        selected_circuitos=["C1"],
        start_date="2026-01-01",
        end_date="2026-01-01",
    )
    assert context["summary"]["total_uv"] == 1.0


def _rows_for_circuit(circuit: str, n_events: int, total_uiti: float, start: str = "2026-01-01") -> pd.DataFrame:
    """Build `n_events` distinct-date rows for `circuit` whose UITI_VANO sums to `total_uiti`."""
    dates = pd.date_range(start, periods=n_events, freq="D").strftime("%Y-%m-%d").tolist()
    per_event = total_uiti / n_events
    return pd.DataFrame(
        {
            "CIRCUITO": [circuit] * n_events,
            "FECHA": dates,
            "UITI_VANO": [per_event] * n_events,
        }
    )


def test_un_marco_sin_vanos_se_queda_sin_banda_en_vez_de_inventarla():
    """Sin `FID_VANO` no hay ranking, y sin ranking no hay banda que citar.

    Aqui vivian dos pruebas que fijaban el contrato ANTERIOR: que `criticidad` saliera
    de `compute_circuit_criticality_groups` y usara sus cinco etiquetas. Ese contrato
    era el defecto -- ese helper narra el grafico de dispersion de `/informe-gerencial`,
    no la barra que el lector de `/report` tiene delante, y su vocabulario incluye
    "Riesgo Muy Alto" y "Riesgo Medio-Bajo", que la barra NO tiene --. Lo que fijaban de
    util (los extremos caen en los extremos, y las dos mitades salen del MISMO calculo)
    lo cubren ahora `test_la_banda_del_circuito_es_la_del_ranking_de_barras` y sus
    vecinas, contra la fuente correcta.

    Lo que aquellas dos ejercitaban SIN saberlo, y se habria perdido con ellas, es este
    marco: ocho circuitos y ni una columna `FID_VANO`. El ranking la necesita. Que ese
    camino degrade a "sin banda" y no reviente ni se invente una etiqueta es un
    contrato por derecho propio.
    """
    frames = [
        _rows_for_circuit("MUYALTO_1", n_events=40, total_uiti=50000.0),
        _rows_for_circuit("ALTO_1", n_events=10, total_uiti=5000.0),
        _rows_for_circuit("MEDIO_1", n_events=10, total_uiti=500.0),
        _rows_for_circuit("BAJO_1", n_events=4, total_uiti=40.0),
    ]
    df = pd.concat(frames, ignore_index=True)
    assert "FID_VANO" not in df.columns, "el fixture pierde su gracia si le sale un FID_VANO"

    results = _compute_circuit_characterization(
        df, selected_circuitos=["BAJO_1", "MEDIO_1", "ALTO_1", "MUYALTO_1"])

    assert results, "un marco sin vanos tiene que seguir describiendo el circuito"
    for row in results:
        assert row["criticidad"] == "No comparable"
        assert row["posicion"] is None
        # lo que NO depende del ranking sigue estando
        assert row["eventos"] > 0
        assert row["uiti_vano_total"] > 0
    # y ninguna etiqueta del vocabulario que la barra no puede mostrar
    assert all(r["criticidad"] not in CRITICALITY_GROUP_LABELS for r in results)


# --- La serie del historiador va por VENTANAS, no por dias -------------------------------


def test_window_series_covers_every_window_including_the_empty_ones():
    """La ventana es la unidad de analisis de los cuadernos 04, 05 y 06 -- una bolsa
    es (vano, ventana) --, y el historiador recibia una serie DIARIA. Peor: recortada
    a 60 dias y filtrando los dias en cero, asi que describia los picos y no la serie.

    Una ventana sin eventos es un dato, no un hueco: leer "hubo cinco ventanas
    tranquilas seguidas" es distinto de no ver esas ventanas. El cuaderno 06 ya dibuja
    su serie asi.
    """
    eventos = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1"],
            "FID_VANO": ["V1", "V1", "V2"],
            "FECHA": ["2026-01-05", "2026-03-20", "2026-03-21"],
            "UITI_VANO": [2.0, 5.0, 1.0],
        }
    )

    serie = window_series_records(eventos, circuito="C1")

    etiquetas = [r["w"] for r in serie]
    assert len(etiquetas) == len(set(etiquetas)), "una ventana no puede repetirse"
    # Enero y marzo tienen eventos; las ventanas intermedias van en cero y SIGUEN ahi.
    assert any(r["uv"] == 0.0 and r["n"] == 0 for r in serie), (
        "las ventanas sin eventos tienen que aparecer, en cero"
    )
    con_eventos = [r for r in serie if r["n"] > 0]
    assert con_eventos, "las ventanas con eventos no pueden perderse"
    assert sum(r["uv"] for r in serie) == pytest.approx(8.0)
    assert sum(r["n"] for r in serie) == 3


def test_window_series_is_empty_for_a_circuit_with_no_events():
    eventos = pd.DataFrame(
        {"CIRCUITO": ["C2"], "FID_VANO": ["V9"], "FECHA": ["2026-01-05"],
         "UITI_VANO": [1.0]}
    )

    assert window_series_records(eventos, circuito="C1") == []


def test_context_package_carries_the_window_series():
    eventos = pd.DataFrame(
        {"CIRCUITO": ["C1", "C1"], "FID_VANO": ["V1", "V1"],
         "FECHA": ["2026-01-05", "2026-02-20"], "UITI_VANO": [2.0, 5.0]}
    )

    paquete = build_context_package(
        events_df=eventos,
        selected_circuitos=["C1"], start_date="2026-01-01", end_date="2026-03-01",
    )

    assert paquete["ventanas"], "el paquete del historiador tiene que traer las ventanas"
    assert {"w", "uv", "n", "desde", "hasta"} <= set(paquete["ventanas"][0])


def test_the_window_grid_can_be_imposed_so_it_matches_the_bag_cache():
    """Las etiquetas `V1`..`V11` NO son relativas al recorte: el cache de bolsas del
    cuaderno 05 las fijo sobre el rango COMPLETO de la base. Derivarlas de los eventos
    ya filtrados hace que la `V1` del historiador y la `V1` del modelo sean dos periodos
    distintos con el mismo nombre, y nada en el informe lo delata.
    """
    completo = pd.date_range("2026-01-01", "2026-04-30", freq="D").to_series()
    rejilla = construir_ventanas(completo)
    # El circuito solo tiene eventos en marzo: por su cuenta, su primera ventana se
    # llamaria V1, cuando en la rejilla completa es V5.
    eventos = pd.DataFrame({
        "CIRCUITO": ["C1"], "FID_VANO": ["V1"],
        "FECHA": ["2026-03-05"], "UITI_VANO": [2.0],
    })

    propia = window_series_records(eventos, circuito="C1")
    impuesta = window_series_records(eventos, circuito="C1", ventanas=rejilla)

    assert [r["w"] for r in propia] == ["V1"], "por su cuenta el circuito se cree en V1"
    assert [r["w"] for r in impuesta] == [v["etiqueta"] for v in rejilla]
    # La rejilla SOLAPA a proposito -- mes completo y 15 a 15 --, asi que un evento cae
    # en dos ventanas. Lo que importa aqui es CUALES: en la rejilla completa el 5 de
    # marzo vive en V4 (15-feb a 14-mar) y V5 (marzo), nunca en V1 (enero).
    con_eventos = {r["w"] for r in impuesta if r["n"] > 0}
    assert con_eventos == {"V4", "V5"}
    por_etiqueta = {r["w"]: r for r in impuesta}
    assert por_etiqueta["V1"]["periodo"] == "2026-01-01 a 2026-01-31"
    assert por_etiqueta["V5"]["desde"] == "2026-03-01"


def test_the_context_declares_which_windows_the_report_studies():
    """Las tres ventanas del estudio van declaradas: sin ellas el historiador recibe
    once y elige por su cuenta cuales narrar, que es exactamente la decision que la
    seleccion determinista existe para quitarle."""
    eventos = pd.DataFrame(
        {"CIRCUITO": ["C1", "C1"], "FID_VANO": ["V1", "V1"],
         "FECHA": ["2026-01-05", "2026-02-20"], "UITI_VANO": [2.0, 5.0]}
    )

    paquete = build_context_package(
        events_df=eventos, selected_circuitos=["C1"],
        start_date="2026-01-01", end_date="2026-03-01",
        ventanas_estudio=["V1", "V3"],
    )

    assert paquete["ventanas_estudio"] == ["V1", "V3"]
    estudiadas = [r["w"] for r in paquete["ventanas"] if r["estudiada"]]
    assert estudiadas == ["V1", "V3"]


def test_the_summary_speaks_in_windows_because_that_is_the_unit_of_the_report():
    """`nonzero_days` describia una rejilla diaria que ya no existe en el informe."""
    eventos = pd.DataFrame(
        {"CIRCUITO": ["C1", "C1"], "FID_VANO": ["V1", "V1"],
         "FECHA": ["2026-01-05", "2026-02-20"], "UITI_VANO": [2.0, 5.0]}
    )

    resumen = build_context_package(
        events_df=eventos, selected_circuitos=["C1"],
        start_date="2026-01-01", end_date="2026-03-01",
    )["summary"]

    assert resumen["total_uv"] == pytest.approx(7.0)
    assert resumen["ventanas_con_eventos"] >= 1
    assert resumen["ventana_pico"]
    assert "nonzero_days" not in resumen


def test_vano_series_covers_every_window_for_each_identified_vano():
    """La serie de los vanos que el diagnostico señalo, para verlos en el tiempo y no
    solo en la ventana en que salieron criticos. Completa, con cero donde el vano no
    registro eventos: una ventana tranquila de un vano critico es informacion -- dice
    que el problema es reciente o intermitente, no cronico."""
    eventos = pd.DataFrame({
        "CIRCUITO": ["C1", "C1", "C1"],
        "FID_VANO": ["V1", "V1", "V2"],
        "FECHA": ["2026-01-05", "2026-03-20", "2026-01-06"],
        "UITI_VANO": [2.0, 5.0, 1.0],
    })

    series = vano_series_records(eventos, circuito="C1", fids=["V1", "V2"])

    assert [s["fid"] for s in series] == ["V1", "V2"], "en el orden pedido"
    for s in series:
        assert len(s["uv"]) == len(s["w"]) == len(s["n"])
        assert any(u == 0.0 for u in s["uv"]), "las ventanas sin eventos van en cero"
    assert sum(series[0]["uv"]) == pytest.approx(7.0)


def test_vano_series_without_fids_is_empty():
    eventos = pd.DataFrame({"CIRCUITO": ["C1"], "FID_VANO": ["V1"],
                            "FECHA": ["2026-01-05"], "UITI_VANO": [1.0]})

    assert vano_series_records(eventos, circuito="C1", fids=[]) == []


# --- Persistir el artefacto no puede perder una corrida ya calculada ----------------------


def test_saving_an_artifact_coerces_numpy_values_instead_of_losing_the_run():
    """`json.dumps` no sabe escribir un tipo de numpy y levanta `TypeError`.

    Eso ocurre al FINAL de `prepare`, cuando el diagnostico y la simulacion ya estan
    calculados: la corrida entera se pierde por un escalar. Y el modelo produce numpy en
    cada paso, asi que basta con que una sola clave nueva olvide un `float(...)` para que
    el informe deje de salir -- exactamente lo que paso con la matriz del grafo.

    Coercionar aqui es la guarda de ultimo recurso, no una excusa para no convertir en el
    origen: los tipos que SI se pueden representar viajan como el numero que son.
    """
    import numpy as np

    destino = tmp_ruta()
    payload = {
        "entero": np.int64(7),
        "flotante": np.float32(1.5),
        "booleano": np.bool_(True),
        "arreglo": np.array([1.0, 2.0]),
        "anidado": {"lista": [np.float64(3.25)]},
    }

    ruta = save_json_artifact(payload, destino)
    leido = json.loads(ruta.read_text(encoding="utf-8"))

    assert leido["entero"] == 7
    assert leido["flotante"] == pytest.approx(1.5)
    assert leido["booleano"] is True
    assert leido["arreglo"] == [1.0, 2.0]
    assert leido["anidado"]["lista"][0] == pytest.approx(3.25)


def test_saving_an_artifact_still_fails_on_something_genuinely_unrepresentable():
    """La guarda coerciona numpy, no cualquier cosa: un objeto sin representacion JSON
    sigue siendo un error, porque escribirlo como su `repr` metería basura en el contexto
    del agente sin que nada lo dijera."""
    class Opaco:
        pass

    with pytest.raises(TypeError):
        save_json_artifact({"x": Opaco()}, tmp_ruta())


# ---------------------------------------------------------------------------
# La banda del circuito: la del RANKING DE BARRAS, y calculada contra la flota.
# ---------------------------------------------------------------------------


def _flota_con_vanos(especificacion, start="2026-01-01"):
    """Una flota con vanos de verdad: el ranking necesita `FID_VANO`.

    `especificacion` es {circuito: (n_vanos, eventos_por_vano, uiti_por_evento)}.
    """
    filas = []
    for circuito, (n_vanos, eventos, uiti) in especificacion.items():
        for v in range(n_vanos):
            fechas = pd.date_range(start, periods=eventos, freq="D").strftime("%Y-%m-%d")
            filas.append(pd.DataFrame({
                "CIRCUITO": [circuito] * eventos,
                "FID_VANO": [f"{circuito}_V{v}"] * eventos,
                "FECHA": list(fechas),
                "UITI_VANO": [uiti] * eventos,
            }))
    return pd.concat(filas, ignore_index=True)


def test_la_banda_del_circuito_es_la_del_ranking_de_barras():
    """La prosa tiene que citar la MISMA banda que el lector ve en la barra.

    Eran dos calculos distintos: la barra la asigna `ranking_circuitos` (vanos en
    Medio-Alto mas Alto, cortes por percentil) y el texto la sacaba de
    `compute_circuit_criticality_groups` (KMeans sobre frecuencia y UITI). Para
    DON23L14 daban `Riesgo Medio-Alto` y `Riesgo Medio-Bajo`.

    Y no es solo que difieran los valores: son VOCABULARIOS distintos. La barra tiene
    cuatro bandas y ninguna se llama "Riesgo Muy Alto"; el informe la nombraba igual.
    """
    from chec_local_interpreter.ranking_circuitos import NOMBRES_RANGO, ranking_circuitos

    df = _flota_con_vanos({
        "TRANQUILO": (6, 1, 1.0),
        "MEDIANO": (6, 4, 60.0),
        "RUIDOSO": (6, 12, 400.0),
        "GRAVE": (6, 30, 3000.0),
    })

    for circuito in ("TRANQUILO", "GRAVE"):
        resultado = _compute_circuit_characterization(df, selected_circuitos=[circuito])
        assert resultado, f"{circuito} no produjo caracterizacion"
        fila = resultado[0]
        esperada = ranking_circuitos(df).tabla.set_index("circuito").loc[circuito, "rango"]
        assert fila["criticidad"] == esperada, (
            f"{circuito}: el texto dice {fila['criticidad']!r} y la barra {esperada!r}")
        assert fila["criticidad"] in NOMBRES_RANGO


def test_un_marco_de_un_solo_circuito_no_inventa_una_banda():
    """El defecto que hacia que TODOS los informes dijeran "Riesgo Muy Alto".

    `/report` filtraba el marco a un circuito ANTES de construir el contexto, asi que
    el agrupamiento corria sobre UN punto y lo metia siempre en el grupo mas alto.
    Medido sobre la base real: un circuito de banda `Riesgo Bajo` con 1 evento tambien
    salia "Riesgo Muy Alto".

    Una banda es COMPARATIVA por definicion: con un solo circuito en el marco no hay
    banda que dar, y decirlo es lo unico honesto.
    """
    df = _flota_con_vanos({"SOLO": (6, 3, 50.0)})

    resultado = _compute_circuit_characterization(df, selected_circuitos=["SOLO"])

    assert resultado, "un solo circuito tiene que producir caracterizacion, no lista vacia"
    assert resultado[0]["criticidad"] == "No comparable", (
        f"con un circuito en el marco invento la banda {resultado[0]['criticidad']!r}")
    assert resultado[0]["circuitos_en_la_flota"] == 1


def test_los_promedios_de_la_red_son_de_la_FLOTA_y_no_del_propio_circuito():
    """`avg_eventos_red` valia exactamente lo mismo que `eventos` en cada informe.

    Con un marco de un circuito, la media de la red es la media de un elemento: el
    circuito comparado consigo mismo. En el informe de DON23L14 se leia
    `eventos: 65` y `avg_eventos_red: 65.0`.
    """
    df = _flota_con_vanos({
        "TRANQUILO": (6, 1, 1.0),
        "GRAVE": (6, 30, 3000.0),
    })

    fila = _compute_circuit_characterization(df, selected_circuitos=["GRAVE"])[0]

    assert fila["avg_eventos_red"] != fila["eventos"], (
        "el promedio de la red es el del propio circuito otra vez")
    assert fila["avg_eventos_red"] < fila["eventos"], (
        "GRAVE esta muy por encima de la flota; su promedio no puede ser mayor")


def test_la_caracterizacion_situa_al_circuito_en_la_flota():
    """Una banda sin puesto no dice si el circuito es de los peores o de los del monton."""
    df = _flota_con_vanos({
        "A": (6, 1, 1.0), "B": (6, 4, 60.0), "C": (6, 12, 400.0), "D": (6, 30, 3000.0),
    })

    fila = _compute_circuit_characterization(df, selected_circuitos=["D"])[0]

    assert fila["posicion"] == 1, "D es el peor de la flota; tiene que ser el puesto 1"
    assert fila["circuitos_en_la_flota"] == 4


def test_el_paquete_del_historiador_situa_al_circuito_contra_la_flota():
    """El defecto vivia AQUI, en quien llama, no en el calculo.

    `build_context_package` recibia como `raw_df` el mismo marco ya filtrado a un
    circuito que recibe como `events_df`. El parametro existe SOLO para la
    caracterizacion, que es comparativa: con un circuito dentro, el agrupamiento corria
    sobre un punto y el promedio de la red era el promedio de un elemento. En el
    informe de DON23L14 se leia `eventos: 65` junto a `avg_eventos_red: 65.0`, y la
    banda "Riesgo Muy Alto" que salia igual para cualquier circuito de la base.

    Por eso el parametro se llama `fleet_df`: `raw_df` no decia que TENIA que ser otro
    marco distinto de `events_df`, y el `else events_df` de dentro tapaba el error.
    """
    flota = _flota_con_vanos({
        "ESTUDIADO": (6, 30, 3000.0),
        "OTRO_1": (6, 1, 1.0),
        "OTRO_2": (6, 2, 5.0),
        "OTRO_3": (6, 4, 20.0),
    })
    del_circuito = flota[flota["CIRCUITO"] == "ESTUDIADO"]

    contexto = build_context_package(
        events_df=del_circuito,
        selected_circuitos=["ESTUDIADO"],
        start_date="2026-01-01",
        end_date="2026-12-31",
        fleet_df=flota,
    )

    fila = contexto["selected_context"]["characterization"][0]
    assert fila["circuitos_en_la_flota"] == 4, (
        "la caracterizacion volvio a mirar solo el circuito estudiado")
    assert fila["avg_eventos_red"] != fila["eventos"]
    assert fila["criticidad"] != "No comparable"
