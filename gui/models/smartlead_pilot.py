"""Pilot launch safety-harness models for narrowly scoped production pilots."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from gui.models.smartlead_publication import utc_now_iso

SMARTLEAD_PILOT_STATUS_DRAFT = "DRAFT"
SMARTLEAD_PILOT_STATUS_READY = "READY"
SMARTLEAD_PILOT_STATUS_ACTIVE = "ACTIVE"
SMARTLEAD_PILOT_STATUS_PAUSED = "PAUSED"
SMARTLEAD_PILOT_STATUS_COMPLETED = "COMPLETED"
SMARTLEAD_PILOT_STATUS_BLOCKED = "BLOCKED"
SMARTLEAD_PILOT_STATUS_ATTENTION_REQUIRED = "ATTENTION_REQUIRED"

SMARTLEAD_PILOT_HEALTH_HEALTHY = "HEALTHY"
SMARTLEAD_PILOT_HEALTH_WATCH = "WATCH"
SMARTLEAD_PILOT_HEALTH_ATTENTION_REQUIRED = "ATTENTION_REQUIRED"

SMARTLEAD_PILOT_EVENT_CREATED = "PILOT_CREATED"
SMARTLEAD_PILOT_EVENT_PREFLIGHT_PASSED = "PREFLIGHT_PASSED"
SMARTLEAD_PILOT_EVENT_ACTIVATION_REQUESTED = "ACTIVATION_REQUESTED"
SMARTLEAD_PILOT_EVENT_ACTIVATED = "ACTIVATED"
SMARTLEAD_PILOT_EVENT_STATUS_REFRESHED = "STATUS_REFRESHED"
SMARTLEAD_PILOT_EVENT_PAUSE_REQUESTED = "PAUSE_REQUESTED"
SMARTLEAD_PILOT_EVENT_PAUSED = "PAUSED"
SMARTLEAD_PILOT_EVENT_ATTENTION_REQUIRED = "ATTENTION_REQUIRED"
SMARTLEAD_PILOT_EVENT_REVIEW_COMPLETED = "REVIEW_COMPLETED"

SMARTLEAD_PILOT_PAUSE_RESULT_PAUSED = "PAUSED"
SMARTLEAD_PILOT_PAUSE_RESULT_ALREADY_PAUSED = "ALREADY_PAUSED"
SMARTLEAD_PILOT_PAUSE_RESULT_ATTENTION_REQUIRED = "ATTENTION_REQUIRED"
SMARTLEAD_PILOT_PAUSE_RESULT_BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class SmartleadPilotRecipient:
    prospect_id: str
    email: str
    remote_lead_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadPilotRecipient":
        raw = data if isinstance(data, dict) else {}
        return cls(
            prospect_id=str(raw.get("prospect_id") or ""),
            email=str(raw.get("email") or ""),
            remote_lead_id=str(raw.get("remote_lead_id") or ""),
        )


@dataclass(frozen=True)
class SmartleadPilotDefinition:
    pilot_id: str
    campaign_id: str
    campaign_name: str
    source_package_id: str
    source_handoff_path: str = ""
    recipients: tuple[SmartleadPilotRecipient, ...] = ()
    created_at: str = ""
    approved_at: str = ""
    activated_at: str = ""
    paused_at: str = ""
    completed_at: str = ""
    status: str = SMARTLEAD_PILOT_STATUS_DRAFT

    @property
    def recipient_count(self) -> int:
        return len(self.recipients)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["recipients"] = [item.to_dict() for item in self.recipients]
        return payload

    @classmethod
    def create(
        cls,
        *,
        campaign_id: str,
        campaign_name: str,
        source_package_id: str,
        source_handoff_path: str,
        recipients: list[SmartleadPilotRecipient],
    ) -> "SmartleadPilotDefinition":
        return cls(
            pilot_id=str(uuid4()),
            campaign_id=str(campaign_id or ""),
            campaign_name=str(campaign_name or ""),
            source_package_id=str(source_package_id or ""),
            source_handoff_path=str(source_handoff_path or ""),
            recipients=tuple(recipients),
            created_at=utc_now_iso(),
            status=SMARTLEAD_PILOT_STATUS_DRAFT,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadPilotDefinition":
        raw = data if isinstance(data, dict) else {}
        return cls(
            pilot_id=str(raw.get("pilot_id") or ""),
            campaign_id=str(raw.get("campaign_id") or ""),
            campaign_name=str(raw.get("campaign_name") or ""),
            source_package_id=str(raw.get("source_package_id") or ""),
            source_handoff_path=str(raw.get("source_handoff_path") or ""),
            recipients=tuple(SmartleadPilotRecipient.from_dict(item) for item in list(raw.get("recipients") or [])),
            created_at=str(raw.get("created_at") or ""),
            approved_at=str(raw.get("approved_at") or ""),
            activated_at=str(raw.get("activated_at") or ""),
            paused_at=str(raw.get("paused_at") or ""),
            completed_at=str(raw.get("completed_at") or ""),
            status=str(raw.get("status") or SMARTLEAD_PILOT_STATUS_DRAFT),
        )


@dataclass(frozen=True)
class SmartleadPilotMetrics:
    total_pilot_recipients: int = 0
    sent: int = 0
    not_sent: int = 0
    replied: int = 0
    bounced: int = 0
    opened: int = 0
    clicked: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadPilotMetrics":
        raw = data if isinstance(data, dict) else {}
        return cls(
            total_pilot_recipients=int(raw.get("total_pilot_recipients") or 0),
            sent=int(raw.get("sent") or 0),
            not_sent=int(raw.get("not_sent") or 0),
            replied=int(raw.get("replied") or 0),
            bounced=int(raw.get("bounced") or 0),
            opened=int(raw.get("opened") or 0),
            clicked=int(raw.get("clicked") or 0),
        )


@dataclass(frozen=True)
class SmartleadPilotRecipientStatus:
    prospect_id: str
    email: str
    remote_lead_id: str = ""
    remote_status: str = ""
    sent: bool = False
    replied: bool = False
    bounced: bool = False
    opened: bool = False
    clicked: bool = False
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadPilotRecipientStatus":
        raw = data if isinstance(data, dict) else {}
        return cls(
            prospect_id=str(raw.get("prospect_id") or ""),
            email=str(raw.get("email") or ""),
            remote_lead_id=str(raw.get("remote_lead_id") or ""),
            remote_status=str(raw.get("remote_status") or ""),
            sent=bool(raw.get("sent", False)),
            replied=bool(raw.get("replied", False)),
            bounced=bool(raw.get("bounced", False)),
            opened=bool(raw.get("opened", False)),
            clicked=bool(raw.get("clicked", False)),
            reasons=tuple(str(item or "") for item in list(raw.get("reasons") or [])),
        )


@dataclass(frozen=True)
class SmartleadPilotSnapshot:
    pilot_id: str
    campaign_id: str
    remote_campaign_status: str = ""
    health: str = SMARTLEAD_PILOT_HEALTH_WATCH
    last_checked_at: str = ""
    campaign_metrics: dict[str, Any] = field(default_factory=dict)
    pilot_metrics: SmartleadPilotMetrics = field(default_factory=SmartleadPilotMetrics)
    recipient_statuses: tuple[SmartleadPilotRecipientStatus, ...] = ()
    warnings: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pilot_metrics"] = self.pilot_metrics.to_dict()
        payload["recipient_statuses"] = [item.to_dict() for item in self.recipient_statuses]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadPilotSnapshot":
        raw = data if isinstance(data, dict) else {}
        return cls(
            pilot_id=str(raw.get("pilot_id") or ""),
            campaign_id=str(raw.get("campaign_id") or ""),
            remote_campaign_status=str(raw.get("remote_campaign_status") or ""),
            health=str(raw.get("health") or SMARTLEAD_PILOT_HEALTH_WATCH),
            last_checked_at=str(raw.get("last_checked_at") or ""),
            campaign_metrics=dict(raw.get("campaign_metrics") or {}),
            pilot_metrics=SmartleadPilotMetrics.from_dict(raw.get("pilot_metrics") if isinstance(raw, dict) else None),
            recipient_statuses=tuple(SmartleadPilotRecipientStatus.from_dict(item) for item in list(raw.get("recipient_statuses") or [])),
            warnings=tuple(str(item or "") for item in list(raw.get("warnings") or [])),
            reasons=tuple(str(item or "") for item in list(raw.get("reasons") or [])),
        )


@dataclass(frozen=True)
class SmartleadPilotEvent:
    event_id: str
    pilot_id: str
    event_type: str
    occurred_at: str
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(cls, *, pilot_id: str, event_type: str, message: str = "", details: dict[str, Any] | None = None) -> "SmartleadPilotEvent":
        return cls(
            event_id=str(uuid4()),
            pilot_id=str(pilot_id or ""),
            event_type=str(event_type or ""),
            occurred_at=utc_now_iso(),
            message=str(message or ""),
            details=dict(details or {}),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadPilotEvent":
        raw = data if isinstance(data, dict) else {}
        return cls(
            event_id=str(raw.get("event_id") or ""),
            pilot_id=str(raw.get("pilot_id") or ""),
            event_type=str(raw.get("event_type") or ""),
            occurred_at=str(raw.get("occurred_at") or ""),
            message=str(raw.get("message") or ""),
            details=dict(raw.get("details") or {}),
        )


@dataclass(frozen=True)
class SmartleadPilotRun:
    definition: SmartleadPilotDefinition
    snapshot: SmartleadPilotSnapshot | None = None
    events: tuple[SmartleadPilotEvent, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "definition": self.definition.to_dict(),
            "snapshot": self.snapshot.to_dict() if self.snapshot is not None else None,
            "events": [item.to_dict() for item in self.events],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SmartleadPilotRun":
        raw = data if isinstance(data, dict) else {}
        snapshot = raw.get("snapshot") if isinstance(raw.get("snapshot"), dict) else None
        return cls(
            definition=SmartleadPilotDefinition.from_dict(raw.get("definition") if isinstance(raw.get("definition"), dict) else None),
            snapshot=SmartleadPilotSnapshot.from_dict(snapshot) if snapshot is not None else None,
            events=tuple(SmartleadPilotEvent.from_dict(item) for item in list(raw.get("events") or [])),
        )


@dataclass(frozen=True)
class SmartleadPilotCheck:
    name: str
    passed: bool
    message: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SmartleadPilotPreflightResult:
    success: bool
    status: str
    message: str
    pilot: SmartleadPilotDefinition | None = None
    checks: tuple[SmartleadPilotCheck, ...] = ()
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "pilot": self.pilot.to_dict() if self.pilot is not None else None,
            "checks": [item.to_dict() for item in self.checks],
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class SmartleadPilotActivationResult:
    success: bool
    status: str
    message: str
    pilot: SmartleadPilotDefinition | None = None
    dry_run: bool = True
    activation_delegated: bool = False
    activation_result: dict[str, Any] | None = None
    expected_pause_target: str = ""
    expected_monitor_targets: tuple[str, ...] = ()
    checks: tuple[SmartleadPilotCheck, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "pilot": self.pilot.to_dict() if self.pilot is not None else None,
            "dry_run": self.dry_run,
            "activation_delegated": self.activation_delegated,
            "activation_result": dict(self.activation_result or {}),
            "expected_pause_target": self.expected_pause_target,
            "expected_monitor_targets": list(self.expected_monitor_targets),
            "checks": [item.to_dict() for item in self.checks],
        }


@dataclass(frozen=True)
class SmartleadPilotPauseResult:
    success: bool
    status: str
    message: str
    pilot: SmartleadPilotDefinition | None = None
    remote_status: str = ""
    attention_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "pilot": self.pilot.to_dict() if self.pilot is not None else None,
            "remote_status": self.remote_status,
            "attention_required": self.attention_required,
        }