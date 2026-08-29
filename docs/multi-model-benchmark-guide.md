# DART QA 다중 모델 벤치마크 가이드

이 문서는 하나의 고정된 DART QA 프롬프트를 여러 AI 모델에 적용해 공정하게 비교하기 위한
작업 가이드다. 사용자가 나중에 Codex에 작업을 맡길 때 필요한 현재 상태, 실험 원칙, 구현 범위,
승인 지점과 완료 조건을 함께 기록한다.

다중 모델 screening 이후 더 복잡한 프롬프트를 개발하는 후속 절차는
[complex-prompt-experiment-guide.md](complex-prompt-experiment-guide.md)를 따른다.

## 1. 이 작업의 목표

다음 두 질문을 분리해서 답한다.

1. 같은 프롬프트를 사용했을 때 어떤 target 모델이 DART QA를 가장 잘 푸는가?
2. NVIDIA NIM으로 개선한 프롬프트가 Ollama 외의 target 모델에도 효과가 있는가?

공정한 비교의 기본 단위는 `target 모델 × 고정 프롬프트`다. 각 모델이 자기 프롬프트를 다시
최적화하게 하면 모델 능력과 프롬프트 최적화 능력이 섞이므로 별도 실험으로 다뤄야 한다.

## 2. 현재 기준 상태

### 데이터셋

- 사례 파일: `local-data/dart-qa/cases/cases.v3.jsonl`
- 사례 수: 30개
- 공시 family 수: 10개
- split: development 12개, validation 9개, test 9개
- 사람 검토자: `meteorfish`
- 데이터셋 SHA-256:
  `ac94a5abe63b24a398b50b1e9d7e90cba076209c7a92ff8497d4923d0f480992`

동일 공시에서 만든 사례는 같은 family와 split에 배치돼 있다. DART HTML은
`local-data/dart-qa/html/`에 있고 저장소에 커밋하면 안 된다.

### 현재 선택된 프롬프트

- 파일:
  `reports/prompt-optimization/ollama-cloud-nim-20260824-01/selected-prompt.md`
- SHA-256:
  `9d24e442571204775807875888c401b241fa325450e23585485bd6dd52dc7954`
- target: Ollama Cloud `gpt-oss:120b`
- optimizer: NVIDIA NIM `nvidia/nemotron-3-ultra-550b-a55b`

현재 프롬프트의 최종 Test 결과는 다음과 같다.

| 지표 | 결과 |
|---|---:|
| 정답 값 일치 | 9/9 |
| 엄격 통과 | 1/9 |
| 평균 품질 점수 | 0.8333 |
| 근거 원문 불일치 | 7건 |
| 필수 문맥 누락 | 1건 |

상세 해석은
`reports/prompt-optimization/ollama-cloud-nim-20260824-01/human-readable-report.ko.md`에 있다.

### 현재 Test의 지위

현재 Test 결과는 이미 사람이 확인했고 실패 유형도 프롬프트 개선 논의에 사용됐다. 따라서 이
Test를 다시 실행해 탐색적인 모델 비교표를 만드는 것은 가능하지만, 그 결과를 새로운 미공개
Test 성능처럼 주장하면 안 된다. 모델이나 프롬프트를 선택한 뒤 신뢰할 수 있는 최종 성능을
측정하려면 새로운 공시 family로 Validation과 Test를 추가해야 한다.

## 3. 지원되는 provider

현재 provider 구현은 다음 네 종류를 지원한다.

| provider kind | 용도 | 키 또는 준비 사항 |
|---|---|---|
| `gemini` | Gemini API 모델 | API 키 환경변수 |
| `ollama` | 로컬 Ollama 또는 Ollama Cloud | 로컬 모델 또는 Cloud API 키 |
| `nvidia_nim` | NVIDIA NIM hosted 모델 | NVIDIA API 키 환경변수 |
| `recorded` | 오프라인 회귀 테스트 | 기록된 fixture |

실제 키는 `.env`에만 저장한다. YAML, 명령행, 로그, 문서에 키 값을 기록하지 않는다. 모델명과
키가 들어 있는 환경변수 이름만 설정에 기록한다.

