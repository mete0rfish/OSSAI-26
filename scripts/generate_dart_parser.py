#!/usr/bin/env python3
"""HTML과 질문에서 답·근거·Python 파싱 코드를 생성한다 (실행하지 않음)."""

import argparse
import json
from pathlib import Path

import yaml
from dotenv import load_dotenv

from dart_parser_workflow.config import ParserGenerationSettings
from dart_parser_workflow.parser_generation import run_parser_generation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True, help="프로젝트 내부 상대 HTML 경로")
    parser.add_argument("--question", required=True)
    parser.add_argument("--html-sha256", help="입력 HTML hash를 알고 있다면 일치 여부 검사")
    parser.add_argument("--config", required=True, help="parser generation YAML 설정")
    parser.add_argument("--output", required=True, help="아직 존재하지 않는 결과 디렉터리")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--authorize-external-transmission", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    load_dotenv(root / ".env", override=False)
    settings = ParserGenerationSettings.model_validate(
        yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    )
    summary = run_parser_generation(
        args.html, args.question, settings, args.output, root,
        expected_html_sha256=args.html_sha256,
        authorize_external_transmission=args.authorize_external_transmission,
    )
    result = json.loads((Path(args.output) / "result.json").read_text(encoding="utf-8"))
    print(json.dumps(
        {"summary": summary.model_dump(mode="json"), "result": result},
        ensure_ascii=False, indent=2,
    ))
    return 0 if summary.observed_status == "complete" and summary.quality_status != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
