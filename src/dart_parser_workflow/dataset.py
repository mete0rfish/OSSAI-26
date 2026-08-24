"""artifact schema v3 JSONL 평가 데이터 loader와 사전 검사."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from .config import DatasetRequirements
from .html_utils import normalize_text, read_html, sha256_bytes, visible_text
from .schemas import EvaluationCaseV3, ModelProbeCaseV3


def load_cases_v3(
    path: str | Path,
    project_root: str | Path,
    *,
    max_html_bytes: int = 5_000_000,
    requirements: DatasetRequirements | None = None,
) -> list[EvaluationCaseV3]:
    root = Path(project_root).resolve()
    rows: list[EvaluationCaseV3] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                case = EvaluationCaseV3.model_validate_json(line)
            except Exception as exc:
                raise ValueError(f"JSONL {line_number}행이 유효하지 않습니다: {exc}") from exc
            resolved = case.html_path if case.html_path.is_absolute() else root / case.html_path
            resolved = resolved.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(f"HTML 경로가 project root 밖입니다: {case.html_path}")
            rows.append(case.model_copy(update={"html_path": resolved}))
    if not rows:
        raise ValueError("v3 평가 사례가 비어 있습니다")
    validate_cases_v3(rows, max_html_bytes=max_html_bytes, requirements=requirements)
    return rows


def validate_cases_v3(
    cases: list[EvaluationCaseV3],
    *,
    max_html_bytes: int,
    requirements: DatasetRequirements | None = None,
) -> None:
    ids = [case.id for case in cases]
    duplicate_ids = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        raise ValueError(f"중복된 case id입니다: {duplicate_ids}")

    family_splits: dict[str, set[str]] = {}
    for case in cases:
        family_splits.setdefault(case.family_id, set()).add(case.split)
    leaked = sorted(family for family, splits in family_splits.items() if len(splits) > 1)
    if leaked:
        raise ValueError(f"family가 여러 split에 포함됩니다: {leaked}")

    for case in cases:
        raw, html = read_html(case.html_path, max_html_bytes)
        actual_hash = sha256_bytes(raw)
        if actual_hash != case.html_sha256:
            raise ValueError(f"HTML SHA-256이 일치하지 않습니다: {case.id}")
        document = visible_text(html)
        expected_quotes = [normalize_text(value) for value in case.expected.evidence_quotes]
        if any(quote not in document for quote in expected_quotes):
            raise ValueError(f"기대 인용이 HTML 화면 텍스트에 없습니다: {case.id}")
        joined_quotes = " ".join(expected_quotes)
        if (
            not case.expected.abstained
            and normalize_text(case.expected.answer) not in joined_quotes
        ):
            raise ValueError(f"기대 답이 기대 인용에 없습니다: {case.id}")
        if any(
            normalize_text(anchor) not in joined_quotes
            for anchor in case.expected.evidence_must_include
        ):
            raise ValueError(f"문맥 anchor가 기대 인용에 없습니다: {case.id}")

    active = requirements or DatasetRequirements()
    split_counts = Counter(case.split for case in cases)
    for split, expected_count in active.split_counts.items():
        if split_counts[split] != expected_count:
            raise ValueError(
                f"{split} 사례 수가 요구조건과 다릅니다: "
                f"actual={split_counts[split]}, expected={expected_count}"
            )
    tag_counts = Counter(tag for case in cases for tag in case.tags)
    for tag, minimum in active.minimum_tag_counts.items():
        if tag_counts[tag] < minimum:
            raise ValueError(
                f"tag 최소 개수를 만족하지 않습니다: {tag}={tag_counts[tag]} < {minimum}"
            )


def dataset_sha256(cases: list[EvaluationCaseV3], project_root: str | Path) -> str:
    root = Path(project_root).resolve()
    canonical: list[dict] = []
    for case in sorted(cases, key=lambda item: item.id):
        row = case.model_dump(mode="json")
        row["html_path"] = str(case.html_path.resolve().relative_to(root))
        canonical.append(row)
    payload = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def load_probe_cases_v3(
    path: str | Path,
    project_root: str | Path,
    *,
    max_html_bytes: int = 5_000_000,
) -> list[ModelProbeCaseV3]:
    """기대 답 필드가 없는 model probe JSONL을 엄격하게 읽는다."""

    root = Path(project_root).resolve()
    rows: list[ModelProbeCaseV3] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                case = ModelProbeCaseV3.model_validate_json(line)
            except Exception as exc:
                raise ValueError(f"probe JSONL {line_number}행이 유효하지 않습니다: {exc}") from exc
            resolved = case.html_path if case.html_path.is_absolute() else root / case.html_path
            resolved = resolved.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(f"HTML 경로가 project root 밖입니다: {case.html_path}")
            rows.append(case.model_copy(update={"html_path": resolved}))
    if not rows:
        raise ValueError("model probe 사례가 비어 있습니다")

    ids = [case.id for case in rows]
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"중복된 probe case id입니다: {duplicates}")
    family_splits: dict[str, set[str]] = {}
    for case in rows:
        family_splits.setdefault(case.family_id, set()).add(case.split)
    leaked = sorted(family for family, splits in family_splits.items() if len(splits) > 1)
    if leaked:
        raise ValueError(f"probe family가 여러 split에 포함됩니다: {leaked}")
    for case in rows:
        raw, _ = read_html(case.html_path, max_html_bytes)
        if sha256_bytes(raw) != case.html_sha256:
            raise ValueError(f"probe HTML SHA-256이 일치하지 않습니다: {case.id}")
    return rows
