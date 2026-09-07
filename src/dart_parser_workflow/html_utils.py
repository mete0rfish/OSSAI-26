"""HTML 입력과 화면 텍스트를 일관되게 처리한다."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from bs4 import BeautifulSoup, Comment, UnicodeDammit

HTML_PREPROCESSOR_VERSION = "compact-html-v1"


@dataclass(frozen=True)
class PreparedHtml:
    raw_html: str
    model_input: str
    preprocessor: str
    prepared_sha256: str
    raw_bytes: int
    prepared_bytes: int


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    return re.sub(r"\s+", " ", normalized)


def read_html(path: Path, max_bytes: int) -> tuple[bytes, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"HTML 파일을 읽을 수 없습니다: {path}: {exc}") from exc
    if len(raw) > max_bytes:
        raise ValueError(f"HTML 파일이 {max_bytes} byte 제한을 초과했습니다: {len(raw)}")
    decoded = UnicodeDammit(raw, is_html=True).unicode_markup
    if decoded is None:
        raise ValueError(f"HTML 문자 인코딩을 판별할 수 없습니다: {path}")
    return raw, decoded


def visible_text(html: str) -> str:
    return normalize_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))


def compact_html(html: str) -> str:
    """불필요한 markup만 제거하고 화면 텍스트와 표 구조는 그대로 보존한다."""

    document = BeautifulSoup(html, "html.parser")
    for node in document.find_all(string=lambda value: isinstance(value, Comment)):
        node.extract()
    for tag in document.find_all(["script", "style", "template", "noscript"]):
        tag.decompose()
    for tag in document.find_all(True):
        tag.attrs = {
            name: value
            for name, value in tag.attrs.items()
            if tag.name in {"td", "th"} and name in {"rowspan", "colspan"}
        }
    compacted = document.decode(formatter="minimal")
    compacted = re.sub(r">[ \t\r\n]+<", "><", compacted).strip()
    if visible_text(compacted) != visible_text(html):
        raise ValueError("HTML 압축 결과의 화면 텍스트가 원본과 다릅니다")
    return compacted


def prepare_html(
    path: Path,
    max_bytes: int,
    strategy: Literal["raw", "compact"],
) -> PreparedHtml:
    raw, html = read_html(path, max_bytes)
    if strategy == "raw":
        model_input = html
        preprocessor = "raw"
    else:
        model_input = compact_html(html)
        preprocessor = HTML_PREPROCESSOR_VERSION
    encoded = model_input.encode()
    return PreparedHtml(
        raw_html=html,
        model_input=model_input,
        preprocessor=preprocessor,
        prepared_sha256=sha256_bytes(encoded),
        raw_bytes=len(raw),
        prepared_bytes=len(encoded),
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())
