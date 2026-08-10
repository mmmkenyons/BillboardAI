"""Sprint 3B project workspace service (pure Python, Qt-free).

This module owns the DOMAIN/BUSINESS logic for the project workspace so it is
testable without a visible desktop: listing/opening projects, AdConcept
selection, user overrides, status changes, and mockup generation from a saved
AdConcept. It never imports Qt and never touches widgets.

Key design decisions (documented for Sprint 3B):

- **AdConcept is authoritative.** The workspace CONCEPTS tab reads the
  structured creative state persisted in ``Project.ad_concepts`` (hydrated to
  ``engine.ad_concept.AdConcept``). ``MockupConcept`` remains the legacy
  HomePage / result view model and is left untouched — no third model exists.
- **Overrides never mutate the source.** User headline/CTA overrides live only
  in ``Project.user_overrides``. ``build_render_concept`` returns a *copy* of
  the AdConcept (via ``dataclasses.replace``) with overrides applied; the
  persisted source AdConcept, BrandProfile, and MessageStrategy are never
  edited.
- **Reopening is persistence, not regeneration.** ``open_project`` only loads
  from ``ProjectStore``; it never runs WebsiteScraper / BrandProfileBuilder /
  MessageStrategyEngine / AdConceptEngine.
"""

from __future__ import annotations

import dataclasses
import logging
import os
from typing import Dict, List, Optional

from engine.ad_concept import AdConcept
from engine.brand_profile import BrandProfile
from engine.layout import CreativeArtworkRenderer, CreativeLayoutEngine
from engine.mockup import render_concept_mockup, scene_artwork_size
from engine.renderer.renderer import list_scene_templates as _list_scene_templates

from gui.models.project import Project
from gui.models.project_artifact import (
    ARTIFACT_TYPE_ARTWORK,
    ARTIFACT_TYPE_MOCKUP,
    ProjectArtifact,
)
from gui.models.project_store import ProjectStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project status model (Sprint 3B). Small, explicit; no CRM behavior.
# ---------------------------------------------------------------------------
STATUS_NEW = "NEW"
STATUS_RESEARCHED = "RESEARCHED"
STATUS_CREATIVE_READY = "CREATIVE_READY"
STATUS_CONTACTED = "CONTACTED"
STATUS_INTERESTED = "INTERESTED"
STATUS_WON = "WON"
STATUS_LOST = "LOST"
STATUS_ARCHIVED = "ARCHIVED"

PROJECT_STATUSES: tuple = (
    STATUS_NEW,
    STATUS_RESEARCHED,
    STATUS_CREATIVE_READY,
    STATUS_CONTACTED,
    STATUS_INTERESTED,
    STATUS_WON,
    STATUS_LOST,
    STATUS_ARCHIVED,
)

# Override fields supported in this sprint.
SUPPORTED_OVERRIDES = ("headline", "cta")

# History event types used by the workspace (ProjectHistory is extensible).
EVENT_STATUS_CHANGED = "status_changed"


def list_scene_templates() -> List[Dict]:
    """Return metadata for every available physical scene template.

    Delegates to the renderer's template discovery so the selector is driven by
    template metadata rather than hardcoded Python branches.
    """
    return _list_scene_templates()


