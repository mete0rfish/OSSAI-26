# 다중 모델 평가 후 복잡한 프롬프트를 개발하는 가이드

이 문서는 기존 DART QA 문제를 여러 target 모델로 먼저 시험한 뒤, 기존 schema v3 워크플로 안에서
더 정교한 프롬프트를 개발하고 공정하게 평가하는 절차를 정의한다. 다중 모델 runner의 구현과
공통 안전 규칙은 [multi-model-benchmark-guide.md](multi-model-benchmark-guide.md)를 함께 따른다.

## 1. 목표와 범위

이 실험은 다음 질문에 순서대로 답한다.

1. 현재 고정 프롬프트를 사용할 때 어떤 target 모델들이 유망한가?
2. 현재의 근거 인용 실패를 줄이는 복잡한 프롬프트를 만들 수 있는가?
3. 최종적으로 어떤 `target 모델 × 프롬프트` 조합이 가장 좋은가?

이 문서에서 말하는 복잡한 프롬프트는 지시문이 더 정교해지는 경우다. 기존 계약은 유지한다.

- `{question}`과 `{html}`이 유일한 placeholder이며 각각 정확히 한 번 사용
- target 출력은 기존 `DisclosureAnswer` JSON schema
- 기대 정답, 허용 답, 기대 근거와 채점 결과를 target에 보내지 않음
- 채점과 조합 선택은 결정론적 Python 코드가 담당

출력 schema를 바꾸거나 Python 파싱 코드를 생성·실행하려는 경우에는 이 흐름에 섞지 않는다.
그 작업은 별도 parser synthesis 워크플로와 안전한 코드 실행 환경이 필요하다.

## 2. 가장 중요한 실험 원칙

모델과 프롬프트를 동시에 계속 바꾸면 성능 향상의 원인을 알 수 없다. 다음 순서를 지킨다.

```text
현재 프롬프트 동결
→ 여러 target 모델을 Development에서 예비평가
→ 상위 모델 2~3개만 남김
→ Development 실패로 복잡한 프롬프트 후보 생성
→ 새로운 Validation에서 모델 × 프롬프트 조합을 한 번 비교
→ 최종 조합 선택과 사람 승인
→ 선택된 조합 하나만 새로운 Test에서 평가
```

각 단계가 끝날 때 prompt, dataset, scorer, provider 설정과 Git SHA를 기록한다. 이전 artifact를
덮어쓰거나 기존 output 디렉터리를 재개하지 않는다.

## 3. 현재 데이터와 결과의 지위

현재 기준 데이터셋은 다음과 같다.

- 파일: `local-data/dart-qa/cases/cases.v3.jsonl`
- 사례: 30개, family 10개
- SHA-256:
  `ac94a5abe63b24a398b50b1e9d7e90cba076209c7a92ff8497d4923d0f480992`

현재 Test는 이미 실행됐고 실패 사례까지 사람이 확인했다. 그 실패는 다음 프롬프트의 가설을 만드는
데 사용할 수 있지만, 그 순간부터 해당 사례는 미공개 Test가 아니다.

따라서 다음 규칙을 적용한다.

- 기존 `cases.v3.jsonl`과 기존 보고서는 수정하지 않고 기준 artifact로 보존한다.
- 현재 10개 family는 새 실험에서 Development 또는 exploratory 자료로만 사용한다.
- split을 바꿀 때는 기존 파일을 덮어쓰지 않고 새로운 dataset 파일과 lineage를 만든다.
- 새로운 회사·공시·문서 template의 family로 Validation과 Test를 만든다.
- 같은 family의 세 질문은 항상 같은 split에 둔다.

정식 실험을 위한 최소 권장량은 새로운 Validation 3개 family와 Test 3개 family다. 가능하면 더
많은 회사와 HTML 구조를 포함한다. 데이터 준비는 `$prepare-dart-qa-data`를 사용하고 사람 검토를
완료한 뒤 live 호출을 시작한다.

## 4. 실험 단계

### 단계 0: 기준선 동결

