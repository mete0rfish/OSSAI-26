from pathlib import Path

import pytest

from dart_parser_workflow.config import (
    ProviderSettings,
    SubmissionSettings,
    load_cases,
    load_settings,
    load_submission_settings,
)

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


def test_submission_config_pins_three_ollama_pro_models() -> None:
    settings = load_submission_settings(ROOT / "configs/submission.ollama-pro.yaml")

    assert [provider.model for provider in settings.models] == [
        "deepseek-v4-flash:0731",
        "gemma4:31b",
        "glm-5.3-flash",
    ]
    assert all(provider.base_url == "https://ollama.com" for provider in settings.models)
    assert settings.dataset.unique_metric_count == 9


def test_live_submission_rejects_non_ollama_provider() -> None:
    providers = [
        ProviderSettings(kind="gemini", model=f"model-{index}", api_key_env="KEY")
        for index in range(3)
    ]

    with pytest.raises(ValueError, match="Ollama Pro"):
        SubmissionSettings(
            baseline_prompt="baseline.md",
            baseline_prompt_sha256="0" * 64,
            candidate_prompt="candidate.md",
            candidate_prompt_sha256="1" * 64,
            models=providers,
        )
