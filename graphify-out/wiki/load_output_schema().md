# load_output_schema()

> God node · 9 connections · [/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/llm_contracts.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/llm_contracts.py#L24)

## Call Trace Diagram

```mermaid
sequenceDiagram
    participant P0 as load_output_schema()
    participant P1 as validate_llm_response()
    participant P2 as main()
    participant P3 as render_prompt()
    participant P4 as _load_json()
    participant P5 as _assert_prompt_contents()
    participant P6 as _valid_output()
    participant P7 as _guardrail_errors()
    participant P8 as _flatten_strings()
    participant P9 as _context_dates()
    participant P10 as _critical_point_ids()
    participant P11 as _unavailable_columns()
    participant P12 as test_valid_json_passes()
    participant P13 as test_date_outside_context_fails()
    participant P14 as test_unavailable_column_referenced_as_present_fails()
    participant P15 as test_malformed_json_fails()
    participant P16 as parse_llm_json()
    participant P17 as ValidationResult
    participant P18 as prompts_dir()
    participant P19 as test_prompt_rendering_includes_context_schema_and_version()
    P0->>+ P1: calls
    P1-->>- P0: return
    P1->>+ P0: calls
    P0-->>- P1: return
    P1->>+ P2: calls
    P2-->>- P1: return
    P2->>+ P1: calls
    P1-->>- P2: return
    P2->>+ P0: calls
    P0-->>- P2: return
    P2->>+ P3: calls
    P3-->>- P2: return
    P2->>+ P4: calls
    P4-->>- P2: return
    P2->>+ P5: calls
    P5-->>- P2: return
    P2->>+ P6: calls
    P6-->>- P2: return
    P1->>+ P7: calls
    P7-->>- P1: return
    P7->>+ P1: calls
    P1-->>- P7: return
    P7->>+ P8: calls
    P8-->>- P7: return
    P7->>+ P9: calls
    P9-->>- P7: return
    P7->>+ P10: calls
    P10-->>- P7: return
    P7->>+ P11: calls
    P11-->>- P7: return
    P1->>+ P12: calls
    P12-->>- P1: return
    P1->>+ P13: calls
    P13-->>- P1: return
    P1->>+ P14: calls
    P14-->>- P1: return
    P1->>+ P15: calls
    P15-->>- P1: return
    P1->>+ P16: calls
    P16-->>- P1: return
    P1->>+ P17: calls
    P17-->>- P1: return
    P0->>+ P2: calls
    P2-->>- P0: return
    P0->>+ P12: calls
    P12-->>- P0: return
    P0->>+ P13: calls
    P13-->>- P0: return
    P0->>+ P14: calls
    P14-->>- P0: return
    P0->>+ P18: calls
    P18-->>- P0: return
    P0->>+ P15: calls
    P15-->>- P0: return
    P0->>+ P19: calls
    P19-->>- P0: return
```

## Connections by Relation

### calls
- [[validate_llm_response()]] `INFERRED`
- [[main()]] `INFERRED`
- [[test_valid_json_passes()]] `INFERRED`
- [[test_date_outside_context_fails()]] `INFERRED`
- [[test_unavailable_column_referenced_as_present_fails()]] `INFERRED`
- [[prompts_dir()]] `EXTRACTED`
- [[test_malformed_json_fails()]] `INFERRED`
- [[test_prompt_rendering_includes_context_schema_and_version()]] `INFERRED`

### contains
- [[llm_contracts.py]] `EXTRACTED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*