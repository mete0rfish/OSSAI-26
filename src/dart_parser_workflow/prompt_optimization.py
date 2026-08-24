"""development/validation/test를 분리한 v3 프롬프트 최적화 실행."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean

from .config import OptimizationSettings
from .dataset import dataset_sha256
from .evaluation import normalize_scalar, score_answer_v3
from .execution import BudgetExceeded, CallLedger
from .html_utils import read_html, sha256_file
from .prompts import load_prompt, render_prompt, validate_prompt_template
from .providers import (
    ModelProvider,
    OptimizerProvider,
    create_optimizer_provider_v3,
    create_target_provider_v3,
)
from .schemas import (
    CaseResultV3,
    EvaluationCaseV3,
    GenerationRequest,
    ModelUsage,
    OptimizationRequest,
    ScoreBreakdown,
    SelectionSummary,
)


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
) -> CaseResultV3:
    return CaseResultV3(
        run_id=run_id,
        sample_id=case.id,
        family_id=case.family_id,
        split=case.split,
        prompt_variant=prompt_variant,
        html_path=str(case.html_path),
        html_sha256=case.html_sha256,
        question=case.question,
        expected=case.expected,
        answerable=not case.expected.abstained,
        score=ScoreBreakdown(quality_score=0, failure_reasons=[status]),
        status=status,
        error=error,
        prompt_sha256=prompt_sha256,
        requested_model=model,
    )


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
) -> CaseResultV3:
    template_hash = _sha256_text(prompt_template)
    try:
        _, html = read_html(case.html_path, max_html_bytes)
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
    prompt = render_prompt(prompt_template, case.question, html)
    ledger.before_request("target")
    try:
        response = provider.generate(
            GenerationRequest(
                sample_id=case.id,
                prompt=prompt,
                provider_role="target",
                prompt_variant=prompt_variant,
            )
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:2000]}"
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
            error=error,
        )
        return _error_result(
            case,
            run_id=run_id,
            prompt_variant=prompt_variant,
            prompt_sha256=template_hash,
            model=requested_model,
            status="generation_error",
            error=error,
        )
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
    )
    answer = response.result
    score, status = score_answer_v3(case, answer, html)
    return CaseResultV3(
        run_id=run_id,
        sample_id=case.id,
        family_id=case.family_id,
        split=case.split,
        prompt_variant=prompt_variant,
        html_path=str(case.html_path),
        html_sha256=case.html_sha256,
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
        requested_model=response.requested_model,
        actual_model=response.actual_model,
        latency_seconds=response.latency_seconds,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
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
    if optimizer_error:
        return SelectionSummary(selected="baseline", reason="optimizer_error", **common)
    if candidate_prompt == baseline_prompt:
        return SelectionSummary(selected="baseline", reason="candidate_identical", **common)
    assert candidate is not None
    if candidate["error_count"] > baseline["error_count"]:
        reason = "validation_errors_increased"
    elif candidate["answerable_abstentions"] > baseline["answerable_abstentions"]:
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
        {
            "sample_id": item.sample_id,
            "question": item.question,
            "expected": item.expected.model_dump(mode="json"),
            "answer": item.answer,
            "evidence": [e.quote for e in item.evidence],
            "quality_score": item.score.quality_score,
            "failure_reasons": item.score.failure_reasons,
            "missing_context": item.score.missing_context,
        }
        for item in development_failures
    ]
    return (
        "아래 DART 질의응답 baseline을 development 실패만 참고해 개선하세요. "
        "validation/test를 추측하거나 기대 답을 prompt에 넣지 마세요. "
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
) -> list[CaseResultV3]:
    results: list[CaseResultV3] = []
    for case in cases:
        result = run_case_v3(
            case,
            run_id=run_id,
            prompt_template=prompt,
            prompt_variant=prompt_variant,
            max_html_bytes=settings.workflow.max_html_bytes,
            provider=provider,
            requested_model=settings.target_provider.model,
            ledger=ledger,
        )
        results.append(result)
        _append_jsonl(output_path, result.model_dump(mode="json"))
    return results


def run_prompt_optimization(
    cases: list[EvaluationCaseV3],
    settings: OptimizationSettings,
    output_dir: str | Path,
    project_root: str | Path,
    *,
    target_provider: ModelProvider | None = None,
    optimizer_provider: OptimizerProvider | None = None,
) -> dict:
    root, output = Path(project_root).resolve(), Path(output_dir).resolve()
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
        failures = [item for item in development if not item.score.strict_pass]
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
