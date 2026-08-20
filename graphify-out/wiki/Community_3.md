# Community 3

> 33 nodes · cohesion 0.13

## Key Concepts

- [data_loader.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L1) (13 connections)
- [resolve_column()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L16) (12 connections)
- [attribution.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/attribution.py#L1) (9 connections)
- [_date_filter()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/attribution.py#L12) (6 connections)
- [top_events_for_day()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/attribution.py#L62) (6 connections)
- [load_dataset()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L35) (6 connections)
- [resolve_columns()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L20) (6 connections)
- [enrich_critical_points()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/attribution.py#L164) (5 connections)
- [summarize_weather_for_day()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/attribution.py#L124) (5 connections)
- [top_labels_for_day()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/attribution.py#L33) (5 connections)
- [filter_events()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L90) (5 connections)
- [numeric_series()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L74) (5 connections)
- [test_data_loader.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/tests/test_data_loader.py#L1) (5 connections)
- [column_lookup()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L12) (4 connections)
- [parse_fecha()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L67) (4 connections)
- [validate_required_columns()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L53) (4 connections)
- [_frame()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/tests/test_data_loader.py#L11) (4 connections)
- [summarize_variable_modes_for_day()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/attribution.py#L138) (3 connections)
- [available_circuits()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L115) (3 connections)
- [dataset_summary()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L122) (3 connections)
- [normalize_id_columns()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L57) (3 connections)
- [test_filter_events_by_circuit_and_dates()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/tests/test_data_loader.py#L45) (3 connections)
- [test_load_csv_preserves_ids_as_strings()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/tests/test_data_loader.py#L22) (3 connections)
- [test_load_parquet_if_available()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/tests/test_data_loader.py#L31) (3 connections)
- [_family_stats()](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/attribution.py#L108) (2 connections)
- *... and 8 more nodes in this community*

## Class Diagram

```mermaid
classDiagram
    class ColumnResolution {
        +schema.py()
    }
```

## Relationships

- No strong cross-community connections detected

## Source Files

- [/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/attribution.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/attribution.py)
- [/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py)
- [/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/schema.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/schema.py)
- [/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/tests/test_data_loader.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/tests/test_data_loader.py)

## Audit Trail

- EXTRACTED: 116 (82%)
- INFERRED: 26 (18%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*