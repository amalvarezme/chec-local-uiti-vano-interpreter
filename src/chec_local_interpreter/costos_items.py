"""CHEC's contract activity price list, and the intervention cost it buys.

The simulator answers what happens to a vano's criticality if this variable
changes. That is half of a maintenance decision; the other half is what the
change COSTS. `data/Actividades_mantenimiento_costos_2026.xlsx` is CHEC's own contract price
list, and joining it to the marked vanos turns "the risk drops one group" into
"the risk drops one group for 283.472 pesos", which is the sentence a work
order is actually approved on.

The two halves are deliberately NOT tied to each other. Picking "PODA EN REDES
RURALES TIPO A" does not move `NR_T`, and lowering `NR_T` does not schedule a
pruning: the model has no mapping from contract activities to features, and
inventing one would produce a number that looks like an estimate of the benefit
of an activity while being nothing of the sort. What the panel puts side by
side is the simulated effect and the quoted cost of the plan the user says they
would execute, and keeping the join in the user's head is the honest place for
it until CHEC provides that mapping.

The file is a PIVOT TABLE export, which is why reading it needs a module and
not a `read_excel`:

  1. Its last row is `Total general`, the pivot's own footer. Offered as an
     activity it looks like any other, and its "unit cost" is the average of
     the whole catalogue -- picking it would add 254.388 pesos of artefact.
  2. Twelve rows carry no unit cost at all. They are set aside and NAMED: a
     list that quietly drops twelve entries reads as a shorter catalogue, not
     as a decision.
  3. There is no item code, so the NAME is the key -- and one name arrives
     mojibake'd. A key nobody can read is a key nobody can pick.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

COLUMNA_ACTIVIDAD = "Actividad"
COLUMNA_COSTO_2026 = "COSTO"
COLUMNA_TIPO = "TIPO_ACTIVIDAD"
COLUMNA_UNIDAD = "UM"
COLUMNA_CODIGO = "Codigo Maximo"
COLUMNA_DESCRIPCION = "Descripción de la actividad"
# Los del libro anterior, que se siguen aceptando: el lector cae a ellos si el archivo
# que recibe es el viejo, en vez de renombrar columnas por posicion y producir basura.
COLUMNA_ITEM = "Etiquetas de fila"
COLUMNA_COSTO = "Promedio de UNITCOST"
FILA_TOTAL = "Total general"

MAX_REPETICIONES = 5
"""Cuantas veces puede repetirse una actividad sobre un mismo vano.

Cinco, y no un numero libre: el desplegable existe para decir "esta poda va dos
veces", no para teclear una cantidad de obra que ya no es una intervencion
puntual sino un contrato. Por encima de eso, el costo deja de ser el de una
orden de trabajo sobre un vano.

El rango arranca en CERO. El cero no sobra por tener casilla: la casilla elige
que actividades entran al plan, y el cero dice en cuales de los vanos marcados
esa actividad NO se ejecuta. Sin el, una lista compartida obligaria a darle la
misma obra a los cinco vanos, y "podar solo este" seria imposible de expresar.
"""


SIN_DESCRIPCION = "Sin descripcion en el libro de actividades."
"""52 de las 142 actividades del libro no traen descripcion.

