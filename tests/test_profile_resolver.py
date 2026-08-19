"""Sprint 5Z profile resolution test suite (Qt-free, offline).

Exercises :mod:`gui.services.profile_resolver` end-to-end with a deterministic
``FakeSite`` fetcher so every scenario (robots, sitemaps, homepage, directory
pages, candidate verification) runs without touching the live web.
"""

from __future__ import annotations

import gzip
import os

import pytest

from gui.models.prospect import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_ERROR,
    RESOLUTION_NOT_ATTEMPTED,
    RESOLUTION_NOT_FOUND,
    RESOLUTION_RESOLVED,
    Prospect,
)
from gui.models.prospect_store import ProspectStore
from gui.services.profile_resolver import (
    ProfileResolverService,
    FetchError,
    _decompress_gzip,
    default_fetcher,
    effective_scrape_url,
    full_name_in_text,
    is_safe_url,
    is_within_parent,
    name_in_url_slug,
    normalize_person_name,
    parse_robots_sitemaps,
    person_name_tokens,
    persons_match,
    same_registered_domain,
)

PARENT = "https://pinnaclerealtyia.com"


class _BrowserPage:
    def __init__(self, final_url: str, html: str) -> None:
        self.final_url = final_url
        self.html = html


class _BrowserSite:
    def __init__(self, pages: dict[str, tuple[str, str]] | None = None) -> None:
        self.pages = pages or {}
        self.requests: list[str] = []

    def fetch(self, url: str) -> _BrowserPage:
        self.requests.append(url)
        if url not in self.pages:
            raise FetchError(f"HTTP 404 for {url}")
        final_url, html = self.pages[url]
        return _BrowserPage(final_url=final_url, html=html)


class _Pages:
    """Serves deterministic HTML/XML keyed by URL path."""

    def __init__(self, *, dup_strong: bool = False) -> None:
        self.dup_strong = dup_strong
        self.requests: list[str] = []

    def fetch(self, url: str) -> str:
        self.requests.append(url)
        path = url.split("//", 1)[-1]
        path = path.split("/", 1)[1] if "/" in path else "/"
        path = "/" + path.strip("/")
        return self._body(path)

    def _body(self, path: str) -> str:
        if path == "/robots.txt":
            return "User-agent: *\nSitemap: https://pinnaclerealtyia.com/sitemap.xml\n"
        if path == "/sitemap.xml" or path == "/sitemap_index.xml":
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
                "<html><head><title>Pinnacle Realty | Des Moines</title></head><body>"
                '<a href="/agents">Our Team</a>'
                '<a href="/agent/meridith-hoffman">Meridith Hoffman</a>'
                "</body></html>"
            )
        if path.startswith("/agents"):
            return (
                "<html><body>"
                "<h1>Our Agents</h1>"
                '<a href="/agent/meridith-hoffman">Meridith Hoffman</a>'
                '<a href="/agent/john-doe">John Doe</a>'
                "</body></html>"
            )
        if path == "/agent/meridith-hoffman":
            bowie_note = (
                "Meridith Hoffman is also featured in our training department."
                if self.dup_strong
                else "John Doe handles the south corridor."
            )
            return (
                "<html><head><title>Meridith Hoffman | Pinnacle Realty</title></head><body>"
                "<h1>Meridith Hoffman</h1>"
                "<p>Meridith Hoffman is a realtor in Des Moines."
                " Bio: licensed 12 years. Experience with farm sales.</p>"
                f"<p>{bowie_note}</p>"
                "<p>Email: meridith@pinnaclerealtyia.com | Phone</p>"
                '<img src="/img/mh.jpg" />'
                '<script type="application/ld+json">'
                '{"@type":"Person","name":"Meridith Hoffman"}'
                "</script>"
                "</body></html>"
            )
        if path == "/agent/john-doe":
            meridith_note = (
                "Meridith Hoffman works here too."
                if self.dup_strong
                else "John Doe is our new agent."
            )
            return (
                "<html><head><title>John Doe | Pinnacle Realty</title></head><body>"
                "<h1>John Doe</h1>"
                f"<p>{meridith_note} John Doe covers rural listings.</p>"
                "</body></html>"
            )
        raise FetchError(f"HTTP 404 for {path}")


