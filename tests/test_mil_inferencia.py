"""RED/GREEN tests for `mil_inferencia`: the report's predictive layer on the
MIL bag model of notebook 05, replacing the MGCECDL row-level path.

The unit changed, and that is the whole point. MGCECDL scored one ROW; the MIL
model scores a BAG -- one (vano, ventana) cell -- which is the unit notebook 04
defines criticality on and the unit notebook 06's simulator moves. A report built
on rows and a dashboard built on bags answered the same question with two models
and no way to reconcile them.

Everything here is measured on UITI: `relevancia_hacia_uiti_minimo` ranks how far
each control can pull a bag's predicted UITI down. Event count never enters this
layer -- it is descriptive and belongs to the historian.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chec_local_interpreter.mil_inferencia import (
    RecursosMIL,
    _aristas_del_modelo,
    compactar_grafo_del_escenario,
    construir_contexto_inferencia_mil,
    diagnostico_de_circuito,
    escenarios_de_circuito,
    influencia_por_ventana,
    knobs_desde_datos,
    mapas_de_escenario,
    relevancia_de_circuito,
    resumen_de_modelo,
    resumen_variables_por_grupo,
    seleccionar_ventanas_reporte,
    simulacion_de_circuito,
    ventana_de_mapas,
    ventanas_de_circuito,
)


class _BagIndexFalso:
    def __init__(self, keys, offsets, counts, y=None):
        self.keys = keys
        self.offsets = np.asarray(offsets, dtype=np.int64)
        self.counts = np.asarray(counts, dtype=np.int64)
        # `y` es el UITI acumulado OBSERVADO de cada bolsa. Va aqui y no en una
        # pasada del modelo porque la clase de criticidad la fija el par
        # (n_obs observado, UITI observado) sobre la geometria del 01.4.
        self.y = np.zeros(len(self.counts)) if y is None else np.asarray(y, dtype=float)


class _PredictorFalso:
    """u-hat es la media de la primera columna de la bolsa, asi que bajar esa
    columna baja el UITI predicho de forma comprobable."""

    def __init__(self, geometria):
        self.geometria = geometria
        self.llamadas = 0

    def predict(self, X_inst, instance_bag=None):
        self.llamadas += 1
        X_inst = np.asarray(X_inst, dtype=float)
        if instance_bag is None:
            return X_inst[:, 0]
        instance_bag = np.asarray(instance_bag)
        n = int(instance_bag.max()) + 1 if instance_bag.size else 0
        return np.array([X_inst[instance_bag == b, 0].mean() for b in range(n)])


def _geometria():
    from chec_impacto.models.criticality_assignment import Geometria

    return Geometria(
        logs=(False, False),
        offset=np.array([0.0, 0.0]),
        scale=np.array([1.0, 1.0]),
        centroides=np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]),
    )


def _knob(knob_id, bounds=(0.0, 4.0)):
    from chec_local_interpreter.vano_controls import Knob

    return Knob(id=knob_id, label=knob_id, kind="numeric",
                feature_names=(knob_id,), bounds=bounds, categories=None,
                default=None, step=None)


def _recursos():
    """Dos vanos de un circuito en una ventana: uno tranquilo y uno critico."""
    X = np.array([[0.0, 1.0], [0.0, 1.0], [3.0, 1.0], [3.0, 1.0]], dtype=np.float32)
    # `keys` es un DataFrame en el artefacto real, con una fila por bolsa.
    bag_index = _BagIndexFalso(
        keys=pd.DataFrame({"CIRCUITO": ["C1", "C1"], "FID_VANO": ["V1", "V2"],
                           "VENTANA": ["W1", "W1"]}),
        offsets=[0, 2, 4],
        counts=[2, 2],
    )
    return RecursosMIL(
        modelo=_PredictorFalso(_geometria()),
        X_inst=X,
        features=["u_driver", "otra"],
        bag_index=bag_index,
        knobs=[_knob("u_driver")],
        label_encoders={},
        max_values_imputed={},
    )


def _recursos_multiventana():
    """Un circuito con cinco ventanas de actividad muy distinta.

    Las clases salen del par (n_obs observado, UITI observado) sobre la geometria de
    `_geometria`, cuyos centroides estan en la diagonal: `counts=3, y=3` cae en la
    clase 3 (Alto) y `counts=1, y=0` en la 0 (Bajo).

        V1  tranquila            0 bolsas criticas   UITI 0
        V2  la peor              2 bolsas criticas   UITI 6
        V3  critica pero menor   2 bolsas criticas   UITI 4
        V4  tranquila            0 bolsas criticas   UITI 0
        V5  ULTIMA, tranquila    0 bolsas criticas   UITI 1
    """
    ventanas = ["V1", "V2", "V3", "V4", "V5"]
    y = [0.0, 0.0, 3.0, 3.0, 2.0, 2.0, 0.0, 0.0, 1.0, 0.0]
    counts = [1, 1, 3, 3, 2, 2, 1, 1, 1, 1]
    keys = pd.DataFrame({
        "CIRCUITO": ["C1"] * 10,
        "FID_VANO": ["V1", "V2"] * 5,
        "VENTANA": [v for v in ventanas for _ in range(2)],
    })
    offsets = np.cumsum([0] + counts)
    X = np.zeros((int(offsets[-1]), 2), dtype=np.float32)
    return RecursosMIL(
        modelo=_PredictorFalso(_geometria()),
        X_inst=X,
        features=["u_driver", "otra"],
        bag_index=_BagIndexFalso(keys=keys, offsets=offsets, counts=counts, y=y),
        knobs=[_knob("u_driver")],
    )


# --- Las tres ventanas que el informe estudia --------------------------------------------


def test_the_report_studies_the_last_window_plus_the_two_most_critical_ones():
    """El informe no recorre las once ventanas: estudia tres.

    La ultima SIEMPRE entra -- es el estado actual del circuito, y un informe que no lo
    incluye describe un pasado --, y las otras dos son las de mayor influencia de UITI,
    ordenadas por bolsas en clase critica. Aqui V5 entra por ser la ultima aunque no
    tenga ninguna bolsa critica, y V2/V3 por ser las dos criticas.
    """
    recursos = _recursos_multiventana()

    assert seleccionar_ventanas_reporte(recursos, circuito="C1") == ["V2", "V3", "V5"]


def test_the_selected_windows_come_back_in_chronological_order():
    """El orden de lectura del informe es el del tiempo. Devolverlas por criticidad
    dejaria la ultima ventana -- el estado actual -- en medio del relato."""
    recursos = _recursos_multiventana()

    seleccion = seleccionar_ventanas_reporte(recursos, circuito="C1")

    assert seleccion == sorted(seleccion, key=lambda v: int(v.lstrip("V")))


def test_the_last_window_is_never_dropped_for_a_more_critical_one():
    """Si las tres mas criticas fueran otras, la ultima seguiria entrando: la pregunta
    del informe es 'como esta hoy y que lo trajo hasta aqui', no 'cuales fueron los
    tres peores momentos del año'."""
    recursos = _recursos_multiventana()
    # V5 pasa a ser la mas tranquila posible y aun asi entra.
    recursos.bag_index.y = np.zeros_like(recursos.bag_index.y)
    recursos.bag_index.y[2:6] = [3.0, 3.0, 2.0, 2.0]

    assert "V5" in seleccionar_ventanas_reporte(recursos, circuito="C1")


