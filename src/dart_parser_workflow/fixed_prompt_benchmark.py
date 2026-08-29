"""optimizer 없이 고정된 v3 프롬프트를 target 모델 하나에 평가한다."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean

from .config import FixedPromptBenchmarkSettings
from .dataset import dataset_sha256
from .execution import CallLedger
from .html_utils import sha256_file
from .prompt_optimization import run_case_v3
from .prompts import load_prompt
from .providers import ModelProvider, create_target_provider_v3
from .schemas import CaseResultV3, EvaluationCaseV3


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _append_jsonl(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def _git_identity(project_root: Path) -> tuple[str | None, bool | None]:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return sha, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _project_path(path: Path, project_root: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(project_root))
    except ValueError:
        return str(resolved)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def aggregate_fixed_prompt_results(results: list[CaseResultV3]) -> dict:
    """고정 프롬프트 결과를 모델 비교용 결정론적 지표로 집계한다."""

    total = len(results)
    latencies = [item.latency_seconds for item in results if item.latency_seconds is not None]
    statuses = Counter(item.status for item in results)

    def ratio(count: int) -> float:
        return count / total if total else 0.0

    strict = sum(item.score.strict_pass for item in results)
    correct = sum(item.score.answer_correct for item in results)
    grounded = sum(item.score.evidence_in_document for item in results)
    context = sum(item.score.expected_context_covered for item in results)
    errors = statuses["input_error"] + statuses["generation_error"]
    unsafe = statuses["unsafe_answer"]
    abstentions = sum(item.answerable and item.abstained for item in results)
    return {
        "case_count": total,
        "mean_quality_score": (
            fmean(item.score.quality_score for item in results) if results else 0.0
        ),
        "strict_pass_count": strict,
        "strict_pass_rate": ratio(strict),
        "exact_answer_count": correct,
        "exact_answer_rate": ratio(correct),
        "evidence_grounded_count": grounded,
        "evidence_grounded_rate": ratio(grounded),
        "context_covered_count": context,
        "context_covered_rate": ratio(context),
        "unsafe_answer_count": unsafe,
        "answerable_abstention_count": abstentions,
        "error_count": errors,
        "status_counts": dict(sorted(statuses.items())),
        "latency_seconds": {
            "mean": fmean(latencies) if latencies else None,
            "p95": _p95(latencies),
        },
    }


def _select_cases(
    cases: list[EvaluationCaseV3],
    *,
    split: str,
    sample_ids: list[str] | None,
) -> list[EvaluationCaseV3]:
    known_ids = {case.id for case in cases}
    requested = set(sample_ids or [])
    unknown = sorted(requested - known_ids)
    if unknown:
        raise ValueError(f"알 수 없는 sample ID입니다: {unknown}")
    selected = [
        case
        for case in cases
        if (split == "all" or case.split == split)
        and (not requested or case.id in requested)
    ]
    if not selected:
        raise ValueError("고정 프롬프트 benchmark 대상 사례가 없습니다")
    return selected


def run_fixed_prompt_benchmark(
    cases: list[EvaluationCaseV3],
    settings: FixedPromptBenchmarkSettings,
    output_dir: str | Path,
    project_root: str | Path,
    *,
    split: str = "all",
    sample_ids: list[str] | None = None,
    target_provider: ModelProvider | None = None,
) -> dict:
    """같은 prompt로 선택된 사례를 target 하나에 실행하고 Python으로 채점한다."""

    if split not in {"all", "development", "validation", "test"}:
        raise ValueError(f"지원하지 않는 split입니다: {split}")
    root = Path(project_root).resolve()
    prompt_path = Path(settings.prompt_path)
    if not prompt_path.is_absolute():
        prompt_path = root / prompt_path
    prompt = load_prompt(prompt_path)
    prompt_hash = _sha256_text(prompt)
    if prompt_hash != settings.prompt_sha256:
        raise ValueError(
            "고정 프롬프트 SHA-256이 일치하지 않습니다: "
            f"actual={prompt_hash}, expected={settings.prompt_sha256}"
        )
    selected = _select_cases(cases, split=split, sample_ids=sample_ids)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    run_id = output.name
    started_at = datetime.now(UTC)
    git_sha, git_dirty = _git_identity(root)
    summary: dict = {
        "schema_version": 3,
        "run_id": run_id,
        "benchmark_type": "fixed_prompt_exploratory",
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "observed_status": "partial",
        "quality_status": "inconclusive",
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "dataset_sha256": dataset_sha256(cases, root),
        "evaluated_dataset_sha256": dataset_sha256(selected, root),
        "evaluated_split": split,
        "sample_ids": [case.id for case in selected],
        "family_ids": sorted({case.family_id for case in selected}),
        "html_sha256": {case.id: case.html_sha256 for case in selected},
        "prompt_path": _project_path(prompt_path, root),
        "prompt_sha256": prompt_hash,
        "scorer_sha256": sha256_file(Path(__file__).with_name("evaluation.py")),
        "target_provider": settings.target_provider.model_dump(mode="json"),
        "expected_answers_sent_to_provider": False,
        "optimizer_used": False,
        "candidate_generated": False,
        "test_used_for_generation_or_selection": False,
        "planned_case_count": len(selected),
        "completed_case_count": 0,
        "metrics": {},
        "metrics_by_split": {},
        "provider_usage": {},
        "error": None,
    }
    _atomic_json(output / "summary.json", summary)
    (output / "fixed-prompt.md").write_text(prompt, encoding="utf-8")
    ledger = CallLedger(output / "calls.jsonl", {"target": settings.target_limits})
    try:
        provider = target_provider or create_target_provider_v3(
            settings.target_provider, root
        )
    except Exception as exc:
        summary.update(
            observed_status="not_run",
            finished_at=datetime.now(UTC).isoformat(),
            error=f"{type(exc).__name__}: {str(exc)[:2000]}",
        )
        _write_final_summary(output, summary)
        return summary

    results: list[CaseResultV3] = []
    try:
        for case in selected:
            result = run_case_v3(
                case,
                run_id=run_id,
                prompt_template=prompt,
                prompt_variant="fixed",
                max_html_bytes=settings.workflow.max_html_bytes,
                provider=provider,
                requested_model=settings.target_provider.model,
                ledger=ledger,
            )
            results.append(result)
            _append_jsonl(output / "results.jsonl", result.model_dump(mode="json"))
        ledger.assert_within_limits("target")
        metrics = aggregate_fixed_prompt_results(results)
        metrics_by_split = {
            name: aggregate_fixed_prompt_results(
                [item for item in results if item.split == name]
            )
            for name in ("development", "validation", "test")
            if any(item.split == name for item in results)
        }
        summary.update(
            observed_status="complete",
            quality_status=(
                "pass" if metrics["strict_pass_count"] == len(results) else "fail"
            ),
            finished_at=datetime.now(UTC).isoformat(),
            completed_case_count=len(results),
            metrics=metrics,
            metrics_by_split=metrics_by_split,
            provider_usage={
                "target": ledger.role_summary("target", settings.target_provider.model)
            },
        )
    except Exception as exc:
        summary.update(
            observed_status="partial",
            quality_status="inconclusive",
            finished_at=datetime.now(UTC).isoformat(),
            completed_case_count=len(results),
            metrics=aggregate_fixed_prompt_results(results),
            provider_usage={
                "target": ledger.role_summary("target", settings.target_provider.model)
            },
            error=f"{type(exc).__name__}: {str(exc)[:2000]}",
        )
    _write_final_summary(output, summary)
    return summary


def _write_final_summary(output: Path, summary: dict) -> None:
    artifact_names = ["calls.jsonl", "fixed-prompt.md", "results.jsonl"]
    summary["artifact_sha256"] = {
        name: sha256_file(output / name)
        for name in artifact_names
        if (output / name).exists()
    }
    _atomic_json(output / "summary.json", summary)
