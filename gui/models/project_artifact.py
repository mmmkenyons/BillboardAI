"""Generic artifact model for a BillboardAI project (Sprint 3A).

An artifact represents a generated file (or other tangible output) owned by a
project. Artifact types are extensible — this sprint ships ``artwork`` and
``mockup``. An artifact records which concept produced it, which physical
scene / composition family was used, where the file lives, its pixel size,
and when it was generated.

Serialization follows the forward-compatible ``to_dict`` / ``from_dict``
pattern used across the engine models: unknown persisted fields are ignored
and missing optional fields receive safe defaults.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

# Initial, extensible artifact types.
ARTIFACT_TYPE_ARTWORK = "artwork"
ARTIFACT_TYPE_MOCKUP = "mockup"
ARTIFACT_TYPES = (ARTIFACT_TYPE_ARTWORK, ARTIFACT_TYPE_MOCKUP)


@dataclass
class ProjectArtifact:
    """A generated artifact registered against a project."""

    artifact_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    artifact_type: str = ""  # "artwork" | "mockup" | extensible
    path: str = ""
    concept_id: str = ""
    scene_template: str = ""
    composition_family: str = ""
    width: int = 0
    height: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "path": self.path,
            "concept_id": self.concept_id,
            "scene_template": self.scene_template,
            "composition_family": self.composition_family,
            "width": self.width,
            "height": self.height,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ProjectArtifact":
        if not isinstance(data, dict):
            data = {}
        created_at = _parse_datetime(data.get("created_at"))
        return cls(
            artifact_id=str(data.get("artifact_id") or str(uuid.uuid4())),
            artifact_type=str(data.get("artifact_type") or ""),
            path=str(data.get("path") or ""),
            concept_id=str(data.get("concept_id") or ""),
            scene_template=str(data.get("scene_template") or ""),
            composition_family=str(data.get("composition_family") or ""),
            width=int(data.get("width", 0) or 0),
            height=int(data.get("height", 0) or 0),
            created_at=created_at,
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