"""Deterministic person-aware personalization for billboard copy.

This module keeps three layers separate:

* source facts: compact, evidence-backed facts extracted from a person profile
* derived personalization: a safe advertising angle chosen from those facts
* generated copy: concise billboard headline / CTA wording

No LLM calls, no live network, and no unsupported superlatives.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field as dataclass_field
import re
from typing import Any, Dict, Iterable, List, Optional

from bs4 import BeautifulSoup


EXPERIENCE = "EXPERIENCE"
LOCAL_EXPERTISE = "LOCAL_EXPERTISE"
SPECIALTY = "SPECIALTY"
SERVICE = "SERVICE"
LEADERSHIP_ROLE = "LEADERSHIP_ROLE"
DISTINCTIVE_TAGLINE = "DISTINCTIVE_TAGLINE"
CUSTOMER_SUPPORT = "CUSTOMER_SUPPORT"
PROPERTY_TYPE_EXPERTISE = "PROPERTY_TYPE_EXPERTISE"
GENERIC_PERSON_BRAND = "GENERIC_PERSON_BRAND"

MAX_HEADLINE_CHARS = 42
MAX_HEADLINE_WORDS = 7
MAX_CTA_CHARS = 18

UNRESOLVED_PERSON_STATUSES = {"AMBIGUOUS", "NOT_FOUND", "ERROR", "TIMEOUT"}


@dataclass
class PersonFact:
    field: str = ""
    value: Any = ""
    evidence: List[str] = dataclass_field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"field": self.field, "value": self.value, "evidence": list(self.evidence)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "PersonFact":
        if not isinstance(data, dict):
            return cls()
        ev = data.get("evidence")
        return cls(
            field=str(data.get("field") or ""),
            value=data.get("value") or "",
            evidence=[str(e) for e in ev] if isinstance(ev, list) else [],
        )


@dataclass
class PersonFacts:
    contact_name: str = ""
    professional_title: str = ""
    company_name: str = ""
    location: str = ""
    service_area: str = ""
    years_experience: str = ""
    specialties: List[str] = dataclass_field(default_factory=list)
    services: List[str] = dataclass_field(default_factory=list)
    credentials: List[str] = dataclass_field(default_factory=list)
    awards_or_roles: List[str] = dataclass_field(default_factory=list)
    bio_summary: str = ""
    phone: str = ""
    email: str = ""
    profile_url: str = ""
    person_tagline: str = ""
    other_supported_facts: List[str] = dataclass_field(default_factory=list)
    provenance: Dict[str, List[str]] = dataclass_field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "PersonFacts":
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered: Dict[str, Any] = {k: data.get(k) for k in known if k in data}
        for key in ("specialties", "services", "credentials", "awards_or_roles", "other_supported_facts"):
            val = filtered.get(key)
            filtered[key] = [str(v) for v in val] if isinstance(val, list) else []
        prov = filtered.get("provenance")
        if isinstance(prov, dict):
            filtered["provenance"] = {
                str(k): [str(v) for v in vals] if isinstance(vals, list) else [str(vals)]
                for k, vals in prov.items()
            }
        else:
            filtered["provenance"] = {}
        return cls(**filtered)

    def has_person_context(self) -> bool:
        return bool((self.contact_name or "").strip())


@dataclass
class PersonalizationResult:
    person_facts: PersonFacts = dataclass_field(default_factory=PersonFacts)
    personalization_angle: str = ""
    personalization_basis: List[str] = dataclass_field(default_factory=list)
    headline: str = ""
    cta: str = ""
    profile_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "person_facts": self.person_facts.to_dict(),
            "personalization_angle": self.personalization_angle,
            "personalization_basis": list(self.personalization_basis),
            "headline": self.headline,
            "cta": self.cta,
            "profile_summary": self.profile_summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "PersonalizationResult":
        if not isinstance(data, dict):
            return cls()
        return cls(
            person_facts=PersonFacts.from_dict(data.get("person_facts")),
            personalization_angle=str(data.get("personalization_angle") or ""),
            personalization_basis=[str(v) for v in data.get("personalization_basis") or []],
            headline=str(data.get("headline") or ""),
            cta=str(data.get("cta") or ""),
            profile_summary=str(data.get("profile_summary") or ""),
        )


_SEO_SEPARATORS = (" | ", " - ", " – ", " — ", " :: ")
_REAL_ESTATE_WORDS = ("realtor", "real estate", "broker", "agent", "listing", "buyers", "sellers", "homes")
_SPECIALTY_PHRASES = (
    "relocation", "new construction", "historic homes", "historical homes",
    "commercial", "land", "condos", "cooperatives", "foreclosures", "short sales",
    "staging", "professional photography", "luxury homes", "first-time buyers",
)
_SERVICE_PHRASES = (
    "staging guidance", "staging assistance", "professional photography",
    "home valuation", "buyer representation", "seller representation",
)
_ROLE_MARKERS = ("top sales leader", "team leader", "broker owner", "managing broker", "principal")
_UNSUPPORTED_SUPERLATIVES = ("#1", "best", "top producer", "market leader")


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _compact_evidence(label: str, text: Any, limit: int = 140) -> str:
    val = _clean(text)
    if len(val) > limit:
        val = val[: limit - 1].rsplit(" ", 1)[0] + "…"
    return f"{label}: {val}" if val else label


def _append_unique(items: List[str], value: str) -> None:
    v = _clean(value)
    if v and v.lower() not in {i.lower() for i in items}:
        items.append(v)


def _sentences(text: str) -> List[str]:
    return [_clean(s) for s in re.split(r"(?<=[.!?])\s+", text or "") if _clean(s)]


def _visible_profile_text(soup: Optional[BeautifulSoup]) -> str:
    if soup is None:
        return ""
    for tag in soup.find_all(["nav", "footer", "script", "style", "noscript"]):
        tag.decompose()
    return _clean(soup.get_text(" ", strip=True))


def _jsonld_items(soup: Optional[BeautifulSoup]) -> List[Dict[str, Any]]:
    if soup is None:
        return []
    import json

    out: List[Dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            raw = json.loads(script.string or "")
        except Exception:
            continue
        if isinstance(raw, dict):
            out.append(raw)
            graph = raw.get("@graph")
            if isinstance(graph, list):
                out.extend([g for g in graph if isinstance(g, dict)])
        elif isinstance(raw, list):
            out.extend([g for g in raw if isinstance(g, dict)])
    return out


def _is_person_jsonld(item: Dict[str, Any]) -> bool:
    typ = item.get("@type")
    if isinstance(typ, list):
        vals = [str(t).lower() for t in typ]
    else:
        vals = [str(typ or "").lower()]
    return "person" in vals or "realestateagent" in vals


def _first_name(name: str) -> str:
    return (_clean(name).split() or [""])[0]


def _strip_seo_title(text: str, company: str = "", name: str = "") -> str:
    candidate = _clean(text)
    for sep in _SEO_SEPARATORS:
        if sep in candidate:
            parts = [_clean(p) for p in candidate.split(sep) if _clean(p)]
            candidate = parts[0] if parts else candidate
            break
    for phrase in (company, name):
        p = _clean(phrase)
        if p:
            candidate = re.sub(re.escape(p), "", candidate, flags=re.I)
    candidate = re.sub(r"[,|\-–—]+", " ", candidate)
    return _clean(candidate)


def _headline_ok(text: str) -> bool:
    t = _clean(text)
    return bool(t) and len(t) <= MAX_HEADLINE_CHARS and len(t.split()) <= MAX_HEADLINE_WORDS


def _choose_short(options: Iterable[str]) -> str:
    for option in options:
        t = _clean(option)
        if _headline_ok(t):
            return t
    for option in options:
        words = _clean(option).split()
        if words:
            candidate = " ".join(words[:MAX_HEADLINE_WORDS])
            if len(candidate) <= MAX_HEADLINE_CHARS:
                return candidate
    return ""


def _extract_years(text: str) -> str:
    patterns = [
        r"\b(\d{1,2})\s*\+?\s+years?\s+(?:of\s+)?(?:experience|in\s+the\s+business|helping|serving)",
        r"\b(?:over|more than)\s+(\d{1,2})\s+years?\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.I)
        if m:
            return m.group(1)
    return ""


def _extract_tagline(soup: Optional[BeautifulSoup], text: str, name: str) -> str:
    if soup is not None:
        for tag in soup.find_all(["h1", "h2", "h3", "strong", "blockquote"]):
            val = _clean(tag.get_text(" ", strip=True)).strip('"“”')
            if not val or val.lower() == name.lower():
                continue
            if 3 <= len(val.split()) <= 7 and len(val) <= MAX_HEADLINE_CHARS:
                if val.isupper() or "!" in val:
                    return val.title().replace("!", "")
    for m in re.finditer(r"[\"“]([^\"”]{8,42})[\"”]", text):
        val = _clean(m.group(1)).strip("!")
        if 2 <= len(val.split()) <= 7:
            return val.title()
    return ""


def _looks_person_context(data: Dict[str, Any], soup: Optional[BeautifulSoup], name: str) -> bool:
    if name:
        title = _clean((data.get("metadata") or {}).get("title") or "")
        h1 = " ".join(_clean(h.get_text(" ", strip=True)) for h in (soup.find_all("h1") if soup else []))
        return name.lower() in f"{title} {h1}".lower() or bool(data.get("person_context"))
    return False


def extract_person_facts(data: Dict[str, Any]) -> PersonFacts:
    """Extract compact, evidence-backed person facts from scraper data."""
    data = data if isinstance(data, dict) else {}
    html = str(data.get("html") or "")
    soup = BeautifulSoup(html, "lxml") if html else None
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    person_context = data.get("person_context") if isinstance(data.get("person_context"), dict) else {}
    resolution_status = _clean(person_context.get("resolution_status") or "")
    intended_person = bool(_clean(person_context.get("contact_name") or ""))
    unresolved_person = intended_person and resolution_status in UNRESOLVED_PERSON_STATUSES

    facts = PersonFacts(
        contact_name="" if unresolved_person else _clean(person_context.get("contact_name") or ""),
        professional_title="" if unresolved_person else _clean(person_context.get("contact_title") or person_context.get("title") or ""),
        company_name=_clean(data.get("company") or person_context.get("company_name") or ""),
        profile_url="" if unresolved_person else _clean(person_context.get("resolved_profile_url") or person_context.get("manual_profile_url") or data.get("url") or ""),
    )
    prov: Dict[str, List[str]] = {}

    def add(field_name: str, value: Any, evidence: str) -> None:
        if not value:
            return
        prov.setdefault(field_name, [])
        if evidence and evidence not in prov[field_name]:
            prov[field_name].append(evidence)

    if unresolved_person:
        facts.provenance = {
            "unresolved_person_fallback": [
                f"intended person identity unresolved: {resolution_status}",
                "person-specific extraction suppressed for parent-site fallback",
            ]
        }
        return facts

    if facts.contact_name:
        add("contact_name", facts.contact_name, _compact_evidence("prospect person context", facts.contact_name))
    if facts.profile_url:
        add("profile_url", facts.profile_url, _compact_evidence("resolved profile URL", facts.profile_url))

    for item in _jsonld_items(soup):
        if not _is_person_jsonld(item):
            continue
        if not facts.contact_name and item.get("name"):
            facts.contact_name = _clean(item.get("name")); add("contact_name", facts.contact_name, _compact_evidence("structured Person JSON-LD", item.get("name")))
        if not facts.professional_title and item.get("jobTitle"):
            facts.professional_title = _clean(item.get("jobTitle")); add("professional_title", facts.professional_title, _compact_evidence("structured Person JSON-LD", item.get("jobTitle")))
        if not facts.phone and item.get("telephone"):
            facts.phone = _clean(item.get("telephone")); add("phone", facts.phone, "structured Person JSON-LD telephone")
        if not facts.email and item.get("email"):
            facts.email = _clean(item.get("email")); add("email", facts.email, "structured Person JSON-LD email")
        works = item.get("worksFor")
        if not facts.company_name and isinstance(works, dict) and works.get("name"):
            facts.company_name = _clean(works.get("name")); add("company_name", facts.company_name, _compact_evidence("structured Person JSON-LD worksFor", works.get("name")))

    title_text = _clean(metadata.get("title") or (soup.title.string if soup and soup.title and soup.title.string else ""))
    if not facts.contact_name and title_text:
        first = _strip_seo_title(title_text, facts.company_name, "")
        if 2 <= len(first.split()) <= 4 and not any(w in first.lower() for w in ("home", "real estate", "properties")):
            facts.contact_name = first
            add("contact_name", first, _compact_evidence("page title", title_text))

    if facts.contact_name:
        add("contact_name", facts.contact_name, _compact_evidence("person context", facts.contact_name))
    if facts.professional_title:
        add("professional_title", facts.professional_title, _compact_evidence("person context", facts.professional_title))
    if facts.profile_url:
        add("profile_url", facts.profile_url, _compact_evidence("scrape URL", facts.profile_url))

    if not _looks_person_context(data, soup, facts.contact_name):
        facts.provenance = prov
        return facts

    body = _visible_profile_text(soup)
    headings = " ".join(_clean(h.get_text(" ", strip=True)) for h in (soup.find_all(["h1", "h2", "h3"]) if soup else []))
    text = _clean(" ".join([title_text, headings, body, str(metadata.get("description") or "")]))

    years = _extract_years(text)
    if years:
        facts.years_experience = years
        add("years_experience", years, _compact_evidence("bio text", re.search(r".{0,35}" + re.escape(years) + r".{0,60}", text).group(0) if re.search(r".{0,35}" + re.escape(years) + r".{0,60}", text) else f"{years} years"))

    for phrase in _SPECIALTY_PHRASES:
        if re.search(r"\b" + re.escape(phrase) + r"\b", text, flags=re.I):
            target = facts.specialties
            if phrase in ("staging", "professional photography"):
                target = facts.services
            _append_unique(target, phrase)
            add("specialties" if target is facts.specialties else "services", phrase, _compact_evidence("bio/profile body", phrase))

    for phrase in _SERVICE_PHRASES:
        if re.search(r"\b" + re.escape(phrase) + r"\b", text, flags=re.I):
            _append_unique(facts.services, phrase)
            add("services", phrase, _compact_evidence("explicit service text", phrase))

    for marker in _ROLE_MARKERS:
        if marker in text.lower():
            _append_unique(facts.awards_or_roles, marker.title())
            add("awards_or_roles", marker.title(), _compact_evidence("title/bio role text", marker))

    facts.person_tagline = _extract_tagline(soup, text, facts.contact_name)
    if facts.person_tagline:
        add("person_tagline", facts.person_tagline, _compact_evidence("profile heading/tagline", facts.person_tagline))

    if not facts.location:
        m = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}),\s*([A-Z]{2})\b", text)
        if m:
            facts.location = f"{m.group(1)}, {m.group(2)}"
            add("location", facts.location, _compact_evidence("profile body", facts.location))

    for sent in _sentences(body):
        if facts.contact_name and facts.contact_name.split()[0].lower() in sent.lower():
            continue
        if any(k in sent.lower() for k in ("helping", "experience", "provides", "specializes", "serving")) and len(sent) <= 180:
            facts.bio_summary = sent
            add("bio_summary", sent, _compact_evidence("bio text", sent))
            break

    # Do not promote unsupported generic page superlatives into facts.
    facts.specialties = [s for s in facts.specialties if s.lower() not in _UNSUPPORTED_SUPERLATIVES]
    facts.provenance = prov
    return facts


def _business_kind(facts: PersonFacts, categories: Iterable[str] = ()) -> str:
    text = " ".join([facts.professional_title, facts.bio_summary, *facts.specialties, *facts.services, *categories]).lower()
    if any(w in text for w in _REAL_ESTATE_WORDS):
        return "real_estate"
    return "professional"


def _basis(facts: PersonFacts, field_name: str) -> List[str]:
    vals = facts.provenance.get(field_name) or []
    return vals[:2]


def choose_personalization(data: Dict[str, Any], categories: Iterable[str] = ()) -> PersonalizationResult:
    facts = extract_person_facts(data)
    if not facts.has_person_context():
        return PersonalizationResult(person_facts=facts)

    kind = _business_kind(facts, categories)
    first = _first_name(facts.contact_name)

    angle = GENERIC_PERSON_BRAND
    basis = _basis(facts, "contact_name")
    headline = ""

    if facts.years_experience:
        angle = EXPERIENCE
        basis = _basis(facts, "years_experience")
        if kind == "real_estate":
            headline = _choose_short([
                f"{facts.years_experience} Years Helping Buyers Move",
                f"{facts.years_experience} Years Helping Clients Move",
                f"{facts.years_experience} Years of Real Estate Experience",
            ])
        else:
            headline = _choose_short([f"{facts.years_experience} Years of Experience", "Experience You Can Trust"])
    elif facts.person_tagline:
        angle = DISTINCTIVE_TAGLINE
        basis = _basis(facts, "person_tagline")
        tagline = facts.person_tagline.strip(".! ")
        if tagline.lower().startswith("sparkle"):
            headline = _choose_short(["Make Your Next Move Sparkle", tagline])
        else:
            headline = _choose_short([tagline])
    elif facts.specialties:
        angle = PROPERTY_TYPE_EXPERTISE if any(s in facts.specialties for s in ("new construction", "historical homes", "historic homes", "commercial", "land", "condos", "cooperatives")) else SPECIALTY
        basis = _basis(facts, "specialties")
        specialty = facts.specialties[0].title()
        headline = _choose_short([f"Your {specialty} Guide", f"{specialty} Expertise"])
    elif facts.services:
        angle = SERVICE
        basis = _basis(facts, "services")
        svc = facts.services[0].title()
        headline = _choose_short([f"{svc} That Helps You Move", f"Guidance For Your Next Move"])
    elif facts.awards_or_roles:
        angle = LEADERSHIP_ROLE
        basis = _basis(facts, "awards_or_roles")
        headline = _choose_short(["Leadership That Moves You", f"Work With {first}"])

    if not headline:
        headline = _choose_short([f"Work With {first}", f"Meet {facts.contact_name}", "Your Local Professional"])

    cta = select_person_cta(facts, angle, kind)
    return PersonalizationResult(
        person_facts=facts,
        personalization_angle=angle,
        personalization_basis=basis,
        headline=headline,
        cta=cta,
        profile_summary=facts.bio_summary,
    )


def select_person_cta(facts: PersonFacts, angle: str, kind: str = "professional") -> str:
    first = _first_name(facts.contact_name)
    if facts.phone and first and len(f"Call {first}") <= MAX_CTA_CHARS:
        return f"Call {first}"
    if first and angle in {EXPERIENCE, SERVICE, SPECIALTY, PROPERTY_TYPE_EXPERTISE, DISTINCTIVE_TAGLINE}:
        return f"Contact {first}" if len(f"Contact {first}") <= MAX_CTA_CHARS else "Let's Talk"
    if kind == "real_estate" and (facts.specialties or facts.services):
        return "Find Your Home"
    return "Let's Talk" if first else "Learn More"


def personalize_scrape_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return data with structured person personalization fields when supported."""
    out = dict(data or {})
    bi = out.get("business_intel") if isinstance(out.get("business_intel"), dict) else {}
    result = choose_personalization(out, categories=bi.get("categories") or [])
    if result.person_facts.provenance.get("unresolved_person_fallback"):
        out.setdefault("generation_diagnostics", {})
        if isinstance(out["generation_diagnostics"], dict):
            out["generation_diagnostics"].update({
                "intended_person_unresolved": True,
                "person_specific_creative_suppressed": True,
            })
    if result.person_facts.has_person_context():
        payload = result.to_dict()
        out["person_facts"] = payload["person_facts"]
        out["personalization_angle"] = payload["personalization_angle"]
        out["personalization_basis"] = payload["personalization_basis"]
        out["personalized_headline"] = payload["headline"]
        out["personalized_cta"] = payload["cta"]
        out["profile_summary"] = payload["profile_summary"]
        out["personalization"] = payload
    return out
