from __future__ import annotations

from contextlib import redirect_stdout
import html
import io
import json
import matplotlib.patches as mpatches
import matplotlib.path as mpath
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pathlib import Path
import shap
import torch
import warnings

from chec_impacto.training.mgcecdl import predict_classification


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


def predict_proba_positiva(model, x_np):
    """Return positive-class probabilities, guarding single-row prediction quirks."""
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


class MGCECDLClassifierShapAdapter:
    """Expose an MGCECDL classifier through a scikit-learn-like predict_proba API."""

    def __init__(self, model, device):
        self.model = model
        self.device = device

    def predict_proba(self, values):
        values = np.asarray(values, dtype=np.float32)
        if values.ndim == 1:
            values = values.reshape(1, -1)
        return np.asarray(
            predict_classification(self.model, values, device=self.device)["fused_probs"],
            dtype=np.float64,
        )


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
            return predict_proba_positiva(self.model, x_np)

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


def _normalizar_nombre_archivo(value):
    text = str(value).strip().lower()
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    normalized = []
    for char in text:
        if char.isalnum():
            normalized.append(char)
        elif char in {" ", "-", "_"}:
            normalized.append("_")
    slug = "".join(normalized).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "grafo"


def estimar_matriz_grafo_mgcecdl(
    model,
    X,
    features,
    rbf_sigma=1.0,
    device="cpu",
    batch_size=1024,
):
    """Estimate a variable-variable matrix from the MGCECDL decoder reconstructions."""
    X = np.asarray(X, dtype=np.float32)
    if X.ndim != 2:
        raise ValueError("X debe ser una matriz 2D.")
    feature_list = list(features)
    if X.shape[1] != len(feature_list):
        raise ValueError("X y features no tienen el mismo numero de columnas.")

    resolved_device = torch.device(device)
    model = model.to(resolved_device)
    model.eval()
    reconstructed_batches = []
    with torch.no_grad():
        for start in range(0, len(X), int(batch_size)):
            x_batch = torch.as_tensor(
                X[start:start + int(batch_size)],
                dtype=torch.float32,
                device=resolved_device,
            )
            outputs = model(x_batch)
            reconstructed_batches.append(outputs["reconstructed_features"].detach().cpu().numpy())

    reconstructed_features = np.vstack(reconstructed_batches)
    variable_profiles = reconstructed_features.T
    squared_norms = np.sum(variable_profiles**2, axis=1, keepdims=True)
    squared_distances = np.maximum(
        squared_norms + squared_norms.T - 2.0 * variable_profiles @ variable_profiles.T,
        0.0,
    )
    profile_dim = max(variable_profiles.shape[1], 1)
    squared_distances = squared_distances / profile_dim
    sigma = max(float(rbf_sigma), 1e-8)
    estimated_matrix = np.exp(-squared_distances / (2.0 * sigma**2)).astype(np.float32)
    np.fill_diagonal(estimated_matrix, 0.0)
    return estimated_matrix


_MODO_PALETTE = [
    "#e74c3c", "#f39c12", "#9b59b6", "#3498db",
    "#1abc9c", "#2ecc71", "#e67e22", "#16a085", "#2980b9",
]


