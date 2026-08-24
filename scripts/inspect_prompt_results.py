#!/usr/bin/env python3
"""v3 prompt 최적화 결과를 간단한 표 형태로 요약한다."""

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="prompt 최적화 결과 확인")
    parser.add_argument("--optimization-dir", required=True)
    args = parser.parse_args(argv)
    root = Path(args.optimization_dir)
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    selection = summary.get("selection") or {}
    print(f"실행 상태: {summary['observed_status']}")
    print(f"품질 상태: {summary['quality_status']}")
    print(f"선택: {selection.get('selected', '-')}")
    print(f"선택 이유: {selection.get('reason', '-')}")
    print(f"baseline 평균: {selection.get('baseline_mean', '-')}")
    print(f"candidate 평균: {selection.get('candidate_mean', '-')}")
    print(
        "test 생성·선택 사용: "
        f"{summary.get('test_used_for_generation_or_selection', False)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
