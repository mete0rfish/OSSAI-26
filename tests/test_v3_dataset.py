import json
from pathlib import Path

import pytest

from dart_parser_workflow.config import DatasetRequirements, load_optimization_settings
from dart_parser_workflow.dataset import load_cases_v3, validate_cases_v3
from dart_parser_workflow.prompts import (
    QUESTION_PRESERVATION_INSTRUCTION,
    render_batch_prompt,
    render_prompt,
    validate_prompt_template,
)
from dart_parser_workflow.schemas import EvaluationCase, EvaluationCaseV3, ModelProbeCaseV3

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
    assert render_prompt(template, "Q", "<p>A</p>") == (
        QUESTION_PRESERVATION_INSTRUCTION + "\n\n질문=Q\nHTML=<p>A</p>"
    )

    with pytest.raises(ValueError, match="placeholder"):
        validate_prompt_template("{question} {html} {expected}")
    with pytest.raises(ValueError, match="정확히 한 번"):
        validate_prompt_template("{question} {question} {html}")


def test_prompt_renderer_preserves_user_question_verbatim() -> None:
    question = "  {html}을 문자 그대로 찾나요?\n{question}도 유지하세요!  "
    template = '출력={"answer":"값"}\n질문={question}\nHTML={html}'

    rendered = render_prompt(template, question, "<p>본문</p>")

    assert rendered == (
        QUESTION_PRESERVATION_INSTRUCTION
        + f'\n\n출력={{"answer":"값"}}\n질문={question}\nHTML=<p>본문</p>'
    )


def test_batch_prompt_preserves_each_json_question_value_verbatim() -> None:
    questions = [
        ("sample-a", "  첫 질문?  "),
        ("sample-b", "둘째\n질문 {html}!"),
    ]

    rendered = render_batch_prompt("{question}\n{html}", questions, "<p>본문</p>")
    payload = rendered.split("[questions]\n", 1)[1].split("\n\n[공통 풀이 지침]", 1)[0]

    assert json.loads(payload) == [
        {"sample_id": sample_id, "question": question}
        for sample_id, question in questions
    ]
    assert "요약·교정·보완·번역·재작성하지" in rendered
    assert rendered.count(QUESTION_PRESERVATION_INSTRUCTION) == 1


def test_question_schema_validation_does_not_trim_user_text() -> None:
    question = "  사용자가 입력한 질문?\n  "
    legacy = EvaluationCase(
        id="legacy",
        html_path=ROOT / "tests/fixtures/sample.html",
        question=question,
        expected="값",
    )
    case_data = load_cases_v3(ROOT / "configs/cases.v3.example.jsonl", ROOT)[0].model_dump()
    case_data["question"] = question
    v3 = EvaluationCaseV3.model_validate(case_data)
    probe_data = {key: value for key, value in case_data.items() if key != "expected"}
    probe = ModelProbeCaseV3.model_validate(probe_data)

    assert legacy.question == question
    assert v3.question == question
    assert probe.question == question


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
