#!/usr/bin/env python3
"""DART QA v3 draft에 hash와 사람 검토 gate를 적용한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dart_parser_workflow.config import load_optimization_settings
from dart_parser_workflow.dataset import dataset_sha256, load_cases_v3, validate_cases_v3
from dart_parser_workflow.html_utils import read_html, sha256_bytes
from dart_parser_workflow.schemas import EvaluationCaseV3


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewChecks(StrictModel):
    answer: bool | None = None
    period: bool | None = None
    scope: bool | None = None
    unit: bool | None = None
    evidence: bool | None = None


class ReviewRow(StrictModel):
    schema_version: Literal[1] = 1
    case_id: str = Field(min_length=1)
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = ""
    decision: Literal["pending", "approved", "revise"] = "pending"
    checks: ReviewChecks = Field(default_factory=ReviewChecks)
    notes: str = ""


def _jsonl_rows(path: Path, label: str) -> list[dict]:
    rows: list[dict] = []
    try:
        handle = path.open(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{label} 파일을 읽을 수 없습니다: {path}: {exc}") from exc
    with handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                message = f"{label} {line_number}행 JSON이 유효하지 않습니다: {exc}"
                raise ValueError(message) from exc
            if not isinstance(value, dict):
                raise ValueError(f"{label} {line_number}행은 JSON 객체여야 합니다")
            rows.append(value)
    if not rows:
        raise ValueError(f"{label}이 비어 있습니다")
    return rows


def _within_root(path: Path, root: Path, label: str) -> Path:
    resolved = path if path.is_absolute() else root / path
    resolved = resolved.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} 경로가 project root 밖입니다: {path}")
    return resolved


def _new_output(path: Path) -> None:
    if path.exists():
        raise ValueError(f"기존 출력 파일을 덮어쓸 수 없습니다: {path}")


def _write_new_text(path: Path, value: str) -> None:
    _new_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.link(temporary, path)
    except FileExistsError as exc:
        raise ValueError(f"기존 출력 파일을 덮어쓸 수 없습니다: {path}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _jsonl(values: list[dict]) -> str:
    return "".join(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
        for value in values
    )


def _case_sha256(row: dict) -> str:
    payload = json.dumps(
        row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _relative_case(case: EvaluationCaseV3, root: Path) -> dict:
    row = case.model_dump(mode="json")
    row["html_path"] = case.html_path.resolve().relative_to(root).as_posix()
    return row


def materialize(
    *,
    drafts_path: Path,
    prepared_path: Path,
    reviews_path: Path,
    project_root: Path,
    max_html_bytes: int,
) -> dict:
    root = project_root.resolve()
    prepared = _within_root(prepared_path, root, "prepared 출력")
    reviews = _within_root(reviews_path, root, "review 출력")
    if prepared == reviews:
        raise ValueError("prepared와 review 출력 경로는 달라야 합니다")
    _new_output(prepared)
    _new_output(reviews)

    allowed_fields = set(EvaluationCaseV3.model_fields)
    cases: list[EvaluationCaseV3] = []
    for line_number, draft in enumerate(_jsonl_rows(drafts_path, "draft JSONL"), 1):
        unknown = sorted(set(draft) - allowed_fields)
        if unknown:
            raise ValueError(f"draft JSONL {line_number}행에 알 수 없는 필드가 있습니다: {unknown}")
        if "html_sha256" in draft:
            raise ValueError(
                f"draft JSONL {line_number}행에서 html_sha256을 제거하세요; 도구가 계산합니다"
            )
        value = dict(draft)
        value.setdefault("schema_version", 3)
        html_value = value.get("html_path")
        if not isinstance(html_value, str) or not html_value:
            raise ValueError(f"draft JSONL {line_number}행에 html_path가 필요합니다")
        html_path = _within_root(Path(html_value), root, "HTML")
        raw, _ = read_html(html_path, max_html_bytes)
        value["html_path"] = html_path.relative_to(root).as_posix()
        value["html_sha256"] = sha256_bytes(raw)
        try:
            case = EvaluationCaseV3.model_validate(value)
        except ValueError as exc:
            raise ValueError(f"draft JSONL {line_number}행이 유효하지 않습니다: {exc}") from exc
        cases.append(case.model_copy(update={"html_path": html_path}))

    validate_cases_v3(cases, max_html_bytes=max_html_bytes)
    prepared_rows = [_relative_case(case, root) for case in cases]
    review_rows = [
        ReviewRow(
            case_id=case.id,
            case_sha256=_case_sha256(row),
        ).model_dump(mode="json")
        for case, row in zip(cases, prepared_rows, strict=True)
    ]
    _write_new_text(prepared, _jsonl(prepared_rows))
    _write_new_text(reviews, _jsonl(review_rows))
    return {
        "materialized": True,
        "count": len(cases),
        "prepared": str(prepared),
        "reviews": str(reviews),
    }


def _approved_reviews(path: Path, case_hashes: dict[str, str]) -> list[ReviewRow]:
    reviews: list[ReviewRow] = []
    seen: set[str] = set()
    for line_number, value in enumerate(_jsonl_rows(path, "review JSONL"), 1):
        try:
            review = ReviewRow.model_validate(value)
        except ValueError as exc:
            raise ValueError(f"review JSONL {line_number}행이 유효하지 않습니다: {exc}") from exc
        if review.case_id in seen:
            raise ValueError(f"중복된 review case_id입니다: {review.case_id}")
        if review.case_id not in case_hashes:
            raise ValueError(f"dataset에 없는 review case_id입니다: {review.case_id}")
        if review.case_sha256 != case_hashes[review.case_id]:
            raise ValueError(f"review case SHA-256이 일치하지 않습니다: {review.case_id}")
        seen.add(review.case_id)
        reviews.append(review)

    missing = sorted(set(case_hashes) - seen)
    if missing:
        raise ValueError(f"review가 누락된 case입니다: {missing}")
    for review in reviews:
        if review.decision != "approved":
            raise ValueError(
                f"승인되지 않은 review입니다: {review.case_id}={review.decision}"
            )
        if not review.reviewer.strip():
            raise ValueError(f"reviewer가 비어 있습니다: {review.case_id}")
        checks = review.checks.model_dump()
        incomplete = sorted(name for name, passed in checks.items() if passed is not True)
        if incomplete:
            raise ValueError(f"review check가 완료되지 않았습니다: {review.case_id}={incomplete}")
    return reviews


def finalize(
    *,
    prepared_path: Path,
    reviews_path: Path,
    config_path: Path,
    output_path: Path,
    project_root: Path,
) -> dict:
    root = project_root.resolve()
    output = _within_root(output_path, root, "final dataset 출력")
    _new_output(output)
    settings = load_optimization_settings(config_path)
    cases = load_cases_v3(
        prepared_path,
        root,
        max_html_bytes=settings.workflow.max_html_bytes,
        requirements=settings.dataset,
    )
    final_rows = [_relative_case(case, root) for case in cases]
    case_hashes = {
        case.id: _case_sha256(row)
        for case, row in zip(cases, final_rows, strict=True)
    }
    reviews = _approved_reviews(reviews_path, case_hashes)
    digest = dataset_sha256(cases, root)
    _write_new_text(output, _jsonl(final_rows))
    return {
        "valid": True,
        "count": len(cases),
        "dataset_sha256": digest,
        "output": str(output),
        "reviewers": sorted({review.reviewer.strip() for review in reviews}),
        "all_reviews_approved": True,
        "live_provider_called": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DART QA v3 draft를 materialize하고 사람 승인 후 finalize합니다"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("--drafts", required=True, type=Path)
    materialize_parser.add_argument("--prepared", required=True, type=Path)
    materialize_parser.add_argument("--reviews", required=True, type=Path)
    materialize_parser.add_argument("--project-root", default=Path("."), type=Path)
    materialize_parser.add_argument("--max-html-bytes", default=5_000_000, type=int)

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--prepared", required=True, type=Path)
    finalize_parser.add_argument("--reviews", required=True, type=Path)
    finalize_parser.add_argument("--config", required=True, type=Path)
    finalize_parser.add_argument("--output", required=True, type=Path)
    finalize_parser.add_argument("--project-root", default=Path("."), type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "materialize":
            if args.max_html_bytes <= 0:
                raise ValueError("max-html-bytes는 0보다 커야 합니다")
            result = materialize(
                drafts_path=args.drafts,
                prepared_path=args.prepared,
                reviews_path=args.reviews,
                project_root=args.project_root,
                max_html_bytes=args.max_html_bytes,
            )
        else:
            result = finalize(
                prepared_path=args.prepared,
                reviews_path=args.reviews,
                config_path=args.config,
                output_path=args.output,
                project_root=args.project_root,
            )
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