class _IdxGzipPages:
    def __init__(self, *, target_has_name: bool = True, duplicate_target: bool = False) -> None:
        self.requests: list[str] = []
        sitemap = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>https://pinnaclerealtyia.com/agent/1000-John-Doe/</loc></url>'
            '<url><loc>https://pinnaclerealtyia.com/agent/1714473-Meridith-Hoffman/</loc></url>'
            '<url><loc>https://pinnaclerealtyia.com/agent/2000-Jane-Roe/</loc></url>'
            '<url><loc>https://pinnaclerealtyia.com/app/uploads/2023/07/Agent-listing.png</loc></url>'
            '</urlset>'
        )
        if duplicate_target:
            sitemap = sitemap.replace(
                '</urlset>',
                '<url><loc>https://pinnaclerealtyia.com/agent/9999-Meridith-Hoffman/</loc></url></urlset>',
            )
        self.gz_text = gzip.decompress(gzip.compress(sitemap.encode("utf-8"))).decode("utf-8")
        self.target_has_name = target_has_name

    def fetch(self, url: str) -> str:
        self.requests.append(url)
        path = url.split("//", 1)[-1]
        path = path.split("/", 1)[1] if "/" in path else "/"
        path = "/" + path.strip("/")
        if path == "/robots.txt":
            return "User-agent: *\nSitemap: https://pinnaclerealtyia.com/sitemap.xml\n"
        if path == "/sitemap.xml" or path == "/sitemap_index.xml":
            return (
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '<sitemap><loc>https://pinnaclerealtyia.com/idx-sitemaps/sitemap-agent-profiles-1.xml.gz</loc></sitemap>'
                '</sitemapindex>'
            )
        if path == "/idx-sitemaps/sitemap-agent-profiles-1.xml.gz":
            return self.gz_text
        if path == "/":
            return "<html><body><a href='/agents'>Agents</a></body></html>"
        if path == "/agents":
            return "<html><body>No matching cards here.</body></html>"
        if path == "/agent/1714473-Meridith-Hoffman":
            if self.target_has_name:
                return (
                    "<html><head><title>Meridith Hoffman | Pinnacle Realty</title></head>"
                    "<body><h1>Meridith Hoffman</h1><p>Bio and experience.</p>"
                    '<script type="application/ld+json">{"@type":"Person","name":"Meridith Hoffman"}</script>'
                    "</body></html>"
                )
            return "<html><head><title>Agent Profile</title></head><body><h1>Our Agent</h1></body></html>"
        if path == "/agent/9999-Meridith-Hoffman":
            return "<html><body><h1>Meridith Hoffman</h1><p>Bio and experience.</p></body></html>"
        if path.startswith("/agent/"):
            return "<html><body><h1>Unrelated Agent</h1></body></html>"
        raise FetchError(f"HTTP 404 for {path}")


class _BlockedIdxReachableProfileSitemapPages(_IdxGzipPages):
    """IDX-style index is blocked, but same-directory agent sitemap is reachable."""

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


def _service(dup_strong: bool = False, browser_fetcher=None) -> tuple[ProfileResolverService, _Pages]:
    site = _Pages(dup_strong=dup_strong)
    return ProfileResolverService(fetcher=site.fetch, browser_fetcher=browser_fetcher), site


def _prospect(
    *, name: str = "Meridith Hoffman", website: str = PARENT, prospect_id: str = "p1"
) -> Prospect:
    return Prospect(
        prospect_id=prospect_id,
        company_name="Pinnacle Realty IA",
        contact_name=name,
        website=website,
    )


# ---------------------------------------------------------------------------
# URL safety + domain boundary
# ---------------------------------------------------------------------------


class TestUrlSafety:
    def test_safe_https_and_http(self) -> None:
        assert is_safe_url("https://pinnaclerealtyia.com/agents")
        assert is_safe_url("http://pinnaclerealtyia.com")

    def test_rejects_bad_schemes(self) -> None:
        assert not is_safe_url("ftp://pinnaclerealtyia.com")
        assert not is_safe_url("file:///etc/passwd")

    def test_rejects_localhost_and_private(self) -> None:
        assert not is_safe_url("http://localhost")
        assert not is_safe_url("http://127.0.0.1/x")
        assert not is_safe_url("http://10.0.0.1")
        assert not is_safe_url("http://192.168.1.1")

    def test_rejects_non_host_and_blank(self) -> None:
        assert not is_safe_url("")
        assert not is_safe_url(None)

    def test_same_registered_domain(self) -> None:
        assert same_registered_domain(
            "https://www.pinnaclerealtyia.com/x", "https://pinnaclerealtyia.com"
        )
        assert not same_registered_domain(
            "https://evil.com", "https://pinnaclerealtyia.com"
        )

    def test_is_within_parent_boundary(self) -> None:
        assert is_within_parent(
            "https://pinnaclerealtyia.com/agent/john-doe", PARENT
        )
        assert not is_within_parent("https://evil.com/agent/john-doe", PARENT)


# ---------------------------------------------------------------------------
# Name normalization (conservative, exact)
# ---------------------------------------------------------------------------


class TestNameNormalization:
    def test_normalize_person_name(self) -> None:
        assert normalize_person_name("Meridith A. Hoffman") == "meridith a hoffman"
        # Hyphens in surnames are intentionally preserved.
        assert normalize_person_name("MERIDITH-HOFFMAN") == "meridith-hoffman"
        assert normalize_person_name("  ") == ""

    def test_person_tokens(self) -> None:
        assert person_name_tokens("Meridith A Hoffman") == ("meridith", "a", "hoffman")

    def test_persons_match_middle_initial_tolerance(self) -> None:
        assert persons_match("Meridith Hoffman", "MERIDITH A. HOFFMAN")
        assert persons_match("John Doe Jr.", "john doe")
        assert not persons_match("Meridith Hoffman", "Meridith Smith")
        # First/last-only matching is structurally impossible.
        assert not persons_match("Meridith", "Meridith")

    def test_full_name_in_text(self) -> None:
        assert full_name_in_text("Meridith Hoffman", "Meet Meridith Hoffman realtor")
        assert full_name_in_text("Meridith Hoffman", "Meridith A Hoffman")
        assert not full_name_in_text("Meridith Hoffman", "Meridith only")

    def test_name_in_url_slug(self) -> None:
        assert name_in_url_slug(
            "Meridith Hoffman", "https://x.com/agents/meridith-hoffman"
        )
        assert not name_in_url_slug("Meridith Hoffman", "https://x.com/john-doe")

    def test_parse_robots_sitemaps(self) -> None:
        robots = (
            "User-agent: *\n"
            "Sitemap: https://x.com/s1.xml\n"
            "Sitemap: https://x.com/s2.xml\n"
        )
        assert parse_robots_sitemaps(robots) == [
            "https://x.com/s1.xml",
            "https://x.com/s2.xml",
        ]


