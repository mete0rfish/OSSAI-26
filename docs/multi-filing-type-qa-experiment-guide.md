# 다중 공시 유형 DART QA 실험 가이드

작성 기준일: 2026-08-28

## 1. 목적

이 문서는 현재 `주요사항보고서(유상증자결정)`에 한정된 DART QA 실험을 다음 세 공시 유형으로
확장하는 방법을 정의한다.

1. 주요사항보고서(유상증자결정)
2. 증권신고서(지분증권)
3. 소액공모공시서류(지분증권)

목표는 두 가지다.

- 세 유형에 공통으로 존재하는 발행 조건을 문서 구조가 달라도 정확히 추출하는 능력을 평가한다.
- 각 유형에만 존재하거나 더 자세하게 기재되는 정보를 이용해 더 어려운 문제를 평가한다.

기존의 다중 모델 원칙은 유지한다. 같은 데이터와 프롬프트를 모든 target 모델에 적용하고, 기대
정답은 모델에 보내지 않으며, 점수와 선택은 Python이 결정한다.

## 2. 공식 서식과 범위 확인

DART는 공시서류 검색에서 주요사항보고서와 발행공시를 별도 공시군으로 관리하고, 발행공시 안에서
증권신고(지분증권)를 구분한다. 공모게시판은 지분증권 신고서의 증권 종류, 청약일과 접수일을
별도로 제공한다. 정정신고와 발행조건확정 신고도 독립 상태로 표시된다.

실제 문제와 필드 정의는 데이터 수집 시점의 최신 공식 서식을 기준으로 다시 확인한다.