다음 항목을 manifest에 기록한다.

| 항목 | 현재 기준 |
|---|---|
| 현재 프롬프트 | `reports/prompt-optimization/ollama-cloud-nim-20260824-01/selected-prompt.md` |
| 프롬프트 SHA-256 | `9d24e442571204775807875888c401b241fa325450e23585485bd6dd52dc7954` |
| 데이터셋 SHA-256 | `ac94a5abe63b24a398b50b1e9d7e90cba076209c7a92ff8497d4923d0f480992` |
| 기존 target | Ollama Cloud `gpt-oss:120b` |
| 기존 optimizer | NVIDIA NIM `nvidia/nemotron-3-ultra-550b-a55b` |

현재 선택 프롬프트의 hash를 확인한 뒤 사람 승인하에
`prompts/dart-qa-selected-v1.md`로 승격한다. `reports/` 파일을 직접 수정하거나 내용이 다른
프롬프트를 같은 이름으로 저장하지 않는다.

### 단계 1: 다중 모델 예비평가

모든 모델에 `dart-qa-selected-v1.md`를 동일하게 적용한다. 이 단계에서는 optimizer를 호출하지
않고 target 모델만 호출한다.

평가 대상은 사용자가 승인한 Gemini, Ollama, NVIDIA NIM 모델이다. 정확한 모델 ID와 현재 가격,
rate limit은 실행 직전에 공식 문서에서 다시 확인한다.

이 단계의 목적은 최종 승자를 정하는 것이 아니라 다음을 확인하는 것이다.

- JSON schema 호환 여부
- Development 정답 정확도와 엄격 통과율
- 근거 인용 방식의 모델별 차이
- generation error와 불필요한 답변 보류
- latency, token과 예상 비용

현재 공개된 Test를 모든 모델에 실행하면 결과를 `exploratory`로 표시한다. 이를 최종 모델 선택이나
새 프롬프트의 최종 성능 주장에 사용하지 않는다.

예비평가 후 상위 2~3개 모델을 남긴다. 이 선택은 비용을 줄이기 위한 screening이며 최종 모델
선택이 아니다.

### 단계 2: 프롬프트 개선 가설 작성

복잡한 프롬프트를 쓰기 전에 해결하려는 실패 유형과 성공 조건을 한 페이지 이내로 고정한다.
현재 결과에서 확인된 우선순위는 다음과 같다.

1. 모델이 `<TR>`과 `<TD>` 태그를 비슷하게 재작성해 `evidence_not_in_document`가 되는 문제
2. 시설자금 근거에서 상위 항목 `자금조달의 목적`이 빠지는 문제
3. 값이 없을 때 주변의 다른 비율을 답해 `unsafe_answer`가 되는 문제
4. 원문 값에 없는 `원`, `%` 등을 답에 덧붙이는 문제
5. 원문의 `-`를 답변 보류로 잘못 처리하는 문제

프롬프트 v2는 모든 가능한 예외를 나열하기보다 이 실패를 직접 해결하는 최소 지시를 추가한다.
복잡도 증가 자체를 개선으로 간주하지 않는다.

### 단계 3: 복잡한 프롬프트 v2 설계

권장 구조는 다음과 같다.

```text
역할과 보안 경계
→ 질문의 대상·단위·범위 식별
→ 표의 행·열 교차값 확인
→ 답의 원문 표기 보존
→ 여러 개의 짧은 원문 evidence 선택
→ 문맥 anchor 확인
→ answerable/unanswerable 판정
→ JSON schema 하나만 반환
```

근거는 긴 HTML 행을 재구성하지 않고 실제 HTML에 존재하는 짧은 문자열을 여러 개 제출하게 한다.

```json
{
  "answer": "826",
  "evidence": [
    {"quote": "6. 신주 발행가액"},
    {"quote": "보통주식 (원)"},
    {"quote": "826"}
  ],
  "confidence": 1.0,
  "abstained": false,
  "abstention_reason": null
}
```

