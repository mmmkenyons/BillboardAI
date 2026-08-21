"""Sprint 5Z profile resolution service (Qt-free).

Resolves "Person Name + Parent Organization Website" into a high-confidence
individual profile URL (e.g. a real-estate agent profile inside a brokerage
site). The resolver is strictly an **enrichment** layer: it never modifies
``Prospect.website`` (the authoritative parent/business website) and never
creates a general crawler or people-search platform.

Design rules:

- **Qt-free / UI-free.** This module never imports Qt and spawns no browser.
- **Injectably networked.** All network access goes through a small fetcher
  ``Fetcher`` so deterministic tests and the durable verifier can use local
  fixtures without touching the live web.
- **Bounded and deterministic.** Hard limits on sitemap depth/child count/URL
  count, directory pages, links, and candidate verification are centralized and
  testable. No infinite pagination, no unrestricted crawling.
- **Safety first.** Discovery allows only ``http``/``https`` and rejects
  localhost / loopback / private IP literals (minimal SSRF protection scoped to
  this layer).
- **Same-domain boundary.** Candidates must share the parent registered domain
  (``tldextract``); external domains are never auto-selected.
- **Wrong-person is worse than NOT_FOUND.** Name matching is deterministic and
  exact (full-name tokens with one middle-initial/suffix tolerance). No fuzzy
  edit distance, no nickname guessing, no first/last-name-only matching. A weak
  or ambiguous candidate is never silently auto-selected.

The service also owns ``effective_scrape_url`` (manual profile URL -> resolved
profile URL -> parent website), which the generation layer calls at job
creation so existing execution remains unchanged.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import tldextract

from engine.scraper.browser_fetch import BrowserHtmlResult, fetch_rendered_html

from gui.models.prospect import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_ERROR,
    RESOLUTION_NOT_FOUND,
    RESOLUTION_RESOLVED,
    RESOLUTION_TIMEOUT,
    Prospect,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Centralized bounds / constants (testable)
# ---------------------------------------------------------------------------
DEFAULT_TIMEOUT = 15.0           # seconds for a single resolver HTTP request
DEFAULT_TOTAL_TIMEOUT = 45.0     # deterministic total resolver operation bound
MAX_SITEMAP_DEPTH = 1            # sitemap-index recursion depth
MAX_CHILD_SITEMAPS = 25          # child sitemap <urlset> fetches per index
MAX_SITEMAP_URLS = 20000         # total distinct sitemap URLs consumed
MAX_SITEMAP_BYTES = 5_000_000    # per-sitemap response size guard
MAX_GZIP_DECOMPRESSED_BYTES = 10_000_000  # decompressed sitemap response guard
MAX_DIRECTORY_PAGES = 5          # homepage-linked directory pages to fetch
MAX_HOMEPAGE_LINKS = 800         # homepage <a href> cap for discovery
MAX_LINKS_SCANNED = 600          # per-directory-page link cap
MAX_CANDIDATES_VERIFY = 8        # candidates whose pages we actually fetch
MAX_SITEMAP_DIAGNOSTICS = 20     # compact per-sitemap observability cap
MAX_BROWSER_LINKS_SCANNED = 200  # per rendered page anchor scan cap
MAX_BROWSER_CANDIDATE_VERIFY = 4 # bounded browser verification retries for weak candidates
VERIFICATION_RESERVE_FRACTION = 0.25  # preserve part of total budget for candidate fetches
MIN_VERIFICATION_RESERVE_SECONDS = 5.0
MAX_LOW_VALUE_SITEMAP_URLS_SCANNED = 1200
LOW_VALUE_SITEMAP_DISCOVERY_FRACTION = 0.18
MIN_POST_SITEMAP_RESERVE_SECONDS = 6.0
MAX_LOW_VALUE_SITEMAPS_ATTEMPTED = 6

SITEMAP_TIER_HIGH_VALUE_PERSON = "HIGH_VALUE_PERSON"
SITEMAP_TIER_GENERAL = "GENERAL"
SITEMAP_TIER_LOW_VALUE_CONTENT = "LOW_VALUE_CONTENT"
SITEMAP_END_HIGH_VALUE_CANDIDATE_FOUND = "HIGH_VALUE_CANDIDATE_FOUND"
SITEMAP_END_DISCOVERY_BUDGET_REACHED = "DISCOVERY_BUDGET_REACHED"
SITEMAP_END_LOW_VALUE_BUDGET_REACHED = "LOW_VALUE_BUDGET_REACHED"
SITEMAP_END_VERIFICATION_RESERVE_REACHED = "VERIFICATION_RESERVE_REACHED"
SITEMAP_END_SITEMAPS_EXHAUSTED = "SITEMAPS_EXHAUSTED"
SITEMAP_END_TOTAL_TIMEOUT = "TOTAL_TIMEOUT"

# Path token indicators that a URL is likely an individual/agent profile.
PROFILE_PATH_TOKENS = (
    "agent", "agents", "realtor", "realtors", "team", "staff", "member",
    "members", "directory", "bio", "profile", "profiles", "people", "person",
    "persons", "advisor", "advisors", "broker", "brokers", "associate",
    "associates", "about",
)
# Path tokens that a page is a directory/home (not itself a profile candidate).
DIRECTORY_PATH_TOKENS = (
    "agents", "realtors", "team", "staff", "members", "directory", "people",
)
SUFFIX_TOKENS = frozenset({"jr", "sr", "ii", "iii", "iv", "v", "md", "dds", "esq"})

NETWORK_ERROR_TOKEN = "network/access failure"
GZIP_MAGIC = b"\x1f\x8b"
SITEMAP_FETCH_FAILED = "FETCH_FAILED"
SITEMAP_PARSED_ZERO_LOCS = "PARSED_ZERO_LOCS"
SITEMAP_PARSED_WITH_LOCS = "PARSED_WITH_LOCS"
SITEMAP_TARGET_MATCH_FOUND = "TARGET_MATCH_FOUND"
STATIC_PROFILE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf",
    ".css", ".js", ".ico", ".zip", ".gz",
})
GENERIC_PROFILE_ROOTS = frozenset({"agent", "agents", "profile", "profiles", "team", "staff"})
HIGH_VALUE_SITEMAP_TOKENS = frozenset({
    "agent", "agents", "people", "person", "persons", "profile", "profiles",
    "team", "teams", "staff", "advisor", "advisors", "broker", "brokers",
    "realtor", "realtors", "associate", "associates", "member", "members",
})
LOW_VALUE_SITEMAP_TOKENS = frozenset({
    "property", "properties", "listing", "listings", "home", "homes", "sale",
    "rent", "rental", "rentals", "sold", "pending", "off", "market",
    "offmarket", "ldp", "pdp", "detail", "details", "inventory", "search",
    "community", "communities", "neighborhood", "neighborhoods",
    "blog", "blogs", "post", "posts", "article", "articles", "news", "press",
    "image", "images", "video", "videos", "product", "products", "building",
    "buildings", "static", "assets", "office", "offices", "location", "locations",
})
EXPLICIT_PERSON_SITEMAP_TOKENS = frozenset({
    "pages", "profiles", "profile", "people", "person", "persons", "team", "teams",
    "staff", "realtors", "brokers", "advisors", "associates",
})

# ---------------------------------------------------------------------------
# Fetching abstraction (injectable for deterministic tests)
# ---------------------------------------------------------------------------


class FetchError(Exception):
    """Raised when a bounded discovery fetch fails (non-2xx, timeout, size)."""


#: Fetcher signature: ``(url) -> body str``, raising FetchError on failure.
Fetcher = Callable[[str], str]
BrowserFetcher = Callable[[str], BrowserHtmlResult]


def default_fetcher(timeout: float = DEFAULT_TIMEOUT) -> Fetcher:
    """Production fetcher: requests + engine user-agent + redirect + size cap."""
    from engine import config as engine_config

    def _fetch(url: str) -> str:
        try:
            response = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": engine_config.USER_AGENT},
                allow_redirects=True,
                stream=True,
            )
        except requests.RequestException as exc:  # noqa: BLE001
            raise FetchError(f"{NETWORK_ERROR_TOKEN}: {exc}") from exc
        if response.status_code != 200:
            raise FetchError(f"HTTP {response.status_code} for {url}")
        chunks: List[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_SITEMAP_BYTES:
                raise FetchError(f"response too large for {url}")
            chunks.append(chunk)
        payload = b"".join(chunks)
        if _is_gzip_payload(url, response.headers.get("Content-Type"), payload):
            payload = _decompress_gzip(payload, url)
        return payload.decode("utf-8", errors="replace")

    return _fetch


def _is_gzip_payload(url: str, content_type: str | None, payload: bytes) -> bool:
    """True for actual gzip bytes or sitemap/document URLs advertised as gzip."""
    low_url = (url or "").lower()
    low_type = (content_type or "").lower()
    return payload.startswith(GZIP_MAGIC) or low_url.endswith(".gz") or "gzip" in low_type


def _decompress_gzip(payload: bytes, url: str) -> bytes:
    """Bounded single-member gzip decompression for sitemap fetches."""
    try:
        data = gzip.decompress(payload)
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise FetchError(f"malformed gzip response for {url}") from exc
    if len(data) > MAX_GZIP_DECOMPRESSED_BYTES:
        raise FetchError(f"decompressed response too large for {url}")
    return data


# ---------------------------------------------------------------------------
# URL safety + domain boundary
# ---------------------------------------------------------------------------

_PRIVATE_HOST_RE = re.compile(
    r"^(127\.|10\.|192\.168\.|169\.254\.|0\.0\.0\.0$|"
    r"100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)"
)
_PRIVATE_HOST_RE2 = re.compile(r"^(172\.(1[6-9]|2\d|3[01])\.)")


def is_safe_url(url: str) -> bool:
    """Return True when the URL is a bounded http(s) target we may fetch."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or host == "::1":
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return False
    if _PRIVATE_HOST_RE.match(host) or _PRIVATE_HOST_RE2.match(host):
        return False
    return "." in host


_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def normalize_url(raw: str) -> str:
    """Best-effort absolute URL; prepend https:// when scheme-less."""
    if not raw:
        return ""
    value = raw.strip()
    if not _URL_SCHEME_RE.match(value):
        value = "https://" + value
    return value


def parent_origin(url: str) -> str:
    """Return ``scheme://netloc`` for a parent website URL (https default)."""
    value = normalize_url(url)
    if not value:
        return ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc}"


