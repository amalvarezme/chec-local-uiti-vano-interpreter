"""Los valores generales del circuito, calculados para la cabecera del informe.

El informe abria con la barra del ranking: 208 rotulos de 8 px girados noventa grados.
Dice el puesto del circuito y nada mas, y para leer el nombre de un vecino hay que
ampliar la imagen. Quien recibe el informe empieza por otra pregunta -- que tan grande
es este circuito, cuanto mide, cuantos vanos estan senalados -- y esa respuesta no
estaba en ninguna parte.

Aqui no se calcula nada nuevo: lo comparativo sale de `ranking_circuitos`, que es
exactamente el mismo calculo que pinta la barra que el lector tiene delante, y lo
fisico sale de los shapefiles de `data/GEO` que el mapa del informe ya lee. Dos
implementaciones del mismo numero se separan en cuanto alguien toca una, y entonces la
cabecera y la figura dicen cosas distintas sin que nada en pantalla lo delate.

**Vano probable de causa de falla no es evento.** Un vano probable de causa de falla es
un VANO que aparece en registros de interrupcion; `registros_vano_evento` cuenta FILAS,
y el mismo vano golpeado cinco veces son cinco filas y un solo vano. Medido sobre la
base real: 159.470 filas son 6.455 interrupciones distintas repartidas sobre 27.390
vanos. Los tres numeros son distintos y el informe los nombra distinto.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import pandas as pd

_COLUMNAS_MINIMAS = {"CIRCUITO", "FID_VANO", "UITI_VANO"}


def _normalizar_fid(serie: pd.Series) -> pd.Series:
    """Misma regla que `ranking_circuitos._normalizar_fid` y que `plotting._norm_map_id`.

    `FID_VANO` llega numerico con sufijo `.0` inconsistente entre filas: sin normalizar,
    `20130434` y `20130434.0` son dos vanos con la mitad de los registros cada uno.
    """
    return serie.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)


# --------------------------------------------------------------------------- ficha


def ficha_general(
    raw_df: pd.DataFrame,
    circuito: str,
    *,
    start_date: Any = None,
    end_date: Any = None,
) -> dict[str, Any]:
    """Los valores de cabecera del circuito, comparados contra los circuitos totales.

    `raw_df` tiene que traer TODOS los circuitos: cada numero de aqui es comparativo
    -- puesto, banda, aporte al total -- y con un solo circuito no hay contra que
    comparar. Es el mismo requisito que ya tiene `_compute_circuit_characterization`,
    y es la razon por la que en su dia todos los informes decian "Riesgo Muy Alto".
    """
    if raw_df is None or raw_df.empty or not _COLUMNAS_MINIMAS <= set(raw_df.columns):
        return {}

    from chec_local_interpreter.ranking_circuitos import ranking_circuitos

    resultado = ranking_circuitos(raw_df, start_date, end_date)
    tabla = resultado.tabla
    if tabla.empty:
        return {}

    fila = tabla[tabla["circuito"].astype(str) == str(circuito)]
    if fila.empty:
        return {}
    fila = fila.iloc[0]

    uiti_total = float(tabla["uiti_total"].sum())
    ficha: dict[str, Any] = {
        "circuito": str(circuito),
        "posicion": int(fila["posicion"]),
        "circuitos_totales": int(len(tabla)),
        "rango": str(fila["rango"]),
        "uiti_circuito": float(fila["uiti_total"]),
        "uiti_total": uiti_total,
        "aporte_uiti_pct": (100.0 * float(fila["uiti_total"]) / uiti_total
                            if uiti_total else 0.0),
        # Vanos que aparecen en registros de interrupcion. NO son eventos: ver el
        # encabezado del modulo.
        "vanos_probables": int(fila["vanos_con_eventos"]),
        "vanos_probables_total": int(tabla["vanos_con_eventos"].sum()),
        # De esos, los que el agrupamiento situa en Medio-Alto o Alto.
        "vanos_criticos": int(fila["vanos_criticos"]),
        "vanos_criticos_total": int(tabla["vanos_criticos"].sum()),
        "registros_vano_evento": int(fila["eventos_total"]),
        "cortes": tuple(float(c) for c in resultado.cortes),
    }
    ficha.update(medidas_fisicas(str(circuito)))
    return ficha


# ------------------------------------------------------------------ medidas fisicas


@lru_cache(maxsize=256)
def medidas_fisicas(circuito: str) -> dict[str, Any]:
    """Longitud total, urbana y rural, y numero de transformadores.

    Sale de los mismos shapefiles que dibuja el mapa del informe: `MVLINSEC` trae
    `LONGITUD` en METROS -- no en grados, pese a que la geometria este en EPSG:4326 --
    y `CLASIFICAC` con el reparto urbano/rural; `GDBCHEC_TRANSFOR` trae un punto por
    transformador.

    Sin `data/GEO` devuelve vacio y la cabecera pierde estas filas, no el informe
    entero: hay entornos donde los shapefiles no estan y el resto del informe si.
    """
    from chec_local_interpreter.plotting import leer_geo_crudo

    medidas: dict[str, Any] = {}

    lineas = leer_geo_crudo("MVLINSEC.shp")
    if lineas is not None and {"CIRCUITO", "LONGITUD"} <= set(lineas.columns):
        tramos = lineas[lineas["CIRCUITO"].astype(str).eq(str(circuito))]
        if not tramos.empty:
            longitud = pd.to_numeric(tramos["LONGITUD"], errors="coerce").fillna(0.0)
            medidas["longitud_km"] = float(longitud.sum()) / 1000.0
            medidas["tramos"] = int(len(tramos))
            if "CLASIFICAC" in tramos.columns:
                # `CENTRO_POBLADO` y los nulos existen en la base y no son ninguna de
                # las dos: se cuentan aparte en vez de repartirse a ojo, que es como un
                # total deja de cuadrar con sus partes.
                clase = tramos["CLASIFICAC"].astype("string").str.strip().str.upper()
                por_clase = longitud.groupby(clase).sum()
                medidas["longitud_urbana_km"] = float(por_clase.get("URBANO", 0.0)) / 1000.0
                medidas["longitud_rural_km"] = float(por_clase.get("RURAL", 0.0)) / 1000.0
                medidas["longitud_otra_km"] = max(
                    0.0,
                    medidas["longitud_km"]
                    - medidas["longitud_urbana_km"]
                    - medidas["longitud_rural_km"],
                )

    transformadores = leer_geo_crudo("GDBCHEC_TRANSFOR.shp")
    if transformadores is not None and "CIRCUITO" in transformadores.columns:
        n = int(transformadores["CIRCUITO"].astype(str).eq(str(circuito)).sum())
        if n:
            medidas["transformadores"] = n

    return medidas


# ------------------------------------------------------------------ vanos de impacto


def vanos_de_mayor_impacto(
    raw_df: pd.DataFrame, circuito: str, *, tope: int = 10
) -> dict[str, list]:
    """Los vanos que mas pesan, por los DOS criterios, y los que estan en los dos.

    Un vano puede concentrar UITI en una sola salida larga y otro puede aparecer en
    todas las ventanas con poco cada vez. Son dos problemas distintos y se atienden
    distinto, asi que el informe no puede quedarse con uno de los dos criterios y
    llamarlo "los vanos importantes".

    La interseccion es lo que el revisor pidio y es la parte accionable: un vano que
    esta en las dos listas lo esta independientemente de con que criterio se mire.
    """
    vacio = {"por_uiti": [], "por_apariciones": [], "coincidentes": []}
    if raw_df is None or raw_df.empty or not _COLUMNAS_MINIMAS <= set(raw_df.columns):
        return vacio

    df = raw_df[raw_df["CIRCUITO"].astype(str) == str(circuito)]
    if df.empty:
        return vacio

    por_vano = pd.DataFrame({
        "fid": _normalizar_fid(df["FID_VANO"]),
        "uiti": pd.to_numeric(df["UITI_VANO"], errors="coerce").fillna(0.0),
    }).groupby("fid").agg(uiti=("uiti", "sum"), apariciones=("uiti", "count"))
    if por_vano.empty:
        return vacio

    def _lista(columna: str) -> list[dict[str, Any]]:
        orden = por_vano.sort_values(columna, ascending=False).head(tope)
        return [{"fid": str(fid), "uiti": float(r["uiti"]),
                 "apariciones": int(r["apariciones"])}
                for fid, r in orden.iterrows()]

    por_uiti = _lista("uiti")
    por_apariciones = _lista("apariciones")
    coincidentes = [v["fid"] for v in por_uiti
                    if v["fid"] in {a["fid"] for a in por_apariciones}]
    return {"por_uiti": por_uiti, "por_apariciones": por_apariciones,
            "coincidentes": coincidentes}


# ------------------------------------------------------------------------ formato


def _num(valor: float, decimales: int = 0) -> str:
    """Convencion local: punto de miles y coma decimal. Misma regla que el gerencial."""
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "@").replace(".", ",").replace("@", ".")


def _escapar(valor: object) -> str:
    import html

    return html.escape("" if valor is None else str(valor))


# --------------------------------------------------------------------- tabla ficha


#: Las filas de la cabecera, en el orden en que se leen. Cada una es (etiqueta, clave,
#: decimales, unidad); una clave ausente -- sin shapefiles, por ejemplo -- se salta en
#: vez de escribirse en cero, que se leeria como "este circuito no tiene longitud".
_FILAS_FICHA: tuple[tuple[str, str, int, str], ...] = (
    ("UITI acumulado del circuito", "uiti_circuito", 1, ""),
    ("Aporte al UITI de todos los circuitos", "aporte_uiti_pct", 1, "%"),
    ("Vanos probables de causa de falla", "vanos_probables", 0, ""),
    ("De ellos, en Medio-Alto o Alto", "vanos_criticos", 0, ""),
    ("Registros vano-evento", "registros_vano_evento", 0, ""),
    ("Longitud total de la red", "longitud_km", 1, " km"),
    ("Longitud urbana", "longitud_urbana_km", 1, " km"),
    ("Longitud rural", "longitud_rural_km", 1, " km"),
    ("Transformadores", "transformadores", 0, ""),
)


def tabla_ficha_html(ficha: dict[str, Any]) -> str:
    """La cabecera del informe: que tan grande es este circuito y cuanto pesa.

    Va ANTES de la barra del ranking a proposito. La barra situa al circuito entre los
    demas, que es una pregunta que solo tiene sentido cuando ya se sabe de que circuito
    se habla.
    """
    if not ficha:
        return ""

    filas = []
    for etiqueta, clave, decimales, unidad in _FILAS_FICHA:
        valor = ficha.get(clave)
        if valor is None:
            continue
        filas.append(
            f"<tr><th>{_escapar(etiqueta)}</th>"
            f"<td class='num'>{_num(float(valor), decimales)}{_escapar(unidad)}</td></tr>"
        )
    if not filas:
        return ""

    encabezado = (
        f"<p class='ficha-titular'><b>{_escapar(ficha.get('circuito', ''))}</b> "
        f"&mdash; {_escapar(ficha.get('rango', ''))}, ubicación "
        f"<b>{_num(float(ficha.get('posicion', 0)))}</b> de "
        f"{_num(float(ficha.get('circuitos_totales', 0)))} circuitos totales</p>"
    )
    # `registros vano-evento` es la fila que mas se malinterpreta: no son eventos ni
    # vanos. Se define PEGADA a la tabla porque una definicion tres secciones mas
    # arriba no la lee nadie.
    nota = (
        "<p class='muted' style='margin:8px 0 0 0;'>Un <b>vano probable de causa de "
        "falla</b> es un vano que aparece en registros de interrupción del período. "
        "Un <b>registro vano-evento</b> es una fila: la misma interrupción golpea "
        "varios vanos y el mismo vano puede aparecer en varias interrupciones, así que "
        "los registros son siempre más que los vanos y más que las interrupciones.</p>"
    )
    return (f"<div class='ficha-circuito'>{encabezado}"
            f"<table class='tabla-informe ficha'><tbody>{''.join(filas)}</tbody></table>"
            f"{nota}</div>")


# ------------------------------------------------------------- tabla clasificacion


def tabla_clasificacion_html(
    raw_df: pd.DataFrame,
    circuito: str,
    *,
    start_date: Any = None,
    end_date: Any = None,
) -> str:
    """La clasificacion de criticidad en tabla, con el numero de ubicacion.

    La barra del ranking lleva 208 rotulos de 8 px girados noventa grados: dice donde
    cae el circuito y no deja leer el nombre de ninguno. La tabla dice lo mismo con los
    nombres legibles, y el numero de ubicacion es lo que permite cruzar las dos -- por
    eso la barra tambien lo lleva ahora en su rotulo.

    Va plegada. Doscientas filas abiertas empujan el informe entero hacia abajo, y la
    pregunta habitual es por el circuito estudiado y sus vecinos, que van visibles.
    """
    if raw_df is None or raw_df.empty or not _COLUMNAS_MINIMAS <= set(raw_df.columns):
        return ""

    from chec_local_interpreter.ranking_circuitos import ranking_circuitos

    tabla = ranking_circuitos(raw_df, start_date, end_date).tabla
    if tabla.empty:
        return ""

    ordenada = tabla.sort_values("posicion")

    def _fila(r) -> str:
        destacada = " class='fila-destacada'" if str(r.circuito) == str(circuito) else ""
        return (
            f"<tr{destacada}>"
            f"<td class='num'>{_num(float(r.posicion))}</td>"
            f"<td>{_escapar(r.circuito)}</td>"
            f"<td>{_escapar(r.rango)}</td>"
            f"<td class='num'>{_num(float(r.vanos_criticos))}</td>"
            f"<td class='num'>{_num(float(r.vanos_con_eventos))}</td>"
            f"<td class='num'>{_num(float(r.uiti_total), 1)}</td>"
            f"</tr>"
        )

    encabezado = (
        "<thead><tr><th>Ubicación</th><th>Circuito</th><th>Clasificación de riesgo</th>"
        "<th>Vanos en Medio-Alto + Alto</th>"
        "<th>Vanos probables de causa de falla</th>"
        "<th>UITI acumulado</th></tr></thead>"
    )

    # El circuito estudiado y sus vecinos inmediatos, visibles sin desplegar nada.
    try:
        indice = [str(c) for c in ordenada["circuito"]].index(str(circuito))
    except ValueError:
        indice = 0
    desde = max(0, indice - 4)
    vecinos = ordenada.iloc[desde:desde + 9]

    filas_vecinas = "".join(_fila(r) for r in vecinos.itertuples())
    filas_todas = "".join(_fila(r) for r in ordenada.itertuples())

    return (
        "<div class='tabla-clasificacion'>"
        f"<table class='tabla-informe'>{encabezado}<tbody>{filas_vecinas}</tbody></table>"
        "<details><summary>Ver los "
        f"{_num(float(len(ordenada)))} circuitos</summary>"
        f"<div class='tabla-desplazable'><table class='tabla-informe'>{encabezado}"
        f"<tbody>{filas_todas}</tbody></table></div></details>"
        "<p class='muted'>La ubicación <b>1</b> es el circuito con más vanos en "
        "Medio-Alto + Alto. Es el mismo número que rotula cada barra de la gráfica de "
        "arriba.</p></div>"
    )


# -------------------------------------------------------------------- tabla ventanas


def tabla_ventanas_html(
    raw_df: pd.DataFrame,
    circuito: str,
    *,
    estudiadas: tuple[str, ...] = (),
) -> str:
    """Las ventanas estudiadas con sus fechas, su UITI, sus registros y sus vanos.

    Estaba como lista narrada por el agente: once frases en prosa donde la pregunta
    ("cual ventana pesa mas") se contesta comparando numeros. La tabla sale de
    `window_series_records`, que es la MISMA rejilla que usan el modelo y el mapa: las
    etiquetas `V1`..`V11` estan fijadas sobre el rango completo de la base y no sobre
    el recorte, asi que la `V1` de aqui es la `V1` de todo lo demas.
    """
    if raw_df is None or raw_df.empty:
        return ""

    from chec_local_interpreter.context_builder import window_series_records

    registros = window_series_records(raw_df, circuito=circuito, estudiadas=estudiadas)
    if not registros:
        return ""

    pico = max(registros, key=lambda r: float(r.get("uv") or 0.0))
    filas = []
    for r in registros:
        marcas = []
        if r.get("estudiada"):
            marcas.append("estudiada a fondo")
        if r["w"] == pico["w"]:
            marcas.append("mayor aporte UITI")
        destacada = " class='fila-destacada'" if r["w"] == pico["w"] else ""
        filas.append(
            f"<tr{destacada}><td>{_escapar(r['w'])}</td>"
            f"<td>{_escapar(r.get('desde', ''))}</td>"
            f"<td>{_escapar(r.get('hasta', ''))}</td>"
            f"<td class='num'>{_num(float(r.get('uv') or 0.0), 1)}</td>"
            f"<td class='num'>{_num(float(r.get('n') or 0))}</td>"
            f"<td class='num'>{_num(float(r.get('vanos') or 0))}</td>"
            f"<td>{_escapar(', '.join(marcas))}</td></tr>"
        )

    # El revisor senalo que "ventana pico" y "ventana de mayor impacto" se leian como
    # dos cosas distintas. Son la misma: la ventana con mas UITI acumulado. Se dice una
    # vez, aqui, y el resto del informe usa un solo nombre.
    nota = (
        "<p class='muted'>La <b>ventana de mayor aporte UITI</b> es la que concentra "
        "más UITI acumulado del período; es a la que el informe llama también ventana "
        "pico, y son la misma. Las ventanas se traslapan quince días entre sí, de modo "
        "que sus valores de UITI <b>no son aditivos</b>: sumar las once contabiliza "
        "varias veces los mismos registros.</p>"
    )
    return (
        "<div class='tabla-ventanas'><table class='tabla-informe'>"
        "<thead><tr><th>Ventana</th><th>Desde</th><th>Hasta</th>"
        "<th>UITI acumulado</th><th>Registros vano-evento</th><th>Vanos</th>"
        "<th></th></tr></thead>"
        f"<tbody>{''.join(filas)}</tbody></table>{nota}</div>"
    )
