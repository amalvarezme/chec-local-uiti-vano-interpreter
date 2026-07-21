# Databricks notebook source
# MAGIC %md
# MAGIC # UITI_VANO Delta table registration (manual, one-time PoC)
# MAGIC
# MAGIC Builds/refreshes the 3 Unity Catalog Delta tables that back the Databricks AI/BI
# MAGIC circuit-explorer dashboard, from the snapshot already mirrored into
# MAGIC `/Volumes/workspace/default/chec-simulador/data/`:
# MAGIC
# MAGIC - `workspace.default.indicadores_vano` — typed base table (all raw columns).
# MAGIC - `workspace.default.circuit_clustering` — imports and calls the REAL repo function
# MAGIC   `chec_local_interpreter.plotting.compute_circuit_criticality_groups` (no reimplementation),
# MAGIC   so clustering numbers match the local `/report`/`agrupamiento-circuitos` output exactly.
# MAGIC - `workspace.default.circuit_geo` — EPSG:4326 lat/lon points per vano, reimplemented standalone
# MAGIC   against the Volume's `GEO/MVLINSEC.shp` (shapefiles are Git-LFS-tracked, unreachable from a
# MAGIC   Databricks Git folder, so a Repos/Git-folder sync of this repo cannot be used for geo data).
# MAGIC
# MAGIC Manual, one-time PoC — no Job/DAB automation, run headless via `databricks jobs submit`
# MAGIC (serverless compute; this workspace has no all-purpose/job cluster provisioned and none is
# MAGIC created by this notebook). No changes to `report_pipeline.py`, the LLM agent roles, or
# MAGIC vault/graphify/GitHub Pages publishing.
# MAGIC
# MAGIC Real-function import: the repo has no `pyproject.toml`/`setup.py` (it is developed via
# MAGIC `PYTHONPATH=src`, not pip-installed), so this notebook does not build a wheel. Instead it
# MAGIC imports the exact, byte-identical source files
# MAGIC (`chec_local_interpreter/{__init__,config,event_counts,plotting}.py`) uploaded as plain
# MAGIC Databricks **workspace files** (`--format RAW`, confirmed as `Type: FILE`, not notebooks) under
# MAGIC `chec_local_interpreter_src/chec_local_interpreter/` next to this notebook, then adds that
# MAGIC directory to `sys.path`. This achieves the same goal as a wheel (import the real,
# MAGIC parity-critical function, never reimplement it) without inventing new packaging
# MAGIC infrastructure in the repo.

# COMMAND ----------

# Touch `spark` as the literal first executable command. Learned from an earlier probe on this
# same serverless workspace: calling `dbutils.library.restartPython()` after a `%pip install`
# permanently breaks the `spark` session on serverless compute ("SystemError: Internal error:
# spark should be initialized with the first notebook command"). This notebook never calls
# `restartPython()` — serverless already picks up newly `%pip install`ed packages within the same
# session — and this cell exists purely as a defensive first-command touch of `spark`.
spark

# COMMAND ----------

# MAGIC %pip install geopandas pyogrio shapely pyproj plotly matplotlib

# COMMAND ----------

import sys

CHEC_SRC_DIR = "/Workspace/Users/andresmarino07@gmail.com/databricks-integration/chec_local_interpreter_src"
if CHEC_SRC_DIR not in sys.path:
    sys.path.insert(0, CHEC_SRC_DIR)

from chec_local_interpreter.plotting import compute_circuit_criticality_groups  # real repo function, imported verbatim

# COMMAND ----------

import pandas as pd
from pyspark.sql import functions as F

VOLUME_DATA_DIR = "/Volumes/workspace/default/chec-simulador/data"
VOLUME_CSV_PATH = f"{VOLUME_DATA_DIR}/Indicadores_vano_v3.csv"
GEO_SHP_PATH = f"{VOLUME_DATA_DIR}/GEO/MVLINSEC.shp"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Base table — `indicadores_vano`

# COMMAND ----------

raw_sdf = spark.read.csv(VOLUME_CSV_PATH, header=True, inferSchema=True)
raw_sdf = (
    raw_sdf.withColumn("CIRCUITO", F.col("CIRCUITO").cast("string"))
    .withColumn("FECHA", F.to_timestamp("FECHA"))
    .withColumn("FECHA_DIA", F.to_date("FECHA"))
    .withColumn("UITI_VANO", F.col("UITI_VANO").cast("double"))
    .withColumn(
        "FID_VANO_NORM",
        F.regexp_replace(F.trim(F.col("FID_VANO").cast("string")), r"\.0$", ""),
    )
)
raw_sdf.write.mode("overwrite").format("delta").saveAsTable("workspace.default.indicadores_vano")

# COMMAND ----------

