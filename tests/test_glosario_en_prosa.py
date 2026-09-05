"""Toda variable que llega a los OJOS del lector va `Nombre natural (CODIGO)`.

El codigo solo no dice nada a quien lee el informe -- `DDT` no es "densidad de descargas
a tierra" para nadie fuera del equipo -- y el nombre solo no se puede buscar en la tabla
ni en el simulador. El glosario ya resuelve las dos mitades en
`glosario_variables.nombre_con_codigo`; lo que fallaba era que no todos los sitios lo
llamaban.

Las FIGURAS son la excepcion deliberada: en una barra, un violin o un nodo del grafo el
nombre completo no cabe y el eje ya dice de que se habla, asi que ahi va el codigo pelado.
"""

from __future__ import annotations

import pandas as pd
import pytest

from chec_local_interpreter.glosario_variables import nombre_con_codigo
from chec_local_interpreter.plotting import render_llm_analysis


def _raw_df() -> pd.DataFrame:
    return pd.DataFrame({
        "CIRCUITO": ["C1"] * 4,
        "FID_VANO": ["v1", "v2", "v3", "v4"],
        "FECHA": pd.to_datetime(["2026-01-01"] * 4),
        "UITI_VANO": [1.0, 2.0, 3.0, 4.0],
    })


def test_el_glosario_traduce_el_codigo_del_ejemplo():
    """El caso que el usuario nombro, contra el glosario real."""
    assert nombre_con_codigo("DDT") == "Densidad de descargas a tierra (DDT)"


def test_un_codigo_fuera_del_glosario_no_se_duplica():
    """Sin esta rama saldria `XYZ (XYZ)`, que se lee como un fallo del informe."""
    assert nombre_con_codigo("XYZ_INEXISTENTE") == "XYZ_INEXISTENTE"
    assert nombre_con_codigo("") == ""


def test_la_tabla_de_variables_a_priorizar_nombra_la_variable(tmp_path):
    """La columna `Variable` de "Comparación con reportes expertos" salia con el codigo
    crudo. Es la tabla que un gerente lee para decidir donde intervenir."""
    analysis = {
        "contexto": {"fuentes_usadas": ["Agente Descriptor"], "n_filas_expertas_comparadas": 0},
        "variables_a_priorizar": [
            {"variable": "DDT", "prioridad": "alta",
             "fuentes_que_la_respaldan": ["Agente Descriptor"],
             "justificacion": "j", "tipo_de_validacion_sugerida": "v"},
        ],
    }
    html = render_llm_analysis(
        validation_data={}, raw_df=_raw_df(), selected_circuitos=["C1"],
        inference_results=None, inference_analysis={}, output_dir=tmp_path,
        expert_alignment_analysis=analysis,
    ).read_text(encoding="utf-8")

    assert "Densidad de descargas a tierra (DDT)" in html
    assert "<td>DDT</td>" not in html, "la variable llego cruda a la tabla"


# ---------------------------------------------------------------------------
# Expansion en PROSA: el codigo se nombra la primera vez que aparece
# ---------------------------------------------------------------------------


def test_nombra_el_codigo_la_primera_vez_que_aparece():
    from chec_local_interpreter.glosario_variables import nombrar_en_prosa

    texto = "El riesgo sube con DDT en las tres ventanas."
    assert nombrar_en_prosa(texto) == (
        "El riesgo sube con Densidad de descargas a tierra (DDT) en las tres ventanas.")


