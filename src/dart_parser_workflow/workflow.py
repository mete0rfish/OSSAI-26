"""DART 공시 HTML 질의응답과 근거 검증을 연결한다."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from bs4 import UnicodeDammit

from .config import AppSettings
from .evaluation import normalize_scalar, validate_evidence
from .prompts import question_answer_prompt
from .providers import ModelProvider, create_provider
from .schemas import CaseResult, EvaluationCase, GenerationRequest, RunSummary


def _read_html(case: EvaluationCase, max_bytes: int) -> str:
    try:
        raw = case.html_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"HTML 파일을 읽을 수 없습니다: {case.html_path}: {exc}") from exc
    if len(raw) > max_bytes:
        raise ValueError(f"HTML 파일이 {max_bytes} byte 제한을 초과했습니다: {len(raw)}")
    decoded = UnicodeDammit(raw, is_html=True).unicode_markup
    if decoded is None:
        raise ValueError(f"HTML 문자 인코딩을 판별할 수 없습니다: {case.html_path}")
    return decoded


def _append_result(path: Path, result: CaseResult) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(result.model_dump_json() + "\n")
        handle.flush()


def _error_result(
    case: EvaluationCase,
    run_id: str,
    model: str,
    status: str,
    error: str,
) -> CaseResult:
    return CaseResult(
        run_id=run_id,
        sample_id=case.id,
        html_path=str(case.html_path),
        question=case.question,
        expected=case.expected,
        normalized_expected=normalize_scalar(case.expected),
        status=status,
        error=error,
        prompt_sha256="",
        requested_model=model,
    )


def _run_case(
    case: EvaluationCase,
    run_id: str,
    settings: AppSettings,
    provider: ModelProvider,
) -> CaseResult:
    try:
        html = _read_html(case, settings.workflow.max_html_bytes)
    except ValueError as exc:
        return _error_result(
            case, run_id, settings.provider.model, "input_error", str(exc)
        )

    prompt = question_answer_prompt(case.question, html)
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    try:
        response = provider.generate(
            GenerationRequest(sample_id=case.id, prompt=prompt)
        )
    except Exception as exc:
        result = _error_result(
            case,
            run_id,
            settings.provider.model,
            "generation_error",
            f"{type(exc).__name__}: {str(exc)[:2000]}",
        )
        return result.model_copy(update={"prompt_sha256": prompt_hash})

    answer = response.result
    normalized_answer = normalize_scalar(answer.answer)
    normalized_expected = normalize_scalar(case.expected)
    answer_correct = not answer.abstained and normalized_answer == normalized_expected
    evidence_in_document, answer_in_evidence = validate_evidence(answer, html)
    passed = answer_correct and evidence_in_document and answer_in_evidence

    if answer.abstained:
        status = "abstained"
    elif not answer_correct:
        status = "wrong_answer"
    elif not evidence_in_document or not answer_in_evidence:
        status = "ungrounded_evidence"
    else:
        status = "passed"

    return CaseResult(
        run_id=run_id,
        sample_id=case.id,
        html_path=str(case.html_path),
        question=case.question,
        expected=case.expected,
        answer=answer.answer,
        evidence=answer.evidence,
        confidence=answer.confidence,
        abstained=answer.abstained,
        abstention_reason=answer.abstention_reason,
        normalized_expected=normalized_expected,
        normalized_answer=normalized_answer,
        answer_correct=answer_correct,
        evidence_in_document=evidence_in_document,
        answer_in_evidence=answer_in_evidence,
        passed=passed,
        status=status,
        prompt_sha256=prompt_hash,
        requested_model=response.requested_model,
        actual_model=response.actual_model,
        latency_seconds=response.latency_seconds,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def run_workflow(
    cases: list[EvaluationCase],
    settings: AppSettings,
    output_dir: str | Path,
    project_root: str | Path,
    *,
    provider: ModelProvider | None = None,
) -> RunSummary:
    """모든 사례를 실행하고 사례별 JSONL 및 전체 요약을 남긴다."""

    started_at = datetime.now(UTC)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    results_path = output / "results.jsonl"
    run_id = output.name
    active_provider = provider or create_provider(settings.provider, project_root)
    results: list[CaseResult] = []

    for case in cases:
        result = _run_case(case, run_id, settings, active_provider)
        results.append(result)
        _append_result(results_path, result)

    passed = sum(result.passed for result in results)
    summary = RunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        results_file=str(results_path),
    )
    (output / "summary.json").write_text(
        summary.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return summary
