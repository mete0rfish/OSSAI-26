"""HTML 읽기부터 생성·검사·실행·평가·결과 저장까지 연결한다."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from bs4 import UnicodeDammit

from .config import AppSettings
from .evaluation import evaluate_parser_quality, normalize_scalar
from .execution import ParserExecutionError, execute_parser
from .prompts import generation_prompt, repair_prompt
from .providers import ModelProvider, create_provider
from .safety import SafetyViolation, validate_parser_source
from .schemas import (
    AttemptResult,
    CaseResult,
    DiagnosticResult,
    EvaluationCase,
    GenerationRequest,
    RunSummary,
)


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


def _input_error_result(
    case: EvaluationCase,
    run_id: str,
    model: str,
    error: str,
) -> CaseResult:
    return CaseResult(
        run_id=run_id,
        sample_id=case.id,
        html_path=str(case.html_path),
        question=case.question,
        expected=case.expected,
        normalized_expected=normalize_scalar(case.expected),
        status="input_error",
        prompt_sha256="",
        requested_model=model,
        attempts=[AttemptResult(attempt=0, error_kind="input_error", error=error)],
    )


def _run_case(
    case: EvaluationCase,
    run_id: str,
    case_output: Path,
    settings: AppSettings,
    provider: ModelProvider,
) -> CaseResult:
    try:
        html = _read_html(case, settings.workflow.max_html_bytes)
    except ValueError as exc:
        return _input_error_result(case, run_id, settings.provider.model, str(exc))

    initial_prompt = generation_prompt(case.question, html)
    prompt_hash = hashlib.sha256(initial_prompt.encode("utf-8")).hexdigest()
    prompt = initial_prompt
    attempts: list[AttemptResult] = []
    final_code: str | None = None
    extracted: str | None = None
    requested_model = settings.provider.model
    actual_model: str | None = None
    final_status = "generation_error"

    for attempt in range(settings.workflow.max_repair_attempts + 1):
        try:
            response = provider.generate(
                GenerationRequest(sample_id=case.id, attempt=attempt, prompt=prompt)
            )
        except Exception as exc:
            attempts.append(
                AttemptResult(
                    attempt=attempt,
                    error_kind="generation_error",
                    error=f"{type(exc).__name__}: {str(exc)[:2000]}",
                )
            )
            final_status = "generation_error"
            break

        requested_model = response.requested_model
        actual_model = response.actual_model
        final_code = response.code
        code_path = case_output / f"parser_attempt_{attempt}.py"
        code_path.write_text(final_code, encoding="utf-8")
        attempt_result = AttemptResult(
            attempt=attempt,
            code_path=str(code_path),
            latency_seconds=response.latency_seconds,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        try:
            validate_parser_source(final_code, settings.execution.max_source_bytes)
            extracted = execute_parser(code_path, html, settings.execution)
        except SafetyViolation as exc:
            attempt_result.error_kind = "safety_rejected"
            attempt_result.error = str(exc)
            final_status = "safety_rejected"
        except ParserExecutionError as exc:
            attempt_result.error_kind = exc.kind
            attempt_result.error = str(exc)
            final_status = "execution_error"
        else:
            attempts.append(attempt_result)
            final_status = (
                "passed"
                if normalize_scalar(extracted) == normalize_scalar(case.expected)
                else "wrong_answer"
            )
            break

        attempts.append(attempt_result)
        if attempt >= settings.workflow.max_repair_attempts:
            break
        assert attempt_result.error is not None
        prompt = repair_prompt(case.question, html, final_code, attempt_result.error)

    diagnostic: DiagnosticResult | None = None
    if final_code is not None:
        diagnostic = evaluate_parser_quality(case.question, final_code, settings.diagnostics)
    normalized_extracted = normalize_scalar(extracted) if extracted is not None else None
    return CaseResult(
        run_id=run_id,
        sample_id=case.id,
        html_path=str(case.html_path),
        question=case.question,
        expected=case.expected,
        extracted=extracted,
        normalized_expected=normalize_scalar(case.expected),
        normalized_extracted=normalized_extracted,
        passed=final_status == "passed",
        status=final_status,
        prompt_sha256=prompt_hash,
        requested_model=requested_model,
        actual_model=actual_model,
        attempts=attempts,
        diagnostic=diagnostic,
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
        case_output = output / case.id
        case_output.mkdir(parents=False, exist_ok=False)
        result = _run_case(case, run_id, case_output, settings, active_provider)
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
