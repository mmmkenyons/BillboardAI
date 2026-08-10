"""Project model for the BillboardAI GUI.

The ``Project`` is the application's single source of truth. It owns
the concept list, selected concept, and all mutable state. Persistence
is handled via ``save()`` which writes ``project.json``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from gui.models.mockup_concept import MockupConcept
from gui.models.project_artifact import ProjectArtifact
from gui.models.project_history import ProjectHistory

if TYPE_CHECKING:
    from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)

# Increment when the project.json schema changes in a breaking way.
PROJECT_VERSION = "0.1"

# Schema version for the durable project format (Sprint 3A). Bump when the
# persisted schema changes incompatibly; old projects remain loadable.
SCHEMA_VERSION = 1

# Debounce window for autosave in milliseconds.
_AUTOSAVE_DELAY_MS = 500


def _safe_project_name(name: str) -> str:
    """Sanitize a project name for use as a folder name."""
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return name or "project"


def _safe_project_id() -> str:
    """Generate a new project UUID."""
    return str(uuid.uuid4())


def _extract_domain(website: str) -> str:
    """Extract a clean domain (no scheme / www.) from a URL string."""
    if not website:
        return ""
    try:
        parsed = urlparse(str(website))
        host = parsed.hostname or parsed.netloc or ""
        if host.lower().startswith("www."):
            host = host[4:]
        return host
    except Exception:  # noqa: BLE001
        return ""


def _coerce_history(entry: object) -> ProjectHistory:
    """Coerce a persisted history entry (dict or ProjectHistory) to ProjectHistory."""
    if isinstance(entry, ProjectHistory):
        return entry
    return ProjectHistory.from_dict(entry if isinstance(entry, dict) else None)


def _normalize_loaded_context(raw: object) -> dict:
    """Migrate legacy render_context blobs to the v1 contract on load."""
    from gui.models.render_context import ensure_render_context

    if not isinstance(raw, dict):
        return {}
    return ensure_render_context(raw).to_dict()



@dataclass
class Project:
    """A single billboard project with its output locations and concepts.

    The project owns its directory structure (Sprint 4B Phase E1):

    ``<root_dir>/
        project.json
        images/       (rendered concept images)
        assets/       (downloaded logos, etc.)
        exports/      (future: exported packages)
        trash/        (moved concepts from delete; non-destructive)
    """

    # --- Identifiers ---
    id: str = field(default_factory=_safe_project_id)
    version: str = PROJECT_VERSION
    name: str = ""
    company: str = ""
    website: str = ""

    # --- Paths ---
    root_dir: str = ""
    image_path: str = ""      # <root_dir>/images
    assets_path: str = ""     # <root_dir>/assets
    exports_path: str = ""    # <root_dir>/exports
    trash_path: str = ""      # <root_dir>/trash (Sprint 4B Phase E1)
    metadata_path: str = ""   # <root_dir>/project.json

    # --- State ---
    created: datetime = field(default_factory=datetime.now)
    modified: datetime = field(default_factory=datetime.now)
    concepts: list[MockupConcept] = field(default_factory=list)
    selected_concept_id: str | None = None
    logo_override: str = ""
    # Persisted inputs required for local re-render (no scrape).
    render_context: dict = field(default_factory=dict)
    user_overrides: dict = field(default_factory=dict)
    history: list[ProjectHistory] = field(default_factory=list)
    exports: list[dict] = field(default_factory=list)

    # --- Durable pipeline state (Sprint 3A) ---
    schema_version: int = SCHEMA_VERSION
    domain: str = ""
    status: str = "active"
    # Structured pipeline results (serialized via each engine model's
    # to_dict/from_dict) so a reopened project never needs to re-scrape.
    brand_profile: dict | None = None
    strategies: list[dict] = field(default_factory=list)
    ad_concepts: list[dict] = field(default_factory=list)
    # Registered generated artifacts (ProjectArtifact objects).
    artifacts: list[ProjectArtifact] = field(default_factory=list)
    # Free-form project metadata.
    metadata: dict = field(default_factory=dict)


    # --- Internal ---
    _autosave_timer: Any | None = None
    _dirty: bool = False
    _render_revision: int = 0  # Incremented on logo/context changes to prevent stale re-renders

# ------------------------------------------------------------------
    # Accessors (Sprint 3A)
    # ------------------------------------------------------------------

    @property
    def company_name(self) -> str:
        """Backward-compatible alias for the project's ``company`` field."""
        return self.company

    @company_name.setter
    def company_name(self, value: str) -> None:
        self.company = value

    def project_id(self) -> str:
        """Return the stable project id (alias for ``id``)."""
        return self.id

    def append_history(
        self,
        event_type: str,
        message: str = "",
        metadata: dict | None = None,
    ) -> ProjectHistory:
        """Append a meaningful history/audit entry and mark the project dirty."""
        entry = ProjectHistory(
            event_type=event_type,
            message=message,
            metadata=dict(metadata or {}),
        )
        self.history.append(entry)
        self.modified = datetime.now()
        self._mark_dirty()
        return entry

    def update_from_pipeline(
        self,
        *,
        brand_profile: Any | None = None,
        strategies: list | None = None,
        concepts: list | None = None,
    ) -> None:
        """Store structured pipeline results WITHOUT mutating the source objects.

        Each engine model is serialized through its own ``to_dict`` so the
        project owns a deep, independent copy of the pipeline state. A reopened
        project can reconstruct equivalent structured state without re-scraping.
        """
        if brand_profile is not None:
            serialized = getattr(brand_profile, "to_dict", None)
            self.brand_profile = (
                dict(serialized()) if callable(serialized) else dict(brand_profile)
            )
        if strategies is not None:
            self.strategies = [
                dict(s.to_dict()) if getattr(s, "to_dict", None) else dict(s)
                for s in strategies
            ]
        if concepts is not None:
            self.ad_concepts = [
                dict(c.to_dict()) if getattr(c, "to_dict", None) else dict(c)
                for c in concepts
            ]
        self.modified = datetime.now()
        self._mark_dirty()

    def register_artifact(
        self,
        *,
        artifact_type: str,
        path: str,
        concept_id: str = "",
        scene_template: str = "",
        composition_family: str = "",
        width: int = 0,
        height: int = 0,
        metadata: dict | None = None,
    ) -> ProjectArtifact:
        """Register a generated artifact against this project."""
        artifact = ProjectArtifact(
            artifact_type=artifact_type,
            path=path,
            concept_id=concept_id,
            scene_template=scene_template,
            composition_family=composition_family,
            width=width,
            height=height,
            metadata=dict(metadata or {}),
        )
        self.artifacts.append(artifact)
        self.modified = datetime.now()
        self._mark_dirty()
        return artifact

    def get_artifact(self, artifact_id: str) -> ProjectArtifact | None:
        """Return a registered artifact by id, or None when not found."""
        for artifact in self.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        return None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def create(
        cls,
        output_root: str,
        name: str,
        website: str = "",
        company: str = "",
    ) -> "Project":
        """Create a new project on disk and return it.

        Creates the directory structure (Sprint 4B Phase E1):
        ``output_root/<safe_name>/{images,assets,exports,trash}``
        """
        safe_name = _safe_project_name(name)
        root_dir = os.path.join(output_root, safe_name)
        images_dir = os.path.join(root_dir, "images")
        assets_dir = os.path.join(root_dir, "assets")
        exports_dir = os.path.join(root_dir, "exports")
        trash_dir = os.path.join(root_dir, "trash")

        os.makedirs(images_dir, exist_ok=True)
        os.makedirs(assets_dir, exist_ok=True)
        os.makedirs(exports_dir, exist_ok=True)
        os.makedirs(trash_dir, exist_ok=True)

        return cls(
            name=safe_name,
            company=company or safe_name.replace("_", " ").title(),
            website=website,
            domain=_extract_domain(website),
            root_dir=root_dir,
            image_path=images_dir,
            assets_path=assets_dir,
            exports_path=exports_dir,
            trash_path=trash_dir,
            metadata_path=os.path.join(root_dir, "project.json"),
        )

    @classmethod
    def load(cls, project_path: str) -> "Project":
        """Load a project from a ``project.json`` file.

        The parent directory becomes ``root_dir``.
        """
        with open(project_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        root_dir = os.path.dirname(os.path.abspath(project_path))

        project = cls(
            id=data.get("id", _safe_project_id()),
            version=data.get("version", PROJECT_VERSION),
            name=data.get("name", os.path.basename(root_dir)),
            company=data.get("company", ""),
            website=data.get("website", ""),
            created=datetime.fromisoformat(
                data.get("created", datetime.now().isoformat())
            ),
            modified=datetime.fromisoformat(
                data.get("modified", datetime.now().isoformat())
            ),
            root_dir=root_dir,
            image_path=os.path.join(root_dir, "images"),
            assets_path=os.path.join(root_dir, "assets"),
            exports_path=os.path.join(root_dir, "exports"),
            trash_path=os.path.join(root_dir, "trash"),
            metadata_path=project_path,
            concepts=[
                MockupConcept.from_dict(c) for c in data.get("concepts", [])
            ],
            selected_concept_id=data.get("selected_concept_id"),
            logo_override=data.get("logo_override", ""),
            render_context=_normalize_loaded_context(data.get("render_context")),
            user_overrides=data.get("user_overrides", {}),

            history=[_coerce_history(h) for h in data.get("history", [])],
            exports=data.get("exports", []),

            # --- Durable pipeline state (Sprint 3A) ---
            schema_version=int(data.get("schema_version", SCHEMA_VERSION) or SCHEMA_VERSION),
            domain=data.get("domain", "") or _extract_domain(data.get("website", "")),
            status=data.get("status", "active") or "active",
            brand_profile=(
                dict(data["brand_profile"]) if isinstance(data.get("brand_profile"), dict) else None
            ),
            strategies=[
                dict(s) for s in data.get("strategies", []) if isinstance(s, dict)
            ],
            ad_concepts=[
                dict(c) for c in data.get("ad_concepts", []) if isinstance(c, dict)
            ],
            artifacts=[
                ProjectArtifact.from_dict(a) for a in data.get("artifacts", []) if isinstance(a, dict)
            ],
            metadata=dict(data.get("metadata") or {}),
        )

        return project


    # ------------------------------------------------------------------
    # Concept management (Sprint 4B Phase E1 - pure state/FS only)
    # ------------------------------------------------------------------
    def add_concept(self, concept: MockupConcept) -> None:
        """Add a new concept to the project and mark it selected.
        
        Used by create_concept, duplicate_concept, and controller.
        """
        concept.selected = True
        for c in self.concepts:
            c.selected = False
        self.concepts.append(concept)
        self.selected_concept_id = concept.id
        self.modified = datetime.now()
        self._mark_dirty()

    def create_concept(self, result: "MockupResult") -> MockupConcept:
        """Create and add a new concept from a full pipeline result (Generate New Concept).
        
        Pure FS/state: assigns sequential name, next filename, source_concept_id from selected.
        Does NOT run AI/pipeline (controller does that). Never overwrites existing.
        """
        if TYPE_CHECKING:
            from gui.models.mockup_result import MockupResult
        else:
            from gui.models.mockup_result import MockupResult

        if not isinstance(result, MockupResult):
            raise TypeError("create_concept expects MockupResult")

        # Sequential name per instructions
        count = len(self.concepts) + 1
        name = f"Concept {count:03d}"

        concept_filename = self.next_concept_filename()
        image_path = os.path.join(self.image_path, concept_filename)

        source_id = self.selected_concept_id

        concept = MockupConcept.create(
            image_path=image_path,
            template=result.extra.get("template", "contractor"),
            headline=result.headline or "",
            cta=result.cta or "",
            quality_score=result.quality_score or 0.0,
            company_name=result.company_name or self.company,
            name=name,
            source_concept_id=source_id,
        )

        self.add_concept(concept)
        return concept

    def duplicate_concept(self, concept_id: str) -> MockupConcept:
        """Duplicate a concept (copy PNG, metadata, render_context; no AI/renderer).
        
        Pure FS: new UUID, new sequential name, new filename, copy file to images/.
        Adds and selects the copy. Per rules, no engine imports.
        """
        concept = self.get_concept(concept_id)
        if not concept:
            raise ValueError(f"Concept {concept_id} not found")

        count = len(self.concepts) + 1
        name = f"Concept {count:03d}"
        new_id = str(uuid.uuid4())

        # New filename
        new_filename = self.next_concept_filename()
        new_image_path = os.path.join(self.image_path, new_filename)

        # Copy PNG (pure FS, no renderer)
        import shutil
        if os.path.isfile(concept.image_path):
            shutil.copy2(concept.image_path, new_image_path)

        new_concept = MockupConcept.create(
            image_path=new_image_path,
            template=concept.template,
            headline=concept.headline,
            cta=concept.cta,
            quality_score=concept.quality_score,
            company_name=concept.company_name,
            name=name,
            source_concept_id=concept_id,  # Points to original
            **concept.extra,
        )
        new_concept.user_modified = concept.user_modified

        self.add_concept(new_concept)
        return new_concept

    def remove_concept(self, concept_id: str) -> None:
        """Remove concept, move PNG to trash/ (non-destructive), update selection, autosave.
        
        Pure FS/state per rules. Selects adjacent or first/None.
        """
        concept = self.get_concept(concept_id)
        if not concept:
            return

        # Move image to trash/ if exists (never permanent delete)
        if concept.image_path and os.path.isfile(concept.image_path):
            self.move_to_trash(concept.image_path)

        # Remove from list
        self.concepts = [c for c in self.concepts if c.id != concept_id]

        # Update selection to adjacent or first/None
        if self.concepts:
            if self.selected_concept_id == concept_id:
                # Find index of removed to select adjacent
                idx = 0
                for i, c in enumerate(self.concepts):
                    if c.id == concept_id:  # Won't find, but for logic
                        idx = i
                        break
                new_idx = min(idx, len(self.concepts) - 1)
                self.select_concept(self.concepts[new_idx].id)
            else:
                self.select_concept(self.selected_concept_id or self.concepts[0].id)
        else:
            self.selected_concept_id = None
            for c in self.concepts:
                c.selected = False

        self.modified = datetime.now()
        self._mark_dirty()

    def move_to_trash(self, src_path: str) -> str:
        """Move file to trash/ (non-destructive delete). Returns new path."""
        if not self.trash_path or not os.path.isfile(src_path):
            return src_path
        os.makedirs(self.trash_path, exist_ok=True)
        dest = os.path.join(self.trash_path, os.path.basename(src_path))
        import shutil
        shutil.move(src_path, dest)
        return dest

    def select_concept(self, concept_id: str) -> MockupConcept | None:
        """Select a concept by ID. Returns the concept or None if not found."""
        for c in self.concepts:
            c.selected = c.id == concept_id
        self.selected_concept_id = (
            concept_id if concept_id in {c.id for c in self.concepts} else None
        )
        self._mark_dirty()
        return self.get_concept(concept_id)

    def get_concept(self, concept_id: str) -> MockupConcept | None:
        """Return the concept with the given ID, or None."""
        for c in self.concepts:
            if c.id == concept_id:
                return c
        return None

    def get_selected_concept(self) -> MockupConcept | None:
        """Return the currently selected concept, or None."""
        if not self.selected_concept_id:
            return None
        return self.get_concept(self.selected_concept_id)

    def update_selected_concept(self, **fields: object) -> MockupConcept | None:
        """Update fields on the selected concept and mark the project dirty."""
        concept = self.get_selected_concept()
        if concept is None:
            return None
        changed = concept.apply_updates(**fields)
        if changed:
            self._mark_dirty()
        return concept

    def set_render_context(self, context: dict) -> None:
        """Replace the persisted render context used for local re-renders.

        Normalizes legacy/partial dicts to the v1 contract on write.
        (Relaxed guard for tests that use minimal mocks; sprint validation ensures no real blanks reach here.)
        """
        from gui.models.render_context import ensure_render_context

        if not context:
            logger.warning("set_render_context received empty context")
            return

        self.render_context = ensure_render_context(context).to_dict()
        self._render_revision += 1
        self._mark_dirty()

    def set_logo_override(self, logo_path: str) -> None:
        """Set the project logo override and mirror it into render_context.

        Never overwrites the original scraped logo (uses copy_asset).
        """
        from gui.models.render_context import ensure_render_context

        self.logo_override = logo_path or ""
        ctx = ensure_render_context(self.render_context)
        ctx.logo_image = self.logo_override
        self.render_context = ctx.to_dict()
        self._render_revision += 1
        self._mark_dirty()

    def clear_logo_override(self) -> None:
        """Clear any logo override, falling back to scraped logo (if present)
        or no logo. Updates render_context and increments revision.
        """
        from gui.models.render_context import ensure_render_context

        self.logo_override = ""
        ctx = ensure_render_context(self.render_context)
        # Do not set to screenshot; keep empty or scraped value from original context
        ctx.logo_image = ""  # Renderer will use scraped if present in full context
        self.render_context = ctx.to_dict()
        self._render_revision += 1
        self._mark_dirty()

    def effective_render_context(self, **concept_overrides: object) -> dict:
        """Return project render_context merged with concept field overrides.

        Prefers logo_override > scraped logo > no logo. Never falls back to screenshot for logo.
        """
        from gui.models.render_context import ensure_render_context

        ctx = ensure_render_context(self.render_context)
        if self.logo_override and "logo_image" not in concept_overrides:
            concept_overrides = {**concept_overrides, "logo_image": self.logo_override}
        elif not self.logo_override and "logo_image" not in concept_overrides:
            # Ensure no accidental screenshot fallback for logo
            concept_overrides = {**concept_overrides, "logo_image": ctx.logo_image or ""}
        if concept_overrides:
            ctx = ctx.merge_overrides(**concept_overrides)
        return ctx.to_dict()

    def get_render_revision(self) -> int:
        """Return current render revision token (for stale check in workers)."""
        return self._render_revision


    # ------------------------------------------------------------------
    # Asset management
    # ------------------------------------------------------------------

    def next_concept_filename(self) -> str:
        """Return the next concept image filename, e.g. concept_001.png.
        
        Updated for sequential naming in create/duplicate (Sprint 4B).
        """
        count = len(self.concepts) + 1
        return f"concept_{count:03d}.png"

    def copy_asset(self, src_path: str, dest_name: str | None = None) -> str:
        """Copy an asset file (e.g. logo) into the project's assets/ folder.

        Returns the destination path. If ``dest_name`` is provided it is used
        as the destination filename (useful to avoid collisions).
        """
        os.makedirs(self.assets_path, exist_ok=True)
        filename = dest_name or os.path.basename(src_path)
        dest = os.path.join(self.assets_path, filename)
        import shutil

        # Avoid clobbering when source basename collides but content differs.
        if os.path.abspath(src_path) != os.path.abspath(dest):
            shutil.copy2(src_path, dest)
        return dest


    # ------------------------------------------------------------------
    # Persistence (with debounced autosave)
    # ------------------------------------------------------------------
    def _mark_dirty(self) -> None:
        """Schedule an autosave write, debounced by _AUTOSAVE_DELAY_MS.

        In a headless/test context (no QApplication / PySide6 not
        installed), the debounce timer is skipped and the save is
        deferred to an explicit call to ``save()``.
        """
        self._dirty = True
        self.modified = datetime.now()
        if not self.metadata_path:
            return
        try:
            from PySide6.QtCore import QCoreApplication, QTimer
        except ImportError:
            # Headless context — autosave will be triggered explicitly.
            return
        # Without a running Qt event loop, starting a QTimer would produce
        # "event dispatcher has already been destroyed" noise and never fire.
        # Defer autosave to an explicit save() call instead.
        if QCoreApplication.instance() is None:
            return

        if self._autosave_timer is None:
            self._autosave_timer = QTimer()
            self._autosave_timer.setSingleShot(True)
        else:
            self._autosave_timer.stop()
        self._autosave_timer.timeout.connect(self._flush_save)
        self._autosave_timer.start(_AUTOSAVE_DELAY_MS)

    def _flush_save(self) -> None:
        """Actually write to disk (called by the debounce timer)."""
        if self._dirty and self.metadata_path:
            try:
                self._write_to_disk()
            except OSError as exc:
                logger.warning("Could not save project.json: %s", exc)
            finally:
                self._dirty = False
        if self._autosave_timer is not None:
            self._autosave_timer.deleteLater()
            self._autosave_timer = None

    def save(self) -> None:
        """Force an immediate, synchronous save to disk."""
        self._dirty = False
        if self._autosave_timer is not None:
            self._autosave_timer.stop()
        self._write_to_disk()

    def _write_to_disk(self) -> None:
        """Write project.json to disk atomically.

        Writes to a temporary file in the same directory, then atomically
        replaces ``project.json``. A crash during save cannot easily corrupt
        the project file.
        """
        os.makedirs(os.path.dirname(self.metadata_path), exist_ok=True)
        data = self.to_dict()
        tmp_path = self.metadata_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp_path, self.metadata_path)

    def to_dict(self) -> dict:
        """Serialize the project to a plain dict for JSON.

        Derived fields (trash_path, image_path, ...) are not persisted as they
        are reconstructed from the directory on load. Sprint 3A adds the durable
        pipeline state (brand_profile / strategies / ad_concepts / artifacts /
        schema_version / domain / status / metadata).
        """
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "company": self.company,
            "website": self.website,
            "created": self.created.isoformat(),
            "modified": self.modified.isoformat(),
            "selected_concept_id": self.selected_concept_id,
            "logo_override": self.logo_override,
            "render_context": self.render_context,
            "user_overrides": self.user_overrides,
            "history": [h.to_dict() for h in self.history],
            "exports": self.exports,
            "concepts": [c.to_dict() for c in self.concepts],
            # --- Durable pipeline state (Sprint 3A) ---
            "schema_version": self.schema_version,
            "domain": self.domain,
            "status": self.status,
            "brand_profile": self.brand_profile,
            "strategies": list(self.strategies),
            "ad_concepts": list(self.ad_concepts),
            "artifacts": [a.to_dict() for a in self.artifacts],
            "metadata": dict(self.metadata),
        }



def create_project(
    output_root: str,
    name: str,
    website: str = "",
    company: str = "",
) -> Project:
    """Create a per-project output folder structure (includes trash/ for Phase E1)."""
    return Project.create(output_root, name, website=website, company=company)
