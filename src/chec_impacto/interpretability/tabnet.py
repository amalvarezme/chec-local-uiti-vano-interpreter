from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import matplotlib.patches as mpatches
import matplotlib.path as mpath
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
import warnings
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    Draft202012Validator = None


def construir_modos_interpretabilidad(features=None, ventana_climatica_horas=12):
    clima_horas = range(ventana_climatica_horas)

    modos_base = {
        "evento_taxonomia": [
            "TIPO", "TIPO_TAXONOMIA", "TIPO_TAX", "CLASE", "COD_CAUSA",
        ],
        "temporal": [
            "FECHA_OPERACION", "mes",
        ],
        "configuracion_electrica": [
            "NFASES", "CNT_FASES", "NEUTRO", "G_N", "NG_RED", "TRAFO",
            "ENERG_CIRCULA",
        ],
        "geometria_red": [
            "LONGITUD", "ALTURA", "LONG_CRUCETA", "CANTIDAD_TIERRA", "NR_T",
            "VAL_CRIT_APOYO",
        ],
        "materiales_conductor": [
            "CALIBRE_F", "MATERIAL_F", "AISLAMIENTO_F", "CALIBRE_NEUTRO",
            "CONDUCTOR",
        ],
        "infraestructura_activos": [
            "COD_APOYO_FIN", "FID_APOYO_FIN", "FID_TRAFO", "FID_ELEMENTO",
            "ELEMENTO", "NORMA", "PROPIETARIO", "CAPACIDAD_NOMINAL",
        ],
        "consumo_usuarios": [
            "CNT_USUS", "PROMEDIO_KWH",
        ],
        "entorno_vegetacion": [
            "VEGETACION",
        ],
        "espacial": [
            "X1", "Y1", "X2", "Y2",
        ],
        "hidrometeorologico": (
            [f"prep_{i}" for i in clima_horas]
            + [f"clouds_{i}" for i in clima_horas]
            + [f"vis_{i}" for i in clima_horas]
        ),
        "eolico": (
            [f"wind_spd_{i}" for i in clima_horas]
            + [f"wind_gust_spd_{i}" for i in clima_horas]
        ),
        "termico": [
            f"temp_{i}" for i in clima_horas
        ],
        "descargas": [
            "kA_max", "kA_min", "kA_std", "kA_mean", "conteo_coincidencias",
            "kA_median",
        ],
    }

    if features is None:
        return modos_base

    features_disponibles = set(features)
    return {
        grupo: variables
        for grupo, variables in (
            (grupo, [variable for variable in variables if variable in features_disponibles])
            for grupo, variables in modos_base.items()
        )
        if variables
    }


def predict_proba_positiva_tabnet(model, x_np):
    """Return positive-class probabilities, guarding TabNet BatchNorm for single rows."""
    x_np = np.asarray(x_np, dtype=np.float64)
    x_np = np.atleast_2d(x_np)

    singleton = len(x_np) == 1
    x_pred = np.repeat(x_np, 2, axis=0) if singleton else x_np

    proba = np.asarray(model.predict_proba(x_pred), dtype=np.float64)
    if proba.ndim == 1:
        out = proba
    elif proba.shape[1] == 1:
        out = proba[:, 0]
    else:
        out = proba[:, 1]

    return out[:1] if singleton else out


def _normalizar_shap_values(shap_values):
    vals = shap_values
    if isinstance(vals, list):
        vals = vals[1] if len(vals) > 1 else vals[0]
    vals = np.asarray(vals, dtype=np.float64)
    if vals.ndim == 3:
        vals = vals[:, :, 1] if vals.shape[2] > 1 else vals[:, :, 0]
    return np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)


