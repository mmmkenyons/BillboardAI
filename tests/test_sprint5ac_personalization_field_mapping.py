from __future__ import annotations

import csv
import json
import os

from gui.models.personalization_field_catalog import (
    DEFAULT_REQUIRED_EXPORT_COLUMNS,
    PersonalizationFieldMapping,
    PersonalizationFieldMappingStore,
    default_personalization_mapping,
    serialize_field_value,
)
from gui.models.smartlead_handoff import DEFAULT_SMARTLEAD_COLUMN_ORDER
from gui.models.smartlead_run_export import SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN
from tests.test_sprint5y_smartlead_export import _hosted, _prepare_run, _ready_prospect, _runtime


def _read_header(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def _read_rows(path: str) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _enable(service, *keys: str, rename: dict[str, str] | None = None, disabled: set[str] | None = None):
    rename = dict(rename or {})
    disabled = set(disabled or set())
    mapping = []
    enabled = set(keys)
    for item in service.get_field_mapping():
        mapping.append(
            PersonalizationFieldMapping(
                field_key=item.field_key,
                export_name=rename.get(item.field_key, item.export_name),
                enabled=(item.enabled or item.field_key in enabled) and item.field_key not in disabled,
                position=item.position,
            )
        )
    service.save_field_mapping(mapping)


def _person_profile(project):
    project.brand_profile = {
        "person_facts": {
            "contact_name": "Alice Owner",
            "professional_title": "Broker Associate",
            "profile_url": "https://profiles.example/alice",
            "years_experience": "18",
            "specialties": ["relocation", "commercial"],
            "services": ["buyer representation"],
            "credentials": ["CRS"],
            "awards_or_roles": ["team lead"],
            "bio_summary": "Experienced relocation specialist.",
            "person_tagline": "Local relocation guide",
        },
        "personalization_angle": "EXPERIENCE",
        "personalization_basis": ["18 years", "relocation"],
        "personalized_headline": "18 Years Helping Movers",
        "personalized_cta": "Call Alice",
        "profile_summary": "Experienced relocation specialist.",
    }


def test_default_mapping_preserves_current_export_schema(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])

    result = c["export_svc"].export_run(run.id)

    assert result.success
    assert _read_header(result.smartlead_csv_path) == list(DEFAULT_SMARTLEAD_COLUMN_ORDER[:6]) + [SMARTLEAD_EXPORT_MOCKUP_URL_COLUMN] + list(DEFAULT_SMARTLEAD_COLUMN_ORDER[6:])


def test_optional_enriched_fields_can_be_enabled_disabled_and_renamed(tmp_path):
    c = _runtime(tmp_path)
    prospect, project, _concept = _ready_prospect(c, "a", "A Co", "a@example.com")
    _person_profile(project)
    c["project_store"].save(project)
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])

    _enable(c["export_svc"], "years_experience", "specialties", "bio_summary", rename={"years_experience": "bb_years"}, disabled={"bio_summary"})
    result = c["export_svc"].export_run(run.id)
    rows = _read_rows(result.smartlead_csv_path)

    header = _read_header(result.smartlead_csv_path)
    assert "bb_years" in header
    assert "specialties" in header
    assert "bio_summary" not in header
    assert rows[0]["bb_years"] == "18"
    assert rows[0]["specialties"] == "relocation; commercial"


def test_duplicate_export_names_rejected(tmp_path):
    store = PersonalizationFieldMappingStore(path=os.path.join(str(tmp_path), "mapping.json"))
    mapping = default_personalization_mapping()
    broken = list(mapping)
    broken[-1] = PersonalizationFieldMapping("personalization_angle", "email", enabled=True, position=999)

    try:
        store.save(broken)
    except ValueError as exc:
        assert "Duplicate" in str(exc) or "reserved" in str(exc)
    else:
        raise AssertionError("duplicate mapping unexpectedly saved")


def test_missing_optional_value_writes_blank_and_does_not_block(tmp_path):
    c = _runtime(tmp_path)
    _ready_prospect(c, "a", "A Co", "a@example.com")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])
    _enable(c["export_svc"], "years_experience")

    result = c["export_svc"].export_run(run.id)
    rows = _read_rows(result.smartlead_csv_path)

    assert result.exported_rows == 1
    assert rows[0]["years_experience"] == ""


def test_profile_url_years_angle_and_bio_export_when_enabled(tmp_path):
    c = _runtime(tmp_path)
    prospect, project, _concept = _ready_prospect(c, "a", "A Co", "a@example.com")
    prospect.manual_profile_url = "https://manual.example/alice"
    c["prospect_store"].save()
    _person_profile(project)
    c["project_store"].save(project)
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])
    _enable(c["export_svc"], "profile_url", "years_experience", "personalization_angle", "bio_summary")

    result = c["export_svc"].export_run(run.id)
    row = _read_rows(result.smartlead_csv_path)[0]

    assert row["profile_url"] == "https://profiles.example/alice"
    assert row["years_experience"] == "18"
    assert row["personalization_angle"] == "EXPERIENCE"
    assert row["bio_summary"] == "Experienced relocation specialist."


def test_mapping_survives_restart_and_corrupt_file_falls_back(tmp_path):
    path = os.path.join(str(tmp_path), "mapping.json")
    store = PersonalizationFieldMappingStore(path=path)
    mapping = list(default_personalization_mapping())
    mapping[-1] = PersonalizationFieldMapping("personalization_angle", "angle", enabled=True, position=mapping[-1].position)
    store.save(mapping)

    loaded = PersonalizationFieldMappingStore(path=path).load_or_default()
    assert any(item.field_key == "personalization_angle" and item.enabled and item.export_name == "angle" for item in loaded)

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("not json")
    fallback = PersonalizationFieldMappingStore(path=path).load_or_default()
    assert [item.export_name for item in fallback if item.enabled] == list(DEFAULT_REQUIRED_EXPORT_COLUMNS)


def test_run_isolation_and_blocked_conflict_excluded_unchanged(tmp_path):
    c = _runtime(tmp_path)
    a, project, _concept = _ready_prospect(c, "a", "A Co", "a@example.com")
    _ready_prospect(c, "b", "B Co", "b@example.com")
    _person_profile(project)
    c["project_store"].save(project)
    run_a = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])
    _enable(c["export_svc"], "years_experience")

    result = c["export_svc"].export_run(run_a.id)
    rows = _read_rows(result.smartlead_csv_path)

    assert [row["prospect_id"] for row in rows] == ["a"]
    assert rows[0]["years_experience"] == "18"


def test_no_prepare_hosting_or_api_side_effects_and_manifest_columns(tmp_path):
    c = _runtime(tmp_path)
    prospect, project, _concept = _ready_prospect(c, "a", "A Co", "a@example.com")
    run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])
    _hosted(c, "a", project, "job-a", "https://cdn.example/a.png")
    handoff_dir = c["run_handoff"].context_for_run(run.id).package_record.handoff_directory
    before = sorted(os.listdir(handoff_dir))
    _enable(c["export_svc"], "personalization_angle")

    result = c["export_svc"].export_run(run.id)

    assert sorted(os.listdir(handoff_dir)) == before
    with open(result.manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    assert "export_columns" in manifest
    assert "field_mapping" in manifest
    assert manifest["export_columns"][0:3] == ["email", "first_name", "company"]


def test_list_serialization_convention():
    assert serialize_field_value(["relocation", "historical homes", "commercial"]) == "relocation; historical homes; commercial"