시설자금 사례에서는 `자금조달의 목적`, `시설자금 (원)`, 실제 값이 evidence 전체에 포함돼야 한다.
각 quote는 모델이 재작성한 텍스트가 아니라 입력 HTML의 실제 연속 문자열이어야 한다.

답변 규칙은 다음처럼 명시한다.

- 답은 질문이 요구한 값만 쓰고 원문에 없는 단위를 추가하지 않는다.
- 원문이 `-`이면 답도 `-`이며 abstention으로 처리하지 않는다.
- 확정값과 예정값이 함께 있으면 질문과 데이터 작성 기준에 맞는 행을 선택한다.
- 해당 항목을 하나로 확정할 수 없을 때만 정확히 `답변 보류`한다.
- 답변 보류 시 evidence는 빈 배열이고 abstention reason을 작성한다.

프롬프트 안에 Validation/Test의 실제 정답이나 공시번호별 예외를 넣지 않는다.

### 단계 4: Development에서 후보 생성

기존 워크플로를 유지하려면 대표 target 모델 하나를 고정하고 NVIDIA NIM optimizer가 해당 모델의
Development strict 실패만 보게 한다.

여러 target 모델의 실패를 한꺼번에 optimizer에 전달하는 기능은 현재 워크플로의 범위를 넘을 수
있다. 이를 원하면 별도 변경으로 구현하고, 모델 ID별 실패가 모두 Development에서 왔는지
검증하는 회귀 테스트를 추가한다.

후보는 다음 경로처럼 버전을 분리한다.

```text
prompts/dart-qa-selected-v1.md
prompts/dart-qa-complex-v2.md
```

두 프롬프트 모두 `{question}`과 `{html}`을 각각 정확히 한 번 포함해야 한다. 후보가 동일하거나
오류·unsafe answer·답변 가능한 문제의 abstention을 늘리면 자동 rollback한다.

### 단계 5: 모델 × 프롬프트 Validation

새로운 Validation에서 상위 모델과 두 프롬프트의 전체 조합을 평가한다.

| target 모델 | v1 현재 프롬프트 | v2 복잡한 프롬프트 |
|---|---:|---:|
| 상위 모델 A | 평가 | 평가 |
| 상위 모델 B | 평가 | 평가 |
| 선택적으로 모델 C | 평가 | 평가 |

모든 조합은 같은 사례, 같은 채점기와 가능한 한 동일한 생성 설정을 사용한다. provider가 지원하지
않는 옵션은 억지로 맞추지 말고 실제 요청 설정을 기록한다.

최종 조합은 Validation에서만 다음 순서로 고른다.

1. strict pass rate가 높은 조합
2. 동률이면 mean quality score가 높은 조합
3. 동률이면 generation error가 적은 조합
4. 동률이면 unsafe answer와 answerable abstention 합계가 적은 조합

복잡한 v2가 선택되려면 최소한 다음 조건을 만족해야 한다.

- strict pass rate가 감소하지 않음
- generation error가 증가하지 않음
- unsafe answer와 answerable abstention이 증가하지 않음
- 설정한 mean quality 개선 기준을 충족함
- 입력 token, latency와 비용 증가가 사람의 승인 범위 안에 있음

Python selector가 `model ID + prompt SHA-256` 조합 하나를 `selection.json`에 기록한다. 모델이나
optimizer가 승자를 선택하면 안 된다.

### 단계 6: 사람 승인

Test 전에 다음 내용을 사람이 검토한다.

- 선택된 requested/actual model ID
- 선택된 prompt 파일과 SHA-256
- dataset, HTML, scorer와 Git SHA-256
- Validation strict pass와 주요 실패 사례
- generation error와 provider quota 상태
- 예상 Test 호출 수, token과 최대 비용
- 새로운 Test family가 후보 생성과 선택에 사용되지 않았는지 여부

승인 전에는 Test를 호출하지 않는다.

### 단계 7: 새로운 Test에서 최종 평가

선택된 `target 모델 + prompt` 조합 하나만 새로운 Test에 실행한다. baseline이나 탈락 모델을 Test에
함께 실행하면 Test를 다시 선택 데이터로 사용하게 될 위험이 있으므로 정식 평가에서는 금지한다.

