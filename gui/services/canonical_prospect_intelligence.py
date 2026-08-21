"""Source-agnostic canonical prospect intelligence helpers.

These helpers consume the existing Sprint 7A ``Prospect`` fields and produce
resolved creative values for downstream generation.  They do not perform I/O
and do not know about any particular import vendor.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from engine.content_safety import detect_challenge_content
from gui.models.prospect import Prospect, is_valid_phone, normalize_phone


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _field_provenance(prospect: Prospect, field_name: str) -> dict[str, Any]:
    meta = prospect.metadata if isinstance(prospect.metadata, dict) else {}
    provenance = meta.get("field_provenance") if isinstance(meta.get("field_provenance"), dict) else {}
    entry = provenance.get(field_name) if isinstance(provenance.get(field_name), dict) else {}
    return dict(entry)


def _source_for_field(prospect: Prospect, field_name: str, default: str = "PROSPECT") -> dict[str, str]:
    entry = _field_provenance(prospect, field_name)
    return {
        "origin": str(entry.get("origin") or default),
        "source_field": field_name,
        "source_column": str(entry.get("source_column") or ""),
    }


def preferred_display_company_name(prospect: Prospect) -> str:
    """Return the safe creative-facing company name without rewriting legal name."""
    meta = prospect.metadata if isinstance(prospect.metadata, dict) else {}
    return (
        _clean(prospect.company_name_for_ads)
        or _clean(meta.get("verified_brand_display_name"))
        or _clean(meta.get("normalized_source_company_name"))
        or _clean(prospect.company_name)
    )


def company_name_diagnostics(prospect: Prospect) -> dict[str, Any]:
    value = preferred_display_company_name(prospect)
    if _clean(prospect.company_name_for_ads):
        field = "company_name_for_ads"
        reason = "explicit canonical ad/display company name"
    elif _clean((prospect.metadata or {}).get("verified_brand_display_name") if isinstance(prospect.metadata, dict) else ""):
        field = "verified_brand_display_name"
        reason = "validated brand/display name from prospect metadata"
    elif _clean((prospect.metadata or {}).get("normalized_source_company_name") if isinstance(prospect.metadata, dict) else ""):
        field = "normalized_source_company_name"
        reason = "normalized imported/source company name"
    else:
        field = "company_name"
        reason = "legal/company name fallback"
    return {"value": value, "source_field": field, "reason": reason, **_source_for_field(prospect, field)}


def _usable_phone(value: Any) -> str:
    digits = normalize_phone(value)
    if not digits or not is_valid_phone(digits):
        return ""
    if len(set(digits[-7:])) <= 1:
        return ""
    if digits.endswith("0000000") or digits in {"1234567890", "0123456789", "1111111111"}:
        return ""
    return digits


def select_creative_phone(prospect: Prospect, website_phone: str = "") -> Dict[str, Any]:
    """Rank phones for creative use while preserving alternatives/provenance."""
    candidates = [
        ("company_phone", prospect.company_phone, 100, "company/corporate phone preferred for billboard creative", "IMPORTED"),
        ("website_phone", website_phone, 90, "validated first-party website business phone", "WEBSITE"),
        ("phone", prospect.phone if not prospect.mobile_phone or prospect.phone != prospect.mobile_phone else "", 80, "legacy business phone fallback", "PROSPECT"),
        ("work_direct_phone", prospect.work_direct_phone, 70, "work direct phone fallback when no company phone", "IMPORTED"),
        ("other_phone", prospect.other_phone, 60, "other safe business phone fallback", "IMPORTED"),
        ("mobile_phone", prospect.mobile_phone, 40, "mobile phone used only because no stronger business phone is available", "IMPORTED"),
    ]
    alternatives: List[dict[str, Any]] = []
    for field_name, raw, rank, reason, origin in candidates:
        phone = _usable_phone(raw)
        if not phone:
            continue
        source = _source_for_field(prospect, field_name, default=origin)
        item = {
            "phone": phone,
            "source_field": field_name,
            "rank": rank,
            "reason": reason,
            "origin": source.get("origin") or origin,
            "source_column": source.get("source_column", ""),
        }
        if phone not in {a["phone"] for a in alternatives}:
            alternatives.append(item)
    if alternatives:
        selected = sorted(alternatives, key=lambda x: (-int(x["rank"]), str(x["source_field"]))) [0]
        return {**selected, "alternatives": alternatives}
    return {"phone": "", "source_field": "", "rank": 0, "reason": "no usable phone supplied", "origin": "", "source_column": "", "alternatives": []}


_NAICS_LABELS = {
    "238160": "Roofing Contractors",
}


def _naics_label(codes: Iterable[str]) -> str:
    for code in codes:
        text = str(code or "").strip()
        if text in _NAICS_LABELS:
            return _NAICS_LABELS[text]
    return "NAICS " + ", ".join(str(c) for c in codes if str(c).strip())


def business_classification(prospect: Prospect, website_categories: Iterable[str] | None = None) -> Dict[str, Any]:
    """Classify business context using NAICS > keywords > industry > website > fallback."""
    if prospect.naics_codes:
        label = _naics_label(prospect.naics_codes)
        keywords = [_clean(k) for k in prospect.company_keywords if _clean(k)]
        return {"basis": "naics_codes", "value": list(prospect.naics_codes), "label": label, "keywords": keywords, "reason": "NAICS evidence outranks keywords, industry, and website evidence", **_source_for_field(prospect, "naics_codes", "IMPORTED")}
    if prospect.company_keywords:
        keywords = [_clean(k) for k in prospect.company_keywords if _clean(k)]
        label = ", ".join(keywords[:3])
        return {"basis": "company_keywords", "value": keywords, "label": label, "keywords": keywords, "reason": "company keywords outrank broad industry and website evidence", **_source_for_field(prospect, "company_keywords", "IMPORTED")}
    if _clean(prospect.industry):
        return {"basis": "industry", "value": prospect.industry, "label": prospect.industry, "keywords": [], "reason": "industry fallback used because no NAICS/keywords were supplied", **_source_for_field(prospect, "industry", "IMPORTED")}
    web = [_clean(c) for c in (website_categories or []) if _clean(c)]
    if web:
        return {"basis": "website", "value": web, "label": web[0], "keywords": [], "reason": "website classification used because stronger structured import evidence was absent", "origin": "WEBSITE", "source_field": "business_intel.categories", "source_column": ""}
    if _clean(prospect.category):
        return {"basis": "category", "value": prospect.category, "label": prospect.category, "keywords": [], "reason": "existing prospect category fallback", "origin": "PROSPECT", "source_field": "category", "source_column": ""}
    return {"basis": "generic_fallback", "value": "", "label": "", "keywords": [], "reason": "no classification evidence supplied", "origin": "FALLBACK", "source_field": "", "source_column": ""}


def location_context(prospect: Prospect) -> Dict[str, Any]:
    city = _clean(prospect.company_city or prospect.city)
    state = _clean(prospect.company_state or prospect.state)
    address = _clean(prospect.company_address or prospect.address)
    parts = [p for p in (city, state) if p]
    return {"address": address, "city": city, "state": state, "label": ", ".join(parts), "origin": "IMPORTED" if (address or city or state) else ""}


def has_generation_intelligence(prospect: Prospect) -> bool:
    if not preferred_display_company_name(prospect):
        return False
    classification = business_classification(prospect)
    location = location_context(prospect)
    phone = select_creative_phone(prospect)
    return bool(classification["label"] or phone["phone"] or location["city"] or location["state"])


def canonical_context(prospect: Prospect, *, website_phone: str = "", website_categories: Iterable[str] | None = None) -> Dict[str, Any]:
    phone = select_creative_phone(prospect, website_phone=website_phone)
    classification = business_classification(prospect, website_categories=website_categories)
    company = company_name_diagnostics(prospect)
    location = location_context(prospect)
    email_state = dict((prospect.metadata or {}).get("email_state") or {}) if isinstance(prospect.metadata, dict) else {}
    fields_used = [f for f in {company.get("source_field"), phone.get("source_field"), classification.get("source_field"), "location" if location.get("label") else ""} if f]
    return {
        "display_company_name": company["value"],
        "legal_company_name": prospect.company_name,
        "company_name": company,
        "selected_phone": phone,
        "classification": classification,
        "location": location,
        "contact": {
            "contact_name": prospect.contact_name,
            "contact_title": prospect.contact_title,
            "origin": "IMPORTED" if prospect.contact_name or prospect.contact_title else "",
            "resolution_status": prospect.resolution_status,
            "resolved_profile_url": prospect.resolved_profile_url,
            "manual_profile_url": prospect.manual_profile_url,
        },
        "email": prospect.email,
        "email_state": email_state or {"status": "email_present" if prospect.email else "email_missing", "email_enrichment_eligible": not bool(prospect.email)},
        "canonical_fields_used": sorted(fields_used),
    }


def canonical_scrape_fallback_data(prospect: Prospect) -> Dict[str, Any]:
    ctx = canonical_context(prospect)
    classification = ctx["classification"]
    services = [classification["label"]] if classification.get("label") else []
    services.extend(classification.get("keywords") or [])
    location = ctx["location"]
    metadata = {
        "canonical_prospect_intelligence": ctx,
        "website_enrichment_status": "not_attempted_no_website",
        "canonical_fallback_used": True,
        "canonical_fields_used": list(ctx["canonical_fields_used"]),
        "description": classification.get("label") or "",
    }
    return {
        "url": prospect.website or "",
        "company": ctx["display_company_name"],
        "headline": classification.get("label") or "",
        "ad_copy": classification.get("label") or "",
        "brand_colors": [],
        "metadata": metadata,
        "business_intel": {
            "phone": ctx["selected_phone"].get("phone", ""),
            "location": location.get("label", ""),
            "services": [s for s in services if s],
            "categories": [classification.get("label", "")] if classification.get("label") else [],
            "differentiators": [],
            "trust_signals": [],
            "awards": [],
            "certifications": [],
            "guarantees": [],
            "years_in_business": "",
        },
        "person_context": ctx["contact"],
    }


def merge_canonical_with_scrape(data: Dict[str, Any], canonical: Dict[str, Any]) -> Dict[str, Any]:
    """Merge canonical prospect evidence into scraper data without weakening safety."""
    merged = dict(data or {})
    meta = dict(merged.get("metadata") or {})
    website_phone = ""
    bi = merged.get("business_intel") if isinstance(merged.get("business_intel"), dict) else {}
    website_phone = _clean(bi.get("phone"))
    challenge = detect_challenge_content(merged.get("html"), merged.get("headline"), merged.get("ad_copy"), merged.get("company"), meta.get("title"), meta.get("description"))

    ctx = dict(canonical)
    display_name = _clean(ctx.get("display_company_name"))
    if display_name:
        if _clean(merged.get("company")) and display_name != _clean(merged.get("company")):
            meta.setdefault("canonical_conflicts", {})["company"] = {"scraped": _clean(merged.get("company")), "selected": display_name, "policy": "creative display name from canonical prospect intelligence wins; scraped alternative preserved"}
        merged["company"] = display_name

    classification = ctx.get("classification") if isinstance(ctx.get("classification"), dict) else {}
    selected_phone = ctx.get("selected_phone") if isinstance(ctx.get("selected_phone"), dict) else {}
    location = ctx.get("location") if isinstance(ctx.get("location"), dict) else {}
    business_intel = dict(bi)
    if selected_phone.get("phone"):
        business_intel["phone"] = selected_phone["phone"]
    if location.get("label") and not _clean(business_intel.get("location")):
        business_intel["location"] = location["label"]
    categories = list(business_intel.get("categories") or [])
    services = list(business_intel.get("services") or [])
    label = _clean(classification.get("label"))
    if label and label not in categories:
        categories.insert(0, label)
    for keyword in classification.get("keywords") or []:
        if keyword and keyword not in services:
            services.append(keyword)
    if label and label not in services:
        services.insert(0, label)
    business_intel["categories"] = categories
    business_intel["services"] = services
    merged["business_intel"] = business_intel

    if challenge.detected:
        meta["website_enrichment_status"] = "challenge_suppressed_canonical_fallback"
        meta["canonical_fallback_used"] = True
        meta["title"] = ""
        meta["description"] = label
        merged["headline"] = ""
        merged["ad_copy"] = ""
    else:
        meta.setdefault("website_enrichment_status", "enriched_with_canonical_intelligence")
        meta.setdefault("canonical_fallback_used", False)
    meta["canonical_prospect_intelligence"] = ctx
    meta["canonical_fields_used"] = list(ctx.get("canonical_fields_used") or [])
    merged["metadata"] = meta
    return merged