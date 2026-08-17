"""SHAP quedo fuera del proyecto, y esta prueba es lo que impide que vuelva.

El analisis de sensibilidad ya no se explica con Kernel SHAP. Lo sustituyo
`relevancia_hacia_uiti_minimo` (rejilla sobre el rango observado, CON signo, y
mirando el interior y no solo los dos extremos) y su continuacion
`plan_hacia_clase_minima`, que buscan el camino de cada vano hacia el grupo mas
bajo moviendo SOLO variables de intervencion. Es otra pregunta y otro metodo:
SHAP atribuye lo que el modelo ya hizo, y estas dos exploran que se puede hacer.

Por que hace falta una prueba y no basta con haber borrado el codigo: SHAP no
entraba al informe porque alguien lo invocara -- no lo invocaba nadie --, sino
por UNA linea de import a tres saltos de distancia:

    mil_inferencia -> mil_persistencia -> mil_vano_ventana -> circuit_analysis

y esa cadena existia para traer `agregar_borda`, veinte lineas de pandas que no
tienen nada que ver con SHAP. Un import asi no se ve en ninguna revision de
codigo: no aparece en el diff que lo activa, no rompe ninguna prueba y solo se
manifiesta como 1,87 s de arranque que nadie atribuye a su causa. Por eso el
invariante se vigila sobre `sys.modules` DESPUES de cargar el modelo de verdad,
que es el unico sitio donde la reaparicion seria visible.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SRC = RAIZ / "src"

# Las carpetas que se vigilan. `tests/golden/` queda fuera a proposito: sus
# archivos son la fotografia de un contrato retirado y describen lo que el
# proyecto HACIA, no lo que hace.
ARBOLES_VIGILADOS = (SRC, RAIZ / "scripts")


def _fuentes_python() -> list[Path]:
    archivos: list[Path] = []
    for arbol in ARBOLES_VIGILADOS:
        if arbol.is_dir():
            archivos.extend(
                ruta for ruta in sorted(arbol.rglob("*.py"))
                if "__pycache__" not in ruta.parts
            )
    assert archivos, "no se encontro ni un archivo que vigilar: revisa ARBOLES_VIGILADOS"
    return archivos


def test_ninguna_fuente_importa_shap():
    """Ni un `import shap` en `src/` ni en `scripts/`.

    Se busca el import y no la palabra suelta para no chocar con `shape`,
    `reshape`, `shapely` ni los shapefiles, que son cuatro cosas legitimas y
    frecuentes en este repo.
    """
    culpables = []
    for ruta in _fuentes_python():
        for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            despojada = linea.strip()
            if despojada.startswith(("import shap", "from shap")) and not despojada.startswith(
                ("import shapely", "from shapely")
            ):
                culpables.append(f"{ruta.relative_to(RAIZ)}:{numero}: {despojada}")

    assert not culpables, (
        "SHAP volvio a entrar al codigo:\n  " + "\n  ".join(culpables)
        + "\n\nEl analisis de sensibilidad es `relevancia_hacia_uiti_minimo` y "
        "`plan_hacia_clase_minima` (mil_simulador_015.py)."
    )


def test_ninguna_fuente_genera_codigo_que_importe_shap():
    """El generador del cuaderno 05 tampoco puede EMITIR un `import shap`.

    `scripts/generate_notebook_10.py` escribe el cuaderno como cadenas de texto,
    asi que su propio `import shap` viviria dentro de un literal y la prueba de
    arriba no lo veria: el archivo que importa SHAP seria el .ipynb generado, que
    no es una fuente de Python. Aqui se mira el contenido completo.
    """
    culpables = []
    for ruta in _fuentes_python():
        texto = ruta.read_text(encoding="utf-8")
        for numero, linea in enumerate(texto.splitlines(), 1):
            despojada = linea.strip()
            if "shap" not in despojada.lower():
                continue
            # Solo se persigue el import emitido; la prosa que EXPLICA por que se
            # retiro SHAP tiene que poder nombrarlo.
            if despojada.startswith(("import shap", "from shap")) and not despojada.startswith(
                ("import shapely", "from shapely")
            ):
                culpables.append(f"{ruta.relative_to(RAIZ)}:{numero}: {despojada}")

    assert not culpables, (
        "el codigo GENERADO importa SHAP:\n  " + "\n  ".join(culpables)
    )


def test_requirements_no_declara_shap():
    requisitos = (RAIZ / "requirements.txt").read_text(encoding="utf-8")
    declaradas = [
        linea.strip() for linea in requisitos.splitlines()
        if linea.strip() and not linea.strip().startswith("#")
    ]
    assert not [d for d in declaradas if d.split("=")[0].split(">")[0].split("<")[0].strip() == "shap"], (
        "`shap` sigue declarado en requirements.txt"
    )


# El guion corre en un interprete propio a proposito: `sys.modules` del proceso de
# pytest ya esta contaminado por cualquier otra prueba que haya importado lo que
# sea, asi que preguntarle ahi no probaria nada.
_GUION_CARGA_EL_MODELO = """
import json
import sys

sys.path.insert(0, {src!r})

# La cadena real del informe: `prepare` resuelve el modelo por aqui.
from chec_impacto.models.mil_persistencia import cargar_modelo_mil  # noqa: F401
from chec_local_interpreter import mil_inferencia  # noqa: F401
from chec_local_interpreter import report_pipeline  # noqa: F401

print(json.dumps({{"shap": "shap" in sys.modules}}))
"""


def test_cargar_el_modelo_del_informe_no_arrastra_shap(tmp_path):
    """El invariante de verdad: la cadena de `prepare` no puede cargar SHAP.

    Las tres pruebas de arriba miran el texto de los archivos; esta mira lo que
    de verdad queda en memoria, que es lo unico que cuesta segundos y megas.
    """
    guion = tmp_path / "sonda.py"
    guion.write_text(_GUION_CARGA_EL_MODELO.format(src=str(SRC)), encoding="utf-8")

    completado = subprocess.run(
        [sys.executable, str(guion)],
        capture_output=True,
        text=True,
        cwd=str(RAIZ),
        timeout=300,
    )
    if completado.returncode != 0:
        pytest.fail(
            "la sonda no pudo cargar la cadena del informe:\n"
            f"{completado.stdout}\n{completado.stderr}"
        )

    veredicto = json.loads(completado.stdout.strip().splitlines()[-1])
    assert veredicto["shap"] is False, (
        "cargar el modelo del informe metio `shap` en sys.modules. Sigue la "
        "cadena de imports desde `chec_impacto.models.mil_persistencia`: casi "
        "seguro alguien volvio a colgar una funcion util de un modulo que "
        "importa SHAP en su cabecera."
    )
