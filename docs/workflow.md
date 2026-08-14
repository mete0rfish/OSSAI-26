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
서버에서 공시를 직접 내려받지 않는다. `dart-html-fetch/driver`로 수집한 로컬 HTML을 입력으로
사용한다.

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
