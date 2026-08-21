from __future__ import annotations

import gzip
import time
from urllib.parse import urlparse

from gui.models.prospect import (
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_NOT_FOUND,
    RESOLUTION_RESOLVED,
    RESOLUTION_TIMEOUT,
    Prospect,
)
from gui.services.copy_quality import PERSON_PROFILE_UNRESOLVED, QUALITY_WARNING, assess_profile_quality
from gui.services.profile_resolver import (
    FetchError,
    ProfileResolverService,
    SITEMAP_END_DISCOVERY_BUDGET_REACHED,
    SITEMAP_END_LOW_VALUE_BUDGET_REACHED,
    SITEMAP_END_SITEMAPS_EXHAUSTED,
    SITEMAP_END_VERIFICATION_RESERVE_REACHED,
    effective_scrape_url,
)


PARENT = "https://example.com"


class Site:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requests: list[str] = []

    def __call__(self, url: str) -> str:
        self.requests.append(url)
        parsed = urlparse(url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        if path in self.pages:
            value = self.pages[path]
            if value == "__FAIL__":
                raise FetchError(f"HTTP 503 for {path}")
            return value
        raise FetchError(f"HTTP 404 for {path}")


def sitemap(*urls: str) -> str:
    return "<urlset>" + "".join(f"<url><loc>{url}</loc></url>" for url in urls) + "</urlset>"


def profile(name: str = "Alex Kahn", *, title: str | None = None, h1: str | None = None, canonical: str = "", schema_name: str | None = None, body: str = "Bio experience phone email") -> str:
    title = title if title is not None else f"{name} | Example Realty"
    h1 = h1 if h1 is not None else name
    schema_name = schema_name if schema_name is not None else name
    canonical_tag = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    schema = f'<script type="application/ld+json">{{"@type":"Person","name":"{schema_name}"}}</script>' if schema_name else ""
    return f"<html><head><title>{title}</title>{canonical_tag}</head><body><h1>{h1}</h1><img src='/a.jpg'><p>{body}</p>{schema}</body></html>"


def resolver_for(pages: dict[str, str], **kwargs) -> ProfileResolverService:
    defaults = {
        "/robots.txt": "",
        "/sitemap.xml": "",
        "/sitemap_index.xml": "",
        "/": "<a href='/team'>Team</a>",
        "/team": "",
    }
    defaults.update(pages)
    return ProfileResolverService(fetcher=Site(defaults), browser_fetcher=None, **kwargs)


def test_strong_individual_identity_can_produce_accepted() -> None:
    service = resolver_for({
        "/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn"),
        "/agent/alex-kahn": profile(),
    })
    result = service.resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_RESOLVED
    assert result.resolved_url == f"{PARENT}/agent/alex-kahn"


def test_weak_name_only_evidence_cannot_produce_accepted() -> None:
    service = resolver_for({
        "/sitemap.xml": sitemap(f"{PARENT}/about/alex-kahn"),
        "/about/alex-kahn": "<html><body>Alex Kahn attended our event.</body></html>",
    })
    result = service.resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_NOT_FOUND
    assert result.resolved_url == ""


def test_team_page_loses_to_verified_individual_profile() -> None:
    service = resolver_for({
        "/sitemap.xml": sitemap(f"{PARENT}/team/alex-kahn", f"{PARENT}/agent/alex-kahn"),
        "/team/alex-kahn": "<html><title>Team</title><body>Alex Kahn and Jamie Kahn</body></html>",
        "/agent/alex-kahn": profile(),
    })
    result = service.resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_RESOLVED
    assert result.resolved_url == f"{PARENT}/agent/alex-kahn"


def test_article_mention_loses_to_verified_individual_profile() -> None:
    service = resolver_for({
        "/sitemap.xml": sitemap(f"{PARENT}/news/alex-kahn-closes-sale", f"{PARENT}/agent/alex-kahn"),
        "/news/alex-kahn-closes-sale": profile(body="Article mentioning Alex Kahn", schema_name="Example News"),
        "/agent/alex-kahn": profile(),
    })
    result = service.resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_RESOLVED
    assert result.resolved_url == f"{PARENT}/agent/alex-kahn"