def registered_domain(url: str) -> str:
    """Return the lowercase registered domain, e.g. 'pinnaclerealtyia.com'."""
    value = normalize_url(url)
    if not value:
        return ""
    try:
        return (tldextract.extract(value).top_domain_under_public_suffix or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def same_registered_domain(a: str, b: str) -> bool:
    rac = registered_domain(a)
    return bool(rac) and rac == registered_domain(b)


def is_within_parent(candidate: str, parent: str) -> bool:
    """Candidates must be a safe http(s) URL within the parent's registration."""
    candidate = normalize_url(candidate)
    parent = parent_origin(parent)
    return bool(is_safe_url(candidate)) and bool(is_safe_url(parent)) and (
        same_registered_domain(candidate, parent)
    )


# ---------------------------------------------------------------------------
# Name normalization (deterministic, conservative)
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^0-9\w\s\-']")
_WS_RE = re.compile(r"\s+")
_INITIAL_RE = re.compile(r"^[a-z]$")


def normalize_person_name(name: Any) -> str:
    """Canonical person name (lowercase, unicode-normalized, tokenized).

    ``Meridith A. Hoffman`` and ``MERIDITH-HOFFMAN`` both become
    ``meridith a hoffman``. Returns ``""`` for blank/whitespace input.
    """
    if name is None:
        return ""
    text = unicodedata.normalize("NFKD", str(name)).strip()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip().lower()


def normalize_person_slug(name: Any) -> str:
    """URL-ish slug from a person name (e.g. ``meridith-hoffman``)."""
    return "-".join(t for t in normalize_person_name(name).split() if t)


def person_name_tokens(name: Any) -> tuple[str, ...]:
    return tuple(t for t in normalize_person_name(name).split() if t)


def _core_name_tokens(name: Any) -> tuple[str, ...]:
    """First + last tokens, dropping one middle initial and conventional suffixes.

    Returns ``()`` when fewer than two distinct salient tokens exist, so
    first-name-only / last-name-only matching is structurally impossible.
    """
    tokens = [t for t in person_name_tokens(name)]
    if len(tokens) < 2:
        return ()
    # Drop conventional suffixes anywhere.
    tokens = [t for t in tokens if t not in SUFFIX_TOKENS]
    if len(tokens) < 2:
        return ()
    # Drop a single middle initial (a one-letter token between first and last).
    reduced: List[str] = [tokens[0]]
    middle = tokens[1:-1]
    initials = [t for t in middle if _INITIAL_RE.match(t)]
    if len(initials) >= 1 and len(middle) == 1:
        # exactly one token sits between first and last and it's an initial
        reduced = [tokens[0]] + [tokens[-1]]
    else:
        reduced = [tokens[0]] + [t for t in middle if not _INITIAL_RE.match(t)] + [tokens[-1]]
    # De-dup adjacent duplicates while preserving order.
    out: List[str] = []
    for t in reduced:
        if not out or out[-1] != t:
            out.append(t)
    return tuple(out)


def persons_match(name_a: Any, name_b: Any) -> bool:
    """Exact full-name comparison (one middle-initial / suffix tolerant)."""
    ca, cb = _core_name_tokens(name_a), _core_name_tokens(name_b)
    return bool(ca) and ca == cb


def full_name_in_text(name: Any, text: Any) -> bool:
    """True when the full name appears contiguously in a token stream (with
    at most one middle initial/suffix tolerated). Never a first/last-only match.
    """
    tokens = _ws_tokens(text)
    core = _core_name_tokens(name)
    if len(core) < 2 or len(tokens) < 2:
        return False
    first, last = core[0], core[-1]
    # Direct adjacency.
    for i in range(len(tokens) - 1):
        if tokens[i] == first and tokens[i + 1] == last:
            return True
    # Tolerate a single middle token that is an initial or suffix.
    for i in range(len(tokens) - 2):
        if tokens[i] == first and tokens[i + 2] == last:
            middle = tokens[i + 1]
            if _INITIAL_RE.match(middle) or middle in SUFFIX_TOKENS:
                return True
    return False


def _ws_tokens(text: Any) -> tuple[str, ...]:
    if not text:
        return ()
    norm = unicodedata.normalize("NFKD", str(text)).strip().lower()
    return tuple(t for t in _WS_RE.sub(" ", norm).split() if t)


def name_in_url_slug(name: Any, url: str) -> bool:
    """True when first+last name tokens appear in the URL path (hyphen tolerant)."""
    core = _core_name_tokens(name)
    if len(core) < 2:
        return False
    try:
        path = (urlparse(normalize_url(url)).path or "").strip("/").lower()
    except ValueError:
        return False
    if not path:
        return False
    slug_tokens = [t.strip().strip("._-") for t in re.split(r"[/\-\s_]+", path) if t.strip()]
    if not slug_tokens:
        return False
    return core[0] in slug_tokens and core[-1] in slug_tokens


# ---------------------------------------------------------------------------
# Parsers (robots + sitemap)
# ---------------------------------------------------------------------------

_SITEMAP_LINE_RE = re.compile(
    r"^\s*Sitemap\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE
)


def parse_robots_sitemaps(robots_text: str) -> List[str]:
    """Return distinct ``Sitemap:`` URLs declared in robots.txt."""
    out: List[str] = []
    seen = set()
    for match in _SITEMAP_LINE_RE.finditer(robots_text or ""):
        url = match.group(1).strip()
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _fetch_or_none(fetcher: Fetcher, url: str) -> Optional[str]:
    if not is_safe_url(url):
        return None
    try:
        return fetcher(url)
    except Exception as exc:  # noqa: BLE001 - never let one fetch kill a batch
        logger.debug("resolver fetch failed for %s: %s", url, exc)
        return None


def _bounded_failure_reason(exc: Exception) -> str:
    """Compact, non-body failure reason suitable for diagnostics metadata."""
    text = " ".join(str(exc or "").split())
    return text[:160]


def _looks_gzip_sitemap_url(url: str) -> bool:
    return (url or "").lower().split("?", 1)[0].endswith(".gz")


def _profile_sitemap_fallbacks(index_url: str) -> List[str]:
    """Small same-directory profile-sitemap fallbacks for blocked sitemap indexes.

    Some real estate platforms expose typed child sitemaps even when their
    sitemap index endpoint is intermittently inaccessible. This does not guess a
    person/profile URL; it only tries bounded, profile-oriented sitemap names
    under an already discovered sitemap-index directory.
    """
    try:
        parsed = urlparse(index_url)
    except ValueError:
        return []
    path = parsed.path or ""
    if path.count("/") < 2:
        return []
    leaf = path.rsplit("/", 1)[-1].lower()
    if leaf not in {"index.xml", "sitemap.xml", "sitemap_index.xml"}:
        return []
    base = index_url.rsplit("/", 1)[0].rstrip("/")
    if not base:
        return []
    names = (
        "sitemap-agent-profiles-1.xml.gz",
        "sitemap-agent-html-sitemap-1.xml.gz",
        "sitemap-agents.xml",
        "sitemap-realtors.xml",
        "sitemap-team.xml",
    )
    return [f"{base}/{name}" for name in names]


def _append_sitemap_diagnostic(diag: Dict[str, Any], record: Dict[str, Any]) -> None:
    records = diag.setdefault("sitemap_diagnostics", [])
    if not isinstance(records, list) or len(records) >= MAX_SITEMAP_DIAGNOSTICS:
        return
    url = str(record.get("url") or "")
    semantic_tier = str(record.get("semantic_tier") or _sitemap_semantic_tier(url))
    compact = {
        "url": url[:240],
        "fetch": str(record.get("fetch") or "")[:40],
        "parse": str(record.get("parse") or "")[:40],
        "gzip_url": bool(record.get("gzip_url")),
        "loc_count": int(record.get("loc_count") or 0),
        "urls_scanned_count": int(record.get("urls_scanned_count") or 0),
        "target_name_loc_count": int(record.get("target_name_loc_count") or 0),
        "candidate_admitted_count": int(record.get("candidate_admitted_count") or 0),
        "relevance_score": int(record.get("relevance_score") or 0),
        "semantic_tier": semantic_tier,
        "low_value_sitemap": bool(record.get("low_value_sitemap")) or semantic_tier == SITEMAP_TIER_LOW_VALUE_CONTENT,
        "high_value_sitemap": bool(record.get("high_value_sitemap")) or semantic_tier == SITEMAP_TIER_HIGH_VALUE_PERSON,
        "skipped_by_relevance_cap": int(record.get("skipped_by_relevance_cap") or 0),
    }
    prioritized = record.get("prioritized_child_urls") or []
    if isinstance(prioritized, list) and prioritized:
        compact["prioritized_child_urls"] = [str(url)[:240] for url in prioritized[:5]]
    reason = str(record.get("failure_reason") or "")[:160]
    if reason:
        compact["failure_reason"] = reason
    records.append(compact)


def _extract_loc_urls(xml_text: str, cap: int) -> List[str]:
    """Return the <loc> URLs from a sitemap / index XML blob (bounded)."""
    out: List[str] = []
    if not xml_text:
        return out
    try:
        soup = BeautifulSoup(xml_text, "xml")
    except Exception:  # noqa: BLE001
        return out
    for loc in soup.find_all("loc"):
        text = (loc.get_text("", strip=True) or "").strip()
        if not text or not is_safe_url(text):
            continue
        out.append(text)
        if len(out) >= cap:
            break
    return out


def _sitemaps_from_index(index_text: str, cap: int) -> List[str]:
    discovered = _extract_loc_urls(index_text, max(cap * 4, cap))
    return _prioritize_sitemap_urls(discovered)[:cap]


def _urls_from_sitemap(sitemap_text: str, cap: int) -> List[str]:
    return _extract_loc_urls(sitemap_text, cap)


def _looks_like_index(body: str) -> bool:
    low = (body or "").lower()
    return "<sitemapindex" in low


def _path_tokens(url: str) -> set[str]:
    try:
        parsed = urlparse(url)
    except ValueError:
        return set()
    text = " ".join([parsed.path or "", parsed.query or ""]).lower()
    return {t.strip().strip("._-") for t in re.split(r"[/\-_\s=&?]+", text) if t.strip()}


def _sitemap_relevance_score(url: str) -> int:
    """Generic semantic priority for sitemap traversal (higher first)."""
    tokens = _path_tokens(url)
    high = len(tokens & HIGH_VALUE_SITEMAP_TOKENS)
    low = len(tokens & LOW_VALUE_SITEMAP_TOKENS)
    if _is_property_by_person_sitemap(url):
        low += 3
        high = 0
    score = high * 20 - low * 8
    low_url = (url or "").lower()
    if "sitemap" in low_url:
        score += 1
    if _looks_gzip_sitemap_url(url):
        score += 1
    return score


def _sitemap_semantic_tier(url: str) -> str:
    """Classify sitemap families into bounded discovery tiers.

    Property/listing/content semantics dominate mixed names such as
    ``for-sale-by-agent`` unless explicit profile/person-page context exists.
    """
    tokens = _path_tokens(url)
    has_low = bool(tokens & LOW_VALUE_SITEMAP_TOKENS)
    has_high = bool(tokens & HIGH_VALUE_SITEMAP_TOKENS)
    explicit_profile = bool(tokens & EXPLICIT_PERSON_SITEMAP_TOKENS) or _looks_agent_profile_sitemap(url)
    if _is_property_by_person_sitemap(url) or (has_low and not explicit_profile):
        return SITEMAP_TIER_LOW_VALUE_CONTENT
    if has_high or explicit_profile:
        return SITEMAP_TIER_HIGH_VALUE_PERSON
    return SITEMAP_TIER_GENERAL


def _prioritize_sitemap_urls(urls: Sequence[str]) -> List[str]:
    indexed = list(enumerate(urls))
    return [
        url
        for _, url in sorted(
            indexed,
            key=lambda item: (-_sitemap_relevance_score(item[1]), item[0], item[1]),
        )
    ]


def _is_low_value_sitemap(url: str) -> bool:
    return _sitemap_semantic_tier(url) == SITEMAP_TIER_LOW_VALUE_CONTENT


def _is_high_value_sitemap(url: str) -> bool:
    return _sitemap_semantic_tier(url) == SITEMAP_TIER_HIGH_VALUE_PERSON


def _is_property_by_person_sitemap(url: str) -> bool:
    """True for listing/property sitemap families segmented by person/agent."""
    tokens = _path_tokens(url)
    has_listing_context = bool(tokens & LOW_VALUE_SITEMAP_TOKENS)
    has_person_token = bool(tokens & HIGH_VALUE_SITEMAP_TOKENS)
    has_explicit_profile_context = bool(tokens & EXPLICIT_PERSON_SITEMAP_TOKENS)
    return has_listing_context and has_person_token and not has_explicit_profile_context and not _looks_agent_profile_sitemap(url)


def _url_person_relevance_score(url: str, person: str) -> int:
    score = 0
    if name_in_url_slug(person, url):
        score += 100
    if _looks_profile_path(url):
        score += 40
    if _looks_directory_path(url):
        score -= 15
    if _looks_article_path(url):
        score -= 25
    if _is_static_profile_candidate(url):
        score -= 100
    tokens = _path_tokens(url)
    score += 6 * len(tokens & HIGH_VALUE_SITEMAP_TOKENS)
    score -= 5 * len(tokens & LOW_VALUE_SITEMAP_TOKENS)
    if _is_property_by_person_sitemap(url):
        score -= 30
    return score


# ---------------------------------------------------------------------------
# Resolution result model
# ---------------------------------------------------------------------------


@dataclass
class ResolutionCandidate:
    """Explainable evidence snapshot for one candidate profile URL."""

    url: str = ""
    method: str = ""                 # sitemap | directory | homepage
    strong_name: bool = False        # full name in title/heading/content/jsonld
    strong_slug: bool = False        # name slug in URL + corroboration
    slug_only: bool = False          # name slug in URL but weak corroboration
    title_contains_name: bool = False
    has_schema: bool = False
    has_contact: bool = False
    has_image: bool = False
    has_bio: bool = False
    linked_from_directory: bool = False
    same_domain: bool = False
    reason: str = ""
    confidence: str = ""
    http_fetch_ok: bool = False
    http_failure_reason: str = ""
    http_evidence_summary: str = ""
    http_confidence: str = ""
    browser_verification_attempted: bool = False
    browser_final_url: str = ""
    browser_title: str = ""
    browser_evidence_summary: str = ""
    browser_confidence: str = ""
    browser_failure_reason: str = ""
    canonical_url: str = ""
    final_url: str = ""
    structured_names: List[str] = field(default_factory=list)

    def plausibility_score(self) -> int:
        score = 0
        if self.strong_name:
            score += 8
        if self.strong_slug:
            score += 5
        if self.slug_only:
            score += 2
        if self.title_contains_name:
            score += 2
        if self.has_schema:
            score += 3
        if self.linked_from_directory:
            score += 2
        if self.has_contact:
            score += 1
        if self.has_image:
            score += 1
        if self.has_bio:
            score += 1
        return score

    def is_strong(self) -> bool:
        return self.strong_name or self.strong_slug


@dataclass
class ResolutionResult:
    """Structured outcome of a single profile resolution."""

    status: str = "NOT_ATTEMPTED"
    url: str = ""
    confidence: str = ""
    method: str = ""
    evidence: str = ""
    candidates: List[ResolutionCandidate] = None  # type: ignore[assignment]
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.candidates is None:
            self.candidates = []

    @property
    def resolved_url(self) -> str:
        return self.url if self.status == RESOLUTION_RESOLVED and self.url else ""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ProfileResolverService:
    """Qt-free resolver orchestrating discovery, decision, and effective URL.

    Network access is injected via :attr:`fetcher` (defaults to the
    ``requests``-based production fetcher) so all tests and the durable verifier
    are deterministic and offline.
    """

    def __init__(
        self,
        *,
        fetcher: Optional[Fetcher] = None,
        browser_fetcher: Optional[BrowserFetcher] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_child_sitemaps: int = MAX_CHILD_SITEMAPS,
        max_sitemap_urls: int = MAX_SITEMAP_URLS,
        max_directory_pages: int = MAX_DIRECTORY_PAGES,
        max_homepage_links: int = MAX_HOMEPAGE_LINKS,
        max_links_scanned: int = MAX_LINKS_SCANNED,
        max_candidates_verify: int = MAX_CANDIDATES_VERIFY,
        max_browser_links_scanned: int = MAX_BROWSER_LINKS_SCANNED,
        max_browser_candidate_verify: int = MAX_BROWSER_CANDIDATE_VERIFY,
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
    ) -> None:
        self._fetcher = fetcher or default_fetcher(timeout=timeout)
        self._browser_fetcher = browser_fetcher
        self._timeout = timeout
        self.max_child_sitemaps = max_child_sitemaps
        self.max_sitemap_urls = max_sitemap_urls
        self.max_directory_pages = max_directory_pages
        self.max_homepage_links = max_homepage_links
        self.max_links_scanned = max_links_scanned
        self.max_candidates_verify = max_candidates_verify
        self.max_browser_links_scanned = max_browser_links_scanned
        self.max_browser_candidate_verify = max_browser_candidate_verify
        self.total_timeout = max(0.001, float(total_timeout or DEFAULT_TOTAL_TIMEOUT))

    def _validate_input(self, person_name: str, parent_website: str):
        parent = parent_origin(parent_website)
        if not parent or not is_safe_url(parent):
            return ResolutionResult(status=RESOLUTION_ERROR,
                                    evidence="parent website is not a safe http(s) URL")
        person = (person_name or "").strip()
        if not person:
            return ResolutionResult(status=RESOLUTION_ERROR, evidence="person name required")
        if len(_core_name_tokens(person)) < 2:
            return ResolutionResult(status=RESOLUTION_ERROR,
                                    evidence="person name needs first and last name")
        return person, parent

    def resolve(self, person_name: str, parent_website: str) -> ResolutionResult:
        """Resolve a person profile within the parent's web presence."""
        _require = self._validate_input(person_name, parent_website)
        if isinstance(_require, ResolutionResult):
            return _require
        person, parent = _require
        started = time.monotonic()

        seen: Dict[str, ResolutionCandidate] = {}
        candidates: List[ResolutionCandidate] = []
        diagnostics: Dict[str, Any] = {
            "robots_fetched": False,
            "sitemap_count_attempted": 0,
            "sitemap_count_parsed": 0,
            "sitemap_urls_examined": [],
            "candidate_count_before_filtering": 0,
            "candidate_count_after_filtering": 0,
            "http_candidates_discovered": 0,
            "http_candidates_usable": 0,
            "http_candidates_unusable": 0,
            "browser_fallback_trigger_reason": "NOT_NEEDED",
            "directory_pages_examined": 0,
            "browser_fallback_attempted": False,
            "browser_homepage_status": "NOT_ATTEMPTED",
            "browser_directory_pages_examined": 0,
            "browser_links_examined": 0,
            "browser_candidates_discovered": 0,
            "browser_failure_reason": "",
            "browser_candidate_verifications_attempted": 0,
            "candidate_diagnostics": [],
            "final_decision_reason": "",
            "sitemap_diagnostics": [],
            "sitemap_prioritization_applied": False,
            "sitemap_low_value_skipped_after_candidate": 0,
            "sitemap_url_entries_skipped_by_relevance_cap": 0,
            "sitemap_high_value_count_attempted": 0,
            "sitemap_general_count_attempted": 0,
            "sitemap_low_value_count_attempted": 0,
            "sitemap_low_value_budget_reached": False,
            "sitemap_discovery_budget_reached": False,
            "post_sitemap_budget_preserved": False,
            "sitemap_remaining_budget_seconds": 0.0,
            "sitemap_discovery_end_reason": "",
            "verification_reserve_seconds": round(min(self.total_timeout * VERIFICATION_RESERVE_FRACTION, max(MIN_VERIFICATION_RESERVE_SECONDS, self.total_timeout * 0.1)), 3),
            "verification_reserve_reached": False,
            "verification_reserve_consumed": False,
            "bounded_limits": {
                "http_request_timeout_seconds": self._timeout,
                "max_child_sitemaps": self.max_child_sitemaps,
                "max_sitemap_urls": self.max_sitemap_urls,
                "max_directory_pages": self.max_directory_pages,
                "max_homepage_links": self.max_homepage_links,
                "max_links_scanned": self.max_links_scanned,
                "max_candidates_verify": self.max_candidates_verify,
                "max_browser_links_scanned": self.max_browser_links_scanned,
                "max_browser_candidate_verify": self.max_browser_candidate_verify,
                "total_timeout_seconds": self.total_timeout,
                "max_low_value_sitemap_urls_scanned": MAX_LOW_VALUE_SITEMAP_URLS_SCANNED,
                "max_low_value_sitemaps_attempted": MAX_LOW_VALUE_SITEMAPS_ATTEMPTED,
                "post_sitemap_reserve_seconds": round(min(self.total_timeout * 0.35, max(MIN_POST_SITEMAP_RESERVE_SECONDS, self.total_timeout * 0.2)), 3),
                "low_value_sitemap_discovery_seconds": round(max(0.25, self.total_timeout * LOW_VALUE_SITEMAP_DISCOVERY_FRACTION), 3),
            },
            "timeout_reason": "",
        }

        def _timed_out(stage: str) -> bool:
            elapsed = time.monotonic() - started
            diagnostics["elapsed_seconds"] = round(elapsed, 3)
            if elapsed <= self.total_timeout:
                return False
            diagnostics["timeout_reason"] = f"TOTAL_RESOLUTION_TIMEOUT:{stage}"
            diagnostics["final_decision_reason"] = "resolution timed out before completing all bounded stages"
            return True

        def _remaining_budget(stage: str) -> float:
            remaining = self.total_timeout - (time.monotonic() - started)
            diagnostics["elapsed_seconds"] = round(time.monotonic() - started, 3)
            if remaining <= 0:
                diagnostics["timeout_reason"] = f"TOTAL_RESOLUTION_TIMEOUT:{stage}"
                diagnostics["final_decision_reason"] = "resolution timed out before starting next bounded operation"
                raise TimeoutError(diagnostics["timeout_reason"])
            return max(0.001, remaining)

        def _remaining_seconds() -> float:
            remaining = self.total_timeout - (time.monotonic() - started)
            diagnostics["elapsed_seconds"] = round(time.monotonic() - started, 3)
            return max(0.0, remaining)

        def _has_high_value_candidate() -> bool:
            return any(name_in_url_slug(person, c.url) and _looks_profile_path(c.url) for c in candidates)

        def _verification_reserve_seconds() -> float:
            return float(diagnostics.get("verification_reserve_seconds") or 0.0)

        def _post_sitemap_reserve_seconds() -> float:
            limits = diagnostics.get("bounded_limits") or {}
            return float(limits.get("post_sitemap_reserve_seconds") or 0.0)

        def _sitemap_low_value_budget_seconds() -> float:
            limits = diagnostics.get("bounded_limits") or {}
            return float(limits.get("low_value_sitemap_discovery_seconds") or 0.0)

        def _note_sitemap_attempt(url: str) -> str:
            tier = _sitemap_semantic_tier(url)
            if tier == SITEMAP_TIER_HIGH_VALUE_PERSON:
                diagnostics["sitemap_high_value_count_attempted"] += 1
            elif tier == SITEMAP_TIER_LOW_VALUE_CONTENT:
                diagnostics["sitemap_low_value_count_attempted"] += 1
            else:
                diagnostics["sitemap_general_count_attempted"] += 1
            return tier

        def _finish_sitemap_discovery(reason: str) -> None:
            diagnostics["sitemap_discovery_end_reason"] = reason
            remaining = _remaining_seconds()
            diagnostics["sitemap_remaining_budget_seconds"] = round(remaining, 3)
            diagnostics["post_sitemap_budget_preserved"] = remaining >= min(
                _post_sitemap_reserve_seconds(),
                max(0.0, self.total_timeout - 0.001),
            )

        def _should_stop_sitemap_for_budget(next_sitemap_url: str) -> bool:
            tier = _sitemap_semantic_tier(next_sitemap_url)
            remaining = _remaining_seconds()
            if remaining <= _verification_reserve_seconds():
                diagnostics["verification_reserve_reached"] = True
                _finish_sitemap_discovery(SITEMAP_END_VERIFICATION_RESERVE_REACHED)
                return True
            if tier == SITEMAP_TIER_LOW_VALUE_CONTENT:
                elapsed = time.monotonic() - started
                low_count = int(diagnostics.get("sitemap_low_value_count_attempted") or 0)
                if low_count >= MAX_LOW_VALUE_SITEMAPS_ATTEMPTED or elapsed >= _sitemap_low_value_budget_seconds():
                    diagnostics["sitemap_low_value_budget_reached"] = True
                    _finish_sitemap_discovery(SITEMAP_END_LOW_VALUE_BUDGET_REACHED)
                    return True
                if remaining <= _post_sitemap_reserve_seconds():
                    diagnostics["sitemap_discovery_budget_reached"] = True
                    _finish_sitemap_discovery(SITEMAP_END_DISCOVERY_BUDGET_REACHED)
                    return True
            return False

        def _should_stop_sitemap_for_verification(next_sitemap_url: str = "") -> bool:
            if not _has_high_value_candidate():
                return False
            if next_sitemap_url:
                diagnostics["verification_reserve_reached"] = True
                _finish_sitemap_discovery(SITEMAP_END_HIGH_VALUE_CANDIDATE_FOUND)
                return True
            reserve = _verification_reserve_seconds()
            remaining = _remaining_seconds()
            if remaining <= reserve:
                diagnostics["verification_reserve_reached"] = True
                _finish_sitemap_discovery(SITEMAP_END_VERIFICATION_RESERVE_REACHED)
                return True
            if next_sitemap_url and _is_low_value_sitemap(next_sitemap_url) and remaining <= reserve * 1.5:
                diagnostics["verification_reserve_reached"] = True
                _finish_sitemap_discovery(SITEMAP_END_VERIFICATION_RESERVE_REACHED)
                return True
            return False

        def _fetch_with_budget(url: str, stage: str) -> str:
            budget = _remaining_budget(stage)
            diagnostics["timeout_stage"] = stage
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="profile-resolver-fetch")
            future = executor.submit(self._fetcher, url)
            try:
                return future.result(timeout=budget)
            except FutureTimeoutError as exc:
                future.cancel()
                diagnostics["elapsed_seconds"] = round(time.monotonic() - started, 3)
                diagnostics["timeout_reason"] = f"TOTAL_RESOLUTION_TIMEOUT:{stage}"
                diagnostics["final_decision_reason"] = "blocking fetch exceeded remaining resolver budget"
                raise TimeoutError(diagnostics["timeout_reason"]) from exc
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

        def _safe_fetch_with_budget(url: str, stage: str) -> Optional[str]:
            if not is_safe_url(url):
                return None
            try:
                return _fetch_with_budget(url, stage)
            except TimeoutError:
                raise
            except Exception as exc:  # noqa: BLE001 - one fetch must not kill resolution
                logger.debug("resolver fetch failed for %s: %s", url, exc)
                return None

        def _browser_fetch_with_budget(url: str, stage: str) -> BrowserHtmlResult:
            budget = _remaining_budget(stage)
            diagnostics["timeout_stage"] = stage
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="profile-resolver-browser")
            future = executor.submit(self._browser_fetch, url)
            try:
                return future.result(timeout=budget)
            except FutureTimeoutError as exc:
                future.cancel()
                diagnostics["elapsed_seconds"] = round(time.monotonic() - started, 3)
                diagnostics["timeout_reason"] = f"TOTAL_RESOLUTION_TIMEOUT:{stage}"
                diagnostics["final_decision_reason"] = "blocking browser operation exceeded remaining resolver budget"
                raise TimeoutError(diagnostics["timeout_reason"]) from exc
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

        def _timeout_result(stage: str, current: Optional[List[ResolutionCandidate]] = None) -> ResolutionResult:
            _timed_out(stage)
            if stage == "sitemap_discovery":
                _finish_sitemap_discovery(SITEMAP_END_TOTAL_TIMEOUT)
            return ResolutionResult(status=RESOLUTION_TIMEOUT, evidence="resolution timeout", candidates=current or candidates, diagnostics=diagnostics)

        def _add_candidate(c: ResolutionCandidate) -> None:
            diagnostics["candidate_count_before_filtering"] += 1
            if not c.url:
                return
            if _is_static_profile_candidate(c.url):
                return
            existing = seen.get(c.url)
            if existing is not None:
                existing.linked_from_directory = (
                    existing.linked_from_directory or c.linked_from_directory
                )
                existing.method = existing.method or c.method
                return
            if is_within_parent(c.url, parent):
                seen[c.url] = c
                candidates.append(c)
                diagnostics["candidate_count_after_filtering"] = len(candidates)

        # Stage 1/2: robots-declared sitemaps + conventional sitemap endpoints.
        try:
            sitemap_urls = self._collect_sitemap_urls(parent, fetcher=lambda url: _safe_fetch_with_budget(url, "collect_sitemaps"))
        except TimeoutError:
            return _timeout_result("collect_sitemaps")
        if _timed_out("collect_sitemaps"):
            return _timeout_result("collect_sitemaps")
        diagnostics["robots_fetched"] = getattr(self, "_last_robots_fetched", False)
        generated_fallbacks = set(getattr(self, "_last_generated_sitemap_fallbacks", set()))
        primary_sitemap_urls = [url for url in sitemap_urls if url not in generated_fallbacks]
        fallback_sitemap_urls = [url for url in sitemap_urls if url in generated_fallbacks]
        prioritized_sitemap_urls = _prioritize_sitemap_urls(primary_sitemap_urls) + _prioritize_sitemap_urls(fallback_sitemap_urls)
        diagnostics["sitemap_prioritization_applied"] = prioritized_sitemap_urls != sitemap_urls
        diagnostics["sitemap_urls_examined"] = prioritized_sitemap_urls[:10]
        for sm in prioritized_sitemap_urls:
            if _timed_out("sitemap_discovery"):
                return _timeout_result("sitemap_discovery", candidates)
            if _should_stop_sitemap_for_verification(sm):
                diagnostics["sitemap_low_value_skipped_after_candidate"] += 1
                break
            if _should_stop_sitemap_for_budget(sm):
                break
            diagnostics["sitemap_count_attempted"] += 1
            sm_tier = _note_sitemap_attempt(sm)
            sm_record: Dict[str, Any] = {"url": sm, "gzip_url": _looks_gzip_sitemap_url(sm), "relevance_score": _sitemap_relevance_score(sm), "semantic_tier": sm_tier}
            try:
                body = _fetch_with_budget(sm, "sitemap_discovery")
            except TimeoutError:
                return _timeout_result("sitemap_discovery", candidates)
            except Exception as exc:  # noqa: BLE001 - one sitemap must not kill resolution
                sm_record.update({
                    "fetch": SITEMAP_FETCH_FAILED,
                    "parse": "NOT_ATTEMPTED",
                    "failure_reason": _bounded_failure_reason(exc),
                })
                _append_sitemap_diagnostic(diagnostics, sm_record)
                continue
            sm_record["fetch"] = "OK"
            if _looks_like_index(body):
                raw_child_urls = _extract_loc_urls(body, max(self.max_child_sitemaps * 4, self.max_child_sitemaps))
                child_urls = _prioritize_sitemap_urls(raw_child_urls)[: self.max_child_sitemaps]
                if child_urls != raw_child_urls[: self.max_child_sitemaps]:
                    diagnostics["sitemap_prioritization_applied"] = True
                sm_record.update({
                    "parse": SITEMAP_PARSED_WITH_LOCS if child_urls else SITEMAP_PARSED_ZERO_LOCS,
                    "loc_count": len(child_urls),
                    "target_name_loc_count": sum(1 for u in child_urls if name_in_url_slug(person, u)),
                    "prioritized_child_urls": child_urls[:5],
                })
                _append_sitemap_diagnostic(diagnostics, sm_record)
                for child in child_urls:
                    if _should_stop_sitemap_for_verification(child):
                        diagnostics["sitemap_low_value_skipped_after_candidate"] += 1
                        break
                    if _should_stop_sitemap_for_budget(child):
                        break
                    diagnostics["sitemap_count_attempted"] += 1
                    child_tier = _note_sitemap_attempt(child)
                    if len(diagnostics["sitemap_urls_examined"]) < 10:
                        diagnostics["sitemap_urls_examined"].append(child)
                    child_record: Dict[str, Any] = {"url": child, "gzip_url": _looks_gzip_sitemap_url(child), "relevance_score": _sitemap_relevance_score(child), "semantic_tier": child_tier}
                    try:
                        child_body = _fetch_with_budget(child, "sitemap_discovery")
                    except TimeoutError:
                        return _timeout_result("sitemap_discovery", candidates)
                    except Exception as exc:  # noqa: BLE001
                        child_record.update({
                            "fetch": SITEMAP_FETCH_FAILED,
                            "parse": "NOT_ATTEMPTED",
                            "failure_reason": _bounded_failure_reason(exc),
                        })
                        _append_sitemap_diagnostic(diagnostics, child_record)
                        continue
                    child_record["fetch"] = "OK"
                    if _looks_like_index(child_body):
                        raw_grandchild_urls = _extract_loc_urls(child_body, max(self.max_child_sitemaps * 4, self.max_child_sitemaps))
                        grandchild_urls = _prioritize_sitemap_urls(raw_grandchild_urls)[: self.max_child_sitemaps]
                        if grandchild_urls != raw_grandchild_urls[: self.max_child_sitemaps]:
                            diagnostics["sitemap_prioritization_applied"] = True
                        child_record.update({
                            "parse": SITEMAP_PARSED_WITH_LOCS if grandchild_urls else SITEMAP_PARSED_ZERO_LOCS,
                            "loc_count": len(grandchild_urls),
                            "target_name_loc_count": sum(1 for u in grandchild_urls if name_in_url_slug(person, u)),
                            "prioritized_child_urls": grandchild_urls[:5],
                        })
                        _append_sitemap_diagnostic(diagnostics, child_record)
                        for grandchild in grandchild_urls:
                            if _should_stop_sitemap_for_verification(grandchild):
                                diagnostics["sitemap_low_value_skipped_after_candidate"] += 1
                                break
                            if _should_stop_sitemap_for_budget(grandchild):
                                break
                            diagnostics["sitemap_count_attempted"] += 1
                            grandchild_tier = _note_sitemap_attempt(grandchild)
                            if len(diagnostics["sitemap_urls_examined"]) < 10:
                                diagnostics["sitemap_urls_examined"].append(grandchild)
                            grandchild_record: Dict[str, Any] = {"url": grandchild, "gzip_url": _looks_gzip_sitemap_url(grandchild), "relevance_score": _sitemap_relevance_score(grandchild), "semantic_tier": grandchild_tier}
                            try:
                                grandchild_body = _fetch_with_budget(grandchild, "sitemap_discovery")
                            except TimeoutError:
                                return _timeout_result("sitemap_discovery", candidates)
                            except Exception as exc:  # noqa: BLE001
                                grandchild_record.update({
                                    "fetch": SITEMAP_FETCH_FAILED,
                                    "parse": "NOT_ATTEMPTED",
                                    "failure_reason": _bounded_failure_reason(exc),
                                })
                                _append_sitemap_diagnostic(diagnostics, grandchild_record)
                                continue
                            grandchild_record["fetch"] = "OK"
                            diagnostics["sitemap_count_parsed"] += 1
                            grandchild_record.update(self._add_from_urlset(grandchild, grandchild_body, person, parent, _add_candidate))
                            diagnostics["sitemap_url_entries_skipped_by_relevance_cap"] += int(grandchild_record.get("skipped_by_relevance_cap") or 0)
                            _append_sitemap_diagnostic(diagnostics, grandchild_record)
                    else:
                        diagnostics["sitemap_count_parsed"] += 1
                        child_record.update(self._add_from_urlset(child, child_body, person, parent, _add_candidate))
                        diagnostics["sitemap_url_entries_skipped_by_relevance_cap"] += int(child_record.get("skipped_by_relevance_cap") or 0)
                        _append_sitemap_diagnostic(diagnostics, child_record)
            else:
                diagnostics["sitemap_count_parsed"] += 1
                sm_record.update(self._add_from_urlset(sm, body, person, parent, _add_candidate))
                diagnostics["sitemap_url_entries_skipped_by_relevance_cap"] += int(sm_record.get("skipped_by_relevance_cap") or 0)
                _append_sitemap_diagnostic(diagnostics, sm_record)

        if not diagnostics.get("sitemap_discovery_end_reason"):
            _finish_sitemap_discovery(SITEMAP_END_SITEMAPS_EXHAUSTED)

        # Stage 4: homepage + a bounded set of directory pages.
        try:
            diagnostics["directory_pages_examined"] = self._discover_from_homepage(
                person, parent, candidates, _add_candidate, fetcher=lambda url: _safe_fetch_with_budget(url, "directory_discovery")
            )
        except TimeoutError:
            return _timeout_result("directory_discovery")
        if _timed_out("directory_discovery"):
            return _timeout_result("directory_discovery")

        # Stage 5: verify the best-bounded candidates by fetching their pages.
        verified: List[ResolutionCandidate] = []
        browser_verify_count = 0
        http_candidates = list(candidates)
        diagnostics["http_candidates_discovered"] = len(http_candidates)
        ranked = self._rank_candidates(http_candidates, person)
        diagnostics["verification_reserve_consumed"] = _remaining_seconds() <= _verification_reserve_seconds()
        try:
            browser_verify_count = self._verify_ranked_candidates(
            ranked,
            verified,
            diagnostics,
            parent,
            person,
            browser_verify_count,
            fetcher=lambda url: _safe_fetch_with_budget(url, "candidate_verification"),
            browser_fetcher=lambda url: _browser_fetch_with_budget(url, "candidate_browser_verification"),
        )
        except TimeoutError:
            return _timeout_result("candidate_verification", verified or candidates)
        if _timed_out("candidate_verification"):
            return ResolutionResult(status=RESOLUTION_TIMEOUT, evidence="resolution timeout", candidates=verified or candidates, diagnostics=diagnostics)

        usable = [c for c in verified if self._is_usable_http_candidate(c, parent)]
        diagnostics["http_candidates_usable"] = len(usable)
        diagnostics["http_candidates_unusable"] = max(0, len(http_candidates) - len(usable))

        if self._should_use_browser_fallback(diagnostics):
            before_browser = len(candidates)
            try:
                self._discover_from_browser(person, parent, candidates, seen, diagnostics, _add_candidate, browser_fetcher=lambda url: _browser_fetch_with_budget(url, "browser_fallback"))
            except TimeoutError:
                return _timeout_result("browser_fallback", verified or candidates)
            if _timed_out("browser_fallback"):
                return ResolutionResult(status=RESOLUTION_TIMEOUT, evidence="resolution timeout", candidates=verified or candidates, diagnostics=diagnostics)
            browser_added = candidates[before_browser:]
            if browser_added:
                try:
                    browser_verify_count = self._verify_ranked_candidates(
                    self._rank_candidates(browser_added, person),
                    verified,
                    diagnostics,
                    parent,
                    person,
                    browser_verify_count,
                    fetcher=lambda url: _safe_fetch_with_budget(url, "candidate_verification"),
                    browser_fetcher=lambda url: _browser_fetch_with_budget(url, "candidate_browser_verification"),
                    )
                except TimeoutError:
                    return _timeout_result("candidate_verification", verified or candidates)

        result = self._decision(verified, person)
        diagnostics["final_decision_reason"] = result.evidence
        result.diagnostics = diagnostics
        return result

    def _verify_ranked_candidates(
        self,
        ranked: List[ResolutionCandidate],
        verified: List[ResolutionCandidate],
        diagnostics: Dict[str, Any],
        parent: str,
        person: str,
        browser_verify_count: int,
        *,
        fetcher: Optional[Fetcher] = None,
        browser_fetcher: Optional[Callable[[str], BrowserHtmlResult]] = None,
    ) -> int:
        fetch = fetcher or (lambda url: _fetch_or_none(self._fetcher, url))
        for cand in ranked[: self.max_candidates_verify]:
            body = fetch(cand.url)
            if body is not None:
                cand.http_fetch_ok = True
            if body is None:
                cand.http_fetch_ok = False
                cand.http_failure_reason = "candidate page fetch failed"
            if body is None and cand.method in {"browser_directory", "browser_homepage"} and self._browser_fetcher is not None:
                try:
                    rendered = (browser_fetcher or self._browser_fetch)(cand.url)
                except Exception:  # noqa: BLE001
                    rendered = None
                if rendered is not None and is_within_parent(rendered.final_url, parent):
                    body = rendered.html or ""
            if body is None:
                cand.strong_name = False
                cand.strong_slug = False
                cand.slug_only = False
                cand.title_contains_name = False
                cand.has_schema = False
                cand.has_contact = False
                cand.has_image = False
                cand.has_bio = False
                cand.confidence = ""
                cand.reason = "candidate page fetch failed"
                self._append_candidate_diagnostic(diagnostics, cand)
                verified.append(cand)
                continue
            self._score_candidate_page(cand, body, person)
            cand.http_evidence_summary = cand.reason
            cand.http_confidence = cand.confidence
            if self._should_browser_verify_candidate(cand, person) and browser_verify_count < self.max_browser_candidate_verify:
                browser_verify_count += 1
                diagnostics["browser_candidate_verifications_attempted"] = browser_verify_count
                self._try_browser_verify_candidate(cand, parent, person, browser_fetcher=browser_fetcher)
            self._append_candidate_diagnostic(diagnostics, cand)
            verified.append(cand)
        return browser_verify_count

    def resolve_prospects(
        self, prospects: Sequence[Prospect], *, apply: bool = True
    ) -> List[ResolutionResult]:
        """Resolve many prospects; one failure never aborts the rest.

        When ``apply=True`` auto-resolution fields are written onto each
        ``Prospect`` in place (the caller persists). Results are ordered.
        """
        results: List[ResolutionResult] = []
        for prospect in prospects:
            if prospect is None:
                results.append(ResolutionResult(status=RESOLUTION_ERROR))
                continue
            parent = prospect.website or ""
            person = (prospect.contact_name or prospect.company_name or "").strip()
            if not parent or not is_safe_url(parent_origin(parent)):
                results.append(ResolutionResult(status=RESOLUTION_ERROR,
                                                evidence="parent website missing/unsafe"))
                continue
            try:
                result = self.resolve(person, parent)
            except Exception as exc:  # noqa: BLE001 - never kill the batch
                logger.warning("resolution failed for %s: %s", prospect.prospect_id, exc)
                result = ResolutionResult(status=RESOLUTION_ERROR,
                                          evidence=f"resolution error: {exc}")
            results.append(result)
            if apply:
                self.apply_result(prospect, result)
        return results

    # ------------------------------------------------------------------
    # Persist / apply / manual override
    # ------------------------------------------------------------------

    def apply_result(self, prospect: Prospect, result: ResolutionResult) -> Prospect:
        """Write auto-resolution fields (never manual) onto ``prospect``.

        Preserves ``prospect.website`` and any existing ``manual_profile_url``.
        Concise evidence is stored only in ``metadata`` (never page bodies).
        """
        if prospect is None:
            raise ValueError("prospect required")
        resolution = result.status if result else RESOLUTION_ERROR
        if resolution not in (RESOLUTION_RESOLVED, RESOLUTION_AMBIGUOUS,
                              RESOLUTION_NOT_FOUND, RESOLUTION_TIMEOUT, RESOLUTION_ERROR):
            resolution = RESOLUTION_ERROR
        resolved = resolution == RESOLUTION_RESOLVED and bool(result and result.url)
        prospect.resolution_status = resolution
        prospect.resolution_confidence = (result.confidence if result and resolved else "")
        prospect.resolved_profile_url = (result.url if result and resolved else "")
        meta = dict(prospect.metadata)
        meta["profile_resolution"] = {
            "resolution_method": (result.method if result else "") or "",
            "resolution_evidence": (result.evidence if result else "") or "",
            "resolved_at": _utc_now_iso(),
            "candidate_count": len(result.candidates) if result and result.candidates else 0,
        }
        if result and result.diagnostics:
            meta["profile_resolution"].update(_compact_diagnostics(result.diagnostics))
        prospect.metadata = meta
        prospect.touch()
        return prospect

    def set_manual_profile_url(self, prospect: Prospect, url: str) -> Prospect:
        """Set a persisted manual override (same scheme/host safety guard)."""
        if prospect is None:
            raise ValueError("prospect required")
        value = normalize_url(url)
        if value and not is_safe_url(value):
            raise ValueError("manual profile URL must be a safe http(s) URL")
        prospect.manual_profile_url = value or ""
        prospect.touch()
        return prospect

    def clear_manual_profile_url(self, prospect: Prospect) -> Prospect:
        prospect.manual_profile_url = ""
        prospect.touch()
        return prospect

    # ------------------------------------------------------------------
    # Effective scrape URL (authoritative single source)
    # ------------------------------------------------------------------

    def effective_scrape_url(self, prospect: Prospect) -> str:
        """manual -> resolved(HIGH/MEDIUM) -> parent website (see module fn)."""
        return effective_scrape_url(prospect)

    # ------------------------------------------------------------------
    # Discovery internals (bounded, deterministic)
    # ------------------------------------------------------------------

    def _collect_sitemap_urls(self, parent: str, *, fetcher: Optional[Callable[[str], Optional[str]]] = None) -> List[str]:
        """robots-declared sitemaps + conventional endpoints (bounded)."""
        urls: List[str] = []
        seen = set()
        self._last_robots_fetched = False
        self._last_generated_sitemap_fallbacks = set()

        def _consider(raw: str) -> None:
            url = urljoin(parent, raw) if not _URL_SCHEME_RE.match(raw) else raw
            if not url or not is_safe_url(url) or not same_registered_domain(url, parent):
                return
            if url not in seen:
                seen.add(url)
                urls.append(url)

        fetch = fetcher or (lambda url: _fetch_or_none(self._fetcher, url))
        robots = fetch(urljoin(parent, "/robots.txt"))
        if robots is not None:
            self._last_robots_fetched = True
            for sm in parse_robots_sitemaps(robots):
                _consider(sm)
        _consider("/sitemap.xml")
        _consider("/sitemap_index.xml")
        for existing in list(urls):
            for fallback in _profile_sitemap_fallbacks(existing):
                self._last_generated_sitemap_fallbacks.add(fallback)
                _consider(fallback)
        return urls

    def _add_from_urlset(
        self,
        sitemap_url: str,
        body: str,
        person: str,
        parent: str,
        add: Callable[[ResolutionCandidate], None],
    ) -> Dict[str, Any]:
        page_urls = _urls_from_sitemap(body, self.max_sitemap_urls)
        target_name_loc_count = sum(1 for url in page_urls if name_in_url_slug(person, url))
        original_loc_count = len(page_urls)
        low_value_sitemap = _is_low_value_sitemap(sitemap_url)
        high_value_sitemap = _is_high_value_sitemap(sitemap_url) or _looks_agent_profile_sitemap(sitemap_url)
        semantic_tier = _sitemap_semantic_tier(sitemap_url)
        ranked_urls = sorted(
            enumerate(page_urls),
            key=lambda item: (-_url_person_relevance_score(item[1], person), item[0], item[1]),
        )
        skipped_by_relevance_cap = 0
        if low_value_sitemap and not target_name_loc_count:
            skipped_by_relevance_cap = max(0, len(ranked_urls) - MAX_LOW_VALUE_SITEMAP_URLS_SCANNED)
            ranked_urls = ranked_urls[:MAX_LOW_VALUE_SITEMAP_URLS_SCANNED]
        page_urls = [url for _, url in ranked_urls]
        admitted = 0
        for url in page_urls:
            if not url or not is_within_parent(url, parent):
                continue
            if _is_static_profile_candidate(url):
                continue
            if _looks_directory_path(url) and not name_in_url_slug(person, url):
                continue
            if high_value_sitemap and _looks_agent_profile_sitemap(sitemap_url) and not name_in_url_slug(person, url):
                continue
            if not _looks_profile_path(url) and not name_in_url_slug(person, url):
                continue
            add(
                ResolutionCandidate(
                    url=url,
                    method="sitemap",
                    slug_only=name_in_url_slug(person, url),
                    same_domain=is_within_parent(url, parent),
                )
            )
            admitted += 1
        parse = SITEMAP_PARSED_ZERO_LOCS
        if page_urls:
            parse = SITEMAP_TARGET_MATCH_FOUND if target_name_loc_count else SITEMAP_PARSED_WITH_LOCS
        return {
            "parse": parse,
            "loc_count": original_loc_count,
            "urls_scanned_count": len(page_urls),
            "target_name_loc_count": target_name_loc_count,
            "candidate_admitted_count": admitted,
            "low_value_sitemap": low_value_sitemap,
            "high_value_sitemap": high_value_sitemap,
            "semantic_tier": semantic_tier,
            "relevance_score": _sitemap_relevance_score(sitemap_url),
            "skipped_by_relevance_cap": skipped_by_relevance_cap,
        }

    def _discover_from_homepage(
        self,
        person: str,
        parent: str,
        candidates: List[ResolutionCandidate],
        add: Callable[[ResolutionCandidate], None],
        *,
        fetcher: Optional[Callable[[str], Optional[str]]] = None,
    ) -> int:
        fetch = fetcher or (lambda url: _fetch_or_none(self._fetcher, url))
        home_body = fetch(parent)
        if home_body is None:
            return 0
        directory_pages: List[str] = []
        seen_dir: set = set()
        try:
            soup = BeautifulSoup(home_body, "lxml")
        except Exception:  # noqa: BLE001
            return 0
        for anchor in soup.find_all("a", href=True)[: self.max_homepage_links]:
            url = normalize_url(urljoin(parent, (anchor.get("href") or "").strip()))
            if not url or not is_within_parent(url, parent):
                continue
            text = " ".join((anchor.get_text(" ", strip=True) or "").lower().split())[:120]
            if name_in_url_slug(person, url) or full_name_in_text(person, text):
                add(ResolutionCandidate(url=url, method="homepage",
                                        slug_only=name_in_url_slug(person, url),
                                        same_domain=True))
            if _looks_directory_path(url) and url not in seen_dir:
                seen_dir.add(url)
                directory_pages.append(url)
        for url in directory_pages[: self.max_directory_pages]:
            body = fetch(url)
            if body is None:
                continue
            for profile_url in self._links_from_directory_page(body, parent, person):
                add(ResolutionCandidate(url=profile_url, method="directory",
                                        slug_only=name_in_url_slug(person, profile_url),
                                        linked_from_directory=True,
                                        same_domain=is_within_parent(profile_url, parent)))
        return len(directory_pages[: self.max_directory_pages])

    def _links_from_directory_page(
        self, dir_body: str, parent: str, person: str
    ) -> List[str]:
        out: List[str] = []
        seen: set = set()
        try:
            soup = BeautifulSoup(dir_body, "lxml")
        except Exception:  # noqa: BLE001
            return out
        for anchor in soup.find_all("a", href=True)[: self.max_links_scanned]:
            url = normalize_url(urljoin(parent, (anchor.get("href") or "").strip()))
            if not url or not is_within_parent(url, parent) or _looks_directory_path(url):
                continue
            if _is_static_profile_candidate(url):
                continue
            if url in seen:
                continue
            seen.add(url)
            text = " ".join((anchor.get_text(" ", strip=True) or "").lower().split())[:120]
            if name_in_url_slug(person, url) or full_name_in_text(person, text):
                out.append(url)
        return out

    @staticmethod
    def _is_usable_http_candidate(cand: ResolutionCandidate, parent: str) -> bool:
        """True when an HTTP-verified candidate has meaningful identity evidence."""
        if cand is None:
            return False
        if not cand.url or not is_within_parent(cand.url, parent):
            return False
        if _is_static_profile_candidate(cand.url) or _is_generic_profile_root(cand.url):
            return False
        if not cand.http_fetch_ok:
            return False
        if cand.confidence in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM):
            return True
        return cand.is_strong() or cand.plausibility_score() > 0

    def _should_use_browser_fallback(self, diagnostics: Dict[str, Any]) -> bool:
        if self._browser_fetcher is None:
            diagnostics["browser_fallback_trigger_reason"] = "NOT_NEEDED"
            return False
        usable_count = int(diagnostics.get("http_candidates_usable") or 0)
        raw_count = int(diagnostics.get("http_candidates_discovered") or 0)
        if usable_count > 0:
            diagnostics["browser_fallback_trigger_reason"] = "NOT_NEEDED"
            return False
        if raw_count > 0:
            diagnostics["browser_fallback_trigger_reason"] = "ONLY_UNUSABLE_HTTP_CANDIDATES"
            return True
        if int(diagnostics.get("sitemap_count_attempted") or 0) <= 0:
            diagnostics["browser_fallback_trigger_reason"] = "NO_HTTP_CANDIDATES"
            return True
        for record in diagnostics.get("sitemap_diagnostics") or []:
            if not isinstance(record, dict):
                continue
            if str(record.get("fetch") or "") != SITEMAP_FETCH_FAILED:
                continue
            reason = str(record.get("failure_reason") or "")
            if "403" in reason or "429" in reason:
                diagnostics["browser_fallback_trigger_reason"] = "HTTP_DISCOVERY_BLOCKED"
                return True
        diagnostics["browser_fallback_trigger_reason"] = "NO_HTTP_CANDIDATES"
        return True

    def _browser_fetch(self, url: str) -> BrowserHtmlResult:
        fetcher = self._browser_fetcher or fetch_rendered_html
        return fetcher(url)

    def _discover_from_browser(
        self,
        person: str,
        parent: str,
        candidates: List[ResolutionCandidate],
        seen: Dict[str, ResolutionCandidate],
        diagnostics: Dict[str, Any],
        add: Callable[[ResolutionCandidate], None],
        *,
        browser_fetcher: Optional[Callable[[str], BrowserHtmlResult]] = None,
    ) -> None:
        diagnostics["browser_fallback_attempted"] = True
        initial_candidate_count = len(candidates)
        try:
            fetch = browser_fetcher or self._browser_fetch
            rendered_home = fetch(parent)
        except Exception as exc:  # noqa: BLE001
            diagnostics["browser_homepage_status"] = "FETCH_FAILED"
            diagnostics["browser_failure_reason"] = _bounded_failure_reason(exc)
            return
        if not is_within_parent(rendered_home.final_url, parent):
            diagnostics["browser_homepage_status"] = "REDIRECT_REJECTED"
            diagnostics["browser_failure_reason"] = f"redirect outside parent domain: {rendered_home.final_url}"[:160]
            return
        diagnostics["browser_homepage_status"] = "OK"
        directory_pages = self._browser_directory_pages(rendered_home.html, rendered_home.final_url, parent, person, diagnostics, add)
        for directory_url in directory_pages[: self.max_directory_pages]:
            try:
                rendered = fetch(directory_url)
            except Exception as exc:  # noqa: BLE001
                diagnostics["browser_failure_reason"] = _bounded_failure_reason(exc)
                continue
            if not is_within_parent(rendered.final_url, parent):
                continue
            diagnostics["browser_directory_pages_examined"] += 1
            for profile_url in self._browser_profile_links(rendered.html, rendered.final_url, parent, person, diagnostics):
                add(
                    ResolutionCandidate(
                        url=profile_url,
                        method="browser_directory",
                        slug_only=name_in_url_slug(person, profile_url),
                        linked_from_directory=True,
                        same_domain=is_within_parent(profile_url, parent),
                    )
                )
        diagnostics["browser_candidates_discovered"] = max(0, len(candidates) - initial_candidate_count)

    def _browser_directory_pages(
        self,
        body: str,
        base_url: str,
        parent: str,
        person: str,
        diagnostics: Dict[str, Any],
        add: Callable[[ResolutionCandidate], None],
    ) -> List[str]:
        directory_pages: List[str] = []
        seen_dir: set[str] = set()
        try:
            soup = BeautifulSoup(body, "lxml")
        except Exception:  # noqa: BLE001
            return directory_pages
        for anchor in soup.find_all("a", href=True)[: self.max_browser_links_scanned]:
            diagnostics["browser_links_examined"] += 1
            url = normalize_url(urljoin(base_url, (anchor.get("href") or "").strip()))
            if not url or not is_within_parent(url, parent):
                continue
            text = " ".join((anchor.get_text(" ", strip=True) or "").lower().split())[:120]
            if name_in_url_slug(person, url) or full_name_in_text(person, text):
                add(ResolutionCandidate(url=url, method="browser_homepage", slug_only=name_in_url_slug(person, url), same_domain=True))
            if _looks_directory_path(url) and url not in seen_dir:
                seen_dir.add(url)
                directory_pages.append(url)
        return directory_pages

    def _browser_profile_links(
        self,
        body: str,
        base_url: str,
        parent: str,
        person: str,
        diagnostics: Dict[str, Any],
    ) -> List[str]:
        out: List[str] = []
        seen_urls: set[str] = set()
        try:
            soup = BeautifulSoup(body, "lxml")
        except Exception:  # noqa: BLE001
            return out
        for anchor in soup.find_all("a", href=True)[: self.max_browser_links_scanned]:
            diagnostics["browser_links_examined"] += 1
            url = normalize_url(urljoin(base_url, (anchor.get("href") or "").strip()))
            if not url or not is_within_parent(url, parent) or _looks_directory_path(url):
                continue
            if _is_static_profile_candidate(url) or url in seen_urls:
                continue
            seen_urls.add(url)
            text = " ".join((anchor.get_text(" ", strip=True) or "").lower().split())[:120]
            if name_in_url_slug(person, url) or full_name_in_text(person, text):
                out.append(url)
        return out

    def _should_browser_verify_candidate(self, cand: ResolutionCandidate, person: str) -> bool:
        if self._browser_fetcher is None:
            return False
        if not cand.same_domain or not cand.url or _is_static_profile_candidate(cand.url):
            return False
        if _looks_directory_path(cand.url):
            return False
        if cand.confidence in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM) and cand.is_strong():
            return False
        if _is_generic_profile_root(cand.url):
            return False
        return bool(name_in_url_slug(person, cand.url))

    def _try_browser_verify_candidate(
        self,
        cand: ResolutionCandidate,
        parent: str,
        person: str,
        *,
        browser_fetcher: Optional[Callable[[str], BrowserHtmlResult]] = None,
    ) -> None:
        cand.browser_verification_attempted = True
        try:
            rendered = (browser_fetcher or self._browser_fetch)(cand.url)
        except Exception as exc:  # noqa: BLE001
            cand.browser_failure_reason = _bounded_failure_reason(exc)
            return
        cand.browser_final_url = rendered.final_url or ""
        if not is_within_parent(cand.browser_final_url, parent):
            cand.browser_failure_reason = f"redirect outside parent domain: {cand.browser_final_url}"[:160]
            return
        browser_probe = ResolutionCandidate(
            url=cand.browser_final_url or cand.url,
            method=cand.method,
            slug_only=cand.slug_only,
            linked_from_directory=cand.linked_from_directory,
            same_domain=True,
        )
        self._score_candidate_page(browser_probe, rendered.html or "", person)
        cand.browser_evidence_summary = browser_probe.reason
        cand.browser_confidence = browser_probe.confidence
        try:
            soup = BeautifulSoup(rendered.html or "", "lxml")
            cand.browser_title = ((soup.title.get_text(" ", strip=True) if soup.title else "") or "")[:160]
        except Exception:  # noqa: BLE001
            cand.browser_title = ""
        if browser_probe.is_strong() and browser_probe.confidence in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM):
            cand.strong_name = browser_probe.strong_name
            cand.strong_slug = browser_probe.strong_slug
            cand.slug_only = browser_probe.slug_only
            cand.title_contains_name = browser_probe.title_contains_name
            cand.has_schema = browser_probe.has_schema
            cand.has_contact = browser_probe.has_contact
            cand.has_image = browser_probe.has_image
            cand.has_bio = browser_probe.has_bio
            cand.reason = browser_probe.reason
            cand.confidence = browser_probe.confidence

    def _append_candidate_diagnostic(self, diagnostics: Dict[str, Any], cand: ResolutionCandidate) -> None:
        rows = diagnostics.setdefault("candidate_diagnostics", [])
        if not isinstance(rows, list) or len(rows) >= self.max_candidates_verify:
            return
        rows.append(
            {
                "url": str(cand.url or "")[:240],
                "method": str(cand.method or "")[:40],
                "http_fetch_ok": bool(cand.http_fetch_ok),
                "http_failure_reason": str(cand.http_failure_reason or "")[:160],
                "http_evidence_summary": str(cand.http_evidence_summary or "")[:160],
                "http_confidence": str(cand.http_confidence or "")[:20],
                "browser_verification_attempted": bool(cand.browser_verification_attempted),
                "browser_final_url": str(cand.browser_final_url or "")[:240],
                "browser_title": str(cand.browser_title or "")[:160],
                "browser_evidence_summary": str(cand.browser_evidence_summary or "")[:160],
                "browser_confidence": str(cand.browser_confidence or "")[:20],
                "browser_failure_reason": str(cand.browser_failure_reason or "")[:160],
                "canonical_url": str(cand.canonical_url or "")[:240],
                "final_url": str(cand.final_url or "")[:240],
                "score": cand.plausibility_score(),
            }
        )

    @staticmethod
    def _rank_candidates(
        candidates: List[ResolutionCandidate], person: str
    ) -> List[ResolutionCandidate]:
        def _key(c: ResolutionCandidate) -> tuple[int, int, str]:
            score = c.plausibility_score()
            exact_name_slug = name_in_url_slug(person, c.url)
            profile_path = _looks_profile_path(c.url)
            article_path = _looks_article_path(c.url)
            directory_path = _looks_directory_path(c.url)
            if exact_name_slug and profile_path:
                score += 60
            elif exact_name_slug:
                score += 45
            elif profile_path:
                score += 25
            if c.linked_from_directory:
                score += 10
            if directory_path:
                score -= 8
            if article_path:
                score -= 20
            return (-score, len(c.url or ""), c.url or "")

        return sorted(candidates, key=_key)

    def _score_candidate_page(
        self, cand: ResolutionCandidate, body: str, person: str
    ) -> ResolutionCandidate:
        title = ""
        soup_text = ""
        primary_heading = ""
        jsonld_names: List[str] = []
        has_schema = False
        has_contact = False
        has_image = False
        has_bio = False
        try:
            soup = BeautifulSoup(body, "lxml")
            title = (soup.title.get_text(" ", strip=True) if soup.title else "") or ""
            heading = soup.find(["h1", "h2"])
            primary_heading = (heading.get_text(" ", strip=True) if heading else "") or ""
            soup_text = soup.get_text(" ", strip=True) or ""
            canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
            if canonical is not None:
                href = (canonical.get("href") or "").strip()
                if href:
                    cand.canonical_url = normalize_url(urljoin(cand.url, href))
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                except Exception:  # noqa: BLE001
                    continue
                _collect_jsonld_names(data, jsonld_names)
                if isinstance(data, (dict, list)) and data:
                    has_schema = True
            if any(t in soup_text.lower() for t in ("tel:", "@", "phone", "email")):
                has_contact = True
            if soup.find("img"):
                has_image = True
            low = soup_text.lower()
            if any(k in low for k in ("bio", "biograph", "experience", "specialties", "about me")):
                has_bio = True
        except Exception:  # noqa: BLE001
            return cand

        article_like = _looks_article_path(cand.url)
        structured_mismatch = bool(jsonld_names) and not any(persons_match(person, n) for n in jsonld_names)
        combined = f"{title}\n{primary_heading}\n{soup_text}"
        cand.title_contains_name = full_name_in_text(person, title)
        heading_contains_name = full_name_in_text(person, primary_heading)
        strong_text = cand.title_contains_name or heading_contains_name
        structured_match = any(persons_match(person, n) for n in jsonld_names)
        slug = name_in_url_slug(person, cand.url)
        corroboration = (
            has_schema or has_bio or cand.linked_from_directory
            or (has_image and has_contact) or cand.title_contains_name
        )
        cand.has_schema = has_schema or bool(jsonld_names)
        cand.structured_names = [str(name) for name in jsonld_names if str(name or "").strip()]
        cand.has_contact = has_contact
        cand.has_image = has_image
        cand.has_bio = has_bio
        cand.strong_name = (structured_match or strong_text) and not article_like and not structured_mismatch
        generic_root = _is_generic_profile_root(cand.url)
        cand.strong_slug = bool(slug) and not generic_root and not article_like and not structured_mismatch and corroboration and not cand.strong_name
        cand.slug_only = bool(slug) and not generic_root and not article_like and not structured_mismatch and not cand.strong_slug and not cand.strong_name
        if article_like and not structured_match and not (heading_contains_name and cand.has_bio):
            cand.title_contains_name = False
        if structured_mismatch:
            cand.has_schema = False
        cand.confidence = _confidence_for(cand)
        cand.reason = _build_reason(cand)
        if structured_mismatch:
            cand.reason = "structured data names another person"
            cand.confidence = ""
        return cand

    def _decision(
        self, verified: List[ResolutionCandidate], person: str
    ) -> ResolutionResult:
        strong = _collapse_equivalent_candidates([c for c in verified if c.is_strong()], person)
        if len(strong) == 1:
            cand = strong[0]
            if cand.confidence in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM):
                return ResolutionResult(
                    status=RESOLUTION_RESOLVED, url=cand.url,
                    confidence=cand.confidence, method=cand.method,
                    evidence=cand.reason or "unique strong name match",
                    candidates=verified,
                )
        if len(strong) > 1:
            return ResolutionResult(
                status=RESOLUTION_AMBIGUOUS,
                evidence=f"multiple plausible candidates ({len(strong)})\u2014 manual review",
                candidates=verified,
            )
        plausible = [c for c in verified if c.plausibility_score() > 0 and _has_intended_person_evidence(c, person)]
        if len(plausible) > 1:
            return ResolutionResult(status=RESOLUTION_AMBIGUOUS,
                                    evidence="multiple weak candidates\u2014manual review",
                                    candidates=verified)
        if plausible:
            return ResolutionResult(status=RESOLUTION_NOT_FOUND,
                                    evidence="only weak evidence\u2014no safe selection",
                                    candidates=verified)
        return ResolutionResult(status=RESOLUTION_NOT_FOUND,
                                evidence="no matching individual profile found",
                                candidates=verified)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _collect_jsonld_names(data: Any, out: List[str]) -> None:
    if isinstance(data, list):
        for item in data:
            _collect_jsonld_names(item, out)
    elif isinstance(data, dict):
        if isinstance(data.get("name"), str):
            out.append(data["name"])
        for value in data.values():
            if isinstance(value, (dict, list)):
                _collect_jsonld_names(value, out)