Test 결과를 본 뒤에는 같은 Test로 다음 작업을 하지 않는다.

- 프롬프트 문구 수정
- 다른 모델 추가 또는 최종 모델 변경
- sampling 설정 변경
- 점수 기준 완화
- 실패 사례별 예외 규칙 추가

실패는 다음 실험 주기의 Development 자료로 넘기고 새로운 Validation/Test를 준비한다.

## 5. 프롬프트 복잡도 관리

복잡한 프롬프트가 길어질수록 비용과 상충 지시가 늘어난다. 다음 항목을 함께 측정한다.

- prompt 문자 수와 token 수
- 사례당 평균 input token 증가량
- 평균과 p95 latency
- 모델별 JSON generation error
- v1 대비 strict pass 절대 개선폭
- 실패 유형별 개선·악화 건수

가능하면 한 버전에서 하나의 주요 가설만 검증한다. 예를 들어 evidence quote 분할과 abstention
정책을 동시에 크게 바꾸면 어떤 변경이 효과가 있었는지 알기 어렵다. 여러 변경을 묶어야 한다면
prompt rationale에 각 변경과 예상 효과를 기록한다.

## 6. 권장 artifact 구조

```text
prompts/
├── dart-qa-baseline.md
├── dart-qa-selected-v1.md
└── dart-qa-complex-v2.md

local-data/dart-qa/cases/
├── cases.v3.jsonl                 # 기존 기준, 수정 금지
└── cases.v3.complex-v2.jsonl      # 새 family와 lineage

reports/model-benchmarks/
├── screening-<run-id>/
├── validation-<run-id>/
└── test-<run-id>/

reports/prompt-optimization/
└── complex-v2-<run-id>/
```

각 run은 새 디렉터리를 사용한다. `calls.jsonl`에는 전체 HTML, 렌더링된 prompt 또는 expected를
기록하지 않고 hash와 제한된 metadata만 기록한다.

## 7. 필요한 도구 변경

고정 프롬프트의 모델별 평가는 `scripts/benchmark_fixed_prompt.py`로 수행한다. 정식 조합 선택에는
[multi-model-benchmark-guide.md](multi-model-benchmark-guide.md)의 matrix orchestration 기능이 추가로
필요하다.

- Development/exploratory screening subcommand
- Validation에서 `모델 × 프롬프트` 전체 조합 실행
- 결정론적 조합 selector와 `selection.json`
- Test에서 선택 조합 하나만 허용하는 lineage 검증
- 조합별 token, 비용, latency와 오류 집계
- 사람용 `comparison.md`와 `comparison.csv`

기존 `optimize_dart_qa_prompt.py`는 대표 모델의 v2 후보 생성에 사용한다. 고정 프롬프트 다중 모델
비교에 이 runner를 반복 사용하면 모델마다 새 candidate가 만들어질 수 있으므로 금지한다.

## 8. 회귀 테스트 체크리스트

구현 또는 변경 시 다음 테스트가 필요하다.

- target request에 expected, accepted answers와 evidence anchors가 없는지 확인
- optimizer request가 Development strict 실패만 포함하는지 확인
- screening에서 Validation/Test 호출이 없는지 확인
- Validation selector가 Test 결과를 읽지 않는지 확인
- Test가 selection의 모델·prompt 조합 하나만 호출하는지 확인
- 모델이나 프롬프트 hash가 바뀌면 Test 실행을 거부하는지 확인
- 동일 family가 여러 split에 있으면 실행 전 실패하는지 확인
- v2가 오류·unsafe answer·answerable abstention을 늘리면 rollback하는지 확인
- strict pass와 answer accuracy를 별도 집계하는지 확인
- prompt별 input token과 비용이 분리 기록되는지 확인
- `calls.jsonl`에 전체 HTML, prompt와 expected가 들어가지 않는지 확인
- existing output 디렉터리를 덮어쓰지 않는지 확인
- partial run과 오류 artifact를 보존하는지 확인
- recorded provider로 전체 선택 흐름을 오프라인 재현할 수 있는지 확인