def test_equivalent_duplicate_candidates_do_not_create_false_ambiguity() -> None:
    service = resolver_for({
        "/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn", f"{PARENT}/realtor/alex-kahn?utm=1"),
        "/agent/alex-kahn": profile(canonical=f"{PARENT}/agent/alex-kahn"),
        "/realtor/alex-kahn?utm=1": profile(canonical=f"{PARENT}/agent/alex-kahn"),
    })
    result = service.resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_RESOLVED


def test_canonical_variants_deduplicate_safely() -> None:
    service = resolver_for({
        "/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn?print=true", f"{PARENT}/agent/alex-kahn"),
        "/agent/alex-kahn?print=true": profile(canonical=f"{PARENT}/agent/alex-kahn"),
        "/agent/alex-kahn": profile(canonical=f"{PARENT}/agent/alex-kahn"),
    })
    assert service.resolve("Alex Kahn", PARENT).status == RESOLUTION_RESOLVED


def test_genuinely_distinct_credible_identities_remain_ambiguous() -> None:
    service = resolver_for({
        "/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn", f"{PARENT}/office2/agent/alex-kahn"),
        "/agent/alex-kahn": profile(canonical=f"{PARENT}/agent/alex-kahn", body="Bio for downtown office"),
        "/office2/agent/alex-kahn": profile(canonical=f"{PARENT}/office2/agent/alex-kahn", body="Bio for beach office"),
    })
    assert service.resolve("Alex Kahn", PARENT).status == RESOLUTION_AMBIGUOUS


def test_candidate_fetch_failure_does_not_poison_entire_run() -> None:
    service = resolver_for({
        "/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn", f"{PARENT}/agent/alex-kahn-broken"),
        "/agent/alex-kahn": profile(),
        "/agent/alex-kahn-broken": "__FAIL__",
    })
    result = service.resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_RESOLVED
    assert any(not c.http_fetch_ok for c in result.candidates)


def test_resolver_level_unrecoverable_failure_returns_error() -> None:
    result = resolver_for({}).resolve("Alex", "http://localhost")
    assert result.status == "ERROR"


def test_timeout_remains_timeout_not_error() -> None:
    def slow_fetch(url: str) -> str:
        time.sleep(0.05)
        return ""

    result = ProfileResolverService(fetcher=slow_fetch, total_timeout=0.001).resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_TIMEOUT
    assert result.diagnostics.get("timeout_reason")


def test_wrong_person_structured_data_causes_rejection() -> None:
    service = resolver_for({
        "/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn"),
        "/agent/alex-kahn": profile(title="Alex Kahn", h1="Jamie Kahn", schema_name="Jamie Kahn"),
    })
    result = service.resolve("Alex Kahn", PARENT)
    assert result.status != RESOLUTION_RESOLVED


def test_external_domain_contamination_protected() -> None:
    service = resolver_for({
        "/sitemap.xml": sitemap("https://external.example/agent/alex-kahn", f"{PARENT}/news/alex-kahn"),
        "/news/alex-kahn": "<html><body>Alex Kahn was mentioned.</body></html>",
    })
    result = service.resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_NOT_FOUND


def test_same_domain_company_evidence_contributes_without_overriding_identity() -> None:
    service = resolver_for({
        "/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn", f"{PARENT}/agent/jamie-kahn"),
        "/agent/alex-kahn": profile(schema_name=None, body="Example Realty bio experience phone email"),
        "/agent/jamie-kahn": profile(name="Jamie Kahn", body="Example Realty bio experience phone email"),
    })
    result = service.resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_RESOLVED
    assert result.resolved_url == f"{PARENT}/agent/alex-kahn"


