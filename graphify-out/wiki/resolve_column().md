# resolve_column()

> God node · 12 connections · [/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/data_loader.py#L16)

## Call Trace Diagram

```mermaid
sequenceDiagram
    participant P0 as resolve_column()
    participant P1 as _date_filter()
    participant P2 as top_events_for_day()
    participant P3 as enrich_critical_points()
    participant P4 as numeric_series()
    participant P5 as _json_value()
    participant P6 as top_labels_for_day()
    participant P7 as summarize_weather_for_day()
    participant P8 as _weather_columns()
    participant P9 as _family_stats()
    participant P10 as summarize_variable_modes_for_day()
    participant P11 as build_daily_series()
    participant P12 as filter_events()
    participant P13 as column_lookup()
    participant P14 as parse_fecha()
    participant P15 as available_circuits()
    participant P16 as text_series()
    P0->>+ P1: calls
    P1-->>- P0: return
    P1->>+ P0: calls
    P0-->>- P1: return
    P1->>+ P2: calls
    P2-->>- P1: return
    P2->>+ P0: calls
    P0-->>- P2: return
    P2->>+ P1: calls
    P1-->>- P2: return
    P2->>+ P3: calls
    P3-->>- P2: return
    P2->>+ P4: calls
    P4-->>- P2: return
    P2->>+ P5: calls
    P5-->>- P2: return
    P1->>+ P6: calls
    P6-->>- P1: return
    P6->>+ P0: calls
    P0-->>- P6: return
    P6->>+ P1: calls
    P1-->>- P6: return
    P6->>+ P3: calls
    P3-->>- P6: return
    P6->>+ P4: calls
    P4-->>- P6: return
    P1->>+ P7: calls
    P7-->>- P1: return
    P7->>+ P1: calls
    P1-->>- P7: return
    P7->>+ P3: calls
    P3-->>- P7: return
    P7->>+ P8: calls
    P8-->>- P7: return
    P7->>+ P9: calls
    P9-->>- P7: return
    P1->>+ P10: calls
    P10-->>- P1: return
    P0->>+ P2: calls
    P2-->>- P0: return
    P0->>+ P11: calls
    P11-->>- P0: return
    P0->>+ P4: calls
    P4-->>- P0: return
    P0->>+ P12: calls
    P12-->>- P0: return
    P0->>+ P6: calls
    P6-->>- P0: return
    P0->>+ P13: calls
    P13-->>- P0: return
    P0->>+ P14: calls
    P14-->>- P0: return
    P0->>+ P15: calls
    P15-->>- P0: return
    P0->>+ P10: calls
    P10-->>- P0: return
    P0->>+ P16: calls
    P16-->>- P0: return
```

## Connections by Relation

### calls
- [[_date_filter()]] `INFERRED`
- [[top_events_for_day()]] `INFERRED`
- [[build_daily_series()]] `INFERRED`
- [[numeric_series()]] `EXTRACTED`
- [[filter_events()]] `EXTRACTED`
- [[top_labels_for_day()]] `INFERRED`
- [[column_lookup()]] `EXTRACTED`
- [[parse_fecha()]] `EXTRACTED`
- [[available_circuits()]] `EXTRACTED`
- [[summarize_variable_modes_for_day()]] `INFERRED`
- [[text_series()]] `EXTRACTED`

### contains
- [[data_loader.py]] `EXTRACTED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*