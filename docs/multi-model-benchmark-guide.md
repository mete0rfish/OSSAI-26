# 다중 모델 벤치마크 가이드

같은 데이터와 고정 프롬프트를 여러 target 모델에 적용해 **정답, 근거, 안전성, 비용을 공정하게
비교하는 방법**을 설명한다. 프롬프트 최적화가 목적이라면
[복잡한 프롬프트 실험 가이드](complex-prompt-experiment-guide.md)를 함께 본다.

## 핵심 원칙

- 모든 모델에 같은 사례, prompt SHA-256, 채점기를 사용한다.
- 기대 답·허용 답·기대 근거는 target에 보내지 않는다.
- Benchmark 중 optimizer나 candidate를 만들지 않는다.
- 모델마다 새 output 디렉터리를 사용한다.
- 공개된 Test 결과는 `exploratory`로만 해석한다.
- 최종 모델 선택은 새로운 Validation에서 하고, 선택된 모델만 새로운 Test에 실행한다.

## 실행 흐름

```text
고정 prompt와 dataset hash 확인
→ 모델별 smoke test
→ 같은 split을 모델마다 독립 실행
→ Python으로 지표 집계
→ Validation 결과로 모델 선택
→ 사람 승인
→ 선택 모델 하나만 새 Test 실행
```

`scripts/benchmark_fixed_prompt.py`는 target 하나를 평가한다. Prompt optimization과 달리
optimizer, candidate, selector를 생성하지 않는다.

```bash
uv run --locked python scripts/benchmark_fixed_prompt.py \
  --cases local-data/dart-qa/cases/cases.v3.jsonl \
  --config configs/fixed-prompt-benchmark.gemini-3.5-flash-lite.yaml \
  --split all \
  --output reports/model-benchmarks/gemini-$(date +%Y%m%d-%H%M%S)
```

`--split`은 `development`, `validation`, `test`, `all` 중 하나다. `--sample-id`를 반복 지정하면
smoke test를 실행할 수 있다.

## 제공 설정

| 설정 | Provider |
| --- | --- |
| `fixed-prompt-benchmark.gemini-3.5-flash-lite.yaml` | Gemini |
| `fixed-prompt-benchmark.gpt-oss-120b.yaml` | Ollama Cloud |
| `fixed-prompt-benchmark.qwen3.5-cloud.yaml` | Ollama Cloud |
| `fixed-prompt-benchmark.nemotron-3-ultra.yaml` | NVIDIA NIM |

정확한 모델 제공 여부, 가격, quota는 live 실행 직전에 공식 문서에서 다시 확인한다. 실제 키가
아닌 **키가 저장된 환경변수 이름**만 YAML이나 CLI에 기록한다.

## 비교 지표

최소한 다음 항목을 함께 비교한다.

| 지표 | 의미 |
| --- | --- |
| exact answer | 기대값과 답의 일치 |
| strict pass | 답·실제 근거·필수 문맥을 모두 충족 |
| unsafe answer | 보류해야 할 문제에서 값을 추측 |
| answerable abstention | 답할 수 있는 문제에서 불필요하게 보류 |
| generation error | 호출·JSON schema 오류 |
| latency / token / cost | 운영 효율과 예산 |

Validation 선택 순서는 다음과 같다.

1. strict pass rate가 높은 모델
2. 동률이면 mean quality score가 높은 모델
3. 동률이면 generation error가 적은 모델
4. 동률이면 unsafe answer와 불필요한 보류가 적은 모델
5. 품질이 비슷하면 비용과 지연을 사람이 검토

모델 ID, prompt SHA-256, dataset·scorer·Git hash와 선택 이유를 selection artifact에 고정한다.

## 공정 비교 체크리스트

- [ ] 같은 dataset과 split 사용
- [ ] 같은 prompt SHA-256 사용
- [ ] temperature와 출력 한도를 가능한 범위에서 고정
- [ ] provider별 실제 요청 설정과 actual model ID 기록
- [ ] 모델별 새 output 디렉터리 사용
- [ ] Validation/Test를 prompt 수정에 재사용하지 않음
- [ ] Test 전에 외부 전송, 호출 수와 비용 상한 승인

Provider가 지원하지 않는 옵션을 억지로 맞추지 않는다. 차이는 숨기지 않고 lineage에 기록한다.

## 산출물과 해석

```text
reports/model-benchmarks/<run-id>/
├── calls.jsonl
├── fixed-prompt.md
├── results.jsonl
└── summary.json
```

`summary.json`은 전체와 split별 점수, 오류, latency와 provider 사용량을 기록한다. 모든 사례를
시도했다면 일부 모델 응답이 실패해도 실행은 `complete`일 수 있다. 품질의 `pass/fail`은 별도로
판정한다.

현재 프로젝트의 데이터와 기존 비교 결과는 [프로젝트 현황](project-status-overview-20260828.md)을
참고한다.
