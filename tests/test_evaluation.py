from dart_parser_workflow.evaluation import normalize_scalar, validate_evidence
from dart_parser_workflow.schemas import DisclosureAnswer, Evidence


def test_normalize_scalar_only_normalizes_unicode_and_whitespace() -> None:
    assert normalize_scalar("  １２３,４５６\n백만원 ") == "123,456 백만원"


def test_validate_evidence_uses_visible_document_text() -> None:
    answer = DisclosureAnswer(
        answer="123원",
        evidence=[Evidence(quote="매출액 123원")],
        confidence=1,
        abstained=False,
    )

    assert validate_evidence(answer, "<tr><th>매출액</th><td>123원</td></tr>") == (
        True,
        True,
    )
