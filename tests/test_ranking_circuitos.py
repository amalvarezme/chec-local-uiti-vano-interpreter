"""El ranking de circuitos del cuaderno 02, portado a Python para el informe.

El informe abria con el agrupamiento de CIRCUITOS -- una nube de 208 puntos por eventos
contra UITI --, que responde "de que tamano es este circuito comparado con los demas".
La pregunta operativa es otra: **cuantos vanos criticos tiene**. Un circuito chico con
cuarenta vanos en Medio-Alto se atiende antes que uno grande con tres, y en la nube los
dos son un punto y no hay forma de verlo.

Este es el mismo calculo del segundo tablero del cuaderno 02: agrupamiento a nivel de
VANO, y por circuito el conteo de sus vanos en Medio-Alto mas Alto. Se porta verbatim --
mismo espacio (eje x lineal, eje y log10), mismo escalador, misma semilla, mismos cortes
P50/P75/P97 -- porque dos implementaciones del mismo ranking se separan en cuanto alguien
toca una, y entonces el tablero y el informe ordenan los circuitos distinto sin que nada
lo diga.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chec_local_interpreter.ranking_circuitos import (
    NOMBRES_RANGO,
    geometria_vanos,
    grupo_de_vanos,
    ranking_circuitos,
)


def _eventos(filas):
    """`filas` es (circuito, fid, n_eventos, uiti_total, fecha_base)."""
    piezas = []
    for circuito, fid, n, uiti, fecha in filas:
        fechas = pd.date_range(fecha, periods=n, freq="D").strftime("%Y-%m-%d").tolist()
        piezas.append(pd.DataFrame({
            "CIRCUITO": [circuito] * n,
            "FID_VANO": [fid] * n,
            "FECHA": fechas,
            "UITI_VANO": [uiti / n] * n,
        }))
    return pd.concat(piezas, ignore_index=True)


def _base_de_cuatro_grupos():
    """Cuatro familias de vanos bien separadas, repartidas en tres circuitos.

    C_ALTO se lleva los dos vanos peores, C_MEDIO los intermedios y C_TRANQUILO los
    flojos. Es lo que hace comprobable el orden del ranking.
    """
    return _eventos([
        ("C_ALTO", "A1", 30, 40000.0, "2026-01-01"),
        ("C_ALTO", "A2", 28, 38000.0, "2026-01-01"),
        ("C_ALTO", "A3", 12, 900.0, "2026-01-01"),
        ("C_MEDIO", "M1", 11, 850.0, "2026-01-01"),
        ("C_MEDIO", "M2", 10, 800.0, "2026-01-01"),
        ("C_TRANQUILO", "T1", 3, 20.0, "2026-01-01"),
        ("C_TRANQUILO", "T2", 2, 15.0, "2026-01-01"),
        ("C_TRANQUILO", "T3", 2, 12.0, "2026-01-01"),
    ])


def test_the_ranking_counts_vanos_in_the_two_critical_groups_not_only_the_worst():
    """El conteo suma Medio-Alto Y Alto. Un circuito con muchos vanos a un paso de la
    clase peor es tan accionable como uno que ya los tiene ahi, y mirando solo Alto esa
    poblacion queda invisible -- que es justo la que todavia se puede evitar."""
    resultado = ranking_circuitos(_base_de_cuatro_grupos())

    fila = resultado.tabla.set_index("circuito").loc["C_ALTO"]
    assert fila["vanos_criticos"] == fila["vanos_medio_alto"] + fila["vanos_alto"]
    assert fila["vanos_criticos"] > 0


def test_the_ranking_orders_circuits_by_their_critical_vano_count():
    resultado = ranking_circuitos(_base_de_cuatro_grupos())

    orden = resultado.tabla["vanos_criticos"].tolist()
    assert orden == sorted(orden), "las barras se dibujan de menor a mayor"
    peor = resultado.tabla.iloc[-1]
    assert peor["circuito"] == "C_ALTO"
    assert peor["posicion"] == 1, "posicion 1 es el mas critico, no el primero dibujado"


def test_every_circuit_of_the_base_appears_even_with_no_events_in_the_window():
    """Los circuitos sin eventos en la ventana quedan en cero, a la izquierda, y CUENTAN
    para los percentiles. Excluirlos sesga los cortes hacia arriba, tanto mas cuanto mas
    corta la ventana, y el circuito estudiado aparece mejor situado de lo que esta."""
    base = _base_de_cuatro_grupos()
    # C_TRANQUILO solo tiene eventos en enero; la ventana pedida es marzo.
    resultado = ranking_circuitos(base, start_date="2026-03-01", end_date="2026-03-31")

    assert set(resultado.tabla["circuito"]) == {"C_ALTO", "C_MEDIO", "C_TRANQUILO"}
    assert resultado.circuitos_sin_eventos == 3
    assert (resultado.tabla["vanos_criticos"] == 0).all()


def test_the_cuts_are_p50_p75_and_p97_not_quartiles():
    """La distribucion tiene una cola larga: con cuartiles el ultimo grupo se lleva un
    cuarto de los circuitos y mezcla los verdaderamente criticos con los del monton. Con
    P97 el grupo de Riesgo Alto queda en el 3% superior, que es lo accionable."""
    resultado = ranking_circuitos(_base_de_cuatro_grupos())

    valores = resultado.tabla["vanos_criticos"].to_numpy()
    assert resultado.cortes == pytest.approx(
        (float(np.percentile(valores, 50)), float(np.percentile(valores, 75)),
         float(np.percentile(valores, 97)))
    )


def test_each_circuit_gets_its_risk_band_from_those_cuts():
    resultado = ranking_circuitos(_base_de_cuatro_grupos())

    for _, fila in resultado.tabla.iterrows():
        assert fila["rango"] in NOMBRES_RANGO
        q1, q2, q3 = resultado.cortes
        v = fila["vanos_criticos"]
        esperado = 0 if v <= q1 else (1 if v <= q2 else (2 if v <= q3 else 3))
        assert fila["rango"] == NOMBRES_RANGO[esperado]


def test_the_partition_is_fitted_once_over_the_full_range_not_per_window():
    """Los centroides se fijan sobre el rango COMPLETO. Si cada ventana reajustara
    K-Means, "Alto" significaria una cosa distinta en cada corrida del informe y dos
    informes del mismo circuito no serian comparables."""
    base = _base_de_cuatro_grupos()

    completa = geometria_vanos(base)
    recortada = ranking_circuitos(base, start_date="2026-01-01", end_date="2026-01-15").geometria

    assert recortada["centroides"] == completa["centroides"]
    assert recortada["offset"] == completa["offset"]


def test_the_group_of_a_vano_comes_from_the_nearest_centroid_rule():
    """La misma regla que aplica el JS del cuaderno: sin ella el informe podria pintar un
    vano de un grupo y el tablero de otro."""
    geometria = geometria_vanos(_base_de_cuatro_grupos())

    grupos = grupo_de_vanos(np.array([30.0, 2.0]), np.array([40000.0, 15.0]), geometria)

    assert grupos[0] == 3, "el vano de 30 eventos y 40.000 de UITI es Alto"
    assert grupos[1] == 0, "el de 2 eventos y 15 de UITI es Bajo"


def test_a_base_without_usable_vanos_yields_an_empty_ranking_not_a_crash():
    vacio = pd.DataFrame(columns=["CIRCUITO", "FID_VANO", "FECHA", "UITI_VANO"])

    resultado = ranking_circuitos(vacio)

    assert resultado.tabla.empty
    assert resultado.cortes == (0.0, 0.0, 0.0)


def test_vano_ids_are_normalised_so_one_vano_is_not_counted_twice():
    """`FID_VANO` llega numerico con sufijo `.0` inconsistente entre filas. Sin
    normalizar, `20130434` y `20130434.0` son dos vanos, cada uno con la mitad de los
    eventos del real, y los dos caen en un grupo mas bajo del que les toca."""
    base = pd.DataFrame({
        "CIRCUITO": ["C1"] * 4,
        "FID_VANO": ["20130434", "20130434.0", "20130434", "20130434.0"],
        "FECHA": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        "UITI_VANO": [1.0, 1.0, 1.0, 1.0],
    })

    resultado = ranking_circuitos(base)

    assert resultado.tabla.set_index("circuito").loc["C1", "vanos_con_eventos"] == 1
