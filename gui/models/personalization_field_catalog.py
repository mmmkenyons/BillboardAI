"""Personalization/export field catalog and Smartlead mapping foundation.

This module is intentionally compact: it defines the exportable BillboardAI
personalization field catalog, default Smartlead-compatible mapping, validation,
and durable local persistence for operator-selected mappings.  It does not call
Smartlead APIs and does not prepare, host, upload, or activate anything.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from typing import Any

from gui.models.smartlead_handoff import DEFAULT_SMARTLEAD_COLUMN_ORDER
from gui.models.smartlead_run_export import SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN

CATEGORY_IDENTITY = "IDENTITY"
CATEGORY_BUSINESS = "BUSINESS"
CATEGORY_LOCATION = "LOCATION"
CATEGORY_PROFILE = "PROFILE"
CATEGORY_PERSON_FACT = "PERSON_FACT"
CATEGORY_DERIVED_PERSONALIZATION = "DERIVED_PERSONALIZATION"
CATEGORY_GENERATED_COPY = "GENERATED_COPY"
CATEGORY_CREATIVE = "CREATIVE"
CATEGORY_SYSTEM = "SYSTEM"

SOURCE_FACT = "SOURCE_FACT"
SOURCE_DERIVED = "DERIVED"
SOURCE_GENERATED = "GENERATED"
SOURCE_SYSTEM = "SYSTEM"

DATA_TEXT = "TEXT"
DATA_LIST = "LIST"
DATA_URL = "URL"
DATA_ID = "ID"

DEFAULT_PERSONALIZATION_MAPPING_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "smartlead",
)
DEFAULT_PERSONALIZATION_MAPPING_PATH = os.path.join(
    DEFAULT_PERSONALIZATION_MAPPING_DIR,
    "personalization_field_mapping.json",
)


def _clean(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class PersonalizationFieldDefinition:
    key: str
    label: str
    category: str
    description: str
    default_export_name: str
    source_type: str
    data_type: str = DATA_TEXT
    is_default: bool = False
    is_required: bool = False
    is_sensitive: bool = False
    is_available: bool = True
    supports_smartlead: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersonalizationFieldMapping:
    field_key: str
    export_name: str
    enabled: bool = False
    position: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_key": self.field_key,
            "export_name": self.export_name,
            "enabled": bool(self.enabled),
            "position": int(self.position),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PersonalizationFieldMapping":
        raw = data if isinstance(data, dict) else {}
        try:
            position = int(raw.get("position") or 0)
        except (TypeError, ValueError):
            position = 0
        return cls(
            field_key=_clean(raw.get("field_key")),
            export_name=normalize_export_name(raw.get("export_name")),
            enabled=bool(raw.get("enabled", False)),
            position=position,
        )


def _field(
    key: str,
    label: str,
    category: str,
    description: str,
    source_type: str,
    *,
    export_name: str | None = None,
    data_type: str = DATA_TEXT,
    is_default: bool = False,
    is_required: bool = False,
    is_sensitive: bool = False,
) -> PersonalizationFieldDefinition:
    return PersonalizationFieldDefinition(
        key=key,
        label=label,
        category=category,
        description=description,
        default_export_name=export_name or key,
        source_type=source_type,
        data_type=data_type,
        is_default=is_default,
        is_required=is_required,
        is_sensitive=is_sensitive,
    )


FIELD_CATALOG: tuple[PersonalizationFieldDefinition, ...] = (
    _field("email", "Email", CATEGORY_IDENTITY, "Lead email address.", SOURCE_FACT, is_default=True, is_required=True, is_sensitive=True),
    _field("first_name", "First Name", CATEGORY_IDENTITY, "Lead first name.", SOURCE_DERIVED, is_default=True),
    _field("contact_name", "Contact Name", CATEGORY_IDENTITY, "Full contact/person name.", SOURCE_FACT, is_default=True),
    _field("company", "Company", CATEGORY_BUSINESS, "Business/company name.", SOURCE_FACT, is_default=True),
    _field("website", "Website", CATEGORY_BUSINESS, "Parent business website.", SOURCE_FACT, data_type=DATA_URL, is_default=True),
    _field("email_subject", "Email Subject", CATEGORY_GENERATED_COPY, "Generated email subject.", SOURCE_GENERATED, is_default=True, is_required=True),
    _field("email_body", "Email Body", CATEGORY_GENERATED_COPY, "Generated email body.", SOURCE_GENERATED, is_default=True, is_required=True),
    _field("category", "Category", CATEGORY_BUSINESS, "Business category.", SOURCE_FACT, is_default=True),
    _field("city", "City", CATEGORY_LOCATION, "Business/opportunity city.", SOURCE_FACT, is_default=True),
    _field("state", "State", CATEGORY_LOCATION, "Business/opportunity state.", SOURCE_FACT, is_default=True),
    _field("location", "Location", CATEGORY_LOCATION, "Person/business location text.", SOURCE_FACT),
    _field("service_area", "Service Area", CATEGORY_LOCATION, "Service-area text from source facts.", SOURCE_FACT),
    _field("profile_url", "Profile URL", CATEGORY_PROFILE, "Manual/resolved/effective person profile URL.", SOURCE_FACT, data_type=DATA_URL),
    _field("professional_title", "Professional Title", CATEGORY_PERSON_FACT, "Person professional title.", SOURCE_FACT),
    _field("years_experience", "Years Experience", CATEGORY_PERSON_FACT, "Evidence-backed years of experience.", SOURCE_FACT),
    _field("specialties", "Specialties", CATEGORY_PERSON_FACT, "Evidence-backed person specialties.", SOURCE_FACT, data_type=DATA_LIST),
    _field("services", "Services", CATEGORY_PERSON_FACT, "Evidence-backed services.", SOURCE_FACT, data_type=DATA_LIST),
    _field("credentials", "Credentials", CATEGORY_PERSON_FACT, "Evidence-backed credentials/certifications.", SOURCE_FACT, data_type=DATA_LIST),
    _field("awards_or_roles", "Awards or Roles", CATEGORY_PERSON_FACT, "Evidence-backed awards or roles.", SOURCE_FACT, data_type=DATA_LIST),
    _field("bio_summary", "Bio Summary", CATEGORY_PERSON_FACT, "Short profile/bio summary.", SOURCE_FACT),
    _field("person_tagline", "Person Tagline", CATEGORY_DERIVED_PERSONALIZATION, "Derived person-aware tagline.", SOURCE_DERIVED),
    _field("personalization_angle", "Personalization Angle", CATEGORY_DERIVED_PERSONALIZATION, "Selected personalization angle.", SOURCE_DERIVED),
    _field("personalization_basis", "Personalization Basis", CATEGORY_DERIVED_PERSONALIZATION, "Evidence/basis for generated personalization.", SOURCE_DERIVED, data_type=DATA_LIST, is_default=True),
    _field("headline", "Headline", CATEGORY_GENERATED_COPY, "Generated billboard headline.", SOURCE_GENERATED, is_default=True),
    _field("cta", "CTA", CATEGORY_GENERATED_COPY, "Generated call to action.", SOURCE_GENERATED, is_default=True),
    _field("mockup_path", "Mockup Path", CATEGORY_CREATIVE, "Local packaged mockup path.", SOURCE_SYSTEM, export_name="mockup_path", data_type=DATA_URL, is_default=True),
    _field("mockup_url", "Mockup URL", CATEGORY_CREATIVE, "Hosted public mockup URL from receipt.", SOURCE_SYSTEM, data_type=DATA_URL, is_default=True),
    _field("prospect_id", "Prospect ID", CATEGORY_SYSTEM, "BillboardAI prospect id.", SOURCE_SYSTEM, data_type=DATA_ID, is_default=True),
    _field("project_id", "Project ID", CATEGORY_SYSTEM, "BillboardAI project id.", SOURCE_SYSTEM, data_type=DATA_ID, is_default=True),
    _field("generation_job_id", "Generation Job ID", CATEGORY_SYSTEM, "BillboardAI generation job id.", SOURCE_SYSTEM, data_type=DATA_ID, is_default=True),
)

FIELD_DEFINITIONS_BY_KEY: dict[str, PersonalizationFieldDefinition] = {field.key: field for field in FIELD_CATALOG}

DEFAULT_REQUIRED_EXPORT_COLUMNS: tuple[str, ...] = (
    tuple(DEFAULT_SMARTLEAD_COLUMN_ORDER[:6])
    + (SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN,)
    + tuple(DEFAULT_SMARTLEAD_COLUMN_ORDER[6:])
)

DEFAULT_OPTIONAL_FIELD_ORDER: tuple[str, ...] = (
    "profile_url",
    "professional_title",
    "location",
    "service_area",
    "years_experience",
    "specialties",
    "services",
    "credentials",
    "awards_or_roles",
    "bio_summary",
    "person_tagline",
    "personalization_angle",
)


def list_personalization_fields() -> list[PersonalizationFieldDefinition]:
    return list(FIELD_CATALOG)


def normalize_export_name(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    return "_".join(text.split())


def serialize_field_value(value: object) -> str:
    """Serialize structured values for CSV deterministically.

    Lists/tuples/sets are emitted as semicolon-separated human-readable values;
    Python list reprs are never written.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        items = [_clean(item) for item in value]
        return "; ".join(item for item in items if item)
    return _clean(value)


