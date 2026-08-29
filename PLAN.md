# OSSAI-26 다음 작업 계획

상태 기준일: 2026-08-28

## 1. 이 문서의 목적

이 문서는 대화 기록이 없는 새 Codex 컨텍스트가 현재 작업을 안전하게 이어가기 위한 handoff다.

다음 목표는 기존 `주요사항보고서(유상증자결정)` 중심 DART QA를 아래 세 공시 유형으로 확장하는
것이다.

1. 주요사항보고서(유상증자결정)
2. 증권신고서(지분증권)
3. 소액공모공시서류(지분증권)

새 실험에서는 공시 유형 공통 문제와 유형별 문제를 만들고, 여러 target 모델에 동일한 데이터와
프롬프트를 적용한다. 교차 문서 비교와 파서 코드 생성은 단일 문서 QA가 안정된 뒤 별도 단계로
추가한다.

## 2. 새 컨텍스트가 가장 먼저 할 일

- [ ] 저장소 루트가 `/Users/sungwib/Desktop/ToyProject/OSSAI-26`인지 확인한다.
- [ ] `AGENTS.md`를 읽는다.
- [ ] `.agents/skills/prepare-dart-qa-data/SKILL.md`를 전부 읽는다.
- [ ] HTML 수집 전 `.claude/skills/dart-html-fetch/SKILL.md`를 전부 읽는다.
- [ ] `README.md`와 `docs/workflow.md`를 읽는다.
- [ ] 아래 세 가이드를 전부 읽는다.
  - `docs/project-status-overview-20260828.md`
  - `docs/multi-model-benchmark-guide.md`
  - `docs/multi-filing-type-qa-experiment-guide.md`
- [ ] `git status --short`를 실행하고 기존 변경을 보존한다.
- [ ] 아래 SHA-256을 실제 파일과 대조한다.
- [ ] 사용자 승인 전 target, optimizer 또는 Test를 호출하지 않는다.

## 3. 변경 보존 주의

2026-08-28 현재 worktree에는 기존 수정과 미추적 파일이 있다. 새 컨텍스트는 이를 사용자 작업으로
간주하고 삭제, reset, checkout 또는 덮어쓰지 않는다.

현재 확인된 상태:

```text
 M README.md
 M docs/workflow.md
 M src/dart_parser_workflow/config.py
?? PLAN.md
?? configs/fixed-prompt-benchmark.gemini-3.5-flash-lite.yaml
?? configs/fixed-prompt-benchmark.gpt-oss-120b.yaml
?? configs/fixed-prompt-benchmark.nemotron-3-ultra.yaml
?? configs/fixed-prompt-benchmark.qwen3.5-cloud.yaml
?? docs/complex-prompt-experiment-guide.md
?? docs/multi-filing-type-qa-experiment-guide.md
?? docs/multi-model-benchmark-guide.md
?? docs/project-status-overview-20260828.md
?? scripts/benchmark_fixed_prompt.py
?? src/dart_parser_workflow/fixed_prompt_benchmark.py
?? tests/test_fixed_prompt_benchmark.py
```

`local-data/`와 `reports/`는 Git에서 제외된 로컬 산출물이다. 실제 DART HTML, 사람 검토 데이터와
모델 결과를 Git에 추가하지 않는다.

## 4. 현재까지 완료된 상태

### 4.1 기존 30문제 데이터셋

- 공시: 주요사항보고서 계열 10개
- 사례: 30개
- split: Development 12 / Validation 9 / Test 9
- 최종 경로: `local-data/dart-qa/cases/cases.v3.jsonl`
- 파일 SHA-256: `ac384246fa6ad188d3b0207470a800a2759fe5f74a2a639e069bd2b0f46462fb`
- canonical dataset SHA-256:
  `ac94a5abe63b24a398b50b1e9d7e90cba076209c7a92ff8497d4923d0f480992`

이 데이터의 Test 결과와 실패 유형은 이미 공개됐으므로 이후 공식 Test로 재사용하지 않는다.

### 4.2 기존 개선 프롬프트 v1