def test_parent_website_canonical_and_no_manual_injection_required() -> None:
    prospect = Prospect(prospect_id="p1", company_name="Example Realty", contact_name="Alex Kahn", website=PARENT)
    result = resolver_for({
        "/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn"),
        "/agent/alex-kahn": profile(),
    }).resolve(prospect.contact_name, prospect.website)
    assert prospect.website == PARENT
    assert prospect.manual_profile_url == ""
    assert effective_scrape_url(prospect) == PARENT
    assert result.status == RESOLUTION_RESOLVED


def test_timeout_remains_unresolved_for_readiness_quality() -> None:
    prospect = Prospect(prospect_id="p2", company_name="Example Realty", contact_name="Alex Kahn", website=PARENT)
    prospect.resolution_status = RESOLUTION_TIMEOUT
    assessment = assess_profile_quality(prospect)
    assert assessment.status == QUALITY_WARNING
    assert PERSON_PROFILE_UNRESOLVED in {reason.code for reason in assessment.reasons}


class LargeSite:
    def __init__(self, *, gzip_agents: bool = False, wrong_person: bool = False, no_agent_sitemap: bool = False, small_irrelevant: bool = False) -> None:
        self.requests: list[str] = []
        self.gzip_agents = gzip_agents
        self.wrong_person = wrong_person
        self.no_agent_sitemap = no_agent_sitemap
        self.small_irrelevant = small_irrelevant

    def __call__(self, url: str) -> str:
        self.requests.append(url)
        path = urlparse(url).path or "/"
        if path == "/robots.txt":
            return "User-agent: *\nSitemap: https://example.com/sitemaps/index.xml\n"
        if path in {"/sitemap.xml", "/sitemap_index.xml"}:
            return ""
        if path == "/sitemaps/index.xml":
            children = [
                f"{PARENT}/sitemaps/for-sale/index.xml",
                f"{PARENT}/sitemaps/listings/index.xml",
                f"{PARENT}/sitemaps/blog/index.xml",
            ]
            if not self.no_agent_sitemap:
                children.append(f"{PARENT}/sitemaps/agent-pages/index.xml")
            return "<sitemapindex>" + "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in children) + "</sitemapindex>"
        if path == "/sitemaps/agent-pages/index.xml":
            return (
                "<sitemapindex>"
                f"<sitemap><loc>{PARENT}/sitemaps/agent-pages/sitemap_1.xml.gz</loc></sitemap>"
                f"<sitemap><loc>{PARENT}/sitemaps/properties/sitemap_99.xml</loc></sitemap>"
                "</sitemapindex>"
            )
        if path == "/sitemaps/agent-pages/sitemap_1.xml.gz":
            body = sitemap(
                f"{PARENT}/agents/jamie-kahn",
                f"{PARENT}/agents/alex-kahn",
                f"{PARENT}/agents/casey-lee",
            )
            if self.gzip_agents:
                return gzip.decompress(gzip.compress(body.encode("utf-8"))).decode("utf-8")
            return body
        if path in {"/sitemaps/for-sale/index.xml", "/sitemaps/listings/index.xml", "/sitemaps/blog/index.xml"}:
            family = path.split("/")[2]
            count = 1 if self.small_irrelevant else 5
            return "<sitemapindex>" + "".join(f"<sitemap><loc>{PARENT}/sitemaps/{family}/sitemap_{i}.xml</loc></sitemap>" for i in range(1, count + 1)) + "</sitemapindex>"
        if "/sitemaps/for-sale/" in path or "/sitemaps/listings/" in path or "/sitemaps/properties/" in path:
            count = 10 if self.small_irrelevant else 3000
            return sitemap(*(f"{PARENT}/properties/listing-{i}" for i in range(count)))
        if "/sitemaps/blog/" in path:
            return sitemap(*(f"{PARENT}/blog/post-{i}" for i in range(100)))
        if path == "/":
            return "<html><a href='/agents'>Agents</a></html>"
        if path == "/agents":
            return f"<html><a href='/agents/alex-kahn'>Alex Kahn</a></html>"
        if path == "/agents/alex-kahn":
            if self.wrong_person:
                return profile(title="Alex Kahn", h1="Jamie Kahn", schema_name="Jamie Kahn")
            return profile()
        if path == "/agents/jamie-kahn":
            return profile(name="Jamie Kahn")
        if path.startswith("/properties/") or path.startswith("/blog/"):
            return "<html><body>Irrelevant page</body></html>"
        raise FetchError(f"HTTP 404 for {path}")


