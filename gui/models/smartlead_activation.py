"""Explicit Smartlead campaign activation models and durable receipt payloads.

Sprint 5T. Activation is a consequential external write and therefore requires
its own narrow, auditable result and receipt types. No secrets are ever stored.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from gui.models.smartlead_publication import utc_now_iso

SMARTLEAD_ACTIVATION_MODE_DRY_RUN = "DRY_RUN"
SMARTLEAD_ACTIVATION_MODE_LIVE = "LIVE"

SMARTLEAD_ACTIVATION_RESULT_ACTIVATED = "ACTIVATED"
SMARTLEAD_ACTIVATION_RESULT_ALREADY_ACTIVE = "ALREADY_ACTIVE"
SMARTLEAD_ACTIVATION_RESULT_BLOCKED = "BLOCKED"
SMARTLEAD_ACTIVATION_RESULT_FAILED = "FAILED"
SMARTLEAD_ACTIVATION_RESULT_DRY_RUN = "DRY_RUN"
SMARTLEAD_ACTIVATION_RESULT_RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


@dataclass(frozen=True)
class SmartleadActivationReceipt:
    activation_id: str
    campaign_id: str
    campaign_name: str
    requested_at: str
    completed_at: str
    source_package_id: str = ""
    prior_remote_status: str = ""
    resulting_remote_status: str = ""
    readiness_status: str = ""
    published_count: int = 0
    sequence_ready: bool = False
    sender_account_count: int = 0
    reconciliation_status: str = ""
    status: str = SMARTLEAD_ACTIVATION_RESULT_FAILED
    message: str = ""
    confirmed: bool = False
    mode: str = SMARTLEAD_ACTIVATION_MODE_DRY_RUN

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        *,
        campaign_id: str,
        campaign_name: str,
        source_package_id: str,
        prior_remote_status: str,
        resulting_remote_status: str,
        readiness_status: str,
        published_count: int,
        sequence_ready: bool,
        sender_account_count: int,
        reconciliation_status: str,
        status: str,
        message: str,
        confirmed: bool,
        mode: str,
    ) -> "SmartleadActivationReceipt":
        now = utc_now_iso()
        return cls(
            activation_id=str(uuid4()),
            campaign_id=str(campaign_id or ""),
            campaign_name=str(campaign_name or ""),
            requested_at=now,
            completed_at=now,
            source_package_id=str(source_package_id or ""),
            prior_remote_status=str(prior_remote_status or ""),
            resulting_remote_status=str(resulting_remote_status or ""),
            readiness_status=str(readiness_status or ""),
            published_count=int(published_count or 0),
            sequence_ready=bool(sequence_ready),
            sender_account_count=int(sender_account_count or 0),
            reconciliation_status=str(reconciliation_status or ""),
            status=str(status or SMARTLEAD_ACTIVATION_RESULT_FAILED),
            message=str(message or ""),
            confirmed=bool(confirmed),
            mode=str(mode or SMARTLEAD_ACTIVATION_MODE_DRY_RUN),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadActivationReceipt":
        raw = data if isinstance(data, dict) else {}
        return cls(
            activation_id=str(raw.get("activation_id") or ""),
            campaign_id=str(raw.get("campaign_id") or ""),
            campaign_name=str(raw.get("campaign_name") or ""),
            requested_at=str(raw.get("requested_at") or ""),
            completed_at=str(raw.get("completed_at") or ""),
            source_package_id=str(raw.get("source_package_id") or ""),
            prior_remote_status=str(raw.get("prior_remote_status") or ""),
            resulting_remote_status=str(raw.get("resulting_remote_status") or ""),
            readiness_status=str(raw.get("readiness_status") or ""),
            published_count=int(raw.get("published_count") or 0),
            sequence_ready=bool(raw.get("sequence_ready", False)),
            sender_account_count=int(raw.get("sender_account_count") or 0),
            reconciliation_status=str(raw.get("reconciliation_status") or ""),
            status=str(raw.get("status") or SMARTLEAD_ACTIVATION_RESULT_FAILED),
            message=str(raw.get("message") or ""),
            confirmed=bool(raw.get("confirmed", False)),
            mode=str(raw.get("mode") or SMARTLEAD_ACTIVATION_MODE_DRY_RUN),
        )


@dataclass(frozen=True)
class SmartleadActivationResult:
    success: bool
    status: str
    message: str
    mode: str = SMARTLEAD_ACTIVATION_MODE_DRY_RUN
    dry_run: bool = True
    campaign_id: str = ""
    campaign_name: str = ""
    source_package_id: str = ""
    prior_remote_status: str = ""
    resulting_remote_status: str = ""
    readiness_status: str = ""
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    intended_request: dict[str, Any] | None = None
    receipt: SmartleadActivationReceipt | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.receipt is not None:
            payload["receipt"] = self.receipt.to_dict()
        return payload