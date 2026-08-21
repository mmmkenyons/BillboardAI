"""Sprint 5A CSV prospect importer (pure Python, Qt-free).

Parses a CSV of businesses into ``Prospect`` records with explicit column
mapping, normalization, validation, deduplication and merge semantics. The
importer is deliberately NOT buried inside the GUI widgets — it lives in the
service layer and is fully testable without a desktop.

Design points:

- **Header row required.** The first non-empty row is the header; aliases for
  common fields are accepted (see :data:`COLUMN_ALIASES`).
- **Explicit column mapping.** ``detect_mapping``/``import_text`` report the
  recognized mapping before import. Unknown columns never crash — they are
  preserved in per-row metadata (``raw_<col>``) when ``preserve_unknown``.
- **Company name is required** for a row to be valid. Missing optional fields
  are fine. A row with no usable website/domain is imported but not marked
  ``READY_FOR_RESEARCH``.
- **Validation is deterministic** (email syntax, phone sanity, URL parse).
  Records are never rejected merely for absent optional data.
- **Deduplication** uses the store's ``find_duplicate`` (exact) and
  ``check_possible_duplicates`` (company+city). Exact duplicates are merged in
  place (preserving the existing id); possible duplicates are reported per-row.
- **No web requests** are ever made.
- **Graceful error handling** — bad rows are skipped and reported in the
  result; the importer continues past them where safe.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from gui.models.prospect import (
    STATUS_IMPORTED,
    STATUS_READY_FOR_RESEARCH,
    Contact,
    Prospect,
    is_valid_email,
    is_valid_phone,
    is_valid_website,
    normalize_category,
    normalize_company_name,
    normalize_domain,
    normalize_email,
    normalize_phone,
    normalize_state,
    normalize_tags,
    normalize_website,
)
from gui.models.prospect_store import ProspectStore
from gui.services.canonical_prospect_intelligence import (
    business_classification,
    preferred_display_company_name,
    select_creative_phone as _select_canonical_creative_phone,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical field catalog / aliases (source-agnostic).
# ---------------------------------------------------------------------------

COLUMN_ALIASES: Dict[str, tuple] = {
    "first_name": ("first_name", "first name", "firstname", "given name", "contact first"),
    "last_name": ("last_name", "last name", "lastname", "surname", "contact last"),
    "website": (
        "website", "url", "domain", "website_url", "website url",
        "parent_website", "brokerage_website", "company_website", "company website", "company domain",
    ),
    "company_name": ("company", "company_name", "company name", "business", "business_name", "business name", "organization", "brokerage_name"),
    "company_name_for_ads": ("company name for emails", "company_name_for_emails", "company display name", "display company name", "brand name", "brand", "ad company name"),
    "phone": ("phone", "phone_number", "telephone"),
    "company_phone": ("company phone", "corporate phone", "business phone", "office phone", "main phone"),
    "mobile_phone": ("mobile", "mobile phone", "cell", "cell phone"),
    "work_direct_phone": ("work direct phone", "direct phone", "work phone"),
    "other_phone": ("other phone", "alternate phone", "alt phone"),
    "email": ("email", "email_address", "email address", "primary email", "work email", "business email"),
    "secondary_email": ("secondary email", "alternate email", "other email"),
    "address": ("address", "street", "street_address"),
    "city": ("city", "town"),
    "state": ("state", "province", "region"),
    "country": ("country",),
    "postal_code": ("postal_code", "zip", "zip_code", "postcode"),
    "company_address": ("company address", "company_address", "organization address"),
    "company_city": ("company city", "company_city", "organization city"),
    "company_state": ("company state", "company_state", "organization state"),
    "company_country": ("company country", "company_country", "organization country"),
    "category": ("category", "business_type"),
    "industry": ("industry", "company industry"),
    "subcategory": ("subcategory", "niche"),
    "naics_codes": ("naics", "naics code", "naics codes"),
    "sic_codes": ("sic", "sic code", "sic codes"),
    "company_keywords": ("keywords", "company keywords", "organization keywords", "business keywords"),
    "employee_count": ("employee count", "employees", "number of employees"),
    "annual_revenue": ("annual revenue", "revenue"),
    "number_of_retail_locations": ("number of retail locations", "retail locations", "locations count"),
    "contact_name": (
        "contact", "contact_name", "name", "primary_contact",
        "agent_name", "person_name",
    ),
    "contact_title": ("title", "contact_title", "job_title", "professional title"),
    "person_linkedin_url": ("person linkedin url", "linkedin", "linkedin url", "contact linkedin"),
    "company_linkedin_url": ("company linkedin url", "organization linkedin", "company linkedin"),
    "source": ("source", "lead_source"),
    "source_id": ("source_id", "source record id", "external_id", "id"),
    "notes": ("notes", "comment", "comments"),
    "tags": ("tags", "tag", "labels"),
    "market_id": ("market_id", "market"),
    "location_hint": ("location_hint", "location"),
    "priority": ("priority", "lead_score"),
    "research_status": ("research_status", "status"),
}

CANONICAL_LABELS: Dict[str, str] = {
    "company_name": "Company Name",
    "company_name_for_ads": "Ad/Display Company",
    "website": "Website",
    "email": "Email",
    "company_phone": "Company Phone",
    "mobile_phone": "Mobile Phone",
    "work_direct_phone": "Work Direct Phone",
    "other_phone": "Other Phone",
    "naics_codes": "NAICS Codes",
    "company_keywords": "Company Keywords",
    "industry": "Industry",
}

MERGEABLE_FIELDS = {"naics_codes", "sic_codes", "company_keywords", "tags"}
CANONICAL_FIELDS = tuple(COLUMN_ALIASES.keys())

MAPPING_EXACT = "EXACT"
MAPPING_ALIAS = "ALIAS"
MAPPING_UNMAPPED = "UNMAPPED"
MAPPING_AMBIGUOUS = "AMBIGUOUS"

_AMBIGUOUS_HEADERS = {"linkedin": ("person_linkedin_url", "company_linkedin_url")}


def _normalize_header_key(value: Any) -> str:
    """Case/spacing/punctuation-tolerant header key (no fuzzy guessing)."""
    text = str(value or "").strip().lower()
    text = re.sub(r"[_\-\/]+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Build a reverse lookup: lowercase header -> canonical field.
_ALIAS_TO_CANON: Dict[str, str] = {}
for _canon, _aliases in COLUMN_ALIASES.items():
    _ALIAS_TO_CANON[_normalize_header_key(_canon)] = _canon
    for _alias in _aliases:
        _ALIAS_TO_CANON[_normalize_header_key(_alias)] = _canon


def canonical_for_header(header: str) -> Optional[str]:
    """Return the canonical prospect field for a raw CSV header, or None."""
    key = _normalize_header_key(header)
    if key in _AMBIGUOUS_HEADERS:
        return None
    return _ALIAS_TO_CANON.get(key)


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass
class ProspectRowResult:
    """Per-row import outcome (inspectable and testable)."""

    row_number: int
    status: str  # imported | merged | skipped | invalid
    prospect_id: str = ""
    message: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ColumnMappingDetail:
    """Source-column mapping preview for UI/tests."""

    source_column: str
    canonical_field: str = ""
    status: str = MAPPING_UNMAPPED
    reason: str = ""
    candidates: List[str] = field(default_factory=list)


@dataclass
class MappingPreview:
    """Full source-header mapping preview."""

    columns: List[ColumnMappingDetail] = field(default_factory=list)

    @property
    def mapping(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for detail in self.columns:
            if detail.status in {MAPPING_EXACT, MAPPING_ALIAS} and detail.canonical_field:
                if detail.canonical_field not in result:
                    result[detail.canonical_field] = detail.source_column
        return result


@dataclass
class ProspectImportResult:
    """Structured summary of a CSV import run."""

    rows_total: int = 0
    imported: int = 0
    merged: int = 0
    skipped: int = 0
    invalid: int = 0
    possible_duplicates: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rows: List[ProspectRowResult] = field(default_factory=list)
    mapping: Dict[str, str] = field(default_factory=dict)
    mapping_details: List[ColumnMappingDetail] = field(default_factory=list)
    unknown_columns: List[str] = field(default_factory=list)

    def summary_dict(self) -> Dict[str, Any]:
        """Compact dict for display in the UI."""
        return {
            "rows_total": self.rows_total,
            "imported": self.imported,
            "merged": self.merged,
            "skipped": self.skipped,
            "invalid": self.invalid,
            "possible_duplicates": self.possible_duplicates,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Import errors
# ---------------------------------------------------------------------------


class ProspectImportError(Exception):
    """Raised for unrecoverable CSV import problems (bad file, no header)."""


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def detect_mapping(headers: List[str]) -> Dict[str, str]:
    """Map raw header names to canonical prospect fields.

    Returns a dict ``{canonical_field: raw_header}``. Unrecognized headers are
    ignored (reported separately by the caller from the full header list).
    """
    return detect_mapping_details(headers).mapping


def detect_mapping_details(headers: List[str]) -> MappingPreview:
    """Return per-source-column mapping status (EXACT/ALIAS/UNMAPPED/AMBIGUOUS)."""
    columns: List[ColumnMappingDetail] = []
    seen_single_value: set[str] = set()
    for header in headers:
        raw = str(header or "").strip()
        key = _normalize_header_key(raw)
        if not raw:
            continue
        if key in _AMBIGUOUS_HEADERS:
            columns.append(ColumnMappingDetail(raw, "", MAPPING_AMBIGUOUS, "multiple plausible canonical fields", list(_AMBIGUOUS_HEADERS[key])))
            continue
        canon = _ALIAS_TO_CANON.get(key)
        if canon is None:
            columns.append(ColumnMappingDetail(raw, "", MAPPING_UNMAPPED, "no safe alias recognized"))
            continue
        status = MAPPING_EXACT if key == _normalize_header_key(canon) else MAPPING_ALIAS
        reason = "canonical header" if status == MAPPING_EXACT else "recognized safe alias"
        if canon in seen_single_value and canon not in MERGEABLE_FIELDS:
            columns.append(ColumnMappingDetail(raw, canon, MAPPING_AMBIGUOUS, "duplicate single-value target", [canon]))
            continue
        seen_single_value.add(canon)
        columns.append(ColumnMappingDetail(raw, canon, status, reason, [canon]))
    return MappingPreview(columns)


def unknown_columns(headers: List[str], mapping: Dict[str, str]) -> List[str]:
    """Return headers that were not recognized as any canonical field."""
    mapped = set(mapping.values())
    return [h for h in headers if h not in mapped and str(h).strip() != ""]


_BLANK_VALUES = {"", "null", "none", "n/a", "na", "-", "--"}


def _clean_import_value(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in _BLANK_VALUES else text


def normalize_code_list(value: Any) -> List[str]:
    """Normalize NAICS/SIC-like code lists while preserving original in metadata."""
    text = _clean_import_value(value)
    if not text:
        return []
    parts = re.split(r"[;,|]+", text)
    codes: List[str] = []
    for part in parts:
        match = re.search(r"\b\d{2,8}\b", part)
        if match and match.group(0) not in codes:
            codes.append(match.group(0))
    return codes


def normalize_keyword_list(value: Any) -> List[str]:
    text = _clean_import_value(value)
    if not text:
        return []
    return [p.strip() for p in re.split(r"[;,|]+", text) if p.strip()]


def select_creative_company_name(prospect: Prospect) -> str:
    """Deterministic creative company-name precedence."""
    return preferred_display_company_name(prospect)


def select_creative_phone(prospect: Prospect) -> Dict[str, str]:
    """Prefer business/company phone for billboard creative; document fallback."""
    selected = _select_canonical_creative_phone(prospect)
    return {str(k): v for k, v in selected.items()}


def classification_evidence(prospect: Prospect) -> Dict[str, Any]:
    """NAICS > keywords > industry > website-derived > fallback."""
    return business_classification(prospect)


# ---------------------------------------------------------------------------
# Row parsing / validation
# ---------------------------------------------------------------------------


def _row_to_prospect(row: Dict[str, Any], mapping: Dict[str, str]) -> Prospect:
    """Build a Prospect from a raw row dict using the active mapping.

    Values are normalized. A one-element primary Contact is created when the
    row carries contact name / title / email / phone.
    """

    def _val(canon: str) -> str:
        header = mapping.get(canon)
        if header is None:
            return ""
        return _clean_import_value(row.get(header, ""))

    def _prov(canon: str, normalized: Any, original: Any = None) -> Optional[Dict[str, Any]]:
        header = mapping.get(canon)
        if header is None:
            return None
        return {
            "origin": "IMPORTED",
            "source_column": header,
            "original_value": _clean_import_value(row.get(header, "") if original is None else original),
            "normalized_value": normalized,
        }

    website_raw = _val("website")
    website = normalize_website(website_raw)
    domain = normalize_domain(website_raw) or normalize_domain(website)
    email_raw = _val("email")
    secondary_email_raw = _val("secondary_email")
    company_phone_raw = _val("company_phone")
    mobile_phone_raw = _val("mobile_phone")
    work_phone_raw = _val("work_direct_phone")
    other_phone_raw = _val("other_phone")
    legacy_phone_raw = _val("phone")
    state = normalize_state(_val("state"))
    company_state = normalize_state(_val("company_state"))
    subcategory = _val("subcategory")
    first_name = _val("first_name")
    last_name = _val("last_name")
    contact_name = _val("contact_name") or " ".join(part for part in (first_name, last_name) if part).strip()
    naics_codes = normalize_code_list(_val("naics_codes"))
    sic_codes = normalize_code_list(_val("sic_codes"))
    keywords = normalize_keyword_list(_val("company_keywords"))
    industry = _val("industry")

    prospect = Prospect(
        company_name=normalize_company_name(_val("company_name")),
        company_name_for_ads=normalize_company_name(_val("company_name_for_ads")),
        website=website,
        domain=domain,
        company_phone=normalize_phone(company_phone_raw),
        mobile_phone=normalize_phone(mobile_phone_raw),
        work_direct_phone=normalize_phone(work_phone_raw),
        other_phone=normalize_phone(other_phone_raw),
        phone=normalize_phone(legacy_phone_raw),
        email=normalize_email(email_raw),
        secondary_email=normalize_email(secondary_email_raw),
        address=_val("address"),
        city=_val("city"),
        state=state,
        postal_code=_val("postal_code"),
        country=_val("country"),
        company_address=_val("company_address"),
        company_city=_val("company_city"),
        company_state=company_state,
        company_country=_val("company_country"),
        category=normalize_category(_val("category")),
        subcategory=subcategory.strip().lower() if subcategory else "",
        naics_codes=naics_codes,
        sic_codes=sic_codes,
        company_keywords=keywords,
        industry=industry,
        employee_count=_val("employee_count"),
        annual_revenue=_val("annual_revenue"),
        number_of_retail_locations=_val("number_of_retail_locations"),
        contact_name=contact_name,
        contact_title=_val("contact_title"),
        person_linkedin_url=_val("person_linkedin_url"),
        company_linkedin_url=_val("company_linkedin_url"),
        source=_val("source"),
        source_id=_val("source_id"),
        notes=_val("notes"),
        tags=normalize_tags(_val("tags")),
        market_id=_val("market_id"),
        location_hint=_val("location_hint"),
        priority=_val("priority"),
        research_status=_val("research_status"),
    )

    selected_phone = select_creative_phone(prospect)
    if not prospect.phone:
        prospect.phone = selected_phone["phone"]
    evidence = classification_evidence(prospect)
    if not prospect.category and evidence["basis"] == "industry":
        prospect.category = normalize_category(str(evidence["value"]))

    provenance: Dict[str, Any] = {}
    for canon in mapping:
        original = row.get(mapping[canon], "")
        normalized = getattr(prospect, canon, _clean_import_value(original))
        entry = _prov(canon, normalized, original)
        if entry is not None:
            provenance[canon] = entry
    prospect.metadata["field_provenance"] = provenance
    prospect.metadata["creative_company_name"] = select_creative_company_name(prospect)
    prospect.metadata["creative_phone"] = selected_phone
    prospect.metadata["classification_evidence"] = evidence
    prospect.metadata["email_state"] = {
        "status": "email_present" if prospect.email else "email_missing",
        "email_enrichment_eligible": not bool(prospect.email),
        "source_column": mapping.get("email", ""),
    }
    if prospect.company_name:
        prospect.metadata["normalized_source_company_name"] = prospect.company_name

    # Status: READY_FOR_RESEARCH only when a usable website/domain exists.
    if prospect.is_ready_for_research():
        prospect.status = STATUS_READY_FOR_RESEARCH
    else:
        prospect.status = STATUS_IMPORTED

    # Build a primary contact from the row's contact fields when any present.
    if contact_name or _val("contact_title") or email_raw or mobile_phone_raw or work_phone_raw:
        prospect.contacts.append(
            Contact(
                prospect_id=prospect.prospect_id,
                name=contact_name,
                title=_val("contact_title"),
                email=prospect.email,
                phone=prospect.work_direct_phone or prospect.mobile_phone,
                is_primary=True,
                metadata={"phone_type": "work_direct_phone" if prospect.work_direct_phone else ("mobile_phone" if prospect.mobile_phone else "")},
            )
        )

    return prospect


def validate_row(prospect: Prospect) -> List[str]:
    """Return a list of validation messages for a prospect (empty = valid).

    Company name is required. Optional fields are validated only when present;
    absent optional data never causes a rejection.
    """
    problems: List[str] = []
    if not prospect.company_name:
        problems.append("company name is required")
    if prospect.email and not is_valid_email(prospect.email):
        problems.append("invalid email")
    if prospect.phone and not is_valid_phone(prospect.phone):
        problems.append("invalid phone")
    for field_name in ("company_phone", "mobile_phone", "work_direct_phone", "other_phone"):
        value = getattr(prospect, field_name, "")
        if value and not is_valid_phone(value):
            problems.append(f"invalid {field_name}")
    if prospect.website and not is_valid_website(prospect.website):
        problems.append("malformed URL")
    return problems
# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------


class ProspectCsvImporter:
    """Import a CSV of businesses into a ProspectStore."""

    def __init__(self, store: ProspectStore, preserve_unknown: bool = True) -> None:
        self._store = store
        self._preserve_unknown = preserve_unknown

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def import_file(
        self,
        path: str,
        source: str = "csv_import",
        mapping: Optional[Dict[str, str]] = None,
    ) -> ProspectImportResult:
        """Import a CSV file. Raises ProspectImportError on fatal problems."""
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError as exc:
            raise ProspectImportError(f"Could not read file: {exc}") from exc
        return self.import_bytes(raw, source=source, mapping=mapping, filename=path)

    def import_bytes(
        self,
        raw: bytes,
        source: str = "csv_import",
        mapping: Optional[Dict[str, str]] = None,
        filename: str = "",
    ) -> ProspectImportResult:
        """Import CSV content from bytes (UTF-8, UTF-8 BOM, or latin-1)."""
        text = _decode_csv(raw)
        return self.import_text(text, source=source, mapping=mapping, filename=filename)

    def import_text(
        self,
        text: str,
        source: str = "csv_import",
        mapping: Optional[Dict[str, str]] = None,
        filename: str = "",
    ) -> ProspectImportResult:
        """Import CSV content from a decoded string."""
        rows = _read_all_rows(text)
        headers = _extract_headers(rows)

        if not headers:
            raise ProspectImportError("CSV is empty or has no header row")

        preview = detect_mapping_details(headers)
        active_mapping = dict(mapping) if mapping is not None else preview.mapping
        result = ProspectImportResult(mapping=active_mapping, mapping_details=preview.columns)
        result.unknown_columns = unknown_columns(headers, active_mapping)
        for col in result.unknown_columns:
            result.warnings.append(f"Unknown column ignored: {col!r}")
        for detail in preview.columns:
            if detail.status == MAPPING_AMBIGUOUS:
                result.warnings.append(f"Ambiguous column not auto-mapped: {detail.source_column!r}")

        if "company_name" not in active_mapping:
            raise ProspectImportError(
                "No company-name column found in the CSV header. "
                f"Recognized mapping: {active_mapping}"
            )

        data_rows = rows[1:]
        result.rows_total = len(data_rows)

        for idx, raw_row in enumerate(data_rows):
            row_number = idx + 2  # 1-based incl. header row
            row = _rows_to_dict(headers, raw_row)
            if _is_blank(row):
                result.skipped += 1
                result.rows.append(
                    ProspectRowResult(
                        row_number=row_number,
                        status="skipped",
                        message="blank row",
                        raw_data=dict(row),
                    )
                )
                continue
            row_result = self._process_row(row, active_mapping, source, row_number)
            result.rows.append(row_result)
            if row_result.status == "imported":
                result.imported += 1
            elif row_result.status == "merged":
                result.merged += 1
            elif row_result.status == "invalid":
                result.invalid += 1

        return result
    # ------------------------------------------------------------------
    # Row processing
    # ------------------------------------------------------------------

    def _process_row(
        self,
        row: Dict[str, Any],
        mapping: Dict[str, str],
        source: str,
        row_number: int,
    ) -> ProspectRowResult:
        prospect = _row_to_prospect(row, mapping)
        raw_data = self._safe_raw(row, mapping)

        problems = validate_row(prospect)
        if problems:
            return ProspectRowResult(
                row_number=row_number,
                status="invalid",
                message="; ".join(problems),
                raw_data=raw_data,
            )

        # Preserve unknown columns in metadata.
        if self._preserve_unknown:
            prospect.metadata.setdefault("source_unmapped", {})
            prospect.metadata.setdefault("source_raw_row", {})
            for header, value in row.items():
                text_value = str(value or "")
                if len(text_value) <= 10000:
                    prospect.metadata["source_raw_row"][header] = text_value
            for header in _unknown_headers(row, mapping):
                value = str(row.get(header, "") or "")
                if len(value) <= 10000:
                    prospect.metadata[f"raw_{header}"] = value
                    prospect.metadata["source_unmapped"][header] = value

        # Provenance.
        if not prospect.source:
            prospect.source = source

        # Exact duplicate -> merge into existing (preserve id).
        existing = self._store.find_duplicate(prospect)
        if existing is not None:
            self._store.merge(existing, prospect)
            return ProspectRowResult(
                row_number=row_number,
                status="merged",
                prospect_id=existing.prospect_id,
                message="exact duplicate merged",
                raw_data=raw_data,
            )

        # Possible duplicates: report but do NOT auto-merge.
        possible = self._store.check_possible_duplicates(prospect)
        new_prospect = self._store.create(prospect)
        message = "imported"
        if possible:
            message = (
                "imported (possible duplicate: "
                + ", ".join(p.prospect_id for p in possible)
                + ")"
            )
        return ProspectRowResult(
            row_number=row_number,
            status="imported",
            prospect_id=new_prospect.prospect_id,
            message=message,
            raw_data=raw_data,
        )

    def _safe_raw(
        self, row: Dict[str, Any], mapping: Dict[str, str]
    ) -> Dict[str, Any]:
        """Return a safe, serializable subset of the raw row for reporting."""
        safe: Dict[str, Any] = {}
        for canon, header in mapping.items():
            if canon != "notes":
                safe[canon] = str(row.get(header, "") or "").strip()
        return safe
# ---------------------------------------------------------------------------
# Internal parse helpers
# ---------------------------------------------------------------------------


def _decode_csv(raw: bytes) -> str:
    """Decode CSV bytes handling UTF-8 BOM, UTF-8, and latin-1 fallback."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # Lenient fallback so a bad encoding still yields a readable import.
        return raw.decode("latin-1")


