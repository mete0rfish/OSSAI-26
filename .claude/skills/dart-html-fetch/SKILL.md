---
name: dart-html-fetch
description: DART(전자공시) 공시 URL에서 HTML을 받아 클렌징 후 파일로 저장한다 — 전체 본문 또는 특정 목차 섹션만 (fixture HTML 생성용). "DART HTML 받아줘/저장해줘", "fixture HTML 만들어줘", "이 공시 URL 긁어와줘", "collector 테스트용 HTML 뽑아줘", "투자위험요소 섹션만 받아줘", "이 공시 목차 보여줘" 같은 요청에 사용. FWDTCECMDC.Tests/HtmlFetchTest.cs 를 독립 실행형 드라이버로 추출한 것.
---

# dart-html-fetch

DART 공시 URL(`main.do?rcpNo=...`)에서 실제 보고서 HTML을 받아 클렌징한 뒤 파일로 저장하는 스킬이다.
원본 `FWDTCECMDC.Tests/HtmlFetchTest.cs`(fixture 생성용 네트워크 테스트)를 프로젝트 없이도 돌릴 수 있게
필요한 소스(`DartPageLoader`/`HttpClientHelper`/`IframeHelper` + 최소 `Variables`/`Enums`)만 추출해 독립 .NET
콘솔 드라이버로 묶었다. `FWDTCECMDC.Tests/collector/fixture/*.html` 를 새로 뜰 때 쓴다.

동작: 메인 HTML fetch → `viewDoc(...)`에서 iframe URL 추출 → 상세 HTML fetch → 원본과 **동일한 클렌징**
(주석/`<br>`/`<p>`/`<div>` 정리, `&nbsp;`→공백, 중복 공백·개행 축소) → 파일 저장.

전체 본문 대신 **특정 목차 섹션만** 받을 수도 있다(`--section`). 큰 공시(투자설명서·사업보고서)에서
필요한 표만 fixture로 뜰 때 쓴다 — 2.6M chars 전체 대신 100K 내외로 줄어든다.

> 경로는 모두 이 스킬 디렉터리(`.claude/skills/dart-html-fetch/`) 기준이다.

## 사용자에게 먼저 물어볼 것 (필수)

이 스킬을 실행하기 전에 **반드시** 두 가지를 확인한다. 없으면 되묻는다.

1. **URL** — DART 공시 URL. `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=<접수번호>` 형태.
2. **HTML 저장 위치** — 저장할 파일 경로(`.html`). 보통 `D:\FWDTCECMDC\FWDTCECMDC.Tests\collector\fixture\<이름>.html`.
3. **범위** — 전체 본문인지 특정 섹션인지. 섹션이면 `--list-sections` 로 목차를 먼저 보여주고 고르게 한다.
   (사용자가 "전체"라고 하면 묻지 않고 기본 경로로 진행한다.)

두 가지 구현이 있다: **.NET 드라이버**(`driver/`, 원본)와 **Python 드라이버**(`driver.python/`,
동일 로직 이식). 둘 다 인자·종료 코드·출력 형식 계약이 동일하므로 원하는 쪽을 쓰면 된다.

## Prerequisites

**.NET 드라이버**
- .NET SDK (net10.0 대상, 확인된 버전 `10.0.301`). `dotnet --version` 으로 확인.
- 네트워크로 `dart.fss.or.kr` 접근 가능해야 함. HtmlAgilityPack은 `dotnet run` 시 NuGet에서 자동 복원.

**Python 드라이버**
- Python 3.10+ (`str | None` 타입 힌트 사용).
- `pip install -r driver.python/requirements.txt` (`requests`).
- 네트워크로 `dart.fss.or.kr` 접근 가능해야 함.

## Build

```bash
"/c/Program Files/dotnet/dotnet.exe" build driver/DartHtmlFetch.csproj -v q -nologo
```

(`DartPageLoader.cs`의 미사용 `ex` 경고 1건은 원본 소스를 그대로 추출한 것이라 정상이다.)

Python 드라이버는 별도 빌드 없이 의존성만 설치하면 된다:

```bash
pip install -r driver.python/requirements.txt
```

## Run (agent path) — 이게 기본 경로다

**상세 HTML 저장** (기본, `Html을_가져와서_클렌징하여_HTML로_저장한다` 대응):

```bash
"/c/Program Files/dotnet/dotnet.exe" run --project driver -- \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260618000086" \
  --out "D:/FWDTCECMDC/FWDTCECMDC.Tests/collector/fixture/딜번호조회.html"
```

또는 Python 드라이버:

```bash
python driver.python/main.py \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260618000086" \
  --out "D:/FWDTCECMDC/FWDTCECMDC.Tests/collector/fixture/딜번호조회.html"
```

성공 시(두 드라이버 동일한 출력 형식, 문자 수도 동일하게 나온다 — 확인됨):
```
[1/3] 메인 HTML 요청: https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260618000086
[2/3] iframe 추출 후 상세 HTML 요청 + 클렌징...
[3/3] 저장 완료: ...\딜번호조회.html (1,149,734 chars)
```

