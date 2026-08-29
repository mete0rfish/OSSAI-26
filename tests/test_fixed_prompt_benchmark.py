import hashlib
import json
from pathlib import Path

import pytest

from dart_parser_workflow.config import (
    ExecutionLimits,
    FixedPromptBenchmarkSettings,
    ProviderSettings,
    load_fixed_prompt_benchmark_settings,
)
from dart_parser_workflow.dataset import load_cases_v3
from dart_parser_workflow.fixed_prompt_benchmark import run_fixed_prompt_benchmark
from dart_parser_workflow.providers import ModelProvider
from dart_parser_workflow.schemas import (
    DisclosureAnswer,
    Evidence,
    GenerationRequest,
    ModelUsage,
    ProviderResponse,
)

ROOT = Path(__file__).parents[1]

LIVE_CONFIGS = [
    "fixed-prompt-benchmark.gpt-oss-120b.yaml",
    "fixed-prompt-benchmark.gemini-3.5-flash-lite.yaml",
    "fixed-prompt-benchmark.qwen3.5-cloud.yaml",
    "fixed-prompt-benchmark.nemotron-3-ultra.yaml",
]


class ExactAnswerProvider(ModelProvider):
    def __init__(self, answers: dict[str, DisclosureAnswer]) -> None:
        self.answers = answers
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        self.requests.append(request)
        return ProviderResponse(
            result=self.answers[request.sample_id],
            requested_model="fixed-test-model",
            actual_model="fixed-test-model-v1",
            usage=ModelUsage(input_tokens=10, output_tokens=5),
            latency_seconds=0.01,
        )


@pytest.mark.parametrize("config_name", LIVE_CONFIGS)
def test_live_fixed_prompt_configs_pin_the_same_prompt(config_name: str) -> None:
    settings = load_fixed_prompt_benchmark_settings(ROOT / "configs" / config_name)
    prompt_path = ROOT / settings.prompt_path

    assert prompt_path.is_file()
    assert hashlib.sha256(prompt_path.read_bytes()).hexdigest() == settings.prompt_sha256
    assert settings.target_limits.max_requests >= 30


def _inputs():
    cases = load_cases_v3(ROOT / "configs/cases.v3.example.jsonl", ROOT)
    prompt_path = ROOT / "prompts/dart-qa-baseline.md"
    prompt_hash = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    settings = FixedPromptBenchmarkSettings(
        prompt_path=str(prompt_path),
        prompt_sha256=prompt_hash,
        target_provider=ProviderSettings(
            kind="recorded",
            model="fixed-test-model",
            recorded_responses="tests/fixtures/v3-recorded-responses.jsonl",
        ),
    )
    answers = {
        case.id: (
            DisclosureAnswer(
                answer="답변 보류",
                evidence=[],
                confidence=1.0,
                abstained=True,
                abstention_reason="공시에서 확인할 수 없음",
            )
            if case.expected.abstained
            else DisclosureAnswer(
                answer=case.expected.answer,
                evidence=[Evidence(quote=case.expected.evidence_quotes[0])],
                confidence=1.0,
                abstained=False,
            )
        )
        for case in cases
    }
    return cases, settings, ExactAnswerProvider(answers)


def test_fixed_prompt_benchmark_scores_all_cases_without_optimizer(tmp_path: Path) -> None:
    cases, settings, provider = _inputs()

    summary = run_fixed_prompt_benchmark(
        cases,
        settings,
        tmp_path / "run",
        ROOT,
        target_provider=provider,
    )

    assert summary["observed_status"] == "complete"
    assert summary["quality_status"] == "pass"
    assert summary["planned_case_count"] == len(cases)
    assert summary["completed_case_count"] == len(cases)
    assert summary["metrics"]["strict_pass_count"] == len(cases)
    assert summary["optimizer_used"] is False
    assert summary["candidate_generated"] is False
    assert summary["expected_answers_sent_to_provider"] is False
    assert {request.prompt_variant for request in provider.requests} == {"fixed"}
    assert all("accepted_answers" not in request.prompt for request in provider.requests)
    assert all("evidence_must_include" not in request.prompt for request in provider.requests)
    assert (tmp_path / "run/fixed-prompt.md").read_bytes() == Path(
        settings.prompt_path
    ).read_bytes()
    calls = [
        json.loads(line)
        for line in (tmp_path / "run/calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(calls) == len(cases)
    assert "prompt" not in calls[0]
    assert "expected" not in calls[0]
    assert "html" not in calls[0]


def test_fixed_prompt_hash_mismatch_fails_before_creating_output(tmp_path: Path) -> None:
    cases, settings, provider = _inputs()
    settings = settings.model_copy(update={"prompt_sha256": "0" * 64})

    with pytest.raises(ValueError, match="SHA-256"):
        run_fixed_prompt_benchmark(
            cases,
            settings,
            tmp_path / "mismatch",
            ROOT,
            target_provider=provider,
        )

    assert not (tmp_path / "mismatch").exists()


def test_fixed_prompt_budget_exhaustion_preserves_partial_run(tmp_path: Path) -> None:
    cases, settings, provider = _inputs()
    settings = settings.model_copy(
        update={"target_limits": ExecutionLimits(max_requests=1, max_attempts=1)}
    )

    summary = run_fixed_prompt_benchmark(
        cases,
        settings,
        tmp_path / "partial",
        ROOT,
        target_provider=provider,
    )

    assert summary["observed_status"] == "partial"
    assert summary["completed_case_count"] == 1
    assert (tmp_path / "partial/results.jsonl").exists()
    assert "상한" in summary["error"]


def test_fixed_prompt_benchmark_refuses_existing_output(tmp_path: Path) -> None:
    cases, settings, provider = _inputs()
    output = tmp_path / "existing"
    output.mkdir()

    with pytest.raises(FileExistsError):
        run_fixed_prompt_benchmark(
            cases,
            settings,
            output,
            ROOT,
            target_provider=provider,
        )