class KernelShapTopVarsExtractor:
    """Compute and cache per-row top variables from Kernel SHAP values."""

    def __init__(
        self,
        model,
        X,
        features,
        top_k=20,
        background_size=40,
        nsamples=80,
        batch_size=64,
        random_state=42,
    ):
        self.model = model
        self.X = np.asarray(X, dtype=np.float64)
        self.features = list(features)
        self.top_k = min(int(top_k), self.X.shape[1])
        self.nsamples = int(nsamples)
        self.batch_size = int(batch_size)
        self.cache = {}

        rng = np.random.default_rng(random_state)
        self.n_background = min(int(background_size), len(self.X))
        background_idx = rng.choice(len(self.X), size=self.n_background, replace=False)
        background = self.X[background_idx]

        def predict_fn(x_np):
            return predict_proba_positiva_tabnet(self.model, x_np)

        with warnings.catch_warnings(), redirect_stdout(io.StringIO()):
            warnings.simplefilter("ignore")
            self.explainer = shap.KernelExplainer(predict_fn, background)

    def calcular_top_vars(self, indices):
        indices = [int(i) for i in indices]
        faltantes = [i for i in indices if i not in self.cache]

        for start in range(0, len(faltantes), self.batch_size):
            batch_idx = faltantes[start:start + self.batch_size]
            if not batch_idx:
                continue

            x_batch = self.X[batch_idx]
            with warnings.catch_warnings(), redirect_stdout(io.StringIO()):
                warnings.simplefilter("ignore")
                shap_values = self.explainer.shap_values(
                    x_batch,
                    nsamples=self.nsamples,
                    silent=True,
                )

            vals = np.abs(_normalizar_shap_values(shap_values))
            if vals.shape != x_batch.shape:
                raise ValueError(f"Forma SHAP inesperada: {vals.shape} vs {x_batch.shape}")

            indices_top = np.argsort(-vals, axis=1, kind="stable")[:, :self.top_k]
            for row_pos, row_idx in enumerate(batch_idx):
                self.cache[row_idx] = {
                    self.features[col_idx]: float(vals[row_pos, col_idx])
                    for col_idx in indices_top[row_pos]
                }

        return [self.cache[i] for i in indices]

    def agregar_top_vars(self, df_eventos):
        out = df_eventos.copy()
        out["_TOP_VARS"] = self.calcular_top_vars(out.index.to_numpy())
        return out


def agregar_borda(df, group_cols, top_col="_TOP_VARS", top_k=20):
    """Suma de puntos Borda por variable dentro de cada grupo."""
    records = []
    row_id = 0
    for _, row in df.iterrows():
        d = row[top_col]
        if not isinstance(d, dict):
            row_id += 1
            continue
        g = {c: row[c] for c in group_cols}
        for pos, var in enumerate(list(d.keys())[:top_k], start=1):
            records.append({**g, "_var": var, "_borda": float(top_k + 1 - pos), "_row": row_id})
        row_id += 1

    if not records:
        return pd.DataFrame(columns=group_cols + ["RELEVANCIA_VARS"])

    exp = pd.DataFrame(records)
    borda = (
        exp.groupby(group_cols + ["_var"], dropna=False, sort=False)["_borda"]
        .sum()
        .reset_index()
    )
    borda = borda.sort_values(
        group_cols + ["_borda"],
        ascending=[True] * len(group_cols) + [False],
        kind="stable",
    )
    borda["_rank"] = borda.groupby(group_cols, sort=False).cumcount()
    borda = borda[borda["_rank"] < top_k].copy()
    borda["_item"] = list(zip(borda["_var"], borda["_borda"]))

    return (
        borda.groupby(group_cols, dropna=False, sort=False)["_item"]
        .agg(lambda items: {v: float(s) for v, s in items})
        .rename("RELEVANCIA_VARS")
        .reset_index()
    )


def agrupar_por_vano(df, extra_group_cols=None, top_col="_TOP_VARS", top_k=20):
    """Aggregate by FID_VANO, optionally adding Borda RELEVANCIA_VARS."""
    gcols = ["FID_VANO"] + (extra_group_cols or [])
    metricas = (
        df.groupby(gcols, dropna=False, sort=False)
        .agg(
            CIRCUITO=("CIRCUITO", "first"),
            UITI_VANO_PROM=("UITI_VANO", "mean"),
            N_APARICIONES=("FID_VANO", "size"),
        )
        .reset_index()
    )
    if top_col not in df.columns:
        return metricas
    rel = agregar_borda(df, gcols, top_col=top_col, top_k=top_k)
    return metricas.merge(rel, on=gcols, how="left")


def construir_modos_chec(features, variables_seleccion_path):
    """Build the six CHEC analysis modes used by the focused circuit notebook."""
    sel_df = pd.read_excel(variables_seleccion_path)
    vars_sel = set(
        sel_df.loc[
            pd.to_numeric(sel_df["SELECCIÓN"], errors="coerce").fillna(0).eq(1),
            "COLUMNA",
        ].astype(str).str.strip()
    )
    features = list(features)
    features_set = set(features)
    prefijos_clim = {"prep", "clouds", "wind_spd", "wind_gust_spd", "temp"}

    def expandir(*vs):
        out = []
        for v in vs:
            if v not in vars_sel or v == "UITI_VANO":
                continue
            if v in prefijos_clim:
                out.extend(f for f in features if f.startswith(f"{v}_"))
            elif v in features_set:
                out.append(v)
        return list(dict.fromkeys(out))

    modos = {
        "Evento, impacto\ne indicadores": expandir(
            "FECHA", "DURACION", "TOT_USUS", "CNT_TRF", "COD_CAUSA", "UITI"
        ),
        "Infraestructura de\nprotección y maniobra": expandir(
            "FID_SW", "COD_EQ_PROTEGE", "TIPO", "CNT_VN", "CNT_VN_SW", "T_USUS_EQ_PROT"
        ),
        "Topología y\nconfiguración espacial": expandir(
            "CIRCUITO", "FID_VANO", "X1", "Y1", "X2", "Y2", "LVSW", "PORC_APORTE_VANO"
        ),
        "Características físicas\ny eléctricas del vano": expandir(
            "FECHA_OPERACION_VANO", "LONGITUD", "CNT_FASES", "CONDUCTOR",
            "CALIBRE_NEUTRO", "NG_RED", "PROMEDIO_KWH_VANO", "TIPO_TAX",
        ),
        "Activos: apoyo final\ny transformador": expandir(
            "COD_APOYO_FIN", "FID_APOYO_FIN", "ALTURA", "CANTIDAD_TIERRA",
            "PROPIETARIO", "CLASE", "ELEMENTO", "NORMA", "VAL_CRIT_APOYO",
            "LONG_CRUCETA", "FID_TRAFO", "CODIGO", "CAPACIDAD_NOMINAL",
            "CNT_USUS", "FECHA_OPERACION_TRF", "PROMEDIO_KWH_TRF",
        ),
        "Entorno, riesgo\ny clima": expandir(
            "NR_T", "DDT", "prep", "clouds", "wind_spd", "wind_gust_spd", "temp"
        ),
    }
    return {k: v for k, v in modos.items() if v}