def test_a_circuit_with_fewer_windows_than_asked_returns_what_it_has():
    """Un circuito con una sola ventana con eventos es un caso real, no un fallo:
    rellenar hasta tres inventaria ventanas sin bolsas, que el informe presentaria como
    'el modelo no encontro nada' cuando lo que no hubo fueron eventos."""
    recursos = _recursos()

    assert seleccionar_ventanas_reporte(recursos, circuito="C1") == ["W1"]
    assert seleccionar_ventanas_reporte(recursos, circuito="NO_EXISTE") == []


def test_the_map_window_is_the_last_one_that_actually_has_events():
    """Los dos mapas -- base y simulado -- describen UNA ventana, y tiene que ser la
    mas cercana a hoy con eventos en el circuito. `ventanas_de_circuito` ya solo lista
    ventanas con bolsas, asi que la ultima de esa lista ES esa ventana: no hay que
    buscar hacia atras ni tratar el hueco como un caso aparte."""
    recursos = _recursos_multiventana()

    assert ventana_de_mapas(recursos, circuito="C1") == "V5"
    assert ventana_de_mapas(recursos, circuito="NO_EXISTE") is None


def test_window_influence_counts_critical_bags_from_observed_data_not_the_model():
    """La clase de una bolsa la fija el par (n_obs observado, UITI observado) sobre la
    geometria del 01.4. Calcularla con una pasada del modelo costaria una evaluacion por
    ventana para elegir ventanas, que es justo lo que la seleccion existe para evitar.
    """
    recursos = _recursos_multiventana()
    llamadas_antes = recursos.modelo.llamadas

    influencia = {i["ventana"]: i for i in influencia_por_ventana(recursos, circuito="C1")}

    assert recursos.modelo.llamadas == llamadas_antes, "elegir ventanas no evalua el modelo"
    assert influencia["V2"]["n_bolsas_criticas"] == 2
    assert influencia["V2"]["uiti_total"] == pytest.approx(6.0)
    assert influencia["V1"]["n_bolsas_criticas"] == 0