def _large_site_result(**kwargs):
    site = LargeSite(**kwargs)
    result = ProfileResolverService(fetcher=site, browser_fetcher=None, total_timeout=3.0).resolve("Alex Kahn", PARENT)
    return result, site


def test_large_site_prioritizes_person_sitemap_and_resolves_before_property_volume() -> None:
    result, site = _large_site_result()
    assert result.status == RESOLUTION_RESOLVED
    assert result.resolved_url == f"{PARENT}/agents/alex-kahn"
    agent_index = site.requests.index(f"{PARENT}/sitemaps/agent-pages/index.xml")
    first_property_child = next((i for i, url in enumerate(site.requests) if "/sitemaps/for-sale/sitemap_" in url), None)
    assert first_property_child is None or agent_index < first_property_child
    assert result.diagnostics["sitemap_prioritization_applied"] is True
    assert result.diagnostics["http_candidates_discovered"] >= 1


def test_exact_intended_name_candidate_verified_before_same_family_noise() -> None:
    result, site = _large_site_result()
    alex_fetch = site.requests.index(f"{PARENT}/agents/alex-kahn")
    first_profile_fetch = min(i for i, url in enumerate(site.requests) if url.startswith(f"{PARENT}/agents/"))
    assert alex_fetch == first_profile_fetch
    assert result.status == RESOLUTION_RESOLVED


def test_irrelevant_sitemap_remains_reachable_when_no_person_sitemap_exists() -> None:
    site = LargeSite(no_agent_sitemap=True, small_irrelevant=True)
    result = ProfileResolverService(fetcher=site, browser_fetcher=None, total_timeout=3.0).resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_NOT_FOUND
    assert any("/sitemaps/for-sale/index.xml" in url for url in site.requests)


def test_early_candidate_discovery_preserves_verification_budget() -> None:
    result, site = _large_site_result()
    assert f"{PARENT}/agents/alex-kahn" in site.requests
    assert result.diagnostics["verification_reserve_seconds"] > 0
    assert result.diagnostics["sitemap_count_attempted"] <= 10


def test_no_acceptance_before_candidate_page_verification() -> None:
    site = LargeSite()
    original = site.__call__

    def missing_profile(url: str) -> str:
        if urlparse(url).path == "/agents/alex-kahn":
            site.requests.append(url)
            raise FetchError("HTTP 404 for profile")
        return original(url)

    result = ProfileResolverService(fetcher=missing_profile, browser_fetcher=None, total_timeout=3.0).resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_NOT_FOUND
    assert result.resolved_url == ""


def test_huge_irrelevant_sitemap_population_is_bounded() -> None:
    result, _site = _large_site_result(no_agent_sitemap=True)
    assert result.diagnostics["sitemap_url_entries_skipped_by_relevance_cap"] > 0
    assert any(d.get("urls_scanned_count", 0) <= 1200 for d in result.diagnostics["sitemap_diagnostics"] if d.get("low_value_sitemap"))


