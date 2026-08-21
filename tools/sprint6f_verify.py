"""Sprint 6F verifier -- deterministic person-profile resolver reliability.

Offline and Qt-free. Exercises resolver contracts that protect throughput
without promoting wrong-person profiles.
"""

from __future__ import annotations

import os
import sys
import time
import gzip
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.models.prospect import RESOLUTION_AMBIGUOUS, RESOLUTION_NOT_FOUND, RESOLUTION_RESOLVED, RESOLUTION_TIMEOUT, Prospect  # noqa: E402
from gui.services.copy_quality import PERSON_PROFILE_UNRESOLVED, QUALITY_WARNING, assess_profile_quality  # noqa: E402
from gui.services.profile_resolver import (  # noqa: E402
    FetchError,
    ProfileResolverService,
    SITEMAP_END_DISCOVERY_BUDGET_REACHED,
    SITEMAP_END_LOW_VALUE_BUDGET_REACHED,
    SITEMAP_END_SITEMAPS_EXHAUSTED,
    SITEMAP_END_VERIFICATION_RESERVE_REACHED,
    effective_scrape_url,
)


PARENT = "https://example.com"


def check(name: str, condition: bool, counts: dict[str, int], detail: str = "") -> None:
    print(("PASS" if condition else "FAIL") + f": {name}{' - ' + detail if detail else ''}")
    counts["passed" if condition else "failed"] += 1


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
        if path not in self.pages:
            raise FetchError(f"HTTP 404 for {path}")
        body = self.pages[path]
        if body == "__FAIL__":
            raise FetchError(f"HTTP 503 for {path}")
        return body


def sitemap(*urls: str) -> str:
    return "<urlset>" + "".join(f"<url><loc>{url}</loc></url>" for url in urls) + "</urlset>"


def profile(
    name: str = "Alex Kahn",
    *,
    title: str | None = None,
    h1: str | None = None,
    canonical: str = "",
    schema_name: str | None = None,
    body: str = "Bio experience phone email",
) -> str:
    title = title if title is not None else f"{name} | Example Realty"
    h1 = h1 if h1 is not None else name
    schema_name = schema_name if schema_name is not None else name
    canonical_tag = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    schema = f'<script type="application/ld+json">{{"@type":"Person","name":"{schema_name}"}}</script>' if schema_name else ""
    return f"<html><head><title>{title}</title>{canonical_tag}</head><body><h1>{h1}</h1><img src='/a.jpg'><p>{body}</p>{schema}</body></html>"


def resolver(pages: dict[str, str], **kwargs) -> ProfileResolverService:
    defaults = {"/robots.txt": "", "/sitemap.xml": "", "/sitemap_index.xml": "", "/": "<a href='/team'>Team</a>", "/team": ""}
    defaults.update(pages)
    return ProfileResolverService(fetcher=Site(defaults), browser_fetcher=None, **kwargs)