def normalizar_minmax(serie):
    vals = pd.to_numeric(serie, errors="coerce").astype(float)
    vals = vals.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    min_val = float(vals.min()) if len(vals) else 0.0
    max_val = float(vals.max()) if len(vals) else 0.0
    if not np.isfinite(min_val) or not np.isfinite(max_val) or max_val <= min_val:
        return vals * 0.0
    return (vals - min_val) / (max_val - min_val)


def _modo_de_variable(variable, modos):
    for modo, variables in modos.items():
        if variable in variables:
            return modo.replace("\n", " ")
    return "modo_no_identificado"


def _series_to_records(serie, modos=None, limit=None):
    if serie is None:
        return []
    work = serie.dropna() if hasattr(serie, "dropna") else pd.Series(dtype=float)
    if limit is not None:
        work = work.head(int(limit))
    records = []
    for key, value in work.items():
        record = {
            "variable" if modos is not None else "modo": str(key).replace("\n", " "),
            "score_normalizado": round(float(value), 4),
        }
        if modos is not None:
            record["modo"] = _modo_de_variable(str(key), modos)
        records.append(record)
    return records


def _tabla_top_records(tabla_top, limit=10):
    if tabla_top is None or tabla_top.empty:
        return []
    cols = [c for c in ["FID_VANO", "UITI_VANO_PROM", "N_APARICIONES"] if c in tabla_top.columns]
    out = []
    for _, row in tabla_top[cols].head(limit).iterrows():
        item = {}
        for col in cols:
            value = row[col]
            if col == "FID_VANO":
                item[col] = str(value)
            elif pd.isna(value):
                item[col] = None
            elif col == "N_APARICIONES":
                item[col] = int(value)
            else:
                item[col] = round(float(value), 4)
        out.append(item)
    return out


