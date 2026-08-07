"""Data model for a single billboard mockup concept within a project."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MockupConcept:
    """A single generated concept within a project.

    Full generation ("Generate New Concept") creates a new concept with
    source_concept_id and sequential name (Concept 001, etc.). In-place
    edits update the selected concept and set ``user_modified`` to True.
    Backward compatible with existing project.json (defaults for new fields).
    """

    id: str
    image_path: str
    template: str

    headline: str
    cta: str

    quality_score: float
    company_name: str = ""

    created_at: datetime = field(default_factory=datetime.now)

    # Whether the user has manually modified this concept's content.
    user_modified: bool = False
    # Whether this concept is currently selected in the gallery.
    selected: bool = False

    # Lineage for "Generate New Concept" / Duplicate (Sprint 4B Phase E1).
    source_concept_id: str | None = None
    # Human-readable sequential name (e.g. "Concept 001").
    name: str = ""

    # Additional metadata from the engine.
    extra: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        image_path: str,
        template: str,
        headline: str,
        cta: str,
        quality_score: float,
        company_name: str = "",
        name: str = "",
        source_concept_id: str | None = None,
        **extra: object,
    ) -> "MockupConcept":
        """Create a new concept with a fresh UUID.
        
        Sequential name ("Concept 001") is typically set by Project.create_concept().
        """
        return cls(
            id=str(uuid.uuid4()),
            image_path=image_path,
            template=template,
            headline=headline,
            cta=cta,
            quality_score=quality_score,
            company_name=company_name,
            name=name,
            source_concept_id=source_concept_id,
            extra=dict(extra),
        )

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON persistence.
        
        Includes new fields for Sprint 4B Phase E1; old project.json loads gracefully.
        """
        return {
            "id": self.id,
            "image_path": self.image_path,
            "template": self.template,
            "headline": self.headline,
            "cta": self.cta,
            "quality_score": self.quality_score,
            "company_name": self.company_name,
            "created_at": self.created_at.isoformat(),
            "user_modified": self.user_modified,
            "selected": self.selected,
            "source_concept_id": self.source_concept_id,
            "name": self.name,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MockupConcept":
        """Deserialize from a plain dict (e.g. loaded from project.json).
        
        Backward compatible: new fields default to None/"" for old files.
        """
        return cls(
            id=data["id"],
            image_path=data["image_path"],
            template=data["template"],
            headline=data["headline"],
            cta=data["cta"],
            quality_score=data.get("quality_score", 0),
            company_name=data.get("company_name", ""),
            created_at=datetime.fromisoformat(
                data.get("created_at", datetime.now().isoformat())
            ),
            user_modified=data.get("user_modified", False),
            selected=data.get("selected", False),
            source_concept_id=data.get("source_concept_id"),
            name=data.get("name", ""),
            extra=data.get("extra", {}),
        )

    def apply_updates(self, **fields: object) -> list[str]:
        """Apply in-place field updates. Returns names of fields that changed.

        Always sets ``user_modified`` when any content field changes.
        Unknown keys are ignored. Supports new Sprint 4B fields.
        """
        allowed = {
            "image_path",
            "template",
            "headline",
            "cta",
            "quality_score",
            "company_name",
            "selected",
            "extra",
            "name",
            "source_concept_id",
        }
        changed: list[str] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if getattr(self, key) != value:
                setattr(self, key, value)
                changed.append(key)
        content_keys = {"image_path", "template", "headline", "cta", "company_name", "name"}
        if any(key in content_keys for key in changed):
            self.user_modified = True
        return changed

    def display_name(self) -> str:
        """Human-readable name for gallery/toolbar (falls back to sequential name)."""
        return self.name or f"Concept {self.id[:8]}"


