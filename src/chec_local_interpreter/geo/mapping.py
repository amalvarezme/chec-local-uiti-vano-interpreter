"""Geospatial mapping helpers for CHEC notebooks."""

from __future__ import annotations

import pandas as pd

try:
    import folium
    import geopandas as gpd
except ImportError:  # pragma: no cover - optional notebook dependencies
    folium = None
    gpd = None


def profile_layer(name: str, gdf) -> dict:
    """Return a compact quality/profile summary for a GeoDataFrame layer."""
    non_geom = gdf.drop(columns=gdf.geometry.name)
    return {
        "layer": name,
        "rows": int(len(gdf)),
        "columns": int(len(gdf.columns)),
        "crs": str(gdf.crs),
        "geometry_types": gdf.geometry.geom_type.value_counts(dropna=False).to_dict(),
        "empty_geometries": int(gdf.geometry.is_empty.sum()),
        "null_geometries": int(gdf.geometry.isna().sum()),
        "bounds": [round(float(x), 6) for x in gdf.total_bounds],
        "top_null_columns": non_geom.isna().mean().sort_values(ascending=False).head(12).round(3).to_dict(),
    }


def norm_id(series: pd.Series) -> pd.Series:
    """Normalize identifier-like columns loaded from CSV/Excel/geospatial files."""
    return (
        series.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .replace({"": pd.NA, "<NA>": pd.NA, "nan": pd.NA, "None": pd.NA})
    )


def style_line(feature):
    """Style a line feature using accumulated UITI evidence when available."""
    value = feature["properties"].get("uiti_vano_total") or 0
    if value > 0:
        color = "#dc2626"
        weight = 4
    else:
        color = "#2563eb"
        weight = 2
    return {"color": color, "weight": weight, "opacity": 0.75}


def available_columns(gdf, columns: list[str]) -> list[str]:
    """Return the requested columns that are present in the frame."""
    return [col for col in columns if col in gdf.columns]


def safe_text(value) -> str:
    """Format nullable values for popup text."""
    if pd.isna(value):
        return ""
    return str(value)


def popup_html(row, fields: list[tuple[str, str]], title: str) -> str:
    """Build a compact HTML table for a map popup."""
    items = []
    for col, label in fields:
        value = row.get(col, "")
        text = safe_text(value)
        if text:
            items.append(f"<tr><th style='text-align:left;padding-right:8px'>{label}</th><td>{text}</td></tr>")
    return f"<strong>{title}</strong><table>{''.join(items)}</table>"


def add_point_layer(
    fmap,
    gdf,
    *,
    name: str,
    color: str,
    radius: int,
    popup_fields: list[tuple[str, str]],
) -> None:
    """Add a point GeoDataFrame as a Folium feature group."""
    if folium is None:
        raise ImportError("folium is required to add point layers.")
    if gdf.empty:
        return
    points = gdf.to_crs("EPSG:4326") if str(gdf.crs) != "EPSG:4326" else gdf
    group = folium.FeatureGroup(name=name, show=True)
    for _, row in points.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        folium.CircleMarker(
            location=[geom.y, geom.x],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            weight=1,
            tooltip=f"{name}: {safe_text(row.get('CODIGO', row.get('G3E_FID', '')))}",
            popup=folium.Popup(popup_html(row, popup_fields, name), max_width=420),
        ).add_to(group)
    group.add_to(fmap)


def make_circuit_map(
    circuito: str,
    *,
    lineas_eventos,
    trafos,
    switches,
    max_features: int | None = None,
):
    """Create a Folium map for one circuit using line, transformer, and switch layers."""
    if folium is None or gpd is None:
        raise ImportError("folium and geopandas are required to create circuit maps.")
    g_lines = lineas_eventos[lineas_eventos["CIRCUITO"].astype(str).eq(str(circuito))].copy()
    g_trafos = trafos[trafos["CIRCUITO"].astype(str).eq(str(circuito))].copy()
    g_switches = switches[switches["CIRCUITO"].astype(str).eq(str(circuito))].copy()
    if max_features is not None:
        g_lines = g_lines.head(max_features)
        g_trafos = g_trafos.head(max_features)
        g_switches = g_switches.head(max_features)
    if g_lines.empty and g_trafos.empty and g_switches.empty:
        raise ValueError(f"No hay geometria para circuito {circuito}")

    bounds_source = pd.concat(
        [
            gdf[["geometry"]].to_crs("EPSG:4326") if str(gdf.crs) != "EPSG:4326" else gdf[["geometry"]]
            for gdf in [g_lines, g_trafos, g_switches]
            if not gdf.empty
        ],
        ignore_index=True,
    )
    bounds = gpd.GeoDataFrame(bounds_source, geometry="geometry", crs="EPSG:4326").total_bounds
    center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]
    fmap = folium.Map(location=center, zoom_start=12, tiles="CartoDB positron")

    if not g_lines.empty:
        folium.GeoJson(
            g_lines[
                available_columns(
                    g_lines,
                    ["FID_VANO_GEO", "CODIGO", "CIRCUITO", "n_eventos", "uiti_vano_total", "geometry"],
                )
            ],
            name="Vanos / tramos MV",
            style_function=style_line,
            tooltip=folium.GeoJsonTooltip(
                fields=available_columns(g_lines, ["FID_VANO_GEO", "CODIGO", "CIRCUITO", "n_eventos", "uiti_vano_total"])
            ),
        ).add_to(fmap)

    add_point_layer(
        fmap,
        g_trafos,
        name="Transformadores",
        color="#f59e0b",
        radius=5,
        popup_fields=[
            ("FID_TRAFO_GEO", "FID trafo"),
            ("CODIGO", "Código"),
            ("CIRCUITO", "Circuito"),
            ("CAPACIDAD_", "Capacidad"),
            ("FASES", "Fases"),
            ("MUNICIPIO", "Municipio"),
            ("DIRECCION", "Dirección"),
            ("ENERGIZADO", "Energizado"),
            ("EST_OPERAT", "Estado operativo"),
        ],
    )
    add_point_layer(
        fmap,
        g_switches,
        name="Interruptores / switches",
        color="#7c3aed",
        radius=4,
        popup_fields=[
            ("FID_SWITCH_GEO", "FID switch"),
            ("CODIGO", "Código"),
            ("TIPO", "Tipo"),
            ("ELEMENTO", "Elemento"),
            ("CIRCUITO", "Circuito"),
            ("CAPACIDAD_", "Capacidad"),
            ("FASES", "Fases"),
            ("MUNICIPIO", "Municipio"),
            ("DIRECCION", "Dirección"),
            ("ENERGIZADO", "Energizado"),
            ("EST_OPERAT", "Estado operativo"),
        ],
    )

    folium.LayerControl(collapsed=False).add_to(fmap)
    fmap.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    return fmap
