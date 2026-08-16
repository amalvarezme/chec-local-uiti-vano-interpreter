"""Construccion compartida de los cuatro visores de tablero (01, 02, 03 y 04).

Los cuatro modulos de `src/chec_tableros/` terminan igual: `construir()` escribe un
documento HTML autocontenido en `reports/paneles/` y devuelve su ruta. Lo unico que
cambia entre ellos es el modulo y el titulo, asi que el procedimiento vive aqui una
sola vez.

Se les pasa `abrir=False`: sin eso la construccion abriria el navegador con el
documento de 27,8 MB antes de empaquetarlo, que es justo lo que estas aplicaciones
existen para no hacer. Fue una sustitucion de texto sobre el `.ipynb`
(`ABRIR_EN_NAVEGADOR = True` -> `False`) mientras el codigo vivio ahi; hoy es un
argumento, que es lo mismo dicho donde el lenguaje lo puede comprobar.

## Por que aqui tambien se vigilan los insumos

Un visor CONGELA el resultado en un HTML, igual que el simulador congela
su paquete. Y tenia el mismo modo de fallo sin la misma defensa: su unica condicion
para reconstruir era que faltara `index.html`. Se actualizaba
`Indicadores_vano_v3.csv`, se abria el tablero, y el tablero seguia dibujando los datos
viejos **sin dar ningun error**. Es la forma mas cara de equivocarse, porque las cifras
se ven perfectamente bien.

Asi que al construir se guarda la huella de cada insumo en el manifiesto y al arrancar
se compara. Misma maquinaria que el simulador (`huellas.py`), mismas dos formas de
huella y el mismo criterio: contenido para lo pequenio, marca para lo pesado.

**La lista de insumos es UNA para los cuatro**, aunque el tablero 02 no abra ningun
shapefile. Vigilar de mas cuesta una reconstruccion que no hacia falta -- 3 a 8 s, y
solo el dia que alguien cambie un shapefile, que es casi nunca --; vigilar de menos
cuesta un tablero que miente. La misma asimetria que ya gobierna la eleccion entre sha1
y marca de tiempo, resuelta hacia el mismo lado.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import empaquetar as _empaquetar
import huellas as _huellas
import raiz as _raiz

# Unico punto de insercion para las cuatro aplicaciones: cada `app.py` ya inserta
# `_comun` y su propia carpeta ANTES de `import construccion`, asi que agregarlo aqui
# -- y no en cada `app.py` -- cubre a las cuatro con una sola linea. Sin esto ninguna
# aplicacion podia importar `chec_local_interpreter` ni `chec_impacto`: las notebooks
# 01-04 no importaban ningun modulo del proyecto, asi que el hueco nunca se notaba.
if str(_raiz.RAIZ_SRC) not in sys.path:
    sys.path.insert(0, str(_raiz.RAIZ_SRC))

# Lo que le da forma al tablero sin ser un dato: este archivo y el que empaqueta. Va por
# contenido -- son unos cientos de KB -- y hace falta: un cambio en el empaquetador o en
# el boton de cerrar no mueve ningun archivo de `data/`, asi que sin estas lineas el
# visor seguiria sirviendo el HTML anterior. Ya paso al cambiar el texto de reapertura en
# `empaquetar.py`.
#
# Eran tres. La tercera era `cuaderno.py`, el ejecutor de `.ipynb`, y se fue con el
# ultimo cuaderno el 2026-08-16.
_CODIGO = (
    Path(__file__).resolve(),
    Path(__file__).resolve().parent / "empaquetar.py",
)

# Y el codigo que el TABLERO importa, que es la mayor parte de lo que decide como se ve:
# el agrupamiento, las capas del mapa, la construccion de ventanas. Eran 67 archivos sin
# vigilar, medidos, y es el mismo modo de fallo que las dos lineas de arriba -- se toca
# `clases_para` y el visor sigue sirviendo el HTML anterior sin dar ningun error -- solo
# que mucho mas ancho.
#
# Entra como UNA huella del arbol y no como 67 sueltas: las huellas se indexan por nombre
# de archivo y los dos paquetes tienen su propio `__init__.py`, asi que sueltas se
# pisarian. Cuesta 1,4 ms por arranque contra los 0,06 s que tarda un visor en servirse.
_ARBOLES = (_raiz.RAIZ_REPO / "src",)

# Los datos. Por marca porque el CSV pesa 540 MB y los shapefiles otros 180: su sha1
# costaria segundos en cada apertura, contra los milisegundos que tarda el tablero ya
# construido en servirse.
#
# De cada shapefile se miran el `.shp` y el `.dbf`, por lo mismo que en el simulador: la
# geometria vive en el primero y los atributos del join en el segundo.
_DATOS = (
    _raiz.datos("Indicadores_vano_v3.csv"),
    *(_raiz.datos("GEO", f"{_nombre}.{_ext}")
      for _nombre in ("MVLINSEC", "GDBCHEC_TRANSFOR", "SWITCHES")
      for _ext in ("shp", "dbf")),
)


# Un TABLERO se nombra SIEMPRE por su modulo (`chec_tableros.clima`). Hubo una segunda
# forma -- el nombre de su cuaderno -- mientras quedaba alguno sin migrar; se retiro el
# 2026-08-16, con el ultimo `.ipynb`. Una bifurcacion que ya no se toma es peor que
# ninguna: parece que el otro camino sigue disponible.
def _construir_con_modulo(modulo: str) -> Path:
    from importlib import import_module

    return import_module(modulo).construir(raiz=_raiz.RAIZ_REPO, abrir=False)


def huellas_actuales() -> dict:
    """La huella de cada insumo de los visores, ahora mismo.

    **No recibe el tablero, y eso es una afirmacion y no un descuido**: la respuesta ya
    no depende de cual sea. Su codigo esta bajo `src/`, que entra entero como UN arbol,
    asi que los cuatro comparten exactamente la misma lista. Tocar `clima.py` marca los
    cuatro como desactualizados; es la misma asimetria que gobierna el resto de este
    archivo -- reconstruir de mas cuesta segundos, servir un tablero viejo cuesta cifras
    que se ven perfectamente bien.

    Hasta el 2026-08-16 si recibia el tablero, porque cada uno aportaba la huella de su
    propio `.ipynb`. Quitar esa parte a tiempo importo: pedir la huella de un cuaderno
    ya borrado habria hecho que la aplicacion se reconstruyera en CADA apertura -- 4 a
    8 s, en silencio.
    """
    return _huellas.huellas_de_insumos(
        por_contenido=_CODIGO,
        por_marca=_DATOS,
        arboles=_ARBOLES,
    )


def motivo_de_reconstruccion(destino: Path) -> str | None:
    """Por que hay que reconstruir el visor de `destino`, o None si esta al dia.

    Un tablero sin construir tambien es un motivo, y se dice con esas palabras: es lo
    que ve quien abre la aplicacion por primera vez.
    """
    manifiesto = Path(destino) / "manifiesto.json"
    if not (Path(destino) / "index.html").exists() or not manifiesto.exists():
        return "todavia no esta construido"
    guardadas = json.loads(manifiesto.read_text(encoding="utf-8")).get("insumos")
    return _huellas.motivo_de_reconstruccion(guardadas, huellas_actuales())


def construir_tablero(tablero: str, destino: Path, *, titulo: str) -> None:
    _raiz.verificar_repo()

    csv = _raiz.datos("Indicadores_vano_v3.csv")
    if not csv.exists():
        raise SystemExit(f"Falta {csv}. Es el insumo del tablero; sin el no hay nada.")
    if csv.stat().st_size < 1024 * 1024:
        raise SystemExit(
            f"{csv} pesa {csv.stat().st_size} bytes: es un puntero de Git LFS sin "
            "descargar, no los datos. Corre `git lfs pull` en la raiz del repositorio."
        )

    t0 = time.perf_counter()
    print(f"[1/2] construyendo {tablero}")
    fuente = _construir_con_modulo(tablero)
    print(f"      tablero completo en {time.perf_counter() - t0:.1f} s")

    if not fuente.exists():
        raise SystemExit(f"{tablero} no dejo su tablero en {fuente}.")

    print(f"[2/2] empaquetando {fuente.name} ({fuente.stat().st_size / 1024**2:,.1f} MB)")
    # Las huellas se toman DESPUES de ejecutar el cuaderno, no antes: si alguien toca un
    # insumo mientras el cuaderno corre, lo que se guarda tiene que ser lo que de verdad
    # entro en el tablero. Tomarlas antes registraria un estado que el tablero no vio, y
    # la siguiente apertura lo daria por al dia.
    paquete = _empaquetar.empaquetar(fuente.read_text("utf-8"), destino, titulo=titulo,
                                     insumos=huellas_actuales())
    print()
    print(paquete.resumen())
    print()
    print(f"  Tablero listo en {destino}")
    ahorro = 1 - paquete.total_gzip / fuente.stat().st_size
    print(f"  Primera apertura: {paquete.total_gzip / 1024**2:,.1f} MB transferidos "
          f"({ahorro:.0%} menos que el documento original).")
    inmutable = sum(p.bytes_gzip for p in paquete.piezas if p.nombre != "index.html")
    print(f"  Aperturas siguientes: {(paquete.total_gzip - inmutable) / 1024:,.0f} KB "
          "(el resto queda en el cache del navegador).")
