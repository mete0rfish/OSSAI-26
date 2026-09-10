import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from dart_parser_workflow.config import ParserGenerationSettings, ProviderSettings
from dart_parser_workflow.html_utils import sha256_bytes, sha256_file
from dart_parser_workflow.parser_code import check_parser_code
from dart_parser_workflow.parser_generation import run_parser_generation
from dart_parser_workflow.parser_providers import (
    GeminiParserProvider,
    NvidiaNimParserProvider,
    OllamaParserProvider,
)
from dart_parser_workflow.parser_schemas import (
    ParserAnswer,
    ParserGenerationResult,
    ParserGenerationSummary,
    ParserProviderResponse,
)
from dart_parser_workflow.schemas import DisclosureAnswer, GenerationRequest

ROOT = Path(__file__).parents[1]
HTML = "tests/fixtures/v3/dev-answer.html"
QUESTION = "2025년 개발 매출액은 얼마인가?"
ANSWER = json.loads(
    (ROOT / "tests/fixtures/parser-generation-response.jsonl").read_text(encoding="utf-8")
)["response"]


def settings():
    return ParserGenerationSettings.model_validate(yaml.safe_load(
        (ROOT / "configs/parser-generation.recorded.yaml").read_text(encoding="utf-8")
    ))


class FakeProvider:
    def __init__(self, answer=None, error=None):
        self.answer = ANSWER if answer is None else answer
        self.error = error
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return ParserProviderResponse(
            result=ParserAnswer.model_validate(self.answer),
            requested_model="fake", actual_model="fake-actual", latency_seconds=0,
        )


def run(tmp_path, *, config=None, provider=None, **kwargs):
    return run_parser_generation(
        HTML, QUESTION, config or settings(), tmp_path / "run", ROOT,
        provider=provider, **kwargs,
    )


def result(tmp_path):
    return ParserGenerationResult.model_validate_json(
        (tmp_path / "run/result.json").read_text(encoding="utf-8")
    )


def test_recorded_generation_roundtrips_code_without_claiming_execution(tmp_path):
    summary = run(tmp_path)
    output = result(tmp_path)
    assert summary.observed_status == "complete"
    assert summary.quality_status == "inconclusive"
    assert summary.code_execution_status == "not_run"
    assert output.response.result.python_code == ANSWER["python_code"]
    assert output.code_check.status == "valid"
    assert output.code_check.correctness == "inconclusive"
    assert output.evidence_in_document and output.answer_in_evidence
    assert output.html_sha256 == sha256_file(ROOT / HTML)
    assert output.code_sha256 == sha256_file(tmp_path / "run/parser.py")
    assert output.response_schema_sha256 and output.checker_sha256
    assert (tmp_path / "run/parser.py").read_text(encoding="utf-8") == ANSWER["python_code"]
    saved = ParserGenerationSummary.model_validate_json(
        (tmp_path / "run/summary.json").read_text(encoding="utf-8")
    )
    assert saved == summary
    calls = (tmp_path / "run/calls.jsonl").read_text(encoding="utf-8")
    assert QUESTION not in calls and "BeautifulSoup" not in calls and "<html>" not in calls
    assert "expected" not in output.model_dump()


@pytest.mark.parametrize("code", [None, "", "   "])
def test_answer_requires_code(code):
    with pytest.raises(ValidationError):
        ParserAnswer.model_validate({**ANSWER, "python_code": code})


def test_existing_qa_schema_still_rejects_code():
    with pytest.raises(ValidationError, match="python_code"):
        DisclosureAnswer.model_validate(ANSWER)
    with pytest.raises(ValidationError, match="python_code"):
        ParserAnswer.model_validate({k: v for k, v in ANSWER.items() if k != "python_code"})


def abstention():
    return dict(
        answer="답변 보류", evidence=[], confidence=0, abstained=True,
        abstention_reason="문맥 없음", python_code=None,
    )


def test_abstention_emits_no_parser_file(tmp_path):
    summary = run(tmp_path, provider=FakeProvider(abstention()))
    output = result(tmp_path)
    assert summary.observed_status == "complete"
    assert summary.quality_status == "inconclusive"
    assert output.status == "abstained"
    assert output.code_check.status == "not_applicable"
    assert output.evidence_in_document is None
    assert not (tmp_path / "run/parser.py").exists()


