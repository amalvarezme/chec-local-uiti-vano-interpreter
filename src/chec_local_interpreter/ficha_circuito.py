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
from typing import Any, Mapping, Sequence

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
    circuito: str | list[str] | tuple[str, ...],
    *,
    start_date: Any = None,
    end_date: Any = None,
) -> str:
    """La clasificacion de criticidad en tabla, con el numero de ubicacion.

    La barra del ranking lleva 208 rotulos de 8 px girados noventa grados: dice donde
    cae el circuito y no deja leer el nombre de ninguno. La tabla dice lo mismo con los
    nombres legibles, y el numero de ubicacion es lo que permite cruzar las dos -- por
    eso la barra tambien lo lleva ahora en su rotulo.

    `circuito` admite un nombre (el informe por circuito) o una lista (el gerencial, que
    resalta los circuitos muestreados del grupo). Son las MISMAS dos formas que acepta
    `plot_ranking_circuitos`: con una sola, la tabla y la figura que la acompana
    marcarian conjuntos distintos sobre los mismos datos.

    Va plegada. Doscientas filas abiertas empujan el informe entero hacia abajo, y la
    pregunta habitual es por los circuitos estudiados y sus vecinos, que van visibles.
    """
    if raw_df is None or raw_df.empty or not _COLUMNAS_MINIMAS <= set(raw_df.columns):
        return ""

    if circuito is None:
        destacados: list[str] = []
    elif isinstance(circuito, str):
        destacados = [circuito] if circuito else []
    else:
        destacados = [str(c) for c in circuito if c]
    conjunto = set(destacados)

    from chec_local_interpreter.ranking_circuitos import ranking_circuitos

    tabla = ranking_circuitos(raw_df, start_date, end_date).tabla
    if tabla.empty:
        return ""

    ordenada = tabla.sort_values("posicion")

    def _fila(r) -> str:
        destacada = " class='fila-destacada'" if str(r.circuito) in conjunto else ""
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

    # Los circuitos estudiados y sus vecinos inmediatos, visibles sin desplegar nada.
    # Con varios destacados, la ventana se abre desde el MEJOR situado de ellos: es el
    # que fija el techo del grupo, y el que un lector busca primero.
    nombres = [str(c) for c in ordenada["circuito"]]
    indices = [nombres.index(c) for c in destacados if c in nombres]
    indice = min(indices) if indices else 0
    desde = max(0, indice - 4)
    vecinos = ordenada.iloc[desde:desde + max(9, len(destacados) + 4)]

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


#: Por que entra cada ventana al estudio, en el MISMO orden en que las aplica
#: `mil_inferencia.seleccionar_ventanas_reporte`. El orden importa: los criterios se
#: aplican sobre lo que queda, asi que una ventana que gana los dos recibe solo el
#: primero y el informe estudia DOS ventanas, no la misma repetida.
CRITERIOS_ESTUDIO: tuple[tuple[str, str], ...] = (
    ("uv", "Mayor UITI acumulado: el momento de mayor impacto del período"),
    ("vanos", "Más vanos tocados: el episodio más extendido del período"),
)
RAZON_ULTIMA = "La última con eventos: cómo está el circuito hoy"
#: Una corrida anterior pudo estudiar otras ventanas. Adjudicarle un criterio que no la
#: eligio seria inventar el motivo, que es peor que no darlo.
RAZON_SIN_CRITERIO = "Estudiada a fondo"


def _orden_ventana(etiqueta: str) -> tuple[int, str]:
    """`V10` va despues de `V9`, no entre `V1` y `V2`.

    Repite la de `mil_inferencia._orden_ventana` a proposito: importarla arrastraria
    torch -- 1,26 s y cientos de MB -- dentro de un modulo que solo pinta HTML.
    """
    resto = str(etiqueta).lstrip("Vv")
    return (int(resto), "") if resto.isdigit() else (10**9, str(etiqueta))


