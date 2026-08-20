"""Que le falta a ESTA maquina para correr el proyecto. Solo biblioteca estandar.

## Por que un script y no una lista de comprobaciones en el comando

`/instalar-local` podria preguntar dieciseis cosas con dieciseis lineas de shell. No lo hace
por lo mismo que `/subir-a-databricks` no arma sus apps copiando bloques de un Markdown:
lo que se puede equivocar en silencio tiene que ser codigo con pruebas. Aqui lo que se
equivoca en silencio es la LISTA -- que insumos hacen falta, que puertos, que piso de
Python -- y por eso ninguna de esas listas se escribe aqui: se importan de quien ya las
tenia.

## Corre ANTES de que exista ningun entorno

Esa es la restriccion que manda: lo ejecuta el Python del sistema en una maquina recien
clonada, asi que no puede importar nada que haya que instalar. Es la misma regla que
gobierna `aplicaciones/_comun/entorno.py`, y por eso este archivo puede importarlo.

## Los tres destinos

Se responde por separado, porque piden cosas distintas y una maquina puede estar lista
para uno y no para otro:

    cuaderno       correr `notebooks/05_mil_vano_ventana.ipynb`
    aplicaciones   abrir CriticidadCHEC y sus cinco tableros en local
    databricks     subirlo todo con `/subir-a-databricks`

Uso:

    python3 scripts/diagnostico_local.py           # informe legible
    python3 scripts/diagnostico_local.py --json    # el mismo dato, para el comando

Sale 0 si los tres destinos estan listos, 1 si a alguno le falta algo.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
COMUN = RAIZ / "aplicaciones" / "_comun"
if str(COMUN) not in sys.path:
    sys.path.insert(0, str(COMUN))

import entorno as _entorno  # noqa: E402
import menu as _menu  # noqa: E402
import servidor as _servidor  # noqa: E402

ES_WINDOWS = os.name == "nt"
ES_MAC = sys.platform == "darwin"
SISTEMA = "windows" if ES_WINDOWS else ("macos" if ES_MAC else "otro")

LISTO, FALTA, AVISO = "listo", "falta", "aviso"

# ---------------------------------------------------------------- lo que se pide

# El piso de Python NO se escribe aqui: lo declara la guarda que lo aplica, con la
# tabla de ruedas medida detras (`tests/test_piso_de_python.py`). Una segunda copia
# seria una segunda verdad, y la que se desactualiza siempre es la copia.
PISO_PYTHON = _entorno.PYTHON_MINIMO

# Igual con los puertos: son del menu local y de nadie mas.
PUERTOS = {"CriticidadCHEC": _menu.PUERTO_MENU, **_menu.PUERTOS}

# Los insumos que un clon tiene que traer, y que nadie genera en destino. Esta lista
# vivia en `tests/test_clon_limpio.py`; se mudo aqui porque tiene dos consumidores --
# esa prueba y este diagnostico -- y el codigo de produccion es el que debe tenerla.
INSUMOS = {
    "data/Indicadores_vano_v3.csv": "la base de eventos (LFS)",
    "data/Variables_seleccion.xlsx": "el diccionario de variables",
    "data/Variables_simular.xlsx": "el catalogo de variables a simular",
    "data/Actividades_mantenimiento_costos_2026.xlsx": "el catalogo de costos",
    "data/geometria_kmeans_014_v1.json": "la geometria KMeans congelada",
    "data/models/mil_vano_ventana_v1.pt": "el modelo MIL entrenado",
    "data/graphs/mgcecdl_feature_order.json": "el orden de features del grafo",
    "data/derived/bolsas_mil_full.joblib": "las bolsas vano x ventana (LFS)",
    "site/data/variables.json": "los modos tematicos A-F del cuaderno 05",
}

SHAPEFILES = ("MVLINSEC", "GDBCHEC_TRANSFOR", "SWITCHES")
SIDECARS = ("shp", "shx", "dbf", "prj")

APPS = ("00_criticidad_chec", "01_clima", "02_agrupamiento_vanos",
        "03_trayectorias_circuitos", "04_trayectorias_vanos", "06_simulador")

# Medidos en `docs/REQUISITOS-MINIMOS.md`, seccion 2: todo con holgura son 16 GB y
# 20 GB libres; el minimo util -- los cuatro tableros -- son 4 GB y 3,5 GB.
RAM_MINIMA_GB = 8
RAM_HOLGADA_GB = 16
DISCO_MINIMO_GB = 6
DISCO_HOLGADO_GB = 20

# El comienzo de un puntero de Git LFS. Un clon sin `git lfs pull` deja archivos de
# ~134 bytes que empiezan asi, y lo caro es que EXISTEN: `fs cp -r` los sube tal cual y
# el hueco aparece mucho despues, dentro de una app que no arranca.
CABECERA_PUNTERO = b"version https://git-lfs.github.com/spec/v1"

# Las tres DLL del runtime de Visual C++ que `torch` carga al importar. NO son un
# paquete de pip: las pone el Visual C++ Redistributable, y sin ellas `import torch`
# muere con `WinError 126` sobre `c10.dll` en un entorno donde pip no tiene nada que
# arreglar. Se midio en una maquina con los 193 paquetes puestos y `pip check` limpio.
DLLS_DEL_RUNTIME_VC = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")

# Windows no deja CREAR un directorio cuyo camino pase de `MAX_PATH` - 12 = 248, aunque
# el limite de un archivo sea 260. Los doce reservados son para lo que vaya dentro.
LIMITE_DE_DIRECTORIO = 248

# El camino mas hondo que crea la instalacion, contado DESDE la raiz del repositorio:
#     aplicaciones / 06_simulador / .venv / Lib / site-packages /
#     torch-2.13.0.dist-info / licenses / third_party / kineto / libkineto /
#     third_party / dynolog / third_party / DCGM / testing / python3 /
#     libs_3rdparty / colorama
# Son las licencias de terceros de `kineto`, anidadas nueve niveles, y las pone
# `torch`. Medido el 2026-08-19 sobre `torch` 2.13.0 con el clon a 65 caracteres:
# 252 en total, cuatro por encima del limite, y la instalacion del simulador aborta
# con `WinError 206` dejando el `.venv` creado y a medias.
COLA_MAS_LARGA = 187


@dataclass(frozen=True)
class Revision:
    """Una comprobacion, su resultado y como se arregla en cada sistema.

    `arreglo` es un diccionario por sistema y no una cadena: casi todo lo que falta se
    instala distinto en macOS y en Windows, y dar el comando del otro sistema es peor
    que no dar ninguno -- se copia, no funciona, y el usuario concluye que el
    diagnostico esta mal.
    """

    clave: str
    titulo: str
    estado: str
    detalle: str
    arreglo: dict = field(default_factory=dict)

    @property
    def mio(self) -> str:
        return self.arreglo.get(SISTEMA, "")


# Que necesita cada destino. Un destino esta listo cuando ninguna de sus revisiones
# esta en `falta`; un `aviso` no lo tumba (holgura de RAM, un puerto ocupado por otra
# cosa) pero se reporta.
METAS = {
    "cuaderno": ("python", "runtime_vc", "entorno_raiz", "datos"),
    "aplicaciones": ("python", "runtime_vc", "rutas_largas", "entornos_apps",
                     "datos", "datos_lfs", "puertos", "red"),
    "databricks": ("python", "runtime_vc", "entorno_raiz", "datos", "datos_lfs", "red",
                   "databricks_cli", "databricks_perfil"),
}

TITULOS_META = {
    "cuaderno": "correr el cuaderno mil_vano (05)",
    "aplicaciones": "abrir CriticidadCHEC y sus tableros en local",
    "databricks": "subirlo todo con /subir-a-databricks",
}


# Como se arregla cada cosa, por sistema. Vive AQUI y no dentro de la rama que la
# necesita, y eso es lo que la hace comprobable: en una maquina sana ninguna rama de
# `falta` se ejecuta nunca, asi que el consejo de Windows -- escrito desde un Mac, que
# es donde se desarrolla esto -- no lo leeria nadie hasta el dia que hiciera falta.
# Con la tabla suelta, `tests/test_diagnostico_local.py` la revisa entera desde macOS.
#
# Los dos sistemas siempre. Dar el comando del otro es peor que no dar ninguno: se
# copia, no funciona, y quien lo lee concluye que el diagnostico esta equivocado.
ARREGLOS = {
    "python": {
        "macos": "brew install python@3.11",
        "windows": "descargar de https://www.python.org/downloads/ y marcar "
                   "'Add python.exe to PATH'; despues se invoca con `py -3`",
    },
    "git": {
        "macos": "xcode-select --install",
        "windows": "winget install Git.Git",
    },
    "git_lfs": {
        "macos": "brew install git-lfs && git lfs install",
        "windows": "winget install GitHub.GitLFS && git lfs install",
    },
    # El mismo comando en los dos, y se escribe repetido en vez de omitirse: la regla es
    # "siempre los dos", y una excepcion invita a la siguiente.
    "datos": {"macos": "git lfs pull", "windows": "git lfs pull"},
    "datos_lfs": {"macos": "git lfs pull", "windows": "git lfs pull"},
    "red": {
        "macos": "export HTTPS_PROXY=http://usuario:clave@proxy.de.la.empresa:8080",
        "windows": "setx HTTPS_PROXY http://usuario:clave@proxy.de.la.empresa:8080 "
                   "y abrir una consola NUEVA; pip no lee el proxy de Opciones de "
                   "Internet (WinINET), que es donde suele estar puesto",
    },
    "entorno_raiz": {
        "macos": "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt",
        "windows": r"py -3 -m venv .venv && .venv\Scripts\pip install -r requirements.txt",
    },
    "entornos_apps": {
        "macos": "doble clic en aplicaciones/<app>/instalar-en-terminal.command",
        "windows": "doble clic en aplicaciones/<app>/instalar.bat",
    },
    "puertos": {
        "macos": "lsof -nP -iTCP:<puerto> -sTCP:LISTEN para ver quien lo tiene",
        "windows": "netsh interface ipv4 show excludedportrange protocol=tcp para ver "
                   "el rango reservado, y pedirle a quien administra la maquina que lo "
                   "libere; netstat -ano | findstr :<puerto> si lo tiene un programa",
    },
    "databricks_cli": {
        "macos": "brew tap databricks/tap && brew install databricks",
        "windows": "winget install Databricks.DatabricksCLI",
    },
    "databricks_perfil": {
        "macos": "databricks auth login --host <URL del workspace>",
        "windows": "databricks auth login --host <URL del workspace>",
    },
    "runtime_vc": {
        "macos": "no hace falta: el runtime de C++ lo trae el sistema",
        "windows": "winget install Microsoft.VCRedist.2015+.x64 "
                   "--accept-package-agreements; pide permisos de administrador, asi "
                   "que lo corre quien los tenga",
    },
    "rutas_largas": {
        "macos": "no hace falta: macOS no tiene MAX_PATH",
        "windows": "en PowerShell como administrador: Set-ItemProperty -Path "
                   r"'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name "
                   "LongPathsEnabled -Value 1 -Type DWord; despues, reiniciar la sesion",
    },
    "disco": {
        "macos": "liberar espacio; los entornos y los paneles son lo que mas pesa",
        "windows": "liberar espacio; los entornos y los paneles son lo que mas pesa",
    },
}


# ---------------------------------------------------------------- utilidades


def _corre(comando: list[str], espera: float = 20.0) -> tuple[int, str, str]:
    """Ejecuta y devuelve `(codigo, stdout, stderr)`. Nunca levanta: un ejecutable que
    no esta es un dato del diagnostico, no un fallo del diagnostico.

    **Los dos flujos van SEPARADOS, y no es un detalle de estilo.** Es la restriccion D7
    del contrato de despliegue: la CLI de Databricks escribe avisos por `stderr` de
    forma intermitente, y juntarlos con `stdout` hace que `json.loads` muera con
    `Expecting value: line 1 column 1` sobre una llamada perfectamente sana. La primera
    version de este archivo los concatenaba y reportaba "no hay ningun perfil
    configurado" en una maquina con dos.
    """
    try:
        hecho = subprocess.run(comando, capture_output=True, text=True, timeout=espera)
    except (OSError, subprocess.SubprocessError):
        return (127, "", "")
    return (hecho.returncode, hecho.stdout or "", hecho.stderr or "")


def _gb_libres(ruta: Path) -> float:
    try:
        return shutil.disk_usage(ruta).free / 1024**3
    except OSError:
        return -1.0


def _gb_de_ram() -> float:
    """La RAM fisica. Dos caminos porque no hay uno portable en la biblioteca estandar."""
    if ES_WINDOWS:
        class _Estado(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        estado = _Estado()
        estado.dwLength = ctypes.sizeof(_Estado)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):
            return estado.ullTotalPhys / 1024**3
        return -1.0
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024**3
    except (ValueError, OSError, AttributeError):
        return -1.0


def _es_puntero(ruta: Path) -> bool:
    try:
        with open(ruta, "rb") as fh:
            return fh.read(len(CABECERA_PUNTERO)) == CABECERA_PUNTERO
    except OSError:
        return False


# ---------------------------------------------------------------- las revisiones


def revisar_sistema() -> Revision:
    detalle = (f"{SISTEMA} | {sys.platform} | {os.uname().machine}"
               if hasattr(os, "uname") else f"{SISTEMA} | {sys.platform}")
    if SISTEMA == "otro":
        return Revision("sistema", "Sistema operativo", AVISO,
                        f"{detalle} -- el proyecto se usa en macOS y Windows; aqui puede "
                        "correr, pero los lanzadores de doble clic no existen")
    return Revision("sistema", "Sistema operativo", LISTO, detalle)


def revisar_memoria() -> Revision:
    gb = _gb_de_ram()
    if gb < 0:
        return Revision("memoria", "RAM", AVISO, "no se pudo medir")
    detalle = f"{gb:.1f} GB"
    if gb < RAM_MINIMA_GB:
        return Revision("memoria", "RAM", AVISO,
                        f"{detalle}; el simulador pide {RAM_MINIMA_GB} GB y los cuatro "
                        "tableros abiertos a la vez tambien")
    if gb < RAM_HOLGADA_GB:
        return Revision("memoria", "RAM", LISTO,
                        f"{detalle}; alcanza, con {RAM_HOLGADA_GB} GB va holgado")
    return Revision("memoria", "RAM", LISTO, detalle)


def revisar_disco() -> Revision:
    gb = _gb_libres(RAIZ)
    if gb < 0:
        return Revision("disco", "Disco libre", AVISO, "no se pudo medir")
    detalle = f"{gb:.1f} GB libres"
    if gb < DISCO_MINIMO_GB:
        return Revision("disco", "Disco libre", FALTA,
                        f"{detalle}; hacen falta {DISCO_MINIMO_GB} GB para los entornos "
                        f"y los paneles, y {DISCO_HOLGADO_GB} para todo con holgura",
                        ARREGLOS["disco"])
    if gb < DISCO_HOLGADO_GB:
        return Revision("disco", "Disco libre", LISTO,
                        f"{detalle}; alcanza, con {DISCO_HOLGADO_GB} GB va holgado")
    return Revision("disco", "Disco libre", LISTO, detalle)


def revisar_python() -> Revision:
    actual = sys.version_info[:3]
    piso = ".".join(str(n) for n in PISO_PYTHON)
    detalle = f"{'.'.join(str(n) for n in actual)} ({sys.executable})"
    arreglo = ARREGLOS["python"]
    if actual[:2] < PISO_PYTHON:
        return Revision("python", "Python del sistema", FALTA,
                        f"{detalle}; hace falta {piso} o superior -- `pandas>=3.0`, "
                        "`numpy>=2.4` y `scikit-learn>=1.9` no publican rueda por debajo",
                        arreglo)
    return Revision("python", "Python del sistema", LISTO, f"{detalle}; piso {piso}")


def revisar_git() -> Revision:
    codigo, salida, _ = _corre(["git", "--version"])
    if codigo != 0:
        return Revision("git", "git", FALTA, "no esta instalado", ARREGLOS["git"])
    return Revision("git", "git", LISTO, salida.strip().splitlines()[0])


def revisar_git_lfs() -> Revision:
    codigo, salida, _ = _corre(["git", "lfs", "version"])
    arreglo = ARREGLOS["git_lfs"]
    if codigo != 0:
        return Revision("git_lfs", "git-lfs", FALTA,
                        "no esta instalado; sin el, el CSV de 566 MB y las bolsas de "
                        "199 MB llegan como punteros de 134 bytes", arreglo)
    return Revision("git_lfs", "git-lfs", LISTO, salida.strip().splitlines()[0])


def revisar_datos() -> Revision:
    """Que los insumos ESTEN. Que traigan sus bytes lo mira la revision de al lado."""
    faltan = [r for r in INSUMOS if not (RAIZ / r).exists()]
    faltan += [f"data/GEO/{n}.{e}" for n in SHAPEFILES for e in SIDECARS
               if not (RAIZ / "data" / "GEO" / f"{n}.{e}").exists()]
    if faltan:
        return Revision("datos", "Insumos del repositorio", FALTA,
                        f"faltan {len(faltan)}: " + ", ".join(faltan[:4])
                        + ("..." if len(faltan) > 4 else ""), ARREGLOS["datos"])
    return Revision("datos", "Insumos del repositorio", LISTO,
                    f"los {len(INSUMOS)} archivos y los {len(SHAPEFILES)} shapefiles "
                    "con sus sidecars")


def revisar_datos_lfs() -> Revision:
    """El fallo mas caro del clon limpio: el archivo existe y son 134 bytes de texto."""
    punteros = [r for r in INSUMOS if (RAIZ / r).exists() and _es_puntero(RAIZ / r)]
    punteros += [f"data/GEO/{n}.{e}" for n in SHAPEFILES for e in SIDECARS
                 if _es_puntero(RAIZ / "data" / "GEO" / f"{n}.{e}")]
    if punteros:
        return Revision("datos_lfs", "Contenido de los archivos de LFS", FALTA,
                        f"{len(punteros)} son punteros y no datos: "
                        + ", ".join(punteros[:3])
                        + ("..." if len(punteros) > 3 else ""), ARREGLOS["datos_lfs"])
    return Revision("datos_lfs", "Contenido de los archivos de LFS", LISTO,
                    "ningun puntero: los archivos traen sus bytes")


def revisar_red() -> Revision:
    """Si pip va a poder salir. Con proxy declarado se sondea el proxy, no PyPI."""
    if _entorno.hay_salida_para_pip():
        return Revision("red", "Salida a PyPI para pip", LISTO, "hay camino")
    return Revision("red", "Salida a PyPI para pip", FALTA,
                    "no se pudo abrir conexion; si esta maquina sale por un proxy "
                    "corporativo, pip NO lee el de Opciones de Internet",
                    ARREGLOS["red"])


# Lo que se le pregunta al Python de una aplicacion: que distribucion de su propio
# `requirements.txt` NO esta instalada. Se compara por nombre de DISTRIBUCION y no por
# modulo importable a proposito -- `scikit-learn` importa como `sklearn`, `jupyter-server`
# como `jupyter_server` --, y asi la lista no se copia aqui: la pone cada aplicacion.
GUION_DE_DISTRIBUCIONES = r"""
import re, sys
from importlib.metadata import PackageNotFoundError, distribution
faltan = []
for linea in open(sys.argv[1], encoding='utf-8'):
    linea = linea.split('#')[0].strip()
    if not linea or linea.startswith('-'):
        continue
    nombre = re.split(r'[<>=!~;\[]', linea)[0].strip()
    if not nombre:
        continue
    try:
        distribution(nombre)
    except PackageNotFoundError:
        faltan.append(nombre)
