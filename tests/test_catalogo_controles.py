"""El catalogo de controles del informe, cacheado en disco.

Construirlo cuesta `procesar_dataset_completo` sobre el CSV entero: 2,3 s y un pico de
2,3 GB de memoria, MEDIDO, para producir 18 knobs, sus encoders y sus maximos imputados.
Ese resultado cabe en 2,6 KB y no depende del circuito ni de la ventana, asi que pagarlo
en cada corrida de `/report` es pagar el dataset completo para leer una tabla de 18 filas.

Aqui se prueba el contrato del cache: que la segunda corrida no reconstruya, que un
archivo fuente mas nuevo lo invalide, y que ninguna falla del cache -- corrupto,
ilegible, directorio de solo lectura -- tumbe una corrida que sin cache funcionaba.
"""

from __future__ import annotations

import joblib
import pytest

from chec_local_interpreter import mil_inferencia


@pytest.fixture
def fuentes(tmp_path):
    """Dos archivos fuente cuyo contenido no importa: solo su identidad en disco."""
    datos = tmp_path / "Indicadores.csv"
    datos.write_text("FECHA\n2026-01-01\n", encoding="utf-8")
    variables = tmp_path / "Variables_seleccion.xlsx"
    variables.write_bytes(b"xlsx")
    return datos, variables


@pytest.fixture
def catalogo_falso(monkeypatch):
    """Sustituye la construccion cara y cuenta cuantas veces se la llama."""
    from chec_local_interpreter.vano_controls import Knob

    llamadas = []

    def _construir(data_path, variables_path):
        llamadas.append((str(data_path), str(variables_path)))
        return mil_inferencia.CatalogoControles(
            knobs=[Knob(id="ALTURA", label="Altura", kind="numeric",
                        feature_names=("ALTURA",), bounds=(4.0, 25.0),
                        categories=None, default=None, step=None)],
            grupos={"ALTURA": "Intervencion"},
            label_encoders={},
            max_values_imputed={"ALTURA": 25.0},
        )

    monkeypatch.setattr(mil_inferencia, "_construir_catalogo_controles", _construir)
    return llamadas


def test_the_first_run_builds_the_catalogue_and_leaves_it_on_disk(tmp_path, fuentes, catalogo_falso):
    datos, variables = fuentes
    cache = tmp_path / "knobs.joblib"

    catalogo = mil_inferencia.catalogo_de_controles(datos, variables, cache_path=cache)

    assert len(catalogo_falso) == 1
    assert [k.id for k in catalogo.knobs] == ["ALTURA"]
    assert cache.exists(), "sin archivo en disco la segunda corrida vuelve a pagar el CSV"


def test_the_second_run_reads_the_cache_instead_of_rebuilding(tmp_path, fuentes, catalogo_falso):
    """Esta es toda la razon de ser del cache: la segunda corrida no toca el CSV."""
    datos, variables = fuentes
    cache = tmp_path / "knobs.joblib"

    primero = mil_inferencia.catalogo_de_controles(datos, variables, cache_path=cache)
    segundo = mil_inferencia.catalogo_de_controles(datos, variables, cache_path=cache)

    assert len(catalogo_falso) == 1, "la segunda corrida reconstruyo el catalogo"
    assert [k.id for k in segundo.knobs] == [k.id for k in primero.knobs]
    assert segundo.grupos == primero.grupos
    assert segundo.max_values_imputed == primero.max_values_imputed


def test_editing_a_source_file_invalidates_the_cache(tmp_path, fuentes, catalogo_falso):
    """Un cache que sobrevive a un cambio del CSV es peor que no tener cache: el informe
    seguiria describiendo rangos de una base que ya no existe, y nada en pantalla lo
    diria."""
    datos, variables = fuentes
    cache = tmp_path / "knobs.joblib"
    mil_inferencia.catalogo_de_controles(datos, variables, cache_path=cache)

    datos.write_text("FECHA\n2026-01-01\n2026-02-01\n", encoding="utf-8")
    mil_inferencia.catalogo_de_controles(datos, variables, cache_path=cache)

    assert len(catalogo_falso) == 2


def test_a_corrupt_cache_rebuilds_instead_of_raising(tmp_path, fuentes, catalogo_falso):
    """Un joblib truncado -- disco lleno a mitad de escritura -- no puede tumbar la
    corrida siguiente: el cache es una optimizacion, y una optimizacion que rompe el
    camino que aceleraba deja el sistema peor que antes de existir."""
    datos, variables = fuentes
    cache = tmp_path / "knobs.joblib"
    cache.write_bytes(b"esto no es un joblib")

    catalogo = mil_inferencia.catalogo_de_controles(datos, variables, cache_path=cache)

    assert len(catalogo_falso) == 1
    assert [k.id for k in catalogo.knobs] == ["ALTURA"]


def test_a_cache_from_another_shape_is_ignored_not_trusted(tmp_path, fuentes, catalogo_falso):
    """Un joblib valido pero con otra forma -- una version anterior del cache -- se
    descarta igual que uno corrupto. Confiar en el produce un `AttributeError` a mitad
    del informe, lejos de aqui y sin relacion aparente con el cache."""
    datos, variables = fuentes
    cache = tmp_path / "knobs.joblib"
    joblib.dump({"knobs": ["esto era el formato viejo"]}, cache)

    mil_inferencia.catalogo_de_controles(datos, variables, cache_path=cache)

    assert len(catalogo_falso) == 1


def test_an_unwritable_cache_location_still_returns_the_catalogue(tmp_path, fuentes, catalogo_falso, monkeypatch):
    """No poder ESCRIBIR el cache degrada a "esta corrida lo paga entero", nunca a un
    informe que no sale."""
    datos, variables = fuentes

    def _explota(*args, **kwargs):
        raise PermissionError("solo lectura")

    monkeypatch.setattr(joblib, "dump", _explota)

    catalogo = mil_inferencia.catalogo_de_controles(
        datos, variables, cache_path=tmp_path / "no-escribible" / "knobs.joblib")

    assert [k.id for k in catalogo.knobs] == ["ALTURA"]


def test_the_catalogue_carries_everything_the_relevance_sweep_needs(tmp_path, fuentes, catalogo_falso):
    """`relevancia_hacia_uiti_minimo` necesita los encoders y los maximos imputados
    ademas de los knobs: sin ellos un control categorico no se puede expandir y el
    barrido lo salta EN SILENCIO, dejandolo fuera del ranking sin decir por que."""
    datos, variables = fuentes

    catalogo = mil_inferencia.catalogo_de_controles(
        datos, variables, cache_path=tmp_path / "knobs.joblib")

    assert {"knobs", "grupos", "label_encoders", "max_values_imputed"} <= set(vars(catalogo))
