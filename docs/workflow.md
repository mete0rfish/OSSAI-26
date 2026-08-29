# 실행과 채점 워크플로

이 문서는 DART QA가 **어떤 데이터를 누구에게 보내고, 어떻게 채점하고, 어떤 기준으로
프롬프트를 선택하는지** 설명한다. 프로젝트 개요와 빠른 시작은 [README](../README.md)를 먼저
참고한다.

## 두 가지 실행 방식

| 구분 | 입력 | 용도 |
| --- | --- | --- |
| schema v2 | YAML | 질문별 답·근거를 단순 평가하는 기존 호환 흐름 |
| schema v3 | JSONL | 데이터 격리, 프롬프트 최적화, Test, robustness를 포함한 권장 흐름 |

두 흐름 모두 모델에는 질문과 HTML만 전달한다. 기대 답과 채점 정보는 로컬 Python 코드에서만
사용한다.

## v3 전체 흐름

```text
사례·HTML 사전 검증
→ Development를 baseline으로 평가
→ strict 실패만 optimizer에 전달
→ Validation에서 baseline과 candidate 비교
→ Python selector가 채택 또는 rollback
→ 선택된 prompt로 Test 실행
→ 사람이 검토한 HTML 변형으로 robustness 평가
```

| 역할 | 허용되는 데이터와 결정 |
| --- | --- |
| target | 질문과 HTML을 받아 답과 근거 생성 |
| optimizer | baseline과 Development strict 실패만 받아 candidate 생성 |
| selector | Validation 결과만 사용해 prompt 선택 |
| Test | 선택 완료 후 품질 확인, 이미 끝난 선택은 변경하지 않음 |

같은 공시·질문의 파생 사례는 같은 `family_id`와 split에 둔다. Validation이나 Test가 candidate
생성에 섞이면 데이터 누출로 간주한다.

## 실행 전 검증

모델 호출 전에 다음 항목을 검사한다.

- case ID 중복과 `family_id` split 누출
- 프로젝트 상대 HTML 경로, 파일 크기와 SHA-256
- answerable/unanswerable 기대값 계약
- 기대 인용의 실제 화면 텍스트 존재 여부
- 기대 답과 `evidence_must_include` 문맥의 인용 포함 여부
- 설정된 split·tag 최소 개수

하나라도 실패하면 provider를 호출하지 않는다.

## 모델 응답과 채점

Target은 다음 `DisclosureAnswer` 형식으로 응답한다.

```json
{
  "answer": "123,456백만원",
  "evidence": [{"quote": "연결 영업이익 123,456백만원"}],
  "confidence": 0.99,
  "abstained": false,
  "abstention_reason": null
}
```

Answerable 사례의 점수는 다음과 같다.

| 조건 | 가중치 |
| --- | ---: |
| 기대 답 또는 허용 답과 일치 | 0.60 |
| 모든 인용이 현재 HTML에 존재 | 0.15 |
| 답이 인용 안에 존재 | 0.10 |
| 필수 문맥이 인용에 포함 | 0.15 |

네 조건을 모두 만족해야 `strict pass`다. Unanswerable 사례는 아래 조건을 모두 만족해야 1점이다.

```text
answer="답변 보류"
abstained=true
evidence=[]
abstention_reason 존재
```

채점기는 Unicode 호환 문자와 공백만 정규화한다. 숫자 쉼표, 부호, 단위, 날짜, 연결/별도 범위는
임의로 바꾸지 않는다. 근거는 HTML 태그를 제거한 화면 표시 텍스트에서 검사한다.

## Candidate 선택과 rollback

Candidate는 Validation에서 다음 조건을 모두 만족해야 선택된다.

```text
baseline과 다른 prompt
오류 수 증가 없음
answerable 보류 증가 없음
strict pass rate 감소 없음
평균 점수 >= baseline 평균 + min_mean_improvement
```

하나라도 실패하면 baseline으로 자동 rollback한다. 점수와 승자는 provider가 아니라 결정론적
Python 코드가 계산한다.

## 주요 CLI

| 목적 | 실행 파일 |
| --- | --- |
| v3 데이터 검증 | `scripts/validate_dataset.py` |
| v3 프롬프트 최적화 | `scripts/optimize_dart_qa_prompt.py` |
| 정답 없는 사전 탐색 | `scripts/probe_dart_qa_model.py` |
| 고정 프롬프트 평가 | `scripts/benchmark_fixed_prompt.py` |
| HTML 변형 생성·평가 | `scripts/generate_html_variants.py`, `scripts/evaluate_html_robustness.py` |
| v2 단일 평가 | `scripts/run_workflow.py` |

API 없는 v3 재현:

```bash
uv run --locked python scripts/validate_dataset.py \
  --cases configs/cases.v3.example.jsonl \
  --config configs/prompt-optimization.recorded.yaml

uv run --locked python scripts/optimize_dart_qa_prompt.py \
  --cases configs/cases.v3.example.jsonl \
  --config configs/prompt-optimization.recorded.yaml \
  --output reports/prompt-optimization/recorded-$(date +%Y%m%d-%H%M%S)
```

기존 v2 재현:

```bash
uv run --locked python scripts/run_workflow.py \
  --cases configs/cases.example.yaml \
  --config configs/recorded.yaml \
  --output reports/v2-recorded-$(date +%Y%m%d-%H%M%S)
```

## Provider와 산출물

지원 provider는 `recorded`, Gemini, NVIDIA NIM, 로컬/Cloud Ollama다. 요청 모델과 API가 반환한
실제 모델, token, 비용, 지연, 오류를 역할별로 기록한다. API 키 값은 `.env`에서만 읽는다.

최적화 결과의 기본 구조는 다음과 같다.

```text
reports/prompt-optimization/<run-id>/
├── calls.jsonl
├── development.jsonl
├── candidate-prompt.md
├── validation.jsonl
├── selected-prompt.md
├── test.jsonl
└── summary.json
```

`calls.jsonl`에는 전체 HTML, 렌더링된 전체 prompt, 기대 답을 기록하지 않는다. 대신 Git,
dataset, HTML, prompt, scorer의 SHA-256과 제한된 호출 metadata를 남긴다.

실행 상태와 품질 상태는 별개다.

| 구분 | 값 |
| --- | --- |
| 실행 | `complete`, `partial`, `not_run` |
| 품질 | `pass`, `fail`, `inconclusive` |

기존 output 디렉터리는 덮어쓰거나 재개하지 않는다. 부분 실행을 보존하고 새 run ID를 사용한다.
