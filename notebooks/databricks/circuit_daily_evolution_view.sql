-- View backing the dashboard's `daily_line_ds` dataset (daily evolution combo chart).
-- Prerequisite: `workspace.default.indicadores_vano` (built by `uiti_vano_tables.py`).
CREATE OR REPLACE VIEW workspace.default.circuit_daily_evolution AS
WITH bounds AS (
  SELECT MIN(FECHA_DIA) AS min_d, MAX(FECHA_DIA) AS max_d FROM workspace.default.indicadores_vano
),
date_spine AS (
  SELECT explode(sequence(min_d, max_d, INTERVAL 1 DAY)) AS fecha_dia FROM bounds
),
circuitos AS (
  SELECT DISTINCT CIRCUITO AS circuito FROM workspace.default.indicadores_vano
),
daily_agg AS (
  SELECT CIRCUITO AS circuito, FECHA_DIA AS fecha_dia, COUNT(*) AS event_count, SUM(UITI_VANO) AS uiti_vano_sum
  FROM workspace.default.indicadores_vano
  GROUP BY CIRCUITO, FECHA_DIA
)
SELECT
  c.circuito,
  d.fecha_dia,
  COALESCE(a.event_count, 0) AS event_count,
  COALESCE(a.uiti_vano_sum, 0.0) AS uiti_vano_sum
FROM circuitos c
CROSS JOIN date_spine d
LEFT JOIN daily_agg a ON a.circuito = c.circuito AND a.fecha_dia = d.fecha_dia
