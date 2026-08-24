#!/usr/bin/env python3
"""선택된 prompt로 원본·HTML 변형을 실행하고 평가한다."""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from dart_parser_workflow.config import (
    load_optimization_settings,
    override_optimization_providers,
)
from dart_parser_workflow.dataset import load_cases_v3
from dart_parser_workflow.robustness import run_html_robustness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DART HTML robustness 평가")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--optimization-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--reviews", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--target-provider",
        choices=("gemini", "ollama", "nvidia_nim", "recorded"),
        help="target provider 종류 (config 값을 덮어씀)",
    )
    parser.add_argument("--target-model", help="평가할 target 모델명 (config 값을 덮어씀)")
    parser.add_argument(
        "--target-api-key-env",
        help="target API 키가 든 환경변수 이름; 키 값 자체를 전달하지 마세요",
    )
    parser.add_argument("--target-base-url", help="target provider API base URL")
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    load_dotenv(root / ".env", override=False)
    settings = load_optimization_settings(args.config)
    settings = override_optimization_providers(
        settings,
        target_kind=args.target_provider,
        target_model=args.target_model,
        target_api_key_env=args.target_api_key_env,
        target_base_url=args.target_base_url,
    )
    cases = load_cases_v3(
        args.cases,
        root,
        max_html_bytes=settings.workflow.max_html_bytes,
        requirements=settings.dataset,
    )
    summary = run_html_robustness(
        cases,
        settings,
        args.optimization_dir,
        args.manifest,
        args.reviews,
        args.output,
        root,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["observed_status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
