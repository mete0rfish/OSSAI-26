from dart_parser_workflow.evaluation import normalize_scalar


def test_normalize_scalar_only_changes_unicode_and_whitespace() -> None:
    assert normalize_scalar(" １２３\n  원 ") == "123 원"
    assert normalize_scalar("123,456백만원") != normalize_scalar("123456백만원")
    assert normalize_scalar("2025-01-02") != normalize_scalar("2025.01.02")
