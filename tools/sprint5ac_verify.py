"""Sprint 5AC verifier: personalization field catalog + Smartlead mapping.

No network, Smartlead API, scraping, generation, hosting, campaign publishing, or
activation is performed. Runtime data is created under a temporary directory.
"""

from __future__ import annotations

import csv
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.personalization_field_catalog import (  # noqa: E402
    DEFAULT_REQUIRED_EXPORT_COLUMNS,
    PersonalizationFieldMapping,
    PersonalizationFieldMappingStore,
    default_personalization_mapping,
    serialize_field_value,
)
from tests.test_sprint5y_smartlead_export import _prepare_run, _ready_prospect, _runtime  # noqa: E402


def check(name: str, ok: bool, counts: dict[str, int], detail: object = "") -> None:
    if ok:
        counts["passed"] += 1
        print(f"PASS {name}")
    else:
        counts["failed"] += 1
        print(f"FAIL {name}: {detail}")


def read_rows(path: str) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_header(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def enable(service, *keys: str, rename: dict[str, str] | None = None, disabled: set[str] | None = None) -> None:
    rename = dict(rename or {})
    disabled = set(disabled or set())
    enabled = set(keys)
    mapping = []
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


def add_person_profile(project) -> None:
    project.brand_profile = {
        "person_facts": {
            "years_experience": "18",
            "specialties": ["relocation", "commercial"],
            "bio_summary": "Experienced relocation specialist.",
            "profile_url": "https://profiles.example/alice",
        },
        "personalization_angle": "EXPERIENCE",
        "personalization_basis": ["18 years", "relocation"],
    }


def main() -> int:
    counts = {"passed": 0, "failed": 0}
    root = tempfile.mkdtemp(prefix="sprint5ac_verify_")
    try:
        c = _runtime(root)
        _a, project, _concept = _ready_prospect(c, "a", "A Co", "a@example.com")
        _ready_prospect(c, "b", "B Co", "b@example.com")
        add_person_profile(project)
        c["project_store"].save(project)
        run = _prepare_run(c["run_service"], c["run_handoff"], "Alpha", ["a"])

        default_result = c["export_svc"].export_run(run.id)
        check("default schema unchanged", read_header(default_result.smartlead_csv_path) == list(DEFAULT_REQUIRED_EXPORT_COLUMNS), counts)

        enable(c["export_svc"], "years_experience", "specialties", "personalization_angle", rename={"years_experience": "bb_years"})
        custom_result = c["export_svc"].export_run(run.id)
        rows = read_rows(custom_result.smartlead_csv_path)
        header = read_header(custom_result.smartlead_csv_path)
        check("custom field enable", "specialties" in header, counts, header)
        check("rename mapping", "bb_years" in header and rows[0]["bb_years"] == "18", counts, rows[0])
        check("person facts exported", rows[0]["specialties"] == "relocation; commercial", counts, rows[0])
        check("personalization angle exported", rows[0]["personalization_angle"] == "EXPERIENCE", counts, rows[0])
        check("deterministic list serialization", serialize_field_value(["relocation", "historical homes", "commercial"]) == "relocation; historical homes; commercial", counts)

        enable(c["export_svc"], disabled={"specialties"})
        disabled_result = c["export_svc"].export_run(run.id)
        check("custom field disable", "specialties" not in read_header(disabled_result.smartlead_csv_path), counts)

        store_path = os.path.join(root, "mapping_restart.json")
        store = PersonalizationFieldMappingStore(path=store_path)
        mapping = default_personalization_mapping()
        mapping[-1] = PersonalizationFieldMapping("personalization_angle", "angle", enabled=True, position=mapping[-1].position)
        store.save(mapping)
        loaded = PersonalizationFieldMappingStore(path=store_path).load_or_default()
        check("mapping restart persistence", any(m.field_key == "personalization_angle" and m.export_name == "angle" and m.enabled for m in loaded), counts)
        with open(store_path, "w", encoding="utf-8") as handle:
            handle.write("corrupt")
        fallback = PersonalizationFieldMappingStore(path=store_path).load_or_default()
        check("corrupt mapping fallback", [m.export_name for m in fallback if m.enabled] == list(DEFAULT_REQUIRED_EXPORT_COLUMNS), counts)
        try:
            store.save(mapping + [PersonalizationFieldMapping("bio_summary", "email", True, 999)])
        except ValueError:
            duplicate_rejected = True
        else:
            duplicate_rejected = False
        check("duplicate-name rejection", duplicate_rejected, counts)

        check("run isolation", {r["prospect_id"] for r in rows} == {"a"}, counts, rows)
        handoff_dir = c["run_handoff"].context_for_run(run.id).package_record.handoff_directory
        before = sorted(os.listdir(handoff_dir))
        c["export_svc"].export_run(run.id)
        check("no external side effects", sorted(os.listdir(handoff_dir)) == before, counts)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"Sprint 5AC verifier: {counts['passed']} passed, {counts['failed']} failed")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
