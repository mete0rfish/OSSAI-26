"""세 모델 × 두 prompt를 비교하고 선택 뒤 Test를 한 번 실행한다."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .config import ProviderSettings, SubmissionSettings
from .dataset import dataset_sha256
from .dataset_review import validate_approved_reviews
from .execution import CallLedger
from .fixed_prompt_benchmark import aggregate_fixed_prompt_results
from .html_utils import sha256_file
from .prompt_optimization import iter_cases_v3
from .prompts import load_prompt
from .providers import ModelProvider, create_target_provider_v3, list_ollama_models
from .schemas import EvaluationCaseV3, GenerationRequest, ModelUsage


class _SubmissionInconclusive(RuntimeError):
    """Stop before Test while preserving a complete inconclusive validation run."""


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


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "model"


def _resolve_prompt(path_value: str, root: Path, expected_hash: str) -> tuple[Path, str]:
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    prompt = load_prompt(path)
    actual_hash = _sha256_text(prompt)
    if actual_hash != expected_hash:
        raise ValueError(
            f"prompt SHA-256이 일치하지 않습니다: path={path}, "
            f"actual={actual_hash}, expected={expected_hash}"
        )
    return path.resolve(), prompt


def _metrics(results: list) -> dict:
    metrics = aggregate_fixed_prompt_results(results)
    metrics.update(
        input_tokens=sum(item.input_tokens or 0 for item in results),
        output_tokens=sum(item.output_tokens or 0 for item in results),
        actual_models=sorted(
            {item.actual_model for item in results if item.actual_model is not None}
        ),
    )
    return metrics


def select_submission_combination(
    validation_results: dict[tuple[str, str], list],
    *,
    min_mean_improvement: float,
    candidate_identical: bool = False,
) -> dict:
    """Validation 결과만으로 candidate gate와 최종 조합 순위를 계산한다."""

    model_ids = list(dict.fromkeys(model for model, _ in validation_results))
    for model_id in model_ids:
        baseline_rows = validation_results[(model_id, "baseline")]
        candidate_rows = validation_results[(model_id, "candidate")]
        baseline_identity = [
            (item.sample_id, item.html_sha256) for item in baseline_rows
        ]
        candidate_identity = [
            (item.sample_id, item.html_sha256) for item in candidate_rows
        ]
        has_error = any(
            item.status in {"input_error", "generation_error"}
            for item in [*baseline_rows, *candidate_rows]
        )
        if has_error or baseline_identity != candidate_identity:
            return {
                "status": "inconclusive",
                "reason": (
                    "validation_technical_error"
                    if has_error
                    else "validation_pair_mismatch"
                ),
                "selected_model": None,
                "selected_prompt": None,
                "model_comparisons": [],
                "test_used_for_selection": False,
            }
    comparisons: list[dict] = []
    eligible: list[dict] = []
    for model_id in model_ids:
        baseline = _metrics(validation_results[(model_id, "baseline")])
        candidate = _metrics(validation_results[(model_id, "candidate")])
        checks = {
            "prompt_changed": not candidate_identical,
            "errors_not_increased": candidate["error_count"] <= baseline["error_count"],
            "unsafe_answers_not_increased": (
                candidate["unsafe_answer_count"] <= baseline["unsafe_answer_count"]
            ),
            "answerable_abstentions_not_increased": (
                candidate["answerable_abstention_count"]
                <= baseline["answerable_abstention_count"]
            ),
            "strict_pass_rate_not_decreased": (
                candidate["strict_pass_rate"] >= baseline["strict_pass_rate"]
            ),
            "mean_improvement_reached": (
                candidate["mean_quality_score"]
                >= baseline["mean_quality_score"] + min_mean_improvement
            ),
        }
        candidate_eligible = all(checks.values())
        comparison = {
            "model": model_id,
            "baseline": baseline,
            "candidate": candidate,
            "candidate_checks": checks,
            "candidate_eligible": candidate_eligible,
        }
        comparisons.append(comparison)
        eligible.append({"model": model_id, "prompt": "baseline", "metrics": baseline})
        if candidate_eligible:
            eligible.append({"model": model_id, "prompt": "candidate", "metrics": candidate})

    def ranking(item: dict) -> tuple:
        metrics = item["metrics"]
        return (
            metrics["strict_pass_rate"],
            metrics["mean_quality_score"],
            -metrics["error_count"],
            -metrics["unsafe_answer_count"],
            -metrics["answerable_abstention_count"],
        )

    selected = max(eligible, key=ranking)
    return {
        "status": "selected",
        "selected_model": selected["model"],
        "selected_prompt": selected["prompt"],
        "selected_metrics": selected["metrics"],
        "all_candidates_rolled_back": not any(
            row["candidate_eligible"] for row in comparisons
        ),
        "ranking_order": [
            "strict_pass_rate_desc",
            "mean_quality_score_desc",
            "error_count_asc",
            "unsafe_answer_count_asc",
            "answerable_abstention_count_asc",
        ],
        "model_comparisons": comparisons,
        "test_used_for_selection": False,
    }


def _run_cases(
    cases: list[EvaluationCaseV3],
    *,
    output_path: Path,
    run_id: str,
    prompt: str,
    prompt_variant: str,
    settings: SubmissionSettings,
    provider: ModelProvider,
    provider_settings: ProviderSettings,
    model_id: str,
    ledger: CallLedger,
    redact_expected: bool = False,
) -> list:
    iterator = iter_cases_v3(
        cases,
        run_id=run_id,
        prompt_template=prompt,
        prompt_variant=prompt_variant,
        workflow=settings.workflow,
        provider=provider,
        provider_settings=provider_settings,
        requested_model=model_id,
        ledger=ledger,
        retry=settings.retry,
    )
    results = []
    for result in iterator:
        results.append(result)
        artifact = result.model_dump(mode="json")
        if redact_expected:
            artifact.pop("expected")
        _append_jsonl(output_path, artifact)
    return results


def _smoke_test(
    *,
    model_id: str,
    provider: ModelProvider,
    ledger: CallLedger,
) -> str:
    prompt = (
        "구조화 응답 사전 점검입니다. answer는 '확인', evidence에는 quote '확인' 하나, "
        "confidence는 1, abstained는 false, abstention_reason은 null로 반환하세요."
    )
    sample_id = f"preflight:{model_id}"
    ledger.before_request("target")
    try:
        response = provider.generate(
            GenerationRequest(
                sample_id=sample_id,
                prompt=prompt,
                prompt_variant="preflight",
            )
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:2000]}"
        ledger.record(
            role="target",
            sample_id=sample_id,
            prompt_variant="preflight",
            prompt=prompt,
            requested_model=model_id,
            actual_model=None,
            usage=ModelUsage(),
            latency_seconds=None,
            error=error,
        )
        raise RuntimeError(f"{model_id} 구조화 응답 사전 점검 실패: {error}") from exc
    ledger.record(
        role="target",
        sample_id=sample_id,
        prompt_variant="preflight",
        prompt=prompt,
        requested_model=response.requested_model,
        actual_model=response.actual_model,
        usage=response.usage,
        latency_seconds=response.latency_seconds,
    )
    if response.result.answer != "확인" or response.result.abstained:
        raise ValueError(f"{model_id} 구조화 응답 사전 점검 값이 예상과 다릅니다")
    return response.actual_model or response.requested_model


def _comparison_markdown(selection: dict, test_metrics: dict) -> str:
    lines = [
        "# 제출 워크플로 비교 결과",
        "",
        "## Validation",
        "",
        "| 모델 | 프롬프트 | exact | strict | 근거 | 문맥 | 평균 점수 | 오류 | unsafe | "
        "보류 | token | 평균 지연 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for comparison in selection["model_comparisons"]:
        for prompt in ("baseline", "candidate"):
            metrics = comparison[prompt]
            lines.append(
                f"| `{comparison['model']}` | {prompt} | "
                f"{metrics['exact_answer_count']}/{metrics['case_count']} | "
                f"{metrics['strict_pass_count']}/{metrics['case_count']} | "
                f"{metrics['evidence_grounded_count']}/{metrics['case_count']} | "
                f"{metrics['context_covered_count']}/{metrics['case_count']} | "
                f"{metrics['mean_quality_score']:.4f} | {metrics['error_count']} | "
                f"{metrics['unsafe_answer_count']} | "
                f"{metrics['answerable_abstention_count']} | "
                f"{metrics['input_tokens'] + metrics['output_tokens']} | "
                f"{metrics['latency_seconds']['mean'] or 0:.3f}s |"
            )
    if selection.get("improved_examples"):
        lines.extend(["", "## Candidate 개선 사례", ""])
        for example in selection["improved_examples"]:
            lines.append(
                f"- `{example['model']}` / `{example['sample_id']}`: "
                f"baseline `{example['baseline_answer']}` → "
                f"candidate `{example['candidate_answer']}`"
            )
    lines.extend(
        [
            "",
            "## 선택 및 Test",
            "",
            f"- 선택 모델: `{selection['selected_model']}`",
            f"- 선택 프롬프트: `{selection['selected_prompt']}`",
            f"- Test strict pass: {test_metrics['strict_pass_count']}/"
            f"{test_metrics['case_count']}",
            f"- Test 평균 점수: {test_metrics['mean_quality_score']:.4f}",
            f"- Test 오류: {test_metrics['error_count']}",
            f"- Test unsafe answer: {test_metrics['unsafe_answer_count']}",
            "",
            "Test 결과는 조합 선택에 사용하지 않았습니다.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_submission_workflow(
    cases: list[EvaluationCaseV3],
    settings: SubmissionSettings,
    output_dir: str | Path,
    project_root: str | Path,
    *,
    providers: dict[str, ModelProvider] | None = None,
    available_model_ids: list[str] | None = None,
    reviews_path: str | Path | None = None,
    authorize_external_transmission: bool = False,
) -> dict:
    root = Path(project_root).resolve()
    baseline_path, baseline = _resolve_prompt(
        settings.baseline_prompt, root, settings.baseline_prompt_sha256
    )
    candidate_path, candidate = _resolve_prompt(
        settings.candidate_prompt, root, settings.candidate_prompt_sha256
    )
    splits = {
        split: [case for case in cases if case.split == split]
        for split in ("development", "validation", "test")
    }
    if any(not rows for rows in splits.values()):
        raise ValueError("development/validation/test split은 모두 비어 있지 않아야 합니다")
    review_summary = None
    if settings.models[0].kind == "ollama" and not authorize_external_transmission:
        raise PermissionError("live submission에는 명시적 외부 전송 승인이 필요합니다")
    if settings.models[0].kind == "ollama":
        if reviews_path is None:
            raise ValueError("live submission에는 승인 완료된 --reviews JSONL이 필요합니다")
        reviews = validate_approved_reviews(cases, reviews_path, root)
        review_path = Path(reviews_path)
        if not review_path.is_absolute():
            review_path = root / review_path
        review_summary = {
            "path": str(review_path.resolve().relative_to(root)),
            "sha256": sha256_file(review_path.resolve()),
            "reviewers": sorted({review.reviewer.strip() for review in reviews}),
            "approved_case_count": len(reviews),
            "all_reviews_approved": True,
        }

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "validation").mkdir()
    run_id = output.name
    git_sha, git_dirty = _git_identity(root)
    summary = {
        "schema_version": 3,
        "run_id": run_id,
        "workflow_type": "submission_model_prompt_selection",
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": None,
        "observed_status": "partial",
        "quality_status": "inconclusive",
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "dataset_sha256": dataset_sha256(cases, root),
        "validation_dataset_sha256": dataset_sha256(splits["validation"], root),
        "test_dataset_sha256": dataset_sha256(splits["test"], root),
        "split_sample_ids": {
            split: [case.id for case in rows] for split, rows in splits.items()
        },
        "baseline_prompt_path": str(baseline_path.relative_to(root)),
        "baseline_prompt_sha256": _sha256_text(baseline),
        "candidate_prompt_path": str(candidate_path.relative_to(root)),
        "candidate_prompt_sha256": _sha256_text(candidate),
        "scorer_sha256": sha256_file(Path(__file__).with_name("evaluation.py")),
        "input_preparation": settings.workflow.model_dump(mode="json"),
        "human_review": review_summary,
        "selection": None,
        "test_metrics": None,
        "test_used_for_generation_or_selection": False,
        "provider_usage": {},
        "error": None,
    }
    _atomic_json(output / "summary.json", summary)
    ledger = CallLedger(output / "calls.jsonl", {"target": settings.target_limits})
    model_settings = {provider.model: provider for provider in settings.models}

    try:
        if available_model_ids is None:
            first = settings.models[0]
            if first.kind == "ollama":
                available_model_ids = list_ollama_models(first)
            else:
                available_model_ids = [provider.model for provider in settings.models]
        missing = sorted(set(model_settings) - set(available_model_ids))
        if missing:
            raise ValueError(f"Ollama Pro에서 정확한 model ID를 찾지 못했습니다: {missing}")

        active_providers = providers or {
            model_id: create_target_provider_v3(provider, root)
            for model_id, provider in model_settings.items()
        }
        if set(active_providers) != set(model_settings):
            raise ValueError("주입한 provider model ID가 submission 설정과 다릅니다")
        preflight = {
            "available_model_ids": sorted(available_model_ids),
            "models": [],
        }
        for model_id, provider in active_providers.items():
            actual_model = _smoke_test(
                model_id=model_id,
                provider=provider,
                ledger=ledger,
            )
            if model_settings[model_id].kind == "ollama" and actual_model != model_id:
                raise ValueError(
                    f"Ollama actual model ID가 요청과 다릅니다: "
                    f"requested={model_id}, actual={actual_model}"
                )
            preflight["models"].append(
                {
                    "requested_model": model_id,
                    "actual_model": actual_model,
                    "structured_response": "passed",
                }
            )
        _atomic_json(output / "preflight.json", preflight)

        validation_results = {}
        for model_id, provider in active_providers.items():
            for prompt_variant, prompt in (
                ("baseline", baseline),
                ("candidate", candidate),
            ):
                path = output / "validation" / f"{_slug(model_id)}.{prompt_variant}.jsonl"
                validation_results[(model_id, prompt_variant)] = _run_cases(
                    splits["validation"],
                    output_path=path,
                    run_id=run_id,
                    prompt=prompt,
                    prompt_variant=prompt_variant,
                    settings=settings,
                    provider=provider,
                    provider_settings=model_settings[model_id],
                    model_id=model_id,
                    ledger=ledger,
                )

        selection = select_submission_combination(
            validation_results,
            min_mean_improvement=settings.selection.min_mean_improvement,
            candidate_identical=baseline == candidate,
        )
        if selection["status"] == "inconclusive":
            _atomic_json(output / "selection.json", selection)
            summary.update(
                observed_status="complete",
                quality_status="inconclusive",
                finished_at=datetime.now(UTC).isoformat(),
                selection=selection,
                provider_usage={
                    "target": ledger.role_summary("target", "multiple-fixed-models")
                },
            )
            raise _SubmissionInconclusive
        improved_examples = []
        for model_id in model_settings:
            baseline_by_id = {
                item.sample_id: item
                for item in validation_results[(model_id, "baseline")]
            }
            for item in validation_results[(model_id, "candidate")]:
                baseline_item = baseline_by_id[item.sample_id]
                if not baseline_item.score.strict_pass and item.score.strict_pass:
                    improved_examples.append(
                        {
                            "model": model_id,
                            "sample_id": item.sample_id,
                            "baseline_answer": baseline_item.answer,
                            "candidate_answer": item.answer,
                        }
                    )
                    if len(improved_examples) == 3:
                        break
            if len(improved_examples) == 3:
                break
        selection["improved_examples"] = improved_examples
        _atomic_json(output / "selection.json", selection)
        summary["selection"] = selection
        _atomic_json(output / "summary.json", summary)
        selected_prompt = candidate if selection["selected_prompt"] == "candidate" else baseline
        (output / "selected-prompt.md").write_text(selected_prompt, encoding="utf-8")

        selected_model = selection["selected_model"]
        test_results = _run_cases(
            splits["test"],
            output_path=output / "test.jsonl",
            run_id=run_id,
            prompt=selected_prompt,
            prompt_variant="selected",
            settings=settings,
            provider=active_providers[selected_model],
            provider_settings=model_settings[selected_model],
            model_id=selected_model,
            ledger=ledger,
            redact_expected=True,
        )
        ledger.assert_within_limits("target")
        test_metrics = _metrics(test_results)
        (output / "comparison.md").write_text(
            _comparison_markdown(selection, test_metrics), encoding="utf-8"
        )
        summary.update(
            observed_status="complete",
            quality_status=(
                "pass" if test_metrics["strict_pass_count"] == len(test_results) else "fail"
            ),
            finished_at=datetime.now(UTC).isoformat(),
            selection=selection,
            test_metrics=test_metrics,
            provider_usage={
                "target": ledger.role_summary("target", "multiple-fixed-models")
            },
        )
    except _SubmissionInconclusive:
        pass
    except Exception as exc:
        summary.update(
            observed_status=("not_run" if summary["selection"] is None else "partial"),
            finished_at=datetime.now(UTC).isoformat(),
            provider_usage={
                "target": ledger.role_summary("target", "multiple-fixed-models")
            },
            error=f"{type(exc).__name__}: {str(exc)[:2000]}",
        )

    artifact_paths = [
        path
        for path in output.rglob("*")
        if path.is_file() and path.name != "summary.json"
    ]
    summary["artifact_sha256"] = {
        str(path.relative_to(output)): sha256_file(path) for path in sorted(artifact_paths)
    }
    _atomic_json(output / "summary.json", summary)
    return summary
