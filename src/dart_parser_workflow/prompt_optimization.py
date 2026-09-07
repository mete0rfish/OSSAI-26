"""development/validation/test를 분리한 v3 프롬프트 최적화 실행."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean

from .config import OptimizationSettings, ProviderSettings, RetrySettings, WorkflowSettings
from .dataset import dataset_sha256
from .evaluation import normalize_scalar, score_answer_v3
from .execution import BudgetExceeded, CallLedger, classify_provider_error
from .html_utils import PreparedHtml, prepare_html, sha256_file
from .prompts import load_prompt, render_batch_prompt, render_prompt, validate_prompt_template
from .providers import (
    ModelProvider,
    OptimizerProvider,
    create_optimizer_provider_v3,
    create_target_provider_v3,
)
from .schemas import (
    BatchDisclosureAnswer,
    BatchGenerationRequest,
    CaseResultV3,
    DevelopmentFailureV3,
    EvaluationCaseV3,
    GenerationRequest,
    ModelUsage,
    OptimizationRequest,
    ScoreBreakdown,
    SelectionSummary,
)


class _SelectionInconclusive(RuntimeError):
    """Stop before Test without converting an inconclusive selection to a partial run."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _append_jsonl(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def _git_identity(project_root: Path) -> tuple[str | None, bool | None]:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return sha, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _error_result(
    case: EvaluationCaseV3,
    *,
    run_id: str,
    prompt_variant: str,
    prompt_sha256: str,
    model: str,
    status: str,
    error: str,
    prepared: PreparedHtml | None = None,
) -> CaseResultV3:
    return CaseResultV3(
        run_id=run_id,
        sample_id=case.id,
        family_id=case.family_id,
        split=case.split,
        prompt_variant=prompt_variant,
        html_path=str(case.html_path),
        html_sha256=case.html_sha256,
        html_preprocessor=prepared.preprocessor if prepared else "raw",
        prepared_html_sha256=prepared.prepared_sha256 if prepared else None,
        raw_html_bytes=prepared.raw_bytes if prepared else None,
        prepared_html_bytes=prepared.prepared_bytes if prepared else None,
        question=case.question,
        expected=case.expected,
        answerable=not case.expected.abstained,
        score=ScoreBreakdown(quality_score=0, failure_reasons=[status]),
        status=status,
        error=error,
        prompt_sha256=prompt_sha256,
        requested_model=model,
    )


def _estimated_input_tokens(prompt: str, workflow: WorkflowSettings) -> int:
    return math.ceil(len(prompt.encode()) / workflow.estimated_bytes_per_token)


def _context_error(
    prompt: str,
    workflow: WorkflowSettings,
    provider: ProviderSettings | None,
) -> str | None:
    if provider is None or provider.context_window_tokens is None:
        return None
    estimated = _estimated_input_tokens(prompt, workflow)
    reserved = provider.max_output_tokens
    if estimated + reserved <= provider.context_window_tokens:
        return None
    return (
        "input_context_exceeded: "
        f"estimated_input_tokens={estimated}, reserved_output_tokens={reserved}, "
        f"context_window_tokens={provider.context_window_tokens}"
    )


