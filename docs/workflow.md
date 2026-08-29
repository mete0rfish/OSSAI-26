# DART 공시 질의응답 검증 흐름

이 프로젝트는 DART 공시 HTML과 자연어 질문을 Gemini에 전달하고, 모델이 반환한 답과
인용 근거가 정확한지 검증한다. 파싱 코드를 생성하거나 실행하지 않는다.

## 전체 흐름

```text
평가 사례 YAML + 실행 설정 YAML
              │
              ▼
       설정과 사례 검증
              │
              ▼
       로컬 공시 HTML 읽기
              │
              ▼
      질문 + HTML 프롬프트 구성
              │
              ▼
 Gemini가 answer + evidence JSON 반환
              │
              ▼
  ┌───────────────────────────────┐
  │ 1. answer와 expected 비교    │
  │ 2. evidence가 HTML에 있는지  │
  │ 3. answer가 evidence에 있는지│
  └───────────────────────────────┘
              │
              ▼
      results.jsonl + summary.json
```

사례가 통과하려면 다음 조건을 모두 만족해야 한다.

1. 모델의 `answer`가 사례의 `expected`와 일치한다.
2. 모든 `evidence.quote`가 공시 HTML의 화면 표시 텍스트에 존재한다.
3. `answer`가 인용 근거 안에 존재한다.

## 1. 평가 사례와 실행 설정

평가 사례는 [`configs/cases.example.yaml`](../configs/cases.example.yaml)에 정의한다.

```yaml
cases:
  - id: operating-profit
    html_path: local-data/example.html
    question: "2025년 연결 영업이익은 얼마인가?"
    expected: "123,456백만원"
```

`expected`는 최종 채점에만 사용하며 모델 프롬프트에는 포함하지 않는다.

실제 Gemini 호출 설정은 [`configs/default.yaml`](../configs/default.yaml)에 있다.

```yaml
artifact_schema_version: 2

provider:
  kind: gemini
  model: gemini-3.6-flash
  api_key_env: GEMINI_API_KEY
  temperature: 0.0
  max_output_tokens: 8192

workflow:
  max_html_bytes: 5000000
```

API 없이 전체 흐름을 재현할 때는
[`configs/recorded.yaml`](../configs/recorded.yaml)의 `recorded` provider를 사용한다.

## 2. CLI 진입

[`scripts/run_workflow.py`](../scripts/run_workflow.py)는
[`src/dart_parser_workflow/cli.py`](../src/dart_parser_workflow/cli.py)의 `main()`을 호출하는
얇은 진입점이다.

```python
settings = load_settings(args.config)
cases = load_cases(args.cases, root)
summary = run_workflow(cases, settings, args.output, root)
```

[`src/dart_parser_workflow/config.py`](../src/dart_parser_workflow/config.py)는 Pydantic을 이용해
설정과 사례를 검증한다. 알 수 없는 설정 필드, 잘못된 provider 설정, 중복 case ID를
실행 전에 거부하고 상대 HTML 경로를 프로젝트 루트 기준의 절대 경로로 바꾼다.

## 3. 공시 HTML 읽기

[`src/dart_parser_workflow/workflow.py`](../src/dart_parser_workflow/workflow.py)의
`_read_html()`이 HTML을 읽는다.

```python
raw = case.html_path.read_bytes()
if len(raw) > max_bytes:
    raise ValueError(...)

decoded = UnicodeDammit(raw, is_html=True).unicode_markup
```

이 단계에서는 파일 존재 여부, 최대 크기와 문자 인코딩을 확인한다. 현재 workflow는 DART
서버에서 공시를 직접 내려받지 않는다. `.claude/skills/dart-html-fetch/driver`로 수집한 로컬
HTML을 입력으로 사용한다.

## 4. 프롬프트 구성

[`src/dart_parser_workflow/prompts.py`](../src/dart_parser_workflow/prompts.py)는 모델에 다음을
요구한다.

- 질문의 대상, 기간, 연결·별도 기준과 단위 구분
- 표의 정확한 행과 열 선택
- 설명 문장 없이 값과 단위만 답변
- 답을 포함하는 실제 공시 원문 인용
- 답을 확인할 수 없는 경우 `답변 보류`

프롬프트에는 질문과 HTML만 넣는다.

