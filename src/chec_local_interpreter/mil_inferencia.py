"""La capa predictiva del reporte, sobre el modelo MIL por bolsas del cuaderno 05.

Sustituye al camino MGCECDL, y lo que cambia no es el algoritmo sino la UNIDAD.
MGCECDL puntuaba una FILA -- un evento --; el MIL puntua una BOLSA, la celda
(vano, ventana) sobre la que el cuaderno 04 define la criticidad y sobre la que el
simulador del 06 opera. Mientras el informe hablaba de filas y el tablero de bolsas,
los dos contestaban la misma pregunta con modelos distintos y sin manera de
reconciliarlos: un vano podia salir critico en uno y no en el otro sin que nada en
pantalla lo explicara.

Todo aqui se mide sobre UITI acumulado, que es lo que el modelo predice. El conteo de
eventos NO entra: es un EJE del espacio KMeans que define la clase, no una salida del
modelo, y pedirle que lo explique seria pedirle una magnitud que no produce. La
frecuencia sigue en el informe, pero como dato descriptivo del historiador.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from chec_local_interpreter.config import PROJECT_ROOT
from chec_local_interpreter.glosario_variables import nombre_con_codigo
# El catalogo del panel, que es lo que acota los valores que el diagnostico puede
# PROPONER. Sin el, el informe recomienda obra que el tablero no deja pedir -- "2,37
# fases", una altura de 6,625 m -- y a la vez se pierde lo que si es ejecutable. Se lee
# con cache por fecha de modificacion, asi que llamarlo por corrida no cuesta.
from chec_local_interpreter.simulador_variables import catalogo_simulacion

RUTA_MODELO_MIL = PROJECT_ROOT / "data" / "models" / "mil_vano_ventana_v1.pt"
RUTA_BOLSAS_MIL = PROJECT_ROOT / "data" / "derived" / "bolsas_mil_full.joblib"

# Los mismos que el panel del cuaderno 06, y por los mismos motivos medidos alli:
# nueve puntos porque 10 de los 15 controles numericos tienen su mejor valor en el
# INTERIOR del rango, y cuatro pasos porque en Medio-Alto y Alto ninguna variable sola
# alcanza el grupo Bajo.
PUNTOS_REJILLA = 9
MAX_PASOS_PLAN = 4
# El diagnostico mira PRIMERO el grupo Alto y completa con Medio-Alto. Los de abajo no
# entran: la pregunta es por donde empezar, y un vano en Medio no es por donde se
# empieza mientras queden vanos en Alto sin atender.
GRUPOS_DIAGNOSTICO = (3, 2)
TOP_VANOS_DIAGNOSTICO = 15
TOP_VARIABLES = 10

# El informe estudia TRES ventanas, no las once que tiene el cache de bolsas. Recorrerlas
# todas cuesta ~3,6 s por ventana y produce once escenarios que nadie lee enteros; tres
# es lo que sostiene el relato "como esta hoy y que lo trajo hasta aqui".
VENTANAS_REPORTE = 3

METRICA = "uiti_acumulado"
UNIDAD = "bolsa (vano, ventana)"


@dataclass
class RecursosMIL:
    """Lo que la capa predictiva necesita cargado una sola vez por corrida."""

    modelo: Any
    X_inst: np.ndarray
    features: Sequence[str]
    bag_index: Any
    knobs: Sequence[Any]
    label_encoders: Mapping[str, Any] = field(default_factory=dict)
    max_values_imputed: Mapping[str, Any] = field(default_factory=dict)
    grupos_por_knob: Mapping[str, str] = field(default_factory=dict)


def cargar_recursos_mil(
    *,
    ruta_modelo: str | Path | None = None,
    ruta_bolsas: str | Path | None = None,
    knobs: Sequence[Any] | None = None,
) -> RecursosMIL | None:
    """Carga el modelo y el cache de bolsas del cuaderno 05, en solo lectura.

    Devuelve `None` cuando falta cualquiera de los dos artefactos -- la misma forma de
    hueco que usaba el camino MGCECDL, para que el que llama degrade en vez de reventar.
    """
    import joblib

    from chec_impacto.models.mil_persistencia import cargar_modelo_mil

    modelo_path = Path(ruta_modelo or RUTA_MODELO_MIL)
    bolsas_path = Path(ruta_bolsas or RUTA_BOLSAS_MIL)
    if not modelo_path.exists() or not bolsas_path.exists():
        return None

    bolsas = joblib.load(bolsas_path)
    # `float32` y no el `float64` del artefacto: los pesos del modelo son float32, asi
    # que la conversion ocurria igual en cada llamada y la mitad de cada numero se
    # descartaba. Medido en el cuaderno 06: la clase y el UITI salen identicos bit a
    # bit, y la matriz baja de 184,7 a 92,4 MB.
    X_inst = np.asarray(bolsas["X"], dtype=np.float32)
    features = list(bolsas["features"])
    bag_index = bolsas["bag_index"]
    del bolsas

    modelo = cargar_modelo_mil(modelo_path, device="cpu", features_esperadas=features)
    return RecursosMIL(
        modelo=modelo,
        X_inst=X_inst,
        features=features,
        bag_index=bag_index,
        knobs=list(knobs or []),
    )


def knobs_desde_datos(datos: Mapping[str, Any]) -> tuple[list[Any], dict[str, str]]:
    """El catalogo de controles del informe, heredado del panel del cuaderno 06.

    Devuelve `(knobs, grupos)`, ya SIN las variables refutadas. El panel no las ofrece
    porque presentarlas junto a la poda invita a simular que se mueve un vano de sitio,
    y el informe hereda ese mismo catalogo en vez de construir uno propio: dos listas de
    palancas para el mismo modelo se separan en cuanto alguien edita una sola.

    Quitarlas del catalogo NO las saca de la simulacion: un override solo se escribe si
    se fija, asi que entran al modelo con el valor observado de cada vano. Lo unico que
    se pierde es poder moverlas.
    """
    from chec_local_interpreter.simulador_variables import GRUPO_POR_KNOB, knobs_simulables
    from chec_local_interpreter.vano_controls import build_knobs

    knobs = build_knobs(
        feature_names=list(datos["features"]),
        original_feature_df=datos["Xdata"],
        label_encoders=datos.get("label_encoders", {}),
        max_values_imputed=datos.get("max_values_imputed", {}),
    )
    simulables = knobs_simulables(knobs)
    return simulables, {k.id: GRUPO_POR_KNOB[k.id] for k in simulables
                        if k.id in GRUPO_POR_KNOB}


RUTA_CATALOGO_CONTROLES = PROJECT_ROOT / "data" / "derived" / "catalogo_controles_mil.joblib"
_VERSION_CATALOGO = 1


@dataclass
class CatalogoControles:
    """Los controles del informe y lo que hace falta para moverlos.

    Los cuatro campos viajan juntos porque el barrido los necesita juntos: sin
    `label_encoders` un control categorico no se puede expandir y
    `relevancia_hacia_uiti_minimo` lo salta EN SILENCIO, dejando al conductor y al
    calibre del neutro fuera del ranking sin decir por que.
    """

    knobs: list[Any]
    grupos: dict[str, str]
    label_encoders: Mapping[str, Any]
    max_values_imputed: Mapping[str, Any]


def catalogo_de_controles(
    data_path: str | Path,
    variables_path: str | Path,
    *,
    cache_path: str | Path | None = None,
) -> CatalogoControles:
    """El catalogo de controles, cacheado en disco entre corridas.

    Construirlo cuesta `procesar_dataset_completo` sobre el CSV entero -- MEDIDO: 2,3 s
    y un pico de 2,3 GB -- para producir 18 knobs con sus encoders y sus maximos
    imputados. Ese resultado cabe en 2,6 KB, no depende del circuito ni de la ventana, y
    solo cambia cuando cambian los archivos fuente. Pagarlo en cada `/report` es leer la
    base completa para consultar una tabla de 18 filas.

    El cache se invalida por (tamano, fecha de modificacion) de los archivos fuente. Un
    cache que sobrevive a un cambio del CSV es peor que no tener cache: el informe
    seguiria describiendo rangos de una base que ya no existe y nada lo diria.

    Cualquier falla del cache -- corrupto, de una version anterior, o un directorio de
    solo lectura -- degrada a "esta corrida lo paga entero", nunca a un informe que no
    sale.
    """
    import joblib

    data_path = Path(data_path)
    variables_path = Path(variables_path)
    destino = Path(cache_path) if cache_path is not None else RUTA_CATALOGO_CONTROLES
    clave = _clave_catalogo(data_path, variables_path)

    if destino.exists():
        try:
            guardado = joblib.load(destino)
            if (isinstance(guardado, dict) and guardado.get("clave") == clave
                    and isinstance(guardado.get("catalogo"), CatalogoControles)):
                return guardado["catalogo"]
        except Exception:  # noqa: BLE001 - joblib truncado, pickle de otra version, permisos
            pass

    try:
        catalogo = _construir_catalogo_controles(data_path, variables_path)
    except Exception as exc:  # noqa: BLE001 - base incompatible con Variables_seleccion.xlsx
        # Sin esta guarda, una corrida CON modelo sobre una base incompatible revienta,
        # mientras que la misma corrida SIN modelo sale entera: el informe se caia por la
        # pieza que existe para hacerlo mas completo. El hueco ya tiene forma declarada --
        # un catalogo vacio produce `sin_controles: true` en la relevancia, que el informe
        # sabe presentar como "no se le paso el catalogo" y no como "ninguna variable
        # mueve este vano". NO se cachea: dejaria el informe sin palancas para siempre,
        # incluso despues de arreglar la base.
        warnings.warn(
            f"No se pudo construir el catalogo de controles: {exc}. El informe sale sin "
            "palancas simulables para esta corrida.",
            stacklevel=2,
        )
        return CatalogoControles(knobs=[], grupos={}, label_encoders={},
                                 max_values_imputed={})
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"clave": clave, "catalogo": catalogo}, destino, compress=3)
    except Exception:  # noqa: BLE001 - no poder escribir el cache no es un fallo del informe
        pass
    return catalogo


def _clave_catalogo(data_path: Path, variables_path: Path) -> tuple:
    """Identidad de las fuentes del catalogo, incluida la tabla que declara que se
    puede simular: los grupos Intervencion/Escenario salen de ella, asi que editarla
    tiene que invalidar el cache igual que editar el CSV."""
    from chec_local_interpreter.simulador_variables import ruta_variables_simular

    def _huella(ruta: Path) -> tuple:
        try:
            estado = ruta.stat()
            return (str(ruta), estado.st_size, estado.st_mtime_ns)
        except OSError:
            return (str(ruta), None, None)

    return (_VERSION_CATALOGO, _huella(data_path), _huella(variables_path),
            _huella(Path(ruta_variables_simular())))


def _construir_catalogo_controles(
    data_path: Path, variables_path: Path
) -> CatalogoControles:
    """La construccion cara: el dataset completo, una sola vez, para 18 filas."""
    import io
    from contextlib import redirect_stdout

    from chec_impacto.data import procesar_dataset_completo

    with redirect_stdout(io.StringIO()):
        datos = procesar_dataset_completo(
            path_clima=Path(data_path),
            path_variables_seleccion=Path(variables_path),
            use_sampling=False,
            min_samples_per_codigo=5,
            target="UITI_VANO",
            filtro_uiti_max=None,
            ventana_climatica_horas=12,
        )

    knobs, grupos = knobs_desde_datos(datos)
    return CatalogoControles(
        knobs=knobs,
        grupos=grupos,
        label_encoders=datos.get("label_encoders", {}),
        max_values_imputed=datos.get("max_values_imputed", {}),
    )


def aplicar_catalogo(recursos: RecursosMIL, catalogo: CatalogoControles) -> RecursosMIL:
    """Cuelga el catalogo de los recursos, que es como el barrido lo consume."""
    recursos.knobs = list(catalogo.knobs)
    recursos.grupos_por_knob = dict(catalogo.grupos)
    recursos.label_encoders = catalogo.label_encoders
    recursos.max_values_imputed = catalogo.max_values_imputed
    return recursos


def _seleccion(recursos: RecursosMIL, *, circuito: str, ventana: str) -> dict[str, Any]:
    from chec_local_interpreter.mil_simulador_015 import seleccionar_bolsas

    return seleccionar_bolsas(recursos.bag_index, circuito=str(circuito),
                              ventana=str(ventana))


def relevancia_de_circuito(
    recursos: RecursosMIL,
    *,
    circuito: str,
    ventana: str,
    top: int = TOP_VARIABLES,
) -> dict[str, Any]:
    """Que variables pueden bajar el UITI de cada vano del circuito, y cuanto.

    Una sola pasada por el circuito completo en esa ventana: `relevancia_hacia_uiti_minimo`
    cuesta `1 + puntos * K` evaluaciones para TODA la seleccion, no una tanda por vano.
    """
    from chec_local_interpreter.mil_simulador_015 import relevancia_hacia_uiti_minimo

    # El barrido recorre los CONTROLES. Sin catalogo devuelve cada vano con la lista
    # de variables vacia, que se lee como "ninguna variable mueve este vano" cuando en
    # realidad es "no se le paso el catalogo". Se declara en el resultado en vez de
    # dejar que el informe lo interprete al reves.
    cabecera = {
        "metrica": METRICA,
        "unidad": UNIDAD,
        "circuito": str(circuito),
        "ventana": str(ventana),
        "n_controles": len(recursos.knobs),
        "sin_controles": not recursos.knobs,
    }
    seleccion = _seleccion(recursos, circuito=circuito, ventana=ventana)
    if not int(seleccion.get("n_bolsas", 0)):
        return {**cabecera, "vanos": {}}

    crudo = relevancia_hacia_uiti_minimo(
        recursos.modelo,
        recursos.X_inst,
        seleccion=seleccion,
        feature_names=recursos.features,
        knobs=recursos.knobs,
        top=int(top),
        puntos=PUNTOS_REJILLA,
        grupos=dict(recursos.grupos_por_knob) or None,
        label_encoders=recursos.label_encoders,
        max_values_imputed=recursos.max_values_imputed,
        catalogo=catalogo_simulacion(),
    )

    vanos: dict[str, Any] = {}
    for fid, entrada in crudo.items():
        vanos[str(fid)] = {
            "u_base": entrada["u_base"],
            "clase_base": entrada["clase_base"],
            "ya_en_clase_minima": entrada["ya_en_clase_minima"],
            # `n_obs` se conserva porque es lo que fija la clase junto al UITI, pero
            # NO se ofrece como magnitud explicable: no es una salida del modelo.
            "n_obs_observado": entrada["n_obs"],
            "variables": [
                {
                    "knob_id": fila["knob_id"],
                    "label": fila["label"],
                    "grupo": fila["grupo"],
                    "valor_optimo": fila["valor"],
                    "u_base": entrada["u_base"],
                    "u_min": fila["u_optimo"],
                    "caida": fila["caida_log"],
                    "avance": fila["avance"],
                    "alcanza": fila["alcanza"],
                }
                for fila in entrada["filas"]
            ],
        }
    return {**cabecera, "vanos": vanos}


GRUPO_INTERVENCION = "Intervencion"
GRUPO_ESCENARIO = "Escenario"
GRUPO_SIN_CLASIFICAR = "Sin clasificar"
GRUPOS_VARIABLES = (GRUPO_INTERVENCION, GRUPO_ESCENARIO, GRUPO_SIN_CLASIFICAR)


def resumen_variables_por_grupo(
    relevancia: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Que variables ayudan mas a bajar de grupo, separadas en obra y escenario.

    Dos bloques y no una lista: el informe sustenta una ORDEN DE TRABAJO, y una racha de
    viento presentada junto a la poda en la misma tabla ordenada por caida de UITI se lee
    como igual de accionable. La climatica no desaparece -- describe el escenario en que
    ocurre el problema, que es informacion real --, pero va rotulada como lo que es.

    Dentro de cada bloque manda `n_vanos_alcanza`: en cuantos vanos ESA SOLA variable
    basta para caer al grupo mas bajo. Ordenar por caida de UITI responde a "que baja mas
    el numero", que no es la pregunta: una variable que baja mucho sin cruzar ninguna
    frontera de grupo no cambia ninguna decision.

    `avance` viene como `None` cuando el vano ya esta en el grupo mas bajo o cuando ese
    grupo es inalcanzable con sus eventos -- ahi no hay camino que medir. Esos vanos se
    EXCLUYEN de la mediana en vez de contar como cero: un cero dice "esta variable no
    avanza nada" y lo que pasa es que no hay nada que avanzar.
    """
    acumulado: dict[str, dict[str, Any]] = {}
    for entrada in (relevancia or {}).get("vanos", {}).values():
        ya_en_minima = bool(entrada.get("ya_en_clase_minima"))
        for fila in entrada.get("variables", []) or []:
            knob_id = str(fila.get("knob_id"))
            registro = acumulado.setdefault(knob_id, {
                "knob_id": knob_id,
                "label": fila.get("label") or knob_id,
                "grupo": fila.get("grupo") or GRUPO_SIN_CLASIFICAR,
                "n_vanos": 0,
                "n_vanos_alcanza": 0,
                "_avances": [],
                "_caidas": [],
                "_valores": [],
            })
            registro["n_vanos"] += 1
            if fila.get("alcanza") and not ya_en_minima:
                registro["n_vanos_alcanza"] += 1
            avance = fila.get("avance")
            if isinstance(avance, (int, float)) and not isinstance(avance, bool):
                registro["_avances"].append(float(avance))
            caida = fila.get("caida")
            if isinstance(caida, (int, float)) and not isinstance(caida, bool):
                registro["_caidas"].append(float(caida))
            if fila.get("valor_optimo") is not None:
                registro["_valores"].append(fila["valor_optimo"])

    salida: dict[str, list[dict[str, Any]]] = {g: [] for g in GRUPOS_VARIABLES}
    for registro in acumulado.values():
        salida.setdefault(registro["grupo"], []).append({
            "knob_id": registro["knob_id"],
            "label": registro["label"],
            "grupo": registro["grupo"],
            "n_vanos": registro["n_vanos"],
            "n_vanos_alcanza": registro["n_vanos_alcanza"],
            "avance_mediano": _mediana(registro["_avances"]),
            "caida_mediana": _mediana(registro["_caidas"]),
            "valor_tipico": _valor_mas_repetido(registro["_valores"]),
        })

    for filas in salida.values():
        filas.sort(key=lambda f: (-f["n_vanos_alcanza"],
                                  -(f["avance_mediano"] or 0.0),
                                  -(f["caida_mediana"] or 0.0),
                                  f["knob_id"]))
    return salida