class TestGzipSitemapSupport:
    def test_default_fetcher_decompresses_actual_gzip_bytes(self, monkeypatch) -> None:
        sitemap = b"<?xml version='1.0'?><urlset><url><loc>https://x.test/agent/a</loc></url></urlset>"

        class FakeResponse:
            status_code = 200
            headers = {"Content-Type": "application/gzip"}

            def iter_content(self, chunk_size: int = 65536):
                yield gzip.compress(sitemap)

        def fake_get(*args, **kwargs):
            return FakeResponse()

        monkeypatch.setattr("gui.services.profile_resolver.requests.get", fake_get)
        assert "<urlset>" in default_fetcher()("https://x.test/sitemap.xml.gz")

    def test_gzip_sitemap_decompresses_and_extracts_urls(self) -> None:
        site = _IdxGzipPages()
        result = ProfileResolverService(fetcher=site.fetch).resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_RESOLVED
        assert result.resolved_url == "https://pinnaclerealtyia.com/agent/1714473-Meridith-Hoffman/"
        assert "/idx-sitemaps/sitemap-agent-profiles-1.xml.gz" in "\n".join(site.requests)

    def test_malformed_gzip_fails_safely(self) -> None:
        with pytest.raises(FetchError):
            _decompress_gzip(b"not gzip", "https://x.test/sitemap.xml.gz")

    def test_decompressed_size_bound_enforced(self, monkeypatch) -> None:
        from gui.services import profile_resolver

        monkeypatch.setattr(profile_resolver, "MAX_GZIP_DECOMPRESSED_BYTES", 5)
        payload = gzip.compress(b"<urlset></urlset>")
        with pytest.raises(FetchError):
            profile_resolver._decompress_gzip(payload, "https://x.test/sitemap.xml.gz")

    def test_idx_sitemap_target_url_prioritized_and_unrelated_not_selected(self) -> None:
        site = _IdxGzipPages()
        result = ProfileResolverService(fetcher=site.fetch).resolve("Meridith Hoffman", PARENT)
        target_index = site.requests.index("https://pinnaclerealtyia.com/agent/1714473-Meridith-Hoffman/")
        unrelated_requests = [i for i, url in enumerate(site.requests) if "John-Doe" in url or "Jane-Roe" in url]
        assert result.status == RESOLUTION_RESOLVED
        assert not unrelated_requests or target_index < min(unrelated_requests)
        assert "John-Doe" not in result.resolved_url

    def test_idx_sitemap_url_still_requires_page_name_evidence(self) -> None:
        site = _IdxGzipPages(target_has_name=False)
        result = ProfileResolverService(fetcher=site.fetch).resolve("Meridith Hoffman", PARENT)
        assert result.status != RESOLUTION_RESOLVED
        assert result.resolved_url == ""

    def test_blocked_nested_index_falls_back_to_same_directory_agent_sitemap(self) -> None:
        site = _BlockedIdxReachableProfileSitemapPages()
        result = ProfileResolverService(fetcher=site.fetch).resolve("Meridith Hoffman", PARENT)
        diagnostics = result.diagnostics["sitemap_diagnostics"]
        agent_record = next(
            r for r in diagnostics
            if r["url"] == "https://pinnaclerealtyia.com/idx-sitemaps/sitemap-agent-profiles-1.xml.gz"
        )
        blocked_record = next(
            r for r in diagnostics
            if r["url"] == "https://pinnaclerealtyia.com/idx-sitemaps/index.xml"
        )
        assert result.status == RESOLUTION_RESOLVED
        assert result.resolved_url == "https://pinnaclerealtyia.com/agent/1714473-Meridith-Hoffman/"
        assert blocked_record["fetch"] == "FETCH_FAILED"
        assert blocked_record["failure_reason"].startswith("HTTP 403")
        assert agent_record["fetch"] == "OK"
        assert agent_record["gzip_url"] is True
        assert agent_record["parse"] == "TARGET_MATCH_FOUND"
        assert agent_record["loc_count"] == 4
        assert agent_record["target_name_loc_count"] == 1
        assert agent_record["candidate_admitted_count"] == 1

    def test_blocked_nested_index_fallback_still_requires_page_evidence(self) -> None:
        site = _BlockedIdxReachableProfileSitemapPages(target_has_name=False)
        result = ProfileResolverService(fetcher=site.fetch).resolve("Meridith Hoffman", PARENT)
        assert result.status != RESOLUTION_RESOLVED
        assert result.resolved_url == ""

    def test_sitemap_diagnostics_are_bounded_and_compact(self) -> None:
        class ManyBlockedIndexes(_BlockedIdxReachableProfileSitemapPages):
            def fetch(self, url: str) -> str:
                if url.endswith("/robots.txt"):
                    return "".join(
                        f"Sitemap: https://pinnaclerealtyia.com/idx-sitemaps-{i}/index.xml\n"
                        for i in range(30)
                    )
                if "/idx-sitemaps-" in url:
                    raise FetchError(f"HTTP 403 for {url} with " + "x" * 500)
                return super().fetch(url)

        result = ProfileResolverService(fetcher=ManyBlockedIndexes().fetch).resolve("Nobody Else", PARENT)
        diagnostics = result.diagnostics["sitemap_diagnostics"]
        assert len(diagnostics) == 20
        assert all("body" not in record and "xml" not in record for record in diagnostics)
        assert all(len(record.get("failure_reason", "")) <= 160 for record in diagnostics)


