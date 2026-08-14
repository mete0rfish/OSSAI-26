from pathlib import Path

import pytest

from dart_parser_workflow.config import load_cases, load_settings

ROOT = Path(__file__).parents[1]


def test_load_example_settings_and_cases() -> None:
    settings = load_settings(ROOT / "configs/recorded.yaml")
    cases = load_cases(ROOT / "configs/cases.example.yaml", ROOT)

    assert settings.provider.kind == "recorded"
    assert cases[0].html_path == (ROOT / "local-data/example.html").resolve()


def test_duplicate_case_ids_are_rejected(tmp_path: Path) -> None:
    case_file = tmp_path / "cases.yaml"
    case_file.write_text(
        """cases:
  - id: same
    html_path: first.html
    question: first
    expected: one
  - id: same
    html_path: second.html
    question: second
    expected: two
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="중복된 case id"):
        load_cases(case_file, tmp_path)
