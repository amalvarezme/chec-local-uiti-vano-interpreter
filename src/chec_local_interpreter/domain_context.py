from __future__ import annotations

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
        "rule_id": "weather_environmental_stress",
        "description": "Las series climaticas contribuyen a estres ambiental acumulado.",
        "source": "Entorno/Riesgo",
        "target": "Eventos/Impacto",
    },
    {
        "rule_id": "environment_operational_hypotheses",
        "description": "NR_T, DDT, precipitacion, viento y rafagas pueden apoyar hipotesis cuando coinciden con etiquetas de evento.",
        "source": "Entorno/Riesgo",
        "target": "Evento/Impacto",
    },
    {
        "rule_id": "physical_susceptibility",
        "description": "Conductor, longitud, fases, neutro, guarda y taxonomia describen susceptibilidad, no causas absolutas.",
        "source": "Fisicas/Electricas",
        "target": "Evento/Impacto",
    },
    {
        "rule_id": "topology_protection",
        "description": "LVSW, CNT_VN, FID_VANO y CIRCUITO describen propagacion y contexto de proteccion.",
        "source": "Topologia",
        "target": "Proteccion",
    },
    {
        "rule_id": "assets_exposure",
        "description": "Variables de activos describen vulnerabilidad estructural y exposicion aguas abajo.",
        "source": "Activos",
        "target": "Entorno/Riesgo",
    },
    {
        "rule_id": "load_impact",
        "description": "Usuarios, transformadores, capacidad y consumo ayudan a explicar la magnitud del impacto.",
        "source": "Activos",
        "target": "Evento/Impacto",
    },
    {
        "rule_id": "protection_restoration_context",
        "description": "Equipos y usuarios protegidos ayudan a explicar alcance de impacto y contexto de reposicion.",
        "source": "Proteccion",
        "target": "Evento/Impacto",
    },
    {
        "rule_id": "duration_users_uiti",
        "description": "Duracion y usuarios afectados explican el impacto de interrupcion a nivel de evento.",
        "source": "Evento/Impacto",
        "target": "UITI_VANO",
    },
    {
        "rule_id": "spatial_traceability",
        "description": "Las coordenadas apoyan trazabilidad espacial y contexto topologico.",
        "source": "Topologia",
        "target": "Topologia",
    },
]


def domain_context_payload() -> dict[str, object]:
    return {
        "variable_groups": VARIABLE_GROUPS,
        "relationship_rules": RELATIONSHIP_RULES,
    }
