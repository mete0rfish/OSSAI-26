import json
from pathlib import Path

from dart_parser_workflow.config import (
    ExecutionLimits,
    ProviderSettings,
    RetrySettings,
    WorkflowSettings,
)
from dart_parser_workflow.dataset import load_cases_v3
from dart_parser_workflow.execution import CallLedger
from dart_parser_workflow.html_utils import compact_html, visible_text
from dart_parser_workflow.prompt_optimization import run_case_v3, run_cases_v3
from dart_parser_workflow.schemas import (
    BatchDisclosureAnswer,
    BatchDisclosureAnswers,
    BatchGenerationRequest,
    BatchProviderResponse,
    DisclosureAnswer,
    Evidence,
    GenerationRequest,
    ProviderResponse,
)

ROOT = Path(__file__).parents[1]


class BatchCapturingProvider:
    def __init__(self) -> None:
        self.batch_requests: list[BatchGenerationRequest] = []
        self.single_requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        self.single_requests.append(request)
        raise AssertionError("같은 HTML 질문은 단일 호출로 실행하면 안 됩니다")

    def generate_batch(self, request: BatchGenerationRequest) -> BatchProviderResponse:
        self.batch_requests.append(request)
        return BatchProviderResponse(
            result=BatchDisclosureAnswers(
                answers=[
                    BatchDisclosureAnswer(
                        sample_id=sample_id,
                        answer="100원",
                        evidence=[Evidence(quote="2025년 개발 매출액 100원")],
                        confidence=1,
                        abstained=False,
                    )
                    for sample_id in request.sample_ids
                ]
            ),
            requested_model="batch-model",
            actual_model="batch-model",
            usage={"input_tokens": 101, "output_tokens": 21},
            latency_seconds=0.01,
        )


class NeverCalledProvider:
    def __init__(self) -> None:
        self.called = False

    def generate(self, request: GenerationRequest) -> ProviderResponse:
        self.called = True
        return ProviderResponse(
            result=DisclosureAnswer(
                answer="100원",
                evidence=[Evidence(quote="100원")],
                confidence=1,
                abstained=False,
            ),
            requested_model="never-called",
            latency_seconds=0.01,
        )


def _development_case():
    return load_cases_v3(ROOT / "configs/cases.v3.example.jsonl", ROOT)[0]


def test_compact_html_preserves_visible_text_and_table_spans() -> None:
    html = """
    <html><head><style>.hidden { display: none; }</style></head>
    <body data-report="secret"><!-- comment -->
      <table style="width: 100%"><tr><th rowspan="2" class="label">항목</th>
      <td colspan="3" onclick="ignore()">100원</td></tr></table>
      <script>ignore()</script>
    </body></html>
    """

    compacted = compact_html(html)

    assert visible_text(compacted) == visible_text(html)
    assert "style=" not in compacted
    assert "class=" not in compacted
    assert "script" not in compacted
    assert "comment" not in compacted
    assert 'rowspan="2"' in compacted
    assert 'colspan="3"' in compacted
    assert len(compacted.encode()) < len(html.encode())


def test_same_html_questions_use_one_batch_call_and_split_usage(tmp_path: Path) -> None:
    first = _development_case()
    second = first.model_copy(
        update={"id": "dev-answer-copy", "question": "같은 개발 매출액을 다시 확인하라"}
    )
    provider = BatchCapturingProvider()
    exposures: list[tuple[str, int]] = []
    ledger = CallLedger(
        tmp_path / "calls.jsonl",
        {"target": ExecutionLimits(max_requests=1, max_attempts=1)},
    )
    workflow = WorkflowSettings(html_preprocessing="compact", batch_questions_by_html=True)
    provider_settings = ProviderSettings(kind="ollama", model="batch-model")

    results = run_cases_v3(
        [first, second],
        run_id="batch",
        prompt_template="{question}\n{html}",
        prompt_variant="baseline",
        workflow=workflow,
        provider=provider,
        provider_settings=provider_settings,
        requested_model="batch-model",
        ledger=ledger,
        retry=RetrySettings(),
        before_attempt=lambda sample_id, attempt: exposures.append((sample_id, attempt)),
    )

    assert not provider.single_requests
    assert len(provider.batch_requests) == 1
    assert exposures == [(first.id, 0), (second.id, 0)]
    assert [result.sample_id for result in results] == [first.id, second.id]
    assert all(result.score.strict_pass for result in results)
    assert sum(result.input_tokens or 0 for result in results) == 101
    assert sum(result.output_tokens or 0 for result in results) == 21
    call = json.loads((tmp_path / "calls.jsonl").read_text(encoding="utf-8"))
    assert call["batch_size"] == 2
    assert call["html_preprocessor"] == "compact-html-v1"
    assert call["prepared_html_bytes"] <= call["raw_html_bytes"]


def test_context_limit_rejects_before_provider_call(tmp_path: Path) -> None:
    case = _development_case()
    provider = NeverCalledProvider()
    ledger = CallLedger(tmp_path / "calls.jsonl", {"target": ExecutionLimits()})
    workflow = WorkflowSettings(estimated_bytes_per_token=1)
    provider_settings = ProviderSettings(
        kind="ollama",
        model="small-context",
        max_output_tokens=10,
        context_window_tokens=20,
    )

    result = run_case_v3(
        case,
        run_id="context-preflight",
        prompt_template="{question}\n{html}",
        prompt_variant="baseline",
        max_html_bytes=workflow.max_html_bytes,
        provider=provider,
        requested_model="small-context",
        ledger=ledger,
        workflow=workflow,
        provider_settings=provider_settings,
    )

    assert result.status == "input_error"
    assert result.error is not None and result.error.startswith("input_context_exceeded")
    assert provider.called is False
    assert ledger.role_summary("target", "small-context")["requests"] == 0
    assert not (tmp_path / "calls.jsonl").exists()
