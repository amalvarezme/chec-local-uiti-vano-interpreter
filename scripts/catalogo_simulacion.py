"""Que ofrecera el panel del simulador despues de editar `Variables_simular.xlsx`.

## Por que hace falta mirarlo antes de abrirlo

Ese archivo decide tres cosas a la vez: QUE variables ofrece el panel, con QUE RANGO,
y con QUE CONTROL -- deslizador continuo, deslizador de enteros o selector cerrado. La
tercera se deduce del tipo declarado y de la lista de valores posibles, y dos de sus
fallos no dan ningun error:

* una variable entera declarada `numeric` sale con deslizador continuo, y el panel deja
  pedir "2,37 fases" y media puesta a tierra;
* una opcion que el codificador del modelo no conoce se cae de la lista en silencio, y
  quien edito el archivo cree que la puso.

Los dos se ven aqui en un segundo, contra el modelo que hay, y no abriendo el simulador
y mirando fila por fila.

## De donde sale cada cosa

Los knobs -- que variables existen, de que tipo, con que categorias sabe tratar el
modelo -- salen de `catalogo_de_controles`, que cachea su resultado en 2,6 KB y solo
paga los 2,3 s de `procesar_dataset_completo` cuando cambian sus fuentes. El rango, la
unidad, las opciones y el veredicto salen del `.xlsx`. Cruzarlos es todo lo que hace
este guion.

Uso:

    python3 scripts/catalogo_simulacion.py           # informe legible
    python3 scripts/catalogo_simulacion.py --json    # el mismo dato

Sale 0 si el archivo y el modelo se entienden, 1 si hay opciones que el modelo no sabe
codificar.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))


@dataclass(frozen=True)
class Fila:
    """Un control del panel, ya resuelto."""

    knob_id: str
    control: str
    veredicto: str
    vmin: float | None
    vmax: float | None
    unidad: str
    opciones: tuple[str, ...]


@dataclass
class Revision:
    filas: list[Fila] = field(default_factory=list)
    incoherencias: list[str] = field(default_factory=list)
    sin_veredicto: list[str] = field(default_factory=list)
    sin_control: list[str] = field(default_factory=list)
    fuera_de_rango: list[str] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {
            "filas": [asdict(f) | {"opciones": list(f.opciones)} for f in self.filas],
            "incoherencias": list(self.incoherencias),
            "sin_veredicto": list(self.sin_veredicto),
            "sin_control": list(self.sin_control),
            "fuera_de_rango": list(self.fuera_de_rango),
        }


def revisar(knobs: Iterable[Any], catalogo: Mapping[str, Any]) -> Revision:
    """Cruza los knobs del modelo con el catalogo del archivo.

    Puro a proposito: sin esto habria que leer los 566 MB del CSV para preguntar de que
    tipo es una columna de un `.xlsx` de 12 KB.
    """
    from chec_local_interpreter.simulador_variables import (VEREDICTOS_OFRECIDOS,
                                                            incoherencias_del_catalogo)

    knobs = list(knobs)
    revision = Revision()
    for knob in knobs:
        # Un knob constante tiene un solo valor observado: el panel ya lo esconde, y
        # una fila cuyo rango es un punto no le dice nada a nadie.
        if knob.kind == "constant":
            continue
        entrada = catalogo.get(knob.id)
        if entrada is None:
            revision.sin_veredicto.append(knob.id)
            continue
        revision.filas.append(Fila(
            knob_id=knob.id,
            control=entrada.control,
            veredicto=entrada.veredicto,
            vmin=entrada.vmin,
            vmax=entrada.vmax,
            unidad=entrada.unidad,
            opciones=tuple(entrada.opciones),
        ))

    # Solo cuenta como desajuste una fila que el archivo OFRECE y el modelo no puede
    # mover. Una fila con veredicto `No` o `Limitado` sin knob es lo correcto: el
    # archivo la nombra justamente para dejar escrito que no se simula. Medido sobre
    # el archivo real: ocho filas caen ahi, y marcarlas serian ocho falsas alarmas
    # permanentes.
    # Un selector sobre una variable que el modelo ve como NUMERO no tiene categorias
    # que comparar, asi que `incoherencias_del_catalogo` lo deja pasar entero. Lo que si
    # se puede juzgar es el rango: pedirle al modelo un valor que nunca vio es
    # extrapolar, y el panel lo ofreceria sin decir nada. El hueco se abrio el
    # 2026-08-19, cuando `CAPACIDAD_NOMINAL` paso de deslizador continuo a selector de
    # 16 capacidades reales de transformador -- un cambio bueno, que nadie estaba
    # comprobando.
    for knob in knobs:
        entrada = catalogo.get(knob.id)
        if (entrada is None or knob.kind == "categorical" or not entrada.opciones
                or not entrada.opciones_numericas or not knob.bounds):
            continue
        minimo, maximo = float(knob.bounds[0]), float(knob.bounds[1])
        fuera = [v for v in entrada.valores_numericos if not minimo <= v <= maximo]
        if fuera:
            revision.fuera_de_rango.append(
                f"{knob.id}: {len(fuera)} de {len(entrada.valores_numericos)} opciones "
                f"caen fuera de lo que el modelo vio en el entrenamiento "
                f"[{minimo:g}, {maximo:g}] -- {[f'{v:g}' for v in fuera[:4]]}"
                f"{' ...' if len(fuera) > 4 else ''}. Simular ahi es extrapolar."
            )

    conocidos = {knob.id for knob in knobs}
    revision.sin_control = [k for k, e in catalogo.items()
                            if k not in conocidos and e.veredicto in VEREDICTOS_OFRECIDOS]
    revision.incoherencias = incoherencias_del_catalogo(knobs, catalogo)
    return revision


def cargar() -> tuple[list[Any], Mapping[str, Any]]:
    """Los knobs del modelo que hay y el catalogo del archivo que hay."""
    from chec_local_interpreter.config import (DEFAULT_DATA_PATH,
                                               DEFAULT_VARIABLES_SELECCION_PATH)
    from chec_local_interpreter.mil_inferencia import catalogo_de_controles
    from chec_local_interpreter.simulador_variables import catalogo_simulacion

    controles = catalogo_de_controles(DEFAULT_DATA_PATH, DEFAULT_VARIABLES_SELECCION_PATH)
    return list(controles.knobs), catalogo_simulacion()


def informe(revision: Revision) -> str:
    lineas = ["", f"  {len(revision.filas)} controles que el panel va a ofrecer", ""]
    for fila in revision.filas:
        rango = ("|".join(fila.opciones) if fila.opciones
                 else f"{fila.vmin} a {fila.vmax} {fila.unidad}".strip())
        lineas.append(f"    {fila.knob_id:<24} {fila.control:<20} {rango}")
        lineas.append(f"    {'':<24} {fila.veredicto}")
    lineas.append("")

    if revision.fuera_de_rango:
        lineas.append("  Opciones fuera del rango que el modelo vio -- simular ahi "
                      "es extrapolar")
        lineas += [f"    {aviso}" for aviso in revision.fuera_de_rango]
        lineas.append("")
    if revision.incoherencias:
        lineas.append("  Opciones que el modelo NO sabe codificar -- no se ofrecen")
        lineas += [f"    {aviso}" for aviso in revision.incoherencias]
        lineas.append("")
    if revision.sin_veredicto:
        lineas.append("  Controles del modelo sin veredicto en el archivo -- el panel "
                      "los deja fuera")
        lineas += [f"    {knob_id}" for knob_id in revision.sin_veredicto]
        lineas.append("")
    if revision.sin_control:
        lineas.append("  Filas del archivo que no corresponden a ningun control del "
                      "modelo -- sobran o el modelo ya no las tiene")
        lineas += [f"    {knob_id}" for knob_id in revision.sin_control]
        lineas.append("")
    if not (revision.incoherencias or revision.sin_veredicto or revision.sin_control
            or revision.fuera_de_rango):
        lineas.append("  El archivo y el modelo se entienden: ningun desajuste.")
        lineas.append("")
    return "\n".join(lineas)


def codigo_de_salida(revision: Revision) -> int:
    """Fallan los dos desajustes que producen un numero equivocado, no una ausencia.

    Una opcion que el modelo no sabe codificar se cae de la lista en silencio; una que
    cae fuera del rango entrenado se ofrece y se simula extrapolando. Los dos devuelven
    un resultado que parece bueno y no lo es.

    Un knob sin veredicto y una fila de mas se reportan pero no rompen: el panel sigue
    funcionando sin ellos, y quien mantiene el archivo decide si sobran o faltan.
    """
    return 1 if (revision.incoherencias or revision.fuera_de_rango) else 0


def main(argv: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizador.add_argument("--json", action="store_true", dest="como_json")
    args = analizador.parse_args(argv)

    knobs, catalogo = cargar()
    revision = revisar(knobs, catalogo)
    if args.como_json:
        print(json.dumps(revision.como_dict(), indent=2, ensure_ascii=False))
    else:
        print(informe(revision))
    return codigo_de_salida(revision)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