- 경로: `reports/prompt-optimization/ollama-cloud-nim-20260824-01/selected-prompt.md`
- SHA-256: `9d24e442571204775807875888c401b241fa325450e23585485bd6dd52dc7954`
- 기존 대표 target: Ollama Cloud `gpt-oss:120b`
- 기존 optimizer: NVIDIA NIM `nvidia/nemotron-3-ultra-550b-a55b`

### 4.3 v1 다중 모델 탐색 결과

같은 30문제와 같은 v1을 적용한 결과:

| 모델 | 값 정확도 | strict pass | generation error |
|---|---:|---:|---:|
| `gpt-oss:120b` | 26/30 | 1/30 | 0 |
| `gemini-3.5-flash-lite` | 22/30 | 9/30 | 0 |
| `nvidia/nemotron-3-ultra-550b-a55b` | 24/30 | 15/30 | 3 |

`qwen3.5:cloud`는 현재 Ollama 계정에서 구독이 필요해 smoke 요청 세 건이 HTTP 403으로 차단됐다.
전체 실행하지 않았다.

상세 보고서:
`reports/model-benchmarks/fixed-v1-20260825-comparison.md`

### 4.4 승인된 공통 프롬프트 v2

- 경로: `reports/prompt-variants/shared-v2-draft-20260826-01/prompt.md`
- SHA-256: `f73d781479fbde4794be6e1b37e7824b682740b37070ba33f119d24232f4b431`
- 검토자: 윤성원
- 상태: 사람 승인 완료
- target 호출: 아직 없음
- optimizer 호출: 없음

v2는 원문 값 보존, 실제 연속 evidence, 주변 숫자 추측 금지와 안전한 abstention을 강화한다.

### 4.5 승인된 신규 Validation 9문제

- 공시 family: 3개
- 사례: 9개
- answerable: 9개
- unanswerable: 0개
- 경로: `local-data/dart-qa/cases/validation-20260827-01.cases.v3.jsonl`
- 파일 SHA-256: `1a8e51deefa98b29544e9a4c45ee97ef7fe68edabb20ae41c730b2224223a22c`
- canonical dataset SHA-256:
  `71fc1e491700f73dbe8e3337b743bccf31efe247064ba0df03ab31dfd74501a7`
- 검토자: 윤성원
- 승인: 9/9

이 Validation은 v2가 동결된 뒤 만들어졌지만 모두 answerable이므로 safe-abstention 성능은 평가할
수 없다.

### 4.6 구현된 고정 프롬프트 runner

관련 파일:

- `scripts/benchmark_fixed_prompt.py`
- `src/dart_parser_workflow/fixed_prompt_benchmark.py`
- `tests/test_fixed_prompt_benchmark.py`
- `configs/fixed-prompt-benchmark.*.yaml`

runner의 보장 사항:

- prompt SHA를 provider 호출 전에 검증
- expected 미전송
- optimizer 미호출
- candidate 미생성
- 새 output 디렉터리 강제
- 전체 HTML과 렌더링된 prompt를 `calls.jsonl`에 기록하지 않음

구현 당시 오프라인 테스트는 64개 통과했고 Ruff도 통과했다. 새 컨텍스트는 작업 후 다시 검증한다.

## 5. 절대 지켜야 할 실험 규칙

- [ ] target prompt에 expected, accepted answer, 기대 evidence anchor를 넣지 않는다.
- [ ] optimizer에는 Development strict 실패만 전달한다.
- [ ] Validation은 prompt·모델·input strategy 선택에만 사용한다.
- [ ] Test는 선택된 조합 하나에만 실행한다.
- [ ] 같은 transaction의 모든 공시 유형, 정정본과 section 파생물은 같은 family와 split에 둔다.
- [ ] 숫자 구두점, 부호, 날짜, 단위와 재무 범위를 자동 정규화하지 않는다.
- [ ] 원문 `-`를 `0`, `--` 또는 `답변 보류`로 바꾸지 않는다.
- [ ] 하나의 값을 확정할 수 없으면 추측하지 않고 정확히 `답변 보류`한다.
- [ ] full HTML을 모델마다 다르게 자르지 않는다.
- [ ] existing dataset, review와 output 디렉터리를 덮어쓰지 않는다.
- [ ] 모델이 점수나 승자를 결정하게 하지 않는다.
- [ ] DART HTML 외부 전송은 별도 사용자 승인 후에만 실행한다.
- [ ] parser 코드는 별도 승인과 sandbox 없이 실행하지 않는다.

