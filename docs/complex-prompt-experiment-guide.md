# 복잡한 프롬프트 실험 가이드

다중 모델 탐색 뒤 프롬프트를 개선하고, **모델 변화와 프롬프트 변화의 효과를 분리해 검증하는
절차**다.

## 실험 순서

```text
현재 prompt 동결
→ 같은 prompt로 여러 모델 Development screening
→ 상위 모델 2~3개 선정
→ Development 실패만으로 candidate 작성
→ 새로운 Validation에서 모델 × prompt 비교
→ Python selector와 사람 승인
→ 선택 조합 하나만 새로운 Test 실행
```

이미 결과와 실패가 공개된 Test는 다음 candidate의 Development 또는 exploratory 자료로만 쓴다.
공식 성능을 주장하려면 새로운 family의 Validation과 Test가 필요하다.

## Candidate 계약

프롬프트가 복잡해져도 다음 계약은 바꾸지 않는다.

- `{question}`과 `{html}`만 각각 정확히 한 번 사용
- 출력은 기존 `DisclosureAnswer` JSON schema
- 기대 답, 기대 근거, Validation/Test 사례를 prompt에 포함하지 않음
- 답은 원문의 구두점·부호·단위를 보존
- Evidence는 재작성하지 않고 HTML에 존재하는 짧은 연속 원문 사용
- 값을 하나로 확정할 수 없을 때만 정확히 `답변 보류`

출력 schema 변경, 교차 문서 추론, Python 파서 생성은 이 실험에 섞지 않는다.

## 개선 가설 작성

한 버전은 가능한 한 하나의 실패군을 해결한다. 현재 우선순위 예시는 다음과 같다.

- 실제 HTML에 없는 형태로 evidence를 재구성
- 항목·기간·단위 같은 필수 문맥 누락
- 값이 없을 때 주변 숫자를 가져오는 unsafe answer
- 원문에 없는 `%`, `원`, 공백 추가
- 원문의 `-`를 보류로 오해

Candidate와 함께 “어떤 실패를 어떤 지시로 줄일지”를 짧게 기록한다. 길이 자체는 개선이 아니다.

## Validation 선택

상위 모델과 baseline/candidate의 전체 조합을 같은 Validation에서 평가한다.

| 조합 | Baseline | Candidate |
| --- | ---: | ---: |
| 모델 A | 평가 | 평가 |
| 모델 B | 평가 | 평가 |

Candidate 조합은 다음 gate를 모두 통과해야 한다.

- strict pass rate 감소 없음
- generation error 증가 없음
- unsafe answer와 answerable abstention 증가 없음
- 설정한 mean quality 개선 폭 충족
- token, latency, 비용 증가가 승인 범위 이내

동률이면 strict pass → mean score → 오류 → unsafe/abstention 순으로 비교한다. 최종
`model ID + prompt SHA-256` 조합은 Python이 선택하고 사람이 승인한다.

## Test 전 승인

다음 항목을 확인하기 전에는 Test를 실행하지 않는다.

- requested/actual model ID와 provider 설정
- prompt, dataset, HTML, scorer, Git hash
- Validation 점수와 주요 실패
- 예상 호출 수, token, 비용 상한
- Test family가 생성·선택에 사용되지 않았다는 증거

Test에는 선택된 조합 하나만 한 번 실행한다. 결과를 본 뒤 같은 Test에서 prompt, 모델, sampling,
채점 기준을 다시 조정하지 않는다.

## 완료 조건

- Candidate가 Development 실패만으로 작성됨
- 모든 조합이 같은 Validation·채점기를 사용함
- 선택 이유와 lineage가 artifact에 기록됨
- Test가 사람 승인 후 선택 조합 하나에만 실행됨
- 정답, strict pass, 근거, 보류, 오류, 비용과 latency를 함께 보고함
- 전체 pytest, Ruff와 dataset validator가 통과함

고정 프롬프트 실행법은 [다중 모델 벤치마크 가이드](multi-model-benchmark-guide.md), 공통 채점
계약은 [워크플로](workflow.md)를 참고한다.
