"""Authoritative value resolution for personalization/export fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.person_personalization import PersonFacts
from gui.models.personalization_field_catalog import FIELD_DEFINITIONS_BY_KEY, serialize_field_value
from gui.models.prospect import Prospect
from gui.models.prospect_generation import ProspectGenerationJob
from gui.models.project import Project
from gui.services.profile_resolver import effective_scrape_url


def _clean(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class PersonalizationFieldContext:
    prospect: Prospect | None = None
    generation_job: ProspectGenerationJob | None = None
    project: Project | None = None
    handoff_fields: dict[str, str] | None = None
    mockup_url: str = ""
    campaign_run_id: str = ""


def _brand_profile(project: Project | None) -> dict[str, Any]:
    raw = getattr(project, "brand_profile", None)
    return dict(raw) if isinstance(raw, dict) else {}


def _person_facts(project: Project | None) -> PersonFacts:
    return PersonFacts.from_dict(_brand_profile(project).get("person_facts"))


def _latest_concept(project: Project | None) -> dict[str, Any]:
    concepts = list(getattr(project, "ad_concepts", None) or [])
    if concepts and isinstance(concepts[-1], dict):
        return dict(concepts[-1])
    mockups = list(getattr(project, "concepts", None) or [])
    if mockups:
        concept = mockups[-1]
        return {
            "headline": getattr(concept, "headline", ""),
            "cta": getattr(concept, "cta", ""),
        }
    return {}


def _metadata_value(job: ProspectGenerationJob | None, key: str) -> object:
    metadata = dict(getattr(job, "metadata", None) or {}) if job is not None else {}
    if key in metadata:
        return metadata.get(key)
    personalization = metadata.get("personalization")
    if isinstance(personalization, dict) and key in personalization:
        return personalization.get(key)
    person_facts = metadata.get("person_facts")
    if isinstance(person_facts, dict) and key in person_facts:
        return person_facts.get(key)
    return ""


def get_personalization_field_value(field_key: str, context: PersonalizationFieldContext) -> str:
    """Resolve one catalog field from persisted export context.

    Resolution is additive and read-only. Existing handoff CSV values win for
    legacy/default columns, then persisted Prospect/Job/Project/BrandProfile data
    fill opt-in personalization fields.
    """
    key = _clean(field_key)
    if key not in FIELD_DEFINITIONS_BY_KEY:
        return ""
    fields = dict(context.handoff_fields or {})
    prospect = context.prospect
    job = context.generation_job
    project = context.project
    profile = _brand_profile(project)
    facts = _person_facts(project)
    concept = _latest_concept(project)

    if key in fields and key not in {"profile_url", "professional_title", "location", "service_area", "years_experience", "specialties", "services", "credentials", "awards_or_roles", "bio_summary", "person_tagline", "personalization_angle"}:
        return serialize_field_value(fields.get(key))

    value: object = ""
    if key == "email":
        value = fields.get("email") or getattr(prospect, "email", "")
    elif key == "first_name":
        value = fields.get("first_name") or _clean(getattr(prospect, "contact_name", "")).split(" ")[0]
    elif key == "contact_name":
        value = fields.get("contact_name") or getattr(prospect, "contact_name", "") or facts.contact_name
    elif key == "company":
        value = fields.get("company") or getattr(prospect, "company_name", "") or profile.get("company_name")
    elif key == "website":
        value = fields.get("website") or getattr(prospect, "website", "") or profile.get("website")
    elif key == "category":
        value = fields.get("category") or getattr(prospect, "category", "")
    elif key == "city":
        value = fields.get("city") or getattr(prospect, "city", "") or getattr(getattr(job, "opportunity_context", None), "city", "")
    elif key == "state":
        value = fields.get("state") or getattr(prospect, "state", "") or getattr(getattr(job, "opportunity_context", None), "state", "")
    elif key == "profile_url":
        value = facts.profile_url or _metadata_value(job, "profile_url") or (effective_scrape_url(prospect) if prospect is not None else "")
    elif key == "professional_title":
        value = facts.professional_title or getattr(prospect, "contact_title", "") or _metadata_value(job, "professional_title")
    elif key == "location":
        value = facts.location or profile.get("location") or ", ".join(p for p in [getattr(prospect, "city", ""), getattr(prospect, "state", "")] if _clean(p))
    elif key == "service_area":
        value = facts.service_area or profile.get("service_area") or _metadata_value(job, "service_area")
    elif key == "years_experience":
        value = facts.years_experience or _metadata_value(job, "years_experience")
    elif key == "specialties":
        value = facts.specialties or _metadata_value(job, "specialties")
    elif key == "services":
        value = facts.services or profile.get("services") or _metadata_value(job, "services")
    elif key == "credentials":
        value = facts.credentials or profile.get("certifications") or _metadata_value(job, "credentials")
    elif key == "awards_or_roles":
        value = facts.awards_or_roles or profile.get("awards") or _metadata_value(job, "awards_or_roles")
    elif key == "bio_summary":
        value = facts.bio_summary or profile.get("profile_summary") or _metadata_value(job, "bio_summary")
    elif key == "person_tagline":
        value = facts.person_tagline or _metadata_value(job, "person_tagline")
    elif key == "personalization_angle":
        value = profile.get("personalization_angle") or _metadata_value(job, "personalization_angle")
    elif key == "personalization_basis":
        value = fields.get("personalization_basis") or profile.get("personalization_basis") or _metadata_value(job, "personalization_basis")
    elif key == "headline":
        value = fields.get("headline") or profile.get("personalized_headline") or concept.get("headline") or profile.get("headline")
    elif key == "cta":
        value = fields.get("cta") or profile.get("personalized_cta") or concept.get("cta")
    elif key == "mockup_path":
        value = fields.get("mockup_path") or fields.get("mockup_relative_path") or getattr(job, "result_path", "")
    elif key == "mockup_url":
        value = context.mockup_url
    elif key == "prospect_id":
        value = fields.get("prospect_id") or getattr(prospect, "prospect_id", "")
    elif key == "project_id":
        value = fields.get("project_id") or getattr(job, "project_id", "") or getattr(project, "id", "")
    elif key == "generation_job_id":
        value = fields.get("generation_job_id") or getattr(job, "id", "")
    elif key == "email_subject":
        value = fields.get("email_subject")
    elif key == "email_body":
        value = fields.get("email_body")

    return serialize_field_value(value)


def personalization_field_available(field_key: str, context: PersonalizationFieldContext) -> bool:
    return bool(get_personalization_field_value(field_key, context))


def personalization_preview_rows(mapping: list, context: PersonalizationFieldContext) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in mapping:
        if not getattr(item, "enabled", False):
            continue
        rows.append(
            {
                "field_key": item.field_key,
                "export_name": item.export_name,
                "example": get_personalization_field_value(item.field_key, context),
            }
        )
    return rows
