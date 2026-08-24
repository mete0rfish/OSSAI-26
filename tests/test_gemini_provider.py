import json
from types import SimpleNamespace

from dart_parser_workflow.config import ProviderSettings
from dart_parser_workflow.providers import GeminiOptimizerProvider, GeminiProvider
from dart_parser_workflow.schemas import (
    DisclosureAnswer,
    GenerationRequest,
    OptimizationRequest,
    PromptCandidate,
)


class FakeModels:
    def __init__(self, response, captured: dict) -> None:
        self.response = response
        self.captured = captured

    def generate_content(self, *, model, contents, config):
        self.captured.update(
            {"model": model, "contents": contents, "config": config}
        )
        return self.response


class FakeClient:
    def __init__(self, *, api_key, response, captured: dict) -> None:
        captured["api_key"] = api_key
        self.models = FakeModels(response, captured)


def test_gemini_target_uses_json_schema_field(monkeypatch) -> None:
    captured = {}
    answer = {
        "answer": "100원",
        "evidence": [{"quote": "시설자금 100원"}],
        "confidence": 0.9,
        "abstained": False,
        "abstention_reason": None,
    }
    response = SimpleNamespace(
        parsed=answer,
        text=json.dumps(answer),
        model_version="gemini-actual",
        usage_metadata=SimpleNamespace(
            prompt_token_count=101,
            candidates_token_count=22,
        ),
    )
    monkeypatch.setenv("GEMINI_API_KEY", "secret-for-test")
    monkeypatch.setattr(
        "dart_parser_workflow.providers.genai.Client",
        lambda *, api_key: FakeClient(
            api_key=api_key,
            response=response,
            captured=captured,
        ),
    )
    settings = ProviderSettings(
        kind="gemini",
        model="gemini-requested",
        api_key_env="GEMINI_API_KEY",
        temperature=0,
        max_output_tokens=321,
    )

    result = GeminiProvider(settings).generate(
        GenerationRequest(sample_id="case-1", prompt="질문과 HTML")
    )

    assert captured["api_key"] == "secret-for-test"
    assert captured["model"] == "gemini-requested"
    assert captured["contents"] == "질문과 HTML"
    assert captured["config"].response_schema is None
    assert (
        captured["config"].response_json_schema
        == DisclosureAnswer.model_json_schema()
    )
    assert result.result.answer == "100원"
    assert result.actual_model == "gemini-actual"
    assert result.usage.input_tokens == 101
    assert result.usage.output_tokens == 22


def test_gemini_optimizer_uses_json_schema_field(monkeypatch) -> None:
    captured = {}
    candidate = {
        "prompt": "개선 {question} {html}",
        "rationale": "표 문맥 강화",
    }
    response = SimpleNamespace(
        parsed=None,
        text=json.dumps(candidate, ensure_ascii=False),
        model_version=None,
        usage_metadata=None,
    )
    monkeypatch.setenv("GEMINI_API_KEY", "secret-for-test")
    monkeypatch.setattr(
        "dart_parser_workflow.providers.genai.Client",
        lambda *, api_key: FakeClient(
            api_key=api_key,
            response=response,
            captured=captured,
        ),
    )
    settings = ProviderSettings(
        kind="gemini",
        model="gemini-optimizer",
        api_key_env="GEMINI_API_KEY",
    )

    result = GeminiOptimizerProvider(settings).propose(
        OptimizationRequest(prompt="baseline과 development 실패")
    )

    assert captured["config"].response_schema is None
    assert (
        captured["config"].response_json_schema
        == PromptCandidate.model_json_schema()
    )
    assert result.result.prompt == "개선 {question} {html}"
    assert result.actual_model == "gemini-optimizer"
