# OSSAI-26 Week 4 검증 방식 반영 설계

## 1. 문서 목적

이 문서는 `OSSAI-26-1/docs/week-04-lab.md`의 프롬프트 최적화·검증 방식을 현재
OSSAI-26 DART 공시 질의응답 프로젝트에 적용하기 위한 설계안이다.

목표는 단순히 AI가 새 프롬프트를 생성하게 만드는 것이 아니다. 다음 원칙을 프로젝트의
평가 절차로 만드는 것이 목표다.

```text
실패 사례로 프롬프트 후보 생성
→ 후보 생성에 쓰지 않은 검증 사례로 기존 프롬프트와 비교
→ 검증 결과가 좋아졌을 때만 후보 선택
→ 별도 test와 HTML 변형에서 최종 품질·견고성 확인
→ 결과가 나쁘거나 불완전하면 기존 프롬프트 유지
```

이 문서는 다음 내용을 다룬다.

1. OSSAI-26과 Week 4 실습 방식의 차이
2. 그대로 사용할 부분과 DART 작업에 맞게 바꿀 부분
3. 목표 평가 구조와 구현 변경 범위
4. 평가 데이터와 HTML 변형 데이터 준비 방법
5. 실행 결과, 계보, 완료 상태 관리 방법
6. 단계별 도입 순서와 완료 기준

## 2. 현재 OSSAI-26 검증 구조

현재 OSSAI-26은 사례별로 다음 입력을 사용한다.

```yaml
cases:
  - id: operating-profit
    html_path: local-data/example.html
    question: "2025년 연결 영업이익은 얼마인가?"
    expected: "123,456백만원"
```

실행 흐름은 다음과 같다.

```text
DART HTML + 질문
→ Gemini가 answer + evidence JSON 생성
→ answer와 expected를 정규화 후 정확 비교
→ 모든 evidence.quote가 HTML 화면 텍스트에 존재하는지 확인
→ answer가 evidence 안에 포함되는지 확인
→ results.jsonl + summary.json 저장
```

현재 통과 조건은 다음 세 조건의 AND다.

```text
answer_correct
AND evidence_in_document
AND answer_in_evidence
```

현재 구조의 장점은 채점 결과가 결정론적이고 설명하기 쉽다는 것이다. 그러나 사례에
development/validation/test 역할이 없고, 기존 프롬프트와 후보 프롬프트를 독립된 데이터로
비교하는 절차가 없으며, HTML이 변형됐을 때의 견고성도 평가하지 않는다.

## 3. Week 4 방식과 현재 프로젝트 비교

| 항목 | OSSAI-26 현재 | OSSAI-26-1 Week 4 | OSSAI-26 반영 방향 |
| --- | --- | --- | --- |
| 작업 대상 | DART HTML 질의응답 | OpenCQA 차트 이미지 질의응답 | DART HTML 유지 |
| 답 생성 모델 | Gemini | NIM Gemma | 설정 가능한 target provider로 분리 |
| 프롬프트 제안 모델 | 없음 | Gemini Flash Lite | optimizer provider 신규 도입 |
| 응답 형식 | `answer`, `evidence`, `confidence`, 보류 정보 | 공통 `StructuredAnswer` | 현재 DART 스키마 유지·확장 |
| 채점 | 정답 정확 일치 + 원문 근거 문자열 검사 | 숫자 F1 70% + 토큰 F1 30% | 정확 일치·근거 검사를 기본으로 유지 |
| 데이터 분할 | 없음 | development 18 / validation 6 / test 6 | `family_id` 기반 60/20/20 분할 |
| 후보 생성 | 없음 | GEPA가 development 실패로 생성 | 1단계 수동 후보, 2단계 GEPA 도입 |
| 후보 선택 | 없음 | validation 평균이 높을 때만 선택 | 평균 + 필수 품질 gate로 선택 |
| test 사용 | 없음 | 생성·선택에 사용하지 않음 | 최종 선택 후 한 번만 평가 |
| 견고성 | 없음 | 이미지 보존·파괴 변형 | HTML 보존·근거 제거 변형 |
| 사람 검토 | 기대값 작성만 | 변형 이미지 근거 상태 판정 | 변형 HTML의 근거 상태 판정 |
| 실행 계보 | prompt SHA, 모델, 토큰, 지연 시간 | Git SHA와 입력·산출물 SHA-256 | Git·데이터·프롬프트·채점기 hash 추가 |
| 실행 완결성 | 성공/실패 집계 | complete/partial/not_run과 품질 분리 | 실행 상태와 품질 상태 분리 |

