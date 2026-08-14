"""기대 정답과 분리된 DART 공시 질의응답 프롬프트."""

from __future__ import annotations

SYSTEM_RULES = """당신은 DART 공시 HTML에서 질문에 해당하는 값을 찾는다.
반드시 지정된 JSON 스키마에 맞는 객체 하나만 반환한다.

답하기 전에 질문의 대상, 기간, 연결·별도 기준과 단위를 구분하고, 표에서는 올바른 행과
열의 교차값인지 확인한다. 답은 설명 문장이 아니라 질문이 요구한 값과 단위만 작성한다.

evidence의 quote에는 답뿐 아니라 그 답이 질문과 연결된다는 것을 확인할 수 있도록 항목명,
기간 또는 표 머리글을 포함한 공시의 연속된 원문을 복사한다. 공시에 없는 문장을 만들거나
요약하지 않는다. 답을 공시에서 확인할 수 없을 때만 answer를 정확히 '답변 보류'로 쓰고,
evidence를 빈 목록으로 반환한다."""


def question_answer_prompt(question: str, html: str) -> str:
    return f"""{SYSTEM_RULES}

[질문]
{question}

[DART 공시 HTML]
{html}
"""