print(' '.join(faltan))
"""


def _causa(error: str) -> str:
    """El porque que Python dejo en `stderr`, propagado tal cual.

    **Esta funcion existe por un fallo concreto de este archivo.** `revisar_entorno_raiz`
    hacia `codigo, _, _ = _corre(...)`: se quedaba con el codigo de salida y tiraba los
    dos flujos. En una maquina con los 193 paquetes puestos y `pip check` limpio,
    reportaba "le falta alguna dependencia (torch, scikit-learn, pandas o plotly)" y
    mandaba a reinstalar `requirements.txt` -- 1,9 GB que la dejaban exactamente igual.
    En el `stderr` descartado venia el diagnostico entero, con su URL:

        OSError: [WinError 126] ... Error loading "...torch\\lib\\c10.dll"
        Microsoft Visual C++ Redistributable is not installed, ...
        It can be downloaded at https://aka.ms/vs/17/release/vc_redist.x64.exe

    Adivinar la causa desde un entero cuando el proceso ya la escribio es el mismo error
    que la restriccion D7 que `_corre` documenta arriba, por el otro lado: alli se
    perdian datos por juntar los flujos, aqui por tirarlos.
    """
    lineas = [l.rstrip() for l in error.splitlines() if l.strip()]
    if not lineas:
        return "sin mensaje; reproducelo a mano con el import de arriba"
    # Desde la linea de la excepcion hasta el final: lo anterior es la pila, que aqui
    # no dice nada -- el import lo lanzo este mismo comando de una linea.
    desde = 0
    for i, linea in enumerate(lineas):
        if linea[:1].isupper() and ("Error" in linea.split(":")[0]
                                    or "Exception" in linea.split(":")[0]):
            desde = i
    texto = " ".join(l.strip() for l in lineas[desde:])
    return texto if len(texto) <= 300 else texto[:297] + "..."


def revisar_runtime_vc() -> Revision:
    """Las DLL de Visual C++ que `torch` necesita para CARGAR, no para instalarse.

    Se revisa por separado -- y no dentro de cada entorno -- porque es un hecho del
    SISTEMA, uno solo, que rompe los siete entornos a la vez: el de la raiz y el del
    simulador, que son los que traen `torch`. Comprobarlo aqui da un unico `arreglo`
    correcto en vez de seis mensajes que culpan a pip.
    """
    if not ES_WINDOWS:
        return Revision("runtime_vc", "Runtime de Visual C++", LISTO,
                        "no aplica: el sistema ya trae el runtime de C++")
    faltan = []
    for nombre in DLLS_DEL_RUNTIME_VC:
        try:
            ctypes.WinDLL(nombre)
        except OSError:
            faltan.append(nombre)
    if faltan:
        return Revision("runtime_vc", "Runtime de Visual C++", FALTA,
                        "no cargan " + ", ".join(faltan) + "; sin ellas `import torch` "
                        "muere con WinError 126 sobre c10.dll aunque pip tenga todo "
                        "puesto y `pip check` salga limpio",
                        ARREGLOS["runtime_vc"])
    return Revision("runtime_vc", "Runtime de Visual C++", LISTO,
                    f"cargan las {len(DLLS_DEL_RUNTIME_VC)}")


def revisar_rutas_largas() -> Revision:
    """`LongPathsEnabled`, contra la hondura que ESTE clon va a necesitar.

    No se responde en absoluto sino contra el sitio donde esta el repositorio: con el
    limite puesto, que la instalacion quepa o no depende de cuantos caracteres consuma
    la ruta del clon, y por eso el detalle da la cuenta y no solo el veredicto.
    """
    if not ES_WINDOWS:
        return Revision("rutas_largas", "Rutas largas de Windows", LISTO,
                        "no aplica: aqui no hay MAX_PATH")
    import winreg  # noqa: PLC0415 -- solo existe en Windows, y solo hace falta aqui
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\FileSystem") as clave:
            valor, _ = winreg.QueryValueEx(clave, "LongPathsEnabled")
    except OSError:
        valor = 0
    if valor:
        return Revision("rutas_largas", "Rutas largas de Windows", LISTO,
                        "LongPathsEnabled=1; la hondura de la ruta deja de importar")
    hondura = len(str(RAIZ)) + COLA_MAS_LARGA
    cuenta = (f"el clon esta a {len(str(RAIZ))} caracteres y torch llega a {hondura}, "
              f"con el corte en {LIMITE_DE_DIRECTORIO}")
    if hondura > LIMITE_DE_DIRECTORIO:
        return Revision("rutas_largas", "Rutas largas de Windows", FALTA,
                        f"LongPathsEnabled=0 y no cabe: {cuenta}; la instalacion del "
                        "simulador aborta con WinError 206 y deja el .venv a medias",
                        ARREGLOS["rutas_largas"])
    return Revision("rutas_largas", "Rutas largas de Windows", AVISO,
                    f"LongPathsEnabled=0; hoy cabe -- {cuenta} -- pero mover el clon "
                    f"{LIMITE_DE_DIRECTORIO - hondura} caracteres mas hondo lo rompe")


def revisar_entorno_raiz() -> Revision:
    """El `.venv` de la raiz: el que corre el cuaderno 05 y el que construye los paneles
    que suben a Databricks.

    Se comprueba IMPORTANDO y no leyendo metadatos, y esa eleccion es la que cazo el
    caso real: `torch` instalado, con su `dist-info` entero, y aun asi incapaz de
    cargar por una DLL del sistema. Ningun recuento de paquetes lo habria visto.
    """
    py = RAIZ / ".venv" / ("Scripts" if ES_WINDOWS else "bin") / \
        ("python.exe" if ES_WINDOWS else "python")
    arreglo = ARREGLOS["entorno_raiz"]
    if not py.exists():
        return Revision("entorno_raiz", "Entorno de la raiz (.venv)", FALTA,
                        "no existe; sin el no corre el cuaderno 05 ni se construyen los "
                        "paneles que suben a Databricks", arreglo)
    codigo, _, error = _corre([str(py), "-c", "import torch, sklearn, pandas, plotly"], 90.0)
    if codigo != 0:
        return Revision("entorno_raiz", "Entorno de la raiz (.venv)", FALTA,
                        "existe pero no importa torch, scikit-learn, pandas y plotly -- "
                        + _causa(error), arreglo)
    return Revision("entorno_raiz", "Entorno de la raiz (.venv)", LISTO,
                    f"{py} con torch, scikit-learn, pandas y plotly")


def revisar_entornos_apps() -> Revision:
    """Que el entorno EXISTA no es que sirva, y confundirlo salio caro.

    Esta revision preguntaba solo `_entorno.existe()`, que mira si hay un `python` bajo
    `.venv`. Una instalacion que aborta a mitad -- por `MAX_PATH`, por red, por disco --
    deja exactamente eso: el entorno creado y la mitad de los paquetes fuera. El
    diagnostico decia "los 6" y daba el destino `aplicaciones` por LISTO con el
    simulador sin `voila`, que es su servidor: no habria abierto. Un verde falso es peor
    que un rojo, porque nadie vuelve a mirar.
    """
    sin_crear, a_medias = [], []
    for app in APPS:
        carpeta = RAIZ / "aplicaciones" / app
        if not _entorno.existe(carpeta):
            sin_crear.append(app)
            continue
        pedidas = carpeta / "requirements.txt"
        if not pedidas.exists():
            continue
        codigo, salida, _ = _corre(
            [str(_entorno.python_del_venv(carpeta)), "-c", GUION_DE_DISTRIBUCIONES,
             str(pedidas)], 60.0)
        if codigo != 0:
            a_medias.append(f"{app} (no se dejo comprobar)")
            continue
        nombres = salida.split()
        if nombres:
            cola = f" y {len(nombres) - 3} mas" if len(nombres) > 3 else ""
            a_medias.append(f"{app} (sin {', '.join(nombres[:3])}{cola})")
    if sin_crear or a_medias:
        partes = []
        if sin_crear:
            partes.append(f"sin crear {len(sin_crear)} de {len(APPS)}: "
                          + ", ".join(sin_crear))
        if a_medias:
            partes.append("a medio instalar: " + "; ".join(a_medias))
        return Revision("entornos_apps", "Entornos de las aplicaciones", FALTA,
                        " -- ".join(partes), ARREGLOS["entornos_apps"])
    return Revision("entornos_apps", "Entornos de las aplicaciones", LISTO,
                    f"los {len(APPS)}, con lo que pide el requirements.txt de cada una")


def revisar_puertos() -> Revision:
    """Libre, tomado o BLOQUEADO. Los tres son distintos y el tercero es el que costo
    una sesion en Windows: la aplicacion arranca en un puerto al azar, viva e invisible
    para el menu."""
    estados = {n: _servidor.estado_del_puerto(p) for n, p in PUERTOS.items()}
    bloqueados = [f"{n} ({PUERTOS[n]})" for n, e in estados.items()
                  if e == _servidor.BLOQUEADO]
    tomados = [f"{n} ({PUERTOS[n]})" for n, e in estados.items()
               if e == _servidor.TOMADO]
    if bloqueados:
        rangos = _servidor.rango_reservado(PUERTOS[bloqueados[0].split(" (")[0]])
        return Revision("puertos", "Puertos de los tableros", FALTA,
                        f"bloqueados por el sistema: {', '.join(bloqueados)}"
                        + (f"; rango reservado {rangos[0]}-{rangos[1]}" if rangos else ""),
                        ARREGLOS["puertos"])
    if tomados:
        return Revision("puertos", "Puertos de los tableros", AVISO,
                        f"ocupados ahora mismo: {', '.join(tomados)} -- si es este "
                        "proyecto, ya esta abierto; si no, hay que liberarlos")
    return Revision("puertos", "Puertos de los tableros", LISTO,
                    f"los {len(PUERTOS)} libres ({min(PUERTOS.values())}-"
                    f"{max(PUERTOS.values())})")


def revisar_databricks_cli() -> Revision:
    arreglo = ARREGLOS["databricks_cli"]
    if shutil.which("databricks") is None:
        return Revision("databricks_cli", "CLI de Databricks", FALTA,
                        "no esta instalada", arreglo)
    codigo, version, error = _corre(["databricks", "--version"])
    if codigo != 0:
        return Revision("databricks_cli", "CLI de Databricks", FALTA,
                        f"esta pero no responde: {(version + error).strip()[:120]}", arreglo)
    # La etapa 4 crea apps con `--compute-size`, y una CLI vieja no tiene esa bandera.
    # Sin esto la corrida llega hasta ahi y muere con un error de argumentos.
    # La ayuda de la CLI sale por stdout en unas versiones y por stderr en otras,
    # asi que aqui SI se miran las dos -- pero para buscar una cadena, no para
    # parsear: es lo que D7 prohibe y esto no lo hace.
    _, ayuda, ayuda_err = _corre(["databricks", "apps", "create", "--help"])
    if "--compute-size" not in (ayuda + ayuda_err):
        return Revision("databricks_cli", "CLI de Databricks", FALTA,
                        f"{version.strip()} -- demasiado vieja: `apps create` no acepta "
                        "`--compute-size`, que es lo que la etapa 4 necesita", arreglo)
    return Revision("databricks_cli", "CLI de Databricks", LISTO,
                    f"{version.strip()}, con `apps create --compute-size`")


def revisar_databricks_perfil() -> Revision:
    """Que haya al menos un perfil. CUAL se usa lo decide `/subir-a-databricks` a partir
    de la URL que pregunta en cada corrida, no este diagnostico."""
    arreglo = ARREGLOS["databricks_perfil"]
    if shutil.which("databricks") is None:
        return Revision("databricks_perfil", "Perfil de Databricks", FALTA,
                        "sin CLI no hay perfil que mirar", arreglo)
    codigo, salida, _ = _corre(["databricks", "auth", "profiles", "-o", "json"])
    if codigo != 0:
        return Revision("databricks_perfil", "Perfil de Databricks", FALTA,
                        "no se pudieron listar los perfiles", arreglo)
    try:
        perfiles = json.loads(salida).get("profiles") or []
    except (ValueError, AttributeError):
        perfiles = []
    if not perfiles:
        return Revision("databricks_perfil", "Perfil de Databricks", FALTA,
                        "no hay ninguno configurado", arreglo)
    validos = [p.get("name") for p in perfiles if p.get("valid")]
    if not validos:
        return Revision("databricks_perfil", "Perfil de Databricks", FALTA,
                        f"hay {len(perfiles)} pero ninguno valido (token vencido): "
                        + ", ".join(str(p.get("name")) for p in perfiles), arreglo)
    return Revision("databricks_perfil", "Perfil de Databricks", LISTO,
                    f"{len(validos)} valido(s): " + ", ".join(validos))


REVISIONES = (
    revisar_sistema, revisar_memoria, revisar_disco, revisar_python,
    revisar_git, revisar_git_lfs, revisar_datos, revisar_datos_lfs, revisar_red,
    revisar_runtime_vc, revisar_rutas_largas,
    revisar_entorno_raiz, revisar_entornos_apps, revisar_puertos,
    revisar_databricks_cli, revisar_databricks_perfil,
)


def revisar() -> list[Revision]:
    return [hacer() for hacer in REVISIONES]


def veredictos(revisiones: list[Revision]) -> dict:
    """Un veredicto por destino, con lo que le falta a cada uno.

    Se responde por separado a proposito: una maquina puede estar perfecta para abrir
    los tableros y no tener la CLI de Databricks, y decir "no esta lista" a secas
    mandaria a instalar cosas que no hacen falta para lo que se quiere hacer.
    """
    por_clave = {r.clave: r for r in revisiones}
    salida = {}
    for meta, claves in METAS.items():
        faltan = [por_clave[c] for c in claves if por_clave[c].estado == FALTA]
        avisos = [por_clave[c] for c in claves if por_clave[c].estado == AVISO]
        salida[meta] = {
            "titulo": TITULOS_META[meta],
            "listo": not faltan,
            "falta": [{"clave": r.clave, "titulo": r.titulo, "detalle": r.detalle,
                       "arreglo": r.mio} for r in faltan],
            "avisos": [{"clave": r.clave, "detalle": r.detalle} for r in avisos],
        }
    return salida


def informe(revisiones: list[Revision], juicios: dict) -> str:
    marca = {LISTO: "OK   ", FALTA: "FALTA", AVISO: "AVISO"}
    lineas = [f"Diagnostico local -- {SISTEMA} -- {RAIZ}", ""]
    for r in revisiones:
        lineas.append(f"  [{marca[r.estado]}] {r.titulo:34s} {r.detalle}")
        if r.estado == FALTA and r.mio:
            lineas.append(f"           -> {r.mio}")
    lineas.append("")
    for meta, juicio in juicios.items():
        estado = "LISTO" if juicio["listo"] else "NO"
        lineas.append(f"  {estado:5s}  {meta:13s} {juicio['titulo']}")
        for f in juicio["falta"]:
            lineas.append(f"           falta: {f['titulo']} -- {f['detalle']}")
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--json", action="store_true",
                            help="emite el diagnostico como JSON en vez del informe")
    args = analizador.parse_args(argv)

    revisiones = revisar()
    juicios = veredictos(revisiones)
    if args.json:
        print(json.dumps({"sistema": SISTEMA, "raiz": str(RAIZ),
                          "revisiones": [asdict(r) for r in revisiones],
                          "destinos": juicios}, indent=1, ensure_ascii=False))
    else:
        print(informe(revisiones, juicios))
    return 0 if all(j["listo"] for j in juicios.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