def _normalized_profile_equivalence_url(url: str) -> str:
    """Return a conservative URL identity key for duplicate profile variants."""
    try:
        parsed = urlparse(normalize_url(url))
    except Exception:  # noqa: BLE001
        return ""
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", parsed.path or "/") or "/"
    # Drop query/fragment only; do not collapse distinct path variants here.
    return f"{parsed.scheme.lower()}://{host}{path.lower()}"


def _has_intended_person_evidence(cand: ResolutionCandidate, person: str) -> bool:
    """True only for evidence that actually identifies the intended person."""
    if cand is None:
        return False
    if cand.strong_name or cand.strong_slug or cand.title_contains_name:
        return True
    if cand.slug_only and name_in_url_slug(person, cand.url):
        return True
    if any(persons_match(person, name) for name in cand.structured_names or []):
        return True
    return False


def _candidate_equivalence_key(cand: ResolutionCandidate, person: str) -> str:
    """Key demonstrably equivalent representations of the same intended profile."""
    urls = [cand.canonical_url, cand.final_url, cand.browser_final_url, cand.url]
    normalized_urls = [_normalized_profile_equivalence_url(url) for url in urls if url]
    normalized_urls = [url for url in normalized_urls if url]
    canonical = normalized_urls[0] if normalized_urls else ""
    structured = [normalize_person_name(name) for name in cand.structured_names or [] if persons_match(person, name)]
    if structured and canonical:
        return f"person:{structured[0]}|url:{canonical}"
    if canonical:
        return f"url:{canonical}"
    return f"raw:{cand.url}"


