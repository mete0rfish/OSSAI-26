#!/usr/bin/env python3
"""기대 답 없이 DART QA target 모델 응답을 수집한다."""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from dart_parser_workflow.config import (
    load_optimization_settings,
    override_optimization_providers,
)
from dart_parser_workflow.dataset import load_probe_cases_v3
from dart_parser_workflow.model_probe import run_model_probe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="정답 비공개 DART QA 모델 probe")
    parser.add_argument("--cases", required=True, help="expected가 없는 probe JSONL")
    parser.add_argument("--config", required=True, help="prompt·한도 기본 설정 YAML")
    parser.add_argument("--output", required=True, help="아직 존재하지 않는 결과 디렉터리")
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--split",
        choices=("development", "validation", "test", "all"),
        default="development",
        help="기본값은 수정용 development; held-out은 명시적으로 선택",
    )
    parser.add_argument(
        "--provider",
        choices=("gemini", "ollama", "nvidia_nim", "recorded"),
        help="target provider 종류 (config 값을 덮어씀)",
    )
    parser.add_argument("--model", help="실행할 target 모델명 (config 값을 덮어씀)")
    parser.add_argument(
        "--api-key-env",
        help="API 키가 든 환경변수 이름; 키 값 자체를 전달하지 마세요",
    )
    parser.add_argument(
        "--base-url",
        help="Ollama 또는 NVIDIA NIM API base URL",
    )
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    load_dotenv(root / ".env", override=False)
    settings = override_optimization_providers(
        load_optimization_settings(args.config),
        target_kind=args.provider,
        target_model=args.model,
        target_api_key_env=args.api_key_env,
        target_base_url=args.base_url,
    )
    cases = load_probe_cases_v3(
        args.cases,
        root,
        max_html_bytes=settings.workflow.max_html_bytes,
    )
    selected = cases if args.split == "all" else [c for c in cases if c.split == args.split]
    summary = run_model_probe(selected, settings, args.output, root)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["observed_status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
