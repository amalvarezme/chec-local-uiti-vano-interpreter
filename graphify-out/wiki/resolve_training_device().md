# resolve_training_device()

> God node · 10 connections · [/Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_impacto/training/mgcecdl.py](file:///Users/andresalvarez/Documents/chec-local-uiti-vano-interpreter/src/chec_impacto/training/mgcecdl.py#L154)

## Call Trace Diagram

```mermaid
sequenceDiagram
    participant P0 as resolve_training_device()
    participant P1 as _coerce_device()
    participant P2 as evaluate_model()
    participant P3 as .compute_components()
    participant P4 as train_mgcecdl_model()
    participant P5 as _initialize_running_metrics()
    participant P6 as _unpack_batch()
    participant P7 as compute_regression_metrics()
    participant P8 as evaluate_classification_model()
    participant P9 as train_mgcecdl_classifier()
    participant P10 as compute_classification_metrics()
    participant P11 as train_one_epoch()
    participant P12 as _train_classification_one_epoch()
    participant P13 as cargar_modelo_mgcecdl()
    participant P14 as crear_objective_regresion_mgcecdl()
    participant P15 as crear_objective_clasificacion_mgcecdl()
    participant P16 as predict_regression()
    participant P17 as predict_classification()
    participant P18 as _probe_cuda_device()
    P0->>+ P1: calls
    P1-->>- P0: return
    P1->>+ P0: calls
    P0-->>- P1: return
    P1->>+ P2: calls
    P2-->>- P1: return
    P2->>+ P3: calls
    P3-->>- P2: return
    P2->>+ P1: calls
    P1-->>- P2: return
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
    P8->>+ P3: calls
    P3-->>- P8: return
    P8->>+ P1: calls
    P1-->>- P8: return
    P8->>+ P9: calls
    P9-->>- P8: return
    P8->>+ P5: calls
    P5-->>- P8: return
    P8->>+ P6: calls
    P6-->>- P8: return
    P8->>+ P10: calls
    P10-->>- P8: return
    P1->>+ P11: calls
    P11-->>- P1: return
    P1->>+ P12: calls
    P12-->>- P1: return
    P1->>+ P13: calls
    P13-->>- P1: return
    P0->>+ P4: calls
    P4-->>- P0: return
    P0->>+ P9: calls
    P9-->>- P0: return
    P0->>+ P14: calls
    P14-->>- P0: return
    P0->>+ P15: calls
    P15-->>- P0: return
    P0->>+ P16: calls
    P16-->>- P0: return
    P0->>+ P17: calls
    P17-->>- P0: return
    P0->>+ P18: calls
    P18-->>- P0: return
```

## Connections by Relation

### calls
- [[_coerce_device()]] `EXTRACTED`
- [[train_mgcecdl_model()]] `EXTRACTED`
- [[train_mgcecdl_classifier()]] `EXTRACTED`
- [[crear_objective_regresion_mgcecdl()]] `EXTRACTED`
- [[crear_objective_clasificacion_mgcecdl()]] `EXTRACTED`
- [[predict_regression()]] `EXTRACTED`
- [[predict_classification()]] `EXTRACTED`
- [[_probe_cuda_device()]] `EXTRACTED`

### contains
- [[mgcecdl.py]] `EXTRACTED`

### rationale_for
- [[Resolve CUDA, MPS, or CPU and fall back when CUDA cannot execute kernels.]] `EXTRACTED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*