import json
from pathlib import Path

from dart_parser_workflow.config import load_cases, load_settings
from dart_parser_workflow.providers import ModelProvider
from dart_parser_workflow.schemas import (
    DisclosureAnswer,
    EvaluationCase,
    Evidence,
    GenerationRequest,
    ProviderResponse,
)
from dart_parser_workflow.workflow import run_workflow

ROOT = Path(__file__).parents[1]


class FakeProvider(ModelProvider):
    def __init__(self, result: DisclosureAnswer) -> None:
        self.result = result
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        self.requests.append(request)
        return ProviderResponse(
            result=self.result,
            requested_model="fake-model",
            actual_model="fake-model",
            latency_seconds=0,
        )


def _settings():
    return load_settings(ROOT / "configs/recorded.yaml")


def _case(tmp_path: Path, expected: str = "123원") -> EvaluationCase:
    html_path = tmp_path / "case.html"
    html_path.write_text(
        "<table><tr><th>2025년 매출액</th><td>123원</td></tr></table>",
        encoding="utf-8",
    )
    return EvaluationCase(
        id="case",
        html_path=html_path,
        question="2025년 매출액은?",
        expected=expected,
    )


def _answer(answer: str = "123원", quote: str = "2025년 매출액 123원") -> DisclosureAnswer:
    return DisclosureAnswer(
        answer=answer,
        evidence=[Evidence(quote=quote)],
        confidence=0.9,
        abstained=False,
    )


def test_recorded_end_to_end_example(tmp_path: Path) -> None:
    cases = load_cases(ROOT / "configs/cases.example.yaml", ROOT)
    settings = load_settings(ROOT / "configs/recorded.yaml")

    summary = run_workflow(cases, settings, tmp_path / "run", ROOT)

    assert summary.passed == 1
    result = json.loads((tmp_path / "run/results.jsonl").read_text(encoding="utf-8"))
    assert result["schema_version"] == 2
    assert result["status"] == "passed"
    assert result["answer"] == "123,456백만원"
    assert result["answer_correct"] is True
    assert result["evidence_in_document"] is True
    assert result["answer_in_evidence"] is True


def test_correct_answer_with_invented_evidence_fails(tmp_path: Path) -> None:
    provider = FakeProvider(_answer(quote="공시에 없는 인용 123원"))

    summary = run_workflow(
        [_case(tmp_path)], _settings(), tmp_path / "run", ROOT, provider=provider
    )

    assert summary.failed == 1
    result = json.loads((tmp_path / "run/results.jsonl").read_text(encoding="utf-8"))
    assert result["status"] == "ungrounded_evidence"
    assert result["answer_correct"] is True
    assert result["evidence_in_document"] is False


def test_wrong_answer_fails_even_when_evidence_exists(tmp_path: Path) -> None:
    provider = FakeProvider(_answer(answer="999원", quote="2025년 매출액 123원"))

    summary = run_workflow(
        [_case(tmp_path)], _settings(), tmp_path / "run", ROOT, provider=provider
    )

    assert summary.failed == 1
    result = json.loads((tmp_path / "run/results.jsonl").read_text(encoding="utf-8"))
    assert result["status"] == "wrong_answer"
    assert result["answer_correct"] is False
    assert result["evidence_in_document"] is True
    assert result["answer_in_evidence"] is False


def test_abstention_is_recorded_as_failure(tmp_path: Path) -> None:
    provider = FakeProvider(
        DisclosureAnswer(
            answer="답변 보류",
            evidence=[],
            confidence=0,
            abstained=True,
            abstention_reason="공시에서 확인할 수 없음",
        )
    )

    summary = run_workflow(
        [_case(tmp_path)], _settings(), tmp_path / "run", ROOT, provider=provider
    )

    assert summary.failed == 1
    result = json.loads((tmp_path / "run/results.jsonl").read_text(encoding="utf-8"))
    assert result["status"] == "abstained"


def test_expected_answer_is_not_sent_to_provider(tmp_path: Path) -> None:
    provider = FakeProvider(_answer())

    run_workflow([_case(tmp_path)], _settings(), tmp_path / "run", ROOT, provider=provider)

    assert len(provider.requests) == 1
    assert "expected" not in provider.requests[0].prompt.lower()


def test_input_failure_does_not_stop_later_cases(tmp_path: Path) -> None:
    missing = EvaluationCase(
        id="missing",
        html_path=tmp_path / "missing.html",
        question="값은?",
        expected="123원",
    )
    valid = _case(tmp_path).model_copy(update={"id": "valid"})
    provider = FakeProvider(_answer())

    summary = run_workflow(
        [missing, valid], _settings(), tmp_path / "run", ROOT, provider=provider
    )

    assert summary.total == 2
    assert summary.passed == 1
    rows = [json.loads(line) for line in (tmp_path / "run/results.jsonl").read_text().splitlines()]
    assert [row["status"] for row in rows] == ["input_error", "passed"]
