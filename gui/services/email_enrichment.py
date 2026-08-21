"""Conditional first-party email enrichment for prospects (Sprint 7C).

This module is Qt-free and deterministic when supplied with HTML/fake fetchers.
It never guesses addresses: every candidate must appear in supplied or fetched
first-party source material.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from engine.content_safety import detect_challenge_content
from gui.models.prospect import Prospect, is_valid_email, normalize_domain, normalize_email


EMAIL_ORIGIN_ENRICHED = "ENRICHED"
STATUS_FOUND = "FOUND"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_SKIPPED_EXISTING = "SKIPPED_EXISTING"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_BLOCKED_CONTENT = "BLOCKED_CONTENT"
STATUS_ERROR = "ERROR"
REASON_EXISTING_EMAIL_PRESENT = "EXISTING_EMAIL_PRESENT"
REASON_MISSING_EMAIL = "MISSING_EMAIL"
REASON_NO_WEBSITE = "NO_WEBSITE"

TYPE_PERSON = "PERSON"
TYPE_BUSINESS_GENERAL = "BUSINESS_GENERAL"
TYPE_SALES = "SALES"
TYPE_INFO = "INFO"
TYPE_SUPPORT = "SUPPORT"
TYPE_UNKNOWN = "UNKNOWN"

SOURCE_HOMEPAGE = "HOMEPAGE"
SOURCE_CONTACT = "CONTACT_PAGE"
SOURCE_ABOUT = "ABOUT_PAGE"
SOURCE_PROFILE = "PROFILE_PAGE"
SOURCE_SCRAPE = "SCRAPE_RESULT"

FREE_MAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "yahoo.com",
    "icloud.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
}
PLACEHOLDER_LOCALS = {"example", "user", "username", "name", "email", "test", "no-reply", "noreply", "null"}
GENERIC_LOCALS = {"contact", "office", "hello", "admin", "service", "team", "business"}
INFO_LOCALS = {"info", "inquiries", "enquiries"}
SALES_LOCALS = {"sales", "estimate", "estimates", "quotes", "quote"}
SUPPORT_LOCALS = {"support", "help", "customerservice", "customer-service", "service"}
REJECTED_DOMAINS = {"example.com", "example.org", "example.net", "localhost", "test.com", "invalid.com"}
_EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})(?![\w-])", re.I)
_TRAILING = " .,!?:;)]}>\"'"


@dataclass(frozen=True)
class EmailSource:
    url: str
    html: str
    source_type: str


@dataclass(frozen=True)
class EmailCandidate:
    email: str
    source_url: str
    source_type: str
    email_type: str
    relevance: str
    confidence: str
    selection_reason: str
    rank: int
    association: str = "COMPANY"
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "email_type": self.email_type,
            "relevance": self.relevance,
            "confidence": self.confidence,
            "selection_reason": self.selection_reason,
            "rank": self.rank,
            "association": self.association,
            "evidence": self.evidence[:180],
        }


@dataclass(frozen=True)
class EmailEnrichmentResult:
    status: str
    attempted: bool
    reason: str
    selected: EmailCandidate | None = None
    alternatives: list[EmailCandidate] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


Fetcher = Callable[[str], Any]


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except ValueError:
        return ""


def _same_domain(url: str, domain: str) -> bool:
    host = _host(url)
    domain = str(domain or "").lower().lstrip("www.")
    return bool(host and domain and (host == domain or host.endswith("." + domain)))


def _normalize_mailto(value: str) -> str:
    text = html_lib.unescape(str(value or "")).strip()
    if text.lower().startswith("mailto:"):
        text = text[7:]
    text = text.split("?", 1)[0].split("#", 1)[0]
    return normalize_email(unquote(text).strip(_TRAILING))


def _candidate_email(value: str) -> str:
    return normalize_email(html_lib.unescape(str(value or "")).strip(_TRAILING))


def _valid_candidate_email(email: str) -> tuple[bool, str]:
    if not is_valid_email(email):
        return False, "malformed"
    local, domain = email.rsplit("@", 1)
    if not local or not domain or domain in REJECTED_DOMAINS or domain.endswith(".local") or domain.endswith(".test"):
        return False, "placeholder_or_test_domain"
    if local.lower() in PLACEHOLDER_LOCALS or "example" in local.lower() or "your" in local.lower():
        return False, "placeholder_local_part"
    if re.search(r"\.(png|jpe?g|gif|svg|webp|css|js)$", email, re.I):
        return False, "asset_filename"
    if any(ch in email for ch in "<>{}[]()\\/"):
        return False, "script_or_markup_fragment"
    return True, ""


def _classify(email: str, contact_name: str, evidence: str, source_type: str) -> tuple[str, str]:
    local = email.split("@", 1)[0].lower()
    compact_local = re.sub(r"[^a-z0-9]", "", local)
    names = [p.lower() for p in re.findall(r"[A-Za-z]+", contact_name or "") if len(p) > 1]
    evidence_l = evidence.lower()
    if local in INFO_LOCALS:
        return TYPE_INFO, "COMPANY"
    if local in SALES_LOCALS:
        return TYPE_SALES, "COMPANY"
    if local in SUPPORT_LOCALS:
        return TYPE_SUPPORT, "COMPANY"
    if local in GENERIC_LOCALS:
        return TYPE_BUSINESS_GENERAL, "COMPANY"
    if names and any(name in compact_local for name in names) and (source_type == SOURCE_PROFILE or any(name in evidence_l for name in names)):
        return TYPE_PERSON, "PERSON"
    return TYPE_UNKNOWN, "COMPANY"


def _business_tokens(prospect: Prospect) -> set[str]:
    text = " ".join([prospect.company_name, prospect.company_name_for_ads, prospect.domain, prospect.website])
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 3 and t not in {"www", "com", "net", "org", "llc", "inc", "the"}}


def _domain_relevance(email: str, prospect: Prospect, source_url: str, evidence: str) -> tuple[bool, str, str]:
    email_domain = email.rsplit("@", 1)[1]
    prospect_domain = normalize_domain(prospect.website) or normalize_domain(prospect.domain)
    if prospect_domain and (email_domain == prospect_domain or email_domain.endswith("." + prospect_domain)):
        return True, "SAME_DOMAIN", "HIGH"
    source_first_party = _same_domain(source_url, prospect_domain) if prospect_domain else False
    if email_domain in FREE_MAIL_DOMAINS:
        tokens = _business_tokens(prospect)
        evidence_l = evidence.lower()
        if source_first_party or any(t in evidence_l for t in tokens):
            return True, "FREE_MAIL_CONTEXTUAL", "MEDIUM"
        return False, "free_mail_without_business_context", "LOW"
    tokens = _business_tokens(prospect)
    if tokens and any(t in email_domain.lower().replace("-", "") for t in tokens):
        return True, "ASSOCIATED_DOMAIN", "MEDIUM"
    if source_first_party:
        return False, "unrelated_third_party_domain", "LOW"
    return False, "not_first_party_supported", "LOW"


def _near_text(text: str, email: str) -> str:
    idx = text.lower().find(email.lower())
    if idx < 0:
        return ""
    return _clean(text[max(0, idx - 120): idx + len(email) + 120])


def extract_email_candidates(source: EmailSource, prospect: Prospect) -> tuple[list[EmailCandidate], list[dict[str, str]], bool]:
    html = str(source.html or "")
    challenge = detect_challenge_content(html)
    if challenge.detected:
        return [], [], True
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    found: dict[str, tuple[str, str]] = {}
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if href.lower().startswith("mailto:"):
            email = _normalize_mailto(href)
            if email:
                found[email] = (SOURCE_CONTACT if source.source_type == SOURCE_CONTACT else source.source_type, _clean(anchor.get_text(" ", strip=True)) or _near_text(text, email))
    for raw in _EMAIL_RE.findall(text + " " + html):
        email = _candidate_email(raw)
        if email and email not in found:
            found[email] = (source.source_type, _near_text(text, email))

    rejected: list[dict[str, str]] = []
    accepted: list[EmailCandidate] = []
    person_centric = bool(_clean(prospect.contact_name))
    profile_verified = str(prospect.resolution_status or "").upper() == "RESOLVED" and bool(prospect.resolved_profile_url or prospect.manual_profile_url)
    for email, (source_type, evidence) in found.items():
        ok, reason = _valid_candidate_email(email)
        if not ok:
            rejected.append({"email": email, "reason": reason})
            continue
        relevant, relevance, confidence = _domain_relevance(email, prospect, source.url, evidence or text[:500])
        if not relevant:
            rejected.append({"email": email, "reason": relevance})
            continue
        email_type, association = _classify(email, prospect.contact_name, evidence or text[:500], source_type)
        rank = 500
        reason_text = "safe supported email"
        if person_centric and email_type == TYPE_PERSON and (source_type == SOURCE_PROFILE or profile_verified):
            rank, reason_text = 10, "explicit intended-person email on verified profile"
        elif person_centric and email_type == TYPE_PERSON:
            rank, reason_text = 20, "explicit intended-person email on same-domain page"
        elif email_type == TYPE_SALES:
            rank, reason_text = (60 if not person_centric else 80), "business sales contact email"
        elif email_type == TYPE_INFO:
            rank, reason_text = (70 if not person_centric else 90), "business info/general email"
        elif email_type in {TYPE_BUSINESS_GENERAL, TYPE_SUPPORT}:
            rank, reason_text = (75 if not person_centric else 95), "business general/support email"
        elif relevance == "SAME_DOMAIN":
            rank, reason_text = (85 if not person_centric else 100), "same-domain supported email"
        elif relevance == "FREE_MAIL_CONTEXTUAL":
            rank, reason_text = 110, "free-mail address explicitly listed in business context"
        accepted.append(EmailCandidate(email, source.url, source_type, email_type, relevance, confidence, reason_text, rank, association, evidence))
    return accepted, rejected, False


def _default_fetcher(url: str) -> str:
    response = requests.get(url, timeout=8, headers={"User-Agent": "BillboardAI/7C Email Enrichment"})
    response.raise_for_status()
    return response.text


def _coerce_fetch_result(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("html") or value.get("text") or "")
    return str(value or "")


def _contact_about_links(html: str, base_url: str, domain: str, limit: int) -> list[EmailSource]:
    if not html or limit <= 0:
        return []
    soup = BeautifulSoup(html, "lxml")
    links: list[tuple[int, str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        label = _clean(anchor.get_text(" ", strip=True)).lower()
        url = urljoin(base_url, href)
        if not _same_domain(url, domain):
            continue
        path = (urlparse(url).path or "").lower()
        if "contact" in path or "contact" in label:
            links.append((0, url, SOURCE_CONTACT))
        elif "about" in path or "about" in label:
            links.append((1, url, SOURCE_ABOUT))
    seen: set[str] = set()
    sources: list[EmailSource] = []
    for _score, url, typ in sorted(links, key=lambda item: (item[0], item[1])):
        if url in seen:
            continue
        seen.add(url)
        sources.append(EmailSource(url=url, html="", source_type=typ))
        if len(sources) >= limit:
            break
    return sources


def _candidate_sources(prospect: Prospect, scrape_data: dict[str, Any] | None, max_pages: int) -> list[EmailSource]:
    data = scrape_data if isinstance(scrape_data, dict) else {}
    sources: list[EmailSource] = []
    html = str(data.get("html") or "")
    url = str(data.get("url") or prospect.website or "")
    if html:
        typ = SOURCE_PROFILE if url and url in {prospect.resolved_profile_url, prospect.manual_profile_url} else SOURCE_SCRAPE
        sources.append(EmailSource(url=url, html=html, source_type=typ))
    elif prospect.website:
        sources.append(EmailSource(url=prospect.website, html="", source_type=SOURCE_HOMEPAGE))
    domain = normalize_domain(prospect.website) or normalize_domain(prospect.domain)
    if html and domain:
        sources.extend(_contact_about_links(html, url or prospect.website, domain, max(0, max_pages - len(sources))))
    return sources[:max_pages]


def enrich_prospect_email(
    prospect: Prospect,
    *,
    scrape_data: dict[str, Any] | None = None,
    fetcher: Fetcher | None = None,
    max_pages: int = 3,
) -> EmailEnrichmentResult:
    if is_valid_email(prospect.email):
        return EmailEnrichmentResult(STATUS_SKIPPED_EXISTING, False, REASON_EXISTING_EMAIL_PRESENT, diagnostics=_diagnostics(STATUS_SKIPPED_EXISTING, False, REASON_EXISTING_EMAIL_PRESENT))
    if not _clean(prospect.website) and not (isinstance(scrape_data, dict) and _clean(scrape_data.get("html"))):
        return EmailEnrichmentResult(STATUS_UNAVAILABLE, False, REASON_NO_WEBSITE, diagnostics=_diagnostics(STATUS_UNAVAILABLE, False, REASON_NO_WEBSITE))
    active_fetcher = fetcher or _default_fetcher
    candidates: list[EmailCandidate] = []
    rejected: list[dict[str, str]] = []
    blocked = False
    errors: list[str] = []
    sources = _candidate_sources(prospect, scrape_data, max_pages=max_pages)
    index = 0
    while index < len(sources) and index < max_pages:
        source = sources[index]
        html = source.html
        if not html:
            try:
                domain = normalize_domain(prospect.website) or normalize_domain(prospect.domain)
                if domain and not _same_domain(source.url, domain):
                    continue
                html = _coerce_fetch_result(active_fetcher(source.url))
            except Exception as exc:  # noqa: BLE001 - enrichment must be non-blocking
                errors.append(str(exc))
                continue
        found, rej, is_blocked = extract_email_candidates(EmailSource(source.url, html, source.source_type), prospect)
        candidates.extend(found)
        rejected.extend(rej)
        blocked = blocked or is_blocked
        if index == 0 and html:
            # Discover contact/about only after fetching homepage when no scrape html was supplied.
            existing_urls = {s.url for s in sources}
            domain = normalize_domain(prospect.website) or normalize_domain(prospect.domain)
            for extra in _contact_about_links(html, source.url, domain, max_pages - len(sources)):
                if extra.url not in existing_urls and len(sources) < max_pages:
                    sources.append(extra)
                    existing_urls.add(extra.url)
        index += 1
    dedup: dict[str, EmailCandidate] = {}
    for cand in candidates:
        current = dedup.get(cand.email)
        if current is None or (cand.rank, cand.source_url) < (current.rank, current.source_url):
            dedup[cand.email] = cand
    ordered = sorted(dedup.values(), key=lambda c: (c.rank, c.email, c.source_url))
    selected = ordered[0] if ordered else None
    status = STATUS_FOUND if selected else (STATUS_BLOCKED_CONTENT if blocked else (STATUS_ERROR if errors and not candidates else STATUS_NOT_FOUND))
    return EmailEnrichmentResult(status, True, REASON_MISSING_EMAIL, selected, ordered[1:], rejected, _diagnostics(status, True, REASON_MISSING_EMAIL, selected, ordered[1:], rejected, errors))


def apply_email_enrichment(prospect: Prospect, result: EmailEnrichmentResult) -> bool:
    meta = prospect.metadata if isinstance(prospect.metadata, dict) else {}
    prospect.metadata = meta
    meta["email_enrichment"] = dict(result.diagnostics)
    meta["email_state"] = {
        "status": "email_present" if prospect.email or result.selected else "email_missing",
        "email_enrichment_eligible": not bool(result.selected or is_valid_email(prospect.email)),
        "email_enrichment_status": result.status,
    }
    if result.selected and not is_valid_email(prospect.email):
        prospect.email = result.selected.email
        provenance = meta.get("field_provenance") if isinstance(meta.get("field_provenance"), dict) else {}
        provenance["email"] = {
            "origin": EMAIL_ORIGIN_ENRICHED,
            "source_url": result.selected.source_url,
            "source_type": result.selected.source_type,
            "email_type": result.selected.email_type,
            "selection_reason": result.selected.selection_reason,
            "confidence": result.selected.confidence,
        }
        meta["field_provenance"] = provenance
        meta["email_state"]["status"] = "email_present"
        meta["email_state"]["email_enrichment_eligible"] = False
        return True
    return False


def enrich_and_persist_prospect_email(
    prospect: Prospect,
    *,
    prospect_store: Any | None = None,
    scrape_data: dict[str, Any] | None = None,
    fetcher: Fetcher | None = None,
    max_pages: int = 3,
) -> EmailEnrichmentResult:
    result = enrich_prospect_email(prospect, scrape_data=scrape_data, fetcher=fetcher, max_pages=max_pages)
    changed = apply_email_enrichment(prospect, result)
    if prospect_store is not None and (changed or result.attempted or result.status == STATUS_SKIPPED_EXISTING):
        prospect.touch()
        prospect_store.update(prospect)
        prospect_store.save()
    return result


def _diagnostics(
    status: str,
    attempted: bool,
    reason: str,
    selected: EmailCandidate | None = None,
    alternatives: Iterable[EmailCandidate] = (),
    rejected: Iterable[dict[str, str]] = (),
    errors: Iterable[str] = (),
) -> dict[str, Any]:
    alts = [a.to_dict() for a in alternatives]
    return {
        "email_enrichment_status": status,
        "email_enrichment_attempted": attempted,
        "email_enrichment_reason": reason,
        "emails_found_count": (1 if selected else 0) + len(alts),
        "selected_email": selected.email if selected else "",
        "selected_email_type": selected.email_type if selected else "",
        "selected_email_source": selected.source_type if selected else "",
        "selected_email_source_url": selected.source_url if selected else "",
        "email_origin": EMAIL_ORIGIN_ENRICHED if selected else "",
        "email_selection_reason": selected.selection_reason if selected else "",
        "email_confidence": selected.confidence if selected else "",
        "email_alternatives": alts,
        "email_candidates_rejected": list(rejected),
        "email_candidate_rejection_reasons": sorted({str(r.get("reason") or "") for r in rejected if r.get("reason")}),
        "errors": [str(e)[:180] for e in errors],
    }