def _mediana(valores: Sequence[float]) -> float | None:
    return float(np.median(np.asarray(valores, dtype=float))) if len(valores) else None


def _valor_mas_repetido(valores: Sequence[Any]) -> Any:
    """El valor que consigue el minimo en MAS vanos, para que la fila se lea como una
    instruccion ("lleva ALTURA a 18 m") y no como un puntaje.

    La moda y no la media: la mitad de los controles son categoricos o enteros, y el
    promedio de 12 y 18 son 15 metros de apoyo que no existen.
    """
    if not len(valores):
        return None
    conteo: dict[Any, int] = {}
    for valor in valores:
        clave = valor.item() if isinstance(valor, (np.floating, np.integer)) else valor
        try:
            conteo[clave] = conteo.get(clave, 0) + 1
        except TypeError:  # un valor no hashable no puede ser moda de nada
            return valores[0]
    return max(conteo.items(), key=lambda par: par[1])[0]


def diagnostico_de_circuito(
    recursos: RecursosMIL,
    *,
    circuito: str,
    ventana: str,
    top: int = TOP_VANOS_DIAGNOSTICO,
    grupos: Sequence[int] = GRUPOS_DIAGNOSTICO,
) -> list[dict[str, Any]]:
    """Los vanos criticos del circuito y el plan que baja a cada uno de clase.

    Sustituye al percentil de `UITI_VANO_PROM`. Un percentil ordena por severidad
    observada; esto ordena por la clase que el modelo asigna a la bolsa y ademas
    entrega QUE mover -- que es lo que convierte una lista de vanos en una orden de
    trabajo. Es el mismo diagnostico que el boton del cuaderno 06.
    """
    from chec_local_interpreter.mil_simulador_015 import plan_hacia_clase_minima

    seleccion = _seleccion(recursos, circuito=circuito, ventana=ventana)
    if not int(seleccion.get("n_bolsas", 0)):
        return []

    plan = plan_hacia_clase_minima(
        recursos.modelo,
        recursos.X_inst,
        seleccion=seleccion,
        feature_names=recursos.features,
        knobs=recursos.knobs,
        puntos=PUNTOS_REJILLA,
        max_pasos=MAX_PASOS_PLAN,
        label_encoders=recursos.label_encoders,
        max_values_imputed=recursos.max_values_imputed,
        catalogo=catalogo_simulacion(),
    )
    if not plan:
        return []

    # `clase_base` sale del PROPIO plan. Antes se pedia con una segunda llamada a
    # `relevancia_hacia_uiti_minimo(top=1, puntos=1)`, que recorre todos los controles
    # para devolver un numero que el plan ya calculo -- es la misma
    # `asignar_clase(n_obs, u_base)` sobre la misma seleccion. Una pasada entera del
    # modelo por ventana, para nada.
    criticos = []
    for fid, entrada in plan.items():
        criticos.append({
            "fid": str(fid),
            "clase_base": int(entrada["clase_base"]),
            "u_base": float(entrada["u_base"]),
            "u_final": float(entrada["u_final"]),
            "clase_final": int(entrada["clase_final"]),
            "alcanza": bool(entrada["alcanza"]),
            # Bajar de Alto a Medio-Alto es una mejora real y hasta ahora se leia igual
            # que no moverse. `alcanza` solo mira el grupo Bajo.
            "baja_de_grupo": bool(entrada["baja_de_grupo"]),
            "objetivo_clase": int(entrada["objetivo_clase"]),
            "pasos": list(entrada["pasos"]),
        })

    # Primero el grupo Alto, despues Medio-Alto, y dentro de cada uno por UITI. Los
    # grupos de abajo NO entran, y sin ninguno en los criticos la respuesta es una
    # lista vacia -- no los menos malos. Devolver los de Medio bajo el rotulo de
    # diagnostico convierte "este circuito esta tranquilo esta ventana" en una orden
    # de trabajo inventada, y quien la lee no tiene como distinguirla de una real.
    orden_grupo = {g: i for i, g in enumerate(grupos)}
    criticos = [c for c in criticos if c["clase_base"] in orden_grupo]
    criticos.sort(key=lambda c: (orden_grupo[c["clase_base"]], -c["u_base"]))
    return criticos[: int(top)]


