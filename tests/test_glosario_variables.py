"""El glosario que pone las variables del dataset en castellano.

El informe escribia los codigos de columna pelados: `NR_T` veinticuatro veces y `DDT`
veintisiete en el de DON23L14, sin decir en ningun sitio que son. Quien lo lee sabe de
redes de distribucion, no de nombres de columna de este CSV en particular.

Los nombres NO se inventan aqui: salen de la tabla de `docs/ContextoProyectoSimuladorCHEC.md`,
que es el documento de contexto del proyecto, y coinciden con los que ya usa el tablero
del clima (`src/chec_tableros/clima.py`).
"""

from __future__ import annotations

import pytest

from chec_local_interpreter.glosario_variables import (
    NOMBRE_NATURAL,
    nombre_con_codigo,
    nombre_natural,
)


def test_una_variable_se_presenta_como_nombre_y_codigo_entre_parentesis():
    """El codigo no se pierde: es lo que hay que buscar en el dataset o en el tablero."""
    assert nombre_con_codigo("NR_T") == "Riesgo por vegetacion cercana al vano (NR_T)"
    assert nombre_con_codigo("DDT") == "Densidad de descargas a tierra (DDT)"


def test_una_variable_climatica_con_rezago_conserva_su_rezago_en_el_codigo():
    """`temp_3` es la temperatura TRES horas antes del evento. Perder el `_3` al
    traducir borraria justo lo que distingue un rezago de otro, que es de lo que habla
    el analisis de estres acumulado."""
    assert nombre_con_codigo("temp_3") == "Temperatura del aire (temp_3)"
    assert nombre_con_codigo("wind_gust_spd_11") == "Rafagas de viento (wind_gust_spd_11)"
    assert nombre_con_codigo("PREP_0") == "Precipitacion (PREP_0)"


def test_la_familia_sin_rezago_tambien_se_traduce():
    """El grafo del informe PLIEGA los rezagos, asi que le llegan `temp` y `PREP` a
    secas. Sin esta rama, justo los nodos del anillo se quedarian sin traducir."""
    assert nombre_natural("temp") == "Temperatura del aire"
    assert nombre_natural("PREP") == "Precipitacion"


def test_una_variable_que_no_esta_en_el_glosario_se_deja_como_esta():
    """Inventar un nombre para una columna desconocida es peor que mostrar el codigo:
    el lector no puede distinguir un nombre real de uno adivinado."""
    assert nombre_natural("COLUMNA_QUE_NO_EXISTE") == "COLUMNA_QUE_NO_EXISTE"
    assert nombre_con_codigo("COLUMNA_QUE_NO_EXISTE") == "COLUMNA_QUE_NO_EXISTE"


def test_no_se_repite_el_codigo_cuando_no_hay_nombre_que_anteponer():
    """`COLUMNA (COLUMNA)` se lee como un error del informe, y lo es."""
    salida = nombre_con_codigo("NO_ESTA")
    assert salida.count("NO_ESTA") == 1


def test_el_glosario_no_distingue_mayusculas():
    """El dataset escribe `TEMP_i` en la documentacion y `temp_0` en las features."""
    assert nombre_natural("temp_0") == nombre_natural("TEMP_0")
    assert nombre_natural("nr_t") == nombre_natural("NR_T")


@pytest.mark.parametrize("codigo", sorted(NOMBRE_NATURAL))
def test_ningun_nombre_del_glosario_repite_su_propio_codigo(codigo):
    """Un nombre que es el codigo otra vez no traduce nada y llena la linea."""
    nombre = NOMBRE_NATURAL[codigo]
    assert nombre.upper() != codigo.upper()
    assert nombre.strip() == nombre and nombre


def test_estan_las_variables_que_el_informe_nombra_de_verdad():
    """Las que aparecen en los informes reales. Un glosario que no cubra estas no
    cambia nada de lo que el lector ve."""
    for codigo in ("NR_T", "DDT", "CAPACIDAD_NOMINAL", "CONDUCTOR", "TIPO",
                   "CALIBRE_NEUTRO", "NG_RED", "CANTIDAD_TIERRA", "ALTURA",
                   "CNT_VN", "PROMEDIO_KWH_TRF", "UITI_VANO", "COD_CAUSA"):
        assert nombre_natural(codigo) != codigo, f"{codigo} no tiene nombre natural"


# ---------------------------------------------------------------------------
# Que llegue al informe, que es donde se veia el problema.
# ---------------------------------------------------------------------------


