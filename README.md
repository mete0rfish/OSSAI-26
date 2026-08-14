# OSSAI-26: DART 공시 파서 생성·검증

DART 공시 HTML과 자연어 질문을 Gemini에 전달해 전용 Python 파서를 생성하고, 파서의
출력값을 사용자가 제공한 기대값과 검증하는 로컬 실험 프로젝트다. 기대값은 Gemini 생성
프롬프트에 넣지 않으며, DeepEval 점수와 관계없이 보수적으로 정규화한 문자열의 일치 여부가
최종 성공을 결정한다.

`OSSAI-26-1`의 검증 가능한 AI workflow 구조를 참고하며 다음 기술을 사용한다.

- Python 3.14
- Gemini API의 안정 모델 `gemini-3.6-flash`
- DeepEval의 Gemini 기반 G-Eval 보조 진단
- Beautiful Soup, Pydantic, PyYAML, pytest, Ruff

## 동작 흐름

```text
로컬 HTML + 질문
→ Gemini가 extract(html: str) -> str 코드 생성
→ AST 안전 검사
→ 제한된 subprocess에서 실행
→ 기대값과 결정론 비교
→ 선택적 DeepEval 코드 품질 진단
→ 생성 코드·JSONL 결과·요약 저장
```

기대값은 마지막 비교 단계에서만 사용한다. 구문·안전 검사·런타임 오류에는 오류 정보만
제공해 최대 2회 코드를 수정하지만, 정상 실행된 오답은 다시 생성하지 않는다.

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

실제 Gemini 생성과 DeepEval 진단을 실행하려면 다음 명령을 사용한다.

```bash
uv run --locked python scripts/run_workflow.py \
  --cases configs/cases.example.yaml \
  --config configs/default.yaml \
  --output reports/live-run
```

DeepEval 진단 API 호출을 생략하려면 `--no-diagnostics`를 추가한다. 진단 실패나 점수는
정답 일치 결과를 바꾸지 않는다.

## 결과

```text
reports/live-run/
├── operating-profit/
│   ├── parser_attempt_0.py
│   └── parser_attempt_1.py  # 수정이 발생한 경우
├── results.jsonl
└── summary.json
```

사례 결과에는 요청·실제 모델 ID, 최초 프롬프트 SHA-256, 시도별 코드 경로와 오류, 토큰 수,
추출값·기대값·통과 여부 및 DeepEval 진단이 기록된다. API 키, 전체 HTML, 전체 프롬프트는
기록하지 않는다. 일부 사례가 실패해도 완료된 결과는 즉시 JSONL에 보존된다.

## 생성 코드 계약과 보안 한계

생성 코드는 다음 함수를 정확히 하나 제공해야 한다.

```python
def extract(html: str) -> str:
    """질문에 해당하는 단일 값을 반환한다."""
```

AST 검사에서 파일·네트워크·프로세스·환경 변수 접근, 동적 코드 실행, 위험한 import,
모듈 import 시 부수 효과를 거부한다. 실행 subprocess에는 정리된 환경, 임시 작업 디렉터리,
CPU·메모리·시간·출력 제한을 적용한다.

이 장치는 Gemini가 우발적으로 만든 위험한 코드를 막기 위한 방어선이며 악의적인 Python에
대한 완전한 샌드박스가 아니다. 신뢰되지 않은 코드를 실행해야 한다면 Docker나 별도 격리
서비스가 필요하다.

## 개발 검사

```bash
uv run --locked ruff check .
uv run --locked pytest
```

실제 Gemini 통합 실행은 비용과 외부 전송이 발생하므로 자동 테스트에 포함하지 않는다.
파서 workflow 자체에는 DART URL 크롤링, 복수 필드 JSON, 표 전체 추출, 웹 UI가 포함되지
않는다. DART HTML 원문 수집은 저장소에 함께 포함된 별도 driver를 사용한다.

## DART HTML 원문 수집

원격에서 추가된 `dart-html-fetch/driver`는 DART 공시 URL에서 메인 또는 상세 HTML을 받아
정리한 뒤 로컬 파일로 저장한다. 의존성을 설치한 후 다음처럼 실행한다.

```bash
python -m pip install -r dart-html-fetch/driver/requirements.txt
python dart-html-fetch/driver/main.py \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=<접수번호>" \
  --out "local-data/disclosure.html"
```

driver의 옵션과 주의사항은 [`dart-html-fetch/SKILL.md`](dart-html-fetch/SKILL.md)를 참고한다.
수집한 HTML 경로와 질문·정답을 사례 YAML에 넣어 위 파서 생성·검증 workflow를 실행한다.

## 모델 비교 방향

현재 구현된 provider는 `gemini-3.6-flash`와 오프라인 저장 응답이다. 이후 동일한 평가 사례와
결정론 채점 조건에서 다음 모델을 비교하고, 사례별 실패 결과를 바탕으로 프롬프트를 수정한다.

- `gemini/gemini-3.5-flash-lite`
- `nvidia_nim/google/gemma-4-31b-it`
