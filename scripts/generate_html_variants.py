#!/usr/bin/env python3
"""검토할 DART HTML 변형과 manifest를 생성한다."""

import argparse
import json
from pathlib import Path

from dart_parser_workflow.config import load_optimization_settings
from dart_parser_workflow.dataset import load_cases_v3
from dart_parser_workflow.robustness import (
    generate_html_variants,
    load_variant_specs,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DART HTML robustness 변형 생성")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--specs", required=True)
    parser.add_argument("--output", required=True)
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
    artifacts = generate_html_variants(
        cases,
        load_variant_specs(args.specs),
        args.output,
        root,
        max_html_bytes=settings.workflow.max_html_bytes,
    )
    print(json.dumps({"generated": len(artifacts)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
