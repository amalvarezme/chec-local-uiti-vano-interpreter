# LLM Output Validator

Validate every LLM response before presenting it as analysis.

## The Response Must

- Be valid JSON.
- Match `uiti_vano_explanation.output_schema.json`.
- Include only dates present in `critical_points` or `daily_series`.
- Not reference unavailable columns as if they were present.
- Not claim use of RAG, operational logs, standards review, predictive models, masks, simulations, or final report generation.
- Include limitations.
- Include data gaps when optional variables are missing.

## If Validation Fails

- Save invalid raw output to `outputs/invalid_llm_output_<timestamp>.txt`.
- Save validation errors to `outputs/llm_validation_errors_<timestamp>.json`.
- Do not present the invalid output as final analysis.
- Print a clear notebook message explaining that the prompt and context were saved for manual review.
