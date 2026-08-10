"""Relevancia de variables sobre TODAS las bolsas del dataset, para el cuaderno 07.

El cuaderno 06 contesta la pregunta para el punado de vanos que hay en pantalla.
Esto la contesta para el dataset entero, que es lo que hace falta para una hoja de
planeacion: una fila por (vano, ventana) con su grupo y las diez variables que mas
le importan.

Dos cosas justifican un modulo propio en vez de un bucle sobre la funcion de 06.

La primera es aritmetica. Cada pasada del modelo ya devuelve un u-hat POR BOLSA,
asi que barrer las 111.233 bolsas cuesta las MISMAS 197 pasadas que barrer cinco
-- medido, un minuto para todo el dataset. Un bucle por seleccion tardaria dias
para obtener exactamente lo mismo.

La segunda es que la pregunta se INVIERTE segun donde este la bolsa. Para una
bolsa en Alto, Medio-Alto o Medio, el ranking util es que la bajaria al grupo mas
bajo. Para una que ya esta en el mas bajo no hay adonde bajar, y el ranking que
lleva informacion es el contrario: que la sacaria de ahi, o sea de que depende que
se quede. Ordenar una bolsa del grupo mas bajo por caida alcanzable devuelve diez
variables que no mueven nada -- el mismo defecto que ya se midio en el panel de 06.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from chec_impacto.models.criticality_assignment import asignar_clase

from .mil_simulador_015 import aplicar_overrides_instancias, candidatos_de_knob

SIN_EVENTOS = "sin eventos"
"""Etiqueta de la celda (vano, ventana) que no registro ni un evento.