def ventanas_de_circuito(recursos: RecursosMIL, *, circuito: str) -> list[str]:
    """Las ventanas en que ESE circuito tiene bolsas, en orden.

    No son todas para todos: un circuito tranquilo puede no registrar una sola celda
    en media parte del ano. Ofrecer ventanas que no tiene produce escenarios vacios
    que el informe presenta como si el modelo no hubiera encontrado nada, cuando lo
    que no hubo fueron eventos.
    """
    keys = recursos.bag_index.keys
    de_este = keys[keys["CIRCUITO"].astype(str) == str(circuito)]
    if de_este.empty:
        return []
    return sorted(de_este["VENTANA"].astype(str).unique().tolist(), key=_orden_ventana)


def _orden_ventana(etiqueta: str) -> tuple[int, str]:
    """`V10` va despues de `V9`, no entre `V1` y `V2`: el orden alfabetico de las
    etiquetas no es el cronologico de las ventanas."""
    resto = str(etiqueta).lstrip("Vv")
    return (int(resto), "") if resto.isdigit() else (10**9, str(etiqueta))


def influencia_por_ventana(
    recursos: RecursosMIL, *, circuito: str
) -> list[dict[str, Any]]:
    """Cuanto pesa cada ventana del circuito, medido sobre DATO OBSERVADO.

    Por ventana: cuantas bolsas caen en clase critica (Alto o Medio-Alto) y cuanto UITI
    acumulan. La clase sale de `asignar_clase` sobre el par (n_obs observado, UITI
    observado) y la geometria del 01.4 -- la misma regla que usa el tablero del 06 --,
    NO de una pasada del modelo. Es deliberado: elegir tres ventanas entre once no puede
    costar once evaluaciones del modelo, que es justo lo que la seleccion existe para
    evitar.

    Devuelve una entrada por ventana, en orden cronologico.
    """
    keys = recursos.bag_index.keys
    de_este = np.asarray(keys["CIRCUITO"].astype(str) == str(circuito))
    if not de_este.any():
        return []

    etiquetas = np.asarray(keys["VENTANA"].astype(str))[de_este]
    n_obs = np.asarray(recursos.bag_index.counts, dtype=np.float64)[de_este]
    uiti = np.asarray(getattr(recursos.bag_index, "y", np.zeros(len(de_este))),
                      dtype=np.float64)[de_este]

    clases = _clases_observadas(recursos, n_obs, uiti)

    salida: list[dict[str, Any]] = []
    for ventana in sorted(set(etiquetas.tolist()), key=_orden_ventana):
        en_ventana = etiquetas == ventana
        criticas = (
            int(np.isin(clases[en_ventana], list(GRUPOS_DIAGNOSTICO)).sum())
            if clases is not None else 0
        )
        salida.append({
            "ventana": str(ventana),
            "n_bolsas": int(en_ventana.sum()),
            "n_bolsas_criticas": criticas,
            "uiti_total": float(uiti[en_ventana].sum()),
        })
    return salida


