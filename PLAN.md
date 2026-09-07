# 과제 제출용 DART QA 개선·자동화 계획

## 계획 원칙

- 기존 169개 Development, Validation 9개와 공개된 기존 Test는 탐색 자료로만 사용한다.
- 최종 평가 데이터는 질문 계약부터 다시 설계하고 새 버전으로 작성한다.
- 질문 계약을 먼저 사람 검토한 뒤 DART 공시와 정답·근거를 수집한다.
- 모델은 Ollama Pro의 세 모델을 그대로 사용하며 다른 provider나 모델로 대체하지 않는다.

## 최종 목표

1. 질문, 정답 범위와 안전 보류 조건이 명확한 DART QA 평가셋을 만든다.
2. baseline 대비 개선 프롬프트의 정량적 향상을 세 Ollama Pro 모델에서 비교한다.
3. 데이터 검증부터 모델 평가·선택·보고서 생성까지 한 명령으로 자동화한다.
4. 선택된 모델·프롬프트를 새로운 Test에 한 번 실행해 최종 성능을 보고한다.

## 비교 모델

| 모델 | 국가 | 역할 |
| --- | --- | --- |
| `deepseek-v4-flash:0731` | 중국 | 1M context 장문 기준 |
| `gemma4:31b` | 미국 | 중형 모델 비교 기준 |
| `glm-5.3-flash` | 중국 | 고속 응답 모델 비교 기준 |

실행 provider는 Ollama Pro로 고정한다. 실행 직전 Ollama Pro 계정의 `/api/tags`에서 세 모델의
정확한 ID와 사용 가능 상태를 확인하고, 확인한 ID를 설정과 lineage에 기록한다.

## 1단계: 질문 계약 재설계

질문을 데이터보다 먼저 확정한다. 증권신고서, 소액공모, 주요사항보고서 등 선택한 공시 유형마다
평가할 질문을 새로 작성하고 다음 항목을 질문 계약에 기록한다.

고유 질문 계약은 총 9개로 제한한다. 증권신고서, 소액공모, 주요사항보고서에 각각 3개를
배정하고, 같은 질문 계약을 서로 다른 split의 신규 공시 family에 적용한다. 행 또는 셀 단위로
분리된 실제 평가 사례는 고유 질문 개수와 별도로 계산한다.

- 고유한 metric ID와 사용자에게 보여 줄 질문 문장
- 적용할 공시 유형과 표·본문 위치
- 답이 가리키는 기간, 재무·회사 범위와 단위
- 답 유형: 금액, 수량, 비율, 날짜 또는 텍스트
- 하나의 정답으로 확정할 수 있는 answerable 조건
- 값·기간·범위·단위를 확정할 수 없을 때의 unanswerable 조건
- strict 정답과 근거를 채점하는 방법

대상자, 목적, 기간 시작·종료처럼 여러 값을 묻는 질문은 행 또는 셀 단위의 원자적 사례로 나눈다.
질문 계약은 DART 데이터 수집과 모델 호출 전에 사람이 검토하고 승인한다.

## 2단계: 필요한 데이터와 필수 항목

평가 사례마다 다음 데이터가 있어야 한다.

- 출처: DART 접수번호, 원문 URL, 회사명, 공시 유형과 공시일
- 입력: 보존된 전체 공시 또는 승인된 섹션 HTML, 프로젝트 상대 경로와 SHA-256
- 격리 정보: 고유 case ID, `family_id`, development/validation/test split
- 질문 정보: 질문 본문, metric, 기간, 범위, 단위와 답 유형
- 정답 정보: 정답, 실제로 같은 표기만 허용한 accepted answers와 abstention 여부
- 근거 정보: 현재 HTML 화면 텍스트에 존재하는 정확한 인용과 필수 문맥 anchor
- 분석 태그: answerable/unanswerable, 공시 유형, table/narrative와 주요 난이도 특성
- 검토 기록: 검토자, 정답·기간·범위·단위·근거 확인 결과와 case hash

unanswerable은 정답을 찾기 어려운 문제가 아니라 현재 HTML만으로 정답의 값·기간·범위·단위를
확정할 수 없는 사례로 한정한다. 기대 출력은 정확히 `답변 보류`로 고정한다.

공개 DART 공시를 사용해도 된다. 다만 같은 공시·질문 계열과 파생 사례는 하나의 `family_id`로
묶고 한 split에만 배치한다. Test는 새로운 family로 만들고, 질문·정답·결과를 모델·프롬프트
선택에 사용하지 않는다.

실제 HTML과 초안은 `local-data/`에만 보관하고 Git, 제출물 또는 호출 로그에 넣지 않는다. 모든
정답과 근거는 모델 답을 사용하지 않고 사람이 원문과 대조해 명시적으로 승인한다.

## 3단계: 데이터 개수와 구성

사용자가 제공한 질문을 그대로 사용하는 최종 평가셋은 총 36개 사례로 고정한다.

