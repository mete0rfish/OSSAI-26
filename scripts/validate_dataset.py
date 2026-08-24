#!/usr/bin/env python3
"""모델 호출 없이 v3 JSONL dataset을 검증한다."""

import argparse
import json
from pathlib import Path

from dart_parser_workflow.config import load_optimization_settings
from dart_parser_workflow.dataset import dataset_sha256, load_cases_v3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DART QA v3 dataset을 검증합니다")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    settings = load_optimization_settings(args.config)
    cases = load_cases_v3(
        args.cases,
        root,
        max_html_bytes=settings.workflow.max_html_bytes,
        requirements=settings.dataset,
    )
    print(
        json.dumps(
            {
                "valid": True,
                "count": len(cases),
                "dataset_sha256": dataset_sha256(cases, root),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