# ---------------------------------------------------------------------------
# End-to-end resolution (deterministic FakeSite)
# ---------------------------------------------------------------------------


class TestResolution:
    def test_resolves_unique_realtor_profile_high_confidence(self) -> None:
        service, _ = _service()
        result = service.resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_RESOLVED
        assert result.resolved_url == "https://pinnaclerealtyia.com/agent/meridith-hoffman"
        assert result.confidence == CONFIDENCE_HIGH
        assert result.url == result.resolved_url

    def test_resolves_from_directory_when_not_in_direct_sitemap(self) -> None:
        class LocalFetcher:
            def __call__(self, url: str) -> str:
                path = url.split("//", 1)[-1]
                path = path.split("/", 1)[1] if "/" in path else "/"
                path = "/" + path.strip("/")
                if path == "/robots.txt":
                    return ""
                if path in ("/", ""):
                    return '<a href="/agents">Team</a>'
                if path == "/agents":
                    return (
                        '<a href="/agent/meridith-hoffman">Meridith Hoffman</a>'
                    )
                if path.startswith("/agent/meridith"):
                    return (
                        "<html><head><title>Meridith Hoffman - Pinnacle</title></head>"
                        "<body><h1>Meridith Hoffman</h1>"
                        "<p>Bio and contact: meridith@pinnaclerealtyia.com</p>"
                        "</body></html>"
                    )
                raise FetchError(f"missing {path}")

        service = ProfileResolverService(fetcher=LocalFetcher())
        result = service.resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_RESOLVED
        assert result.resolved_url == "https://pinnaclerealtyia.com/agent/meridith-hoffman"

    def test_http_success_does_not_invoke_browser_fallback(self) -> None:
        browser = _BrowserSite({PARENT: (PARENT, "<html></html>")})
        service, _ = _service(browser_fetcher=browser.fetch)
        result = service.resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_RESOLVED
        assert browser.requests == []
        assert result.diagnostics.get("browser_fallback_attempted") is False

    def test_browser_fallback_invoked_when_http_discovery_blocked_and_barren(self) -> None:
        class Blocked(_Pages):
            def _body(self, path: str) -> str:
                if path == "/robots.txt":
                    return "User-agent: *\nSitemap: https://pinnaclerealtyia.com/sitemap.xml\n"
                if path in {"/sitemap.xml", "/sitemap_index.xml", "/sitemap-agents.xml", "/sitemap-pages.xml", "/"}:
                    raise FetchError(f"HTTP 403 for https://pinnaclerealtyia.com{path}")
                return super()._body(path)

        browser = _BrowserSite(
            {
                PARENT: (PARENT, '<a href="/agents">Agents</a>'),
                f"{PARENT}/agents": (f"{PARENT}/agents", '<a href="/agent/meridith-hoffman">Meridith Hoffman</a>'),
            }
        )
        service = ProfileResolverService(fetcher=Blocked().fetch, browser_fetcher=browser.fetch)
        result = service.resolve("Meridith Hoffman", PARENT)
        assert result.diagnostics.get("browser_fallback_attempted") is True
        assert browser.requests[0] == PARENT

    def test_browser_directory_and_candidate_resolves_high(self) -> None:
        class Blocked(_Pages):
            def _body(self, path: str) -> str:
                if path == "/robots.txt":
                    return ""
                if path == "/":
                    return "<html><body>No useful requests path</body></html>"
                raise FetchError(f"HTTP 403 for https://pinnaclerealtyia.com{path}")

        browser = _BrowserSite(
            {
                PARENT: (PARENT, '<a href="/agents">Our Team</a>'),
                f"{PARENT}/agents": (f"{PARENT}/agents", '<a href="/agent/meridith-hoffman">Meridith Hoffman</a>'),
                f"{PARENT}/agent/meridith-hoffman": (
                    f"{PARENT}/agent/meridith-hoffman",
                    "<html><head><title>Meridith Hoffman | Pinnacle Realty</title></head><body><h1>Meridith Hoffman</h1><p>Bio and experience.</p></body></html>",
                ),
            }
        )
        service = ProfileResolverService(fetcher=Blocked().fetch, browser_fetcher=browser.fetch)
        result = service.resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_RESOLVED
        assert result.confidence == CONFIDENCE_HIGH

    def test_browser_name_bearing_url_without_page_corroboration_not_resolved(self) -> None:
        class Blocked(_Pages):
            def _body(self, path: str) -> str:
                if path == "/robots.txt":
                    return ""
                if path == "/":
                    return "<html></html>"
                if path == "/agent/meridith-hoffman":
                    return "<html><body><h1>About Our Team</h1></body></html>"
                raise FetchError(f"HTTP 403 for https://pinnaclerealtyia.com{path}")

        browser = _BrowserSite({PARENT: (PARENT, '<a href="/agent/meridith-hoffman">Meridith Hoffman</a>')})
        service = ProfileResolverService(fetcher=Blocked().fetch, browser_fetcher=browser.fetch)
        result = service.resolve("Meridith Hoffman", PARENT)
        assert result.status != RESOLUTION_RESOLVED

    def test_browser_ambiguous_two_plausible_candidates(self) -> None:
        class Blocked(_Pages):
            def _body(self, path: str) -> str:
                if path == "/robots.txt":
                    return ""
                if path in {"/agent/meridith-hoffman", "/agent/meridith-hoffman-2"}:
                    return "<html><head><title>Meridith Hoffman | Pinnacle Realty</title></head><body><h1>Meridith Hoffman</h1></body></html>"
                raise FetchError(f"HTTP 403 for https://pinnaclerealtyia.com{path}")

        browser = _BrowserSite(
            {
                PARENT: (PARENT, '<a href="/agents">Agents</a>'),
                f"{PARENT}/agents": (f"{PARENT}/agents", '<a href="/agent/meridith-hoffman">Meridith Hoffman</a><a href="/agent/meridith-hoffman-2">Meridith Hoffman</a>'),
            }
        )
        service = ProfileResolverService(fetcher=Blocked().fetch, browser_fetcher=browser.fetch)
        result = service.resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_AMBIGUOUS

    def test_browser_rejects_external_and_private_and_redirect_external(self) -> None:
        class Blocked(_Pages):
            def _body(self, path: str) -> str:
                if path == "/robots.txt":
                    return ""
                raise FetchError(f"HTTP 403 for https://pinnaclerealtyia.com{path}")

        browser = _BrowserSite(
            {
                PARENT: ("https://external.example/", '<a href="https://external.example/agents">Agents</a><a href="http://127.0.0.1/x">Local</a>')
            }
        )
        service = ProfileResolverService(fetcher=Blocked().fetch, browser_fetcher=browser.fetch)
        result = service.resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_NOT_FOUND
        assert result.diagnostics.get("browser_homepage_status") == "REDIRECT_REJECTED"

    def test_browser_bounds_respected(self) -> None:
        class Blocked(_Pages):
            def _body(self, path: str) -> str:
                if path == "/robots.txt":
                    return ""
                raise FetchError(f"HTTP 403 for https://pinnaclerealtyia.com{path}")

        many_links = "".join(f'<a href="/agents-{i}">Agents {i}</a>' for i in range(20))
        pages = {PARENT: (PARENT, many_links)}
        for i in range(20):
            pages[f"{PARENT}/agents-{i}"] = (f"{PARENT}/agents-{i}", '<a href="/agent/meridith-hoffman">Meridith Hoffman</a>')
        browser = _BrowserSite(pages)
        service = ProfileResolverService(fetcher=Blocked().fetch, browser_fetcher=browser.fetch, max_directory_pages=3, max_browser_links_scanned=5)
        result = service.resolve("Meridith Hoffman", PARENT)
        assert result.diagnostics.get("browser_directory_pages_examined") <= 3
        assert result.diagnostics.get("browser_links_examined") <= 20

    def test_browser_failure_graceful(self) -> None:
        class Blocked(_Pages):
            def _body(self, path: str) -> str:
                if path == "/robots.txt":
                    return ""
                raise FetchError(f"HTTP 403 for https://pinnaclerealtyia.com{path}")

        class BrokenBrowser:
            def __call__(self, url: str) -> _BrowserPage:
                raise RuntimeError("browser unavailable")

        service = ProfileResolverService(fetcher=Blocked().fetch, browser_fetcher=BrokenBrowser())
        result = service.resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_NOT_FOUND
        assert result.diagnostics.get("browser_fallback_attempted") is True
        assert result.confidence == ""

    def test_http_candidate_strong_does_not_trigger_browser_verification(self) -> None:
        browser = _BrowserSite({f"{PARENT}/agent/meridith-hoffman": (f"{PARENT}/agent/meridith-hoffman", "<html></html>")})
        service, _ = _service(browser_fetcher=browser.fetch)
        result = service.resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_RESOLVED
        rows = result.diagnostics.get("candidate_diagnostics") or []
        assert rows
        assert all(not row.get("browser_verification_attempted") for row in rows)

    def test_http_candidate_weak_triggers_browser_verification_and_resolves(self) -> None:
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

        browser = _BrowserSite({
            f"{PARENT}/agent/meridith-hoffman": (
                f"{PARENT}/agent/meridith-hoffman",
                "<html><head><title>Meridith Hoffman | Pinnacle Realty</title></head><body><h1>Meridith Hoffman</h1></body></html>",
            )
        })
        result = ProfileResolverService(fetcher=WeakHttp(), browser_fetcher=browser.fetch).resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_RESOLVED
        rows = result.diagnostics.get("candidate_diagnostics") or []
        assert any(row.get("browser_verification_attempted") for row in rows)

    def test_http_candidate_weak_browser_still_weak_remains_not_found(self) -> None:
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

        browser = _BrowserSite({
            f"{PARENT}/agent/meridith-hoffman": (f"{PARENT}/agent/meridith-hoffman", "<html><body><p>About our agents</p></body></html>")
        })
        result = ProfileResolverService(fetcher=WeakHttp(), browser_fetcher=browser.fetch).resolve("Meridith Hoffman", PARENT)
        assert result.status != RESOLUTION_RESOLVED

    def test_browser_candidate_redirect_external_rejected(self) -> None:
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

        browser = _BrowserSite({
            f"{PARENT}/agent/meridith-hoffman": ("https://external.example/profile", "<html><h1>Meridith Hoffman</h1></html>")
        })
        result = ProfileResolverService(fetcher=WeakHttp(), browser_fetcher=browser.fetch).resolve("Meridith Hoffman", PARENT)
        rows = result.diagnostics.get("candidate_diagnostics") or []
        assert any("redirect outside parent domain" in (row.get("browser_failure_reason") or "") for row in rows)

    def test_about_candidate_does_not_trigger_browser_verification(self) -> None:
        class AboutHttp:
            def __call__(self, url: str) -> str:
                path = url.split("//", 1)[-1]
                path = path.split("/", 1)[1] if "/" in path else "/"
                path = "/" + path.strip("/")
                if path == "/robots.txt":
                    return ""
                if path in ("/", ""):
                    return '<a href="/about">Meridith Hoffman</a>'
                if path == "/about":
                    return "<html><body><p>Meridith Hoffman mentioned in company history.</p></body></html>"
                raise FetchError(f"missing {path}")

        browser = _BrowserSite({f"{PARENT}/about": (f"{PARENT}/about", "<html></html>")})
        result = ProfileResolverService(fetcher=AboutHttp(), browser_fetcher=browser.fetch).resolve("Meridith Hoffman", PARENT)
        rows = result.diagnostics.get("candidate_diagnostics") or []
        assert rows
        assert all(not row.get("browser_verification_attempted") for row in rows)

    def test_multiple_browser_verified_strong_candidates_are_ambiguous(self) -> None:
        class WeakHttp:
            def __call__(self, url: str) -> str:
                path = url.split("//", 1)[-1]
                path = path.split("/", 1)[1] if "/" in path else "/"
                path = "/" + path.strip("/")
                if path == "/robots.txt":
                    return ""
                if path in ("/", ""):
                    return '<a href="/agents">Team</a>'
                if path == "/agents":
                    return '<a href="/agent/meridith-hoffman">Meridith Hoffman</a><a href="/agent/meridith-hoffman-2">Meridith Hoffman</a>'
                if path in {"/agent/meridith-hoffman", "/agent/meridith-hoffman-2"}:
                    return "<html><body><p>Call today</p></body></html>"
                raise FetchError(f"missing {path}")

        browser = _BrowserSite({
            f"{PARENT}/agent/meridith-hoffman": (f"{PARENT}/agent/meridith-hoffman", "<html><head><title>Meridith Hoffman</title></head><body><h1>Meridith Hoffman</h1></body></html>"),
            f"{PARENT}/agent/meridith-hoffman-2": (f"{PARENT}/agent/meridith-hoffman-2", "<html><head><title>Meridith Hoffman</title></head><body><h1>Meridith Hoffman</h1></body></html>"),
        })
        result = ProfileResolverService(fetcher=WeakHttp(), browser_fetcher=browser.fetch).resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_AMBIGUOUS

    def test_browser_candidate_verification_count_bound_respected(self) -> None:
        class WeakMany:
            def __call__(self, url: str) -> str:
                path = url.split("//", 1)[-1]
                path = path.split("/", 1)[1] if "/" in path else "/"
                path = "/" + path.strip("/")
                if path == "/robots.txt":
                    return ""
                if path in ("/", ""):
                    return '<a href="/agents">Team</a>'
                if path == "/agents":
                    return ''.join(f'<a href="/agent/meridith-hoffman-{i}">Meridith Hoffman</a>' for i in range(8))
                if path.startswith("/agent/meridith-hoffman-"):
                    return "<html><body><p>Call today</p></body></html>"
                raise FetchError(f"missing {path}")

        browser_pages = {f"{PARENT}/agent/meridith-hoffman-{i}": (f"{PARENT}/agent/meridith-hoffman-{i}", "<html><body>Weak</body></html>") for i in range(8)}
        browser = _BrowserSite(browser_pages)
        result = ProfileResolverService(fetcher=WeakMany(), browser_fetcher=browser.fetch, max_browser_candidate_verify=2).resolve("Meridith Hoffman", PARENT)
        assert result.diagnostics.get("browser_candidate_verifications_attempted") <= 2

    def test_resolves_when_medium_confidence_slug_only(self) -> None:
        # Candidate page has the name slug + image/contact corroboration but no
        # full-name text, yielding at least MEDIUM.
        class SlugFetcher:
            def __call__(self, url: str) -> str:
                host = url.split("//", 1)[-1]
                path = host.split("/", 1)[1] if "/" in host else "/"
                path = "/" + path.strip("/")
                if path in ("/robots.txt", "/sitemap.xml", "/sitemap_index.xml"):
                    return ""
                if path in ("/", ""):
                    return '<a href="/team">Team</a><a href="/agent/alex-kahn">Alex</a>'
                if path == "/team":
                    return '<a href="/agent/alex-kahn">Alex Kahn</a>'
                if path.startswith("/agent/alex-kahn"):
                    return (
                        "<html><head><title>Realtor in Des Moines</title></head>"
                        "<body><p>Call today</p>"
                        '<img src="/a.jpg"><a href="mailto:a@pinnaclerealtyia.com">'
                        "</body></html>"
                    )
                raise FetchError(f"missing {path}")

        service = ProfileResolverService(fetcher=SlugFetcher())
        result = service.resolve("Alex Kahn", PARENT)
        assert result.status == RESOLUTION_RESOLVED
        assert result.resolved_url == "https://pinnaclerealtyia.com/agent/alex-kahn"
        assert result.confidence in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM)

    def test_ambiguous_when_multiple_strong_candidates(self) -> None:
        service, _ = _service(dup_strong=True)
        result = service.resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_AMBIGUOUS
        assert result.resolved_url == ""

    def test_static_assets_are_not_profile_candidates(self) -> None:
        class StaticSite(_Pages):
            def _body(self, path: str) -> str:
                if path == "/sitemap-agents.xml":
                    return (
                        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                        '<url><loc>https://pinnaclerealtyia.com/agent/meridith-hoffman.png</loc></url>'
                        '<url><loc>https://pinnaclerealtyia.com/agent/meridith-hoffman.pdf</loc></url>'
                        '<url><loc>https://pinnaclerealtyia.com/agent/meridith-hoffman.js</loc></url>'
                        '<url><loc>https://pinnaclerealtyia.com/agent/meridith-hoffman.css</loc></url>'
                        "</urlset>"
                    )
                return super()._body(path)

        site = StaticSite()
        result = ProfileResolverService(fetcher=site.fetch).resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_RESOLVED  # homepage/directory fixture still finds real HTML profile
        assert not any(url.endswith((".png", ".pdf", ".js", ".css")) for url in site.requests)

    def test_generic_agent_root_cannot_resolve_without_full_name_evidence(self) -> None:
        class RootOnlySite(_Pages):
            def _body(self, path: str) -> str:
                if path == "/sitemap-agents.xml":
                    return '<urlset><url><loc>https://pinnaclerealtyia.com/agent/</loc></url></urlset>'
                if path == "/":
                    return "<html><body>No directory links.</body></html>"
                if path == "/agent":
                    return "<html><body><h1>Agent Directory</h1></body></html>"
                return super()._body(path)

        result = ProfileResolverService(fetcher=RootOnlySite().fetch).resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_NOT_FOUND
        assert result.resolved_url == ""

    def test_404_candidate_cannot_resolve(self) -> None:
        class MissingCandidateSite(_Pages):
            def _body(self, path: str) -> str:
                if path == "/sitemap-agents.xml":
                    return '<urlset><url><loc>https://pinnaclerealtyia.com/agent/meridith-hoffman</loc></url></urlset>'
                if path == "/":
                    return "<html><body>No directory links.</body></html>"
                if path == "/agent/meridith-hoffman":
                    raise FetchError("HTTP 404 for /agent/meridith-hoffman")
                return super()._body(path)

        result = ProfileResolverService(fetcher=MissingCandidateSite().fetch).resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_NOT_FOUND
        assert result.resolved_url == ""

    def test_403_candidate_cannot_resolve(self) -> None:
        class ForbiddenCandidateSite(_Pages):
            def _body(self, path: str) -> str:
                if path == "/sitemap-agents.xml":
                    return '<urlset><url><loc>https://pinnaclerealtyia.com/agent/meridith-hoffman</loc></url></urlset>'
                if path == "/":
                    return "<html><body>No directory links.</body></html>"
                if path == "/agent/meridith-hoffman":
                    raise FetchError("HTTP 403 for /agent/meridith-hoffman")
                return super()._body(path)

        result = ProfileResolverService(fetcher=ForbiddenCandidateSite().fetch).resolve("Meridith Hoffman", PARENT)
        assert result.status == RESOLUTION_NOT_FOUND
        assert result.resolved_url == ""

    def test_diagnostics_are_compactly_persisted(self) -> None:
        service, _ = _service()
        prospect = _prospect()
        result = service.resolve("Meridith Hoffman", PARENT)
        service.apply_result(prospect, result)
        meta = prospect.metadata["profile_resolution"]
        assert meta["robots_fetched"] is True
        assert meta["sitemap_count_attempted"] >= 1
        assert meta["candidate_count_after_filtering"] >= 1
        assert meta["final_decision_reason"]

    def test_not_found_when_no_matching_profile(self) -> None:
        service, _ = _service()
        result = service.resolve("Nobody Else", PARENT)
        assert result.status == RESOLUTION_NOT_FOUND
        assert result.resolved_url == ""

    def test_error_for_unsafe_parent(self) -> None:
        service, _ = _service()
        result = service.resolve("Meridith Hoffman", "http://localhost")
        assert result.status == RESOLUTION_ERROR

    def test_error_when_name_missing(self) -> None:
        service, _ = _service()
        result = service.resolve("  ", PARENT)
        assert result.status == RESOLUTION_ERROR

    def test_error_when_first_last_only(self) -> None:
        service, _ = _service()
        result = service.resolve("Meridith", PARENT)
        assert result.status == RESOLUTION_ERROR


