-- View backing the dashboard's `circuit_map_lines_equipment_ds` dataset (geo maps).
-- Prerequisite: `workspace.default.indicadores_vano` (built by `uiti_vano_tables.py` from
-- data/Indicadores_vano_v3.csv with ALL raw columns, including X1/Y1/X2/Y2/FID_VANO/
-- FID_TRAFO/FID_SW geometry) — no separate table is needed. `indicadores_vano_v_3` was a
-- stale name from an earlier iteration; corrected 2026-07-24 after empirically confirming
-- indicadores_vano already has 100% non-null X1/Y1/FID_VANO/FID_SW and real lon/lat values.
CREATE OR REPLACE VIEW workspace.default.circuit_map_lines_equipment AS
SELECT circuito, geom_type, fid, lon1, lat1, lon2, lat2, fecha_dia, event_count, uiti_vano_sum FROM (
  SELECT CIRCUITO AS circuito, 'vano' AS geom_type, CAST(FID_VANO AS STRING) AS fid, X1 AS lon1, Y1 AS lat1, X2 AS lon2, Y2 AS lat2, DATE_TRUNC('DAY', FECHA) AS fecha_dia, COUNT(*) AS event_count, SUM(UITI_VANO) AS uiti_vano_sum
  FROM workspace.default.indicadores_vano
  WHERE X1 IS NOT NULL AND Y1 IS NOT NULL AND X2 IS NOT NULL AND Y2 IS NOT NULL
  GROUP BY CIRCUITO, FID_VANO, X1, Y1, X2, Y2, DATE_TRUNC('DAY', FECHA)

  UNION ALL

  SELECT CIRCUITO AS circuito, 'transformador' AS geom_type, CAST(FID_TRAFO AS STRING) AS fid, X2 AS lon1, Y2 AS lat1, CAST(NULL AS DOUBLE) AS lon2, CAST(NULL AS DOUBLE) AS lat2, DATE_TRUNC('DAY', FECHA) AS fecha_dia, CAST(NULL AS BIGINT) AS event_count, CAST(NULL AS DOUBLE) AS uiti_vano_sum
  FROM workspace.default.indicadores_vano
  WHERE FID_TRAFO IS NOT NULL AND X2 IS NOT NULL AND Y2 IS NOT NULL
  GROUP BY CIRCUITO, FID_TRAFO, X2, Y2, DATE_TRUNC('DAY', FECHA)

  UNION ALL

  SELECT CIRCUITO AS circuito, 'switch' AS geom_type, CAST(FID_SW AS STRING) AS fid, X1 AS lon1, Y1 AS lat1, CAST(NULL AS DOUBLE) AS lon2, CAST(NULL AS DOUBLE) AS lat2, DATE_TRUNC('DAY', FECHA) AS fecha_dia, CAST(NULL AS BIGINT) AS event_count, CAST(NULL AS DOUBLE) AS uiti_vano_sum
  FROM workspace.default.indicadores_vano
  WHERE FID_SW IS NOT NULL AND X1 IS NOT NULL AND Y1 IS NOT NULL
  GROUP BY CIRCUITO, FID_SW, X1, Y1, DATE_TRUNC('DAY', FECHA)
)
