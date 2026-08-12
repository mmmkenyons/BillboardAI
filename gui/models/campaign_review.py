"""Narrow persisted and composed models for campaign review decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

CAMPAIGN_REVIEW_STATUS_APPROVED = "APPROVED"
CAMPAIGN_REVIEW_STATUS_EXCLUDED = "EXCLUDED"
CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"

CAMPAIGN_REVIEW_STATUSES: tuple[str, ...] = (
    CAMPAIGN_REVIEW_STATUS_APPROVED,
    CAMPAIGN_REVIEW_STATUS_EXCLUDED,
    CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW,
)


def _clean(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class CampaignReviewDecision:
    prospect_id: str
    status: str = CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW
    note: str = ""
    reviewed_at: str = ""

    def to_dict(self) -> dict[str, str]:
        data = asdict(self)
        return {key: str(value or "") for key, value in data.items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CampaignReviewDecision":
        raw = data if isinstance(data, dict) else {}
        status = _clean(raw.get("status")) or CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW
        if status not in CAMPAIGN_REVIEW_STATUSES:
            status = CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW
        return cls(
            prospect_id=_clean(raw.get("prospect_id")),
            status=status,
            note=_clean(raw.get("note")),
            reviewed_at=_clean(raw.get("reviewed_at")),
        )


@dataclass(frozen=True)
class CampaignReviewRow:
    prospect_id: str
    company: str = ""
    email: str = ""
    contact_name: str = ""
    city: str = ""
    state: str = ""
    category: str = ""
    website: str = ""
    email_subject: str = ""
    email_body: str = ""
    mockup_path: str = ""
    opportunity_display: str = ""
    creative_summary: str = ""
    placement_name: str = ""
    placement_type: str = ""
    technical_status: str = ""
    technical_reasons: tuple[str, ...] = ()
    technical_warnings: tuple[str, ...] = ()
    review_status: str = CAMPAIGN_REVIEW_STATUS_NEEDS_REVIEW
    review_note: str = ""
    reviewed_at: str = ""
    generation_job_id: str = ""
    project_id: str = ""

    @property
    def packageable(self) -> bool:
        return self.review_status == CAMPAIGN_REVIEW_STATUS_APPROVED and self.technical_status in {"READY", "WARNING"}


def reviewed_now() -> str:
    return datetime.now(timezone.utc).isoformat()