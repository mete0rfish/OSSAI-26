"""기대 정답과 완전히 분리된 파서 생성 프롬프트."""

from __future__ import annotations

SYSTEM_RULES = """당신은 저장된 DART 공시 HTML을 읽는 Python 파서를 작성한다.
반드시 JSON 객체 {"code": "..."}만 반환한다.
코드는 extract(html: str) -> str 함수를 정의해야 하며 단일 문자열만 반환한다.
허용 라이브러리는 bs4, re, html, unicodedata, datetime, decimal, typing이다.
파일, 네트워크, 환경 변수, 프로세스, 동적 코드 실행을 사용하지 않는다.
모듈을 import할 때 실행되는 부수 효과를 만들지 않는다.
HTML 구조와 레이블을 이용해 값을 찾고, 특정 결과값을 상수로 반환하지 않는다.
값을 찾지 못하면 예외를 발생시켜 실패 원인이 드러나게 한다."""


def generation_prompt(question: str, html: str) -> str:
    return f"""{SYSTEM_RULES}

[질문]
{question}

[HTML]
{html}
"""


def repair_prompt(question: str, html: str, previous_code: str, error: str) -> str:
    return f"""{SYSTEM_RULES}

이전 코드가 검사 또는 실행에 실패했다. 오류만 고쳐 전체 코드를 다시 반환한다.
정답에 관한 정보는 제공되지 않는다.

[질문]
{question}

[이전 코드]
{previous_code}

[오류]
{error}

[HTML]
{html}
"""