def _figuras_plotly_barras_radar(titulo, circuito, top_vars_bar, puntajes):
    import plotly.graph_objects as go

    bar_fig = go.Figure()
    bar_fig.add_trace(
        go.Bar(
            x=[str(x) for x in top_vars_bar.index],
            y=[float(y) for y in top_vars_bar.values],
            marker_color=["#1f4e79" if i < 5 else "#5b9bd5" for i in range(len(top_vars_bar))],
            hovertemplate="<b>%{x}</b><br>Score normalizado: %{y:.3f}<extra></extra>",
        )
    )
    bar_fig.update_layout(
        title=f"Kernel SHAP + Borda ponderado min-max - {circuito}<br><sup>{titulo}</sup>",
        xaxis_title="Variable",
        yaxis_title="Borda ponderado normalizado min-max",
        yaxis=dict(range=[0, 1.05]),
        height=460,
        margin=dict(l=60, r=30, t=90, b=120),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    bar_fig.update_xaxes(tickangle=45)

    theta = [str(x).replace("\n", " ") for x in puntajes.index]
    r = [float(y) for y in puntajes.values]
    radar_fig = go.Figure()
    radar_fig.add_trace(
        go.Scatterpolar(
            r=r + r[:1],
            theta=theta + theta[:1],
            fill="toself",
            line=dict(color="#1f4e79", width=3),
            fillcolor="rgba(91, 155, 213, 0.35)",
            marker=dict(color="#17365d", size=8),
            hovertemplate="<b>%{theta}</b><br>Score normalizado: %{r:.3f}<extra></extra>",
        )
    )
    radar_fig.update_layout(
        title=f"Kernel SHAP + Borda promedio min-max por modo - {circuito}<br><sup>{titulo}</sup>",
        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
        height=560,
        margin=dict(l=80, r=80, t=100, b=80),
        paper_bgcolor="#ffffff",
    )
    return bar_fig, radar_fig


def puntaje_borda_ponderado_eventos(df_eventos, features, top_col="_TOP_VARS", top_k=20):
    puntajes = pd.Series(0.0, index=list(features))

    for d in df_eventos[top_col]:
        if not isinstance(d, dict):
            continue
        for pos, (var, atribucion) in enumerate(list(d.items())[:top_k], start=1):
            if var in puntajes.index:
                borda = float(top_k + 1 - pos)
                puntajes.loc[var] += borda * float(atribucion)

    return puntajes.sort_values(ascending=False)


def graficar_barras_y_radar(
    df_eventos,
    titulo,
    circuito,
    features,
    modos,
    shap_extractor,
    top_k=20,
    show=True,
):
    """Plot feature bars and mode radar from Kernel SHAP + Borda weighted scores."""
    if df_eventos.empty:
        raise ValueError(f"Sin eventos para: {titulo}")

    df_eventos = shap_extractor.agregar_top_vars(df_eventos)
    borda = puntaje_borda_ponderado_eventos(df_eventos, features, top_k=top_k)
    print(f"{titulo} | eventos: {len(df_eventos):,} | vanos: {df_eventos['FID_VANO'].nunique()}")

    top_vars_bar = normalizar_minmax(borda).sort_values(ascending=False).head(top_k)
    colores = ["#1f4e79" if i < 5 else "#5b9bd5" for i in range(len(top_vars_bar))]

    puntajes = pd.Series(
        {
            nombre: float(borda.reindex(cols, fill_value=0.0).mean())
            for nombre, cols in modos.items()
        }
    )
    puntajes = normalizar_minmax(puntajes)
    fig_barras_plotly, fig_radar_plotly = _figuras_plotly_barras_radar(
        titulo, circuito, top_vars_bar, puntajes
    )

    if show:
        fig, ax = plt.subplots(figsize=(14, 5))
        top_vars_bar.plot(kind="bar", ax=ax, color=colores, edgecolor="white", linewidth=0.4)
        for val, patch in zip(top_vars_bar.values[:5], ax.patches[:5]):
            ax.text(
                patch.get_x() + patch.get_width() / 2,
                patch.get_height() * 1.015,
                f"{val:.3f}",
                ha="center", va="bottom", fontsize=7.5, color="#1f4e79", fontweight="bold",
            )
        ax.set_title(
            f"Kernel SHAP + Borda ponderado min-max — {circuito}\n{titulo}",
            fontsize=13, fontweight="bold", pad=12,
        )
        ax.set_xlabel("Variable", fontsize=10)
        ax.set_ylabel("Borda ponderado normalizado min-max", fontsize=10)
        ax.set_ylim(0, 1.05)
        ax.tick_params(axis="x", rotation=50, labelsize=8)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        plt.show()

        n_m = len(puntajes)
        ang = np.linspace(0, 2 * np.pi, n_m, endpoint=False)
        ang_c = np.r_[ang, ang[0]]
        val_c = np.r_[puntajes.values, puntajes.values[0]]

        fig, ax = plt.subplots(figsize=(10, 8), subplot_kw={"polar": True})
        ax.plot(ang_c, val_c, color="#1f4e79", linewidth=2.4)
        ax.fill(ang_c, val_c, color="#5b9bd5", alpha=0.35)
        ax.scatter(ang, puntajes.values, color="#17365d", s=60, zorder=3)
        ax.set_xticks(ang)
        ax.set_xticklabels(list(puntajes.index), fontsize=9, fontweight="bold")
        ax.tick_params(axis="x", pad=28)
        ax.set_ylim(0, 1.0)
        ax.grid(alpha=0.35)
        ax.set_title(
            f"Kernel SHAP + Borda promedio min-max por modo — {circuito}\n{titulo}",
            fontsize=13, fontweight="bold", pad=46,
        )
        fig.subplots_adjust(top=0.80, bottom=0.10, left=0.10, right=0.90)
        plt.show()

    return {
        "eventos": df_eventos,
        "borda": borda,
        "variables_normalizadas": top_vars_bar,
        "modos_normalizados": puntajes,
        "metodo_radar": "promedio_borda_ponderado_por_modo_minmax",
        "fig_barras": fig_barras_plotly,
        "fig_radar": fig_radar_plotly,
    }


def _resumen_eventos_tabnet(df_eventos):
    if df_eventos is None or df_eventos.empty:
        return {"n_eventos": 0, "n_vanos": 0, "uiti_vano_prom": None, "uiti_vano_total": None}
    uiti = pd.to_numeric(df_eventos.get("UITI_VANO"), errors="coerce")
    return {
        "n_eventos": int(len(df_eventos)),
        "n_vanos": int(df_eventos["FID_VANO"].nunique()) if "FID_VANO" in df_eventos else 0,
        "uiti_vano_prom": None if uiti.dropna().empty else round(float(uiti.mean()), 4),
        "uiti_vano_total": None if uiti.dropna().empty else round(float(uiti.sum()), 4),
    }


def _buscar_ruta_experta(variable, target="UITI_VANO", ventana_climatica_horas=12):
    try:
        from chec_impacto.data.graph import construir_aristas_grafo_chec
    except ImportError:
        return None

    edges = construir_aristas_grafo_chec(ventana_climatica_horas)
    adjacency = {}
    for source, dest, weight in edges:
        adjacency.setdefault(source, []).append((dest, float(weight)))
    queue = [(variable, [variable], 1.0)]
    visited = set()
    while queue:
        node, path, min_weight = queue.pop(0)
        if node == target:
            return {
                "tiene_camino_a_uiti_vano": True,
                "ruta_resumida": " -> ".join(path),
                "peso_minimo_ruta": round(float(min_weight), 4),
            }
        if node in visited:
            continue
        visited.add(node)
        for next_node, weight in adjacency.get(node, []):
            if next_node not in visited:
                queue.append((next_node, [*path, next_node], min(min_weight, weight)))
    return {
        "tiene_camino_a_uiti_vano": False,
        "ruta_resumida": "sin_camino_experto_detectado",
        "peso_minimo_ruta": None,
    }


def construir_contexto_escenario_tabnet(
    *,
    nombre,
    criterio,
    resultado,
    tabla_top=None,
    modos=None,
    top_k=20,
    fechas_interes=None,
    ventana_climatica_horas=12,
):
    """Build a compact serializable context for one TabNet SHAP scenario."""
    modos = modos or {}
    variables = _series_to_records(resultado.get("variables_normalizadas"), modos=modos, limit=top_k)
    mode_records = _series_to_records(resultado.get("modos_normalizados"))
    for item in variables:
        ruta = _buscar_ruta_experta(
            item["variable"],
            ventana_climatica_horas=ventana_climatica_horas,
        )
        item.update(ruta or {})
    return {
        "nombre": str(nombre),
        "criterio": str(criterio),
        "fechas_interes": list(fechas_interes or []),
        "resumen": _resumen_eventos_tabnet(resultado.get("eventos")),
        "n_vanos_efectivo": int(len(tabla_top)) if tabla_top is not None else None,
        "top_vanos": _tabla_top_records(tabla_top),
        "top_variables": variables,
        "modos": mode_records,
        "metodo_radar": resultado.get("metodo_radar", "promedio_borda_ponderado_por_modo_minmax"),
        "cautelas": [
            "Kernel SHAP explica la salida del modelo TabNet, no causalidad operacional comprobada.",
            "Los scores min-max son comparables dentro del escenario, no como magnitudes crudas entre escenarios.",
        ],
    }


def construir_contexto_tabnet(
    *,
    circuito_interes,
    fecha_inicio,
    fecha_fin,
    fechas_interes,
    top_n_vanos,
    top_k_vars,
    filtro_uiti_max,
    ventana_climatica_horas,
    features,
    base,
    escenarios,
    modelo="TabNet clasificacion",
):
    """Build the TabNet package consumed by the TabNet LLM agent."""
    feature_list = list(features)
    return {
        "analysis_name": "tabnet_shap_top97_interpretability",
        "contexto": {
            "circuito": str(circuito_interes),
            "periodo": {"inicio": str(fecha_inicio), "fin": str(fecha_fin)},
            "fechas_interes": list(fechas_interes or []),
            "top_n_configurado": int(top_n_vanos),
            "top_k_vars": int(top_k_vars),
            "filtro_uiti_max": filtro_uiti_max,
            "ventana_climatica_horas": int(ventana_climatica_horas),
            "n_eventos": int(len(base)),
            "n_vanos": int(base["FID_VANO"].nunique()) if "FID_VANO" in base else 0,
            "n_features": len(feature_list),
            "modelo": str(modelo),
            "metodo_explicacion": "Kernel SHAP + Borda ponderado",
            "normalizacion_graficos": "min-max 0-1 dentro de cada escenario",
        },
        "features": feature_list,
        "escenarios": escenarios,
    }


TABNET_OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "tabnet_shap_interpretation.output_schema.v1",
    "type": "object",
    "additionalProperties": True,
    "required": ["contexto", "escenarios", "hallazgos", "limitaciones"],
    "properties": {
        "contexto": {"type": "object"},
        "escenarios": {"type": "array", "minItems": 1},
        "coherencia_grafo_modelo": {"type": "array"},
        "hallazgos": {"type": "array", "items": {"type": "string"}},
        "limitaciones": {"type": "array", "items": {"type": "string"}},
    },
}


