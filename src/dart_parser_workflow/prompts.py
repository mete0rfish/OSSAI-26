"""파일 기반 DART 공시 질의응답 프롬프트."""

from __future__ import annotations

import json
import re
from pathlib import Path

BASELINE_PROMPT_PATH = Path(__file__).parents[2] / "prompts/dart-qa-baseline.md"
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_REQUIRED_PLACEHOLDERS = {"question", "html"}
QUESTION_PRESERVATION_INSTRUCTION = (
    "입력된 질문은 사용자가 제공한 원문입니다. 질문을 요약·교정·보완·번역·재작성하지 말고\n"
    "문자, 공백, 문장부호를 수정 없이 그대로 사용해 답합니다."
)


def load_prompt(path: str | Path = BASELINE_PROMPT_PATH) -> str:
    prompt = Path(path).read_text(encoding="utf-8")
    validate_prompt_template(prompt)
    return prompt


def validate_prompt_template(prompt: str) -> None:
    placeholders = set(_PLACEHOLDER.findall(prompt))
    if placeholders != _REQUIRED_PLACEHOLDERS:
        raise ValueError(
            "프롬프트 placeholder는 {question}, {html}을 각각 포함해야 합니다: "
            f"발견={sorted(placeholders)}"
        )
    for name in _REQUIRED_PLACEHOLDERS:
        if prompt.count("{" + name + "}") != 1:
            raise ValueError(f"프롬프트의 {{{name}}} placeholder는 정확히 한 번 필요합니다")


def render_prompt(template: str, question: str, html: str) -> str:
    validate_prompt_template(template)
    values = {"question": question, "html": html}
    rendered = _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)
    if QUESTION_PRESERVATION_INSTRUCTION in template:
        return rendered
    return QUESTION_PRESERVATION_INSTRUCTION + "\n\n" + rendered


def render_batch_prompt(
    template: str,
    questions: list[tuple[str, str]],
    html: str,
) -> str:
    """같은 공시의 여러 질문을 한 번에 처리하도록 기존 prompt 계약을 감싼다."""

    payload = [
        {"sample_id": sample_id, "question": question}
        for sample_id, question in questions
    ]
    batch_rule = (
        "[배치 실행 규칙]\n"
        "아래 공통 HTML에 대해 questions의 모든 질문을 각각 독립적으로 답하십시오. "
        "각 결과에는 입력과 동일한 sample_id를 넣고, questions와 정확히 같은 순서로 "
        "answers 배열에 한 번씩 반환하십시오. 공통 지침의 단수형 표현과 단일 응답 지시는 "
        "각 answers 원소에 적용하며, 최종 출력 형식은 배치 JSON 스키마를 따릅니다.\n\n"
        "[questions]\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\n\n[공통 풀이 지침]\n"
    )
    rendered = render_prompt(template, "위 questions 배열의 각 question", html)
    return batch_rule + rendered


def question_answer_prompt(question: str, html: str) -> str:
    return render_prompt(load_prompt(), question, html)
