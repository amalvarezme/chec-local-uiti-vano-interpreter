"""RED/GREEN tests for row 4 of notebook 06: observed against simulated UITI.

Two bars per selected vano -- the `uiti_acumulado` MEASURED in the active window
and the UITI the model predicts after the intervention -- plus a last group with
the whole circuit.

The error bar is the piece that needed measuring rather than inventing. Two
candidates were tried on real data:

  * Bootstrap over the bag's own events: resample the instances of each bag and
    re-predict. Measured over 50 and 200 replicas on AGU23L14: relative standard
    deviation 0.000. The prediction does not depend on which events fell in the
    bag, so that bar would have been decoration.
  * The model's own offset on that bag, `|u_base - observado|`. Measured over
    599 real bags: median relative error 39,4%, p90 104%, and the sum runs
    +34,0% above the observed total (Pearson 0,950 -- it ranks well, the LEVEL is
    off). That is the dominant uncertainty by two orders of magnitude, it is
    local to each vano, and it costs no extra model call.

The second one is what the bars carry, and the title's `+-` is its total. That
matters for reading the figure: the base bar is a measurement and the simulated
one is a prediction, so the naked difference between them carries the model's
level error. The `+-` is exactly what covers it.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from chec_local_interpreter.simulador_variables import (
    barras_uiti_por_vano,
    rotacion_radial,
)


def _tabla():
    return pd.DataFrame(
        {
            "FID_VANO": ["VA", "VB"],
            "n_obs": [4, 2],
            "u_base": [12.0, 30.0],
            "u_simulado": [8.0, 25.0],
            "base_clase_idx": [3, 2],
            "simulado_clase_idx": [2, 2],
            "delta_riesgo_ordinal": [-1, 0],
        }
    )


def test_one_group_per_vano_with_the_measured_and_the_predicted_value():
    """La barra base es el `uiti_acumulado` MEDIDO en la ventana, no la base del
    modelo: es el dato de la base de datos, que es contra lo que el usuario compara."""
    barras = barras_uiti_por_vano(_tabla(), observados={"VA": 10.0, "VB": 28.0},
                                  total_circuito=100.0)

    assert barras["x"][:2] == ["VA", "VB"]
    assert barras["observado"][:2] == [10.0, 28.0]
    assert barras["simulado"][:2] == [8.0, 25.0]


def test_the_error_bar_is_the_models_own_offset_on_that_bag():
    """`|u_base - observado|`: lo que el modelo se equivoco en la BASE de ese mismo
    vano. Es la unica incertidumbre local medible -- el bootstrap sobre los eventos
    de la bolsa da cero -- y va sobre la barra simulada, que es la predicha."""
    barras = barras_uiti_por_vano(_tabla(), observados={"VA": 10.0, "VB": 28.0},
                                  total_circuito=100.0)

    assert barras["error"][:2] == [2.0, 2.0]  # |12-10| y |30-28|


def test_the_last_group_is_the_whole_circuit():
    """El ultimo grupo son TODOS los vanos originales: sin el, la figura dice cuanto
    baja la seleccion pero no cuanto pesa esa bajada en el circuito."""
    barras = barras_uiti_por_vano(_tabla(), observados={"VA": 10.0, "VB": 28.0},
                                  total_circuito=100.0)

    assert barras["x"][-1] == barras["etiqueta_total"]
    assert barras["observado"][-1] == 100.0
    # Los no seleccionados se quedan como estan; solo los simulados cambian.
    assert barras["simulado"][-1] == pytest.approx(100.0 - (10.0 + 28.0) + (8.0 + 25.0))
    # El error del total es la SUMA de los desfases y no su cuadratura: el sesgo del
    # modelo es sistematico -- medido, +34% sobre 599 bolsas -- asi que sumarlos en
    # cuadratura afirmaria una cancelacion que no ocurre.
    assert barras["error"][-1] == pytest.approx(4.0)


def test_the_headline_reduction_carries_its_deviation():
    """El titulo dice cuanto baja el UITI acumulado y con cuanta incertidumbre. Sin
    el `+-`, una bajada de 5 con un desfase de 4 se leeria como un resultado firme."""
    barras = barras_uiti_por_vano(_tabla(), observados={"VA": 10.0, "VB": 28.0},
                                  total_circuito=100.0)

    assert barras["reduccion"] == pytest.approx((10.0 + 28.0) - (8.0 + 25.0))
    assert barras["desviacion"] == pytest.approx(4.0)


def test_a_vano_without_a_measured_cell_is_left_out_of_the_bars():
    """Un vano puntuado sin celda en la ventana activa no tiene valor medido contra
    el que comparar. Ponerlo con base cero afirmaria que su UITI observado fue cero,
    que es justo lo que nadie midio."""
    barras = barras_uiti_por_vano(_tabla(), observados={"VA": 10.0}, total_circuito=100.0)

    assert barras["x"][:-1] == ["VA"]
    assert barras["simulado"][-1] == pytest.approx(100.0 - 10.0 + 8.0)


def test_no_simulation_yields_empty_bars_and_no_headline():
    """Sin resultado no se dibuja un cero: un cero seria una reduccion nula medida,
    y lo que pasa es que nadie corrio el modelo."""
    barras = barras_uiti_por_vano(None, observados={}, total_circuito=0.0)

    assert barras["x"] == []
    assert barras["reduccion"] is None


# --- Rotacion de los rotulos del grafo circular ---------------------------------------


@pytest.mark.parametrize(
    "angulo, esperado_anclaje",
    [(0, "left"), (45, "left"), (90, "left"), (135, "right"), (180, "right"),
     (225, "right"), (270, "left"), (315, "left")],
)
def test_radial_labels_never_read_upside_down(angulo, esperado_anclaje):
    """El rotulo sale del nodo hacia AFUERA del circulo y siempre se lee de
    izquierda a derecha. En la mitad izquierda eso obliga a girar media vuelta y a
    anclar por el otro lado; sin eso, la mitad de los nombres quedan al reves."""
    x, y = math.cos(math.radians(angulo)), math.sin(math.radians(angulo))

    giro, anclaje = rotacion_radial(x, y)

    assert anclaje == esperado_anclaje
    # Leible siempre: el texto nunca queda cabeza abajo. La holgura es por el mismo
    # motivo que la de la funcion -- en la base del circulo `cos` no da cero exacto y
    # el giro sale como 90 mas un femto --, no por permitir un giro de mas.
    assert -90.0 - 1e-9 <= giro <= 90.0 + 1e-9


def test_the_label_follows_the_radius_of_its_node():
    """Un nodo a 30 grados lleva su rotulo girado 30 grados: es lo que hace que los
    nombres sigan la secuencia del circulo en vez de cruzarse sobre las aristas.
    `textangle` de plotly gira en sentido HORARIO, de ahi el signo."""
    x, y = math.cos(math.radians(30)), math.sin(math.radians(30))

    giro, anclaje = rotacion_radial(x, y)

    assert giro == pytest.approx(-30.0)
    assert anclaje == "left"


def test_the_centre_has_no_radius_to_follow():
    """Un nodo exactamente en el centro no tiene direccion radial. Se deja horizontal
    en vez de inventarle un angulo desde un atan2 de (0, 0)."""
    assert rotacion_radial(0.0, 0.0) == (0.0, "left")