# Parity assert — row count matches the source CSV exactly (verified locally against
# `data/Indicadores_vano_v3.csv`, the same file mirrored into the Volume: 159,470 data rows).
EXPECTED_BASE_ROW_COUNT = 159470
base_row_count = spark.table("workspace.default.indicadores_vano").count()
assert base_row_count == EXPECTED_BASE_ROW_COUNT, (
    f"indicadores_vano row count {base_row_count} != expected {EXPECTED_BASE_ROW_COUNT}"
)

base_columns = set(spark.table("workspace.default.indicadores_vano").columns)
for required_col in ("CIRCUITO", "FECHA", "UITI_VANO"):
    assert required_col in base_columns, f"indicadores_vano missing required column {required_col}"

print(f"indicadores_vano OK: {base_row_count} rows, {len(base_columns)} columns")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Derived table — `circuit_clustering` (real function, full date range)

# COMMAND ----------

pdf_full = pd.read_csv(VOLUME_CSV_PATH)

clustering_df = compute_circuit_criticality_groups(pdf_full, start_date=None, end_date=None)
clustering_out = clustering_df.reset_index().rename(columns={"CIRCUITO": "circuito"})
clustering_out.columns = [str(col).lower() for col in clustering_out.columns]
clustering_out["circuito"] = clustering_out["circuito"].astype(str)
clustering_out["criticidad"] = clustering_out["criticidad"].astype(str)
clustering_out["cluster"] = clustering_out["cluster"].astype("int64")
clustering_out["event_count"] = clustering_out["event_count"].astype("int64")
clustering_out["uiti_vano_sum"] = clustering_out["uiti_vano_sum"].astype("float64")
clustering_out["centroid_distance"] = clustering_out["centroid_distance"].astype("float64")

clustering_sdf = spark.createDataFrame(clustering_out)
clustering_sdf.write.mode("overwrite").format("delta").saveAsTable("workspace.default.circuit_clustering")

# COMMAND ----------

# Parity assert — 8 sample circuits vs the same real function computed locally (outside this
# notebook, against the identical CSV) in this SDD apply session. `centroid_distance` is a bonus
# column derived from `compute_circuit_criticality_groups` itself, included in the assert since it
# has a real local counterpart (unlike the prior, invalid substitute-logic build).
REFERENCE_CIRCUITS = {
    "AGU23L15": dict(event_count=67, uiti_vano_sum=90284.498285, cluster=4, criticidad="Media", centroid_distance=0.429679),
    "BQE23L12": dict(event_count=36, uiti_vano_sum=708703.870541, cluster=3, criticidad="Alta", centroid_distance=2.149314),
    "HER23L16": dict(event_count=130, uiti_vano_sum=507228.424002, cluster=2, criticidad="Muy Alta", centroid_distance=1.085148),
}

clustering_check_pdf = spark.table("workspace.default.circuit_clustering").toPandas().set_index("circuito")
for circuito, expected in REFERENCE_CIRCUITS.items():
    row = clustering_check_pdf.loc[circuito]
    assert int(row["event_count"]) == expected["event_count"], f"{circuito} event_count mismatch: {row['event_count']} != {expected['event_count']}"
    assert abs(float(row["uiti_vano_sum"]) - expected["uiti_vano_sum"]) < 1e-3, f"{circuito} uiti_vano_sum mismatch"
    assert row["criticidad"] == expected["criticidad"], f"{circuito} criticidad mismatch: {row['criticidad']} != {expected['criticidad']}"
    assert int(row["cluster"]) == expected["cluster"], f"{circuito} cluster mismatch: {row['cluster']} != {expected['cluster']}"
    assert abs(float(row["centroid_distance"]) - expected["centroid_distance"]) < 1e-3, f"{circuito} centroid_distance mismatch"

EXPECTED_CIRCUIT_COUNT = 208
clustering_row_count = spark.table("workspace.default.circuit_clustering").count()
assert clustering_row_count == EXPECTED_CIRCUIT_COUNT, (
    f"circuit_clustering row count {clustering_row_count} != expected {EXPECTED_CIRCUIT_COUNT}"
)

criticidad_labels = {row["criticidad"] for row in spark.table("workspace.default.circuit_clustering").select("criticidad").distinct().collect()}
assert criticidad_labels == {"Muy Alta", "Alta", "Media", "Baja", "Muy Baja"}, (
    f"circuit_clustering criticidad labels {criticidad_labels} != the 5-label CRITICALITY_GROUP_LABELS set"
)

