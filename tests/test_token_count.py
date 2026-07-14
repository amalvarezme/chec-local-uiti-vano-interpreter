import json
from chec_local_interpreter.data.loader import load_dataset, filter_events
from chec_local_interpreter.analysis.critical_points import (
    build_daily_series, compute_daily_features,
    detect_point_reasons, rank_critical_points, detect_critical_periods
)
from chec_local_interpreter.analysis.context_builder import build_context_package
from chec_local_interpreter.analysis.attribution import enrich_critical_points
from chec_local_interpreter.llm.contracts import render_prompt, load_output_schema
from chec_local_interpreter.config import PROMPT_VERSION

DATA_PATH = "data/Indicadores_vano_v3.csv"
raw_df = load_dataset(DATA_PATH)
events_df = filter_events(raw_df, selected_circuitos=['DON23L13'])
daily_df = build_daily_series(events_df)
feature_df = compute_daily_features(daily_df)
reasons = detect_point_reasons(feature_df)
critical_points = rank_critical_points(feature_df, reasons, max_points=6)
critical_points = enrich_critical_points(events_df, critical_points)
critical_periods = detect_critical_periods(feature_df)

context_package = build_context_package(
    raw_df=raw_df, events_df=events_df, daily_df=daily_df,
    critical_points=critical_points, critical_periods=critical_periods,
    selected_circuitos=['DON23L13'], start_date=None, end_date=None,
)

output_schema = load_output_schema()
context_json = json.dumps(context_package, ensure_ascii=False, indent=2)
schema_json = json.dumps(output_schema, ensure_ascii=False, indent=2)

prompt = render_prompt(
    context_json=context_json,
    output_schema_json=schema_json,
    prompt_version=PROMPT_VERSION,
)

# Size breakdown
print("=== PROMPT SIZE BREAKDOWN ===")
print(f"Total prompt chars: {len(prompt)}")
print(f"Total prompt words (approx tokens): {len(prompt.split())}")
print()

# Context package breakdown
print("=== CONTEXT PACKAGE BREAKDOWN ===")
for key, value in context_package.items():
    s = json.dumps(value, ensure_ascii=False, indent=2)
    print(f"  {key}: {len(s)} chars / ~{len(s.split())} words")

print()
print(f"  context_json total: {len(context_json)} chars / ~{len(context_json.split())} words")
print(f"  schema_json total: {len(schema_json)} chars / ~{len(schema_json.split())} words")

# Check daily_series record count
ds = context_package.get("daily_series", [])
print(f"\n  daily_series record count: {len(ds)}")

# Critical point sizes
cps = context_package.get("critical_points", [])
print(f"  critical_points count: {len(cps)}")
for i, cp in enumerate(cps):
    s = json.dumps(cp, ensure_ascii=False, indent=2)
    print(f"    CP {i}: {len(s)} chars")

# Estimate token count (rough: ~4 chars per token for Spanish/mixed text)
est_tokens = len(prompt) // 4
print(f"\n=== ESTIMATED TOKEN COUNT: ~{est_tokens} tokens ===")
print(f"    (DeepSeek limit: 32768)")
print(f"    {'✅ FITS' if est_tokens < 32768 else '❌ EXCEEDS LIMIT'}")
