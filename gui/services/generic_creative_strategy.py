"""Deterministic creative strategy for the universal generic template.

This module is intentionally source-independent: it consumes canonical prospect
intelligence dictionaries and never reaches back into importer-specific fields,
live websites, broad search, or enrichment.  It provides the missing seam
between "generic fallback is eligible" and "generic fallback says something
credible for this specific business".
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


HOME_SERVICE = "HOME_SERVICE"
LOCAL_PROFESSIONAL = "LOCAL_PROFESSIONAL"
FOOD_RETAIL = "FOOD_RETAIL"
HEALTH_WELLNESS = "HEALTH_WELLNESS"
REAL_ESTATE = "REAL_ESTATE"
AUTOMOTIVE = "AUTOMOTIVE"
PERSONAL_SERVICE = "PERSONAL_SERVICE"
B2B_SERVICE = "B2B_SERVICE"
GENERAL_LOCAL_BUSINESS = "GENERAL_LOCAL_BUSINESS"

SERVICE_FORWARD = "SERVICE_FORWARD"
BRAND_FORWARD = "BRAND_FORWARD"
LOCAL_FORWARD = "LOCAL_FORWARD"
PRODUCT_FORWARD = "PRODUCT_FORWARD"

CALL = "CALL"
VISIT = "VISIT"
LEARN_MORE = "LEARN_MORE"
GET_STARTED = "GET_STARTED"
REQUEST_INFO = "REQUEST_INFO"

TYPOGRAPHY_FIRST = "TYPOGRAPHY_FIRST"
BRAND_COLOR_TYPOGRAPHY = "BRAND_COLOR_TYPOGRAPHY"
LOGO_SUPPORTED = "LOGO_SUPPORTED"
VISUAL_SUPPORTED = "VISUAL_SUPPORTED"

_UNSUPPORTED_CLAIM_PATTERNS = (
    r"#\s*1",
    r"\bbest\b",
    r"\bguaranteed\b",
    r"\bfree estimate\b",
    r"\blicensed\b",
    r"\binsured\b",
    r"\baward[ -]?winning\b",
    r"\byears? of experience\b",
    r"\bdiscount\b",
    r"\bsale\b",
)


@dataclass(frozen=True)
class GenericCreativeStrategy:
    business_display_name: str = ""
    business_classification: str = ""
    creative_intent: str = GENERAL_LOCAL_BUSINESS
    primary_service: str = ""
    secondary_service: str = ""
    location: str = ""
    location_used: bool = False
    safe_phone: str = ""
    headline: str = ""
    subtitle: str = ""
    cta: str = "Learn More"
    cta_theme: str = LEARN_MORE
    headline_theme: str = "classification"
    visual_family: str = BRAND_FORWARD
    brand_confidence: str = "weak"
    brand_fallback_mode: str = TYPOGRAPHY_FIRST
    classification_basis: str = ""
    classification_provenance: str = ""
    evidence_terms: tuple[str, ...] = field(default_factory=tuple)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence_terms"] = list(self.evidence_terms)
        return result


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9#]+", " ", str(value or "").lower()).strip()


def _title(value: str) -> str:
    small = {"and", "or", "of", "in", "for", "to", "with", "the"}
    words = []
    for i, word in enumerate(_clean(value).split()):
        low = word.lower()
        words.append(low if i and low in small else word[:1].upper() + word[1:].lower())
    return " ".join(words)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = _clean(item)
        key = _norm(text)
        if text and key and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _city_from_location(location: dict[str, Any]) -> str:
    city = _clean(location.get("city"))
    if city:
        return city
    label = _clean(location.get("label"))
    if "," in label:
        return _clean(label.split(",", 1)[0])
    return label


def _classification_terms(classification: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in ("keywords", "value"):
        raw = classification.get(key)
        if isinstance(raw, (list, tuple)):
            terms.extend(_clean(v) for v in raw)
        elif raw and key != "value":
            terms.append(_clean(raw))
    label = _clean(classification.get("label"))
    if label:
        terms.insert(0, label)
    return _dedupe([t for t in terms if not re.fullmatch(r"\d{2,6}", _clean(t))])


_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (REAL_ESTATE, ("real estate", "realtor", "broker", "property", "leasing")),
    (HEALTH_WELLNESS, ("dent", "clinic", "medical", "health", "wellness", "therapy", "chiropr", "doctor")),
    (FOOD_RETAIL, ("bakery", "cake", "cakes", "baked", "restaurant", "coffee", "cafe", "food", "catering", "donut", "bread")),
    (B2B_SERVICE, ("media", "marketing", "consulting", "logistics", "software", "accounting", "legal", "outdoor advertising", "billboard", "advertising")),
    (AUTOMOTIVE, ("auto", "automotive", "car", "truck", "tire", "collision", "mechanic", "repair shop")),
    (HOME_SERVICE, ("landscap", "lawn", "tree", "garden", "solar", "roof", "plumb", "hvac", "paint", "moving", "movers", "packing", "relocation", "cleaning", "electric", "contractor", "repair", "installation")),
    (PERSONAL_SERVICE, ("salon", "spa", "barber", "fitness", "personal", "beauty")),
    (LOCAL_PROFESSIONAL, ("law", "attorney", "insurance", "financial", "tax", "accountant", "advisor")),
)


def _keyword_matches(norm_text: str, keyword: str) -> bool:
    key = _norm(keyword)
    if not key:
        return False
    if " " in key:
        return key in norm_text
    if len(key) <= 4:
        return bool(re.search(rf"\b{re.escape(key)}\b", norm_text))
    return key in norm_text


def _creative_intent(corpus: str) -> str:
    low = _norm(corpus)
    for intent, keywords in _INTENT_KEYWORDS:
        if any(_keyword_matches(low, keyword) for keyword in keywords):
            return intent
    return GENERAL_LOCAL_BUSINESS


def _primary_service(terms: list[str], classification_label: str, company: str) -> tuple[str, str]:
    company_norm = _norm(company)
    meaningful = []
    for term in terms:
        norm = _norm(term)
        if not norm or norm == company_norm:
            continue
        meaningful.append(term)
    if meaningful:
        return meaningful[0], meaningful[1] if len(meaningful) > 1 else ""
    return _clean(classification_label), ""


def _headline_for(intent: str, primary: str, company: str, city: str) -> tuple[str, str, bool]:
    service = _title(primary)
    city_title = _title(city)
    low = _norm(primary + " " + company)
    if "landscap" in low or "lawn" in low or "garden" in low:
        return (f"{service} That Fit Your Property" if service else "Outdoor Services That Fit Your Property", "service_specific", False)
    if "solar" in low:
        return (f"{service} For Your Home" if service else "Solar Energy For Your Home", "service_specific", False)
    if any(k in low for k in ("bakery", "cake", "baked", "bread")):
        return (f"Fresh {service}" if service and not service.lower().startswith("fresh") else "Made Fresh Here", "product_specific", False)
    if any(k in low for k in ("moving", "movers", "packing", "relocation")):
        return (f"{service} Made Simpler" if service else "Moving Made Simpler", "service_specific", False)
    if any(k in low for k in ("media", "advertising", "outdoor")):
        return (f"{service} That Gets Seen" if service else "Local Advertising That Gets Seen", "b2b_specific", False)
    if intent == FOOD_RETAIL:
        return (f"{service} Made Here" if service else "Made Fresh Here", "product_specific", False)
    if intent == HOME_SERVICE:
        return (f"{service} Help When You Need It" if service else "Local Service Help When You Need It", "service_specific", False)
    if intent == B2B_SERVICE:
        return (f"{service} For Local Businesses" if service else "Support For Local Businesses", "b2b_specific", False)
    if city_title and service and len(f"{city_title} {service}") <= 42:
        return f"{city_title} {service}", "local_classification", True
    if service:
        return f"{service} From {company}" if len(f"{service} From {company}") <= 48 else service, "classification", False
    return company, "restrained_company", False


def _subtitle(primary: str, secondary: str, city: str, location_used_in_headline: bool) -> str:
    bits = []
    if secondary and _norm(secondary) != _norm(primary):
        bits.append(_title(secondary))
    if city and not location_used_in_headline:
        bits.append(f"In {_title(city)}")
    return " • ".join(bits[:2])


def _cta(selected_phone: dict[str, Any], website: str, intent: str) -> tuple[str, str]:
    phone = _clean(selected_phone.get("phone"))
    if phone:
        return f"Call {phone}", CALL
    if website:
        if intent == FOOD_RETAIL:
            return "Visit Us", VISIT
        return "Learn More", LEARN_MORE
    if intent in {B2B_SERVICE, LOCAL_PROFESSIONAL}:
        return "Request Info", REQUEST_INFO
    return "Get Started", GET_STARTED


def _visual_family(intent: str, has_location: bool, primary: str, brand_confidence: str) -> str:
    low = _norm(primary)
    if intent == FOOD_RETAIL:
        return PRODUCT_FORWARD
    if has_location and intent in {GENERAL_LOCAL_BUSINESS, LOCAL_PROFESSIONAL}:
        return LOCAL_FORWARD
    if primary and intent in {HOME_SERVICE, B2B_SERVICE, AUTOMOTIVE, HEALTH_WELLNESS, PERSONAL_SERVICE}:
        return SERVICE_FORWARD
    return BRAND_FORWARD if brand_confidence != "weak" else SERVICE_FORWARD


def _claim_safe(*parts: str) -> bool:
    text = " ".join(parts)
    return not any(re.search(pattern, text, flags=re.I) for pattern in _UNSUPPORTED_CLAIM_PATTERNS)


def derive_generic_creative_strategy(
    canonical: dict[str, Any] | None,
    *,
    website: str = "",
    brand_colors: list[str] | None = None,
    has_logo: bool = False,
    has_visual_asset: bool = False,
) -> GenericCreativeStrategy:
    ctx = canonical if isinstance(canonical, dict) else {}
    classification = ctx.get("classification") if isinstance(ctx.get("classification"), dict) else {}
    selected_phone = ctx.get("selected_phone") if isinstance(ctx.get("selected_phone"), dict) else {}
    location = ctx.get("location") if isinstance(ctx.get("location"), dict) else {}
    company = _clean(ctx.get("display_company_name") or ctx.get("legal_company_name"))
    label = _clean(classification.get("label"))
    terms = _classification_terms(classification)
    city = _city_from_location(location)
    primary, secondary = _primary_service(terms, label, company)
    corpus = " ".join([company, label, primary, secondary, " ".join(terms)])
    intent = _creative_intent(corpus)
    brand_confidence = "strong" if has_logo else ("medium" if brand_colors else "weak")
    headline, headline_theme, location_used = _headline_for(intent, primary, company, city)
    sub = _subtitle(primary, secondary, city, location_used)
    cta, cta_theme = _cta(selected_phone, website, intent)
    if not _claim_safe(headline, sub, cta):
        headline = _title(primary or label) or company
        sub = f"In {_title(city)}" if city else ""
        cta, cta_theme = (f"Call {_clean(selected_phone.get('phone'))}", CALL) if _clean(selected_phone.get("phone")) else ("Learn More", LEARN_MORE)
    visual = _visual_family(intent, bool(city), primary, brand_confidence)
    fallback = VISUAL_SUPPORTED if has_visual_asset else (LOGO_SUPPORTED if has_logo else (BRAND_COLOR_TYPOGRAPHY if brand_colors else TYPOGRAPHY_FIRST))
    diagnostics = {
        "creative_intent": intent,
        "classification_basis": _clean(classification.get("basis")),
        "classification_label": label,
        "classification_source_field": _clean(classification.get("source_field")),
        "primary_service_source": "classification_or_keywords" if primary else "none",
        "cta_source": "selected_phone" if selected_phone.get("phone") else ("website" if website else "safe_default"),
        "location_source": "canonical_location" if city else "none",
        "unsupported_claims_filtered": True,
        "source_independent": True,
    }
    return GenericCreativeStrategy(
        business_display_name=company,
        business_classification=label,
        creative_intent=intent,
        primary_service=primary,
        secondary_service=secondary,
        location=city,
        location_used=location_used,
        safe_phone=_clean(selected_phone.get("phone")),
        headline=headline,
        subtitle=sub,
        cta=cta,
        cta_theme=cta_theme,
        headline_theme=headline_theme,
        visual_family=visual,
        brand_confidence=brand_confidence,
        brand_fallback_mode=fallback,
        classification_basis=_clean(classification.get("basis")),
        classification_provenance=_clean(classification.get("source_field")),
        evidence_terms=tuple(terms),
        diagnostics=diagnostics,
    )