## 6. 시작 전에 필요한 사용자 결정

새 컨텍스트는 다음 두 실험을 조용히 섞지 않는다.

### 결정 A. 기존 주요사항보고서 v1/v2 실험 마감

선택지:

1. 권장: unanswerable Validation family를 추가한 뒤 v1/v2 × 3모델을 비교한다.
2. 빠른 예비평가: 현재 answerable 9문제로 비교하되 abstention 성능 미평가를 명시한다.
3. 현재 상태로 동결하고 다중 공시 유형 pilot부터 시작한다.

사용자가 선택하지 않았다면 새 컨텍스트는 이 결정을 먼저 요청한다. 기존 실험을 마감하지 않아도
다중 유형 pilot의 로컬 데이터 준비는 가능하지만 artifact와 결론을 별도 experiment로 관리한다.

### 결정 B. 다중 공시 유형 pilot URL

권장 입력은 유형별 3개, 총 9개의 새로운 Development family다.

```text
검토자: 이름
용도: 다중 공시 유형 Development pilot
수집 범위: 전체 HTML + 목차 목록

[주요사항보고서(유상증자결정)]
URL 3개

[증권신고서(지분증권)]
URL 3개

[소액공모공시서류(지분증권)]
URL 3개

[거래 연결 관계]
- 같은 발행 거래에 속한 URL 묶음
- 원본/정정/발행조건확정 관계
```

URL이 없으면 임의 공시를 골라 수집하지 않는다.

## 7. 권장 활성 작업: 다중 공시 유형 Development pilot

### Phase 1. 데이터 계약 초안

- [ ] 세 공시 유형의 최신 공식 서식과 실제 목차를 확인한다.
- [ ] `metric contract` 목록을 작성한다.
- [ ] 공통 문제와 유형별 문제를 분리한다.
- [ ] 각 metric의 기간, 범위, 단위, 예정/확정 우선순위와 unanswerable 조건을 명시한다.
- [ ] taxonomy 초안을 사람에게 보여 주고 승인받는다.

권장 공통 metric:

- `equity_type`
- `new_share_count`
- `issue_price_per_share`
- `gross_proceeds`
- `facility_funds`
- `operating_funds`
- `debt_repayment_funds`
- `subscription_period`
- `payment_date`
- `allocation_method`

공통이라는 이유만으로 질문 문구를 먼저 만들지 않는다. 세 유형에서 의미, 범위와 상태가 동일한지
확인한 뒤 같은 metric ID를 사용한다.

### Phase 2. HTML 수집과 transaction manifest

- [ ] `.claude/skills/dart-html-fetch/SKILL.md`를 읽는다.
- [ ] 전체 HTML을 `local-data/dart-qa-multitype/html/<filing-type>/` 아래 새 경로에 저장한다.
- [ ] 증권신고서와 소액공모공시서류는 `--list-sections` 결과도 보존한다.
- [ ] HTML SHA-256과 파일 크기를 기록한다.
- [ ] 같은 거래와 정정 체인을 transaction manifest에 묶는다.
- [ ] 모든 pilot family는 Development에 둔다.
- [ ] model/provider를 호출하지 않는다.

실제 Python fetch driver는 현재 저장소에서 다음 경로에 있다.

```text
.claude/skills/dart-html-fetch/driver/main.py
```

스킬 문서에 `driver.python/main.py`가 기재돼 있어도 실제 파일 위치를 먼저 확인한다.

권장 manifest 경로:

```text
local-data/dart-qa-multitype/manifests/transactions.development-pilot.v1.jsonl
```

transaction 단위 family 예시:

```text
transaction-<issuer-id>-<board-decision-date>-<sequence>
```

### Phase 3. 입력 전략 결정

증권신고서가 길기 때문에 세 전략을 섞지 않는다.

1. full document end-to-end
2. 사람 승인 section bundle
3. retrieval + extraction

