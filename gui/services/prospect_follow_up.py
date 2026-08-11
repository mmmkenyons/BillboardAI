"""Sprint 5H Prospect Follow-Up Queue service (Qt-free).

A read/triage layer over existing Prospect workflow state. This module does NOT
own workflow data, does NOT mutate prospects, and does NOT perform scrape,
research, geocoding, enrichment, or opportunity recomputation. It derives
display-ready follow-up items from the authoritative ProspectStore.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from gui.models.prospect import (
    CLOSED_WORKFLOW_STATUSES,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    PRIORITY_URGENT,
    WORKFLOW_STATUS_LOST,
    WORKFLOW_STATUS_NOT_INTERESTED,
    WORKFLOW_STATUS_WON,
    Prospect,
)
from gui.models.prospect_store import ProspectStore


# ---------------------------------------------------------------------------
# Timing states (derived, read-only)
# ---------------------------------------------------------------------------
TIMING_OVERDUE = "OVERDUE"
TIMING_DUE_TODAY = "DUE_TODAY"
TIMING_UPCOMING = "UPCOMING"
TIMING_NO_DUE_DATE = "NO_DUE_DATE"
TIMING_CLOSED = "CLOSED"

TIMING_STATES: tuple = (
    TIMING_OVERDUE,
    TIMING_DUE_TODAY,
    TIMING_UPCOMING,
    TIMING_NO_DUE_DATE,
    TIMING_CLOSED,
)

# ---------------------------------------------------------------------------
# Filter constants
# ---------------------------------------------------------------------------
STATUS_FILTER_ACTIVE = "ACTIVE"
STATUS_FILTER_ALL = "ALL"
STATUS_FILTER_CLOSED = "CLOSED"
PRIORITY_FILTER_ALL = "ALL"
TIMING_FILTER_ALL = "ALL"
TIMING_FILTER_NEEDS_ATTENTION = "NEEDS_ATTENTION"
SORT_MODE_DEFAULT = "DEFAULT"

# Terminal workflow statuses excluded from the default active queue.
_TERMINAL_STATUSES = set(CLOSED_WORKFLOW_STATUSES)

# Deterministic ordering weights.
_TIMING_SORT_WEIGHT: Dict[str, int] = {
    TIMING_OVERDUE: 0,
    TIMING_DUE_TODAY: 1,
    TIMING_UPCOMING: 2,
    TIMING_NO_DUE_DATE: 3,
    TIMING_CLOSED: 4,
}

_PRIORITY_SORT_WEIGHT: Dict[str, int] = {
    PRIORITY_URGENT: 0,
    PRIORITY_HIGH: 1,
    PRIORITY_NORMAL: 2,
    PRIORITY_LOW: 3,
}


# ---------------------------------------------------------------------------
# Timing classification
# ---------------------------------------------------------------------------

def _today_value(today: Optional[Any]) -> date:
    """Normalize an injected today to a ``date`` object."""
    if today is None:
        return date.today()
    if isinstance(today, date):
        return today
    if hasattr(today, "date"):
        return today.date()
    return date.fromisoformat(str(today).strip())


def derive_timing_state(prospect: Prospect, today: Optional[Any] = None) -> str:
    """Derive the follow-up timing state for a prospect.

    Rules (date-only, no wall-clock time):
        - workflow_status in terminal statuses -> CLOSED
        - next_action_date < today             -> OVERDUE
        - next_action_date == today            -> DUE_TODAY
        - next_action_date > today             -> UPCOMING
        - next_action_date is None             -> NO_DUE_DATE
    """
    if not prospect:
        return TIMING_NO_DUE_DATE

    status = (prospect.workflow_status or "").strip()
    if status in _TERMINAL_STATUSES:
        return TIMING_CLOSED

    raw_date = prospect.next_action_date
    if raw_date is None or str(raw_date).strip() == "":
        return TIMING_NO_DUE_DATE

    try:
        action_date = date.fromisoformat(str(raw_date).strip())
    except (TypeError, ValueError):
        return TIMING_NO_DUE_DATE

    compare = _today_value(today)
    if action_date < compare:
        return TIMING_OVERDUE
    if action_date == compare:
        return TIMING_DUE_TODAY
    return TIMING_UPCOMING


# ---------------------------------------------------------------------------
# Derived item
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProspectFollowUpItem:
    """A lightweight derived row for the Follow-Up Queue."""

    prospect_id: str = ""
    company_name: str = ""
    workflow_status: str = ""
    priority: str = ""
    next_action: str = ""
    next_action_date: Optional[str] = None
    timing_state: str = TIMING_NO_DUE_DATE
    location_summary: str = ""

    @property
    def needs_attention(self) -> bool:
        """True when the item is overdue, due today, or urgent priority."""
        return (
            self.timing_state in (TIMING_OVERDUE, TIMING_DUE_TODAY)
            or self.priority == PRIORITY_URGENT
        )


def _build_item(prospect: Prospect, today: Optional[Any]) -> ProspectFollowUpItem:
    """Build a follow-up item from a prospect without mutation or side effects."""
    parts = [p for p in (prospect.city, prospect.state) if p and str(p).strip()]
    location_summary = ", ".join(parts)

    return ProspectFollowUpItem(
        prospect_id=prospect.prospect_id or "",
        company_name=(prospect.company_name or "").strip(),
        workflow_status=(prospect.workflow_status or "").strip(),
        priority=(prospect.priority or "").strip(),
        next_action=(prospect.next_action or "").strip(),
        next_action_date=prospect.next_action_date,
        timing_state=derive_timing_state(prospect, today),
        location_summary=location_summary,
    )


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------

def _matches_search(item: ProspectFollowUpItem, prospect: Prospect, text: str) -> bool:
    """Case-insensitive search over identifying fields."""
    if not text:
        return True
    needle = text.lower()
    haystacks = [
        item.company_name,
        prospect.domain or "",
        prospect.website or "",
        item.next_action,
    ]
    return any(needle in h.lower() for h in haystacks)


def _matches_status(item: ProspectFollowUpItem, status_filter: Optional[str]) -> bool:
    """Apply status filter (Active / All / Closed / individual status)."""
    filt = (status_filter or STATUS_FILTER_ACTIVE).strip().upper()
    if filt == STATUS_FILTER_ALL:
        return True
    if filt == STATUS_FILTER_CLOSED:
        return item.workflow_status in _TERMINAL_STATUSES
    if filt == STATUS_FILTER_ACTIVE:
        return item.workflow_status not in _TERMINAL_STATUSES
    return item.workflow_status == filt


def _matches_priority(item: ProspectFollowUpItem, priority_filter: Optional[str]) -> bool:
    """Apply priority filter (All / individual priority)."""
    filt = (priority_filter or PRIORITY_FILTER_ALL).strip().upper()
    if filt == PRIORITY_FILTER_ALL:
        return True
    return item.priority == filt


def _matches_timing(item: ProspectFollowUpItem, timing_filter: Optional[str]) -> bool:
    """Apply timing filter (All / individual timing / Needs Attention)."""
    filt = (timing_filter or TIMING_FILTER_ALL).strip().upper()
    if filt == TIMING_FILTER_ALL:
        return True
    if filt == TIMING_FILTER_NEEDS_ATTENTION:
        return item.needs_attention
    return item.timing_state == filt


def _sort_key(item: ProspectFollowUpItem) -> tuple:
    """Deterministic sort key for the default queue view.

    Order:
        1. Timing bucket (overdue first, closed last)
        2. Priority (urgent first, low last)
        3. Next-action date (earlier first; missing dates sort last within bucket)
        4. Company name (case-insensitive)
        5. Prospect id (deterministic tie-breaker)
    """
    try:
        date_key = (
            date.fromisoformat(item.next_action_date)
            if item.next_action_date
            else date.max
        )
    except (TypeError, ValueError):
        date_key = date.max

    return (
        _TIMING_SORT_WEIGHT.get(item.timing_state, 99),
        _PRIORITY_SORT_WEIGHT.get(item.priority, 99),
        date_key,
        (item.company_name or "").lower(),
        item.prospect_id or "",
    )



# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ProspectFollowUpService:
    """Qt-free query service for the Prospect Follow-Up Queue.

    Derives items directly from the authoritative ProspectStore. Filtering and
    sorting are deterministic and read-only.
    """

    def __init__(self, store: ProspectStore) -> None:
        self._store = store

    @property
    def store(self) -> ProspectStore:
        """The authoritative ProspectStore backing this query service."""
        return self._store

    def list_items(
        self,
        *,
        today: Optional[Any] = None,
        status_filter: Optional[str] = None,
        priority_filter: Optional[str] = None,
        timing_filter: Optional[str] = None,
        search_text: Optional[str] = None,
        sort_mode: Optional[str] = None,
    ) -> List[ProspectFollowUpItem]:
        """Return derived follow-up items matching the requested filters.

        Defaults: active/non-terminal prospects, all priorities, all non-closed
        timing states, default deterministic sort.
        """
        prospects = self._load_prospects()
        items = [_build_item(p, today) for p in prospects]

        search = (search_text or "").strip()
        status = (status_filter or STATUS_FILTER_ACTIVE).strip().upper()
        priority = (priority_filter or PRIORITY_FILTER_ALL).strip().upper()
        timing = (timing_filter or TIMING_FILTER_ALL).strip().upper()

        # When both status and timing are at their defaults, exclude CLOSED rows.
        exclude_closed_by_default = (
            status == STATUS_FILTER_ACTIVE and timing == TIMING_FILTER_ALL
        )

        result = []
        for item, prospect in zip(items, prospects):
            if not _matches_status(item, status):
                continue
            if not _matches_priority(item, priority):
                continue
            if exclude_closed_by_default and item.timing_state == TIMING_CLOSED:
                continue
            if not _matches_timing(item, timing):
                continue
            if not _matches_search(item, prospect, search):
                continue
            result.append(item)

        if (sort_mode or SORT_MODE_DEFAULT) == SORT_MODE_DEFAULT:
            result.sort(key=_sort_key)
        return result

    def _load_prospects(self) -> List[Prospect]:
        """Load the authoritative snapshot once without clobbering injected memory."""
        self._store.load_or_empty()
        return self._store.list()

