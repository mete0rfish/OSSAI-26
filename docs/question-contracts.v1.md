# 제출용 DART QA 질문 계약 v1 초안

상태: **사람 승인 완료**. 이 계약을 기준으로 신규 DART 공시 family를 배치하고 36건 데이터
초안을 준비한다. 사례별 정답·기간·범위·단위·근거는 별도의 사람 검토를 다시 받아야 한다.

## 공통 계약

- 사례의 질문에는 대상 회사·기간·주식 종류·재무 범위를 필요한 만큼 명시한다.
- 답은 계산·환산하지 않고 질문 대상 셀이나 본문의 원문 표기 하나만 사용한다.
- 복수 값을 묻지 않는다. 시작일과 종료일, 보통주와 우선주 등은 각각 별도 사례로 만든다.
- 값·기간·범위·단위 중 하나라도 현재 HTML에서 확정되지 않으면 unanswerable이다.
- Answerable 근거는 현재 HTML의 연속된 화면 텍스트이며, 값과 식별 문맥 anchor를 포함한다.
- Unanswerable 기대 출력은 정확히 `답변 보류`이고 accepted answer·근거·anchor는 모두 비운다.
- 정정 공시를 쓰면 질문에 정정 후 최종 상태를 명시하고 원 공시와 같은 거래는 한 family로 묶는다.

## 고유 metric 9개

| Metric ID | 공시 유형 | 위치 | 답 유형 | 사용자 질문 계약 |
| --- | --- | --- | --- | --- |
| `registration-offering-total` | 증권신고서 | 모집·매출 조건 표 | 금액 | “정정 후 최종 증권신고서에서 [증권 종류]의 모집 또는 매출 총액은 얼마인가?” |
| `registration-new-shares` | 증권신고서 | 증권의 종류·수량 표 | 수량 | “정정 후 최종 증권신고서에서 새로 모집하는 [증권 종류]의 수량은 몇 주인가?” |
| `registration-subscription-end` | 증권신고서 | 청약 일정 표 | 날짜 | “정정 후 최종 증권신고서에서 [대상자]의 청약 종료일은 언제인가?” |
| `small-offering-total` | 소액공모공시서류 | 모집 조건 표 | 금액 | “정정 후 최종 소액공모공시서류의 모집 총액은 얼마인가?” |
| `small-offering-issue-price` | 소액공모공시서류 | 발행 조건 표 | 금액 | “정정 후 최종 소액공모공시서류에서 [증권 종류] 1주의 발행가액은 얼마인가?” |
| `small-offering-subscription-method` | 소액공모공시서류 | 청약 방법 본문 | 텍스트 | “정정 후 최종 소액공모공시서류에 기재된 [대상자]의 청약 방법은 무엇인가?” |
| `material-fact-discount-rate` | 주요사항보고서 | 발행가액 산정 표 | 비율 | “정정 후 최종 주요사항보고서에서 기준주가에 대한 할인 또는 할증률은 얼마인가?” |
| `material-fact-facility-funds` | 주요사항보고서 | 자금조달 목적 표 | 금액 | “정정 후 최종 주요사항보고서에서 자금조달 목적 중 시설자금은 얼마인가?” |
| `material-fact-payment-date` | 주요사항보고서 | 발행 일정 표 | 날짜 | “정정 후 최종 주요사항보고서의 납입일은 언제인가?” |

## 유형별 판정 규칙

### 증권신고서

- `registration-offering-total`: 증권 종류, 모집/매출 구분, 금액과 표의 단위를 한 조합으로
  확정할 수 있어야 한다. 합계가 없거나 복수 범위가 충돌하면 unanswerable이다.
- `registration-new-shares`: 질문한 증권 종류의 수량 셀을 사용한다. 종류 머리글이나 수량 단위가
  없으면 unanswerable이다.
- `registration-subscription-end`: 질문한 대상자의 종료일 셀만 사용한다. 기간 전체를 한 답으로
  합치지 않으며 시작일만 있거나 대상자 구분이 없으면 unanswerable이다.

### 소액공모공시서류

- `small-offering-total`: 모집 범위의 총액과 표 단위를 함께 확정한다. 납입 총액이나 자금 사용액을
  대신 사용하지 않는다.
- `small-offering-issue-price`: 질문한 증권 종류의 1주당 발행가액만 사용한다. 예정·확정 값이
  함께 있으면 질문에 상태를 명시하고 그 상태의 값이 없으면 unanswerable이다.
- `small-offering-subscription-method`: 질문한 대상자에게 직접 대응하는 연속 원문만 답으로 쓴다.
  여러 방법이 병렬로 기재돼 하나를 고를 수 없으면 사례를 원자화하거나 unanswerable로 둔다.

### 주요사항보고서

- `material-fact-discount-rate`: “기준주가에 대한 할인 또는 할증률” 항목의 직접 대응값만 쓴다.
  발행가액 산정 설명에 있는 다른 비율은 대체 근거가 아니다.
- `material-fact-facility-funds`: “자금조달의 목적” 아래 “시설자금” 직접 대응값과 머리글 단위를
  확인한다. 다른 목적 금액이나 합계를 대신 쓰지 않는다.
- `material-fact-payment-date`: “납입일” 직접 대응값만 쓴다. 이사회결의일·청약일·상장예정일을
  대신 쓰지 않으며 값이 미정이면 unanswerable이다.

## Strict 채점 계약

Answerable은 accepted answer 일치, 모든 인용의 현재 HTML 존재, 답의 인용 포함, 모든 필수 문맥
anchor 충족을 모두 통과해야 strict pass다. Unanswerable은 정확한 안전 보류 계약을 모두 지켜야
통과한다. Unicode 호환 문자와 공백 외에 숫자 구두점·단위·날짜를 정규화하지 않는다.

## 사람 승인 기록

- 검토자: Codex 대화 사용자
- 결정: approved
- 확인 항목: 질문 문장, 기간, 범위, 단위, answerable/unanswerable 경계, strict 근거 규칙
- 승인 일자: 2026-09-03 (Asia/Seoul)
- 승인 근거: 이 Codex 대화에서 사용자가 “질문 계약 v1을 승인합니다”라고 명시적으로 승인