def _read_all_rows(text: str) -> List[List[str]]:
    """Parse CSV text into a list of rows (each a list of cell strings)."""
    reader = csv.reader(io.StringIO(text))
    rows: List[List[str]] = []
    for row in reader:
        cells = [str(c) if c is not None else "" for c in row]
        rows.append(cells)
    return rows


def _extract_headers(rows: List[List[str]]) -> List[str]:
    """Return the first non-blank row as headers (empty list if none)."""
    for row in rows:
        stripped = [str(c).strip() for c in row]
        if any(stripped):
            return stripped
    return []


def _rows_to_dict(headers: List[str], raw_row: List[str]) -> Dict[str, Any]:
    """Map a raw row (list of cells) to a dict keyed by header.

    Duplicate headers: the FIRST occurrence wins (matching the mapping
    detection, which also uses the first occurrence). Ragged rows are handled
    (missing cells -> empty string; extra cells ignored).
    """
    result: Dict[str, Any] = {}
    for i, header in enumerate(headers):
        if header in result:
            continue  # first occurrence wins for duplicate headers
        value = raw_row[i] if i < len(raw_row) else ""
        result[header] = value
    return result


def _is_blank(row: Dict[str, Any]) -> bool:
    """True when every cell in the row is blank/whitespace."""
    return all(not str(v or "").strip() for v in row.values())


def _unknown_headers(
    row: Dict[str, Any], mapping: Dict[str, str]
) -> List[str]:
    """Return the raw headers in a row that are not part of the active mapping."""
    mapped = set(mapping.values())
    return [h for h in row.keys() if h not in mapped and str(h).strip() != ""]