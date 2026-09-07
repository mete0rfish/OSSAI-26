---
name: run-dart-qa-agent-workflow
description: Run the repository's approval-gated DART QA prompt workflow through immutable Development, Validation, Test, and robustness stages. Use when starting, continuing, inspecting, or approving the AI Agent workflow. Do not use for dataset authoring.
---

# Run DART QA Agent Workflow

Operate the shared Python controller; do not reproduce scoring, selection, approval, or retry
logic in the skill.

## Before acting

- Read `README.md`, `docs/workflow.md`, and `docs/ai-agent-workflow-plan.md`.
- Inspect state with `scripts/run_agent_workflow.py status --workflow <path>` when a workflow
  already exists.
- Use the configured v3 dataset and optimization YAML. Do not inspect Validation/Test expected
  values or raw held-out result files.
- Pass every configured user question to the target model verbatim. Never trim, summarize,
  correct, translate, supplement, or rewrite it.
- Never delete, overwrite, or resume an existing report or stage directory.

## Follow the state machine

- No workflow: run `prepare` with a new workflow path.
- `prepared` or retryable `developing`: run `develop` with a new `stage-run-id`.
- `awaiting_validation_approval`: show only the candidate and Development gate summary, then stop.
- Approved Validation: run `validate` once and report its sanitized selection summary.
- `awaiting_test_approval`: show the sealed selection digest, then stop.
- Approved Test: run `test` with a new stage and campaign ID.
- `reporting`: run robustness only when the user separately requests it and reviewed variants exist.

Use `uv run --locked python scripts/run_agent_workflow.py <command> ...`; fall back to
`.venv/bin/python` only when the sandbox cannot use the uv cache.

## Approval and transmission

- Never infer, fabricate, or grant human approval.
- Run `approve-validation` or `approve-test` only when the user explicitly approves that stage
  and supplies the approver name.
- Add `--authorize-external-transmission` only when the user explicitly authorizes the current
  live stage to send DART HTML and questions externally.
- Stop on digest, lineage, exposure, budget, or phase errors. Do not weaken the controller.
- A partial Test requires a new approval listing only explicitly authorized re-exposure cases.

## Handoff

Report the workflow path, phase, stage-run ID, execution status, quality status, approval needed,
and sanitized artifact paths. Do not quote held-out case contents or expected answers.
