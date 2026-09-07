#!/usr/bin/env python3
"""승인 기반 DART QA Agent 워크플로의 단계별 CLI."""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from dart_parser_workflow.agent_workflow import (
    approve_agent_stage,
    develop_agent_workflow,
    load_agent_workflow_manifest,
    prepare_agent_workflow,
    run_agent_test,
    validate_agent_workflow,
)
from dart_parser_workflow.config import load_optimization_settings
from dart_parser_workflow.dataset import load_cases_v3


def _common_inputs(parser: argparse.ArgumentParser, *, stage_run: bool = False) -> None:
    parser.add_argument("--cases", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--project-root", default=".")
    if stage_run:
        parser.add_argument("--stage-run-id", required=True)


def _load_inputs(args: argparse.Namespace):
    root = Path(args.project_root).resolve()
    load_dotenv(root / ".env", override=False)
    settings = load_optimization_settings(args.config)
    cases = load_cases_v3(
        args.cases,
        root,
        max_html_bytes=settings.workflow.max_html_bytes,
        requirements=settings.dataset,
    )
    return root, settings, cases


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DART QA Agent 워크플로")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="새 workflow와 manifest 생성")
    _common_inputs(prepare)
    prepare.add_argument("--reviews")

    develop = commands.add_parser("develop", help="Development 후보 생성·게이트")
    _common_inputs(develop, stage_run=True)
    develop.add_argument("--authorize-external-transmission", action="store_true")

    approve_validation = commands.add_parser(
        "approve-validation", help="봉인된 candidate의 Validation 승인"
    )
    approve_validation.add_argument("--workflow", required=True)
    approve_validation.add_argument("--approved-by", required=True)
    approve_validation.add_argument("--expires-in-hours", type=float, default=24)
    approve_validation.add_argument("--authorize-external-transmission", action="store_true")

    validate = commands.add_parser("validate", help="승인된 candidate Validation·선택")
    _common_inputs(validate, stage_run=True)

    approve_test = commands.add_parser(
        "approve-test", help="봉인된 selection의 Test 승인"
    )
    approve_test.add_argument("--workflow", required=True)
    approve_test.add_argument("--approved-by", required=True)
    approve_test.add_argument("--expires-in-hours", type=float, default=24)
    approve_test.add_argument("--authorize-external-transmission", action="store_true")
    approve_test.add_argument("--allow-reexposure-case", action="append", default=[])

    test = commands.add_parser("test", help="승인된 Test campaign 실행")
    _common_inputs(test, stage_run=True)
    test.add_argument("--test-campaign-id")

    status = commands.add_parser("status", help="현재 workflow manifest 출력")
    status.add_argument("--workflow", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "status":
        result = load_agent_workflow_manifest(args.workflow)
    elif args.command in {"approve-validation", "approve-test"}:
        stage = "validation" if args.command == "approve-validation" else "test"
        result = approve_agent_stage(
            args.workflow,
            stage,
            args.approved_by,
            external_transmission_authorized=args.authorize_external_transmission,
            expires_in_hours=args.expires_in_hours,
            allowed_reexposure_case_ids=(
                [] if stage == "validation" else args.allow_reexposure_case
            ),
        )
    else:
        root, settings, cases = _load_inputs(args)
        if args.command == "prepare":
            result = prepare_agent_workflow(
                cases,
                settings,
                args.workflow,
                root,
                args.config,
                reviews_path=args.reviews,
            )
        elif args.command == "develop":
            result = develop_agent_workflow(
                cases,
                settings,
                args.workflow,
                root,
                args.config,
                args.stage_run_id,
                authorize_external_transmission=args.authorize_external_transmission,
            )
        elif args.command == "validate":
            result = validate_agent_workflow(
                cases,
                settings,
                args.workflow,
                root,
                args.config,
                args.stage_run_id,
            )
        else:
            result = run_agent_test(
                cases,
                settings,
                args.workflow,
                root,
                args.config,
                args.stage_run_id,
                test_campaign_id=args.test_campaign_id,
            )
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
