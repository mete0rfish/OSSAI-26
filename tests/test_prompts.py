import inspect

from dart_parser_workflow.prompts import question_answer_prompt


def test_question_answer_prompt_has_no_expected_answer_parameter() -> None:
    assert list(inspect.signature(question_answer_prompt).parameters) == ["question", "html"]


def test_question_answer_prompt_requests_answer_and_evidence() -> None:
    prompt = question_answer_prompt("질문", "<p>본문</p>")

    assert "질문" in prompt
    assert "<p>본문</p>" in prompt
    assert "evidence" in prompt
    assert "기대값" not in prompt
