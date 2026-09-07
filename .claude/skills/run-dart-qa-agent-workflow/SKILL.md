---
name: run-dart-qa-agent-workflow
description: Run the repository's approval-gated DART QA prompt workflow through immutable Development, Validation, Test, and robustness stages. Use when starting, continuing, inspecting, or approving the AI Agent workflow. Do not use for dataset authoring.
---

# Run DART QA Agent Workflow

Use `scripts/run_agent_workflow.py` as the only workflow controller. Do not implement scoring,
selection, approval, or retry decisions in Claude Code instructions.

## Before acting

- Read `README.md`, `docs/workflow.md`, and `docs/ai-agent-workflow-plan.md`.
- For an existing workflow, run `status` before choosing an action.
- Do not inspect Validation/Test expected values or raw held-out result files.
- Pass every configured user question to the target model verbatim. Never trim, summarize,
  correct, translate, supplement, or rewrite it.
- Never delete, overwrite, or append to a completed report or stage directory.

## Execute only the permitted transition

- No workflow → `prepare` with a new path.
- `prepared` or retryable `developing` → `develop` with a new stage-run ID.
- `awaiting_validation_approval` → present the Development candidate/gate and stop.
- Approved Validation → `validate` once; report only sanitized selection data.
- `awaiting_test_approval` → present the sealed selection digest and stop.
- Approved Test → `test` with a new stage-run and campaign ID.
- `reporting` → robustness only after a separate user request and completed variant review.

Run commands with `uv run --locked python`; use `.venv/bin/python` only when uv cache access is
blocked.

## Preserve approval boundaries

- Do not create an approval unless the user explicitly approves that stage and names the approver.
- Do not add `--authorize-external-transmission` without explicit authorization for that live
  stage.
- Stop on phase, digest, lineage, exposure, or budget failures; never bypass the controller.
- For partial Test continuation, require a new approval naming every allowed re-exposure case.

Report the workflow path, phase, stage-run ID, execution and quality status, next approval, and
sanitized artifact paths. Never quote held-out expected answers.
