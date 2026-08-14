import pytest

from dart_parser_workflow.safety import SafetyViolation, validate_parser_source

SAFE_SOURCE = """from bs4 import BeautifulSoup

LABEL = "영업이익"

def extract(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(string=LABEL)
    if node is None:
        raise ValueError("not found")
    return node.parent.find_next("td").get_text(strip=True)
"""


def test_safe_parser_is_accepted() -> None:
    validate_parser_source(SAFE_SOURCE, 100_000)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("import os\ndef extract(html): return os.getcwd()", "허용되지 않은 import"),
        ("def extract(html): return open('/tmp/value').read()", "허용되지 않은 함수"),
        ("def extract(html): return html.__class__.__name__", "dunder attribute"),
        ("print('side effect')\ndef extract(html): return html", "모듈 import 시 실행"),
        ("def other(html): return html", "정확히 하나의 extract"),
    ],
)
def test_unsafe_parser_is_rejected(source: str, message: str) -> None:
    with pytest.raises(SafetyViolation, match=message):
        validate_parser_source(source, 100_000)


def test_source_size_is_limited() -> None:
    with pytest.raises(SafetyViolation, match="크기 제한"):
        validate_parser_source(SAFE_SOURCE, 10)
