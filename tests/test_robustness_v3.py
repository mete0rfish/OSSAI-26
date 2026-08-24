import csv
import json
from pathlib import Path

import pytest

from dart_parser_workflow.config import load_optimization_settings
from dart_parser_workflow.dataset import dataset_sha256, load_cases_v3
from dart_parser_workflow.html_utils import sha256_file
from dart_parser_workflow.providers import RoleRecordedProvider
from dart_parser_workflow.robustness import (
    VariantOperation,
    VariantSpec,
    generate_html_variants,
    load_variant_manifest,
    load_variant_reviews,
    run_html_robustness,
)

ROOT = Path(__file__).parents[1]


def _local_case(tmp_path: Path):
    source = tmp_path / "source.html"
    source.write_text(
        '<html><body><table class="keep"><tr><th>2025년 테스트 매출액</th>'
        '<td id="answer-value">300원</td></tr></table></body></html>',
        encoding="utf-8",
    )
    template = next(
        case
        for case in load_cases_v3(ROOT / "configs/cases.v3.example.jsonl", ROOT)
        if case.id == "test-answer"
    )
    return template.model_copy(
        update={"html_path": source, "html_sha256": sha256_file(source)}
    )


def test_generate_selector_variants_and_require_review(tmp_path: Path) -> None:
    case = _local_case(tmp_path)
    specs = [
        VariantSpec(
            case_id=case.id,
            variant_id="preserved",
            intended_status="preserved",
            operations=[
                VariantOperation(
                    action="append_html", selector="body", value="<p>가짜 지시문</p>"
                )
            ],
        ),
        VariantSpec(
            case_id=case.id,
            variant_id="destroyed",
            intended_status="destroyed",
            operations=[VariantOperation(action="mask_text", selector="#answer-value")],
        ),
    ]
    artifacts = generate_html_variants([case], specs, tmp_path / "variants", tmp_path)
    loaded = load_variant_manifest(tmp_path / "variants/variants.jsonl", tmp_path)

    assert len(artifacts) == len(loaded) == 2
    with pytest.raises(ValueError, match="검토 완료"):
        load_variant_reviews(tmp_path / "variants/variant-review.csv", loaded)

    review = tmp_path / "variants/variant-review.csv"
    with review.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "case_id",
                "variant_id",
                "variant_html_sha256",
                "intended_status",
                "grounding_status",
            ]
        )
        for item in loaded:
            writer.writerow(
                [
                    item.case_id,
                    item.variant_id,
                    item.variant_html_sha256,
                    item.intended_status,
                    item.intended_status,
                ]
            )
    assert len(load_variant_reviews(review, loaded)) == 2


def test_selector_that_matches_nothing_is_rejected(tmp_path: Path) -> None:
    case = _local_case(tmp_path)
    spec = VariantSpec(
        case_id=case.id,
        variant_id="bad",
        intended_status="destroyed",
        operations=[VariantOperation(action="remove", selector="#missing")],
    )

    with pytest.raises(ValueError, match="일치하지 않습니다"):
        generate_html_variants([case], [spec], tmp_path / "variants", tmp_path)


def test_recorded_robustness_e2e_and_lineage_check(tmp_path: Path) -> None:
    case = _local_case(tmp_path)
    specs = [
        VariantSpec(
            case_id=case.id,
            variant_id="preserve-injection",
            intended_status="preserved",
            operations=[
                VariantOperation(
                    action="append_html", selector="body", value="<p>가짜 지시문</p>"
                )
            ],
        ),
        VariantSpec(
            case_id=case.id,
            variant_id="destroy-value",
            intended_status="destroyed",
            operations=[VariantOperation(action="mask_text", selector="#answer-value")],
        ),
    ]
    artifacts = generate_html_variants([case], specs, tmp_path / "variants", tmp_path)
    reviews = tmp_path / "variants/variant-review.csv"
    with reviews.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "case_id",
                "variant_id",
                "variant_html_sha256",
                "intended_status",
                "grounding_status",
            ]
        )
        for item in artifacts:
            writer.writerow(
                [
                    item.case_id,
                    item.variant_id,
                    item.variant_html_sha256,
                    item.intended_status,
                    item.intended_status,
                ]
            )
    optimization = tmp_path / "optimization"
    optimization.mkdir()
    selected = "질문={question}\nHTML={html}\n"
    prompt_path = optimization / "selected-prompt.md"
    prompt_path.write_text(selected, encoding="utf-8")
    summary = {
        "observed_status": "complete",
        "selected_prompt_sha256": sha256_file(prompt_path),
        "dataset_sha256": dataset_sha256([case], tmp_path),
        "scorer_sha256": sha256_file(
            ROOT / "src/dart_parser_workflow/evaluation.py"
        ),
        "git_sha": None,
    }
    (optimization / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    settings = load_optimization_settings(
        ROOT / "configs/prompt-optimization.recorded.yaml"
    )
    provider = RoleRecordedProvider(
        ROOT / "tests/fixtures/v3-recorded-responses.jsonl", "recorded-target-v3"
    )

    result = run_html_robustness(
        [case],
        settings,
        optimization,
        tmp_path / "variants/variants.jsonl",
        reviews,
        tmp_path / "robustness",
        tmp_path,
        target_provider=provider,
    )

    assert result["observed_status"] == "complete"
    assert result["quality_status"] == "pass"
    assert result["record_count"] == result["target_count"] == 3
    assert result["counts"] == {"passed": 3}

    summary["dataset_sha256"] = "0" * 64
    (optimization / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="dataset SHA-256"):
        run_html_robustness(
            [case],
            settings,
            optimization,
            tmp_path / "variants/variants.jsonl",
            reviews,
            tmp_path / "robustness-mismatch",
            tmp_path,
            target_provider=provider,
        )