def test_relevance_is_measured_on_uiti_and_never_on_event_count():
    """El modelo predice UITI acumulado. El conteo de eventos es un eje del espacio
    KMeans que define la clase, no una salida del modelo: pedirle que lo explique
    seria pedirle una magnitud que no produce."""
    recursos = _recursos()

    resultado = relevancia_de_circuito(recursos, circuito="C1", ventana="W1")

    assert resultado["metrica"] == "uiti_acumulado"
    assert resultado["vanos"], "un circuito con bolsas tiene que producir relevancia"
    for entrada in resultado["vanos"].values():
        for variable in entrada["variables"]:
            assert {"knob_id", "u_base", "u_min", "caida"} <= set(variable)
            assert "eventos" not in variable and "n_obs" not in variable


def test_relevance_on_a_circuit_with_no_bags_is_empty_not_an_error():
    """Un circuito sin bolsas en la ventana es un caso normal -- hay circuitos con
    una sola ventana con eventos en todo el ano --, no un fallo del reporte."""
    recursos = _recursos()

    resultado = relevancia_de_circuito(recursos, circuito="NO_EXISTE", ventana="W1")

    assert resultado["vanos"] == {}
    assert resultado["metrica"] == "uiti_acumulado"


def test_the_diagnosis_ranks_the_critical_vanos_and_carries_their_plan():
    """Los vanos criticos ya no salen de un percentil de UITI promedio sino del
    diagnostico del cuaderno 06: el plan que lleva cada bolsa hacia su clase minima,
    mirando primero el grupo Alto y completando con Medio-Alto."""
    recursos = _recursos()

    criticos = diagnostico_de_circuito(recursos, circuito="C1", ventana="W1", top=5)

    assert criticos, "el vano en clase alta tiene que aparecer"
    primero = criticos[0]
    assert {"fid", "clase_base", "u_base", "pasos", "alcanza"} <= set(primero)
    # Ordenado por criticidad: el vano de u=3 va antes que el de u=0.
    assert primero["fid"] == "V2"
    assert all(isinstance(paso.get("knob_id"), str) for paso in primero["pasos"])


def test_the_diagnosis_never_reports_more_vanos_than_asked():
    recursos = _recursos()

    assert len(diagnostico_de_circuito(recursos, circuito="C1", ventana="W1", top=1)) == 1