## 4. 그대로 반영할 원칙

### 4.1 개발·검증·테스트 분리

프롬프트를 고칠 때 사용한 사례로 개선 여부를 판단하지 않는다.

```text
development: 실패 분석과 후보 프롬프트 생성
validation: baseline과 candidate 중 하나 선택
test: 선택이 끝난 뒤 최종 품질 확인
```

test 사례는 후보 생성 함수와 선택 함수에 전달하지 않는다. 실행 결과에는 다음 값을 명시한다.

```json
{
  "test_used_for_generation_or_selection": false
}
```

### 4.2 역할 분리

모델과 일반 코드의 책임을 분리한다.

| 역할 | 책임 |
| --- | --- |
| target provider | DART HTML과 질문으로 답·근거 생성 |
| deterministic scorer | 기대 답과 원문을 기준으로 점수·실패 이유 계산 |
| optimizer provider | baseline, 실패 답, 기대값, 점수, 이유를 보고 후보 프롬프트 제안 |
| selector | validation 결과만으로 baseline/candidate 선택 |

optimizer provider는 점수를 결정하지 않는다. selector도 AI가 아니라 Python 코드로 구현한다.

### 4.3 후보 자동 rollback

후보를 생성했다는 이유만으로 선택하지 않는다.

```text
candidate가 baseline과 같음
→ baseline / candidate_identical

candidate가 validation 기준을 충족하며 평균도 개선
→ candidate / validation_improved

나머지
→ baseline / validation_not_improved
```

### 4.4 실행 완결성과 품질 분리

다음 두 상태를 별도로 관리한다.

```text
실행 상태: complete / partial / not_run
품질 상태: pass / fail / inconclusive
```

`complete`는 필요한 호출과 파일이 모두 만들어졌다는 뜻이지, 모델 품질이 좋다는 뜻이 아니다.

### 4.5 중간 결과 보존

실행이 중단돼도 기존 폴더에 이어 쓰거나 삭제하지 않는다. 해당 폴더를 `partial` 근거로
보존하고 새 `run_id`로 재실행한다.

## 5. DART 작업에 맞게 변경할 부분

### 5.1 Week 4의 숫자·토큰 F1을 그대로 사용하지 않는다

DART 질문은 대체로 특정 금액, 비율, 날짜, 단위처럼 정확한 값을 요구한다. 숫자·토큰 F1은
부분적으로 맞는 장문 답에 높은 점수를 줄 수 있고, 정확한 단위나 연결·별도 기준의 오류를
충분히 벌점 처리하지 못할 수 있다.

따라서 다음 두 수준을 함께 사용한다.

#### 필수 통과 gate

기존의 엄격한 조건을 유지한다.

```text
정답 일치
AND 모든 인용이 HTML 화면 텍스트에 존재
AND 답이 인용 안에 존재
AND 기대 문맥 anchor가 인용 안에 존재
```

#### 최적화용 연속 점수

GEPA와 평균 비교를 위해 0~1 점수가 필요하다. 초기 제안은 다음과 같다.

```text
quality_score =
  0.60 × answer_correct
+ 0.15 × evidence_in_document
+ 0.10 × answer_in_evidence
+ 0.15 × expected_context_covered
```

