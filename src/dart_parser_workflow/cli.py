"""프로젝트의 명령행 진입점."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .config import load_cases, load_settings
from .workflow import run_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DART HTML 파서를 생성하고 기대값과 검증합니다")
    parser.add_argument("--cases", required=True, help="평가 사례 YAML")
    parser.add_argument("--config", required=True, help="실행 설정 YAML")
    parser.add_argument("--output", required=True, help="새 결과 디렉터리")
    parser.add_argument("--project-root", default=".", help="상대 경로의 기준 프로젝트 루트")
    parser.add_argument(
        "--no-diagnostics",
        action="store_true",
        help="DeepEval 보조 진단을 실행하지 않습니다",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.project_root).resolve()
    load_dotenv(root / ".env", override=False)
    os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

    settings = load_settings(args.config)
    if args.no_diagnostics:
        settings = settings.model_copy(
            update={"diagnostics": settings.diagnostics.model_copy(update={"enabled": False})}
        )
    cases = load_cases(args.cases, root)
    summary = run_workflow(cases, settings, args.output, root)
    print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if summary.failed == 0 else 1