def construir_prompt_tabnet(context_package, skill_bundle, output_schema=None):
    schema = output_schema or TABNET_OUTPUT_SCHEMA
    return (
        "Eres un agente de inferencias CHEC distinto del agente base de puntos criticos. "
        "Debes interpretar exclusivamente el paquete estructurado recibido y devolver JSON valido en espanol.\n\n"
        "Usa estas skills como contrato operativo:\n\n"
        f"{skill_bundle.strip()}\n\n"
        "---\n\n"
        "Contexto de inferencias:\n"
        "```json\n"
        f"{json.dumps(context_package, ensure_ascii=False, indent=2)}\n"
        "```\n\n"
        "Schema de salida:\n"
        "```json\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
        "```\n\n"
        "Devuelve solo JSON valido. Para cada item de `escenarios`, el campo `interpretacion` "
        "debe ser una discusion narrativa de nivel ejecutivo y operativo, similar al agente base: "
        "un parrafo sustantivo que conecte el criterio del escenario, las barras, el radar, los "
        "vanos priorizados, el periodo, la lectura electrica y la cautela metodologica integrada "
        "en la redaccion. No escribas listas de variables ni listas de modos dentro de "
        "`interpretacion`; usa esas senales para construir una lectura. Evita repetir limitaciones "
        "como bullets y evita titular la respuesta con el nombre de un modelo especifico. Interpreta "
        "los escenarios, sus barras de variables, sus radares por modo y la coherencia con el grafo "
        "experto sin afirmar causalidad. Lee los radares como promedio de Borda ponderado por modo "
        "normalizado min-max, no como suma total; por tanto no sobreponderan modos con muchas variables."
    )