def _case_result(
    case: EvaluationCaseV3,
    *,
    run_id: str,
    prompt_variant: str,
    template_hash: str,
    prepared: PreparedHtml,
    answer: BatchDisclosureAnswer,
    requested_model: str,
    actual_model: str | None,
    latency_seconds: float,
    input_tokens: int | None,
    output_tokens: int | None,
) -> CaseResultV3:
    score, status = score_answer_v3(case, answer, prepared.raw_html)
    return CaseResultV3(
        run_id=run_id,
        sample_id=case.id,
        family_id=case.family_id,
        split=case.split,
        prompt_variant=prompt_variant,
        html_path=str(case.html_path),
        html_sha256=case.html_sha256,
        html_preprocessor=prepared.preprocessor,
        prepared_html_sha256=prepared.prepared_sha256,
        raw_html_bytes=prepared.raw_bytes,
        prepared_html_bytes=prepared.prepared_bytes,
        question=case.question,
        expected=case.expected,
        answerable=not case.expected.abstained,
        answer=answer.answer,
        evidence=answer.evidence,
        confidence=answer.confidence,
        abstained=answer.abstained,
        abstention_reason=answer.abstention_reason,
        normalized_answer=normalize_scalar(answer.answer),
        score=score,
        status=status,
        prompt_sha256=template_hash,
        requested_model=requested_model,
        actual_model=actual_model,
        latency_seconds=latency_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _usage_share(value: int | None, index: int, count: int) -> int | None:
    if value is None:
        return None
    quotient, remainder = divmod(value, count)
    return quotient + int(index < remainder)


def run_case_v3(
    case: EvaluationCaseV3,
    *,
    run_id: str,
    prompt_template: str,
    prompt_variant: str,
    max_html_bytes: int,
    provider: ModelProvider,
    requested_model: str,
    ledger: CallLedger,
    retry: RetrySettings | None = None,
    before_attempt: Callable[[str, int], None] | None = None,
    workflow: WorkflowSettings | None = None,
    provider_settings: ProviderSettings | None = None,
) -> CaseResultV3:
    template_hash = _sha256_text(prompt_template)
    workflow = workflow or WorkflowSettings(max_html_bytes=max_html_bytes)
    try:
        prepared = prepare_html(
            case.html_path,
            max_html_bytes,
            workflow.html_preprocessing,
        )
    except ValueError as exc:
        return _error_result(
            case,
            run_id=run_id,
            prompt_variant=prompt_variant,
            prompt_sha256=template_hash,
            model=requested_model,
            status="input_error",
            error=str(exc),
        )
    prompt = render_prompt(prompt_template, case.question, prepared.model_input)
    if error := _context_error(prompt, workflow, provider_settings):
        return _error_result(
            case,
            run_id=run_id,
            prompt_variant=prompt_variant,
            prompt_sha256=template_hash,
            model=requested_model,
            status="input_error",
            error=error,
            prepared=prepared,
        )
    retry_policy = retry or RetrySettings()
    for attempt in range(retry_policy.max_attempts_per_call):
        ledger.before_request("target")
        if before_attempt is not None:
            before_attempt(case.id, attempt)
        try:
            response = provider.generate(
                GenerationRequest(
                    sample_id=case.id,
                    attempt=attempt,
                    prompt=prompt,
                    provider_role="target",
                    prompt_variant=prompt_variant,
                )
            )
        except Exception as exc:
            classified = classify_provider_error(exc, retry_policy)
            ledger.record(
                role="target",
                sample_id=case.id,
                prompt_variant=prompt_variant,
                prompt=prompt,
                requested_model=requested_model,
                actual_model=None,
                usage=ModelUsage(),
                latency_seconds=None,
                html_sha256=case.html_sha256,
                html_preprocessor=prepared.preprocessor,
                prepared_html_sha256=prepared.prepared_sha256,
                raw_html_bytes=prepared.raw_bytes,
                prepared_html_bytes=prepared.prepared_bytes,
                estimated_input_tokens=_estimated_input_tokens(prompt, workflow),
                attempt=attempt,
                error=classified.summary(),
            )
            if classified.retryable and attempt + 1 < retry_policy.max_attempts_per_call:
                delay = retry_policy.initial_backoff_seconds * (2**attempt)
                if delay:
                    time.sleep(delay)
                continue
            return _error_result(
                case,
                run_id=run_id,
                prompt_variant=prompt_variant,
                prompt_sha256=template_hash,
                model=requested_model,
                status="generation_error",
                error=classified.summary(),
                prepared=prepared,
            )
        break
    else:  # pragma: no cover - the validated retry count is always positive
        raise AssertionError("retry loop가 실행되지 않았습니다")
    ledger.record(
        role="target",
        sample_id=case.id,
        prompt_variant=prompt_variant,
        prompt=prompt,
        requested_model=response.requested_model,
        actual_model=response.actual_model,
        usage=response.usage,
        latency_seconds=response.latency_seconds,
        html_sha256=case.html_sha256,
        html_preprocessor=prepared.preprocessor,
        prepared_html_sha256=prepared.prepared_sha256,
        raw_html_bytes=prepared.raw_bytes,
        prepared_html_bytes=prepared.prepared_bytes,
        estimated_input_tokens=_estimated_input_tokens(prompt, workflow),
        attempt=attempt,
    )
    answer = BatchDisclosureAnswer(
        sample_id=case.id,
        **response.result.model_dump(),
    )
    return _case_result(
        case,
        run_id=run_id,
        prompt_variant=prompt_variant,
        template_hash=template_hash,
        prepared=prepared,
        answer=answer,
        requested_model=response.requested_model,
        actual_model=response.actual_model,
        latency_seconds=response.latency_seconds,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def _run_batch_v3(
    cases: list[EvaluationCaseV3],
    *,
    run_id: str,
    prompt_template: str,
    prompt_variant: str,
    workflow: WorkflowSettings,
    provider: ModelProvider,
    provider_settings: ProviderSettings,
    requested_model: str,
    ledger: CallLedger,
    retry: RetrySettings,
    before_attempt: Callable[[str, int], None] | None,
) -> list[CaseResultV3]:
    template_hash = _sha256_text(prompt_template)
    try:
        prepared = prepare_html(
            cases[0].html_path,
            workflow.max_html_bytes,
            workflow.html_preprocessing,
        )
    except ValueError as exc:
        return [
            _error_result(
                case,
                run_id=run_id,
                prompt_variant=prompt_variant,
                prompt_sha256=template_hash,
                model=requested_model,
                status="input_error",
                error=str(exc),
            )
            for case in cases
        ]
    questions = [(case.id, case.question) for case in cases]
    prompt = render_batch_prompt(prompt_template, questions, prepared.model_input)
    if error := _context_error(prompt, workflow, provider_settings):
        return [
            _error_result(
                case,
                run_id=run_id,
                prompt_variant=prompt_variant,
                prompt_sha256=template_hash,
                model=requested_model,
                status="input_error",
                error=error,
                prepared=prepared,
            )
            for case in cases
        ]
    sample_ids = [case.id for case in cases]
    batch_id = "batch:" + ",".join(sample_ids)
    generate_batch = provider.generate_batch  # type: ignore[attr-defined]
    for attempt in range(retry.max_attempts_per_call):
        ledger.before_request("target")
        if before_attempt is not None:
            for sample_id in sample_ids:
                before_attempt(sample_id, attempt)
        try:
            response = generate_batch(
                BatchGenerationRequest(
                    sample_ids=sample_ids,
                    attempt=attempt,
                    prompt=prompt,
                    provider_role="target",
                    prompt_variant=prompt_variant,
                )
            )
            returned_ids = [answer.sample_id for answer in response.result.answers]
            if returned_ids != sample_ids:
                raise ValueError(
                    "batch 응답 sample_id 또는 순서가 요청과 일치하지 않습니다"
                )
        except Exception as exc:
            classified = classify_provider_error(exc, retry)
            ledger.record(
                role="target",
                sample_id=batch_id,
                prompt_variant=prompt_variant,
                prompt=prompt,
                requested_model=requested_model,
                actual_model=None,
                usage=ModelUsage(),
                latency_seconds=None,
                html_sha256=cases[0].html_sha256,
                html_preprocessor=prepared.preprocessor,
                prepared_html_sha256=prepared.prepared_sha256,
                raw_html_bytes=prepared.raw_bytes,
                prepared_html_bytes=prepared.prepared_bytes,
                estimated_input_tokens=_estimated_input_tokens(prompt, workflow),
                batch_size=len(cases),
                attempt=attempt,
                error=classified.summary(),
            )
            if classified.retryable and attempt + 1 < retry.max_attempts_per_call:
                delay = retry.initial_backoff_seconds * (2**attempt)
                if delay:
                    time.sleep(delay)
                continue
            return [
                _error_result(
                    case,
                    run_id=run_id,
                    prompt_variant=prompt_variant,
                    prompt_sha256=template_hash,
                    model=requested_model,
                    status="generation_error",
                    error=classified.summary(),
                    prepared=prepared,
                )
                for case in cases
            ]
        break
    else:  # pragma: no cover - retry count is validated as positive
        raise AssertionError("retry loop가 실행되지 않았습니다")
    ledger.record(
        role="target",
        sample_id=batch_id,
        prompt_variant=prompt_variant,
        prompt=prompt,
        requested_model=response.requested_model,
        actual_model=response.actual_model,
        usage=response.usage,
        latency_seconds=response.latency_seconds,
        html_sha256=cases[0].html_sha256,
        html_preprocessor=prepared.preprocessor,
        prepared_html_sha256=prepared.prepared_sha256,
        raw_html_bytes=prepared.raw_bytes,
        prepared_html_bytes=prepared.prepared_bytes,
        estimated_input_tokens=_estimated_input_tokens(prompt, workflow),
        batch_size=len(cases),
        attempt=attempt,
    )
    return [
        _case_result(
            case,
            run_id=run_id,
            prompt_variant=prompt_variant,
            template_hash=template_hash,
            prepared=prepared,
            answer=answer,
            requested_model=response.requested_model,
            actual_model=response.actual_model,
            latency_seconds=response.latency_seconds,
            input_tokens=_usage_share(response.usage.input_tokens, index, len(cases)),
            output_tokens=_usage_share(response.usage.output_tokens, index, len(cases)),
        )
        for index, (case, answer) in enumerate(
            zip(cases, response.result.answers, strict=True)
        )
    ]


def iter_cases_v3(
    cases: list[EvaluationCaseV3],
    *,
    run_id: str,
    prompt_template: str,
    prompt_variant: str,
    workflow: WorkflowSettings,
    provider: ModelProvider,
    provider_settings: ProviderSettings,
    requested_model: str,
    ledger: CallLedger,
    retry: RetrySettings,
    before_attempt: Callable[[str, int], None] | None = None,
) -> Iterator[CaseResultV3]:
    """split 경계를 지키며 같은 HTML의 질문을 한 provider 호출로 묶는다."""

    grouped: dict[tuple[str, str], list[EvaluationCaseV3]] = {}
    for case in cases:
        grouped.setdefault((case.split, case.html_sha256), []).append(case)
    for grouped_cases in grouped.values():
        can_batch = (
            workflow.batch_questions_by_html
            and len(grouped_cases) > 1
            and callable(getattr(provider, "generate_batch", None))
        )
        if can_batch:
            batch_results = _run_batch_v3(
                grouped_cases,
                run_id=run_id,
                prompt_template=prompt_template,
                prompt_variant=prompt_variant,
                workflow=workflow,
                provider=provider,
                provider_settings=provider_settings,
                requested_model=requested_model,
                ledger=ledger,
                retry=retry,
                before_attempt=before_attempt,
            )
        else:
            batch_results = [
                run_case_v3(
                    case,
                    run_id=run_id,
                    prompt_template=prompt_template,
                    prompt_variant=prompt_variant,
                    max_html_bytes=workflow.max_html_bytes,
                    provider=provider,
                    requested_model=requested_model,
                    ledger=ledger,
                    retry=retry,
                    before_attempt=before_attempt,
                    workflow=workflow,
                    provider_settings=provider_settings,
                )
                for case in grouped_cases
            ]
        yield from batch_results


def run_cases_v3(
    cases: list[EvaluationCaseV3],
    *,
    run_id: str,
    prompt_template: str,
    prompt_variant: str,
    workflow: WorkflowSettings,
    provider: ModelProvider,
    provider_settings: ProviderSettings,
    requested_model: str,
    ledger: CallLedger,
    retry: RetrySettings,
    before_attempt: Callable[[str, int], None] | None = None,
) -> list[CaseResultV3]:
    return list(
        iter_cases_v3(
            cases,
            run_id=run_id,
            prompt_template=prompt_template,
            prompt_variant=prompt_variant,
            workflow=workflow,
            provider=provider,
            provider_settings=provider_settings,
            requested_model=requested_model,
            ledger=ledger,
            retry=retry,
            before_attempt=before_attempt,
        )
    )


def _aggregate(results: list[CaseResultV3]) -> dict[str, float | int]:
    total = len(results)
    return {
        "mean": fmean(item.score.quality_score for item in results) if results else 0.0,
        "strict_pass_rate": (
            sum(item.score.strict_pass for item in results) / total if total else 0.0
        ),
        "error_count": sum(
            item.status in {"input_error", "generation_error"} for item in results
        ),
        "answerable_abstentions": sum(
            item.answerable and item.abstained for item in results
        ),
    }


def select_prompt(
    baseline_prompt: str,
    candidate_prompt: str,
    baseline_results: list[CaseResultV3],
    candidate_results: list[CaseResultV3],
    *,
    min_mean_improvement: float,
    optimizer_error: bool = False,
) -> SelectionSummary:
    baseline = _aggregate(baseline_results)
    candidate = _aggregate(candidate_results) if candidate_results else None
    common = {
        "baseline_mean": float(baseline["mean"]),
        "baseline_strict_pass_rate": float(baseline["strict_pass_rate"]),
        "baseline_error_count": int(baseline["error_count"]),
        "baseline_answerable_abstentions": int(baseline["answerable_abstentions"]),
        "candidate_mean": float(candidate["mean"]) if candidate else None,
        "candidate_strict_pass_rate": (
            float(candidate["strict_pass_rate"]) if candidate else None
        ),
        "candidate_error_count": int(candidate["error_count"]) if candidate else None,
        "candidate_answerable_abstentions": (
            int(candidate["answerable_abstentions"]) if candidate else None
        ),
    }
    if baseline["error_count"] or (candidate and candidate["error_count"]):
        return SelectionSummary(selected="none", reason="validation_inconclusive", **common)
    if optimizer_error:
        return SelectionSummary(selected="baseline", reason="optimizer_error", **common)
    if candidate_prompt == baseline_prompt:
        return SelectionSummary(selected="baseline", reason="candidate_identical", **common)
    assert candidate is not None
    if candidate["answerable_abstentions"] > baseline["answerable_abstentions"]:
        reason = "answerable_abstentions_increased"
    elif candidate["strict_pass_rate"] < baseline["strict_pass_rate"]:
        reason = "strict_pass_rate_decreased"
    elif candidate["mean"] >= baseline["mean"] + min_mean_improvement:
        return SelectionSummary(selected="candidate", reason="validation_improved", **common)
    else:
        reason = "validation_not_improved"
    return SelectionSummary(selected="baseline", reason=reason, **common)


def build_optimizer_prompt(
    baseline_prompt: str, development_failures: list[CaseResultV3]
) -> str:
    rows = [
        DevelopmentFailureV3(
            sample_id=item.sample_id,
            question=item.question,
            expected=item.expected,
            answer=item.answer,
            evidence=[e.quote for e in item.evidence],
            quality_score=item.score.quality_score,
            failure_reasons=item.score.failure_reasons,
            missing_context=item.score.missing_context,
        ).model_dump(mode="json")
        for item in development_failures
    ]
    return (
        "아래 DART 질의응답 baseline을 development 실패만 참고해 개선하세요. "
        "validation/test를 추측하거나 기대 답을 prompt에 넣지 마세요. "
        "사용자가 제공한 질문을 요약·교정·보완·번역·재작성하지 않고 수정 없이 그대로 "
        "사용하라는 지침을 반드시 보존하세요. "
        "{question}과 {html} placeholder를 정확히 한 번씩 보존하고 JSON 객체로 응답하세요.\n\n"
        f"[baseline]\n{baseline_prompt}\n\n"
        "[development failures]\n"
        + json.dumps(rows, ensure_ascii=False, sort_keys=True)
    )


def _run_split(
    cases: list[EvaluationCaseV3],
    *,
    output_path: Path,
    run_id: str,
    prompt: str,
    prompt_variant: str,
    settings: OptimizationSettings,
    provider: ModelProvider,
    ledger: CallLedger,
    redact_expected: bool = False,
) -> list[CaseResultV3]:
    results = []
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
    )
    for result in iterator:
        results.append(result)
        artifact = result.model_dump(mode="json")
        if redact_expected:
            artifact.pop("expected")
        _append_jsonl(output_path, artifact)
    return results


def run_prompt_optimization(
    cases: list[EvaluationCaseV3],
    settings: OptimizationSettings,
    output_dir: str | Path,
    project_root: str | Path,
    *,
    target_provider: ModelProvider | None = None,
    optimizer_provider: OptimizerProvider | None = None,
    authorize_external_transmission: bool = False,
) -> dict:
    root, output = Path(project_root).resolve(), Path(output_dir).resolve()
    if (
        any(
            provider.kind != "recorded"
            for provider in (settings.target_provider, settings.optimizer_provider)
        )
        and not authorize_external_transmission
    ):
        raise PermissionError("live 최적화에는 명시적 외부 전송 승인이 필요합니다")
    baseline_path = Path(settings.baseline_prompt)
    if not baseline_path.is_absolute():
        baseline_path = root / baseline_path
    baseline = load_prompt(baseline_path)
    dataset_hash = dataset_sha256(cases, root)
    splits = {
        name: [case for case in cases if case.split == name]
        for name in ("development", "validation", "test")
    }
    if any(not values for values in splits.values()):
        raise ValueError("development/validation/test split은 모두 비어 있지 않아야 합니다")
    output.mkdir(parents=True, exist_ok=False)
    run_id = output.name
    started_at = datetime.now(UTC)
    git_sha, git_dirty = _git_identity(root)
    summary: dict = {
        "schema_version": 3,
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "observed_status": "partial",
        "quality_status": "inconclusive",
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "dataset_sha256": dataset_hash,
        "split_sample_ids": {name: [case.id for case in rows] for name, rows in splits.items()},
        "html_sha256": {case.id: case.html_sha256 for case in cases},
        "baseline_prompt_sha256": _sha256_text(baseline),
        "candidate_prompt_sha256": None,
        "selected_prompt_sha256": None,
        "scorer_sha256": sha256_file(Path(__file__).with_name("evaluation.py")),
        "input_preparation": settings.workflow.model_dump(mode="json"),
        "test_used_for_generation_or_selection": False,
        "selection": None,
        "provider_usage": {},
        "error": None,
    }
    _atomic_json(output / "summary.json", summary)
    ledger = CallLedger(
        output / "calls.jsonl",
        {"target": settings.target_limits, "optimizer": settings.optimizer_limits},
    )
    try:
        active_target = target_provider or create_target_provider_v3(
            settings.target_provider, root
        )
        active_optimizer = optimizer_provider or create_optimizer_provider_v3(
            settings.optimizer_provider, root
        )
    except Exception as exc:
        summary.update(
            observed_status="not_run",
            finished_at=datetime.now(UTC).isoformat(),
            error=f"{type(exc).__name__}: {exc}",
        )
        _atomic_json(output / "summary.json", summary)
        return summary

    try:
        development = _run_split(
            splits["development"],
            output_path=output / "development.jsonl",
            run_id=run_id,
            prompt=baseline,
            prompt_variant="baseline",
            settings=settings,
            provider=active_target,
            ledger=ledger,
        )
        failures = [
            item
            for item in development
            if not item.score.strict_pass
            and item.status not in {"input_error", "generation_error"}
        ]
        optimizer_failed = False
        candidate = baseline
        if failures:
            optimizer_prompt = build_optimizer_prompt(baseline, failures)
            ledger.before_request("optimizer")
            response = None
            try:
                response = active_optimizer.propose(
                    OptimizationRequest(prompt=optimizer_prompt)
                )
                candidate = response.result.prompt
                validate_prompt_template(candidate)
            except BudgetExceeded:
                raise
            except Exception as exc:
                optimizer_failed = True
                ledger.record(
                    role="optimizer",
                    sample_id="prompt-candidate",
                    prompt_variant="optimizer",
                    prompt=optimizer_prompt,
                    requested_model=(
                        response.requested_model
                        if response is not None
                        else settings.optimizer_provider.model
                    ),
                    actual_model=response.actual_model if response is not None else None,
                    usage=response.usage if response is not None else ModelUsage(),
                    latency_seconds=(
                        response.latency_seconds if response is not None else None
                    ),
                    error=f"{type(exc).__name__}: {str(exc)[:2000]}",
                )
            else:
                ledger.record(
                    role="optimizer",
                    sample_id="prompt-candidate",
                    prompt_variant="optimizer",
                    prompt=optimizer_prompt,
                    requested_model=response.requested_model,
                    actual_model=response.actual_model,
                    usage=response.usage,
                    latency_seconds=response.latency_seconds,
                )
        (output / "candidate-prompt.md").write_text(candidate, encoding="utf-8")
        baseline_validation = _run_split(
            splits["validation"],
            output_path=output / "validation.jsonl",
            run_id=run_id,
            prompt=baseline,
            prompt_variant="baseline",
            settings=settings,
            provider=active_target,
            ledger=ledger,
        )
        candidate_validation: list[CaseResultV3] = []
        if candidate != baseline and not optimizer_failed:
            candidate_validation = _run_split(
                splits["validation"],
                output_path=output / "validation.jsonl",
                run_id=run_id,
                prompt=candidate,
                prompt_variant="candidate",
                settings=settings,
                provider=active_target,
                ledger=ledger,
            )
        selection = select_prompt(
            baseline,
            candidate,
            baseline_validation,
            candidate_validation,
            min_mean_improvement=settings.selection.min_mean_improvement,
            optimizer_error=optimizer_failed,
        )
        if selection.selected == "none":
            summary.update(
                observed_status="complete",
                quality_status="inconclusive",
                finished_at=datetime.now(UTC).isoformat(),
                candidate_prompt_sha256=_sha256_text(candidate),
                selection=selection.model_dump(mode="json"),
                provider_usage={
                    "target": ledger.role_summary(
                        "target", settings.target_provider.model
                    ),
                    "optimizer": ledger.role_summary(
                        "optimizer", settings.optimizer_provider.model
                    ),
                },
            )
            raise _SelectionInconclusive
        selected_prompt = candidate if selection.selected == "candidate" else baseline
        (output / "selected-prompt.md").write_text(selected_prompt, encoding="utf-8")
        test_results = _run_split(
            splits["test"],
            output_path=output / "test.jsonl",
            run_id=run_id,
            prompt=selected_prompt,
            prompt_variant="selected",
            settings=settings,
            provider=active_target,
            ledger=ledger,
            redact_expected=True,
        )
        ledger.assert_within_limits("target")
        ledger.assert_within_limits("optimizer")
        summary.update(
            observed_status="complete",
            quality_status=(
                "pass" if all(item.score.strict_pass for item in test_results) else "fail"
            ),
            finished_at=datetime.now(UTC).isoformat(),
            candidate_prompt_sha256=_sha256_text(candidate),
            selected_prompt_sha256=_sha256_text(selected_prompt),
            selection=selection.model_dump(mode="json"),
            provider_usage={
                "target": ledger.role_summary(
                    "target", settings.target_provider.model
                ),
                "optimizer": ledger.role_summary(
                    "optimizer", settings.optimizer_provider.model
                ),
            },
        )
    except _SelectionInconclusive:
        pass
    except Exception as exc:
        summary.update(
            observed_status="partial",
            quality_status="inconclusive",
            finished_at=datetime.now(UTC).isoformat(),
            error=f"{type(exc).__name__}: {str(exc)[:2000]}",
            provider_usage={
                "target": ledger.role_summary(
                    "target", settings.target_provider.model
                ),
                "optimizer": ledger.role_summary(
                    "optimizer", settings.optimizer_provider.model
                ),
            },
        )
    artifact_names = [
        "calls.jsonl",
        "development.jsonl",
        "candidate-prompt.md",
        "validation.jsonl",
        "selected-prompt.md",
        "test.jsonl",
    ]
    summary["artifact_sha256"] = {
        name: sha256_file(output / name)
        for name in artifact_names
        if (output / name).exists()
    }
    _atomic_json(output / "summary.json", summary)
    return summary