모델의 현재 제공 여부, 정확한 ID, 가격, rate limit은 실행 직전에 각 provider의 공식 문서에서
다시 확인한다. 확인한 날짜와 가격은 `PricingSettings`에 기록하고 비용 상한을 설정한다.

## 4. 권장 실험 설계

### 4.1 탐색 실험

목적은 파이프라인 호환성과 대략적인 모델 특성을 확인하는 것이다.

- 현재 선택 프롬프트를 고정한다.
- 현재 Validation 또는 이미 공개된 Test에 여러 모델을 실행한다.
- 결과는 `exploratory`로 표시한다.
- 이 결과를 보고 프롬프트를 고친 뒤 같은 사례에서 개선 성능을 주장하지 않는다.
- 실제 호출 전 development에서 모델당 1~3개 smoke test를 먼저 수행한다.

### 4.2 정식 모델 선택 실험

목적은 운영에 사용할 target 모델 하나를 선택하는 것이다.

1. 새로운 공시 family를 수집하고 사람 검토를 완료한다.
2. 선택된 프롬프트와 그 SHA-256을 고정한다.
3. 모든 후보 모델을 같은 Validation 사례에서 평가한다.
4. 결정론적 Python selector가 Validation 결과만으로 승자를 고른다.
5. 사람은 모델명, 비용, 오류, selection manifest를 확인한다.
6. 승인 후 선택된 모델 하나만 새로운 Test에서 한 번 평가한다.
7. Test 결과는 모델 또는 프롬프트 재선택에 사용하지 않는다.

### 4.3 프롬프트 전이 실험

개선 프롬프트가 다른 모델에서도 효과적인지 보려면 각 모델에 다음 두 프롬프트를 모두 적용한다.

- baseline: `prompts/dart-qa-baseline.md`
- selected: 위에서 고정한 개선 프롬프트

같은 모델 안에서 baseline과 selected의 차이를 비교한다. 이 실험 중에는 모델별 새 candidate를
생성하지 않는다. 모델마다 별도 candidate를 생성하는 실험은 `모델별 최적화 실험`이라는 다른
이름과 별도 데이터 split으로 수행한다.

## 5. 비교 지표와 선택 규칙

각 모델에 대해 최소한 다음 지표를 기록한다.

| 지표 | 의미 |
|---|---|
| strict pass rate | 답·근거·문맥을 모두 만족한 비율 |
| mean quality score | 부분 성공을 포함한 평균 점수 |
| exact answer accuracy | 정답 값이 정확히 일치한 비율 |
| evidence grounding rate | 모든 인용이 현재 HTML에 실제로 존재한 비율 |
| context coverage rate | 필수 항목명·단위·범위를 포함한 비율 |
| unsafe answer count | unanswerable 문제에서 추측한 건수 |
| answerable abstention count | 답이 있는데 불필요하게 보류한 건수 |
| generation error count | 형식 오류, API 오류 등 생성 실패 건수 |
| latency | 평균, 중앙값, p95 응답 시간 |
| tokens and cost | 입출력 token과 검증된 가격 기준 비용 |

권장 모델 선택 순서는 다음과 같다.

1. Validation strict pass rate가 가장 높은 모델
2. 동률이면 mean quality score가 높은 모델
3. 다시 동률이면 generation error가 적은 모델
4. 다시 동률이면 unsafe answer와 answerable abstention 합계가 적은 모델

비용과 지연시간을 선택 기준에 포함하려면 실행 전에 사용자가 가중치 또는 최대 허용치를
승인해야 한다. provider가 점수를 계산하거나 승자를 선택하게 해서는 안 된다.

## 6. 현재 코드로 가능한 작업

`scripts/probe_dart_qa_model.py`는 기대 정답을 모델에 전달하지 않고 여러 target 모델의 응답과
근거 grounding을 수집할 수 있다. 다만 expected가 없는 probe 입력을 사용하므로 정답 점수나
엄격 통과율은 계산하지 않는다.

예시:

```bash
uv run --locked python scripts/probe_dart_qa_model.py \
  --cases local-data/dart-qa/inputs/cases.20260823-01.probe.jsonl \
  --config configs/prompt-optimization.ollama-cloud-nvidia-nim.yaml \
  --provider ollama \
  --model gpt-oss:120b \
  --api-key-env OLLAMA_API_KEY \
  --base-url https://ollama.com \
  --split development \
  --output reports/model-probes/ollama-smoke-YYYYMMDD-HHMMSS
```

