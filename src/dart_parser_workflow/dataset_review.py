"""v3 dataset의 사례별 사람 검토 승인 기록을 검증한다."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from .schemas import EvaluationCaseV3, StrictModel


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


def review_case_row(case: EvaluationCaseV3, project_root: str | Path) -> dict:
    root = Path(project_root).resolve()
    row = case.model_dump(mode="json")
    row["html_path"] = case.html_path.resolve().relative_to(root).as_posix()
    return row


def review_case_sha256(row: dict) -> str:
    payload = json.dumps(
        row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_approved_reviews(
    cases: list[EvaluationCaseV3],
    reviews_path: str | Path,
    project_root: str | Path,
) -> list[ReviewRow]:
    root = Path(project_root).resolve()
    path = Path(reviews_path)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"review 경로가 project root 밖입니다: {reviews_path}")
    case_hashes = {
        case.id: review_case_sha256(review_case_row(case, root)) for case in cases
    }
    reviews: list[ReviewRow] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                review = ReviewRow.model_validate_json(line)
            except ValueError as exc:
                raise ValueError(
                    f"review JSONL {line_number}행이 유효하지 않습니다: {exc}"
                ) from exc
            if review.case_id in seen:
                raise ValueError(f"중복된 review case_id입니다: {review.case_id}")
            if review.case_id not in case_hashes:
                raise ValueError(f"dataset에 없는 review case_id입니다: {review.case_id}")
            if review.case_sha256 != case_hashes[review.case_id]:
                raise ValueError(
                    f"review case SHA-256이 일치하지 않습니다: {review.case_id}"
                )
            seen.add(review.case_id)
            reviews.append(review)
    if not reviews:
        raise ValueError("review JSONL이 비어 있습니다")
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
        incomplete = sorted(
            name
            for name, passed in review.checks.model_dump().items()
            if passed is not True
        )
        if incomplete:
            raise ValueError(
                f"review check가 완료되지 않았습니다: {review.case_id}={incomplete}"
            )
    return reviews