def construir_grafo_interactivo_muestras(
    feature_scores,
    features,
    graph_adjacency_matrix,
    graph_preserved_edges=None,
    output_path=None,
    title="Grafo interactivo de variables relevantes",
    top_k=20,
    height="680px",
    min_edge_weight=1e-8,
    max_edges=80,
    modos=None,
):
    """Create an interactive vis-network HTML graph for the most relevant variables."""
    scores = pd.Series(feature_scores, dtype=float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    scores = scores[scores > 0].sort_values(ascending=False).head(int(top_k))
    if scores.empty:
        raise ValueError("No hay variables con puntaje positivo para construir el grafo.")

    feature_list = list(features)
    positions = {feature: index for index, feature in enumerate(feature_list)}
    adjacency = np.asarray(graph_adjacency_matrix, dtype=float)
    if adjacency.shape != (len(feature_list), len(feature_list)):
        raise ValueError(
            "graph_adjacency_matrix debe tener forma "
            f"({len(feature_list)}, {len(feature_list)})."
        )

    selected_features = [f for f in scores.index if f in positions]
    selected_set = set(selected_features)
    score_norm = normalizar_minmax(scores.reindex(selected_features, fill_value=0.0))

    mode_styles = {}
    for idx, mode_name in enumerate(modos or {}):
        mode_id = chr(ord("A") + idx)
        mode_styles[mode_name] = {"id": mode_id}

    feature_to_mode = {}
    if modos:
        for mode_name, mode_feats in modos.items():
            for feat in mode_feats:
                if feat not in feature_to_mode:
                    feature_to_mode[feat] = {
                        "name": mode_name.replace("\n", " "),
                        **mode_styles.get(mode_name, {"id": "", "color": "#7f8c8d"}),
                    }

    nodes = []
    for feature in selected_features:
        score_val = float(score_norm.loc[feature])
        mode_info = feature_to_mode.get(feature, {"id": "", "name": "Sin modo asignado"})
        tooltip_lines = [
            str(feature),
            f"Relevancia: {score_val:.3e}",
        ]
        nodes.append({
            "id": feature,
            "label": feature,
            "_score": score_val,
            "mode_id": mode_info["id"],
            "mode_name": mode_info["name"],
            "title": "\n".join(tooltip_lines),
        })

    preserved_lookup = {}
    for edge in graph_preserved_edges or []:
        source = str(edge.get("source"))
        target = str(edge.get("target"))
        preserved_lookup[(source, target)] = edge

    edge_by_pair = {}
    for left_pos, source in enumerate(selected_features):
        source_index = positions[source]
        for target in selected_features[left_pos + 1:]:
            target_index = positions[target]
            forward_weight = float(adjacency[source_index, target_index])
            backward_weight = float(adjacency[target_index, source_index])
            weight = max(forward_weight, backward_weight)
            if weight <= float(min_edge_weight):
                continue

            edge_source, edge_target = (source, target) if forward_weight >= backward_weight else (target, source)
            edge_info = (
                preserved_lookup.get((edge_source, edge_target))
                or preserved_lookup.get((edge_target, edge_source))
                or {}
            )
            is_virtual = bool(edge_info.get("is_virtual", False))
            pair_key = frozenset((source, target))
            edge_by_pair[pair_key] = (weight, edge_source, edge_target, is_virtual)

    edge_candidates = sorted(edge_by_pair.values(), key=lambda item: item[0], reverse=True)
    if max_edges is not None:
        edge_candidates = edge_candidates[: int(max_edges)]

    raw_edge_weights = [item[0] for item in edge_candidates]
    max_raw_edge = max(raw_edge_weights) if raw_edge_weights else 0.0

    edges = []
    for weight, source, target, is_virtual in edge_candidates:
        norm_w = weight / max_raw_edge if max_raw_edge > 0 else 0.0
        edge_tooltip = f"Valor: {weight:.3e}"
        edges.append({
            "from": source,
            "to": target,
            "_norm_w": norm_w,
            "width": round(0.5 + 8.5 * norm_w, 2),
            "title": edge_tooltip,
            "color": {"color": "#555555", "opacity": round(0.34 + 0.58 * norm_w, 3)},
            "dashes": is_virtual,
            "arrows": {"to": {"enabled": True, "scaleFactor": 0.48}},
        })

    # --- Output path and graph ID ---
    output_path = Path(output_path or "grafo_interactivo_mgcecdl.html")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph_id = f"net_{_normalizar_nombre_archivo(output_path.stem)}"

    payload_json = json.dumps(
        {"nodes": nodes, "edges": edges},
        ensure_ascii=False,
    )
    title_esc = html.escape(str(title))
    height_esc = html.escape(str(height))

    html_doc = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title_esc}</title>
  <link rel="stylesheet"
    href="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/dist/dist/vis-network.min.css"
    integrity="sha512-WgxfT5LWjfszlPHXRmBWHkV2eceiWTOBvrKCNbdgDYTHrT2AeLCGbF4sZlZw3UMN3WtL0tGUoIAKsu8mllg/XA=="
    crossorigin="anonymous" referrerpolicy="no-referrer" />
  <script
    src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/dist/vis-network.min.js"
    integrity="sha512-LnvoEWDFrqGHlHmDD2101OrLcbsfkrzoSpvtSQtxK3RMnRV0eOkhhBN2dXHKRrUU8p2DGRTk35n4O8nWSVe1mQ=="
    crossorigin="anonymous" referrerpolicy="no-referrer"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      background: #ffffff;
      color: #1a2332;
      overflow: hidden;
    }}
    .layout {{ position: relative; height: {height_esc}; }}
    .graph-wrap {{
      position: absolute; inset: 0;
      background: #ffffff;
    }}
    #{graph_id} {{ width: 100%; height: 100%; }}
  </style>
