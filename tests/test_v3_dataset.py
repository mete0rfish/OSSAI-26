from pathlib import Path

import pytest

from dart_parser_workflow.config import DatasetRequirements, load_optimization_settings
from dart_parser_workflow.dataset import load_cases_v3, validate_cases_v3
from dart_parser_workflow.prompts import render_prompt, validate_prompt_template

ROOT = Path(__file__).parents[1]


def test_load_v3_example_and_validate_split_requirements() -> None:
    settings = load_optimization_settings(ROOT / "configs/prompt-optimization.recorded.yaml")
    cases = load_cases_v3(
        ROOT / "configs/cases.v3.example.jsonl",
        ROOT,
        requirements=settings.dataset,
    )

    assert len(cases) == 6
    assert {case.split for case in cases} == {"development", "validation", "test"}
    assert all(case.html_path.is_absolute() for case in cases)


def test_family_split_leak_is_rejected() -> None:
    cases = load_cases_v3(ROOT / "configs/cases.v3.example.jsonl", ROOT)
    leaked = [
        case.model_copy(update={"family_id": "leaked"})
        if case.id in {"dev-answer", "val-answer"}
        else case
        for case in cases
    ]

    with pytest.raises(ValueError, match="여러 split"):
        validate_cases_v3(leaked, max_html_bytes=5_000_000)


def test_html_hash_mismatch_is_rejected() -> None:
    cases = load_cases_v3(ROOT / "configs/cases.v3.example.jsonl", ROOT)
    changed = [cases[0].model_copy(update={"html_sha256": "0" * 64}), *cases[1:]]

    with pytest.raises(ValueError, match="SHA-256"):
        validate_cases_v3(changed, max_html_bytes=5_000_000)


def test_prompt_renderer_allows_only_required_placeholders() -> None:
    template = "질문={question}\nHTML={html}"
    assert render_prompt(template, "Q", "<p>A</p>") == "질문=Q\nHTML=<p>A</p>"

    with pytest.raises(ValueError, match="placeholder"):
        validate_prompt_template("{question} {html} {expected}")
    with pytest.raises(ValueError, match="정확히 한 번"):
        validate_prompt_template("{question} {question} {html}")


def test_submission_dataset_requirements_check_answerability_and_families() -> None:
    cases = load_cases_v3(ROOT / "configs/cases.v3.example.jsonl", ROOT)
    requirements = DatasetRequirements(
        split_counts={"development": 2, "validation": 2, "test": 2},
        answerable_counts={"development": 1, "validation": 1, "test": 1},
        minimum_family_counts={"development": 2, "validation": 2, "test": 2},
    )

    validate_cases_v3(cases, max_html_bytes=5_000_000, requirements=requirements)

    with pytest.raises(ValueError, match="answerable 사례 수"):
        validate_cases_v3(
            cases,
            max_html_bytes=5_000_000,
            requirements=requirements.model_copy(
                update={"answerable_counts": {"development": 2}}
            ),
        )


def test_answerability_tag_must_match_expected_contract() -> None:
    cases = load_cases_v3(ROOT / "configs/cases.v3.example.jsonl", ROOT)
    changed = [
        cases[0].model_copy(update={"tags": ["unanswerable", "table"]}),
        *cases[1:],
    ]

    with pytest.raises(ValueError, match="answerability tag"):
        validate_cases_v3(changed, max_html_bytes=5_000_000)


def test_unique_metric_count_is_exact() -> None:
    cases = load_cases_v3(ROOT / "configs/cases.v3.example.jsonl", ROOT)

    with pytest.raises(ValueError, match="고유 metric 수"):
        validate_cases_v3(
            cases,
            max_html_bytes=5_000_000,
            requirements=DatasetRequirements(unique_metric_count=3),
        )