@pytest.mark.parametrize("patch", [
    {"python_code": "def extract(html): return 'guess'"},
    {"answer": "guess"}, {"evidence": [{"quote": "guess"}]},
    {"abstention_reason": "  "},
])
def test_abstention_contract_cannot_be_weakened(patch):
    with pytest.raises(ValidationError):
        ParserAnswer.model_validate({**abstention(), **patch})


@pytest.mark.parametrize("source", [
    "def extract(:", "return 1", "```python\ndef extract(html): return None\n```",
    "def other(html): return None", "async def extract(html): return None",
    "def extract(html, question): return None", "def extract(html=None): return None",
    "def extract(html, *args): return None", "def extract(html, **kwargs): return None",
    "@decorator\ndef extract(html): return None", "def extract(html): yield None",
    "def extract(html): return None\ndef extract(html): return None",
])
def test_invalid_syntax_and_entrypoint(source):
    assert check_parser_code(source).status == "invalid"


def test_invalid_code_preserves_answer_and_marks_quality_failed(tmp_path):
    summary = run(tmp_path, provider=FakeProvider({**ANSWER, "python_code": "def extract(:"}))
    assert summary.observed_status == "complete"
    assert summary.quality_status == "fail"
    output = result(tmp_path)
    assert output.response.result.answer == "100원"
    assert output.code_check.syntax_valid is False


def test_static_checks_never_execute_code(tmp_path):
    marker = tmp_path / "must-not-exist"
    source = f"open({str(marker)!r}, 'w').write('executed')\ndef extract(html): return None"
    summary = run(tmp_path, provider=FakeProvider({**ANSWER, "python_code": source}))
    assert summary.quality_status == "inconclusive"
    assert not marker.exists()
    assert result(tmp_path).code_check.execution_status == "not_run"


def test_missing_evidence_fails_quality_even_with_valid_code(tmp_path):
    summary = run(tmp_path, provider=FakeProvider({**ANSWER, "evidence": [{"quote": "fake"}]}))
    assert summary.observed_status == "complete"
    assert summary.quality_status == "fail"
    assert not result(tmp_path).evidence_in_document


def test_generation_failure_preserves_partial_run_and_redacts_error(tmp_path):
    summary = run(tmp_path, provider=FakeProvider(error=RuntimeError("secret HTML credentials")))
    assert summary.observed_status == "partial"
    assert summary.error == "RuntimeError"
    for path in (tmp_path / "run").iterdir():
        assert "secret HTML credentials" not in path.read_text(encoding="utf-8")
    assert result(tmp_path).status == "generation_error"


def test_initialization_failure_is_not_run(tmp_path, monkeypatch):
    def fail(*args):
        raise ValueError("private configuration")
    monkeypatch.setattr("dart_parser_workflow.parser_generation.create_parser_provider", fail)
    assert run(tmp_path).observed_status == "not_run"
    assert not (tmp_path / "run/calls.jsonl").exists()


def test_output_cannot_be_reused(tmp_path):
    run(tmp_path)
    before = (tmp_path / "run/result.json").read_bytes()
    fake = FakeProvider()
    with pytest.raises(FileExistsError):
        run(tmp_path, provider=fake)
    assert not fake.requests
    assert (tmp_path / "run/result.json").read_bytes() == before


def test_hash_mismatch_prevents_any_call_or_output(tmp_path):
    fake = FakeProvider()
    with pytest.raises(ValueError, match="SHA-256"):
        run(tmp_path, provider=fake, expected_html_sha256="0" * 64)
    assert not fake.requests
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("source,question", [
    ("../outside.html", QUESTION), (str(ROOT / HTML), QUESTION), (HTML, "   "),
])
def test_invalid_inputs_prevent_calls(tmp_path, source, question):
    fake = FakeProvider()
    with pytest.raises(ValueError):
        run_parser_generation(source, question, settings(), tmp_path / "run", ROOT, provider=fake)
    assert not fake.requests


def test_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path / "outside.html"
    outside.write_text("<p>outside</p>", encoding="utf-8")
    root = tmp_path / "project"
    root.mkdir()
    (root / "input.html").symlink_to(outside)
    with pytest.raises(ValueError, match="밖"):
        run_parser_generation("input.html", QUESTION, settings(), tmp_path / "run", root)