def _prefer_candidate(existing: ResolutionCandidate, challenger: ResolutionCandidate) -> ResolutionCandidate:
    """Keep the strongest representative for an equivalent profile cluster."""
    existing_score = existing.plausibility_score()
    challenger_score = challenger.plausibility_score()
    if challenger_score > existing_score:
        return challenger
    if challenger_score < existing_score:
        return existing
    # Prefer a canonical-looking URL when scores tie.
    if challenger.canonical_url and not existing.canonical_url:
        return challenger
    if len(challenger.url or "") < len(existing.url or ""):
        return challenger
    return existing


def _collapse_equivalent_candidates(
    candidates: List[ResolutionCandidate], person: str
) -> List[ResolutionCandidate]:
    """Collapse only demonstrably equivalent strong candidates.

    This does not merge distinct same-name professionals; it only collapses
    URL/canonical/redirect variants that identify the same intended person.
    """
    clusters: Dict[str, ResolutionCandidate] = {}
    for cand in candidates:
        if not _has_intended_person_evidence(cand, person):
            continue
        key = _candidate_equivalence_key(cand, person)
        existing = clusters.get(key)
        clusters[key] = cand if existing is None else _prefer_candidate(existing, cand)
    return list(clusters.values())


def _looks_directory_path(url: str) -> bool:
    try:
        path = (urlparse(url).path or "").strip("/").lower()
    except ValueError:
        return False
    tokens = set(t.strip().strip("._-") for t in re.split(r"[/\-_\s]+", path) if t.strip())
    return bool(tokens & set(DIRECTORY_PATH_TOKENS))