**메인 HTML(원본) 저장** (`mainHtml를_저장한다` 대응) — `--main-only` 추가:

```bash
"/c/Program Files/dotnet/dotnet.exe" run --project driver -- \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260618000086" \
  --out "D:/FWDTCECMDC/FWDTCECMDC.Tests/collector/fixture/main.html" --main-only

# 또는
python driver.python/main.py \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260618000086" \
  --out "D:/FWDTCECMDC/FWDTCECMDC.Tests/collector/fixture/main.html" --main-only
```

### 특정 섹션만 저장 (`--list-sections` → `--section`)

**1단계 — 목차 확인** (`--out` 불필요, 네트워크 요청 1회):

```bash
python driver.python/main.py \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260723000639" --list-sections

# 또는
"/c/Program Files/dotnet/dotnet.exe" run --project driver -- \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260723000639" --list-sections
```

```
[1/3] 메인 HTML 요청: https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260723000639
[2/2] 목차:
목차 27개 (--section 에 '#번호' 또는 섹션명을 지정)
  #1   투 자 설 명 서   [eleId=1 length=4680]
  #2   【 본    문 】   [eleId=2 length=3324016]
  #3     요약정보   [eleId=3 length=64176]
  ...
  #9       III. 투자위험요소   [eleId=9 length=142300]
  ...
  #15      II. 사업의 내용   [eleId=15 length=189025]
```

**2단계 — 섹션 저장**:

```bash
python driver.python/main.py \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260723000639" \
  --out "D:/FWDTCECMDC/FWDTCECMDC.Tests/collector/fixture/투자위험요소.html" \
  --section "#9"
```

```
[2/3] 섹션 "【 본    문 】 > 제1부 모집 또는 매출에 관한 사항 > III. 투자위험요소" 요청 + 클렌징... (eleId=9, offset=131687, length=142300)
[3/3] 저장 완료: ...\투자위험요소.html (111,173 chars)
```

`--section` 지정자 3가지:

| 형식 | 예 | 설명 |
|---|---|---|
| `#번호` | `--section "#9"` | 목차 순번. **가장 확실함** — 이걸 기본으로 써라. |
| 섹션명 | `--section "II. 사업의 내용"` | 공백 무시 부분일치. 완전일치 우선. |
| `eleId=N` | `--section "eleId=15"` | `eleId` 정확 일치. |

섹션명이 여러 곳과 겹치면(예: 투자설명서의 `투자위험요소` = 요약 `#5` + 본문 `#9`) 저장하지 않고
후보 목록 + 전체 목차를 출력하며 exit 2 로 끝난다. 이때 `#번호`로 다시 지정한다.

옵션(두 드라이버 공통):
- `--url <URL>` (필수)
- `--out <경로.html>` (필수, 상위 폴더는 자동 생성. `--list-sections` 일 때만 생략 가능)
- `--main-only` — 클렌징한 상세 HTML 대신 메인 HTML 원본을 저장
- `--list-sections` — 목차만 출력하고 종료
- `--section <지정자>` — 전체 본문 대신 그 섹션만 fetch + 클렌징 (`--main-only` 와 배타)
- `--sleep <ms>` — 요청 간격 재정의(기본 2500). **줄이지 말 것**(차단 회피).

종료 코드: `0` 성공 / `1` fetch 실패·차단·목차 미발견 / `2` 인자 누락·섹션 미발견·모호.

## Run (human path)

원본 워크플로는 테스트 러너로 도는 것이다: `FWDTCECMDC.Tests/HtmlFetchTest.cs`의
`Html을_가져와서_클렌징하여_HTML로_저장한다` 실행. URL·저장경로가 코드에 하드코딩되어 있어
매번 편집해야 하므로, 위 드라이버(인자로 지정)를 쓰는 편이 낫다.

## Gotchas

- **차단 페이지**: DART가 `<title>거부</title>` + "검토중인 문서입니다." 를 반환하면 드라이버가
  즉시 `[실패]`로 종료(exit 1)한다. 잠시 후 재시도. `--sleep`을 줄이면 차단이 잦아진다.
- **iframe 미발견**: 상세 HTML은 메인 페이지의 `viewDoc("rcpNo","dcmNo",...,"dtd")` JS 호출에서
  URL을 뽑는다. 이 패턴이 없으면(공시 형식이 다르면) 상세 fetch가 `null`→exit 1. 이때는 `--main-only`로 메인만 저장해 확인.
- **인코딩**: 응답 charset(헤더→meta→UTF-8 폴백)을 자동 판별하고, 파일은 UTF-8(BOM 포함)로 저장한다.
  .NET 드라이버는 EUC-KR 대응 위해 `CodePagesEncodingProvider`를 등록해 둠. Python 드라이버는 저장 시
  `encoding="utf-8-sig"`로 동일하게 BOM을 붙인다. 저장 파일 첫 글자에 BOM(`﻿`)이 붙는다.
