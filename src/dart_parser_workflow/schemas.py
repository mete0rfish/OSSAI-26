"""워크플로의 입력·출력 스키마."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationCase(StrictModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    html_path: Path
    question: str = Field(min_length=1)
    expected: str

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question은 공백일 수 없습니다")
        return value


class CaseFile(StrictModel):
    cases: list[EvaluationCase] = Field(min_length=1)


class GeneratedParser(StrictModel):
    code: str = Field(min_length=1)


class GenerationRequest(StrictModel):
    sample_id: str
    attempt: int = Field(ge=0)
    prompt: str


class ModelUsage(StrictModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class ProviderResponse(StrictModel):
    code: str
    requested_model: str
    actual_model: str | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_seconds: float = Field(ge=0)


class DiagnosticResult(StrictModel):
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = None
    error: str | None = None


RunStatus = Literal[
    "passed",
    "wrong_answer",
    "input_error",
    "generation_error",
    "safety_rejected",
    "execution_error",
]


class AttemptResult(StrictModel):
    attempt: int = Field(ge=0)
    code_path: str | None = None
    error_kind: str | None = None
    error: str | None = None
    latency_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class CaseResult(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str
    sample_id: str
    html_path: str
    question: str
    expected: str
    extracted: str | None = None
    normalized_expected: str
    normalized_extracted: str | None = None
    passed: bool = False
    status: RunStatus
    prompt_sha256: str
    requested_model: str
    actual_model: str | None = None
    attempts: list[AttemptResult]
    diagnostic: DiagnosticResult | None = None


class RunSummary(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    results_file: str

    @classmethod
    def start_time(cls) -> datetime:
        return datetime.now(UTC)