No es un grupo. Sin celda no hay bolsa, sin bolsa no hay prediccion y sin
prediccion no hay ranking; darle el grupo mas bajo seria afirmar algo que nadie
midio, que es justamente el error que el resto del proyecto evita en los mapas.
"""

LECTURA_BAJAR = "top de variables para BAJAR al grupo Bajo"
LECTURA_SOSTENER = "top de variables de las que depende SOSTENERSE en Bajo"

_PISO_U = 1e-12


@dataclass
class BarridoLote:
    """El barrido completo: por cada control, el mejor y el peor u de cada bolsa.

    Se guardan los DOS extremos y no solo el minimo. El minimo contesta que baja
    al vano; el maximo contesta de que depende que se quede donde esta. Cual de
    los dos se usa lo decide el grupo de cada bolsa, no el barrido, asi que el
    barrido no tiene por que saberlo -- y correrlo dos veces costaria el doble
    para obtener numeros que ya estaban calculados.
    """

    u_base: np.ndarray                      # (B,)
    labels: list[str]
    knob_ids: list[str]
    candidatos: list[list[Any]]
    u_min: np.ndarray = field(default_factory=lambda: np.empty((0, 0)))   # (K, B)
    u_max: np.ndarray = field(default_factory=lambda: np.empty((0, 0)))
    idx_min: np.ndarray = field(default_factory=lambda: np.empty((0, 0), dtype=int))
    idx_max: np.ndarray = field(default_factory=lambda: np.empty((0, 0), dtype=int))

    def valor(self, k: int, b: int, extremo: str) -> Any:
        """El valor del control `k` que consigue ese extremo en la bolsa `b`."""
        indices = self.idx_min if extremo == "min" else self.idx_max
        return self.candidatos[k][int(indices[k, b])]


def barrer_todas_las_bolsas(
    predictor: Any,
    X_inst: np.ndarray,
    *,
    instance_bag: np.ndarray,
    feature_names: Sequence[str],
    knobs: Sequence[Any],
    puntos: int = 9,
    label_encoders: Mapping[str, Any] | None = None,
    max_values_imputed: Mapping[str, Any] | None = None,
) -> BarridoLote:
    """Recorre cada control sobre TODAS las instancias a la vez.

    Una pasada por candidato, y cada pasada devuelve el u-hat de las 111 mil
    bolsas. Medido: 0,30 s por pasada, 197 candidatos, un minuto en total.

    Se recorren TODOS los controles que se le pasen, tambien los categoricos --
    su rejilla son sus categorias. Dejarlos fuera quitaria del analisis al
    conductor, al calibre del neutro y al tipo de proteccion, que son tres de las
    obras que CHEC efectivamente ejecuta. Los constantes si quedan fuera: un unico
    valor observado no mueve nada y probarlo gasta una pasada sobre 288 mil filas.
    """
    X = np.asarray(X_inst, dtype=np.float64)
    ib = np.asarray(instance_bag, dtype=np.int64)
    u_base = np.asarray(predictor.predict(X, instance_bag=ib), dtype=float)

    labels: list[str] = []
    knob_ids: list[str] = []
    candidatos: list[list[Any]] = []
    filas_min, filas_max, filas_imin, filas_imax = [], [], [], []
    for knob in knobs:
        valores = candidatos_de_knob(knob, puntos=puntos)
        if valores is None:
            continue
        us = []
        for valor in valores:
            overrides = [{"variable": f, "valor": valor} for f in knob.feature_names]
            X_sim, aplicadas, _avisos = aplicar_overrides_instancias(
                X, feature_names, overrides,
                label_encoders=label_encoders, max_values_imputed=max_values_imputed,
            )
            if not aplicadas:
                us = []
                break
            us.append(np.asarray(predictor.predict(X_sim, instance_bag=ib), dtype=float))
        if not us:
            continue
        matriz = np.vstack(us)                      # (candidatos, B)
        labels.append(knob.label)
        knob_ids.append(knob.id)
        candidatos.append(list(valores))
        filas_min.append(matriz.min(axis=0))
        filas_max.append(matriz.max(axis=0))
        filas_imin.append(matriz.argmin(axis=0))
        filas_imax.append(matriz.argmax(axis=0))

    vacio = np.empty((0, len(u_base)))
    return BarridoLote(
        u_base=u_base, labels=labels, knob_ids=knob_ids, candidatos=candidatos,
        u_min=np.vstack(filas_min) if filas_min else vacio,
        u_max=np.vstack(filas_max) if filas_max else vacio,
        idx_min=(np.vstack(filas_imin) if filas_imin
                 else np.empty((0, len(u_base)), dtype=int)),
        idx_max=(np.vstack(filas_imax) if filas_imax
                 else np.empty((0, len(u_base)), dtype=int)),
    )


def _log10(valores: np.ndarray) -> np.ndarray:
    return np.log10(np.maximum(np.asarray(valores, dtype=float), _PISO_U))


def _top_con_cuota(
    orden: np.ndarray, metrica: np.ndarray, knob_ids: Sequence[str],
    grupos: Mapping[str, str] | None, top: int,
) -> list[list[int]]:
    """Los `top` indices de control de cada bolsa, reservando sitio por grupo.

    Sin la reserva, un ranking copado por las cuatro familias climaticas no deja
    ni una palanca que una cuadrilla pueda ejecutar, y la hoja existe para
    sostener ordenes de trabajo.
    """
    if not grupos:
        return [list(fila[:top]) for fila in orden]
    nombres = [g for g in dict.fromkeys(grupos.get(k, "") for k in knob_ids) if g]
    if len(nombres) < 2:
        return [list(fila[:top]) for fila in orden]
    cuota = max(1, top // len(nombres))
    grupo_de = np.array([grupos.get(k, "") for k in knob_ids])
    elegidos = []
    for fila in orden:
        tomados: list[int] = []
        for nombre in nombres:
            del_grupo = [int(k) for k in fila if grupo_de[k] == nombre][:cuota]
            tomados.extend(del_grupo)
        for k in fila:                       # el resto, por orden global
            if len(tomados) >= top:
                break
            if int(k) not in tomados:
                tomados.append(int(k))
        tomados.sort(key=lambda k: -metrica[k])
        elegidos.append(tomados[:top])
    return elegidos


def ranking_por_bolsa(
    barrido: BarridoLote,
    *,
    n_obs: np.ndarray,
    geometria: Any,
    top: int = 10,
    grupos: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Las `top` variables de cada bolsa, y en que direccion se leen.

    Una bolsa por ENCIMA del grupo mas bajo se ordena por cuanto BAJA su u-hat:
    es la pregunta de una orden de trabajo. Una que ya esta en el mas bajo se
    ordena por cuanto lo SUBIRIA: no hay adonde bajar, y lo que lleva informacion
    es de que depende que se quede -- sus fragilidades.

    La metrica es la misma en los dos casos, la diferencia en ORDENES DE MAGNITUD
    de u, que es el eje que usa la geometria KMeans. En unidades, el ranking de
    un vano caro seria incomparable con el de uno barato.
    """
    clases, _ = asignar_clase(np.asarray(n_obs, dtype=float), barrido.u_base, geometria)
    clases = np.asarray(clases, dtype=int)
    base_log = _log10(barrido.u_base)
    caida = base_log[None, :] - _log10(barrido.u_min)     # (K, B)
    subida = _log10(barrido.u_max) - base_log[None, :]

    en_la_minima = clases == 0
    metrica = np.where(en_la_minima[None, :], subida, caida)
    orden = np.argsort(-metrica, axis=0).T                # (B, K)

    labels_por_bolsa: list[list[str]] = []
    ids_por_bolsa: list[list[str]] = []
    valores_por_bolsa: list[list[Any]] = []
    metrica_por_bolsa: list[list[float]] = []
    for b in range(len(barrido.u_base)):
        indices = _top_con_cuota(orden[b: b + 1], metrica[:, b], barrido.knob_ids,
                                 grupos, top)[0]
        extremo = "max" if en_la_minima[b] else "min"
        labels_por_bolsa.append([barrido.labels[k] for k in indices])
        ids_por_bolsa.append([barrido.knob_ids[k] for k in indices])
        valores_por_bolsa.append([barrido.valor(k, b, extremo) for k in indices])
        metrica_por_bolsa.append([float(metrica[k, b]) for k in indices])
    return {
        "clases": clases,
        "direccion": ["sostener" if e else "bajar" for e in en_la_minima],
        "labels": labels_por_bolsa,
        "knob_ids": ids_por_bolsa,
        "valores": valores_por_bolsa,
        "metrica": metrica_por_bolsa,
    }


