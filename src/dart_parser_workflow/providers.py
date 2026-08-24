"""Gemini, Ollama, NVIDIA NIM 실제 호출과 저장 응답 재생 provider."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from google import genai
from google.genai import types
from pydantic import BaseModel

from .config import ProviderSettings
from .schemas import (
    DisclosureAnswer,
    GenerationRequest,
    ModelUsage,
    OptimizationRequest,
    OptimizerResponse,
    PromptCandidate,
    ProviderResponse,
)


class ModelProvider(Protocol):
    def generate(self, request: GenerationRequest) -> ProviderResponse: ...


class OptimizerProvider(Protocol):
    def propose(self, request: OptimizationRequest) -> OptimizerResponse: ...


def _gemini_generation_config(
    settings: ProviderSettings,
    response_model: type[BaseModel],
) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        temperature=settings.temperature,
        max_output_tokens=settings.max_output_tokens,
        response_mime_type="application/json",
        response_json_schema=response_model.model_json_schema(),
    )


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
            config=_gemini_generation_config(self.settings, DisclosureAnswer),
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


class GeminiOptimizerProvider:
    def __init__(self, settings: ProviderSettings) -> None:
        assert settings.api_key_env is not None
        api_key = os.environ.get(settings.api_key_env)
        if not api_key:
            raise ValueError(f"환경 변수 {settings.api_key_env}에 Gemini API 키가 없습니다")
        self.settings = settings
        self.client = genai.Client(api_key=api_key)

    def propose(self, request: OptimizationRequest) -> OptimizerResponse:
        started = time.monotonic()
        response = self.client.models.generate_content(
            model=self.settings.model,
            contents=request.prompt,
            config=_gemini_generation_config(self.settings, PromptCandidate),
        )
        latency = time.monotonic() - started
        parsed = response.parsed
        if isinstance(parsed, PromptCandidate):
            result = parsed
        elif parsed is not None:
            result = PromptCandidate.model_validate(parsed)
        else:
            result = PromptCandidate.model_validate_json(response.text)
        metadata = getattr(response, "usage_metadata", None)
        return OptimizerResponse(
            result=result,
            requested_model=self.settings.model,
            actual_model=getattr(response, "model_version", None) or self.settings.model,
            usage=ModelUsage(
                input_tokens=getattr(metadata, "prompt_token_count", None),
                output_tokens=getattr(metadata, "candidates_token_count", None),
            ),
            latency_seconds=latency,
        )


def _ollama_chat(
    settings: ProviderSettings,
    prompt: str,
    response_model: type[BaseModel],
    api_key: str | None,
) -> tuple[BaseModel, dict, float]:
    cloud = settings.base_url == "https://ollama.com"
    messages = [{"role": "user", "content": prompt}]
    if cloud:
        schema = response_model.model_json_schema()
        schema_instruction = (
            "반드시 아래 JSON Schema를 충족하는 JSON 객체 하나만 반환하십시오. "
            "Markdown 코드 블록이나 JSON 밖의 설명을 추가하지 마십시오.\n"
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        )
        messages.insert(0, {"role": "system", "content": schema_instruction})
    payload = {
        "model": settings.model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": settings.temperature,
            "num_predict": settings.max_output_tokens,
        },
    }
    if not cloud:
        payload["think"] = False
        payload["format"] = response_model.model_json_schema()
    headers = {"Content-Type": "application/json"}
    if api_key is not None:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{settings.base_url}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers=headers,
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(
            request,
            timeout=settings.request_timeout_seconds,
        ) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:2000]
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama 연결 실패: {exc.reason}") from exc
    latency = time.monotonic() - started
    try:
        value = json.loads(raw)
        if value.get("error"):
            raise RuntimeError(f"Ollama 오류: {str(value['error'])[:2000]}")
        content = value["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("message.content가 문자열이 아닙니다")
        parsed = response_model.model_validate_json(content)
    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Ollama 구조화 응답이 유효하지 않습니다: {exc}") from exc
    return parsed, value, latency


def _ollama_api_key(settings: ProviderSettings) -> str | None:
    if settings.api_key_env is None:
        return None
    api_key = os.environ.get(settings.api_key_env)
    if not api_key:
        raise ValueError(
            f"환경 변수 {settings.api_key_env}에 Ollama API 키가 없습니다"
        )
    return api_key


class OllamaProvider:
    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings
        self.api_key = _ollama_api_key(settings)

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        parsed, response, latency = _ollama_chat(
            self.settings,
            request.prompt,
            DisclosureAnswer,
            self.api_key,
        )
        assert isinstance(parsed, DisclosureAnswer)
        return ProviderResponse(
            result=parsed,
            requested_model=self.settings.model,
            actual_model=str(response.get("model") or self.settings.model),
            usage=ModelUsage(
                input_tokens=response.get("prompt_eval_count"),
                output_tokens=response.get("eval_count"),
            ),
            latency_seconds=latency,
        )


class OllamaOptimizerProvider:
    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings
        self.api_key = _ollama_api_key(settings)

    def propose(self, request: OptimizationRequest) -> OptimizerResponse:
        parsed, response, latency = _ollama_chat(
            self.settings,
            request.prompt,
            PromptCandidate,
            self.api_key,
        )
        assert isinstance(parsed, PromptCandidate)
        return OptimizerResponse(
            result=parsed,
            requested_model=self.settings.model,
            actual_model=str(response.get("model") or self.settings.model),
            usage=ModelUsage(
                input_tokens=response.get("prompt_eval_count"),
                output_tokens=response.get("eval_count"),
            ),
            latency_seconds=latency,
        )


def _nvidia_nim_api_key(settings: ProviderSettings) -> str:
    assert settings.api_key_env is not None
    api_key = os.environ.get(settings.api_key_env)
    if not api_key:
        raise ValueError(
            f"환경 변수 {settings.api_key_env}에 NVIDIA NIM API 키가 없습니다"
        )
    return api_key


def _nvidia_nim_chat(
    settings: ProviderSettings,
    prompt: str,
    response_model: type[BaseModel],
    api_key: str,
) -> tuple[BaseModel, dict, float]:
    schema = response_model.model_json_schema()
    schema_instruction = (
        "반드시 아래 JSON Schema를 충족하는 JSON 객체 하나만 반환하십시오. "
        "Markdown 코드 블록이나 JSON 밖의 설명을 추가하지 마십시오.\n"
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )
    payload = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": schema_instruction},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": settings.temperature,
        "max_tokens": settings.max_output_tokens,
    }
    if settings.top_p is not None:
        payload["top_p"] = settings.top_p
    if settings.enable_thinking is not None:
        payload["chat_template_kwargs"] = {
            "enable_thinking": settings.enable_thinking,
        }
    request = urllib.request.Request(
        f"{settings.base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(
            request,
            timeout=settings.request_timeout_seconds,
        ) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:2000]
        raise RuntimeError(f"NVIDIA NIM HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"NVIDIA NIM 연결 실패: {exc.reason}") from exc
    latency = time.monotonic() - started
    try:
        value = json.loads(raw)
        content = value["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("choices[0].message.content가 문자열이 아닙니다")
        parsed = response_model.model_validate_json(content)
    except (IndexError, KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"NVIDIA NIM 구조화 응답이 유효하지 않습니다: {exc}") from exc
    return parsed, value, latency


class NvidiaNimProvider:
    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings
        self.api_key = _nvidia_nim_api_key(settings)

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        parsed, response, latency = _nvidia_nim_chat(
            self.settings,
            request.prompt,
            DisclosureAnswer,
            self.api_key,
        )
        assert isinstance(parsed, DisclosureAnswer)
        usage = response.get("usage") or {}
        return ProviderResponse(
            result=parsed,
            requested_model=self.settings.model,
            actual_model=str(response.get("model") or self.settings.model),
            usage=ModelUsage(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            ),
            latency_seconds=latency,
        )


class NvidiaNimOptimizerProvider:
    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings
        self.api_key = _nvidia_nim_api_key(settings)

    def propose(self, request: OptimizationRequest) -> OptimizerResponse:
        parsed, response, latency = _nvidia_nim_chat(
            self.settings,
            request.prompt,
            PromptCandidate,
            self.api_key,
        )
        assert isinstance(parsed, PromptCandidate)
        usage = response.get("usage") or {}
        return OptimizerResponse(
            result=parsed,
            requested_model=self.settings.model,
            actual_model=str(response.get("model") or self.settings.model),
            usage=ModelUsage(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            ),
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


class RoleRecordedProvider:
    """v3 fixture를 역할·sample·prompt 종류·attempt 조합으로 재생한다."""

    def __init__(self, path: str | Path, model: str) -> None:
        self.model = model
        self.rows: dict[tuple[str, str, str, int], dict] = {}
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                key = (
                    str(row["provider_role"]),
                    str(row["sample_id"]),
                    str(row.get("prompt_variant", "baseline")),
                    int(row.get("attempt", 0)),
                )
                if key in self.rows:
                    raise ValueError(f"중복된 recorded 응답 키입니다: {key}")
                self.rows[key] = row

    def _row(self, role: str, sample_id: str, prompt_variant: str, attempt: int) -> dict:
        key = (role, sample_id, prompt_variant, attempt)
        if key not in self.rows:
            raise KeyError(f"저장 응답이 없습니다: {key}")
        return self.rows[key]

    @staticmethod
    def _usage(row: dict) -> ModelUsage:
        return ModelUsage.model_validate(row.get("usage", {}))

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        started = time.monotonic()
        row = self._row(
            request.provider_role,
            request.sample_id,
            request.prompt_variant,
            request.attempt,
        )
        return ProviderResponse(
            result=DisclosureAnswer.model_validate(row["response"]),
            requested_model=self.model,
            actual_model=str(row.get("actual_model", self.model)),
            usage=self._usage(row),
            latency_seconds=time.monotonic() - started,
        )

    def propose(self, request: OptimizationRequest) -> OptimizerResponse:
        started = time.monotonic()
        row = self._row(
            request.provider_role,
            request.sample_id,
            request.prompt_variant,
            request.attempt,
        )
        return OptimizerResponse(
            result=PromptCandidate.model_validate(row["response"]),
            requested_model=self.model,
            actual_model=str(row.get("actual_model", self.model)),
            usage=self._usage(row),
            latency_seconds=time.monotonic() - started,
        )


def create_provider(settings: ProviderSettings, project_root: str | Path) -> ModelProvider:
    if settings.kind == "gemini":
        return GeminiProvider(settings)
    if settings.kind == "ollama":
        return OllamaProvider(settings)
    if settings.kind == "nvidia_nim":
        return NvidiaNimProvider(settings)
    assert settings.recorded_responses is not None
    path = Path(settings.recorded_responses)
    if not path.is_absolute():
        path = Path(project_root) / path
    return RecordedProvider(path.resolve(), settings.model)


def _recorded_path(settings: ProviderSettings, project_root: str | Path) -> Path:
    assert settings.recorded_responses is not None
    path = Path(settings.recorded_responses)
    if not path.is_absolute():
        path = Path(project_root) / path
    return path.resolve()


def create_target_provider_v3(
    settings: ProviderSettings, project_root: str | Path
) -> ModelProvider:
    if settings.kind == "gemini":
        return GeminiProvider(settings)
    if settings.kind == "ollama":
        return OllamaProvider(settings)
    if settings.kind == "nvidia_nim":
        return NvidiaNimProvider(settings)
    return RoleRecordedProvider(_recorded_path(settings, project_root), settings.model)


def create_optimizer_provider_v3(
    settings: ProviderSettings, project_root: str | Path
) -> OptimizerProvider:
    if settings.kind == "gemini":
        return GeminiOptimizerProvider(settings)
    if settings.kind == "ollama":
        return OllamaOptimizerProvider(settings)
    if settings.kind == "nvidia_nim":
        return NvidiaNimOptimizerProvider(settings)
    return RoleRecordedProvider(_recorded_path(settings, project_root), settings.model)
