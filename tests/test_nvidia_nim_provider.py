import json
import urllib.request

import pytest

from dart_parser_workflow.config import (
    OptimizationSettings,
    ProviderSettings,
    override_optimization_providers,
)
from dart_parser_workflow.providers import NvidiaNimOptimizerProvider, NvidiaNimProvider
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


def test_nvidia_nim_target_uses_hosted_openai_compatible_chat(monkeypatch) -> None:
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
        captured["timeout"] = timeout
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data)
        return FakeResponse(
            {
                "model": "nvidia/test-model-v2",
                "choices": [
                    {"message": {"role": "assistant", "content": json.dumps(answer)}}
                ],
                "usage": {"prompt_tokens": 101, "completion_tokens": 22},
            }
        )

    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "secret-for-test")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    settings = ProviderSettings(
        kind="nvidia_nim",
        model="nvidia/test-model",
        api_key_env="NVIDIA_NIM_API_KEY",
        request_timeout_seconds=9,
        temperature=0,
        top_p=0.95,
        enable_thinking=True,
        max_output_tokens=321,
    )

    response = NvidiaNimProvider(settings).generate(
        GenerationRequest(sample_id="case-1", prompt="질문과 HTML")
    )

    assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert captured["timeout"] == 9
    assert captured["authorization"] == "Bearer secret-for-test"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["temperature"] == 0.0
    assert captured["payload"]["top_p"] == 0.95
    assert captured["payload"]["chat_template_kwargs"] == {
        "enable_thinking": True,
    }
    assert captured["payload"]["max_tokens"] == 321
    assert captured["payload"]["messages"][1] == {
        "role": "user",
        "content": "질문과 HTML",
    }
    assert "JSON Schema" in captured["payload"]["messages"][0]["content"]
    assert response.result.answer == "100원"
    assert response.actual_model == "nvidia/test-model-v2"
    assert response.usage.input_tokens == 101
    assert response.usage.output_tokens == 22


def test_nvidia_nim_optimizer_validates_prompt_candidate(monkeypatch) -> None:
    candidate = {
        "prompt": "개선 {question} {html}",
        "rationale": "표 문맥 강화",
    }

    def fake_urlopen(request, timeout):
        return FakeResponse(
            {
                "model": "nvidia/optimizer-model",
                "choices": [
                    {"message": {"role": "assistant", "content": json.dumps(candidate)}}
                ],
            }
        )

    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "secret-for-test")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    settings = ProviderSettings(
        kind="nvidia_nim",
        model="nvidia/optimizer-model",
        api_key_env="NVIDIA_NIM_API_KEY",
    )

    response = NvidiaNimOptimizerProvider(settings).propose(
        OptimizationRequest(prompt="baseline과 development 실패")
    )

    assert response.result.prompt == "개선 {question} {html}"
    assert response.result.rationale == "표 문맥 강화"


def test_nvidia_nim_requires_configured_environment_key(monkeypatch) -> None:
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    settings = ProviderSettings(
        kind="nvidia_nim",
        model="nvidia/test-model",
        api_key_env="NVIDIA_NIM_API_KEY",
    )

    with pytest.raises(ValueError, match="NVIDIA_NIM_API_KEY"):
        NvidiaNimProvider(settings)


def test_switching_to_nvidia_nim_uses_safe_defaults() -> None:
    settings = OptimizationSettings(
        target_provider=ProviderSettings(
            kind="gemini",
            model="gemini-model",
            api_key_env="GEMINI_API_KEY",
        ),
        optimizer_provider=ProviderSettings(
            kind="gemini",
            model="gemini-model",
            api_key_env="GEMINI_API_KEY",
        ),
    )

    updated = override_optimization_providers(settings, target_kind="nvidia_nim")

    assert updated.target_provider.api_key_env == "NVIDIA_NIM_API_KEY"
    assert updated.target_provider.base_url == "https://integrate.api.nvidia.com/v1"