def razones_de_estudio(
    registros: Sequence[Mapping[str, Any]],
    estudiadas: Sequence[str] = (),
) -> dict[str, str]:
    """Por que entro al estudio cada ventana marcada, con los criterios que la eligieron.

    La tabla marcaba "estudiada a fondo" y nada mas: el lector veia tres ventanas
    señaladas entre once sin saber por que esas tres, y el criterio solo vivia en el
    codigo del selector.

    Reconstruirlo aqui es honesto porque usa la MISMA regla sobre los MISMOS numeros. El
    selector elige el maximo GLOBAL de cada criterio, asi que la ventana estudiada con
    mas UITI es necesariamente la de mas UITI de todas: restringir la busqueda a las
    estudiadas da la misma respuesta sin necesidad de volver a abrir el artefacto del
    modelo.

    Devuelve solo las ventanas estudiadas. Una ventana que no encaja en ningun criterio
    -- una corrida vieja, otra seleccion -- se marca sin adjudicarle un motivo falso.
    """
    marcadas = {str(e) for e in estudiadas or ()}
    if not marcadas:
        return {}

    # La ultima del CIRCUITO es la ultima con eventos, que es la que toma
    # `ventanas_de_circuito`: una ventana sin bolsas no es candidata a nada.
    con_eventos = [r for r in registros if float(r.get("uv") or 0.0) > 0]
    razones: dict[str, str] = {}
    if con_eventos:
        ultima = str(con_eventos[-1].get("w"))
        if ultima in marcadas:
            razones[ultima] = RAZON_ULTIMA

    for campo, texto in CRITERIOS_ESTUDIO:
        candidatos = [r for r in con_eventos
                      if str(r.get("w")) in marcadas and str(r.get("w")) not in razones]
        if not candidatos:
            break
        # Mismo desempate que el selector: el criterio, luego el UITI, luego la mas
        # reciente. Sin el ultimo, un empate exacto lo decidiria el orden de las filas.
        mejor = max(candidatos, key=lambda r: (float(r.get(campo) or 0.0),
                                               float(r.get("uv") or 0.0),
                                               _orden_ventana(r.get("w"))))
        razones[str(mejor.get("w"))] = texto

    for w in marcadas:
        razones.setdefault(w, RAZON_SIN_CRITERIO)
    return razones


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
    # La ultima columna dice POR QUE se estudio la ventana, no que se estudio. Ver
    # `razones_de_estudio`: son los mismos tres criterios que la eligieron.
    razones = razones_de_estudio(registros, estudiadas)
    filas = []
    for r in registros:
        motivo = razones.get(str(r["w"]), "")
        destacada = " class='fila-destacada'" if r["w"] == pico["w"] else ""
        filas.append(
            f"<tr{destacada}><td>{_escapar(r['w'])}</td>"
            f"<td>{_escapar(r.get('desde', ''))}</td>"
            f"<td>{_escapar(r.get('hasta', ''))}</td>"
            f"<td class='num'>{_num(float(r.get('uv') or 0.0), 1)}</td>"
            f"<td class='num'>{_num(float(r.get('n') or 0))}</td>"
            f"<td class='num'>{_num(float(r.get('vanos') or 0))}</td>"
            f"<td>{_escapar(motivo)}</td></tr>"
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
        "<th>¿Por qué se estudió?</th></tr></thead>"
        f"<tbody>{''.join(filas)}</tbody></table>{nota}</div>"
    )


# ------------------------------------------------------------------- afectacion


#: Umbrales del tipo de afectacion. Estan aqui, con nombre, y no incrustados en un `if`:
#: son la definicion operativa de "sostenida" y cualquiera que discuta el veredicto
#: discute estos dos numeros.
#:
#: `SOSTENIDA_MIN_VENTANAS` es una FRACCION de la rejilla, no un conteo: el periodo del
#: informe se elige al invocarlo y una rejilla de cinco ventanas no puede exigir ocho.
SOSTENIDA_MIN_VENTANAS = 0.6
#: Por encima de esta fraccion en UNA sola ventana, el periodo lo explica esa ventana.
PUNTUAL_MIN_CONCENTRACION = 0.5


