import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from dart_parser_workflow.config import ExecutionLimits, PricingSettings
from dart_parser_workflow.execution import BudgetExceeded, CallLedger
from dart_parser_workflow.schemas import ModelUsage


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
