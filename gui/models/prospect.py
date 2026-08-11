"""Sprint 5A durable prospect domain models.

A **Prospect** is a business we may want to sell advertising to. It is a
distinct concept from (and exists *before*) a Project, a Contact, an Inventory
Placement, or an Opportunity:

- ``Prospect``  — a business we may sell advertising to.
- ``Project``   — persistent working state for one prospect/campaign effort.
- ``Contact``   — a person/email/phone associated with a prospect.
- ``Placement`` — a sellable advertising unit (Sprint 4A inventory).
- ``Opportunity`` — a future relationship between a prospect and a placement
                    (NOT modeled in this sprint).

This module is deliberately decoupled from:
- the GUI widgets / services (never imports Qt)
- the scraper / brand pipeline (no web requests, no scraping)
- projects / inventory / outreach

It never performs network I/O — normalization and deduplication are purely
deterministic string operations, so models are pure and testable in isolation.

Serialization follows the forward-compatible ``to_dict`` / ``from_dict`` pattern
used across the engine/GUI models: unknown persisted fields are ignored and
missing optional fields receive safe defaults.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Controlled prospect-status model (lifecycle of the prospect record, NOT a
# deal-stage / sales-pipeline status).
# ---------------------------------------------------------------------------
STATUS_NEW = "NEW"
STATUS_IMPORTED = "IMPORTED"
STATUS_READY_FOR_RESEARCH = "READY_FOR_RESEARCH"
STATUS_RESEARCHED = "RESEARCHED"
STATUS_DISQUALIFIED = "DISQUALIFIED"
STATUS_ARCHIVED = "ARCHIVED"

PROSPECT_STATUSES: tuple = (
    STATUS_NEW,
    STATUS_IMPORTED,
    STATUS_READY_FOR_RESEARCH,
    STATUS_RESEARCHED,
    STATUS_DISQUALIFIED,
    STATUS_ARCHIVED,
)

_DEFAULT_STATUS = STATUS_NEW

# ---------------------------------------------------------------------------
# Controlled workflow-status model (sales follow-up state, NOT the prospect
# record lifecycle status). Sprint 5G.
# ---------------------------------------------------------------------------
WORKFLOW_STATUS_NEW = "NEW"
WORKFLOW_STATUS_RESEARCHING = "RESEARCHING"
WORKFLOW_STATUS_READY_TO_CONTACT = "READY_TO_CONTACT"
WORKFLOW_STATUS_CONTACTED = "CONTACTED"
WORKFLOW_STATUS_FOLLOW_UP = "FOLLOW_UP"
WORKFLOW_STATUS_QUALIFIED = "QUALIFIED"
WORKFLOW_STATUS_NOT_INTERESTED = "NOT_INTERESTED"
WORKFLOW_STATUS_WON = "WON"
WORKFLOW_STATUS_LOST = "LOST"

WORKFLOW_STATUSES: tuple = (
    WORKFLOW_STATUS_NEW,
    WORKFLOW_STATUS_RESEARCHING,
    WORKFLOW_STATUS_READY_TO_CONTACT,
    WORKFLOW_STATUS_CONTACTED,
    WORKFLOW_STATUS_FOLLOW_UP,
    WORKFLOW_STATUS_QUALIFIED,
    WORKFLOW_STATUS_NOT_INTERESTED,
    WORKFLOW_STATUS_WON,
    WORKFLOW_STATUS_LOST,
)

WORKFLOW_STATUS_LABELS: Dict[str, str] = {
    WORKFLOW_STATUS_NEW: "New",
    WORKFLOW_STATUS_RESEARCHING: "Researching",
    WORKFLOW_STATUS_READY_TO_CONTACT: "Ready to Contact",
    WORKFLOW_STATUS_CONTACTED: "Contacted",
    WORKFLOW_STATUS_FOLLOW_UP: "Follow Up",
    WORKFLOW_STATUS_QUALIFIED: "Qualified",
    WORKFLOW_STATUS_NOT_INTERESTED: "Not Interested",
    WORKFLOW_STATUS_WON: "Won",
    WORKFLOW_STATUS_LOST: "Lost",
}

PIPELINE_WORKFLOW_ORDER: tuple = (
    WORKFLOW_STATUS_NEW,
    WORKFLOW_STATUS_RESEARCHING,
    WORKFLOW_STATUS_READY_TO_CONTACT,
    WORKFLOW_STATUS_CONTACTED,
    WORKFLOW_STATUS_FOLLOW_UP,
    WORKFLOW_STATUS_QUALIFIED,
    WORKFLOW_STATUS_WON,
    WORKFLOW_STATUS_LOST,
    WORKFLOW_STATUS_NOT_INTERESTED,
)

ACTIVE_WORKFLOW_STATUSES: tuple = (
    WORKFLOW_STATUS_NEW,
    WORKFLOW_STATUS_RESEARCHING,
    WORKFLOW_STATUS_READY_TO_CONTACT,
    WORKFLOW_STATUS_CONTACTED,
    WORKFLOW_STATUS_FOLLOW_UP,
    WORKFLOW_STATUS_QUALIFIED,
)

CLOSED_WORKFLOW_STATUSES: tuple = (
    WORKFLOW_STATUS_WON,
    WORKFLOW_STATUS_LOST,
    WORKFLOW_STATUS_NOT_INTERESTED,
)

_DEFAULT_WORKFLOW_STATUS = WORKFLOW_STATUS_NEW

PRIORITY_LOW = "LOW"
PRIORITY_NORMAL = "NORMAL"
PRIORITY_HIGH = "HIGH"
PRIORITY_URGENT = "URGENT"

PRIORITIES: tuple = (
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    PRIORITY_HIGH,
    PRIORITY_URGENT,
)

PRIORITY_LABELS: Dict[str, str] = {
    PRIORITY_LOW: "Low",
    PRIORITY_NORMAL: "Normal",
    PRIORITY_HIGH: "High",
    PRIORITY_URGENT: "Urgent",
}

_DEFAULT_PRIORITY = PRIORITY_NORMAL

# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------


def filesystem_safe_id(prefix: str = "") -> str:
    """Return a stable, filesystem-safe, JSON-safe unique id.

    A UUID is used (never a human/company label alone) so multiple prospects
    never collide and the value is safe to use as a directory/filename part.
    """
    uid = str(uuid.uuid4())
    return f"{prefix}_{uid}" if prefix else uid


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (second precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _clean(value: Any) -> str:
    """Coerce a value to a trimmed string (None -> empty)."""
    if value is None:
        return ""
    return str(value).strip()


def _optional_float(value: Any) -> Optional[float]:
    """Coerce to float or None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_iso_date(value: Any) -> Optional[str]:
    """Coerce a value to an ISO-8601 date string (YYYY-MM-DD) or None.

    Malformed values are treated consistently with the project's safe-default
    strategy: return None rather than crashing or inventing a date.
    """
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = date.fromisoformat(text)
        return parsed.isoformat()
    except (TypeError, ValueError):
        return None


