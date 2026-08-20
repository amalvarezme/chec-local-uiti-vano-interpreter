# validate_llm_response()

> God node · 10 connections · [/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/llm_validation.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_local_interpreter/llm_validation.py#L139)

## Call Trace Diagram

```mermaid
sequenceDiagram
    participant P0 as validate_llm_response()
    participant P1 as load_output_schema()
    participant P2 as main()
    participant P3 as render_prompt()
    participant P4 as _load_json()
    participant P5 as _assert_prompt_contents()
    participant P6 as _valid_output()
    participant P7 as test_valid_json_passes()
    participant P8 as _context()
    participant P9 as _valid_output()
    participant P10 as test_date_outside_context_fails()
    participant P11 as test_unavailable_column_referenced_as_present_fails()
    participant P12 as prompts_dir()
    participant P13 as test_malformed_json_fails()
    participant P14 as test_prompt_rendering_includes_context_schema_and_version()
    participant P15 as _guardrail_errors()
    participant P16 as parse_llm_json()
    participant P17 as ValidationResult
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
    P2->>+ P6: calls
    P6-->>- P2: return
    P1->>+ P7: calls
    P7-->>- P1: return
    P7->>+ P0: calls
    P0-->>- P7: return
    P7->>+ P1: calls
    P1-->>- P7: return
    P7->>+ P8: calls
    P8-->>- P7: return
    P7->>+ P9: calls
    P9-->>- P7: return
    P1->>+ P10: calls
    P10-->>- P1: return
    P1->>+ P11: calls
    P11-->>- P1: return
    P1->>+ P12: calls
    P12-->>- P1: return
    P1->>+ P13: calls
    P13-->>- P1: return
    P1->>+ P14: calls
    P14-->>- P1: return
    P0->>+ P2: calls
    P2-->>- P0: return
    P0->>+ P15: calls
    P15-->>- P0: return
    P0->>+ P7: calls
    P7-->>- P0: return
    P0->>+ P10: calls
    P10-->>- P0: return
    P0->>+ P11: calls
    P11-->>- P0: return
    P0->>+ P13: calls
    P13-->>- P0: return
    P0->>+ P16: calls
    P16-->>- P0: return
    P0->>+ P17: calls
    P17-->>- P0: return
```

## Connections by Relation

### calls
- [[load_output_schema()]] `INFERRED`
- [[main()]] `INFERRED`
- [[_guardrail_errors()]] `EXTRACTED`
- [[test_valid_json_passes()]] `INFERRED`
- [[test_date_outside_context_fails()]] `INFERRED`
- [[test_unavailable_column_referenced_as_present_fails()]] `INFERRED`
- [[test_malformed_json_fails()]] `INFERRED`
- [[parse_llm_json()]] `EXTRACTED`
- [[ValidationResult]] `EXTRACTED`

### contains
- [[llm_validation.py]] `EXTRACTED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*