class LargeSite:
    def __init__(self, *, wrong_person: bool = False, no_agent_sitemap: bool = False, gzip_agents: bool = False) -> None:
        self.requests: list[str] = []
        self.wrong_person = wrong_person
        self.no_agent_sitemap = no_agent_sitemap
        self.gzip_agents = gzip_agents

    def __call__(self, url: str) -> str:
        self.requests.append(url)
        path = urlparse(url).path or "/"
        if path == "/robots.txt":
            return f"User-agent: *\nSitemap: {PARENT}/sitemaps/index.xml\n"
        if path in {"/sitemap.xml", "/sitemap_index.xml"}:
            return ""
        if path == "/sitemaps/index.xml":
            children = [f"{PARENT}/sitemaps/for-sale/index.xml", f"{PARENT}/sitemaps/blog/index.xml"]
            if not self.no_agent_sitemap:
                children.append(f"{PARENT}/sitemaps/agent-pages/index.xml")
            return "<sitemapindex>" + "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in children) + "</sitemapindex>"
        if path == "/sitemaps/agent-pages/index.xml":
            return "<sitemapindex>" f"<sitemap><loc>{PARENT}/sitemaps/agent-pages/sitemap_1.xml.gz</loc></sitemap>" f"<sitemap><loc>{PARENT}/sitemaps/properties/sitemap_9.xml</loc></sitemap>" "</sitemapindex>"
        if path == "/sitemaps/agent-pages/sitemap_1.xml.gz":
            body = sitemap(f"{PARENT}/agents/jamie-kahn", f"{PARENT}/agents/alex-kahn")
            if self.gzip_agents:
                return gzip.decompress(gzip.compress(body.encode("utf-8"))).decode("utf-8")
            return body
        if path in {"/sitemaps/for-sale/index.xml", "/sitemaps/blog/index.xml"}:
            family = path.split("/")[2]
            return "<sitemapindex>" + "".join(f"<sitemap><loc>{PARENT}/sitemaps/{family}/sitemap_{i}.xml</loc></sitemap>" for i in range(1, 4)) + "</sitemapindex>"
        if "/sitemaps/for-sale/" in path or "/sitemaps/properties/" in path:
            return sitemap(*(f"{PARENT}/properties/listing-{i}" for i in range(3000)))
        if "/sitemaps/blog/" in path:
            return sitemap(*(f"{PARENT}/blog/post-{i}" for i in range(25)))
        if path == "/":
            return "<a href='/agents'>Agents</a>"
        if path == "/agents":
            return "<a href='/agents/alex-kahn'>Alex Kahn</a>"
        if path == "/agents/alex-kahn":
            if self.wrong_person:
                return profile(title="Alex Kahn", h1="Jamie Kahn", schema_name="Jamie Kahn")
            return profile()
        if path == "/agents/jamie-kahn":
            return profile(name="Jamie Kahn")
        raise FetchError(f"HTTP 404 for {path}")


def large_result(**kwargs):
    site = LargeSite(**kwargs)
    result = ProfileResolverService(fetcher=site, browser_fetcher=None, total_timeout=3.0).resolve("Alex Kahn", PARENT)
    return result, site


def low_value_budget_result(*, directory_target: bool = True):
    pages = {
        "/robots.txt": (
            f"User-agent: *\n"
            f"Sitemap: {PARENT}/sitemaps/agent-pages.xml\n"
            f"Sitemap: {PARENT}/sitemaps/for-sale-by-agent/index.xml\n"
            f"Sitemap: {PARENT}/xmlsitemaps/ldp/pending_index_ldp.xml\n"
            f"Sitemap: {PARENT}/xmlsitemaps/ldp/off-market_index_ldp.xml\n"
        ),
        "/sitemaps/agent-pages.xml": sitemap(f"{PARENT}/agents/jamie-kahn"),
        "/xmlsitemaps/ldp/pending_index_ldp.xml": "<sitemapindex>" + "".join(
            f"<sitemap><loc>{PARENT}/xmlsitemaps/ldp/pending_page_{i}_ldp.xml</loc></sitemap>" for i in range(12)
        ) + "</sitemapindex>",
        "/xmlsitemaps/ldp/off-market_index_ldp.xml": sitemap(f"{PARENT}/properties/off-market-1"),
        "/sitemaps/for-sale-by-agent/index.xml": sitemap(f"{PARENT}/properties/for-sale-by-agent/alex-kahn-listing"),
        "/": "<a href='/agents'>Agents</a>",
        "/agents": "<a href='/profile/alex-kahn'>Alex Kahn</a>" if directory_target else "",
        "/profile/alex-kahn": profile(),
    }
    for i in range(12):
        pages[f"/xmlsitemaps/ldp/pending_page_{i}_ldp.xml"] = sitemap(*(
            f"{PARENT}/properties/pending-{i}-{j}" for j in range(1500)
        ))
    site = Site({"/sitemap.xml": "", "/sitemap_index.xml": "", **pages})
    result = ProfileResolverService(fetcher=site, browser_fetcher=None, total_timeout=3.0).resolve("Alex Kahn", PARENT)
    return result, site


def deterministic_clock_factory(increment: float):
    elapsed = {"seconds": 0.0}

    def deterministic_clock() -> float:
        elapsed["seconds"] += increment
        return elapsed["seconds"]

    return deterministic_clock