def test_live_requires_authorization_before_provider_creation(tmp_path):
    config = settings()
    config.provider = ProviderSettings(kind="ollama", model="test")
    fake = FakeProvider()
    with pytest.raises(ValueError, match="authorize-external-transmission"):
        run(tmp_path, config=config, provider=fake)
    assert not fake.requests
    assert not (tmp_path / "run").exists()
    assert run(
        tmp_path, config=config, provider=fake, authorize_external_transmission=True,
    ).observed_status == "complete"


def test_consumed_budget_retains_response_and_partial_status(tmp_path):
    config = settings()
    config.limits.max_output_tokens = 1
    fake = FakeProvider()
    original = fake.generate

    def generate(request):
        response = original(request)
        response.usage.output_tokens = 2
        return response

    fake.generate = generate
    summary = run(tmp_path, config=config, provider=fake)
    assert summary.observed_status == "partial"
    assert summary.error == "BudgetExceeded"
    assert result(tmp_path).response.result.answer == "100원"
    assert len((tmp_path / "run/calls.jsonl").read_text().splitlines()) == 1


def test_prompt_uses_only_question_and_html_and_hashes_exact_input(tmp_path):
    fake = FakeProvider()
    run(tmp_path, provider=fake)
    prompt = fake.requests[0].prompt
    assert QUESTION in prompt
    assert (ROOT / HTML).read_text(encoding="utf-8") in prompt
    assert "expected" not in prompt
    assert result(tmp_path).prompt_sha256 == sha256_bytes(prompt.encode())


def test_question_is_preserved_verbatim_in_prompt_and_artifact(tmp_path):
    fake = FakeProvider()
    question = "  2025년\t개발 매출액?? {html}\n "
    run_parser_generation(HTML, question, settings(), tmp_path / "run", ROOT, provider=fake)
    assert question in fake.requests[0].prompt
    assert result(tmp_path).question == question


def test_context_limit_prevents_generation(tmp_path):
    config = settings()
    config.provider.context_window_tokens = config.provider.max_output_tokens + 1
    fake = FakeProvider()
    with pytest.raises(ValueError, match="input_context_exceeded"):
        run(tmp_path, config=config, provider=fake)
    assert not fake.requests
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("workflow", [
    {"html_preprocessing": "compact"}, {"batch_questions_by_html": True},
])
def test_parser_generation_rejects_unsupported_preprocessing_and_batch(workflow):
    with pytest.raises(ValidationError):
        ParserGenerationSettings.model_validate({**settings().model_dump(), "workflow": workflow})


@pytest.mark.parametrize("parsed", [True, False])
def test_gemini_parser_schema_and_code_survive_transport(monkeypatch, parsed):
    captured = {}

    def generate_content(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            parsed=ANSWER if parsed else None, text=json.dumps(ANSWER),
            model_version="actual", usage_metadata=None,
        )

    monkeypatch.setenv("TEST_KEY", "offline")
    monkeypatch.setattr(
        "dart_parser_workflow.providers.genai.Client",
        lambda **kwargs: SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)),
    )
    provider = GeminiParserProvider(ProviderSettings(
        kind="gemini", model="test", api_key_env="TEST_KEY",
    ))
    response = provider.generate(GenerationRequest(sample_id="input", prompt="test"))
    assert captured["config"].response_json_schema == ParserAnswer.model_json_schema()
    assert response.model_dump()["result"]["python_code"] == ANSWER["python_code"]


@pytest.mark.parametrize("kind", ["ollama", "nvidia_nim"])
def test_http_parser_providers_use_new_schema(monkeypatch, kind):
    captured = {}

    def chat(settings, prompt, response_model, api_key):
        captured["schema"] = response_model
        return response_model.model_validate(ANSWER), {"model": "actual"}, 0

    monkeypatch.setenv("TEST_KEY", "offline")
    monkeypatch.setattr(f"dart_parser_workflow.providers._{kind}_chat", chat)
    cls = OllamaParserProvider if kind == "ollama" else NvidiaNimParserProvider
    response = cls(ProviderSettings(kind=kind, model="test", api_key_env="TEST_KEY")).generate(
        GenerationRequest(sample_id="input", prompt="test")
    )
    assert captured["schema"] is ParserAnswer
    assert response.model_dump()["result"]["python_code"] == ANSWER["python_code"]