def test_las_familias_de_clima_tambien_se_nombran_en_prosa():
    """`PREP_i` es un codigo como `NR_T`, y salia pelado en el informe.

    La alternancia se construia solo con las claves de `NOMBRE_NATURAL`, y las cuatro
    variables de clima no viven ahi sino en `FAMILIAS_CLIMA`. `nombre_con_codigo` SI las
    resolvia -- se llama por codigo suelto y pasa por `nombre_natural` --, asi que las
    tablas salian bien y solo la PROSA quedaba sin nombrar: medido sobre el informe de
    DON23L13, `PREP_i`, `WIND_SPD_i` y `WIND_GUST_SPD_i` aparecian una vez cada uno y
    ninguna con su nombre, mientras `NR_T` y `DDT` si lo llevaban en la misma seccion.

    La forma con `_i` es la que usa la documentacion para nombrar a la familia entera
    (`domain.variable_groups` lista `PREP_i`, no los doce rezagos), y es la que el agente
    escribe.
    """
    from chec_local_interpreter.glosario_variables import nombrar_en_prosa

    texto = ("La hipotesis apoya en PREP_i, WIND_SPD_i y WIND_GUST_SPD_i sobre el "
             "vano, junto a NR_T.")

    salida = nombrar_en_prosa(texto)

    assert "Precipitación (PREP_i)" in salida
    assert "Velocidad del viento (WIND_SPD_i)" in salida
    assert "Ráfagas de viento (WIND_GUST_SPD_i)" in salida
    # Y la que ya funcionaba sigue funcionando.
    assert "Riesgo por vegetación cercana al vano (NR_T)" in salida


def test_la_rafaga_gana_sobre_la_velocidad_del_viento():
    """`WIND_GUST_SPD_i` y `WIND_SPD_i` comparten cola. La alternancia va de mas largo a
    mas corto justamente para que la rafaga no acabe nombrada como velocidad con un
    `GUST_` suelto delante."""
    from chec_local_interpreter.glosario_variables import nombrar_en_prosa

    salida = nombrar_en_prosa("Solo WIND_GUST_SPD_i pesa aqui.")

    assert "Ráfagas de viento (WIND_GUST_SPD_i)" in salida
    assert "Velocidad del viento" not in salida


def test_no_repite_el_nombre_en_cada_aparicion():
    """Nombrarlo en cada mencion convierte un parrafo en una lista de definiciones. Se
    presenta una vez, como en cualquier texto tecnico, y despues va el codigo."""
    from chec_local_interpreter.glosario_variables import nombrar_en_prosa

    salida = nombrar_en_prosa("DDT sube, y DDT baja, y DDT vuelve a subir.")

    assert salida.count("Densidad de descargas a tierra") == 1
    assert salida.count("DDT") == 3


def test_respeta_lo_que_el_agente_ya_escribio_bien():
    from chec_local_interpreter.glosario_variables import nombrar_en_prosa

    ya = "La densidad de descargas a tierra (DDT) domina el periodo, y DDT no cede."
    assert nombrar_en_prosa(ya) == ya


def test_no_toca_la_palabra_corriente_en_minuscula():
    """`TIPO` y `CONDUCTOR` son codigos; `tipo` y `conductor` son castellano. Una regla
    que ignore la caja llena el informe de ruido -- y es el mismo error que ya se pago
    una vez con `DURACION`, que es columna y no palabra."""
    from chec_local_interpreter.glosario_variables import nombrar_en_prosa

    texto = "El tipo de conductor no explica el patrón; TIPO sí aparece en el modelo."
    salida = nombrar_en_prosa(texto)

    assert "El tipo de conductor no explica" in salida
    assert "Tipo de equipo de protección (TIPO)" in salida


def test_el_codigo_pegado_a_otra_palabra_no_cuenta():
    from chec_local_interpreter.glosario_variables import nombrar_en_prosa

    assert nombrar_en_prosa("la variable DDT_EXTRA no existe") == "la variable DDT_EXTRA no existe"


def test_un_texto_vacio_o_ausente_no_revienta():
    from chec_local_interpreter.glosario_variables import nombrar_en_prosa

    assert nombrar_en_prosa("") == ""
    assert nombrar_en_prosa(None) == ""


# ---------------------------------------------------------------------------
# La pasada sobre la respuesta entera del agente
# ---------------------------------------------------------------------------


def test_la_pasada_nombra_la_prosa_y_respeta_la_identidad():
    """`variable` es la CLAVE con la que el grafo radial agrupa estrategias entre
    circuitos y la que viaja al `.resumen.json`. Expandirla ahi rompe el agrupamiento y
    ademas duplica el nombre, porque la tabla ya la pasa por el glosario al pintarla.
    La prosa de al lado si se expande."""
    from chec_local_interpreter.glosario_variables import nombrar_prosa_en_datos

    datos = {
        "variables_a_priorizar": [
            {"variable": "DDT", "justificacion": "DDT domina el periodo"},
        ],
    }
    salida = nombrar_prosa_en_datos(datos)

    item = salida["variables_a_priorizar"][0]
    assert item["variable"] == "DDT", "la identidad no se toca"
    assert item["justificacion"] == "Densidad de descargas a tierra (DDT) domina el periodo"


