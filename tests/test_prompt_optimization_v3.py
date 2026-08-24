import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dart_parser_workflow.config import (
    ExecutionLimits,
    ProviderSettings,
    load_optimization_settings,
    override_optimization_providers,
)
from dart_parser_workflow.dataset import load_cases_v3
from dart_parser_workflow.prompt_optimization import run_prompt_optimization, select_prompt
from dart_parser_workflow.providers import RoleRecordedProvider
from dart_parser_workflow.schemas import OptimizationRequest, OptimizerResponse

ROOT = Path(__file__).parents[1]


class CapturingOptimizer:
    def __init__(self, delegate: RoleRecordedProvider) -> None:
        self.delegate = delegate
        self.requests: list[OptimizationRequest] = []

    def propose(self, request: OptimizationRequest) -> OptimizerResponse:
        self.requests.append(request)
        return self.delegate.propose(request)


def _inputs():
    settings = load_optimization_settings(ROOT / "configs/prompt-optimization.recorded.yaml")
    cases = load_cases_v3(
        ROOT / "configs/cases.v3.example.jsonl",
        ROOT,
        requirements=settings.dataset,
    )
    fixture = ROOT / "tests/fixtures/v3-recorded-responses.jsonl"
    return settings, cases, fixture


def test_cli_provider_overrides_keep_secrets_in_environment_names() -> None:
    settings = load_optimization_settings(ROOT / "configs/prompt-optimization.default.yaml")

    overridden = override_optimization_providers(
        settings,
        target_kind="ollama",
        target_model="gemini-target-test",
        target_api_key_env="GEMINI_KEY_A",
        target_base_url="http://127.0.0.1:11434",
        optimizer_model="gemini-optimizer-test",
        optimizer_api_key_env="GEMINI_KEY_B",
    )

    assert settings.target_provider.model != "gemini-target-test"
    assert overridden.target_provider.kind == "ollama"
    assert overridden.target_provider.model == "gemini-target-test"
    assert overridden.target_provider.api_key_env == "GEMINI_KEY_A"
    assert overridden.target_provider.base_url == "http://127.0.0.1:11434"
    assert overridden.optimizer_provider.model == "gemini-optimizer-test"
    assert overridden.optimizer_provider.api_key_env == "GEMINI_KEY_B"
    assert overridden.target_provider.temperature == settings.target_provider.temperature
    assert overridden.optimizer_limits == settings.optimizer_limits


def test_recorded_v3_optimization_keeps_test_out_of_selection(tmp_path: Path) -> None:
    settings, cases, fixture = _inputs()
    target = RoleRecordedProvider(fixture, "recorded-target-v3")
    optimizer = CapturingOptimizer(RoleRecordedProvider(fixture, "recorded-optimizer-v3"))

    summary = run_prompt_optimization(
        cases,
        settings,
        tmp_path / "run",
        ROOT,
        target_provider=target,
        optimizer_provider=optimizer,
    )

    assert summary["observed_status"] == "complete"
    assert summary["quality_status"] == "pass"
    assert summary["selection"]["selected"] == "candidate"
    assert summary["selection"]["reason"] == "validation_improved"
    assert len(optimizer.requests) == 1
    optimizer_prompt = optimizer.requests[0].prompt
    assert "dev-answer" in optimizer_prompt
    assert "val-answer" not in optimizer_prompt
    assert "test-answer" not in optimizer_prompt
    calls = [
        json.loads(line)
        for line in (tmp_path / "run/calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    first_test = next(index for index, row in enumerate(calls) if row["sample_id"] == "test-answer")
    assert all(row["sample_id"] not in {"test-answer", "test-none"} for row in calls[:first_test])
    assert summary["test_used_for_generation_or_selection"] is False


def test_budget_exhaustion_preserves_partial_run(tmp_path: Path) -> None:
    settings, cases, fixture = _inputs()
    settings = settings.model_copy(
        update={"target_limits": ExecutionLimits(max_requests=1, max_attempts=1)}
    )

    summary = run_prompt_optimization(
        cases,
        settings,
        tmp_path / "partial",
        ROOT,
        target_provider=RoleRecordedProvider(fixture, "recorded-target-v3"),
        optimizer_provider=RoleRecordedProvider(fixture, "recorded-optimizer-v3"),
    )

    assert summary["observed_status"] == "partial"
    assert summary["quality_status"] == "inconclusive"
    assert (tmp_path / "partial/development.jsonl").exists()
    assert "상한" in summary["error"]


def _result(
    mean: float,
    *,
    strict: bool = True,
    status: str = "passed",
    abstained: bool = False,
):
    return SimpleNamespace(
        score=SimpleNamespace(quality_score=mean, strict_pass=strict),
        status=status,
        answerable=True,
        abstained=abstained,
    )


@pytest.mark.parametrize(
    ("candidate", "expected_reason"),
    [
        (_result(1, status="generation_error"), "validation_errors_increased"),
        (_result(1, abstained=True), "answerable_abstentions_increased"),
        (_result(1, strict=False), "strict_pass_rate_decreased"),
        (_result(0.505), "validation_not_improved"),
        (_result(0.8), "validation_improved"),
    ],
)
def test_selector_applies_rollback_gates_in_order(candidate, expected_reason) -> None:
    selection = select_prompt(
        "base {question} {html}",
        "candidate {question} {html}",
        [_result(0.5)],
        [candidate],
        min_mean_improvement=0.01,
    )

    assert selection.reason == expected_reason
    assert selection.selected == (
        "candidate" if expected_reason == "validation_improved" else "baseline"
    )


def test_missing_live_provider_key_is_not_run(monkeypatch, tmp_path: Path) -> None:
    settings, cases, _ = _inputs()
    monkeypatch.delenv("OSSAI_TEST_MISSING_KEY", raising=False)
    live = ProviderSettings(
        kind="gemini",
        model="test-model",
        api_key_env="OSSAI_TEST_MISSING_KEY",
    )
    settings = settings.model_copy(
        update={"target_provider": live, "optimizer_provider": live}
    )

    summary = run_prompt_optimization(cases, settings, tmp_path / "not-run", ROOT)

    assert summary["observed_status"] == "not_run"
    assert summary["quality_status"] == "inconclusive"
