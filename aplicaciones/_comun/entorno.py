"""Entorno virtual propio de cada aplicacion, identico en macOS y en Windows.

Cada aplicacion instala SOLO sus dependencias en su propio `.venv`. No comparten
entorno con el repositorio ni entre ellas, y por una razon medible: el visor de
tableros (01 y 02) no necesita `torch` ni `geopandas` para SERVIR el tablero ya
construido, y el simulador (06) no necesita `scikit-learn` en tiempo de ejecucion.
Un entorno unico las obligaria a instalar la union de las tres.

Este modulo usa solo la biblioteca estandar: corre con el Python del sistema,
ANTES de que exista ningun entorno.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import urllib.parse
import venv
from pathlib import Path

# `venv` reproduce el layout de la instalacion, y en Windows los ejecutables van a
# Scripts/ en vez de bin/. No hay forma portable de preguntarlo sin el interprete
# ya creado, asi que se decide por plataforma.
ES_WINDOWS = os.name == "nt"
SUBCARPETA_BIN = "Scripts" if ES_WINDOWS else "bin"
NOMBRE_PYTHON = "python.exe" if ES_WINDOWS else "python"

# El repositorio corre sobre 3.11. Se admite desde 3.10 porque nada de estas
# aplicaciones usa sintaxis mas nueva, y se rechaza 3.9 y anteriores explicitamente:
# `list[str]` en anotaciones evaluadas y `zoneinfo` fallan ahi de formas poco claras.
PYTHON_MINIMO = (3, 10)


def ruta_venv(app: Path) -> Path:
    return app / ".venv"


def python_del_venv(app: Path) -> Path:
    return ruta_venv(app) / SUBCARPETA_BIN / NOMBRE_PYTHON


def ejecutable_del_venv(app: Path, nombre: str) -> Path:
    """Ruta de un ejecutable instalado por pip dentro del entorno (p. ej. `voila`)."""
    sufijo = ".exe" if ES_WINDOWS else ""
    return ruta_venv(app) / SUBCARPETA_BIN / f"{nombre}{sufijo}"


def verificar_python_actual() -> None:
    if sys.version_info < PYTHON_MINIMO:
        raise SystemExit(
            f"Se necesita Python {PYTHON_MINIMO[0]}.{PYTHON_MINIMO[1]} o superior; "
            f"este es {sys.version.split()[0]} ({sys.executable}).\n"
            "En macOS: brew install python@3.11 -- en Windows: https://www.python.org/downloads/"
        )


def existe(app: Path) -> bool:
    return python_del_venv(app).exists()


# ---------------------------------------------------- hay salida para pip?

# Los dos hosts con los que habla pip y ningun otro: el indice y el almacen de ruedas.
HOSTS_DE_PYPI = ("pypi.org", "files.pythonhosted.org")

# Las variables que leen `requests`/`urllib3`, que es por donde va pip. En el orden en
# que pip las mira: la de HTTPS primero, porque el indice es HTTPS.
VARIABLES_DE_PROXY = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")

# Cuanto se espera a que conteste. Corto a proposito: esto es un sondeo previo, y lo que
# evita -- una instalacion colgada sin final ni mensaje -- cuesta infinitamente mas.
ESPERA_DEL_SONDEO = 5.0


def _alcanzable(host: str, puerto: int, espera: float = ESPERA_DEL_SONDEO) -> bool:
    try:
        with socket.create_connection((host, puerto), timeout=espera):
            return True
    except OSError:
        return False


def _proxy_declarado() -> tuple[str, int] | None:
    """El host y el puerto del proxy que pip va a usar, si hay uno en el entorno.

    Devuelve `None` cuando no hay ninguna variable puesta, y tambien cuando la que hay
    no se sabe leer. Los dos casos son distintos y aqui no hace falta separarlos: quien
    llama solo necesita saber a quien preguntarle, y si no lo sabe deja pasar a pip.
    """
    for nombre in VARIABLES_DE_PROXY:
        valor = os.environ.get(nombre)
        if not valor:
            continue
        partes = urllib.parse.urlparse(valor if "//" in valor else f"//{valor}")
        if not partes.hostname:
            return None
        return (partes.hostname, partes.port or (443 if partes.scheme == "https" else 80))
    return None


def hay_salida_para_pip(espera: float = ESPERA_DEL_SONDEO) -> bool:
    """Si pip va a poder llegar a donde tiene que llegar.

    Con proxy declarado se sondea EL PROXY y no PyPI: detras de un proxy la salida
    directa esta cortada a proposito, asi que preguntarle a PyPI daria por rota una
    maquina que funciona.

    Sin proxy declarado se sondea PyPI, y basta con que conteste uno de los dos hosts:
    lo que se esta preguntando es si hay camino, no si el indice esta sano.

    Un valor de proxy que no se sepa leer se deja pasar. pip si sabria leerlo, y negar
    la instalacion por no entenderlo seria cambiar un fallo diagnosticable por uno que
    no lo es.
    """
    proxy = _proxy_declarado()
    if proxy is not None:
        return _alcanzable(proxy[0], proxy[1], espera)
    if any(os.environ.get(n) for n in VARIABLES_DE_PROXY):
        return True
    return any(_alcanzable(host, 443, espera) for host in HOSTS_DE_PYPI)


def aviso_sin_salida() -> str:
    """El texto de la alerta cuando pip no tiene por donde salir.

    Nombra la variable de entorno porque es lo unico que arregla el caso, y no es nada
    evidente: la maquina TIENE internet -- el navegador entra, y por eso el menu se abre
    y se ve bien --, asi que nadie va a buscar el fallo ahi.
    """
    return (
        "\n  SIN SALIDA A PYPI: no se pudo abrir conexion con pypi.org, asi que pip no\n"
        "  va a poder instalar nada y la instalacion se quedaria colgada sin decir por\n"
        "  que.\n\n"
        "  Si esta maquina sale a internet por un proxy corporativo, ese es el motivo:\n"
        "  **pip no lee el proxy de Opciones de Internet** (WinINET), que es donde suele\n"
        "  estar puesto en Windows. Solo lee estas variables de entorno:\n\n"
        "    setx HTTPS_PROXY http://usuario:clave@proxy.de.la.empresa:8080\n"
        "    setx HTTP_PROXY  http://usuario:clave@proxy.de.la.empresa:8080\n\n"
        "  Hay que abrir una consola NUEVA despues de ponerlas, y volver a abrir la\n"
        "  aplicacion. El dato que hay que pedirle a quien administra la maquina es la\n"
        "  direccion y el puerto del proxy.\n")


def crear(app: Path, *, recrear: bool = False) -> Path:
    """Crea el entorno de la aplicacion e instala su `requirements.txt`.

    Devuelve la ruta del interprete del entorno. Es idempotente: volver a llamarla
    reinstala las dependencias sobre el entorno existente, que es lo que hace falta
    cuando `requirements.txt` cambia.
    """
    verificar_python_actual()
    destino = ruta_venv(app)

    if recrear and destino.exists():
        import shutil

        print(f"[entorno] borrando {destino}")
        shutil.rmtree(destino)

    if not python_del_venv(app).exists():
        print(f"[entorno] creando {destino} con {sys.executable}")
        # `with_pip=True` es el valor por defecto, pero se deja explicito: sin pip el
        # entorno queda inservible y el error aparece recien en el install de abajo.
        venv.EnvBuilder(with_pip=True, clear=False).create(destino)
    else:
        print(f"[entorno] reutilizando {destino}")

    py = python_del_venv(app)
    requisitos = app / "requirements.txt"
    if not requisitos.exists():
        raise SystemExit(f"Falta {requisitos}")

    # ANTES de pip, y no despues: sin salida a la red pip no falla rapido, se queda
    # reintentando -- y el menu lo lanza con la salida capturada y sin `timeout`, asi
    # que ese cuelgue no tiene final ni deja ver una sola linea.
    if not hay_salida_para_pip():
        raise SystemExit(aviso_sin_salida())

    # pip nuevo en el entorno antes de instalar: las ruedas de `pyarrow` y `torch`
    # dependen de etiquetas de plataforma que pip viejo no sabe leer, y el sintoma es
    # una compilacion desde fuente de veinte minutos en vez de un mensaje claro.
    _correr([str(py), "-m", "pip", "install", "--upgrade", "pip", "wheel"])
    _correr([str(py), "-m", "pip", "install", "-r", str(requisitos)])
    return py


def asegurar(app: Path) -> Path:
    """Devuelve el interprete del entorno, o explica como crearlo."""
    py = python_del_venv(app)
    if not py.exists():
        # En macOS el doble clic es `Iniciar.app`, que ya instala solo si hace falta; el
        # `.command` de al lado es para una terminal ya abierta y no se nombra aqui como
        # "doble clic", que es justo la confusion que costo una sesion.
        script = "instalar.bat (doble clic)" if ES_WINDOWS else "Iniciar.app (doble clic)"
        raise SystemExit(
            f"La aplicacion {app.name} todavia no tiene entorno.\n"
            f"Abre primero {app / script}."
        )
    return py


def _correr(comando: list[str]) -> None:
    print("[entorno] $ " + " ".join(comando))
    resultado = subprocess.run(comando)
    if resultado.returncode != 0:
        raise SystemExit(
            f"Fallo la instalacion de dependencias (codigo {resultado.returncode}). "
            "El detalle esta en las lineas de pip de arriba."
        )