def collapse_whitespace(value: str) -> str:
    """Collapse runs of whitespace into a single space; strip ends."""
    return re.sub(r"\s+", " ", value).strip()


def _string_list(value: Any) -> List[str]:
    """Coerce a persisted value to a list of strings (safe defaults)."""
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if item is not None]


# ---------------------------------------------------------------------------
# Normalization (deterministic, no I/O)
# ---------------------------------------------------------------------------

# US state abbreviations (2-letter) used for state normalization.
_STATE_ABBREVIATIONS: Dict[str, str] = {
    "al": "AL", "ak": "AK", "az": "AZ", "ar": "AR", "ca": "CA", "co": "CO",
    "ct": "CT", "de": "DE", "fl": "FL", "ga": "GA", "hi": "HI", "id": "ID",
    "il": "IL", "in": "IN", "ia": "IA", "ks": "KS", "ky": "KY", "la": "LA",
    "me": "ME", "md": "MD", "ma": "MA", "mi": "MI", "mn": "MN", "ms": "MS",
    "mo": "MO", "mt": "MT", "ne": "NE", "nv": "NV", "nh": "NH", "nj": "NJ",
    "nm": "NM", "ny": "NY", "nc": "NC", "nd": "ND", "oh": "OH", "ok": "OK",
    "or": "OR", "pa": "PA", "ri": "RI", "sc": "SC", "sd": "SD", "tn": "TN",
    "tx": "TX", "ut": "UT", "vt": "VT", "va": "VA", "wa": "WA", "wv": "WV",
    "wi": "WI", "wy": "WY",
    "dc": "DC", "pr": "PR", "vi": "VI", "gu": "GU", "as": "AS", "mp": "MP",
}