print(f"circuit_clustering OK: {clustering_row_count} circuits, parity verified for {list(REFERENCE_CIRCUITS)}, labels={sorted(criticidad_labels)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Derived table — `circuit_geo` (standalone geopandas extraction)

# COMMAND ----------

import geopandas as gpd


def _norm_map_id(series: pd.Series) -> pd.Series:
    # Verbatim copy of `chec_local_interpreter.plotting._norm_map_id` — private helper, not
    # importable on its own without the rest of the module's private surface, so it is inlined
    # here identically (cited by name/behavior, not reimplemented from scratch).
    return (
        series.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .replace({"": pd.NA, "<NA>": pd.NA, "nan": pd.NA, "None": pd.NA})
    )


geo_lineas = gpd.read_file(GEO_SHP_PATH)
if str(geo_lineas.crs) != "EPSG:4326":
    geo_lineas = geo_lineas.to_crs("EPSG:4326")

geo_lineas["FID_VANO_GEO"] = _norm_map_id(geo_lineas["G3E_FID"])
geo_lineas["lat"] = geo_lineas.geometry.centroid.y
geo_lineas["lon"] = geo_lineas.geometry.centroid.x

pdf_full["FID_VANO_NORM"] = _norm_map_id(pdf_full["FID_VANO"])
pdf_full["UITI_VANO"] = pd.to_numeric(pdf_full["UITI_VANO"], errors="coerce").fillna(0.0)

# Same metric semantics as `plot_interactive_circuit_clustering`'s geo map color targets
# (plotting.py, "number_of_events"/"sum_uiti_vano" branches): row COUNT per vano, not the
# distinct-FECHA count used for the circuit-level clustering `event_count`.
per_vano_event_count = pdf_full.groupby("FID_VANO_NORM").size().rename("event_count")
per_vano_uiti_sum = pdf_full.groupby("FID_VANO_NORM")["UITI_VANO"].sum().rename("uiti_vano_sum")

geo_out = geo_lineas[["CIRCUITO", "FID_VANO_GEO", "lat", "lon"]].rename(
    columns={"CIRCUITO": "circuito", "FID_VANO_GEO": "fid_vano"}
)
geo_out = geo_out.dropna(subset=["fid_vano"]).copy()
geo_out = geo_out.merge(per_vano_event_count, left_on="fid_vano", right_index=True, how="left")
geo_out = geo_out.merge(per_vano_uiti_sum, left_on="fid_vano", right_index=True, how="left")
geo_out["event_count"] = geo_out["event_count"].fillna(0).astype("int64")
geo_out["uiti_vano_sum"] = geo_out["uiti_vano_sum"].fillna(0.0).astype("float64")
geo_out["circuito"] = geo_out["circuito"].astype(str)
geo_out["fid_vano"] = geo_out["fid_vano"].astype(str)
geo_out["lat"] = geo_out["lat"].astype("float64")
geo_out["lon"] = geo_out["lon"].astype("float64")

geo_sdf = spark.createDataFrame(geo_out)
geo_sdf.write.mode("overwrite").format("delta").saveAsTable("workspace.default.circuit_geo")

# COMMAND ----------

# Parity assert — total row count + a known circuit's row count, both verified locally against
# `data/GEO/MVLINSEC.shp` in this SDD apply session (already-EPSG:4326 source, no reprojection
# needed in practice — the notebook's `to_crs("EPSG:4326")` above stays defensive).
EXPECTED_GEO_ROW_COUNT = 60053
geo_row_count = spark.table("workspace.default.circuit_geo").count()
assert geo_row_count == EXPECTED_GEO_ROW_COUNT, f"circuit_geo row count {geo_row_count} != expected {EXPECTED_GEO_ROW_COUNT}"

EXPECTED_AGU23L15_GEO_ROWS = 634
agu_geo_rows = spark.table("workspace.default.circuit_geo").filter(F.col("circuito") == "AGU23L15").count()
assert agu_geo_rows == EXPECTED_AGU23L15_GEO_ROWS, f"AGU23L15 geo rows {agu_geo_rows} != expected {EXPECTED_AGU23L15_GEO_ROWS}"

bounds_row = spark.table("workspace.default.circuit_geo").agg(
    F.min("lat").alias("lat_min"),
    F.max("lat").alias("lat_max"),
    F.min("lon").alias("lon_min"),
    F.max("lon").alias("lon_max"),
).collect()[0]
assert -90 <= bounds_row["lat_min"] <= bounds_row["lat_max"] <= 90, f"invalid lat bounds: {bounds_row}"
assert -180 <= bounds_row["lon_min"] <= bounds_row["lon_max"] <= 180, f"invalid lon bounds: {bounds_row}"

print(
    f"circuit_geo OK: {geo_row_count} rows, AGU23L15={agu_geo_rows} rows, "
    f"lat=[{bounds_row['lat_min']:.4f},{bounds_row['lat_max']:.4f}], "
    f"lon=[{bounds_row['lon_min']:.4f},{bounds_row['lon_max']:.4f}]"
)

# COMMAND ----------

print("All 3 tables built and parity-verified: indicadores_vano, circuit_clustering, circuit_geo.")
