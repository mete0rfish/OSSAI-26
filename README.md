# OSSAI-26: DART 공시 질의응답 검증

DART 공시 HTML과 자연어 질문을 Gemini에 전달하고, 모델이 질문에 해당하는 값과 공시
원문 근거를 정확히 찾는지 검증하는 로컬 실험 프로젝트다. 파싱 코드는 생성하거나 실행하지
않는다.

`OSSAI-26-1`의 검증 가능한 AI workflow 구조를 참고하며 다음 기술을 사용한다.

- Python 3.14
- Gemini API의 안정 모델 `gemini-3.6-flash`
- Beautiful Soup, Pydantic, PyYAML, pytest, Ruff

## 평가 흐름

```text
로컬 DART HTML + 질문
→ Gemini가 answer + evidence JSON 반환
→ 기대값과 답을 결정론적으로 비교
→ 인용문이 실제 HTML 본문에 존재하는지 확인
→ 답이 인용문에 포함되는지 확인
→ JSONL 결과와 요약 저장
```

사례가 통과하려면 다음 조건을 모두 만족해야 한다.

1. `answer`가 사용자가 제공한 `expected`와 일치한다.
2. 모든 `evidence.quote`가 공시의 화면 표시 텍스트에 존재한다.
3. `answer`가 인용 근거 안에 존재한다.

이 구조는 정답만 우연히 생성한 경우와 실제 공시에서 답을 찾아 인용한 경우를 구분한다.
기대값은 모델 프롬프트에 포함되지 않는다.

## 환경 준비

Python 3.14, `uv`, Git이 필요하다.

```bash
uv python install 3.14
uv sync --locked --dev
cp .env.example .env
```

실제 API를 사용할 때 `.env`의 `GEMINI_API_KEY`를 채운다. HTML 원문과 질문은 Gemini
API로 외부 전송되므로 전송 권한이 있는 자료만 사용해야 한다. `.env`, 실제 입력 HTML,
실행 결과는 Git에서 제외된다.

## 평가 사례

사례 파일은 질문 하나와 단일 문자열 기대값 하나를 갖는다. `html_path`는 프로젝트 루트를
기준으로 해석한다.

```yaml
cases:
  - id: operating-profit
    html_path: local-data/example.html
    question: "2025년 연결 영업이익은 얼마인가?"
    expected: "123,456백만원"
```

비교 전 Unicode 호환 정규화, 앞뒤 공백 제거, 연속 공백·줄바꿈 통합만 수행한다. 숫자의
쉼표, 통화 기호, 날짜 표현, 단위는 변환하지 않는다.

## 실행

먼저 저장된 응답으로 API 없는 전체 흐름을 확인할 수 있다. `--output`은 아직 존재하지 않는
새 디렉터리여야 한다.

```bash
uv run --locked python scripts/run_workflow.py \
  --cases configs/cases.example.yaml \
  --config configs/recorded.yaml \
  --output reports/recorded-example
```

실제 Gemini 질의응답을 실행하려면 다음 명령을 사용한다.

```bash
uv run --locked python scripts/run_workflow.py \
  --cases configs/cases.example.yaml \
  --config configs/default.yaml \
  --output reports/live-run
```

## 결과

```text
reports/live-run/
├── results.jsonl
└── summary.json
```

사례 결과에는 질문, 기대값, 모델 답, 인용 근거, 정답 일치 여부, 근거 검증 결과, 요청·실제
모델 ID, 프롬프트 SHA-256, 지연 시간과 토큰 수가 기록된다. API 키, 전체 HTML, 전체
프롬프트는 기록하지 않는다. 일부 사례가 실패해도 완료된 결과는 즉시 JSONL에 보존된다.

실패 상태는 다음과 같이 구분한다.

- `wrong_answer`: 답이 기대값과 다름
- `ungrounded_evidence`: 답은 맞지만 인용이 본문에 없거나 답을 포함하지 않음
- `abstained`: 모델이 답변을 보류함
- `input_error`: HTML을 읽을 수 없거나 크기 제한을 초과함
- `generation_error`: 모델 호출 또는 구조화 응답 검증에 실패함

## DART HTML 원문 수집

`dart-html-fetch/driver`는 DART 공시 URL에서 메인 또는 상세 HTML을 받아 정리한 뒤 로컬
파일로 저장한다.

```bash
python -m pip install -r dart-html-fetch/driver/requirements.txt
python dart-html-fetch/driver/main.py \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=<접수번호>" \
  --out "local-data/disclosure.html"
```

driver의 옵션과 주의사항은 [`dart-html-fetch/SKILL.md`](dart-html-fetch/SKILL.md)를 참고한다.
수집한 HTML 경로와 질문·정답을 사례 YAML에 넣어 질의응답 검증 workflow를 실행한다.

## 개발 검사

```bash
uv run --locked ruff check .
uv run --locked pytest
```

실제 Gemini 통합 실행은 비용과 외부 전송이 발생하므로 자동 테스트에 포함하지 않는다.
