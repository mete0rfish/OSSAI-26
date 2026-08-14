"""YAML 설정과 평가 사례를 엄격하게 읽는다."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schemas import CaseFile, EvaluationCase


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderSettings(SettingsModel):
    kind: Literal["gemini", "recorded"]
    model: str = Field(min_length=1)
    api_key_env: str | None = Field(default=None, min_length=1)
    recorded_responses: str | None = None
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_output_tokens: int = Field(default=8192, gt=0)

    @model_validator(mode="after")
    def validate_provider(self) -> ProviderSettings:
        if self.kind == "gemini" and not self.api_key_env:
            raise ValueError("Gemini provider에는 api_key_env가 필요합니다")
        if self.kind == "recorded" and not self.recorded_responses:
            raise ValueError("recorded provider에는 recorded_responses가 필요합니다")
        return self


class WorkflowSettings(SettingsModel):
    max_html_bytes: int = Field(default=5_000_000, gt=0)
    max_repair_attempts: int = Field(default=2, ge=0, le=5)


class ExecutionSettings(SettingsModel):
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    memory_mb: int = Field(default=512, ge=64, le=4096)
    max_source_bytes: int = Field(default=100_000, gt=0)
    max_output_bytes: int = Field(default=16_384, gt=0)


class DiagnosticSettings(SettingsModel):
    enabled: bool = True
    model: str = Field(default="gemini-3.6-flash", min_length=1)
    api_key_env: str = Field(default="GEMINI_API_KEY", min_length=1)


class AppSettings(SettingsModel):
    artifact_schema_version: Literal[1] = 1
    provider: ProviderSettings
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    diagnostics: DiagnosticSettings = Field(default_factory=DiagnosticSettings)


def load_settings(path: str | Path) -> AppSettings:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return AppSettings.model_validate(value)


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
