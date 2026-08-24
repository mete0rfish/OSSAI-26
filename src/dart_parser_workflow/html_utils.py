"""HTML 입력과 화면 텍스트를 일관되게 처리한다."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup, UnicodeDammit


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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())