def _clases_observadas(
    recursos: RecursosMIL, n_obs: np.ndarray, uiti: np.ndarray
) -> np.ndarray | None:
    """La clase de cada bolsa, o `None` si el artefacto no expone su geometria.

    Sin geometria no hay clase que asignar, y el ranking cae a UITI acumulado. Se
    devuelve `None` en vez de inventar una clase 0 para todas: eso haria que TODAS las
    ventanas empataran en cero bolsas criticas y el desempate por UITI pareciera la
    regla principal cuando en realidad es el respaldo.
    """
    geometria = getattr(recursos.modelo, "geometria", None)
    if geometria is None:
        return None
    from chec_impacto.models.criticality_assignment import asignar_clase

    clases, _ = asignar_clase(n_obs, uiti, geometria)
    return np.asarray(clases)


def seleccionar_ventanas_reporte(
    recursos: RecursosMIL, *, circuito: str, cuantas: int = VENTANAS_REPORTE
) -> list[str]:
    """Las ventanas que el informe estudia: la ultima, mas las de mayor influencia.

    La ultima entra SIEMPRE. Es el estado actual del circuito, y un informe que la deja
    fuera porque hubo meses peores describe un pasado: la pregunta operativa es "como
    esta hoy y que lo trajo hasta aqui".

    Las demas se ordenan por bolsas en clase critica y se desempatan por UITI acumulado.
    El conteo de bolsas criticas va primero porque es la magnitud en la que se decide una
    intervencion -- cuantos vanos hay que atender --, mientras que el UITI total lo puede
    inflar un solo vano muy malo.

    Devuelve en orden CRONOLOGICO, que es el orden en que se lee el informe.
    """
    disponibles = ventanas_de_circuito(recursos, circuito=circuito)
    if not disponibles:
        return []

    ultima = disponibles[-1]
    seleccion = {ultima}
    faltan = max(0, int(cuantas) - 1)
    if faltan:
        influencia = [i for i in influencia_por_ventana(recursos, circuito=circuito)
                      if i["ventana"] != ultima]
        influencia.sort(
            key=lambda i: (-i["n_bolsas_criticas"], -i["uiti_total"],
                           _orden_ventana(i["ventana"])))
        seleccion.update(i["ventana"] for i in influencia[:faltan])

    return sorted(seleccion, key=_orden_ventana)