def test_listing_by_agent_sitemap_family_is_bounded_not_profile_prioritized() -> None:
    pages = {
        "/robots.txt": f"User-agent: *\nSitemap: {PARENT}/sitemaps/for-sale-by-agent/index.xml\nSitemap: {PARENT}/sitemaps/agent-pages/index.xml\n",
        "/sitemaps/for-sale-by-agent/index.xml": "<sitemapindex>" + "".join(f"<sitemap><loc>{PARENT}/sitemaps/for-sale-by-agent/page_{i}.xml</loc></sitemap>" for i in range(5)) + "</sitemapindex>",
        "/sitemaps/agent-pages/index.xml": f"<sitemapindex><sitemap><loc>{PARENT}/sitemaps/agent-pages/sitemap_1.xml</loc></sitemap></sitemapindex>",
        "/sitemaps/agent-pages/sitemap_1.xml": sitemap(f"{PARENT}/agents/alex-kahn"),
        "/agents/alex-kahn": profile(),
    }
    for i in range(5):
        pages[f"/sitemaps/for-sale-by-agent/page_{i}.xml"] = sitemap(*(f"{PARENT}/properties/listing-{i}-{j}" for j in range(3000)))
    service = resolver_for(pages, total_timeout=3.0)
    result = service.resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_RESOLVED
    assert result.resolved_url == f"{PARENT}/agents/alex-kahn"
    assert any(d.get("low_value_sitemap") for d in result.diagnostics["sitemap_diagnostics"] if "for-sale-by-agent" in d.get("url", "")) or result.diagnostics["sitemap_low_value_skipped_after_candidate"] >= 1


def test_nested_sitemap_index_prioritization_prefers_agent_child() -> None:
    result, site = _large_site_result()
    agent_child = site.requests.index(f"{PARENT}/sitemaps/agent-pages/sitemap_1.xml.gz")
    property_child = next((i for i, url in enumerate(site.requests) if "/sitemaps/properties/sitemap_99.xml" in url), None)
    assert property_child is None or agent_child < property_child
    assert result.status == RESOLUTION_RESOLVED


def test_gzip_sitemap_behavior_remains_supported() -> None:
    result, _site = _large_site_result(gzip_agents=True)
    assert result.status == RESOLUTION_RESOLVED
    assert result.resolved_url == f"{PARENT}/agents/alex-kahn"


def test_discovery_timeout_remains_timeout_when_budget_genuinely_exhausted() -> None:
    def slow_fetch(url: str) -> str:
        time.sleep(0.03)
        return "<sitemapindex><sitemap><loc>https://example.com/sitemaps/agent-pages/index.xml</loc></sitemap></sitemapindex>"

    result = ProfileResolverService(fetcher=slow_fetch, browser_fetcher=None, total_timeout=0.001).resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_TIMEOUT
    assert result.diagnostics.get("timeout_stage")


def test_discovery_optimization_does_not_weaken_ambiguity_protection() -> None:
    service = resolver_for({
        "/robots.txt": f"User-agent: *\nSitemap: {PARENT}/sitemaps/agent-pages.xml\n",
        "/sitemaps/agent-pages.xml": sitemap(f"{PARENT}/agents/alex-kahn", f"{PARENT}/office2/agents/alex-kahn"),
        "/agents/alex-kahn": profile(canonical=f"{PARENT}/agents/alex-kahn", body="Bio for downtown"),
        "/office2/agents/alex-kahn": profile(canonical=f"{PARENT}/office2/agents/alex-kahn", body="Bio for beach"),
    })
    assert service.resolve("Alex Kahn", PARENT).status == RESOLUTION_AMBIGUOUS


def test_same_name_wrong_person_remains_protected() -> None:
    result, _site = _large_site_result(wrong_person=True)
    assert result.status != RESOLUTION_RESOLVED


def test_generic_business_non_person_behavior_unaffected() -> None:
    result = resolver_for({}).resolve("Alex", PARENT)
    assert result.status == "ERROR"


def test_sprint6f2_ldp_pending_offmarket_are_low_value_property_sitemaps() -> None:
    pages = {
        "/robots.txt": (
            f"User-agent: *\n"
            f"Sitemap: {PARENT}/xmlsitemaps/ldp/pending_index_ldp.xml\n"
            f"Sitemap: {PARENT}/xmlsitemaps/ldp/off-market_index_ldp.xml\n"
        ),
        "/xmlsitemaps/ldp/pending_index_ldp.xml": sitemap(f"{PARENT}/properties/pending-1"),
        "/xmlsitemaps/ldp/off-market_index_ldp.xml": sitemap(f"{PARENT}/properties/off-market-1"),
    }
    result = resolver_for(pages, total_timeout=3.0).resolve("Alex Kahn", PARENT)
    ldp_rows = [
        row for row in result.diagnostics["sitemap_diagnostics"]
        if "ldp" in row.get("url", "")
    ]
    assert ldp_rows
    assert all(row.get("semantic_tier") == "LOW_VALUE_CONTENT" for row in ldp_rows)


