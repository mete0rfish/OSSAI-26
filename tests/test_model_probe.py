import json
from pathlib import Path

import pytest

from dart_parser_workflow.config import load_optimization_settings
from dart_parser_workflow.dataset import load_probe_cases_v3
from dart_parser_workflow.model_probe import run_model_probe
from dart_parser_workflow.schemas import DisclosureAnswer, ProviderResponse

ROOT = Path(__file__).parents[1]


class ProbeProvider:
    def generate(self, request):
        if request.sample_id == "dev-none":
            answer = DisclosureAnswer(
                answer="답변 보류",
                evidence=[],
                confidence=1.0,
                abstained=True,
                abstention_reason="문서에 값이 없음",
            )
        else:
            answer = DisclosureAnswer(
                answer="100원",
                evidence=[{"quote": "2025년 개발 매출액 100원"}],
                confidence=1.0,
                abstained=False,
            )
        return ProviderResponse(
            result=answer,
            requested_model="probe-model",
            actual_model="probe-model",
            latency_seconds=0,
        )


def _probe_file(tmp_path: Path, *, keep_expected: bool = False) -> Path:
    rows = []
    source = ROOT / "configs/cases.v3.example.jsonl"
    for line in source.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if not keep_expected:
            row.pop("expected")
        rows.append(row)
    path = tmp_path / "probe.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def test_probe_input_rejects_expected_answers(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expected"):
        load_probe_cases_v3(_probe_file(tmp_path, keep_expected=True), ROOT)


def test_probe_collects_answers_without_expected_or_scores(tmp_path: Path) -> None:
    cases = load_probe_cases_v3(_probe_file(tmp_path), ROOT)
    development = [case for case in cases if case.split == "development"]
    settings = load_optimization_settings(ROOT / "configs/prompt-optimization.recorded.yaml")

    summary = run_model_probe(
        development,
        settings,
        tmp_path / "run",
        ROOT,
        target_provider=ProbeProvider(),
    )

    assert summary["observed_status"] == "complete"
    assert summary["expected_answers_used"] is False
    rows = [
        json.loads(line)
        for line in (tmp_path / "run/responses.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 2
    assert all("expected" not in row and "score" not in row for row in rows)
    assert {row["status"] for row in rows} == {"answered", "abstained"}