JSON 스키마 오류는 0점으로 처리한다. `expected_context_covered`는 사람이 작성한
`evidence_must_include`의 항목명, 기간, 연결·별도 기준, 단위가 모델 인용에 포함됐는지를
결정론적으로 검사한다.

최종 선택에서는 평균만 보지 않고 다음 gate를 함께 적용한다.

```text
candidate validation 평균 > baseline validation 평균
AND candidate strict pass rate >= baseline strict pass rate
AND candidate의 input_error/generation_error 증가 없음
AND answerable 사례의 abstained 수 증가 없음
```

소수점 오차나 의미 없는 미세 개선을 피하려면 최소 개선 폭도 설정한다.

```yaml
selection:
  min_mean_improvement: 0.01
```

### 5.2 답변 가능 사례와 불가능 사례를 모두 포함한다

현재 예시는 모두 답변 가능한 질문이다. 실제 안전성을 보려면 HTML에 답이 없는 질문도 필요하다.

| 사례 종류 | 기대 행동 |
| --- | --- |
| answerable | 정확한 답과 실제 원문 인용 반환 |
| unanswerable | `답변 보류`, 빈 evidence, 보류 이유 반환 |

`unanswerable`은 질문 자체가 엉뚱한 경우뿐 아니라, 원래는 답변 가능하지만 목표 행·열·섹션을
제거한 HTML 변형도 포함한다.

### 5.3 프롬프트 생성 모델과 답 생성 모델을 논리적으로 분리한다

초기 구현에서는 같은 API 제공자를 사용할 수 있지만 설정과 결과 기록에서는 역할을 분리한다.

```yaml
target_provider:
  kind: gemini
  model: <answer-model>

optimizer_provider:
  kind: gemini
  model: <optimizer-model>
```

두 역할이 같은 모델이어도 각각의 요청 수, 토큰, 비용, 오류, 실제 모델 ID를 별도로 기록한다.
가능하면 후보 생성 모델과 최종 답 생성 모델을 분리해 자기 답에 맞춘 프롬프트를 제안하는 편향을
줄인다.

### 5.4 프롬프트를 파일 하나로 관리한다

현재 실행 프롬프트는 Python 문자열에 있고 `prompts/html-question-answer.md`에도 유사 내용이
있다. 최적화 도입 전에 실행 프롬프트의 단일 원본을 정한다.

권장 구조는 다음과 같다.

```text
prompts/dart-qa-baseline.md
reports/prompt-optimization/<run-id>/candidate-prompt.md
reports/prompt-optimization/<run-id>/selected-prompt.md
```

코드는 baseline 파일을 읽고 `{question}`, `{html}` 같은 허용된 placeholder만 치환한다.

## 6. 목표 평가 아키텍처

```text
cases.v3.jsonl
  ├─ development
  │    └─ baseline 실행 → score/reason → optimizer → candidate
  ├─ validation
  │    ├─ baseline 실행
  │    ├─ candidate 실행
  │    └─ selector가 하나 선택
  └─ test
       └─ selected prompt로 최종 1회 평가

selected prompt
  └─ robustness variants
       ├─ preserved: 같은 핵심 답과 근거 유지
       └─ destroyed: 안전하게 답변 보류
```

### 6.1 후보 선택 의사 코드

```python
if candidate_text == baseline_text:
    selected = "baseline"
    reason = "candidate_identical"
elif candidate_error_count > baseline_error_count:
    selected = "baseline"
    reason = "validation_errors_increased"
elif candidate_abstained_on_answerable > baseline_abstained_on_answerable:
    selected = "baseline"
    reason = "answerable_abstentions_increased"
elif candidate_strict_pass_rate < baseline_strict_pass_rate:
    selected = "baseline"
    reason = "strict_pass_rate_decreased"
elif candidate_mean >= baseline_mean + min_mean_improvement:
    selected = "candidate"
    reason = "validation_improved"
else:
    selected = "baseline"
    reason = "validation_not_improved"
```

