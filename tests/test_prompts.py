import inspect

from dart_parser_workflow.prompts import generation_prompt, repair_prompt


def test_generation_prompt_has_no_expected_answer_parameter() -> None:
    assert list(inspect.signature(generation_prompt).parameters) == ["question", "html"]


def test_repair_prompt_contains_error_but_has_no_expected_answer_parameter() -> None:
    assert list(inspect.signature(repair_prompt).parameters) == [
        "question",
        "html",
        "previous_code",
        "error",
    ]
    prompt = repair_prompt("질문", "<p>본문</p>", "def extract(html): pass", "SyntaxError")
    assert "SyntaxError" in prompt
    assert "정답에 관한 정보는 제공되지 않는다" in prompt
