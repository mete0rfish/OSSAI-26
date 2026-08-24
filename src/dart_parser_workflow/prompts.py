"""파일 기반 DART 공시 질의응답 프롬프트."""

from __future__ import annotations

import re
from pathlib import Path

BASELINE_PROMPT_PATH = Path(__file__).parents[2] / "prompts/dart-qa-baseline.md"
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_REQUIRED_PLACEHOLDERS = {"question", "html"}


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
    return template.replace("{question}", question).replace("{html}", html)


def question_answer_prompt(question: str, html: str) -> str:
    return render_prompt(load_prompt(), question, html)