def validar_respuesta_tabnet(response_text, context_package, schema=None):
    from chec_local_interpreter.llm_validation import parse_llm_json

    errors = []
    try:
        data = parse_llm_json(response_text)
    except json.JSONDecodeError as exc:
        return {"ok": False, "data": None, "errors": [f"Invalid JSON: {exc}"]}

    schema = schema or TABNET_OUTPUT_SCHEMA
    if Draft202012Validator is not None:
        validator = Draft202012Validator(schema)
        for error in sorted(validator.iter_errors(data), key=lambda item: item.path):
            location = ".".join(str(part) for part in error.path) or "<root>"
            errors.append(f"{location}: {error.message}")

    expected_circuit = str(context_package.get("contexto", {}).get("circuito"))
    reported_circuit = str(data.get("contexto", {}).get("circuito"))
    if reported_circuit and reported_circuit != expected_circuit:
        errors.append(f"Circuito reportado no coincide: {reported_circuit} != {expected_circuit}")

    scenario_names = {s.get("nombre") for s in context_package.get("escenarios", [])}
    for scenario in data.get("escenarios", []):
        if isinstance(scenario, dict) and scenario.get("nombre") not in scenario_names:
            errors.append(f"Escenario fuera del contexto: {scenario.get('nombre')}")

    return {"ok": not errors, "data": data, "errors": errors}


def _calcular_radar_tabnet(
    model,
    X,
    df,
    modos,
    predictions=None,
    ponderar_por_clase=True,
):
    _, masks = model.explain(X)

    masks_list = [
        np.asarray(masks[k])
        for k in (
            sorted(masks.keys())
            if isinstance(masks, dict)
            else range(len(masks))
        )
    ]

    mask_avg_steps = np.mean(masks_list, axis=0)
    mask_normalized = mask_avg_steps / (mask_avg_steps.sum(axis=1, keepdims=True) + 1e-8)

    if predictions is None:
        preds_array = np.ones((mask_normalized.shape[0], 1))
    else:
        preds_array = np.asarray(predictions).reshape(-1, 1).astype(float)

    pesos_pred = preds_array + 1.0 if ponderar_por_clase else np.ones_like(preds_array)
    atribucion_matrix = mask_normalized * pesos_pred
    df_atrib = pd.DataFrame(atribucion_matrix, columns=df.columns)

    mode_scores = {}
    for modo, variables in modos.items():
        vars_presentes = [v for v in variables if v in df_atrib.columns]
        if len(vars_presentes) == 0:
            score = 0.0
        else:
            score = df_atrib[vars_presentes].sum(axis=1).mean()
        mode_scores[modo] = float(score)

    return pd.Series(mode_scores), df_atrib


