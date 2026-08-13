"""Derived Smartlead launch-control and reconciliation models (Sprint 5S).

These models represent BillboardAI's local, read-only understanding of whether a
campaign is safe to hand off for an explicit future activation action. They do
not represent Smartlead's own activation state and are never user-editable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

SMARTLEAD_LAUNCH_STATUS_NOT_READY = "NOT_READY"
SMARTLEAD_LAUNCH_STATUS_READY = "READY"
SMARTLEAD_LAUNCH_STATUS_PARTIAL = "PARTIAL"
SMARTLEAD_LAUNCH_STATUS_BLOCKED = "BLOCKED"
SMARTLEAD_LAUNCH_STATUS_RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"

SMARTLEAD_RECONCILE_MATCHED = "MATCHED"
SMARTLEAD_RECONCILE_LOCAL_ONLY = "LOCAL_ONLY"
SMARTLEAD_RECONCILE_REMOTE_ONLY = "REMOTE_ONLY"
SMARTLEAD_RECONCILE_MISMATCH = "MISMATCH"
SMARTLEAD_RECONCILE_FAILED = "FAILED"
SMARTLEAD_RECONCILE_PENDING = "PENDING"
SMARTLEAD_RECONCILE_DUPLICATE_REMOTE = "DUPLICATE_REMOTE"


@dataclass(frozen=True)
class SmartleadReconciliationRow:
    campaign_id: str
    publication_key: str
    prospect_id: str
    email: str
    local_status: str = ""
    remote_status: str = ""
    classification: str = SMARTLEAD_RECONCILE_PENDING
    remote_lead_id: str = ""
    duplicate_remote_lead_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SmartleadReconciliationResult:
    campaign_id: str
    campaign_name: str = ""
    remote_campaign_found: bool = False
    checked_at: str = ""
    matched: int = 0
    local_only: int = 0
    remote_only: int = 0
    mismatched: int = 0
    failed: int = 0
    pending: int = 0
    duplicate_remote: int = 0
    reconciliation_required: bool = False
    rows: tuple[SmartleadReconciliationRow, ...] = ()
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rows"] = [row.to_dict() for row in self.rows]
        return payload


@dataclass(frozen=True)
class SmartleadLaunchReadiness:
    campaign_id: str
    campaign_name: str = ""
    status: str = SMARTLEAD_LAUNCH_STATUS_NOT_READY
    total_expected: int = 0
    published_count: int = 0
    failed_count: int = 0
    pending_count: int = 0
    duplicate_count: int = 0
    missing_asset_count: int = 0
    sequence_ready: bool = False
    remote_campaign_found: bool = False
    reconciliation_required: bool = False
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)