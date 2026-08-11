"""Sprint 5I Prospect Pipeline / Command Center service (Qt-free).

Derives portfolio-level pipeline summaries and per-stage drill-down rows from the
authoritative ProspectStore. This module is read-only with respect to persisted
prospect data and intentionally reuses Sprint 5H timing derivation semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from gui.models.prospect import (
    ACTIVE_WORKFLOW_STATUSES,
    CLOSED_WORKFLOW_STATUSES,
    PIPELINE_WORKFLOW_ORDER,
    WORKFLOW_STATUSES,
)
from gui.models.prospect_store import ProspectStore
from gui.services.prospect_follow_up import (
    TIMING_DUE_TODAY,
    TIMING_OVERDUE,
    ProspectFollowUpItem,
    ProspectFollowUpService,
    _build_item,
    _sort_key,
)


@dataclass(frozen=True)
class PipelineSummary:
    """Compact derived portfolio-level pipeline metrics."""

    total_prospects: int = 0
    active_prospects: int = 0
    closed_prospects: int = 0
    needs_attention_prospects: int = 0
    overdue_prospects: int = 0
    due_today_prospects: int = 0
    urgent_prospects: int = 0
    won_prospects: int = 0
    lost_prospects: int = 0
    not_interested_prospects: int = 0
    stage_counts: Dict[str, int] = field(default_factory=dict)


class ProspectPipelineService:
    """Qt-free query service for the Sales Pipeline / Command Center."""

    def __init__(self, store: ProspectStore) -> None:
        self._store = store
        self._follow_up = ProspectFollowUpService(store)

    @property
    def store(self) -> ProspectStore:
        return self._store

    @property
    def stage_order(self) -> tuple:
        return PIPELINE_WORKFLOW_ORDER

    def summary(self, *, today: Optional[Any] = None) -> PipelineSummary:
        items = self._load_items(today=today)
        stage_counts = {status: 0 for status in PIPELINE_WORKFLOW_ORDER}
        for item in items:
            status = item.workflow_status if item.workflow_status in WORKFLOW_STATUSES else PIPELINE_WORKFLOW_ORDER[0]
            stage_counts[status] = stage_counts.get(status, 0) + 1

        active_items = [item for item in items if item.workflow_status in ACTIVE_WORKFLOW_STATUSES]
        closed_items = [item for item in items if item.workflow_status in CLOSED_WORKFLOW_STATUSES]
        overdue_items = [item for item in active_items if item.timing_state == TIMING_OVERDUE]
        due_today_items = [item for item in active_items if item.timing_state == TIMING_DUE_TODAY]
        urgent_items = [item for item in active_items if item.priority == "URGENT"]
        needs_attention = [
            item for item in active_items
            if item.timing_state in (TIMING_OVERDUE, TIMING_DUE_TODAY) or item.priority == "URGENT"
        ]

        unique_needs_attention = {item.prospect_id for item in needs_attention if item.prospect_id}

        return PipelineSummary(
            total_prospects=len(items),
            active_prospects=len(active_items),
            closed_prospects=len(closed_items),
            needs_attention_prospects=len(unique_needs_attention),
            overdue_prospects=len(overdue_items),
            due_today_prospects=len(due_today_items),
            urgent_prospects=len(urgent_items),
            won_prospects=stage_counts.get("WON", 0),
            lost_prospects=stage_counts.get("LOST", 0),
            not_interested_prospects=stage_counts.get("NOT_INTERESTED", 0),
            stage_counts=stage_counts,
        )

    def list_stage(
        self,
        workflow_status: str,
        *,
        today: Optional[Any] = None,
    ) -> List[ProspectFollowUpItem]:
        stage = (workflow_status or "").strip().upper()
        if stage not in WORKFLOW_STATUSES:
            raise ValueError(f"Unknown workflow status: {workflow_status}")
        return [item for item in self._load_items(today=today) if item.workflow_status == stage]

    def _load_items(self, *, today: Optional[Any] = None) -> List[ProspectFollowUpItem]:
        prospects = self._follow_up._load_prospects()
        items = [_build_item(prospect, today) for prospect in prospects]
        items.sort(key=_sort_key)
        return items