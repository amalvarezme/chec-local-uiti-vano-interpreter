"""Un tablero migrado se construye importando, no ejecutando celdas.

Es el objetivo entero de la fase 3 de `sdd/retire-base-apps-notebooks`, y hasta aqui
nada lo comprobaba: el golden dice que el HTML sale igual, pero saldria igual tambien
si `construccion.py` siguiera pasando por `exec()`. Estas pruebas miran el CAMINO, no
el resultado.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from ayudas_tableros import ESTATICOS, MIGRADOS, SIMULADOR

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "aplicaciones" / "_comun"))
sys.path.insert(0, str(RAIZ / "src"))


def _construccion():
    return importlib.import_module("construccion")


def test_cada_visor_declara_el_mismo_modulo_que_leen_las_pruebas():
    """`construir.py` decide con que se construye; `ayudas_tableros.py`, de donde leen
    las pruebas. Si una avanza sin la otra, el tablero se construye desde el modulo
    mientras decenas de pruebas siguen mirando otro sitio -- y pasan, porque no
    contradicen nada: simplemente dejan de decir algo.

    Ya no hay una tabla `_MIGRADOS` en `construccion.py`: cada aplicacion nombra su
    propio tablero, que es donde esa decision pertenece. Lo que se compara ahora es lo
    que declaran los cuatro `construir.py` contra lo que leen las pruebas.
    """
    import re

    declarados = set()
    for app in sorted((RAIZ / "aplicaciones").glob("0[1-4]_*")):
        texto = (app / "construir.py").read_text(encoding="utf-8")
        declarados |= set(re.findall(r'TABLERO = "chec_tableros\.(\w+)"', texto))

    assert declarados == set(ESTATICOS.values()), (
        f"las aplicaciones declaran {sorted(declarados)} y las pruebas leen "
        f"{sorted(ESTATICOS.values())}"
    )


@pytest.mark.parametrize("cuaderno, modulo", sorted(ESTATICOS.items()))
def test_el_modulo_del_tablero_existe_y_expone_construir(cuaderno, modulo):
    m = importlib.import_module(f"chec_tableros.{modulo}")
    assert callable(m.construir), f"{modulo} no expone construir()"


def test_el_simulador_expone_sus_dos_mitades():
    """El simulador tambien esta migrado, y su contrato es OTRO.

    Los cuatro estaticos reciben una raiz y devuelven la ruta de un HTML. El
    simulador es un tablero VIVO: `construir()` recibe el `Derivado` que produce
    `derivacion` y devuelve un widget, porque lo sirve Voila con un kernel detras.
    Meterlo en la misma parametrizacion obligaria a poner un `if` en cada prueba de
    este fichero, que es como una lista deja de decir lo que significa.
    """
    from inspect import signature

    derivacion = importlib.import_module("chec_tableros.simulador.derivacion")
    tablero = importlib.import_module("chec_tableros.simulador.tablero")

    assert callable(derivacion.derivar) and callable(derivacion.cargar)
    assert callable(tablero.construir)
    # El primer parametro es el `Derivado`, y es POSICIONAL: es lo que hace que los
    # dos caminos -- derivar y cargar -- sean intercambiables sin que el tablero
    # sepa cual corrio.
    primero = list(signature(tablero.construir).parameters)[0]
    assert primero == "derivado", f"construir() empieza por {primero!r}"


@pytest.mark.parametrize("cuaderno", sorted(ESTATICOS))
def test_el_cuaderno_del_tablero_migrado_ya_no_existe(cuaderno):
    """Migrar y no borrar deja dos fuentes, y la que se pudre es la que nadie ejecuta.

    El `.ipynb` se borro el 2026-08-15. Lo unico que tenia y que el modulo no podia
    heredar era su narrativa -- el `Como leerlo`, que no es codigo --, y esa vive
    ahora en el README de su aplicacion. El codigo esta en `src/chec_tableros/`.

    El cuaderno 06 NO entra aqui todavia: su codigo ya salio, pero borrarlo es la
    fase 4 de este mismo cambio. Mientras tanto nadie lo ejecuta -- ni `preparar.py`
    ni ninguna aplicacion lo nombra --, y `test_el_cuaderno_06_ya_no_es_insumo_de_su_
    aplicacion` es lo que fija que asi siga.
    """
    assert not (RAIZ / "notebooks" / "base_apps" / f"{cuaderno}.ipynb").exists(), (
        f"{cuaderno}.ipynb sigue ahi: el tablero vive en src/chec_tableros/ y dos "
        "fuentes se separan en silencio"
    )


APPS_DE_TABLERO = {
    "01_uiti_vano_clima": "01_clima",
    "02_uiti_vano_kmeans": "02_agrupamiento_vanos",
    "03_uiti_vano_trayectorias_circuitos": "03_trayectorias_circuitos",
    "04_uiti_vano_trayectorias_vano": "04_trayectorias_vanos",
    SIMULADOR: "06_simulador",
}


@pytest.mark.parametrize("cuaderno", sorted(MIGRADOS))
def test_la_narrativa_del_cuaderno_sobrevivio_en_el_readme_de_su_aplicacion(cuaderno):
    """Borrar el cuaderno no puede costar su documentacion.

    Eran 493 lineas repartidas en los cuatro estaticos, y 790 mas del simulador, que
    explican QUE se esta mirando: que significa un punto, por que los grupos de un
    tablero no son comparables con los de otro, de donde sale cada numero. Nada de
    eso cabe en el codigo, y es lo primero que busca quien abre la aplicacion.

    El simulador entra aqui aunque su cuaderno todavia exista: la narrativa se movio
    en la misma rebanada que el codigo, para que borrarlo despues sea un `unlink` y
    no una decision.
    """
    readme = (RAIZ / "aplicaciones" / APPS_DE_TABLERO[cuaderno] / "README.md").read_text(
        encoding="utf-8")
    assert "Cómo leer este tablero" in readme, (
        f"{APPS_DE_TABLERO[cuaderno]} perdio su narrativa")
    if cuaderno != SIMULADOR:
        assert "Como leerlo" in readme or "Cómo leerlo" in readme


@pytest.mark.parametrize("modulo", sorted(ESTATICOS.values()))
def test_construir_un_tablero_migrado_no_ejecuta_celdas(modulo, monkeypatch, tmp_path):
    """Se rompe `cuaderno.ejecutar` a proposito.

    Sin esto la prueba seria una promesa: bastaria con que el HTML saliera bien, y
    saldria bien por cualquiera de los dos caminos. Lo que se comprueba es el CAMINO.
    """
    construccion = _construccion()
    modulo_cuaderno = importlib.import_module("cuaderno")

    def _prohibido(*_a, **_k):
        raise AssertionError(f"{modulo} se construyo ejecutando celdas")

    monkeypatch.setattr(modulo_cuaderno, "ejecutar", _prohibido)
    monkeypatch.setattr(
        construccion, "_construir_con_modulo",
        lambda _m: _fingir_html(tmp_path))
    monkeypatch.setattr(construccion._empaquetar, "empaquetar", lambda *a, **k: _Vacio())

    construccion.construir_tablero(f"chec_tableros.{modulo}", tmp_path / "panel",
                                   titulo="x")


def _fingir_html(tmp_path: Path) -> Path:
    ruta = tmp_path / "panel.html"
    ruta.write_text("<html></html>", encoding="utf-8")
    return ruta


class _Vacio:
    """Sustituto del paquete: la prueba mira el camino, no el empaquetado."""

    piezas: list = []
    total_gzip = 1

    def resumen(self) -> str:
        return ""
