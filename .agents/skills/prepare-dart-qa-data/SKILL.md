---
name: prepare-dart-qa-data
description: Prepare human-reviewed DART disclosure QA datasets for this repository's artifact schema v3 workflow. Use when collecting DART HTML, drafting answerable or unanswerable evaluation cases, assigning family-safe development/validation/test splits, calculating HTML hashes, creating a review checklist, or finalizing and validating cases.v3.jsonl. Also use for Korean requests such as "DART 평가 데이터 준비해줘", "QA 사례 만들어줘", "공시 HTML로 정답·근거 데이터셋 만들어줘", or "데이터 검토표 만들어줘".
---

# Prepare DART QA Data

Build a local, review-gated dataset for the repository's prompt optimization workflow. Treat all
Codex-authored answers and evidence as drafts until a person explicitly approves them.

## Preserve the responsibility boundary

- Let Codex collect authorized HTML, calculate hashes, draft cases, assign families and splits,
  run mechanical checks, and summarize validation errors.
- Require one named human reviewer to approve the answer, period, scope, unit, and evidence for
  every case. The author may also be the reviewer.
- Never infer human approval from silence, prior conversation, or a successful validator run.
- Never call the target, optimizer, optimization, or robustness provider as part of preparation.
- Never ask the user to paste an API key. Get separate external-transmission authorization before
  any later live provider run.
- Keep real DART HTML and drafts under `local-data/`; do not add them to Git.
- Never overwrite a prepared dataset, review file, or final dataset. Choose a new path or run ID.

## 1. Establish the dataset contract

Before writing files, obtain or derive:

- DART receipt numbers or URLs and whether to collect the full filing or named sections;
- the metrics, periods, scopes, units, and answer types to evaluate;
- the target case count and development/validation/test counts;
- required tags from the selected optimization config;
- the intended local paths under `local-data/dart-qa/`.

If a choice affects the factual answer, ask the user instead of guessing. Inspect
`src/dart_parser_workflow/schemas.py`, `src/dart_parser_workflow/dataset.py`, and the selected
optimization config before drafting; they are the current machine-readable contract.

Use this layout unless the user already has a compatible one:

```text
local-data/dart-qa/
├── html/
├── drafts/
├── reviews/
└── cases/
```

## 2. Collect and preserve HTML

When collection is needed, read `.claude/skills/dart-html-fetch/SKILL.md` completely before
running its driver. Use its Python driver at
`.claude/skills/dart-html-fetch/driver.python/main.py` unless the environment favors .NET.

List sections first when only part of a large filing is required. Save the chosen full filing or
section under `local-data/dart-qa/html/`. Preserve that file as the immutable evaluation input;
re-fetch into a new file if the source changes.

Do not fetch when the user has not supplied the URL or receipt number and the missing filing
cannot be derived from repository context. Report DART blocking or ambiguous section matches
instead of silently switching documents.

## 3. Draft cases without hashes

Create JSONL with one object per line using the current `EvaluationCaseV3` fields, but omit
`html_sha256`; `schema_version` may also be omitted. Keep `html_path` project-relative.

For answerable cases:

- Copy `expected.answer` and every `evidence_quotes` value from visible HTML text.
- Preserve numeric punctuation, period, financial scope, and unit exactly.
- Put enough adjacent context in the quote to disambiguate the value.
- Make every `evidence_must_include` anchor occur inside the combined evidence quotes.
- Add accepted answers only when they are genuinely equivalent under Unicode and whitespace
  normalization; do not use accepted answers to hide unit or scope differences.

For unanswerable cases, use exactly:

```json
{
  "answer": "답변 보류",
  "accepted_answers": [],
  "abstained": true,
  "evidence_quotes": [],
  "evidence_must_include": []
}
```

Assign the same `family_id` to the same filing/question family and all derived cases. Allocate
whole families to one split only. Include at least `answerable` or `unanswerable` in `tags`, plus
useful structural tags such as `table` or `narrative`.

Never use a target-provider answer as expected ground truth.

## 4. Materialize hashes and the review template

Run the bundled tool from the project root:

```bash
uv run --locked python \
  .agents/skills/prepare-dart-qa-data/scripts/prepare_dataset.py materialize \
  --drafts local-data/dart-qa/drafts/cases.draft.jsonl \
  --prepared local-data/dart-qa/drafts/cases.prepared.jsonl \
  --reviews local-data/dart-qa/reviews/review.jsonl \
  --project-root .
```

This command calculates the HTML hash, validates the v3 case structure, checks paths, evidence,
IDs, and family isolation, then creates a pending review row for every case. Fix the source draft
or HTML selection when it fails; do not edit generated hashes by hand.

## 5. Obtain explicit human approval

Read [references/review-guide.md](references/review-guide.md) before presenting the review. Show
the reviewer each question, proposed answer or abstention, period, scope, unit, and exact evidence.
Record corrections in the draft and re-run `materialize` to new output paths.

Only after explicit approval, edit the corresponding review row:

```json
{
  "schema_version": 1,
  "case_id": "example-case",
  "case_sha256": "materialize가 기록한 64자리 SHA-256",
  "reviewer": "reviewer-name",
  "decision": "approved",
  "checks": {
    "answer": true,
    "period": true,
    "scope": true,
    "unit": true,
    "evidence": true
  },
  "notes": ""
}
```

Use `decision: "revise"` when any field needs correction. Never change a pending or revise row to
approved on Codex's own authority.

## 6. Finalize and validate

After every case is approved, run:

```bash
uv run --locked python \
  .agents/skills/prepare-dart-qa-data/scripts/prepare_dataset.py finalize \
  --prepared local-data/dart-qa/drafts/cases.prepared.jsonl \
  --reviews local-data/dart-qa/reviews/review.jsonl \
  --config configs/prompt-optimization.default.yaml \
  --output local-data/dart-qa/cases/cases.v3.jsonl \
  --project-root .
```

The command rejects missing, duplicate, stale-hash, pending, revise, unnamed, or partially checked
reviews. It applies the selected config's split and tag requirements through the repository's v3
validator, creates the final JSONL atomically, and prints its dataset SHA-256.

## 7. Report the handoff

Report:

- final dataset path, case count, split counts, and dataset SHA-256;
- reviewer name and whether all rows were approved;
- any remaining collection or review limitations;
- that no live provider was called during preparation.

Stop after validation unless the user separately asks to run optimization or robustness.

## Handle failures

- On hash mismatch after preparation, treat the HTML as changed and restart with new prepared and
  review paths.
- On family leakage, move the whole family rather than only the reported case.
- On evidence failure, inspect visible text and correct the quote; do not weaken the validator.
- On split or tag count failure, update the dataset plan or selected config explicitly.
- On an existing output path, preserve it and choose a new versioned filename.
