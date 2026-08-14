"""Gemini 실제 호출과 저장 응답 재생 provider."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Protocol

from google import genai
from google.genai import types

from .config import ProviderSettings
from .schemas import DisclosureAnswer, GenerationRequest, ModelUsage, ProviderResponse


class ModelProvider(Protocol):
    def generate(self, request: GenerationRequest) -> ProviderResponse: ...


class GeminiProvider:
    def __init__(self, settings: ProviderSettings) -> None:
        assert settings.api_key_env is not None
        api_key = os.environ.get(settings.api_key_env)
        if not api_key:
            raise ValueError(f"환경 변수 {settings.api_key_env}에 Gemini API 키가 없습니다")
        self.settings = settings
        self.client = genai.Client(api_key=api_key)

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        started = time.monotonic()
        response = self.client.models.generate_content(
            model=self.settings.model,
            contents=request.prompt,
            config=types.GenerateContentConfig(
                temperature=self.settings.temperature,
                max_output_tokens=self.settings.max_output_tokens,
                response_mime_type="application/json",
                response_schema=DisclosureAnswer,
            ),
        )
        latency = time.monotonic() - started
        parsed = response.parsed
        if isinstance(parsed, DisclosureAnswer):
            result = parsed
        elif parsed is not None:
            result = DisclosureAnswer.model_validate(parsed)
        else:
            result = DisclosureAnswer.model_validate_json(response.text)

        metadata = getattr(response, "usage_metadata", None)
        usage = ModelUsage(
            input_tokens=getattr(metadata, "prompt_token_count", None),
            output_tokens=getattr(metadata, "candidates_token_count", None),
        )
        return ProviderResponse(
            result=result,
            requested_model=self.settings.model,
            actual_model=getattr(response, "model_version", None) or self.settings.model,
            usage=usage,
            latency_seconds=latency,
        )


class RecordedProvider:
    """`sample_id`로 저장된 구조화 답변을 재생한다."""

    def __init__(self, path: str | Path, model: str) -> None:
        self.model = model
        self.responses: dict[tuple[str, int], DisclosureAnswer] = {}
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                key = (str(row["sample_id"]), int(row.get("attempt", 0)))
                self.responses[key] = DisclosureAnswer.model_validate(row["response"])

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        started = time.monotonic()
        key = (request.sample_id, request.attempt)
        if key not in self.responses:
            raise KeyError(f"저장 응답이 없습니다: sample_id={key[0]}, attempt={key[1]}")
        return ProviderResponse(
            result=self.responses[key],
            requested_model=self.model,
            actual_model=self.model,
            latency_seconds=time.monotonic() - started,
        )


def create_provider(settings: ProviderSettings, project_root: str | Path) -> ModelProvider:
    if settings.kind == "gemini":
        return GeminiProvider(settings)
    assert settings.recorded_responses is not None
    path = Path(settings.recorded_responses)
    if not path.is_absolute():
        path = Path(project_root) / path
    return RecordedProvider(path.resolve(), settings.model)