def test_sprint6f2_mixed_for_sale_by_agent_remains_low_value() -> None:
    service = resolver_for({
        "/robots.txt": f"User-agent: *\nSitemap: {PARENT}/sitemaps/for-sale-by-agent/index.xml\n",
        "/sitemaps/for-sale-by-agent/index.xml": sitemap(f"{PARENT}/properties/for-sale-by-agent/alex-kahn-listing"),
    })
    result = service.resolve("Alex Kahn", PARENT)
    row = next(row for row in result.diagnostics["sitemap_diagnostics"] if "for-sale-by-agent" in row.get("url", ""))
    assert row["semantic_tier"] == "LOW_VALUE_CONTENT"
    assert row["low_value_sitemap"] is True


def test_sprint6f2_low_value_families_cannot_starve_verification() -> None:
    pages = {
        "/robots.txt": (
            f"User-agent: *\n"
            f"Sitemap: {PARENT}/sitemaps/agent-pages.xml\n"
            f"Sitemap: {PARENT}/xmlsitemaps/ldp/pending_index_ldp.xml\n"
        ),
        "/sitemaps/agent-pages.xml": sitemap(f"{PARENT}/agents/alex-kahn"),
        "/agents/alex-kahn": profile(),
        "/xmlsitemaps/ldp/pending_index_ldp.xml": "<sitemapindex>" + "".join(
            f"<sitemap><loc>{PARENT}/xmlsitemaps/ldp/pending_page_{i}_ldp.xml</loc></sitemap>" for i in range(20)
        ) + "</sitemapindex>",
    }
    for i in range(20):
        pages[f"/xmlsitemaps/ldp/pending_page_{i}_ldp.xml"] = sitemap(*(
            f"{PARENT}/properties/pending-{i}-{j}" for j in range(2000)
        ))
    site = Site({**{"/sitemap.xml": "", "/sitemap_index.xml": "", "/": "", "/team": ""}, **pages})
    result = ProfileResolverService(fetcher=site, browser_fetcher=None, total_timeout=3.0).resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_RESOLVED
    assert f"{PARENT}/agents/alex-kahn" in site.requests
    assert result.diagnostics["sitemap_discovery_end_reason"] == "HIGH_VALUE_CANDIDATE_FOUND"
    assert result.diagnostics["sitemap_low_value_count_attempted"] == 0


def test_sprint6f2_no_person_candidate_preserves_homepage_discovery_budget() -> None:
    pages = {
        "/robots.txt": (
            f"User-agent: *\n"
            f"Sitemap: {PARENT}/sitemaps/agent-pages.xml\n"
            f"Sitemap: {PARENT}/xmlsitemaps/ldp/off-market_index_ldp.xml\n"
        ),
        "/sitemaps/agent-pages.xml": sitemap(f"{PARENT}/agents/jamie-kahn"),
        "/xmlsitemaps/ldp/off-market_index_ldp.xml": "<sitemapindex>" + "".join(
            f"<sitemap><loc>{PARENT}/xmlsitemaps/ldp/off-market_page_{i}_ldp.xml</loc></sitemap>" for i in range(30)
        ) + "</sitemapindex>",
        "/": "<html><a href='/agents'>Agents</a></html>",
        "/agents": f"<html><a href='/profile/alex-kahn'>Alex Kahn</a></html>",
        "/profile/alex-kahn": profile(),
    }
    for i in range(30):
        pages[f"/xmlsitemaps/ldp/off-market_page_{i}_ldp.xml"] = sitemap(*(
            f"{PARENT}/properties/off-market-{i}-{j}" for j in range(2000)
        ))
    site = Site({**{"/sitemap.xml": "", "/sitemap_index.xml": "", "/team": ""}, **pages})
    result = ProfileResolverService(fetcher=site, browser_fetcher=None, total_timeout=3.0).resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_RESOLVED
    assert result.method == "directory"
    assert result.diagnostics["directory_pages_examined"] == 1
    assert result.diagnostics["sitemap_low_value_budget_reached"] is True
    assert result.diagnostics["post_sitemap_budget_preserved"] is True