### 6.2 결과 파일

```text
reports/prompt-optimization/<run-id>/
├── calls.jsonl
├── development.jsonl
├── candidate-prompt.md
├── validation.jsonl
├── selected-prompt.md
├── test.jsonl
└── summary.json

reports/robustness/<run-id>/
├── calls.jsonl
├── responses.jsonl
├── evaluation.json
├── evaluation-manifest.json
└── summary.json
```

`calls.jsonl`에는 API 키나 전체 HTML을 저장하지 않는다. 요청·실제 모델, 역할, sample ID,
프롬프트 hash, HTML hash, 토큰, 지연 시간, 오류만 기록한다.

## 7. 평가 데이터 스키마

기존 YAML은 작은 예제에는 적합하지만, 분할·출처·문맥 근거·계보를 포함하려면 JSONL 기반의
새 스키마가 적합하다.

### 7.1 권장 사례 형식

```json
{
  "schema_version": 3,
  "id": "2025-acme-operating-profit-consolidated",
  "family_id": "rcp-20260318000123-operating-profit",
  "split": "development",
  "html_path": "local-data/dart-qa/html/20260318000123.html",
  "html_sha256": "64자리 SHA-256",
  "source": {
    "rcp_no": "20260318000123",
    "url": "https://dart.fss.or.kr/...",
    "company": "예시회사",
    "report_type": "사업보고서",
    "filing_date": "2026-03-18"
  },
  "question": "2025년 연결 영업이익은 얼마인가?",
  "question_metadata": {
    "metric": "영업이익",
    "period": "2025",
    "scope": "consolidated",
    "unit": "백만원",
    "answer_type": "scalar"
  },
  "expected": {
    "answer": "123,456백만원",
    "accepted_answers": [],
    "abstained": false,
    "evidence_quotes": [
      "구분 2025년 연결 영업이익 123,456백만원"
    ],
    "evidence_must_include": [
      "2025년",
      "연결 영업이익",
      "123,456백만원"
    ]
  },
  "tags": ["table", "consolidated", "annual", "unit-baegmanwon"]
}
```

답변 보류 기대 사례는 다음과 같이 작성한다.

```json
{
  "expected": {
    "answer": "답변 보류",
    "accepted_answers": [],
    "abstained": true,
    "evidence_quotes": [],
    "evidence_must_include": []
  }
}
```

### 7.2 `family_id`가 필요한 이유

같은 공시에서 만든 질문이나 같은 질문에서 파생한 HTML 변형이 서로 다른 split에 들어가면
데이터 누출이 발생한다.

예를 들어 다음 사례는 모두 같은 family로 묶는다.

```text
원본 공시의 2025년 연결 영업이익 질문
공백만 바꾼 HTML
불필요한 섹션을 추가한 HTML
영업이익 행을 제거한 HTML
같은 표에서 단위만 묻는 유사 질문
```

분할은 개별 case가 아니라 `family_id` 단위로 수행한다. 한 family의 모든 사례와 변형은 반드시
같은 split 또는 별도 robustness 묶음에 있어야 한다.

## 8. 데이터 준비 방법

### 8.1 권장 규모

최소 실습 규모는 Week 4와 같은 30개다.

```text
development 18
validation 6
test 6
```

그러나 validation 6개는 한두 사례의 영향이 너무 크므로 실제 프로젝트 판단용 권장 최소는
다음과 같다.

```text
전체 60~100개 이상
development 60%
validation 20%
test 20%
```

가능하면 split마다 answerable과 unanswerable, 표와 서술문, 연결과 별도, 다양한 단위를 모두
포함한다.

### 8.2 수집 범위 정의

다음 축이 한쪽으로 치우치지 않도록 수집표를 먼저 만든다.

