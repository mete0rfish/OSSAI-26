import json
from pathlib import Path

import pytest

from dart_parser_workflow.agent_workflow import (
    _claim_test_exposure,
    approve_agent_stage,
    develop_agent_workflow,
    load_agent_workflow_manifest,
    prepare_agent_workflow,
    run_agent_test,
    validate_agent_workflow,
)
from dart_parser_workflow.config import load_optimization_settings
from dart_parser_workflow.dataset import load_cases_v3
from dart_parser_workflow.providers import RoleRecordedProvider
from dart_parser_workflow.schemas import TestExposureV3 as ExposureV3

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "configs/prompt-optimization.recorded.yaml"
FIXTURE = ROOT / "tests/fixtures/v3-recorded-responses.jsonl"


def _inputs():
    settings = load_optimization_settings(CONFIG)
    cases = load_cases_v3(
        ROOT / "configs/cases.v3.example.jsonl",
        ROOT,
        requirements=settings.dataset,
    )
    return settings, cases


def _prepare_and_develop(tmp_path: Path):
    settings, cases = _inputs()
    workflow = tmp_path / "workflow"
    prepare_agent_workflow(cases, settings, workflow, ROOT, CONFIG)
    develop_agent_workflow(
        cases,
        settings,
        workflow,
        ROOT,
        CONFIG,
        "dev-1",
        target_provider=RoleRecordedProvider(FIXTURE, "recorded-target-v3"),
        optimizer_provider=RoleRecordedProvider(FIXTURE, "recorded-optimizer-v3"),
    )
    return workflow, settings, cases


def _prepare_validate(tmp_path: Path):
    workflow, settings, cases = _prepare_and_develop(tmp_path)
    approve_agent_stage(workflow, "validation", "reviewer")
    validate_agent_workflow(
        cases,
        settings,
        workflow,
        ROOT,
        CONFIG,
        "val-1",
        target_provider=RoleRecordedProvider(FIXTURE, "recorded-target-v3"),
    )
    return workflow, settings, cases


def test_recorded_agent_workflow_requires_approvals_and_redacts_held_out(
    tmp_path: Path,
) -> None:
    workflow, settings, cases = _prepare_and_develop(tmp_path)
    manifest = load_agent_workflow_manifest(workflow)
    assert manifest.phase == "awaiting_validation_approval"

    with pytest.raises(ValueError, match="활성 validation 승인"):
        validate_agent_workflow(
            cases,
            settings,
            workflow,
            ROOT,
            CONFIG,
            "val-without-approval",
        )
    assert not (workflow / "validation/val-without-approval").exists()

    approve_agent_stage(workflow, "validation", "reviewer")
    validate_agent_workflow(
        cases,
        settings,
        workflow,
        ROOT,
        CONFIG,
        "val-1",
        target_provider=RoleRecordedProvider(FIXTURE, "recorded-target-v3"),
    )
    validation_rows = [
        json.loads(line)
        for path in (workflow / "validation/val-1").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert all("expected" not in row for row in validation_rows)

    with pytest.raises(ValueError, match="활성 test 승인"):
        run_agent_test(
            cases,
            settings,
            workflow,
            ROOT,
            CONFIG,
            "test-without-approval",
        )
    assert not (workflow / "test/test-without-approval").exists()

    approve_agent_stage(workflow, "test", "reviewer")
    run_agent_test(
        cases,
        settings,
        workflow,
        ROOT,
        CONFIG,
        "test-1",
        test_campaign_id="campaign-1",
        target_provider=RoleRecordedProvider(FIXTURE, "recorded-target-v3"),
    )
    manifest = load_agent_workflow_manifest(workflow)
    assert manifest.phase == "reporting"
    assert manifest.quality_status == "pass"
    test_rows = [
        json.loads(line)
        for line in (workflow / "test/test-1/test.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert all("expected" not in row for row in test_rows)
    assert len((workflow / "test-exposure.jsonl").read_text().splitlines()) == 2
    assert len(list((workflow / "approvals").glob("*.json"))) == 2


def test_validation_approval_is_bound_to_candidate_artifacts(tmp_path: Path) -> None:
    workflow, settings, cases = _prepare_and_develop(tmp_path)
    approve_agent_stage(workflow, "validation", "reviewer")
    candidate = workflow / "development/dev-1/candidate-prompt.md"
    candidate.write_text(candidate.read_text(encoding="utf-8") + "\n변조", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact가 변경"):
        validate_agent_workflow(
            cases,
            settings,
            workflow,
            ROOT,
            CONFIG,
            "val-1",
        )
    assert not (workflow / "validation/val-1").exists()


def test_expired_validation_approval_is_rejected(tmp_path: Path) -> None:
    workflow, settings, cases = _prepare_and_develop(tmp_path)
    approve_agent_stage(workflow, "validation", "reviewer")
    manifest = load_agent_workflow_manifest(workflow)
    approval_path = workflow / str(manifest.active_validation_approval)
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval["expires_at"] = "2000-01-01T00:00:00Z"
    approval_path.write_text(json.dumps(approval), encoding="utf-8")

    with pytest.raises(ValueError, match="만료"):
        validate_agent_workflow(
            cases,
            settings,
            workflow,
            ROOT,
            CONFIG,
            "val-1",
        )
    assert not (workflow / "validation/val-1").exists()


def test_test_exposure_requires_explicit_reexposure_approval(tmp_path: Path) -> None:
    path = tmp_path / "exposure.jsonl"
    first = ExposureV3(
        workflow_id="workflow",
        test_campaign_id="campaign-1",
        stage_run_id="test-1",
        sample_id="case-1",
        attempt=0,
        approval_id="approval-1",
        exposed_at="2026-01-01T00:00:00Z",
    )
    second = first.model_copy(
        update={
            "test_campaign_id": "campaign-2",
            "stage_run_id": "test-2",
            "approval_id": "approval-2",
        }
    )
    _claim_test_exposure(path, first, set())
    with pytest.raises(PermissionError, match="재노출"):
        _claim_test_exposure(path, second, set())
    _claim_test_exposure(path, second, {"case-1"})


def test_prepare_refuses_existing_workflow_directory(tmp_path: Path) -> None:
    settings, cases = _inputs()
    workflow = tmp_path / "existing"
    workflow.mkdir()

    with pytest.raises(FileExistsError):
        prepare_agent_workflow(cases, settings, workflow, ROOT, CONFIG)


def test_test_approval_cannot_be_created_before_validation(tmp_path: Path) -> None:
    workflow, _, _ = _prepare_and_develop(tmp_path)

    with pytest.raises(ValueError, match="test 승인을 만들 수 없는 phase"):
        approve_agent_stage(workflow, "test", "reviewer")


def test_effective_settings_are_bound_to_workflow(tmp_path: Path) -> None:
    workflow, settings, cases = _prepare_and_develop(tmp_path)
    changed = settings.model_copy(
        update={
            "target_provider": settings.target_provider.model_copy(
                update={"temperature": 0.5}
            )
        }
    )
    approve_agent_stage(workflow, "validation", "reviewer")

    with pytest.raises(ValueError, match="config"):
        validate_agent_workflow(
            cases,
            changed,
            workflow,
            ROOT,
            CONFIG,
            "val-1",
        )
