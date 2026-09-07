import json
from pathlib import Path

import pytest

from dart_parser_workflow.config import load_submission_settings
from dart_parser_workflow.dataset import load_cases_v3
from dart_parser_workflow.schemas import (
    DisclosureAnswer,
    Evidence,
    GenerationRequest,
    ProviderResponse,
)
from dart_parser_workflow.submission import run_submission_workflow

ROOT = Path(__file__).parents[1]


class RollbackProvider:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        if request.prompt_variant == "preflight":
            answer = DisclosureAnswer(
                answer="확인",
                evidence=[Evidence(quote="확인")],
                confidence=1,
                abstained=False,
            )
        elif request.sample_id.endswith("none"):
            answer = DisclosureAnswer(
                answer="답변 보류",
                evidence=[],
                confidence=1,
                abstained=True,
                abstention_reason="현재 HTML에서 확인할 수 없음",
            )
        else:
            expected = "300원" if request.sample_id == "test-answer" else "200원"
            value = "190원" if request.prompt_variant == "candidate" else expected
            period = "테스트" if request.sample_id == "test-answer" else "검증"
            answer = DisclosureAnswer(
                answer=value,
                evidence=[Evidence(quote=f"2025년 {period} 매출액 {value}")],
                confidence=1,
                abstained=False,
            )
        return ProviderResponse(
            result=answer,
            requested_model=self.model_id,
            actual_model=self.model_id,
            latency_seconds=0.01,
        )


class ValidationFailureProvider(RollbackProvider):
    def generate(self, request: GenerationRequest) -> ProviderResponse:
        if request.sample_id == "val-answer" and request.prompt_variant == "baseline":
            raise TimeoutError("transient validation failure")
        return super().generate(request)


def _inputs():
    settings = load_submission_settings(ROOT / "configs/submission.recorded.yaml")
    cases = load_cases_v3(
        ROOT / "configs/cases.v3.example.jsonl",
        ROOT,
        requirements=settings.dataset,
    )
    return settings, cases


def test_recorded_submission_runs_six_validation_combinations_then_test(
    tmp_path: Path,
) -> None:
    settings, cases = _inputs()

    summary = run_submission_workflow(cases, settings, tmp_path / "submission", ROOT)

    assert summary["observed_status"] == "complete"
    assert summary["quality_status"] == "pass"
    assert summary["selection"]["selected_model"] == "recorded-model-a"
    assert summary["selection"]["selected_prompt"] == "candidate"
    assert summary["selection"]["test_used_for_selection"] is False
    assert summary["test_used_for_generation_or_selection"] is False
    assert len(list((tmp_path / "submission/validation").glob("*.jsonl"))) == 6
    selection = json.loads(
        (tmp_path / "submission/selection.json").read_text(encoding="utf-8")
    )
    assert len(selection["model_comparisons"]) == 3
    assert selection["improved_examples"]
    test_rows = [
        json.loads(line)
        for line in (tmp_path / "submission/test.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert all("expected" not in row for row in test_rows)
    calls = [
        json.loads(line)
        for line in (tmp_path / "submission/calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    first_test = next(index for index, row in enumerate(calls) if row["sample_id"] == "test-answer")
    assert len(calls[:first_test]) == 15
    assert all("prompt" not in row and "expected" not in row for row in calls)
    assert (tmp_path / "submission/comparison.md").is_file()


def test_submission_refuses_existing_output(tmp_path: Path) -> None:
    settings, cases = _inputs()
    output = tmp_path / "existing"
    output.mkdir()

    with pytest.raises(FileExistsError):
        run_submission_workflow(cases, settings, output, ROOT)


def test_submission_prompt_hash_mismatch_fails_before_output(tmp_path: Path) -> None:
    settings, cases = _inputs()
    settings = settings.model_copy(update={"candidate_prompt_sha256": "0" * 64})

    with pytest.raises(ValueError, match="SHA-256"):
        run_submission_workflow(cases, settings, tmp_path / "mismatch", ROOT)

    assert not (tmp_path / "mismatch").exists()


def test_submission_rolls_all_candidates_back_before_test(tmp_path: Path) -> None:
    settings, cases = _inputs()
    providers = {
        model.model: RollbackProvider(model.model) for model in settings.models
    }

    summary = run_submission_workflow(
        cases,
        settings,
        tmp_path / "rollback",
        ROOT,
        providers=providers,
        available_model_ids=list(providers),
    )

    assert summary["observed_status"] == "complete"
    assert summary["selection"]["selected_prompt"] == "baseline"
    assert summary["selection"]["all_candidates_rolled_back"] is True
    assert all(
        not row["candidate_eligible"]
        for row in summary["selection"]["model_comparisons"]
    )


def test_submission_stops_before_calls_when_exact_model_id_is_missing(
    tmp_path: Path,
) -> None:
    settings, cases = _inputs()

    summary = run_submission_workflow(
        cases,
        settings,
        tmp_path / "missing-model",
        ROOT,
        available_model_ids=["recorded-model-a", "recorded-model-b"],
    )

    assert summary["observed_status"] == "not_run"
    assert "recorded-model-c" in summary["error"]
    assert not (tmp_path / "missing-model/calls.jsonl").exists()
    assert not (tmp_path / "missing-model/selection.json").exists()
    assert not (tmp_path / "missing-model/test.jsonl").exists()


def test_submission_validation_error_is_inconclusive_and_skips_test(
    tmp_path: Path,
) -> None:
    settings, cases = _inputs()
    providers = {
        model.model: (
            ValidationFailureProvider(model.model)
            if index == 0
            else RollbackProvider(model.model)
        )
        for index, model in enumerate(settings.models)
    }

    summary = run_submission_workflow(
        cases,
        settings,
        tmp_path / "inconclusive",
        ROOT,
        providers=providers,
        available_model_ids=list(providers),
    )

    assert summary["observed_status"] == "complete"
    assert summary["quality_status"] == "inconclusive"
    assert summary["selection"]["status"] == "inconclusive"
    assert not (tmp_path / "inconclusive/test.jsonl").exists()


def test_identical_candidate_is_automatically_rolled_back(tmp_path: Path) -> None:
    settings, cases = _inputs()
    settings = settings.model_copy(
        update={
            "candidate_prompt": settings.baseline_prompt,
            "candidate_prompt_sha256": settings.baseline_prompt_sha256,
        }
    )

    summary = run_submission_workflow(cases, settings, tmp_path / "identical", ROOT)

    assert summary["observed_status"] == "complete"
    assert summary["selection"]["selected_prompt"] == "baseline"
    assert summary["selection"]["all_candidates_rolled_back"] is True
    assert all(
        row["candidate_checks"]["prompt_changed"] is False
        for row in summary["selection"]["model_comparisons"]
    )


def test_live_submission_requires_approved_review_before_output(tmp_path: Path) -> None:
    _, cases = _inputs()
    live_settings = load_submission_settings(ROOT / "configs/submission.ollama-pro.yaml")

    with pytest.raises(PermissionError, match="외부 전송 승인"):
        run_submission_workflow(cases, live_settings, tmp_path / "live", ROOT)

    assert not (tmp_path / "live").exists()

    with pytest.raises(ValueError, match="reviews"):
        run_submission_workflow(
            cases,
            live_settings,
            tmp_path / "live-reviewed",
            ROOT,
            authorize_external_transmission=True,
        )

    assert not (tmp_path / "live-reviewed").exists()
