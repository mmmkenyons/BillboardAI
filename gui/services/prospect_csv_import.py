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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column aliases (canonical field -> accepted header names).
# ---------------------------------------------------------------------------

COLUMN_ALIASES: Dict[str, tuple] = {
    "company_name": ("company", "company_name", "business", "business_name"),
    "website": ("website", "url", "domain", "website_url"),
    "phone": ("phone", "phone_number", "telephone"),
    "email": ("email", "email_address"),
    "address": ("address", "street", "street_address"),
    "city": ("city", "town"),
    "state": ("state", "province"),
    "postal_code": ("postal_code", "zip", "zip_code", "postcode"),
    "category": ("category", "industry", "business_type"),
    "subcategory": ("subcategory", "niche"),
    "contact_name": ("contact", "contact_name", "name", "primary_contact"),
    "contact_title": ("title", "contact_title", "job_title"),
    "source": ("source", "lead_source"),
    "source_id": ("source_id", "external_id", "id"),
    "notes": ("notes", "comment", "comments"),
    "tags": ("tags", "tag", "labels"),
    "market_id": ("market_id", "market"),
    "location_hint": ("location_hint", "location"),
    "priority": ("priority", "lead_score"),
    "research_status": ("research_status", "status"),
}

# Canonical field names accepted by the mapping.
CANONICAL_FIELDS = tuple(COLUMN_ALIASES.keys())

# Build a reverse lookup: lowercase header -> canonical field.
_ALIAS_TO_CANON: Dict[str, str] = {}
for _canon, _aliases in COLUMN_ALIASES.items():
    _ALIAS_TO_CANON[_canon] = _canon
    for _alias in _aliases:
        _ALIAS_TO_CANON[_alias.lower()] = _canon


def canonical_for_header(header: str) -> Optional[str]:
    """Return the canonical prospect field for a raw CSV header, or None."""
    key = str(header or "").strip().lower()
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
    mapping: Dict[str, str] = {}
    for header in headers:
        canon = canonical_for_header(header)
        if canon is None:
            continue
        # First occurrence wins; later duplicates are ignored.
        if canon not in mapping:
            mapping[canon] = header
    return mapping


def unknown_columns(headers: List[str], mapping: Dict[str, str]) -> List[str]:
    """Return headers that were not recognized as any canonical field."""
    mapped = set(mapping.values())
    return [h for h in headers if h not in mapped and str(h).strip() != ""]


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
        return str(row.get(header, "") or "").strip()

    website_raw = _val("website")
    website = normalize_website(website_raw)
    domain = normalize_domain(website_raw) or normalize_domain(website)
    email_raw = _val("email")
    phone_raw = _val("phone")
    state = normalize_state(_val("state"))
    subcategory = _val("subcategory")

    prospect = Prospect(
        company_name=normalize_company_name(_val("company_name")),
        website=website,
        domain=domain,
        phone=normalize_phone(phone_raw),
        email=normalize_email(email_raw),
        address=_val("address"),
        city=_val("city"),
        state=state,
        postal_code=_val("postal_code"),
        category=normalize_category(_val("category")),
        subcategory=subcategory.strip().lower() if subcategory else "",
        contact_name=_val("contact_name"),
        contact_title=_val("contact_title"),
        source=_val("source"),
        source_id=_val("source_id"),
        notes=_val("notes"),
        tags=normalize_tags(_val("tags")),
        market_id=_val("market_id"),
        location_hint=_val("location_hint"),
        priority=_val("priority"),
        research_status=_val("research_status"),
    )

    # Status: READY_FOR_RESEARCH only when a usable website/domain exists.
    if prospect.is_ready_for_research():
        prospect.status = STATUS_READY_FOR_RESEARCH
    else:
        prospect.status = STATUS_IMPORTED

    # Build a primary contact from the row's contact fields when any present.
    if _val("contact_name") or _val("contact_title") or email_raw or phone_raw:
        prospect.contacts.append(
            Contact(
                prospect_id=prospect.prospect_id,
                name=_val("contact_name"),
                title=_val("contact_title"),
                email=prospect.email,
                phone=prospect.phone,
                is_primary=True,
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

        active_mapping = dict(mapping) if mapping is not None else detect_mapping(headers)
        result = ProspectImportResult(mapping=active_mapping)
        result.unknown_columns = unknown_columns(headers, active_mapping)
        for col in result.unknown_columns:
            result.warnings.append(f"Unknown column ignored: {col!r}")

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
            for header in _unknown_headers(row, mapping):
                prospect.metadata[f"raw_{header}"] = str(row.get(header, "") or "")

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