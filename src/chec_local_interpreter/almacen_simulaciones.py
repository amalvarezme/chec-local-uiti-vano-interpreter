"""Donde quedan las simulaciones guardadas, y como se recuperan.

El tablero del simulador corre en dos sitios que no comparten un solo supuesto
sobre el disco:

- **En la maquina del usuario**, servido por Voila desde `aplicaciones/06_simulador`.
  Hay disco de verdad, el archivo se abre con doble clic y el informe se puede
  lanzar al navegador.
- **En Databricks Apps**, servido por el mismo Voila dentro de un contenedor
  efimero. Lo que se escriba en su disco desaparece con el proximo despliegue y
  ademas el usuario no puede alcanzarlo. La unica superficie que sobrevive y que
  el usuario ve es el Volume de Unity Catalog -- y el Volume **no esta montado**
  (contrato D2, `mount.err` contesta `HTTP 403`): se llega por la Files API.

Este modulo es la unica pieza que conoce esa diferencia. El tablero pide "guarda
esto" y "damelo de vuelta"; nunca aprende cual de los dos mundos le toco.

## La eleccion no se adivina

La hace `SIMULACIONES_VOLUMEN`, que `/subir-a-databricks` escribe resuelta en el
`app.yaml` de la app -- igual que ya hace con `VOLUME_06` y `RUTA_VARIABLES_SIMULAR`.
Adivinar por el entorno ("si existe `/Volumes`, es Databricks") es lo que produce
un tablero local intentando escribir en un Volume que no existe, con un error
que no apunta a esta decision.

`SIMULACIONES_LOCAL` elige la carpeta en el camino local; la aplicacion la fija a
la suya. Sin ninguna de las dos, las simulaciones cuelgan del HOME del usuario y
no del arbol del proyecto: la aplicacion se reconstruye y se mueve -- en Windows
hay un `.bat` que la traslada a una ruta corta -- y el trabajo del usuario no
puede viajar con ella.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from chec_local_interpreter.simulaciones_guardadas import EXTENSION

ENTORNO_VOLUMEN = "SIMULACIONES_VOLUMEN"
ENTORNO_LOCAL = "SIMULACIONES_LOCAL"

CARPETA_POR_DEFECTO = ("CriticidadCHEC", "simulaciones")
"""Bajo el HOME. Dos niveles y no uno: la aplicacion local va a dejar mas cosas
del usuario ahi con el tiempo, y una carpeta `simulaciones` suelta en el home no
dice de que programa es."""


def _nombre_informe(nombre: str) -> str:
    """El HTML que acompania a un registro. Comparten nombre base a proposito: es lo
    que hace que quien abra la carpeta dentro de un anio los vea como una pareja y no
    como dos archivos que coinciden por casualidad."""
    if nombre.endswith(EXTENSION):
        return nombre[: -len(EXTENSION)] + ".html"
    return nombre + ".html"


class AlmacenLocal:
    """Una carpeta del disco de quien usa el tablero."""

    def __init__(self, raiz: Path | str):
        self.raiz = Path(raiz)

    def donde(self) -> str:
        return str(self.raiz)

    def pista(self) -> str:
        """Como se llega a lo que se acaba de guardar. Lo publica el panel al lado de
        la ruta: los dos almacenes escriben lo mismo y se alcanzan de formas distintas,
        y sin decir cual, un informe correctamente guardado se da por perdido."""
        return "Se abre con doble clic desde esa carpeta."

    def guardar(self, nombre: str, *, datos: bytes, informe: str) -> dict[str, str]:
        """Escribe el registro y su informe, y devuelve donde quedo cada uno.

        Crea la carpeta: la primera vez que alguien guarda no existe todavia, y
        pedirle al usuario que la cree antes seria un paso que nadie recuerda.
        """
        self.raiz.mkdir(parents=True, exist_ok=True)
        registro = self.raiz / self._clave_segura(nombre)
        registro.write_bytes(datos)
        # `encoding="utf-8"` explicito y no el del sistema: los nombres del contrato
        # llevan tilde, y en Windows el defecto sigue siendo cp1252, asi que el
        # informe saldria roto SOLO alli -- el peor sitio para descubrirlo.
        salida = self.raiz / _nombre_informe(self._clave_segura(nombre))
        salida.write_text(informe, encoding="utf-8")
        return {"registro": str(registro), "informe": str(salida)}

    def listar(self) -> list[dict[str, Any]]:
        """Las simulaciones guardadas, de la mas reciente a la mas vieja.

        Una carpeta ausente devuelve vacio y no levanta: es el estado normal en la
        primera apertura del tablero, y una excepcion ahi se lee como que el tablero
        se rompio.

        Solo los registros. La carpeta acaba con el doble de archivos -- cada
        registro trae su informe -- mas lo que el usuario deje ahi, y ofrecer un
        `.html` como algo que se puede cargar promete algo que falla al abrirlo.
        """
        if not self.raiz.is_dir():
            return []
        entradas = [
            {"clave": p.name, "bytes": p.stat().st_size, "orden": p.stat().st_mtime}
            for p in self.raiz.iterdir()
            if p.is_file() and p.name.endswith(EXTENSION)
        ]
        entradas.sort(key=lambda e: (e["orden"], e["clave"]), reverse=True)
        return entradas

    def leer(self, clave: str) -> bytes:
        return (self.raiz / self._clave_segura(clave)).read_bytes()

    @staticmethod
    def _clave_segura(clave: str) -> str:
        """La clave viene de un desplegable de la interfaz, pero un registro
        guardado se puede renombrar a mano. Un nombre con separadores de ruta no
        puede convertirse en una escritura a cualquier sitio del disco."""
        limpio = str(clave)
        if limpio != Path(limpio).name or limpio in ("", ".", ".."):
            raise ValueError(
                f"Nombre de simulacion invalido: {clave!r}. Tiene que ser un nombre "
                "de archivo, no una ruta."
            )
        return limpio


class AlmacenVolumen:
    """Una carpeta de un Volume de Unity Catalog, por la Files API.

    `cliente` se inyecta para poder probarlo sin Databricks; en produccion nace de
    `WorkspaceClient()`, que resuelve sus credenciales del entorno de la app.
    """

    def __init__(self, volumen: str, *, cliente: Any = None):
        self.volumen = str(volumen).rstrip("/")
        self._cliente = cliente

    @property
    def cliente(self):
        if self._cliente is None:
            from databricks.sdk import WorkspaceClient

            self._cliente = WorkspaceClient()
        return self._cliente

    def donde(self) -> str:
        return self.volumen

    def pista(self) -> str:
        """Voila no sirve archivos sueltos, asi que desde la propia pagina no hay
        descarga: el informe se baja por la interfaz del workspace. Decirlo aqui es la
        diferencia entre encontrarlo y darlo por perdido."""
        return ("Se baja desde <b>Catalog → Volumes</b> en el workspace: la aplicación "
                "no puede ofrecer la descarga directamente.")

    def guardar(self, nombre: str, *, datos: bytes, informe: str) -> dict[str, str]:
        """Sube el registro y su informe por la Files API.

        NO con un `open()` sobre `/Volumes`: dentro del contenedor de una app ese
        montaje contesta 403 (contrato D2) y el fallo aparece como un
        `FileNotFoundError` que no menciona el montaje por ningun lado.
        """
        clave = AlmacenLocal._clave_segura(nombre)
        # La crea `/subir-a-databricks` al desplegar, pero una app desplegada contra
        # un Volume mas viejo no la tiene y `upload` a una carpeta ausente falla.
        # Es idempotente, asi que se pide siempre en vez de comprobar antes.
        try:
            self.cliente.files.create_directory(self.volumen)
        except Exception:  # noqa: BLE001 -- ya existe, o no hay permiso; lo dira `upload`
            pass
        import io

        registro = f"{self.volumen}/{clave}"
        salida = f"{self.volumen}/{_nombre_informe(clave)}"
        self.cliente.files.upload(registro, io.BytesIO(datos), overwrite=True)
        self.cliente.files.upload(salida, io.BytesIO(informe.encode("utf-8")),
                                  overwrite=True)
        return {"registro": registro, "informe": salida}

    def listar(self) -> list[dict[str, Any]]:
        """Igual que en local: solo registros, del mas nuevo al mas viejo.

        Un Volume sin la carpeta -- o sin permiso para listarla -- devuelve vacio.
        Al usuario le sirve mas un desplegable vacio con el panel entero funcionando
        que un tablero que no abre.
        """
        try:
            entradas = list(self.cliente.files.list_directory_contents(self.volumen))
        except Exception:  # noqa: BLE001 -- carpeta ausente o sin permiso
            return []
        salida = [
            {
                "clave": e.name,
                "bytes": int(getattr(e, "file_size", 0) or 0),
                "orden": int(getattr(e, "last_modified", 0) or 0),
            }
            for e in entradas
            if not getattr(e, "is_directory", False) and str(e.name).endswith(EXTENSION)
        ]
        salida.sort(key=lambda e: (e["orden"], e["clave"]), reverse=True)
        return salida

    def leer(self, clave: str) -> bytes:
        ruta = f"{self.volumen}/{AlmacenLocal._clave_segura(clave)}"
        return self.cliente.files.download(ruta).contents.read()


def almacen_por_defecto(
    entorno: Mapping[str, str] | None = None, *, cliente_volumen: Any = None
):
    """El almacen que le toca a esta corrida del tablero.

    `entorno` entra como argumento -- con `os.environ` por defecto -- para que la
    decision se pueda probar sin escribir variables de proceso, que es estado
    global y se filtra entre pruebas.
    """
    entorno = os.environ if entorno is None else entorno
    volumen = str(entorno.get(ENTORNO_VOLUMEN, "")).strip()
    if volumen:
        return AlmacenVolumen(volumen, cliente=cliente_volumen)
    local = str(entorno.get(ENTORNO_LOCAL, "")).strip()
    if local:
        return AlmacenLocal(Path(local))
    return AlmacenLocal(Path.home().joinpath(*CARPETA_POR_DEFECTO))
