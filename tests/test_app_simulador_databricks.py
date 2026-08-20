"""La fuente de `simulador-vano`, la segunda Databricks App del proyecto.

## Por que existe este archivo

`arranque.py`, su `app.yaml` y su `requirements.txt` vivian **dentro** del comando
`/app-simulador-vano.md`, como bloques de codigo en un Markdown. Al fundir los cuatro
comandos de Databricks en `/subir-a-databricks` (commit `1c0aa56`), la etapa 4c se
quedo con las lineas que los suben --

    databricks workspace import <base>/arranque.py --file <scratch>/arranque.py

-- y perdio lo que los escribia. Desde entonces esa etapa no se puede ejecutar: manda
subir tres archivos que no existen en ningun sitio del repositorio.

La leccion es la que ya dejo escrita `scripts/empacar_app_databricks.py`: codigo que
solo vive en un `.md` es codigo que ninguna herramienta ve. `criticidad_chec` se salvo
de esto porque se promovio a carpeta con pruebas; el simulador no.

## Lo que estas pruebas fijan

Que los tres archivos existan, que lo que `arranque.py` importa viaje o este declarado,
y que las DOS variables de entorno que lee esten puestas en `app.yaml`. Esa ultima es la
que faltaba en el original: el `app.yaml` solo fijaba `PAQUETE_06`, asi que `VOLUME_06`
caia a su defecto `/Volumes/workspace/default/...` -- el catalogo que en CHEC no existe
(contrato D1). La app arrancaba y no encontraba su paquete.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "aplicaciones" / "databricks" / "simulador"


def _empacador():
    spec = importlib.util.spec_from_file_location(
        "empacar_app_databricks_sim", RAIZ / "scripts" / "empacar_app_databricks.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# ------------------------------------------------------- los archivos existen


@pytest.mark.parametrize("nombre", ["arranque.py", "app.yaml", "requirements.txt"])
def test_la_fuente_de_la_app_vive_en_el_repositorio(nombre: str):
    """No en un bloque de codigo dentro de un comando, que es de donde se perdio."""
    assert (APP / nombre).is_file(), (
        f"falta {APP / nombre}: la etapa 4c de /subir-a-databricks manda subirlo y "
        "nada lo escribe")


# ------------------------------------------------------- las dos variables de entorno


def test_el_yaml_fija_todas_las_variables_que_arranque_lee():
    """El defecto de `VOLUME_06` apunta a `workspace.default`, que en CHEC no existe.

    Se leen del arbol de sintaxis las llamadas `os.environ.get(...)` de `arranque.py` y
    se exige que cada nombre aparezca en `app.yaml`. Dejar una fuera no rompe el
    arranque: lo desvia a un Volume de otro workspace, y el sintoma -- "la app no
    encuentra el paquete" -- no apunta hasta aqui.
    """
    arbol = ast.parse((APP / "arranque.py").read_text("utf-8"))
    leidas = set()
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "get"
                and isinstance(nodo.func.value, ast.Attribute)
                and nodo.func.value.attr == "environ"
                and nodo.args and isinstance(nodo.args[0], ast.Constant)):
            leidas.add(nodo.args[0].value)

    yaml = (APP / "app.yaml").read_text("utf-8")
    # `DATABRICKS_APP_PORT` lo pone la plataforma, no el `app.yaml`.
    puestas = set(re.findall(r"- name:\s*\"?([A-Z_0-9]+)\"?", yaml)) | {"DATABRICKS_APP_PORT"}
    faltan = sorted(leidas - puestas)
    assert not faltan, (
        f"`arranque.py` lee {faltan} y `app.yaml` no las fija: caen a su defecto, que "
        "apunta al Volume de otro workspace")


def test_el_yaml_arranca_por_arranque_y_no_por_voila_directo():
    """Voila tiene que ser hijo directo del proceso de la plataforma, y quien lo hace
    hijo directo es el `execvp` de `arranque.py`. Llamar a Voila desde el `command` se
    saltaria la bajada del paquete."""
    yaml = (APP / "app.yaml").read_text("utf-8")
    assert "arranque.py" in yaml, f"el `command` no pasa por arranque.py:\n{yaml}"


# ------------------------------------------------------- lo que importa, viaja


def test_lo_que_arranque_importa_viaja_o_esta_declarado():
    """Misma guarda que en `criticidad_chec`: un import que no viaja es un contenedor
    que no arranca, y solo se ve en Databricks con el despliegue ya hecho."""
    IMPORTA_COMO = {"databricks-sdk": "databricks", "scikit-learn": "sklearn",
                    "jupyter-server": "jupyter_server"}
    declaradas = set()
    for linea in (APP / "requirements.txt").read_text("utf-8").splitlines():
        paquete = re.split(r"[<>=#\s]", linea.strip())[0]
        if paquete and not linea.strip().startswith("#"):
            declaradas.add(IMPORTA_COMO.get(paquete, paquete.replace("-", "_")))

    faltan = []
    arbol = ast.parse((APP / "arranque.py").read_text("utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos = [a.name.split(".")[0] for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0:
            modulos = [(nodo.module or "").split(".")[0]]
        else:
            continue
        for modulo in modulos:
            if modulo in declaradas or modulo in sys.stdlib_module_names:
                continue
            faltan.append(f"arranque.py importa {modulo!r}")
    assert not faltan, "\n  ".join(faltan)


def test_anywidget_esta_declarado():
    """No es opcional y no es evidente: `plotly>=6` levanta `ImportError` en
    `go.FigureWidget` sin el, y el tablero entero es un `FigureWidget`. Recortar el
    `requirements.txt` mas alla de la auditoria de imports ya produjo un
    `ModuleNotFoundError` en produccion."""
    declaradas = (APP / "requirements.txt").read_text("utf-8")
    assert "anywidget" in declaradas


# ------------------------------------------------------- las dos decisiones de Voila


def _llamada_a_execvp() -> ast.Call:
    arbol = ast.parse((APP / "arranque.py").read_text("utf-8"))
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "execvp"):
            return nodo
    raise AssertionError("`arranque.py` no llama a os.execvp")


def test_voila_queda_como_hijo_directo():
    """`os.execvp` y no `subprocess.run`: las senales de la plataforma tienen que
    llegarle a Voila, y un lanzador que se queda vivo detras se las come.

    Se mira el ARBOL y no el texto. La primera version de esta prueba buscaba la cadena
    `"subprocess.run"` en el archivo y fallaba contra el comentario que explica por que
    NO se usa. Prohibir la palabra prohibe tambien explicarla.
    """
    assert _llamada_a_execvp().args[0].value == "voila"
    arbol = ast.parse((APP / "arranque.py").read_text("utf-8"))
    modulos = {a.name.split(".")[0] for n in ast.walk(arbol)
               if isinstance(n, ast.Import) for a in n.names}
    assert "subprocess" not in modulos, (
        "`arranque.py` importa subprocess: Voila tiene que ser hijo directo")


def test_no_se_pasa_base_url():
    """Databricks Apps hace proxy en la RAIZ. Un `base_url` ahi deja todos los assets
    en 404 -- y la pagina se ve en blanco, que parece un fallo del kernel.

    Se miran los ARGUMENTOS de la llamada, por lo mismo que arriba.
    """
    argumentos = _llamada_a_execvp().args[1]
    banderas = [e.value for e in argumentos.elts if isinstance(e, ast.Constant)]
    culpables = [b for b in banderas if "base_url" in str(b)]
    assert not culpables, f"se le pasa base_url a Voila: {culpables}"


# ------------------------------------------------------- el empaquetado


def test_preparar_la_fuente_del_simulador_sustituye_el_volumen(tmp_path):
    """Y es idempotente, como la del otro: cada pasada copia del repositorio y
    sustituye sobre esa copia limpia."""
    empacador = _empacador()
    empacador.preparar_fuente_simulador(tmp_path, volumen_paquete="/Volumes/x/y/chec/paquete_06")
    yaml = (tmp_path / "app.yaml").read_text("utf-8")
    assert "/Volumes/x/y/chec/paquete_06" in yaml
    for nombre in ("arranque.py", "requirements.txt"):
        assert (tmp_path / nombre).is_file()

    empacador.preparar_fuente_simulador(tmp_path, volumen_paquete="/Volumes/otro/z/chec/paquete_06")
    yaml = (tmp_path / "app.yaml").read_text("utf-8")
    assert "/Volumes/otro/z/chec/paquete_06" in yaml
    assert "/Volumes/x/y/chec/paquete_06" not in yaml


def test_una_sustitucion_que_no_encuentra_su_marca_aborta(tmp_path, monkeypatch):
    """Igual que en `criticidad_chec`: en silencio, la app arranca apuntando al Volume
    de otro workspace y el sintoma no apunta hasta aqui."""
    empacador = _empacador()
    monkeypatch.setattr(empacador, "MARCA_VOLUMEN_PAQUETE", "/Volumes/marca/que/no/esta")
    with pytest.raises(SystemExit, match="Volume"):
        empacador.preparar_fuente_simulador(tmp_path, volumen_paquete="/Volumes/x/y/z")


def test_la_fuente_del_simulador_falla_si_le_falta_un_archivo(tmp_path, monkeypatch):
    empacador = _empacador()
    monkeypatch.setattr(empacador, "ARCHIVOS_SIMULADOR",
                        (*empacador.ARCHIVOS_SIMULADOR, "no_existe.py"))
    with pytest.raises(SystemExit, match="Falta"):
        empacador.preparar_fuente_simulador(tmp_path, volumen_paquete="/Volumes/x/y/z")


# ------------------------------------------------------- el contrato del manifiesto


def test_arranque_lee_del_manifiesto_lo_que_preparar_escribe():
    """El unico contrato entre las dos mitades, y vivia solo en la prosa.

    `aplicaciones/06_simulador/preparar.py` escribe el `manifiesto.json` que viaja al
    Volume; `arranque.py` lo lee dentro del contenedor para saber que bajar y comprobar
    que llego entero. Son dos archivos que no se importan entre si y que nadie ejecuta
    junto, asi que un cambio de forma en el escritor no rompe nada aqui: rompe en
    Databricks, al arrancar la app, con un `KeyError` dentro de un contenedor.

    Se comparan las CLAVES: las que `arranque.py` pide y las que `preparar.py` pone.
    """
    lector = ast.parse((APP / "arranque.py").read_text("utf-8"))
    pedidas = {n.slice.value for n in ast.walk(lector)
               if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name)
               and n.value.id == "manifiesto" and isinstance(n.slice, ast.Constant)}
    assert pedidas, "la prueba no encontro ninguna lectura del manifiesto"

    escritor = (RAIZ / "aplicaciones" / "06_simulador" / "preparar.py").read_text("utf-8")
    arbol = ast.parse(escritor)
    puestas = set()
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1
                and isinstance(nodo.targets[0], ast.Name)
                and nodo.targets[0].id == "manifiesto"
                and isinstance(nodo.value, ast.Dict)):
            puestas = {k.value for k in nodo.value.keys if isinstance(k, ast.Constant)}
    assert puestas, "no se pudo leer el diccionario del manifiesto en preparar.py"

    faltan = sorted(pedidas - puestas)
    assert not faltan, (
        f"`arranque.py` pide {faltan} del manifiesto y `preparar.py` no las escribe: "
        "la app arrancaria con un KeyError dentro del contenedor")


def test_arranque_comprueba_el_tamanio_de_cada_pieza():
    """Una descarga cortada deja un archivo que EXISTE. Comprobar solo la existencia
    dejaria pasar un `X_inst.npy` a medias, y eso no falla al bajar: falla dentro del
    tablero, con un error que no apunta a la descarga."""
    fuente = (APP / "arranque.py").read_text("utf-8")
    assert 'meta["bytes"]' in fuente and "st_size" in fuente, (
        "arranque.py no compara el tamanio de lo que baja contra el manifiesto")


# --------------------------------------------- el catalogo que la app lee en cada arranque

def test_el_arranque_apunta_al_catalogo_de_simulacion_del_paquete():
    """`Variables_simular.xlsx` NO se congela dentro del paquete como los demas objetos.

    `preparar.py` lo copia como archivo suelto justo porque el tablero lo lee en CADA
    arranque -- asi editarlo se nota sin reconstruir nada --, y quien tiene que decirle
    donde esta es el lanzador, por la variable de entorno `RUTA_VARIABLES_SIMULAR`.

    Sin ponerla, `ruta_variables_simular()` devuelve la ruta RELATIVA
    `data/Variables_simular.xlsx`, que se resuelve contra el directorio de trabajo del
    proceso. En el contenedor de Databricks ahi no hay ningun `data/`, asi que
    `catalogo_simulacion()` levanta "el panel no sabe que ofrecer" apuntando a una ruta
    que en ese contenedor no significa nada. La aplicacion local lo pone
    (`06_simulador/app.py`); esta no lo ponia.
    """
    fuente = (RAIZ / "aplicaciones" / "databricks" / "simulador" / "arranque.py").read_text(
        encoding="utf-8")
    assert "RUTA_VARIABLES_SIMULAR" in fuente, (
        "el lanzador de Databricks no apunta al catalogo de simulacion: el panel "
        "arrancaria sin saber que variables ofrecer")
    arbol = ast.parse(fuente)
    asignaciones = [n for n in ast.walk(arbol)
                    if isinstance(n, ast.Subscript)
                    and isinstance(n.value, ast.Attribute)
                    and n.value.attr == "environ"]
    assert asignaciones, (
        "`RUTA_VARIABLES_SIMULAR` se nombra pero no se escribe en `os.environ`; "
        "`execvp` hereda el entorno del proceso, asi que ponerla ahi es lo que la hace "
        "llegar a Voila")


def test_el_catalogo_viaja_dentro_del_paquete_que_baja_la_app():
    """La ruta que declara el lanzador tiene que ser la del paquete, no la del Volume:
    `arranque.py` baja el paquete al disco local del contenedor precisamente porque el
    montaje FUSE de `/Volumes` no esta garantizado (contrato D2)."""
    fuente = (RAIZ / "aplicaciones" / "databricks" / "simulador" / "arranque.py").read_text(
        encoding="utf-8")
    linea = next((l for l in fuente.splitlines() if "RUTA_VARIABLES_SIMULAR" in l
                  and "environ" in l), "")
    assert "DESTINO" in linea, (
        "la ruta del catalogo tiene que colgar de DESTINO -- la copia local del paquete "
        f"--, no de VOLUMEN. Linea encontrada: {linea.strip()!r}")