- **클렌징은 상세 HTML에만** 적용된다. `--main-only`로 받은 메인 HTML은 원본 그대로다.
  `--section` 으로 받은 섹션 HTML은 전체 본문과 **동일한 클렌징**을 거친다(같은 로더 경로를 탄다).
- **목차 출처**: 섹션 정보는 메인 HTML의 `makeToc()` 안 JS 리터럴(`nodeN['eleId'|'offset'|'length']`)에서
  파싱한다. 변수명 숫자(`node1`/`node2`/`node3`)가 목차 깊이다. DART가 이 렌더링 방식을 바꾸면
  `[실패] 목차를 찾지 못했습니다` 가 나오므로, `--main-only`로 메인을 받아 `makeToc` 구조를 다시 확인해야 한다.
- **목차 없는 공시**: 단순 공시는 `makeToc()`에 노드가 없을 수 있다. 이때 `--section`/`--list-sections`는
  exit 1 이고, 전체 본문(`--section` 없이)으로 받으면 된다.
- **`length` 는 문서 내 바이트 길이**로, 저장된 파일 크기와 정확히 같지는 않다(클렌징·인코딩 차이).
  목차의 `length` 는 섹션 크기를 가늠하는 용도로만 보면 된다.
- **섹션 URL 은 `offset`/`length` 로 잘라오는 방식**이다. 전체 본문 URL(`IframeHelper`)은 `offset=0&length=0`
  이고, 섹션 URL 만 실제 값을 넣는다. 두 드라이버 출력은 바이트 단위로 동일함을 확인했다.
- **Python 드라이버는 SSL 인증서 검증을 비활성화**한다(`requests` 세션 `verify=False` + `urllib3`
  `InsecureRequestWarning` 억제) — .NET 드라이버의 `DangerousAcceptAnyServerCertificateValidator`와 동일 취지.
- **Python 드라이버는 동기 실행**이다(원본의 `async`/`Task.Delay` 폴링을 `time.sleep` 루프로 단순화).
  단발성 CLI라 동작 차이는 없다.

## Troubleshooting

- `[실패] 메인 HTML이 비어 있습니다` → 네트워크 불가 또는 20분 타임아웃. DART 접속/URL 확인.
- `[실패] DART 차단/검토중 페이지...` → 차단됨. 몇 분 뒤 재시도.
- `[실패] 상세 HTML을 가져오지 못했습니다` → iframe(`viewDoc`) 미발견. `--main-only`로 메인 확인.
- `[실패] '...' 이(가) 여러 섹션과 일치합니다` → 출력된 후보에서 `#번호`를 골라 다시 실행.
- `[실패] 목차를 찾지 못했습니다` → 목차 없는 공시이거나 DART 렌더링 변경. 전체 본문으로 받거나
  `--main-only` 로 메인 HTML의 `makeToc` 구조 확인.
- NuGet 복원 실패(.NET) → 사내 프록시/피드 설정 확인(HtmlAgilityPack 1.11.72 필요).
- `ModuleNotFoundError: requests`(Python) → `pip install -r driver.python/requirements.txt` 재실행.

## 구성

```
.claude/skills/dart-html-fetch/
  SKILL.md
  driver/
    DartHtmlFetch.csproj   # net10.0 콘솔, HtmlAgilityPack 참조
    Program.cs             # --url/--out/--main-only/--section/--list-sections 진입점
    DartPageLoader.cs      # 원본 core/Networking/DartPageLoader.cs 추출
    HttpClientHelper.cs    # 원본 core/Networking/HttpClientHelper.cs 추출
    IframeHelper.cs        # 원본 core/Networking/IframeHelper.cs 추출 (전체 본문 URL)
    TocHelper.cs           # 이 스킬 고유: makeToc() 목차 파싱 + 섹션 URL 빌드 + 섹션 매칭
    Variables.cs           # SleepInterval/UseHtmlCache 만 추출
    Enums.cs               # RequestMethod/ReturnType 만 추출
  driver.python/           # 위 driver/ 와 동일 로직의 Python 이식판
    requirements.txt       # requests
    main.py                # Program.cs 미러 (동일 인자·종료 코드·출력)
    dart_page_loader.py    # DartPageLoader.cs 대응 (동기 함수 + time.sleep)
    http_client_helper.py  # HttpClientHelper.cs 대응
    iframe_helper.py       # IframeHelper.cs 대응
    toc_helper.py          # TocHelper.cs 대응
    variables.py           # SLEEP_INTERVAL_MS/USE_HTML_CACHE
    enums.py               # RequestMethod/ReturnType
```

원본 네트워킹 코드가 바뀌면 두 드라이버(`driver/`, `driver.python/`) 모두 함께 갱신할 것.

`TocHelper`/`toc_helper` 는 원본 프로젝트에 없는 이 스킬 고유 코드다. 섹션 fetch는 로더를
수정하지 않고 `LoadSubHtmlAsync(null, sectionUrl)` / `load_sub_html("", section_url)` 로
URL을 직접 주입하는 방식이라(메인 HTML이 비면 로더가 인자 URL을 상세 URL로 쓴다) 원본 추출
코드와의 동기화가 깨지지 않는다.