| 축 | 포함할 값 예시 |
| --- | --- |
| 공시 종류 | 사업보고서, 반기보고서, 분기보고서, 주요사항보고서 |
| 답 위치 | 표, 본문 문장, 주석, 복수 표 중 하나 |
| 기간 | 당기, 전기, 분기, 누적, 특정 기준일 |
| 범위 | 연결, 별도, 회사 전체, 사업부문 |
| 값 종류 | 금액, 비율, 날짜, 건수, 텍스트 상태 |
| 단위 | 원, 천원, 백만원, 억원, %, 주, 명 |
| 난이도 | 단일 값, 유사 값 반복, 다중 조건, 답 없음 |
| 방해 요소 | 인접 연도, 연결·별도 동시 등장, 동일 숫자 반복, 관련 없는 큰 표 |
| HTML 특성 | UTF-8/EUC-KR 계열, 큰 파일, 중첩 표, 병합 셀 |

### 8.3 원본 HTML 수집

1. DART 접수번호와 원문 URL을 출처 목록에 기록한다.
2. 수집 도구로 상세 HTML 또는 필요한 섹션을 저장한다.
3. 수집 직후 SHA-256을 계산한다.
4. 원본은 수정하지 않고 immutable source로 보존한다.
5. 모델 입력용 정리본이 필요하면 별도 파일로 만들고 원본과의 관계를 manifest에 기록한다.

권장 디렉터리는 다음과 같다.

```text
local-data/dart-qa/
├── source/                 # 내려받은 원본, 수정 금지
├── html/                   # 평가에 실제 사용하는 HTML
├── cases/
│   ├── authored.jsonl      # 검토 전 전체 사례
│   ├── development.jsonl
│   ├── validation.jsonl
│   └── test.jsonl
├── variants/
└── manifests/
```

실제 DART HTML과 질문을 외부 모델로 전송할 권한이 있는지 확인하고, 민감하거나 비공개인 자료는
포함하지 않는다.

### 8.4 질문과 기대 답 작성

각 사례는 사람이 HTML을 직접 보고 작성한다.

1. 질문의 대상, 기간, 연결·별도 기준, 단위를 먼저 기록한다.
2. 최종 `answer`를 현재 서비스가 요구하는 정확한 표현으로 작성한다.
3. 허용할 표현이 여러 개라면 `accepted_answers`에 명시적으로 추가한다.
4. 답을 확인할 수 있는 연속 원문을 `evidence_quotes`에 복사한다.
5. 기간·항목·범위·단위를 확인할 핵심 문자열을 `evidence_must_include`에 작성한다.
6. 답을 찾을 수 없는 사례는 억지로 정답을 만들지 않고 `abstained=true`로 작성한다.

`accepted_answers`는 편의를 위해 광범위하게 추가하지 않는다. 단위 변환이나 반올림을 허용할
경우에는 사례별 임의 문자열 대신 별도의 명시적 정규화 정책을 먼저 정의한다.

### 8.5 2인 검토

가능하면 작성자와 검토자를 분리한다.

검토자는 다음을 확인한다.

- 질문이 한 가지로 해석되는가
- 기대 답이 정확한 행과 열에서 나왔는가
- 기간과 연결·별도 범위가 맞는가
- 단위가 답에 포함됐는가
- `evidence_quotes`가 실제 화면 텍스트에 연속해서 존재하는가
- answerable/unanswerable 판정이 맞는가
- 같은 family가 여러 split에 섞이지 않았는가

검토 결과에는 `author`, `reviewer`, `reviewed_at`을 manifest에 기록하되 개인 정보가 필요 없다면
팀 별칭만 사용한다.

### 8.6 데이터 분할

다음 순서로 분할한다.

1. 모든 사례에 `family_id`를 부여한다.
2. 공시 종류·범위·답 유형·난이도별 분포를 계산한다.
3. `family_id` 단위로 60/20/20에 가깝게 배정한다.
4. 고정된 `random_seed`를 기록한다.
5. split별 태그 분포와 answerable/unanswerable 비율을 확인한다.
6. test 파일은 후보 생성·선택 코드에서 접근하지 않도록 경로를 분리한다.

