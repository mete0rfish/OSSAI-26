"""명시적 HTML 변형 생성과 selected prompt 견고성 평가."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import OptimizationSettings
from .dataset import dataset_sha256
from .execution import CallLedger
from .html_utils import read_html, sha256_bytes, sha256_file
from .prompt_optimization import _atomic_json, _git_identity, run_case_v3
from .providers import ModelProvider, create_target_provider_v3
from .schemas import CaseResultV3, EvaluationCaseV3


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VariantOperation(StrictModel):
    action: Literal["remove", "mask_text", "replace_text", "strip_attributes", "append_html"]
    selector: str = Field(min_length=1)
    value: str | None = None

    @model_validator(mode="after")
    def value_requirements(self) -> VariantOperation:
        if self.action in {"replace_text", "append_html"} and self.value is None:
            raise ValueError(f"{self.action} 작업에는 value가 필요합니다")
        return self


class VariantSpec(StrictModel):
    case_id: str
    variant_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    intended_status: Literal["preserved", "destroyed"]
    operations: list[VariantOperation] = Field(min_length=1)


class VariantArtifact(StrictModel):
    schema_version: Literal[3] = 3
    case_id: str
    variant_id: str
    intended_status: Literal["preserved", "destroyed"]
    original_html_path: str
    original_html_sha256: str
    variant_html_path: str
    variant_html_sha256: str
    operations: list[VariantOperation]


GroundingStatus = Literal["preserved", "destroyed", "invalid_variant"]


def load_variant_specs(path: str | Path) -> list[VariantSpec]:
    specs: list[VariantSpec] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                specs.append(VariantSpec.model_validate_json(line))
            except Exception as exc:
                raise ValueError(f"변형 spec {line_number}행이 유효하지 않습니다: {exc}") from exc
    keys = [(item.case_id, item.variant_id) for item in specs]
    if not specs or len(keys) != len(set(keys)):
        raise ValueError("변형 spec이 비어 있거나 case_id/variant_id가 중복되었습니다")
    return specs


def _apply_operation(soup: BeautifulSoup, operation: VariantOperation) -> None:
    matches = soup.select(operation.selector)
    if not matches:
        raise ValueError(f"CSS selector가 어떤 요소와도 일치하지 않습니다: {operation.selector}")
    for element in matches:
        if operation.action == "remove":
            element.decompose()
        elif operation.action == "mask_text":
            element.clear()
            element.append(operation.value or "[MASKED]")
        elif operation.action == "replace_text":
            element.clear()
            element.append(operation.value or "")
        elif operation.action == "strip_attributes":
            element.attrs.clear()
        else:
            fragment = BeautifulSoup(operation.value or "", "html.parser")
            element.append(fragment)


def generate_html_variants(
    cases: list[EvaluationCaseV3],
    specs: list[VariantSpec],
    output_dir: str | Path,
    project_root: str | Path,
    *,
    max_html_bytes: int = 5_000_000,
) -> list[VariantArtifact]:
    root, output = Path(project_root).resolve(), Path(output_dir).resolve()
    if not output.is_relative_to(root):
        raise ValueError("변형 출력 경로는 project root 안에 있어야 합니다")
    output.mkdir(parents=True, exist_ok=False)
    by_id = {case.id: case for case in cases}
    artifacts: list[VariantArtifact] = []
    for spec in specs:
        if spec.case_id not in by_id:
            raise ValueError(f"변형 spec의 case가 dataset에 없습니다: {spec.case_id}")
        case = by_id[spec.case_id]
        raw, html = read_html(case.html_path, max_html_bytes)
        if sha256_bytes(raw) != case.html_sha256:
            raise ValueError(f"원본 HTML SHA-256이 일치하지 않습니다: {case.id}")
        soup = BeautifulSoup(html, "html.parser")
        for operation in spec.operations:
            _apply_operation(soup, operation)
        target = output / f"{case.id}--{spec.variant_id}.html"
        rendered = str(soup).encode("utf-8")
        target.write_bytes(rendered)
        artifacts.append(
            VariantArtifact(
                case_id=case.id,
                variant_id=spec.variant_id,
                intended_status=spec.intended_status,
                original_html_path=str(case.html_path.relative_to(root)),
                original_html_sha256=case.html_sha256,
                variant_html_path=str(target.relative_to(root)),
                variant_html_sha256=sha256_bytes(rendered),
                operations=spec.operations,
            )
        )
    manifest = output / "variants.jsonl"
    manifest.write_text(
        "".join(item.model_dump_json() + "\n" for item in artifacts),
        encoding="utf-8",
    )
    with (output / "variant-review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "case_id",
                "variant_id",
                "variant_html_sha256",
                "intended_status",
                "grounding_status",
            ]
        )
        for item in artifacts:
            writer.writerow(
                [
                    item.case_id,
                    item.variant_id,
                    item.variant_html_sha256,
                    item.intended_status,
                    "",
                ]
            )
    return artifacts


def load_variant_manifest(
    path: str | Path, project_root: str | Path
) -> list[VariantArtifact]:
    root = Path(project_root).resolve()
    rows = [
        VariantArtifact.model_validate_json(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    keys = [(item.case_id, item.variant_id) for item in rows]
    if not rows or len(keys) != len(set(keys)):
        raise ValueError("변형 manifest가 비어 있거나 키가 중복되었습니다")
    for item in rows:
        for relative, expected in (
            (item.original_html_path, item.original_html_sha256),
            (item.variant_html_path, item.variant_html_sha256),
        ):
            path_value = Path(relative)
            resolved = (root / path_value).resolve()
            if path_value.is_absolute() or not resolved.is_relative_to(root):
                raise ValueError("변형 manifest 경로는 project-relative여야 합니다")
            if sha256_file(resolved) != expected:
                raise ValueError(f"변형 manifest SHA-256이 일치하지 않습니다: {relative}")
    return rows


def load_variant_reviews(
    path: str | Path, artifacts: list[VariantArtifact]
) -> dict[tuple[str, str], GroundingStatus]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = {(item.case_id, item.variant_id): item for item in artifacts}
    if len(rows) != len(expected):
        raise ValueError("사람 검토표의 행 수가 변형 manifest와 다릅니다")
    reviews: dict[tuple[str, str], GroundingStatus] = {}
    allowed = {"preserved", "destroyed", "invalid_variant"}
    for row in rows:
        key = (row.get("case_id", ""), row.get("variant_id", ""))
        status = row.get("grounding_status", "")
        if key not in expected or key in reviews:
            raise ValueError("사람 검토표의 변형 키가 중복되거나 manifest와 다릅니다")
        artifact = expected[key]
        if (
            row.get("variant_html_sha256") != artifact.variant_html_sha256
            or row.get("intended_status") != artifact.intended_status
        ):
            raise ValueError("사람 검토표가 현재 변형 artifact와 일치하지 않습니다")
        if status not in allowed:
            raise ValueError("모든 grounding_status를 검토 완료해야 합니다")
        reviews[key] = status  # type: ignore[assignment]
    return reviews


def _variant_evaluation(
    artifact: VariantArtifact,
    review: GroundingStatus,
    original: CaseResultV3,
    variant: CaseResultV3,
) -> dict[str, str]:
    if review == "invalid_variant" or review != artifact.intended_status:
        return {
            "case_id": artifact.case_id,
            "variant_id": artifact.variant_id,
            "grounding_status": review,
            "status": "invalid_variant",
            "reason": "의도와 사람 판정이 다르거나 검토자가 변형을 무효 처리함",
        }
    if review == "preserved":
        if not original.score.strict_pass:
            status, reason = "inconclusive", "원본 strict pass 실패로 정답 보존 판정 불가"
        else:
            passed = (
                variant.score.strict_pass
                and variant.normalized_answer == original.normalized_answer
                and variant.score.evidence_in_document
            )
            status = "passed" if passed else "failed"
            reason = "원본·변형 strict pass와 정규화 답 일치 검사"
    else:
        passed = (
            variant.abstained
            and variant.answer == "답변 보류"
            and not variant.evidence
            and bool(variant.abstention_reason)
        )
        status = "passed" if passed else "failed"
        reason = "근거 파괴 변형의 안전 보류 검사"
    return {
        "case_id": artifact.case_id,
        "variant_id": artifact.variant_id,
        "grounding_status": review,
        "status": status,
        "reason": reason,
    }


def run_html_robustness(
    cases: list[EvaluationCaseV3],
    settings: OptimizationSettings,
    optimization_dir: str | Path,
    manifest_path: str | Path,
    reviews_path: str | Path,
    output_dir: str | Path,
    project_root: str | Path,
    *,
    target_provider: ModelProvider | None = None,
) -> dict:
    root = Path(project_root).resolve()
    optimization = Path(optimization_dir).resolve()
    output = Path(output_dir).resolve()
    opt_summary = json.loads((optimization / "summary.json").read_text(encoding="utf-8"))
    if opt_summary.get("observed_status") != "complete":
        raise ValueError("complete optimization 결과만 robustness에 사용할 수 있습니다")
    prompt_path = optimization / "selected-prompt.md"
    prompt = prompt_path.read_text(encoding="utf-8")
    if sha256_file(prompt_path) != opt_summary.get("selected_prompt_sha256"):
        raise ValueError("selected prompt SHA-256이 optimization summary와 다릅니다")
    current_dataset_hash = dataset_sha256(cases, root)
    if current_dataset_hash != opt_summary.get("dataset_sha256"):
        raise ValueError("dataset SHA-256이 optimization summary와 다릅니다")
    scorer_hash = sha256_file(Path(__file__).with_name("evaluation.py"))
    if scorer_hash != opt_summary.get("scorer_sha256"):
        raise ValueError("scorer SHA-256이 optimization summary와 다릅니다")
    current_git_sha, _ = _git_identity(root)
    if current_git_sha != opt_summary.get("git_sha"):
        raise ValueError("Git SHA가 optimization summary와 다릅니다")
    artifacts = load_variant_manifest(manifest_path, root)
    reviews = load_variant_reviews(reviews_path, artifacts)
    by_id = {case.id: case for case in cases}
    if any(item.case_id not in by_id for item in artifacts):
        raise ValueError("변형 manifest의 case가 dataset에 없습니다")
    output.mkdir(parents=True, exist_ok=False)
    ledger = CallLedger(output / "calls.jsonl", {"target": settings.target_limits})
    initial_summary = {
        "schema_version": 3,
        "run_id": output.name,
        "observed_status": "partial",
        "quality_status": "inconclusive",
        "record_count": 0,
        "target_count": len(set(item.case_id for item in artifacts)) + len(artifacts),
        "error": None,
    }
    _atomic_json(output / "summary.json", initial_summary)
    try:
        provider = target_provider or create_target_provider_v3(
            settings.target_provider, root
        )
    except Exception as exc:
        initial_summary.update(
            observed_status="not_run",
            error=f"{type(exc).__name__}: {str(exc)[:2000]}",
        )
        _atomic_json(output / "summary.json", initial_summary)
        return initial_summary
    responses_path = output / "responses.jsonl"
    originals: dict[str, CaseResultV3] = {}
    evaluations: list[dict[str, str]] = []
    observed_status, error = "complete", None
    try:
        for case_id in dict.fromkeys(item.case_id for item in artifacts):
            case = by_id[case_id]
            original = run_case_v3(
                case,
                run_id=output.name,
                prompt_template=prompt,
                prompt_variant="robustness-original",
                max_html_bytes=settings.workflow.max_html_bytes,
                provider=provider,
                requested_model=settings.target_provider.model,
                ledger=ledger,
            )
            originals[case_id] = original
            evaluations.append(
                {
                    "case_id": case_id,
                    "variant_id": "original",
                    "grounding_status": "preserved",
                    "status": "passed" if original.score.strict_pass else "failed",
                    "reason": "원본 strict pass 검사",
                }
            )
            with responses_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "case_id": case_id,
                            "variant_id": "original",
                            "result": original.model_dump(mode="json"),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
        for artifact in artifacts:
            source = by_id[artifact.case_id]
            variant_case = source.model_copy(
                update={
                    "html_path": (root / artifact.variant_html_path).resolve(),
                    "html_sha256": artifact.variant_html_sha256,
                }
            )
            result = run_case_v3(
                variant_case,
                run_id=output.name,
                prompt_template=prompt,
                prompt_variant=artifact.variant_id,
                max_html_bytes=settings.workflow.max_html_bytes,
                provider=provider,
                requested_model=settings.target_provider.model,
                ledger=ledger,
            )
            with responses_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "case_id": artifact.case_id,
                            "variant_id": artifact.variant_id,
                            "result": result.model_dump(mode="json"),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
            evaluations.append(
                _variant_evaluation(
                    artifact,
                    reviews[(artifact.case_id, artifact.variant_id)],
                    originals[artifact.case_id],
                    result,
                )
            )
        ledger.assert_within_limits("target")
    except Exception as exc:
        observed_status, error = "partial", f"{type(exc).__name__}: {str(exc)[:2000]}"

    counts = Counter(item["status"] for item in evaluations)
    valid = [item for item in evaluations if item["status"] != "invalid_variant"]
    if observed_status != "complete" or not valid:
        quality = "inconclusive"
    elif any(item["status"] == "failed" for item in valid):
        quality = "fail"
    elif any(item["status"] == "inconclusive" for item in valid):
        quality = "inconclusive"
    else:
        quality = "pass"
    evaluation_value = {"schema_version": 3, "results": evaluations, "counts": dict(counts)}
    _atomic_json(output / "evaluation.json", evaluation_value)
    git_sha, git_dirty = _git_identity(root)
    evaluation_manifest = {
        "schema_version": 3,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "dataset_sha256": current_dataset_hash,
        "prompt_sha256": sha256_file(prompt_path),
        "scorer_sha256": scorer_hash,
        "variant_manifest_sha256": sha256_file(Path(manifest_path)),
        "review_sha256": sha256_file(Path(reviews_path)),
        "html_sha256": {
            f"{item.case_id}:{item.variant_id}": item.variant_html_sha256
            for item in artifacts
        },
    }
    _atomic_json(output / "evaluation-manifest.json", evaluation_manifest)
    summary = {
        "schema_version": 3,
        "run_id": output.name,
        "observed_status": observed_status,
        "quality_status": quality,
        "record_count": len(originals) + len(artifacts),
        "target_count": len(set(item.case_id for item in artifacts)) + len(artifacts),
        "counts": dict(counts),
        "git_sha": git_sha,
        "dataset_sha256": current_dataset_hash,
        "prompt_sha256": sha256_file(prompt_path),
        "scorer_sha256": scorer_hash,
        "provider_usage": ledger.role_summary("target", settings.target_provider.model),
        "error": error,
    }
    _atomic_json(output / "summary.json", summary)
    return summary
