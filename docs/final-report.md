# DART QA 개선·자동화 최종 보고서

## 현재 상태

질문 계약 v1과 DART QA 36건은 윤성원 검토자가 승인했다. 2026-09-05 Ollama Cloud에서 세 모델의
Validation 6조합과 선택 후 Test를 실행했다. 실행은 `complete`지만 최종 품질은 `fail`이다. 공식
산출물은 `reports/submission/ollama-pro-submission-v3-20260905-03/`에 보존한다.

## 문제와 개선 방법

기존 탐색 실험에서는 값이 맞아도 evidence를 재작성하거나 기간·단위 문맥을 빠뜨리는 문제가
있었고, 답이 없는 항목에서 주변 숫자를 선택하는 unsafe answer도 관찰됐다. 공통 v2 prompt는
행·열 직접 대응, 원문 표기 보존, 연속 원문 인용, 안전 보류를 강화한다.

제출 워크플로는 다음을 결정론적으로 수행한다.

1. 36건 수, answerable 비율, family 격리, 9개 metric과 split별 tag를 검증한다.
2. Ollama Pro `/api/tags`의 정확한 model ID와 세 모델의 구조화 응답을 사전 점검한다.
3. 동일한 Validation 12건에서 세 모델 × baseline/v2 여섯 조합을 실행한다.
4. 모델별 candidate rollback gate를 적용한 뒤 strict pass, 평균 점수, 오류, unsafe answer,
   answerable 보류 순으로 한 조합을 선택한다.
5. 선택 파일을 저장한 후에만 선택 조합으로 Test 12건을 한 번 실행한다.
6. `selection.json`, `comparison.md`, `summary.json`과 hash lineage를 생성한다.

## 정량 결과

| 모델 | 프롬프트 | Validation strict | 평균 점수 | 오류 | unsafe |
| --- | --- | ---: | ---: | ---: | ---: |
| `deepseek-v4-flash:0731` | baseline | 3/12 | 0.4792 | 1 | 2 |
| `deepseek-v4-flash:0731` | candidate | 1/12 | 0.1667 | 3 | 4 |
| `gemma4:31b` | baseline | 1/12 | 0.1917 | 2 | 5 |
| `gemma4:31b` | candidate | 0/12 | 0.2750 | 3 | 3 |
| `glm-5.3-flash` | baseline | 3/12 | 0.3375 | 0 | 5 |
| `glm-5.3-flash` | candidate | 3/12 | 0.3625 | 2 | 4 |

모든 candidate가 rollback 조건에 걸려 `deepseek-v4-flash:0731 + baseline`을 선택했다. 격리된
Test 결과는 strict pass `4/12`, 평균 점수 `0.5000`, 오류 4건, unsafe answer 1건이다. Test는
조합 생성이나 선택에 사용하지 않았다.

Gemma의 단일 바깥쪽 JSON 코드 블록을 엄격하게 제거하도록 수정한 뒤 Validation 생성 오류는
baseline `12→2`, candidate `12→3`으로 줄었다. 남은 오류는 코드 블록 문제가 아니라 모델이
만든 JSON 자체의 문법 오류이며 자동 보정하지 않았다.

## 후속 v3 Development 결과

공식 실행 뒤 Validation/Test 결과를 사용하지 않고 Development 12건만으로 v3 후보를 작성했다.
DeepSeek는 strict `3→7`, 평균 `0.4333→0.7792`, GLM은 strict `4→8`, 평균
`0.4583→0.8042`로 개선되어 두 모델에서 Development gate를 통과했다. Gemma도 strict
`2→6`으로 늘었지만 오류가 `3→4`로 증가해 rollback 조건에 걸렸다. 이 Development 단계에서는
아직 Validation을 실행하지 않았다.

## 후속 v3 Validation 결과

Development gate를 통과한 DeepSeek와 GLM의 baseline/v3, 그리고 Gemma baseline을 Validation
12건에서 비교했다. v3는 DeepSeek strict `0→7`, GLM strict `2→8`, unsafe answer는 두 모델
모두 `5→0`으로 개선했다. 하지만 빈 Ollama 응답 때문에 오류가 각각 `1→2`, `0→2`로 증가해
두 candidate 모두 rollback됐다. 따라서 Validation 선택은 `glm-5.3-flash + baseline`이며 Test는
실행하지 않았다.

## 재현성과 안전

Live 시작 전에 36건 모두의 review case hash, reviewer, 승인 결정과 다섯 확인 항목을 재검증한다.
전체 HTML, 렌더링 prompt, 기대 답은 `calls.jsonl`에 기록하지 않는다. Test 결과 JSONL도 기대
정답을 제거한다. Live 실행은 API key를 환경변수에서만 읽고 명시적 외부 전송 승인 플래그가
없으면 시작하지 않는다. 기존 출력 디렉터리는 덮어쓰지 않는다.

## 한계와 다음 검토점

- 36건 데이터는 승인됐지만 strict pass가 낮아 품질 기준은 통과하지 못했다.
- candidate 프롬프트는 세 모델 모두 rollback됐으므로 다음 개선에는 Development 실패만 사용한다.
- 긴 증권신고서의 전체 HTML과 승인 section bundle은 서로 다른 조건이므로 혼합 비교하지 않는다.
- 모델·prompt 선택 후 같은 Test로 재튜닝하면 공식 Test의 격리가 깨진다.
