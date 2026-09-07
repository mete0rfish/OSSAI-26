"""v3 실행의 호출 계보와 역할별 예산을 관리한다."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import ExecutionLimits, RetrySettings
from .schemas import ModelUsage


class BudgetExceeded(RuntimeError):
    pass


TechnicalErrorCode = Literal[
    "timeout",
    "rate_limit",
    "transport",
    "server_error",
    "empty_response",
    "response_schema",
    "provider_error",
]


@dataclass(frozen=True)
class ErrorClassification:
    code: TechnicalErrorCode
    retryable: bool
    exception_type: str

    def summary(self) -> str:
        return f"{self.code}: {self.exception_type}"


def classify_provider_error(
    exc: Exception, retry: RetrySettings
) -> ErrorClassification:
    """Provider 예외를 원문 응답을 노출하지 않는 기술 오류로 분류한다."""

    exception_type = type(exc).__name__
    message = str(exc).lower()
    if isinstance(exc, TimeoutError) or "timed out" in message or "timeout" in message:
        return ErrorClassification("timeout", True, exception_type)
    if "http 429" in message or "rate limit" in message:
        return ErrorClassification("rate_limit", True, exception_type)
    if any(f"http {status}" in message for status in range(500, 600)):
        return ErrorClassification("server_error", True, exception_type)
    if "연결 실패" in message or "connection" in message:
        return ErrorClassification("transport", True, exception_type)
    if "empty" in message or "비어" in message:
        return ErrorClassification("empty_response", True, exception_type)
    if isinstance(exc, (ValueError, TypeError)):
        return ErrorClassification(
            "response_schema", retry.retry_schema_errors, exception_type
        )
    return ErrorClassification("provider_error", False, exception_type)


@dataclass
class UsageTotals:
    requests: int = 0
    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def as_dict(self) -> dict[str, int | float]:
        return {
            "requests": self.requests,
            "attempts": self.attempts,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 10),
        }


class CallLedger:
    def __init__(self, path: Path, limits: dict[str, ExecutionLimits]) -> None:
        self.path = path
        self.limits = limits
        self.started = time.monotonic()
        self.totals = {role: UsageTotals() for role in limits}
        self.actual_models = {role: set() for role in limits}
        self.error_counts = {role: 0 for role in limits}

    def before_request(self, role: str) -> None:
        limits, totals = self.limits[role], self.totals[role]
        self.assert_within_limits(role)
        if totals.requests >= limits.max_requests:
            raise BudgetExceeded(f"{role} 요청 상한을 초과했습니다")
        if totals.attempts >= limits.max_attempts:
            raise BudgetExceeded(f"{role} 시도 상한을 초과했습니다")
        if time.monotonic() - self.started >= limits.max_wall_seconds:
            raise BudgetExceeded(f"{role} 실행 시간 상한을 초과했습니다")
        totals.requests += 1
        totals.attempts += 1

    def record(
        self,
        *,
        role: str,
        sample_id: str,
        prompt_variant: str,
        prompt: str,
        requested_model: str,
        actual_model: str | None,
        usage: ModelUsage,
        latency_seconds: float | None,
        html_sha256: str | None = None,
        html_preprocessor: str | None = None,
        prepared_html_sha256: str | None = None,
        raw_html_bytes: int | None = None,
        prepared_html_bytes: int | None = None,
        estimated_input_tokens: int | None = None,
        batch_size: int = 1,
        attempt: int = 0,
        error: str | None = None,
    ) -> None:
        totals, limits = self.totals[role], self.limits[role]
        input_tokens = usage.input_tokens or 0
        output_tokens = usage.output_tokens or 0
        totals.input_tokens += input_tokens
        totals.output_tokens += output_tokens
        call_cost = 0.0
        if limits.pricing:
            call_cost = (
                input_tokens * limits.pricing.input_usd_per_million_tokens
                + output_tokens * limits.pricing.output_usd_per_million_tokens
            ) / 1_000_000
            totals.cost_usd += call_cost
        if actual_model:
            self.actual_models[role].add(actual_model)
        if error:
            self.error_counts[role] += 1
        row = {
            "provider_role": role,
            "sample_id": sample_id,
            "prompt_variant": prompt_variant,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "html_sha256": html_sha256,
            "html_preprocessor": html_preprocessor,
            "prepared_html_sha256": prepared_html_sha256,
            "raw_html_bytes": raw_html_bytes,
            "prepared_html_bytes": prepared_html_bytes,
            "estimated_input_tokens": estimated_input_tokens,
            "batch_size": batch_size,
            "attempt": attempt,
            "requested_model": requested_model,
            "actual_model": actual_model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": round(call_cost, 10),
            "cumulative_cost_usd": round(totals.cost_usd, 10),
            "latency_seconds": latency_seconds,
            "error": error,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()

    def assert_within_limits(self, role: str) -> None:
        self._check_consumed(role)

    def role_summary(self, role: str, requested_model: str) -> dict:
        return {
            "requested_model": requested_model,
            "actual_models": sorted(self.actual_models[role]),
            "error_count": self.error_counts[role],
            **self.totals[role].as_dict(),
        }

    def _check_consumed(self, role: str) -> None:
        limits, totals = self.limits[role], self.totals[role]
        if limits.max_input_tokens is not None and totals.input_tokens > limits.max_input_tokens:
            raise BudgetExceeded(f"{role} 입력 token 상한을 초과했습니다")
        if limits.max_output_tokens is not None and totals.output_tokens > limits.max_output_tokens:
            raise BudgetExceeded(f"{role} 출력 token 상한을 초과했습니다")
        if limits.max_cost_usd is not None and totals.cost_usd > limits.max_cost_usd:
            raise BudgetExceeded(f"{role} 비용 상한을 초과했습니다")
