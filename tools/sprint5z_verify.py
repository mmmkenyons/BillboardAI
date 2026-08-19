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
import gzip

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
    _decompress_gzip,
    effective_scrape_url,
    is_safe_url,
)
from gui.services.prospect_csv_import import ProspectCsvImporter, detect_mapping

PARENT = "https://pinnaclerealtyia.com"


class _BrowserPage:
    def __init__(self, final_url: str, html: str) -> None:
        self.final_url = final_url
        self.html = html


class _BrowserSite:
    def __init__(self, pages: dict[str, tuple[str, str]]) -> None:
        self.pages = pages
        self.requests: list[str] = []

    def fetch(self, url: str) -> _BrowserPage:
        self.requests.append(url)
        final_url, html = self.pages[url]
        return _BrowserPage(final_url, html)


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


class _IdxPages:
    def __init__(self, *, target_has_name: bool = True) -> None:
        self.requests: list[str] = []
        self.target_has_name = target_has_name
        self.agent_sitemap = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>https://pinnaclerealtyia.com/agent/100-John-Doe/</loc></url>'
            '<url><loc>https://pinnaclerealtyia.com/agent/1714473-Meridith-Hoffman/</loc></url>'
            '<url><loc>https://pinnaclerealtyia.com/app/uploads/Agent-listing.png</loc></url>'
            '</urlset>'
        )

    def fetch(self, url: str) -> str:
        self.requests.append(url)
        path = url.split("//", 1)[-1]
        path = path.split("/", 1)[1] if "/" in path else "/"
        path = "/" + path.strip("/")
        if path == "/robots.txt":
            return "User-agent: *\nSitemap: https://pinnaclerealtyia.com/sitemap.xml\n"
        if path in ("/sitemap.xml", "/sitemap_index.xml"):
            return (
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<sitemap><loc>https://pinnaclerealtyia.com/idx-sitemaps/sitemap-agent-profiles-1.xml.gz</loc></sitemap>'
                '</sitemapindex>'
            )
        if path == "/idx-sitemaps/sitemap-agent-profiles-1.xml.gz":
            return gzip.decompress(gzip.compress(self.agent_sitemap.encode("utf-8"))).decode("utf-8")
        if path == "/":
            return "<html><body><a href='/agents'>Agents</a></body></html>"
        if path == "/agents":
            return "<html><body>No name-bearing cards.</body></html>"
        if path == "/agent/1714473-Meridith-Hoffman":
            if self.target_has_name:
                return "<html><head><title>Meridith Hoffman</title></head><body><h1>Meridith Hoffman</h1><p>Bio.</p></body></html>"
            return "<html><body><h1>Agent Profile</h1></body></html>"
        if path.startswith("/agent/"):
            return "<html><body><h1>Unrelated Agent</h1></body></html>"
        raise FetchError(f"HTTP 404 for {path}")


class _BlockedIdxPages(_IdxPages):
    def fetch(self, url: str) -> str:
        self.requests.append(url)
        path = url.split("//", 1)[-1]
        path = path.split("/", 1)[1] if "/" in path else "/"
        path = "/" + path.strip("/")
        if path == "/robots.txt":
            return "User-agent: *\nSitemap: https://pinnaclerealtyia.com/idx-sitemaps/index.xml\n"
        if path == "/idx-sitemaps/index.xml":
            raise FetchError("HTTP 403 for https://pinnaclerealtyia.com/idx-sitemaps/index.xml")
        if path == "/idx-sitemaps/sitemap-agent-html-sitemap-1.xml.gz":
            return '<urlset><url><loc>https://pinnaclerealtyia.com/agents/</loc></url></urlset>'
        return super().fetch(url)


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