def _dibujar_radar(ax, mode_scores, max_val, title, cmap_name="RdYlGn_r"):
    categorias = list(mode_scores.index)
    valores = mode_scores.values.tolist()

    angles = np.linspace(0, 2 * np.pi, len(categorias), endpoint=False).tolist()
    valores_loop = valores + valores[:1]
    angles_loop = angles + angles[:1]

    ax.set_ylim(0, max_val)
    ax.set_xticks(angles)
    ax.set_xticklabels(categorias, size=10, fontweight="bold")
    ax.tick_params(axis="both", which="major", pad=15)

    r_grid = np.linspace(0, max_val, 100)
    theta_grid = np.linspace(0, 2 * np.pi, 100)
    radius_grid, theta_mesh = np.meshgrid(r_grid, theta_grid)

    gradient = ax.pcolormesh(
        theta_mesh,
        radius_grid,
        radius_grid,
        cmap=cmap_name,
        shading="gouraud",
        zorder=1,
    )

    verts = np.column_stack([angles_loop, valores_loop])
    path_data = mpath.Path(verts)
    patch = mpatches.PathPatch(
        path_data,
        transform=ax.transData,
        facecolor="none",
        edgecolor="none",
    )
    ax.add_patch(patch)
    gradient.set_clip_path(patch)

    ax.plot(angles_loop, valores_loop, color="#444444", linewidth=2, zorder=3)
    ax.scatter(angles, valores, color="#222222", s=45, zorder=4, edgecolor="white")
    ax.set_title(title, size=12, fontweight="bold", pad=18)


def radar_atribucion_degradado(
    clf,
    X,
    df,
    modos,
    predictions,
    cmap_name="RdYlGn_r",
    figsize=(9, 9),
    title="Atribución con Degradado Dinámico",
    ponderar_por_clase=True,
):
    mode_scores, df_atrib = _calcular_radar_tabnet(
        clf,
        X,
        df,
        modos,
        predictions=predictions,
        ponderar_por_clase=ponderar_por_clase,
    )
    max_val = mode_scores.max() * 1.2 if mode_scores.max() > 0 else 1.0

    fig, ax = plt.subplots(figsize=figsize, subplot_kw=dict(polar=True))
    _dibujar_radar(ax, mode_scores, max_val, title, cmap_name=cmap_name)
    plt.tight_layout()
    plt.show()

    return mode_scores, df_atrib


def radar_atribucion_degradado_modelos(
    modelos,
    X,
    df,
    modos,
    cmap_name="RdYlGn_r",
    figsize=(12, 12),
    title="Atribución TabNet por tipo de modelo",
):
    orden = [m for m in ["clasificacion", "regresion"] if m in modelos]
    if not orden:
        raise ValueError("No hay modelos disponibles para graficar.")

    resultados = {}
    max_global = 0.0

    for modo_modelo in orden:
        model = modelos[modo_modelo]
        preds = model.predict(X)
        ponderar = modo_modelo == "clasificacion"
        mode_scores, df_atrib = _calcular_radar_tabnet(
            model,
            X,
            df,
            modos,
            predictions=preds,
            ponderar_por_clase=ponderar,
        )
        resultados[modo_modelo] = {
            "mode_scores": mode_scores,
            "df_atrib": df_atrib,
            "predictions": preds,
        }
        max_global = max(max_global, mode_scores.max())

    max_global = max_global * 1.2 if max_global > 0 else 1.0

    fig, axes = plt.subplots(
        len(orden),
        1,
        figsize=figsize,
        subplot_kw=dict(polar=True),
    )
    if len(orden) == 1:
        axes = [axes]

    for ax, modo_modelo in zip(axes, orden):
        etiqueta = "Clasificación" if modo_modelo == "clasificacion" else "Regresión"
        _dibujar_radar(
            ax,
            resultados[modo_modelo]["mode_scores"],
            max_global,
            etiqueta,
            cmap_name=cmap_name,
        )

    plt.suptitle(title, fontsize=16, fontweight="bold", y=1.02)
    plt.tight_layout()
    plt.show()

    return resultados


def _extraer_shap_matrix(shap_values, class_idx=1):
    if isinstance(shap_values, list):
        if len(shap_values) > class_idx:
            shap_matrix = shap_values[class_idx]
        else:
            shap_matrix = shap_values[-1]
    else:
        shap_values = np.asarray(shap_values)
        if shap_values.ndim == 2:
            shap_matrix = shap_values
        elif shap_values.ndim == 3:
            if shap_values.shape[2] > class_idx:
                shap_matrix = shap_values[:, :, class_idx]
            else:
                shap_matrix = shap_values[:, :, -1]
        else:
            raise ValueError(
                f"Formato de shap_values no soportado. Shape recibido: {shap_values.shape}"
            )

    shap_matrix = np.asarray(shap_matrix)
    if shap_matrix.ndim != 2:
        raise ValueError(
            f"shap_matrix debe ser 2D, pero tiene shape: {shap_matrix.shape}"
        )
    return shap_matrix