def test_the_model_summary_names_the_bag_unit_not_the_row():
    """Lo que el informe imprime sobre el modelo tiene que decir en que unidad
    trabaja: es la diferencia entre 'la variable X pesa en este circuito' y 'la
    variable X pesa en esta celda vano-ventana'."""
    recursos = _recursos()

    resumen = resumen_de_modelo(recursos)

    assert resumen["unidad"] == "bolsa (vano, ventana)"
    assert resumen["objetivo"] == "uiti_acumulado"
    assert resumen["n_bolsas"] == 2
    assert "mgcecdl" not in str(resumen).lower()


def test_the_diagnosis_returns_nothing_when_no_vano_reaches_a_critical_group():
    """Sin vanos en Alto ni Medio-Alto la respuesta correcta es "ninguno", no los
    menos malos. Devolver los de Medio bajo el rotulo de diagnostico convierte
    "este circuito esta tranquilo esta ventana" en una orden de trabajo inventada.
    """
    recursos = _recursos()
    # Las dos bolsas quedan en las clases bajas: u = 0 en ambos vanos.
    recursos.X_inst = np.zeros_like(recursos.X_inst)

    criticos = diagnostico_de_circuito(recursos, circuito="C1", ventana="W1", top=5)

    assert criticos == []


def test_relevance_says_when_it_ran_without_controls():
    """El barrido recorre los CONTROLES; sin catalogo devuelve vanos con la lista de
    variables vacia, que se lee como "ninguna variable mueve este vano" cuando en
    realidad es "no se le paso el catalogo". Se declara en el resultado."""
    recursos = _recursos()
    recursos.knobs = []

    resultado = relevancia_de_circuito(recursos, circuito="C1", ventana="W1")

    assert resultado["n_controles"] == 0
    assert resultado["sin_controles"] is True


# --- Los escenarios, que con el MIL son VENTANAS -----------------------------------------


def test_scenarios_are_windows_because_that_is_what_a_bag_is():
    """Con MGCECDL un escenario era un percentil de filas; con el MIL la unidad es la
    bolsa (vano, ventana), asi que el escenario natural es la VENTANA. Mantener el
    percentil habria dejado el informe hablando de una particion que el modelo no ve.
    """
    recursos = _recursos()

    escenarios = escenarios_de_circuito(recursos, circuito="C1")

    assert escenarios, "un circuito con bolsas tiene al menos un escenario"
    uno = escenarios[0]
    assert uno["ventana"] == "W1"
    assert uno["metrica"] == "uiti_acumulado"
    assert {"nombre", "ventana", "relevancia", "vanos_criticos"} <= set(uno)


def test_scenarios_are_restricted_to_the_windows_asked_for():
    recursos = _recursos()

    assert escenarios_de_circuito(recursos, circuito="C1", ventanas=["W9"]) == []
    assert len(escenarios_de_circuito(recursos, circuito="C1", ventanas=["W1"])) == 1


def test_ventanas_de_circuito_lists_only_the_windows_that_circuit_has():
    """Un circuito tranquilo puede no tener bolsas en media parte del ano. Ofrecer
    ventanas que ese circuito no tiene produce escenarios vacios que el informe
    presenta como si el modelo no hubiera encontrado nada."""
    recursos = _recursos()

    assert ventanas_de_circuito(recursos, circuito="C1") == ["W1"]
    assert ventanas_de_circuito(recursos, circuito="NO_EXISTE") == []


def test_knobs_come_from_the_dataset_and_drop_the_refuted_ones():
    """El panel del cuaderno 06 no ofrece las variables refutadas -- coordenadas del
    vano, identidad -- porque presentarlas junto a la poda invita a simular que se
    mueve un vano de sitio. El informe hereda ese catalogo, no uno propio: dos listas
    de palancas para el mismo modelo se separan en cuanto alguien edita una.
    """
    datos = {
        "features": ["NR_T", "X2"],
        "Xdata": pd.DataFrame({"NR_T": [0.0, 1.0, 2.0], "X2": [1.0, 2.0, 3.0]}),
        "label_encoders": {},
        "max_values_imputed": {},
    }

    knobs, grupos = knobs_desde_datos(datos)

    ids = {k.id for k in knobs}
    assert "NR_T" in ids
    assert "X2" not in ids, "las variables refutadas no son palancas"
    assert grupos.get("NR_T") in {"Intervencion", "Escenario"}


