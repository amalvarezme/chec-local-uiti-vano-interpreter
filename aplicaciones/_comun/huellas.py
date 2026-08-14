"""La huella de los insumos de una aplicacion, y si hay que reconstruir por ellos.

Una aplicacion que CONGELA resultados -- hoy el simulador del cuaderno 06 -- tiene un
modo de fallo propio: los objetos del paquete salen de unos insumos, y el resto del
cuaderno los consume suponiendo su forma. Un insumo editado con un paquete viejo hace
que el tablero dibuje datos que ya no corresponden **sin dar ningun error**. Ya paso:
al ajustar `data/Variables_simular.xlsx` la aplicacion siguio ofreciendo el catalogo
anterior, porque el manifiesto solo guardaba el sha1 del cuaderno.

Aqui se calcula la huella de cada insumo al construir, y se compara al arrancar.

**Dos formas de huella, y la diferencia es deliberada.** Por CONTENIDO (sha1) para lo
pequenio: el cuaderno y los cuatro archivos que viajan dentro del paquete suman ~1 MB
y su sha1 cuesta microsegundos, y ademas un `git checkout` mueve la fecha de todos los
archivos sin cambiar ninguno -- con marcas de tiempo eso reconstruiria el paquete
entero sin motivo. Por MARCA (bytes + mtime) para lo pesado: el CSV, el artefacto de
bolsas y los shapefiles suman 909 MB, y hashearlos en cada arranque costaria segundos
contra los 0,3 s que tarda el paquete en cargar. Una marca falla del lado seguro --
puede provocar una reconstruccion de mas, nunca una de menos.

Solo biblioteca estandar: esto lo lee el arranque de la aplicacion, que corre antes
de que exista ningun entorno virtual.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, Mapping

# Bloque de lectura del sha1. 1 MiB es el punto en que el coste deja de ser el numero
# de llamadas y pasa a ser el disco; por debajo se pagan miles de llamadas de mas.
_BLOQUE = 1024 * 1024


def huella_de_archivo(ruta: Path, *, por_contenido: bool) -> dict[str, Any]:
    """La huella de UN insumo, o `{'falta': True}` si no esta.

    Un insumo ausente no lanza: es justo el caso en que hay que reconstruir, y quien
    construya tiene su propia verificacion de insumos, que ademas explica que cuaderno
    produce cada uno. Lanzar aqui cambiaria ese mensaje util por una traza.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        return {"falta": True}
    info = ruta.stat()
    if not por_contenido:
        return {"bytes": info.st_size, "mtime_ns": info.st_mtime_ns}
    resumen = hashlib.sha1()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(_BLOQUE), b""):
            resumen.update(bloque)
    return {"bytes": info.st_size, "sha1": resumen.hexdigest()}