def test_la_pasada_no_muta_la_entrada():
    """El mismo dict lo leen despues el grafo radial y el `.resumen.json`."""
    from chec_local_interpreter.glosario_variables import nombrar_prosa_en_datos

    datos = {"nota": "NR_T sube"}
    salida = nombrar_prosa_en_datos(datos)

    assert datos["nota"] == "NR_T sube"
    assert salida["nota"] != datos["nota"]


def test_la_pasada_deja_intactas_las_listas_de_codigos():
    from chec_local_interpreter.glosario_variables import nombrar_prosa_en_datos

    datos = {"variable_groups_used": ["Proteccion"], "data_ref": "NR_T",
             "variables_modelo_predictivo": ["NR_T", "DDT"]}
    salida = nombrar_prosa_en_datos(datos)

    assert salida["variable_groups_used"] == ["Proteccion"]
    assert salida["data_ref"] == "NR_T"
    assert salida["variables_modelo_predictivo"] == ["NR_T", "DDT"]


def test_no_se_expande_dentro_del_nombre_que_acaba_de_insertar():
    """`UITI_VANO` se expande a "UITI atribuido al vano (UITI_VANO)", y la pasada
    siguiente encontraba ese `UITI` recien insertado y lo expandia otra vez:

        un Usuarios interrumpidos por tiempo de interrupcion (UITI) atribuido al vano (UITI_VANO)

    Un reemplazo sobre el texto que el reemplazo anterior acaba de cambiar es una
    receta para esto. Los codigos se buscan UNA vez, sobre el texto original.
    """
    from chec_local_interpreter.glosario_variables import nombrar_en_prosa

    salida = nombrar_en_prosa("un UITI_VANO acumulado de 283.733")

    assert salida == "un UITI atribuido al vano (UITI_VANO) acumulado de 283.733"
    assert "(UITI)" not in salida


def test_el_codigo_corto_se_nombra_si_aparece_por_su_cuenta():
    """La guarda anterior no puede volverse "nunca expandas UITI": cuando el agente
    escribe `UITI` suelto, sigue habiendo que decir que es."""
    from chec_local_interpreter.glosario_variables import nombrar_en_prosa

    salida = nombrar_en_prosa("el UITI del circuito y su UITI_VANO")

    assert salida.startswith("el Usuarios interrumpidos por tiempo de interrupción (UITI) del circuito")
    assert "UITI atribuido al vano (UITI_VANO)" in salida


# ---------------------------------------------------------------------------
# Los nombres de GRUPO tambien llegan a la pantalla
# ---------------------------------------------------------------------------


def test_el_grupo_canonico_se_escribe_acentuado_cuando_se_muestra():
    """`Proteccion` y `Topologia` son identificadores del esquema y por eso van sin tilde
    en `variable_groups_used`. Pero el informe los IMPRIMIA tal cual ("Modo Topologia"),
    y ahi son texto para un lector, no una clave. `NOMBRE_LEGIBLE_GRUPO` existe justo
    para esa traduccion.
    """
    from chec_local_interpreter.domain_context import NOMBRE_LEGIBLE_GRUPO

    assert NOMBRE_LEGIBLE_GRUPO["Proteccion"] == "Protección"
    assert NOMBRE_LEGIBLE_GRUPO["Topologia"] == "Topología"


def test_el_informe_no_imprime_el_grupo_sin_tilde(tmp_path):
    validation = {
        "circuit_characterization": {
            "probable_justifications_rules": [
                {"modo": "Topologia", "variables_asociadas": ["FID_VANO"],
                 "justificacion_fisico_logica": "j", "analisis_causas": "a"},
            ],
        },
    }
    html = render_llm_analysis(
        validation_data=validation, raw_df=_raw_df(), selected_circuitos=["C1"],
        inference_results=None, inference_analysis={}, output_dir=tmp_path,
    ).read_text(encoding="utf-8")

    assert "Modo Topología" in html
    assert "Modo Topologia" not in html
