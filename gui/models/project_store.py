"""ProjectStore: repository abstraction for durable BillboardAI projects.

The GUI should eventually talk to this abstraction rather than manually
opening JSON files. It owns the on-disk layout:

    <root>/
        <project_id>/
            project.json
            assets/
            artwork/
            mockups/
            exports/

Project IDs are stable filesystem-safe UUIDs (never company-name alone), so a
company can have multiple projects/campaigns. ``list()`` is deterministic and
ignores unrelated filesystem entries.

Saves are atomic: a temporary JSON is written and then atomically replaced
over ``project.json``, so a crash during save cannot easily corrupt a project.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from typing import List, Optional, Union

from gui.models.project import Project, _extract_domain

logger = logging.getLogger(__name__)

# Default project root (git-ignored via output/).
DEFAULT_PROJECT_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "projects",
)

# Sub-directories created under each project directory.
_SUBDIRS = ("assets", "artwork", "mockups", "exports")


class ProjectStore:
    """Create / save / load / list / archive / delete durable projects."""

    def __init__(self, root: Optional[Union[str, "os.PathLike[str]"]] = None) -> None:
        self._root = os.path.abspath(str(root)) if root else DEFAULT_PROJECT_ROOT

    # ------------------------------------------------------------------
    # Properties & lookup
    # ------------------------------------------------------------------

    @property
    def root(self) -> str:
        """The absolute root directory that holds project directories."""
        return self._root

    def project_path(self, project_id: str) -> Optional[str]:
        """Return the absolute path of a project dir, or None if it has no project.json."""
        if not project_id:
            return None
        candidate = os.path.join(self._root, str(project_id))
        if os.path.isfile(os.path.join(candidate, "project.json")):
            return candidate
        return None

    def exists(self, project_id: str) -> bool:
        """Return True when a project with the given id exists on disk."""
        return self.project_path(project_id) is not None
# ------------------------------------------------------------------
    # Create / Save / Load
    # ------------------------------------------------------------------

    def create(
        self,
        company_name: str = "",
        website: str = "",
        name: str = "",
    ) -> Project:
        """Create a new project on disk and return it.

        The directory is keyed by a fresh UUID (filesystem-safe, stable), so
        multiple projects for the same company are always allowed.
        """
        project_id = str(uuid.uuid4())
        root_dir = os.path.join(self._root, project_id)
        artwork_dir = os.path.join(root_dir, "artwork")
        assets_dir = os.path.join(root_dir, "assets")
        exports_dir = os.path.join(root_dir, "exports")
        trash_dir = os.path.join(root_dir, "_trash")

        for sub in _SUBDIRS:
            os.makedirs(os.path.join(root_dir, sub), exist_ok=True)
        os.makedirs(trash_dir, exist_ok=True)

        pretty_name = name or company_name or project_id
        project = Project(
            id=project_id,
            name=pretty_name,
            company=company_name,
            website=website,
            domain=_extract_domain(website),
            root_dir=root_dir,
            image_path=artwork_dir,
            assets_path=assets_dir,
            exports_path=exports_dir,
            trash_path=trash_dir,
            metadata_path=os.path.join(root_dir, "project.json"),
        )
        project.append_history(
            "project_created",
            f"Project created for {company_name or website or project_id}",
            {"company_name": company_name, "website": website},
        )
        self.save(project)
        return project

    def save(self, project: Project) -> None:
        """Persist a project to disk (atomic write)."""
        project.save()

    def load(self, project_id: str) -> Project:
        """Load a project by id. Raises FileNotFoundError when missing."""
        path = self.project_path(project_id)
        if path is None:
            raise FileNotFoundError(f"No project found for id {project_id!r}")
        return Project.load(os.path.join(path, "project.json"))
# ------------------------------------------------------------------
    # Listing / lifecycle
    # ------------------------------------------------------------------

    def list(self) -> List[Project]:
        """Return all projects, deterministically ordered by directory name.

        Unrelated filesystem entries (files, non-project dirs) are ignored.
        Unreadable project.json files are skipped with a warning.
        """
        if not os.path.isdir(self._root):
            return []
        projects: List[Project] = []
        for entry in sorted(os.listdir(self._root)):
            json_path = os.path.join(self._root, entry, "project.json")
            if not os.path.isfile(json_path):
                continue
            try:
                projects.append(Project.load(json_path))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping unreadable project %r: %s", entry, exc)
        return projects

    def archive(self, project_id: str) -> str:
        """Move a project into an ``_archive`` subfolder (non-destructive).

        Returns the destination path. Raises FileNotFoundError when missing.
        """
        source = self.project_path(project_id)
        if source is None:
            raise FileNotFoundError(f"No project found for id {project_id!r}")
        archive_dir = os.path.join(self._root, "_archive")
        os.makedirs(archive_dir, exist_ok=True)
        dest = os.path.join(archive_dir, os.path.basename(source))
        if os.path.abspath(source) != os.path.abspath(dest):
            shutil.move(source, dest)
        return dest

    def delete(self, project_id: str) -> bool:
        """Permanently delete a project directory. Returns True when removed."""
        source = self.project_path(project_id)
        if source is None:
            return False
        shutil.rmtree(source, ignore_errors=True)
        return True