- [DART 기업공시 길라잡이](https://dart.fss.or.kr/info/main.do)
- [DART 공시서류 상세검색](https://dart.fss.or.kr/dsab007/detailSearch.ax)
- [DART 지분증권 공모게시판](https://dart.fss.or.kr/dsac005/search.ax)
- [증권신고서·소액공모공시서류·주요사항보고서 관련 서식 개정 사례](https://dart.fss.or.kr/dsaa003/selectGuideMain.ax?seqno=345)

세 유형이 동일한 발행 거래와 관련될 수는 있지만 항상 세 문서가 한 묶음으로 존재하는 것은 아니다.
증권신고서와 소액공모공시서류를 모든 거래에서 동시에 찾으려고 하지 않는다. 실제 제출 관계를
확인해 존재하는 문서만 transaction family에 연결한다.

## 3. 기존 실험과 분리

현재 완료된 실험은 주요사항보고서 세 질문을 대상으로 한다.

- 기준주가에 대한 할인 또는 할증률
- 자금조달 목적 중 시설자금
- 신주발행가액

현재 승인된 v2 프롬프트는 이 세 질문과 주요사항보고서 구조를 직접 반영한다. 따라서 이를 곧바로
세 공시 유형의 범용 프롬프트라고 간주하면 안 된다.

권장 방식은 다음과 같다.

1. 현재 주요사항보고서 v1/v2 Validation 실험을 기존 experiment ID로 마무리한다.
2. 현재 데이터, 프롬프트와 결과의 SHA-256을 동결한다.
3. 다중 공시 유형 실험은 별도 experiment ID와 새 Development/Validation/Test로 시작한다.
4. 기존 v2는 주요사항보고서 전용 기준선으로만 사용한다.
5. 다중 유형 범용 프롬프트는 새 Development 실패만으로 별도 생성한다.

현재 30문제와 신규 Validation 9문제의 답과 구조는 이미 사람에게 공개됐다. 새 문제 분류나 범용
프롬프트를 설계하는 Development 자료로는 사용할 수 있지만, 다중 유형 실험의 최종 Test로 다시
사용하지 않는다.

## 4. 공시 유형별 역할

| 공시 유형 | 실험에서 보는 역할 | 대표적인 난점 |
|---|---|---|
| 주요사항보고서(유상증자결정) | 이사회가 결정한 발행 조건을 요약한 사건 공시 | 한 표에 핵심 값이 밀집, 정정 전후 값, `-`와 값 부재 구분 |
| 증권신고서(지분증권) | 모집·매출 조건, 인수·청약, 자금 사용과 위험을 상세히 설명하는 발행공시 | 긴 문서, 같은 값의 반복, 예정·확정 상태, 요약표와 세부표 불일치 가능성 |
| 소액공모공시서류(지분증권) | 소액공모의 발행 조건과 자금 사용을 기재하는 발행공시 | 신고서와 비슷한 명칭의 표, 간소화된 구성, 정정·청약 조건 구분 |

문서 유형 이름만으로 특정 목차나 값이 반드시 존재한다고 가정하지 않는다. 실제 HTML에 항목이
없거나 하나의 값을 확정할 수 없으면 해당 사례는 `unanswerable` 후보로 검토한다.

## 5. 문제 난이도 단계

문제는 다음 다섯 단계로 분리한다. 서로 다른 단계를 하나의 점수로만 합치지 않는다.

### L1. 직접 추출

한 표의 명확한 행·열 교차값을 원문 그대로 추출한다.

- 보통주식 발행 수
- 1주당 발행가액
- 납입일
- 시설자금

현재 schema v3와 채점기가 가장 잘 지원하는 유형이다.

### L2. 문맥 선택

같은 문서에 비슷한 값이 여러 개 있을 때 질문의 상태와 범위에 맞는 값을 선택한다.

- 예정발행가와 확정발행가 중 질문 기준에 맞는 값
- 정정 전과 정정 후 값
- 보통주식과 종류주식 중 보통주식 값
- 요약표의 시설자금과 세부 사용계획의 개별 시설 투자 금액 구분

### L3. 문서 내 다중 구간 연결

한 문서의 서로 다른 목차에 있는 문맥을 함께 확인한다.

- 모집 개요의 발행가액과 자금 사용 목적의 총 조달액 연결
- 청약 일정과 납입 일정 구분
- 요약표와 상세표에 동일 값이 기재됐는지 확인

답 자체가 문서에 존재하고 여러 evidence quote로 근거를 만들 수 있으면 schema v3로 처리할 수
있다. 계산 결과나 판정 문장이 문서에 직접 존재하지 않으면 별도 schema가 필요하다.

### L4. 교차 문서 비교

같은 발행 거래에 속한 여러 공시를 함께 비교한다.

- 주요사항보고서와 증권신고서의 신주발행가액이 같은가?
- 정정신고 후 납입일이 이전 신고보다 어떻게 바뀌었는가?
- 주요사항보고서와 소액공모공시서류의 시설자금 금액이 일치하는가?
- 발행조건확정 신고가 예정발행가를 어떤 값으로 확정했는가?

현재 `EvaluationCaseV3`는 한 사례에 `html_path` 하나만 허용하므로 L4를 정식으로 지원하지 않는다.
여러 HTML을 임의로 이어 붙이기보다 다중 source와 source별 evidence를 지원하는 additive schema를
설계한다.

### L5. 계산·검증·파서 생성

문서의 여러 값을 이용해 계산하거나 실행 가능한 파서를 생성한다.

- 발행주식수 × 1주당 발행가액과 총 조달액의 일치 여부
- 자금 사용 목적 세부 금액의 합계 검증
- 기존 주식수와 신주 수를 이용한 희석률 계산
- 세 공시 유형을 처리하는 Python 파싱 코드 생성

현재 채점기는 `expected.answer`가 evidence 안에 존재해야 하므로 계산 결과가 원문에 없는 문제를
그대로 수용하지 못한다. L5는 QA schema와 섞지 않고 계산식·허용 오차·코드 실행 제한을 포함한
별도 워크플로로 만든다.

## 6. 공통 문제 후보

공통 문제는 세 유형에서 명칭이 비슷하다는 이유만으로 만들지 않는다. 먼저 `metric contract`를
정의하고, 각 유형에서 의미와 범위가 실제로 같은지 사람 검토로 확인한다.

| metric ID | 질문 예시 | 반드시 고정할 기준 |
|---|---|---|
| `equity_type` | 발행되는 지분증권의 종류는 무엇인가? | 보통주/종류주식, 모집·매출 범위 |
| `new_share_count` | 이번 발행의 보통주식 수는 얼마인가? | 신주만인지 매출주식 포함인지, 단위 `주` |
| `issue_price_per_share` | 보통주 1주당 발행가액은 얼마인가? | 예정/확정 상태, 값 셀 자체의 단위 표기 |
| `gross_proceeds` | 이번 모집 또는 발행의 총 금액은 얼마인가? | 모집총액인지 순수입금인지, 비용 차감 전후 |
| `facility_funds` | 자금 사용 목적 중 시설자금은 얼마인가? | 요약표 금액인지 세부 내역 합계인지 |
| `operating_funds` | 자금 사용 목적 중 운영자금은 얼마인가? | 동일 표의 직접 대응값 |
| `debt_repayment_funds` | 자금 사용 목적 중 채무상환자금은 얼마인가? | 차환·상환 세부 내역과 요약값 구분 |
| `subscription_period` | 일반청약자의 청약 기간은 언제인가? | 청약 대상 집단, 시작·종료일 원문 표기 |
| `payment_date` | 주금 납입일은 언제인가? | 청약일·환불일·납입기일과 구분 |
| `allocation_method` | 신주는 어떤 방식으로 배정되는가? | 주주배정·일반공모·제3자배정 등 문서 표현 |

### 공통 문제 계약 예시: 신주발행가액

질문을 쓰기 전에 다음을 데이터 계약에 기록한다.

- `metric_id`: `issue_price_per_share`
- 증권 종류: 보통주식
- 상태: 현재 공시에서 유효한 값
- 우선순위: 확정값이 있으면 확정값, 없으면 질문이 예정값을 허용하는지 명시
- 단위: 값 셀의 원문 표기 유지, 머리글 단위를 답에 임의로 추가하지 않음
- 충돌 처리: 정정 전후 또는 여러 표가 충돌하고 우선순위를 확정할 수 없으면 `답변 보류`

같은 질문 문구라도 이 계약이 다르면 같은 metric으로 집계하지 않는다.

## 7. 유형별 문제 후보

### 주요사항보고서(유상증자결정)

- 기준주가에 대한 할인 또는 할증률
- 기준주가 산정방법
- 증자방식
- 증자 전 발행주식총수
- 제3자배정 대상자와 선정 경위
- 이사회결의일
- 신주 상장 예정일
- 현물출자 여부

### 증권신고서(지분증권)

- 모집 또는 매출 주식 수
- 예정·확정 발행가액과 산정 절차
- 모집 또는 매출 총액
- 발행제비용과 예상 순수입금
- 대표주관회사·인수회사와 인수 방법
- 청약 대상별 청약 일정
- 배정 방법 또는 배정 비율
- 자금 사용 목적별 금액과 세부 사용 시기
- 기존 주주에 대한 희석 관련 표의 직접 기재값
- 신고서에 기재된 특정 위험요인의 존재 여부

위험요인 문제는 “가장 중요한 위험은 무엇인가?”처럼 주관적 요약을 요구하지 않는다. 명시된 제목,
특정 조건의 존재 여부 또는 원문 분류를 묻는 객관식·추출형 문제로 한정한다.

### 소액공모공시서류(지분증권)

- 발행 증권의 종류와 수
- 1주당 발행가액과 총 공모금액
- 청약 기간과 납입일
- 청약·배정 방법
- 자금 사용 목적별 금액
- 발행제비용 또는 순수입금
- 소액공모 관련 사유의 원문 표기
- 정정 전후 변경된 발행 조건

특정 금액 기준이나 법률 요건을 질문에 하드코딩할 때는 데이터 수집 시점의 최신 공식 기준과 공시
원문을 함께 검토한다. 모델의 일반 지식만으로 법적 기준을 답하게 하지 않는다.

## 8. 고난도 unanswerable 설계

어려운 문제는 숫자가 없는 문서를 고르는 것만으로 만들지 않는다. 실제로 혼동하기 쉬운 주변 값이
있지만 질문 대상 값은 확정할 수 없는 사례를 포함한다.

권장 유형:

- 예정발행가만 있고 질문이 확정발행가를 요구하는 사례
- 할인율 설명은 있지만 기준주가 표의 할인·할증률 값이 없는 사례
- 시설 투자 세부 항목은 있지만 요약표의 시설자금 총액을 확정할 수 없는 사례
- 보통주와 종류주식 값 중 질문의 증권 종류가 불명확한 사례
- 정정 전후 값은 있으나 현재 유효값을 식별할 정정 문맥이 누락된 section HTML
- 다른 회사나 다른 거래의 첨부 내용만 존재하는 사례

unanswerable은 모델 실패를 유도하기 위해 임의로 만들지 않는다. 현재 제공된 HTML과 질문 계약만으로
답·기간·범위·단위를 하나로 확정할 수 없는 경우에만 사용한다.

권장 비율은 각 공시 유형과 split에서 전체 사례의 25~35%다. 특정 유형에만 unanswerable이 몰리지
않게 한다.

## 9. 긴 증권신고서 처리 방식

증권신고서는 주요사항보고서보다 훨씬 길 수 있다. provider마다 context 한도가 다르므로 평가 입력을
임의로 잘라 모델별로 다르게 보내면 공정한 비교가 깨진다.

세 가지 실험을 별도로 정의한다.

### A. 전체 문서 end-to-end

- 세 모델에 동일한 전체 HTML bytes를 전달한다.
- 가장 작은 공통 context 한도 안에 들어오는 문서만 사용한다.
- 한 모델이 처리하지 못하면 해당 모델의 capacity error로 기록하고 그 모델만 문서를 잘라주지 않는다.

### B. 사람 승인 section bundle

- 전체 HTML은 로컬에 불변 원본으로 보존한다.
- DART 목차에서 질문에 필요한 section을 결정론적으로 추출한다.
- section 이름, offset·length, 원본 HTML SHA와 bundle SHA를 manifest에 기록한다.
- 같은 bundle을 모든 모델에 전달한다.

이 평가는 검색 능력이 아니라 주어진 관련 구간의 추출 능력을 측정한다.

### C. 2단계 retrieval + extraction

- 1단계가 질문에 필요한 section ID를 선택한다.
- 2단계가 선택된 section에서 답과 근거를 추출한다.
- section selection accuracy와 answer strict pass를 따로 계산한다.

전체 문서, oracle section bundle과 model-selected section 결과를 하나의 평균으로 섞지 않는다. 어떤
입력 전략을 평가했는지 artifact에 명시한다.

HTML을 token 한도에서 단순 잘라내는 방식은 금지한다. 잘린 위치 때문에 답이 사라진 사례를 원래
문서의 unanswerable로 채점해서는 안 된다.

## 10. transaction family와 split

기존에는 접수번호 하나를 family로 사용했다. 다중 공시 유형에서는 같은 발행 거래에 여러 접수번호와
정정본이 연결될 수 있으므로 family 단위를 거래로 확장한다.

권장 식별자:

```text
transaction-<issuer-id>-<board-decision-date>-<sequence>
```

별도 transaction manifest를 둔다.

```json
{
  "transaction_id": "transaction-example-20260101-01",
  "issuer": "예시회사",
  "split": "development",
  "filings": [
    {
      "rcp_no": "접수번호",
      "report_type": "주요사항보고서(유상증자결정)",
      "filing_state": "original",
      "supersedes": null
    }
  ]
}
```

실제 manifest에는 회사 식별자, 제출일, 원본·정정·발행조건확정 관계와 HTML SHA를 추가한다.

분할 규칙:

- 같은 거래의 모든 공시 유형, 정정본과 파생 section은 같은 family와 split에 둔다.
- 동일 공시에서 만든 표현 변형과 HTML 변형도 같은 split에 둔다.
- 가능하면 같은 발행회사의 매우 유사한 서식을 Validation/Test에 반복 배치하지 않는다.
- Test family의 공시번호, 정답, 목차 특징을 prompt 생성이나 선택에 사용하지 않는다.

## 11. 권장 데이터 규모와 균형

### 단계 1: 구조 탐색용 pilot

모두 Development로 시작한다.

| 공시 유형 | 원본 family | 정정 family | 권장 합계 |
|---|---:|---:|---:|
| 주요사항보고서 | 2 | 1 | 3 |
| 증권신고서 | 2 | 1 | 3 |
| 소액공모공시서류 | 2 | 1 | 3 |

family마다 공통 문제 3~5개와 유형별 문제 2~3개를 만들면 약 45~72개 사례가 된다. pilot의 목적은
최종 점수가 아니라 taxonomy와 section 전략을 확정하는 것이다.

### 단계 2: 정식 비교 데이터

공시 유형별로 다음 family 수를 권장한다.

| split | 유형별 family | 세 유형 합계 |
|---|---:|---:|
| Development | 4 | 12 |
| Validation | 3 | 9 |
| Test | 3 | 9 |
| 합계 | 10 | 30 |

공통 문제 4개와 유형별 문제 2개를 family마다 적용하면 약 180개 사례다. 비용이 크면 문제 수를
줄이되 각 유형·split·answerability 조합이 비지 않도록 한다.

최소 균형 축:

- 공시 유형
- Development/Validation/Test
- answerable/unanswerable
- 원본/정정/발행조건확정 상태
- 직접 추출/문맥 선택/다중 구간 연결
- 표/narrative/mixed evidence

전체 사례 수가 큰 유형이 평균을 지배하지 않도록 유형별 macro average도 계산한다.

## 12. schema 확장 로드맵

### v3로 가능한 범위

L1, L2와 일부 L3는 현재 schema를 유지할 수 있다.

- `source.report_type`에 정규화된 공시 유형 기록
- `question_metadata.metric`에 canonical metric ID 또는 표시명 기록
- `period`, `scope`, `unit`을 질문별로 명시
- `tags`에 공시 유형, 난이도와 filing state 추가
- 같은 거래의 문서들은 같은 `family_id` 사용

권장 tag 예시:

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
metric:issue-price
answerable
unanswerable
```

현재 validator는 tag별 최소 개수는 확인할 수 있지만 `공시 유형 × split × answerability` 교차 균형은
검증하지 않는다. 정식 데이터셋을 만들기 전에 matrix requirement 검증을 추가한다.

### additive v4가 필요한 범위

L4와 L5를 위해 기존 v3를 변경하지 않고 새 schema를 추가한다.

필요 필드 예시:

```text
sources[]
  source_id
  rcp_no
  report_type
  filing_state
  html_path
  html_sha256

question_metadata
  metric_id
  task_level
  source_scope
  comparison_operator

expected
  answer
  evidence[]
    source_id
    quote
  derivation
  tolerance
```

추가 검증:

- 모든 evidence가 지정한 source HTML에 실제로 존재하는지 확인
- transaction manifest와 source 목록이 일치하는지 확인
- 정정 관계가 순환하지 않는지 확인
- 계산 문제의 입력값, 식과 허용 오차를 결정론적으로 검증
- v3 결과와 scorer가 영향을 받지 않는지 회귀 테스트

## 13. 프롬프트 전략

처음부터 세 유형별 프롬프트를 따로 최적화하면 모델 능력, 공시 유형과 프롬프트 차이가 섞인다.

권장 순서:

1. 범용 baseline 하나를 모든 공시 유형과 모델에 적용한다.
2. 유형별·metric별 실패를 Development에서 분석한다.
3. 공통 core와 유형별 addendum을 가진 routed prompt 후보를 만든다.
4. 같은 모델 안에서 `범용 prompt vs routed prompt`를 Validation으로 비교한다.
5. 모든 target 모델에 동일한 prompt 전략과 SHA를 적용한다.

범용 prompt의 권장 구조:

```text
역할과 HTML 보안 경계
→ 공시 유형과 filing state 식별
→ 질문의 canonical metric·상태·범위·단위 식별
→ 유형별 목차 후보 탐색
→ 정정/예정/확정 우선순위 적용
→ 원문 값 보존
→ source 안의 실제 연속 evidence 인용
→ answerable/unanswerable 판정
→ JSON 객체 하나 반환
```

유형별 addendum에는 목차 후보와 동의어만 넣는다. Development의 공시번호, 실제 정답과 회사별
예외를 넣지 않는다. 모델별 addendum도 만들지 않는다.

## 14. 다중 모델 실험 행렬

현재 후보 모델을 유지한다면 정식 Validation 행렬은 다음과 같다.

| target 모델 | 범용 baseline | 공통 core + 유형 addendum |
|---|---:|---:|
| `gpt-oss:120b` | 실행 | 실행 |
| `gemini-3.5-flash-lite` | 실행 | 실행 |
| `nvidia/nemotron-3-ultra-550b-a55b` | 실행 | 실행 |

모든 조합은 다음을 고정한다.

- 동일한 승인 데이터셋
- 동일한 input strategy: full, section bundle 또는 retrieval 중 하나
- 동일한 scorer
- expected 미전송
- optimizer 미호출
- 모델별 candidate 미생성
- 조합별 새 output 디렉터리
- prompt, dataset, HTML, scorer, model과 Git SHA 기록

Qwen처럼 접근 권한이 없는 모델은 smoke 차단을 보존하고 전체 평가에 포함하지 않는다.

## 15. 채점과 선택

전체 micro average만으로 조합을 선택하지 않는다. 다음 지표를 함께 계산한다.

### 전체 지표

- exact answer match
- strict pass
- evidence in document
- required context coverage
- unsafe answer
- answerable abstention
- generation/capacity error
- latency, token과 비용

### 층화 지표

- 공시 유형별 strict pass
- 공통 metric별 strict pass
- 유형별 unanswerable safe-abstention
- 난이도 L1/L2/L3별 strict pass
- 원본/정정/발행조건확정별 strict pass
- full document/section/retrieval별 결과

### 선택 gate

후보 prompt는 최소한 다음을 만족해야 한다.

- 전체 strict pass가 감소하지 않음
- 어느 공시 유형에서도 generation error와 unsafe answer가 증가하지 않음
- answerable abstention이 증가하지 않음
- 공시 유형별 strict pass가 설정한 허용 하락폭을 넘지 않음
- 유형별 macro average와 worst-type strict pass가 개선됨
- 비용과 latency 증가가 승인된 상한 이내임

Validation에서 `model ID + prompt SHA + input strategy` 조합 하나를 선택한다. 선택된 조합만 새로운
Test에 실행한다.

## 16. 파서 코드 생성 실험으로 확장

값 답변과 파서 코드 생성을 같은 prompt와 점수로 평가하지 않는다. 별도 parser synthesis artifact를
정의한다.

권장 계약:

- 입력: 로컬 HTML path 또는 HTML string
- 출력: canonical metric JSON
- 네트워크 사용 금지
- 허용 라이브러리 고정
- 파일시스템 쓰기 금지 또는 임시 디렉터리만 허용
- 실행 timeout, memory와 output 크기 제한
- Development fixture만 코드 생성 과정에 제공
- Validation 테스트로 코드 후보 선택
- 선택한 코드 하나만 새로운 Test fixture에 실행

평가 지표:

- 공시 유형별 필드 정확도
- 원문 값 보존
- unanswerable 처리
- 정정·예정·확정 우선순위
- 예외·timeout·보안 위반
- 유형별 parser branch의 과적합 여부

QA 실험에서 확정한 `metric contract`와 사람 검토 정답을 parser 테스트 oracle로 재사용하되, Test
정답은 코드 생성 모델에 보내지 않는다.

## 17. 권장 artifact 구조

```text
local-data/dart-qa-multitype/
├── html/
│   ├── major-equity-issuance/
│   ├── registration-equity/
│   └── small-offering-equity/
├── section-bundles/
├── manifests/
│   └── transactions.v1.jsonl
├── drafts/
├── reviews/
└── cases/

prompts/
├── dart-qa-multitype-baseline.md
└── dart-qa-multitype-routed-v1.md

reports/multitype-benchmarks/
├── development-<run-id>/
├── validation-<run-id>/
└── test-<run-id>/
```

실제 DART HTML과 검토 데이터는 `local-data/` 아래에 두고 Git에 추가하지 않는다. 각 run과 prepared,
review, final 파일은 새 run ID를 사용하며 기존 파일을 덮어쓰지 않는다.

## 18. 단계별 실행 계획

### 단계 0. 현재 실험 마감

- 주요사항보고서 v1/v2 Validation을 완료한다.
- 선택 또는 rollback 결과와 SHA를 기록한다.
- 현재 실험의 Test 여부를 별도로 결정한다.

### 단계 1. taxonomy pilot

- 세 유형에서 Development family를 각 3개 수집한다.
- 전체 HTML과 section 목록을 보존한다.
- 공통 metric contract와 유형별 문제를 작성한다.
- 사람 검토 후 taxonomy를 승인한다.

### 단계 2. 입력 전략 결정

- 전체 HTML 크기와 target별 context 한도를 측정한다.
- full document 또는 승인 section bundle 중 공통 전략을 선택한다.
- retrieval 실험은 별도 track으로 분리한다.

### 단계 3. 범용 baseline screening

- 같은 범용 prompt를 모든 모델의 Development에 적용한다.
- 유형별·난이도별 실패를 정리한다.
- 상위 모델 2~3개를 비용 screening 목적으로 남긴다.

### 단계 4. routed prompt 후보

- Development 실패만 사용한다.
- 공통 core와 유형 addendum 후보를 만든다.
- 사람에게 문구, 길이, 예상 비용과 누출 검사를 제시하고 승인받는다.

### 단계 5. 새로운 Validation

- 세 유형의 새 transaction family를 사용한다.
- `모델 × 범용/routed prompt` 전체 조합을 한 번 실행한다.
- Python selector가 조합 하나를 선택하거나 baseline으로 rollback한다.

### 단계 6. 새로운 Test

- 선택 결과와 비용을 사람이 승인한다.
- 선택한 `model + prompt + input strategy` 하나만 실행한다.
- Test 결과는 다음 실험 주기의 Development 자료로만 넘긴다.

### 단계 7. 교차 문서와 파서 생성

- report-local QA 결과가 안정된 뒤 additive v4를 구현한다.
- L4 교차 문서 비교를 먼저 검증한다.
- 그 후 L5 계산과 parser synthesis를 별도 sandbox에서 실행한다.

## 19. 사람 승인 지점

다음 단계에서는 반드시 멈추고 사람 승인을 받는다.

1. 세 유형의 공시 URL과 transaction 연결을 확정한 뒤
2. 공통 metric contract와 유형별 질문 목록을 만든 뒤
3. 각 case의 답·기간·범위·단위·근거를 materialize한 뒤
4. section bundle을 외부 모델 입력으로 사용하기 전
5. DART HTML을 각 provider로 전송하기 전
6. routed prompt 후보와 SHA를 만든 뒤
7. Validation selection을 만든 뒤
8. 새로운 Test를 실행하기 전
9. 생성된 parser 코드를 sandbox에서 실행하기 전

## 20. 구현 전 회귀 테스트 체크리스트

- 같은 transaction의 여러 공시와 정정본이 다른 split으로 새지 않는지 확인
- 공시 유형, split과 answerability 교차 최소 개수를 확인
- source report type과 tag가 일치하는지 확인
- section bundle의 parent HTML SHA와 section manifest를 검증
- model별로 다른 HTML truncation을 적용하지 않는지 확인
- target request에 expected, accepted answer와 evidence anchor가 없는지 확인
- 공통 metric의 상태·범위·단위 계약이 유형별로 동일한지 확인
- 교차 문서 evidence가 올바른 source에 존재하는지 확인
- 계산 문제의 식과 허용 오차가 결정론적인지 확인
- Validation selector가 Test artifact를 읽지 않는지 확인
- 선택되지 않은 모델·prompt가 Test에 호출되지 않는지 확인
- parser 실행에서 network, 임의 파일 쓰기와 무제한 실행을 차단하는지 확인
- 기존 schema v3 데이터와 scorer 회귀 테스트가 그대로 통과하는지 확인

## 21. 첫 실행을 위한 권장 요청 형식

다음 단계에서는 우선 taxonomy pilot용 URL만 제공한다.

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
- 같은 발행 거래에 속한 URL이 있으면 묶어서 표시
- 정정 또는 발행조건확정 관계가 있으면 원본 URL과 함께 표시
```

이 단계에서는 모델을 호출하지 않는다. 전체 HTML을 수집하고 transaction manifest, 공통 metric
contract, 문제 초안과 사람 검토표를 만든 뒤 승인을 기다린다.

## 22. 완료 정의

다음 조건을 모두 만족해야 다중 공시 유형 실험이 완료된다.

- 세 공시 유형의 최신 서식과 transaction 관계가 기록됨
- 공통 metric과 유형별 metric 계약이 사람에게 승인됨
- 각 유형·split·answerability가 균형 있게 구성됨
- 전체 HTML 또는 section bundle 전략이 모델 전체에 동일하게 적용됨
- 같은 transaction과 정정 체인이 하나의 split에 격리됨
- 범용 prompt와 routed prompt가 새 Validation에서 비교됨
- Python selector가 모델·prompt·input strategy 조합 하나를 선택함
- Test는 사람 승인 후 선택된 조합 하나에만 실행됨
- target에 expected와 채점 정보가 전달되지 않음
- 유형별 exact, strict, evidence, context, abstention, error, latency와 비용이 보고됨
- 교차 문서와 parser synthesis는 additive schema·sandbox로 분리됨
- 기존 schema v3 결과와 데이터가 변경되지 않음
