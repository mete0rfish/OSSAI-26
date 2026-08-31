# 과제 제출용 DART QA 개선·자동화 계획

## 최종 목표

1. baseline 대비 개선 프롬프트의 정량적 향상을 제시한다.
2. 데이터 검증부터 모델 평가·선택·보고서 생성까지 한 명령으로 자동화한다.
3. 선택된 모델·프롬프트를 새로운 Test에 한 번 실행해 최종 성능을 보고한다.

## 비교 모델

| 모델 | 국가 | 역할 |
| --- | --- | --- |
| `deepseek-v4-flash` | 중국 | 1M context 장문 기준 |
| `qwen3.5:397b` | 중국 | 다국어 대형 모델 |
| `gpt-oss:120b` | 미국 | 기존 비교 기준선 |

실행 전 Ollama Pro 계정의 `/api/tags`에서 정확한 모델 ID를 확인하고 고정한다.

## 데이터 준비

- 169개 Development QA의 정답·근거 사람 검토 완료
- 기존 family와 겹치지 않는 Validation 작성: answerable과 unanswerable 포함
- 최종 Test는 별도 신규 family로 작성하고 선택 완료 전까지 비공개 유지
- 공개된 기존 Test 결과는 탐색 자료로만 사용

## 실험 순서

1. **사전 점검:** 세 모델의 인증, JSON 응답과 context 처리를 smoke test
2. **장문 probe:** 기존 12문항과 증권신고서 3건으로 실행 안정성 확인
3. **Validation 비교:** 세 모델 각각 baseline과 공통 v2 프롬프트를 같은 데이터로 평가
4. **자동 선택:** strict pass, 평균 점수, 오류와 unsafe answer 순으로 조합 하나 선택
5. **최종 Test:** 선택 모델·프롬프트 조합만 신규 Test에 한 번 실행
6. **보고서 생성:** 비교표, 개선 사례, 실행 상태와 lineage를 Markdown/JSON으로 출력

## 정량적 결과

Validation에서 선택 모델의 baseline과 v2를 같은 조건으로 비교한다.

- exact answer와 strict pass 건수·비율·증감
- evidence 존재와 필수 문맥 충족률
- unsafe answer와 불필요한 보류 건수
- generation error, latency와 token 사용량
- baseline 실패에서 v2 strict pass로 개선된 대표 사례 2~3개

Candidate는 strict pass가 감소하지 않고, 오류·answerable 보류가 증가하지 않으며,
평균 점수가 최소 `0.01` 향상될 때만 채택한다. Test는 최종 절대 성능으로 별도 보고한다.

## 자동화 결과물

`scripts/run_submission_workflow.py` 한 명령으로 다음을 순서대로 수행한다.

```text
데이터·hash 검증 → Validation 6개 조합 실행 → 자동 선택
→ 선택 조합 Test 실행 → 비교표·최종 요약 생성
```

산출물에는 호출 로그, 모델별 결과, `selection.json`, `comparison.md`, `summary.json`을 포함한다.
Recorded provider 기반 오프라인 E2E 테스트와 Ruff·pytest 통과 결과를 자동화 증빙으로 남긴다.

## 제출물

- `docs/final-report.md`: 문제, 개선 방법, 정량 결과, 대표 사례, 한계
- `README.md`: 한 명령 실행법과 산출물 구조
- `reports/submission/<run-id>/`: 재현 가능한 결과와 lineage
- 자동화 코드·설정·회귀 테스트

실제 DART HTML, API 키와 전체 렌더링 prompt는 제출하거나 호출 로그에 기록하지 않는다.
