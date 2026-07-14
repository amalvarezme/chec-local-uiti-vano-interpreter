# Shared CHEC Domain Language

These rules unify the domain vocabulary used by the base descriptor, inference, expert-alignment, and simulator agents.

## Core variables

- `CIRCUITO`: circuit identifier.
- `FID_VANO`: spatial/operational span identifier; usual aggregation unit for prioritized spans.
- `FECHA`: event timestamp.
- `DURACION`, `TOT_USUS`, `UITI`, `PORC_APORTE_VANO`, and `UITI_VANO`: interruption duration, affected users, interruption impact, span contribution, and span-level impact.
- `UITI_VANO` is an impact indicator, target, ranking criterion, or class basis. Do not treat it as a model predictor when it is excluded from `features`.
- `NR_T`: vegetation-related risk near the span.
- `DDT`: ground-flash density / atmospheric discharge density.
- Climate lag families include `prep`, `temp`, `wind_gust_spd`, `wind_spd`, `clouds`, `pres`, `sp`, `rh`, and `solar_rad`; suffixes represent lagged windows present in the supplied features.

## CHEC modes

Use these semantic groups consistently:

1. Event, impact, and indicators.
2. Protection and switching infrastructure.
3. Topology and spatial configuration.
4. Physical and electrical span characteristics.
5. Assets: end support and transformer.
6. Environment, risk, and climate.

## Language rules

Use cautious, evidence-based language:

- Prefer: "sugiere", "es compatible con", "podría estar asociado con", "la evidencia tabular muestra", "el modelo asignó relevancia", "requiere validación operativa".
- Avoid: "causó definitivamente", "demuestra que", "la causa fue", "el modelo prueba", "el grafo demuestra causalidad", "el vano es malo".
- Do not convert temporal coincidence into cause.
- Do not convert model importance, SHAP, Borda, attention, graph weights, or simulator changes into operational causality.
- Distinguish observed values, model explanations, graph context, and operational hypotheses.

## Interpretation defaults

- Interpret variables through their CHEC mode and, when available, their relation to `UITI_VANO` or risk classes.
- Distinguish severity/impact (`UITI_VANO`, `UITI_VANO_PROM`) from recurrence/frequency (`N_APARICIONES`).
- A high-impact low-frequency span is not the same operational pattern as a low-impact high-frequency span.
- If a variable is absent from model `features`, use it only as original context or graph-route context, not as a predictor used by the model.