def tipo_de_afectacion(serie) -> dict[str, Any]:
    """Sostenida o puntual, decidido sobre la serie por ventana.

    Se calcula y no se le pide al agente. Es un umbral sobre dos cifras -- en cuantas
    ventanas hubo actividad, y que fraccion del UITI se lleva la mayor --, y un modelo
    contestando eso sobre los mismos numeros puede dar una respuesta distinta en cada
    corrida sin que nada haya cambiado. Ademas se puede discutir: el veredicto viaja con
    las dos cifras que lo sostienen.

    Sin actividad devuelve vacio. Un "puntual" por defecto sobre una serie en cero seria
    afirmar algo sobre un circuito del que no hay nada que decir.
    """
    registros = [r for r in (serie or []) if isinstance(r, dict)]
    valores = [float(r.get("uv") or 0.0) for r in registros]
    total = sum(valores)
    if not registros or total <= 0:
        return {}

    con_actividad = sum(1 for v in valores if v > 0)
    indice_pico = max(range(len(valores)), key=lambda i: valores[i])
    fraccion_pico = valores[indice_pico] / total

    if fraccion_pico >= PUNTUAL_MIN_CONCENTRACION:
        # Una sola ventana explica la mitad o mas del periodo: da igual en cuantas hubo
        # algo, lo que hay que atender es ese episodio.
        tipo = "puntual"
    elif con_actividad >= SOSTENIDA_MIN_VENTANAS * len(registros):
        tipo = "sostenida"
    else:
        # Ni concentrada en una ventana ni repartida por casi todas.
        tipo = "intermitente"

    return {
        "tipo": tipo,
        "ventanas_con_actividad": con_actividad,
        "ventanas_totales": len(registros),
        "ventana_pico": str(registros[indice_pico].get("w") or ""),
        "periodo_pico": str(registros[indice_pico].get("periodo") or ""),
        "uiti_pico": valores[indice_pico],
        "pct_ventana_pico": 100.0 * fraccion_pico,
    }


#: Que significa cada veredicto, en una linea. La palabra sola no dice que hacer.
_LECTURA_AFECTACION = {
    "sostenida": ("el problema está repartido a lo largo del período y no lo explica "
                  "un episodio concreto"),
    "puntual": ("una sola ventana explica la mayor parte del período: el resto del "
                "tiempo el circuito se comporta distinto"),
    "intermitente": ("la actividad ni se reparte por todo el período ni la concentra "
                     "una sola ventana"),
}


def afectacion_html(afectacion: dict[str, Any]) -> str:
    """El veredicto con las dos cifras que lo sostienen, nunca solo el adjetivo."""
    if not afectacion:
        return ""
    tipo = str(afectacion.get("tipo", ""))
    periodo = afectacion.get("periodo_pico")
    detalle_periodo = f", {_escapar(periodo)}" if periodo else ""
    return (
        "<div class='content-box'>"
        f"<p style='margin:0 0 6px 0;'>La afectación del período es "
        f"<b>{_escapar(tipo)}</b>: {_escapar(_LECTURA_AFECTACION.get(tipo, ''))}.</p>"
        f"<p class='muted' style='margin:0;'>Registran actividad "
        f"<b>{_num(float(afectacion.get('ventanas_con_actividad', 0)))}</b> de las "
        f"{_num(float(afectacion.get('ventanas_totales', 0)))} ventanas de la rejilla, "
        f"y la de mayor aporte "
        f"(<b>{_escapar(afectacion.get('ventana_pico', ''))}</b>{detalle_periodo}) "
        f"concentra el <b>{_num(float(afectacion.get('pct_ventana_pico', 0.0)), 1)}%</b> "
        f"del UITI acumulado.</p></div>"
    )
