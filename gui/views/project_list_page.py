"""Project browser page for Sprint 3B.

Lists persisted projects from the ProjectStore as cards, each showing company
name, website/domain, status, modified date, selected-concept indicator, and
artifact count. Provides Open Project / Archive actions and a Create/New
Generate shortcut. Never deletes permanently.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.models.project import Project

logger = logging.getLogger(__name__)


class ProjectBrowserPage(QWidget):
    """Shows saved projects and lets the user open or archive them."""

    open_project_requested = Signal(str)  # project_id
    archive_requested = Signal(str)  # project_id
    new_generate_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 24)
        root.setSpacing(16)

        heading = QLabel("Projects", self)
        heading.setObjectName("logoTitle")
        root.addWidget(heading)

        sub = QLabel("Open a saved prospect project to continue working.", self)
        sub.setObjectName("logoSubtitle")
        root.addWidget(sub)

        # New generate button.
        action_row = QHBoxLayout()
        self.new_generate_button = QPushButton("+ New Generate", self)
        self.new_generate_button.setObjectName("primaryButton")
        self.new_generate_button.clicked.connect(self.new_generate_requested.emit)
        action_row.addStretch(1)
        action_row.addWidget(self.new_generate_button)
        root.addLayout(action_row)

        # Scrollable card list.
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cards_container = QWidget(self._scroll)
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 8, 0)
        self._cards_layout.setSpacing(12)
        self._cards_layout.addStretch(1)
        self._scroll.setWidget(self._cards_container)
        root.addWidget(self._scroll, stretch=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_projects(self, projects: List[Project]) -> None:
        """Populate the browser with the given projects."""
        self._clear_cards()
        if not projects:
            empty = QLabel(
                "No saved projects yet.\nGenerate a mockup to create your first project.",
                self._cards_container,
            )
            empty.setObjectName("emptyState")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._cards_layout.addWidget(empty)
            return
        for project in projects:
            self._cards_layout.addWidget(self._build_card(project))

    def _clear_cards(self) -> None:
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_card(self, project: Project) -> QFrame:
        card = QFrame(self._cards_container)
        card.setObjectName("projectCard")
        card.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(16)

        info = QVBoxLayout()
        info.setSpacing(4)

        company = QLabel(project.company or project.name or "Untitled", card)
        company.setObjectName("projectTitle")
        info.addWidget(company)

        website = QLabel(project.domain or project.website or "—", card)
        website.setObjectName("projectMeta")
        info.addWidget(website)

        status = QLabel(f"Status: {project.status or '—'}", card)
        status.setObjectName("projectMeta")
        info.addWidget(status)

        modified = QLabel(
            f"Modified: {project.modified.strftime('%Y-%m-%d %H:%M')}", card
        )
        modified.setObjectName("projectMeta")
        info.addWidget(modified)

        extras = []
        if project.selected_concept_id:
            extras.append("selected concept ✓")
        if project.artifacts:
            extras.append(f"{len(project.artifacts)} artifact(s)")
        if extras:
            line = QLabel(" · ".join(extras), card)
            line.setObjectName("projectMeta")
            info.addWidget(line)

        layout.addLayout(info, stretch=1)

        actions = QVBoxLayout()
        actions.setSpacing(8)
        open_btn = QPushButton("Open Project", card)
        open_btn.setObjectName("primaryButton")
        open_btn.clicked.connect(
            lambda _=False, pid=project.id: self.open_project_requested.emit(pid)
        )
        archive_btn = QPushButton("Archive", card)
        archive_btn.setObjectName("secondaryButton")
        archive_btn.clicked.connect(
            lambda _=False, pid=project.id: self.archive_requested.emit(pid)
        )
        actions.addWidget(open_btn)
        actions.addWidget(archive_btn)
        layout.addLayout(actions)

        return card