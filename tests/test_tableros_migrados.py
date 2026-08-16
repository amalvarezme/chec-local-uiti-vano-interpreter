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

from ayudas_tableros import MIGRADOS

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "aplicaciones" / "_comun"))
sys.path.insert(0, str(RAIZ / "src"))


def _construccion():
    return importlib.import_module("construccion")


def test_las_dos_tablas_de_migrados_no_se_separan():
    """`construccion.py` decide como construir; `ayudas_tableros.py` decide de donde
    leen las pruebas. Si una avanza sin la otra, el tablero se construye desde el
    modulo mientras decenas de pruebas siguen mirando el cuaderno vacio -- y pasan,
    porque un cuaderno adelgazado no contradice nada, simplemente ya no dice nada.
    """
    del_codigo = {n[:-6] for n in _construccion()._MIGRADOS}
    assert del_codigo == set(MIGRADOS), (
        f"construccion.py migro {sorted(del_codigo)} y las pruebas leen "
        f"{sorted(MIGRADOS)}"
    )


@pytest.mark.parametrize("cuaderno, modulo", sorted(MIGRADOS.items()))
def test_el_modulo_del_tablero_existe_y_expone_construir(cuaderno, modulo):
    m = importlib.import_module(f"chec_tableros.{modulo}")
    assert callable(m.construir), f"{modulo} no expone construir()"


@pytest.mark.parametrize("cuaderno", sorted(MIGRADOS))
def test_el_cuaderno_migrado_ya_no_lleva_el_tablero_dentro(cuaderno):
    """El cuaderno se queda como envoltorio delgado hasta que la rebanada S11 lo borre.

    Que siga existiendo no es olvido: conserva su narrativa (`Como leerlo`) y sirve de
    puerta de entrada. Lo que no puede es conservar tambien el codigo, porque entonces
    hay dos implementaciones y la que se rompe en silencio es la que nadie ejecuta.
    """
    doc = json.loads(
        (RAIZ / "notebooks" / "base_apps" / f"{cuaderno}.ipynb").read_text(encoding="utf-8"))
    codigo = "\n".join("".join(c["source"]) for c in doc["cells"]
                       if c["cell_type"] == "code")
    lineas = [l for l in codigo.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    assert len(lineas) < 40, (
        f"{cuaderno} conserva {len(lineas)} lineas de codigo: el tablero deberia vivir "
        "solo en src/chec_tableros/"
    )
    assert "chec_tableros" in codigo, f"{cuaderno} no llama a su modulo"


@pytest.mark.parametrize("cuaderno", sorted(MIGRADOS))
def test_construir_un_tablero_migrado_no_ejecuta_celdas(cuaderno, monkeypatch, tmp_path):
    """Se rompe `cuaderno.ejecutar` a proposito.

    Sin esto la prueba seria una promesa: `construccion.py` podria seguir ejecutando
    las celdas y el HTML saldria igual de bien, porque el cuaderno delgado tambien
    llama al modulo.
    """
    construccion = _construccion()
    modulo_cuaderno = importlib.import_module("cuaderno")

    def _prohibido(*_a, **_k):
        raise AssertionError(f"{cuaderno} se construyo ejecutando celdas")

    monkeypatch.setattr(modulo_cuaderno, "ejecutar", _prohibido)
    monkeypatch.setattr(
        construccion, "_construir_con_modulo",
        lambda _m: _fingir_html(tmp_path))
    monkeypatch.setattr(construccion._empaquetar, "empaquetar", lambda *a, **k: _Vacio())

    construccion.construir_tablero(f"{cuaderno}.ipynb", tmp_path / "panel", titulo="x")


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