def _verify_5z1_hardening(counts: dict[str, int]) -> None:
    xml = b"<urlset><url><loc>https://x.test/agent/meridith-hoffman</loc></url></urlset>"
    check("gzip sitemap bytes decompress", _decompress_gzip(gzip.compress(xml), "https://x.test/s.xml.gz") == xml, counts)
    try:
        _decompress_gzip(b"not gzip", "https://x.test/s.xml.gz")
        malformed_ok = False
    except FetchError:
        malformed_ok = True
    check("malformed gzip rejected safely", malformed_ok, counts)

    idx = _IdxPages()
    result = ProfileResolverService(fetcher=idx.fetch).resolve("Meridith Hoffman", PARENT)
    check("IDX agent sitemap resolves name-bearing verified profile", result.status == RESOLUTION_RESOLVED and result.resolved_url.endswith("/agent/1714473-Meridith-Hoffman/"), counts)
    check("IDX unrelated agent not selected", "John-Doe" not in result.resolved_url, counts)
    check("static asset excluded from profile verification", not any(req.endswith("Agent-listing.png") for req in idx.requests), counts)

    weak = _IdxPages(target_has_name=False)
    weak_result = ProfileResolverService(fetcher=weak.fetch).resolve("Meridith Hoffman", PARENT)
    check("name-bearing IDX URL still requires page evidence", weak_result.status != RESOLUTION_RESOLVED and weak_result.resolved_url == "", counts)

    blocked = _BlockedIdxPages()
    blocked_result = ProfileResolverService(fetcher=blocked.fetch).resolve("Meridith Hoffman", PARENT)
    diag = blocked_result.diagnostics.get("sitemap_diagnostics", [])
    agent_record = next((r for r in diag if r.get("url") == "https://pinnaclerealtyia.com/idx-sitemaps/sitemap-agent-profiles-1.xml.gz"), {})
    index_record = next((r for r in diag if r.get("url") == "https://pinnaclerealtyia.com/idx-sitemaps/index.xml"), {})
    check("blocked nested sitemap index fallback resolves profile", blocked_result.status == RESOLUTION_RESOLVED and blocked_result.resolved_url.endswith("/agent/1714473-Meridith-Hoffman/"), counts)
    check("blocked sitemap index diagnostic records fetch failure", index_record.get("fetch") == "FETCH_FAILED", counts)
    check("fallback agent sitemap diagnostic records target loc admission", agent_record.get("parse") == "TARGET_MATCH_FOUND" and agent_record.get("target_name_loc_count") == 1 and agent_record.get("candidate_admitted_count") == 1, counts)

    class RootOnly(_Pages):
        def _body(self, path: str) -> str:
            if path == "/sitemap-agents.xml":
                return '<urlset><url><loc>https://pinnaclerealtyia.com/agent/</loc></url></urlset>'
            if path == "/":
                return "<html><body>No directory links.</body></html>"
            if path == "/agent":
                return "<html><body><h1>Agent Directory</h1></body></html>"
            return super()._body(path)

    root_result = ProfileResolverService(fetcher=RootOnly().fetch).resolve("Meridith Hoffman", PARENT)
    check("generic /agent/ root cannot resolve without full-name evidence", root_result.status != RESOLUTION_RESOLVED and root_result.resolved_url == "", counts)


