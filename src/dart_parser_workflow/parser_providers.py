"""기존 provider transport에 답·코드 응답 계약을 적용한다."""

from pathlib import Path
from typing import Protocol

from .config import ProviderSettings
from .parser_schemas import ParserAnswer, ParserProviderResponse
from .providers import (
    GeminiProvider,
    NvidiaNimProvider,
    OllamaProvider,
    RecordedProvider,
    _recorded_path,
)
from .schemas import GenerationRequest


class ParserProvider(Protocol):
    def generate(self, request: GenerationRequest) -> ParserProviderResponse: ...


class GeminiParserProvider(GeminiProvider):
    response_model = ParserAnswer
    response_type = ParserProviderResponse


class OllamaParserProvider(OllamaProvider):
    response_model = ParserAnswer
    response_type = ParserProviderResponse


class NvidiaNimParserProvider(NvidiaNimProvider):
    response_model = ParserAnswer
    response_type = ParserProviderResponse


class RecordedParserProvider(RecordedProvider):
    response_model = ParserAnswer
    response_type = ParserProviderResponse


def create_parser_provider(
    settings: ProviderSettings, project_root: Path
) -> ParserProvider:
    if settings.kind == "gemini":
        return GeminiParserProvider(settings)
    if settings.kind == "ollama":
        return OllamaParserProvider(settings)
    if settings.kind == "nvidia_nim":
        return NvidiaNimParserProvider(settings)
    return RecordedParserProvider(_recorded_path(settings, project_root), settings.model)
