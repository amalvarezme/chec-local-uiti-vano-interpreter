"""Guarda de retiro del agrupamiento K-Means de CIRCUITO.

`plotting.compute_circuit_criticality_groups` agrupaba los circuitos por
K-Means sobre (numero de eventos x UITI acumulado del circuito) y los nombraba
con CINCO etiquetas: `Riesgo Muy Alto`, `Riesgo Alto`, `Riesgo Medio-Alto`,
`Riesgo Medio-Bajo`, `Riesgo Bajo`. `plot_interactive_circuit_clustering`
dibujaba su nube y `CRITICALITY_GROUP_LABELS` / `CRITICALITY_GROUP_COLORS` le
ponian el vocabulario y la paleta.

**Por que se retiro.** Convivia con `ranking_circuitos` -- conteo de vanos en
Medio-Alto + Alto, cortado en P50/P75/P97, CUATRO bandas -- usando las mismas
palabras para decir cosas distintas. Medido sobre los 208 circuitos de la flota,
"Riesgo Alto" eran 16 circuitos por K-Means y 7 por el ranking, y solo 3 estaban
en los dos. Eso produjo dos defectos reales que costaron dos arreglos: informes
que citaban `Riesgo Muy Alto`, una etiqueta que su propia figura no podia
mostrar, y una grafica de apertura con cinco clases que ninguno de los dos
comandos que la invocaban podia nombrar.

Sus consumidores se migraron uno a uno al ranking:

- la prosa de `/report` (`context_builder._compute_circuit_characterization`),
- la banda y los slugs de `/reporte-lote` (`batch_report_contract.GROUP_SLUGS`),
- el agrupamiento y la barra de `/informe-gerencial`,
- la grafica del paso 1.5 (`circuit_clustering_contract.render_clustering`).

Cuando se borro no le quedaba NINGUN consumidor de produccion: lo unico que lo
llamaba eran sus propias pruebas.

**Que se pierde y donde estaba el valor.** La nube situaba al circuito por
TAMANO -- cuantas veces falla contra cuanto UITI acumula --, que es una pregunta
legitima y distinta de "cuantos vanos criticos tiene". Si vuelve a hacer falta,
tiene que volver con un vocabulario PROPIO que no comparta palabras con las
bandas del ranking, y sobre su propia figura. El codigo se saca de git.

**Por que la aguja es el simbolo importable y no la palabra.** Las cadenas
`Riesgo Muy Alto` y `Riesgo Medio-Bajo` se nombran a proposito en los
guardarrailes de los prompts de `historical` e `inference` -- que le prohiben al
agente escribirlas -- y en los comentarios que explican este retiro. Vigilar la
palabra pelada marcaria esas menciones legitimas.

Mismo estilo que `tests/test_relevancia_lote_retirado.py` y
`tests/test_graph_view_builder_retirado.py`.
"""

from __future__ import annotations

import pytest

SIMBOLOS_RETIRADOS = (
    "compute_circuit_criticality_groups",
    "plot_interactive_circuit_clustering",
    "CRITICALITY_GROUP_LABELS",
    "CRITICALITY_GROUP_COLORS",
    "run_kmeans",
)


@pytest.mark.parametrize("simbolo", SIMBOLOS_RETIRADOS)
def test_plotting_ya_no_expone_el_agrupamiento_kmeans_de_circuito(simbolo):
    from chec_local_interpreter import plotting

    assert not hasattr(plotting, simbolo)


@pytest.mark.parametrize(
    "simbolo", ("plot_interactive_circuit_clustering", "compute_circuit_criticality_groups")
)
def test_el_contrato_del_paso_1_5_ya_no_lo_reexporta(simbolo):
    """El envoltorio existia como punto de intercepcion de las pruebas.

    Sin funcion detras no hay nada que interceptar, y dejarlo seria un alias
    importable hacia un modulo borrado.
    """
    from chec_local_interpreter import circuit_clustering_contract

    assert not hasattr(circuit_clustering_contract, simbolo)


def test_el_unico_vocabulario_de_banda_es_el_del_ranking():
    """Lo que sustituyo a las cinco clases, afirmado de frente."""
    from chec_local_interpreter.ranking_circuitos import NOMBRES_RANGO

    assert NOMBRES_RANGO == (
        "Riesgo Bajo", "Riesgo Medio", "Riesgo Medio-Alto", "Riesgo Alto",
    )
