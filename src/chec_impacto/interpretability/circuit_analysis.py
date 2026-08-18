"""Interpretabilidad de la era MGCECDL: modos, grafos, radares y prompts.

Aqui vivia la atribucion por Kernel SHAP -- `KernelShapTopVarsExtractor` y los
radares comparativos --, retirada del proyecto entero. La pregunta que se hace
hoy no es "que peso tuvo cada variable en lo que el modelo ya predijo" sino "que
muevo para que este vano baje de grupo", y esa la contestan
`relevancia_hacia_uiti_minimo` y `plan_hacia_clase_minima`
(`chec_local_interpreter/mil_simulador_015.py`) recorriendo el interior del rango
de cada palanca de INTERVENCION y componiendo escenarios.

`agregar_borda` se fue con ellos, pero por otro motivo: es pandas puro y el
predictor MIL la importaba desde aqui, de modo que cargar el modelo arrastraba
SHAP entero. Vive ahora en `interpretability/borda.py` y se reexporta abajo para
no romper a quien la pedia por este nombre.
"""

from __future__ import annotations

import html
import json
import matplotlib.patches as mpatches
import matplotlib.path as mpath
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pathlib import Path

from chec_impacto.interpretability.borda import agregar_borda


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


def normalizar_minmax(serie):
    vals = pd.to_numeric(serie, errors="coerce").astype(float)
    vals = vals.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    min_val = float(vals.min()) if len(vals) else 0.0
    max_val = float(vals.max()) if len(vals) else 0.0
    if not np.isfinite(min_val) or not np.isfinite(max_val) or max_val <= min_val:
        return vals * 0.0
    return (vals - min_val) / (max_val - min_val)


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