def test_the_inference_context_declares_the_model_the_unit_and_the_metric():
    """El agente de inferencia cita lo que el contexto declara. Si el contexto no dice
    en que unidad trabaja el modelo, el agente escribe "la variable X pesa en este
    circuito" cuando lo medido es "pesa en esta celda vano-ventana", y nadie que lea el
    informe puede notar la diferencia.
    """
    recursos = _recursos()

    contexto = construir_contexto_inferencia_mil(
        recursos, circuito="C1", fecha_inicio="2026-01-01", fecha_fin="2026-03-01",
        fechas_interes=["2026-02-01"],
    )

    assert contexto["modelo_tipo"] == "mil_bolsas"
    assert contexto["unidad"] == "bolsa (vano, ventana)"
    assert contexto["metrica"] == "uiti_acumulado"
    assert "mgcecdl" not in str(contexto).lower()
    # `nombre` por escenario es lo que el validador usa como universo citable.
    assert all("nombre" in e for e in contexto["escenarios"])
    assert contexto["ventanas"] == ["W1"]


def test_the_inference_context_survives_a_circuit_with_no_bags():
    recursos = _recursos()

    contexto = construir_contexto_inferencia_mil(
        recursos, circuito="NO_EXISTE", fecha_inicio="2026-01-01",
        fecha_fin="2026-03-01", fechas_interes=[],
    )

    assert contexto["escenarios"] == []
    assert contexto["ventanas"] == []
    assert contexto["modelo_tipo"] == "mil_bolsas"


# --- Variables de intervencion contra variables de escenario ------------------------------


def _relevancia_de_prueba():
    """Tres vanos, tres palancas: una de obra que sirve, una de obra que no alcanza y
    una climatica que baja mucho pero no se puede ejecutar."""
    def _fila(knob_id, grupo, caida, avance, alcanza, valor):
        return {"knob_id": knob_id, "label": knob_id, "grupo": grupo,
                "valor_optimo": valor, "u_base": 10.0, "u_min": 1.0,
                "caida": caida, "avance": avance, "alcanza": alcanza}

    return {
        "metrica": "uiti_acumulado",
        "vanos": {
            "V1": {"u_base": 10.0, "clase_base": 3, "ya_en_clase_minima": False,
                   "n_obs_observado": 3, "variables": [
                       _fila("PODA", "Intervencion", 1.0, 1.0, True, 5.0),
                       _fila("ALTURA", "Intervencion", 0.2, 0.2, False, 18.0),
                       _fila("clima:wind_spd", "Escenario", 2.0, 1.0, True, 0.5),
                   ]},
            "V2": {"u_base": 8.0, "clase_base": 2, "ya_en_clase_minima": False,
                   "n_obs_observado": 2, "variables": [
                       _fila("PODA", "Intervencion", 0.8, 0.9, True, 5.0),
                       _fila("ALTURA", "Intervencion", 0.1, 0.1, False, 18.0),
                   ]},
            "V3": {"u_base": 0.4, "clase_base": 0, "ya_en_clase_minima": True,
                   "n_obs_observado": 1, "variables": [
                       _fila("ALTURA", "Intervencion", 0.3, None, False, 16.0),
                   ]},
        },
    }


def test_variables_are_split_between_what_a_crew_can_execute_and_what_it_cannot():
    """El informe sustenta una ORDEN DE TRABAJO. Presentar la racha de viento junto a la
    poda en una sola lista ordenada por caida deja arriba la que nadie puede comprar, y
    quien lee no tiene como distinguirlas: las dos aparecen como 'lo que mas baja el
    UITI'. Van en dos bloques declarados."""
    resumen = resumen_variables_por_grupo(_relevancia_de_prueba())

    assert set(resumen) >= {"Intervencion", "Escenario"}
    assert [v["knob_id"] for v in resumen["Escenario"]] == ["clima:wind_spd"]
    assert {v["knob_id"] for v in resumen["Intervencion"]} == {"PODA", "ALTURA"}