</head>
<body>
  <div class="layout">
    <div class="graph-wrap">
      <div id="{graph_id}"></div>
    </div>
  </div>

  <script>
  (() => {{
    function lerpRGB(a, b, t) {{
      return [
        Math.round(a[0] + t * (b[0] - a[0])),
        Math.round(a[1] + t * (b[1] - a[1])),
        Math.round(a[2] + t * (b[2] - a[2])),
      ];
    }}
    const CS = [[69,117,180],[255,255,191],[215,48,39]];
    function scoreToCSS(t) {{
      t = Math.max(0, Math.min(1, t));
      const rgb = t <= 0.5 ? lerpRGB(CS[0], CS[1], t * 2) : lerpRGB(CS[1], CS[2], (t - 0.5) * 2);
      return `rgb(${{rgb[0]}},${{rgb[1]}},${{rgb[2]}})`;
    }}

    const payload = {payload_json};
    const container = document.getElementById('{graph_id}');

    if (typeof vis === 'undefined') {{
      container.innerHTML = `
        <div style="margin:24px;padding:20px;border:1px solid #d1dce8;border-radius:8px;
                    background:#f8fafc;color:#3d5166;font-family:system-ui,sans-serif;">
          <b style="font-size:14px;">vis-network no disponible</b>
          <p style="margin-top:8px;font-size:12px;line-height:1.6;">
            Abre este archivo en un navegador con acceso a internet.
          </p>
        </div>`;
      return;
    }}

    var nodes = new vis.DataSet(
      payload.nodes.map(n => {{
        const bg = scoreToCSS(n._score);
        return {{
          id: n.id, label: n.label, title: n.title,
          size: 16 + 8 * Math.max(0, Math.min(1, n._score)), shape: 'dot',
          color: {{
            background: bg,
            border: bg,
            highlight: {{ background: bg, border: '#2c3e50' }},
            hover:     {{ background: bg, border: '#2c3e50' }},
          }},
          font: {{
            size: 14, color: '#000000',
            face: "'Segoe UI', system-ui, sans-serif",
            strokeWidth: 0,
          }},
          borderWidth: 1,
          borderWidthSelected: 3,
        }};
      }})
    );

    var edges = new vis.DataSet(
      payload.edges.map(e => ({{
        from: e.from, to: e.to,
        width: e.width, title: e.title,
        color: e.color, dashes: e.dashes,
        arrows: e.arrows,
        smooth: {{ type: 'dynamic' }},
      }}))
    );

    // --- Resaltado de vecindad (click) ---
    const origColors = {{}};
    const origLabels = {{}};
    nodes.get().forEach(n => {{ origColors[n.id] = n.color; origLabels[n.id] = n.label; }});
    let highlightActive = false;

    function resetHighlight() {{
      nodes.update(nodes.get().map(n => ({{
        id: n.id, color: origColors[n.id], label: origLabels[n.id],
      }})));
      highlightActive = false;
    }}

    function applyHighlight(selId) {{
      const conn = new Set(network.getConnectedNodes(selId));
      nodes.update(nodes.get().map(n => {{
        const fade = n.id !== selId && !conn.has(n.id);
        return {{
          id: n.id,
          color: fade
            ? {{ background:'rgba(210,222,234,0.38)', border:'rgba(180,200,220,0.42)' }}
            : origColors[n.id],
          label: fade ? undefined : origLabels[n.id],
        }};
      }}));
      highlightActive = true;
    }}

    // --- F&iacute;sica con inercia (barnesHut, amortiguaci&oacute;n baja) ---
    const options = {{
      physics: {{
        enabled: true,
        solver: 'barnesHut',
        barnesHut: {{
          gravitationalConstant: -2000,
          centralGravity: 0.1,
          springLength: 150,
          springConstant: 0.05,
          damping: 0.9,
          avoidOverlap: 0.12,
        }},
        stabilization: {{ enabled: true, fit: true, iterations: 550, updateInterval: 30 }},
      }},
      interaction: {{
        hover: true, tooltipDelay: 60,
        navigationButtons: false,
        keyboard: {{ enabled: false, bindToWindow: false }},
        zoomView: true, dragNodes: true,
      }},
      nodes: {{ shape: 'dot' }},
      edges: {{
        smooth: {{ type: 'dynamic' }},
        hoverWidth: w => w + 1,
        selectionWidth: w => w + 2,
      }},
    }};

    const network = new vis.Network(container, {{ nodes, edges }}, options);

    network.on('click', params => {{
      if (params.nodes.length > 0) {{
        applyHighlight(params.nodes[0]);
      }} else if (highlightActive) {{
        resetHighlight();
      }}
    }});

    network.once('stabilizationIterationsDone', () => {{
      network.fit({{ animation: {{ duration: 500, easingFunction: 'easeInOutQuad' }} }});
      // Reducir fuerzas pero mantener f&iacute;sica activa → inercia al arrastrar
      network.setOptions({{
        physics: {{
          barnesHut: {{
            gravitationalConstant: -2000,
            springConstant: 0.05,
            damping: 0.9,
          }}
        }}
      }});
    }});
  }})();
  </script>