probe는 다음 용도로만 사용한다.

- 모델 ID와 API 연결 확인
- JSON 응답 schema 호환성 확인
- 응답 시간과 token 규모 확인
- 소수 development 사례의 근거 형식 확인

사람 검토가 끝난 expected 포함 v3 사례를 같은 prompt로 채점할 때는
`scripts/benchmark_fixed_prompt.py`를 사용한다. 모델별 설정은
`configs/fixed-prompt-benchmark.*.yaml`에 있고, runner는 설정의 prompt SHA-256을 검증한 뒤 target
provider만 호출한다. optimizer와 candidate 생성은 없다.

```bash
uv run --locked python scripts/benchmark_fixed_prompt.py \
  --cases local-data/dart-qa/cases/cases.v3.jsonl \
  --config configs/fixed-prompt-benchmark.gemini-3.5-flash-lite.yaml \
  --split all \
  --output reports/model-benchmarks/gemini-3.5-flash-lite-YYYYMMDD-HHMMSS
```

`scripts/optimize_dart_qa_prompt.py`를 다중 모델의 고정 프롬프트 비교 도구로 사용하면 안 된다.
이 runner는 development 실패를 optimizer에 전달하고 모델별 candidate를 생성하므로 비교 조건이
달라진다.

## 7. 추가로 구현해야 하는 기능

고정 프롬프트를 모델별로 채점하는 runner는 구현돼 있다. 정식 Validation 모델 선택과 Test gate를
한 번에 관리하려면 다음 matrix orchestration 기능을 추가로 구현한다.

### 7.1 프롬프트를 안정된 경로로 승격

현재 선택 프롬프트는 커밋하지 않는 `reports/` 아래에 있다. 벤치마크 구현 전에 원본 파일의
SHA-256이 이 문서에 기록된 값과 일치하는지 확인하고, 사람 승인 후 같은 내용을
`prompts/dart-qa-selected-v1.md`처럼 버전이 붙은 안정된 경로에 복사한다. 복사본의 hash가 원본과
같아야 한다. 이후 모든 benchmark manifest는 이 안정된 파일과 hash를 사용한다.

이 문서의 예시 명령에 나오는 `prompts/dart-qa-selected-v1.md`는 아직 생성되지 않은 목표 경로다.
원본 확인 없이 새 프롬프트를 추정해 만들면 안 된다.

### 7.2 권장 파일 구조

```text
src/dart_parser_workflow/model_benchmark.py
scripts/benchmark_dart_qa_models.py
configs/model-benchmark.example.yaml
tests/test_model_benchmark.py
```

필요하면 strict Pydantic 모델은 `schemas.py`와 `config.py`에 추가한다. 모든 설정과 artifact
모델은 `extra="forbid"`를 유지한다.

### 7.3 재사용할 기존 코드

- `dataset.load_cases_v3`: dataset와 family split 검증
- `html_utils.read_html`: HTML 크기와 hash 검증
- `prompts.load_prompt`, `prompts.render_prompt`: 고정 프롬프트 로딩과 렌더링
- `providers.create_target_provider_v3`: provider별 target 생성
- `evaluation.score_answer_v3`: 결정론적 정답·근거 채점
- `execution.CallLedger`: token, 비용, 오류, 호출 metadata 기록

target provider에는 `{question}`과 `{html}`이 렌더링된 프롬프트만 전달한다. expected, accepted
answers, evidence anchors와 점수는 절대 전달하지 않는다.

### 7.4 두 단계 CLI

한 명령이 Validation과 Test를 연속 실행하지 않도록 두 단계로 나누는 것을 권장한다.

Validation 단계 예시:

```bash
uv run --locked python scripts/benchmark_dart_qa_models.py validate \
  --cases local-data/dart-qa/cases/cases.v3.jsonl \
  --prompt prompts/dart-qa-selected-v1.md \
  --matrix configs/model-benchmark.yaml \
  --output reports/model-benchmarks/benchmark-YYYYMMDD-validation
```

이 단계는 모든 후보 모델을 Validation에 실행하고 `selection.json`을 만든다. Test를 호출하지
않는다.

사람 승인 후 Test 단계 예시:

```bash
uv run --locked python scripts/benchmark_dart_qa_models.py test \
  --cases local-data/dart-qa/cases/cases.v3.jsonl \
  --prompt prompts/dart-qa-selected-v1.md \
  --matrix configs/model-benchmark.yaml \
  --selection reports/model-benchmarks/benchmark-YYYYMMDD-validation/selection.json \
  --output reports/model-benchmarks/benchmark-YYYYMMDD-test
```

Test 단계는 selection manifest의 dataset, prompt, scorer, Git, provider 설정 hash를 다시 검증하고
선택된 모델 하나만 실행해야 한다. 기존 출력 디렉터리를 재개하거나 덮어쓰지 않는다.

### 7.5 제안하는 matrix 설정 형태

아래는 아직 구현되지 않은 목표 schema 예시다.

```yaml
artifact_schema_version: 3
prompt_variants:
  - id: baseline
    path: prompts/dart-qa-baseline.md
  - id: selected
    path: prompts/dart-qa-selected-v1.md

models:
  - id: ollama-cloud-gpt-oss-120b
    provider:
      kind: ollama
      model: gpt-oss:120b
      api_key_env: OLLAMA_API_KEY
      base_url: https://ollama.com
      request_timeout_seconds: 300
      temperature: 0.0
      max_output_tokens: 8192
    limits:
      max_requests: 50
      max_attempts: 50
      max_wall_seconds: 3600

  - id: nvidia-nim-model-a
    provider:
      kind: nvidia_nim
      model: nvidia/실행-직전-확인한-모델-ID
      api_key_env: NVIDIA_NIM_API_KEY
      base_url: https://integrate.api.nvidia.com/v1
      request_timeout_seconds: 300
      temperature: 0.0
      max_output_tokens: 8192
    limits:
      max_requests: 50
      max_attempts: 50
      max_wall_seconds: 3600
```

Gemini도 같은 구조로 추가한다. provider가 지원하지 않는 sampling 옵션을 억지로 동일하게 만들지
말고, 실제 요청 설정과 실제 반환 모델 ID를 artifact에 기록한다.

### 7.6 산출물 구조

```text
reports/model-benchmarks/<run-id>/
├── manifest.json
├── calls.jsonl
├── results/
│   ├── <model-id>--<prompt-id>.jsonl
│   └── ...
├── summary.json
├── comparison.csv
├── comparison.md
└── selection.json            # Validation 단계에만 생성
```

`calls.jsonl`에는 전체 HTML이나 렌더링된 prompt를 기록하지 않는다. 다음과 같은 제한된 metadata만
기록한다.

- sample ID, family ID, split
- provider role, provider kind
- requested model, actual model
- dataset, HTML, prompt, scorer와 설정 SHA-256
- token, latency, 비용, attempt와 bounded error

### 7.7 실행 상태와 품질 상태

실행 완결성과 모델 품질을 분리한다.

- `complete`: 예정된 모든 호출과 artifact 생성 완료
- `partial`: 일부 호출이나 artifact만 완료
- `not_run`: provider 준비 단계에서 중단
- `pass`, `fail`, `inconclusive`: 별도의 품질 판정

모델 응답 오류가 있어도 모든 예정 사례를 시도했다면 실행은 `complete`일 수 있다. 반대로 높은
점수의 일부 결과만 있어도 전체 호출이 끝나지 않았다면 `partial`이다.

## 8. 테스트와 안전 요구사항

구현 시 다음 회귀 테스트를 포함한다.

- expected가 target prompt 또는 provider request에 포함되지 않는지 확인
- Validation 실행에서 Test provider 호출이 0건인지 확인
- Test 실행이 selection manifest의 모델 하나만 호출하는지 확인
- family가 여러 split에 걸치면 실행 전 실패하는지 확인
- prompt, dataset, HTML, scorer, Git hash가 다르면 Test 실행을 거부하는지 확인
- 동일 출력 디렉터리가 있으면 덮어쓰지 않고 실패하는지 확인
- generation error와 budget 초과 시 partial artifact를 보존하는지 확인
- 모델별 token, 비용, latency, requested/actual model이 분리 기록되는지 확인
- unanswerable 안전 보류와 answerable abstention을 별도로 집계하는지 확인
- `calls.jsonl`에 전체 HTML, prompt, expected가 들어가지 않는지 확인
- deterministic recorded provider로 전체 흐름을 오프라인 검증하는지 확인