초기에는 다음 설정을 사용할 수 있다.

```yaml
dataset:
  random_seed: 42
  split_ratio:
    development: 0.6
    validation: 0.2
    test: 0.2
```

### 8.7 데이터 자동 검사

모델을 호출하기 전에 다음 검사를 모두 통과해야 한다.

- ID 중복 없음
- `family_id`가 둘 이상의 split에 없음
- HTML 파일 존재 및 SHA-256 일치
- 질문이 공백이 아님
- answerable 사례의 기대 답과 근거가 비어 있지 않음
- unanswerable 사례의 기대 근거가 비어 있음
- 모든 `evidence_quotes`가 HTML 화면 텍스트에 존재
- `evidence_must_include`가 기대 인용에 포함
- split별 목표 개수와 최소 태그 분포 충족
- test가 optimizer 입력 목록에 없음

## 9. HTML 견고성 데이터 준비

이미지 회전·압축 대신 HTML 작업에 맞는 변형을 만든다.

### 9.1 근거 보존 변형(`preserved`)

질문의 답과 문맥은 그대로 남아 있어야 한다.

- 공백·줄바꿈 변경
- 불필요한 HTML attribute 제거
- wrapper `div` 추가 또는 제거
- 관련 없는 섹션 추가
- 주석과 script 제거
- 동일한 화면 텍스트를 유지하는 인코딩 재저장
- 관련 없는 표의 순서 변경

기대 행동은 원본과 같은 정답을 반환하고 실제 변형 HTML의 근거를 인용하는 것이다.

### 9.2 근거 파괴 변형(`destroyed`)

답을 확인하는 데 필요한 정보가 실제로 사라져야 한다.

- 목표 값이 있는 셀 제거
- 목표 행 전체 제거
- 연도 헤더 제거
- 연결·별도 구분 헤더 제거
- 단위가 있는 표 제목 제거
- 목표 섹션 전체 제거
- 값을 마스킹 문자열로 교체

기대 행동은 답을 추정하지 않고 `답변 보류`를 반환하는 것이다.

### 9.3 교란 변형

근거는 보존하지만 오답 가능성을 높이는 변형이다.

- 인접 연도 값을 포함한 관련 없는 표 추가
- 같은 항목의 별도 기준 표 추가
- 같은 숫자를 다른 항목에 추가
- HTML 본문에 모델을 향한 가짜 지시문 추가

마지막 항목은 prompt injection 견고성을 확인한다. 공시 본문 안의 문장은 데이터이지 시스템
지시문이 아니므로 모델이 이를 명령으로 따르지 않아야 한다.

### 9.4 사람 판정

변형 이름만으로 상태를 결정하지 않는다. 사람이 실제 변형 HTML을 렌더링하거나 화면 텍스트로
확인한 뒤 다음 중 하나를 기록한다.

```text
preserved: 질문에 필요한 값과 문맥이 남아 있음
destroyed: 질문에 필요한 값 또는 필수 문맥이 사라짐
invalid_variant: 생성 의도와 실제 상태가 다름
```

`invalid_variant`는 모델 실패로 계산하지 않고 평가에서 제외한다.

### 9.5 견고성 판정

#### Preserved

```text
원본 strict pass
AND 변형 strict pass
AND 정규화된 핵심 답 동일
AND 변형 evidence가 변형 HTML에 실제 존재
```

원본이 실패하면 `inconclusive`다. 잘못된 원본 답을 그대로 재현한 것을 견고성 성공으로
계산하지 않는다.

#### Destroyed

```text
abstained=true
AND answer="답변 보류"
AND evidence=[]
AND abstention_reason 존재
```

## 10. 구현 변경 범위

### 10.1 스키마와 설정

- `schemas.py`
  - `split`, `family_id`, `html_sha256`, source metadata 추가
  - `accepted_answers`, `expected_abstained`, 기대 근거·문맥 anchor 추가
  - `ScoreBreakdown`, `SelectionSummary`, robustness 결과 모델 추가
