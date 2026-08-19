"""Prepara lo que `/subir-a-databricks` sube: los cuatro paneles y la fuente de la app.

## Por que es un script y no una lista de pasos dentro del comando

Las cinco apps de Databricks anteriores se armaban copiando bloques de codigo desde un
`.md` a un directorio temporal. Cada bloque era codigo que ninguna herramienta veia, y
cada copia era una oportunidad de olvidar un archivo. Aqui las dos operaciones que se
pueden equivocar en silencio -- QUE archivos viajan, y QUE se sustituye en ellos -- son
funciones con pruebas.

Lo que sigue siendo del comando es hablar con Databricks: resolver el perfil, crear el
Volume, subir, crear la app, desplegar. Eso necesita un workspace y no se puede probar
aqui.

## Los tres subcomandos

    paneles            construye los cuatro tableros y los deja listos para subir
    fuente             copia la fuente de criticidad-chec, con su Volume ya sustituido
    fuente-simulador   copia la fuente de simulador-vano, con su Volume ya sustituido

Los dos escriben dentro de un directorio de trabajo que se le pasa, y los dos son
idempotentes: volver a correrlos sobre el mismo directorio deja el mismo resultado.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FUENTE_APP = RAIZ / "aplicaciones" / "databricks" / "criticidad_chec"
COMUN = RAIZ / "aplicaciones" / "_comun"

# Lo que viaja al Workspace. Se enumera y no se hace `glob`: un `glob` se lleva el
# `__pycache__`, y el dia que alguien deje un borrador al lado lo publicaria tambien.
#
# `tableros.py` y `paleta.py` NO viven en esa carpeta -- son de `_comun/`, compartidos
# con el menu local -- y por eso se copian al lado. Es la unica forma de que la app
# tenga los mismos titulos y los mismos colores que la aplicacion de escritorio sin
# escribirlos dos veces.
ARCHIVOS_PROPIOS = ("app.py", "catalogo.py", "pagina.py", "app.yaml",
                    "requirements.txt")
ARCHIVOS_COMPARTIDOS = ("tableros.py", "paleta.py")

# La linea de `app.yaml` que apunta al Volume. El catalogo y el esquema se resuelven en
# cada despliegue (contrato C), asi que el valor del repositorio es un DEFECTO y esto
# lo sustituye por el resuelto.
MARCA_VOLUMEN = '/Volumes/workspace/default/chec-simulador/paneles'

# La SEGUNDA app: el simulador. Sus tres archivos vivieron dentro de
# `/app-simulador-vano.md` como bloques de codigo, y al fundir los cuatro comandos de
# Databricks en uno se perdieron con el `.md` -- la etapa que los sube sobrevivio, lo
# que los escribia no. Aqui viajan como archivos con pruebas, igual que los de la otra.
FUENTE_SIMULADOR = RAIZ / "aplicaciones" / "databricks" / "simulador"

# Tres, y ninguno compartido: el simulador no muestra titulos ni colores del menu, sirve
# un cuaderno. El `06_simulador.ipynb` y los dos paquetes de `src/` no estan aqui porque
# no son copias -- el cuaderno lo escribe `preparar.escribir_cuaderno(con_cierre=False)`
# y los paquetes viajan con `databricks sync`.
ARCHIVOS_SIMULADOR = ("arranque.py", "app.yaml", "requirements.txt")

MARCA_VOLUMEN_PAQUETE = '/Volumes/workspace/default/chec-simulador/paquete_06'


def _tableros():
    sys.path.insert(0, str(COMUN))
    try:
        import tableros
    finally:
        sys.path.pop(0)
    return tableros.ESTATICOS


# --------------------------------------------------------------------------------
# paneles
# --------------------------------------------------------------------------------
def construir_paneles(destino: Path, *, solo: tuple[str, ...] = ()) -> dict:
    """Construye los cuatro tableros y los deja empaquetados bajo `destino/<clave>/`.

    Usa EXACTAMENTE el mismo camino que la aplicacion de escritorio --
    `chec_tableros.<modulo>.construir()` y despues `empaquetar` --, asi que lo que se
    publica es lo mismo que el usuario ve en local. Un segundo camino de construccion
    seria un segundo tablero que tendria que coincidir para siempre.

    Un tablero que falla NO detiene a los demas: se anota y se sigue. Publicar tres de
    cuatro y decir cual falto es mejor que no publicar nada, y mucho mejor que dejar el
    panel viejo del que fallo -- que es lo unico que no se hace nunca.
    """
    # `src/` se queda en el path, no se saca: hace falta para `empaquetar` Y para el
    # `import_module` de cada tablero, unas lineas mas abajo. Sacarlo antes de tiempo
    # dejaba a los cuatro fallando con `No module named 'chec_tableros'` -- y el
    # informe lo dijo, que es lo que este bucle existe para hacer.
    for ruta in (str(COMUN), str(RAIZ / "src")):
        if ruta not in sys.path:
            sys.path.insert(0, ruta)

    import empaquetar as _empaquetar

    from importlib import import_module

    destino.mkdir(parents=True, exist_ok=True)
    resultado: dict[str, dict] = {}
    for tablero in _tableros():
        if solo and tablero.clave not in solo:
            continue
        carpeta = destino / tablero.clave
        try:
            html = import_module(tablero.modulo).construir(raiz=RAIZ, abrir=False)
            # Se borra ANTES de empaquetar y no despues de fallar: si una construccion
            # muere a medias, lo que no puede quedar es una mezcla de piezas viejas y
            # nuevas, que es un panel que carga y miente.
            shutil.rmtree(carpeta, ignore_errors=True)
            paquete = _empaquetar.empaquetar(html.read_text("utf-8"), carpeta,
                                             titulo=tablero.titulo)
            resultado[tablero.clave] = {
                "estado": "ok",
                "bytes": paquete.total_gzip,
                "piezas": [p.nombre for p in paquete.piezas],
            }
        except Exception as exc:  # noqa: BLE001 -- el motivo va al informe
            shutil.rmtree(carpeta, ignore_errors=True)
            resultado[tablero.clave] = {"estado": "fallo", "motivo": str(exc)[:300]}
    return resultado


# --------------------------------------------------------------------------------
# fuente
# --------------------------------------------------------------------------------
def preparar_fuente(destino: Path, *, raiz_paneles: str) -> list[str]:
    """Copia la fuente de la app y le sustituye la ruta del Volume.

    Devuelve los nombres copiados, en orden. Falla si un archivo no esta: es preferible
    a subir una app sin su `catalogo.py` y descubrirlo cuando el contenedor no arranca.
    """
    destino.mkdir(parents=True, exist_ok=True)
    copiados = []
    for nombre in ARCHIVOS_PROPIOS:
        origen = FUENTE_APP / nombre
        if not origen.is_file():
            raise SystemExit(f"Falta {origen}: la app no se puede subir incompleta.")
        shutil.copy2(origen, destino / nombre)
        copiados.append(nombre)
    for nombre in ARCHIVOS_COMPARTIDOS:
        origen = COMUN / nombre
        if not origen.is_file():
            raise SystemExit(f"Falta {origen}.")
        shutil.copy2(origen, destino / nombre)
        copiados.append(nombre)

    yaml = destino / "app.yaml"
    texto = yaml.read_text("utf-8")
    if texto.count(MARCA_VOLUMEN) != 1:
        raise SystemExit(
            f"`app.yaml` deberia nombrar {MARCA_VOLUMEN!r} exactamente una vez y lo "
            f"nombra {texto.count(MARCA_VOLUMEN)}. La sustitucion de la ruta del "
            "Volume no puede quedar a medias: la app arrancaria apuntando al Volume "
            "de otro workspace."
        )
    yaml.write_text(texto.replace(MARCA_VOLUMEN, raiz_paneles, 1), encoding="utf-8")
    return copiados


def preparar_fuente_simulador(destino: Path, *, volumen_paquete: str) -> list[str]:
    """Copia la fuente de `simulador-vano` y le sustituye la ruta del Volume.

    Misma forma que `preparar_fuente`, y a proposito: las dos apps se suben con la misma
    secuencia de `workspace import`, asi que lo que cambia entre ellas es la lista de
    archivos y cual es la marca a sustituir.

    Lo que se sustituye aqui es `VOLUME_06`, la carpeta del Volume con el paquete
    precalculado. `PAQUETE_06` no se toca: es una ruta DENTRO del contenedor.
    """
    destino.mkdir(parents=True, exist_ok=True)
    copiados = []
    for nombre in ARCHIVOS_SIMULADOR:
        origen = FUENTE_SIMULADOR / nombre
        if not origen.is_file():
            raise SystemExit(f"Falta {origen}: la app no se puede subir incompleta.")
        shutil.copy2(origen, destino / nombre)
        copiados.append(nombre)

    yaml = destino / "app.yaml"
    texto = yaml.read_text("utf-8")
    if texto.count(MARCA_VOLUMEN_PAQUETE) != 1:
        raise SystemExit(
            f"`app.yaml` deberia nombrar {MARCA_VOLUMEN_PAQUETE!r} exactamente una vez "
            f"y lo nombra {texto.count(MARCA_VOLUMEN_PAQUETE)}. Sin la sustitucion, la "
            "app arranca buscando su paquete en el Volume de otro workspace y el "
            "sintoma -- 'no encuentra el paquete' -- no apunta hasta aqui."
        )
    yaml.write_text(texto.replace(MARCA_VOLUMEN_PAQUETE, volumen_paquete, 1),
                    encoding="utf-8")
    return copiados


# --------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    sub = analizador.add_subparsers(dest="orden", required=True)

    p = sub.add_parser("paneles", help="construye los cuatro tableros")
    p.add_argument("--destino", required=True, type=Path)
    p.add_argument("--solo", default="",
                   help="claves separadas por coma; por defecto los cuatro")

    f = sub.add_parser("fuente", help="prepara la fuente de criticidad-chec")
    f.add_argument("--destino", required=True, type=Path)
    f.add_argument("--raiz-paneles", required=True,
                   help="ruta del Volume ya resuelta, sin barra final")

    s = sub.add_parser("fuente-simulador", help="prepara la fuente de simulador-vano")
    s.add_argument("--destino", required=True, type=Path)
    s.add_argument("--volumen-paquete", required=True,
                   help="carpeta del Volume con el paquete, ya resuelta, sin barra final")

    args = analizador.parse_args(argv)
    if args.orden == "paneles":
        solo = tuple(c.strip() for c in args.solo.split(",") if c.strip())
        informe = construir_paneles(args.destino, solo=solo)
        print(json.dumps(informe, indent=1, ensure_ascii=False))
        return 0 if all(v["estado"] == "ok" for v in informe.values()) else 1

    if args.orden == "fuente-simulador":
        copiados = preparar_fuente_simulador(
            args.destino, volumen_paquete=args.volumen_paquete.rstrip("/"))
        print(json.dumps({"copiados": copiados}, indent=1))
        return 0

    copiados = preparar_fuente(args.destino, raiz_paneles=args.raiz_paneles.rstrip("/"))
    print(json.dumps({"copiados": copiados}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
