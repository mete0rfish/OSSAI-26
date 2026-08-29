# DART QA 프롬프트 실험 현황

작성 기준일: 2026-08-28

## 1. 프로젝트 목적

이 프로젝트는 DART 공시 HTML에서 AI 모델이 질문에 해당하는 값을 정확하게 추출할 수 있는지
평가하고, 그 결과를 바탕으로 프롬프트를 개선하는 실험이다.

현재 모든 공시에 다음 세 질문을 적용한다.

1. 기준주가에 대한 할인 또는 할증률은 얼마인가?
2. 자금조달의 목적 중 시설자금은 얼마인가?
3. 신주발행가액은 얼마인가?

평가는 숫자만 맞히는지에 그치지 않는다. 모델은 원문의 쉼표, 부호, 하이픈과 단위를 임의로
바꾸지 않아야 하며, 값을 확정할 수 없으면 추측하지 않고 `답변 보류`해야 한다. 제출한 근거도
현재 HTML에 실제로 존재하고 항목명·범위·단위·값을 식별할 수 있어야 한다.

이 조건을 모두 통과한 사례를 `strict pass`로 집계한다.

## 2. 역할과 누출 방지 원칙

워크플로에는 세 역할이 있다.

- target 모델: 질문과 HTML을 받아 답과 근거를 생성한다.
- optimizer 모델: Development 실패를 읽고 후보 프롬프트를 제안한다.
- Python 채점기·selector: 점수를 계산하고 프롬프트 채택 또는 rollback을 결정한다.

다음 원칙을 유지한다.

- 기대 정답은 target 모델에 보내지 않는다.
- Development 실패만 프롬프트 후보 생성에 사용한다.
- Validation은 후보 선택에만 사용한다.
- Test는 선택이 끝난 뒤 한 번만 실행한다.
- 같은 공시에서 만든 사례는 같은 `family_id`와 split에 배치한다.
- 모델이 점수나 승자를 결정하지 않는다.
- 전체 HTML과 렌더링된 전체 프롬프트를 호출 로그에 저장하지 않는다.

## 3. 최초 30문제 데이터셋

DART 공시 10개의 전체 HTML을 수집하고 공시당 세 질문을 적용해 총 30문제를 만들었다.

| 항목 | 값 |
|---|---:|
| 공시 | 10개 |
| 전체 사례 | 30개 |
| Development | 12개 |
| Validation | 9개 |
| Test | 9개 |
| 데이터셋 SHA-256 | `ac94a5abe63b24a398b50b1e9d7e90cba076209c7a92ff8497d4923d0f480992` |

사람 검토 과정에서 다음 기준을 확정했다.

- 표에 적힌 `-`는 `0`이나 `답변 보류`로 바꾸지 않고 원문 그대로 `-`로 사용한다.
- 할인율 후보가 여러 개면 질문 대상 표 항목에 직접 대응하는 값을 사용한다.
- 확정발행가가 없고 예정발행가에 값이 있으면 예정발행가를 사용한다.
- 여러 후보 중 하나를 확정할 수 없으면 `답변 보류`한다.

데이터셋은
[`local-data/dart-qa/cases/cases.v3.jsonl`](../local-data/dart-qa/cases/cases.v3.jsonl)에 있다.

## 4. 첫 번째 개선 프롬프트 v1

초기 프롬프트의 Development 실패를 분석하고 다음 구성으로 프롬프트를 개선했다.

- 대표 target: Ollama Cloud `gpt-oss:120b`
- optimizer: NVIDIA NIM `nvidia/nemotron-3-ultra-550b-a55b`
- 선택된 프롬프트 SHA-256:
  `9d24e442571204775807875888c401b241fa325450e23585485bd6dd52dc7954`

이 프롬프트를 현재 실험에서는 v1 개선 프롬프트라고 부른다.

원본은
[`reports/prompt-optimization/ollama-cloud-nim-20260824-01/selected-prompt.md`](../reports/prompt-optimization/ollama-cloud-nim-20260824-01/selected-prompt.md)에
보존되어 있다.

## 5. v1 고정 다중 모델 평가

v1을 수정하지 않고 같은 30문제와 같은 채점기를 세 target 모델에 적용했다.