# ---------------------------------------------------------------------------
# Application layer + effective URL selection
# ---------------------------------------------------------------------------


class TestApplyAndEffectiveUrl:
    def test_apply_result_preserves_website_and_sets_fields(self) -> None:
        service, _ = _service()
        prospect = _prospect(website="https://broker.other.com")
        result = service.resolve("Meridith Hoffman", PARENT)
        returned = service.apply_result(prospect, result)
        assert returned is prospect
        assert prospect.website == "https://broker.other.com"  # never replaced
        assert prospect.resolution_status == RESOLUTION_RESOLVED
        assert prospect.resolution_confidence == CONFIDENCE_HIGH
        assert (
            prospect.resolved_profile_url
            == "https://pinnaclerealtyia.com/agent/meridith-hoffman"
        )
        assert "profile_resolution" in prospect.metadata

    def test_apply_result_preserves_manual_override(self) -> None:
        service, _ = _service()
        prospect = _prospect()
        service.set_manual_profile_url(
            prospect, "https://pinnaclerealtyia.com/agent/manual-jane"
        )
        result = service.resolve("Meridith Hoffman", PARENT)
        service.apply_result(prospect, result)
        # Applying auto-resolution must never clobber a manual override.
        assert (
            prospect.manual_profile_url
            == "https://pinnaclerealtyia.com/agent/manual-jane"
        )

    def test_effective_manual_wins(self) -> None:
        prospect = _prospect()
        prospect.manual_profile_url = "https://pinnaclerealtyia.com/agent/manual"
        prospect.resolution_status = RESOLUTION_RESOLVED
        prospect.resolved_profile_url = "https://pinnaclerealtyia.com/agent/auto"
        prospect.resolution_confidence = CONFIDENCE_HIGH
        assert effective_scrape_url(prospect) == "https://pinnaclerealtyia.com/agent/manual"

    def test_effective_resolved_high_confidence(self) -> None:
        prospect = _prospect()
        prospect.resolution_status = RESOLUTION_RESOLVED
        prospect.resolved_profile_url = "https://pinnaclerealtyia.com/agent/auto"
        prospect.resolution_confidence = CONFIDENCE_HIGH
        assert effective_scrape_url(prospect) == "https://pinnaclerealtyia.com/agent/auto"

    def test_effective_low_confidence_falls_back_to_website(self) -> None:
        prospect = _prospect()
        prospect.resolution_status = RESOLUTION_RESOLVED
        prospect.resolved_profile_url = "https://pinnaclerealtyia.com/agent/auto"
        prospect.resolution_confidence = "LOW"
        assert effective_scrape_url(prospect) == PARENT

    def test_effective_unsafe_manual_ignored(self) -> None:
        prospect = _prospect()
        prospect.manual_profile_url = "http://localhost/x"
        assert effective_scrape_url(prospect) == PARENT

    def test_effective_none(self) -> None:
        assert effective_scrape_url(None) == ""

    def test_set_manual_rejects_unsafe(self) -> None:
        service, _ = _service()
        with pytest.raises(ValueError):
            service.set_manual_profile_url(_prospect(), "http://localhost/x")

    def test_clear_manual(self) -> None:
        service, _ = _service()
        prospect = _prospect()
        service.set_manual_profile_url(
            prospect, "https://pinnaclerealtyia.com/agent/manual"
        )
        assert prospect.manual_profile_url
        service.clear_manual_profile_url(prospect)
        assert prospect.manual_profile_url == ""


