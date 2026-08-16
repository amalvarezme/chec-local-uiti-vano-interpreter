"""De donde se lee la fuente de un tablero mientras dura la migracion.

Los cinco tableros tenian su codigo dentro de un `.ipynb`, y decenas de pruebas lo
leian de ahi. Se estan moviendo a `src/chec_tableros/` de a uno
(`sdd/retire-base-apps-notebooks`, fase 3), asi que durante un tiempo unos viven en
un cuaderno y otros en un modulo.

Que cada prueba resuelva eso por su cuenta es como se termina con tres criterios
distintos y con una que se olvida de actualizar. Aqui hay uno solo, y la tabla de
migrados es la unica linea que hay que tocar cuando un tablero cambia de casa.

Lo que estas pruebas comprueban -- que los cuatro mapas compartan paleta, que el CSS
de dos columnas sea identico, que los violines lleven su unidad -- son invariantes
del TABLERO, no del formato en que se guarda. Por eso se repuntan en vez de borrarse.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CUADERNOS = RAIZ / "notebooks" / "base_apps"
MODULOS = RAIZ / "src" / "chec_tableros"

# Nombre del cuaderno (sin `.ipynb`) -> modulo que ya se lo llevo.
MIGRADOS = {
    "01_uiti_vano_clima": "clima",
    "02_uiti_vano_kmeans": "agrupamiento",
    "03_uiti_vano_trayectorias_circuitos": "trayectorias_circuitos",
    "04_uiti_vano_trayectorias_vano": "trayectorias_vanos",
    # El simulador se partio en dos porque tiene dos ciclos de vida: `derivacion` corre
    # al CONSTRUIR el paquete y `tablero` corre en cada apertura. Lo que las pruebas de
    # abajo miran -- paleta, rejilla de paneles, encuadre, rotulos -- es siempre lo
    # segundo, asi que aqui apunta al tablero. Quien necesite la derivacion la importa
    # como modulo, que para eso salio del cuaderno.
    "06_uiti_vano_explicabilidad_simulador": "simulador/tablero",
}


# Los cuatro que producen un HTML estatico y los sirve `aplicaciones/_comun/
# construccion.py`. El simulador queda fuera y no por antiguedad: es un tablero VIVO
# de ipywidgets que Voila sirve con un kernel detras, asi que su `construir()` recibe
# un `Derivado` y devuelve un widget donde los otros reciben una raiz y devuelven una
# ruta. Meterlos en la misma lista obliga a poner un `if` en cada prueba que la use.
ESTATICOS = {c: m for c, m in MIGRADOS.items() if "/" not in m}
SIMULADOR = "06_uiti_vano_explicabilidad_simulador"


def esta_migrado(nombre: str) -> bool:
    return _clave(nombre) in MIGRADOS


def fuente_de_tablero(nombre: str, *, solo_codigo: bool = False) -> str:
    """El codigo de un tablero, venga de donde venga.

    `nombre` acepta con o sin `.ipynb`, que es como lo nombran las pruebas hoy.
    `solo_codigo` descarta las celdas de texto del cuaderno; en un modulo no hay
    tal distincion, asi que devuelve lo mismo en los dos casos.
    """
    clave = _clave(nombre)
    modulo = MIGRADOS.get(clave)
    if modulo is not None:
        return (MODULOS / f"{modulo}.py").read_text(encoding="utf-8")

    documento = json.loads((CUADERNOS / f"{clave}.ipynb").read_text(encoding="utf-8"))
    return "\n".join(
        "".join(celda["source"])
        for celda in documento["cells"]
        if not solo_codigo or celda["cell_type"] == "code"
    )


def fuente_del_cuaderno(nombre: str) -> str:
    """El texto del `.ipynb`, SIEMPRE, este migrado o no.

    No es lo mismo que `fuente_de_tablero`, y confundirlos cuesta caro. Esa
    contesta *donde vive el codigo del tablero*; esta contesta *que hay dentro del
    archivo de cuaderno*. Los comandos de despliegue parchean el `.ipynb` por
    contenido -- la linea del `%pip install`, el bloque de `sys.path` -- y esas
    marcas siguen viviendo ahi aunque el tablero ya no.
    """
    documento = json.loads(
        (CUADERNOS / f"{_clave(nombre)}.ipynb").read_text(encoding="utf-8"))
    return "\n".join("".join(celda["source"]) for celda in documento["cells"])


def cuerpo_de_funcion(fuente: str, nombre: str) -> str:
    """El codigo de una funcion del tablero, acotado por `ast`.

    Estas pruebas cortaban el texto entre dos marcas -- `fuente.index("def X(")` hasta
    el siguiente `"\\nY = "` --, y esas marcas dependian de que todo estuviera a nivel
    0, que es lo que dejo de ser cierto cuando el tablero paso a ser el cuerpo de
    `construir()`. Peor que fallar: `"\\ndef "` no aparece nunca dentro de una funcion
    anidada, asi que el corte se extendia hasta el final del modulo y un `not in`
    sobre eso ya no puede fallar.

    Devuelve el codigo sin comentarios, porque `ast.unparse` los pierde. Es lo que se
    quiere: la prosa de estos tableros nombra por extenso lo que la prueba busca.
    """
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nombre:
            return ast.unparse(nodo)
    raise AssertionError(f"no se encontro `def {nombre}` en la fuente del tablero")


def _clave(nombre: str) -> str:
    return nombre[:-6] if nombre.endswith(".ipynb") else nombre
