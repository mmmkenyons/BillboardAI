"""Project Workspace page for Sprint 3B.

A clean desktop workspace for a single open prospect project. Provides a left
sidebar (project identity, status, website, last modified, back-to-projects)
and a main area with five tabs: OVERVIEW, RESEARCH, CONCEPTS, ARTWORK/MOCKUPS,
HISTORY.

The page is a thin view: it reads current state from the
:class:`~gui.controllers.project_controller.ProjectWorkspaceController` and
emits signals for the controller to act on. All business logic lives in the
Qt-free service layer.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.models.project import Project
from gui.services.project_workspace import PROJECT_STATUSES, SUPPORTED_OVERRIDES

if TYPE_CHECKING:
    from gui.controllers.project_controller import ProjectWorkspaceController

logger = logging.getLogger(__name__)


class ProjectWorkspacePage(QWidget):
    """The single open project's workspace."""

    back_requested = Signal()
    open_concept_requested = Signal(str)  # concept_id
    set_override_requested = Signal(str, str)  # field, value
    reset_override_requested = Signal(str)  # field
    set_status_requested = Signal(str)  # status
    generate_mockup_requested = Signal(str)  # scene_template
    open_image_requested = Signal(str)  # absolute path
    open_folder_requested = Signal(str)  # folder path

    def __init__(
        self,
        controller: Optional["ProjectWorkspaceController"] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._project: Optional[Project] = None
        self._build_ui()
        self.clear()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(16)

        root.addWidget(self._build_sidebar())

        self._tabs = QTabWidget(self)
        self._tabs.setObjectName("workspaceTabs")
        self._tabs.addTab(self._build_overview_tab(), "Overview")
        self._tabs.addTab(self._build_research_tab(), "Research")
        self._tabs.addTab(self._build_concepts_tab(), "Concepts")
        self._tabs.addTab(self._build_artifacts_tab(), "Artwork / Mockups")
        self._tabs.addTab(self._build_history_tab(), "History")
        root.addWidget(self._tabs, stretch=1)

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------
    def _build_sidebar(self) -> QFrame:
        side = QFrame(self)
        side.setObjectName("workspaceSidebar")
        side.setFixedWidth(240)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(10)

        back_btn = QPushButton("← Back to Projects", side)
        back_btn.setObjectName("secondaryButton")
        back_btn.clicked.connect(self.back_requested.emit)
        layout.addWidget(back_btn)

        layout.addSpacing(8)
        self.side_company = QLabel("—", side)
        self.side_company.setObjectName("projectTitle")
        self.side_company.setWordWrap(True)
        layout.addWidget(self.side_company)

        self.side_status = QLabel("", side)
        self.side_status.setObjectName("projectMeta")
        layout.addWidget(self.side_status)

        # Project status selector (Sprint 3B final patch).
        status_heading = QLabel("Status", side)
        status_heading.setObjectName("projectMeta")
        layout.addWidget(status_heading)
        self.status_combo = QComboBox(side)
        self.status_combo.setObjectName("statusCombo")
        self.status_combo.currentIndexChanged.connect(self._on_status_changed)
        layout.addWidget(self.status_combo)

        self.side_website = QLabel("", side)
        self.side_website.setObjectName("projectMeta")
        self.side_website.setWordWrap(True)
        layout.addWidget(self.side_website)

        self.side_modified = QLabel("", side)
        self.side_modified.setObjectName("projectMeta")
        layout.addWidget(self.side_modified)

        layout.addStretch(1)
        return side

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    def _build_overview_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("Project Identity"))
        self._identity = QFormLayout()
        layout.addLayout(self._identity)

        layout.addWidget(self._section_label("Project Summary"))
        self._summary = QFormLayout()
        layout.addLayout(self._summary)

        layout.addStretch(1)
        return page

    def _build_research_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("Identity"))
        self._r_identity = QFormLayout()
        layout.addLayout(self._r_identity)

        layout.addWidget(self._section_label("Services"))
        self._r_services = QFormLayout()
        layout.addLayout(self._r_services)

        layout.addWidget(self._section_label("Sales Evidence"))
        self._r_evidence = QFormLayout()
        layout.addLayout(self._r_evidence)

        layout.addWidget(self._section_label("Branding"))
        self._r_branding = QFormLayout()
        layout.addLayout(self._r_branding)

        layout.addStretch(1)
        return page

    def _build_concepts_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Overrides panel.
        overrides = QFrame(page)
        overrides.setObjectName("cardFrame")
        overrides.setFrameShape(QFrame.Shape.StyledPanel)
        o_layout = QVBoxLayout(overrides)
        o_layout.setContentsMargins(14, 12, 14, 12)
        o_layout.setSpacing(8)
        o_layout.addWidget(self._section_label("User Overrides"))
        o_form = QFormLayout()
        self.override_headline = QLineEdit(overrides)
        self.override_headline.setPlaceholderText("Source concept headline")
        self.override_cta = QLineEdit(overrides)
        self.override_cta.setPlaceholderText("Source concept CTA")
        o_form.addRow("Headline", self.override_headline)
        o_form.addRow("CTA", self.override_cta)
        o_layout.addLayout(o_form)
        o_buttons = QHBoxLayout()
        save_ovr = QPushButton("Save Override", overrides)
        save_ovr.setObjectName("primaryButton")
        save_ovr.clicked.connect(self._on_save_overrides)
        reset_ovr = QPushButton("Reset Override", overrides)
        reset_ovr.setObjectName("secondaryButton")
        reset_ovr.clicked.connect(self._on_reset_overrides)
        o_buttons.addWidget(save_ovr)
        o_buttons.addWidget(reset_ovr)
        o_buttons.addStretch(1)
        o_layout.addLayout(o_buttons)
        self.override_note = QLabel("", overrides)
        self.override_note.setObjectName("projectMeta")
        o_layout.addWidget(self.override_note)
        layout.addWidget(overrides)

        # Generate mockup panel.
        gen = QFrame(page)
        gen.setObjectName("cardFrame")
        gen.setFrameShape(QFrame.Shape.StyledPanel)
        g_layout = QHBoxLayout(gen)
        g_layout.setContentsMargins(14, 12, 14, 12)
        g_layout.setSpacing(10)
        g_layout.addWidget(self._section_label("Generate Mockup"))
        self.scene_combo = QComboBox(gen)
        g_layout.addWidget(self.scene_combo, stretch=1)
        self.generate_button = QPushButton("Generate Mockup", gen)
        self.generate_button.setObjectName("primaryButton")
        self.generate_button.clicked.connect(self._on_generate_mockup)
        g_layout.addWidget(self.generate_button)
        layout.addWidget(gen)

        # Concept gallery.
        self._concepts_scroll = QScrollArea(page)
        self._concepts_scroll.setWidgetResizable(True)
        self._concepts_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._concepts_container = QWidget(self._concepts_scroll)
        self._concepts_layout = QVBoxLayout(self._concepts_container)
        self._concepts_layout.setContentsMargins(0, 0, 8, 0)
        self._concepts_layout.setSpacing(12)
        self._concepts_layout.addStretch(1)
        self._concepts_scroll.setWidget(self._concepts_container)
        layout.addWidget(self._concepts_scroll, stretch=1)
        return page

    def _build_artifacts_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("Artwork"))
        self._artwork_scroll = QScrollArea(page)
        self._artwork_scroll.setWidgetResizable(True)
        self._artwork_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._artwork_container = QWidget(self._artwork_scroll)
        self._artwork_layout = QVBoxLayout(self._artwork_container)
        self._artwork_layout.setContentsMargins(0, 0, 8, 0)
        self._artwork_layout.setSpacing(12)
        self._artwork_layout.addStretch(1)
        self._artwork_scroll.setWidget(self._artwork_container)
        layout.addWidget(self._artwork_scroll, stretch=1)

        layout.addWidget(self._section_label("Physical Mockups"))
        self._mockups_scroll = QScrollArea(page)
        self._mockups_scroll.setWidgetResizable(True)
        self._mockups_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._mockups_container = QWidget(self._mockups_scroll)
        self._mockups_layout = QVBoxLayout(self._mockups_container)
        self._mockups_layout.setContentsMargins(0, 0, 8, 0)
        self._mockups_layout.setSpacing(12)
        self._mockups_layout.addStretch(1)
        self._mockups_scroll.setWidget(self._mockups_container)
        layout.addWidget(self._mockups_scroll, stretch=1)
        return page

    def _build_history_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._section_label("Project History"))
        self._history_scroll = QScrollArea(page)
        self._history_scroll.setWidgetResizable(True)
        self._history_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._history_container = QWidget(self._history_scroll)
        self._history_layout = QVBoxLayout(self._history_container)
        self._history_layout.setContentsMargins(0, 0, 8, 0)
        self._history_layout.setSpacing(8)
        self._history_layout.addStretch(1)
        self._history_scroll.setWidget(self._history_container)
        layout.addWidget(self._history_scroll, stretch=1)
        return page

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setObjectName("previewHeading")
        return label

    # ------------------------------------------------------------------
    # Slot handlers
    # ------------------------------------------------------------------
    def _on_save_overrides(self) -> None:
        h = self.override_headline.text().strip()
        c = self.override_cta.text().strip()
        if self._project is not None:
            if h != self._project.user_overrides.get("headline", ""):
                self.set_override_requested.emit("headline", h)
            if c != self._project.user_overrides.get("cta", ""):
                self.set_override_requested.emit("cta", c)

    def _on_reset_overrides(self) -> None:
        if self._project is None:
            return
        if "headline" in self._project.user_overrides:
            self.reset_override_requested.emit("headline")
        if "cta" in self._project.user_overrides:
            self.reset_override_requested.emit("cta")

    def _on_generate_mockup(self) -> None:
        scene = self.scene_combo.currentData()
        if scene:
            self.generate_mockup_requested.emit(scene)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_controller(self, controller) -> None:
        """Attach the workspace controller (used by MainWindow wiring)."""
        self._controller = controller

    def set_project(self, project: Optional[Project]) -> None:
        """Set the active project and refresh all tabs."""
        self._project = project
        self.refresh()

    def clear(self) -> None:
        """Clear the workspace to its empty state."""
        self._project = None
        self.side_company.setText("No project open")
        self.side_status.setText("")
        self.status_combo.blockSignals(True)
        self.status_combo.clear()
        self.status_combo.setEnabled(False)
        self.status_combo.blockSignals(False)
        self.side_website.setText("")
        self.side_modified.setText("")
        self.override_headline.setEnabled(False)
        self.override_cta.setEnabled(False)
        self.generate_button.setEnabled(False)
        self.scene_combo.clear()
        self._clear_layout(self._identity)
        self._clear_layout(self._summary)
        self._clear_layout(self._r_identity)
        self._clear_layout(self._r_services)
        self._clear_layout(self._r_evidence)
        self._clear_layout(self._r_branding)
        self._clear_layout(self._concepts_layout)
        self._clear_layout(self._artwork_layout)
        self._clear_layout(self._mockups_layout)
        self._clear_layout(self._history_layout)

    def refresh(self) -> None:
        """Re-render all tabs from the current project (idempotent)."""
        if self._project is None:
            self.clear()
            return
        self._populate_sidebar()
        self._populate_scene_selector()
        self._populate_overview()
        self._populate_research()
        self._populate_concepts()
        self._populate_artifacts()
        self._populate_history()

    # ------------------------------------------------------------------
    # Populate helpers
    # ------------------------------------------------------------------
    def _populate_sidebar(self) -> None:
        p = self._project
        if p is None:
            return
        self.side_company.setText(p.company or p.name or "Untitled")
        self.side_status.setText(f"Status: {p.status or '—'}")
        self._populate_status_selector()
        self.side_website.setText(p.domain or p.website or "—")
        self.side_modified.setText(
            f"Modified: {p.modified.strftime('%Y-%m-%d %H:%M')}"
        )

    def _available_statuses(self) -> tuple:
        """Return the status model from the controller/service (no duplication)."""
        if self._controller is not None:
            statuses = self._controller.available_statuses()
            if statuses:
                return tuple(statuses)
        from gui.services.project_workspace import PROJECT_STATUSES

        return tuple(PROJECT_STATUSES)

    def _populate_status_selector(self) -> None:
        """Populate the status combo from available_statuses() and select the
        current persisted Project.status. Signals are blocked during population
        so initial load / refresh never emits a spurious status-change event."""
        p = self._project
        if p is None:
            return
        statuses = self._available_statuses()
        current = (p.status or "").upper()
        self.status_combo.blockSignals(True)
        self.status_combo.setEnabled(True)
        try:
            self.status_combo.clear()
            for status in statuses:
                self.status_combo.addItem(status, status)
            idx = self.status_combo.findData(current)
            if idx >= 0:
                self.status_combo.setCurrentIndex(idx)
            else:
                # Persisted status not in the model (e.g. legacy "active"): add it
                # as the selected value without sending a change signal.
                self.status_combo.addItem(current or "—", current)
                self.status_combo.setCurrentIndex(self.status_combo.count() - 1)
        finally:
            self.status_combo.blockSignals(False)

    def _on_status_changed(self, index: int) -> None:
        """Emit set_status_requested when the user changes status (no-op during
        programmatic population because signals are blocked)."""
        if index < 0:
            return
        status = self.status_combo.itemData(index)
        if status and self._project is not None:
            if status == (self._project.status or "").upper():
                return  # no actual change
            self.set_status_requested.emit(status)

    def _populate_scene_selector(self) -> None:
        current = self.scene_combo.currentData()
        self.scene_combo.blockSignals(True)
        self.scene_combo.clear()
        from gui.services.project_workspace import list_scene_templates

        for meta in list_scene_templates():
            name = meta.get("name") or meta.get("id") or "—"
            size = meta.get("artwork_size") or {}
            label = f"{name} ({size.get('width', '?')}×{size.get('height', '?')})"
            self.scene_combo.addItem(label, meta.get("id"))
        if current:
            idx = self.scene_combo.findData(current)
            if idx >= 0:
                self.scene_combo.setCurrentIndex(idx)
        self.scene_combo.blockSignals(False)

    def _populate_overview(self) -> None:
        p = self._project
        if p is None:
            return
        self._clear_layout(self._identity)
        self._clear_layout(self._summary)
        fields = [
            ("Company", p.company),
            ("Website", p.website),
            ("Domain", p.domain),
            ("Status", p.status),
            ("Created", p.created.strftime("%Y-%m-%d %H:%M")),
            ("Modified", p.modified.strftime("%Y-%m-%d %H:%M")),
            ("Selected Concept", p.selected_concept_id or "—"),
            ("Artifacts", str(len(p.artifacts))),
        ]
        for label, value in fields:
            self._identity.addRow(label, self._value_label(str(value or "—")))

        profile = self._profile()
        if profile is None:
            self._summary.addRow(
                "Research", self._value_label("No saved research yet.")
            )
            return
        summary = [
            ("Core Categories", ", ".join(profile.categories or []) or "—"),
            ("Service Area", profile.service_area or "—"),
            ("Phone", profile.phone or "—"),
            ("Years in Business", profile.years_in_business or "—"),
            ("Key Differentiators", ", ".join(profile.differentiators or []) or "—"),
            ("Key Trust Signals", ", ".join(profile.trust_signals or []) or "—"),
        ]
        for label, value in summary:
            self._summary.addRow(label, self._value_label(value))

    def _populate_research(self) -> None:
        p = self._project
        if p is None:
            return
        self._clear_layout(self._r_identity)
        self._clear_layout(self._r_services)
        self._clear_layout(self._r_evidence)
        self._clear_layout(self._r_branding)
        profile = self._profile()
        if profile is None:
            self._r_identity.addRow(
                "Research", self._value_label("No saved research.")
            )
            return
        self._r_identity.addRow(
            "Company", self._value_label(profile.company_name or p.company or "—")
        )
        self._r_identity.addRow(
            "Website", self._value_label(profile.website or p.website or "—")
        )
        self._r_identity.addRow(
            "Domain", self._value_label(profile.domain or p.domain or "—")
        )
        self._r_identity.addRow("Phone", self._value_label(profile.phone or "—"))
        self._r_identity.addRow(
            "Location", self._value_label(profile.location or "—")
        )
        self._r_identity.addRow(
            "Service Area", self._value_label(profile.service_area or "—")
        )

        services = ", ".join(profile.services or []) or "—"
        categories = ", ".join(profile.categories or []) or "—"
        self._r_services.addRow("Services", self._value_label(services))
        self._r_services.addRow("Categories", self._value_label(categories))

        self._r_evidence.addRow(
            "Differentiators",
            self._value_label(", ".join(profile.differentiators or []) or "—"),
        )
        self._r_evidence.addRow(
            "Trust Signals",
            self._value_label(", ".join(profile.trust_signals or []) or "—"),
        )
        self._r_evidence.addRow(
            "Guarantees",
            self._value_label(", ".join(profile.guarantees or []) or "—"),
        )
        self._r_evidence.addRow(
            "Awards", self._value_label(", ".join(profile.awards or []) or "—")
        )
        self._r_evidence.addRow(
            "Certifications",
            self._value_label(", ".join(profile.certifications or []) or "—"),
        )
        self._r_evidence.addRow(
            "Years in Business", self._value_label(profile.years_in_business or "—")
        )

        colors = ", ".join(profile.colors or []) or "—"
        brand_line = f"Brand Colors: {colors}"
        if profile.logo is not None and profile.logo.path:
            brand_line += f"  |  Logo: {os.path.basename(str(profile.logo.path))}"
        self._r_branding.addRow("Branding", self._value_label(brand_line))

    def _populate_concepts(self) -> None:
        p = self._project
        if p is None:
            return
        self._clear_layout(self._concepts_layout)
        self.override_headline.setEnabled(True)
        self.override_cta.setEnabled(True)
        self.generate_button.setEnabled(True)

        # Populate override fields from saved user_overrides.
        self.override_headline.setText(p.user_overrides.get("headline", ""))
        self.override_cta.setText(p.user_overrides.get("cta", ""))
        active = []
        if p.user_overrides.get("headline"):
            active.append("headline")
        if p.user_overrides.get("cta"):
            active.append("CTA")
        self.override_note.setText(
            f"Active overrides: {', '.join(active) or 'none'}. "
            "Source concepts are never modified."
        )

        from gui.services.project_workspace import ProjectWorkspaceService
        from gui.widgets.concept_card import ConceptCard

        svc = ProjectWorkspaceService(store=self._ctrl_store())
        concepts = svc.all_ad_concepts(p)
        if not concepts:
            empty = QLabel(
                "No concepts saved for this project.", self._concepts_container
            )
            empty.setObjectName("emptyState")
            self._concepts_layout.addWidget(empty)
            return

        artworks = {a.concept_id: a for a in p.artifacts if a.artifact_type == "artwork"}
        for concept in concepts:
            thumb = ""
            artifact = artworks.get(concept.concept_id)
            if artifact is not None:
                thumb = svc.resolve_artifact_path(p, artifact)
            card = ConceptCard(
                concept,
                selected=(concept.concept_id == p.selected_concept_id),
                thumbnail_path=thumb,
                parent=self._concepts_container,
            )
            card.clicked.connect(self.open_concept_requested.emit)
            self._concepts_layout.addWidget(card)

    def _populate_artifacts(self) -> None:
        p = self._project
        if p is None:
            return
        self._clear_layout(self._artwork_layout)
        self._clear_layout(self._mockups_layout)

        from gui.services.project_workspace import ProjectWorkspaceService
        from gui.widgets.artifact_card import ArtifactCard

        svc = ProjectWorkspaceService(store=self._ctrl_store())
        artworks = [a for a in p.artifacts if a.artifact_type == "artwork"]
        mockups = [a for a in p.artifacts if a.artifact_type == "mockup"]

        if not artworks:
            empty = QLabel("No artwork generated yet.", self._artwork_container)
            empty.setObjectName("emptyState")
            self._artwork_layout.addWidget(empty)
        for artifact in artworks:
            card = self._build_artifact_card(artifact, svc)
            self._artwork_layout.addWidget(card)

        if not mockups:
            empty = QLabel("No physical mockups yet.", self._mockups_container)
            empty.setObjectName("emptyState")
            self._mockups_layout.addWidget(empty)
        for artifact in mockups:
            card = self._build_artifact_card(artifact, svc)
            self._mockups_layout.addWidget(card)

    def _build_artifact_card(self, artifact, svc) -> QFrame:
        from gui.widgets.artifact_card import ArtifactCard

        path = svc.resolve_artifact_path(self._project, artifact)
        card = ArtifactCard(artifact, image_path=path, parent=self._artwork_container)
        card.open_image.connect(self.open_image_requested.emit)
        card.open_folder.connect(self.open_folder_requested.emit)
        return card

    def _populate_history(self) -> None:
        p = self._project
        if p is None:
            return
        self._clear_layout(self._history_layout)
        if not p.history:
            empty = QLabel("No project history yet.", self._history_container)
            empty.setObjectName("emptyState")
            self._history_layout.addWidget(empty)
            return
        for entry in p.history:
            timestamp = entry.timestamp.strftime("%Y-%m-%d %H:%M")
            text = f"{timestamp}  [{entry.event_type}]  {entry.message}"
            row = QLabel(text, self._history_container)
            row.setObjectName("historyRow")
            row.setWordWrap(True)
            self._history_layout.addWidget(row)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _ctrl_store(self):
        """Return the store backing the controller/service (for populating)."""
        if self._controller is not None:
            svc = self._controller.service
            if svc is not None:
                return svc.store
        return None

    def _profile(self):
        if self._project is None:
            return None
        from gui.services.project_workspace import ProjectWorkspaceService

        svc = ProjectWorkspaceService(store=self._ctrl_store())
        return svc.hydrate_brand_profile(self._project)

    def _value_label(self, text: str) -> QLabel:
        label = QLabel(str(text), self)
        label.setObjectName("projectMeta")
        label.setWordWrap(True)
        return label

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()