def escenarios_de_circuito(
    recursos: RecursosMIL,
    *,
    circuito: str,
    ventanas: Sequence[str] | None = None,
    top_variables: int = TOP_VARIABLES,
    top_vanos: int = TOP_VANOS_DIAGNOSTICO,
) -> list[dict[str, Any]]:
    """Un escenario por VENTANA del circuito.

    Con MGCECDL un escenario era un percentil de filas -- top por severidad, top por
    frecuencia --; con el MIL la unidad es la bolsa (vano, ventana), asi que el
    escenario natural es la ventana. Mantener el percentil habria dejado el informe
    hablando de una particion que el modelo no ve por dentro, y obligaba a explicar
    dos recortes distintos de la misma poblacion.

    Cada escenario trae lo que el agente de inferencia necesita para una ventana: que
    variables bajan el UITI de sus vanos, y cuales son los criticos con su plan.
    """
    disponibles = ventanas_de_circuito(recursos, circuito=circuito)
    if ventanas is not None:
        pedidas = {str(v) for v in ventanas}
        disponibles = [v for v in disponibles if v in pedidas]

    escenarios: list[dict[str, Any]] = []
    for ventana in disponibles:
        relevancia = relevancia_de_circuito(
            recursos, circuito=circuito, ventana=ventana, top=top_variables)
        if not relevancia["vanos"]:
            continue
        criticos = diagnostico_de_circuito(
            recursos, circuito=circuito, ventana=ventana, top=top_vanos)
        escenarios.append({
            "nombre": f"{circuito} -- ventana {ventana}",
            "circuito": str(circuito),
            "ventana": str(ventana),
            "metrica": METRICA,
            "unidad": UNIDAD,
            "n_vanos": len(relevancia["vanos"]),
            "relevancia": relevancia,
            # El corte intervencion/escenario va DENTRO del escenario: las palancas que
            # sirven en una ventana no son las que sirven en otra, y una sola tabla para
            # las tres ventanas borraria justo esa diferencia.
            "variables_por_grupo": resumen_variables_por_grupo(relevancia),
            "vanos_criticos": criticos,
            # La simulacion del informe mueve SOLO palancas de intervencion: es lo que
            # sustenta una orden de trabajo. Trae el UITI medido contra el estimado y el
            # grupo de criticidad en cada caso, mas el grafo diferencia de la seleccion.
            "simulacion": simulacion_de_circuito(
                recursos, circuito=circuito, ventana=ventana,
                fids=[c["fid"] for c in criticos]),
        })
    return escenarios