def test_the_ranking_leads_with_what_actually_changes_the_group_not_what_drops_most():
    """La pregunta del informe no es 'que baja mas el UITI' sino 'que cambia de grupo a
    riesgo bajo'. ALTURA baja el UITI en los tres vanos y no cambia de grupo en ninguno;
    PODA lo cambia en dos. PODA va primero."""
    intervencion = resumen_variables_por_grupo(_relevancia_de_prueba())["Intervencion"]

    assert intervencion[0]["knob_id"] == "PODA"
    assert intervencion[0]["n_vanos_alcanza"] == 2
    assert intervencion[1]["n_vanos_alcanza"] == 0


def test_a_vano_already_in_the_lowest_group_never_counts_as_a_variable_reaching_it():
    """V3 ya esta en el grupo mas bajo: ninguna variable lo lleva ahi, porque no hay
    camino que recorrer. Contarlo inflaria el merito de ALTURA con un vano que no
    necesitaba intervencion."""
    intervencion = resumen_variables_por_grupo(_relevancia_de_prueba())["Intervencion"]
    altura = next(v for v in intervencion if v["knob_id"] == "ALTURA")

    assert altura["n_vanos"] == 3
    assert altura["n_vanos_alcanza"] == 0
    # `avance` es None en V3 (no hay camino): promediarlo como cero hundiria la variable
    # por un vano que no aporta informacion sobre ella.
    assert altura["avance_mediano"] == pytest.approx(0.15)


def test_the_summary_carries_the_value_so_it_reads_as_an_instruction():
    """'Sube ALTURA' no es una orden de trabajo; 'lleva ALTURA a 18 m' si. El valor que
    consigue el minimo viaja con la variable."""
    intervencion = resumen_variables_por_grupo(_relevancia_de_prueba())["Intervencion"]
    poda = next(v for v in intervencion if v["knob_id"] == "PODA")

    assert poda["valor_tipico"] == 5.0


def test_a_relevance_without_vanos_yields_both_groups_empty_not_a_crash():
    resumen = resumen_variables_por_grupo({"vanos": {}})

    assert resumen["Intervencion"] == []
    assert resumen["Escenario"] == []


def test_each_scenario_carries_its_own_split_of_the_two_groups():
    """El corte por grupo va DENTRO del escenario, no una vez por informe: las palancas
    que sirven en enero no son las que sirven en abril, y una sola lista para las tres
    ventanas borraria justo esa diferencia."""
    recursos = _recursos()
    recursos.grupos_por_knob = {"u_driver": "Intervencion"}

    escenario = escenarios_de_circuito(recursos, circuito="C1")[0]

    assert "variables_por_grupo" in escenario
    assert [v["knob_id"] for v in escenario["variables_por_grupo"]["Intervencion"]] == ["u_driver"]
    assert escenario["variables_por_grupo"]["Escenario"] == []


# --- Los dos mapas de la ultima ventana: base contra intervenido --------------------------


def _escenario_de_mapas():
    return {
        "ventana": "V11",
        "relevancia": {"vanos": {
            "A": {"u_base": 9.0, "clase_base": 3, "ya_en_clase_minima": False,
                  "n_obs_observado": 3, "variables": []},
            "B": {"u_base": 4.0, "clase_base": 2, "ya_en_clase_minima": False,
                  "n_obs_observado": 2, "variables": []},
            "C": {"u_base": 0.2, "clase_base": 0, "ya_en_clase_minima": True,
                  "n_obs_observado": 1, "variables": []},
        }},
        "simulacion": {"vanos": [
            {"fid": "A", "u_base": 9.0, "u_simulado": 1.0,
             "clase_base": 3, "clase_simulada": 1, "delta_grupo": -2, "pasos": []},
        ]},
    }