def default_personalization_mapping() -> list[PersonalizationFieldMapping]:
    mappings: list[PersonalizationFieldMapping] = []
    position = 0
    for column in DEFAULT_REQUIRED_EXPORT_COLUMNS:
        key = "mockup_path" if column == "mockup_path" else column
        mappings.append(PersonalizationFieldMapping(field_key=key, export_name=column, enabled=True, position=position))
        position += 1
    for key in DEFAULT_OPTIONAL_FIELD_ORDER:
        definition = FIELD_DEFINITIONS_BY_KEY[key]
        mappings.append(
            PersonalizationFieldMapping(
                field_key=key,
                export_name=definition.default_export_name,
                enabled=False,
                position=position,
            )
        )
        position += 1
    return mappings


def enabled_mappings_in_order(mapping: list[PersonalizationFieldMapping]) -> list[PersonalizationFieldMapping]:
    return [item for item in sorted(mapping, key=lambda m: (m.position, m.field_key)) if item_is_enabled(item)]


def item_is_enabled(item: PersonalizationFieldMapping) -> bool:
    return bool(item.enabled)


def validate_personalization_mapping(mapping: list[PersonalizationFieldMapping]) -> None:
    known = set(FIELD_DEFINITIONS_BY_KEY)
    seen: dict[str, str] = {}
    required = set(DEFAULT_REQUIRED_EXPORT_COLUMNS)
    enabled_required: set[str] = set()
    for item in mapping:
        if item.field_key not in known:
            raise ValueError(f"Unknown personalization field: {item.field_key}.")
        export_name = normalize_export_name(item.export_name)
        if item.enabled:
            if not export_name:
                raise ValueError(f"Export column name is required for {item.field_key}.")
            if any(ch in export_name for ch in "\r\n\t") or any(ord(ch) < 32 for ch in export_name):
                raise ValueError(f"Export column name contains illegal control characters: {export_name!r}.")
            key = export_name.lower()
            if key in seen:
                raise ValueError(f"Duplicate enabled export column name is not allowed: {export_name}.")
            seen[key] = item.field_key
            if export_name in required:
                if item.field_key not in {export_name, "mockup_path"}:
                    raise ValueError(f"Optional field {item.field_key} cannot map to reserved column {export_name}.")
                enabled_required.add(export_name)
    missing = [column for column in DEFAULT_REQUIRED_EXPORT_COLUMNS if column not in enabled_required]
    if missing:
        raise ValueError(f"Required Smartlead export columns cannot be disabled: {', '.join(missing)}.")


