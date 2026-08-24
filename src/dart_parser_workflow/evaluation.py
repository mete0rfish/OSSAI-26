"""답과 인용 근거를 결정론적으로 검증한다."""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

from .schemas import (
    DisclosureAnswer,
    EvaluationCaseV3,
    ScoreBreakdown,
    V3CaseStatus,
)


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


def score_answer_v3(
    case: EvaluationCaseV3, answer: DisclosureAnswer, html: str
) -> tuple[ScoreBreakdown, V3CaseStatus]:
    """v3 answerable/unanswerable 규칙으로 응답을 채점한다."""

    if case.expected.abstained:
        safe_abstention = (
            answer.abstained
            and answer.answer == "답변 보류"
            and not answer.evidence
            and bool(answer.abstention_reason)
        )
        reasons = [] if safe_abstention else ["unsafe_answer"]
        return (
            ScoreBreakdown(
                answer_correct=safe_abstention,
                evidence_in_document=safe_abstention,
                answer_in_evidence=safe_abstention,
                expected_context_covered=safe_abstention,
                quality_score=1.0 if safe_abstention else 0.0,
                strict_pass=safe_abstention,
                failure_reasons=reasons,
            ),
            "passed" if safe_abstention else "unsafe_answer",
        )

    if answer.abstained:
        return (
            ScoreBreakdown(
                quality_score=0.0,
                failure_reasons=["unexpected_abstention"],
            ),
            "unexpected_abstention",
        )

    normalized_answer = normalize_scalar(answer.answer)
    accepted = {
        normalize_scalar(value)
        for value in [case.expected.answer, *case.expected.accepted_answers]
    }
    answer_correct = normalized_answer in accepted
    evidence_in_document, answer_in_evidence = validate_evidence(answer, html)
    quotes = " ".join(normalize_scalar(item.quote) for item in answer.evidence)
    missing_context = [
        anchor
        for anchor in case.expected.evidence_must_include
        if normalize_scalar(anchor) not in quotes
    ]
    context_covered = not missing_context
    quality_score = round(
        0.60 * answer_correct
        + 0.15 * evidence_in_document
        + 0.10 * answer_in_evidence
        + 0.15 * context_covered,
        4,
    )
    strict_pass = (
        answer_correct and evidence_in_document and answer_in_evidence and context_covered
    )
    reasons: list[str] = []
    if not answer_correct:
        reasons.append("wrong_answer")
    if not evidence_in_document:
        reasons.append("evidence_not_in_document")
    if not answer_in_evidence:
        reasons.append("answer_not_in_evidence")
    if not context_covered:
        reasons.append("missing_context")
    if strict_pass:
        status: V3CaseStatus = "passed"
    elif not answer_correct:
        status = "wrong_answer"
    elif not evidence_in_document or not answer_in_evidence:
        status = "ungrounded_evidence"
    else:
        status = "missing_context"
    return (
        ScoreBreakdown(
            answer_correct=answer_correct,
            evidence_in_document=evidence_in_document,
            answer_in_evidence=answer_in_evidence,
            expected_context_covered=context_covered,
            missing_context=missing_context,
            quality_score=quality_score,
            strict_pass=strict_pass,
            failure_reasons=reasons,
        ),
        status,
    )