```python
def question_answer_prompt(question: str, html: str) -> str:
    return f"""{SYSTEM_RULES}

[질문]
{question}

[DART 공시 HTML]
{html}
"""
```

## 5. 구조화된 모델 응답

[`src/dart_parser_workflow/providers.py`](../src/dart_parser_workflow/providers.py)의
`GeminiProvider`는 Gemini에 Pydantic 응답 스키마를 전달한다.

```python
config=types.GenerateContentConfig(
    temperature=self.settings.temperature,
    max_output_tokens=self.settings.max_output_tokens,
    response_mime_type="application/json",
    response_schema=DisclosureAnswer,
)
```

응답은 [`src/dart_parser_workflow/schemas.py`](../src/dart_parser_workflow/schemas.py)의
`DisclosureAnswer` 형식을 따라야 한다.

```json
{
  "answer": "123,456백만원",
  "evidence": [
    {
      "quote": "구분 2025년 연결 영업이익 123,456백만원"
    }
  ],
  "confidence": 0.99,
  "abstained": false,
  "abstention_reason": null
}
```

일반 답변에는 하나 이상의 근거가 필요하다. 답변을 보류할 때는 `answer`가 정확히
`답변 보류`여야 하고, `evidence`는 비어 있으며 `abstention_reason`이 있어야 한다.

## 6. 답과 근거 검증

`workflow.py`는 모델 응답을 받은 뒤 다음 조건을 계산한다.

```python
answer_correct = not answer.abstained and normalized_answer == normalized_expected
evidence_in_document, answer_in_evidence = validate_evidence(answer, html)
passed = answer_correct and evidence_in_document and answer_in_evidence
```

[`src/dart_parser_workflow/evaluation.py`](../src/dart_parser_workflow/evaluation.py)의
`normalize_scalar()`는 Unicode 호환 문자와 공백만 정규화한다.

```python
normalized = unicodedata.normalize("NFKC", value).strip()
return re.sub(r"\s+", " ", normalized)
```

숫자의 쉼표, 통화 기호, 날짜 표현과 단위는 변환하지 않는다.

근거 검증은 HTML 태그를 제거한 화면 표시 텍스트를 기준으로 한다.

```python
document_text = normalize_scalar(
    BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
)
quotes = [normalize_scalar(item.quote) for item in answer.evidence]

evidence_in_document = all(quote in document_text for quote in quotes)
answer_in_evidence = normalize_scalar(answer.answer) in " ".join(quotes)
```

## 7. 결과 상태

| 상태 | 의미 |
| --- | --- |
| `passed` | 답, 공시 근거, 근거 안의 답이 모두 확인됨 |
| `wrong_answer` | 답이 기대값과 다름 |
| `ungrounded_evidence` | 답은 맞지만 인용이 본문에 없거나 답을 포함하지 않음 |
| `abstained` | 모델이 답변을 보류함 |
| `input_error` | HTML을 읽을 수 없거나 크기·인코딩 검증에 실패함 |
| `generation_error` | 모델 호출 또는 구조화 응답 검증에 실패함 |

각 사례 결과는 즉시 `results.jsonl`에 추가된다. 한 사례가 실패해도 다음 사례를 계속
처리하고, 마지막에 전체 통계를 `summary.json`으로 저장한다.

```text
reports/live-run/
├── results.jsonl
└── summary.json
```

결과에는 질문, 기대값, 모델 답, 인용 근거, 세부 검증 결과, 모델 ID, 프롬프트 SHA-256,
지연 시간과 토큰 수가 포함된다. API 키, 전체 HTML과 전체 프롬프트는 저장하지 않는다.

## 8. 실행 방법

저장된 응답으로 API 없는 전체 흐름을 실행한다.

```bash
uv run --locked python scripts/run_workflow.py \
  --cases configs/cases.example.yaml \
  --config configs/recorded.yaml \
  --output reports/recorded-example
```

실제 Gemini를 호출하려면 `.env`에 `GEMINI_API_KEY`를 설정하고 실행한다.

```bash
uv run --locked python scripts/run_workflow.py \
  --cases configs/cases.example.yaml \
  --config configs/default.yaml \
  --output reports/live-run
```

`--output`으로 지정한 디렉터리는 실행 전에 존재하지 않아야 한다.