완료 전 다음 명령을 실행한다.

```bash
uv run --locked pytest
uv run --locked ruff check .
uv run --locked python scripts/validate_dataset.py \
  --cases local-data/dart-qa/cases/cases.v3.jsonl \
  --config configs/prompt-optimization.ollama-cloud-nvidia-nim.yaml
git diff --check
```

샌드박스에서 uv cache를 사용할 수 없으면 프로젝트 설정을 바꾸지 말고 `.venv/bin/pytest`와
`.venv/bin/ruff check .`을 사용한다.

## 9. 사람 승인 지점

Codex는 다음 단계에서 멈추고 사람 승인을 받아야 한다.

1. 외부 전송 전: DART HTML을 각 provider에 보내는 권한
2. live 실행 전: 정확한 모델 ID, 가격 확인일, 요청·token·비용 상한
3. Validation 후: 자동 선택 결과와 오류·비용 검토
4. Test 전: selection manifest와 새로운 Test의 미공개 상태 확인
5. 결과 확정 전: 사람용 비교표와 실패 사례 검토

키 값이나 전체 HTML을 승인 화면, 로그 또는 결과 요약에 노출하지 않는다.

## 10. Codex 작업 순서

나중에 작업하는 Codex는 다음 순서를 따른다.

1. `AGENTS.md`, `README.md`, `docs/workflow.md`와 이 문서를 모두 읽는다.
2. `git status --short`로 사용자의 기존 변경을 확인하고 보존한다.
3. 현재 artifact와 dataset hash가 이 문서의 값과 일치하는지 확인한다.
4. 사용자가 원하는 비교가 탐색용인지 정식 모델 선택용인지 확인한다.
5. 비교할 provider·모델 ID와 비용 상한을 확정한다.
6. 정식 실험이면 `$prepare-dart-qa-data`로 새로운 family와 split을 준비하고 사람 검토를 받는다.
7. 고정 프롬프트 benchmark runner와 오프라인 회귀 테스트를 구현한다.
8. 전체 pytest, Ruff, dataset validator와 diff check를 통과시킨다.
9. 소수 development 사례로 provider smoke test를 수행한다.
10. Validation을 실행하고 selection manifest를 만든 뒤 사람 승인을 기다린다.
11. 승인 후 선택된 모델만 새로운 Test에 실행한다.
12. 정답 정확도와 엄격 통과를 혼동하지 않는 한국어 비교 보고서를 작성한다.

## 11. Codex에 전달할 작업 요청 예시

다음 요청을 새 Codex 작업에 그대로 사용할 수 있다.

> `docs/multi-model-benchmark-guide.md`를 먼저 전부 읽고 가이드에 따라 작업해줘. 고정된 개선
> 프롬프트를 Gemini, Ollama, NVIDIA NIM target 모델에 공정하게 비교할 수 있는 두 단계
> Validation/Test benchmark runner를 구현해. expected answer는 provider에 보내지 말고 Python만
> 채점과 모델 선택을 담당해야 해. 우선 recorded provider를 사용한 오프라인 테스트와 문서까지
> 완료한 뒤, live 모델 호출 전에 정확한 모델 목록·비용·DART HTML 외부 전송 승인을 요청하고
> 기다려줘. 기존 Test는 탐색용으로만 취급하고 정식 최종 평가는 새로운 family를 사용해.

## 12. 완료 정의

다음 조건을 모두 만족해야 작업이 완료된다.

- 같은 고정 프롬프트와 사례가 모든 후보 모델에 적용됨
- expected가 어떤 target 호출에도 포함되지 않음
- Validation만으로 모델을 선택함
- Test는 선택 완료와 사람 승인 후 선택 모델 하나에만 실행됨
- lineage hash와 provider 사용량이 완전하게 기록됨
- 새 출력 디렉터리만 사용하고 partial run을 보존함
- 모델별 정답·근거·문맥·안전 보류·오류·속도·비용 비교표가 생성됨
- 전체 테스트와 Ruff가 통과함
- 사람이 읽을 수 있는 한국어 최종 보고서가 생성됨
