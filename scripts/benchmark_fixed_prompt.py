#!/usr/bin/env python3
"""optimizer 없이 고정된 DART QA prompt를 target 모델 하나에 평가한다."""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from dart_parser_workflow.config import (
    load_fixed_prompt_benchmark_settings,
    override_fixed_prompt_provider,
)
from dart_parser_workflow.dataset import load_cases_v3
from dart_parser_workflow.fixed_prompt_benchmark import run_fixed_prompt_benchmark


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="고정 DART QA prompt target 평가")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--split",
        choices=("development", "validation", "test", "all"),
        default="all",
    )
    parser.add_argument(
        "--sample-id",
        action="append",
        help="반복 지정 가능; 생략하면 선택 split 전체를 실행",
    )
    parser.add_argument(
        "--provider",
        choices=("gemini", "ollama", "nvidia_nim", "recorded"),
        help="target provider 종류 (config 값을 덮어씀)",
    )
    parser.add_argument("--model", help="target 모델명 (config 값을 덮어씀)")
    parser.add_argument(
        "--api-key-env",
        help="API 키가 든 환경변수 이름; 키 값 자체를 전달하지 마세요",
    )
    parser.add_argument("--base-url", help="target provider API base URL")
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    load_dotenv(root / ".env", override=False)
    settings = override_fixed_prompt_provider(
        load_fixed_prompt_benchmark_settings(args.config),
        target_kind=args.provider,
        target_model=args.model,
        target_api_key_env=args.api_key_env,
        target_base_url=args.base_url,
    )
    cases = load_cases_v3(
        args.cases,
        root,
        max_html_bytes=settings.workflow.max_html_bytes,
        requirements=settings.dataset,
    )
    summary = run_fixed_prompt_benchmark(
        cases,
        settings,
        args.output,
        root,
        split=args.split,
        sample_ids=args.sample_id,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["observed_status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
