from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from chec_local_interpreter.config import PROMPT_VERSION, SCHEMA_VERSION
from chec_local_interpreter.data_loader import resolve_columns
from chec_local_interpreter.domain_context import domain_context_payload
from chec_local_interpreter.event_counts import count_unique_event_dates


def _date_text(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _safe_float(value: Any) -> float:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return 0.0
    return round(float(numeric), 2)


def window_series_records(
    events_df: pd.DataFrame,
    *,
    circuito: str | None = None,
    ventanas: Sequence[Mapping[str, Any]] | None = None,
    estudiadas: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """La serie del circuito por VENTANA, completa, con cero donde no hubo eventos.

    La ventana es la unidad de analisis del resto del flujo -- una bolsa del modelo MIL
    es (vano, ventana), y de ahi salen las clases de criticidad --, asi que describir el
    circuito por dia obliga a quien lee a traducir entre dos rejillas que no coinciden.

    Va COMPLETA a proposito: `construir_tabla_vano_ventana` agrega EVENTOS, asi que una
    ventana sin fila no es una ventana sin medir, es una ventana sin eventos, y vale
    cero. Leer "cinco ventanas tranquilas seguidas" es una lectura que no se puede hacer
    si esas ventanas no aparecen.

    `ventanas` impone la rejilla en vez de derivarla de los eventos recibidos, y ese es
    el uso correcto en el informe. Las etiquetas `V1`..`V11` NO son relativas al recorte:
    el cache de bolsas del cuaderno 05 las fijo sobre el rango COMPLETO de la base.
    Derivarlas del subconjunto filtrado hace que la `V1` del historiador y la `V1` del
    modelo sean dos periodos distintos con el mismo nombre, sin que nada lo delate.
    """
    # `construir_tabla_vano_ventana` agrega por (CIRCUITO, FID_VANO, ventana). Sin esas
    # columnas no hay serie por ventana que construir -- y eso NO es un fallo: hay
    # caminos del reporte que entregan eventos ya agregados, sin identidad de vano.
    # Se devuelve vacio y el paquete sigue armandose con el resto.
    requeridas = {"FECHA", "CIRCUITO", "FID_VANO", "UITI_VANO"}
    if events_df is None or events_df.empty or not requeridas <= set(events_df.columns):
        return []
    from chec_local_interpreter.ventanas_015 import (
        construir_tabla_vano_ventana,
        construir_ventanas,
    )

    df = events_df.copy()
    df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce")
    # Los cortes de `construir_ventanas` son Timestamps SIN zona. Comparar contra una
    # columna con zona levanta TypeError, y hay caminos del reporte que la traen asi.
    if getattr(df["FECHA"].dtype, "tz", None) is not None:
        df["FECHA"] = df["FECHA"].dt.tz_localize(None)
    df = df[df["FECHA"].notna()]
    # `construir_tabla_vano_ventana` descarta las filas con UITI en cero, asi que
    # compara la columna contra un numero. Hay fixtures y caminos que la traen como
    # texto, y ahi la comparacion levanta TypeError en vez de dar una serie vacia.
    df["UITI_VANO"] = pd.to_numeric(df["UITI_VANO"], errors="coerce").fillna(0.0)
    if df.empty:
        return []

    ventanas = list(ventanas) if ventanas is not None else construir_ventanas(df["FECHA"])
    if circuito is not None:
        df = df[df["CIRCUITO"].astype(str) == str(circuito)]
        if df.empty:
            return []
    tabla = construir_tabla_vano_ventana(df, ventanas)

    por_ventana: dict[int, tuple[float, int, int]] = {}
    if not tabla.empty:
        for vi, grupo in tabla.groupby("ventana_i"):
            por_ventana[int(vi)] = (
                _safe_float(grupo["uiti_acumulado"].sum()),
                int(grupo["num_eventos"].sum()),
                int(grupo["FID_VANO"].nunique()),
            )

    estudiadas = {str(e) for e in estudiadas or ()}
    registros: list[dict[str, Any]] = []
    for v in ventanas:
        uv, n, vanos = por_ventana.get(int(v["i"]), (0.0, 0, 0))
        registros.append({
            "w": str(v["etiqueta"]),
            "periodo": str(v["periodo"]),
            # Los dos extremos, ademas del periodo en texto: el validador whitelistea
            # fechas comparando cadenas, y sacarlas de "2026-01-01 a 2026-01-31" a base
            # de partir el texto es una regla de parseo escondida en otro modulo.
            "desde": _date_text(v["desde"]),
            "hasta": _date_text(v["hasta_excl"] - pd.Timedelta(days=1)),
            "uv": uv,
            "n": n,
            "vanos": vanos,
            "estudiada": str(v["etiqueta"]) in estudiadas,
        })
    return registros


def vano_series_records(
    events_df: pd.DataFrame,
    *,
    circuito: str,
    fids: Sequence[str],
    ventanas: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Una serie por vano identificado, sobre la secuencia COMPLETA de ventanas.

    El diagnostico señala vanos en UNA ventana. Verlos solo ahi no distingue un
    problema cronico de uno que aparecio el mes pasado, y esas dos cosas se atienden
    distinto. Las ventanas sin eventos van en cero, no ausentes: una ventana tranquila
    de un vano critico es informacion, no un hueco.
    """
    fids = [str(f) for f in fids]
    requeridas = {"FECHA", "CIRCUITO", "FID_VANO", "UITI_VANO"}
    if not fids or events_df is None or events_df.empty or not requeridas <= set(events_df.columns):
        return []

    from chec_local_interpreter.ventanas_015 import (
        construir_tabla_vano_ventana,
        construir_ventanas,
        series_temporal_vanos,
    )

    df = events_df.copy()
    df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce")
    if getattr(df["FECHA"].dtype, "tz", None) is not None:
        df["FECHA"] = df["FECHA"].dt.tz_localize(None)
    df = df[df["FECHA"].notna()]
    df["UITI_VANO"] = pd.to_numeric(df["UITI_VANO"], errors="coerce").fillna(0.0)
    if df.empty:
        return []

    # Misma rejilla impuesta que en `window_series_records`, y por lo mismo: la serie de
    # un vano y la serie del circuito tienen que hablar de las MISMAS once ventanas.
    ventanas = list(ventanas) if ventanas is not None else construir_ventanas(df["FECHA"])
    tabla = construir_tabla_vano_ventana(df, ventanas)
    series = series_temporal_vanos(tabla, circuito=str(circuito), fids=fids,
                                   n_ventanas=len(ventanas))
    etiquetas = [str(v["etiqueta"]) for v in ventanas]
    return [{"fid": str(s["fid"]), "w": etiquetas,
             "uv": [float(u) for u in s["uiti"]],
             "n": [int(e) for e in s["eventos"]]}
            for s in series]


def window_summary(
    events_df: pd.DataFrame, ventanas_serie: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """El resumen del periodo, contado en VENTANAS.

    Antes contaba `nonzero_days` y nombraba el dia pico: describia una rejilla diaria
    que el informe ya no tiene. La ventana es la unidad del ranking del 02, del
    diagnostico del 06 y de la bolsa que el modelo puntua, y un resumen que habla de
    dias obliga a quien lee a traducir entre dos rejillas que no coinciden.
    """
    eventos = (
        int(count_unique_event_dates(events_df, []).sum())
        if events_df is not None and not events_df.empty else 0
    )
    serie = [r for r in (ventanas_serie or []) if isinstance(r, Mapping)]
    if not serie:
        return {"events": eventos, "ventanas_con_eventos": 0, "total_uv": 0.0,
                "ventana_pico": None, "uv_pico": 0.0}

    pico = max(serie, key=lambda r: float(r.get("uv") or 0.0))
    return {
        "events": eventos,
        "ventanas": len(serie),
        "ventanas_con_eventos": sum(1 for r in serie if float(r.get("uv") or 0.0) > 0),
        "total_uv": _safe_float(sum(float(r.get("uv") or 0.0) for r in serie)),
        "ventana_pico": str(pico.get("w")),
        "periodo_pico": str(pico.get("periodo")),
        "uv_pico": _safe_float(pico.get("uv")),
    }


def build_context_package(
    *,
    events_df: pd.DataFrame,
    selected_circuitos: list[str],
    start_date: str | None,
    end_date: str | None,
    ventanas: Sequence[Mapping[str, Any]] | None = None,
    ventanas_estudio: Sequence[str] = (),
    raw_df: pd.DataFrame | None = None,
    top_vanos_percentile: float = 97,
) -> dict[str, Any]:
    """El contexto determinista del historiador, en la rejilla de ventanas del flujo.

    Ya no lleva `critical_points`, `critical_periods` ni `daily`. El informe se apoya en
    el ranking del cuaderno 02 y en el diagnostico y la simulacion del 06, y la unidad de
    los tres es la ventana; la deteccion de puntos criticos ponia al historiador a
    describir DIAS, una segunda rejilla sobre el mismo periodo que nadie reconcilia y que
    no coincide con la bolsa (vano, ventana) que el modelo puntua.
    """
    resolution = resolve_columns(events_df) if not events_df.empty else None
    unavailable = resolution.unavailable_optional if resolution is not None else []

    # La serie por ventana, completa: es la que da la forma del periodo.
    serie_ventanas = window_series_records(
        events_df,
        circuito=selected_circuitos[0] if len(selected_circuitos) == 1 else None,
        ventanas=ventanas,
        estudiadas=ventanas_estudio,
    )

    context = {
        "analysis_name": "local_uiti_vano_interpretability",
        "metadata": {
            "v": PROMPT_VERSION,
            "schema": SCHEMA_VERSION,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M"),
            "circuitos": selected_circuitos,
            "start": _date_text(start_date) if start_date else None,
            "end": _date_text(end_date) if end_date else None,
            "unavailable_cols": unavailable,
        },
        "selected_context": {
            "circuitos": selected_circuitos,
            "indicator": "UITI_VANO",
            "characterization": _compute_circuit_characterization(
                raw_df if raw_df is not None else events_df,
                selected_circuitos,
                top_vanos_percentile=top_vanos_percentile,
            ),
        },
        "summary": window_summary(events_df, serie_ventanas),
        "ventanas": serie_ventanas,
        # Las tres que el informe estudia, declaradas. Sin ellas el historiador recibe
        # once y elige por su cuenta cuales narrar, que es justo la decision que la
        # seleccion determinista existe para quitarle.
        "ventanas_estudio": [str(v) for v in ventanas_estudio or ()],
        "domain": domain_context_payload(),
    }
    return context


def _json_seguro(valor: Any) -> Any:
    """Convierte un tipo de numpy en su equivalente de Python.

    Guarda de ULTIMO recurso, no una excusa para no convertir en el origen. La razon es
    donde falla: `json.dumps` levanta `TypeError` al final de `prepare`, cuando el
    diagnostico y la simulacion ya estan calculados, asi que la corrida entera se pierde
    por un escalar. Y todo lo que produce el modelo es numpy, de modo que basta con que
    una clave nueva olvide un `float(...)` para que el informe deje de salir -- que es
    exactamente lo que ocurrio con la matriz del grafo diferencia.

    Lo que NO se puede representar sigue siendo un error: escribirlo como su `repr`
    meteria basura en el contexto del agente sin que nada lo dijera.
    """
    import numpy as np

    if isinstance(valor, np.ndarray):
        return valor.tolist()
    if isinstance(valor, np.generic):
        return valor.item()
    raise TypeError(f"Object of type {type(valor).__name__} is not JSON serializable")


def save_json_artifact(payload: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_seguro),
        encoding="utf-8",
    )
    return target


def _compute_circuit_characterization(
    df: pd.DataFrame,
    selected_circuitos: list[str],
    *,
    top_vanos_percentile: float = 97,
) -> list[dict[str, Any]]:
    if df.empty or not selected_circuitos:
        return []
        
    df_copy = df.copy()
    if 'UITI_VANO' not in df_copy.columns or 'CIRCUITO' not in df_copy.columns:
        return []
        
    df_copy['UITI_VANO'] = pd.to_numeric(df_copy['UITI_VANO'], errors='coerce').fillna(0.0)
    
    counts = count_unique_event_dates(df_copy, 'CIRCUITO')
    sums = df_copy.groupby('CIRCUITO')['UITI_VANO'].sum()
    
    try:
        from chec_local_interpreter.plotting import compute_circuit_criticality_groups
        # No dates passed: df_copy is already the caller-selected/pre-filtered
        # window, so re-filtering here would be a no-op (mirrors the previous
        # inline behavior, which never filtered by date either).
        df_coords = compute_circuit_criticality_groups(df_copy)
    except ImportError:
        df_coords = pd.DataFrame({
            'event_count': counts,
            'uiti_vano_sum': sums
        }).dropna()
        df_coords['cluster'] = 0
        df_coords['criticidad'] = "Desconocido"

    if df_coords.empty:
        return []

    global_avg_events = counts.mean()
    global_avg_uiti = sums.mean()
    
    df_coords_sorted = df_coords.sort_values(by='uiti_vano_sum', ascending=False)
    circuits_to_process = [c for c in df_coords_sorted.index if c in selected_circuitos][:5]
    
    results = []
    for circuito in circuits_to_process:
        if circuito in df_coords.index:
            row = df_coords.loc[circuito]
            label = row['criticidad']

            percentile = min(max(float(top_vanos_percentile), 0.0), 100.0)
            quantile_value = percentile / 100.0

            # Compute top-percentile vanos using the same threshold rule used by
            # the inference scenarios: metric >= percentile(metric).
            df_circuito = df_copy[df_copy['CIRCUITO'] == circuito]
            p97_uiti_list = []
            p97_events_list = []
            if not df_circuito.empty and 'FID_VANO' in df_circuito.columns:
                vano_stats = df_circuito.groupby('FID_VANO').agg(
                    events=('FID_VANO', 'count'),
                    uiti_sum=('UITI_VANO', 'sum')
                )
                if not vano_stats.empty:
                    try:
                        p97_uiti = vano_stats['uiti_sum'].quantile(quantile_value)
                        p97_events = vano_stats['events'].quantile(quantile_value)
                        
                        top_uiti_vanos = vano_stats[vano_stats['uiti_sum'] >= p97_uiti].sort_values('uiti_sum', ascending=False)
                        top_events_vanos = vano_stats[vano_stats['events'] >= p97_events].sort_values('events', ascending=False)
                        
                        p97_uiti_list = [f"{fid}(U:{r['uiti_sum']:.0f})" for fid, r in top_uiti_vanos.iterrows()][:5]
                        p97_events_list = [f"{fid}(E:{r['events']})" for fid, r in top_events_vanos.iterrows()][:5]
                    except Exception:
                        p97_uiti_list = []
                        p97_events_list = []

            results.append({
                "circuito": circuito,
                "criticidad": label,
                "eventos": int(row['event_count']),
                "uiti_vano_total": round(float(row['uiti_vano_sum']), 0),
                "avg_eventos_red": round(float(global_avg_events), 0),
                "avg_uiti_red": round(float(global_avg_uiti), 0),
                "top_vanos_percentile": percentile,
                "p97_uiti": p97_uiti_list,
                "p97_eventos": p97_events_list,
            })
            
    return results
