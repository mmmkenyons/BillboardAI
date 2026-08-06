"""Data model for a single billboard mockup concept within a project."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MockupConcept:
    """A single generated concept within a project.

    Each time the user generates a mockup, a new concept is created and
    added to the project. The concept is immutable once created (except
    for the ``selected`` flag); if the user modifies content, a new
    concept is generated rather than editing in place.
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
        **extra: object,
    ) -> "MockupConcept":
        """Create a new concept with a fresh UUID."""
        return cls(
            id=str(uuid.uuid4()),
            image_path=image_path,
            template=template,
            headline=headline,
            cta=cta,
            quality_score=quality_score,
            company_name=company_name,
            extra=dict(extra),
        )

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON persistence."""
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
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MockupConcept":
        """Deserialize from a plain dict (e.g. loaded from project.json)."""
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
            extra=data.get("extra", {}),
        )
