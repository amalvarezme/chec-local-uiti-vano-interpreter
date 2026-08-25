"""Guardar una corrida del simulador, y volver a ella.

El boton "Guardar" del cuaderno 06 produce DOS archivos que contestan dos
preguntas distintas, y por eso no pueden ser el mismo:

- **Que decidimos** -- un informe HTML autocontenido con las ocho figuras tal
  como quedaron, mas las tres tablas con las que se aprueba una orden de
  trabajo: que vanos con que variables y en que valor, que actividades del
  contrato por vano con su costo, y el UITI medido contra el simulado con su
  porcentaje de mejora.
- **Como vuelvo aqui** -- un registro lo bastante pequenio como para tener
  cientos, que el boton "Cargar" convierte otra vez en un tablero vivo.

## Por que el registro NO guarda las figuras

Todo lo que se ve en pantalla es DERIVADO: sale de correr el modelo MIL sobre
las entradas. Congelar los ocho paneles seria guardar el valor de retorno de una
funcion al lado de sus argumentos -- dos fuentes de verdad que se separan en
cuanto alguien reentrena. El registro guarda las ENTRADAS y un resumen de lo que
salio; cargar vuelve a correr.

Eso obliga a una honestidad extra, y de ahi el `sello`: lleva el sha1 de los
artefactos con los que se corrio. Un registro replayed contra un modelo
reentrenado LO DICE, en vez de producir numeros distintos bajo el mismo nombre.

El resumen viaja igual, y no contradice lo anterior: es lo que permite rearmar
el informe -- y comparar al cargar -- sin un modelo en la sala.

## Por que gzip de JSON

Porque quien audite una decision dentro de dos anios tiene que poder abrir el
archivo sin este programa. Medido sobre una corrida de quince vanos con seis
variables y tres actividades cada uno: 21 KB. Un `pickle` seria mas pequenio,
no lo abre nadie, y ejecuta codigo al leerse. Un `parquet` pide pandas para
mirar tres diccionarios.

## Este modulo no sabe de widgets

Recibe listas de diccionarios y devuelve texto y bytes. El tablero es quien
traduce sus controles a esas listas (`chec_tableros/simulador/tablero.py`) y
quien las vuelve a repartir por la rejilla al cargar. Asi las tablas del informe
se pueden probar sin levantar un kernel.
"""

from __future__ import annotations

import gzip
import html as _html
import json
import re
from typing import Any, Mapping, Sequence

ESQUEMA = 1
"""Version del formato del registro.

Se declara DENTRO del archivo. Sin ella, un registro de hoy leido por el
simulador de manana se interpreta con reglas que ya no son las suyas y falla en
el sitio equivocado -- al repartir los controles, no al abrir el archivo.
"""

EXTENSION = ".simchec.json.gz"
"""La doble extension es deliberada: `.json.gz` le dice a cualquier herramienta
como abrirlo, y `.simchec` le dice a esta aplicacion cuales de los `.json.gz` de
una carpeta son suyos."""

GRANO_CIRCUITO = "(todo el circuito)"
"""La clave bajo la que el simulador guarda los valores cuando NO hay vanos
marcados: la pregunta es entonces por el circuito entero y hay una sola columna
de controles. Es el mismo literal que usa el tablero, y esta aqui para que el
viaje al disco no lo convierta en un fid inventado.
"""

SELLO_DISTINTO = "sello_distinto"
OTRA_VERSION = "otra_version"

CLAVE_MODELO = "modelo MIL"
CLAVE_FEATURES = "variables del modelo"
CLAVE_CATALOGO = "catálogo de variables simulables"
"""Las claves del sello se escriben como se leen en pantalla: el aviso al cargar
las enumera tal cual. Un `mil_vano_ventana_v1.pt` en medio de una frase obliga a
quien decide a traducir un nombre de archivo."""

# Lo que Windows no admite en un nombre de archivo. La etiqueta de ventana del
# tablero lleva dos puntos (`V10: 2024-06-01 a ...`), asi que sin esto un nombre
# que funciona en macOS revienta al guardar en Windows -- y revienta al ESCRIBIR,
# o sea despues de que el panel ya dijo que estaba guardando.
_PROHIBIDOS = re.compile(r'[\\/:*?"<>|\s]+')


# --------------------------------------------------------------------------------
# El registro
# --------------------------------------------------------------------------------


