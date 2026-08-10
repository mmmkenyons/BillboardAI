"""Lightweight project history / audit trail model (Sprint 3A).

A history entry is a meaningful user/project activity record (project_created,
research_completed, concepts_generated, concept_selected, artwork_generated,
mockup_generated, override_changed, ...). It is an audit trail — not undo/redo
and not a log of every internal function call.

Serialization follows the forward-compatible ``to_dict`` / ``from_dict``
pattern: unknown persisted fields are ignored and missing optional fields
receive safe defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

# Canonical event types (extensible).
EVENT_PROJECT_CREATED = "project_created"
EVENT_RESEARCH_COMPLETED = "research_completed"
EVENT_CONCEPTS_GENERATED = "concepts_generated"
EVENT_CONCEPT_SELECTED = "concept_selected"
EVENT_ARTWORK_GENERATED = "artwork_generated"
EVENT_MOCKUP_GENERATED = "mockup_generated"
EVENT_OVERRIDE_CHANGED = "override_changed"


@dataclass
class ProjectHistory:
    """A single project history / audit entry."""

    timestamp: datetime = field(default_factory=datetime.now)
    event_type: str = ""
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "message": self.message,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ProjectHistory":
        if not isinstance(data, dict):
            data = {}
        timestamp = _parse_datetime(data.get("timestamp"))
        return cls(
            timestamp=timestamp,
            event_type=str(data.get("event_type") or ""),
            message=str(data.get("message") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


def _parse_datetime(value: object) -> datetime:
    """Parse an ISO timestamp, falling back to now on malformed/empty input."""
    if value:
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            pass
    return datetime.now()