pilot에서는 full HTML을 원본으로 반드시 보존한다. 모든 target의 공통 context 한도에 들어오지 않으면
모델별 truncation을 하지 말고 section bundle 전략을 선택한다.

section bundle을 사용할 때 기록할 항목:

- parent full HTML path와 SHA
- section 번호·이름
- DART offset·length
- bundle 생성 방법
- bundle path와 SHA
- 사람 승인자

token 한도에서 HTML 앞부분만 자르는 방식은 금지한다.

### Phase 4. report-local QA 초안

첫 pilot은 현재 schema v3가 지원하는 L1, L2와 일부 L3에 한정한다.

- L1: 직접 행·열 추출
- L2: 예정/확정, 정정 전후와 증권 종류 선택
- L3: 같은 문서의 여러 section 문맥 연결. 단, 답 자체는 원문에 존재해야 함

권장 tag:

```text
filing:major-equity-issuance
filing:registration-equity
filing:small-offering-equity
task:direct
task:context-selection
task:cross-section
state:original
state:corrected
state:final-terms
metric:<canonical-id>
answerable
unanswerable
```

정답 초안 규칙:

- answerable 답과 evidence는 visible HTML 원문에서 복사한다.
- 값, 부호, 쉼표와 단위를 변형하지 않는다.
- answer가 evidence에 실제로 포함돼야 한다.
- evidence에는 항목, 기간·상태, 범위, 단위와 값을 식별할 문맥을 포함한다.
- unanswerable은 정확히 `답변 보류`, 빈 accepted answer/evidence/anchor를 사용한다.
- target 모델 답을 ground truth로 사용하지 않는다.

권장 pilot 규모:

- 유형별 Development family 3개
- family별 공통 문제 3~5개
- family별 유형 문제 2~3개
- 전체 약 45~72개 사례
- 유형별 answerable/unanswerable을 모두 포함

### Phase 5. materialize와 사람 검토

- [ ] draft JSONL을 새 run ID로 만든다.
- [ ] prepare skill의 `materialize` 명령을 실행한다.
- [ ] 사람용 검토표에 질문, 답, 기간, 범위, 단위, evidence를 모두 표시한다.
- [ ] 검토자가 각 사례를 명시적으로 승인하거나 수정하게 한다.
- [ ] 승인 전에는 final dataset을 만들지 않는다.
- [ ] 승인 전에는 target, optimizer 또는 robustness provider를 호출하지 않는다.

명령 템플릿:

```bash
.venv/bin/python \
  .agents/skills/prepare-dart-qa-data/scripts/prepare_dataset.py materialize \
  --drafts <새-draft.jsonl> \
  --prepared <새-prepared.jsonl> \
  --reviews <새-pending-review.jsonl> \
  --project-root .
```

사람 승인 후 pending review를 덮어쓰지 말고 새 approved review 파일을 만든다. 그 후 새 final output
경로로 finalize한다.

```bash
.venv/bin/python \
  .agents/skills/prepare-dart-qa-data/scripts/prepare_dataset.py finalize \
  --prepared <prepared.jsonl> \
  --reviews <approved-review.jsonl> \
  --config configs/prompt-optimization.default.yaml \
  --output <새-final-cases.v3.jsonl> \
  --project-root .
```

### Phase 6. 정식 데이터 균형 validator

현재 validator는 global tag 최소 개수만 확인한다. 정식 multi-type 데이터 전에 다음 교차 행렬을
검증하는 기능과 회귀 테스트를 추가한다.

- filing type × split
- filing type × answerability
- filing type × task level
- filing state × split
- metric × filing type

같은 transaction의 모든 source와 정정본이 한 split에만 있는지도 manifest 기반으로 검증한다.

schema, validator 또는 output 파일을 변경하면 `README.md`와 `docs/workflow.md`도 함께 갱신한다.

## 8. 현재 v3에 넣지 말아야 할 문제

다음 문제를 하나의 `html_path` v3 사례에 억지로 넣지 않는다.

- 주요사항보고서와 증권신고서 값 비교
- 원본과 정정본의 변화량 계산
- 여러 source 중 최신 유효값 선택
- 발행주식수 × 발행가액 계산
- 자금 사용 목적 세부 금액 합계
- 희석률 계산
- 실행 가능한 parser 코드 생성