def _verify_5z3_browser_fallback(counts: dict[str, int]) -> None:
    class Blocked(_Pages):
        def _body(self, path: str) -> str:
            if path == "/robots.txt":
                return "User-agent: *\nSitemap: https://pinnaclerealtyia.com/sitemap.xml\n"
            raise FetchError(f"HTTP 403 for https://pinnaclerealtyia.com{path}")

    browser = _BrowserSite(
        {
            PARENT: (PARENT, '<a href="/agents">Agents</a>'),
            f"{PARENT}/agents": (f"{PARENT}/agents", '<a href="/agent/meridith-hoffman">Meridith Hoffman</a>'),
            f"{PARENT}/agent/meridith-hoffman": (
                f"{PARENT}/agent/meridith-hoffman",
                "<html><head><title>Meridith Hoffman | Pinnacle Realty</title></head><body><h1>Meridith Hoffman</h1><p>Bio and contact.</p></body></html>",
            ),
        }
    )
    result = ProfileResolverService(fetcher=Blocked().fetch, browser_fetcher=browser.fetch).resolve("Meridith Hoffman", PARENT)
    check("browser fallback attempted when requests discovery blocked", result.diagnostics.get("browser_fallback_attempted") is True, counts)
    check("browser fallback resolves bounded same-domain profile", result.status == RESOLUTION_RESOLVED and result.resolved_url.endswith("/agent/meridith-hoffman"), counts)
    check("browser diagnostics record directory examination", int(result.diagnostics.get("browser_directory_pages_examined") or 0) >= 1, counts)

    class WeakHttp:
        def __call__(self, url: str) -> str:
            path = url.split("//", 1)[-1]
            path = path.split("/", 1)[1] if "/" in path else "/"
            path = "/" + path.strip("/")
            if path == "/robots.txt":
                return "User-agent: *\nSitemap: https://pinnaclerealtyia.com/sitemap-agent-profiles.xml\n"
            if path == "/sitemap-agent-profiles.xml":
                return '<urlset><url><loc>https://pinnaclerealtyia.com/agent/meridith-hoffman</loc></url></urlset>'
            if path == "/agent/meridith-hoffman":
                return '<html><body><div id="app"></div></body></html>'
            raise FetchError(f"missing {path}")

    browser_verify = _BrowserSite(
        {
            f"{PARENT}/agent/meridith-hoffman": (
                f"{PARENT}/agent/meridith-hoffman",
                "<html><head><title>Meridith Hoffman | Pinnacle Realty</title></head><body><h1>Meridith Hoffman</h1></body></html>",
            )
        }
    )
    verify_result = ProfileResolverService(fetcher=WeakHttp(), browser_fetcher=browser_verify.fetch).resolve("Meridith Hoffman", PARENT)
    verify_rows = verify_result.diagnostics.get("candidate_diagnostics") or []
    check("weak HTTP candidate triggers browser verification", verify_result.diagnostics.get("browser_candidate_verifications_attempted", 0) >= 1 and any(row.get("browser_verification_attempted") for row in verify_rows), counts)
    check("browser verification reuses normal scoring to resolve", verify_result.status == RESOLUTION_RESOLVED and verify_result.resolved_url.endswith("/agent/meridith-hoffman"), counts)

    browser_weak = _BrowserSite({f"{PARENT}/agent/meridith-hoffman": (f"{PARENT}/agent/meridith-hoffman", "<html><body>Weak</body></html>")})
    weak_result = ProfileResolverService(fetcher=WeakHttp(), browser_fetcher=browser_weak.fetch).resolve("Meridith Hoffman", PARENT)
    weak_rows = weak_result.diagnostics.get("candidate_diagnostics") or []
    check("weak browser candidate still rejected", weak_result.diagnostics.get("browser_candidate_verifications_attempted", 0) >= 1 and weak_result.status != RESOLUTION_RESOLVED, counts)

    browser_redirect = _BrowserSite({f"{PARENT}/agent/meridith-hoffman": ("https://external.example/profile", "<html><h1>Meridith Hoffman</h1></html>")})
    redirect_result = ProfileResolverService(fetcher=WeakHttp(), browser_fetcher=browser_redirect.fetch).resolve("Meridith Hoffman", PARENT)
    redirect_rows = redirect_result.diagnostics.get("candidate_diagnostics") or []
    check("external redirect during browser candidate verification rejected", redirect_result.diagnostics.get("browser_candidate_verifications_attempted", 0) >= 1 and any("redirect outside parent domain" in (row.get("browser_failure_reason") or "") for row in redirect_rows), counts)


def main() -> int:
    print("PROFILE RESOLUTION - SPRINT 5Z\n")
    print("SYNTHETIC VERIFICATION DATA (offline, no live network)\n")
    counts = {"passed": 0, "failed": 0}
    _verify_resolution(counts)
    _verify_apply_and_effective(counts)
    _verify_persistence(counts)
    _verify_csv_aliases(counts)
    _verify_5z1_hardening(counts)
    _verify_5z3_browser_fallback(counts)
    print("\nSPRINT 5Z VERIFICATION COMPLETE")
    print(f"Passed: {counts['passed']}")
    print(f"Failed: {counts['failed']}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())