class ProjectWorkspaceService:
    """Stateless domain operations over a ``ProjectStore`` + ``Project``."""

    def __init__(self, store: Optional[ProjectStore] = None) -> None:
        self._store = store or ProjectStore()

    @property
    def store(self) -> ProjectStore:
        """The underlying repository (used by the controller for persistence)."""
        return self._store

    # ------------------------------------------------------------------
    # Listing / opening (reopen is persistence, not regeneration)
    # ------------------------------------------------------------------
    def list_projects(self) -> List[Project]:
        """Return all persisted projects (deterministic ordering)."""
        return self._store.list()

    def open_project(self, project_id: str) -> Project:
        """Load a project from the store. Never scrapes / regenerates."""
        return self._store.load(project_id)

    def save(self, project: Project) -> None:
        """Persist a project through the repository/store abstraction."""
        self._store.save(project)

    def archive_project(self, project_id: str) -> str:
        """Move a project to the archive (non-destructive)."""
        return self._store.archive(project_id)

    # ------------------------------------------------------------------
    # Hydration (persisted structured state -> engine objects)
    # ------------------------------------------------------------------
    def hydrate_brand_profile(self, project: Project) -> Optional[BrandProfile]:
        """Reconstruct a BrandProfile from the saved snapshot (or None)."""
        if not project.brand_profile:
            return None
        return BrandProfile.from_dict(project.brand_profile)

    def hydrate_ad_concept(
        self, project: Project, concept_id: Optional[str] = None
    ) -> Optional[AdConcept]:
        """Reconstruct the AdConcept for ``concept_id`` (defaults to selected)."""
        cid = concept_id or project.selected_concept_id
        if not cid:
            return None
        for raw in project.ad_concepts:
            if not isinstance(raw, dict):
                continue
            concept = AdConcept.from_dict(raw)
            if concept.concept_id == cid:
                return concept
        return None

    def all_ad_concepts(self, project: Project) -> List[AdConcept]:
        """Reconstruct every saved AdConcept (empty when none)."""
        result: List[AdConcept] = []
        for raw in project.ad_concepts:
            if isinstance(raw, dict):
                result.append(AdConcept.from_dict(raw))
        return result

    def concept_exists(self, project: Project, concept_id: str) -> bool:
        """True when ``concept_id`` is present in the saved AdConcepts."""
        return any(c.concept_id == concept_id for c in self.all_ad_concepts(project))

    # ------------------------------------------------------------------
    # Overrides (Project.user_overrides only; AdConcept never mutated)
    # ------------------------------------------------------------------
    def build_render_concept(
        self, ad_concept: AdConcept, overrides: Optional[Dict[str, str]]
    ) -> AdConcept:
        """Return a COPY of the AdConcept with override fields applied.

        The source :class:`AdConcept` is never mutated. Overrides are drawn from
        ``Project.user_overrides`` (headline / CTA). Empty override values fall
        back to the source concept's own copy.
        """
        overrides = overrides or {}
        headline = overrides.get("headline")
        cta = overrides.get("cta")
        return dataclasses.replace(
            ad_concept,
            headline=headline if headline else ad_concept.headline,
            cta=cta if cta else ad_concept.cta,
        )

    def set_override(self, project: Project, field: str, value: str) -> None:
        """Persist a user override and append a history entry."""
        if field not in SUPPORTED_OVERRIDES:
            raise ValueError(f"Unsupported override field: {field!r}")
        value = str(value or "").strip()
        project.user_overrides[field] = value
        project.append_history(
            "override_changed",
            f"Updated {field} override",
            {"field": field, "value": value},
        )
        self._store.save(project)

    def reset_override(self, project: Project, field: str) -> None:
        """Remove a user override and append a history entry."""
        if field in project.user_overrides:
            project.user_overrides.pop(field, None)
            project.append_history(
                "override_changed",
                f"Reset {field} override",
                {"field": field},
            )
            self._store.save(project)

    # ------------------------------------------------------------------
    # Concept selection
    # ------------------------------------------------------------------
    def select_concept(self, project: Project, concept_id: str) -> None:
        """Mark ``concept_id`` selected, persist, and append history."""
        if not self.concept_exists(project, concept_id):
            raise ValueError(f"Concept {concept_id!r} no longer exists")
        project.selected_concept_id = concept_id
        project.append_history(
            "concept_selected",
            f"Selected concept {concept_id}",
            {"concept_id": concept_id},
        )
        self._store.save(project)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def set_status(self, project: Project, status: str) -> None:
        """Set the project status, persist, and append history."""
        status = str(status).upper()
        if status not in PROJECT_STATUSES:
            raise ValueError(f"Unknown status: {status!r}")
        project.status = status
        project.append_history(
            EVENT_STATUS_CHANGED,
            f"Status changed to {status}",
            {"status": status},
        )
        self._store.save(project)

    # ------------------------------------------------------------------
    # Mockup generation (selected AdConcept -> effective render copy)
    # ------------------------------------------------------------------
    def generate_mockup(
        self,
        project: Project,
        scene_template: str,
        concept_id: Optional[str] = None,
    ) -> List[ProjectArtifact]:
        """Render artwork + physical mockup for the selected AdConcept.

        Flow:
            1. hydrate the selected AdConcept (raises if none / missing)
            2. hydrate the BrandProfile snapshot (raises if none)
            3. build an effective render COPY with user overrides applied
            4. render rectangular artwork to ``artwork/``
            5. render physical mockup to ``mockups/``
            6. register both ``ProjectArtifact`` records + history
            7. persist the project

        Returns the registered artifacts. The source AdConcept is never mutated.
        """
        ad = self.hydrate_ad_concept(project, concept_id)
        if ad is None:
            raise ValueError("No AdConcept is selected. Choose a concept first.")
        profile = self.hydrate_brand_profile(project)
        if profile is None:
            raise ValueError(
                "This project has no saved research to render from. "
                "Run research on this project first."
            )

        render_concept = self.build_render_concept(ad, project.user_overrides)
        width, height = scene_artwork_size(scene_template)
        os.makedirs(os.path.join(project.root_dir, "artwork"), exist_ok=True)
        os.makedirs(os.path.join(project.root_dir, "mockups"), exist_ok=True)

        safe_id = (ad.concept_id or "selected").replace(" ", "_")
        artifacts: List[ProjectArtifact] = []

        # 1. Rectangular artwork artifact.
        artwork_path = os.path.join(
            project.root_dir, "artwork", f"concept_{safe_id}_artwork.png"
        )
        spec = CreativeLayoutEngine().resolve(render_concept, profile, width, height)
        CreativeArtworkRenderer().render_to_file(spec, artwork_path)
        artwork_artifact = project.register_artifact(
            artifact_type=ARTIFACT_TYPE_ARTWORK,
            path=os.path.relpath(artwork_path, project.root_dir),
            concept_id=ad.concept_id,
            composition_family=render_concept.composition_family,
            width=width,
            height=height,
            metadata={"override_applied": bool(project.user_overrides)},
        )
        project.append_history(
            "artwork_generated",
            f"Generated artwork for concept {ad.concept_id}",
            {"path": artwork_path},
        )
        artifacts.append(artwork_artifact)

        # 2. Physical mockup artifact.
        mockup_path = os.path.join(
            project.root_dir, "mockups", f"concept_{safe_id}_{scene_template}.png"
        )
        render_concept_mockup(render_concept, profile, scene_template, mockup_path)
        mockup_artifact = project.register_artifact(
            artifact_type=ARTIFACT_TYPE_MOCKUP,
            path=os.path.relpath(mockup_path, project.root_dir),
            concept_id=ad.concept_id,
            scene_template=scene_template,
            composition_family=render_concept.composition_family,
            width=width,
            height=height,
            metadata={"override_applied": bool(project.user_overrides)},
        )
        project.append_history(
            "mockup_generated",
            f"Generated physical mockup ({scene_template}) for concept {ad.concept_id}",
            {"scene_template": scene_template},
        )
        artifacts.append(mockup_artifact)

        self._store.save(project)
        logger.info(
            "Mockup generated for concept %s scene %s", ad.concept_id, scene_template
        )
        return artifacts

    @staticmethod
    def resolve_artifact_path(project: Project, artifact: ProjectArtifact) -> str:
        """Resolve an artifact's (possibly relative) path to an absolute one."""
        if not artifact.path:
            return ""
        if os.path.isabs(artifact.path):
            return artifact.path
        return os.path.join(project.root_dir, artifact.path)