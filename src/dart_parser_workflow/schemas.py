"""워크플로의 입력·출력 스키마."""

from __future__ import annotations

from datetime import date, datetime
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
        if not value.strip():
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
    attempt: int = Field(default=0, ge=0)
    prompt: str
    provider_role: Literal["target", "optimizer"] = "target"
    prompt_variant: str = "baseline"


class BatchGenerationRequest(StrictModel):
    sample_ids: list[str] = Field(min_length=2)
    attempt: int = Field(default=0, ge=0)
    prompt: str
    provider_role: Literal["target"] = "target"
    prompt_variant: str = "baseline"

    @field_validator("sample_ids")
    @classmethod
    def sample_ids_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("batch sample_ids가 중복되었습니다")
        return value


class ModelUsage(StrictModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class ProviderResponse(StrictModel):
    result: DisclosureAnswer
    requested_model: str
    actual_model: str | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_seconds: float = Field(ge=0)


class BatchDisclosureAnswer(DisclosureAnswer):
    sample_id: str = Field(min_length=1)


class BatchDisclosureAnswers(StrictModel):
    answers: list[BatchDisclosureAnswer] = Field(min_length=2)

    @field_validator("answers")
    @classmethod
    def answers_must_have_unique_ids(
        cls, value: list[BatchDisclosureAnswer]
    ) -> list[BatchDisclosureAnswer]:
        sample_ids = [answer.sample_id for answer in value]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("batch 응답 sample_id가 중복되었습니다")
        return value


class BatchProviderResponse(StrictModel):
    result: BatchDisclosureAnswers
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


# Artifact schema v3 is intentionally additive.  The v2 models above remain the
# public contract of run_workflow.py.
Split = Literal["development", "validation", "test"]


class SourceMetadata(StrictModel):
    rcp_no: str = Field(min_length=1)
    url: str = Field(min_length=1)
    company: str = Field(min_length=1)
    report_type: str = Field(min_length=1)
    filing_date: date


class QuestionMetadata(StrictModel):
    metric: str = Field(min_length=1)
    period: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    answer_type: str = Field(min_length=1)


class ExpectedAnswerV3(StrictModel):
    answer: str = Field(min_length=1)
    accepted_answers: list[str] = Field(default_factory=list)
    abstained: bool = False
    evidence_quotes: list[str] = Field(default_factory=list)
    evidence_must_include: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_expected_answer(self) -> ExpectedAnswerV3:
        if any(not value.strip() for value in self.accepted_answers):
            raise ValueError("accepted_answers에는 빈 문자열을 넣을 수 없습니다")
        if len(self.accepted_answers) != len(set(self.accepted_answers)):
            raise ValueError("accepted_answers가 중복되었습니다")
        if self.abstained:
            if self.answer != "답변 보류":
                raise ValueError("unanswerable expected.answer는 '답변 보류'여야 합니다")
            if self.accepted_answers or self.evidence_quotes or self.evidence_must_include:
                raise ValueError("unanswerable 사례의 허용 답과 기대 근거는 비어 있어야 합니다")
        elif not self.evidence_quotes or not self.evidence_must_include:
            raise ValueError("answerable 사례에는 기대 인용과 문맥 anchor가 필요합니다")
        return self


class EvaluationCaseV3(StrictModel):
    schema_version: Literal[3] = 3
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    family_id: str = Field(min_length=1)
    split: Split
    html_path: Path
    html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: SourceMetadata
    question: str = Field(min_length=1)
    question_metadata: QuestionMetadata
    expected: ExpectedAnswerV3
    tags: list[str] = Field(min_length=1)

    @field_validator("question")
    @classmethod
    def v3_question_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question은 공백일 수 없습니다")
        return value

    @field_validator("tags")
    @classmethod
    def tags_must_be_unique_and_non_blank(cls, value: list[str]) -> list[str]:
        if any(not tag.strip() for tag in value) or len(value) != len(set(value)):
            raise ValueError("tags는 비어 있지 않은 고유 문자열이어야 합니다")
        return value


class ModelProbeCaseV3(StrictModel):
    """기대 답 없이 여러 target 모델의 응답을 수집하는 입력 사례."""

    schema_version: Literal[3] = 3
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    family_id: str = Field(min_length=1)
    split: Split
    html_path: Path
    html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: SourceMetadata
    question: str = Field(min_length=1)
    question_metadata: QuestionMetadata
    tags: list[str] = Field(min_length=1)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question은 공백일 수 없습니다")
        return value

    @field_validator("tags")
    @classmethod
    def tags_must_be_unique_and_non_blank(cls, value: list[str]) -> list[str]:
        if any(not tag.strip() for tag in value) or len(value) != len(set(value)):
            raise ValueError("tags는 비어 있지 않은 고유 문자열이어야 합니다")
        return value


ModelProbeStatus = Literal["answered", "abstained", "input_error", "generation_error"]


class ModelProbeResultV3(StrictModel):
    schema_version: Literal[3] = 3
    run_id: str
    sample_id: str
    family_id: str
    split: Split
    html_path: str
    html_sha256: str
    question: str
    answer: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float | None = None
    abstained: bool = False
    abstention_reason: str | None = None
    evidence_in_document: bool | None = None
    answer_in_evidence: bool | None = None
    status: ModelProbeStatus
    error: str | None = None
    prompt_sha256: str
    requested_model: str
    actual_model: str | None = None
    latency_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class PromptCandidate(StrictModel):
    prompt: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class OptimizationRequest(StrictModel):
    sample_id: str = "prompt-candidate"
    attempt: int = Field(default=0, ge=0)
    prompt: str
    provider_role: Literal["optimizer"] = "optimizer"
    prompt_variant: str = "optimizer"


class OptimizerResponse(StrictModel):
    result: PromptCandidate
    requested_model: str
    actual_model: str | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_seconds: float = Field(ge=0)


V3CaseStatus = Literal[
    "passed",
    "wrong_answer",
    "ungrounded_evidence",
    "missing_context",
    "unexpected_abstention",
    "unsafe_answer",
    "input_error",
    "generation_error",
]


class ScoreBreakdown(StrictModel):
    answer_correct: bool = False
    evidence_in_document: bool = False
    answer_in_evidence: bool = False
    expected_context_covered: bool = False
    missing_context: list[str] = Field(default_factory=list)
    quality_score: float = Field(ge=0, le=1)
    strict_pass: bool = False
    failure_reasons: list[str] = Field(default_factory=list)


class CaseResultV3(StrictModel):
    schema_version: Literal[3] = 3
    run_id: str
    sample_id: str
    family_id: str
    split: Split
    prompt_variant: str
    html_path: str
    html_sha256: str
    html_preprocessor: str = "raw"
    prepared_html_sha256: str | None = None
    raw_html_bytes: int | None = Field(default=None, ge=0)
    prepared_html_bytes: int | None = Field(default=None, ge=0)
    question: str
    expected: ExpectedAnswerV3
    answerable: bool
    answer: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float | None = None
    abstained: bool = False
    abstention_reason: str | None = None
    normalized_answer: str | None = None
    score: ScoreBreakdown
    status: V3CaseStatus
    error: str | None = None
    prompt_sha256: str
    requested_model: str
    actual_model: str | None = None
    latency_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


SelectionReason = Literal[
    "validation_improved",
    "validation_not_improved",
    "candidate_identical",
    "validation_errors_increased",
    "answerable_abstentions_increased",
    "strict_pass_rate_decreased",
    "optimizer_error",
    "validation_inconclusive",
]


class SelectionSummary(StrictModel):
    selected: Literal["baseline", "candidate", "none"]
    reason: SelectionReason
    baseline_mean: float
    candidate_mean: float | None = None
    baseline_strict_pass_rate: float
    candidate_strict_pass_rate: float | None = None
    baseline_error_count: int
    candidate_error_count: int | None = None
    baseline_answerable_abstentions: int
    candidate_answerable_abstentions: int | None = None


AgentPhase = Literal[
    "prepared",
    "developing",
    "awaiting_validation_approval",
    "validating",
    "selected",
    "awaiting_test_approval",
    "testing",
    "reporting",
]
ExecutionStatus = Literal["complete", "partial", "not_run"]
QualityStatus = Literal["pass", "fail", "inconclusive"]
ApprovalStatus = Literal["pending", "approved", "rejected"]


class AgentWorkflowManifestV3(StrictModel):
    schema_version: Literal[3] = 3
    workflow_id: str = Field(min_length=1)
    phase: AgentPhase
    execution_status: ExecutionStatus
    quality_status: QualityStatus
    approval_status: ApprovalStatus
    created_at: datetime
    updated_at: datetime
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scorer_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_case_ids: dict[Split, list[str]]
    split_manifest_sha256: dict[Split, str]
    review_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    latest_stage_run_id: str | None = None
    latest_stage: Literal["development", "validation", "test"] | None = None
    development_stage_run_id: str | None = None
    validation_stage_run_id: str | None = None
    test_stage_run_id: str | None = None
    active_validation_approval: str | None = None
    active_test_approval: str | None = None
    iteration: int = Field(default=0, ge=0)
    selected_prompt_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    selected_prompt_variant: Literal["baseline", "candidate"] | None = None
    test_campaign_id: str | None = None
    used_approval_ids: list[str] = Field(default_factory=list)


class StageRunManifestV3(StrictModel):
    schema_version: Literal[3] = 3
    workflow_id: str
    stage_run_id: str
    parent_run_id: str | None = None
    stage: Literal["development", "validation", "test"]
    execution_status: ExecutionStatus
    quality_status: QualityStatus
    started_at: datetime
    finished_at: datetime | None = None
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: dict[str, str] = Field(default_factory=dict)
    error_code: str | None = None


class ApprovalArtifactV3(StrictModel):
    schema_version: Literal[3] = 3
    approval_id: str = Field(min_length=1)
    workflow_id: str
    stage: Literal["validation", "test"]
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    expires_at: datetime
    nonce: str = Field(min_length=1)
    subject_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    external_transmission_authorized: bool = False
    allowed_reexposure_case_ids: list[str] = Field(default_factory=list)


class RepairTelemetryV3(StrictModel):
    sample_id: str
    prompt_variant: str
    error_code: str
    retryable: bool
    attempts: int = Field(ge=0)
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_seconds: float | None = Field(default=None, ge=0)


class DevelopmentFailureV3(StrictModel):
    sample_id: str
    question: str
    expected: ExpectedAnswerV3
    answer: str | None = None
    evidence: list[str] = Field(default_factory=list)
    quality_score: float = Field(ge=0, le=1)
    failure_reasons: list[str] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)


class TestExposureV3(StrictModel):
    schema_version: Literal[3] = 3
    workflow_id: str
    test_campaign_id: str
    stage_run_id: str
    sample_id: str
    attempt: int = Field(ge=0)
    approval_id: str
    exposed_at: datetime
