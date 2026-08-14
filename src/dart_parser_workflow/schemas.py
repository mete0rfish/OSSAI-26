"""워크플로의 입력·출력 스키마."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class Evidence(StrictModel):
    quote: str = Field(min_length=1)


class DisclosureAnswer(StrictModel):
    answer: str = Field(min_length=1)
    evidence: list[Evidence]
    confidence: float = Field(ge=0, le=1)
    abstained: bool
    abstention_reason: str | None = None

    @model_validator(mode="after")
    def validate_abstention(self) -> DisclosureAnswer:
        if self.abstained:
            if self.answer != "답변 보류":
                raise ValueError("답변 보류 시 answer는 '답변 보류'여야 합니다")
            if self.evidence:
                raise ValueError("답변 보류 시 evidence는 비어 있어야 합니다")
            if not self.abstention_reason:
                raise ValueError("답변 보류 시 abstention_reason이 필요합니다")
        elif not self.evidence:
            raise ValueError("일반 답변에는 evidence가 하나 이상 필요합니다")
        return self


class GenerationRequest(StrictModel):
    sample_id: str
    attempt: Literal[0] = 0
    prompt: str


class ModelUsage(StrictModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class ProviderResponse(StrictModel):
    result: DisclosureAnswer
    requested_model: str
    actual_model: str | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_seconds: float = Field(ge=0)


RunStatus = Literal[
    "passed",
    "wrong_answer",
    "ungrounded_evidence",
    "abstained",
    "input_error",
    "generation_error",
]


class CaseResult(StrictModel):
    schema_version: Literal[2] = 2
    run_id: str
    sample_id: str
    html_path: str
    question: str
    expected: str
    answer: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float | None = None
    abstained: bool = False
    abstention_reason: str | None = None
    normalized_expected: str
    normalized_answer: str | None = None
    answer_correct: bool = False
    evidence_in_document: bool = False
    answer_in_evidence: bool = False
    passed: bool = False
    status: RunStatus
    error: str | None = None
    prompt_sha256: str
    requested_model: str
    actual_model: str | None = None
    latency_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class RunSummary(StrictModel):
    schema_version: Literal[2] = 2
    run_id: str
    started_at: datetime
    finished_at: datetime
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    results_file: str