def construir_contexto_inferencia_mil(
    recursos: RecursosMIL,
    *,
    circuito: str,
    fecha_inicio: str,
    fecha_fin: str,
    fechas_interes: Sequence[str] = (),
    ventanas: Sequence[str] | None = None,
) -> dict[str, Any]:
    """El contexto determinista que consume el agente de inferencia.

    Declara EXPLICITAMENTE el modelo, la unidad y la metrica. El agente cita lo que el
    contexto declara: sin la unidad escrita, redacta "esta variable pesa en este
    circuito" cuando lo medido es "pesa en esta celda vano-ventana", y quien lee el
    informe no tiene como notar la diferencia.

    Conserva `nombre` por escenario porque es el universo citable que el validador
    exige -- un escenario sin nombre no se puede referenciar sin inventar uno.
    """
    escenarios = escenarios_de_circuito(recursos, circuito=circuito, ventanas=ventanas)
    resumen = resumen_de_modelo(recursos)
    return {
        "circuito_interes": str(circuito),
        "fecha_inicio": str(fecha_inicio),
        "fecha_fin": str(fecha_fin),
        "fechas_interes": [str(f) for f in fechas_interes or []],
        "modelo": resumen["modelo"],
        "modelo_tipo": "mil_bolsas",
        "unidad": UNIDAD,
        "metrica": METRICA,
        "n_bolsas": resumen["n_bolsas"],
        "n_instancias": resumen["n_instancias"],
        "n_features": resumen["n_features"],
        "features": list(recursos.features),
        # Las mismas ochenta, en castellano y con su codigo entre parentesis. El sobre de
        # inferencia NO lleva `domain`, asi que `variables_nombradas` -- que si viaja en
        # el del historiador -- no le llegaba: este agente recibia ochenta codigos pelados
        # y sacaba los nombres de su propio playbook, que es como dos juegos de nombres
        # para las mismas columnas empiezan a separarse.
        "features_nombradas": [nombre_con_codigo(str(f)) for f in recursos.features],
        "n_controles": len(recursos.knobs),
        "ventanas": ventanas_de_circuito(recursos, circuito=circuito)
                    if ventanas is None else
                    [v for v in ventanas_de_circuito(recursos, circuito=circuito)
                     if v in {str(x) for x in ventanas}],
        "escenarios": escenarios,
        "metadata": {
            # Lo que el agente NO puede afirmar, escrito donde lo va a leer.
            "uiti_es_objetivo": True,
            "eventos_no_son_objetivo": (
                "El conteo de eventos es un EJE del espacio KMeans que fija la clase, "
                "no una salida del modelo: este contexto no lo explica."
            ),
            "grafo_del_modelo": (
                "El grafo se reconstruye de las compuertas del propio MIL, no de una "
                "aproximacion RBF sobre otro modelo."
            ),
        },
    }


TOP_ARISTAS_CONTEXTO = 15


def compactar_grafo_del_escenario(
    escenario: dict[str, Any], *, features: Sequence[str], top: int = TOP_ARISTAS_CONTEXTO
) -> None:
    """Sustituye la MATRIZ del grafo diferencia por las aristas que mas se movieron.

    La matriz es `n_features x n_features` -- 6.400 numeros con el modelo real -- y va
    dentro del contexto que recibe el agente. Dos problemas, y el segundo tumba la
    corrida:

    1. El agente no puede leer una matriz cruda. Lo que puede citar son las relaciones
       que la intervencion movio, que es exactamente lo que dibuja el panel.
    2. Un `ndarray` no es serializable: `json.dumps` levanta `TypeError` al escribir
       `inference.bc.json` y se pierde la corrida entera despues de haberla calculado.

    Muta el escenario EN SITIO y se llama despues de dibujar las figuras, que si
    necesitan la matriz completa.
    """
    simulacion = (escenario or {}).get("simulacion")
    if not isinstance(simulacion, dict):
        return
    grafo = simulacion.get("grafo_diferencia")
    if not isinstance(grafo, dict):
        return

    matriz = grafo.pop("matriz", None)
    # `colapso` trae ademas `per_edge_variance`: un arreglo con la varianza de CADA
    # arista. Es diagnostico del estimador del grafo, no algo que el agente pueda citar,
    # y viaja como ndarray. Se queda el resumen escalar que ese mismo diccionario trae.
    colapso = grafo.get("colapso")
    if isinstance(colapso, dict):
        grafo["colapso"] = {k: v for k, v in colapso.items() if k != "per_edge_variance"}

    aristas: list[dict[str, Any]] = []
    if matriz is not None and not grafo.get("voided"):
        m = np.asarray(matriz, dtype=float)
        # Solo el triangulo superior: la matriz es simetrica y la arista (A,B) es la
        # misma que la (B,A). Recorrerla entera duplicaria cada relacion en el ranking.
        filas, columnas = np.triu_indices(m.shape[0], k=1)
        pesos = m[filas, columnas]
        for i in np.argsort(-pesos)[: int(top)]:
            if pesos[i] <= 0:
                break
            a, b = int(filas[i]), int(columnas[i])
            aristas.append({
                "entre": [_nombre_feature(features, a), _nombre_feature(features, b)],
                "movimiento": round(float(pesos[i]), 6),
            })
    grafo["aristas"] = aristas


def _nombre_feature(features: Sequence[str], indice: int) -> str:
    try:
        return str(features[indice])
    except (IndexError, TypeError):
        return f"feature_{indice}"


