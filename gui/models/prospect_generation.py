"""Durable prospect-driven mockup generation job models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

JOB_STATUS_QUEUED = "QUEUED"
JOB_STATUS_RUNNING = "RUNNING"
JOB_STATUS_SUCCEEDED = "SUCCEEDED"
JOB_STATUS_FAILED = "FAILED"

JOB_STATUSES = (
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    JOB_STATUS_FAILED,
)


def _job_id() -> str:
    return str(uuid.uuid4())


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


@dataclass
class GenerationEligibility:
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    resolved_template: str = ""
    website: str = ""


@dataclass
class OpportunityGenerationContext:
    opportunity_id: str = ""
    location_id: str = ""
    placement_id: str = ""
    scene_template: str = ""
    retailer_name: str = ""
    location_name: str = ""
    store_number: str = ""
    city: str = ""
    state: str = ""
    placement_name: str = ""
    placement_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "location_id": self.location_id,
            "placement_id": self.placement_id,
            "scene_template": self.scene_template,
            "retailer_name": self.retailer_name,
            "location_name": self.location_name,
            "store_number": self.store_number,
            "city": self.city,
            "state": self.state,
            "placement_name": self.placement_name,
            "placement_type": self.placement_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OpportunityGenerationContext":
        raw = data if isinstance(data, dict) else {}
        return cls(
            opportunity_id=str(raw.get("opportunity_id") or ""),
            location_id=str(raw.get("location_id") or ""),
            placement_id=str(raw.get("placement_id") or ""),
            scene_template=str(raw.get("scene_template") or ""),
            retailer_name=str(raw.get("retailer_name") or ""),
            location_name=str(raw.get("location_name") or ""),
            store_number=str(raw.get("store_number") or ""),
            city=str(raw.get("city") or ""),
            state=str(raw.get("state") or ""),
            placement_name=str(raw.get("placement_name") or ""),
            placement_type=str(raw.get("placement_type") or ""),
        )


@dataclass
class ProspectGenerationJob:
    id: str = field(default_factory=_job_id)
    prospect_id: str = ""
    website: str = ""
    template: str = ""
    status: str = JOB_STATUS_QUEUED
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    project_id: str = ""
    result_path: str = ""
    error: str = ""
    output_root: str = ""
    project_root: str = ""
    opportunity_id: str = ""
    location_id: str = ""
    placement_id: str = ""
    opportunity_context: OpportunityGenerationContext | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prospect_id": self.prospect_id,
            "website": self.website,
            "template": self.template,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "project_id": self.project_id,
            "result_path": self.result_path,
            "error": self.error,
            "output_root": self.output_root,
            "project_root": self.project_root,
            "opportunity_id": self.opportunity_id,
            "location_id": self.location_id,
            "placement_id": self.placement_id,
            "opportunity_context": self.opportunity_context.to_dict() if self.opportunity_context else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProspectGenerationJob":
        raw = data if isinstance(data, dict) else {}
        status = str(raw.get("status") or JOB_STATUS_QUEUED)
        if status not in JOB_STATUSES:
            status = JOB_STATUS_QUEUED
        return cls(
            id=str(raw.get("id") or _job_id()),
            prospect_id=str(raw.get("prospect_id") or ""),
            website=str(raw.get("website") or ""),
            template=str(raw.get("template") or ""),
            status=status,
            created_at=_parse_dt(raw.get("created_at")) or datetime.now(),
            started_at=_parse_dt(raw.get("started_at")),
            completed_at=_parse_dt(raw.get("completed_at")),
            project_id=str(raw.get("project_id") or ""),
            result_path=str(raw.get("result_path") or ""),
            error=str(raw.get("error") or ""),
            output_root=str(raw.get("output_root") or ""),
            project_root=str(raw.get("project_root") or ""),
            opportunity_id=str(raw.get("opportunity_id") or ""),
            location_id=str(raw.get("location_id") or ""),
            placement_id=str(raw.get("placement_id") or ""),
            opportunity_context=(
                OpportunityGenerationContext.from_dict(raw.get("opportunity_context"))
                if isinstance(raw.get("opportunity_context"), dict)
                else None
            ),
            metadata=dict(raw.get("metadata") or {}),
        )