현재 v3는 한 사례에 source와 `html_path` 하나만 가진다. 계산 결과도 evidence 원문에 존재해야 하는
현재 scorer와 충돌할 수 있다.

L4 교차 문서 비교와 L5 계산·parser synthesis는 additive v4 또는 별도 artifact로 설계한다. 기존
v3 모델과 scorer를 변경하지 않는다.

## 9. additive v4 이후 계획

report-local pilot이 안정된 뒤에만 진행한다.

- [ ] `sources[]`와 source별 HTML SHA 지원
- [ ] source ID가 포함된 evidence 구조
- [ ] transaction manifest lineage 검증
- [ ] original/corrected/final-terms precedence 검증
- [ ] 계산식, 입력값, 허용 오차 구조
- [ ] v3와 병행 가능한 strict Pydantic schema
- [ ] 잘못된 source evidence와 family leakage 회귀 테스트
- [ ] docs와 README 동시 갱신

parser synthesis는 별도 워크플로로 둔다.

- 입력과 출력 schema 고정
- Development fixture만 코드 생성 모델에 제공
- 네트워크 차단
- 허용 라이브러리 고정
- 임의 파일 쓰기 차단
- timeout, memory와 output 제한
- Validation으로 코드 후보 선택
- 선택한 코드 하나만 새 Test fixture에 실행

## 10. 다중 모델 실험 계획

사람 검토가 끝난 multi-type dataset과 범용 baseline이 준비된 뒤 실행한다.

현재 후보 모델:

- Ollama Cloud `gpt-oss:120b`
- Gemini `gemini-3.5-flash-lite`
- NVIDIA NIM `nvidia/nemotron-3-ultra-550b-a55b`

Prompt 전략:

1. 범용 baseline 하나
2. 공통 core + 유형 addendum 후보 하나

모델별 전용 candidate를 만들지 않는다.

Validation 행렬:

| 모델 | 범용 baseline | core + 유형 addendum |
|---|---:|---:|
| GPT-OSS | 실행 | 실행 |
| Gemini | 실행 | 실행 |
| Nemotron | 실행 | 실행 |

각 조합은 동일한 dataset, input strategy와 scorer를 사용하고 새 output 디렉터리에 기록한다.

실행 전 필수 승인:

- 정확한 모델 ID
- provider별 API key env 이름. 키 값 자체는 요청하지 않음
- 요청·token·시간·비용 상한
- 최신 pricing 또는 비용 미산정 표기
- DART HTML을 각 provider로 전송한다는 명시적 승인

고정 프롬프트 runner 명령 형식:

```bash
.venv/bin/python scripts/benchmark_fixed_prompt.py \
  --cases <승인된-cases.v3.jsonl> \
  --config <고정-prompt-config.yaml> \
  --split validation \
  --output <새-output-directory>
```

`--output`은 기존 경로를 사용하지 않는다. v1/v2 또는 범용/routed prompt마다 별도 config에서
`prompt_path`와 `prompt_sha256`을 고정한다.

## 11. 채점과 선택 기준

전체 평균만 보지 않는다.

필수 지표:

- exact answer
- strict pass
- evidence in document
- context coverage
- unsafe answer
- answerable abstention
- generation/capacity error
- input/output tokens
- mean/p95 latency
- 검증 가능한 경우 비용

층화 지표:

- 공시 유형별 strict pass
- 공통 metric별 strict pass
- task level별 strict pass
- original/corrected/final-terms별 strict pass
- 유형별 safe-abstention
- 유형별 macro average와 worst-type strict pass

후보 prompt rollback 조건:

- generation error 증가
- unsafe answer 증가
- answerable abstention 증가
- 전체 strict pass 감소
- 특정 공시 유형이 허용 하락폭을 초과
- mean improvement 기준 미달
- 승인된 비용·latency 상한 초과

Validation에서 `model + prompt SHA + input strategy` 조합 하나를 Python으로 선택한다. Test에는 이
조합 하나만 실행한다.

## 12. 승인 게이트