def relevancia_media_por_grupo(
    barrido: BarridoLote, *, clases: np.ndarray, n_clases: int = 4,
) -> dict[int, dict[str, dict[str, float]]]:
    """La caida alcanzable de cada control por grupo de criticidad: media, DESVIACION
    y cuantas bolsas la sostienen.

    Es lo que se puede leer de un vistazo con 111 mil bolsas: la pregunta del
    cuaderno 07 no es que mueve a UN vano sino que mueve al GRUPO. Se promedia en
    ordenes de magnitud, no en unidades de UITI, para que un punado de bolsas
    caras no se lleve el promedio entero.

    La desviacion NO es decoracion. Una media alta con una desviacion del mismo
    tamano dice que la variable funciona en unos vanos del grupo y no en otros, y
    esa es una recomendacion distinta -- "revisar vano por vano" -- de la que da
    una media alta y estable, que si sostiene una politica para todo el grupo.
    Sin la barra de error, las dos se dibujan identicas.
    """
    clases = np.asarray(clases, dtype=int)
    caida = _log10(barrido.u_base)[None, :] - _log10(barrido.u_min)
    resumen: dict[int, dict[str, dict[str, float]]] = {}
    for clase in range(n_clases):
        mascara = clases == clase
        if not mascara.any():
            resumen[clase] = {}
            continue
        resumen[clase] = {
            label: {
                "media": float(caida[k, mascara].mean()),
                "desviacion": float(caida[k, mascara].std()),
                "n_bolsas": int(mascara.sum()),
            }
            for k, label in enumerate(barrido.labels)
        }
    return resumen


def gates_medias_por_grupo(
    gates: np.ndarray, clases: np.ndarray, n_clases: int = 4,
) -> dict[int, np.ndarray]:
    """Las compuertas del grafo experto PROMEDIADAS dentro de cada grupo.

    El grafo del cuaderno 06 describe una seleccion de vanos; aqui la "seleccion"
    es el grupo de criticidad entero, que es la unidad en la que este cuaderno
    piensa. Se devuelve la submatriz de compuertas de cada grupo -- y no ya el
    grafo -- porque quien decide si se puede reconstruir es
    `grafo_por_grupo_si_no_colapsado`, y esa decision depende de si las compuertas
    VARIAN dentro del grupo: un grupo cuyos vanos estan compuertados igual no
    produjo ninguna estructura propia, y dibujarla seria presentar el grafo
    experto fijo como si la hubiera estimado ese grupo.
    """
    gates = np.asarray(gates, dtype=float)
    clases = np.asarray(clases, dtype=int)
    return {clase: gates[clases == clase] for clase in range(n_clases)
            if (clases == clase).any()}