Un panel de informacion en blanco se lee como que la consulta fallo; decirlo lo
distingue de una actividad que si tiene texto y no se cargo.
"""


@dataclass(frozen=True)
class ItemCosto:
    """Una actividad del contrato: lo que cuesta y lo que ES.

    La casilla del panel solo tiene sitio para el precio y el nombre. El resto --
    tipo, unidad, codigo maximo y descripcion -- es lo que contesta el boton de
    informacion, y viaja aqui para que el cuaderno no vuelva a abrir el libro por su
    cuenta: dos lecturas del mismo archivo se separan en cuanto alguien cambia una.
    """

    nombre: str
    costo: float
    tipo: str = ""
    unidad: str = ""
    codigo_maximo: str = ""
    descripcion: str = SIN_DESCRIPCION


@dataclass(frozen=True)
class CatalogoCostos:
    """Lo que se puede costear, y lo que no.

    `sin_costo` no es un residuo: es la lista que el panel NOMBRA debajo de las
    casillas. Sin ella, doce actividades ausentes se leen como que el contrato
    no las incluye.
    """

    items: tuple[ItemCosto, ...]
    sin_costo: tuple[str, ...]

    @property
    def por_nombre(self) -> dict[str, float]:
        """`nombre -> costo unitario`, que es como el costeo lo consulta."""
        return {item.nombre: item.costo for item in self.items}


# Los caracteres con los que EMPIEZA una secuencia UTF-8 mal decodificada. Se exige
# uno para intentar la reparacion: sin ese filtro, cualquier nombre que por casualidad
# forme bytes UTF-8 validos se "repararia" hacia algo que nunca fue.
_MARCAS_MOJIBAKE = ("Ã", "Â", "â")

# cp1252 y NO latin-1, que es el reflejo. Medido sobre el archivo real:
# `CONDUCCIÃ“N` trae `“` (U+201C), y ese caracter es como cp1252 lee el byte 0x93 --
# el segundo byte de la `Ó` en UTF-8. latin-1 no tiene nada en 0x93, asi que ni
# siquiera puede codificarlo y la reparacion fallaba en silencio. Se deja latin-1
# detras como respaldo porque los dos juegos coinciden fuera del rango 0x80-0x9F.
_CODECS_ORIGEN = ("cp1252", "latin-1")


def reparar_texto(texto: str) -> str:
    """Deshace el mojibake de UTF-8 leido como cp1252 (`CONDUCCIÃ“N`).

    Solo cuando el viaje de vuelta es exacto. Aplicada a ciegas sobre un nombre
    sano con tilde lo rompe en la direccion contraria, y como el NOMBRE es la
    clave del catalogo, romperlo aqui es perder la actividad.
    """
    if not any(marca in texto for marca in _MARCAS_MOJIBAKE):
        return texto
    for codec in _CODECS_ORIGEN:
        try:
            return texto.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return texto


def leer_catalogo_costos(path: str | Path) -> CatalogoCostos:
    """El catalogo de actividades de `Actividades_mantenimiento_costos_2026.xlsx`.

    Las columnas se leen por NOMBRE y no por posicion. El lector anterior renombraba
    las dos primeras por orden, y ese libro trae siete: tomaria `TIPO_ACTIVIDAD` como
    nombre de la actividad y el codigo maximo como su precio, SIN fallar -- el panel
    saldria con dos "actividades" y precios de seis cifras que son codigos.

    Conserva el ORDEN DEL ARCHIVO, que es por tipo de mantenimiento y es lo que hace
    encontrable una lista de 142 casillas. Ordenar por costo pondria una poda urbana al
    lado de una reubicacion de poste solo porque valen parecido, y quien busca una poda
    no la busca por precio.
    """
    tabla = pd.read_excel(path)
    columnas = {str(c).strip(): c for c in tabla.columns}

    def _col(*candidatas: str):
        for c in candidatas:
            if c in columnas:
                return tabla[columnas[c]]
        # Vacio y de tipo objeto: una serie de `None` sale float64, y en esta version
        # de pandas `astype(str)` CONSERVA el NaN en vez de escribir "nan", asi que
        # `reparar_texto` recibiria un float y reventaria al leer el libro anterior.
        return pd.Series([""] * len(tabla), dtype=object)

    def _texto(serie):
        return serie.fillna("").astype(str).map(reparar_texto)

    nombres = _texto(_col(COLUMNA_ACTIVIDAD, COLUMNA_ITEM))
    costos = pd.to_numeric(_col(COLUMNA_COSTO_2026, COLUMNA_COSTO), errors="coerce")
    tipos = _texto(_col(COLUMNA_TIPO))
    unidades = _col(COLUMNA_UNIDAD).fillna("").astype(str)
    codigos = _col(COLUMNA_CODIGO)
    descripciones = _col(COLUMNA_DESCRIPCION)

    items: list[ItemCosto] = []
    sin_costo: list[str] = []
    for nombre, costo, tipo, unidad, codigo, descripcion in zip(
        nombres, costos, tipos, unidades, codigos, descripciones
    ):
        if nombre == FILA_TOTAL or nombre in ("nan", "None", ""):
            continue
        if pd.isna(costo):
            sin_costo.append(nombre)
            continue
        texto = "" if descripcion is None or pd.isna(descripcion) else str(descripcion).strip()
        items.append(ItemCosto(
            nombre=nombre,
            costo=float(costo),
            tipo="" if tipo in ("nan", "None") else tipo,
            unidad="" if unidad in ("nan", "None") else unidad.strip(),
            # El codigo va como TEXTO: es un identificador, y formateado como numero
            # pierde ceros a la izquierda y se imprime con separador de miles.
            codigo_maximo="" if codigo is None or pd.isna(codigo) else str(int(codigo))
                          if isinstance(codigo, (int, float)) else str(codigo).strip(),
            descripcion=reparar_texto(texto) if texto else SIN_DESCRIPCION,
        ))
    return CatalogoCostos(items=tuple(items), sin_costo=tuple(sin_costo))


def costos_de_intervencion(
    items_por_vano: Mapping[str, Mapping[str, int]],
    catalogo: CatalogoCostos,
) -> dict[str, Any]:
    """El costo de la intervencion: por vano y en total.

    `items_por_vano` es `{fid: {actividad: repeticiones}}` -- exactamente lo que
    la rejilla del panel tiene marcado. Devuelve el total de cada vano con su
    DETALLE, porque el total contesta cuanto y el detalle contesta por que: sin
    el, un vano caro obliga a reabrir el panel para saber que actividad lo
    encarecio.

    El detalle va de mayor a menor subtotal. La primera linea es la que hay que
    negociar; en el orden en que se fueron marcando las casillas, la que manda
    queda donde caiga.

    Un vano sin actividades cuesta cero y SIGUE en el resultado: ese cero dice
    que la simulacion movio su riesgo sin obra asociada, y sacarlo lo borraria
    de la grafica, donde se leeria como que no se estudio.

    Una actividad en CERO no entra al detalle: sale del total porque no se
    ejecuta, y listarla como "0 x PODA: 0" llenaria el desglose de renglones que
    no cuestan nada. Un vano con TODO en cero sigue apareciendo, eso si, con su
    barra en cero -- decir "a este no le hago nada" es una respuesta, y se
    distingue de un vano que nunca se marco.

    Levanta antes que devolver un numero equivocado. Una actividad que no esta
    en el catalogo no puede valer cero -- el presupuesto saldria mas barato de
    lo que es y nada en pantalla lo diria -- y unas repeticiones fuera de lo que
    el desplegable ofrece son un error de programa, no una eleccion.
    """
    precios = catalogo.por_nombre
    por_vano: dict[str, dict[str, Any]] = {}
    total = 0.0
    for fid, actividades in items_por_vano.items():
        renglones = []
        for item, repeticiones in actividades.items():
            if item not in precios:
                raise KeyError(
                    f"La actividad {item!r} no esta en el catalogo de costos. "
                    "El nombre es la clave: si el libro cambio, el panel esta "
                    "ofreciendo una actividad que ya no existe."
                )
            n = int(repeticiones)
            if not 0 <= n <= MAX_REPETICIONES:
                raise ValueError(
                    f"Repeticiones fuera de rango para {item!r}: {repeticiones}. "
                    f"El desplegable solo ofrece de 0 a {MAX_REPETICIONES}."
                )
            if n == 0:
                continue
            renglones.append({
                "item": item,
                "costo_unitario": precios[item],
                "repeticiones": n,
                "subtotal": precios[item] * n,
            })
        renglones.sort(key=lambda r: r["subtotal"], reverse=True)
        subtotal_vano = float(sum(r["subtotal"] for r in renglones))
        por_vano[fid] = {"total": subtotal_vano, "renglones": renglones}
        total += subtotal_vano
    return {"por_vano": por_vano, "total": total}
