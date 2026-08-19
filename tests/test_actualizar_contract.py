"""El contrato de `/actualizar`: lo que el Markdown no puede perder en la proxima edicion.

Un comando es prosa, y la prosa no tiene quien le pregunte si sigue siendo cierta. Este
repositorio ya lo pago dos veces: la etapa 4c de `/subir-a-databricks` mandaba subir
tres archivos que se habian ido con el comando que los contenia, y su inventario
nombraba un `graphs/*.npy` que no existe en todo `data/`.

Lo que se fija aqui:

1. **Mide antes de reentrenar.** Reentrenar cuesta entre 8 y 14 minutos de CPU. Un
   comando que empieza por ahi los gasta el dia que solo se movio una celda de un
   `.xlsx` que ni siquiera entra al modelo.
2. **No tiene una segunda copia de la lista de fuentes ni del plan.** Los declara
   `scripts/estado_actualizacion.py`, que es tambien quien los compara. Una copia en un
   `.md` es la que nadie actualiza.
3. **Termina entregando a `/subir-a-databricks`** y no habla con el workspace por su
   cuenta: hay un solo comando que lo hace.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
COMANDO = RAIZ / ".claude" / "commands" / "actualizar.md"

sys.path.insert(0, str(RAIZ / "scripts"))
import estado_actualizacion as est  # noqa: E402

TEXTO = COMANDO.read_text(encoding="utf-8") if COMANDO.exists() else ""


def test_el_comando_existe_con_su_descripcion():
    assert TEXTO.startswith("---\ndescription:"), (
        "sin frontmatter el comando no aparece en la lista de skills")


def test_mide_antes_de_tocar_nada():
    assert "scripts/estado_actualizacion.py" in TEXTO
    posicion = TEXTO.index("scripts/estado_actualizacion.py")
    assert posicion < len(TEXTO) // 2, (
        "el diagnostico tiene que estar en la primera mitad del comando: es lo que "
        "decide si hay que reentrenar o si no hay nada que hacer")


def test_no_copia_la_lista_de_fuentes():
    presentes = [f.ruta for f in est.FUENTES if f.ruta in TEXTO]
    assert len(presentes) < len(est.FUENTES), (
        "el comando enumera las cuatro fuentes: esa lista vive en "
        "`scripts/estado_actualizacion.py`, que es quien las compara. Dos copias, y la "
        f"que se desactualiza es siempre la del Markdown. Copiadas: {presentes}")


def test_dice_de_donde_sale_la_lista_y_el_plan():
    assert re.search(r"FUENTES|estado_actualizacion\.py.*declara|declara.*FUENTES",
                     TEXTO, re.IGNORECASE | re.DOTALL), (
        "sin decir donde viven la lista y el plan, la proxima edicion los copia aqui")


def test_los_pasos_se_leen_del_plan_y_no_se_reescriben():
    assert "plan" in TEXTO, "el comando tiene que ejecutar lo que devuelve `plan[]`"
    prohibidas = ("scripts/exportar_geometria.py", "gestor.py iniciar --reconstruir")
    copiadas = [orden for orden in prohibidas if orden in TEXTO]
    assert not copiadas, (
        "esas ordenes son el campo `orden` de un paso de `PASOS`; escribirlas tambien "
        f"aqui crea dos versiones del mismo paso: {copiadas}")


@pytest.mark.parametrize("veredicto", [est.REENTRENAR, est.SOLO_PANEL, est.SIN_SELLAR,
                                       est.AL_DIA])
def test_los_cuatro_veredictos_estan_contemplados(veredicto):
    assert veredicto in TEXTO, (
        f"el comando no dice que hacer con el veredicto `{veredicto}`")


def test_avisa_del_costo_antes_de_reentrenar():
    assert re.search(r"8\s*(a|-|y)\s*14\s*minutos", TEXTO), (
        "reentrenar cuesta entre 8 y 14 minutos de CPU; el numero va antes de empezar")
    assert "CPU" in TEXTO, (
        "el reentrenamiento va en CPU a proposito: medido, le gana a MPS por 6x y usa "
        "3,4x menos memoria")


def test_explica_por_que_el_grafo_no_se_ve_hasta_reentrenar():
    assert "graph.py" in TEXTO
    assert re.search(r"\.pt|adyacencia", TEXTO), (
        "la adyacencia se congela DENTRO del `.pt`: sin decirlo, editar el grafo parece "
        "que ya tuvo efecto porque las cinco aplicaciones se reconstruyen igual")


def test_distingue_lo_que_reentrena_de_lo_que_solo_cambia_el_panel():
    assert "Variables_simular.xlsx" in TEXTO
    assert re.search(r"no\s+(hay que\s+)?reentrena", TEXTO, re.IGNORECASE), (
        "editar el catalogo de simulacion no reentrena nada; sin decirlo, el comando "
        "gasta 14 minutos por una celda")


def test_nombra_el_control_que_le_toca_a_cada_variable():
    for control in ("deslizador", "selector"):
        assert control in TEXTO, (
            f"sin nombrar `{control}`, no se entiende que revisa el paso `catalogo`")


def test_sella_y_dice_por_que():
    assert "sellar" in TEXTO
    assert re.search(r"manifest\.sha256\.json|modelo congelado", TEXTO), (
        "reentrenar deja en rojo la guarda del modelo congelado hasta que se vuelve a "
        "escribir su sha; si el comando no lo dice, se descubre en la suite")


def test_pregunta_una_sola_vez_y_para():
    assert re.search(r"[Pp]ara\.?\s+Espera", TEXTO), (
        "reentrenar son 14 minutos: no se empieza por suposicion")


def test_entrega_a_databricks_y_no_habla_con_el_workspace():
    assert "/subir-a-databricks" in TEXTO
    assert "databricks fs " not in TEXTO and "databricks apps " not in TEXTO, (
        "hay un solo comando que habla con el workspace, y no es este")


def test_nombra_los_dos_sistemas():
    for sistema in ("macOS", "Windows"):
        assert sistema in TEXTO, f"falta {sistema}: la mitad de las maquinas son la otra"
