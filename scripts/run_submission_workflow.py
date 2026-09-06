#!/usr/bin/env python3
"""세 Ollama Pro 모델과 두 prompt를 비교한 뒤 선택 조합만 Test한다."""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from dart_parser_workflow.config import load_submission_settings
from dart_parser_workflow.dataset import load_cases_v3
from dart_parser_workflow.submission import run_submission_workflow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DART QA 과제 제출 워크플로")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--reviews",
        help="사례별 승인 완료 review JSONL; live 실행에서는 필수",
    )
    parser.add_argument(
        "--authorize-external-transmission",
        action="store_true",
        help="DART HTML과 질문의 외부 전송을 이번 실행에 승인",
    )
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    load_dotenv(root / ".env", override=False)
    settings = load_submission_settings(args.config)
    if any(model.kind != "recorded" for model in settings.models):
        if not args.authorize_external_transmission:
            parser.error(
                "live 실행에는 --authorize-external-transmission이 필요합니다. "
                "실제 DART HTML과 질문이 외부 provider로 전송됩니다."
            )
        if not args.reviews:
            parser.error("live 실행에는 승인 완료된 --reviews JSONL이 필요합니다")
    cases = load_cases_v3(
        args.cases,
        root,
        max_html_bytes=settings.workflow.max_html_bytes,
        requirements=settings.dataset,
    )
    summary = run_submission_workflow(
        cases,
        settings,
        args.output,
        root,
        reviews_path=args.reviews,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["observed_status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