def tabla_vano_ventana(
    *,
    claves: pd.DataFrame,
    ventanas: Sequence[str],
    clases: np.ndarray,
    nombres_clase: Sequence[str],
    ranking: Mapping[str, Any],
    top: int = 10,
) -> pd.DataFrame:
    """La hoja: una fila por (vano, ventana), con su grupo y su top.

    La rejilla es COMPLETA a proposito -- todo vano contra todas las ventanas --
    aunque solo un tercio de las celdas tenga eventos. Un vano al que le faltan
    ventanas se lee como que no existio en ellas, cuando lo que paso es que no
    registro eventos, y esa diferencia es la que la etiqueta `sin eventos`
    sostiene.

    `LECTURA_DEL_TOP` no es decoracion: las dos direcciones no significan lo
    mismo, y sin decirlo la hoja se lee como si el top de un vano en Bajo fuera
    "como bajarlo mas".
    """
    claves = claves.reset_index(drop=True)
    por_celda = {
        (str(c), str(v), str(w)): i
        for i, (c, v, w) in enumerate(zip(claves["CIRCUITO"], claves["FID_VANO"],
                                          claves["VENTANA"]))
    }
    vanos = claves[["CIRCUITO", "FID_VANO"]].drop_duplicates()
    filas = []
    for circuito, fid in zip(vanos["CIRCUITO"].astype(str), vanos["FID_VANO"].astype(str)):
        for ventana in ventanas:
            i = por_celda.get((circuito, fid, str(ventana)))
            fila: dict[str, Any] = {"CIRCUITO": circuito, "FID_VANO": fid,
                                    "VENTANA": str(ventana)}
            if i is None:
                fila["GRUPO"] = SIN_EVENTOS
                fila["LECTURA_DEL_TOP"] = ""
                for k in range(top):
                    fila[f"TOP_{k + 1}"] = ""
            else:
                fila["GRUPO"] = nombres_clase[int(clases[i])]
                fila["LECTURA_DEL_TOP"] = (
                    LECTURA_SOSTENER if ranking["direccion"][i] == "sostener"
                    else LECTURA_BAJAR
                )
                etiquetas = ranking["labels"][i]
                for k in range(top):
                    fila[f"TOP_{k + 1}"] = etiquetas[k] if k < len(etiquetas) else ""
            filas.append(fila)
    return pd.DataFrame(filas)


def guardar_hojas(rutas_hojas: Mapping[str, pd.DataFrame], destino: Any) -> None:
    """Escribe varias hojas en un `.xlsx` sin armar el libro entero en RAM.

    Se escribe fila a fila con `xlsxwriter` en vez de `DataFrame.to_excel`, y no es
    una preferencia de estilo: `to_excel` recorre el DataFrame **por columnas**, y
    el modo `constant_memory` de xlsxwriter descarta una fila en cuanto el cursor
    pasa a la siguiente. Combinar los dos produce un archivo que se abre sin error
    y trae **solo la primera columna**; las demas vuelven vacias. Se detecto
    escribiendo las 301 mil filas de 07 y leyendolas de vuelta: 1,5 MB y una sola
    celda con grupo.

    Sin `constant_memory` el modo por defecto guarda las ~4,8 millones de celdas en
    memoria antes de tocar el disco. Escribiendo por filas se pueden tener las dos
    cosas, que es lo que hace esto.
    """
    import xlsxwriter

    libro = xlsxwriter.Workbook(str(destino), {"constant_memory": True})
    try:
        for nombre, tabla in rutas_hojas.items():
            hoja = libro.add_worksheet(nombre[:31])
            columnas = list(tabla.columns)
            for j, columna in enumerate(columnas):
                hoja.write(0, j, str(columna))
            for i, fila in enumerate(tabla.itertuples(index=False, name=None), start=1):
                for j, valor in enumerate(fila):
                    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
                        continue
                    hoja.write(i, j, valor)
    finally:
        libro.close()
