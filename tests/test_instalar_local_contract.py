"""El contrato de `/instalar-local`: lo que el Markdown no puede perder en la proxima edicion.

Un comando es prosa, y la prosa no tiene quien le pregunte si sigue siendo cierta. Este
repositorio ya pago dos veces por eso: la etapa 4c mandaba subir tres archivos que se
habian ido con el comando que los contenia, y el inventario de la etapa 3 nombraba un
`graphs/*.npy` que no existe. Lo que se fija aqui es lo que volveria a costar lo mismo.

Tres propiedades:

1. **Diagnostica antes de instalar.** Un comando que instala a ciegas reinstala 4 GB de
   entornos que ya estaban.
2. **No tiene una segunda copia de ninguna lista.** Ni los puertos, ni el piso de
   Python, ni los nombres de los insumos: los declara `scripts/diagnostico_local.py` y
   quienes ya los tenian. Una copia en un `.md` es la que nadie actualiza.
3. **Nombra los dos sistemas en cada paso que cambia entre ellos**, y le deja al usuario
   lo que necesita a una persona delante.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
COMANDO = RAIZ / ".claude" / "commands" / "instalar-local.md"
GUION = RAIZ / "scripts" / "diagnostico_local.py"

sys.path.insert(0, str(RAIZ / "scripts"))
import diagnostico_local as diag  # noqa: E402

TEXTO = COMANDO.read_text(encoding="utf-8")


def test_el_comando_existe_con_su_descripcion():
    assert TEXTO.startswith("---\ndescription:"), (
        "sin frontmatter el comando no aparece en la lista de skills")


def test_diagnostica_antes_de_instalar():
    """El paso 0 corre el diagnostico, y esta antes que cualquier instalacion."""
    assert "scripts/diagnostico_local.py --json" in TEXTO
    primera_instalacion = min(
        TEXTO.index(m) for m in ("git lfs pull", "pip install -r requirements.txt"))
    assert TEXTO.index("diagnostico_local.py") < primera_instalacion, (
        "el comando instala antes de mirar que falta")


def test_vuelve_a_diagnosticar_al_final():
    """Que un paso no diera error no es que el destino quedara listo, y son dos
    afirmaciones distintas -- la misma leccion que la etapa 5 de /subir-a-databricks."""
    ultimo = TEXTO.rindex("diagnostico_local.py")
    assert ultimo > TEXTO.index("## 7."), "el comando no vuelve a comprobar al final"


def test_pregunta_una_sola_vez_y_para():
    """La regla de este repositorio es una pregunta y esperar. Y aqui pesa: los pasos de
    abajo bajan gigabytes."""
    assert re.search(r"\bpara\.\s|\bPara\.\s|\*\*para\.", TEXTO, re.I), (
        "el comando no dice explicitamente que se detenga a esperar la respuesta")
    assert TEXTO.count("## ") >= 7


# ------------------------------------------------------- ninguna lista copiada


@pytest.mark.parametrize("patron,que", [
    (r"\b88\d\d\b", "un numero de puerto"),
    (r"\b3\.1[0-9]\b", "una version concreta de Python"),
    (r"Indicadores_vano_v3|bolsas_mil_full|Variables_seleccion|geometria_kmeans", "un nombre de insumo"),
])
def test_el_comando_no_copia_ninguna_lista(patron: str, que: str):
    """Lo que se copia se desactualiza. Los puertos los declara `menu.py`, el piso lo
    declara `entorno.py`, y los insumos el propio diagnostico -- que es de donde los
    lee tambien `tests/test_clon_limpio.py`."""
    encontrados = re.findall(patron, TEXTO)
    assert not encontrados, (
        f"el comando escribe {que} ({encontrados[:3]}) en vez de leerlo del diagnostico")


def test_el_comando_dice_de_donde_salen_las_listas():
    """Y no como un detalle de estilo: es la instruccion que impide que la proxima
    edicion las copie."""
    for fuente in ("entorno.py", "menu.py", "test_clon_limpio.py"):
        assert fuente in TEXTO, f"el comando no dice que {fuente} es una de las fuentes"


# ------------------------------------------------------- macOS y Windows, los dos


@pytest.mark.parametrize("mac,windows", [
    ("brew install git-lfs", "winget install GitHub.GitLFS"),
    ("brew tap databricks/tap", "winget install Databricks.DatabricksCLI"),
    ("instalar-en-terminal.command", "instalar.bat"),
    ("Iniciar.app", "iniciar.bat"),
    (".venv/bin/pip", r".venv\Scripts\pip"),
    ("python3 -m venv", "py -3 -m venv"),
])
def test_cada_paso_que_cambia_trae_las_dos_formas(mac: str, windows: str):
    """Dar solo la de macOS es el error concreto: se copia, no funciona, y quien lo lee
    concluye que el comando esta mal."""
    assert mac in TEXTO, f"falta la forma de macOS: {mac!r}"
    assert windows in TEXTO, f"falta la forma de Windows: {windows!r}"


def test_los_comandos_de_windows_del_diagnostico_aparecen_en_el_comando():
    """Las dos mitades tienen que decir lo mismo. El diagnostico da el `arreglo`
    resuelto; el comando lo ejecuta. Si divergen, el usuario ve dos consejos."""
    for clave in ("git_lfs", "databricks_cli"):
        herramienta = diag.ARREGLOS[clave]["windows"].split(" && ")[0]
        assert herramienta in TEXTO, (
            f"el diagnostico manda `{herramienta}` para {clave} y el comando no lo dice")


# ------------------------------------------------------- lo que necesita a una persona


@pytest.mark.parametrize("asunto", ["Python", "auth login", "BLOQUEADO"])
def test_lo_que_no_puede_hacer_el_agente_esta_nombrado(asunto: str):
    """Tres cosas piden permisos de administrador, un navegador o a quien administra la
    maquina. Intentarlas y fallar es peor que decir quien las hace."""
    bloque = TEXTO[TEXTO.index("## 2."):TEXTO.index("## 3.")]
    assert asunto in bloque, f"el comando no dice que {asunto!r} lo hace otra persona"


def test_el_prefijo_de_shell_interactivo_se_explica():
    """En esta sesion, lo interactivo lo corre el usuario con `!`. Sin decirlo, el
    agente intenta el `auth login` y se queda esperando un navegador que no ve."""
    assert "prefijo `!`" in TEXTO


def test_distingue_puerto_bloqueado_de_puerto_ocupado():
    """Son distintos y se arreglan distinto: ocupado es que hay algo escuchando;
    bloqueado es que el sistema no deja atarse, y ahi la aplicacion arranca en un
    puerto al azar, viva e invisible para el menu."""
    assert "no es un puerto\nocupado" in TEXTO or "no es un puerto ocupado" in TEXTO


def test_avisa_del_peso_antes_de_bajarlo():
    """~900 MB de LFS y ~1,9 GB de entorno raiz. Empezar sin decirlo deja al usuario
    mirando una barra que no sabe cuanto dura."""
    assert "900 MB" in TEXTO, "no avisa del peso de `git lfs pull`"
    assert "1,9 GB" in TEXTO, "no avisa del peso del entorno raiz"


def test_no_habla_con_databricks():
    """Instalar la CLI y abrir sesion no es desplegar. El unico que habla con el
    workspace es `/subir-a-databricks`, y mezclarlos daria dos comandos que suben."""
    for prohibido in ("databricks fs cp", "databricks apps deploy", "databricks sync",
                      "databricks workspace import"):
        assert prohibido not in TEXTO, (
            f"el comando ejecuta `{prohibido}`; subir es de /subir-a-databricks")