| 모델 | 값 정확도 | 엄격 통과 | generation error | 평균 지연 |
|---|---:|---:|---:|---:|
| `gpt-oss:120b` | **26/30** | 1/30 | 0 | **2.93초** |
| `gemini-3.5-flash-lite` | 22/30 | 9/30 | 0 | 6.52초 |
| `nvidia/nemotron-3-ultra-550b-a55b` | 24/30 | **15/30** | 3 | 41.50초 |

`qwen3.5:cloud`도 후보였지만 현재 Ollama 계정에서 구독이 필요한 모델이어서 smoke 단계의 세 요청이
모두 HTTP 403으로 차단됐다. 전체 30문제는 실행하지 않았다.

### 모델별 특징

#### GPT-OSS

- 값은 30개 중 26개를 맞혀 가장 높은 값 정확도를 기록했다.
- 실제 HTML에 없는 형태로 근거를 재구성하는 경우가 많았다.
- 값은 맞아도 근거 조건을 충족하지 못해 strict 통과는 1개뿐이었다.

#### Gemini 3.5 Flash-Lite

- 근거, 문맥, 실행 안정성의 균형이 비교적 좋았다.
- 원문의 하이픈 한 글자 `-`를 `--`로 변경하는 오류가 발생했다.

#### NVIDIA Nemotron 3 Ultra

- strict 통과와 근거 원문 일치 성능이 가장 높았다.
- 다른 모델보다 느렸고 NVIDIA endpoint 과부하로 HTTP 503 오류가 3건 발생했다.

세 모델 모두 답을 확정할 수 없는 할인율 사례에서 주변 문장의 다른 숫자 `25`를 가져오는
unsafe answer를 만들었다.

상세 결과는
[`reports/model-benchmarks/fixed-v1-20260825-comparison.md`](../reports/model-benchmarks/fixed-v1-20260825-comparison.md)에서
확인할 수 있다.

이 평가의 Test 결과와 실패 유형은 이미 사람에게 공개됐다. 따라서 현재 30문제 결과는 모델의
특성을 이해하는 탐색·진단 자료이며, 새로운 프롬프트의 공식 최종 성능으로 주장할 수 없다.

## 6. 공통 프롬프트 v2

세 모델의 Development 12개 결과에서 관찰한 실패만 이용해 공통 프롬프트 v2를 작성했다. 모델별
전용 candidate는 만들지 않았다.

v2의 주요 변경은 다음과 같다.

- 질문 대상 행·열에 직접 대응하는 값만 선택한다.
- 발행가 산정 설명 등 주변 문장의 다른 할인율을 대신 사용하지 않는다.
- 원문에 없는 `원`, `%`, 공백이나 설명을 답에 추가하지 않는다.
- 하이픈 한 글자 `-`를 `--`로 바꾸거나 답변 보류로 처리하지 않는다.
- 확정발행가에 값이 있으면 우선하고, 없을 때 값이 있는 예정발행가를 사용한다.
- 근거를 재구성하지 않고 HTML에 존재하는 짧은 연속 원문을 제출한다.
- 하나의 값을 확정할 수 없으면 추측하지 않고 `답변 보류`한다.

후보 작성 과정에서는 target과 optimizer를 호출하지 않았다. Validation/Test의 개별 정답이나
공시번호도 프롬프트에 포함하지 않았다.

| 항목 | 값 |
|---|---|
| 검토자 | 윤성원 |
| 결정 | 승인 |
| v2 SHA-256 | `f73d781479fbde4794be6e1b37e7824b682740b37070ba33f119d24232f4b431` |

관련 산출물:

- [승인된 v2 프롬프트](../reports/prompt-variants/shared-v2-draft-20260826-01/prompt.md)
- [v2 변경 근거](../reports/prompt-variants/shared-v2-draft-20260826-01/change-rationale.md)
- [윤성원 승인 기록](../reports/prompt-variants/shared-v2-draft-20260826-01/approval-20260827-yoon-seongwon.json)

v2는 아직 target 모델에 실행하지 않았다.

## 7. 새로운 Validation 데이터

v2를 이미 노출된 30문제로 선택하지 않기 위해 새로운 DART 공시 세 개를 수집했다. 공시당 같은
세 질문을 적용해 Validation 9문제를 만들었다.