완료 전 전체 pytest, Ruff, dataset validator와 `git diff --check`를 실행한다.

## 9. 사람 승인 지점

Codex는 다음 단계에서 멈추고 승인을 기다린다.

1. 기존 선택 프롬프트를 `prompts/`로 승격하기 전
2. DART HTML을 각 외부 provider에 보내기 전
3. 정확한 모델 목록, 가격, quota와 비용 상한을 확인한 뒤
4. 다중 모델 screening 결과와 상위 모델 목록을 만든 뒤
5. 복잡한 프롬프트 v2 초안과 변경 이유를 만든 뒤
6. Validation 결과와 최종 조합 selection을 만든 뒤
7. 새로운 Test를 실행하기 전

## 10. Codex 작업 순서

나중에 작업하는 Codex는 다음 순서를 따른다.

1. `AGENTS.md`, `README.md`, `docs/workflow.md`를 읽는다.
2. `docs/multi-model-benchmark-guide.md`와 이 문서를 전부 읽는다.
3. `git status --short`로 사용자 변경을 확인하고 보존한다.
4. 기존 dataset, prompt와 artifact hash를 검증한다.
5. 비교할 target 모델 목록과 비용 상한을 사용자와 확정한다.
6. 고정 프롬프트 benchmark runner가 없으면 recorded provider 테스트부터 구현한다.
7. 현재 프롬프트로 Development screening을 수행하고 상위 모델 후보를 보고한다.
8. 새로운 DART family의 초안과 검토표를 만들고 사람 승인을 기다린다.
9. Development 실패만 이용해 복잡한 프롬프트 v2를 만든다.
10. 사람에게 v2 문구와 가설을 보여 주고 승인받는다.
11. 새로운 Validation에서 모델 × 프롬프트 조합을 평가한다.
12. selection manifest와 비용을 보고하고 Test 승인까지 기다린다.
13. 선택 조합 하나만 새로운 Test에 실행한다.
14. 값 정확도와 엄격 통과를 구분한 한국어 보고서를 작성한다.

## 11. Codex에 전달할 요청 예시

> `docs/multi-model-benchmark-guide.md`와 `docs/complex-prompt-experiment-guide.md`를 먼저 전부
> 읽고 순서대로 작업해줘. 현재 선택 프롬프트를 고정한 상태로 여러 target 모델을 Development에서
> screening하고, 상위 모델을 추린 뒤 Development 실패만 이용해 근거 인용과 답변 보류 규칙을
> 강화한 복잡한 프롬프트 v2를 만들어줘. 새로운 Validation에서 상위 모델 × v1/v2 전체 조합을
> Python으로 비교해 하나의 조합을 선택하고, 사람 승인을 받기 전에는 새로운 Test를 호출하지 마.
> 기존 Test는 exploratory 자료로만 사용하고, target에는 expected를 보내지 마. live 호출 전에는
> 정확한 모델 ID, 가격, 비용 상한과 DART HTML 외부 전송 승인을 요청해줘.

## 12. 완료 정의

다음 조건을 모두 만족해야 실험이 완료된다.

- 현재 프롬프트와 데이터 기준선이 hash로 동결됨
- 여러 모델 screening에서 같은 프롬프트와 사례를 사용함
- 복잡한 프롬프트가 Development 실패만으로 만들어짐
- 새로운 Validation에서 모델 × 프롬프트 조합을 한 번 선택함
- Test는 사람 승인 후 선택 조합 하나에만 실행됨
- target에 expected나 채점 정보가 전달되지 않음
- 정답 정확도, 엄격 통과, 근거, 문맥, 안전 보류, 오류, 비용과 latency가 모두 비교됨
- 기존 v2/v3 artifact와 결과가 보존됨
- 전체 테스트, Ruff와 dataset 검증이 통과함
- 사람이 읽을 수 있는 한국어 결과 보고서가 생성됨
