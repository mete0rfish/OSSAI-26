import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from dart_parser_workflow.config import (
    ExecutionLimits,
    PricingSettings,
    RetrySettings,
    load_optimization_settings,
)
from dart_parser_workflow.dataset import load_cases_v3
from dart_parser_workflow.execution import BudgetExceeded, CallLedger
from dart_parser_workflow.prompt_optimization import run_case_v3
from dart_parser_workflow.schemas import (
    DisclosureAnswer,
    Evidence,
    GenerationRequest,
    ModelUsage,
    ProviderResponse,
)

ROOT = Path(__file__).parents[1]


class TimeoutThenSuccessProvider:
    def __init__(self) -> None:
        self.attempts: list[int] = []

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        self.attempts.append(request.attempt)
        if request.attempt == 0:
            raise TimeoutError("secret provider response")
        return ProviderResponse(
            result=DisclosureAnswer(
                answer="100원",
                evidence=[Evidence(quote="2025년 개발 매출액 100원")],
                confidence=1,
                abstained=False,
            ),
            requested_model="retry-model",
            actual_model="retry-model",
            latency_seconds=0.01,
        )


def test_cost_limit_requires_pricing() -> None:
    with pytest.raises(ValidationError, match="pricing"):
        ExecutionLimits(max_cost_usd=0.01)


def test_call_ledger_records_hashes_and_enforces_cost(tmp_path: Path) -> None:
    limits = ExecutionLimits(
        max_cost_usd=0.0001,
        pricing=PricingSettings(
            verified_on=date.today(),
            input_usd_per_million_tokens=10,
            output_usd_per_million_tokens=20,
        ),
    )
    ledger = CallLedger(tmp_path / "calls.jsonl", {"target": limits})
    ledger.before_request("target")
    ledger.record(
        role="target",
        sample_id="sample",
        prompt_variant="baseline",
        prompt="secret prompt",
        html_sha256="a" * 64,
        requested_model="requested",
        actual_model="actual",
        usage=ModelUsage(input_tokens=100, output_tokens=10),
        latency_seconds=0.1,
    )

    with pytest.raises(BudgetExceeded, match="비용"):
        ledger.assert_within_limits("target")
    row = json.loads((tmp_path / "calls.jsonl").read_text(encoding="utf-8"))
    assert row["html_sha256"] == "a" * 64
    assert "secret prompt" not in row.values()
    assert ledger.role_summary("target", "requested")["actual_models"] == ["actual"]


def test_retry_records_attempts_without_raw_error_content(tmp_path: Path) -> None:
    settings = load_optimization_settings(ROOT / "configs/prompt-optimization.recorded.yaml")
    case = load_cases_v3(
        ROOT / "configs/cases.v3.example.jsonl",
        ROOT,
        requirements=settings.dataset,
    )[0]
    provider = TimeoutThenSuccessProvider()
    ledger = CallLedger(
        tmp_path / "calls.jsonl",
        {"target": ExecutionLimits(max_requests=2, max_attempts=2)},
    )

    result = run_case_v3(
        case,
        run_id="retry",
        prompt_template="{question}\n{html}",
        prompt_variant="baseline",
        max_html_bytes=settings.workflow.max_html_bytes,
        provider=provider,
        requested_model="retry-model",
        ledger=ledger,
        retry=RetrySettings(max_attempts_per_call=2),
    )

    assert result.score.strict_pass is True
    assert provider.attempts == [0, 1]
    rows = [
        json.loads(line)
        for line in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["attempt"] for row in rows] == [0, 1]
    assert rows[0]["error"] == "timeout: TimeoutError"
    assert "secret provider response" not in (tmp_path / "calls.jsonl").read_text()
