"""답·Python 코드 생성 전용 계약. 기존 QA 응답 계약은 변경하지 않는다."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .schemas import DisclosureAnswer, ProviderResponse, StrictModel


class ParserAnswer(DisclosureAnswer):
    python_code: str | None = Field(max_length=50_000)

    @model_validator(mode="after")
    def validate_code(self) -> ParserAnswer:
        if self.abstained:
            if self.python_code is not None:
                raise ValueError("답변 보류 시 python_code는 null이어야 합니다")
            if not self.abstention_reason or not self.abstention_reason.strip():
                raise ValueError("답변 보류 이유는 비어 있을 수 없습니다")
        elif not self.python_code or not self.python_code.strip():
            raise ValueError("일반 답변에는 python_code가 필요합니다")
        elif self.answer == "답변 보류" or self.abstention_reason is not None:
            raise ValueError("일반 답변은 보류 상태와 혼합할 수 없습니다")
        return self


class ParserProviderResponse(ProviderResponse):
    result: ParserAnswer


class ParserCodeCheck(StrictModel):
    status: Literal["valid", "invalid", "not_applicable"]
    syntax_valid: bool | None = None
    entrypoint_valid: bool | None = None
    issues: list[str] = Field(default_factory=list)
    execution_status: Literal["not_run"] = "not_run"
    correctness: Literal["inconclusive"] = "inconclusive"


class ParserGenerationResult(StrictModel):
    schema_version: Literal[4] = 4
    artifact_type: Literal["parser_generation"] = "parser_generation"
    run_id: str
    html_path: str
    html_sha256: str
    question: str
    prompt_sha256: str
    response_schema_sha256: str
    checker_sha256: str
    git_sha: str | None
    git_dirty: bool | None
    status: Literal["answered", "abstained", "generation_error"]
    response: ParserProviderResponse | None = None
    code_check: ParserCodeCheck | None = None
    code_sha256: str | None = None
    evidence_in_document: bool | None = None
    answer_in_evidence: bool | None = None
    error: str | None = None


class ParserGenerationSummary(StrictModel):
    schema_version: Literal[4] = 4
    artifact_type: Literal["parser_generation"] = "parser_generation"
    run_id: str
    observed_status: Literal["complete", "partial", "not_run"]
    quality_status: Literal["fail", "inconclusive"] = "inconclusive"
    expected_answers_used: Literal[False] = False
    code_execution_status: Literal["not_run"] = "not_run"
    error: str | None = None
