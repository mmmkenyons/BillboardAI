"""Deterministic outreach-readiness quality gates for generated creative.

This module is intentionally Qt-free, network-free, and model/API-free.  It
distinguishes technically generated output from outreach-ready output using
compact, structured reasons that Campaign Assembly can consume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from gui.models.prospect import (
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_ERROR,
    RESOLUTION_NOT_FOUND,
    RESOLUTION_RESOLVED,
    RESOLUTION_TIMEOUT,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
)


QUALITY_PASS = "PASS"
QUALITY_WARNING = "WARNING"
QUALITY_BLOCKED = "BLOCKED"

PERSON_PROFILE_RESOLVED = "PERSON_PROFILE_RESOLVED"
PERSON_PROFILE_UNRESOLVED = "PERSON_PROFILE_UNRESOLVED"

HEADLINE_TOO_LONG = "HEADLINE_TOO_LONG"
HEADLINE_TOO_MANY_WORDS = "HEADLINE_TOO_MANY_WORDS"
SEO_TITLE_LIKE = "SEO_TITLE_LIKE"
TRUNCATED_PHRASE = "TRUNCATED_PHRASE"
MALFORMED_COPY = "MALFORMED_COPY"
GENERIC_PLACEHOLDER_COPY = "GENERIC_PLACEHOLDER_COPY"
UNSUPPORTED_SUPERLATIVE = "UNSUPPORTED_SUPERLATIVE"
UNSUPPORTED_NUMERIC_CLAIM = "UNSUPPORTED_NUMERIC_CLAIM"
PERSON_NAME_MISMATCH = "PERSON_NAME_MISMATCH"
COMPANY_NAME_MISMATCH = "COMPANY_NAME_MISMATCH"
MISSING_HEADLINE = "MISSING_HEADLINE"
MISSING_CTA = "MISSING_CTA"

_SUPERLATIVE_TERMS = (
    "fastest", "best", "#1", "number one", "top-rated", "top rated",
    "leading", "largest", "guaranteed", "most trusted",
)
_SEO_SEPARATORS = (" | ", " - ", " – ", " — ", "::")
_DANGLING_ENDINGS = {
    "and", "or", "with", "for", "to", "from", "of", "in", "near", "what",
    "your", "our", "the", "a", "an", "get", "join", "work",
}


@dataclass(frozen=True)
class CopyQualityReason:
    code: str
    message: str
    evidence: str = ""


@dataclass(frozen=True)
class CopyQualityAssessment:
    status: str = QUALITY_PASS
    reasons: tuple[CopyQualityReason, ...] = field(default_factory=tuple)

    @property
    def blocking_reasons(self) -> tuple[CopyQualityReason, ...]:
        return self.reasons if self.status == QUALITY_BLOCKED else ()

    @property
    def warning_reasons(self) -> tuple[CopyQualityReason, ...]:
        return self.reasons if self.status == QUALITY_WARNING else ()


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9#]+", " ", str(value or "").lower()).strip()


def _tokens(value: object) -> list[str]:
    return [t for t in _norm(value).split() if t]


def _source_texts(prospect: Any, concept: Any, project: Any, row: Any) -> list[str]:
    texts: list[str] = []
    extra = getattr(concept, "extra", None)
    if isinstance(extra, dict):
        texts.append(str(extra))
    for attr in ("brand_profile", "strategies", "ad_concepts", "metadata"):
        value = getattr(project, attr, None)
        if value:
            texts.append(str(value))
    for attr in ("metadata", "notes", "category", "company_name", "contact_name"):
        value = getattr(prospect, attr, None)
        if value:
            texts.append(str(value))
    return texts


def _claim_supported(claim: str, source_texts: Iterable[str]) -> bool:
    needle = _norm(claim)
    if not needle:
        return True
    return any(needle in _norm(text) for text in source_texts)


def _numbers(value: str) -> list[str]:
    return re.findall(r"(?:[$#]\s*)?\d[\d,]*(?:\.\d+)?\s*(?:%|years?|homes?|minutes?|minute|off)?", value, flags=re.I)


def _name_mismatch(text: str, expected: str) -> bool:
    expected_tokens = _tokens(expected)
    if len(expected_tokens) < 2:
        return False
    # If generated text names the first name with a different nearby last name,
    # block.  This catches wrong-person contamination without requiring the copy
    # to mention every intended person.
    first, last = expected_tokens[0], expected_tokens[-1]
    toks = _tokens(text)
    for i, tok in enumerate(toks[:-1]):
        if toks[i + 1] == last and tok != first and tok not in {"owner", "team"}:
            return True
    return False


def _company_mismatch(text: str, expected: str) -> bool:
    expected_key = _norm(expected)
    if len(expected_key) < 3:
        return False
    indicators = (" at ", " for ", " from ")
    low = f" {_norm(text)} "
    if expected_key in low:
        return False
    # If body explicitly says another capitalized company-like name after a
    # business preposition, treat as suspicious.  Require a business suffix/type
    # word so locations like "for Castle Rock" do not false-block.
    raw = f" {_clean(text)} "
    if not any(ind in raw.lower() for ind in indicators):
        return False
    match = re.search(r"\b[A-Z][A-Za-z&]+(?:\s+[A-Z][A-Za-z&]+){0,4}\s+(?:LLC|Inc|Company|Co|Group|Realty|Dental|Roofing|Agency|Compass)\b", raw)
    return bool(match)


def assess_copy_quality(*, prospect: Any, concept: Any, project: Any, row: Any) -> CopyQualityAssessment:
    headline = _clean(getattr(row, "headline", "") or getattr(concept, "headline", ""))
    cta = _clean(getattr(row, "cta", "") or getattr(concept, "cta", ""))
    subject = _clean(getattr(row, "email_subject", ""))
    body = _clean(getattr(row, "email_body", ""))
    combined = "\n".join(part for part in (headline, cta, subject, body) if part)
    source_texts = _source_texts(prospect, concept, project, row)

    blocking: list[CopyQualityReason] = []
    warnings: list[CopyQualityReason] = []

    if not headline:
        blocking.append(CopyQualityReason(MISSING_HEADLINE, "Generated billboard creative is missing a headline."))
    if row is not None and hasattr(row, "cta") and not cta:
        blocking.append(CopyQualityReason(MISSING_CTA, "Generated billboard creative is missing a CTA."))

    if len(headline) > 72:
        warnings.append(CopyQualityReason(HEADLINE_TOO_LONG, "Headline is unusually long for outreach creative.", headline[:120]))
    if len(headline.split()) > 9:
        warnings.append(CopyQualityReason(HEADLINE_TOO_MANY_WORDS, "Headline has too many words for billboard creative.", headline[:120]))
    if any(sep in headline for sep in _SEO_SEPARATORS):
        warnings.append(CopyQualityReason(SEO_TITLE_LIKE, "Headline resembles a source page title.", headline[:120]))
    headline_tokens = _tokens(headline)
    if headline and headline_tokens and headline_tokens[-1] in _DANGLING_ENDINGS:
        blocking.append(CopyQualityReason(TRUNCATED_PHRASE, "Generated copy appears truncated.", headline[:120]))
    if re.search(r"\b(join|get|claim)\b.+\bfree\s*$", headline, flags=re.I):
        blocking.append(CopyQualityReason(TRUNCATED_PHRASE, "Generated copy appears truncated.", headline[:120]))
    if _norm(headline) in {"work with what", "join today and get a free", "make your message unforgettable"}:
        warnings.append(CopyQualityReason(GENERIC_PLACEHOLDER_COPY, "Generated copy appears generic or malformed.", headline[:120]))
    if not headline and not subject and not body:
        blocking.append(CopyQualityReason(MALFORMED_COPY, "Generated copy is empty."))

    low = _norm(combined)
    for term in _SUPERLATIVE_TERMS:
        if _norm(term) in low and not _claim_supported(term, source_texts):
            blocking.append(CopyQualityReason(UNSUPPORTED_SUPERLATIVE, f"Unsupported superlative claim: \"{term}\".", term))

    for number in _numbers(combined):
        if not _claim_supported(number, source_texts):
            blocking.append(CopyQualityReason(UNSUPPORTED_NUMERIC_CLAIM, f"Unsupported numeric claim: \"{number.strip()}\".", number.strip()))

    if _name_mismatch(combined, getattr(prospect, "contact_name", "")):
        blocking.append(CopyQualityReason(PERSON_NAME_MISMATCH, "Generated copy appears to reference a different person."))
    if _company_mismatch(combined, getattr(prospect, "company_name", "")):
        blocking.append(CopyQualityReason(COMPANY_NAME_MISMATCH, "Generated copy appears to reference a different company."))

    if blocking:
        return CopyQualityAssessment(QUALITY_BLOCKED, tuple(blocking))
    if warnings:
        return CopyQualityAssessment(QUALITY_WARNING, tuple(warnings))
    return CopyQualityAssessment(QUALITY_PASS, ())


def assess_profile_quality(prospect: Any) -> CopyQualityAssessment:
    contact_name = _clean(getattr(prospect, "contact_name", ""))
    if len(contact_name.split()) < 2:
        return CopyQualityAssessment(QUALITY_PASS, ())
    has_manual = bool(_clean(getattr(prospect, "manual_profile_url", "")))
    status = _clean(getattr(prospect, "resolution_status", ""))
    confidence = _clean(getattr(prospect, "resolution_confidence", ""))
    resolved_url = _clean(getattr(prospect, "resolved_profile_url", ""))
    if has_manual or (status == RESOLUTION_RESOLVED and resolved_url and confidence in {CONFIDENCE_HIGH, CONFIDENCE_MEDIUM}):
        return CopyQualityAssessment(QUALITY_PASS, ())
    if status not in {RESOLUTION_NOT_FOUND, RESOLUTION_AMBIGUOUS, RESOLUTION_TIMEOUT, RESOLUTION_ERROR}:
        return CopyQualityAssessment(QUALITY_PASS, ())
    return CopyQualityAssessment(
        QUALITY_WARNING,
        (CopyQualityReason(PERSON_PROFILE_UNRESOLVED, "Individual profile not resolved."),),
    )