| Split | 전체 | Answerable | Unanswerable | 최소 신규 family | 용도 |
| --- | ---: | ---: | ---: | ---: | --- |
| Development | 12 | 7 | 5 | 4 | 질문·프롬프트 개선과 실패 분석 |
| Validation | 12 | 7 | 5 | 4 | 모델·프롬프트 조합 선택 |
| Test | 12 | 8 | 4 | 4 | 선택 완료 후 최종 1회 평가 |

각 split에는 선택한 공시 유형을 모두 포함하고, 금액·수량·비율·날짜·텍스트와
table/narrative 사례가 한 유형에 과도하게 치우치지 않게 배분한다. 정정 공시와 원 공시를 함께
쓸 때에는 실제 최종 상태를 질문 계약에 명시한다.

family 전체를 한 split에 배치하면서 위 개수를 맞춘다. 필요한 구성을 채우지 못하면 family를
쪼개거나 다른 split에서 가져오지 않고 새로운 공시를 추가한다.

## 4단계: 데이터 작성과 사람 검토

1. 승인된 질문 계약에 맞는 DART 접수번호와 전체 공시 또는 섹션을 선정한다.
2. HTML을 새 로컬 경로에 보존하고 case 초안을 작성한다.
3. hash, 경로, ID, evidence와 family split 격리를 기계 검증한다.
4. 모든 사례의 정답, 기간, 범위, 단위와 근거를 사람이 원문과 대조한다.
5. 수정 사항을 반영해 새 prepared/review 파일을 만들고 다시 검토한다.
6. 모든 사례가 명시적으로 승인된 뒤 최종 schema v3 JSONL을 생성한다.

Test도 실행 전에 정답 검토를 완료하되, 선택 로직에서는 Test 질문·정답과 결과를 읽지 못하게
분리한다. 데이터 준비 단계에서는 Ollama 또는 다른 live provider를 호출하지 않는다.

## 5단계: 실험 순서

1. **사전 점검:** Ollama Pro 인증, 정확한 모델 ID, JSON 응답과 context 처리를 smoke test한다.
2. **장문 probe:** Development에서 고른 6문항과 장문 증권신고서 3건으로 실행 안정성을 확인한다.
3. **프롬프트 개선:** Development 실패만 사용해 모든 모델에 공통으로 적용할 v2 프롬프트를 확정한다.
4. **Validation 비교:** 세 모델 각각 baseline과 공통 v2를 동일한 12건으로 평가한다.
5. **자동 선택:** strict pass, 평균 점수, 오류, unsafe answer와 answerable 보류 순으로 하나를 선택한다.
6. **최종 Test:** 선택 모델·프롬프트 조합만 격리된 신규 Test 12건에 한 번 실행한다.
7. **보고서 생성:** 비교표, 개선 사례, 실행 상태와 lineage를 Markdown/JSON으로 출력한다.

## 정량적 결과

Validation에서 각 모델의 baseline과 v2를 같은 조건으로 비교한다.

- exact answer와 strict pass 건수·비율·증감
- evidence 존재와 필수 문맥 충족률
- unsafe answer와 불필요한 보류 건수
- generation error, latency와 token 사용량
- baseline 실패에서 v2 strict pass로 개선된 대표 사례 2~3개

Candidate는 strict pass가 감소하지 않고, 오류·answerable 보류가 증가하지 않으며, 평균 점수가
최소 `0.01` 향상될 때만 채택한다. 조건을 만족하지 않으면 baseline으로 자동 rollback한다.
Test 결과는 선택에 사용하지 않고 최종 절대 성능으로 별도 보고한다.

## 자동화 결과물

사람 검토가 끝난 최종 데이터셋을 입력으로 `scripts/run_submission_workflow.py` 한 명령이 다음을
순서대로 수행한다.

```text
데이터·hash·lineage 검증 → Ollama Pro 사전 점검 → Validation 6개 조합 실행
→ 자동 선택 또는 rollback → 선택 조합 Test 1회 실행 → 비교표·최종 요약 생성
```

산출물에는 호출 로그, 모델별 결과, `selection.json`, `comparison.md`, `summary.json`을 포함한다.
Recorded provider 기반 오프라인 E2E 테스트와 Ruff·pytest 통과 결과를 자동화 증빙으로 남긴다.

## 실행 승인과 안전

- Ollama Pro API key는 로컬 환경 변수로만 설정하고 파일이나 로그에 기록하지 않는다.
- 실제 DART HTML과 질문을 외부 모델에 보내기 전에 별도의 외부 전송 승인을 받는다.
- 전체 렌더링 prompt와 실제 HTML은 `calls.jsonl`에 기록하지 않고 hash와 제한된 메타데이터만 남긴다.
- 기존 데이터, review 파일과 보고서 디렉터리를 덮어쓰지 않고 새 버전 또는 run ID를 사용한다.

## 제출물

- 승인된 질문 계약과 데이터 구성표
- `docs/final-report.md`: 문제, 개선 방법, 정량 결과, 대표 사례와 한계
- `README.md`: 한 명령 실행법과 산출물 구조
- `reports/submission/<run-id>/`: 재현 가능한 결과와 lineage
- 자동화 코드·설정·회귀 테스트

실제 DART HTML, API key, 전체 렌더링 prompt와 비공개 Test 정답은 제출하지 않는다.
