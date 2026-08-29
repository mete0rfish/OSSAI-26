# 다중 공시 유형 QA 실험 가이드

기존 유상증자결정 중심 평가를 **서로 다른 DART 문서 구조로 확장하는 데이터·실험 설계**다.

## 범위

1. 주요사항보고서(유상증자결정)
2. 증권신고서(지분증권)
3. 소액공모공시서류(지분증권)

목표는 공통 발행 조건의 구조 변화 대응력과, 유형별 정보의 정확한 추출 능력을 함께 평가하는
것이다. 실제 필드와 서식은 수집 시점의 DART 원문에서 다시 확인한다.

- [DART 기업공시 길라잡이](https://dart.fss.or.kr/info/main.do)
- [DART 공시서류 상세검색](https://dart.fss.or.kr/dsab007/detailSearch.ax)
- [DART 지분증권 공모게시판](https://dart.fss.or.kr/dsac005/search.ax)

## 질문 설계

| 범주 | 질문 예시 |
| --- | --- |
| 공통 | 신주발행가액, 발행 주식 수, 자금조달 목적, 청약·납입 일정 |
| 유상증자결정 | 할인·할증률, 증자 방식, 배정 기준 |
| 증권신고서 | 모집가액, 인수 방식, 희석·위험 정보 |
| 소액공모 | 모집 총액, 청약 방법, 소액공모 한도 관련 정보 |

질문은 난이도를 명시한다.

| 단계 | 범위 | 현재 schema v3 |
| --- | --- | --- |
| L1 | 한 표의 직접 값 추출 | 가능 |
| L2 | 기간·단위·연결/별도 등 문맥 선택 | 가능 |
| L3 | 한 문서의 여러 구간 연결 | 제한적으로 가능 |
| L4 | 관련 공시 간 비교 | 별도 schema 필요 |
| L5 | 계산·검증·파서 생성 | 별도 안전 워크플로 필요 |

첫 실험은 L1~L2에 집중한다. L4~L5를 v3 사례에 억지로 넣지 않는다.

## 데이터 단위와 split

한 사례에는 다음 정보가 필요하다.

- `filing_type`, 공시 접수번호와 원문 URL
- 질문의 metric·period·scope·unit·answer type
- HTML 경로와 SHA-256
- 사람이 검토한 기대 답·허용 답·근거·필수 문맥
- answerable/unanswerable과 난이도 tag

동일 거래의 원문, 정정공시, 발행조건확정, 파생 질문은 하나의 transaction `family_id`로 묶고
모두 같은 split에 둔다. 문서가 달라도 같은 거래가 Development와 Validation/Test에 나뉘면
누출이다.

권장 순서는 다음과 같다.

1. 유형별 2~3개 문서로 Development pilot 작성
2. HTML 구조와 질문 계약 확인
3. 작성자와 다른 사람이 답·기간·범위·단위·근거 검토
4. 새로운 family로 Validation과 Test 구성
5. 유형·질문·answerability별 최소 개수 검사

## 긴 문서 처리

증권신고서처럼 긴 문서는 세 전략을 구분해 실험한다.

| 전략 | 장점 | 주의점 |
| --- | --- | --- |
| 전체 HTML | 실제 end-to-end 성능 측정 | token·비용 증가 |
| 사람 승인 section bundle | 저렴하고 재현하기 쉬움 | retrieval 성능은 측정하지 않음 |
| retrieval → extraction | 운영 구조에 가까움 | retrieval 정답과 lineage schema가 추가로 필요 |

초기 pilot은 전체 HTML 또는 사람 승인 bundle 중 하나를 선택하고 결과에 전략을 기록한다. 서로
다른 전략의 점수를 같은 조건처럼 직접 비교하지 않는다.

## 실험 흐름

```text
질문 taxonomy 승인
→ 유형별 Development pilot 수집·검토
→ 공통 baseline으로 여러 모델 screening
→ Development 실패로 prompt 개선
→ 새로운 Validation에서 모델 × prompt 선택
→ 사람 승인
→ 새로운 Test에서 선택 조합만 평가
```

전체 평균 외에 `filing_type`, 질문 종류, 난이도, answerability별 지표를 함께 본다. 특정 유형의
unsafe answer나 generation error가 늘면 전체 평균이 좋아도 선택하지 않는다.

## Schema 확장 기준

다음 요구가 생기기 전까지 v3를 유지한다.

- 여러 HTML을 한 사례의 입력으로 사용
- retrieval 결과와 extraction 결과를 분리 채점
- 문서 간 계산 과정과 중간 근거를 저장
- 생성된 파서 코드를 격리 환경에서 실행·평가

필요할 때 v3를 변경하지 말고 additive schema v4와 별도 artifact를 설계한다.

## 승인과 완료 조건

Live 호출 전에 사람이 다음을 승인한다.

- 공시 URL과 외부 전송 범위
- 질문·정답·근거 검토 결과
- split과 transaction family 격리
- 모델 목록, 호출 수와 비용 상한
- Validation 선택 결과와 Test 실행

실험 완료 시 유형별 데이터 수, strict pass, unsafe answer, 오류, 비용과 lineage를 보고한다. 데이터
준비는 [`$prepare-dart-qa-data`](../.agents/skills/prepare-dart-qa-data/SKILL.md), 공통 실행 규칙은
[워크플로](workflow.md)를 따른다.