def test_the_two_maps_cover_every_vano_of_the_window_not_only_the_intervened_ones():
    """El mapa es del CIRCUITO, no de los quince vanos del diagnostico. Dibujar solo los
    intervenidos dejaria el resto del circuito en blanco, que se lee como 'sin datos'
    cuando lo que pasa es que no hacia falta intervenirlos."""
    mapas = mapas_de_escenario(_escenario_de_mapas())

    assert set(mapas["base"]["clase"]) == {"A", "B", "C"}
    assert set(mapas["simulado"]["clase"]) == {"A", "B", "C"}
    assert mapas["ventana"] == "V11"


def test_both_maps_read_the_class_from_the_model_so_the_only_difference_is_the_work():
    """Las dos clases salen de la MISMA fuente -- el u-hat del modelo sobre la geometria
    del 01.4 --, y el mapa base usa `clase_base` de la propia simulacion. Si el izquierdo
    pintara UITI observado y el derecho prediccion, los dos mapas diferirian por el
    cambio de fuente y no por la intervencion, que es lo unico que se quiere ver."""
    mapas = mapas_de_escenario(_escenario_de_mapas())

    assert mapas["base"]["clase"]["A"] == "Alto"
    assert mapas["simulado"]["clase"]["A"] == "Medio"
    # Un vano sin intervencion se pinta igual en los dos: la diferencia es la obra.
    assert mapas["base"]["clase"]["B"] == mapas["simulado"]["clase"]["B"] == "Medio-Alto"
    assert mapas["base"]["valor"]["A"] == 3 and mapas["simulado"]["valor"]["A"] == 1


def test_the_maps_declare_which_vanos_were_intervened():
    """Sin la lista, un lector que ve dos mapas casi iguales no puede distinguir 'la
    intervencion no movio nada' de 'no se intervino casi nada'."""
    mapas = mapas_de_escenario(_escenario_de_mapas())

    assert mapas["intervenidos"] == ["A"]


def test_a_scenario_without_simulation_still_yields_a_base_map():
    """Un circuito cuyo diagnostico no señalo ningun vano critico sigue teniendo un mapa
    base que decir: el simulado sale identico al base y la lista de intervenidos vacia,
    que es la lectura correcta -- no hay nada que intervenir."""
    escenario = _escenario_de_mapas()
    escenario["simulacion"] = {"vanos": []}

    mapas = mapas_de_escenario(escenario)

    assert mapas["intervenidos"] == []
    assert mapas["base"]["clase"] == mapas["simulado"]["clase"]


# --- La simulacion del informe: solo lo que una cuadrilla puede ejecutar ------------------


def test_the_report_simulation_only_moves_intervention_levers():
    """El informe sustenta una ORDEN DE TRABAJO. Un escenario -- lluvia, viento -- no se
    ejecuta: incluirlo produce una caida de UITI que nadie puede comprar, y presentada
    junto a la poda se lee como si fuera igual de accionable.

    Las de escenario no desaparecen del modelo: entran con el valor observado de cada
    vano, que es lo que corresponde. Lo que no hacen es moverse.
    """
    recursos = _recursos()
    recursos.grupos_por_knob = {"u_driver": "Escenario"}

    resultado = simulacion_de_circuito(recursos, circuito="C1", ventana="W1",
                                       fids=["V2"])

    assert resultado["knobs_usados"] == [], "un control de escenario no se mueve"
    assert resultado["solo_intervencion"] is True


def test_the_report_simulation_reports_base_and_simulated_uiti_and_class():
    """Las dos barras del informe -- medido y estimado -- y el grupo de criticidad de
    cada una. Sin la clase, una caida de UITI no dice si el vano cambio de grupo, que es
    la unidad en la que se decide."""
    recursos = _recursos()
    recursos.grupos_por_knob = {"u_driver": "Intervencion"}

    resultado = simulacion_de_circuito(recursos, circuito="C1", ventana="W1",
                                       fids=["V2"])

    assert resultado["knobs_usados"] == ["u_driver"]
    fila = resultado["vanos"][0]
    assert {"fid", "u_base", "u_simulado", "clase_base", "clase_simulada"} <= set(fila)
    assert fila["u_simulado"] <= fila["u_base"], "la intervencion no puede empeorarlo"


