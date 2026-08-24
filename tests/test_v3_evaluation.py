from pathlib import Path

from dart_parser_workflow.dataset import load_cases_v3
from dart_parser_workflow.evaluation import score_answer_v3
from dart_parser_workflow.schemas import DisclosureAnswer, Evidence

ROOT = Path(__file__).parents[1]


def _answer(value: str, quote: str) -> DisclosureAnswer:
    return DisclosureAnswer(
        answer=value,
        evidence=[Evidence(quote=quote)],
        confidence=0.9,
        abstained=False,
    )


def test_answerable_strict_score_and_missing_context() -> None:
    case = load_cases_v3(ROOT / "configs/cases.v3.example.jsonl", ROOT)[0]
    html = case.html_path.read_text(encoding="utf-8")

    score, status = score_answer_v3(
        case, _answer("100원", "2025년 개발 매출액 100원"), html
    )
    assert status == "passed"
    assert score.quality_score == 1
    assert score.strict_pass

    score, status = score_answer_v3(case, _answer("100원", "매출액 100원"), html)
    assert status == "missing_context"
    assert score.quality_score == 0.85
    assert score.missing_context == ["2025년", "개발 매출액"]


def test_unanswerable_uses_binary_safe_abstention_score() -> None:
    case = load_cases_v3(ROOT / "configs/cases.v3.example.jsonl", ROOT)[1]
    html = case.html_path.read_text(encoding="utf-8")
    abstention = DisclosureAnswer(
        answer="답변 보류",
        evidence=[],
        confidence=0,
        abstained=True,
        abstention_reason="문서에 값이 없음",
    )

    score, status = score_answer_v3(case, abstention, html)
    assert (score.quality_score, score.strict_pass, status) == (1, True, "passed")

    score, status = score_answer_v3(case, _answer("999원", "개발 영업이익 999원"), html)
    assert (score.quality_score, score.strict_pass, status) == (0, False, "unsafe_answer")
