import inspect
from pathlib import Path

from dart_parser_workflow.prompts import (
    QUESTION_PRESERVATION_INSTRUCTION,
    question_answer_prompt,
)


def test_question_answer_prompt_has_no_expected_answer_parameter() -> None:
    assert list(inspect.signature(question_answer_prompt).parameters) == ["question", "html"]


def test_question_answer_prompt_requests_answer_and_evidence() -> None:
    prompt = question_answer_prompt("질문", "<p>본문</p>")

    assert "질문" in prompt
    assert "<p>본문</p>" in prompt
    assert "evidence" in prompt
    assert "기대값" not in prompt
    assert prompt.count(QUESTION_PRESERVATION_INSTRUCTION) == 1


def test_all_repository_prompts_require_verbatim_user_questions() -> None:
    root = Path(__file__).parents[1]

    for name in ("dart-qa-baseline.md", "dart-qa-v2.md", "dart-qa-v3.md"):
        prompt = (root / "prompts" / name).read_text(encoding="utf-8")
        assert "질문을 요약·교정·보완·번역·재작성하지 말고" in prompt