def test_the_report_simulation_without_marked_vanos_is_empty_not_the_whole_circuit():
    """Sin vanos identificados no hay nada que simular. Caer al circuito completo
    produciria un plan sobre vanos que el diagnostico no señalo, presentado como si
    los hubiera señalado."""
    recursos = _recursos()
    recursos.grupos_por_knob = {"u_driver": "Intervencion"}

    assert simulacion_de_circuito(recursos, circuito="C1", ventana="W1",
                                  fids=[])["vanos"] == []


def test_the_difference_graph_is_read_from_the_attribute_the_model_actually_has():
    """`edge_index` cuelga de `modelo.model`, no de `modelo.model.base`.

    Buscarlo en el sitio equivocado no revienta: la guarda devuelve `None` y el
    informe pierde el panel EN SILENCIO. Medido contra el artefacto real, esa era la
    diferencia entre un grafo y ningun grafo, sin un solo mensaje de error.
    """
    recursos = _recursos()
    recursos.grupos_por_knob = {"u_driver": "Intervencion"}

    class _ModeloConAristas:
        edge_index = np.array([[0, 1], [1, 0]])

    recursos.modelo.model = _ModeloConAristas()
    recursos.modelo.device = "cpu"

    assert _aristas_del_modelo(recursos.modelo) is not None
    # Y en el sitio viejo NO esta, que es lo que hacia fallar la lectura.
    assert getattr(getattr(recursos.modelo.model, "base", None), "edge_index", None) is None


# --- El grafo diferencia no cabe en el contexto del agente --------------------------------


def test_the_difference_graph_matrix_never_reaches_the_agent_context():
    """La matriz es de `n_features x n_features` -- 6.400 numeros con el modelo real.

    El agente no puede leer una matriz cruda, y ademas ni siquiera es serializable: un
    `ndarray` dentro de `inference.bc.json` revienta `json.dumps` y tumba la corrida
    entera al escribir el artefacto. Lo que el agente necesita son las aristas que MAS se
    movieron, que es lo mismo que dibuja el panel.
    """
    escenario = {
        "ventana": "V1",
        "simulacion": {
            "grafo_diferencia": {
                "voided": False,
                "matriz": np.array([[0.0, 0.9, 0.1],
                                    [0.9, 0.0, 0.5],
                                    [0.1, 0.5, 0.0]]),
                "n_vanos": 7,
                "colapso": 0.2,
            }
        },
    }

    compactar_grafo_del_escenario(escenario, features=["A", "B", "C"], top=2)

    grafo = escenario["simulacion"]["grafo_diferencia"]
    assert "matriz" not in grafo
    assert grafo["n_vanos"] == 7
    assert [a["movimiento"] for a in grafo["aristas"]] == [0.9, 0.5]
    assert grafo["aristas"][0]["entre"] == ["A", "B"]
    # Y lo que queda tiene que poder escribirse a disco.
    import json
    json.dumps(escenario)


def test_a_voided_difference_graph_says_so_instead_of_vanishing():
    """Un grafo anulado -- menos de tres vanos -- se declara. Borrarlo se lee como que la
    intervencion no movio nada, que es lo contrario de 'no se pudo estimar'."""
    escenario = {"simulacion": {"grafo_diferencia": {
        "voided": True, "matriz": None, "n_vanos": 2, "colapso": 1.0}}}

    compactar_grafo_del_escenario(escenario, features=["A"], top=5)

    grafo = escenario["simulacion"]["grafo_diferencia"]
    assert grafo["voided"] is True
    assert grafo["aristas"] == []
    assert grafo["n_vanos"] == 2


def test_a_scenario_without_a_difference_graph_is_left_alone():
    escenario = {"simulacion": {"grafo_diferencia": None}}

    compactar_grafo_del_escenario(escenario, features=["A"], top=5)

    assert escenario["simulacion"]["grafo_diferencia"] is None