def test_sprint6f2_large_real_person_sitemap_with_target_still_discovers_candidate() -> None:
    target = f"{PARENT}/agents/alex-kahn"
    urls = [f"{PARENT}/agents/person-{i}" for i in range(9999)] + [target] + [f"{PARENT}/agents/person-extra-{i}" for i in range(10000)]
    service = resolver_for({
        "/robots.txt": f"User-agent: *\nSitemap: {PARENT}/sitemaps/agent-pages.xml\n",
        "/sitemaps/agent-pages.xml": sitemap(*urls),
        "/agents/alex-kahn": profile(),
    }, total_timeout=10.0)
    result = service.resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_RESOLVED
    assert result.resolved_url == target
    row = next(row for row in result.diagnostics["sitemap_diagnostics"] if row.get("url", "").endswith("agent-pages.xml"))
    assert row["semantic_tier"] == "HIGH_VALUE_PERSON"
    assert row["target_name_loc_count"] == 1


def test_sprint6f2_large_real_person_sitemap_no_target_then_low_value_bounded() -> None:
    pages = {
        "/robots.txt": (
            f"User-agent: *\n"
            f"Sitemap: {PARENT}/sitemaps/agent-pages.xml\n"
            f"Sitemap: {PARENT}/xmlsitemaps/ldp/pending_index_ldp.xml\n"
        ),
        "/sitemaps/agent-pages.xml": sitemap(*(f"{PARENT}/agents/person-{i}" for i in range(20000))),
        "/xmlsitemaps/ldp/pending_index_ldp.xml": "<sitemapindex>" + "".join(
            f"<sitemap><loc>{PARENT}/xmlsitemaps/ldp/pending_page_{i}_ldp.xml</loc></sitemap>" for i in range(20)
        ) + "</sitemapindex>",
        "/": "<html><a href='/agents'>Agents</a></html>",
        "/agents": "",
    }
    for i in range(20):
        pages[f"/xmlsitemaps/ldp/pending_page_{i}_ldp.xml"] = sitemap(*(
            f"{PARENT}/properties/pending-{i}-{j}" for j in range(2000)
        ))
    result = resolver_for(pages, total_timeout=10.0).resolve("Alex Kahn", PARENT)
    assert result.status == RESOLUTION_NOT_FOUND
    assert result.diagnostics["sitemap_high_value_count_attempted"] >= 1
    assert result.diagnostics["post_sitemap_budget_preserved"] is True
    assert result.diagnostics["sitemap_low_value_count_attempted"] <= result.diagnostics["bounded_limits"]["max_low_value_sitemaps_attempted"]
    assert result.diagnostics["sitemap_remaining_budget_seconds"] >= result.diagnostics["bounded_limits"]["post_sitemap_reserve_seconds"]
    assert result.diagnostics["sitemap_discovery_end_reason"] in {
        SITEMAP_END_LOW_VALUE_BUDGET_REACHED,
        SITEMAP_END_DISCOVERY_BUDGET_REACHED,
        SITEMAP_END_VERIFICATION_RESERVE_REACHED,
        SITEMAP_END_SITEMAPS_EXHAUSTED,
    }
    if result.diagnostics["sitemap_discovery_end_reason"] == SITEMAP_END_LOW_VALUE_BUDGET_REACHED:
        assert result.diagnostics["sitemap_low_value_budget_reached"] is True