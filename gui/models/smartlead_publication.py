"""Publication models for Smartlead dry-run and live lead upload orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

SMARTLEAD_PUBLISH_MODE_DRY_RUN = "DRY_RUN"
SMARTLEAD_PUBLISH_MODE_LIVE = "LIVE"

SMARTLEAD_PUBLISH_STATUS_PENDING = "PENDING"
SMARTLEAD_PUBLISH_STATUS_SKIPPED = "SKIPPED"
SMARTLEAD_PUBLISH_STATUS_SUCCEEDED = "SUCCEEDED"
SMARTLEAD_PUBLISH_STATUS_FAILED = "FAILED"
SMARTLEAD_PUBLISH_STATUS_NOT_ATTEMPTED = "NOT_ATTEMPTED"

SMARTLEAD_TARGET_MODE_EXISTING = "EXISTING_CAMPAIGN"
SMARTLEAD_TARGET_MODE_CREATE_DRAFT = "CREATE_DRAFT_CAMPAIGN"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SmartleadCampaignSummary:
    campaign_id: str
    name: str
    status: str
    created_at: str = ""


@dataclass(frozen=True)
class SmartleadCampaignDetails:
    campaign_id: str
    name: str
    status: str
    created_at: str = ""
    updated_at: str = ""
    client_id: str = ""
    sequence_count: int = 0
    email_account_count: int = 0
    raw_sequence_configured: bool = False
    raw_sender_accounts_configured: bool = False


@dataclass(frozen=True)
class SmartleadConnectionTestResult:
    connected: bool
    status: str
    message: str


@dataclass(frozen=True)
class SmartleadPublishTarget:
    mode: str = SMARTLEAD_TARGET_MODE_EXISTING
    campaign_id: str = ""
    campaign_name: str = ""
    create_name: str = ""


@dataclass(frozen=True)
class SmartleadPublishLead:
    publication_key: str
    prospect_id: str
    email: str
    first_name: str = ""
    company: str = ""
    custom_fields: dict[str, str] = field(default_factory=dict)
    local_mockup_path: str = ""
    source_row: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SmartleadPublishedLead:
    publication_key: str
    prospect_id: str
    email: str
    status: str
    remote_lead_id: str = ""
    published_at: str = ""
    campaign_id: str = ""
    error_code: str = ""
    reason: str = ""
    batch_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadPublishedLead":
        raw = data if isinstance(data, dict) else {}
        return cls(
            publication_key=str(raw.get("publication_key") or ""),
            prospect_id=str(raw.get("prospect_id") or ""),
            email=str(raw.get("email") or ""),
            status=str(raw.get("status") or SMARTLEAD_PUBLISH_STATUS_NOT_ATTEMPTED),
            remote_lead_id=str(raw.get("remote_lead_id") or ""),
            published_at=str(raw.get("published_at") or ""),
            campaign_id=str(raw.get("campaign_id") or ""),
            error_code=str(raw.get("error_code") or ""),
            reason=str(raw.get("reason") or ""),
            batch_index=int(raw.get("batch_index") or 0),
        )


@dataclass(frozen=True)
class SmartleadPublicationReceipt:
    publication_id: str
    created_at: str
    source_package_id: str
    source_package_directory: str
    handoff_manifest_path: str
    campaign_id: str
    campaign_name: str
    target_mode: str
    mode: str
    total_candidates: int
    attempted: int
    succeeded: int
    skipped: int
    failed: int
    lead_results: tuple[SmartleadPublishedLead, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        source_package_id: str,
        source_package_directory: str,
        handoff_manifest_path: str,
        campaign_id: str,
        campaign_name: str,
        target_mode: str,
        mode: str,
        total_candidates: int,
        lead_results: list[SmartleadPublishedLead],
    ) -> "SmartleadPublicationReceipt":
        attempted = sum(1 for item in lead_results if item.status in {SMARTLEAD_PUBLISH_STATUS_SUCCEEDED, SMARTLEAD_PUBLISH_STATUS_FAILED})
        succeeded = sum(1 for item in lead_results if item.status == SMARTLEAD_PUBLISH_STATUS_SUCCEEDED)
        skipped = sum(1 for item in lead_results if item.status == SMARTLEAD_PUBLISH_STATUS_SKIPPED)
        failed = sum(1 for item in lead_results if item.status == SMARTLEAD_PUBLISH_STATUS_FAILED)
        return cls(
            publication_id=str(uuid4()),
            created_at=utc_now_iso(),
            source_package_id=source_package_id,
            source_package_directory=source_package_directory,
            handoff_manifest_path=handoff_manifest_path,
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            target_mode=target_mode,
            mode=mode,
            total_candidates=total_candidates,
            attempted=attempted,
            succeeded=succeeded,
            skipped=skipped,
            failed=failed,
            lead_results=tuple(lead_results),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["lead_results"] = [item.to_dict() for item in self.lead_results]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadPublicationReceipt":
        raw = data if isinstance(data, dict) else {}
        return cls(
            publication_id=str(raw.get("publication_id") or ""),
            created_at=str(raw.get("created_at") or ""),
            source_package_id=str(raw.get("source_package_id") or ""),
            source_package_directory=str(raw.get("source_package_directory") or ""),
            handoff_manifest_path=str(raw.get("handoff_manifest_path") or ""),
            campaign_id=str(raw.get("campaign_id") or ""),
            campaign_name=str(raw.get("campaign_name") or ""),
            target_mode=str(raw.get("target_mode") or SMARTLEAD_TARGET_MODE_EXISTING),
            mode=str(raw.get("mode") or SMARTLEAD_PUBLISH_MODE_DRY_RUN),
            total_candidates=int(raw.get("total_candidates") or 0),
            attempted=int(raw.get("attempted") or 0),
            succeeded=int(raw.get("succeeded") or 0),
            skipped=int(raw.get("skipped") or 0),
            failed=int(raw.get("failed") or 0),
            lead_results=tuple(SmartleadPublishedLead.from_dict(item) for item in list(raw.get("lead_results") or [])),
        )


@dataclass(frozen=True)
class SmartleadPublishResult:
    success: bool
    message: str
    mode: str
    target_mode: str
    dry_run: bool
    campaign_id: str = ""
    campaign_name: str = ""
    total_candidates: int = 0
    eligible: int = 0
    blocked_or_conflict: int = 0
    attempted: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    batches_planned: int = 0
    batches_attempted: int = 0
    receipt: SmartleadPublicationReceipt | None = None
    payload_preview: tuple[dict[str, Any], ...] = ()
    lead_results: tuple[SmartleadPublishedLead, ...] = ()