def _calcular_kernel_shap_modelo(
    model,
    X,
    df,
    modos,
    background_size=50,
    sample_size_explain=100,
    nsamples=100,
    class_indices=(0, 1, 2, 3),
    use_abs=True,
):
    X = np.asarray(X)
    if X.shape[1] != len(df.columns):
        raise ValueError(
            f"X tiene {X.shape[1]} columnas pero df tiene {len(df.columns)} columnas."
        )

    if sample_size_explain is not None and sample_size_explain < len(X):
        idx_eval = np.random.choice(len(X), size=sample_size_explain, replace=False)
        X_eval = X[idx_eval]
    else:
        X_eval = X

    bg_size = min(background_size, len(X))
    idx_bg = np.random.choice(len(X), size=bg_size, replace=False)
    X_bg = X[idx_bg]

    predict_fn = model.predict_proba if hasattr(model, "predict_proba") else model.predict

    def predict_kernel(X_input):
        X_input = np.asarray(X_input)
        pred = predict_fn(X_input)
        return np.asarray(pred)

    explainer = shap.KernelExplainer(predict_kernel, X_bg)
    shap_values = explainer.shap_values(X_eval, nsamples=nsamples)

    outputs = class_indices if hasattr(model, "predict_proba") else ("regresion",)
    resultados = {}

    for output_idx in outputs:
        class_idx = output_idx if isinstance(output_idx, int) else 0
        shap_matrix = _extraer_shap_matrix(shap_values, class_idx=class_idx)

        if use_abs:
            shap_matrix = np.abs(shap_matrix)

        df_atrib = pd.DataFrame(shap_matrix, columns=df.columns)
        mode_scores = {}

        for modo, variables in modos.items():
            vars_presentes = [v for v in variables if v in df_atrib.columns]
            if len(vars_presentes) == 0:
                mode_scores[modo] = 0.0
            else:
                mode_scores[modo] = float(df_atrib[vars_presentes].sum(axis=1).mean())

        resultados[output_idx] = {
            "mode_scores": pd.Series(mode_scores),
            "df_atrib": df_atrib,
        }

    return resultados, shap_values


def comparar_radar_kernel_shap_modelos(
    modelos,
    X,
    df,
    modos,
    background_size=50,
    sample_size_explain=100,
    nsamples=100,
    class_indices=(0, 1, 2, 3),
    use_abs=True,
    cmap_name="RdYlGn_r",
    figsize=(22, 10),
    title="Comparación de atribuciones por modos usando Kernel SHAP",
):
    orden = [m for m in ["clasificacion", "regresion"] if m in modelos]
    if not orden:
        raise ValueError("No hay modelos disponibles para Kernel SHAP.")

    resultados = {}
    shap_values_por_modelo = {}
    max_global = 0.0

    for modo_modelo in orden:
        resultados_modo, shap_values = _calcular_kernel_shap_modelo(
            modelos[modo_modelo],
            X,
            df,
            modos,
            background_size=background_size,
            sample_size_explain=sample_size_explain,
            nsamples=nsamples,
            class_indices=class_indices,
            use_abs=use_abs,
        )
        resultados[modo_modelo] = resultados_modo
        shap_values_por_modelo[modo_modelo] = shap_values

        for item in resultados_modo.values():
            max_global = max(max_global, item["mode_scores"].max())

    max_global = max_global * 1.2 if max_global > 0 else 1.0
    n_cols = len(class_indices)

    fig, axes = plt.subplots(
        2,
        n_cols,
        figsize=figsize,
        subplot_kw=dict(polar=True),
    )

    for row_idx, modo_modelo in enumerate(["clasificacion", "regresion"]):
        for col_idx in range(n_cols):
            ax = axes[row_idx, col_idx]

            if modo_modelo not in resultados:
                ax.set_visible(False)
                continue

            if modo_modelo == "clasificacion":
                output_key = class_indices[col_idx]
                if output_key not in resultados[modo_modelo]:
                    ax.set_visible(False)
                    continue
                titulo_ax = f"Clasificación - Clase {output_key}"
            else:
                if col_idx > 0:
                    ax.set_visible(False)
                    continue
                output_key = "regresion"
                titulo_ax = "Regresión"

            _dibujar_radar(
                ax,
                resultados[modo_modelo][output_key]["mode_scores"],
                max_global,
                titulo_ax,
                cmap_name=cmap_name,
            )

    plt.suptitle(title, fontsize=16, fontweight="bold", y=1.03)
    plt.tight_layout()
    plt.show()

    tablas = {}
    if "clasificacion" in resultados:
        tablas["clasificacion"] = pd.DataFrame({
            f"Clase_{class_idx}": resultados["clasificacion"][class_idx]["mode_scores"]
            for class_idx in class_indices
            if class_idx in resultados["clasificacion"]
        })
    if "regresion" in resultados:
        tablas["regresion"] = pd.DataFrame({
            "Regresion": resultados["regresion"]["regresion"]["mode_scores"]
        })

    return resultados, tablas, shap_values_por_modelo


def comparar_radar_kernel_shap_4_clases(clf, *args, **kwargs):
    return comparar_radar_kernel_shap_modelos({"clasificacion": clf}, *args, **kwargs)