</body>
</html>
"""
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


def mostrar_grafo_interactivo_muestras(*args, **kwargs):
    """Create an interactive graph HTML and return its path."""
    output_path = construir_grafo_interactivo_muestras(*args, **kwargs)
    print(f"Grafo interactivo guardado en: {output_path}")
    return output_path


def graficar_barras_y_radar(
    df_eventos,
    titulo,
    circuito,
    features,
    modos,
    shap_extractor,
    top_k=20,
    graph_adjacency_matrix=None,
    graph_preserved_edges=None,
    graph_output_dir=None,
    graph_output_name=None,
    graph_source="expert",
    estimated_graph_model=None,
    X_model=None,
    estimated_graph_rbf_sigma=1.0,
    estimated_graph_device="cpu",
    estimated_graph_batch_size=1024,
):
    """Plot feature bars, mode radar, and optionally an interactive graph."""
    if df_eventos.empty:
        raise ValueError(f"Sin eventos para: {titulo}")

    df_eventos = shap_extractor.agregar_top_vars(df_eventos)
    borda = puntaje_borda_ponderado_eventos(df_eventos, features, top_k=top_k)
    print(f"{titulo} | eventos: {len(df_eventos):,} | vanos: {df_eventos['FID_VANO'].nunique()}")

    top_vars_bar = normalizar_minmax(borda).sort_values(ascending=False).head(top_k)
    colores = ["#1f4e79" if i < 5 else "#5b9bd5" for i in range(len(top_vars_bar))]

    fig_barras, ax = plt.subplots(figsize=(14, 5))
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
    fig_barras.tight_layout()
    plt.show()

    puntajes = pd.Series(
        {nombre: float(borda.reindex(cols, fill_value=0.0).sum()) for nombre, cols in modos.items()}
    )
    puntajes = normalizar_minmax(puntajes)
    n_m = len(puntajes)
    ang = np.linspace(0, 2 * np.pi, n_m, endpoint=False)
    ang_c = np.r_[ang, ang[0]]
    val_c = np.r_[puntajes.values, puntajes.values[0]]

    fig_radar, ax = plt.subplots(figsize=(10, 8), subplot_kw={"polar": True})
    ax.plot(ang_c, val_c, color="#1f4e79", linewidth=2.4)
    ax.fill(ang_c, val_c, color="#5b9bd5", alpha=0.35)
    ax.scatter(ang, puntajes.values, color="#17365d", s=60, zorder=3)
    ax.set_xticks(ang)
    ax.set_xticklabels(list(puntajes.index), fontsize=9, fontweight="bold")
    ax.tick_params(axis="x", pad=28)
    ax.set_ylim(0, 1.0)
    ax.grid(alpha=0.35)
    ax.set_title(
        f"Kernel SHAP + Borda ponderado min-max por modo — {circuito}\n{titulo}",
        fontsize=13, fontweight="bold", pad=46,
    )
    fig_radar.subplots_adjust(top=0.80, bottom=0.10, left=0.10, right=0.90)
    plt.show()

    graph_path = None
    if graph_adjacency_matrix is not None or estimated_graph_model is not None:
        if graph_source == "estimated":
            if estimated_graph_model is None or X_model is None:
                raise ValueError(
                    "graph_source='estimated' requiere estimated_graph_model y X_model."
                )
            scenario_indices = df_eventos.index.to_numpy(dtype=int)
            scenario_X = np.asarray(X_model, dtype=np.float32)[scenario_indices]
            graph_matrix = estimar_matriz_grafo_mgcecdl(
                model=estimated_graph_model,
                X=scenario_X,
                features=features,
                rbf_sigma=estimated_graph_rbf_sigma,
                device=estimated_graph_device,
                batch_size=estimated_graph_batch_size,
            )
            preserved_edges = None
            source_label = "matriz estimada por reconstruccion"
        else:
            graph_matrix = graph_adjacency_matrix
            preserved_edges = graph_preserved_edges
            source_label = "grafo experto preservado"

        output_dir = Path(graph_output_dir or ".")
        output_name = graph_output_name or _normalizar_nombre_archivo(
            f"{circuito}_{titulo}_grafo_mgcecdl.html"
        )
        if not str(output_name).lower().endswith(".html"):
            output_name = f"{output_name}.html"
        graph_path = mostrar_grafo_interactivo_muestras(
            feature_scores=borda,
            features=features,
            graph_adjacency_matrix=graph_matrix,
            graph_preserved_edges=preserved_edges,
            output_path=output_dir / output_name,
            title=f"Grafo interactivo MGCECDL ({source_label}) — {circuito} | {titulo}",
            top_k=top_k,
            modos=modos,  # pasado para enriquecer tooltips con nombre del modo
        )

    return {
        "eventos": df_eventos,
        "borda": borda,
        "variables_normalizadas": top_vars_bar,
        "modos_normalizados": puntajes,
        "grafo_interactivo": graph_path,
        "fig_barras": fig_barras,
        "fig_radar": fig_radar,
    }


def _series_to_score_records(series, limit=None):
    if series is None:
        return []
    ordered = series.sort_values(ascending=False)
    if limit is not None:
        ordered = ordered.head(int(limit))
    return [
        {"nombre": str(index), "score_normalizado": float(value)}
        for index, value in ordered.items()
    ]


def construir_contexto_escenario_inferencia(
    nombre,
    criterio,
    resultado,
    tabla_top,
    modos,
    top_k=20,
    fechas_interes=None,
    ventana_climatica_horas=12,
):
    """Build a compact, JSON-safe context for one MGCECDL inference scenario."""
    graph_path = resultado.get("grafo_interactivo") if isinstance(resultado, dict) else None
    graph_path_text = str(graph_path) if graph_path is not None else None
    variables = resultado.get("variables_normalizadas") if isinstance(resultado, dict) else None
    mode_scores = resultado.get("modos_normalizados") if isinstance(resultado, dict) else None
    eventos = resultado.get("eventos") if isinstance(resultado, dict) else None
    tabla_records = (
        tabla_top.head(20)
        .where(pd.notna(tabla_top.head(20)), None)
        .to_dict(orient="records")
        if isinstance(tabla_top, pd.DataFrame)
        else []
    )
    return {
        "nombre": str(nombre),
        "criterio": str(criterio),
        "fechas_interes": list(fechas_interes or []),
        "n_eventos": int(len(eventos)) if isinstance(eventos, pd.DataFrame) else 0,
        "n_vanos_efectivo": int(len(tabla_top)) if isinstance(tabla_top, pd.DataFrame) else 0,
        "top_k_vars": int(top_k),
        "ventana_climatica_horas": int(ventana_climatica_horas),
        "top_variables": _series_to_score_records(variables, limit=top_k),
        "modos": _series_to_score_records(mode_scores),
        "tabla_top_vanos": tabla_records,
        "grafo": {
            "path": graph_path_text,
            "fuente": "reconstruccion_mgcecdl_rbf" if graph_path_text else None,
            "pesos": "normalizados_0_1_por_maximo" if graph_path_text else None,
        },
    }


def construir_contexto_inferencia(
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
    modelo,
    graph_feature_order=None,
    estimated_graph_source="reconstruccion_mgcecdl_rbf",
    estimated_graph_rbf_sigma=None,
    top_vanos_percentile=None,
):
    """Build the structured context consumed by the inference LLM skills."""
    features_list = [str(feature) for feature in features]
    graph_paths = []
    for escenario in escenarios:
        if not isinstance(escenario, dict):
            continue
        graph_info = escenario.get("grafo", {})
        if isinstance(graph_info, dict) and graph_info.get("path"):
            graph_paths.append(
                {
                    "escenario": escenario.get("nombre"),
                    "path": graph_info.get("path"),
                    "fuente": graph_info.get("fuente"),
                    "pesos": graph_info.get("pesos"),
                }
            )
    return {
        "circuito_interes": str(circuito_interes),
        "fecha_inicio": str(fecha_inicio),
        "fecha_fin": str(fecha_fin),
        "fechas_interes": list(fechas_interes or []),
        "top_n_vanos": int(top_n_vanos),
        "top_vanos_percentile": None if top_vanos_percentile is None else float(top_vanos_percentile),
        "top_k_vars": int(top_k_vars),
        "filtro_uiti_max": filtro_uiti_max,
        "ventana_climatica_horas": int(ventana_climatica_horas),
        "modelo": str(modelo),
        "modelo_tipo": "mgcecdl_clasificacion",
        "n_eventos": int(len(base)) if isinstance(base, pd.DataFrame) else None,
        "n_vanos": int(base["FID_VANO"].nunique()) if isinstance(base, pd.DataFrame) and "FID_VANO" in base else None,
        "n_features": len(features_list),
        "features": features_list,
        "graph_feature_order": graph_feature_order or features_list,
        "estimated_graph_source": estimated_graph_source,
        "estimated_graph_rbf_sigma": estimated_graph_rbf_sigma,
        "graph_html_paths": graph_paths,
        "escenarios": list(escenarios),
        "metadata": {
            "uiti_vano_es_objetivo": True,
            "features_no_incluyen_objetivo": "UITI_VANO" not in features_list,
            "grafo_estimado_desde_reconstruccion": bool(graph_paths),
        },
    }


def _compactar_contexto_inferencia_para_prompt(context_package, *, top_variables_limit=3, modos_limit=3, tabla_limit=0):
    """Return the same inference context with bounded lists for LLM generation."""
    if not isinstance(context_package, dict):
        return context_package

    compact = dict(context_package)
    compact["features"] = list(context_package.get("features", []))
    compact["graph_feature_order"] = list(context_package.get("graph_feature_order", []))
    escenarios_compactos = []
    for escenario in context_package.get("escenarios", []):
        if not isinstance(escenario, dict):
            continue
        escenario_out = dict(escenario)
        escenario_out["top_variables"] = list(escenario.get("top_variables", []))[:top_variables_limit]
        escenario_out["modos"] = list(escenario.get("modos", []))[:modos_limit]
        escenario_out["tabla_top_vanos"] = list(escenario.get("tabla_top_vanos", []))[:tabla_limit]
        escenario_out["tabla_top_vanos_resumen"] = (
            f"Se entrega solo una muestra de {min(tabla_limit, len(escenario.get('tabla_top_vanos', [])))} "
            f"registros; n_vanos_efectivo conserva el total seleccionado."
        )
        escenarios_compactos.append(escenario_out)
    compact["escenarios"] = escenarios_compactos
    return compact


def construir_prompt_inferencia(context_package, skill_bundle):
    """Render the MGCECDL inference prompt from context plus loaded skills."""
    prompt_context = _compactar_contexto_inferencia_para_prompt(context_package)
    return (
        "Eres un agente de interpretacion de inferencia MGCECDL para CHEC. "
        "Todas las instrucciones tecnicas y de salida estan en las skills cargadas. "
        "Devuelve solo JSON valido y usa exclusivamente el contexto entregado.\n\n"
        "## Skills de inferencia\n"
        f"{skill_bundle}\n\n"
        "## Contexto estructurado\n"
        f"{json.dumps(prompt_context, ensure_ascii=False, indent=2)}"
    )


def validar_respuesta_inferencia(response_text, context_package):
    """Validate a JSON inference-agent response with lightweight scenario checks."""
    try:
        text = str(response_text).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"ok": False, "data": None, "errors": [f"JSON invalido: {exc}"]}

    errors = []
    if not isinstance(data, dict):
        return {"ok": False, "data": None, "errors": ["La respuesta debe ser un objeto JSON."]}

    expected_names = {
        str(item.get("nombre"))
        for item in context_package.get("escenarios", [])
        if isinstance(item, dict) and item.get("nombre")
    }
    received_names = {
        str(item.get("nombre"))
        for item in data.get("escenarios", [])
        if isinstance(item, dict) and item.get("nombre")
    }
    missing = sorted(expected_names - received_names)
    if missing:
        errors.append(f"Faltan escenarios en la respuesta: {missing}")

    expected_graphs = [
        item
        for item in context_package.get("graph_html_paths", [])
        if isinstance(item, dict) and item.get("path")
    ]
    graph_discussions = data.get("discusion_grafos", [])
    if isinstance(graph_discussions, dict):
        graph_discussions = [
            {"seccion": key, "lectura": value}
            for key, value in graph_discussions.items()
            if str(value or "").strip()
        ]
        data["discusion_grafos"] = graph_discussions

    def _graph_section(value):
        text = str(value or "").strip().lower()
        if any(token in text for token in ["critico", "crítico", "punto", "fecha"]):
            return "puntos_criticos"
        if any(token in text for token in ["periodo", "período", "completo", "general"]):
            return "periodo_completo"
        return ""

    expected_graph_sections = {
        _graph_section(item.get("escenario") or item.get("nombre") or item.get("path"))
        for item in expected_graphs
    }
    expected_graph_sections.discard("")
    received_graph_sections = {
        _graph_section(item.get("seccion") or item.get("section") or item.get("apartado") or item.get("escenario") or item.get("nombre"))
        for item in graph_discussions
        if isinstance(item, dict)
        and str(item.get("lectura") or item.get("interpretacion") or item.get("discusion") or item.get("texto") or "").strip()
    } if isinstance(graph_discussions, list) else set()
    received_graph_sections.discard("")
    missing_graph_sections = sorted(expected_graph_sections - received_graph_sections)
    if missing_graph_sections:
        errors.append(f"Faltan discusiones de grafos por seccion: {missing_graph_sections}")

    text_blob = json.dumps(data, ensure_ascii=False).lower()
    forbidden = ["causó", "causo", "demuestra causalidad", "prueba causal"]
    for phrase in forbidden:
        if phrase in text_blob:
            errors.append(f"Lenguaje causal no permitido: {phrase}")
    return {"ok": not errors, "data": data, "errors": errors}


def _calcular_radar(
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
    mode_scores, df_atrib = _calcular_radar(
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
    title="Atribución por tipo de modelo",
):
    orden = [m for m in ["clasificacion"] if m in modelos]
    if not orden:
        raise ValueError("No hay modelos disponibles para graficar.")

    resultados = {}
    max_global = 0.0

    for modo_modelo in orden:
        model = modelos[modo_modelo]
        preds = model.predict(X)
        mode_scores, df_atrib = _calcular_radar(
            model,
            X,
            df,
            modos,
            predictions=preds,
            ponderar_por_clase=True,
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
        _dibujar_radar(
            ax,
            resultados[modo_modelo]["mode_scores"],
            max_global,
            "Clasificación",
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

    outputs = class_indices
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
    orden = [m for m in ["clasificacion"] if m in modelos]
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
        n_cols,
        figsize=figsize,
        subplot_kw=dict(polar=True),
    )
    axes = np.atleast_1d(axes)

    for col_idx in range(n_cols):
        ax = axes[col_idx]
        output_key = class_indices[col_idx]
        if output_key not in resultados["clasificacion"]:
            ax.set_visible(False)
            continue
        titulo_ax = f"Clasificación - Clase {output_key}"

        _dibujar_radar(
            ax,
            resultados["clasificacion"][output_key]["mode_scores"],
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

    return resultados, tablas, shap_values_por_modelo


def comparar_radar_kernel_shap_4_clases(clf, *args, **kwargs):
    return comparar_radar_kernel_shap_modelos({"clasificacion": clf}, *args, **kwargs)
