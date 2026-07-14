# Shared JSON Output Safety

These rules apply to every report-generation LLM agent unless a profile-specific contract is stricter.

## Mandatory response format

- Return exactly one valid JSON object when the caller requests JSON.
- Do not include markdown, code fences, comments, text before the JSON, text after the JSON, or `<think>` tags.
- Keep arrays compact; profile-specific contracts may set maximum item counts, but five items per list is the default upper bound.
- Close every object and array. Before finalizing, verify commas, brackets, braces, and required keys.
- Use only values present in the provided context, tables, model outputs, graph metadata, or validated artifacts.
- Do not invent circuits, dates, variables, graph paths, costs, risks, classes, PDFs, or evidence.

## Invalid or uncertain inputs

- If required input is missing, return the required JSON shape with explicit limitations or empty arrays rather than inventing analysis.
- If the input table/context is empty, state the limitation and avoid conclusions.
- If optional variables are unavailable, mention the data gap only when the profile contract requires it.
- Never present invalid or unvalidated LLM output as final analysis.

## Prohibited additions

- Do not claim use of RAG, vector stores, Databricks, Dash, FastAPI, external searches, raw PDFs, bitácoras, normative reviews, feature-importance masks, or manual what-if simulations unless the profile-specific context explicitly provides that artifact and permits it.
- Do not log, expose, or infer secrets or credentials.