def registro_de_simulacion(
    *,
    circuito: str,
    ventana_i: int,
    ventana_etiqueta: str,
    ventana_periodo: str,
    vanos: Sequence[str],
    variables: Sequence[Mapping[str, Any]],
    actividades: Sequence[Mapping[str, Any]],
    uiti: Sequence[Mapping[str, Any]],
    total_uiti: Mapping[str, Any],
    costo_total: float,
    reduccion: float | None,
    desviacion: float | None,
    cambian: int,
    n_vanos: int,
    sello: Mapping[str, str],
    creado_en: str,
    nombre: str = "",
) -> dict[str, Any]:
    """El registro completo de una corrida, ya en tipos de JSON puro.

    Todo entra como argumento con nombre y nada se deduce aqui: este modulo no
    puede mirar los controles del tablero, y una deduccion suya seria una segunda
    version de lo que el tablero acaba de simular.

    Las tres listas -- `variables`, `actividades`, `uiti` -- son PLANAS y cada
    fila se nombra a si misma (`vano` incluido). Es lo que permite que la misma
    lista sirva para pintar una tabla del informe y para repartir los controles
    al cargar, sin dos representaciones que tengan que coincidir.

    Los campos de presentacion -- la etiqueta de la variable, su grupo, su
    unidad, la descripcion de la actividad -- viajan RESUELTOS dentro del
    registro y no como claves contra un catalogo. Es un archivo de trazabilidad:
    abrirlo dentro de dos anios no puede depender de que el libro de costos de
    entonces siga trayendo la misma fila.
    """
    return {
        "esquema": ESQUEMA,
        "creado_en": str(creado_en),
        "nombre": str(nombre),
        "sello": {str(k): str(v) for k, v in dict(sello).items()},
        "seleccion": {
            "circuito": str(circuito),
            "ventana_i": int(ventana_i),
            "ventana_etiqueta": str(ventana_etiqueta),
            "ventana_periodo": str(ventana_periodo),
            "vanos": [str(v) for v in vanos],
        },
        "variables": [
            {
                "vano": str(f["vano"]),
                "knob_id": str(f["knob_id"]),
                "variable": str(f.get("variable", f["knob_id"])),
                "grupo": str(f.get("grupo", "Sin grupo")),
                "unidad": str(f.get("unidad", "")),
                # El valor conserva su TIPO: un knob categorico guarda su etiqueta
                # y uno numerico su numero. Pasarlo todo a texto obligaria a
                # adivinar al cargar cual de los dos era.
                "valor": _valor_json(f["valor"]),
            }
            for f in variables
        ],
        "actividades": [
            {
                "vano": str(f["vano"]),
                "actividad": str(f["actividad"]),
                "repeticiones": int(f["repeticiones"]),
                "costo_unitario": float(f["costo_unitario"]),
                "subtotal": float(f["subtotal"]),
                "descripcion": str(f.get("descripcion", "")),
            }
            for f in actividades
        ],
        "uiti": [
            {
                "vano": str(f["vano"]),
                "observado": float(f["observado"]),
                "simulado": float(f["simulado"]),
                "error": float(f.get("error", 0.0)),
                "clase_observado": _clase_json(f.get("clase_observado")),
                "clase_simulado": _clase_json(f.get("clase_simulado")),
            }
            for f in uiti
        ],
        "total_uiti": {
            "observado": float(total_uiti.get("observado", 0.0)),
            "simulado": float(total_uiti.get("simulado", 0.0)),
            "error": float(total_uiti.get("error", 0.0)),
        },
        "resumen": {
            "costo_total": float(costo_total),
            "reduccion": None if reduccion is None else float(reduccion),
            "desviacion": None if desviacion is None else float(desviacion),
            "cambian": int(cambian),
            "n_vanos": int(n_vanos),
        },
    }


def _valor_json(valor: Any) -> Any:
    """Un valor de control, en tipos que JSON entiende.

    `numpy.float64` no es serializable y el fallo saldria al ESCRIBIR el archivo:
    o sea, despues de que el panel ya dijo que estaba guardando. Se convierte aqui,
    al armar el registro, que es donde todavia se puede decir que paso.
    """
    if isinstance(valor, bool):
        return bool(valor)
    if isinstance(valor, (int,)):
        return int(valor)
    if hasattr(valor, "item"):          # numpy escalar
        valor = valor.item()
    if isinstance(valor, float):
        return float(valor)
    if isinstance(valor, (int, bool)):
        return valor
    return str(valor)