## 현재 검증 범위와 한계

현재 근거 검증은 결정론적인 문자열 검사다. 인용문이 실제 HTML에 있고 답이 인용문 안에
있는지는 확인하지만, 인용문이 질문의 연도·항목·연결 기준과 의미적으로 올바르게 연결되는지
까지 자동 판정하지는 않는다.

이를 더 엄격히 평가하려면 평가 사례에 기대 근거를 추가하거나 질문과 인용문의 의미적
관련성을 별도로 채점하는 단계가 필요하다.

## v3 프롬프트 최적화 흐름

v3는 위 v2 흐름을 교체하지 않고 별도 CLI로 제공한다.

```text
v3 JSONL 사전 검사
→ development baseline 실행
→ strict 실패만 optimizer에 전달
→ validation에서 baseline/candidate 비교 및 rollback
→ 선택 완료 후 test 실행
→ selected prompt로 사람이 검토한 HTML 변형 평가
```

### 데이터와 채점

각 사례에는 `family_id`, 명시적 split, HTML SHA-256, 출처와 질문 metadata, 구조화된 expected,
tags가 필요하다. 같은 family가 여러 split에 있거나 기대 인용이 실제 HTML 화면 텍스트에 없으면
모델 호출 전에 실패한다.

answerable 점수는 정답 60%, 문서에 있는 근거 15%, 근거 안의 답 10%, 기대 문맥 anchor 15%다.
strict pass는 네 조건을 모두 만족해야 한다. unanswerable은 정확한 `답변 보류`, 보류 flag,
빈 evidence와 보류 이유를 모두 만족할 때만 1점이다.

### 역할과 선택 경계

- target provider는 질문과 HTML만 받아 답과 근거를 만든다.
- optimizer provider는 baseline과 development 실패 기록만 받아 후보를 제안한다.
- selector는 validation 결과만 받아 동일 후보, 오류 증가, answerable 보류 증가, strict pass rate
  감소를 차례로 차단하고 최소 평균 개선 폭까지 확인한다.
- test는 selector가 반환한 뒤에만 실행되며 summary에
  `test_used_for_generation_or_selection=false`가 기록된다.

live CLI의 `--target-model`, `--optimizer-model`은 YAML의 역할별 모델명을 실행 단위로
덮어쓴다. `--target-api-key-env`, `--optimizer-api-key-env`은 API 키 자체가 아니라 키가 저장된
환경변수 이름만 받는다. 덮어쓴 요청 모델과 API가 반환한 실제 모델은 기존과 같이 호출 ledger와
summary에 기록된다. 서로 다른 모델을 비교할 때는 dataset, prompt, temperature와 실행 한도를
고정하고 실행별로 새 출력 디렉터리를 사용한다.

사람 승인 전 모델 응답을 비교하는 `probe_dart_qa_model.py`는 `expected` 필드를 금지하는 별도
입력 schema를 사용한다. target에는 질문과 HTML만 전달하고 optimizer·정답 채점·prompt 선택은
실행하지 않는다. 응답의 인용이 현재 HTML에 있는지와 답이 인용에 포함되는지만 결정론적으로
기록한다. 기본 development 외 split은 사용자가 명시적으로 선택해야 한다.

Ollama provider는 설정의 `base_url`(기본 `http://localhost:11434`)에 있는 native
`POST /api/chat`을 사용한다. 요청은 `stream=false`, `think=false`이며 Pydantic JSON Schema를
`format`에 전달한다. temperature는 Ollama option의 `temperature`, 출력 한도는 `num_predict`로
매핑한다. 응답의 `message.content`를 같은 Pydantic schema로 검증하고 `prompt_eval_count`,
`eval_count`를 token 사용량으로 기록한다. 로컬 Ollama에는 API 키를 요구하지 않는다.

Ollama Cloud 직접 API는 `base_url=https://ollama.com`과 `api_key_env=OLLAMA_API_KEY`를 사용한다.
Cloud는 structured outputs를 지원하지 않으므로 `format`을 보내지 않고 JSON Schema를 system
지시문으로 전달한다. 반환값은 로컬 경로와 동일한 Pydantic schema로 엄격하게 검증하며, 형식이
맞지 않으면 임의 보정하지 않고 `generation_error`로 기록한다.

