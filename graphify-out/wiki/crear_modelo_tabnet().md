# crear_modelo_tabnet()

> God node · 11 connections · [/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_impacto/models/tabnet.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_impacto/models/tabnet.py#L216)

## Call Trace Diagram

```mermaid
sequenceDiagram
    participant P0 as crear_modelo_tabnet()
    participant P1 as resolver_config_entrenamiento_tabnet()
    participant P2 as cargar_o_entrenar_tabnet()
    participant P3 as cargar_modelo_tabnet()
    participant P4 as .predict()
    participant P5 as .predict_proba()
    participant P6 as make_kmse_loss()
    participant P7 as .save_model()
    participant P8 as CustomTabNetRegressor
    participant P9 as CustomTabNetClassifier
    participant P10 as configurar_entrenamiento_tabnet()
    participant P11 as cargar_modelos_disponibles()
    participant P12 as objective_regression()
    participant P13 as objective_classification()
    participant P14 as make_tabnet()
    participant P15 as build_optimizer()
    participant P16 as resolve_tabnet_device()
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
    P2->>+ P7: calls
    P7-->>- P2: return
    P1->>+ P3: calls
    P3-->>- P1: return
    P3->>+ P8: calls
    P8-->>- P3: return
    P3->>+ P1: calls
    P1-->>- P3: return
    P3->>+ P9: calls
    P9-->>- P3: return
    P3->>+ P2: calls
    P2-->>- P3: return
    P3->>+ P10: calls
    P10-->>- P3: return
    P3->>+ P11: calls
    P11-->>- P3: return
    P1->>+ P10: calls
    P10-->>- P1: return
    P1->>+ P12: calls
    P12-->>- P1: return
    P1->>+ P13: calls
    P13-->>- P1: return
    P1->>+ P7: calls
    P7-->>- P1: return
    P0->>+ P8: calls
    P8-->>- P0: return
    P0->>+ P9: calls
    P9-->>- P0: return
    P0->>+ P2: calls
    P2-->>- P0: return
    P0->>+ P10: calls
    P10-->>- P0: return
    P0->>+ P12: calls
    P12-->>- P0: return
    P0->>+ P13: calls
    P13-->>- P0: return
    P0->>+ P14: calls
    P14-->>- P0: return
    P0->>+ P15: calls
    P15-->>- P0: return
    P0->>+ P16: calls
    P16-->>- P0: return
```

## Connections by Relation

### calls
- [[resolver_config_entrenamiento_tabnet()]] `EXTRACTED`
- [[CustomTabNetRegressor]] `EXTRACTED`
- [[CustomTabNetClassifier]] `EXTRACTED`
- [[cargar_o_entrenar_tabnet()]] `INFERRED`
- [[configurar_entrenamiento_tabnet()]] `EXTRACTED`
- [[objective_regression()]] `INFERRED`
- [[objective_classification()]] `INFERRED`
- [[make_tabnet()]] `EXTRACTED`
- [[build_optimizer()]] `EXTRACTED`
- [[resolve_tabnet_device()]] `EXTRACTED`

### contains
- [[tabnet.py]] `EXTRACTED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*