def main() -> int:
    counts = {"passed": 0, "failed": 0}

    strong = resolver({"/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn"), "/agent/alex-kahn": profile()}).resolve("Alex Kahn", PARENT)
    check("exact strong person profile accepted", strong.status == RESOLUTION_RESOLVED and strong.resolved_url.endswith("/agent/alex-kahn"), counts, strong.status)

    weak = resolver({"/sitemap.xml": sitemap(f"{PARENT}/about/alex-kahn"), "/about/alex-kahn": "<html><body>Alex Kahn mentioned in a paragraph.</body></html>"}).resolve("Alex Kahn", PARENT)
    check("weak mention not accepted", weak.status == RESOLUTION_NOT_FOUND and weak.resolved_url == "", counts, weak.status)

    team = resolver({"/sitemap.xml": sitemap(f"{PARENT}/team/alex-kahn", f"{PARENT}/agent/alex-kahn"), "/team/alex-kahn": "<html><body>Alex Kahn and Jamie Kahn</body></html>", "/agent/alex-kahn": profile()}).resolve("Alex Kahn", PARENT)
    check("team page loses to individual profile", team.status == RESOLUTION_RESOLVED and team.resolved_url.endswith("/agent/alex-kahn"), counts, team.status)

    article = resolver({"/sitemap.xml": sitemap(f"{PARENT}/news/alex-kahn-sale", f"{PARENT}/agent/alex-kahn"), "/news/alex-kahn-sale": profile(schema_name="Example News", body="Article mentioning Alex Kahn"), "/agent/alex-kahn": profile()}).resolve("Alex Kahn", PARENT)
    check("article mention loses to individual profile", article.status == RESOLUTION_RESOLVED and article.resolved_url.endswith("/agent/alex-kahn"), counts, article.status)

    equivalent = resolver({"/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn", f"{PARENT}/realtor/alex-kahn?utm=1"), "/agent/alex-kahn": profile(canonical=f"{PARENT}/agent/alex-kahn"), "/realtor/alex-kahn?utm=1": profile(canonical=f"{PARENT}/agent/alex-kahn")}).resolve("Alex Kahn", PARENT)
    check("equivalent candidates collapse safely", equivalent.status == RESOLUTION_RESOLVED, counts, equivalent.status)

    distinct = resolver({"/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn", f"{PARENT}/office2/agent/alex-kahn"), "/agent/alex-kahn": profile(canonical=f"{PARENT}/agent/alex-kahn"), "/office2/agent/alex-kahn": profile(canonical=f"{PARENT}/office2/agent/alex-kahn")}).resolve("Alex Kahn", PARENT)
    check("distinct credible identities remain ambiguous", distinct.status == RESOLUTION_AMBIGUOUS, counts, distinct.status)

    isolated = resolver({"/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn", f"{PARENT}/agent/alex-kahn-broken"), "/agent/alex-kahn": profile(), "/agent/alex-kahn-broken": "__FAIL__"}).resolve("Alex Kahn", PARENT)
    check("candidate failure isolated", isolated.status == RESOLUTION_RESOLVED and any(not c.http_fetch_ok for c in isolated.candidates), counts, isolated.status)

    error = resolver({}).resolve("Alex", "http://localhost")
    check("resolver-level error represented safely", error.status == "ERROR" and error.url == "", counts, error.status)

    def slow_fetch(_url: str) -> str:
        time.sleep(0.05)
        return ""

    timed = ProfileResolverService(fetcher=slow_fetch, total_timeout=0.001).resolve("Alex Kahn", PARENT)
    check("timeout represented as TIMEOUT", timed.status == RESOLUTION_TIMEOUT and timed.url == "", counts, timed.status)
    check("resolver budget preserved", bool(timed.diagnostics.get("timeout_reason")) and timed.diagnostics.get("bounded_limits", {}).get("total_timeout_seconds") == 0.001, counts)

    wrong = resolver({"/sitemap.xml": sitemap(f"{PARENT}/agent/alex-kahn"), "/agent/alex-kahn": profile(title="Alex Kahn", h1="Jamie Kahn", schema_name="Jamie Kahn")}).resolve("Alex Kahn", PARENT)
    check("wrong-person structured identity rejected", wrong.status != RESOLUTION_RESOLVED, counts, wrong.status)

    external = resolver({"/sitemap.xml": sitemap("https://external.example/agent/alex-kahn", f"{PARENT}/news/alex-kahn"), "/news/alex-kahn": "<html><body>Alex Kahn mentioned.</body></html>"}).resolve("Alex Kahn", PARENT)
    check("external-domain contamination protected", external.status == RESOLUTION_NOT_FOUND, counts, external.status)

    prospect = Prospect(prospect_id="p1", company_name="Example Realty", contact_name="Alex Kahn", website=PARENT)
    check("no manual profile injection required", prospect.manual_profile_url == "", counts)
    check("parent Prospect.website remains canonical", prospect.website == PARENT and effective_scrape_url(prospect) == PARENT, counts)

    prospect.resolution_status = RESOLUTION_TIMEOUT
    quality = assess_profile_quality(prospect)
    check("timeout remains unresolved for readiness", quality.status == QUALITY_WARNING and PERSON_PROFILE_UNRESOLVED in {reason.code for reason in quality.reasons}, counts, quality.status)

    large, large_site = large_result()
    check("relevant sitemap prioritized", large.status == RESOLUTION_RESOLVED and large.resolved_url.endswith("/agents/alex-kahn") and large.diagnostics.get("sitemap_prioritization_applied"), counts, large.status)
    check("large irrelevant sitemap bounded", int(large.diagnostics.get("sitemap_count_attempted") or 0) <= 10, counts, str(large.diagnostics.get("sitemap_count_attempted")))
    alex_index = large_site.requests.index(f"{PARENT}/agents/alex-kahn") if f"{PARENT}/agents/alex-kahn" in large_site.requests else 9999
    first_profile_index = min((i for i, url in enumerate(large_site.requests) if url.startswith(f"{PARENT}/agents/")), default=9999)
    check("intended-name candidate prioritized", alex_index == first_profile_index, counts)
    check("verification budget preserved", f"{PARENT}/agents/alex-kahn" in large_site.requests and large.diagnostics.get("verification_reserve_seconds", 0) > 0, counts)
    check("nested sitemap prioritization works", f"{PARENT}/sitemaps/agent-pages/sitemap_1.xml.gz" in large_site.requests, counts)
    gz, _gz_site = large_result(gzip_agents=True)
    check("gzip behavior preserved", gz.status == RESOLUTION_RESOLVED and gz.resolved_url.endswith("/agents/alex-kahn"), counts, gz.status)
    check("high-value person sitemap tier recorded", any(row.get("semantic_tier") == "HIGH_VALUE_PERSON" for row in large.diagnostics.get("sitemap_diagnostics", []) if "agent-pages" in row.get("url", "")), counts)

    low_budget, low_site = low_value_budget_result()
    low_rows = low_budget.diagnostics.get("sitemap_diagnostics", [])
    check("LDP/pending/off-market low-value classification", any("ldp" in row.get("url", "") and row.get("semantic_tier") == "LOW_VALUE_CONTENT" for row in low_rows), counts)
    mixed = resolver({"/robots.txt": f"User-agent: *\nSitemap: {PARENT}/sitemaps/for-sale-by-agent/index.xml\n", "/sitemaps/for-sale-by-agent/index.xml": sitemap(f"{PARENT}/properties/for-sale-by-agent/alex-kahn-listing")}).resolve("Alex Kahn", PARENT)
    check("mixed property/person semantics low-value", any("for-sale-by-agent" in row.get("url", "") and row.get("semantic_tier") == "LOW_VALUE_CONTENT" for row in mixed.diagnostics.get("sitemap_diagnostics", [])), counts)
    check("low-value families preserve post-sitemap budget", low_budget.diagnostics.get("sitemap_low_value_budget_reached") and low_budget.diagnostics.get("post_sitemap_budget_preserved"), counts, str(low_budget.diagnostics.get("sitemap_discovery_end_reason")))
    check("post-sitemap directory discovery still runs", low_budget.status == RESOLUTION_RESOLVED and low_budget.method == "directory" and f"{PARENT}/profile/alex-kahn" in low_site.requests, counts, low_budget.status)

    large_no_target_pages = {
        "/robots.txt": f"User-agent: *\nSitemap: {PARENT}/sitemaps/agent-pages.xml\nSitemap: {PARENT}/xmlsitemaps/ldp/pending_index_ldp.xml\n",
        "/sitemaps/agent-pages.xml": sitemap(*(f"{PARENT}/agents/person-{i}" for i in range(20000))),
        "/xmlsitemaps/ldp/pending_index_ldp.xml": "<sitemapindex>" + "".join(f"<sitemap><loc>{PARENT}/xmlsitemaps/ldp/pending_page_{i}_ldp.xml</loc></sitemap>" for i in range(12)) + "</sitemapindex>",
        "/": "<a href='/agents'>Agents</a>",
        "/agents": "",
    }
    for i in range(12):
        large_no_target_pages[f"/xmlsitemaps/ldp/pending_page_{i}_ldp.xml"] = sitemap(*(f"{PARENT}/properties/pending-{i}-{j}" for j in range(1500)))
    large_no_target = resolver(
        large_no_target_pages,
        total_timeout=10.0,
        monotonic_clock=deterministic_clock_factory(0.25),
    ).resolve("Alex Kahn", PARENT)
    check("large legitimate person sitemap without target remains high-value", large_no_target.diagnostics.get("sitemap_high_value_count_attempted", 0) >= 1, counts)
    large_no_target_end_reason = large_no_target.diagnostics.get("sitemap_discovery_end_reason")
    large_no_target_limits = large_no_target.diagnostics.get("bounded_limits", {})
    large_no_target_bounded = (
        large_no_target.status == RESOLUTION_NOT_FOUND
        and large_no_target.diagnostics.get("post_sitemap_budget_preserved") is True
        and large_no_target.diagnostics.get("sitemap_low_value_count_attempted", 0) <= large_no_target_limits.get("max_low_value_sitemaps_attempted", 0)
        and large_no_target.diagnostics.get("sitemap_remaining_budget_seconds", 0.0) >= large_no_target_limits.get("post_sitemap_reserve_seconds", 0.0)
        and large_no_target_end_reason in {
            SITEMAP_END_LOW_VALUE_BUDGET_REACHED,
            SITEMAP_END_DISCOVERY_BUDGET_REACHED,
            SITEMAP_END_VERIFICATION_RESERVE_REACHED,
            SITEMAP_END_SITEMAPS_EXHAUSTED,
        }
        and (
            large_no_target_end_reason != SITEMAP_END_LOW_VALUE_BUDGET_REACHED
            or large_no_target.diagnostics.get("sitemap_low_value_budget_reached") is True
        )
    )
    check("subsequent low-value inventory bounded after no target", large_no_target_bounded, counts, large_no_target_end_reason or large_no_target.status)

    huge_urls = [f"{PARENT}/agents/person-{i}" for i in range(9999)] + [f"{PARENT}/agents/alex-kahn"] + [f"{PARENT}/agents/person-extra-{i}" for i in range(10000)]
    huge = resolver({"/robots.txt": f"User-agent: *\nSitemap: {PARENT}/sitemaps/agent-pages.xml\n", "/sitemaps/agent-pages.xml": sitemap(*huge_urls), "/agents/alex-kahn": profile()}, total_timeout=10.0).resolve("Alex Kahn", PARENT)
    check("large legitimate person sitemap with target works", huge.status == RESOLUTION_RESOLVED and huge.resolved_url.endswith("/agents/alex-kahn"), counts, huge.status)

    missing_site = LargeSite()
    original = missing_site.__call__
    def missing_profile(url: str) -> str:
        if urlparse(url).path == "/agents/alex-kahn":
            missing_site.requests.append(url)
            raise FetchError("HTTP 404 for profile")
        return original(url)
    missing = ProfileResolverService(fetcher=missing_profile, browser_fetcher=None, total_timeout=3.0).resolve("Alex Kahn", PARENT)
    check("no acceptance before verification", missing.status == RESOLUTION_NOT_FOUND and missing.resolved_url == "", counts, missing.status)
    slow = ProfileResolverService(fetcher=slow_fetch, total_timeout=0.001).resolve("Alex Kahn", PARENT)
    check("timeout remains TIMEOUT", slow.status == RESOLUTION_TIMEOUT, counts, slow.status)
    wrong_large, _wrong_site = large_result(wrong_person=True)
    check("wrong-person safety preserved", wrong_large.status != RESOLUTION_RESOLVED, counts, wrong_large.status)
    generic = resolver({}).resolve("Alex", PARENT)
    check("generic resolver behavior preserved", generic.status == "ERROR", counts, generic.status)

    print(f"\nSprint 6F verifier: {counts['passed']} passed, {counts['failed']} failed")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())