| 접수번호 | 할인·할증률 | 시설자금 | 신주발행가액 |
|---|---:|---:|---:|
| `20260826000431` | `-10` | `-` | `1,301` |
| `20260826000480` | `-10` | `-` | `2,858` |
| `20260826000580` | `-10` | `-` | `631` |

| 항목 | 값 |
|---|---|
| 신규 family | 3개 |
| Validation 사례 | 9개 |
| answerable | 9개 |
| unanswerable | 0개 |
| 검토자 | 윤성원 |
| 승인 | 9/9 |
| 데이터셋 SHA-256 | `71fc1e491700f73dbe8e3337b743bccf31efe247064ba0df03ab31dfd74501a7` |

관련 산출물:

- [최종 Validation 데이터셋](../local-data/dart-qa/cases/validation-20260827-01.cases.v3.jsonl)
- [승인된 검토 기록](../local-data/dart-qa/reviews/validation-20260827-01.review.approved.jsonl)
- [사람이 읽는 검토표](../local-data/dart-qa/reviews/validation-20260827-01.review.md)

현재 신규 Validation은 모두 answerable이다. 값 추출과 근거 품질은 비교할 수 있지만, v2의 주요
목표인 안전한 `답변 보류` 성능은 평가할 수 없다는 한계가 있다.

## 8. 구현된 다중 모델 실행 기반

같은 프롬프트를 여러 target 모델에 공정하게 적용하기 위한 고정 프롬프트 benchmark runner를
구현했다.

runner는 다음 조건을 보장한다.

- 실행 전 설정의 프롬프트 SHA-256과 실제 파일을 대조한다.
- 기대 정답을 target 모델에 보내지 않는다.
- optimizer를 생성하거나 호출하지 않는다.
- 모델별 candidate 프롬프트를 만들지 않는다.
- 모델마다 새로운 output 디렉터리를 사용한다.
- 전체 HTML과 렌더링된 전체 프롬프트를 호출 로그에 저장하지 않는다.
- dataset, prompt, scorer, model과 Git 계보를 결과에 기록한다.

구현 당시 오프라인 테스트 64개와 Ruff 검사를 모두 통과했다.

관련 문서:

- [프로젝트 README](../README.md)
- [실행·채점 워크플로](workflow.md)
- [다중 모델 benchmark 가이드](multi-model-benchmark-guide.md)
- [복잡한 프롬프트 실험 가이드](complex-prompt-experiment-guide.md)

## 9. 현재 상태

완료된 작업:

- 최초 30문제 데이터셋 작성과 사람 검토
- 첫 번째 개선 프롬프트 v1 생성
- 같은 v1으로 세 모델의 탐색 평가
- 다중 모델 평가 결과와 공통 실패 유형 분석
- 공통 프롬프트 v2 작성과 사람 승인
- 새로운 Validation 9문제 작성과 사람 승인
- 고정 프롬프트 다중 모델 runner 구현

아직 하지 않은 작업:

- 신규 Validation에서 v1과 v2 실행
- `3개 모델 × 2개 프롬프트` 총 6개 조합 비교
- Validation 결과에 따른 프롬프트 또는 모델 선택
- 새로운 최종 Test 데이터 준비
- 선택된 조합의 최종 Test 실행

현재 프로젝트는 **v2 프롬프트와 신규 Validation은 승인됐지만, v1/v2 비교 실행은 시작하지 않은
단계**다.

## 10. 다음 권장 단계

1. `답변 보류` 사례가 포함되도록 새로운 Validation 공시를 3~5개 추가한다.
2. 새 Validation HTML을 외부 target 모델로 전송하는 별도 승인을 받는다.
3. GPT-OSS, Gemini, Nemotron에 v1과 v2를 각각 실행한다.
4. Python 채점기로 오류, unsafe answer, answerable abstention, strict 통과율과 평균 점수를 비교한다.
5. v2를 채택하거나 v1으로 rollback하고 모델·프롬프트 조합 하나를 선택한다.
6. 지금까지 사용하지 않은 새로운 DART family로 Test를 준비한다.
7. 선택된 조합만 새로운 Test에 한 번 실행한다.

현재 Validation 9문제로 바로 예비실험을 할 수도 있지만, 이 경우 안전한 답변 보류 성능은 판단할
수 없다. 최종 선택 전에 unanswerable 사례를 보강하는 경로를 권장한다.
