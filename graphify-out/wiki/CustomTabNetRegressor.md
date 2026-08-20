# CustomTabNetRegressor

> God node · 9 connections · [/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_impacto/models/tabnet.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_impacto/models/tabnet.py#L128)

## Call Trace Diagram

```mermaid
sequenceDiagram
    participant P0 as CustomTabNetRegressor
    participant P1 as crear_modelo_tabnet()
    participant P2 as resolver_config_entrenamiento_tabnet()
    participant P3 as cargar_o_entrenar_tabnet()
    participant P4 as cargar_modelo_tabnet()
    participant P5 as configurar_entrenamiento_tabnet()
    participant P6 as objective_regression()
    participant P7 as objective_classification()
    participant P8 as .save_model()
    participant P9 as CustomTabNetClassifier
    participant P10 as .predict()
    participant P11 as .predict_proba()
    participant P12 as make_kmse_loss()
    participant P13 as make_tabnet()
    participant P14 as build_optimizer()
    participant P15 as resolve_tabnet_device()
    P0->>+ P1: calls
    P1-->>- P0: return
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
    P2->>+ P8: calls
    P8-->>- P2: return
    P1->>+ P0: calls
    P0-->>- P1: return
    P1->>+ P9: calls
    P9-->>- P1: return
    P9->>+ P1: calls
    P1-->>- P9: return
    P9->>+ P4: calls
    P4-->>- P9: return
    P1->>+ P3: calls
    P3-->>- P1: return
    P3->>+ P1: calls
    P1-->>- P3: return
    P3->>+ P2: calls
    P2-->>- P3: return
    P3->>+ P4: calls
    P4-->>- P3: return
    P3->>+ P10: calls
    P10-->>- P3: return
    P3->>+ P11: calls
    P11-->>- P3: return
    P3->>+ P12: calls
    P12-->>- P3: return
    P3->>+ P8: calls
    P8-->>- P3: return
    P1->>+ P5: calls
    P5-->>- P1: return
    P1->>+ P6: calls
    P6-->>- P1: return
    P1->>+ P7: calls
    P7-->>- P1: return
    P1->>+ P13: calls
    P13-->>- P1: return
    P1->>+ P14: calls
    P14-->>- P1: return
    P1->>+ P15: calls
    P15-->>- P1: return
    P0->>+ P4: calls
    P4-->>- P0: return
```

## Connections by Relation

### calls
- [[crear_modelo_tabnet()]] `EXTRACTED`
- [[cargar_modelo_tabnet()]] `EXTRACTED`

### contains
- [[tabnet.py]] `EXTRACTED`

### inherits
- [[_PortableBatchNormPredictionMixin]] `EXTRACTED`
- [[TabNetRegressor]] `EXTRACTED`

### method
- [[.predict()]] `EXTRACTED`
- [[.compute_loss()]] `EXTRACTED`
- [[._predict_batch()]] `EXTRACTED`

### rationale_for
- [[TabNetRegressor con salida no negativa e inferencia portable.]] `EXTRACTED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*