def _clase_json(clase: Any) -> int | None:
    if clase is None:
        return None
    if hasattr(clase, "item"):
        clase = clase.item()
    try:
        return int(clase)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------------
# Ida y vuelta al disco
# --------------------------------------------------------------------------------


def serializar(registro: Mapping[str, Any]) -> bytes:
    """El registro como gzip de JSON UTF-8.

    `ensure_ascii=False` y no el escapado por defecto: los nombres del contrato
    llevan tilde y `\\u00f3` los deja ilegibles para quien abra el archivo a mano,
    que es justamente el caso de uso que justifica JSON.
    """
    crudo = json.dumps(registro, ensure_ascii=False, sort_keys=False).encode("utf-8")
    # `mtime=0`: sin el, gzip estampa la hora y dos guardados del mismo registro
    # producen bytes distintos. Un archivo que cambia sin que cambie su contenido
    # rompe cualquier comparacion posterior.
    return gzip.compress(crudo, mtime=0)


def deserializar(datos: bytes) -> dict[str, Any]:
    """El registro que hay dentro de `datos`, o `ValueError` explicando por que no.

    Levanta antes que devolver medio registro. Un archivo de otra version, o uno
    que no es del simulador, se detecta AQUI -- donde se puede decir que archivo
    era -- y no mas adelante repartiendo controles contra claves que no existen.
    """
    try:
        registro = json.loads(gzip.decompress(datos).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "No se pudo leer el archivo como una simulacion guardada: se esperaba "
            f"gzip de JSON UTF-8. ({exc})"
        ) from exc
    if not isinstance(registro, dict) or "esquema" not in registro:
        raise ValueError(
            "El archivo no es una simulacion guardada del simulador: no declara "
            "un esquema."
        )
    if int(registro["esquema"]) > ESQUEMA:
        raise ValueError(
            f"El archivo trae el esquema {registro['esquema']} y este simulador "
            f"entiende hasta el {ESQUEMA}. Actualiza el proyecto antes de cargarlo."
        )
    return registro


def nombre_de_archivo(registro: Mapping[str, Any]) -> str:
    """El nombre con el que se guarda: circuito, ventana y fecha, en ese orden.

    Ese orden y no otro porque es el orden en que se busca: primero de que
    circuito era, despues de que periodo, y la fecha desempata entre varias
    corridas del mismo escenario.

    Se limpia de lo que Windows rechaza. La etiqueta de ventana lleva dos puntos
    y un circuito puede traer una barra, y un nombre que funciona en macOS y
    revienta en Windows es un fallo que solo aparece en la maquina del usuario.
    """
    sel = registro["seleccion"]
    fecha = str(registro.get("creado_en", ""))[:19].replace(":", "-")
    trozos = [sel.get("circuito", "circuito"), sel.get("ventana_etiqueta", "V"), fecha]
    return "_".join(_PROHIBIDOS.sub("-", str(t)).strip("-") for t in trozos) + EXTENSION


# --------------------------------------------------------------------------------
# Reponer las entradas al cargar
# --------------------------------------------------------------------------------


