"""Lo que cuesta ARRANCAR el flujo del informe, antes de calcular nada.

Una corrida de `/report` invoca el CLI unas diez veces. Seis de esas llamadas solo
escriben un JSON de pocos bytes -- `record-usage`, `record-duration`, `verify-usage`
--, y aun asi pagaban el arranque completo del paquete. Medido en esta maquina:

    import chec_impacto.models.criticality_assignment   1,49 s   2.585 modulos

`criticality_assignment` importa torch PEREZOSAMENTE y su propio docstring dice por
que: "this module is imported by notebook and reporting code paths that have no
reason to pay for torch". Esa intencion la anulaba el `__init__` del PAQUETE, que
importaba `mgcecdl`, `mgcecdl_graph` y `mgcecdl_graph_search` de entrada. Tocar
cualquier submodulo -- aunque no necesitara nada de eso -- ejecutaba el `__init__`
y con el, torch.

    con el `__init__` vacio (techo medido)             0,03 s     199 modulos

Estas pruebas fijan el contrato: importar la asignacion de clase no carga torch, y
las exportaciones del paquete siguen estando para quien si las pide.

Se miden en un SUBPROCESO a proposito. `sys.modules` es global al interprete, y la
suite ya tiene torch cargado por otras pruebas mucho antes de llegar aqui: dentro
del mismo proceso la comprobacion pasaria siempre, mida lo que mida.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SRC = str(RAIZ / "src")


def _en_subproceso(codigo: str) -> str:
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True, text=True, cwd=RAIZ,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": SRC, "HOME": str(Path.home())},
    )
    assert resultado.returncode == 0, resultado.stderr
    return resultado.stdout.strip()


def test_asignar_la_clase_de_criticidad_no_carga_torch():
    """La usa el informe, la usan los tableros y la usan los cuadernos, y ninguno de
    los tres entrena nada al importarla."""
    salida = _en_subproceso(
        "import sys; import chec_impacto.models.criticality_assignment; "
        "print('torch' in sys.modules)"
    )

    assert salida == "False", (
        "importar la asignacion de clase volvio a arrastrar torch: son 1,5 s en cada "
        "una de las diez llamadas al CLI de una corrida de /report"
    )


def test_el_paquete_de_modelos_no_se_trae_torch_por_existir():
    """Importar `chec_impacto.models` a secas no es pedir un modelo."""
    salida = _en_subproceso(
        "import sys; import chec_impacto.models; print('torch' in sys.modules)"
    )

    assert salida == "False"


def test_las_exportaciones_del_paquete_siguen_ahi():
    """El aplazamiento no puede cambiar la API: cuatro sitios del repo -- dos pruebas,
    el generador del cuaderno 05 y el propio cuaderno -- importan estos nombres DEL
    PAQUETE, no del submodulo."""
    salida = _en_subproceso(
        "from chec_impacto.models import MGCECDLRegressor, GraphEdgeIndex, "
        "construir_edge_index; print(MGCECDLRegressor.__name__, "
        "GraphEdgeIndex.__name__, construir_edge_index.__name__)"
    )

    assert salida == "MGCECDLRegressor GraphEdgeIndex construir_edge_index"


def test_pedir_un_nombre_que_no_existe_sigue_dando_AttributeError():
    """Un `__getattr__` de modulo que devuelve algo para cualquier nombre convierte un
    error de tecleo en un fallo mucho mas adentro."""
    salida = _en_subproceso(
        "import chec_impacto.models as m\n"
        "try:\n"
        "    m.NoExisteEsteNombre\n"
        "except AttributeError as e:\n"
        "    print('AttributeError')\n"
    )

    assert salida == "AttributeError"


def test_registrar_tokens_y_tiempos_no_arranca_el_modelo(tmp_path):
    """`record-usage` y `record-duration` escriben un JSON de pocos bytes.

    Son seis de las diez llamadas al CLI de una corrida, y pagaban el arranque entero
    del paquete para eso.
    """
    salida = _en_subproceso(
        "import sys\n"
        "from chec_local_interpreter import report_contract\n"
        "print('torch' in sys.modules)\n"
    )

    assert salida == "False", (
        "el contrato del informe volvio a arrastrar torch al importarse: lo pagan las "
        "seis llamadas que solo escriben un JSON"
    )


def test_construir_el_prompt_de_inferencia_no_carga_torch():
    """El CLI del rol `inference` renderiza un prompt y valida un JSON. Ninguna de las
    dos cosas necesita el modelo, y las dos lo pagaban.

    `construir_prompt_inferencia` vive en `circuit_analysis`, cuyo propio archivo se
    describe como "pure prompt-rendering only". Importarlo ejecutaba el `__init__` del
    paquete `interpretability`, que se traia `mgcecdl_graph` y con el torch: 1,47 s en
    cada una de las dos llamadas del rol.
    """
    salida = _en_subproceso(
        "import sys\n"
        "from chec_impacto.interpretability.circuit_analysis import "
        "construir_prompt_inferencia\n"
        "print('torch' in sys.modules)\n"
    )

    assert salida == "False"


def test_las_exportaciones_de_interpretabilidad_siguen_ahi():
    """El aplazamiento no puede cambiar la API del paquete."""
    salida = _en_subproceso(
        "from chec_impacto.interpretability import (grafo_reconstruido_por_grupo, "
        "agregar_borda, construir_modos_interpretabilidad)\n"
        "print(grafo_reconstruido_por_grupo.__name__, agregar_borda.__name__, "
        "construir_modos_interpretabilidad.__name__)\n"
    )

    assert salida == (
        "grafo_reconstruido_por_grupo agregar_borda construir_modos_interpretabilidad")
