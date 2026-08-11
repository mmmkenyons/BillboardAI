"""Sprint 5B research pipeline orchestration service (Qt-free).

Runs the EXISTING real research pipeline for a single prospect without any
widget/DOM code and returns a structured :class:`ResearchResult`:

    1. validate / normalize the prospect website
    2. run ``WebsiteScraper``
    3. build a ``BrandProfile`` (BrandProfileBuilder)
    4. generate ``MessageStrategy`` (MessageStrategyEngine)
    5. generate ``AdConcept`` (AdConceptEngine)
    6. create / reuse a durable ``Project`` and populate it
    7. return success / error details

The service is a thin *orchestrator*: it never re-implements extraction. All
scraper/engine dependencies can be injected (or monkeypatched) so unit tests run
without a browser or live websites.

**Idempotency** — a Prospect must never get duplicate Projects:
- a persisted job's ``project_id`` wins if it still exists;
- otherwise the existing Project already associated with this prospect (its
  ``metadata["prospect_id"]`` matches) is reused;
- otherwise (and only then) a new Project is created.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from engine.ad_concept import AdConcept, AdConceptEngine
from engine.brand_profile import BrandProfile, BrandProfileBuilder
from engine.message_strategy import MessageStrategy, MessageStrategyEngine
from gui.models.project import Project
from gui.models.project_store import ProjectStore
from gui.models.prospect import Prospect

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error classification (small, explainable)
# ---------------------------------------------------------------------------

# Error type tokens used for both the job's last_error_type and retry decisions.
ERR_NO_WEBSITE = "no_website"
ERR_INVALID_URL = "invalid_url"
ERR_SCRAPE_TRANSIENT = "scrape_transient"
ERR_SCRAPE_PERMANENT = "scrape_permanent"
ERR_BRAND_PROFILE = "brand_profile"
ERR_STRATEGIES = "strategies"
ERR_CONCEPTS = "concepts"
ERR_PROJECT = "project"
ERR_UNKNOWN = "unknown"

# Transient error classes (value in exception class name, so it is robust to
# import differences across environments) -> RETRY_PENDING when attempts remain.
_TRANSIENT_MARKERS = (
    "Timeout",
    "TimeoutError",
    "ConnectionError",
    "ConnectionResetError",
    "RemoteDisconnected",
    "PlaywrightConnectionError",
    "NetworkError",
    "net::ERR_",
    "ERR_NAME_NOT_RESOLVED",
    "ERR_CONNECTION",
    "ECONNRESET",
    "socket.timeout",
)


def _transient_by_name(exc: Exception) -> bool:
    name = type(exc).__name__
    text = f"{type(exc).__module__}.{name} {str(exc)[:200]}"
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _TRANSIENT_MARKERS)


def _classify_error(exc: Exception, website: str) -> Dict[str, Any]:
    """Return ``{"type": ..., "retryable": bool}`` for a pipeline exception."""

    def _url_missing(m: str) -> bool:
        lowered = (m or "").lower()
        return any(k in lowered for k in ("no website", "missing url", "no url"))

    msg = str(exc)
    # No-URL / permanent validation failures never retry.
    if not website or _url_missing(msg):
        return {"type": ERR_NO_WEBSITE, "retryable": False}
    if isinstance(exc, ValueError) or _url_missing(msg) or "invalid" in msg.lower():
        return {"type": ERR_INVALID_URL, "retryable": False}
    if _transient_by_name(exc):
        return {"type": ERR_SCRAPE_TRANSIENT, "retryable": True}
    return {"type": ERR_SCRAPE_PERMANENT, "retryable": False}


def _normalize_website_url(raw: str) -> str:
    """Best-effort URL for the scraper (empty -> invalid)."""
    value = str(raw or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value


def _validate_url(value: str) -> None:
    """Raise ValueError for clearly unusable URLs (permanent validation error)."""
    if not value:
        raise ValueError("No website for prospect")
    parsable = value.split("#", 1)[0].split("?", 1)[0]
    host = parsable.split("://", 1)[-1] if "://" in parsable else parsable
    if not host or "." not in host or " " in host:
        raise ValueError(f"Invalid website URL: {value!r}")


@dataclass
class ResearchResult:
    """Structured outcome of one research run (success or error)."""

    success: bool
    prospect_id: str = ""
    job_id: str = ""
    project_id: str = ""
    brand_profile: Optional[BrandProfile] = None
    strategies: List[MessageStrategy] = field(default_factory=list)
    concepts: List[AdConcept] = field(default_factory=list)
    error: str = ""
    error_type: str = ""
    retryable: bool = False
    scraped: bool = False
    stages: List[str] = field(default_factory=list)

class ResearchPipelineService:
    """Orchestrates the real research pipeline for a single prospect.

    All expensive engine dependencies are injectable so tests never launch a
    browser or depend on a live website. Defaults use the real engine classes.

    Args:
        project_store: Durable ``ProjectStore`` (default ``ProjectStore()``).
        scraper_factory: Callable(url) -> object with a ``run(progress_callback)``
            method returning the scraper data dict. Default wraps ``WebsiteScraper``.
        brand_builder: Callable(data) -> BrandProfile (default ``BrandProfileBuilder``).
        message_engine: Callable(profile) -> list (default ``MessageStrategyEngine``).
        concept_engine: Callable(profile, strategies) -> list (default ``AdConceptEngine``).
    """

    def __init__(
        self,
        project_store: Optional[ProjectStore] = None,
        scraper_factory: Optional[Callable[[str], Any]] = None,
        brand_builder: Optional[Callable[[Dict[str, Any]], BrandProfile]] = None,
        message_engine: Optional[Callable[[BrandProfile], List[MessageStrategy]]] = None,
        concept_engine: Optional[
            Callable[[BrandProfile, List[MessageStrategy]], List[AdConcept]]
        ] = None,
    ) -> None:
        self._project_store = project_store or ProjectStore()

        if scraper_factory is not None:
            self._scraper_factory = scraper_factory
        else:
            from engine.scraper.site import WebsiteScraper

            self._scraper_factory = WebsiteScraper

        self._brand_builder = brand_builder or BrandProfileBuilder.from_scrape_data
        self._message_engine = message_engine or MessageStrategyEngine().generate
        self._concept_engine = concept_engine or AdConceptEngine().generate

    @property
    def project_store(self) -> ProjectStore:
        return self._project_store

    # ------------------------------------------------------------------
    # Existing-project lookup (idempotency)
    # ------------------------------------------------------------------
    def find_project_for_prospect(self, prospect_id: str) -> Optional[Project]:
        """Return the durable Project already associated with a prospect, or None.

        Association key: a project whose ``metadata["prospect_id"]`` matches.
        """
        if not prospect_id:
            return None
        for project in self._project_store.list():
            if str(project.metadata.get("prospect_id") or "") == prospect_id:
                return project
        return None

    def _resolve_project(
        self, result: ResearchResult, company: str, website: str
    ) -> Project:
        """Create (or reuse) the Project for a successful research run."""
        existing = self.find_project_for_prospect(result.prospect_id)
        if existing is not None:
            return existing
        self._report(result, "Saving Project")
        return self._project_store.create(
            company_name=company or "", website=website or ""
        )

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------
    def run(
        self,
        prospect: Prospect,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> ResearchResult:
        """Run the full research pipeline for a prospect.

        Never raises for ordinary research/scrape failures — it returns a
        ``ResearchResult`` with ``success=False`` and structured error info so
        the queue coordinator can handle retries per job.
        """
        result = ResearchResult(
            success=False,
            prospect_id=prospect.prospect_id,
        )
        try:
            self._execute(prospect, result, progress_callback)
        except Exception as exc:  # noqa: BLE001 - per-job failure must not kill the queue
            classification = _classify_error(exc, result.website or prospect.website)
            result.success = False
            result.error = str(exc)[:400]
            result.error_type = classification["type"]
            result.retryable = classification["retryable"]
            if result.error_type in (
                ERR_BRAND_PROFILE,
                ERR_STRATEGIES,
                ERR_CONCEPTS,
                ERR_PROJECT,
            ):
                result.retryable = False
            logger.warning(
                "Research pipeline failed prospect_id=%s error=%s type=%s retryable=%s",
                prospect.prospect_id,
                result.error,
                result.error_type,
                result.retryable,
            )
        return result

    def _execute(
        self,
        prospect: Prospect,
        result: ResearchResult,
        progress_callback: Optional[Callable[[str], None]],
    ) -> None:
        # 1. Validate website.
        website = _normalize_website_url(prospect.website or prospect.domain)
        result.website = website
        _validate_url(website)

        # 2. Scrape.
        self._report(result, "Opening website")
        self._report(result, "Scraping")
        scraper = self._scraper_factory(website)
        run_fn = getattr(scraper, "run", None)
        if run_fn is None:
            raise ValueError("Scraper has no run() method")

        def _scrape_progress(
            percent: int, message: str, stage: Optional[str] = None
        ) -> None:
            if callable(progress_callback):
                progress_callback(str(stage or message or ""))

        data = run_fn(progress_callback=_scrape_progress)
        result.scraped = True

        # 3. BrandProfile.
        self._report(result, "Building BrandProfile")
        brand_profile = self._brand_builder(data if isinstance(data, dict) else {})
        result.brand_profile = brand_profile

        # 4. Message strategies.
        self._report(result, "Generating Strategies")
        strategies = list(self._message_engine(brand_profile) or [])
        result.strategies = strategies

        # 5. Ad concepts.
        self._report(result, "Generating Concepts")
        concepts = list(self._concept_engine(brand_profile, strategies) or [])
        result.concepts = concepts

        # 6. Project (create or reuse — idempotent).
        company = brand_profile.company_name or prospect.company_name
        project = self._resolve_project(result, company, website)
        result.project_id = project.id

        # Populate structured pipeline state + prospect association.
        project.update_from_pipeline(
            brand_profile=brand_profile, strategies=strategies, concepts=concepts
        )
        project.metadata["prospect_id"] = prospect.prospect_id
        project.metadata.setdefault("research_job_provenance", True)
        project.append_history(
            "project_created_from_prospect",
            f"Project created from prospect research for {company}",
        )
        project.append_history("research_completed", "Research pipeline completed")
        project.status = "RESEARCHED"
        self._report(result, "Saving Project")
        self._project_store.save(project)

        result.success = True

    @staticmethod
    def _report(result: ResearchResult, stage: str) -> None:
        result.stages.append(stage)
