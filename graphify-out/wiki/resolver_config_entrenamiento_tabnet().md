# resolver_config_entrenamiento_tabnet()

> God node · 9 connections · [/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_impacto/models/tabnet.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_impacto/models/tabnet.py#L18)

## Call Trace Diagram

```mermaid
sequenceDiagram
    participant P0 as resolver_config_entrenamiento_tabnet()
    participant P1 as crear_modelo_tabnet()
    participant P2 as CustomTabNetRegressor
    participant P3 as cargar_modelo_tabnet()
    participant P4 as CustomTabNetClassifier
    participant P5 as cargar_o_entrenar_tabnet()
    participant P6 as .predict()
    participant P7 as .predict_proba()
    participant P8 as make_kmse_loss()
    participant P9 as .save_model()
    participant P10 as configurar_entrenamiento_tabnet()
    participant P11 as objective_regression()
    participant P12 as objective_classification()
    participant P13 as make_tabnet()
    participant P14 as build_optimizer()
    participant P15 as resolve_tabnet_device()
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
    P1->>+ P4: calls
    P4-->>- P1: return
    P4->>+ P1: calls
    P1-->>- P4: return
    P4->>+ P3: calls
    P3-->>- P4: return
    P1->>+ P5: calls
    P5-->>- P1: return
    P5->>+ P1: calls
    P1-->>- P5: return
    P5->>+ P0: calls
    P0-->>- P5: return
    P5->>+ P3: calls
    P3-->>- P5: return
    P5->>+ P6: calls
    P6-->>- P5: return
    P5->>+ P7: calls
    P7-->>- P5: return
    P5->>+ P8: calls
    P8-->>- P5: return
    P5->>+ P9: calls
    P9-->>- P5: return
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
    P1->>+ P15: calls
    P15-->>- P1: return
    P0->>+ P5: calls
    P5-->>- P0: return
    P0->>+ P3: calls
    P3-->>- P0: return
    P0->>+ P10: calls
    P10-->>- P0: return
    P0->>+ P11: calls
    P11-->>- P0: return
    P0->>+ P12: calls
    P12-->>- P0: return
    P0->>+ P9: calls
    P9-->>- P0: return
```

## Connections by Relation

### calls
- [[crear_modelo_tabnet()]] `EXTRACTED`
- [[cargar_o_entrenar_tabnet()]] `INFERRED`
- [[cargar_modelo_tabnet()]] `EXTRACTED`
- [[configurar_entrenamiento_tabnet()]] `EXTRACTED`
- [[objective_regression()]] `INFERRED`
- [[objective_classification()]] `INFERRED`
- [[.save_model()]] `EXTRACTED`

### contains
- [[tabnet.py]] `EXTRACTED`

### rationale_for
- [[Derive fit-only settings that pytorch-tabnet does not serialize.]] `EXTRACTED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*