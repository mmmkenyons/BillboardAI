"""Per-project output organization for generated mockups."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def _safe_project_name(name: str) -> str:
    """Sanitize a project name for use as a folder name."""
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return name or "project"


@dataclass
class Project:
    """A single generated mockup project with its output locations."""

    name: str
    root_dir: str
    image_path: str
    metadata_path: str


def create_project(output_root: str, name: str) -> Project:
    """Create a per-project output folder structure.

    Creates ``output_root/<name>/images/`` and reserves a ``metadata.json``
    path for future metadata. The rendered image is written into the
    ``images/`` subfolder.
    """
    safe_name = _safe_project_name(name)
    root_dir = os.path.join(output_root, safe_name)
    images_dir = os.path.join(root_dir, "images")

    os.makedirs(images_dir, exist_ok=True)

    return Project(
        name=safe_name,
        root_dir=root_dir,
        image_path=images_dir,
        metadata_path=os.path.join(root_dir, "metadata.json"),
    )