# Full state names -> abbreviations (common; enough for import smoothing).
_STATE_FULL_NAMES: Dict[str, str] = {
    "colorado": "CO", "arizona": "AZ", "california": "CA", "texas": "TX",
    "florida": "FL", "south dakota": "SD", "north dakota": "ND",
    "new york": "NY", "new jersey": "NJ", "new mexico": "NM",
    "georgia": "GA", "washington": "WA", "oregon": "OR", "nevada": "NV",
    "utah": "UT", "kansas": "KS", "virginia": "VA", "tennessee": "TN",
    "oklahoma": "OK", "wyoming": "WY", "montana": "MT", "idaho": "ID",
    "nebraska": "NE",
}


def normalize_website(value: Any) -> str:
    """Normalize a website URL for storage/comparison.

    - trims whitespace
    - adds ``https://`` scheme when only a host is given
    - lowercases the host
    - strips obvious trailing-slash noise (pathless URLs)
    """
    text = _clean(value)
    if not text:
        return ""
    text = collapse_whitespace(text)
    if not re.search(r"://", text):
        text = "https://" + text
    try:
        parsed = urlparse(text)
    except ValueError:
        return text
    host = (parsed.hostname or "").lower()
    if not host or "." not in host:
        return text
    return f"{parsed.scheme}://{host}"


def normalize_domain(value: Any) -> str:
    """Extract a clean, lowercased domain (no scheme, no ``www.``)."""
    website = normalize_website(value)
    if not website:
        return ""
    try:
        parsed = urlparse(website)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_email(value: Any) -> str:
    """Normalize an email address (trim + lowercase).

    The whole address is lowercased so equivalent-format emails compare equal
    for deterministic duplicate detection (local parts are treated
    case-insensitively for matching purposes).
    """
    text = _clean(value)
    if not text:
        return ""
    return text.replace(" ", "").lower()


def normalize_phone(value: Any) -> str:
    """Normalize a phone number to digits only (or empty when absent).

    A leading ``+1`` country code is preserved as ``1...``. Non-digits are
    stripped. Deterministic so equivalent formats compare equal.
    """
    text = _clean(value)
    if not text:
        return ""
    digits = re.sub(r"\D", "", text)
    if digits.startswith("001"):
        digits = digits[2:]
    elif digits.startswith("01") and len(digits) == 12:
        digits = digits[1:]
    return digits


def normalize_category(value: Any) -> str:
    """Normalize a category for safe comparison (trim + lowercase)."""
    return _clean(value).strip().lower()