NVIDIA NIM provider는 hosted API 기본 주소 `https://integrate.api.nvidia.com/v1`의 OpenAI 호환
`POST /chat/completions`를 사용한다. `api_key_env`의 환경변수 값을 Bearer token으로만 전송하며
설정·명령행·artifact에는 키 값을 기록하지 않는다. 반환 schema 지시는 system message로 전달하고,
assistant의 `choices[0].message.content`를 `DisclosureAnswer` 또는 `PromptCandidate`로 엄격하게
검증한다. `usage.prompt_tokens`, `usage.completion_tokens`와 API가 반환한 실제 모델 ID를 ledger에
기록한다. provider 종류를 CLI에서 `nvidia_nim`으로 바꾸고 키 변수명을 생략하면
`NVIDIA_NIM_API_KEY`와 hosted 기본 주소를 사용한다. 다른 NIM 호환 endpoint는 역할별
`--target-base-url` 또는 `--optimizer-base-url`로 덮어쓴다.

## 고정 프롬프트 target benchmark

`scripts/benchmark_fixed_prompt.py`는 승인된 v3 dataset과 고정 프롬프트를 target 모델 하나에
실행한다. prompt optimization과 달리 optimizer provider를 설정·생성·호출하지 않고 candidate와
selection도 만들지 않는다.

실행 전에 다음 순서로 입력을 검증한다.

1. prompt에 `{question}`과 `{html}`이 각각 정확히 한 번 있는지 확인
2. 실제 prompt SHA-256이 설정의 `prompt_sha256`과 같은지 확인
3. dataset ID, family split, HTML hash, 기대 근거와 문맥 anchor 검증
4. 선택 split과 sample ID가 유효한지 확인
5. 아직 존재하지 않는 output 디렉터리 생성

target request에는 렌더링된 질문과 HTML만 포함된다. expected, accepted answers, 기대 인용과 문맥
anchor는 Python scorer에서만 사용된다. `run_case_v3`와 `score_answer_v3`를 재사용하므로 기존
optimization과 answer/evidence 판정 기준이 같다.

결과 디렉터리는 다음 artifact를 만든다.

```text
reports/model-benchmarks/<run-id>/
├── calls.jsonl
├── fixed-prompt.md
├── results.jsonl
└── summary.json
```

`summary.json`은 `expected_answers_sent_to_provider=false`, `optimizer_used=false`,
`candidate_generated=false`를 기록한다. 전체와 split별 exact answer, evidence grounding, context,
strict pass, abstention, unsafe answer, 오류, latency와 provider 사용량을 집계한다. 모든 예정 사례를
시도했으면 응답 오류가 있어도 실행 상태는 `complete`일 수 있고, 품질 상태는 별도로 판정한다.

현재처럼 이미 공개된 Test를 포함한 30개 전체 실행은 `fixed_prompt_exploratory`로 기록한다. 이
결과를 prompt 생성이나 최종 성능 주장에 재사용하지 않는다.

NIM 설정의 선택적 `top_p`는 chat completion의 같은 필드로 전달한다. `enable_thinking`을 지정하면
`chat_template_kwargs.enable_thinking`으로 전달한다. 모델별 권장값이 다르므로 API Catalog의 해당
모델 페이지를 확인하고, 공정한 비교에서는 실행별 값을 lineage 설정과 함께 고정한다. Gemma 4
NIM target과 Gemini optimizer의 실행 가능한 조합은
`configs/prompt-optimization.gemma4-nim-gemini.yaml`에 기록되어 있다.

### 계보와 완결성

호출 로그에는 전체 HTML·prompt 대신 prompt/HTML SHA-256, 역할, sample, 모델, token, 비용,
지연과 오류가 남는다. summary는 Git, dataset, split IDs, prompt, scorer와 HTML hash를 기록한다.
robustness는 optimization의 Git·dataset·selected prompt·scorer hash가 현재 입력과 모두 일치할
때만 실행한다.

모든 예정 사례가 시도되고 artifact가 생성되면 `complete`, 호출 전에 provider를 준비하지
못하면 `not_run`, 중단·예산 소진·계보 불일치는 `partial`이다. 이 값은 모델 품질의
`pass/fail/inconclusive`와 별개다.
