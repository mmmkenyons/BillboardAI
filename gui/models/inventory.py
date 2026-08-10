"""Sprint 4A durable advertising-inventory domain models.

This module models the **advertising inventory** BillboardAI ultimately sells.
It is deliberately decoupled from:

- prospects / matching / outreach (later sprints)
- creative generation / rendering internals
- the GUI widgets / services

It never imports Qt or engine rendering modules, so these models are pure and
testable in isolation.

Domain separation (do NOT conflate these):

- ``Retailer``        — a retail brand / venue brand (e.g. King Soopers,
                        parent = Kroger).
- ``Market``          — a geographic operating market (e.g. Denver Metro).
- ``Location``        — one real physical store/venue/site (e.g. King Soopers
                        #123 in Castle Rock, CO).
- ``Placement``       — one specific sellable ad position at a Location
                        (e.g. Front Cart Corral A).
- ``SceneTemplate``   — NOT modeled here; a Placement simply *references* a
                        physical scene template name as an opaque string. No
                        template names are hardcoded.

Pricing is stored as **integer cents** (a ``Money`` value object) rather than
floats. JSON has no native Decimal, so serialization stores cents + currency;
``Decimal`` is used only when converting dollar amounts to cents so no float
rounding error can creep into the stored value.

Serialization follows the forward-compatible ``to_dict`` / ``from_dict``
pattern used across the engine/GUI models: unknown persisted fields are
ignored and missing optional fields receive safe defaults.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# Controlled status model (no contract/billing state yet).
# --------------------------------------------------------------------------
STATUS_AVAILABLE = "AVAILABLE"
STATUS_HELD = "HELD"
STATUS_SOLD = "SOLD"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_MAINTENANCE = "MAINTENANCE"
STATUS_ARCHIVED = "ARCHIVED"

PLACEMENT_STATUSES: tuple = (
    STATUS_AVAILABLE,
    STATUS_HELD,
    STATUS_SOLD,
    STATUS_UNAVAILABLE,
    STATUS_MAINTENANCE,
    STATUS_ARCHIVED,
)

# --------------------------------------------------------------------------
# Price periods (simple, durable; no rate cards / discounts yet).
# --------------------------------------------------------------------------
PERIOD_ONETIME = "ONETIME"
PERIOD_MONTH = "MONTH"
PERIOD_YEAR = "YEAR"

PRICE_PERIODS: tuple = (PERIOD_ONETIME, PERIOD_MONTH, PERIOD_YEAR)

# Default currency for pricing.
DEFAULT_CURRENCY = "USD"

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def filesystem_safe_id(prefix: str = "") -> str:
    """Return a stable, filesystem-safe, JSON-safe unique id.

    A UUID is used (never a human/company label alone) so multiple entities of
    the same kind never collide and the value is safe to use as a directory or
    filename component.
    """
    uid = str(uuid.uuid4())
    return f"{prefix}_{uid}" if prefix else uid


def _norm_category(category: Optional[str]) -> str:
    """Normalize a category string for safe comparison (trim + lowercase)."""
    if not category:
        return ""
    return str(category).strip().lower()


def _clean_text(value: Any) -> str:
    """Coerce a persisted value to a trimmed string (None -> empty)."""
    if value is None:
        return ""
    return str(value).strip()


def _optional_int(value: Any) -> Optional[int]:
    """Coerce a persisted value to an int, or None when absent/invalid."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> Optional[float]:
    """Coerce a persisted value to a float, or None when absent/invalid."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any) -> List[str]:
    """Coerce a persisted value to a list of strings (safe defaults)."""
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if item is not None]
# --------------------------------------------------------------------------
# Money value object (integer cents = JSON-safe, no float precision loss).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Money:
    """A monetary amount stored as integer cents."""

    amount_cents: int
    currency: str = DEFAULT_CURRENCY

    @classmethod
    def cents(cls, amount_cents: int, currency: str = DEFAULT_CURRENCY) -> "Money":
        """Build from integer cents (the canonical representation)."""
        return cls(int(amount_cents), currency or DEFAULT_CURRENCY)

    @classmethod
    def dollars(cls, amount: Any, currency: str = DEFAULT_CURRENCY) -> "Money":
        """Build from a dollar amount, converting via Decimal (no float error).

        ``Decimal(str(amount))`` avoids binary float artifacts, so e.g.
        ``0.1 + 0.2`` dollars never becomes 30.000000000000004 cents.
        """
        if amount is None or amount == "":
            raise ValueError("Money.dollars requires a numeric amount")
        cents = (Decimal(str(amount)) * 100).to_integral_value(
            rounding=ROUND_HALF_UP
        )
        return cls(int(cents), currency or DEFAULT_CURRENCY)

    @property
    def amount_dollars(self) -> float:
        """The amount in dollars (read convenience only; never persisted)."""
        return self.amount_cents / 100

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "amount_cents": self.amount_cents,
            "currency": self.currency,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["Money"]:
        if not isinstance(data, dict):
            return None
        try:
            cents = int(data.get("amount_cents", 0) or 0)
        except (TypeError, ValueError):
            cents = 0
        currency = str(data.get("currency") or DEFAULT_CURRENCY)
        return cls(cents, currency)

    def format(self) -> str:
        """Format like ``$12,000`` or ``$12,000.50`` (no currency code)."""
        sign = "-" if self.amount_cents < 0 else ""
        abs_cents = abs(self.amount_cents)
        dollars = abs_cents // 100
        remainder = abs_cents % 100
        if remainder == 0:
            return f"{sign}${dollars:,}"
        return f"{sign}${dollars:,}.{remainder:02d}"


# --------------------------------------------------------------------------
# Retailer
# --------------------------------------------------------------------------


@dataclass
class Retailer:
    """A retail / venue brand (e.g. King Soopers, parent = Kroger)."""

    retailer_id: str = field(default_factory=lambda: filesystem_safe_id("retailer"))
    name: str = ""
    parent_company: str = ""
    brand_name: str = ""
    website: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "retailer_id": self.retailer_id,
            "name": self.name,
            "parent_company": self.parent_company,
            "brand_name": self.brand_name,
            "website": self.website,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Retailer":
        data = data if isinstance(data, dict) else {}
        return cls(
            retailer_id=_clean_text(data.get("retailer_id")) or filesystem_safe_id("retailer"),
            name=_clean_text(data.get("name")),
            parent_company=_clean_text(data.get("parent_company")),
            brand_name=str(data.get("brand_name") or "").strip()
            if data.get("brand_name")
            else _clean_text(data.get("name")),
            website=_clean_text(data.get("website")),
            metadata=dict(data.get("metadata") or {}),
        )


# --------------------------------------------------------------------------
# Market
# --------------------------------------------------------------------------


@dataclass
class Market:
    """A geographic operating market (e.g. Denver Metro). Lightweight."""

    market_id: str = field(default_factory=lambda: filesystem_safe_id("market"))
    name: str = ""
    state: str = ""
    region: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "name": self.name,
            "state": self.state,
            "region": self.region,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Market":
        data = data if isinstance(data, dict) else {}
        return cls(
            market_id=_clean_text(data.get("market_id")) or filesystem_safe_id("market"),
            name=_clean_text(data.get("name")),
            state=_clean_text(data.get("state")),
            region=_clean_text(data.get("region")),
            metadata=dict(data.get("metadata") or {}),
        )
# --------------------------------------------------------------------------
# Location
# --------------------------------------------------------------------------


@dataclass
class Location:
    """One real physical store/venue/site where placements exist."""

    location_id: str = field(default_factory=lambda: filesystem_safe_id("location"))
    retailer_id: str = ""
    market_id: str = ""
    name: str = ""
    store_number: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    weekly_traffic: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "location_id": self.location_id,
            "retailer_id": self.retailer_id,
            "market_id": self.market_id,
            "name": self.name,
            "store_number": self.store_number,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "weekly_traffic": self.weekly_traffic,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Location":
        data = data if isinstance(data, dict) else {}
        return cls(
            location_id=_clean_text(data.get("location_id")) or filesystem_safe_id("location"),
            retailer_id=_clean_text(data.get("retailer_id")),
            market_id=_clean_text(data.get("market_id")),
            name=_clean_text(data.get("name")),
            store_number=str(data.get("store_number") or ""),
            address=_clean_text(data.get("address")),
            city=_clean_text(data.get("city")),
            state=_clean_text(data.get("state")),
            postal_code=_clean_text(data.get("postal_code")),
            latitude=_optional_float(data.get("latitude")),
            longitude=_optional_float(data.get("longitude")),
            weekly_traffic=_optional_int(data.get("weekly_traffic")),
            metadata=dict(data.get("metadata") or {}),
        )
# --------------------------------------------------------------------------
# Placement
# --------------------------------------------------------------------------


@dataclass
class Placement:
    """One specific sellable advertising position at a real Location."""

    placement_id: str = field(default_factory=lambda: filesystem_safe_id("placement"))
    location_id: str = ""
    name: str = ""
    placement_type: str = ""
    # Reference to a physical scene template name (opaque string, never
    # hardcoded here or branched on in this module).
    scene_template: str = ""
    status: str = STATUS_AVAILABLE

    price: Optional[Money] = None
    price_period: str = PERIOD_YEAR
    setup_fee: Optional[Money] = None

    # Category restrictions: ``exclusive_category`` is the single category that
    # owns this placement (sold/reserved); ``blocked_categories`` are categories
    # that may never use it. Both are normalized for comparison.
    exclusive_category: str = ""
    blocked_categories: List[str] = field(default_factory=list)

    start_date: Optional[str] = None
    end_date: Optional[str] = None

    # Traffic override (None => inherit from the Location).
    traffic_override: Optional[int] = None

    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available_for(self, category: str) -> bool:
        """Return whether this placement is available for ``category``.

        Deterministic rules considered:
        1. The placement status must be ``AVAILABLE``.
        2. The (normalized) category must not be blocked.
        3. If an ``exclusive_category`` is set, only that category is accepted.

        ``category`` is an explicit input string; no prospect data is inferred.
        """
        if self.status != STATUS_AVAILABLE:
            return False

        norm = _norm_category(category)
        if not norm:
            return False

        blocked = {_norm_category(c) for c in self.blocked_categories}
        if norm in blocked:
            return False

        exclusive = _norm_category(self.exclusive_category)
        if exclusive:
            return norm == exclusive

        return True

    def effective_weekly_traffic(self, location: Optional[Location] = None) -> Optional[int]:
        """Return the traffic to use for this placement.

        A placement-level ``traffic_override`` wins; otherwise the Location's
        ``weekly_traffic`` is inherited. Returns None when neither is set.
        """
        if self.traffic_override is not None:
            return self.traffic_override
        if location is not None:
            return location.weekly_traffic
        return None

    def price_display(self) -> str:
        """Human display like ``$12,000/year`` (empty when no price)."""
        if self.price is None:
            return ""
        base = self.price.format()
        period = self.price_period.lower() if self.price_period else ""
        return f"{base}/{period}" if period else base
# ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "placement_id": self.placement_id,
            "location_id": self.location_id,
            "name": self.name,
            "placement_type": self.placement_type,
            "scene_template": self.scene_template,
            "status": self.status,
            "price": self.price.to_dict() if self.price is not None else None,
            "price_period": self.price_period,
            "setup_fee": self.setup_fee.to_dict() if self.setup_fee is not None else None,
            "exclusive_category": self.exclusive_category,
            "blocked_categories": list(self.blocked_categories),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "traffic_override": self.traffic_override,
            "notes": self.notes,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Placement":
        data = data if isinstance(data, dict) else {}
        status = _clean_text(data.get("status")) or STATUS_AVAILABLE
        if status not in PLACEMENT_STATUSES:
            status = STATUS_AVAILABLE
        period = _clean_text(data.get("price_period")) or PERIOD_YEAR
        if period not in PRICE_PERIODS:
            period = PERIOD_YEAR
        return cls(
            placement_id=_clean_text(data.get("placement_id")) or filesystem_safe_id("placement"),
            location_id=_clean_text(data.get("location_id")),
            name=_clean_text(data.get("name")),
            placement_type=_clean_text(data.get("placement_type")),
            scene_template=_clean_text(data.get("scene_template")),
            status=status,
            price=Money.from_dict(data.get("price")),
            price_period=period,
            setup_fee=Money.from_dict(data.get("setup_fee")),
            exclusive_category=_clean_text(data.get("exclusive_category")),
            blocked_categories=_string_list(data.get("blocked_categories")),
            start_date=data.get("start_date") or None,
            end_date=data.get("end_date") or None,
            traffic_override=_optional_int(data.get("traffic_override")),
            notes=_clean_text(data.get("notes")),
            metadata=dict(data.get("metadata") or {}),
        )

    def is_valid_scene_template(self, known: set) -> bool:
        """Advisory check that ``scene_template`` is among ``known`` names.

        This is OPTIONAL and caller-driven: the model never validates against
        on-disk assets itself, so inventory loading never fails just because a
        scene asset is temporarily missing. Pass the set of known template ids
        (e.g. from the renderer) when you want a soft sanity check.
        """
        if not self.scene_template:
            return False
        return self.scene_template in set(known or ())