def variables_por_vano(registro: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """`{vano: {knob_id: valor}}` -- exactamente la forma que la rejilla del panel
    necesita para abrir cada control en su valor guardado."""
    por_vano: dict[str, dict[str, Any]] = {}
    for fila in registro.get("variables", ()):
        por_vano.setdefault(str(fila["vano"]), {})[str(fila["knob_id"])] = fila["valor"]
    return por_vano


def actividades_por_vano(registro: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """`{vano: {actividad: repeticiones}}` -- la otra mitad de lo que se repone."""
    por_vano: dict[str, dict[str, int]] = {}
    for fila in registro.get("actividades", ()):
        por_vano.setdefault(str(fila["vano"]), {})[str(fila["actividad"])] = int(
            fila["repeticiones"])
    return por_vano


def sello_del_modelo(
    modelo: Any, features: Sequence[str], knobs: Sequence[str] = ()
) -> dict[str, str]:
    """La firma de los artefactos con los que corre ESTE tablero.

    Tres cosas y no una, porque no significan lo mismo al cargar: reentrenar
    cambia todos los numeros; cambiar la lista de features cambia lo que el modelo
    mira; y editar el catalogo de variables simulables solo cambia que controles
    ofrece el panel -- las variables que sobreviven siguen dando lo mismo.

    Se firma el modelo EN MEMORIA y no el archivo del que salio. El tablero corre
    con `data/models/` en el cuaderno y con `paquete/` en la aplicacion, y no
    conoce ninguna de las dos rutas: pedirle una seria meterle un cuarto camino
    que mantener. Lo que se quiere saber -- son los mismos pesos -- lo contesta el
    `state_dict`, y ademas lo contesta igual en los dos sitios.

    Un artefacto que no se deje mirar deja su firma VACIA y el guardado sigue: el
    sello es una cortesia para quien cargue manana, y perder la simulacion de hoy
    por no poder firmarla seria un pesimo negocio. Una firma vacia no dispara el
    aviso de `veredicto_del_sello`, porque "no se pudo calcular" no es "cambio".
    """
    import hashlib

    def _firma_del_modelo() -> str:
        estado = getattr(modelo, "state_dict", None)
        if estado is None:
            estado = getattr(getattr(modelo, "model", None), "state_dict", None)
        if estado is None:
            return ""
        try:
            pesos = estado()
            h = hashlib.sha1()
            # Ordenado por clave: `state_dict` no garantiza orden entre versiones de
            # torch, y un sello que cambiara por eso avisaria de un reentrenamiento
            # que nunca ocurrio.
            for clave in sorted(pesos):
                h.update(str(clave).encode("utf-8"))
                h.update(pesos[clave].detach().cpu().numpy().tobytes())
            return h.hexdigest()
        except Exception:  # noqa: BLE001 -- el sello nunca puede tumbar un guardado
            return ""

    def _firma_de_lista(valores: Sequence[str]) -> str:
        return hashlib.sha1(
            "\n".join(str(v) for v in valores).encode("utf-8")).hexdigest()

    return {
        CLAVE_MODELO: _firma_del_modelo(),
        CLAVE_FEATURES: _firma_de_lista(features),
        CLAVE_CATALOGO: _firma_de_lista(sorted(str(k) for k in knobs)),
    }


def veredicto_del_sello(
    registro: Mapping[str, Any], sello_actual: Mapping[str, str]
) -> dict[str, str] | None:
    """Que hay que advertirle a quien carga, o `None` si no hay nada.

    El defecto que esto impide: cargar una simulacion de julio contra el modelo
    de agosto devuelve numeros distintos bajo el mismo nombre y sin una sola
    senal. Se AVISA y se carga igual -- bloquearlo dejaria sin abrir un registro
    que sigue siendo la mejor descripcion de lo que se decidio ese dia.
    """
    if int(registro.get("esquema", ESQUEMA)) < ESQUEMA:
        return {
            "clase": OTRA_VERSION,
            "mensaje": (
                f"Esta simulación se guardó con la versión {registro['esquema']} del "
                f"formato y este simulador usa la {ESQUEMA}. Se carga igual, pero "
                "revisa que el escenario quedó como esperabas."
            ),
        }
    guardado = dict(registro.get("sello") or {})
    # Una firma VACIA -- de un lado o del otro -- significa "no se pudo calcular", y
    # eso no es "cambio". Contarla como diferencia pondria un aviso de modelo
    # reentrenado sobre un artefacto que nadie toco.
    cambiados = sorted(
        nombre for nombre, sha in guardado.items()
        if sha and sello_actual.get(nombre) and str(sello_actual[nombre]) != str(sha)
    )
    if not cambiados:
        return None
    return {
        "clase": SELLO_DISTINTO,
        "mensaje": (
            "Esta simulación se corrió con otra versión de "
            + ", ".join(cambiados)
            + ". Se vuelve a simular con la actual, así que los números pueden no "
            "coincidir con los del informe que se guardó ese día."
        ),
    }


# --------------------------------------------------------------------------------
# El informe HTML
# --------------------------------------------------------------------------------


def _esc(texto: Any) -> str:
    """Lo que viene del libro de costos lo edita una persona en Excel. Un `<`
    suelto rompio ya una vez el panel del simulador, y aqui romperia el informe
    entero -- que es ademas lo que se archiva."""
    return _html.escape(str(texto), quote=True)


def _miles(valor: float) -> str:
    """Formato espaniol: punto de miles y sin decimales. Es como se leen los pesos
    en el contrato, y mezclarlo con el formato ingles en el mismo documento hace
    dudar de cada cifra."""
    return f"{valor:,.0f}".replace(",", ".")


def _decimal(valor: float, cifras: int = 1) -> str:
    entero = f"{valor:,.{cifras}f}"
    return entero.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _porcentaje(observado: float, simulado: float) -> tuple[str, str]:
    """El cambio relativo y el color con el que se lee.

    Devuelve texto y color, y no un numero, porque hay un caso sin numero: un
    vano medido en 0 existe -- es un vano sin UITI acumulado en la ventana -- y
    su porcentaje no esta definido. Decir "sin base" es una respuesta; un
    `ZeroDivisionError` al generar el informe no lo es, y menos despues de que
    el panel dijo que estaba guardando.
    """
    if not observado:
        return "sin base", "#5b4a48"
    cambio = (observado - simulado) / observado * 100.0
    if cambio > 0:
        return f"baja {_decimal(cambio)} %", "#15803d"
    if cambio < 0:
        return f"sube {_decimal(-cambio)} %", "#b91c1c"
    return "igual", "#5b4a48"


_ESTILO = """
  :root { color-scheme: light; }
  body { font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
         color: #2b2b2b; background: #ffffff; margin: 0; padding: 24px; }
  h1 { font-size: 22px; margin: 0 0 4px 0; }
  h2 { font-size: 16px; margin: 28px 0 6px 0; border-left: 4px solid rgb(0,128,36);
       padding-left: 8px; }
  .meta { font-size: 13px; color: #5b4a48; margin-bottom: 18px; }
  .meta b { color: #2b2b2b; }
  .nota { font-size: 12px; color: #5b4a48; margin: 4px 0 10px 0; max-width: 900px; }
  /* Las tablas de contrato son anchas -- la descripcion de una actividad llega a
     1.166 caracteres -- y la pagina no puede scrollear a lo ancho: cada tabla
     scrollea dentro de su propia caja. */
  .caja-tabla { overflow-x: auto; }
  table { border-collapse: collapse; font-size: 12px; margin-bottom: 6px; }
  th, td { border: 1px solid #cfe3ac; padding: 4px 8px; text-align: left;
           vertical-align: top; }
  th { background: #f3f8ec; font-weight: 600; }
  td.num, th.num { text-align: right; white-space: nowrap; }
  tr.total td { font-weight: 700; background: #f3f8ec; }
  .vacio { font-size: 12px; color: #5b4a48; font-style: italic; }
  .desc { max-width: 420px; white-space: pre-wrap; color: #5b4a48; }
"""


def _tabla_variables(registro: Mapping[str, Any]) -> str:
    filas = registro.get("variables") or ()
    if not filas:
        return ('<p class="vacio">La simulación corrió sin fijar ninguna variable: '
                'todos los controles quedaron en el valor actual del vano.</p>')
    cuerpo = "".join(
        "<tr>"
        f"<td>{_esc(f['vano'])}</td>"
        f"<td>{_esc(f['variable'])}</td>"
        f"<td>{_esc(f['grupo'])}</td>"
        f"<td class=\"num\">{_esc(_valor_legible(f['valor']))}</td>"
        f"<td>{_esc(f.get('unidad') or '')}</td>"
        "</tr>"
        for f in filas
    )
    return (
        '<div class="caja-tabla"><table>'
        "<thead><tr><th>Vano</th><th>Variable</th><th>Grupo</th>"
        '<th class="num">Valor fijado</th><th>Unidad</th></tr></thead>'
        f"<tbody>{cuerpo}</tbody></table></div>"
    )


def _valor_legible(valor: Any) -> str:
    if isinstance(valor, bool):
        return "sí" if valor else "no"
    if isinstance(valor, (int, float)):
        return _decimal(float(valor), 0 if float(valor).is_integer() else 2)
    return str(valor)


def _tabla_actividades(registro: Mapping[str, Any]) -> str:
    """Una tabla POR VANO y no una sola con el vano como columna.

    El plan se aprueba vano por vano: el jefe de zona mira una cuadrilla, un
    vano y su lista de obras, y una tabla corrida de cincuenta renglones obliga
    a reconstruir mentalmente esos grupos en cada lectura. Cada bloque cierra con
    su subtotal, que es la cifra con la que se compara un vano contra otro.
    """
    filas = registro.get("actividades") or ()
    if not filas:
        return ('<p class="vacio">La simulación no lleva actividades de contrato: '
                'se estimó el efecto sin costear la obra.</p>')
    por_vano: dict[str, list[Mapping[str, Any]]] = {}
    for f in filas:
        por_vano.setdefault(str(f["vano"]), []).append(f)

    bloques = []
    for vano, renglones in por_vano.items():
        subtotal = sum(float(r["subtotal"]) for r in renglones)
        cuerpo = "".join(
            "<tr>"
            f"<td>{_esc(r['actividad'])}</td>"
            f"<td class=\"num\">{int(r['repeticiones'])}</td>"
            f"<td class=\"num\">{_miles(float(r['costo_unitario']))}</td>"
            f"<td class=\"num\">{_miles(float(r['subtotal']))}</td>"
            f"<td class=\"desc\">{_esc(r.get('descripcion') or '')}</td>"
            "</tr>"
            for r in renglones
        )
        bloques.append(
            f"<h3 style=\"font-size:13px;margin:14px 0 4px 0;\">Vano {_esc(vano)}</h3>"
            '<div class="caja-tabla"><table>'
            '<thead><tr><th>Actividad</th><th class="num">Intervenciones</th>'
            '<th class="num">Costo unitario (COP)</th>'
            '<th class="num">Costo total (COP)</th><th>Descripción</th></tr></thead>'
            f"<tbody>{cuerpo}"
            f'<tr class="total"><td>Subtotal del vano</td><td class="num"></td>'
            f'<td class="num"></td><td class="num">{_miles(subtotal)}</td>'
            "<td></td></tr>"
            "</tbody></table></div>"
        )
    total = float(registro.get("resumen", {}).get("costo_total", 0.0))
    bloques.append(
        f'<p style="font-size:14px;margin-top:14px;"><b>Costo total de la '
        f"intervención: {_miles(total)} COP</b></p>"
    )
    return "".join(bloques)


def _tabla_uiti(registro: Mapping[str, Any]) -> str:
    filas = registro.get("uiti") or ()
    if not filas:
        return ('<p class="vacio">La corrida no dejó ningún vano con UITI medido en la '
                'ventana activa, así que no hay nada que contrastar.</p>')
    cuerpo = ""
    for f in filas:
        texto, color = _porcentaje(float(f["observado"]), float(f["simulado"]))
        cuerpo += (
            "<tr>"
            f"<td>{_esc(f['vano'])}</td>"
            f"<td class=\"num\">{_decimal(float(f['observado']))}</td>"
            f"<td class=\"num\">{_decimal(float(f['simulado']))}"
            f" &plusmn; {_decimal(float(f.get('error', 0.0)))}</td>"
            f'<td class="num" style="color:{color};">{texto}</td>'
            "</tr>"
        )
    total = registro.get("total_uiti") or {}
    t_obs, t_sim = float(total.get("observado", 0.0)), float(total.get("simulado", 0.0))
    texto, color = _porcentaje(t_obs, t_sim)
    cuerpo += (
        '<tr class="total">'
        "<td>Total de los vanos simulados</td>"
        f'<td class="num">{_decimal(t_obs)}</td>'
        f'<td class="num">{_decimal(t_sim)} &plusmn; '
        f'{_decimal(float(total.get("error", 0.0)))}</td>'
        f'<td class="num" style="color:{color};">{texto}</td>'
        "</tr>"
    )
    return (
        '<div class="caja-tabla"><table>'
        '<thead><tr><th>Vano</th><th class="num">UITI medido</th>'
        '<th class="num">UITI simulado</th>'
        '<th class="num">Mejora / subida</th></tr></thead>'
        f"<tbody>{cuerpo}</tbody></table></div>"
    )


def _linea_de_reduccion(resumen: Mapping[str, Any]) -> str:
    """La cifra que el informe viene a producir, con el verbo que le corresponde.

    `reduccion` es `medido - simulado` y puede salir NEGATIVA: la intervencion
    simulada empeora el UITI de esos vanos, y eso es un resultado legitimo -- no
    todo escenario mejora. Publicado como "baja -59,4" se lee como una errata y
    esconde justo el desenlace que hay que ver.

    El `+-` no es adorno estadistico: es el desfase acumulado del modelo, y en estos
    datos puede ser del orden de la propia diferencia. Cuando la tapa, se DICE, en
    vez de dejar publicada una mejora que el margen no sostiene.
    """
    reduccion = resumen.get("reduccion")
    if reduccion is None:
        return "La corrida no dejó una reducción comparable de UITI."
    reduccion = float(reduccion)
    desviacion = float(resumen.get("desviacion") or 0.0)
    verbo = "baja" if reduccion >= 0 else "sube"
    linea = (f"El UITI acumulado de los vanos intervenidos {verbo} "
             f"<b>{_decimal(abs(reduccion))}</b> &plusmn; {_decimal(desviacion)}.")
    if desviacion >= abs(reduccion):
        linea += (" El desfase del modelo es mayor que el cambio: esta corrida "
                  "<b>no sostiene</b> una diferencia en un sentido ni en el otro.")
    return linea


def informe_html(registro: Mapping[str, Any], *, figuras_html: str) -> str:
    """El informe completo: las figuras de la corrida y sus tres tablas.

    `figuras_html` llega ya renderizado por quien tiene la figura -- el tablero
    --, con plotly.js EMBEBIDO. Este modulo no importa plotly: se prueba sin el,
    y el informe no depende de que el equipo tenga internet al abrirlo, que es
    justo el caso de un HTML descargado del Volume de Databricks y abierto en un
    portatil en campo.
    """
    sel = registro.get("seleccion", {})
    res = registro.get("resumen", {})
    linea_reduccion = _linea_de_reduccion(res)
    n_marcados = len(sel.get("vanos") or ())
    n_puntuados = int(res.get("n_vanos", 0))
    # DOS cuentas y no una. Los vanos marcados son el plan; los puntuados son
    # aquellos con eventos en la ventana activa, que es lo unico que el modelo puede
    # puntuar -- medido sobre 30 circuitos, solo el 21% de las casillas de vano los
    # tienen. Publicar solo la segunda ponia "Vanos simulados: 2" encima de una tabla
    # de quince, y se lee como si trece se hubieran perdido.
    linea_vanos = (
        f"<b>Vanos marcados:</b> {n_marcados} &nbsp;|&nbsp; "
        f"<b>Con eventos en la ventana (los que el modelo puntúa):</b> {n_puntuados}"
        if n_marcados else
        f"<b>Vanos puntuados:</b> {n_puntuados} (sin marcar: todo el circuito)"
    )
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Simulación {_esc(sel.get('circuito', ''))} {_esc(sel.get('ventana_etiqueta', ''))}</title>
<style>{_ESTILO}</style>
</head>
<body>
<h1>Simulador de criticidad por vano &mdash; corrida guardada</h1>
<div class="meta">
  <b>Circuito:</b> {_esc(sel.get('circuito', ''))} &nbsp;|&nbsp;
  <b>Ventana:</b> {_esc(sel.get('ventana_etiqueta', ''))}
  ({_esc(sel.get('ventana_periodo', ''))}) &nbsp;|&nbsp;
  {linea_vanos} &nbsp;|&nbsp;
  <b>Cambian de grupo:</b> {int(res.get('cambian', 0))} &nbsp;|&nbsp;
  <b>Guardada:</b> {_esc(registro.get('creado_en', ''))}
</div>
<p class="nota">{linea_reduccion}
El UITI simulado lo <b>estima el modelo MIL</b> y el medido sale de la base de eventos:
son cantidades de naturaleza distinta, y por eso cada valor simulado viaja con el
desfase del modelo en la base de ese mismo vano (&plusmn;). Sin ese margen, el sesgo
del modelo se leería como ahorro.</p>

<h2>Vanos y variables simuladas</h2>
<p class="nota">Cada renglón es un control del panel abierto en el valor con el que se
simuló ese vano. Las variables de <b>Intervención</b> son lo que se hace; las de
<b>Escenario</b>, las condiciones bajo las que se evalúa.</p>
{_tabla_variables(registro)}

<h2>Actividades de contrato por vano</h2>
<p class="nota">El costo sale de la lista de precios del contrato, no del modelo. Marcar
una actividad no mueve ninguna variable: el panel pone lado a lado el efecto simulado y
el costo cotizado del plan, y el puente entre los dos lo pone quien decide.</p>
{_tabla_actividades(registro)}

<h2>UITI medido contra UITI simulado</h2>
{_tabla_uiti(registro)}

<h2>Figuras de la corrida</h2>
<p class="nota">Los ocho paneles viajan dentro de este archivo y se dibujan sin conexión.
Lo único que se descarga es el <b>mapa de fondo</b> de las dos primeras figuras: sin
internet los vanos se dibujan igual, sobre fondo vacío.</p>
{figuras_html}
</body>
</html>
"""