- `config.py`
  - JSONL 사례 loader 추가
  - family 단위 split 누출 검사
  - target/optimizer provider 설정 분리
  - selection 최소 개선 폭 설정

### 10.2 프롬프트와 provider

- `prompts.py`
  - 프롬프트 문자열 하드코딩 제거 또는 파일 loader로 축소
- `providers.py`
  - target/optimizer 역할별 provider 및 사용량 기록
  - recorded 응답도 역할별 fixture로 분리
- `prompts/dart-qa-baseline.md`
  - baseline 단일 원본

### 10.3 채점과 선택

- `evaluation.py`
  - strict pass와 `quality_score`를 함께 계산
  - 실패 이유에 missing/extra context를 기록
  - answerable/unanswerable 분기
- 신규 `prompt_optimization.py`
  - development만 optimizer에 전달
  - validation 비교와 rollback
  - test 미사용 증거 기록

### 10.4 실행 스크립트

```text
scripts/validate_dataset.py
scripts/optimize_dart_qa_prompt.py
scripts/inspect_prompt_results.py
scripts/generate_html_variants.py
scripts/evaluate_html_robustness.py
```

### 10.5 테스트

최소 다음 회귀 테스트가 필요하다.

- development만 optimizer에 전달됨
- validation만 selector에 전달됨
- test가 생성·선택에 사용되지 않음
- 같은 family가 여러 split에 있으면 실패
- 후보 평균이 낮으면 baseline 선택
- 후보 평균이 높아도 strict pass rate가 낮으면 baseline 선택
- 후보가 동일하면 추가 target 호출 없이 baseline 선택
- 원본 실패 시 preserved 변형은 inconclusive
- destroyed 변형에서 일반 답을 하면 실패
- invalid variant는 품질 집계에서 제외
- HTML·프롬프트·채점기 hash 불일치 시 평가 중단
- partial 실행이 complete로 표시되지 않음

## 11. 실행 계보와 manifest

각 전체 실행은 다음 값을 기록한다.

```json
{
  "git_sha": "실행 코드 commit",
  "dataset_sha256": "전체 사례 canonical hash",
  "split_sample_ids": {
    "development": [],
    "validation": [],
    "test": []
  },
  "baseline_prompt_sha256": "...",
  "candidate_prompt_sha256": "...",
  "selected_prompt_sha256": "...",
  "scorer_sha256": "...",
  "test_used_for_generation_or_selection": false,
  "target_provider": {},
  "optimizer_provider": {}
}
```

프롬프트 최적화와 robustness 실행을 연결할 때 다음 항목이 모두 일치해야 한다.

1. `git_sha`
2. `dataset_sha256`
3. optimization의 `selected_prompt_sha256`와 robustness의 `prompt_sha256`
4. 원본·변형 HTML SHA-256
5. scorer schema/version

하나라도 다르면 `complete`가 아니라 `partial` 또는 `inconclusive`로 처리한다.

## 12. 단계별 도입 계획

### Phase 0. 기준 정리

- 실행 프롬프트를 `prompts/dart-qa-baseline.md` 한 곳으로 통합
- DART 수집기 문서 경로를 실제 `.claude/skills/dart-html-fetch` 경로와 맞춤
- 현재 recorded 예제가 계속 통과하는지 확인

### Phase 1. 평가 데이터 v3와 채점기

- 새 사례 스키마 구현
- family 단위 development/validation/test 분할
- strict gate + quality score + 실패 이유 구현
- 모델 호출 없는 dataset validator와 scorer 테스트 완성

### Phase 2. Baseline 대 수동 후보 비교

- GEPA 없이 사람이 작성한 candidate를 사용
- 동일 target provider로 validation 비교
- rollback과 결과 파일 구조 검증
- test가 선택 전에 사용되지 않는지 확인

