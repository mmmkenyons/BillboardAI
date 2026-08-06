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

from gui.models.mockup_concept import MockupConcept

if TYPE_CHECKING:
    from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)

# Increment when the project.json schema changes in a breaking way.
PROJECT_VERSION = "0.1"

# Debounce window for autosave in milliseconds.
_AUTOSAVE_DELAY_MS = 500


def _safe_project_name(name: str) -> str:
    """Sanitize a project name for use as a folder name."""
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return name or "project"


def _safe_project_id() -> str:
    """Generate a new project UUID."""
    return str(uuid.uuid4())


@dataclass
class Project:
    """A single billboard project with its output locations and concepts.

    The project owns its directory structure:

    ``<root_dir>/
        project.json
        images/       (rendered concept images)
        assets/       (downloaded logos, etc.)
        exports/      (future: exported packages)
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
    metadata_path: str = ""   # <root_dir>/project.json

    # --- State ---
    created: datetime = field(default_factory=datetime.now)
    modified: datetime = field(default_factory=datetime.now)
    concepts: list[MockupConcept] = field(default_factory=list)
    selected_concept_id: str | None = None
    logo_override: str = ""
    user_overrides: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    exports: list[dict] = field(default_factory=list)

    # --- Internal ---
    _autosave_timer: Any | None = None
    _dirty: bool = False

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

        Creates the directory structure:
        ``output_root/<safe_name>/{images,assets,exports}``
        """
        safe_name = _safe_project_name(name)
        root_dir = os.path.join(output_root, safe_name)
        images_dir = os.path.join(root_dir, "images")
        assets_dir = os.path.join(root_dir, "assets")
        exports_dir = os.path.join(root_dir, "exports")

        os.makedirs(images_dir, exist_ok=True)
        os.makedirs(assets_dir, exist_ok=True)
        os.makedirs(exports_dir, exist_ok=True)

        return cls(
            name=safe_name,
            company=company or safe_name.replace("_", " ").title(),
            website=website,
            root_dir=root_dir,
            image_path=images_dir,
            assets_path=assets_dir,
            exports_path=exports_dir,
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
            metadata_path=project_path,
            concepts=[
                MockupConcept.from_dict(c) for c in data.get("concepts", [])
            ],
            selected_concept_id=data.get("selected_concept_id"),
            logo_override=data.get("logo_override", ""),
            user_overrides=data.get("user_overrides", {}),
            history=data.get("history", []),
            exports=data.get("exports", []),
        )

        return project

    # ------------------------------------------------------------------
    # Concept management
    # ------------------------------------------------------------------
    def add_concept(self, concept: MockupConcept) -> None:
        """Add a new concept to the project and mark it selected."""
        concept.selected = True
        for c in self.concepts:
            c.selected = False
        self.concepts.append(concept)
        self.selected_concept_id = concept.id
        self.modified = datetime.now()
        self._mark_dirty()

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

    # ------------------------------------------------------------------
    # Asset management
    # ------------------------------------------------------------------
    def next_concept_filename(self) -> str:
        """Return the next concept image filename, e.g. concept_001.png."""
        count = len(self.concepts) + 1
        return f"concept_{count:03d}.png"

    def copy_asset(self, src_path: str) -> str:
        """Copy an asset file (e.g. logo) into the project's assets/ folder.

        Returns the destination path.
        """
        os.makedirs(self.assets_path, exist_ok=True)
        filename = os.path.basename(src_path)
        dest = os.path.join(self.assets_path, filename)
        import shutil

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
            from PySide6.QtCore import QTimer
        except ImportError:
            # Headless context — autosave will be triggered explicitly.
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
        """Write project.json to disk."""
        os.makedirs(os.path.dirname(self.metadata_path), exist_ok=True)
        data = self.to_dict()
        with open(self.metadata_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

    def to_dict(self) -> dict:
        """Serialize the project to a plain dict for JSON."""
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
            "user_overrides": self.user_overrides,
            "history": self.history,
            "exports": self.exports,
            "concepts": [c.to_dict() for c in self.concepts],
        }


def create_project(
    output_root: str,
    name: str,
    website: str = "",
    company: str = "",
) -> Project:
    """Create a per-project output folder structure.

    Creates ``output_root/<name>/images/`` and reserves a ``project.json``
    path for future metadata. The rendered image is written into the
    ``images/`` subfolder.
    """
    return Project.create(output_root, name, website=website, company=company)