def test_el_contexto_de_dominio_no_reparte_claves_de_maquina():
    """`topology_protection`, `weather_environmental_stress` y
    `environment_operational_hypotheses` salian IMPRESAS en el informe de DON23L14:
    dos, dos y tres veces. El agente las citaba porque estaban en su contexto.

    Un identificador en snake_case ingles dentro de un informe para operacion no
    aclara nada y hace parecer que el texto lo escribio el programa. Se quitan de la
    fuente, que es la unica forma de que no puedan citarse.
    """
    import re

    from chec_local_interpreter.domain_context import domain_context_payload

    payload = domain_context_payload()
    plano = repr(payload)
    for jerga in ("topology_protection", "weather_environmental_stress",
                  "environment_operational_hypotheses", "physical_susceptibility",
                  "assets_exposure", "load_impact", "duration_users_uiti",
                  "spatial_traceability", "protection_restoration_context"):
        assert jerga not in plano, f"el contexto sigue repartiendo {jerga!r}"

    # y ninguna clave nueva con la misma forma
    for regla in payload["relationship_rules"]:
        for valor in regla.values():
            if isinstance(valor, str):
                assert not re.fullmatch(r"[a-z]+(_[a-z]+){2,}", valor), (
                    f"{valor!r} parece una clave de maquina")


def test_cada_regla_del_dominio_se_nombra_en_castellano():
    from chec_local_interpreter.domain_context import domain_context_payload

    reglas = domain_context_payload()["relationship_rules"]
    assert reglas
    for regla in reglas:
        assert regla.get("nombre"), f"regla sin nombre: {regla}"
        assert regla.get("description")


def test_los_grupos_de_variables_traen_el_nombre_natural_de_cada_una():
    """El agente recibe los codigos; si no le llega tambien el nombre, no puede
    escribirlo aunque se lo pidan."""
    from chec_local_interpreter.domain_context import domain_context_payload

    grupos = domain_context_payload()["variable_groups"]
    entorno = grupos["Entorno/Riesgo"]
    assert "Riesgo por vegetacion cercana al vano (NR_T)" in entorno["variables_nombradas"]
    # el listado de codigos sigue estando: es lo que hay que cruzar contra el dataset
    assert "NR_T" in entorno["variables"]


def test_el_comodin_de_rezago_de_la_documentacion_tambien_se_traduce():
    """`VARIABLE_GROUPS` escribe `PREP_i` y `TEMP_i`, con la `i` literal: es como la
    documentacion nombra a la familia entera, no un rezago concreto.

    La regla de rezago exige que el sufijo sean TODO digitos -- y tiene que exigirlo,
    porque si no `TIPO_TAX` se fundiria con `TIPO` --, asi que estas se colaban sin
    traducir justo en la lista que el agente recibe.
    """
    assert nombre_natural("PREP_i") == "Precipitacion"
    assert nombre_con_codigo("TEMP_i") == "Temperatura del aire (TEMP_i)"
    assert nombre_con_codigo("WIND_GUST_SPD_i") == "Rafagas de viento (WIND_GUST_SPD_i)"
    # y la guarda sigue en pie
    assert nombre_natural("TIPO_TAX") == "Taxonomia constructiva del vano"


def test_el_contexto_de_inferencia_tambien_recibe_los_nombres():
    """El glosario llegaba SOLO al historiador.

    Detectado por el propio agente de inferencia en una corrida real: su sobre no trae
    `domain`, asi que no trae `variables_nombradas`. Solo `features`, ochenta codigos
    pelados. Tuvo que sacar los nombres de su propio playbook, que es como dos juegos
    de nombres para las mismas columnas empiezan a separarse -- justo lo que el glosario
    existe para cerrar.
    """
    import numpy as np

    from chec_local_interpreter.mil_inferencia import RecursosMIL, construir_contexto_inferencia_mil

    class _BagIndex:
        keys = None
        offsets = np.array([0], dtype=np.int64)
        counts = np.array([], dtype=np.int64)
        y = np.array([])

    import pandas as pd
    bag = _BagIndex()
    bag.keys = pd.DataFrame({"CIRCUITO": [], "FID_VANO": [], "VENTANA": []})

    recursos = RecursosMIL(
        modelo=object(), X_inst=np.zeros((0, 3), dtype=np.float32),
        features=["NR_T", "DDT", "temp_0"], bag_index=bag, knobs=[],
    )

    contexto = construir_contexto_inferencia_mil(
        recursos, circuito="C1", fecha_inicio="2026-01-01", fecha_fin="2026-01-31")

    assert contexto["features_nombradas"] == [
        "Riesgo por vegetacion cercana al vano (NR_T)",
        "Densidad de descargas a tierra (DDT)",
        "Temperatura del aire (temp_0)",
    ]
    # los codigos siguen: son la clave contra el modelo y contra el dataset
    assert contexto["features"] == ["NR_T", "DDT", "temp_0"]
