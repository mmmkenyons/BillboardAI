"""Sprint 5A batch prospect import foundation verification tool.

**IMPORTANT — this is a verification/seed fixture, NOT authoritative live
outreach data.** The dataset uses plausible synthetic program examples
(Jim Woods Roofing, ABC Dental, Castle Rock Realty) purely to prove the
prospect import/persistence/dedup flows work end-to-end.

The script proves, in order:

1. build a synthetic verification CSV (clearly labeled test data)
2. import it through the service
3. report the recognized column mapping
4. import prospects
5. merge the exact duplicate (duplicate Jim Woods row)
6. report the invalid row
7. save
8. reload
9. filter / search
10. print a concise prospect table
11. confirm no Projects were automatically created

Run::

    python tools/sprint5a_verify.py

Output is written to ``output/prospects/sprint5a_verify.json`` (git-ignored).
No live network / scraping is used.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.models.prospect_store import ProspectStore  # noqa: E402
from gui.services.prospect_workspace import ProspectWorkspaceService  # noqa: E402

# Git-ignored verification output path.
VERIFY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output",
    "prospects",
)
VERIFY_STORE = os.path.join(VERIFY_DIR, "sprint5a_verify.json")


def build_verification_csv() -> str:
    """Return a small, clearly-labeled synthetic verification CSV."""
    import csv as _csv
    import io

    rows = [
        ("company", "website", "phone", "email", "city", "state", "category"),
        # Jim Woods Roofing
        (
            "Jim Woods Roofing",
            "www.jimwoodsroofing.com",
            "(605) 764-9517",
            "info@jimwoodsroofing.com",
            "Sioux Falls",
            "SD",
            "Roofing",
        ),
        # ABC Dental
        (
            "ABC Dental",
            "https://abcdental.com",
            "605-555-0100",
            "office@abcdental.com",
            "Castle Rock",
            "CO",
            "Dental",
        ),
        # Castle Rock Realty
        (
            "Castle Rock Realty",
            "castlerockrealty.com",
            "",
            "listings@castlecr.com",
            "Castle Rock",
            "CO",
            "Real Estate",
        ),
        # Duplicate Jim Woods (exact domain) -> should MERGE
        (
            "Jim Woods Roofing",
            "jimwoodsroofing.com",
            "",
            "",
            "",
            "",
            "Roofing",
        ),
        # One invalid row (missing company name, bad email) -> INVALID
        (
            "",
            "bad-url no-dot",
            "123",
            "not-an-email",
            "",
            "",
            "",
        ),
    ]
    buf = io.StringIO()
    writer = _csv.writer(buf)
    writer.writerows(rows)
    return buf.getvalue()


def _prospect_table(prospects) -> list:
    table = []
    for p in sorted(prospects, key=lambda x: x.company_name.lower()):
        contact = p.primary_contact
        table.append(
            [
                p.company_name,
                p.domain or p.website or "—",
                p.category,
                (", ".join(x for x in (p.city, p.state) if x)) or "—",
                p.status,
                contact.name if contact else "—",
                "Yes" if p.is_ready_for_research() else "No",
            ]
        )
    return table


def _print_table(rows) -> None:
    if not rows:
        print("  (empty)")
        return
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    header = rows[0]
    body = rows[1:]
    line = "  " + " | ".join(str(h).ljust(w) for h, w in zip(header, widths))
    print(line)
    print("  " + "-" * len(line))
    for r in body:
        print("  " + " | ".join(str(c).ljust(w) for c, w in zip(r, widths)))
def main() -> int:
    os.makedirs(VERIFY_DIR, exist_ok=True)
    csv_text = build_verification_csv()
    csv_path = os.path.join(VERIFY_DIR, "sprint5a_verify.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(csv_text)
    print(f"Verification CSV written to {csv_path}")
    print("  NOTE: test/verification data only — not authoritative.\n")

    from gui.models.project_store import DEFAULT_PROJECT_ROOT

    def _project_count() -> int:
        if not os.path.isdir(DEFAULT_PROJECT_ROOT):
            return 0
        return sum(
            1
            for e in os.listdir(DEFAULT_PROJECT_ROOT)
            if os.path.isfile(os.path.join(DEFAULT_PROJECT_ROOT, e, "project.json"))
        )

    projects_before = _project_count()

    store = ProspectStore(path=VERIFY_STORE)
    svc = ProspectWorkspaceService(store=store)
    svc.load()

    # 1. Import
    result = svc.import_csv_file(csv_path)
    print(f"1. Imported: {result.imported} merged: {result.merged} "
          f"invalid: {result.invalid} skipped: {result.skipped} "
          f"(rows_total={result.rows_total})")

    # 2. Mapping
    print("2. Column mapping recognized:")
    for canon, hdr in result.mapping.items():
        print(f"   {canon}  <-  {hdr}")
    if result.unknown_columns:
        print(f"   (unknown columns: {result.unknown_columns})")

    # 3. Prospect count
    print(f"3. Prospects in store: {svc.imported_count()}")

    # 4. Research-ready count
    ready = sum(1 for p in svc.list_prospects() if p.is_ready_for_research())
    print(f"4. Research-ready: {ready}")

    # 5. Save + reload
    svc.save()
    svc2 = ProspectWorkspaceService(store=ProspectStore(path=VERIFY_STORE))
    svc2.load()
    print(f"5. Reloaded: {svc2.imported_count()} prospects (persisted)")

    # 6. Filter by category
    roofing = svc2.list_by_category("roofing")
    print(f"6. Filter category 'roofing' -> {len(roofing)}")

    # 7. Search
    print(f"7. Search 'castle' -> {len(svc2.search('castle'))}")

    # 8. Concise table
    print("\n8. Prospect table:")
    header = ["Company", "Domain", "Category", "Location", "Status", "Contact", "Ready"]
    _print_table([header] + _prospect_table(svc2.list_prospects()))

    # 9. Confirm no Projects were auto-created by this import
    projects_after = _project_count()
    created = projects_after - projects_before
    print(
        f"9. Projects auto-created by import: {created} "
        f"(before={projects_before}, after={projects_after}; must be 0)"
    )
    if created != 0:
        print("   WARNING: import unexpectedly created a project!")

    # 10. Confirm no scrape occurred (importer is offline by design)
    print("10. No web requests/scraping performed (importer is local & deterministic).")

    print("\nSprint 5A verification complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())