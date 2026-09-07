"""승인 경계와 불변 stage run을 갖는 DART QA Agent 워크플로."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import OptimizationSettings
from .dataset import dataset_sha256
from .dataset_review import validate_approved_reviews
from .execution import BudgetExceeded, CallLedger, classify_provider_error
from .html_utils import normalize_text, sha256_file
from .prompt_optimization import build_optimizer_prompt, iter_cases_v3, select_prompt
from .prompts import load_prompt, validate_prompt_template
from .providers import (
    ModelProvider,
    OptimizerProvider,
    create_optimizer_provider_v3,
    create_target_provider_v3,
)
from .schemas import (
    AgentWorkflowManifestV3,
    ApprovalArtifactV3,
    CaseResultV3,
    EvaluationCaseV3,
    ModelUsage,
    OptimizationRequest,
    RepairTelemetryV3,
    StageRunManifestV3,
    TestExposureV3,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_TECHNICAL_STATUSES = {"input_error", "generation_error"}


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _append_jsonl(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def _resolve_project_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _source_tree_sha256(root: Path) -> str:
    rows: list[tuple[str, str]] = []
    for directory in ("src", "scripts", "prompts"):
        base = root / directory
        if not base.exists():
            continue
        paths = (
            item
            for item in base.rglob("*")
            if item.is_file()
            and "__pycache__" not in item.parts
            and (directory == "prompts" or item.suffix == ".py")
        )
        for path in sorted(paths):
            rows.append((str(path.relative_to(root)), sha256_file(path)))
    return _canonical_sha256(rows)


def _scorer_bundle_sha256(root: Path) -> str:
    paths = [
        root / "src/dart_parser_workflow/schemas.py",
        root / "src/dart_parser_workflow/evaluation.py",
        root / "src/dart_parser_workflow/prompt_optimization.py",
        root / "src/dart_parser_workflow/execution.py",
    ]
    return _canonical_sha256(
        [(str(path.relative_to(root)), sha256_file(path)) for path in paths]
    )


def _split_manifest_sha256(cases: list[EvaluationCaseV3]) -> str:
    rows = [
        {"id": case.id, "family_id": case.family_id, "html_sha256": case.html_sha256}
        for case in sorted(cases, key=lambda item: item.id)
    ]
    return _canonical_sha256(rows)


def _baseline(settings: OptimizationSettings, root: Path) -> str:
    return load_prompt(_resolve_project_path(settings.baseline_prompt, root))


def _config_sha256(
    settings: OptimizationSettings, config_path: str | Path, root: Path
) -> str:
    return _canonical_sha256(
        {
            "file_sha256": sha256_file(_resolve_project_path(config_path, root)),
            "effective_settings": settings.model_dump(mode="json"),
        }
    )


def _manifest_path(workflow: Path) -> Path:
    return workflow / "workflow-manifest.json"


def load_agent_workflow_manifest(
    workflow_dir: str | Path,
) -> AgentWorkflowManifestV3:
    path = _manifest_path(Path(workflow_dir).resolve())
    return AgentWorkflowManifestV3.model_validate_json(path.read_text(encoding="utf-8"))


def _save_manifest(workflow: Path, manifest: AgentWorkflowManifestV3) -> None:
    _atomic_json(_manifest_path(workflow), manifest)


def _stage_path(workflow: Path, stage: str, stage_run_id: str) -> Path:
    return workflow / stage / stage_run_id


def _new_stage_path(workflow: Path, stage: str, stage_run_id: str) -> Path:
    if not _SAFE_ID.fullmatch(stage_run_id):
        raise ValueError("stage_run_id는 안전한 영문·숫자·점·밑줄·하이픈이어야 합니다")
    path = _stage_path(workflow, stage, stage_run_id)
    path.mkdir(parents=True, exist_ok=False)
    return path


def _load_stage_manifest(path: Path) -> StageRunManifestV3:
    return StageRunManifestV3.model_validate_json(
        (path / "stage-manifest.json").read_text(encoding="utf-8")
    )


def _artifact_hashes(stage_path: Path) -> dict[str, str]:
    return {
        str(path.relative_to(stage_path)): sha256_file(path)
        for path in sorted(stage_path.rglob("*"))
        if path.is_file() and path.name != "stage-manifest.json"
    }


def _finalize_stage(
    path: Path,
    manifest: StageRunManifestV3,
    *,
    execution_status: str,
    quality_status: str,
    error_code: str | None = None,
) -> StageRunManifestV3:
    finished = manifest.model_copy(
        update={
            "execution_status": execution_status,
            "quality_status": quality_status,
            "finished_at": _now(),
            "artifacts": _artifact_hashes(path),
            "error_code": error_code,
        }
    )
    _atomic_json(path / "stage-manifest.json", finished)
    return finished


def _assert_bindings(
    manifest: AgentWorkflowManifestV3,
    cases: list[EvaluationCaseV3],
    settings: OptimizationSettings,
    config_path: str | Path,
    root: Path,
) -> None:
    actual = {
        "dataset": dataset_sha256(cases, root),
        "config": _config_sha256(settings, config_path, root),
        "source": _source_tree_sha256(root),
        "scorer": _scorer_bundle_sha256(root),
        "baseline": _sha256_text(_baseline(settings, root)),
    }
    expected = {
        "dataset": manifest.dataset_sha256,
        "config": manifest.config_sha256,
        "source": manifest.source_tree_sha256,
        "scorer": manifest.scorer_bundle_sha256,
        "baseline": manifest.baseline_prompt_sha256,
    }
    mismatched = sorted(name for name in actual if actual[name] != expected[name])
    if mismatched:
        raise ValueError(f"workflow binding이 변경되었습니다: {mismatched}")


def _require_live_authorization(
    settings: OptimizationSettings,
    authorized: bool,
    manifest: AgentWorkflowManifestV3,
) -> None:
    live = any(
        provider.kind != "recorded"
        for provider in (settings.target_provider, settings.optimizer_provider)
    )
    if live and not authorized:
        raise PermissionError("live 단계에는 명시적 외부 전송 승인이 필요합니다")
    if live and manifest.review_sha256 is None:
        raise PermissionError("live 단계에는 승인 완료된 dataset review가 필요합니다")


def prepare_agent_workflow(
    cases: list[EvaluationCaseV3],
    settings: OptimizationSettings,
    workflow_dir: str | Path,
    project_root: str | Path,
    config_path: str | Path,
    *,
    reviews_path: str | Path | None = None,
) -> AgentWorkflowManifestV3:
    root = Path(project_root).resolve()
    workflow = Path(workflow_dir).resolve()
    review_sha256 = None
    live = any(
        provider.kind != "recorded"
        for provider in (settings.target_provider, settings.optimizer_provider)
    )
    if live:
        if reviews_path is None:
            raise ValueError("live workflow 준비에는 승인 완료된 reviews JSONL이 필요합니다")
        validate_approved_reviews(cases, reviews_path, root)
        review_sha256 = sha256_file(_resolve_project_path(reviews_path, root))
    now = _now()
    splits = {
        split: [case for case in cases if case.split == split]
        for split in ("development", "validation", "test")
    }
    if any(not rows for rows in splits.values()):
        raise ValueError("development/validation/test split은 모두 비어 있지 않아야 합니다")
    workflow.mkdir(parents=True, exist_ok=False)
    manifest = AgentWorkflowManifestV3(
        workflow_id=workflow.name,
        phase="prepared",
        execution_status="complete",
        quality_status="inconclusive",
        approval_status="pending",
        created_at=now,
        updated_at=now,
        dataset_sha256=dataset_sha256(cases, root),
        config_sha256=_config_sha256(settings, config_path, root),
        source_tree_sha256=_source_tree_sha256(root),
        scorer_bundle_sha256=_scorer_bundle_sha256(root),
        baseline_prompt_sha256=_sha256_text(_baseline(settings, root)),
        split_case_ids={split: [case.id for case in rows] for split, rows in splits.items()},
        split_manifest_sha256={
            split: _split_manifest_sha256(rows) for split, rows in splits.items()
        },
        review_sha256=review_sha256,
    )
    _save_manifest(workflow, manifest)
    return manifest


def _stage_input_digest(
    manifest: AgentWorkflowManifestV3,
    stage: str,
    parent_run_id: str | None,
    approval_digest: str | None = None,
) -> str:
    return _canonical_sha256(
        {
            "workflow_id": manifest.workflow_id,
            "stage": stage,
            "parent_run_id": parent_run_id,
            "dataset_sha256": manifest.dataset_sha256,
            "config_sha256": manifest.config_sha256,
            "source_tree_sha256": manifest.source_tree_sha256,
            "scorer_bundle_sha256": manifest.scorer_bundle_sha256,
            "baseline_prompt_sha256": manifest.baseline_prompt_sha256,
            "approval_digest": approval_digest,
        }
    )


def _initial_stage_manifest(
    manifest: AgentWorkflowManifestV3,
    stage: str,
    stage_run_id: str,
    parent_run_id: str | None,
    approval_digest: str | None = None,
) -> StageRunManifestV3:
    return StageRunManifestV3(
        workflow_id=manifest.workflow_id,
        stage_run_id=stage_run_id,
        parent_run_id=parent_run_id,
        stage=stage,
        execution_status="partial",
        quality_status="inconclusive",
        started_at=_now(),
        input_digest=_stage_input_digest(
            manifest, stage, parent_run_id, approval_digest
        ),
    )


def _write_results(path: Path, results: list[CaseResultV3], *, redact: bool) -> None:
    for result in results:
        value = result.model_dump(mode="json")
        if redact:
            value.pop("expected")
        _append_jsonl(path, value)


def _run_cases(
    cases: list[EvaluationCaseV3],
    *,
    output_path: Path,
    run_id: str,
    prompt: str,
    prompt_variant: str,
    settings: OptimizationSettings,
    provider: ModelProvider,
    ledger: CallLedger,
    redact: bool,
    before_attempt=None,
) -> list[CaseResultV3]:
    iterator = iter_cases_v3(
        cases,
        run_id=run_id,
        prompt_template=prompt,
        prompt_variant=prompt_variant,
        workflow=settings.workflow,
        provider=provider,
        provider_settings=settings.target_provider,
        requested_model=settings.target_provider.model,
        ledger=ledger,
        retry=settings.retry,
        before_attempt=before_attempt,
    )
    results = []
    for result in iterator:
        results.append(result)
        _write_results(output_path, [result], redact=redact)
    return results


def _technical_telemetry(
    results: list[CaseResultV3], prompt_variant: str, attempts: int
) -> list[RepairTelemetryV3]:
    rows = []
    for result in results:
        if result.status not in _TECHNICAL_STATUSES:
            continue
        code = (
            "input_error"
            if result.status == "input_error"
            else (result.error or result.status).split(":", 1)[0]
        )
        rows.append(
            RepairTelemetryV3(
                sample_id=result.sample_id,
                prompt_variant=prompt_variant,
                error_code=code,
                retryable=code
                in {"timeout", "rate_limit", "transport", "server_error", "empty_response"},
                attempts=0 if result.status == "input_error" else attempts,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_seconds=result.latency_seconds,
            )
        )
    return rows


def _validate_candidate_literals(
    candidate: str, development_cases: list[EvaluationCaseV3]
) -> None:
    normalized = normalize_text(candidate)
    leaked = []
    for case in development_cases:
        if case.expected.abstained:
            continue
        for answer in [case.expected.answer, *case.expected.accepted_answers]:
            if normalize_text(answer) in normalized:
                leaked.append(case.id)
                break
    if leaked:
        raise ValueError(f"candidate prompt에 Development expected가 포함되었습니다: {leaked}")


def _propose_candidate(
    prompt: str,
    settings: OptimizationSettings,
    provider: OptimizerProvider,
    ledger: CallLedger,
) -> str:
    for attempt in range(settings.retry.max_attempts_per_call):
        ledger.before_request("optimizer")
        try:
            response = provider.propose(OptimizationRequest(attempt=attempt, prompt=prompt))
        except BudgetExceeded:
            raise
        except Exception as exc:
            classified = classify_provider_error(exc, settings.retry)
            ledger.record(
                role="optimizer",
                sample_id="prompt-candidate",
                prompt_variant="optimizer",
                prompt=prompt,
                requested_model=settings.optimizer_provider.model,
                actual_model=None,
                usage=ModelUsage(),
                latency_seconds=None,
                attempt=attempt,
                error=classified.summary(),
            )
            if classified.retryable and attempt + 1 < settings.retry.max_attempts_per_call:
                delay = settings.retry.initial_backoff_seconds * (2**attempt)
                if delay:
                    time.sleep(delay)
                continue
            raise RuntimeError(classified.summary()) from exc
        ledger.record(
            role="optimizer",
            sample_id="prompt-candidate",
            prompt_variant="optimizer",
            prompt=prompt,
            requested_model=response.requested_model,
            actual_model=response.actual_model,
            usage=response.usage,
            latency_seconds=response.latency_seconds,
            attempt=attempt,
        )
        validate_prompt_template(response.result.prompt)
        return response.result.prompt
    raise AssertionError("retry loop가 실행되지 않았습니다")


def develop_agent_workflow(
    cases: list[EvaluationCaseV3],
    settings: OptimizationSettings,
    workflow_dir: str | Path,
    project_root: str | Path,
    config_path: str | Path,
    stage_run_id: str,
    *,
    authorize_external_transmission: bool = False,
    target_provider: ModelProvider | None = None,
    optimizer_provider: OptimizerProvider | None = None,
) -> StageRunManifestV3:
    root, workflow = Path(project_root).resolve(), Path(workflow_dir).resolve()
    workflow_manifest = load_agent_workflow_manifest(workflow)
    _assert_bindings(workflow_manifest, cases, settings, config_path, root)
    _require_live_authorization(
        settings, authorize_external_transmission, workflow_manifest
    )
    if workflow_manifest.phase not in {"prepared", "developing"}:
        raise ValueError(f"Development를 시작할 수 없는 phase입니다: {workflow_manifest.phase}")
    if workflow_manifest.iteration >= settings.agent_workflow.max_iterations:
        raise ValueError("Development 최대 반복 횟수에 도달했습니다")
    parent = (
        workflow_manifest.latest_stage_run_id
        if workflow_manifest.latest_stage == "development"
        else None
    )
    stage_path = _new_stage_path(workflow, "development", stage_run_id)
    stage = _initial_stage_manifest(workflow_manifest, "development", stage_run_id, parent)
    workflow_manifest = workflow_manifest.model_copy(
        update={
            "phase": "developing",
            "execution_status": "partial",
            "quality_status": "inconclusive",
            "approval_status": "pending",
            "updated_at": _now(),
        }
    )
    _save_manifest(workflow, workflow_manifest)
    ledger = CallLedger(
        stage_path / "calls.jsonl",
        {"target": settings.target_limits, "optimizer": settings.optimizer_limits},
    )
    try:
        target = target_provider or create_target_provider_v3(settings.target_provider, root)
        optimizer = optimizer_provider or create_optimizer_provider_v3(
            settings.optimizer_provider, root
        )
        development = [case for case in cases if case.split == "development"]
        baseline = _baseline(settings, root)
        baseline_results = _run_cases(
            development,
            output_path=stage_path / "baseline.jsonl",
            run_id=stage_run_id,
            prompt=baseline,
            prompt_variant="baseline",
            settings=settings,
            provider=target,
            ledger=ledger,
            redact=False,
        )
        technical = _technical_telemetry(
            baseline_results,
            "baseline",
            settings.retry.max_attempts_per_call,
        )
        if technical:
            _atomic_json(
                stage_path / "repair-telemetry.json",
                {"items": [item.model_dump(mode="json") for item in technical]},
            )
            stage = _finalize_stage(
                stage_path,
                stage,
                execution_status="complete",
                quality_status="inconclusive",
                error_code="development_technical_error",
            )
            workflow_manifest = workflow_manifest.model_copy(
                update={
                    "execution_status": "complete",
                    "latest_stage": "development",
                    "latest_stage_run_id": stage_run_id,
                    "development_stage_run_id": stage_run_id,
                    "iteration": workflow_manifest.iteration + 1,
                    "updated_at": _now(),
                }
            )
            _save_manifest(workflow, workflow_manifest)
            return stage
        failures = [item for item in baseline_results if not item.score.strict_pass]
        if not failures:
            raise ValueError("Development baseline에 개선할 품질 실패가 없습니다")
        optimizer_prompt = build_optimizer_prompt(baseline, failures)
        candidate = _propose_candidate(optimizer_prompt, settings, optimizer, ledger)
        _validate_candidate_literals(candidate, development)
        (stage_path / "candidate-prompt.md").write_text(candidate, encoding="utf-8")
        candidate_results = _run_cases(
            development,
            output_path=stage_path / "candidate.jsonl",
            run_id=stage_run_id,
            prompt=candidate,
            prompt_variant="candidate",
            settings=settings,
            provider=target,
            ledger=ledger,
            redact=False,
        )
        gate = select_prompt(
            baseline,
            candidate,
            baseline_results,
            candidate_results,
            min_mean_improvement=settings.selection.min_mean_improvement,
        )
        gate_value = {
            "candidate_id": f"candidate-{workflow_manifest.iteration + 1}",
            "parent_prompt_sha256": _sha256_text(baseline),
            "iteration": workflow_manifest.iteration + 1,
            "change_class": "prompt",
            "eligible": gate.selected == "candidate",
            "decision": gate.model_dump(mode="json"),
        }
        _atomic_json(stage_path / "gate.json", gate_value)
        eligible = gate.selected == "candidate"
        stage = _finalize_stage(
            stage_path,
            stage,
            execution_status="complete",
            quality_status="pass" if eligible else "fail",
        )
        workflow_manifest = workflow_manifest.model_copy(
            update={
                "phase": "awaiting_validation_approval" if eligible else "developing",
                "execution_status": "complete",
                "quality_status": "pass" if eligible else "fail",
                "approval_status": "pending",
                "latest_stage": "development",
                "latest_stage_run_id": stage_run_id,
                "development_stage_run_id": stage_run_id,
                "iteration": workflow_manifest.iteration + 1,
                "updated_at": _now(),
            }
        )
        _save_manifest(workflow, workflow_manifest)
        return stage
    except Exception as exc:
        if not (stage_path / "stage-manifest.json").exists():
            stage = _finalize_stage(
                stage_path,
                stage,
                execution_status="partial",
                quality_status="inconclusive",
                error_code=type(exc).__name__,
            )
        workflow_manifest = workflow_manifest.model_copy(
            update={
                "phase": "developing",
                "execution_status": "partial",
                "quality_status": "inconclusive",
                "latest_stage": "development",
                "latest_stage_run_id": stage_run_id,
                "development_stage_run_id": stage_run_id,
                "updated_at": _now(),
            }
        )
        _save_manifest(workflow, workflow_manifest)
        raise


def _active_approval_path(
    workflow: Path, manifest: AgentWorkflowManifestV3, stage: str
) -> Path:
    relative = (
        manifest.active_validation_approval
        if stage == "validation"
        else manifest.active_test_approval
    )
    if relative is None:
        raise ValueError(f"활성 {stage} 승인이 없습니다")
    path = (workflow / relative).resolve()
    if not path.is_relative_to(workflow):
        raise ValueError("승인 경로가 workflow 밖입니다")
    return path


def _approval_subject(
    workflow: Path, manifest: AgentWorkflowManifestV3, stage: str
) -> str:
    source_stage = "development" if stage == "validation" else "validation"
    source_run_id = (
        manifest.development_stage_run_id
        if stage == "validation"
        else manifest.validation_stage_run_id
    )
    if source_run_id is None:
        raise ValueError("승인할 stage run이 없습니다")
    stage_path = _stage_path(workflow, source_stage, source_run_id)
    stage_manifest_path = stage_path / "stage-manifest.json"
    values = {
        "workflow_id": manifest.workflow_id,
        "stage": stage,
        "dataset_sha256": manifest.dataset_sha256,
        "config_sha256": manifest.config_sha256,
        "source_tree_sha256": manifest.source_tree_sha256,
        "scorer_bundle_sha256": manifest.scorer_bundle_sha256,
        "stage_manifest_sha256": sha256_file(stage_manifest_path),
    }
    if stage == "validation":
        values.update(
            candidate_prompt_sha256=sha256_file(stage_path / "candidate-prompt.md"),
            gate_sha256=sha256_file(stage_path / "gate.json"),
            case_manifest_sha256=manifest.split_manifest_sha256["validation"],
        )
    else:
        values.update(
            selection_sha256=sha256_file(stage_path / "selection.json"),
            selected_prompt_sha256=sha256_file(stage_path / "selected-prompt.md"),
            case_manifest_sha256=manifest.split_manifest_sha256["test"],
        )
    return _canonical_sha256(values)


def approve_agent_stage(
    workflow_dir: str | Path,
    stage: str,
    approved_by: str,
    *,
    external_transmission_authorized: bool = False,
    allowed_reexposure_case_ids: list[str] | None = None,
    expires_in_hours: float = 24,
) -> ApprovalArtifactV3:
    if stage not in {"validation", "test"}:
        raise ValueError("승인 stage는 validation 또는 test여야 합니다")
    workflow = Path(workflow_dir).resolve()
    manifest = load_agent_workflow_manifest(workflow)
    expected_phase = (
        "awaiting_validation_approval" if stage == "validation" else "awaiting_test_approval"
    )
    if manifest.phase != expected_phase:
        raise ValueError(f"{stage} 승인을 만들 수 없는 phase입니다: {manifest.phase}")
    active = (
        manifest.active_validation_approval
        if stage == "validation"
        else manifest.active_test_approval
    )
    if active is not None:
        raise ValueError(f"아직 사용되지 않은 {stage} 승인이 있습니다")
    approver = approved_by.strip()
    if not approver:
        raise ValueError("approved_by는 비어 있을 수 없습니다")
    if expires_in_hours <= 0 or expires_in_hours > 168:
        raise ValueError("승인 유효시간은 0시간 초과 168시간 이하여야 합니다")
    allowed = sorted(set(allowed_reexposure_case_ids or []))
    if stage == "validation" and allowed:
        raise ValueError("재노출 허용은 Test 승인에서만 사용할 수 있습니다")
    unknown = sorted(set(allowed) - set(manifest.split_case_ids["test"]))
    if unknown:
        raise ValueError(f"Test에 없는 재노출 case입니다: {unknown}")
    approval_id = str(uuid.uuid4())
    approval = ApprovalArtifactV3(
        approval_id=approval_id,
        workflow_id=manifest.workflow_id,
        stage=stage,
        approved_by=approver,
        approved_at=_now(),
        expires_at=_now() + timedelta(hours=expires_in_hours),
        nonce=str(uuid.uuid4()),
        subject_digest=_approval_subject(workflow, manifest, stage),
        external_transmission_authorized=external_transmission_authorized,
        allowed_reexposure_case_ids=allowed,
    )
    path = workflow / "approvals" / f"{stage}-{approval_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(path, approval)
    approval_field = (
        "active_validation_approval" if stage == "validation" else "active_test_approval"
    )
    _save_manifest(
        workflow,
        manifest.model_copy(
            update={
                "approval_status": "approved",
                approval_field: str(path.relative_to(workflow)),
                "updated_at": _now(),
            }
        ),
    )
    return approval


def _verified_approval(
    workflow: Path,
    manifest: AgentWorkflowManifestV3,
    stage: str,
    *,
    live: bool,
) -> ApprovalArtifactV3:
    approval = ApprovalArtifactV3.model_validate_json(
        _active_approval_path(workflow, manifest, stage).read_text(encoding="utf-8")
    )
    if approval.workflow_id != manifest.workflow_id or approval.stage != stage:
        raise ValueError("승인 대상 workflow 또는 stage가 다릅니다")
    if approval.approval_id in manifest.used_approval_ids:
        raise ValueError("이미 사용된 승인입니다")
    if _now() >= approval.expires_at:
        raise ValueError("승인이 만료되었습니다")
    if approval.subject_digest != _approval_subject(workflow, manifest, stage):
        raise ValueError("승인 이후 대상 artifact가 변경되었습니다")
    if live and not approval.external_transmission_authorized:
        raise PermissionError("live stage의 외부 전송이 승인되지 않았습니다")
    return approval


def _paired_results_match(
    baseline: list[CaseResultV3], candidate: list[CaseResultV3]
) -> bool:
    return [
        (item.sample_id, item.html_sha256, item.requested_model) for item in baseline
    ] == [
        (item.sample_id, item.html_sha256, item.requested_model) for item in candidate
    ]


def validate_agent_workflow(
    cases: list[EvaluationCaseV3],
    settings: OptimizationSettings,
    workflow_dir: str | Path,
    project_root: str | Path,
    config_path: str | Path,
    stage_run_id: str,
    *,
    target_provider: ModelProvider | None = None,
) -> StageRunManifestV3:
    root, workflow = Path(project_root).resolve(), Path(workflow_dir).resolve()
    workflow_manifest = load_agent_workflow_manifest(workflow)
    _assert_bindings(workflow_manifest, cases, settings, config_path, root)
    if workflow_manifest.phase != "awaiting_validation_approval":
        raise ValueError(f"Validation을 시작할 수 없는 phase입니다: {workflow_manifest.phase}")
    live = settings.target_provider.kind != "recorded"
    approval = _verified_approval(workflow, workflow_manifest, "validation", live=live)
    development_path = _stage_path(
        workflow, "development", workflow_manifest.development_stage_run_id or ""
    )
    candidate = (development_path / "candidate-prompt.md").read_text(encoding="utf-8")
    baseline = _baseline(settings, root)
    stage_path = _new_stage_path(workflow, "validation", stage_run_id)
    stage = _initial_stage_manifest(
        workflow_manifest,
        "validation",
        stage_run_id,
        workflow_manifest.development_stage_run_id,
        approval.subject_digest,
    )
    ledger = CallLedger(stage_path / "calls.jsonl", {"target": settings.target_limits})
    try:
        provider = target_provider or create_target_provider_v3(
            settings.target_provider, root
        )
        validation_cases = [case for case in cases if case.split == "validation"]
        baseline_results = _run_cases(
            validation_cases,
            output_path=stage_path / "baseline.jsonl",
            run_id=stage_run_id,
            prompt=baseline,
            prompt_variant="baseline",
            settings=settings,
            provider=provider,
            ledger=ledger,
            redact=True,
        )
        candidate_results = _run_cases(
            validation_cases,
            output_path=stage_path / "candidate.jsonl",
            run_id=stage_run_id,
            prompt=candidate,
            prompt_variant="candidate",
            settings=settings,
            provider=provider,
            ledger=ledger,
            redact=True,
        )
        selection = select_prompt(
            baseline,
            candidate,
            baseline_results,
            candidate_results,
            min_mean_improvement=settings.selection.min_mean_improvement,
        )
        if not _paired_results_match(baseline_results, candidate_results):
            selection = selection.model_copy(
                update={"selected": "none", "reason": "validation_inconclusive"}
            )
        _atomic_json(stage_path / "selection.json", selection)
        selected = selection.selected != "none"
        if selected:
            selected_prompt = candidate if selection.selected == "candidate" else baseline
            (stage_path / "selected-prompt.md").write_text(
                selected_prompt, encoding="utf-8"
            )
        stage = _finalize_stage(
            stage_path,
            stage,
            execution_status="complete",
            quality_status="pass" if selected else "inconclusive",
            error_code=None if selected else "validation_inconclusive",
        )
        updates = {
            "phase": "awaiting_test_approval" if selected else "validating",
            "execution_status": "complete",
            "quality_status": "pass" if selected else "inconclusive",
            "approval_status": "pending",
            "latest_stage": "validation",
            "latest_stage_run_id": stage_run_id,
            "validation_stage_run_id": stage_run_id,
            "active_validation_approval": None,
            "updated_at": _now(),
            "used_approval_ids": [
                *workflow_manifest.used_approval_ids,
                approval.approval_id,
            ],
        }
        if selected:
            updates.update(
                selected_prompt_sha256=_sha256_text(selected_prompt),
                selected_prompt_variant=selection.selected,
            )
        _save_manifest(workflow, workflow_manifest.model_copy(update=updates))
        return stage
    except Exception as exc:
        if not (stage_path / "stage-manifest.json").exists():
            _finalize_stage(
                stage_path,
                stage,
                execution_status="partial",
                quality_status="inconclusive",
                error_code=type(exc).__name__,
            )
        _save_manifest(
            workflow,
            workflow_manifest.model_copy(
                update={
                    "phase": "validating",
                    "execution_status": "partial",
                    "quality_status": "inconclusive",
                    "approval_status": "pending",
                    "latest_stage": "validation",
                    "latest_stage_run_id": stage_run_id,
                    "validation_stage_run_id": stage_run_id,
                    "active_validation_approval": None,
                    "used_approval_ids": [
                        *workflow_manifest.used_approval_ids,
                        approval.approval_id,
                    ],
                    "updated_at": _now(),
                }
            ),
        )
        raise


def _claim_test_exposure(
    path: Path,
    exposure: TestExposureV3,
    allowed_reexposure: set[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        previous = [
            TestExposureV3.model_validate_json(line) for line in handle if line.strip()
        ]
        duplicate = any(
            item.test_campaign_id == exposure.test_campaign_id
            and item.stage_run_id == exposure.stage_run_id
            and item.sample_id == exposure.sample_id
            and item.attempt == exposure.attempt
            for item in previous
        )
        if duplicate:
            raise ValueError("동일한 Test exposure를 중복 기록할 수 없습니다")
        prior_campaign = any(
            item.sample_id == exposure.sample_id
            and (
                item.test_campaign_id != exposure.test_campaign_id
                or item.stage_run_id != exposure.stage_run_id
            )
            for item in previous
        )
        if prior_campaign and exposure.sample_id not in allowed_reexposure:
            raise PermissionError(
                f"승인되지 않은 Test case 재노출입니다: {exposure.sample_id}"
            )
        handle.seek(0, os.SEEK_END)
        handle.write(exposure.model_dump_json() + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def run_agent_test(
    cases: list[EvaluationCaseV3],
    settings: OptimizationSettings,
    workflow_dir: str | Path,
    project_root: str | Path,
    config_path: str | Path,
    stage_run_id: str,
    *,
    test_campaign_id: str | None = None,
    target_provider: ModelProvider | None = None,
) -> StageRunManifestV3:
    root, workflow = Path(project_root).resolve(), Path(workflow_dir).resolve()
    workflow_manifest = load_agent_workflow_manifest(workflow)
    _assert_bindings(workflow_manifest, cases, settings, config_path, root)
    if workflow_manifest.phase != "awaiting_test_approval":
        raise ValueError(f"Test를 시작할 수 없는 phase입니다: {workflow_manifest.phase}")
    live = settings.target_provider.kind != "recorded"
    approval = _verified_approval(workflow, workflow_manifest, "test", live=live)
    campaign_id = test_campaign_id or str(uuid.uuid4())
    if not _SAFE_ID.fullmatch(campaign_id):
        raise ValueError("test_campaign_id 형식이 올바르지 않습니다")
    validation_path = _stage_path(
        workflow, "validation", workflow_manifest.validation_stage_run_id or ""
    )
    selected_prompt = (validation_path / "selected-prompt.md").read_text(encoding="utf-8")
    if _sha256_text(selected_prompt) != workflow_manifest.selected_prompt_sha256:
        raise ValueError("선택 prompt hash가 manifest와 다릅니다")
    stage_path = _new_stage_path(workflow, "test", stage_run_id)
    stage = _initial_stage_manifest(
        workflow_manifest,
        "test",
        stage_run_id,
        workflow_manifest.test_stage_run_id or workflow_manifest.validation_stage_run_id,
        approval.subject_digest,
    )
    ledger = CallLedger(stage_path / "calls.jsonl", {"target": settings.target_limits})
    allowed = set(approval.allowed_reexposure_case_ids)

    def before_attempt(sample_id: str, attempt: int) -> None:
        _claim_test_exposure(
            workflow / "test-exposure.jsonl",
            TestExposureV3(
                workflow_id=workflow_manifest.workflow_id,
                test_campaign_id=campaign_id,
                stage_run_id=stage_run_id,
                sample_id=sample_id,
                attempt=attempt,
                approval_id=approval.approval_id,
                exposed_at=_now(),
            ),
            allowed,
        )

    try:
        provider = target_provider or create_target_provider_v3(
            settings.target_provider, root
        )
        test_cases = [case for case in cases if case.split == "test"]
        results = _run_cases(
            test_cases,
            output_path=stage_path / "test.jsonl",
            run_id=stage_run_id,
            prompt=selected_prompt,
            prompt_variant="selected",
            settings=settings,
            provider=provider,
            ledger=ledger,
            redact=True,
            before_attempt=before_attempt,
        )
        has_errors = any(item.status in _TECHNICAL_STATUSES for item in results)
        quality = (
            "inconclusive"
            if has_errors
            else "pass"
            if all(item.score.strict_pass for item in results)
            else "fail"
        )
        summary = {
            "schema_version": 3,
            "workflow_id": workflow_manifest.workflow_id,
            "test_campaign_id": campaign_id,
            "case_count": len(results),
            "strict_pass_count": sum(item.score.strict_pass for item in results),
            "error_count": sum(item.status in _TECHNICAL_STATUSES for item in results),
            "quality_status": quality,
            "expected_in_artifacts": False,
        }
        _atomic_json(stage_path / "summary.json", summary)
        stage = _finalize_stage(
            stage_path,
            stage,
            execution_status="complete",
            quality_status=quality,
            error_code="test_technical_error" if has_errors else None,
        )
        _save_manifest(
            workflow,
            workflow_manifest.model_copy(
                update={
                    "phase": "reporting",
                    "execution_status": "complete",
                    "quality_status": quality,
                    "approval_status": "approved",
                    "latest_stage": "test",
                    "latest_stage_run_id": stage_run_id,
                    "test_stage_run_id": stage_run_id,
                    "active_test_approval": None,
                    "test_campaign_id": campaign_id,
                    "used_approval_ids": [
                        *workflow_manifest.used_approval_ids,
                        approval.approval_id,
                    ],
                    "updated_at": _now(),
                }
            ),
        )
        return stage
    except Exception as exc:
        if not (stage_path / "stage-manifest.json").exists():
            _finalize_stage(
                stage_path,
                stage,
                execution_status="partial",
                quality_status="inconclusive",
                error_code=type(exc).__name__,
            )
        _save_manifest(
            workflow,
            workflow_manifest.model_copy(
                update={
                    "phase": "awaiting_test_approval",
                    "execution_status": "partial",
                    "quality_status": "inconclusive",
                    "approval_status": "pending",
                    "latest_stage": "test",
                    "latest_stage_run_id": stage_run_id,
                    "test_stage_run_id": stage_run_id,
                    "active_test_approval": None,
                    "used_approval_ids": [
                        *workflow_manifest.used_approval_ids,
                        approval.approval_id,
                    ],
                    "updated_at": _now(),
                }
            ),
        )
        raise
