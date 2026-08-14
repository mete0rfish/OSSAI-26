"""결정론 정답 비교와 선택적인 DeepEval 코드 품질 진단."""

from __future__ import annotations

import os
import re
import unicodedata

from .config import DiagnosticSettings
from .schemas import DiagnosticResult


def normalize_scalar(value: str) -> str:
    """의미 변환 없이 Unicode와 공백 표현만 정규화한다."""

    normalized = unicodedata.normalize("NFKC", value).strip()
    return re.sub(r"\s+", " ", normalized)


def evaluate_parser_quality(
    question: str,
    code: str,
    settings: DiagnosticSettings,
) -> DiagnosticResult | None:
    if not settings.enabled:
        return None
    api_key = os.environ.get(settings.api_key_env)
    if not api_key:
        return DiagnosticResult(
            error=f"환경 변수 {settings.api_key_env}에 진단용 API 키가 없습니다"
        )

    try:
        os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")
        os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
        from deepeval.metrics import GEval
        from deepeval.models import GeminiModel
        from deepeval.test_case import LLMTestCase, SingleTurnParams

        judge = GeminiModel(model=settings.model, api_key=api_key, temperature=0)
        metric = GEval(
            name="DART parser quality",
            evaluation_steps=[
                "질문에 등장하는 항목과 기간을 코드가 HTML 레이블 및 구조로 찾는지 확인한다.",
                "특정 추출 결과를 그대로 반환하는 하드코딩이나 취약한 위치 인덱스에 "
                "의존하는지 확인한다.",
                "코드가 간결하고 읽기 쉬우며 값이 없을 때 명확히 실패하는지 확인한다.",
                "실행 결과의 정답 여부는 판단하지 말고 파서 코드 품질만 0에서 1 사이로 평가한다.",
            ],
            evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
            threshold=None,
            model=judge,
            async_mode=False,
        )
        test_case = LLMTestCase(input=question, actual_output=code)
        metric.measure(test_case)
        return DiagnosticResult(
            score=float(metric.score) if metric.score is not None else None,
            reason=metric.reason,
        )
    except Exception as exc:  # 진단 실패는 주 평가 결과를 바꾸지 않는다.
        return DiagnosticResult(error=f"{type(exc).__name__}: {str(exc)[:2000]}")
