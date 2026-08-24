"""YAML 설정과 평가 사례를 엄격하게 읽는다."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .schemas import CaseFile, EvaluationCase

ProviderKind = Literal["gemini", "ollama", "nvidia_nim", "recorded"]


def _default_base_url(kind: ProviderKind) -> str:
    if kind == "nvidia_nim":
        return "https://integrate.api.nvidia.com/v1"
    return "http://localhost:11434"


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderSettings(SettingsModel):
    kind: ProviderKind
    model: str = Field(min_length=1)
    api_key_env: str | None = Field(default=None, min_length=1)
    recorded_responses: str | None = None
    base_url: str = "http://localhost:11434"
    request_timeout_seconds: float = Field(default=120, gt=0)
    temperature: float = Field(default=0.0, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    enable_thinking: bool | None = None
    max_output_tokens: int = Field(default=8192, gt=0)

    @model_validator(mode="before")
    @classmethod
    def apply_kind_specific_base_url(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("kind") == "nvidia_nim":
            if "base_url" not in value:
                value = {**value, "base_url": _default_base_url("nvidia_nim")}
        return value

    @field_validator("base_url")
    @classmethod
    def base_url_must_be_http(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url은 http:// 또는 https:// URL이어야 합니다")
        return value

    @model_validator(mode="after")
    def validate_provider(self) -> ProviderSettings:
        if self.kind in {"gemini", "nvidia_nim"} and not self.api_key_env:
            raise ValueError(f"{self.kind} provider에는 api_key_env가 필요합니다")
        if (
            self.kind == "ollama"
            and self.base_url == "https://ollama.com"
            and not self.api_key_env
        ):
            raise ValueError("Ollama Cloud에는 api_key_env가 필요합니다")
        if self.kind == "recorded" and not self.recorded_responses:
            raise ValueError("recorded provider에는 recorded_responses가 필요합니다")
        return self


class WorkflowSettings(SettingsModel):
    max_html_bytes: int = Field(default=5_000_000, gt=0)


class AppSettings(SettingsModel):
    artifact_schema_version: Literal[2] = 2
    provider: ProviderSettings
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)


class PricingSettings(SettingsModel):
    verified_on: date
    input_usd_per_million_tokens: float = Field(ge=0)
    output_usd_per_million_tokens: float = Field(ge=0)


class ExecutionLimits(SettingsModel):
    max_requests: int = Field(default=1000, gt=0)
    max_attempts: int = Field(default=1000, gt=0)
    max_input_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)
    max_wall_seconds: float = Field(default=7200, gt=0)
    pricing: PricingSettings | None = None

    @model_validator(mode="after")
    def cost_limit_requires_pricing(self) -> ExecutionLimits:
        if self.max_cost_usd is not None and self.pricing is None:
            raise ValueError("max_cost_usd를 사용하려면 pricing이 필요합니다")
        return self


class SelectionSettings(SettingsModel):
    min_mean_improvement: float = Field(default=0.01, ge=0)


class DatasetRequirements(SettingsModel):
    split_counts: dict[Literal["development", "validation", "test"], int] = Field(
        default_factory=dict
    )
    minimum_tag_counts: dict[str, int] = Field(default_factory=dict)

    @field_validator("split_counts", "minimum_tag_counts")
    @classmethod
    def counts_must_be_non_negative(cls, value: dict[str, int]) -> dict[str, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("dataset 최소 개수는 음수일 수 없습니다")
        return value


class OptimizationSettings(SettingsModel):
    artifact_schema_version: Literal[3] = 3
    baseline_prompt: str = "prompts/dart-qa-baseline.md"
    target_provider: ProviderSettings
    optimizer_provider: ProviderSettings
    target_limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    optimizer_limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    selection: SelectionSettings = Field(default_factory=SelectionSettings)
    dataset: DatasetRequirements = Field(default_factory=DatasetRequirements)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)


def load_settings(path: str | Path) -> AppSettings:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return AppSettings.model_validate(value)


def load_optimization_settings(path: str | Path) -> OptimizationSettings:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return OptimizationSettings.model_validate(value)


def override_optimization_providers(
    settings: OptimizationSettings,
    *,
    target_kind: ProviderKind | None = None,
    target_model: str | None = None,
    target_api_key_env: str | None = None,
    target_base_url: str | None = None,
    optimizer_kind: ProviderKind | None = None,
    optimizer_model: str | None = None,
    optimizer_api_key_env: str | None = None,
    optimizer_base_url: str | None = None,
) -> OptimizationSettings:
    """CLI에서 모델명과 API key 환경변수 이름만 안전하게 교체한다."""

    def override(
        provider: ProviderSettings,
        *,
        kind: ProviderKind | None,
        model: str | None,
        api_key_env: str | None,
        base_url: str | None,
    ) -> ProviderSettings:
        value = provider.model_dump()
        if kind is not None:
            value["kind"] = kind
            if kind != provider.kind and base_url is None:
                value["base_url"] = _default_base_url(kind)
            if kind == "nvidia_nim" and api_key_env is None:
                value["api_key_env"] = "NVIDIA_NIM_API_KEY"
        if model is not None:
            value["model"] = model
        if api_key_env is not None:
            value["api_key_env"] = api_key_env
        if base_url is not None:
            value["base_url"] = base_url
        return ProviderSettings.model_validate(value)

    value = settings.model_dump()
    value["target_provider"] = override(
        settings.target_provider,
        kind=target_kind,
        model=target_model,
        api_key_env=target_api_key_env,
        base_url=target_base_url,
    ).model_dump()
    value["optimizer_provider"] = override(
        settings.optimizer_provider,
        kind=optimizer_kind,
        model=optimizer_model,
        api_key_env=optimizer_api_key_env,
        base_url=optimizer_base_url,
    ).model_dump()
    return OptimizationSettings.model_validate(value)


def load_cases(path: str | Path, project_root: str | Path) -> list[EvaluationCase]:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cases = CaseFile.model_validate(value).cases
    seen: set[str] = set()
    resolved: list[EvaluationCase] = []
    root = Path(project_root).resolve()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"중복된 case id입니다: {case.id}")
        seen.add(case.id)
        html_path = case.html_path
        if not html_path.is_absolute():
            html_path = root / html_path
        resolved.append(case.model_copy(update={"html_path": html_path.resolve()}))
    return resolved
