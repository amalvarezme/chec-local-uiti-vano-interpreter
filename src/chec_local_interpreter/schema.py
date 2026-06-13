from __future__ import annotations

from dataclasses import dataclass

from chec_local_interpreter.config import REQUIRED_COLUMNS

EVENT_IMPACT_COLUMNS = (
    "DURACION",
    "UITI",
    "TOT_USUS",
    "CNT_USUS",
    "CNT_TRF",
    "COD_CAUSA",
    "DESC_CAUSA",
)

PROTECTION_COLUMNS = (
    "FID_SW",
    "COD_EQ_PROTEGE",
    "TIPO",
    "CNT_VN_SW",
    "T_USUS_EQ_PROT",
)

TOPOLOGY_COLUMNS = (
    "FID_VANO",
    "X1",
    "Y1",
    "X2",
    "Y2",
    "LVSW",
    "CNT_VN",
    "PORC_APORTE_VANO",
)

PHYSICAL_ELECTRICAL_COLUMNS = (
    "FECHA_OPERACION_VANO",
    "LONGITUD",
    "CNT_FASES",
    "CONDUCTOR",
    "CALIBRE_NEUTRO",
    "NG_RED",
    "PROMEDIO_KWH_VANO",
    "TIPO_TAX",
)

ASSET_COLUMNS = (
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
)

ENVIRONMENT_COLUMNS = ("NR_T", "DDT")
WEATHER_PREFIXES = (
    "PREP",
    "CLOUDS",
    "VIS",
    "WIND_SPD",
    "WIND_GUST_SPD",
    "TEMP",
)

OPTIONAL_COLUMNS = tuple(
    dict.fromkeys(
        EVENT_IMPACT_COLUMNS
        + PROTECTION_COLUMNS
        + TOPOLOGY_COLUMNS
        + PHYSICAL_ELECTRICAL_COLUMNS
        + ASSET_COLUMNS
        + ENVIRONMENT_COLUMNS
    )
)


@dataclass(frozen=True)
class ColumnResolution:
    required: dict[str, str]
    optional: dict[str, str]
    unavailable_optional: list[str]


def expected_columns() -> tuple[str, ...]:
    return REQUIRED_COLUMNS + OPTIONAL_COLUMNS
