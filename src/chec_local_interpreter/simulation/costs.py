from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_COST_ITEMS_PATH = Path("data/COSTOS ITEMS CONTRATOS.xlsx")
ITEM_COLUMN_CANDIDATES = ["Etiquetas de fila", "item", "descripcion", "descripción"]
COST_COLUMN_CANDIDATES = ["Promedio de UNITCOST", "unitcost", "costo", "valor"]

VARIABLE_COST_KEYWORDS: dict[str, list[str]] = {
    "CNT_TRF": ["transformador", "bajantes", "transporte transformador"],
    "CAPACIDAD_NOMINAL": ["transformador", "kva", "instalacion transformador"],
    "PROMEDIO_KWH_TRF": ["transformador", "bajantes"],
    "FID_TRAFO": ["transformador"],
    "LONGITUD": ["red primaria", "instalacion por hilo", "cable"],
    "CNT_FASES": ["red primaria", "instalacion por hilo", "cable"],
    "CONDUCTOR": ["red primaria", "instalacion por hilo", "cable"],
    "CALIBRE_NEUTRO": ["red secundaria", "cable", "hilo"],
    "NG_RED": ["cable de guarda", "red desnuda", "red primaria"],
    "ALTURA": ["apoyo", "poste", "vestida poste"],
    "VAL_CRIT_APOYO": ["apoyo", "poste", "retiro de apoyo"],
    "COD_APOYO_FIN": ["apoyo", "poste"],
    "LONG_CRUCETA": ["cruceta", "vestida poste"],
    "CANTIDAD_TIERRA": ["puesta a tierra", "tierra primaria", "tierra secundaria"],
    "NR_T": ["poda", "redes rurales", "redes urbanas"],
    "DDT": ["puesta a tierra", "inspeccion"],
    "TIPO": ["inspeccion", "proteccion", "mantenimiento redes"],
    "TIPO_TAX": ["inspeccion", "mantenimiento redes"],
    "CNT_VN": ["red primaria", "mantenimiento redes", "inspeccion"],
}


def _normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("Ã“N", "ON").replace("Ã“", "O").replace("Ã", "A")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^A-Za-z0-9]+", " ", text).upper()
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: Any) -> set[str]:
    stopwords = {
        "DE",
        "DEL",
        "LA",
        "EL",
        "LOS",
        "LAS",
        "Y",
        "O",
        "A",
        "EN",
        "PARA",
        "POR",
        "CON",
        "SIN",
        "SERVICIO",
        "SERVICIOS",
    }
    return {token for token in _normalize_text(value).split() if len(token) > 2 and token not in stopwords}


def _resolve_column(columns: list[str], candidates: list[str]) -> str:
    normalized = {_normalize_text(col): col for col in columns}
    for candidate in candidates:
        key = _normalize_text(candidate)
        if key in normalized:
            return normalized[key]
    raise ValueError(f"No se encontró ninguna columna esperada entre: {candidates}")


def load_cost_items(path: str | Path = DEFAULT_COST_ITEMS_PATH) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    raw = pd.read_excel(source)
    item_col = _resolve_column(list(raw.columns), ITEM_COLUMN_CANDIDATES)
    cost_col = _resolve_column(list(raw.columns), COST_COLUMN_CANDIDATES)
    df = raw[[item_col, cost_col]].rename(columns={item_col: "item", cost_col: "costo_promedio"}).copy()
    df["item"] = df["item"].fillna("").astype(str).str.strip()
    df["costo_promedio"] = pd.to_numeric(df["costo_promedio"], errors="coerce")
    df = df[df["item"] != ""].reset_index(drop=True)
    return df


def _query_for_variable(variable: str, row: pd.Series | None = None) -> str:
    parts = [variable]
    for key, keywords in VARIABLE_COST_KEYWORDS.items():
        if key in str(variable).upper():
            parts.extend(keywords)
    if row is not None:
        for column in ["observacion", "direccion_cambio_minimo", "direccion_cambio_maximo"]:
            value = row.get(column)
            if value not in (None, ""):
                parts.append(str(value))
    return " ".join(parts)