이 단계에서 비교 구조가 안정된 뒤 자동 optimizer를 도입한다.

### Phase 3. 자동 프롬프트 후보 생성

- optimizer provider 또는 DeepEval GEPA 연결
- 요청·시도·토큰·비용·시간 상한 적용
- development 실패 이유만 optimizer에 전달
- validation gate를 통과한 경우에만 candidate 선택

### Phase 4. HTML 견고성

- preserved/destroyed/교란 변형 생성
- 사람 검토표와 `invalid_variant` 처리
- 선택된 프롬프트로 원본·변형 평가
- robustness manifest와 optimization 계보 연결

### Phase 5. 최종 test와 운영 판단

- 선택 완료 후 test를 한 번 실행
- 태그별 성능과 실패 사례 검토
- 데이터 규모가 충분할 때만 배포 품질을 주장
- 실패가 있으면 새 development 데이터로 다음 최적화 cycle 수행

## 13. 첫 데이터셋 권장 구성

첫 구현은 다음 30개로 시작할 수 있다.

| 구분 | 전체 | answerable | unanswerable |
| --- | ---: | ---: | ---: |
| development | 18 | 14 | 4 |
| validation | 6 | 5 | 1 |
| test | 6 | 5 | 1 |
| 합계 | 30 | 24 | 6 |

answerable 24개에는 최소한 다음 조합을 포함한다.

- 연결/별도 각각 6개 이상
- 연간/분기·반기 각각 6개 이상
- 금액/비율/날짜·건수 각각 4개 이상
- 표/서술문 각각 6개 이상
- 동일 문서 안에 유사 숫자가 반복되는 사례 6개 이상

각 split의 비율이 완전히 같을 필요는 없지만 validation과 test에 특정 유형이 전혀 없는 상태는
피한다.

robustness는 test를 직접 변형해 선택 과정에 다시 사용하지 않는다. 초기에는 별도의 검토 완료
base case 5개를 선정하고, 사례당 다음 변형을 권장한다.

```text
preserved 2개
destroyed 2개
교란 1개
```

총 25개 변형으로 시작한다.

## 14. 완료 기준

다음 조건을 모두 만족하면 Week 4 방식의 1차 반영이 완료된 것으로 본다.

- 사례가 family 단위 development/validation/test로 분리돼 있다.
- test 사례가 후보 생성·선택 코드에 전달되지 않는다.
- baseline과 candidate를 같은 validation 사례·모델·설정으로 비교한다.
- 후보가 명시된 최소 개선 폭과 strict gate를 모두 통과할 때만 선택된다.
- 후보가 나쁘거나 같으면 baseline으로 자동 rollback한다.
- answerable과 unanswerable을 모두 채점한다.
- expected evidence와 문맥 anchor가 실제 HTML에서 자동 검증된다.
- preserved/destroyed HTML 변형을 사람이 확인한다.
- 원본 실패, invalid variant, provider 오류를 실패와 구분한다.
- 실행 상태와 품질 상태를 별도로 기록한다.
- Git, 데이터, HTML, 프롬프트, 채점기 SHA-256 계보가 남는다.
- 실제 API 없이 recorded fixture로 전체 흐름을 재현하는 테스트가 통과한다.

## 15. 이 설계로 주장할 수 있는 범위

이 구조를 구현해도 한 번의 실행만으로 모든 DART 공시에서 성능이 좋아졌다고 주장할 수는 없다.
말할 수 있는 것은 다음 범위다.

```text
고정된 코드·모델·데이터·채점 규칙에서
development 실패를 참고해 만든 후보를
분리된 validation에서 baseline과 비교했고,
정해 둔 선택 기준에 따라 하나를 골랐으며,
별도 test와 검토된 HTML 변형에서 결과를 기록했다.
```

데이터가 작거나 공개돼 있거나 특정 공시 유형에 치우쳐 있다면 그 한계도 `summary.json`과 분석
문서에 함께 남긴다.
