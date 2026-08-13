"""메인 HTML(main.do)의 makeToc() 에서 목차 트리를 추출하고 섹션 URL을 만든다.

DART 메인 페이지는 좌측 목차를 `makeToc()` 안에서 JS 리터럴로 만든다:

    var node3 = {};
    node3['text'] = "2. 투자위험요소";
    node3['eleId'] = "5";
    node3['offset'] = "66274";
    node3['length'] = "3540";
    node3['dtd'] = "dart4.xsd";

변수명의 숫자(node1/node2/node3)가 목차 깊이다. 각 노드의 eleId/offset/length 를
`/report/viewer.do` 에 그대로 실어 보내면 **그 섹션만** 받을 수 있다.
(전체 본문은 offset=0&length=0 — IframeHelper 가 만드는 URL이 이것이다.)
"""

import re

_NEW_NODE = re.compile(r"""var\s+node(\d+)\s*=\s*\{\s*\}""")
_ASSIGN = re.compile(r"""node(\d+)\['(\w+)'\]\s*=\s*"([^"]*)"\s*;""")
_MAKE_TOC = re.compile(r"function\s+makeToc\s*\(\s*\)\s*\{")


def _normalize(text: str) -> str:
    """비교용 정규화 — DART 제목은 '투 자 설 명 서'처럼 공백이 끼어 있다."""
    return re.sub(r"\s+", "", text or "").replace("　", "")


def parse_toc(main_html: str) -> list[dict]:
    """목차 노드 목록을 문서 순서대로 반환. 각 노드는 depth/path/no 가 추가된 dict."""
    body = main_html or ""
    match = _MAKE_TOC.search(body)
    if match:
        body = body[match.end():]

    nodes: list[dict] = []
    current: dict | None = None

    for line in body.splitlines():
        new_node = _NEW_NODE.search(line)
        if new_node:
            current = {"depth": int(new_node.group(1))}
            nodes.append(current)
            continue

        assign = _ASSIGN.search(line)
        if assign and current is not None:
            depth, key, value = int(assign.group(1)), assign.group(2), assign.group(3)
            if depth == current["depth"]:
                current[key] = value

    nodes = [n for n in nodes if n.get("eleId")]

    # 부모 경로 계산 (depth 스택)
    stack: list[str] = []
    for index, node in enumerate(nodes, start=1):
        depth = node["depth"]
        del stack[depth - 1:]
        text = node.get("text", "")
        stack.append(text)
        node["no"] = index
        node["path"] = " > ".join(stack)

    return nodes


def build_section_url(node: dict) -> str:
    """노드 하나에 해당하는 viewer.do URL."""
    dtd = node.get("dtd", "")
    dtd_param = f"&dtd={dtd}" if dtd else ""
    return (
        f"https://dart.fss.or.kr/report/viewer.do?rcpNo={node['rcpNo']}"
        f"&dcmNo={node['dcmNo']}&eleId={node['eleId']}"
        f"&offset={node.get('offset', '0')}&length={node.get('length', '0')}{dtd_param}"
    )


def format_toc(nodes: list[dict]) -> str:
    lines = [f"목차 {len(nodes)}개 (--section 에 '#번호' 또는 섹션명을 지정)"]
    for node in nodes:
        indent = "  " * (node["depth"] - 1)
        lines.append(
            f'  #{node["no"]:<3} {indent}{node.get("text", "")}'
            f'   [eleId={node["eleId"]} length={node.get("length", "?")}]'
        )
    return "\n".join(lines)


def find_section(nodes: list[dict], spec: str):
    """섹션 지정자로 노드 하나를 찾는다.

    반환: (node, None) 성공 / (None, 에러메시지) 실패(미발견·모호).

    지정자 형식:
      #12          목차 순번
      eleId=9      eleId 정확 일치
      투자위험요소  섹션명 (공백 무시, 완전일치 우선 → 부분일치)
    """
    spec = (spec or "").strip()
    if not spec:
        return None, "섹션 지정자가 비어 있습니다."

    if spec.startswith("#"):
        raw = spec[1:].strip()
        if not raw.isdigit():
            return None, f"'{spec}' — '#' 뒤에는 목차 순번(숫자)이 와야 합니다."
        hits = [n for n in nodes if n["no"] == int(raw)]
        if not hits:
            return None, f"목차 순번 {raw} 이(가) 없습니다 (1~{len(nodes)})."
        return hits[0], None

    if spec.lower().startswith("eleid="):
        wanted = spec.split("=", 1)[1].strip()
        hits = [n for n in nodes if n["eleId"] == wanted]
        if not hits:
            return None, f"eleId={wanted} 인 섹션이 없습니다."
        return hits[0], None

    needle = _normalize(spec)
    exact = [n for n in nodes if _normalize(n.get("text", "")) == needle]
    candidates = exact or [n for n in nodes if needle in _normalize(n.get("text", ""))]

    if not candidates:
        return None, f"'{spec}' 과(와) 일치하는 섹션이 없습니다."

    if len(candidates) > 1:
        listing = "\n".join(
            f'  #{n["no"]}  {n["path"]}   [eleId={n["eleId"]}]' for n in candidates
        )
        return None, f"'{spec}' 이(가) 여러 섹션과 일치합니다. '#번호'로 지정하세요:\n{listing}"

    return candidates[0], None
