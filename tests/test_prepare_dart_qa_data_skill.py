import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from dart_parser_workflow.config import load_optimization_settings
from dart_parser_workflow.dataset import load_cases_v3

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / ".agents/skills/prepare-dart-qa-data/scripts/prepare_dataset.py"


def _load_skill_module():
    spec = importlib.util.spec_from_file_location("prepare_dart_qa_data", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SKILL = _load_skill_module()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _make_workspace(tmp_path: Path) -> tuple[Path, list[dict]]:
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    rows: list[dict] = []
    source_rows = [
        json.loads(line)
        for line in (ROOT / "configs/cases.v3.example.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    for source_row in source_rows:
        row = dict(source_row)
        source_html = ROOT / row["html_path"]
        target_html = html_dir / source_html.name
        shutil.copyfile(source_html, target_html)
        row["html_path"] = target_html.relative_to(tmp_path).as_posix()
        row.pop("html_sha256")
        rows.append(row)
    drafts = tmp_path / "drafts.jsonl"
    _write_jsonl(drafts, rows)
    return drafts, rows


def _approve_reviews(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row["reviewer"] = "홍길동"
        row["decision"] = "approved"
        row["checks"] = {
            "answer": True,
            "period": True,
            "scope": True,
            "unit": True,
            "evidence": True,
        }
    _write_jsonl(path, rows)
    return rows


def _materialize(tmp_path: Path) -> tuple[Path, Path, Path]:
    drafts, _ = _make_workspace(tmp_path)
    prepared = tmp_path / "prepared.jsonl"
    reviews = tmp_path / "reviews.jsonl"
    result = SKILL.materialize(
        drafts_path=drafts,
        prepared_path=prepared,
        reviews_path=reviews,
        project_root=tmp_path,
        max_html_bytes=5_000_000,
    )
    assert result["count"] == 6
    return drafts, prepared, reviews


def test_materialize_and_finalize_six_case_fixture_e2e(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    drafts, _ = _make_workspace(tmp_path)
    prepared = tmp_path / "prepared.jsonl"
    reviews = tmp_path / "reviews.jsonl"
    assert SKILL.main(
        [
            "materialize",
            "--drafts",
            str(drafts),
            "--prepared",
            str(prepared),
            "--reviews",
            str(reviews),
            "--project-root",
            str(tmp_path),
        ]
    ) == 0
    materialized = json.loads(capsys.readouterr().out)
    assert materialized["count"] == 6
    prepared_rows = [
        json.loads(line) for line in prepared.read_text(encoding="utf-8").splitlines()
    ]
    for row in prepared_rows:
        html = tmp_path / row["html_path"]
        assert row["html_sha256"] == hashlib.sha256(html.read_bytes()).hexdigest()

    review_rows = [
        json.loads(line) for line in reviews.read_text(encoding="utf-8").splitlines()
    ]
    assert all(row["decision"] == "pending" for row in review_rows)
    _approve_reviews(reviews)

    final = tmp_path / "cases/cases.v3.jsonl"
    assert SKILL.main(
        [
            "finalize",
            "--prepared",
            str(prepared),
            "--reviews",
            str(reviews),
            "--config",
            str(ROOT / "configs/prompt-optimization.recorded.yaml"),
            "--output",
            str(final),
            "--project-root",
            str(tmp_path),
        ]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    settings = load_optimization_settings(ROOT / "configs/prompt-optimization.recorded.yaml")
    cases = load_cases_v3(final, tmp_path, requirements=settings.dataset)

    assert len(cases) == 6
    assert result["count"] == 6
    assert len(result["dataset_sha256"]) == 64
    assert result["reviewers"] == ["홍길동"]
    assert result["all_reviews_approved"] is True
    assert result["live_provider_called"] is False

    with pytest.raises(ValueError, match="덮어쓸 수 없습니다"):
        SKILL.finalize(
            prepared_path=prepared,
            reviews_path=reviews,
            config_path=ROOT / "configs/prompt-optimization.recorded.yaml",
            output_path=final,
            project_root=tmp_path,
        )


@pytest.mark.parametrize("change", ["unknown", "traversal"])
def test_materialize_rejects_invalid_drafts(tmp_path: Path, change: str) -> None:
    drafts, rows = _make_workspace(tmp_path)
    if change == "unknown":
        rows[0]["unexpected"] = True
        expected = "알 수 없는 필드"
    else:
        rows[0]["html_path"] = "../outside.html"
        expected = "project root 밖"
    _write_jsonl(drafts, rows)

    with pytest.raises(ValueError, match=expected):
        SKILL.materialize(
            drafts_path=drafts,
            prepared_path=tmp_path / "prepared.jsonl",
            reviews_path=tmp_path / "reviews.jsonl",
            project_root=tmp_path,
            max_html_bytes=5_000_000,
        )


def test_materialize_does_not_overwrite_outputs(tmp_path: Path) -> None:
    drafts, _ = _make_workspace(tmp_path)
    prepared = tmp_path / "prepared.jsonl"
    reviews = tmp_path / "reviews.jsonl"
    prepared.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="덮어쓸 수 없습니다"):
        SKILL.materialize(
            drafts_path=drafts,
            prepared_path=prepared,
            reviews_path=reviews,
            project_root=tmp_path,
            max_html_bytes=5_000_000,
        )
    assert prepared.read_text(encoding="utf-8") == "keep"
    assert not reviews.exists()


@pytest.mark.parametrize("change", ["missing", "duplicate", "pending", "revise", "unchecked"])
def test_finalize_rejects_incomplete_reviews(tmp_path: Path, change: str) -> None:
    _, prepared, reviews = _materialize(tmp_path)
    rows = _approve_reviews(reviews)
    if change == "missing":
        rows.pop()
        expected = "누락"
    elif change == "duplicate":
        rows.append(dict(rows[0]))
        expected = "중복"
    elif change == "pending":
        rows[0]["decision"] = "pending"
        expected = "승인되지 않은"
    elif change == "revise":
        rows[0]["decision"] = "revise"
        expected = "승인되지 않은"
    else:
        rows[0]["checks"]["evidence"] = False
        expected = "완료되지 않았"
    _write_jsonl(reviews, rows)

    with pytest.raises(ValueError, match=expected):
        SKILL.finalize(
            prepared_path=prepared,
            reviews_path=reviews,
            config_path=ROOT / "configs/prompt-optimization.recorded.yaml",
            output_path=tmp_path / "final.jsonl",
            project_root=tmp_path,
        )


def test_finalize_applies_config_split_requirements(tmp_path: Path) -> None:
    _, prepared, reviews = _materialize(tmp_path)
    _approve_reviews(reviews)
    config = tmp_path / "config.yaml"
    content = (ROOT / "configs/prompt-optimization.recorded.yaml").read_text(
        encoding="utf-8"
    )
    config.write_text(content.replace("development: 2", "development: 3", 1), encoding="utf-8")

    with pytest.raises(ValueError, match="development 사례 수"):
        SKILL.finalize(
            prepared_path=prepared,
            reviews_path=reviews,
            config_path=config,
            output_path=tmp_path / "final.jsonl",
            project_root=tmp_path,
        )


def test_finalize_rejects_review_after_case_changes(tmp_path: Path) -> None:
    _, prepared, reviews = _materialize(tmp_path)
    _approve_reviews(reviews)
    rows = [json.loads(line) for line in prepared.read_text(encoding="utf-8").splitlines()]
    rows[0]["question"] = "승인 후 변경된 질문은 무엇인가?"
    _write_jsonl(prepared, rows)

    with pytest.raises(ValueError, match="case SHA-256"):
        SKILL.finalize(
            prepared_path=prepared,
            reviews_path=reviews,
            config_path=ROOT / "configs/prompt-optimization.recorded.yaml",
            output_path=tmp_path / "final.jsonl",
            project_root=tmp_path,
        )
