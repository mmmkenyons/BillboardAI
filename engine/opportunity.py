"""Sprint 5C prospect-to-inventory opportunity matching domain.

This module is the **pure, Qt-free, I/O-free** core of opportunity matching:

- ``Opportunity`` — the durable relationship between one **Prospect** and one
  **Placement** (a *sales possibility*). It is NOT a Project, a Placement, a
  Prospect, or a CRM deal stage.
- ``OpportunityEngine`` — deterministic eligibility + 0-100 decomposable score
  + human/machine-readable reasons, plus a stable rank helper.

Design rules honored:

- **No GUI.** This module imports only the standard library. Inputs
  (``prospect``, ``placement``, ``location``, ``market``, ``brand_profile``) are
  duck-typed: the engine reads the attributes it needs and never imports Qt or
  the GUI/engine model packages.
- **No web / scraping / LLM.** Everything here is deterministic string + numeric
  logic. No network, no scraper, no LLM.
- **Eligibility first, score second.** A placement must pass HARD eligibility
  before it can receive a meaningful score. Hard-blocked placements get
  ``eligible = False``, ``score = 0`` and explicit blocking reasons — blockers
  are never buried inside a low numeric score.
- **Reuse inventory restriction logic.** The engine delegates category
  restriction checks to ``Placement.is_available_for(category)`` and only
  orchestrates *which normalized category form* to present. It never
  re-implements the status / blocked / exclusive rules.
- **Deterministic and transparent.** ``score`` is always ``sum(score_components)``
  and each component plus its reasons can be explained by the UI.

Domain separation reminder (do NOT conflate):

- ``Prospect``  — a business we may sell advertising to (raw/managed lead).
- ``Project``   — researched persistent working state for a prospect.
- ``Placement`` — a sellable advertising unit.
- ``Opportunity`` — the prospect <-> placement sales possibility.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Opportunity status (recommendation/match lifecycle, NOT a sales pipeline).
# ---------------------------------------------------------------------------
STATUS_NEW = "NEW"
STATUS_RECOMMENDED = "RECOMMENDED"
STATUS_REVIEWED = "REVIEWED"
STATUS_SELECTED = "SELECTED"
STATUS_REJECTED = "REJECTED"
STATUS_ARCHIVED = "ARCHIVED"

OPPORTUNITY_STATUSES: tuple = (
    STATUS_NEW,
    STATUS_RECOMMENDED,
    STATUS_REVIEWED,
    STATUS_SELECTED,
    STATUS_REJECTED,
    STATUS_ARCHIVED,
)

# Statuses that represent an explicit human decision and are therefore preserved
# across recomputes (the engine only updates NEW / RECOMMENDED automatically).
MANUAL_STATUSES: tuple = (
    STATUS_REVIEWED,
    STATUS_SELECTED,
    STATUS_REJECTED,
    STATUS_ARCHIVED,
)

_DEFAULT_STATUS = STATUS_NEW

# ---------------------------------------------------------------------------
# Scoring weights. The MVP weighting is deliberately simple and documented:
#
#   Category fit          35  (researched evidence rewarded; a gate)
#   Market/location fit   20  (exact city+state / same market / distance)
#   Traffic               15  (relative inventory-quality signal only)
#   Prospect quality      15  (research + structured contact evidence)
#   Commercial fit        15  (conservative contact + pricing + trust evidence)
#   -------------------------
#   Total                100
#
# Weights are module constants so the UI and future sales tools can explain
# exactly why a prospect is ranked #1 without reading magic numbers.
# ---------------------------------------------------------------------------
CATEGORY_WEIGHT = 35
MARKET_WEIGHT = 20
TRAFFIC_WEIGHT = 15
QUALITY_WEIGHT = 15
COMMERCIAL_WEIGHT = 15
TOTAL_WEIGHT = (
    CATEGORY_WEIGHT + MARKET_WEIGHT + TRAFFIC_WEIGHT + QUALITY_WEIGHT + COMMERCIAL_WEIGHT
)

# Reflects "researched evidence first" for category source.
_CATEGORY_BRAND_PROFILE = 35
_CATEGORY_PROSPECT_CATEGORY = 28
_CATEGORY_PROSPECT_SUBCATEGORY = 22

# Market-fit sub-scores.
_MARKET_CITY_STATE = MARKET_WEIGHT  # 20
_MARKET_SAME_MARKET = 18
_MARKET_SAME_STATE_ONLY = 5  # small — a shared state is NOT treated as nearby
_MARKET_DISTANCE_THRESHOLD_MILES = 15.0

# Traffic bands (deterministic; relative inventory-quality signal only).
_TRAFFIC_BAND_LOW = 5
_TRAFFIC_BAND_MODERATE = 8
_TRAFFIC_BAND_STRONG = 12
_TRAFFIC_BAND_VERY_STRONG = TRAFFIC_WEIGHT  # 15

# Prospect-quality sub-awards.
_QUALITY_PROJECT = 5
_QUALITY_Q_HIGH = 4
_QUALITY_Q_MID = 2
_QUALITY_VISION_HIGH = 2
_QUALITY_VISION_MID = 1
_QUALITY_PHONE = 2
_QUALITY_WEBSITE = 1
_QUALITY_CATEGORIES = 1

# Commercial-fit sub-awards (conservative; no budget/revenue inference).
_COMMERCIAL_CONTACT = 5
_COMMERCIAL_PRICE = 5
_COMMERCIAL_EXCLUSIVITY_FIT = 3
_COMMERCIAL_TRUST = 2

# ---------------------------------------------------------------------------
# Small explicit synonym/normalization map (no giant taxonomy). The canonical
# key is the first token; the value is the set of accepted *forms* that will be
# presented to ``Placement.is_available_for``. This lets e.g. a prospect tagged
# "real estate" match a placement exclusive to "Realtor" WITHOUT re-implementing
# inventory restriction logic.
# ---------------------------------------------------------------------------
_CATEGORY_ALIASES: Dict[str, frozenset] = {
    "roofing": frozenset({"roofing"}),
    "dentist": frozenset({"dentist", "dental", "dentistry"}),
    "real estate": frozenset({"real estate", "realtor", "real-estate", "real_estate"}),
}

# Reverse alias -> canonical, built once.
_ALIAS_TO_CANONICAL: Dict[str, str] = {}
for _canon, _forms in _CATEGORY_ALIASES.items():
    for _form in _forms:
        _ALIAS_TO_CANONICAL[_form] = _canon
# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def filesystem_safe_id(prefix: str = "") -> str:
    """Return a stable, filesystem-safe, JSON-safe unique id."""
    uid = str(uuid.uuid4())
    return f"{prefix}_{uid}" if prefix else uid


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (second precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_token(value: Any) -> str:
    """Trim + lowercase + collapse whitespace for safe deterministic compare."""
    if value is None:
        return ""
    s = re.sub(r"\s+", " ", str(value).strip())
    return s.lower()


def canonical_category(value: Any) -> str:
    """Return the canonical category key for a raw token (or the token itself).

    ``None``/empty returns ``""``. Unknown tokens are returned normalized but
    unchanged (we never fabricate a category).
    """
    token = normalize_token(value)
    if not token:
        return ""
    return _ALIAS_TO_CANONICAL.get(token, token)


def category_forms(canonical: str) -> frozenset:
    """Return the set of presentable category forms for a canonical key.

    Falls back to ``{canonical}`` when the canonical is not in the small map.
    """
    if canonical in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[canonical]
    return frozenset({canonical}) if canonical else frozenset()


def display_category(value: Any) -> str:
    """A short human display for a category (first letter capitalized)."""
    c = normalize_token(value)
    if not c:
        return ""
    return c[0].upper() + c[1:]


def haversine_miles(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Great-circle distance in miles between two lat/lng points.

    Uses the standard haversine formula with Earth radius 3958.8 miles.
    """
    r = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * r * math.asin(math.sqrt(a))