def huella_de_arbol(raiz: Path, *, patron: str = "*.py") -> dict[str, Any]:
    """La huella de un ARBOL de codigo entero, en una sola entrada.

    Existe por el punto ciego mas ancho que tenian las cinco aplicaciones. Todas
    congelan el resultado de un cuaderno, y ese cuaderno importa
    `chec_local_interpreter` y `chec_impacto`: 67 archivos bajo `src/`, de los que no se
    vigilaba ni uno. Cambiar `clases_para`, las capas del mapa o la construccion de
    ventanas no movia ninguna huella, asi que la aplicacion seguia sirviendo el panel
    anterior **sin dar ningun error**. Es el mismo fallo que ya obligo a vigilar
    `empaquetar.py` y `preparar.py`, un nivel mas abajo.

    Una sola huella y no una por archivo, por dos razones:

    1. Las huellas se indexan por NOMBRE de archivo, y los dos paquetes tienen su
       propio `__init__.py`. Sueltas, el segundo pisaria al primero en silencio y la
       mitad del arbol dejaria de vigilarse.
    2. Un manifiesto con 67 entradas mas es ilegible justo cuando hace falta leerlo,
       que es cuando alguien pregunta por que se reconstruyo.

    Por CONTENIDO y no por marca: son 1,3 MB y su sha1 cuesta 1,4 ms medidos -- nada
    frente a los 0,06 s que tarda un visor en servirse --, y un `git checkout` mueve la
    fecha de los 67 sin cambiar ninguno. La ruta relativa entra en el resumen junto al
    contenido, asi que mover un modulo de sitio tambien cuenta como cambio.

    `patron` deja fuera lo que no es codigo: `__pycache__` se regenera solo y cambiaria
    en cuanto alguien importe algo, reconstruyendo las cinco aplicaciones sin motivo.
    """
    raiz = Path(raiz)
    if not raiz.exists():
        return {"falta": True}
    resumen = hashlib.sha1()
    archivos = 0
    total = 0
    # Ordenado por ruta relativa: sin orden fijo el recorrido del disco cambia el sha1
    # entre maquinas, y cada arranque reconstruiria.
    for ruta in sorted(raiz.rglob(patron), key=lambda r: r.relative_to(raiz).as_posix()):
        if not ruta.is_file() or "__pycache__" in ruta.parts:
            continue
        datos = ruta.read_bytes()
        resumen.update(ruta.relative_to(raiz).as_posix().encode("utf-8"))
        resumen.update(b"\0")
        resumen.update(hashlib.sha1(datos).digest())
        archivos += 1
        total += len(datos)
    return {"archivos": archivos, "bytes": total, "sha1": resumen.hexdigest()}


def huellas_de_insumos(
    *,
    por_contenido: Iterable[Path] = (),
    por_marca: Iterable[Path] = (),
    arboles: Iterable[Path] = (),
) -> dict[str, dict[str, Any]]:
    """Las huellas de todos los insumos, indexadas por NOMBRE de archivo.

    Por nombre y no por ruta absoluta: la ruta cambia entre maquinas -- y entre el
    repositorio y el contenedor de la aplicacion -- y compararlas convertiria cada
    cambio de carpeta en una reconstruccion.

    `arboles` son carpetas de codigo que entran como UNA entrada cada una, con el
    nombre de la carpeta y una barra al final para que se lea como lo que es. Ver
    `huella_de_arbol`.
    """
    return {
        **{Path(r).name: huella_de_archivo(r, por_contenido=True) for r in por_contenido},
        **{Path(r).name: huella_de_archivo(r, por_contenido=False) for r in por_marca},
        **{Path(r).name + "/": huella_de_arbol(r) for r in arboles},
    }


def motivo_de_reconstruccion(
    guardadas: Mapping[str, Mapping[str, Any]] | None,
    actuales: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """Por que hay que reconstruir, en una frase, o None si no hace falta.

    El motivo NOMBRA los insumos que se movieron. Un "hay que reconstruir" a secas
    obliga a adivinar cual de los ocho cambio, que es el trabajo que esta comprobacion
    existe para ahorrar.

    `None` -- la clave no esta en el manifiesto -- se reconstruye y se dice que es por
    el FORMATO: es un paquete de la version que solo registraba el cuaderno, y de sus
    demas insumos no se puede afirmar nada. Un diccionario VACIO es otra cosa y no se
    confunde con eso: es un manifiesto que registro cero insumos, asi que cualquiera
    de los actuales es nuevo y se nombra.
    """
    if guardadas is None:
        return ("el paquete lo construyo una version anterior, que no registraba sus "
                "insumos")
    cambiados = sorted(
        nombre for nombre, huella in actuales.items()
        if dict(guardadas.get(nombre, {})) != dict(huella)
    )
    if not cambiados:
        return None
    if len(cambiados) == 1:
        return f"cambio {cambiados[0]} desde la ultima construccion"
    return ("cambiaron " + ", ".join(cambiados) + " desde la ultima construccion")