def mapa_base_de_escenario(escenario: Mapping[str, Any]) -> dict[str, Any]:
    """El mapa de la ventana: como esta el circuito, vano por vano.

    Cubre TODOS los vanos de la ventana, no solo los quince del diagnostico: el mapa es
    del circuito, y dejar el resto en blanco se lee como "sin datos" cuando lo que pasa
    es que no hacia falta intervenirlos.

    La clase sale del u-hat del modelo sobre la geometria del 01.4, via `clase_base`.
    Pintarla con UITI observado la dejaria fuera de escala con el diagnostico y con la
    tabla del plan, que si hablan del modelo.

    Antes esto devolvia DOS capas, base y simulada, y el informe las ponia lado a lado.
    El informe ahora dibuja el mapa base de las TRES ventanas que estudia: comparar el
    circuito consigo mismo en tres momentos dice DONDE esta el problema y como llego
    hasta ahi, mientras que el mapa simulado repetia en forma de mapa lo que la tabla
    del plan ya da con numeros. La capa simulada no se calcula y se descarta: se fue.

    Funcion pura sobre el escenario que `escenarios_de_circuito` ya construyo: no vuelve
    a cargar el modelo ni a evaluar nada.
    """
    relevancia = (escenario or {}).get("relevancia", {}) or {}
    base_idx = {
        str(fid): int(entrada.get("clase_base", 0))
        for fid, entrada in (relevancia.get("vanos", {}) or {}).items()
    }

    def _capa(indices: Mapping[str, int]) -> dict[str, Any]:
        return {
            # `valor` es lo que colorea la linea y `clase` lo que la rotula: el mapa
            # necesita las dos, y derivar el rotulo del numero en el renderizador
            # obligaria a repetir alli el vocabulario de criticidad.
            "valor": {fid: int(idx) for fid, idx in indices.items()},
            "clase": {fid: _nombre_clase(idx) for fid, idx in indices.items()},
        }

    # Los quince de mayor UITI acumulado ESTIMADO, de mayor a menor. El color del mapa
    # dice en que grupo esta cada vano; esta lista dice cuales concentran el impacto,
    # que es otra pregunta: un vano en Alto con poco UITI acumulado no es por donde
    # empieza una cuadrilla. Se ordena por `u_base`, la misma magnitud que usan el
    # diagnostico y la tabla del plan, para que las tres hablen de lo mismo.
    _por_uiti = sorted(
        ((str(fid), float(entrada.get("u_base", 0.0)))
         for fid, entrada in (relevancia.get("vanos", {}) or {}).items()),
        key=lambda par: par[1], reverse=True,
    )

    return {
        "ventana": str((escenario or {}).get("ventana", "")),
        "base": _capa(base_idx),
        "top_uiti": [fid for fid, _ in _por_uiti[:TOP_VANOS_DIAGNOSTICO]],
        "n_vanos": len(base_idx),
    }


