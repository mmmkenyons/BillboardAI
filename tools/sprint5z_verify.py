"""Sprint 5Z verifier -- individual profile resolution (Qt-free, offline).

Proves the Sprint 5Z enrichment boundary end-to-end over deterministic local
fixtures: person-name profile resolution within a parent website, safe additive
persistence, single-source effective scrape-URL selection, bounded/SSRF safety,
and the new CSV person/agent column aliases. No live network, no Qt.
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.prospect import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_ERROR,
    RESOLUTION_RESOLVED,
    Prospect,
)
from gui.models.prospect_store import ProspectStore
from gui.services.profile_resolver import (
    ProfileResolverService,
    FetchError,
    effective_scrape_url,
    is_safe_url,
)
from gui.services.prospect_csv_import import ProspectCsvImporter, detect_mapping

PARENT = "https://pinnaclerealtyia.com"


def check(name: str, condition: bool, counts: dict[str, int]) -> None:
    print(("PASS" if condition else "FAIL") + f": {name}")
    counts["passed" if condition else "failed"] += 1


class _Pages:
    """Deterministic fake site mirroring a brokerage with an agent directory."""

    def __init__(self, *, dup_strong: bool = False) -> None:
        self.dup_strong = dup_strong
        self.requests: list[str] = []

    def fetch(self, url: str) -> str:
        self.requests.append(url)
        path = url.split("//", 1)[-1]
        path = path.split("/", 1)[1] if "/" in path else "/"
        return self._body("/" + path.strip("/"))

    def _body(self, path: str) -> str:
        if path == "/robots.txt":
            return "User-agent: *\nSitemap: https://pinnaclerealtyia.com/sitemap.xml\n"
        if path in ("/sitemap.xml", "/sitemap_index.xml"):
            return (
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<sitemap><loc>https://pinnaclerealtyia.com/sitemap-agents.xml</loc></sitemap>"
                "<sitemap><loc>https://pinnaclerealtyia.com/sitemap-pages.xml</loc></sitemap>"
                "</sitemapindex>"
            )
        if path == "/sitemap-agents.xml":
            return (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<url><loc>https://pinnaclerealtyia.com/agent/meridith-hoffman</loc></url>"
                "<url><loc>https://pinnaclerealtyia.com/agent/john-doe</loc></url>"
                "</urlset>"
            )
        if path == "/sitemap-pages.xml":
            return (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<url><loc>https://pinnaclerealtyia.com/contact</loc></url>"
                "</urlset>"
            )
        if path == "/":
            return (
                "<html><head><title>Pinnacle Realty</title></head><body>"
                '<a href="/agents">Our Team</a>'
                '<a href="/agent/meridith-hoffman">Meridith Hoffman</a>'
                "</body></html>"
            )
        if path.startswith("/agents"):
            return (
                "<html><body><h1>Our Agents</h1>"
                '<a href="/agent/meridith-hoffman">Meridith Hoffman</a>'
                '<a href="/agent/john-doe">John Doe</a>'
                "</body></html>"
            )
        if path == "/agent/meridith-hoffman":
            note = (
                "Meridith Hoffman is also in training."
                if self.dup_strong
                else "John Doe handles the south corridor."
            )
            return (
                "<html><head><title>Meridith Hoffman | Pinnacle</title></head><body>"
                "<h1>Meridith Hoffman</h1>"
                "<p>Meridith Hoffman is a realtor. Bio: 12 years, farm sales.</p>"
                f"<p>{note}</p>"
                '<p>Email: meridith@pinnaclerealtyia.com</p><img src="/mh.jpg">'
                '<script type="application/ld+json">'
                '{"@type":"Person","name":"Meridith Hoffman"}'
                "</script></body></html>"
            )
        if path == "/agent/john-doe":
            note = (
                "Meridith Hoffman works here too."
                if self.dup_strong
                else "John Doe is our new agent."
            )
            return (
                "<html><head><title>John Doe | Pinnacle</title></head><body>"
                f"<h1>John Doe</h1><p>{note} John Doe covers rural listings.</p>"
                "</body></html>"
            )
        raise FetchError(f"HTTP 404 for {path}")


def _prospect_(*, name: str = "Meridith Hoffman", website: str = PARENT,
               prospect_id: str = "p1") -> Prospect:
    return Prospect(
        prospect_id=prospect_id,
        company_name="Pinnacle Realty IA",
        contact_name=name,
        website=website,
    )


def _verify_resolution(counts: dict[str, int]) -> None:
    site = _Pages()
    service = ProfileResolverService(fetcher=site.fetch)

    # Unique strong match -> RESOLVED / HIGH, correct URL.
    result = service.resolve("Meridith Hoffman", PARENT)
    check("unique profile resolves", result.status == RESOLUTION_RESOLVED, counts)
    check(
        "resolved URL is the agent profile",
        result.resolved_url == "https://pinnaclerealtyia.com/agent/meridith-hoffman",
        counts,
    )
    check("resolved confidence HIGH", result.confidence == CONFIDENCE_HIGH, counts)

    check(
        "discovery stayed on safe hosts",
        all(is_safe_url(r) and "localhost" not in r for r in site.requests),
        counts,
    )

    nf = service.resolve("Nobody Else", PARENT)
    check("no-match is NOT_FOUND", nf.status == "NOT_FOUND", counts)
    check("NOT_FOUND has no URL", nf.resolved_url == "", counts)

    dup = _Pages(dup_strong=True)
    amb = ProfileResolverService(fetcher=dup.fetch).resolve("Meridith Hoffman", PARENT)
    check("multiple strong candidates is AMBIGUOUS",
          amb.status == RESOLUTION_AMBIGUOUS, counts)

    err = service.resolve("Meridith Hoffman", "http://localhost")
    check("unsafe parent is ERROR", err.status == RESOLUTION_ERROR, counts)
    check("first/last-only name rejected",
          service.resolve("Meridith", PARENT).status == RESOLUTION_ERROR, counts)
    check("blank name rejected",
          service.resolve("  ", PARENT).status == RESOLUTION_ERROR, counts)


def _verify_apply_and_effective(counts: dict[str, int]) -> None:
    service = ProfileResolverService(fetcher=_Pages().fetch)
    prospect = _prospect_(website="https://broker.other.com")
    result = service.resolve("Meridith Hoffman", PARENT)
    service.apply_result(prospect, result)
    check("apply preserves parent website",
          prospect.website == "https://broker.other.com", counts)
    check("apply sets RESOLVED",
          prospect.resolution_status == RESOLUTION_RESOLVED, counts)
    check(
        "apply writes resolved profile URL",
        prospect.resolved_profile_url == "https://pinnaclerealtyia.com/agent/meridith-hoffman",
        counts,
    )
    check("apply records evidence metadata",
          "profile_resolution" in prospect.metadata, counts)

    p = _prospect_()
    p.manual_profile_url = "https://pinnaclerealtyia.com/agent/manual"
    p.resolution_status = RESOLUTION_RESOLVED
    p.resolved_profile_url = "https://pinnaclerealtyia.com/agent/auto"
    p.resolution_confidence = CONFIDENCE_HIGH
    check("manual beats auto in effective URL",
          effective_scrape_url(p) == "https://pinnaclerealtyia.com/agent/manual", counts)

    p2 = _prospect_()
    p2.resolution_status = RESOLUTION_RESOLVED
    p2.resolved_profile_url = "https://pinnaclerealtyia.com/agent/auto"
    p2.resolution_confidence = CONFIDENCE_HIGH
    check("resolved HIGH used when no manual",
          effective_scrape_url(p2) == "https://pinnaclerealtyia.com/agent/auto", counts)

    p3 = _prospect_()
    p3.resolution_status = RESOLUTION_RESOLVED
    p3.resolved_profile_url = "https://pinnaclerealtyia.com/agent/auto"
    p3.resolution_confidence = "LOW"
    check("LOW confidence falls back to parent website",
          effective_scrape_url(p3) == PARENT, counts)

    p4 = _prospect_()
    p4.manual_profile_url = "http://localhost/x"
    check("unsafe manual is ignored",
          effective_scrape_url(p4) == PARENT, counts)
    check("manual override rejected when unsafe",
          _rejects_manual(service, "http://localhost/x"), counts)


def _rejects_manual(service: ProfileResolverService, url: str) -> bool:
    try:
        service.set_manual_profile_url(_prospect_(), url)
        return False
    except ValueError:
        return True


def _verify_persistence(counts: dict[str, int]) -> None:
    root = tempfile.mkdtemp(prefix="sprint5z_")
    store = ProspectStore(path=os.path.join(root, "prospects.json"))
    prospect = _prospect_(prospect_id="persist", name="Meridith Hoffman")
    store.create(prospect)
    service = ProfileResolverService(fetcher=_Pages().fetch)
    result = service.resolve("Meridith Hoffman", PARENT)
    service.apply_result(prospect, result)
    store.update(prospect)

    reloaded = store.get("persist")
    check(
        "resolution fields survive reload",
        reloaded is not None
        and reloaded.resolution_status == RESOLUTION_RESOLVED
        and reloaded.resolved_profile_url
        == "https://pinnaclerealtyia.com/agent/meridith-hoffman",
        counts,
    )


def _verify_csv_aliases(counts: dict[str, int]) -> None:
    m_agent = detect_mapping(["company", "agent_name"])
    check("agent_name maps to contact_name",
          m_agent.get("contact_name") == "agent_name", counts)
    m_person = detect_mapping(["company", "person_name"])
    check("person_name maps to contact_name",
          m_person.get("contact_name") == "person_name", counts)

    root = tempfile.mkdtemp(prefix="sprint5z_csv_")
    imp = ProspectCsvImporter(
        ProspectStore(path=os.path.join(root, "prospects.json"))
    )
    result = imp.import_text("company,agent_name\nPinnacle Realty,Meridith Hoffman\n")
    imported_ok = result.imported == 1
    p = imp._store.list()[0] if imp._store.list() else None
    check(
        "person/agent header imports contact",
        imported_ok and p is not None and p.contact_name == "Meridith Hoffman",
        counts,
    )


def main() -> int:
    print("PROFILE RESOLUTION - SPRINT 5Z\n")
    print("SYNTHETIC VERIFICATION DATA (offline, no live network)\n")
    counts = {"passed": 0, "failed": 0}
    _verify_resolution(counts)
    _verify_apply_and_effective(counts)
    _verify_persistence(counts)
    _verify_csv_aliases(counts)
    print("\nSPRINT 5Z VERIFICATION COMPLETE")
    print(f"Passed: {counts['passed']}")
    print(f"Failed: {counts['failed']}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())