"""답과 인용 근거를 결정론적으로 검증한다."""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

from .schemas import DisclosureAnswer


def normalize_scalar(value: str) -> str:
    """의미 변환 없이 Unicode와 공백 표현만 정규화한다."""

    normalized = unicodedata.normalize("NFKC", value).strip()
    return re.sub(r"\s+", " ", normalized)


def validate_evidence(answer: DisclosureAnswer, html: str) -> tuple[bool, bool]:
    """모든 인용이 본문에 있고 답이 인용 중에 있는지 반환한다."""

    if answer.abstained or not answer.evidence:
        return False, False

    document_text = normalize_scalar(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    quotes = [normalize_scalar(item.quote) for item in answer.evidence]
    evidence_in_document = all(quote in document_text for quote in quotes)
    answer_in_evidence = normalize_scalar(answer.answer) in " ".join(quotes)
    return evidence_in_document, answer_in_evidence