# ---------------------------------------------------------------------------
# Batch resolution + persistence round-trip
# ---------------------------------------------------------------------------


class TestBatchAndPersistence:
    def test_resolve_prospects_applies_in_place(self) -> None:
        service, _ = _service()
        prospects = [
            _prospect(prospect_id="ok", name="Meridith Hoffman"),
            _prospect(prospect_id="bad-site", website="http://localhost"),
        ]
        results = service.resolve_prospects(prospects, apply=True)
        assert len(results) == 2
        assert results[0].status == RESOLUTION_RESOLVED
        assert results[1].status == RESOLUTION_ERROR
        # One failure never aborts the rest. The safe site was applied; the
        # pre-validation error is reported but not written onto the prospect.
        assert prospects[0].resolution_status == RESOLUTION_RESOLVED
        assert prospects[1].resolution_status == RESOLUTION_NOT_ATTEMPTED

    def test_resolve_prospects_apply_false_only_reports(self) -> None:
        service, _ = _service()
        prospects = [_prospect(prospect_id="ok", name="Meridith Hoffman")]
        results = service.resolve_prospects(prospects, apply=False)
        assert results[0].status == RESOLUTION_RESOLVED
        assert prospects[0].resolution_status == RESOLUTION_NOT_ATTEMPTED

    def test_persistence_round_trip(self, tmp_path) -> None:
        store = ProspectStore(path=os.path.join(str(tmp_path), "prospects.json"))
        prospect = _prospect(prospect_id="p-round", name="Meridith Hoffman")
        store.create(prospect)
        service, _ = _service()
        result = service.resolve("Meridith Hoffman", PARENT)
        service.apply_result(prospect, result)
        store.update(prospect)

        reloaded = store.get("p-round")
        assert reloaded is not None
        assert reloaded.resolution_status == RESOLUTION_RESOLVED
        assert reloaded.resolution_confidence == CONFIDENCE_HIGH
        assert (
            reloaded.resolved_profile_url
            == "https://pinnaclerealtyia.com/agent/meridith-hoffman"
        )