def mapping_fingerprint(mapping: list[PersonalizationFieldMapping]) -> str:
    payload = [item.to_dict() for item in sorted(mapping, key=lambda m: (m.position, m.field_key))]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class PersonalizationFieldMappingStore:
    def __init__(self, path: str | None = None) -> None:
        self._path = os.path.abspath(path or DEFAULT_PERSONALIZATION_MAPPING_PATH)

    @property
    def path(self) -> str:
        return self._path

    def load_or_default(self) -> list[PersonalizationFieldMapping]:
        if not os.path.exists(self._path):
            return default_personalization_mapping()
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            raw_items = list((payload or {}).get("mapping") or [])
            loaded = [PersonalizationFieldMapping.from_dict(item) for item in raw_items if isinstance(item, dict)]
            merged = self._merge_with_defaults(loaded)
            validate_personalization_mapping(merged)
            return merged
        except Exception:
            return default_personalization_mapping()

    def save(self, mapping: list[PersonalizationFieldMapping]) -> None:
        normalized = [
            PersonalizationFieldMapping(
                field_key=item.field_key,
                export_name=normalize_export_name(item.export_name),
                enabled=bool(item.enabled),
                position=int(item.position),
            )
            for item in mapping
        ]
        validate_personalization_mapping(normalized)
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        payload = {
            "schema_version": 1,
            "mapping": [item.to_dict() for item in sorted(normalized, key=lambda m: (m.position, m.field_key))],
            "fingerprint": mapping_fingerprint(normalized),
        }
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, self._path)

    @staticmethod
    def _merge_with_defaults(loaded: list[PersonalizationFieldMapping]) -> list[PersonalizationFieldMapping]:
        defaults = default_personalization_mapping()
        by_key = {item.field_key: item for item in loaded if item.field_key}
        merged: list[PersonalizationFieldMapping] = []
        for default in defaults:
            override = by_key.get(default.field_key)
            if override is None:
                merged.append(default)
                continue
            merged.append(
                PersonalizationFieldMapping(
                    field_key=default.field_key,
                    export_name=normalize_export_name(override.export_name) or default.export_name,
                    enabled=bool(override.enabled),
                    position=int(override.position or default.position),
                )
            )
        return sorted(merged, key=lambda m: (m.position, m.field_key))
