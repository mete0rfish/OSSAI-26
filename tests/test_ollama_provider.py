import json
import urllib.request

import pytest

from dart_parser_workflow.config import ProviderSettings
from dart_parser_workflow.providers import OllamaOptimizerProvider, OllamaProvider
from dart_parser_workflow.schemas import GenerationRequest, OptimizationRequest


class FakeResponse:
    def __init__(self, value: dict) -> None:
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.value, ensure_ascii=False).encode()


def test_ollama_target_uses_native_structured_chat(monkeypatch) -> None:
    captured = {}
    answer = {
        "answer": "100원",
        "evidence": [{"quote": "매출액 100원"}],
        "confidence": 0.9,
        "abstained": False,
        "abstention_reason": None,
    }

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data)
        return FakeResponse(
            {
                "model": "qwen-local:latest",
                "message": {"role": "assistant", "content": json.dumps(answer)},
                "prompt_eval_count": 101,
                "eval_count": 22,
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    settings = ProviderSettings(
        kind="ollama",
        model="qwen-local",
        base_url="http://127.0.0.1:11434/",
        request_timeout_seconds=9,
        temperature=0,
        max_output_tokens=321,
    )

    response = OllamaProvider(settings).generate(
        GenerationRequest(sample_id="case-1", prompt="질문과 HTML")
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["timeout"] == 9
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["think"] is False
    assert captured["payload"]["format"]["type"] == "object"
    assert captured["payload"]["options"] == {"temperature": 0.0, "num_predict": 321}
    assert response.result.answer == "100원"
    assert response.actual_model == "qwen-local:latest"
    assert response.usage.input_tokens == 101
    assert response.usage.output_tokens == 22


def test_ollama_optimizer_validates_prompt_candidate(monkeypatch) -> None:
    candidate = {
        "prompt": "개선 {question} {html}",
        "rationale": "표 문맥 강화",
    }

    def fake_urlopen(request, timeout):
        return FakeResponse(
            {
                "model": "optimizer-local",
                "message": {"role": "assistant", "content": json.dumps(candidate)},
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    settings = ProviderSettings(kind="ollama", model="optimizer-local")

    response = OllamaOptimizerProvider(settings).propose(
        OptimizationRequest(prompt="baseline과 development 실패")
    )

    assert response.result.prompt == "개선 {question} {html}"
    assert response.result.rationale == "표 문맥 강화"


def test_ollama_cloud_uses_bearer_auth_and_prompt_schema(monkeypatch) -> None:
    captured = {}
    answer = {
        "answer": "100원",
        "evidence": [{"quote": "시설자금 100원"}],
        "confidence": 0.9,
        "abstained": False,
        "abstention_reason": None,
    }

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data)
        return FakeResponse(
            {
                "model": "gpt-oss:120b",
                "message": {"role": "assistant", "content": json.dumps(answer)},
            }
        )

    monkeypatch.setenv("OLLAMA_API_KEY", "cloud-secret-for-test")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    settings = ProviderSettings(
        kind="ollama",
        model="gpt-oss:120b",
        api_key_env="OLLAMA_API_KEY",
        base_url="https://ollama.com",
    )

    response = OllamaProvider(settings).generate(
        GenerationRequest(sample_id="case-1", prompt="질문과 HTML")
    )

    assert captured["url"] == "https://ollama.com/api/chat"
    assert captured["authorization"] == "Bearer cloud-secret-for-test"
    assert "format" not in captured["payload"]
    assert "think" not in captured["payload"]
    assert captured["payload"]["messages"][1] == {
        "role": "user",
        "content": "질문과 HTML",
    }
    assert "JSON Schema" in captured["payload"]["messages"][0]["content"]
    assert response.result.answer == "100원"


def test_ollama_cloud_requires_api_key_configuration(monkeypatch) -> None:
    with pytest.raises(ValueError, match="api_key_env"):
        ProviderSettings(
            kind="ollama",
            model="gpt-oss:120b",
            base_url="https://ollama.com",
        )

    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    settings = ProviderSettings(
        kind="ollama",
        model="gpt-oss:120b",
        api_key_env="OLLAMA_API_KEY",
        base_url="https://ollama.com",
    )
    with pytest.raises(ValueError, match="OLLAMA_API_KEY"):
        OllamaProvider(settings)


def test_ollama_rejects_non_http_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        ProviderSettings(kind="ollama", model="local", base_url="localhost:11434")