def _looks_article_path(url: str) -> bool:
    try:
        path = (urlparse(url).path or "").strip("/").lower()
    except ValueError:
        return False
    tokens = set(t.strip().strip("._-") for t in re.split(r"[/\-_\s]+", path) if t.strip())
    return bool(tokens & {"blog", "blogs", "news", "article", "articles", "press", "stories", "story"})


def _is_generic_profile_root(url: str) -> bool:
    try:
        parts = [p for p in (urlparse(url).path or "").strip("/").lower().split("/") if p]
    except ValueError:
        return False
    return len(parts) == 1 and parts[0].strip("._-") in GENERIC_PROFILE_ROOTS


def _is_static_profile_candidate(url: str) -> bool:
    try:
        path = (urlparse(url).path or "").lower()
    except ValueError:
        return True
    leaf = path.rsplit("/", 1)[-1]
    return any(leaf.endswith(ext) for ext in STATIC_PROFILE_EXTENSIONS)


def _looks_agent_profile_sitemap(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    leaf = path.rsplit("/", 1)[-1]
    return "sitemap-agent-profiles" in leaf or (
        "agent" in leaf and "profile" in leaf and "sitemap" in leaf
    )


def _compact_diagnostics(diag: Dict[str, Any]) -> Dict[str, Any]:
    compact = {
        "robots_fetched": bool(diag.get("robots_fetched")),
        "sitemap_count_attempted": int(diag.get("sitemap_count_attempted") or 0),
        "sitemap_count_parsed": int(diag.get("sitemap_count_parsed") or 0),
        "sitemap_urls_examined": list(diag.get("sitemap_urls_examined") or [])[:10],
        "candidate_count_before_filtering": int(diag.get("candidate_count_before_filtering") or 0),
        "candidate_count_after_filtering": int(diag.get("candidate_count_after_filtering") or 0),
        "http_candidates_discovered": int(diag.get("http_candidates_discovered") or 0),
        "http_candidates_usable": int(diag.get("http_candidates_usable") or 0),
        "http_candidates_unusable": int(diag.get("http_candidates_unusable") or 0),
        "browser_fallback_trigger_reason": str(diag.get("browser_fallback_trigger_reason") or "")[:80],
        "directory_pages_examined": int(diag.get("directory_pages_examined") or 0),
        "browser_fallback_attempted": bool(diag.get("browser_fallback_attempted")),
        "browser_homepage_status": str(diag.get("browser_homepage_status") or "")[:40],
        "browser_directory_pages_examined": int(diag.get("browser_directory_pages_examined") or 0),
        "browser_links_examined": int(diag.get("browser_links_examined") or 0),
        "browser_candidates_discovered": int(diag.get("browser_candidates_discovered") or 0),
        "browser_failure_reason": str(diag.get("browser_failure_reason") or "")[:160],
        "browser_candidate_verifications_attempted": int(diag.get("browser_candidate_verifications_attempted") or 0),
        "sitemap_prioritization_applied": bool(diag.get("sitemap_prioritization_applied")),
        "sitemap_low_value_skipped_after_candidate": int(diag.get("sitemap_low_value_skipped_after_candidate") or 0),
        "sitemap_url_entries_skipped_by_relevance_cap": int(diag.get("sitemap_url_entries_skipped_by_relevance_cap") or 0),
        "sitemap_high_value_count_attempted": int(diag.get("sitemap_high_value_count_attempted") or 0),
        "sitemap_general_count_attempted": int(diag.get("sitemap_general_count_attempted") or 0),
        "sitemap_low_value_count_attempted": int(diag.get("sitemap_low_value_count_attempted") or 0),
        "sitemap_low_value_budget_reached": bool(diag.get("sitemap_low_value_budget_reached")),
        "sitemap_discovery_budget_reached": bool(diag.get("sitemap_discovery_budget_reached")),
        "post_sitemap_budget_preserved": bool(diag.get("post_sitemap_budget_preserved")),
        "sitemap_remaining_budget_seconds": float(diag.get("sitemap_remaining_budget_seconds") or 0.0),
        "sitemap_discovery_end_reason": str(diag.get("sitemap_discovery_end_reason") or "")[:80],
        "verification_reserve_seconds": float(diag.get("verification_reserve_seconds") or 0.0),
        "verification_reserve_reached": bool(diag.get("verification_reserve_reached")),
        "verification_reserve_consumed": bool(diag.get("verification_reserve_consumed")),
        "timeout_stage": str(diag.get("timeout_stage") or "")[:80],
        "timeout_reason": str(diag.get("timeout_reason") or "")[:160],
        "elapsed_seconds": float(diag.get("elapsed_seconds") or 0.0),
        "final_decision_reason": str(diag.get("final_decision_reason") or "")[:240],
    }
    sitemap_diag = diag.get("sitemap_diagnostics") or []
    if isinstance(sitemap_diag, list):
        compact["sitemap_diagnostics"] = [
            record for record in sitemap_diag[:MAX_SITEMAP_DIAGNOSTICS]
            if isinstance(record, dict)
        ]
    candidate_diag = diag.get("candidate_diagnostics") or []
    if isinstance(candidate_diag, list):
        compact["candidate_diagnostics"] = [
            record for record in candidate_diag[:MAX_CANDIDATES_VERIFY]
            if isinstance(record, dict)
        ]
    return compact


def _looks_profile_path(url: str) -> bool:
    try:
        path = (urlparse(url).path or "").strip("/").lower()
    except ValueError:
        return False
    tokens = set(t.strip().strip("._-") for t in re.split(r"[/\-_]+", path) if t.strip())
    return bool(tokens & set(PROFILE_PATH_TOKENS))


def _confidence_for(cand: ResolutionCandidate) -> str:
    if cand.strong_name:
        return CONFIDENCE_HIGH
    if cand.strong_slug:
        if cand.has_schema or cand.has_bio or cand.title_contains_name:
            return CONFIDENCE_HIGH
        return CONFIDENCE_MEDIUM
    if cand.slug_only or cand.title_contains_name:
        return CONFIDENCE_LOW
    return CONFIDENCE_LOW


def _build_reason(cand: ResolutionCandidate) -> str:
    parts: List[str] = []
    if cand.strong_name:
        parts.append("full name in page title/heading/content")
    elif cand.title_contains_name:
        parts.append("name in title")
    if cand.strong_slug:
        parts.append("name slug in URL + corroboration")
    elif cand.slug_only:
        parts.append("name slug in URL (weak corroboration)")
    if cand.linked_from_directory:
        parts.append("linked from agent/team directory")
    if cand.has_schema:
        parts.append("person/structured data")
    if cand.has_contact:
        parts.append("contact info")
    if cand.has_bio:
        parts.append("biography-like content")
    if cand.has_image:
        parts.append("profile image")
    return ", ".join(parts) or "no strong evidence"


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def effective_scrape_url(prospect: Prospect) -> str:
    """Authoritative scrape-target selection: manual -> resolved -> parent.

    - a valid ``manual_profile_url`` always wins;
    - otherwise a ``RESOLVED`` profile with HIGH/MEDIUM confidence wins;
    - otherwise the parent ``prospect.website`` (unchanged identity).

    This is the single source of truth for URL selection so the logic is never
    duplicated across generation/batch/workers. No network is performed here.
    """
    if prospect is None:
        return ""
    manual = (prospect.manual_profile_url or "").strip()
    if manual and is_safe_url(manual):
        return manual
    if (
        (prospect.resolution_status or "") == RESOLUTION_RESOLVED
        and (prospect.resolved_profile_url or "").strip()
        and is_safe_url(prospect.resolved_profile_url)
        and (prospect.resolution_confidence or "") in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM)
    ):
        return prospect.resolved_profile_url.strip()
    return (prospect.website or "").strip()