def mapas_de_ventanas(
    recursos: RecursosMIL,
    *,
    circuito: str,
    escenarios: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """El mapa base de TODAS las ventanas con bolsas del circuito, en orden.

    El informe ESTUDIA tres ventanas, y eso no cambia: el barrido de relevancia, el
    diagnostico y la simulacion cuestan `1 + puntos * K` evaluaciones por ventana, y
    once escenarios enteros no los lee nadie. El mapa no es esa parte. Sacar la clase
    base de una ventana cuesta UNA pasada de bolsas -- medido: 15 ms por ventana, 0,17 s
    las once de DON23L14 --, y quedarse en tres deja al lector reconstruyendo de memoria
    como se movio el problema por el trazado entre una ventana y la siguiente, que es
    justo lo que un deslizador contesta de un vistazo.

    Una ventana que ya tiene escenario NO se vuelve a evaluar: su relevancia ya trae
    `clase_base` y `u_base` por vano. Recalcularla pagaria dos veces por el mismo numero
    y dejaria abierta la puerta a que el mapa y las tablas de ese escenario discrepen.

    Que las dos rutas coinciden esta MEDIDO, no supuesto: sobre los 116 vanos de
    DON23L14 en V11, `simular_bolsas` sin overrides y `relevancia_de_circuito` devuelven
    la misma clase y el mismo `u_base` en los 116, sin una sola discrepancia. Las dos
    terminan en `asignar_clase(n_obs observado, u-hat, geometria)`.
    """
    from chec_local_interpreter.mil_simulador_015 import clase_base_de_bolsas

    por_ventana = {str(e.get("ventana")): e for e in escenarios or ()}
    mapas: list[dict[str, Any]] = []
    for ventana in ventanas_de_circuito(recursos, circuito=circuito):
        escenario = por_ventana.get(ventana)
        if escenario is None:
            seleccion = _seleccion(recursos, circuito=circuito, ventana=ventana)
            if not int(seleccion.get("n_bolsas", 0)):
                continue
            # UNA pasada del modelo por ventana. `simular_bolsas` sin overrides da lo
            # mismo -- probado en `test_clase_base_de_bolsas_da_lo_mismo_que_simular_
            # sin_overrides` -- pero paga dos, y aqui eso se multiplica por las once.
            tabla = clase_base_de_bolsas(recursos.modelo, recursos.X_inst,
                                         seleccion=seleccion)
            # Se arma la MISMA forma de escenario que `mapa_base_de_escenario` consume,
            # en vez de un segundo constructor de mapas: dos caminos que producen la
            # misma estructura se separan en cuanto uno de los dos cambie.
            escenario = {
                "ventana": ventana,
                "relevancia": {"vanos": {
                    str(fid): {"clase_base": k, "u_base": float(u)}
                    for fid, k, u in zip(tabla["FID_VANO"], tabla["base_clase_idx"],
                                         tabla["u_base"])
                }},
            }
        mapas.append(mapa_base_de_escenario(escenario))
    return mapas


def _nombre_clase(indice: Any) -> str:
    from chec_impacto.models.criticality_assignment import GRUPOS

    try:
        return GRUPOS[int(indice)]
    except (TypeError, ValueError, IndexError):
        return "Sin clase"


def knobs_de_intervencion(recursos: RecursosMIL) -> list[Any]:
    """Solo las palancas que una cuadrilla puede ejecutar.

    El informe sustenta una ORDEN DE TRABAJO. Un control de escenario -- lluvia,
    viento, temperatura -- no se ejecuta: simularlo produce una caida de UITI que nadie
    puede comprar, y presentada junto a la poda se lee como si fuera igual de
    accionable. Las de escenario NO desaparecen del modelo: entran con el valor
    observado de cada vano, que es lo que corresponde. Lo que no hacen es moverse.
    """
    return [k for k in recursos.knobs
            if recursos.grupos_por_knob.get(k.id) == GRUPO_INTERVENCION]


def simulacion_de_circuito(
    recursos: RecursosMIL,
    *,
    circuito: str,
    ventana: str,
    fids: Sequence[str],
    max_pasos: int = MAX_PASOS_PLAN,
) -> dict[str, Any]:
    """Que le pasa al UITI y al grupo de los vanos identificados si se interviene.

    Devuelve, por vano, el UITI base y el simulado con su grupo de criticidad en cada
    caso, mas el grafo DIFERENCIA de la seleccion. La diferencia y no los dos grafos:
    el grafo reconstruido es casi todo pesos fijos del experto -- las compuertas solo
    los reescalan --, asi que el antes y el despues se ven iguales lado a lado y el
    efecto de la intervencion, que es lo unico que interesa, queda invisible.
    """
    from chec_local_interpreter.mil_simulador_015 import (
        gates_de_bolsas,
        grafo_de_gates,
        grafo_diferencia,
        plan_hacia_clase_minima,
        simular_bolsas,
    )

    knobs = knobs_de_intervencion(recursos)
    vacio = {"circuito": str(circuito), "ventana": str(ventana),
             "solo_intervencion": True, "metrica": METRICA, "unidad": UNIDAD,
             "knobs_usados": [k.id for k in knobs], "vanos": [], "grafo_diferencia": None}

    fids = [str(f) for f in fids]
    if not fids or not knobs:
        return vacio

    from chec_local_interpreter.mil_simulador_015 import seleccionar_bolsas

    seleccion = seleccionar_bolsas(recursos.bag_index, circuito=str(circuito),
                                   ventana=str(ventana), marcados=fids)
    if not int(seleccion.get("n_bolsas", 0)):
        return vacio

    plan = plan_hacia_clase_minima(
        recursos.modelo, recursos.X_inst, seleccion=seleccion,
        feature_names=recursos.features, knobs=knobs, puntos=PUNTOS_REJILLA,
        max_pasos=int(max_pasos), label_encoders=recursos.label_encoders,
        max_values_imputed=recursos.max_values_imputed,
        catalogo=catalogo_simulacion(),
    )
    overrides = {
        fid: [{"variable": paso["knob_id"], "valor": paso["valor"]}
              for paso in entrada.get("pasos", [])]
        for fid, entrada in plan.items()
    }

    tabla, meta = simular_bolsas(
        recursos.modelo, recursos.X_inst, seleccion=seleccion,
        feature_names=recursos.features, overrides_por_vano=overrides,
        label_encoders=recursos.label_encoders,
        max_values_imputed=recursos.max_values_imputed,
    )

    vanos = [
        {
            "fid": str(fila["FID_VANO"]),
            "u_base": float(fila["u_base"]),
            "u_simulado": float(fila["u_simulado"]),
            "clase_base": int(fila["base_clase_idx"]),
            "clase_simulada": int(fila["simulado_clase_idx"]),
            "delta_grupo": int(fila["delta_riesgo_ordinal"]),
            "pasos": list(plan.get(str(fila["FID_VANO"]), {}).get("pasos", [])),
        }
        for _, fila in tabla.iterrows()
    ]

    return {**vacio, "vanos": vanos,
            "grafo_diferencia": _grafo_diferencia_de(recursos, seleccion, meta,
                                                     gates_de_bolsas, grafo_de_gates,
                                                     grafo_diferencia)}


def _aristas_del_modelo(modelo: Any) -> Any | None:
    """`edge_index` del artefacto MIL, o `None` si no lo expone.

    Cuelga de `modelo.model`, NO de `modelo.model.base`. Buscarlo en el sitio
    equivocado no revienta: se devuelve `None` y el informe pierde el panel del grafo
    en silencio, sin un solo mensaje. Se aisla aqui para que el sitio correcto quede
    en UN lugar y con su prueba.
    """
    return getattr(getattr(modelo, "model", None), "edge_index", None)


def _grafo_diferencia_de(recursos, seleccion, meta, gates_de_bolsas, grafo_de_gates,
                         grafo_diferencia) -> dict[str, Any] | None:
    """El grafo diferencia, o `None` si el modelo no expone sus aristas.

    Se aisla aqui porque depende de internals del artefacto (`edge_index`) que un
    modelo futuro podria no traer: sin el, el informe pierde un panel, no la corrida.
    """
    edge_index = _aristas_del_modelo(recursos.modelo)
    if edge_index is None or meta.get("X_simulado") is None:
        return None
    filas = np.asarray(seleccion["filas"], dtype=np.int64)
    instance_bag = np.asarray(seleccion["instance_bag"], dtype=np.int64)
    n_bolsas = int(seleccion["n_bolsas"])
    X_base = np.asarray(recursos.X_inst[filas], dtype=np.float64)
    g_base = gates_de_bolsas(recursos.modelo, X_base, instance_bag, n_bolsas)
    g_sim = gates_de_bolsas(recursos.modelo, meta["X_simulado"], instance_bag, n_bolsas)
    return grafo_diferencia(g_base, g_sim, edge_index, len(recursos.features))


def resumen_de_modelo(recursos: RecursosMIL) -> dict[str, Any]:
    """Lo que el informe imprime sobre el modelo que lo respalda.

    Nombra la UNIDAD explicitamente porque es la diferencia entre "esta variable pesa
    en este circuito" y "esta variable pesa en esta celda vano-ventana", y el lector
    no tiene como deducirla del resto del informe.
    """
    return {
        "modelo": "MIL por bolsas (cuaderno 05)",
        "unidad": UNIDAD,
        "objetivo": METRICA,
        "n_bolsas": len(recursos.bag_index.keys),
        "n_instancias": int(np.asarray(recursos.X_inst).shape[0]),
        "n_features": len(recursos.features),
        "puntos_rejilla": PUNTOS_REJILLA,
        "max_pasos_plan": MAX_PASOS_PLAN,
    }