새 컨텍스트는 다음 지점에서 멈추고 사용자의 명시적 승인을 기다린다.

- [ ] pilot URL과 transaction 연결을 확정한 뒤
- [ ] 공통 metric contract와 질문 목록을 만든 뒤
- [ ] 답·기간·범위·단위·evidence 검토표를 만든 뒤
- [ ] section bundle을 확정한 뒤
- [ ] HTML을 외부 provider에 보내기 전
- [ ] 범용/routed prompt 후보와 SHA를 만든 뒤
- [ ] Validation selection을 만든 뒤
- [ ] 새로운 Test를 호출하기 전
- [ ] 생성된 parser 코드를 실행하기 전

승인 없이 다음 단계로 넘어가지 않는다. 과거의 다른 HTML 또는 다른 provider 전송 승인을 새
multi-type 데이터에 자동 적용하지 않는다.

## 13. 검증 명령

의존성 변경이 필요하지 않으면 lockfile을 수정하지 않는다.

우선 명령:

```bash
uv run --locked pytest
uv run --locked ruff check .
```

샌드박스의 uv cache 접근이 막히면 설정을 바꾸지 말고 다음을 사용한다.

```bash
.venv/bin/pytest
.venv/bin/ruff check .
```

v3 데이터 검증:

```bash
.venv/bin/python scripts/validate_dataset.py \
  --cases <final-cases.v3.jsonl> \
  --config configs/prompt-optimization.default.yaml
```

마지막에 실행:

```bash
git diff --check
git status --short
```

실제 HTML, `.env`, API 키 또는 생성된 `reports/`를 commit 대상으로 추가하지 않는다.

## 14. 다음 컨텍스트가 사용자에게 처음 보고할 내용

다음과 같이 짧게 보고한 뒤 진행한다.

```text
PLAN.md와 다중 공시 유형 가이드를 확인했습니다. 기존 데이터·프롬프트 SHA와 dirty worktree를
보존하겠습니다. 먼저 기존 주요사항보고서 v1/v2 실험을 마감할지, 별도 multi-type Development
pilot을 바로 시작할지 확인하겠습니다. pilot을 시작하려면 세 공시 유형별 URL 3개와 같은 거래·정정
관계를 보내주세요. HTML 수집과 사람 검토 단계에서는 모델을 호출하지 않겠습니다.
```

사용자가 이미 URL과 관계를 제공했다면 같은 질문을 반복하지 말고 Phase 1부터 실행한다.

## 15. 현재 권장 next action

가장 권장하는 즉시 다음 작업은 다음과 같다.

1. 기존 주요사항보고서 실험을 별도 artifact로 동결할지 사용자에게 확인한다.
2. multi-type Development pilot URL을 유형별 3개씩 받는다.
3. 모델 호출 없이 전체 HTML과 목차를 수집한다.
4. transaction manifest와 공통 metric contract 초안을 만든다.
5. 유형별·공통 문제 초안과 사람 검토표를 만든다.
6. 검토 승인 전 멈춘다.

## 16. 완료 정의

### Development pilot 완료

- 세 공시 유형의 family가 각각 최소 3개 있음
- full HTML과 목차 lineage가 보존됨
- transaction과 정정 관계가 manifest에 기록됨
- 공통 metric contract와 유형별 질문이 사람에게 승인됨
- answerable/unanswerable 사례가 각 유형에 존재함
- prepared cases와 review가 schema와 HTML 근거 검증을 통과함
- 사람 승인 전 provider를 호출하지 않음

### 정식 multi-type 실험 완료

- filing type × split × answerability 균형이 기계적으로 검증됨
- 범용 prompt와 유형 addendum prompt가 새 Validation에서 비교됨
- 같은 데이터와 input strategy가 모든 모델에 적용됨
- expected와 채점 정보가 target에 전달되지 않음
- Python selector가 조합 하나를 선택하거나 rollback함
- Test는 승인된 선택 조합 하나에만 실행됨
- 유형별 품질, 안전성, 오류, 비용과 latency 보고서가 생성됨
- 교차 문서와 parser synthesis는 additive schema·sandbox로 분리됨
- 기존 v3 데이터, 프롬프트와 결과가 변경되지 않음
