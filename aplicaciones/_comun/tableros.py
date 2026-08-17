"""Que tableros hay, como se llaman y de que modulo salen. Una sola lista.

Estaba escrita dentro de `menu.catalogo()`, mezclada con los puertos y con los
procesos que el menu gobierna. Sale de ahi porque tiene DOS consumidores que no se
parecen en nada:

  * el menu local (`menu.py`), que lanza cada tablero como proceso hijo en su propio
    puerto y vigila si vive;
  * la aplicacion consolidada de Databricks (`aplicaciones/databricks/criticidad_chec`),
    que no lanza nada -- sirve cuatro paneles ya construidos, cada uno bajo su ruta.

Lo unico que comparten es ESTO: que tableros hay, como se titulan y como se explican.
Duplicarlo en los dos sitios era garantizar que el dia que alguien cambie un titulo lo
cambie en uno solo, y que el usuario vea dos nombres para el mismo tablero segun por
donde entre.

Lo que NO vive aqui, a proposito:

  * los puertos, que son del menu local y de nadie mas (`_contrato-apps-locales.md`);
  * las rutas de Databricks, que son de la app consolidada;
  * si el tablero necesita un kernel vivo, que aqui se dice como un dato (`vivo`) y
    cada consumidor interpreta a su manera -- el menu lo arranca con Voila, y la app
    consolidada simplemente no lo incluye.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tablero:
    """Un tablero del proyecto, descrito sin decir donde se sirve.

    `clave` es el identificador estable: nombra la carpeta de la aplicacion local, la
    ruta de la app consolidada y la carpeta del panel dentro del Volume. Que sea uno
    solo es lo que permite que los tres se encuentren sin una tabla de traduccion.
    """

    clave: str
    carpeta: str
    modulo: str
    titulo: str
    descripcion: str
    # Si necesita un interprete de Python EN EJECUCION para responder. Solo el
    # simulador: su boton "Simular" corre el modelo MIL sobre lo que el usuario elija,
    # y no hay respuesta que precomputar. Los otros cuatro se congelan en un HTML.
    vivo: bool = False


TABLEROS: tuple[Tablero, ...] = (
    Tablero(
        "clima", "01_clima", "chec_tableros.clima",
        "Nube por vano y clima",
        "La nube por vano sobre el mapa, con las 6 variables, la serie de doble eje "
        "y los 6 violines.",
    ),
    Tablero(
        "agrupamiento", "02_agrupamiento_vanos", "chec_tableros.agrupamiento",
        "Agrupamiento de vanos",
        "Agrupamiento por UITI acumulado y número de eventos.",
    ),
    Tablero(
        "trayectorias_circuitos", "03_trayectorias_circuitos",
        "chec_tableros.trayectorias_circuitos",
        "Trayectorias de circuitos",
        "Trayectoria y agrupamiento de circuitos con ventana deslizante.",
    ),
    Tablero(
        "trayectorias_vanos", "04_trayectorias_vanos",
        "chec_tableros.trayectorias_vanos",
        "Trayectorias de vanos",
        "Lo mismo un nivel mas abajo: agrupamiento y evolucion por vano.",
    ),
    Tablero(
        "simulador", "06_simulador", "chec_tableros.simulador",
        "Simulador de riesgo por vano",
        "Qué pasaría si: corre el modelo MIL sobre los vanos y valores que elijas. "
        "Es la unica que necesita Python vivo.",
        vivo=True,
    ),
)

POR_CLAVE: dict[str, Tablero] = {t.clave: t for t in TABLEROS}

# Los que se pueden congelar en un HTML y servir como archivos estaticos. Es la lista
# que la app consolidada de Databricks publica, y la razon de que el simulador no este
# no es su tamanio: es que un HTML no puede correr PyTorch.
ESTATICOS: tuple[Tablero, ...] = tuple(t for t in TABLEROS if not t.vivo)
