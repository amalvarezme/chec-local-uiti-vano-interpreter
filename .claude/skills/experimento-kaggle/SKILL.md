---
name: experimento-kaggle
description: "Trigger: /experimento-kaggle, prueba de código, experimento remoto, correr en Kaggle. Propone diagrama de bloques y cuaderno, exige aprobación del usuario (gate), y ejecuta remoto en Kaggle vía CLI."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.1.0"
  runtime: claude
  canonical_contract: references/kaggle-cli-notes.md
---

## Activation Contract

Use this skill when the user wants to prototype/test a code or model experiment (training
run, hyperparameter search, ablation) that should not run as a long, silent local process,
but instead be proposed, human-approved, and executed remotely on Kaggle.

Invocation: `/experimento-kaggle <descripción del experimento>`

## Hard Rules

- Never reimplement a model that already exists in `src/`. Before authoring any model/loss
  code for an experiment, run the precondition guard against the resolved project root:
  `python -c "from chec_impacto.models.mgcecdl import MGCECDLRegressor, MGCECDLRegressionLoss"`
  (swap the import for whatever model is in scope for the experiment). If it raises
  `ImportError`, STOP before writing any model/loss code, name the branch/worktree that
  carries the missing code (e.g. `worktree-agent-a4051edb7e841e0f9` for `MGCECDLRegressor`),
  and wait — never fall back to a substitute implementation.
- Never push or run anything on Kaggle before the user explicitly approves both the block
  diagram and the notebook. This is a hard gate — do not infer approval from silence or from
  an earlier unrelated confirmation.
- Always propose the workflow first as a Mermaid block diagram (data → config → smoke run →
  full run → outputs) before writing any notebook code.
- Build the notebook with two explicit, parametrized modes: `smoke` (tiny — few epochs/trials,
  small data subsample, must finish in well under a minute) and `full`. Never trust a bare exit
  code as success; read the actual printed output/metrics.
- Never touch, request, or store the user's Kaggle credentials. Only check whether
  `~/.kaggle/kaggle.json` or `KAGGLE_USERNAME`/`KAGGLE_KEY` exist; if not, stop and tell the
  user exactly how to place their own token, then wait.
- Prefer an already-connected Kaggle MCP tool in this session (`ToolSearch("kaggle")`) if one
  exists. Otherwise use the official `kaggle` CLI/Python package. Never install or recommend an
  unverified third-party MCP server without telling the user it's third-party and getting
  explicit confirmation first.
- Poll `kaggle kernels status` for real state; never report a run as finished/failed without
  having actually polled it after this session's own push.
- After completion, pull outputs with `kaggle kernels output` and report them plainly,
  including failures — never fabricate results.

## Execution Steps

Full CLI commands, `kernel-metadata.json` schema, and accelerator options are in
`references/kaggle-cli-notes.md`.

1. Restate the experiment goal; propose the Mermaid block diagram; STOP for approval.
2. Once approved, check the **Experiment Families** table below. If the experiment matches a
   listed family, run the precondition guard for its reuse module first, then import (never
   rewrite) the listed classes and compare results against the family's baseline reference
   file using its named primary metric. Then build the notebook under
   `notebooks/kaggle_experiments/<slug>/` with the `smoke`/`full` split, plus its
   `kernel-metadata.json`.
3. STOP again: present the notebook path and what it does; require explicit approval before
   any push. Revise and re-present on any requested change — never proceed on unclear approval.
4. Verify Kaggle auth is configured; if missing, stop and instruct the user.
5. `kaggle kernels push -p <folder>` in `smoke` mode; poll `kaggle kernels status <kernel>`
   until terminal; pull with `kaggle kernels output <kernel> -p <dir> -o`; verify the real
   smoke output before ever pushing `full`.
6. Only after a verified-passing smoke run, push `full` (optionally `--accelerator`/`-t`);
   poll status; pull outputs.
7. Report the diagram, notebook path, kernel slug, every status transition observed, and the
   final outputs location.

### Experiment Families

Reuse-first dispatch table — matching families import the listed module instead of
rewriting it, and are judged against the listed baseline reference file's primary metric.

| Family | Reuse from (module) | Baseline ref | Primary metric |
|---|---|---|---|
| `uiti-vano-regression` | `chec_impacto.models.mgcecdl` | `references/uiti-vano-regression-baseline.md` | `mae_original` (lower is better) |

## Output Contract

Return: the approved diagram, notebook + `kernel-metadata.json` paths, kernel slug/URL, the
smoke-run verified result, full-run status history, and the local path of pulled outputs with
a plain-language summary (including any failure).

## References

- `references/kaggle-cli-notes.md`
