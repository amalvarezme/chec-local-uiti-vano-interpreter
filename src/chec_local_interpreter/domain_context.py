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
        "description": "Fecha, duración, usuarios, transformadores, causas e indicadores de impacto.",
        "variables": ["FECHA", "DURACION", "TOT_USUS", "CNT_TRF", "UITI", "UITI_VANO", "COD_CAUSA", "DESC_CAUSA"],
    },
    "Proteccion": {
        "description": "Equipos que detectan, despejan y aíslan fallas.",
        "variables": ["FID_SW", "COD_EQ_PROTEGE", "TIPO", "CNT_VN_SW", "T_USUS_EQ_PROT"],
    },
    "Topologia": {
        "description": "Circuito, vano, coordenadas, distancia y aporte del tramo.",
        "variables": ["CIRCUITO", "FID_VANO", "X1", "Y1", "X2", "Y2", "LVSW", "CNT_VN", "PORC_APORTE_VANO"],
    },
    "Fisicas/Electricas": {
        "description": "Características técnico-constructivas que describen susceptibilidad.",
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
        "description": "Riesgo vegetal, descargas y series climáticas como estresores ambientales.",
        "variables": ["NR_T", "DDT", "PREP_i", "CLOUDS_i", "VIS_i", "WIND_SPD_i", "WIND_GUST_SPD_i", "TEMP_i"],
    },
}

RELATIONSHIP_RULES: list[dict[str, object]] = [
    {
        "nombre": "Clima que acumula estrés sobre la red",
        "description": "Las series climáticas contribuyen a estrés ambiental acumulado.",
        "source": "Entorno/Riesgo",
        "target": "Eventos/Impacto",
    },
    {
        "nombre": "Entorno que respalda hipótesis de causa",
        "description": "NR_T, DDT, precipitación, viento y ráfagas pueden apoyar hipótesis cuando coinciden con etiquetas de evento.",
        "source": "Entorno/Riesgo",
        "target": "Evento/Impacto",
    },
    {
        "nombre": "Construcción del vano que lo hace más susceptible",
        "description": "Conductor, longitud, fases, neutro, guarda y taxonomía describen susceptibilidad, no causas absolutas.",
        "source": "Fisicas/Electricas",
        "target": "Evento/Impacto",
    },
    {
        "nombre": "Trazado del circuito y alcance de la protección",
        "description": "LVSW, CNT_VN, FID_VANO y CIRCUITO describen propagación y contexto de protección.",
        "source": "Topologia",
        "target": "Proteccion",
    },
    {
        "nombre": "Estado de los apoyos frente al entorno",
        "description": "Variables de activos describen vulnerabilidad estructural y exposición aguas abajo.",
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
        "nombre": "Protección que fija el alcance y la reposición",
        "description": "Equipos y usuarios protegidos ayudan a explicar alcance de impacto y contexto de reposición.",
        "source": "Proteccion",
        "target": "Evento/Impacto",
    },
    {
        "nombre": "Duración y usuarios que componen el UITI",
        "description": "Duración y usuarios afectados explican el impacto de interrupción a nivel de evento.",
        "source": "Evento/Impacto",
        "target": "UITI_VANO",
    },
    {
        "nombre": "Coordenadas para ubicar el tramo",
        "description": "Las coordenadas apoyan trazabilidad espacial y contexto topológico.",
        "source": "Topologia",
        "target": "Topologia",
    },
]


#: Nombre de grupo -> como se ESCRIBE en el informe. La clave no se acentua a proposito:
#: es un identificador. `/informe-gerencial` la usa para agrupar y los propios agentes la
#: emiten en `variable_groups_used`, asi que acentuarla romperia ese contrato. Pero el
#: agente la citaba tal cual dentro de su prosa, y de ahi salian "Proteccion" y
#: "Topologia" impresos en un informe para operacion.
NOMBRE_LEGIBLE_GRUPO: dict[str, str] = {
    "Evento/Impacto": "Evento / Impacto",
    "Proteccion": "Protección",
    "Topologia": "Topología",
    "Fisicas/Electricas": "Físicas / Eléctricas",
    "Activos": "Activos",
    "Entorno/Riesgo": "Entorno / Riesgo",
}


def domain_context_payload() -> dict[str, object]:
    """El contexto de dominio, con cada variable y cada grupo tambien en castellano.

    `variables_nombradas` y `nombre_legible` se calculan aqui y no se escriben a mano
    en cada grupo: dos listas paralelas mantenidas por separado se separan en cuanto
    alguien agregue una columna, y la que se quedaria corta es justo la legible.
    """
    grupos = {
        nombre: {
            **datos,
            "nombre_legible": NOMBRE_LEGIBLE_GRUPO.get(nombre, nombre),
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
