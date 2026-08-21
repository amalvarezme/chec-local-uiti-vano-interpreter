"""`scripts/diagnostico_local.py`: lo que le falta a esta maquina, y como se arregla.

Lo que se fija aqui no es el resultado --- depende de la maquina --- sino las cuatro
propiedades que lo hacen util y que se pierden en silencio:

1. **Corre con el Python del sistema.** Es lo primero que se ejecuta en una maquina
   recien clonada, antes de que exista ningun entorno. Un import de pandas aqui lo
   volveria inutil justo en el caso para el que existe.
2. **No tiene una segunda copia de ninguna lista.** El piso de Python, los puertos y
   los insumos ya los declara alguien; una copia se desactualiza y miente.
3. **Cada cosa que puede faltar dice como se arregla, en LOS DOS sistemas.** Dar el
   comando de macOS a quien esta en Windows es peor que no dar ninguno: se copia, no
   funciona, y el usuario concluye que el diagnostico esta mal.
4. **Los tres destinos son independientes.** Faltar la CLI de Databricks no puede
   hundir el veredicto de "abrir los tableros en local".
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
GUION = RAIZ / "scripts" / "diagnostico_local.py"

sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "aplicaciones" / "_comun"))
import diagnostico_local as diag  # noqa: E402
import entorno as _entorno  # noqa: E402
import menu as _menu  # noqa: E402


# ------------------------------------------------------- corre donde tiene que correr


def test_solo_usa_la_biblioteca_estandar():
    """Se comprueba ejecutandolo, no leyendo sus imports: lo que importa es que no
    arrastre nada por una cadena de tres saltos, que es como entro `torch` en un sitio
    donde nadie lo llamaba."""
    hecho = subprocess.run([sys.executable, "-S", "-c",
                            "import sys; sys.path.insert(0, %r); import diagnostico_local"
                            % str(RAIZ / "scripts")],
                           capture_output=True, text=True, timeout=120)
    assert hecho.returncode == 0, hecho.stderr[-2000:]


def test_el_informe_sale_y_el_codigo_dice_si_falta_algo():
    hecho = subprocess.run([sys.executable, str(GUION)], capture_output=True, text=True,
                           timeout=300)
    assert hecho.returncode in (0, 1), hecho.stderr[-2000:]
    assert "Diagnostico local" in hecho.stdout
    for destino in diag.METAS:
        assert destino in hecho.stdout, f"el informe no habla de {destino!r}"


def test_el_json_tiene_la_forma_que_el_comando_espera():
    hecho = subprocess.run([sys.executable, str(GUION), "--json"], capture_output=True,
                           text=True, timeout=300)
    datos = json.loads(hecho.stdout)
    assert set(datos) >= {"sistema", "raiz", "revisiones", "destinos"}
    assert set(datos["destinos"]) == set(diag.METAS)
    for destino in datos["destinos"].values():
        assert set(destino) == {"titulo", "listo", "falta", "avisos"}
    claves = {r["clave"] for r in datos["revisiones"]}
    for meta, exigidas in diag.METAS.items():
        assert set(exigidas) <= claves, f"{meta} exige claves que nadie revisa"


# ------------------------------------------------------- ninguna lista se copia


def test_el_piso_de_python_es_el_de_la_guarda_que_lo_aplica():
    """Y no un numero escrito aqui. La guarda es `entorno.verificar_python_actual`, con
    la tabla de ruedas medida detras en `tests/test_piso_de_python.py`."""
    assert diag.PISO_PYTHON is _entorno.PYTHON_MINIMO


def test_los_puertos_son_los_que_declara_el_menu():
    """Los puertos son del menu local y de nadie mas. Una segunda tabla aqui daria por
    libre un puerto que el menu no usa, y por ocupado uno que si."""
    assert set(diag.PUERTOS.values()) == {_menu.PUERTO_MENU, *_menu.PUERTOS.values()}


def test_los_insumos_son_los_mismos_que_exige_el_clon_limpio():
    """Las dos preguntas son la misma: que tiene que traer un clon. `test_clon_limpio`
    comprueba que viajen en git; esto comprueba que esten en el disco de aqui."""
    import test_clon_limpio

    assert test_clon_limpio.INSUMOS is diag.INSUMOS, (
        "hay dos listas de insumos; la que se desactualiza es siempre la copia")
    assert test_clon_limpio.SHAPEFILES is diag.SHAPEFILES


def test_las_aplicaciones_revisadas_son_las_que_hay():
    """Una carpeta nueva en `aplicaciones/` que nadie agregue aqui saldria como
    instalada sin estarlo."""
    en_disco = sorted(p.name for p in (RAIZ / "aplicaciones").glob("0*") if p.is_dir())
    assert sorted(diag.APPS) == en_disco


# ------------------------------------------------------- los dos sistemas


@pytest.mark.parametrize("hacer", diag.REVISIONES, ids=lambda f: f.__name__)
def test_cada_revision_devuelve_un_estado_conocido(hacer):
    revision = hacer()
    assert revision.estado in (diag.LISTO, diag.FALTA, diag.AVISO)
    assert revision.detalle, f"{revision.clave} no explica nada"


@pytest.mark.parametrize("clave", sorted(diag.ARREGLOS))
def test_cada_arreglo_cubre_los_dos_sistemas(clave: str):
    """La tabla se revisa entera DESDE macOS, y esa es la razon de que sea una tabla.

    Dentro de la rama que lo necesita, el consejo de Windows no se ejecuta nunca en la
    maquina donde esto se desarrolla: se escribiria una vez y se pudriria sin que nadie
    lo notara hasta el dia que hiciera falta. Suelto, se comprueba siempre.
    """
    arreglo = diag.ARREGLOS[clave]
    assert set(arreglo) == {"macos", "windows"}, (
        f"{clave} solo trae arreglo para {sorted(arreglo)}")
    assert all(v.strip() for v in arreglo.values()), f"{clave} trae un arreglo vacio"


def test_toda_revision_que_puede_faltar_toma_su_arreglo_de_la_tabla():
    """Se recorre el CODIGO: en esta maquina casi ninguna rama de `falta` se ejecuta,
    asi que esperar a que falle para ver si trae arreglo es no comprobarlo nunca."""
    import ast

    arbol = ast.parse(GUION.read_text(encoding="utf-8"))
    sin_arreglo = []
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                and nodo.func.id == "Revision"):
            continue
        if len(nodo.args) < 3:
            continue
        estado = nodo.args[2]
        if not (isinstance(estado, ast.Name) and estado.id == "FALTA"):
            continue
        tiene = len(nodo.args) >= 5 or any(k.arg == "arreglo" for k in nodo.keywords)
        if not tiene:
            sin_arreglo.append(f"linea {nodo.lineno}")
    assert not sin_arreglo, (
        f"estas revisiones dicen que falta algo y no dicen como arreglarlo: {sin_arreglo}")


@pytest.mark.parametrize("clave,marca_windows", [
    ("git_lfs", "winget"),
    ("databricks_cli", "winget"),
    ("python", "python.org"),
    ("entorno_raiz", "py -3"),
    ("entornos_apps", "instalar.bat"),
    ("puertos", "netsh"),
    ("red", "setx"),
    ("runtime_vc", "winget"),
    ("rutas_largas", "LongPathsEnabled"),
])
def test_el_arreglo_de_windows_no_es_el_de_macos(clave: str, marca_windows: str):
    """Nueve cosas que se instalan o se miran distinto. Copiar el `brew install`, el
    `export` o el `.command` a Windows es el error concreto que esto impide.

    Las dos ultimas son de Windows y de nadie mas -- el runtime de Visual C++ y
    `LongPathsEnabled` --, y aun asi pasan por aqui: en macOS su revision sale
    `listo` sin mirar nada, asi que su `arreglo` es justo el tipo de texto que se
    pudre sin que nadie lo note."""
    windows = diag.ARREGLOS[clave]["windows"]
    assert marca_windows in windows, f"{clave}: el arreglo de Windows no nombra {marca_windows!r}"
    for de_mac in ("brew ", "xcode-select", "export ", ".command", "lsof"):
        assert de_mac not in windows, f"{clave}: el arreglo de Windows trae {de_mac!r}"


# ------------------------------------------------------- D7, aprendida a golpes


def test_los_dos_flujos_de_un_comando_no_se_mezclan():
    """Restriccion D7 del contrato de despliegue, y este archivo la incumplio primero.

    La CLI de Databricks escribe avisos por `stderr` de forma intermitente. Con los dos
    flujos juntos, `json.loads` muere con `Expecting value: line 1 column 1` sobre una
    llamada sana --- y el diagnostico reportaba "no hay ningun perfil configurado" en
    una maquina con tres.
    """
    codigo, salida, error = diag._corre(
        [sys.executable, "-c",
         "import sys; print('{\"profiles\": []}'); print('aviso', file=sys.stderr)"])
    assert codigo == 0
    assert json.loads(salida) == {"profiles": []}, (
        "stdout llego contaminado con stderr: json.loads no puede leerlo")
    assert "aviso" in error


def test_un_ejecutable_que_no_existe_no_tumba_el_diagnostico():
    """El caso normal en una maquina recien instalada, no la excepcion."""
    codigo, salida, error = diag._corre(["no-existe-este-programa-3f9a"])
    assert codigo == 127
    assert salida == "" and error == ""


# ------------------------------------------------------- los tres destinos, aparte


def test_faltar_databricks_no_hunde_a_las_aplicaciones():
    """Decir "esta maquina no esta lista" a secas mandaria a instalar la CLI de
    Databricks a quien solo quiere abrir un tablero."""
    revisiones = [diag.Revision(clave, clave, diag.LISTO, "ok")
                  for claves in diag.METAS.values() for clave in claves]
    revisiones = list({r.clave: r for r in revisiones}.values())
    revisiones = [diag.Revision(r.clave, r.titulo, diag.FALTA, "no esta",
                                {"macos": "x", "windows": "x"})
                  if r.clave.startswith("databricks") else r
                  for r in revisiones]
    juicios = diag.veredictos(revisiones)
    assert juicios["aplicaciones"]["listo"] is True
    assert juicios["cuaderno"]["listo"] is True
    assert juicios["databricks"]["listo"] is False
    assert [f["clave"] for f in juicios["databricks"]["falta"]] == [
        "databricks_cli", "databricks_perfil"]


def test_un_aviso_no_tumba_un_destino():
    """Un puerto ocupado por el propio proyecto ya abierto es un aviso, no un muro."""
    revisiones = [diag.Revision(c, c, diag.LISTO, "ok")
                  for c in dict.fromkeys(sum((list(v) for v in diag.METAS.values()), []))]
    revisiones = [diag.Revision(r.clave, r.titulo, diag.AVISO, "ocupado")
                  if r.clave == "puertos" else r for r in revisiones]
    juicios = diag.veredictos(revisiones)
    assert juicios["aplicaciones"]["listo"] is True
    assert juicios["aplicaciones"]["avisos"][0]["clave"] == "puertos"
