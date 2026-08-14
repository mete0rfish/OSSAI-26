import json
from pathlib import Path

from dart_parser_workflow.config import AppSettings, load_cases, load_settings
from dart_parser_workflow.providers import ModelProvider
from dart_parser_workflow.schemas import (
    EvaluationCase,
    GenerationRequest,
    ProviderResponse,
)
from dart_parser_workflow.workflow import run_workflow

ROOT = Path(__file__).parents[1]


class SequenceProvider(ModelProvider):
    def __init__(self, codes: list[str]) -> None:
        self.codes = codes
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        self.requests.append(request)
        return ProviderResponse(
            code=self.codes[request.attempt],
            requested_model="fake-model",
            actual_model="fake-model",
            latency_seconds=0,
        )


def _settings() -> AppSettings:
    settings = load_settings(ROOT / "configs/recorded.yaml")
    return settings.model_copy(
        update={"workflow": settings.workflow.model_copy(update={"max_repair_attempts": 2})}
    )


def _case(tmp_path: Path, expected: str = "value") -> EvaluationCase:
    html_path = tmp_path / "case.html"
    html_path.write_text("<p>value</p>", encoding="utf-8")
    return EvaluationCase(id="case", html_path=html_path, question="값은?", expected=expected)


def test_recorded_end_to_end_example(tmp_path: Path) -> None:
    cases = load_cases(ROOT / "configs/cases.example.yaml", ROOT)
    settings = load_settings(ROOT / "configs/recorded.yaml")

    summary = run_workflow(cases, settings, tmp_path / "run", ROOT)

    assert summary.passed == 1
    result = json.loads((tmp_path / "run/results.jsonl").read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    assert result["extracted"] == "123,456백만원"
    assert result["diagnostic"] is None


def test_runtime_error_is_repaired_without_expected_in_prompt(tmp_path: Path) -> None:
    broken = "def extract(html: str) -> str:\n    raise ValueError('broken')\n"
    fixed = "def extract(html: str) -> str:\n    return 'value'\n"
    provider = SequenceProvider([broken, fixed])

    summary = run_workflow(
        [_case(tmp_path)],
        _settings(),
        tmp_path / "run",
        ROOT,
        provider=provider,
    )

    assert summary.passed == 1
    assert len(provider.requests) == 2
    assert "broken" in provider.requests[1].prompt
    assert "expected" not in provider.requests[1].prompt.lower()


def test_wrong_answer_is_not_retried(tmp_path: Path) -> None:
    provider = SequenceProvider(["def extract(html: str) -> str:\n    return 'wrong'\n"])

    summary = run_workflow(
        [_case(tmp_path)],
        _settings(),
        tmp_path / "run",
        ROOT,
        provider=provider,
    )

    assert summary.failed == 1
    assert len(provider.requests) == 1
    result = json.loads((tmp_path / "run/results.jsonl").read_text(encoding="utf-8"))
    assert result["status"] == "wrong_answer"


def test_input_failure_does_not_stop_later_cases(tmp_path: Path) -> None:
    missing = EvaluationCase(
        id="missing",
        html_path=tmp_path / "missing.html",
        question="값은?",
        expected="value",
    )
    valid = _case(tmp_path)
    valid = valid.model_copy(update={"id": "valid"})
    provider = SequenceProvider(["def extract(html: str) -> str:\n    return 'value'\n"])

    summary = run_workflow(
        [missing, valid],
        _settings(),
        tmp_path / "run",
        ROOT,
        provider=provider,
    )

    assert summary.total == 2
    assert summary.passed == 1
    rows = [json.loads(line) for line in (tmp_path / "run/results.jsonl").read_text().splitlines()]
    assert [row["status"] for row in rows] == ["input_error", "passed"]
