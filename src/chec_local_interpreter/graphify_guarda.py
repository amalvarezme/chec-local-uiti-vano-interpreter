"""Decide si `/graphify --update` puede correr sin podar el grafo.

## El defecto que existe para evitar, medido

El paso 9 de `/report` encadenaba `/graphify` sobre `reports/vault`. El manifiesto de
`graphify-out/` describe el PROYECTO ENTERO -- 426 claves, todas relativas a la raiz:
`astro.config.mjs`, `data/models/...`, `src/...` -- y CERO de ellas cuelgan de
`reports/vault`. Al reanclar esas claves contra la raiz mas estrecha, todas resuelven a
rutas que nunca existieron, y la deteccion incremental las reporta como BORRADAS.
Continuar habria podado 426 archivos de un grafo de 6.479 nodos.

    detect_incremental('reports/vault')  ->    1 nuevo,  426 borrados,  0 existen
    detect_incremental('.')              ->  152 nuevos,  16 borrados,  0 existen

## Por que la guarda anterior no servia

Decia: "si algun borrado reportado no existe en disco, aborta". **Un borrado genuino
tampoco existe en disco** -- esa es la definicion de borrado. Con esa regla, los 16
borrados reales que se ven desde la raiz -- pruebas y comandos retirados de verdad --
tambien abortaban, y el grafo no podia enterarse nunca de que algo se habia ido. La
guarda protegia el grafo al precio de congelarlo.

## Lo que si distingue

No si el archivo existe, sino si el manifiesto esta ANCLADO en la misma raiz que se
esta escaneando. Se mide la fraccion de claves del manifiesto que resuelven bajo la
raiz de escaneo: sana ronda 1, desanclada es 0. Un proyecto que retira decenas de
archivos sigue resolviendo la inmensa mayoria; uno mal anclado no resuelve ninguna.

Devuelve un DATO y no lanza: el runbook decide con el, y una excepcion aqui tumbaria un
informe que ya esta completo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: Por debajo de esta fraccion de claves resueltas, el manifiesto no describe lo que se
#: esta escaneando. 0,5 y no 0,9: un proyecto puede retirar mucho de golpe -- la limpieza
#: de comandos de agosto se llevo nueve de una vez -- y eso no es un desanclaje. Lo que
#: delata el desanclaje es resolver CASI NINGUNA, no que falten muchas.
ANCLAJE_MINIMO = 0.5

NOMBRE_MANIFIESTO = "manifest.json"
DIR_SALIDA = "graphify-out"


@dataclass(frozen=True)
class Veredicto:
    """Si se puede seguir, con el numero que lo sostiene."""

    seguir: bool
    resuelven: int
    total: int
    motivo: str

    @property
    def fraccion(self) -> float:
        return (self.resuelven / self.total) if self.total else 1.0

    def linea(self) -> str:
        """Una linea para la consola del runbook: el numero y la decision."""
        return (f"claves del manifiesto que resuelven bajo la raiz de escaneo: "
                f"{self.resuelven}/{self.total} ({100 * self.fraccion:.0f}%) -> "
                f"{'SEGUIR' if self.seguir else 'ABORTAR'} · {self.motivo}")


def revisar_anclaje(*, raiz_escaneo: Path, raiz_manifiesto: Path) -> Veredicto:
    """Comprueba que el manifiesto describa lo que `raiz_escaneo` contiene.

    `raiz_manifiesto` es donde vive `graphify-out/`, que normalmente es la raiz del
    proyecto. `raiz_escaneo` es lo que se le va a pasar a graphify.
    """
    manifiesto = Path(raiz_manifiesto) / DIR_SALIDA / NOMBRE_MANIFIESTO
    if not manifiesto.is_file():
        return Veredicto(True, 0, 0,
                         "no hay manifiesto todavia: nada que podar en la primera corrida")

    try:
        datos = json.loads(manifiesto.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        # Sin poder leerlo no se puede AFIRMAR que el anclaje sea correcto, y el precio
        # de equivocarse es podar el grafo.
        return Veredicto(False, 0, 0, f"no se pudo leer {manifiesto.name}: {exc}")

    claves = list(datos) if isinstance(datos, dict) else []
    if not claves:
        return Veredicto(True, 0, 0, "el manifiesto esta vacio: nada que podar")

    escaneo = Path(raiz_escaneo).resolve()
    base = Path(raiz_manifiesto).resolve()
    resuelven = 0
    for clave in claves:
        ruta = Path(str(clave))
        absoluta = ruta if ruta.is_absolute() else base / ruta
        try:
            absoluta.resolve().relative_to(escaneo)
        except ValueError:
            continue
        resuelven += 1

    fraccion = resuelven / len(claves)
    if fraccion < ANCLAJE_MINIMO:
        return Veredicto(
            False, resuelven, len(claves),
            "el manifiesto esta anclado en otra raiz: casi ninguna de sus claves cuelga "
            "de la carpeta que se va a escanear, asi que graphify las leeria como "
            "borradas y podaria el grafo",
        )
    return Veredicto(True, resuelven, len(claves),
                     "el manifiesto describe esta raiz")


def main(argv: list[str] | None = None) -> int:
    """`python -m chec_local_interpreter.graphify_guarda [raiz_escaneo]`.

    Sale con 0 si se puede seguir y 1 si hay que abortar, e imprime siempre la linea con
    el numero: el runbook necesita el porque, no solo el codigo.
    """
    import argparse

    from chec_local_interpreter.config import PROJECT_ROOT

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("raiz_escaneo", nargs="?", default=str(PROJECT_ROOT),
                        help="lo que se le va a pasar a graphify (por defecto, la raiz)")
    parser.add_argument("--raiz-manifiesto", default=str(PROJECT_ROOT),
                        help="donde vive graphify-out/ (por defecto, la raiz)")
    args = parser.parse_args(argv)

    veredicto = revisar_anclaje(raiz_escaneo=Path(args.raiz_escaneo),
                                raiz_manifiesto=Path(args.raiz_manifiesto))
    print(veredicto.linea())
    return 0 if veredicto.seguir else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
