# OSSAI-26 Repository Instructions

## Project overview

- This is a Python 3.14 experiment for evaluating Gemini answers and evidence against local DART disclosure HTML.
- Preserve the existing YAML/artifact schema v2 workflow while extending the JSONL/artifact schema v3 optimization and robustness workflows.
- Read `README.md` for user-facing commands and `docs/workflow.md` for the execution and scoring model before changing behavior.

## Environment and commands

- Use `uv` and the committed lockfile. Do not add or update dependencies unless the task requires it.
- Install: `uv sync --locked --dev`
- Run all tests: `uv run --locked pytest`
- Run lint: `uv run --locked ruff check .`
- If sandboxed `uv` cache access is unavailable, use `.venv/bin/pytest` and `.venv/bin/ruff check .` without changing project configuration.
- Validate the recorded v3 dataset with:
  `uv run --locked python scripts/validate_dataset.py --cases configs/cases.v3.example.jsonl --config configs/prompt-optimization.recorded.yaml`

## Code conventions

- Keep application code under `src/dart_parser_workflow`, thin CLI wrappers under `scripts`, and deterministic fixtures under `tests/fixtures`.
- Use strict Pydantic models with `extra="forbid"` for configuration, inputs, and artifacts.
- Keep deterministic scoring and selection in Python; providers may generate answers or candidate prompts but must not decide scores or winners.
- Use Unicode compatibility and whitespace normalization only. Do not silently normalize numeric punctuation, units, dates, or financial scope.
- Keep the executable DART QA prompt in `prompts/dart-qa-baseline.md`; `{question}` and `{html}` are the only supported placeholders.
- Maintain Ruff's 100-character line limit and the configured E/F/I/UP/B rules.

## Evaluation invariants

- Never include expected answers in target-provider prompts.
- Only development failures may be sent to the optimizer. Only validation results may select a prompt. Test cases run only after selection.
- Preserve automatic rollback when a candidate is identical, increases errors or answerable abstentions, reduces strict pass rate, or misses the configured mean-improvement threshold.
- Treat answerable and unanswerable cases separately. An unanswerable case passes only with the exact safe-abstention contract.
- Validate IDs, family split isolation, project-relative paths, HTML hashes, expected evidence, and context anchors before model calls.
- Keep run completeness (`complete`, `partial`, `not_run`) separate from quality (`pass`, `fail`, `inconclusive`).

## Artifacts, data, and safety

- Do not commit `.env`, API keys, real DART HTML, or generated `reports/` artifacts.
- DART HTML and questions may be sent to an external model. Use live providers only when the data is authorized for external transmission.
- Do not write full HTML or rendered prompts to `calls.jsonl`; record hashes and bounded metadata instead.
- Never overwrite or resume an existing optimization, variant, or robustness output directory. Preserve partial runs and use a new run ID.
- Require completed human review for HTML variants. Exclude `invalid_variant` from quality aggregation.
- Keep tests deterministic and offline. Live Gemini calls are not part of the automated test suite.

## Change validation

- Add regression tests for behavior changes, including failure and rollback paths.
- Run the focused tests while iterating, then run the full pytest and Ruff commands before handing off.
- When changing schemas, prompts, scoring, lineage, or output files, update `README.md` and `docs/workflow.md` in the same change.
- Preserve unrelated working-tree changes and generated local data.

## Code review rules

- Flag any path that can leak validation or test data into candidate generation or selection.
- Flag evidence checks that accept text not present in the current HTML variant.
- Flag lineage checks that allow mismatched dataset, HTML, prompt, scorer, or Git identities.
- Flag changes that conflate successful execution with model quality or that weaken safe abstention.
