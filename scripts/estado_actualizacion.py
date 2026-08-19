"""Que hay que rehacer cuando cambia un archivo base, y en que orden.

## La pregunta que ninguna huella contesta

Cada aplicacion guarda la huella de sus insumos y se reconstruye sola cuando alguno se
mueve (`aplicaciones/DATOS-Y-ACTUALIZACIONES.md`, seccion 2). Esa huella contesta
*"cambio algun insumo?"*. Este guion contesta la otra: *"los artefactos derivados
salieron de ESTAS fuentes?"*. Son distintas, y la segunda es la que falla en silencio.

El caso mas caro es el grafo experto. `src/chec_impacto/data/graph.py` declara las
aristas; `mil_persistencia.guardar_modelo_mil` guarda la adyacencia DENTRO del `.pt` y
`cargar_modelo_mil` la lee de ahi -- no la reconstruye del codigo. Editar el grafo no
cambia absolutamente nada hasta que se reentrena. Mientras tanto las cinco aplicaciones
SI se reconstruyen, porque vigilan `src/` entero como un solo arbol, y sirven un panel
nuevo sobre un modelo del grafo anterior. Nada da error.

## Las cuatro fuentes, y la asimetria entre ellas

Tres deciden como se ENTRENO el modelo y una decide que OFRECE el panel. Confundirlas
cuesta en las dos direcciones: tratar `Variables_simular.xlsx` como las otras manda
reentrenar 8-14 minutos de CPU por editar una celda, y tratar las otras como esa deja
al simulador puntuando con un modelo que no corresponde.

## Donde vive cada huella

El sha del `.pt` NO se guarda aqui. Ya tiene casa -- `data/models/manifest.sha256.json`,
que `tests/test_frozen_model_guard.py` compara -- y una segunda copia seria una segunda
verdad. Sellar escribe en las dos casas, cada dato en la suya.

Uso:

    python3 scripts/estado_actualizacion.py            # informe legible
    python3 scripts/estado_actualizacion.py --json     # el mismo dato, para /actualizar
    python3 scripts/estado_actualizacion.py --sellar   # graba el estado actual

Sale 0 si no hay nada que rehacer, 1 si el plan trae pasos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

RUTA_MANIFIESTO = "data/models/procedencia.json"
RUTA_MANIFIESTO_MODELO = "data/models/manifest.sha256.json"
CLAVE_MODELO = "data/models/mil_vano_ventana_v1.pt"

VERSION_MANIFIESTO = 1

AL_DIA = "al-dia"
REENTRENAR = "reentrenar"
SOLO_PANEL = "solo-panel"
SIN_SELLAR = "sin-sellar"


@dataclass(frozen=True)
class Fuente:
    """Un archivo que se edita a mano o llega de afuera."""

    ruta: str
    que: str
    reentrena: bool
    porque: str


FUENTES = (
    Fuente(
        ruta="data/Indicadores_vano_v3.csv",
        que="la base de eventos",
        reentrena=True,
        porque="es la matriz de la que salen las bolsas vano x ventana y el objetivo "
               "UITI que el modelo ajusta; tambien reajusta la geometria KMeans",
    ),
    Fuente(
        ruta="data/Variables_seleccion.xlsx",
        que="el diccionario de variables que entran al modelo",
        reentrena=True,
        porque="`procesar_dataset_completo` lo lee para decidir que columnas componen "
               "la matriz de features, o sea la forma misma del espacio aprendido",
    ),
    Fuente(
        ruta="src/chec_impacto/data/graph.py",
        que="el grafo experto base",
        reentrena=True,
        porque="la adyacencia se congela dentro del `.pt` al guardar y se lee de ahi al "
               "cargar; editar las aristas no cambia nada hasta que se reentrena",
    ),
    Fuente(
        ruta="data/Variables_simular.xlsx",
        que="el catalogo de variables simulables",
        reentrena=False,
        porque="solo decide que ofrece el panel -- rango, unidad, valores posibles y si "
               "el control es deslizador o selector --, nunca como se entreno el modelo",
    ),
)


@dataclass(frozen=True)
class Derivado:
    """Un archivo que produce otro paso, y que por eso puede quedar viejo."""

    ruta: str
    que: str
    produce: str
    paso: str


DERIVADOS = (
    Derivado(
        ruta="data/derived/bolsas_mil_full.joblib",
        que="las bolsas vano x ventana",
        produce='notebooks/05_mil_vano_ventana.ipynb con EJECUCION="entrenamiento"',
        paso="reentrenar",
    ),
    Derivado(
        ruta="data/geometria_kmeans_014_v1.json",
        que="la geometria KMeans congelada",
        produce="python scripts/exportar_geometria.py",
        paso="geometria",
    ),
)

#: El modelo va aparte porque su huella vive en el manifiesto del modelo congelado y no
#: en este. Se comprueba igual que los otros dos; solo cambia de donde se lee lo grabado.
MODELO = Derivado(
    ruta=CLAVE_MODELO,
    que="el modelo MIL entrenado",
    produce='notebooks/05_mil_vano_ventana.ipynb con EJECUCION="entrenamiento"',
    paso="reentrenar",
)


@dataclass(frozen=True)
class Paso:
    clave: str
    titulo: str
    orden: str
    porque: str


#: El orden NO es alfabetico ni casual. `catalogo` va antes de `sellar` porque valida
#: contra el modelo que acaba de salir: sellar un estado que el catalogo rechaza dejaria
#: escrito que todo cuadra justo cuando no cuadra.
ORDEN_PLAN = ("reentrenar", "geometria", "catalogo", "sellar", "aplicaciones", "databricks")

PASOS = {
    "reentrenar": Paso(
        clave="reentrenar",
        titulo="Reentrenar el modelo MIL",
        orden='notebooks/05_mil_vano_ventana.ipynb con EJECUCION="entrenamiento" y mode="full"',
        porque="escribe las bolsas y el `.pt`; entre 8 y 14 minutos en CPU, que le gana "
               "a MPS por 6x, y no se puede hacer desde un job de Databricks",
    ),
    "geometria": Paso(
        clave="geometria",
        titulo="Rehacer la geometria KMeans",
        orden="python scripts/exportar_geometria.py",
        porque="reajusta los centroides sobre el CSV nuevo; el simulador falla al "
               "arrancar si la geometria no corresponde a la del modelo",
    ),
    "catalogo": Paso(
        clave="catalogo",
        titulo="Revisar que ofrecera el panel",
        orden="python3 scripts/catalogo_simulacion.py",
        porque="dice que control le toca a cada variable -- deslizador, deslizador de "
               "enteros o selector --, con que rango, y que opciones el modelo no sabe codificar",
    ),
    "sellar": Paso(
        clave="sellar",
        titulo="Sellar el estado",
        orden="python3 scripts/estado_actualizacion.py --sellar",
        porque="graba las fuentes y los derivados, y reescribe el manifiesto del modelo "
               "congelado, que si no deja su guarda en rojo sin decir por que",
    ),
    "aplicaciones": Paso(
        clave="aplicaciones",
        titulo="Reconstruir las aplicaciones locales",
        orden="cd aplicaciones/06_simulador && python3 ../_comun/gestor.py iniciar --reconstruir",
        porque="las cinco se reconstruyen solas al abrirlas, pero forzarlo aqui deja el "
               "fallo a la vista ahora y no delante de quien las abra manana",
    ),
    "databricks": Paso(
        clave="databricks",
        titulo="Subir lo nuevo a Databricks",
        orden="/subir-a-databricks",
        porque="el Volume y las apps siguen sirviendo los artefactos anteriores hasta "
               "que se suban; nada en Databricks se entera solo",
    ),
}


@dataclass
class Estado:
    veredicto: str
    fuentes_movidas: list[str]
    derivados_movidos: list[str]
    faltantes: list[str]
    plan: list[Paso]

    def como_dict(self) -> dict:
        return {
            "veredicto": self.veredicto,
            "fuentes_movidas": self.fuentes_movidas,
            "derivados_movidos": self.derivados_movidos,
            "faltantes": self.faltantes,
            "plan": [
                {"clave": p.clave, "titulo": p.titulo, "orden": p.orden, "porque": p.porque}
                for p in self.plan
            ],
        }


# ------------------------------------------------------------------------- huellas

def huella(ruta: Path) -> str | None:
    """El sha256 del archivo, o `None` si no esta.

    Por CONTENIDO y no por (bytes, fecha) como hacen las aplicaciones: un `git lfs pull`
    o un `git checkout` reescriben la fecha de archivos identicos, y aqui una falsa
    alarma no cuesta 3 s de reconstruccion -- cuesta mandar reentrenar 14 minutos.
    Medido: 1,1 s el CSV de 566 MB en frio, y 0,3 s las cuatro fuentes y los tres
    derivados juntos -- 765 MB -- con el cache de paginas caliente.
    """
    if not ruta.is_file():
        return None
    digest = hashlib.sha256()
    with ruta.open("rb") as flujo:
        for bloque in iter(lambda: flujo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _leer_json(ruta: Path) -> dict:
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return contenido if isinstance(contenido, dict) else {}


def leer_manifiesto(raiz: Path = RAIZ) -> dict:
    return _leer_json(raiz / RUTA_MANIFIESTO)


def huella_registrada_del_modelo(raiz: Path = RAIZ) -> str | None:
    return _leer_json(raiz / RUTA_MANIFIESTO_MODELO).get(CLAVE_MODELO)


# ------------------------------------------------------------------------- el estado

def estado(raiz: Path = RAIZ) -> Estado:
    manifiesto = leer_manifiesto(raiz)
    if not manifiesto:
        return Estado(SIN_SELLAR, [], [], [], [PASOS["sellar"]])

    grabadas = manifiesto.get("fuentes", {})
    grabados = dict(manifiesto.get("derivados", {}))
    grabados[MODELO.ruta] = huella_registrada_del_modelo(raiz)

    fuentes_movidas, faltantes = [], []
    for fuente in FUENTES:
        actual = huella(raiz / fuente.ruta)
        if actual is None:
            faltantes.append(fuente.ruta)
        elif actual != grabadas.get(fuente.ruta):
            fuentes_movidas.append(fuente.ruta)

    derivados_movidos, derivados_faltantes = [], []
    for derivado in (*DERIVADOS, MODELO):
        actual = huella(raiz / derivado.ruta)
        if actual is None:
            derivados_faltantes.append(derivado)
        elif actual != grabados.get(derivado.ruta):
            derivados_movidos.append(derivado.ruta)

    faltantes += [d.ruta for d in derivados_faltantes]

    movidas = set(fuentes_movidas)
    reentrena = any(f.reentrena and f.ruta in movidas for f in FUENTES)
    reentrena = reentrena or any(d.paso == "reentrenar" for d in derivados_faltantes)

    claves: set[str] = set()
    if reentrena:
        claves.add("reentrenar")
    if "data/Indicadores_vano_v3.csv" in movidas or any(
            d.paso == "geometria" for d in derivados_faltantes):
        claves.add("geometria")
    if claves or fuentes_movidas or derivados_movidos:
        claves |= {"catalogo", "sellar", "aplicaciones", "databricks"}

    if reentrena:
        veredicto = REENTRENAR
    elif movidas:
        veredicto = SOLO_PANEL
    elif claves:
        veredicto = SIN_SELLAR
    else:
        veredicto = AL_DIA

    plan = [PASOS[c] for c in ORDEN_PLAN if c in claves]
    return Estado(veredicto, fuentes_movidas, derivados_movidos, faltantes, plan)


def sellar(raiz: Path = RAIZ) -> dict:
    """Graba el estado actual en sus dos casas y devuelve lo escrito."""
    manifiesto = {
        "version": VERSION_MANIFIESTO,
        "fuentes": {f.ruta: huella(raiz / f.ruta) for f in FUENTES},
        "derivados": {d.ruta: huella(raiz / d.ruta) for d in DERIVADOS},
    }
    destino = raiz / RUTA_MANIFIESTO
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    del_modelo = raiz / RUTA_MANIFIESTO_MODELO
    grabado = _leer_json(del_modelo)
    grabado[CLAVE_MODELO] = huella(raiz / CLAVE_MODELO)
    del_modelo.parent.mkdir(parents=True, exist_ok=True)
    del_modelo.write_text(json.dumps(grabado, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    return manifiesto


# ------------------------------------------------------------------------- el informe

def informe(actual: Estado) -> str:
    titulos = {
        AL_DIA: "Todo al dia: los artefactos derivados salieron de las fuentes que hay.",
        REENTRENAR: "Hay que reentrenar: se movio una fuente que decide como se entreno.",
        SOLO_PANEL: "Solo cambia el panel: no hay que reentrenar nada.",
        SIN_SELLAR: "Los derivados no corresponden a lo sellado; falta dejarlo escrito.",
    }
    lineas = ["", titulos.get(actual.veredicto, actual.veredicto), ""]

    if actual.fuentes_movidas:
        lineas.append("  Fuentes que se movieron")
        for ruta in actual.fuentes_movidas:
            fuente = next(f for f in FUENTES if f.ruta == ruta)
            marca = "reentrena" if fuente.reentrena else "solo panel"
            lineas.append(f"    {ruta}  ({fuente.que} -- {marca})")
            lineas.append(f"      {fuente.porque}.")
        lineas.append("")

    if actual.derivados_movidos:
        lineas.append("  Derivados que ya no son los sellados")
        for ruta in actual.derivados_movidos:
            lineas.append(f"    {ruta}")
        lineas.append("")

    if actual.faltantes:
        lineas.append("  No estan en el disco")
        for ruta in actual.faltantes:
            lineas.append(f"    {ruta}")
        lineas.append("")

    if actual.plan:
        lineas.append("  Que hacer, en este orden")
        for numero, paso in enumerate(actual.plan, start=1):
            lineas.append(f"    {numero}. {paso.titulo}")
            lineas.append(f"       {paso.orden}")
            lineas.append(f"       {paso.porque}.")
        lineas.append("")
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizador.add_argument("--raiz", default=str(RAIZ),
                            help="la raiz del repositorio (por defecto, la de este guion)")
    analizador.add_argument("--json", action="store_true", dest="como_json",
                            help="el mismo dato, para que lo lea /actualizar")
    analizador.add_argument("--sellar", action="store_true",
                            help="graba el estado actual como el bueno")
    args = analizador.parse_args(argv)
    raiz = Path(args.raiz).resolve()

    if args.sellar:
        manifiesto = sellar(raiz)
        if args.como_json:
            print(json.dumps(manifiesto, indent=2, ensure_ascii=False))
        else:
            print(f"\nSellado: {len(manifiesto['fuentes'])} fuentes y "
                  f"{len(manifiesto['derivados']) + 1} derivados.\n")
        return 0

    actual = estado(raiz)
    if args.como_json:
        print(json.dumps(actual.como_dict(), indent=2, ensure_ascii=False))
    else:
        print(informe(actual))
    return 0 if actual.veredicto == AL_DIA else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
