"""기대 답 없이 target 모델 응답과 근거 grounding만 수집한다."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from .config import OptimizationSettings
from .evaluation import validate_evidence
from .execution import BudgetExceeded, CallLedger
from .html_utils import read_html
from .prompts import load_prompt, render_prompt
from .providers import ModelProvider, create_target_provider_v3
from .schemas import GenerationRequest, ModelProbeCaseV3, ModelProbeResultV3, ModelUsage


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


def run_model_probe(
    cases: list[ModelProbeCaseV3],
    settings: OptimizationSettings,
    output_dir: str | Path,
    project_root: str | Path,
    *,
    target_provider: ModelProvider | None = None,
) -> dict:
    """정답·점수·optimizer 없이 선택된 사례를 target 모델에 실행한다."""

    if not cases:
        raise ValueError("실행할 model probe 사례가 없습니다")
    root = Path(project_root).resolve()
    output = Path(output_dir).resolve()
    prompt_path = Path(settings.baseline_prompt)
    if not prompt_path.is_absolute():
        prompt_path = root / prompt_path
    prompt_template = load_prompt(prompt_path)
    prompt_hash = hashlib.sha256(prompt_template.encode()).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now(UTC)
    summary = {
        "schema_version": 3,
        "run_id": output.name,
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "observed_status": "partial",
        "expected_answers_used": False,
        "case_count": len(cases),
        "response_count": 0,
        "error_count": 0,
        "splits": sorted({case.split for case in cases}),
        "sample_ids": [case.id for case in cases],
        "prompt_sha256": prompt_hash,
        "provider_usage": {},
        "error": None,
    }
    _atomic_json(output / "summary.json", summary)
    ledger = CallLedger(output / "calls.jsonl", {"target": settings.target_limits})
    try:
        provider = target_provider or create_target_provider_v3(
            settings.target_provider, root
        )
    except Exception as exc:
        summary.update(
            observed_status="not_run",
            finished_at=datetime.now(UTC).isoformat(),
            error=f"{type(exc).__name__}: {str(exc)[:2000]}",
        )
        _atomic_json(output / "summary.json", summary)
        return summary

    responses_path = output / "responses.jsonl"
    try:
        for case in cases:
            try:
                _, html = read_html(case.html_path, settings.workflow.max_html_bytes)
                prompt = render_prompt(prompt_template, case.question, html)
            except ValueError as exc:
                result = ModelProbeResultV3(
                    run_id=output.name,
                    sample_id=case.id,
                    family_id=case.family_id,
                    split=case.split,
                    html_path=str(case.html_path),
                    html_sha256=case.html_sha256,
                    question=case.question,
                    status="input_error",
                    error=str(exc),
                    prompt_sha256=prompt_hash,
                    requested_model=settings.target_provider.model,
                )
                _append_jsonl(responses_path, result.model_dump(mode="json"))
                continue

            ledger.before_request("target")
            try:
                response = provider.generate(
                    GenerationRequest(
                        sample_id=case.id,
                        prompt=prompt,
                        provider_role="target",
                        prompt_variant="probe",
                    )
                )
            except BudgetExceeded:
                raise
            except Exception as exc:
                error = f"{type(exc).__name__}: {str(exc)[:2000]}"
                ledger.record(
                    role="target",
                    sample_id=case.id,
                    prompt_variant="probe",
                    prompt=prompt,
                    requested_model=settings.target_provider.model,
                    actual_model=None,
                    usage=ModelUsage(),
                    latency_seconds=None,
                    html_sha256=case.html_sha256,
                    error=error,
                )
                result = ModelProbeResultV3(
                    run_id=output.name,
                    sample_id=case.id,
                    family_id=case.family_id,
                    split=case.split,
                    html_path=str(case.html_path),
                    html_sha256=case.html_sha256,
                    question=case.question,
                    status="generation_error",
                    error=error,
                    prompt_sha256=prompt_hash,
                    requested_model=settings.target_provider.model,
                )
                _append_jsonl(responses_path, result.model_dump(mode="json"))
                continue

            ledger.record(
                role="target",
                sample_id=case.id,
                prompt_variant="probe",
                prompt=prompt,
                requested_model=response.requested_model,
                actual_model=response.actual_model,
                usage=response.usage,
                latency_seconds=response.latency_seconds,
                html_sha256=case.html_sha256,
            )
            answer = response.result
            evidence_in_document, answer_in_evidence = validate_evidence(answer, html)
            result = ModelProbeResultV3(
                run_id=output.name,
                sample_id=case.id,
                family_id=case.family_id,
                split=case.split,
                html_path=str(case.html_path),
                html_sha256=case.html_sha256,
                question=case.question,
                answer=answer.answer,
                evidence=answer.evidence,
                confidence=answer.confidence,
                abstained=answer.abstained,
                abstention_reason=answer.abstention_reason,
                evidence_in_document=(None if answer.abstained else evidence_in_document),
                answer_in_evidence=(None if answer.abstained else answer_in_evidence),
                status="abstained" if answer.abstained else "answered",
                prompt_sha256=prompt_hash,
                requested_model=response.requested_model,
                actual_model=response.actual_model,
                latency_seconds=response.latency_seconds,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            _append_jsonl(responses_path, result.model_dump(mode="json"))
        ledger.assert_within_limits("target")
        rows = [
            json.loads(line)
            for line in responses_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        summary.update(
            observed_status="complete",
            response_count=len(rows),
            error_count=sum(row["status"].endswith("error") for row in rows),
        )
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {str(exc)[:2000]}"
        if responses_path.exists():
            summary["response_count"] = sum(
                bool(line.strip())
                for line in responses_path.read_text(encoding="utf-8").splitlines()
            )
    summary.update(
        finished_at=datetime.now(UTC).isoformat(),
        provider_usage=ledger.role_summary("target", settings.target_provider.model),
    )
    _atomic_json(output / "summary.json", summary)
    return summary
