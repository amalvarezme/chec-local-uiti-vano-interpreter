"""El contexto de dominio que reciben los agentes del informe.

Las reglas se nombran en castellano y NO llevan identificador de maquina. Lo llevaban
-- `topology_protection`, `weather_environmental_stress`,
`environment_operational_hypotheses` -- y salian impresas en el informe: el agente las
citaba porque estaban en su contexto, y nadie valida contra ellas, asi que su unico
efecto era poner claves en snake_case ingles delante de quien opera la red. Quitarlas de
la FUENTE es la unica forma de que no puedan citarse; pedir en el prompt que no se
mencionen deja el defecto a un descuido de distancia.

Cada grupo viaja ademas con `variables_nombradas`: los mismos codigos con su nombre en
castellano delante. El listado de codigos pelados se queda -- es lo que hay que cruzar
contra el dataset --, pero el agente ya no tiene que adivinar como se llama `NR_T` para
escribirlo.
"""

from __future__ import annotations

from chec_local_interpreter.glosario_variables import nombre_con_codigo

VARIABLE_GROUPS: dict[str, dict[str, object]] = {
    "Evento/Impacto": {
        "description": "Fecha, duracion, usuarios, transformadores, causas e indicadores de impacto.",
        "variables": ["FECHA", "DURACION", "TOT_USUS", "CNT_TRF", "UITI", "UITI_VANO", "COD_CAUSA", "DESC_CAUSA"],
    },
    "Proteccion": {
        "description": "Equipos que detectan, despejan y aislan fallas.",
        "variables": ["FID_SW", "COD_EQ_PROTEGE", "TIPO", "CNT_VN_SW", "T_USUS_EQ_PROT"],
    },
    "Topologia": {
        "description": "Circuito, vano, coordenadas, distancia y aporte del tramo.",
        "variables": ["CIRCUITO", "FID_VANO", "X1", "Y1", "X2", "Y2", "LVSW", "CNT_VN", "PORC_APORTE_VANO"],
    },
    "Fisicas/Electricas": {
        "description": "Caracteristicas tecnico-constructivas que describen susceptibilidad.",
        "variables": [
            "FECHA_OPERACION_VANO",
            "LONGITUD",
            "CNT_FASES",
            "CONDUCTOR",
            "CALIBRE_NEUTRO",
            "NG_RED",
            "PROMEDIO_KWH_VANO",
            "TIPO_TAX",
        ],
    },
    "Activos": {
        "description": "Apoyos y transformadores asociados al vano.",
        "variables": [
            "COD_APOYO_FIN",
            "FID_APOYO_FIN",
            "PROPIETARIO",
            "CLASE",
            "ELEMENTO",
            "NORMA",
            "ALTURA",
            "LONG_CRUCETA",
            "CANTIDAD_TIERRA",
            "VAL_CRIT_APOYO",
            "FID_TRAFO",
            "CODIGO",
            "CAPACIDAD_NOMINAL",
            "CNT_USUS",
            "FECHA_OPERACION_TRF",
            "PROMEDIO_KWH_TRF",
        ],
    },
    "Entorno/Riesgo": {
        "description": "Riesgo vegetal, descargas y series climaticas como estresores ambientales.",
        "variables": ["NR_T", "DDT", "PREP_i", "CLOUDS_i", "VIS_i", "WIND_SPD_i", "WIND_GUST_SPD_i", "TEMP_i"],
    },
}

RELATIONSHIP_RULES: list[dict[str, object]] = [
    {
        "nombre": "Clima que acumula estres sobre la red",
        "description": "Las series climaticas contribuyen a estres ambiental acumulado.",
        "source": "Entorno/Riesgo",
        "target": "Eventos/Impacto",
    },
    {
        "nombre": "Entorno que respalda hipotesis de causa",
        "description": "NR_T, DDT, precipitacion, viento y rafagas pueden apoyar hipotesis cuando coinciden con etiquetas de evento.",
        "source": "Entorno/Riesgo",
        "target": "Evento/Impacto",
    },
    {
        "nombre": "Construccion del vano que lo hace mas susceptible",
        "description": "Conductor, longitud, fases, neutro, guarda y taxonomia describen susceptibilidad, no causas absolutas.",
        "source": "Fisicas/Electricas",
        "target": "Evento/Impacto",
    },
    {
        "nombre": "Trazado del circuito y alcance de la proteccion",
        "description": "LVSW, CNT_VN, FID_VANO y CIRCUITO describen propagacion y contexto de proteccion.",
        "source": "Topologia",
        "target": "Proteccion",
    },
    {
        "nombre": "Estado de los apoyos frente al entorno",
        "description": "Variables de activos describen vulnerabilidad estructural y exposicion aguas abajo.",
        "source": "Activos",
        "target": "Entorno/Riesgo",
    },
    {
        "nombre": "Carga servida que fija la magnitud del impacto",
        "description": "Usuarios, transformadores, capacidad y consumo ayudan a explicar la magnitud del impacto.",
        "source": "Activos",
        "target": "Evento/Impacto",
    },
    {
        "nombre": "Proteccion que fija el alcance y la reposicion",
        "description": "Equipos y usuarios protegidos ayudan a explicar alcance de impacto y contexto de reposicion.",
        "source": "Proteccion",
        "target": "Evento/Impacto",
    },
    {
        "nombre": "Duracion y usuarios que componen el UITI",
        "description": "Duracion y usuarios afectados explican el impacto de interrupcion a nivel de evento.",
        "source": "Evento/Impacto",
        "target": "UITI_VANO",
    },
    {
        "nombre": "Coordenadas para ubicar el tramo",
        "description": "Las coordenadas apoyan trazabilidad espacial y contexto topologico.",
        "source": "Topologia",
        "target": "Topologia",
    },
]


def domain_context_payload() -> dict[str, object]:
    """El contexto de dominio, con cada variable tambien en castellano.

    `variables_nombradas` se calcula aqui y no se escribe a mano en cada grupo: dos
    listas paralelas mantenidas por separado se separan en cuanto alguien agregue una
    columna, y la que se quedaria corta es justo la legible.
    """
    grupos = {
        nombre: {
            **datos,
            "variables_nombradas": [
                nombre_con_codigo(str(v)) for v in datos.get("variables", [])
            ],
        }
        for nombre, datos in VARIABLE_GROUPS.items()
    }
    return {
        "variable_groups": grupos,
        "relationship_rules": RELATIONSHIP_RULES,
    }