def _as_float(value: Any) -> Optional[float]:
    """Coerce a persisted lat/lng token (float or numeric string) to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
# ---------------------------------------------------------------------------
# Opportunity model
# ---------------------------------------------------------------------------


@dataclass
class Opportunity:
    """A durable prospect <-> placement sales possibility.

    Optional relationship fields (project_id, location_id, market_id,
    distance_miles, ...) are safe to leave empty; ``from_dict`` supplies safe
    defaults and ignores unknown persisted fields (forward compatible).
    """

    opportunity_id: str = field(default_factory=lambda: filesystem_safe_id("opportunity"))
    prospect_id: str = ""
    project_id: str = ""
    placement_id: str = ""
    location_id: str = ""
    market_id: str = ""

    status: str = _DEFAULT_STATUS

    eligible: bool = False
    eligibility_reasons: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    score: int = 0
    score_components: Dict[str, Any] = field(default_factory=dict)

    recommended_category: str = ""

    distance_miles: Optional[float] = None
    distance_source: str = ""

    created_at: str = field(default_factory=utc_now_iso)
    modified_at: str = field(default_factory=utc_now_iso)

    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """Update ``modified_at`` (keeps ``created_at`` stable)."""
        self.modified_at = utc_now_iso()

    def key(self) -> Tuple[str, str]:
        """Return the idempotency key ``(prospect_id, placement_id)``."""
        return (self.prospect_id or "", self.placement_id or "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "prospect_id": self.prospect_id,
            "project_id": self.project_id,
            "placement_id": self.placement_id,
            "location_id": self.location_id,
            "market_id": self.market_id,
            "status": self.status,
            "eligible": self.eligible,
            "eligibility_reasons": list(self.eligibility_reasons),
            "reasons": list(self.reasons),
            "score": self.score,
            "score_components": dict(self.score_components),
            "recommended_category": self.recommended_category,
            "distance_miles": self.distance_miles,
            "distance_source": self.distance_source,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "notes": self.notes,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Opportunity":
        data = data if isinstance(data, dict) else {}
        status = str(data.get("status") or _DEFAULT_STATUS)
        if status not in OPPORTUNITY_STATUSES:
            status = _DEFAULT_STATUS
        return cls(
            opportunity_id=str(data.get("opportunity_id") or filesystem_safe_id("opportunity")),
            prospect_id=str(data.get("prospect_id") or ""),
            project_id=str(data.get("project_id") or ""),
            placement_id=str(data.get("placement_id") or ""),
            location_id=str(data.get("location_id") or ""),
            market_id=str(data.get("market_id") or ""),
            status=status,
            eligible=bool(data.get("eligible", False)),
            eligibility_reasons=[str(r) for r in data.get("eligibility_reasons") or []],
            reasons=[str(r) for r in data.get("reasons") or []],
            score=int(data.get("score", 0) or 0),
            score_components=dict(data.get("score_components") or {}),
            recommended_category=str(data.get("recommended_category") or ""),
            distance_miles=_as_float(data.get("distance_miles")),
            distance_source=str(data.get("distance_source") or ""),
            created_at=str(data.get("created_at") or utc_now_iso()),
            modified_at=str(data.get("modified_at") or utc_now_iso()),
            notes=str(data.get("notes") or ""),
            metadata=dict(data.get("metadata") or {}),
        )
# ---------------------------------------------------------------------------
# OpportunityEngine
# ---------------------------------------------------------------------------


class OpportunityEngine:
    """Deterministic eligibility + score + reasons for one prospect/placement.

    The engine is stateless and pure: it never talks to a store, never performs
    I/O, and never imports Qt. Callers (e.g. ``OpportunityService``) are
    responsible for locating the prospect/project/inventory objects.
    """

    def evaluate(
        self,
        prospect: Any,
        placement: Any,
        location: Any,
        brand_profile: Any = None,
        market: Any = None,
    ) -> Opportunity:
        """Evaluate one prospect against one placement -> an ``Opportunity``.

        ``prospect``        — duck-typed Prospect (category, subcategory, city,
                              state, market_id, phone, domain, metadata).
        ``placement``       — duck-typed Placement (status, is_available_for,
                              exclusive_category, blocked_categories, price,
                              effective_weekly_traffic).
        ``location``        — duck-typed Location (city, state, latitude,
                              longitude, weekly_traffic) or None.
        ``brand_profile``   — optional researched BrandProfile.
        ``market``          — optional Market (reserved; not used in MVP score).
        """
        eligible, eligibility_reasons = self._check_eligibility(
            prospect, placement, location, brand_profile
        )

        opportunity = Opportunity(
            prospect_id=getattr(prospect, "prospect_id", "") or "",
            placement_id=getattr(placement, "placement_id", "") or "",
            location_id=getattr(location, "location_id", "") if location is not None else "",
            market_id=(
                (getattr(location, "market_id", "") or "")
                if location is not None
                else (getattr(market, "market_id", "") or "")
            ),
            eligible=eligible,
            eligibility_reasons=list(eligibility_reasons),
        )

        # Distance is always computed architecturally (even when ineligible) so
        # Sprint 5D can reason about 'nearest available placement'.
        opportunity.distance_miles, opportunity.distance_source = self._distance(
            prospect, location
        )

        if not eligible:
            opportunity.score = 0
            opportunity.score_components = self._zero_components()
            opportunity.reasons = list(eligibility_reasons)
            opportunity.status = STATUS_NEW
            return opportunity

        # Eligible -> score components + reasons.
        cat, source = self._resolve_category(prospect, brand_profile, placement)
        opportunity.recommended_category = cat or ""

        reasons: List[str] = []
        components: Dict[str, Any] = {}

        components["category_fit"], cat_reason = self._category_fit(source, cat)
        components["market_fit"], mkt_reason = self._market_fit(
            prospect, location, opportunity.distance_miles
        )
        components["traffic"], traffic_reason = self._traffic(placement, location)
        components["prospect_quality"], qual_reason = self._prospect_quality(
            prospect, brand_profile
        )
        components["commercial_fit"], comm_reason = self._commercial_fit(
            prospect, placement, brand_profile, cat
        )

        for reason in (cat_reason, mkt_reason, traffic_reason, qual_reason, comm_reason):
            if reason:
                reasons.append(reason)

        opportunity.score_components = components
        opportunity.score = int(round(float(sum(components.values()))))
        opportunity.score = min(TOTAL_WEIGHT, max(0, opportunity.score))
        opportunity.reasons = reasons
        opportunity.status = STATUS_RECOMMENDED
        return opportunity
    # ------------------------------------------------------------------
    # Eligibility (hard blockers)
    # ------------------------------------------------------------------

    def _check_eligibility(
        self, prospect: Any, placement: Any, location: Any, brand_profile: Any
    ) -> Tuple[bool, List[str]]:
        """Return (eligible, reasons). Hard blockers never degrade to a score."""
        status = getattr(placement, "status", "") or ""
        if status and status != "AVAILABLE":
            return False, [f"Placement is {status}"]

        location_id = getattr(placement, "location_id", "") or ""
        if not location_id:
            return False, ["Placement has no associated location"]
        if location is None:
            return False, ["Placement location not found in inventory"]

        cat, _source = self._resolve_category(prospect, brand_profile, placement)
        if cat is not None:
            return True, []

        candidates = self._category_candidates(prospect, brand_profile)
        if not candidates:
            return False, ["No supported category evidence"]

        return False, self._category_blocked_reasons(candidates, placement)

    def _category_blocked_reasons(
        self, candidates: List[Tuple[str, str]], placement: Any
    ) -> List[str]:
        """Produce a specific reason when no candidate category cleared the gate."""
        blocked_norms = {
            normalize_token(c) for c in getattr(placement, "blocked_categories", []) or []
        }
        exclusive = normalize_token(getattr(placement, "exclusive_category", "") or "")

        for canon, _src in candidates:
            for form in category_forms(canon):
                if normalize_token(form) in blocked_norms:
                    return [f"{display_category(canon)} category blocked"]
        if exclusive:
            return [f"{display_category(exclusive)} category already exclusive"]
        return ["Category not supported by placement"]

    # ------------------------------------------------------------------
    # Category resolution (researched evidence first, fallback after)
    # ------------------------------------------------------------------

    def _category_candidates(
        self, prospect: Any, brand_profile: Any
    ) -> List[Tuple[str, str]]:
        """Ordered, deduped (canonical, source) category candidates.

        Priority: BrandProfile.categories -> Prospect.category ->
        Prospect.subcategory. We only use existing evidence; we never infer an
        industry from a company name.
        """
        result: List[Tuple[str, str]] = []
        seen = set()

        bp_categories = (
            list(getattr(brand_profile, "categories", None) or [])
            if brand_profile is not None
            else []
        )
        for raw in bp_categories:
            canon = canonical_category(raw)
            if canon and canon not in seen:
                seen.add(canon)
                result.append((canon, "brand_profile"))

        pc = canonical_category(getattr(prospect, "category", "") or "")
        if pc and pc not in seen:
            seen.add(pc)
            result.append((pc, "prospect_category"))

        ps = canonical_category(getattr(prospect, "subcategory", "") or "")
        if ps and ps not in seen:
            seen.add(ps)
            result.append((ps, "prospect_subcategory"))

        return result

    def _resolve_category(
        self, prospect: Any, brand_profile: Any, placement: Any
    ) -> Tuple[Optional[str], Optional[str]]:
        """Return (canonical_category, source) of the best supported category.

        Tests each candidate's presentable forms against
        ``Placement.is_available_for`` (reusing inventory restriction logic).
        Returns (None, None) when no candidate is supported — we never invent a
        category to force eligibility.
        """
        for canon, source in self._category_candidates(prospect, brand_profile):
            for form in category_forms(canon):
                try:
                    if placement.is_available_for(form):
                        return canon, source
                except Exception:  # noqa: BLE001 - defensive duck-typing
                    continue
        return None, None
    # ------------------------------------------------------------------
    # Distance (Haversine; no geocoding in Sprint 5C)
    # ------------------------------------------------------------------

    def _prospect_coords(self, prospect: Any) -> Tuple[Optional[float], Optional[float]]:
        """Prospect lat/lng from metadata (forward-compatible seam).

        The current ``Prospect`` model has no native coordinates, so this looks
        in ``prospect.metadata["latitude"]`` / ``["longitude"]`` (float or
        numeric string). Sprint 5D will add real geocoding; until then real
        prospects typically yield ``None``.
        """
        meta = getattr(prospect, "metadata", None) or {}
        lat = None
        lng = None
        if isinstance(meta, dict):
            lat = _as_float(meta.get("latitude") or meta.get("lat"))
            lng = _as_float(meta.get("longitude") or meta.get("lng") or meta.get("lon"))
        return lat, lng

    def _distance(
        self, prospect: Any, location: Any
    ) -> Tuple[Optional[float], str]:
        """Straight-line (Haversine) miles when BOTH sides have coordinates."""
        if location is None:
            return None, ""
        p_lat, p_lng = self._prospect_coords(prospect)
        loc_lat = _as_float(getattr(location, "latitude", None))
        loc_lng = _as_float(getattr(location, "longitude", None))
        if p_lat is None or p_lng is None or loc_lat is None or loc_lng is None:
            return None, ""
        return round(haversine_miles(p_lat, p_lng, loc_lat, loc_lng), 1), "haversine"

    # ------------------------------------------------------------------
    # Scoring components
    # ------------------------------------------------------------------

    def _category_fit(self, source: Optional[str], category: Optional[str]) -> Tuple[int, str]:
        """Researched evidence is rewarded; the category is a gate for eligibility."""
        if source == "brand_profile":
            return _CATEGORY_BRAND_PROFILE, f"{display_category(category)} category allowed (researched profile)"
        if source == "prospect_category":
            return _CATEGORY_PROSPECT_CATEGORY, f"{display_category(category)} category allowed (prospect category)"
        if source == "prospect_subcategory":
            return _CATEGORY_PROSPECT_SUBCATEGORY, f"{display_category(category)} category allowed (subcategory)"
        return 0, ""

    def _market_fit(
        self, prospect: Any, location: Any, distance_miles: Optional[float]
    ) -> Tuple[int, str]:
        """Deterministic market/location fit (no external geocoding)."""
        if location is None:
            return 0, "No geographic proximity evidence"

        # Distance-derived bonus when BOTH sides have coordinates (>= derived).
        if distance_miles is not None and distance_miles <= _MARKET_DISTANCE_THRESHOLD_MILES:
            scale = max(0.0, 1.0 - (distance_miles / _MARKET_DISTANCE_THRESHOLD_MILES))
            sub = int(round(_MARKET_CITY_STATE * scale))
            sub = min(_MARKET_CITY_STATE, max(0, sub))
            return sub, f"{distance_miles} miles from placement"

        p_city = normalize_token(getattr(prospect, "city", "") or "")
        l_city = normalize_token(getattr(location, "city", "") or "")
        p_state = normalize_token(getattr(prospect, "state", "") or "")
        l_state = normalize_token(getattr(location, "state", "") or "")

        if p_city and l_city and p_city == l_city and p_state and l_state and p_state == l_state:
            return _MARKET_CITY_STATE, "Same city as placement"

        p_market = getattr(prospect, "market_id", "") or ""
        l_market = getattr(location, "market_id", "") or ""
        if p_market and l_market and p_market == l_market:
            return _MARKET_SAME_MARKET, "Same market"

        if p_state and l_state and p_state == l_state:
            # Small bonus only; a shared state is NOT treated as "nearby".
            return _MARKET_SAME_STATE_ONLY, "Same state only (not treated as nearby)"

        return 0, "No geographic proximity evidence"

    def _traffic(self, placement: Any, location: Any) -> Tuple[int, str]:
        """Relative inventory-quality signal (never ROI)."""
        try:
            traffic = placement.effective_weekly_traffic(location)
        except Exception:  # noqa: BLE001
            traffic = None
        if traffic is None:
            return 0, "Traffic unknown"
        traffic = int(traffic)
        label = f"{traffic:,} weekly shoppers"
        if traffic < 5000:
            return _TRAFFIC_BAND_LOW, f"Low weekly traffic ({label})"
        if traffic < 10000:
            return _TRAFFIC_BAND_MODERATE, f"Moderate weekly traffic ({label})"
        if traffic < 20000:
            return _TRAFFIC_BAND_STRONG, f"Strong weekly traffic ({label})"
        return _TRAFFIC_BAND_VERY_STRONG, f"Very strong weekly traffic ({label})"
    def _prospect_quality(self, prospect: Any, brand_profile: Any) -> Tuple[int, str]:
        """Structured evidence only; sparse profiles are not 'bad prospects'."""
        sub = 0
        reasons: List[str] = []

        has_project = brand_profile is not None
        if has_project:
            sub += _QUALITY_PROJECT
            reasons.append("Researched business profile available")

        q = _as_float(getattr(brand_profile, "quality_score", None)) if has_project else None
        if q is not None:
            if q >= 75.0:
                sub += _QUALITY_Q_HIGH
            elif q >= 50.0:
                sub += _QUALITY_Q_MID

        v = _as_float(getattr(brand_profile, "vision_score", None)) if has_project else None
        if v is not None:
            if v >= 75.0:
                sub += _QUALITY_VISION_HIGH
            elif v >= 50.0:
                sub += _QUALITY_VISION_MID

        if getattr(prospect, "phone", "") or (
            has_project and getattr(brand_profile, "phone", "")
        ):
            sub += _QUALITY_PHONE
            reasons.append("Phone/contact available")

        if getattr(prospect, "domain", "") or getattr(prospect, "website", ""):
            sub += _QUALITY_WEBSITE
            reasons.append("Website/domain present")

        if has_project and (
            getattr(brand_profile, "categories", None) or getattr(brand_profile, "services", None)
        ):
            sub += _QUALITY_CATEGORIES

        sub = min(QUALITY_WEIGHT, sub)
        return sub, "; ".join(reasons) if reasons else "Limited prospect evidence"

    def _commercial_fit(
        self, prospect: Any, placement: Any, brand_profile: Any, category: Optional[str]
    ) -> Tuple[int, str]:
        """Conservative commercial fit; no budget/revenue/ability-to-pay inference."""
        sub = 0
        has_contact = bool(
            getattr(prospect, "phone", "")
            or getattr(prospect, "email", "")
            or getattr(prospect, "contact_name", "")
        )
        if has_contact:
            sub += _COMMERCIAL_CONTACT

        if getattr(placement, "price", None) is not None:
            sub += _COMMERCIAL_PRICE

        if category:
            sub += _COMMERCIAL_EXCLUSIVITY_FIT

        has_trust = bool(
            brand_profile
            and (
                getattr(brand_profile, "differentiators", None)
                or getattr(brand_profile, "trust_signals", None)
                or getattr(brand_profile, "guarantees", None)
                or getattr(brand_profile, "certifications", None)
            )
        )
        if has_trust:
            sub += _COMMERCIAL_TRUST

        sub = min(COMMERCIAL_WEIGHT, sub)
        return sub, ""

    def _zero_components(self) -> Dict[str, Any]:
        return {
            "category_fit": 0,
            "market_fit": 0,
            "traffic": 0,
            "prospect_quality": 0,
            "commercial_fit": 0,
        }


# ---------------------------------------------------------------------------
# Ranking (deterministic)
# ---------------------------------------------------------------------------


def rank_opportunities(
    opportunities: List[Opportunity],
    include_ineligible: bool = False,
    limit: Optional[int] = None,
) -> List[Opportunity]:
    """Sort opportunities score DESC with a deterministic tie-breaker.

    Ineligible opportunities are omitted by default. ``limit`` truncates the
    result (None = unlimited).
    """
    candidates: List[Opportunity] = []
    for opp in opportunities:
        if opp.eligible or include_ineligible:
            candidates.append(opp)

    candidates.sort(
        key=lambda o: (
            -o.score,
            o.placement_id,
            o.prospect_id,
            o.opportunity_id,
        )
    )
    if limit is not None and limit >= 0:
        candidates = candidates[:limit]
    return candidates
