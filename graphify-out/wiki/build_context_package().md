# build_context_package()

> God node · 10 connections · [/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/context_builder.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/context_builder.py#L74)

## Call Trace Diagram

```mermaid
sequenceDiagram
    participant P0 as build_context_package()
    participant P1 as test_context_package_includes_core_sections_and_missing_optional_columns()
    participant P2 as detect_point_reasons()
    participant P3 as test_high_spike_day_is_detected()
    participant P4 as test_sharp_increase_day_is_detected()
    participant P5 as CriticalityThresholds
    participant P6 as _date_text()
    participant P7 as _reason()
    participant P8 as build_daily_series()
    participant P9 as resolve_column()
    participant P10 as numeric_series()
    participant P11 as test_missing_optional_columns_do_not_crash_context_generation()
    participant P12 as test_build_daily_series_fills_missing_dates_without_quality_error()
    participant P13 as compute_daily_features()
    participant P14 as rank_critical_points()
    participant P15 as enrich_critical_points()
    participant P16 as resolve_columns()
    participant P17 as daily_series_records()
    participant P18 as _date_text()
    participant P19 as window_summary()
    participant P20 as _compute_circuit_characterization()
    participant P21 as build_graphify_context()
    participant P22 as domain_context_payload()
    P0->>+ P1: calls
    P1-->>- P0: return
    P1->>+ P0: calls
    P0-->>- P1: return
    P1->>+ P2: calls
    P2-->>- P1: return
    P2->>+ P1: calls
    P1-->>- P2: return
    P2->>+ P3: calls
    P3-->>- P2: return
    P2->>+ P4: calls
    P4-->>- P2: return
    P2->>+ P5: calls
    P5-->>- P2: return
    P2->>+ P6: calls
    P6-->>- P2: return
    P2->>+ P7: calls
    P7-->>- P2: return
    P1->>+ P8: calls
    P8-->>- P1: return
    P8->>+ P9: calls
    P9-->>- P8: return
    P8->>+ P1: calls
    P1-->>- P8: return
    P8->>+ P10: calls
    P10-->>- P8: return
    P8->>+ P11: calls
    P11-->>- P8: return
    P8->>+ P12: calls
    P12-->>- P8: return
    P1->>+ P13: calls
    P13-->>- P1: return
    P1->>+ P14: calls
    P14-->>- P1: return
    P1->>+ P15: calls
    P15-->>- P1: return
    P0->>+ P16: calls
    P16-->>- P0: return
    P0->>+ P17: calls
    P17-->>- P0: return
    P0->>+ P18: calls
    P18-->>- P0: return
    P0->>+ P19: calls
    P19-->>- P0: return
    P0->>+ P20: calls
    P20-->>- P0: return
    P0->>+ P11: calls
    P11-->>- P0: return
    P0->>+ P21: calls
    P21-->>- P0: return
    P0->>+ P22: calls
    P22-->>- P0: return
```

## Connections by Relation

### calls
- [[test_context_package_includes_core_sections_and_missing_optional_columns()]] `INFERRED`
- [[resolve_columns()]] `INFERRED`
- [[daily_series_records()]] `EXTRACTED`
- [[_date_text()]] `EXTRACTED`
- [[window_summary()]] `EXTRACTED`
- [[_compute_circuit_characterization()]] `EXTRACTED`
- [[test_missing_optional_columns_do_not_crash_context_generation()]] `INFERRED`
- [[build_graphify_context()]] `INFERRED`
- [[domain_context_payload()]] `INFERRED`

### contains
- [[context_builder.py]] `EXTRACTED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*