# 프로젝트 현황 — 2026-08-28

현재 프로젝트는 **개선 프롬프트 v2와 새 Validation 데이터가 승인됐지만, v1/v2 공식 비교는 아직
실행하지 않은 단계**다.

## 핵심 자산

| 자산 | 상태 |
| --- | --- |
| 최초 데이터셋 | 공시 10개, 사례 30개, Development 12 / Validation 9 / Test 9 |
| 데이터셋 SHA-256 | `ac94a5abe63b24a398b50b1e9d7e90cba076209c7a92ff8497d4923d0f480992` |
| 개선 프롬프트 v1 | 생성·평가 완료 |
| v1 SHA-256 | `9d24e442571204775807875888c401b241fa325450e23585485bd6dd52dc7954` |
| 공통 프롬프트 v2 | 사람 승인, target 미실행 |
| v2 SHA-256 | `f73d781479fbde4794be6e1b37e7824b682740b37070ba33f119d24232f4b431` |
| 새 Validation | 신규 family 3개, answerable 9개, 사람 승인 |
| 새 Validation SHA-256 | `71fc1e491700f73dbe8e3337b743bccf31efe247064ba0df03ab31dfd74501a7` |

평가 질문은 할인·할증률, 시설자금, 신주발행가액 세 종류다. 답의 원문 표기와 실제 evidence,
필수 문맥, 안전한 `답변 보류`를 함께 평가한다.

## v1 다중 모델 탐색 결과

같은 30개 사례와 같은 v1 prompt를 적용했다.

| 모델 | 값 정확도 | strict pass | generation error | 평균 지연 |
| --- | ---: | ---: | ---: | ---: |
| `gpt-oss:120b` | 26/30 | 1/30 | 0 | 2.93초 |
| `gemini-3.5-flash-lite` | 22/30 | 9/30 | 0 | 6.52초 |
| `nvidia/nemotron-3-ultra-550b-a55b` | 24/30 | 15/30 | 3 | 41.50초 |

관찰된 공통 실패는 evidence 재작성, 필수 문맥 누락, 원문 부호 변경, 답할 수 없는 할인율에서
주변 숫자를 가져오는 unsafe answer였다. 이 Test와 실패 유형은 이미 공개됐으므로 이후 결과는
탐색 자료이며 새로운 공식 Test 성능으로 주장할 수 없다.

## v2와 새 Validation

v2는 다음 규칙을 강화했다.

- 질문 대상 행·열에 직접 대응하는 값만 선택
- 원문에 없는 단위·공백·설명 추가 금지
- 실제 HTML의 짧은 연속 원문만 evidence로 제출
- `-`를 그대로 보존
- 값을 하나로 확정할 수 없으면 `답변 보류`

새 Validation 9개는 v1/v2 선택을 위해 기존 family와 분리했다. 다만 모두 answerable이므로 안전한
보류 성능은 판단할 수 없다.

## 구현 상태

완료:

- v3 데이터 검증, 프롬프트 최적화와 rollback
- Gemini, Ollama, NVIDIA NIM, recorded provider
- 고정 프롬프트 다중 모델 benchmark runner
- HTML 변형 생성과 robustness 평가
- 오프라인 회귀 테스트와 lineage 기록

남은 작업:

1. 새 Validation에 unanswerable family 보강
2. 외부 전송과 비용 승인
3. 세 모델에 v1/v2 조합 실행
4. Validation으로 모델·prompt 조합 하나 선택
5. 새로운 family로 최종 Test 작성·검토
6. 선택 조합만 Test에 한 번 실행

실행법은 [다중 모델 벤치마크 가이드](multi-model-benchmark-guide.md), 평가 규칙은
[워크플로](workflow.md)를 참고한다.