def _score_cost_item(query_tokens: set[str], item_tokens: set[str]) -> float:
    if not query_tokens or not item_tokens:
        return 0.0
    overlap = len(query_tokens & item_tokens)
    if overlap == 0:
        return 0.0
    return overlap / math.sqrt(len(query_tokens) * len(item_tokens))


def find_cost_matches(
    query: str,
    cost_items: pd.DataFrame,
    *,
    top_n: int = 3,
    min_score: float = 0.05,
) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    rows: list[dict[str, Any]] = []
    for _, row in cost_items.iterrows():
        score = _score_cost_item(query_tokens, _tokens(row.get("item")))
        if score < min_score:
            continue
        cost = row.get("costo_promedio")
        rows.append(
            {
                "item_costo": str(row.get("item", "")).strip(),
                "costo_promedio": None if pd.isna(cost) else float(cost),
                "puntaje_cercania": round(float(score), 4),
            }
        )
    rows.sort(
        key=lambda item: (
            item["puntaje_cercania"],
            -1 if item["costo_promedio"] is None else 0,
            0 if item["costo_promedio"] is None else item["costo_promedio"],
        ),
        reverse=True,
    )
    return rows[:top_n]


def build_auto_simulation_cost_context(
    simulation_table: pd.DataFrame,
    cost_items: pd.DataFrame,
    *,
    top_variables: int = 8,
    matches_per_variable: int = 3,
) -> dict[str, Any]:
    if simulation_table is None or simulation_table.empty:
        return {
            "disponible": False,
            "advertencias": ["La tabla del simulador automático está vacía; no se estiman costos."],
            "coincidencias": [],
        }
    if cost_items is None or cost_items.empty:
        return {
            "disponible": False,
            "advertencias": ["La tabla de costos está vacía; no se estiman costos."],
            "coincidencias": [],
        }

    work = simulation_table.copy()
    if "magnitud_max_cambio_abs" not in work.columns:
        for column in ["cambio_absoluto_minimo", "cambio_absoluto_maximo"]:
            if column in work.columns:
                work[column] = pd.to_numeric(work[column], errors="coerce")
        available = [col for col in ["cambio_absoluto_minimo", "cambio_absoluto_maximo"] if col in work.columns]
        work["magnitud_max_cambio_abs"] = work[available].abs().max(axis=1) if available else 0.0
    work["magnitud_max_cambio_abs"] = pd.to_numeric(work["magnitud_max_cambio_abs"], errors="coerce").fillna(0.0)
    work = work.sort_values("magnitud_max_cambio_abs", ascending=False, kind="stable").head(top_variables)

    coincidencias: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        variable = str(row.get("variable", "")).strip()
        if not variable:
            continue
        matches = find_cost_matches(
            _query_for_variable(variable, row),
            cost_items,
            top_n=matches_per_variable,
        )
        if not matches:
            continue
        coincidencias.append(
            {
                "variable": variable,
                "magnitud_max_cambio_abs": float(row.get("magnitud_max_cambio_abs") or 0.0),
                "riesgo_base_etiqueta": row.get("riesgo_base_etiqueta", ""),
                "riesgo_valor_minimo_etiqueta": row.get("riesgo_valor_minimo_etiqueta", ""),
                "riesgo_valor_maximo_etiqueta": row.get("riesgo_valor_maximo_etiqueta", ""),
                "items_costo_cercanos": matches,
            }
        )

    return {
        "disponible": bool(coincidencias),
        "metodo": "Coincidencia determinística por tokens entre variables sensibles y descripciones de COSTOS ITEMS CONTRATOS.xlsx.",
        "advertencias": [] if coincidencias else ["No se encontraron ítems de costo cercanos para las variables simuladas."],
        "coincidencias": coincidencias,
    }