def normalize_tags(value: Any) -> List[str]:
    """Normalize a tags input (list or comma-separated) to a de-duplicated list.

    Tags are trimmed, blank entries dropped, and duplicates removed
    case-insensitively while preserving the first-seen casing.
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
    else:
        parts = [str(p).strip() for p in value]
    seen: List[str] = []
    for part in parts:
        if not part:
            continue
        if part.lower() not in {s.lower() for s in seen}:
            seen.append(part)
    return seen


def normalize_state(value: Any) -> str:
    """Coerce a US state to a 2-letter uppercase abbreviation when possible."""
    text = _clean(value).strip().lower()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    if len(text) == 2 and text in _STATE_ABBREVIATIONS:
        return _STATE_ABBREVIATIONS[text]
    if text in _STATE_FULL_NAMES:
        return _STATE_FULL_NAMES[text]
    return ""


def normalize_company_name(value: Any) -> str:
    """Light, deterministic normalization of a business name.

    We deliberately do NOT over-normalize: case is left as provided (names are
    displayed to humans), whitespace is collapsed, and leading/trailing
    whitespace is removed. A lowercased, punctuation-lite key is provided via
    :func:`company_key` for fuzzy matching.
    """
    text = _clean(value)
    return collapse_whitespace(text)


def company_key(value: Any) -> str:
    """A lowercased, punctuation-lite key for fuzzy company comparison."""
    text = normalize_company_name(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Validation (deterministic, no I/O)
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def is_valid_email(email: str) -> bool:
    """Basic email syntax check (non-empty, one @, a dotted domain)."""
    normalized = normalize_email(email)
    if not normalized:
        return False
    return bool(_EMAIL_RE.match(normalized))


def is_valid_phone(phone: str) -> bool:
    """Basic phone sanity check (7+ digits; 10 typical for US)."""
    digits = normalize_phone(phone)
    if not digits:
        return False
    return 7 <= len(digits) <= 15


def is_valid_website(website: str) -> bool:
    """Check that a website value is parseable with a plausible host."""
    normalized = normalize_website(website)
    if not normalized:
        return False
    try:
        parsed = urlparse(normalized)
    except ValueError:
        return False
    host = parsed.hostname or ""
    return "." in host and bool(host.strip())


# ---------------------------------------------------------------------------
# Contact model
# ---------------------------------------------------------------------------


@dataclass
class Contact:
    """A person/email/phone associated with a Prospect.

    A separate first-class model (rather than nested fields) so a prospect can
    hold multiple contacts cleanly later — without building a CRM. For MVP a
    prospect may carry one primary contact; the model does not enforce a CRM.
    """

    contact_id: str = field(
        default_factory=lambda: filesystem_safe_id("contact")
    )
    prospect_id: str = ""
    name: str = ""
    title: str = ""
    email: str = ""
    phone: str = ""
    is_primary: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contact_id": self.contact_id,
            "prospect_id": self.prospect_id,
            "name": self.name,
            "title": self.title,
            "email": self.email,
            "phone": self.phone,
            "is_primary": bool(self.is_primary),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Contact":
        data = data if isinstance(data, dict) else {}
        return cls(
            contact_id=_clean(data.get("contact_id"))
            or filesystem_safe_id("contact"),
            prospect_id=_clean(data.get("prospect_id")),
            name=_clean(data.get("name")),
            title=_clean(data.get("title")),
            email=_clean(data.get("email")),
            phone=_clean(data.get("phone")),
            is_primary=bool(data.get("is_primary", False)),
            metadata=dict(data.get("metadata") or {}),
        )


# ---------------------------------------------------------------------------
# Prospect model
# ---------------------------------------------------------------------------


@dataclass
class Prospect:
    """A business we may want to sell advertising to (durable record)."""

    prospect_id: str = field(
        default_factory=lambda: filesystem_safe_id("prospect")
    )
    company_name: str = ""
    website: str = ""
    domain: str = ""

    phone: str = ""
    email: str = ""

    address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""

    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geocode_metadata: Dict[str, Any] = field(default_factory=dict)

    category: str = ""
    subcategory: str = ""

    contact_name: str = ""
    contact_title: str = ""

    source: str = ""
    source_id: str = ""

    status: str = _DEFAULT_STATUS

    notes: str = ""
    tags: List[str] = field(default_factory=list)

    created_at: str = field(default_factory=utc_now_iso)
    modified_at: str = field(default_factory=utc_now_iso)

    metadata: Dict[str, Any] = field(default_factory=dict)

    # Future-facing hints (Sprint 5B/5C). Not used for matching yet.
    market_id: str = ""
    location_hint: str = ""
    research_status: str = ""

    # Sprint 5G: sales follow-up / action workflow state.
    workflow_status: str = _DEFAULT_WORKFLOW_STATUS
    priority: str = _DEFAULT_PRIORITY
    next_action: str = ""
    next_action_date: Optional[str] = None
    workflow_notes: str = ""

    # For MVP, a prospect carries zero-or-more contacts (usually one primary).
    contacts: List[Contact] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def primary_contact(self) -> Optional[Contact]:
        """Return the primary contact, else the first contact, else None."""
        for contact in self.contacts:
            if contact.is_primary:
                return contact
        return self.contacts[0] if self.contacts else None

    def is_ready_for_research(self) -> bool:
        """True when a usable website/domain exists (Sprint 5A rule)."""
        return bool(self.domain or self.website)

    def touch(self) -> None:
        """Stamp modified_at to now (called on any mutation)."""
        self.modified_at = utc_now_iso()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prospect_id": self.prospect_id,
            "company_name": self.company_name,
            "website": self.website,
            "domain": self.domain,
            "phone": self.phone,
            "email": self.email,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "geocode_metadata": dict(self.geocode_metadata),
            "category": self.category,
            "subcategory": self.subcategory,
            "contact_name": self.contact_name,
            "contact_title": self.contact_title,
            "source": self.source,
            "source_id": self.source_id,
            "status": self.status,
            "notes": self.notes,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "metadata": dict(self.metadata),
            "market_id": self.market_id,
            "location_hint": self.location_hint,
            "research_status": self.research_status,
            "workflow_status": self.workflow_status,
            "priority": self.priority,
            "next_action": self.next_action,
            "next_action_date": self.next_action_date,
            "workflow_notes": self.workflow_notes,
            "contacts": [c.to_dict() for c in self.contacts],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Prospect":
        data = data if isinstance(data, dict) else {}
        status = _clean(data.get("status")) or _DEFAULT_STATUS
        if status not in PROSPECT_STATUSES:
            status = _DEFAULT_STATUS
        workflow_status = _clean(data.get("workflow_status")) or _DEFAULT_WORKFLOW_STATUS
        if workflow_status not in WORKFLOW_STATUSES:
            workflow_status = _DEFAULT_WORKFLOW_STATUS
        priority = _clean(data.get("priority")) or _DEFAULT_PRIORITY
        if priority not in PRIORITIES:
            priority = _DEFAULT_PRIORITY
        next_action_date = _optional_iso_date(data.get("next_action_date"))
        contacts_raw = data.get("contacts") or []
        contacts = [
            Contact.from_dict(c)
            for c in contacts_raw
            if isinstance(c, dict)
        ]
        return cls(
            prospect_id=_clean(data.get("prospect_id"))
            or filesystem_safe_id("prospect"),
            company_name=_clean(data.get("company_name")),
            website=_clean(data.get("website")),
            domain=_clean(data.get("domain")),
            phone=_clean(data.get("phone")),
            email=_clean(data.get("email")),
            address=_clean(data.get("address")),
            city=_clean(data.get("city")),
            state=_clean(data.get("state")),
            postal_code=_clean(data.get("postal_code")),
            latitude=_optional_float(data.get("latitude")),
            longitude=_optional_float(data.get("longitude")),
            geocode_metadata=dict(data.get("geocode_metadata") or {}),
            category=_clean(data.get("category")),
            subcategory=_clean(data.get("subcategory")),
            contact_name=_clean(data.get("contact_name")),
            contact_title=_clean(data.get("contact_title")),
            source=_clean(data.get("source")),
            source_id=_clean(data.get("source_id")),
            status=status,
            notes=_clean(data.get("notes")),
            tags=_string_list(data.get("tags")),
            created_at=_clean(data.get("created_at")) or utc_now_iso(),
            modified_at=_clean(data.get("modified_at")) or utc_now_iso(),
            metadata=dict(data.get("metadata") or {}),
            market_id=_clean(data.get("market_id")),
            location_hint=_clean(data.get("location_hint")),
            research_status=_clean(data.get("research_status")),
            workflow_status=workflow_status,
            priority=priority,
            next_action=_clean(data.get("next_action")),
            next_action_date=next_action_date,
            workflow_notes=_clean(data.get("workflow_notes")),
            contacts=contacts,
        )
# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

DEDUP_EXACT = "EXACT_DUPLICATE"
DEDUP_POSSIBLE = "POSSIBLE_DUPLICATE"
DEDUP_UNIQUE = "UNIQUE"


class ProspectDeduplicator:
    """Deterministic duplicate detection between two prospects.

    Evidence order (first match wins):

    1. exact normalized domain
    2. exact normalized website
    3. exact normalized email
    4. exact normalized phone
    5. strong fallback: normalized company + city/state

    Blank values never create a match (a missing domain cannot equal a missing
    domain). Fuzzy company-name-only matches are NOT auto-merged — they are
    reported as ``POSSIBLE_DUPLICATE`` only with corroborating city/state.
    """

    @staticmethod
    def compare(a: Prospect, b: Prospect) -> str:
        """Return EXACT_DUPLICATE / POSSIBLE_DUPLICATE / UNIQUE for (a, b)."""
        domain_a = normalize_domain(a.domain or a.website)
        domain_b = normalize_domain(b.domain or b.website)
        if domain_a and domain_a == domain_b:
            return DEDUP_EXACT

        website_a = normalize_website(a.website)
        website_b = normalize_website(b.website)
        if website_a and website_a == website_b:
            return DEDUP_EXACT

        email_a = normalize_email(a.email)
        email_b = normalize_email(b.email)
        if email_a and email_a == email_b:
            return DEDUP_EXACT

        phone_a = normalize_phone(a.phone)
        phone_b = normalize_phone(b.phone)
        if phone_a and phone_a == phone_b:
            return DEDUP_EXACT

        # Strong fallback: company name + city/state both match.
        key_a = company_key(a.company_name)
        key_b = company_key(b.company_name)
        city_a = _clean(a.city).lower()
        city_b = _clean(b.city).lower()
        state_a = normalize_state(a.state)
        state_b = normalize_state(b.state)
        if (
            key_a
            and key_a == key_b
            and (city_a or state_a)
            and (
                (city_a and city_a == city_b)
                or (state_a and state_a == state_b)
            )
        ):
            return DEDUP_POSSIBLE

        return DEDUP_UNIQUE

    @classmethod
    def compare_keys(cls, candidate: Prospect, existing: Prospect) -> str:
        """Alias for :meth:`compare` (candidate/existing naming)."""
        return cls.compare(candidate, existing)