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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from chec_local_interpreter.config import PROJECT_ROOT

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
TOP_VANOS_DIAGNOSTICO = 10
TOP_VARIABLES = 10

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
    )
    if not plan:
        return []

    from chec_local_interpreter.mil_simulador_015 import relevancia_hacia_uiti_minimo

    clases = relevancia_hacia_uiti_minimo(
        recursos.modelo, recursos.X_inst, seleccion=seleccion,
        feature_names=recursos.features, knobs=recursos.knobs, top=1,
        puntos=1, label_encoders=recursos.label_encoders,
        max_values_imputed=recursos.max_values_imputed,
    )

    criticos = []
    for fid, entrada in plan.items():
        clase_base = int(clases.get(fid, {}).get("clase_base", 0))
        criticos.append({
            "fid": str(fid),
            "clase_base": clase_base,
            "u_base": float(entrada["u_base"]),
            "u_final": float(entrada["u_final"]),
            "clase_final": int(entrada["clase_final"]),
            "alcanza": bool(entrada["alcanza"]),
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
        escenarios.append({
            "nombre": f"{circuito} -- ventana {ventana}",
            "circuito": str(circuito),
            "ventana": str(ventana),
            "metrica": METRICA,
            "unidad": UNIDAD,
            "n_vanos": len(relevancia["vanos"]),
            "relevancia": relevancia,
            "vanos_criticos": diagnostico_de_circuito(
                recursos, circuito=circuito, ventana=ventana, top=top_vanos),
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
