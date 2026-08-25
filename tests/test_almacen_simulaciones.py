"""RED/GREEN tests for `almacen_simulaciones`: DONDE quedan las simulaciones.

El tablero del simulador corre en dos sitios que no comparten un solo supuesto
sobre el disco:

- **En la maquina del usuario**, servido por Voila. Hay disco de verdad, el
  archivo se puede abrir con doble clic, y el HTML se puede lanzar al navegador.
- **En Databricks Apps**, servido por el mismo Voila dentro de un contenedor
  efimero. Lo que se escriba en su disco desaparece con el proximo despliegue, y
  el usuario no tiene forma de alcanzarlo: la unica superficie que sobrevive y
  que el usuario ve es el Volume de Unity Catalog, y el Volume **no esta montado**
  (contrato D2) -- se llega por la Files API.

Este modulo es la unica pieza que sabe esa diferencia. El tablero pide "guarda
esto" y "damelo de vuelta", y no aprende nunca cual de los dos mundos le toco.

La eleccion NO se adivina mirando el entorno con heuristicas: la hace una
variable que `/subir-a-databricks` escribe en el `app.yaml` de la app. Adivinar
-- por ejemplo, "si existe /Volumes entonces es Databricks" -- es lo que produce
un tablero local que intenta escribir en un Volume que no existe.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chec_local_interpreter.almacen_simulaciones import (
    ENTORNO_LOCAL,
    ENTORNO_VOLUMEN,
    AlmacenLocal,
    AlmacenVolumen,
    almacen_por_defecto,
)


DATOS = b"\x1f\x8bfake-gzip"
INFORME = "<!doctype html><html><body>hola</body></html>"
NOMBRE = "DON23L14_V10_2026-08-25T10-00-00.simchec.json.gz"


# ------------------------------------------------------------------ almacen local


def test_el_almacen_local_crea_su_carpeta_al_guardar(tmp_path):
    """La carpeta puede no existir todavia -- es la primera vez que alguien guarda --
    y crearla es parte de guardar, no un paso previo que alguien tenga que recordar."""
    almacen = AlmacenLocal(tmp_path / "simulaciones")
    almacen.guardar(NOMBRE, datos=DATOS, informe=INFORME)
    assert (tmp_path / "simulaciones").is_dir()


def test_el_almacen_local_escribe_el_registro_y_el_informe_juntos(tmp_path):
    """Los dos archivos comparten nombre base a proposito: es lo que permite que quien
    abra la carpeta dentro de un anio vea el informe y su registro como una pareja."""
    almacen = AlmacenLocal(tmp_path)
    destino = almacen.guardar(NOMBRE, datos=DATOS, informe=INFORME)
    assert (tmp_path / NOMBRE).read_bytes() == DATOS
    assert (tmp_path / NOMBRE.replace(".simchec.json.gz", ".html")).read_text("utf-8") == INFORME
    assert destino["registro"].endswith(NOMBRE)
    assert destino["informe"].endswith(".html")


def test_el_informe_se_escribe_en_utf8(tmp_path):
    """Los nombres del contrato llevan tilde. Escrito con la codificacion por defecto
    del sistema, el informe sale roto en Windows -- y solo en Windows."""
    almacen = AlmacenLocal(tmp_path)
    almacen.guardar(NOMBRE, datos=DATOS, informe="<p>Poda en árboles</p>")
    crudo = (tmp_path / NOMBRE.replace(".simchec.json.gz", ".html")).read_bytes()
    assert "árboles".encode("utf-8") in crudo


def test_el_almacen_local_lista_lo_guardado_de_lo_mas_nuevo_a_lo_mas_viejo(tmp_path):
    almacen = AlmacenLocal(tmp_path)
    almacen.guardar("A_V1_2026-01-01T00-00-00.simchec.json.gz", datos=DATOS, informe="")
    almacen.guardar("B_V2_2026-02-01T00-00-00.simchec.json.gz", datos=DATOS, informe="")
    claves = [e["clave"] for e in almacen.listar()]
    assert claves == ["B_V2_2026-02-01T00-00-00.simchec.json.gz",
                      "A_V1_2026-01-01T00-00-00.simchec.json.gz"]


def test_el_almacen_local_no_lista_los_informes_ni_lo_ajeno(tmp_path):
    """La carpeta acaba teniendo el doble de archivos que simulaciones, y ademas lo
    que el usuario deje ahi. Ofrecer un `.html` como algo que se puede cargar es
    prometer algo que va a fallar al abrirlo."""
    almacen = AlmacenLocal(tmp_path)
    almacen.guardar(NOMBRE, datos=DATOS, informe=INFORME)
    (tmp_path / "notas.txt").write_text("nada")
    assert [e["clave"] for e in almacen.listar()] == [NOMBRE]


def test_el_almacen_local_devuelve_los_bytes_que_guardo(tmp_path):
    almacen = AlmacenLocal(tmp_path)
    almacen.guardar(NOMBRE, datos=DATOS, informe=INFORME)
    assert almacen.leer(NOMBRE) == DATOS


def test_listar_una_carpeta_que_no_existe_devuelve_vacio_y_no_revienta(tmp_path):
    """La primera apertura del tablero, antes de guardar nada. Un panel que arranca
    con una excepcion en vez de con una lista vacia se lee como que el tablero se
    rompio."""
    assert AlmacenLocal(tmp_path / "todavia-no").listar() == []


def test_el_almacen_local_rechaza_una_clave_que_se_sale_de_su_carpeta(tmp_path):
    """La clave viaja desde un desplegable de la interfaz. No puede convertirse en
    una ruta a cualquier sitio del disco."""
    almacen = AlmacenLocal(tmp_path)
    with pytest.raises(ValueError):
        almacen.leer("../../etc/passwd")


def test_el_almacen_local_dice_donde_guarda(tmp_path):
    """El panel publica esa frase despues de guardar. Sin ella, el usuario sabe que
    se guardo y no donde, que en Databricks es la diferencia entre encontrar el
    informe y darlo por perdido."""
    assert str(tmp_path) in AlmacenLocal(tmp_path).donde()


# --------------------------------------------------------------- almacen de Volume


class _ClienteFalso:
    """Lo minimo de `WorkspaceClient().files` que este modulo usa.

    Se inyecta en vez de parchear el SDK: la prueba comprueba QUE llamadas hace el
    almacen y con que rutas, que es exactamente lo que se rompe cuando el Volume
    cambia de sitio.
    """

    def __init__(self):
        self.archivos: dict[str, bytes] = {}
        self.carpetas: list[str] = []
        self.files = self

    def create_directory(self, directory_path):
        self.carpetas.append(directory_path)

    def upload(self, file_path, contents, overwrite=False):
        self.archivos[file_path] = contents.read() if hasattr(contents, "read") else contents

    def download(self, file_path):
        class _R:
            def __init__(self, datos):
                self.contents = _Bytes(datos)
        if file_path not in self.archivos:
            raise FileNotFoundError(file_path)
        return _R(self.archivos[file_path])

    def list_directory_contents(self, directory_path):
        for i, (ruta, datos) in enumerate(sorted(self.archivos.items())):
            if ruta.rsplit("/", 1)[0] != directory_path.rstrip("/"):
                continue
            yield _Entrada(ruta, ruta.rsplit("/", 1)[-1], len(datos), 1000 + i)


class _Bytes:
    def __init__(self, datos):
        self._datos = datos

    def read(self):
        return self._datos


class _Entrada:
    def __init__(self, path, name, file_size, last_modified):
        self.path, self.name = path, name
        self.file_size, self.last_modified = file_size, last_modified
        self.is_directory = False


VOLUMEN = "/Volumes/gold/chec/chec-simulador/simulaciones"


def test_el_almacen_de_volume_sube_por_la_files_api():
    """Y no con un `open()` sobre `/Volumes`: el montaje FUSE contesta 403 dentro del
    contenedor de una app (contrato D2), y ese fallo se ve como un `FileNotFoundError`
    que no menciona el montaje por ningun lado."""
    cliente = _ClienteFalso()
    almacen = AlmacenVolumen(VOLUMEN, cliente=cliente)
    almacen.guardar(NOMBRE, datos=DATOS, informe=INFORME)
    assert cliente.archivos[f"{VOLUMEN}/{NOMBRE}"] == DATOS
    assert cliente.archivos[
        f"{VOLUMEN}/{NOMBRE.replace('.simchec.json.gz', '.html')}"
    ] == INFORME.encode("utf-8")


def test_el_almacen_de_volume_crea_la_carpeta_antes_de_subir():
    """`/subir-a-databricks` la crea al desplegar, pero una app que se despliega contra
    un Volume mas viejo no la tiene, y `upload` a una carpeta ausente falla."""
    cliente = _ClienteFalso()
    AlmacenVolumen(VOLUMEN, cliente=cliente).guardar(NOMBRE, datos=DATOS, informe=INFORME)
    assert VOLUMEN in cliente.carpetas


def test_el_almacen_de_volume_lista_solo_sus_registros():
    cliente = _ClienteFalso()
    almacen = AlmacenVolumen(VOLUMEN, cliente=cliente)
    almacen.guardar(NOMBRE, datos=DATOS, informe=INFORME)
    assert [e["clave"] for e in almacen.listar()] == [NOMBRE]


def test_el_almacen_de_volume_devuelve_los_bytes_que_subio():
    cliente = _ClienteFalso()
    almacen = AlmacenVolumen(VOLUMEN, cliente=cliente)
    almacen.guardar(NOMBRE, datos=DATOS, informe=INFORME)
    assert almacen.leer(NOMBRE) == DATOS


def test_el_almacen_de_volume_dice_la_ruta_del_volume():
    assert VOLUMEN in AlmacenVolumen(VOLUMEN, cliente=_ClienteFalso()).donde()


def test_listar_un_volume_vacio_devuelve_vacio_y_no_revienta():
    class _Roto(_ClienteFalso):
        def list_directory_contents(self, directory_path):
            raise RuntimeError("NOT_FOUND")

    assert AlmacenVolumen(VOLUMEN, cliente=_Roto()).listar() == []


# ----------------------------------------------------------------- la eleccion


def test_sin_variable_de_entorno_el_almacen_es_local(tmp_path):
    almacen = almacen_por_defecto(entorno={})
    assert isinstance(almacen, AlmacenLocal)


def test_la_variable_del_volume_manda_sobre_todo(tmp_path):
    """La escribe `/subir-a-databricks` en el `app.yaml`. Es una decision del
    despliegue, no algo que el tablero deba adivinar mirando si existe `/Volumes`."""
    almacen = almacen_por_defecto(entorno={ENTORNO_VOLUMEN: VOLUMEN},
                                  cliente_volumen=_ClienteFalso())
    assert isinstance(almacen, AlmacenVolumen)
    assert VOLUMEN in almacen.donde()


def test_la_variable_local_elige_la_carpeta(tmp_path):
    almacen = almacen_por_defecto(entorno={ENTORNO_LOCAL: str(tmp_path / "mias")})
    assert isinstance(almacen, AlmacenLocal)
    assert str(tmp_path / "mias") in almacen.donde()


def test_la_carpeta_por_defecto_cuelga_del_home_del_usuario():
    """Y no del arbol del repositorio ni de la carpeta de la aplicacion: la aplicacion
    se reconstruye y se mueve -- en Windows hay un `.bat` que la traslada a una ruta
    corta --, y las simulaciones del usuario no pueden viajar con ella."""
    almacen = almacen_por_defecto(entorno={})
    assert str(Path.home()) in almacen.donde()


# --------------------------------------------------- como se llega a lo guardado


def test_el_almacen_local_dice_que_se_abre_con_doble_clic(tmp_path):
    """Los dos almacenes escriben lo mismo y se alcanzan de formas distintas, y el
    panel tiene que decir CUAL. En local basta el doble clic; en Databricks el archivo
    esta en un Volume y no hay descarga desde la pagina de Voila -- sin esa frase, un
    informe correctamente guardado se da por perdido."""
    assert "doble clic" in AlmacenLocal(tmp_path).pista()


def test_el_almacen_de_volume_dice_por_donde_se_baja():
    pista = AlmacenVolumen(VOLUMEN, cliente=_ClienteFalso()).pista()
    assert "Catalog" in pista and "Volumes" in pista
