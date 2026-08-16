"""Sprint 5A Prospects workspace page (Qt view).

A basic page to inspect and manage imported prospects. It is deliberately a
thin view: it reads state through the
:class:`~gui.controllers.prospect_controller.ProspectController` and calls
controller methods for mutations. All business logic and persistence live in
the Qt-free service layer; widgets never write JSON directly and never import
CSV files by themselves (that is the service's job).

Layout:
- LEFT / FILTERS: status combo, category combo, a compact summary.
- MAIN TABLE: Company, Domain/Website, Category, City/State, Status,
  Primary Contact, Research Ready.
- ACTIONS: Import CSV, Add Prospect, Edit Prospect, Archive.

This is NOT a CRM pipeline — only prospect-record lifecycle is managed here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Optional

from PySide6.QtCore import QDate, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.models.prospect import (
    PRIORITIES,
    PRIORITY_LABELS,
    WORKFLOW_STATUSES,
    WORKFLOW_STATUS_LABELS,
    Prospect,
)
from gui.services.workflow_presentation import format_status

if TYPE_CHECKING:
    from gui.controllers.prospect_controller import ProspectController

logger = logging.getLogger(__name__)

_STATUS_ALL = "ALL"
_CATEGORY_ALL = "ALL"

# Display columns in the main table.
_COLUMNS = (
    "company",
    "domain",
    "category",
    "location",
    "status",
    "research",
    "contact",
    "ready",
)

# Research queue table columns.
_QUEUE_COLUMNS = (
    "company",
    "website",
    "status",
    "attempts",
    "last error",
    "project",
    "updated",
)


class _FlowLayout(QLayout):
    """Minimal responsive flow layout: items wrap to additional lines when the
    available width is insufficient (Qt does not ship QFlowLayout)."""

    def __init__(self, parent: QWidget | None = None, hspacing: int = 8, vspacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = hspacing
        self._v_spacing = vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        ml = self.contentsMargins().left() + self.contentsMargins().right()
        mt = self.contentsMargins().top() + self.contentsMargins().bottom()
        return size + QSize(ml, mt)

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        for item in self._items:
            wid = item.widget()
            if wid is not None and not wid.isVisible():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class _ProspectEditorDialog(QDialog):
    """Create/edit dialog for a single prospect (manual editor)."""

    def __init__(
        self,
        controller: "ProspectController",
        prospect: Optional[Prospect] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._prospect = prospect
        self.setWindowTitle("Edit Prospect" if prospect else "Add Prospect")
        self.resize(520, 520)
        self._build_ui()
        if prospect is not None:
            self._populate(prospect)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        self.f_company = QLineEdit(self)
        self.f_website = QLineEdit(self)
        self.f_phone = QLineEdit(self)
        self.f_email = QLineEdit(self)
        self.f_city = QLineEdit(self)
        self.f_state = QLineEdit(self)
        self.f_category = QLineEdit(self)
        self.f_contact_name = QLineEdit(self)
        self.f_contact_title = QLineEdit(self)
        self.f_notes = QLineEdit(self)
        self.f_tags = QLineEdit(self)

        form.addRow("Company*", self.f_company)
        form.addRow("Website", self.f_website)
        form.addRow("Phone", self.f_phone)
        form.addRow("Email", self.f_email)
        form.addRow("City", self.f_city)
        form.addRow("State", self.f_state)
        form.addRow("Category", self.f_category)
        form.addRow("Contact Name", self.f_contact_name)
        form.addRow("Contact Title", self.f_contact_title)
        form.addRow("Notes", self.f_notes)
        form.addRow("Tags (comma)", self.f_tags)
        root.addLayout(form)

        self._error_label = QLabel("", self)
        self._error_label.setStyleSheet("color: #e74c3c;")
        self._error_label.setWordWrap(True)
        root.addWidget(self._error_label)

        buttons = QDialogButtonBox(self)
        save_btn = buttons.addButton(
            "Save", QDialogButtonBox.ButtonRole.AcceptRole
        )
        save_btn.setObjectName("primaryButton")
        buttons.addButton(
            QDialogButtonBox.StandardButton.Cancel
        )
        save_btn.clicked.connect(self._do_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _populate(self, prospect: Prospect) -> None:
        self.f_company.setText(prospect.company_name)
        self.f_website.setText(prospect.website)
        self.f_phone.setText(prospect.phone)
        self.f_email.setText(prospect.email)
        self.f_city.setText(prospect.city)
        self.f_state.setText(prospect.state)
        self.f_category.setText(prospect.category)
        contact = prospect.primary_contact
        self.f_contact_name.setText(
            prospect.contact_name or (contact.name if contact else "")
        )
        self.f_contact_title.setText(
            prospect.contact_title or (contact.title if contact else "")
        )
        self.f_notes.setText(prospect.notes)
        self.f_tags.setText(", ".join(prospect.tags))

    def _do_save(self) -> None:
        fields = dict(
            company_name=self.f_company.text(),
            website=self.f_website.text(),
            phone=self.f_phone.text(),
            email=self.f_email.text(),
            city=self.f_city.text(),
            state=self.f_state.text(),
            category=self.f_category.text(),
            contact_name=self.f_contact_name.text(),
            contact_title=self.f_contact_title.text(),
            notes=self.f_notes.text(),
            tags=self.f_tags.text(),
        )
        if self._prospect is not None:
            result = self._controller.update_prospect(
                self._prospect.prospect_id, **fields
            )
        else:
            result = self._controller.create_prospect(**fields)
        if result is None:
            self._error_label.setText("Please fix the highlighted issue.")
            return
        self.accept()
class _ImportDialog(QDialog):
    """Simple CSV import dialog: choose file -> preview mapping -> import."""

    def __init__(
        self, controller: "ProspectController", parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self.setWindowTitle("Import Prospects CSV")
        self.resize(520, 420)
        self._content: Optional[str] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        heading = QLabel("Import Prospects from CSV", self)
        heading.setObjectName("logoTitle")
        root.addWidget(heading)

        hint = QLabel(
            "Choose a CSV with a header row. Common field names are auto-detected "
            "(company, website, phone, email, city, state, category, contact...).",
            self,
        )
        hint.setWordWrap(True)
        hint.setObjectName("logoSubtitle")
        root.addWidget(hint)

        file_row = QHBoxLayout()
        self.file_label = QLabel("No file selected", self)
        self.file_label.setObjectName("projectMeta")
        choose_btn = QPushButton("Choose File...", self)
        choose_btn.clicked.connect(self._choose_file)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(choose_btn)
        root.addLayout(file_row)

        map_heading = QLabel("Recognized Column Mapping", self)
        map_heading.setObjectName("emptyState")
        root.addWidget(map_heading)
        self.mapping_label = QLabel("Select a file to preview mapping.", self)
        self.mapping_label.setObjectName("projectMeta")
        self.mapping_label.setWordWrap(True)
        root.addWidget(self.mapping_label)

        self.result_label = QLabel("", self)
        self.result_label.setObjectName("emptyState")
        self.result_label.setWordWrap(True)
        root.addWidget(self.result_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close, self
        )
        self.import_btn = buttons.addButton(
            "Import", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.import_btn.setEnabled(False)
        self.import_btn.setObjectName("primaryButton")
        buttons.rejected.connect(self.reject)
        self.import_btn.clicked.connect(self._do_import)
        root.addWidget(buttons)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV", "", "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError as exc:
            QMessageBox.warning(self, "Import", f"Could not read file:\n{exc}")
            return
        from gui.services.prospect_csv_import import _decode_csv

        self._content = _decode_csv(raw)
        self.file_label.setText(path)
        self.result_label.setText("")
        mapping = self._controller.preview_mapping(self._content)
        if mapping:
            lines = [f"{canon}  <-  {hdr}" for canon, hdr in mapping.items()]
            self.mapping_label.setText("\n".join(lines))
            self.import_btn.setEnabled("company_name" in mapping)
            if "company_name" not in mapping:
                self.mapping_label.setText(
                    "No company-name column found. "
                    + ("\n".join(lines) if lines else "")
                )
        else:
            self.mapping_label.setText(
                "No recognized columns. Check that the CSV has a header row."
            )
            self.import_btn.setEnabled(False)

    def _do_import(self) -> None:
        if not self._content:
            return
        result = self._controller.import_csv(self._content)
        if result is None:
            return
        self.result_label.setText(
            f"Total {result.rows_total} | Imported {result.imported} | "
            f"Merged {result.merged} | Invalid {result.invalid} | "
            f"Skipped {result.skipped} | Possible dup {result.possible_duplicates}"
        )
        self._content = None
        self.accept()
class ProspectWorkspacePage(QWidget):
    """The prospects workspace: filters + table + actions."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._controller: Optional["ProspectController"] = None
        self._prospects: List[Prospect] = []
        self._selected_id: Optional[str] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(16)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_main_area(), stretch=1)

    def _build_sidebar(self) -> QFrame:
        side = QFrame(self)
        side.setObjectName("workspaceSidebar")
        side.setMinimumWidth(240)
        side.setMaximumWidth(320)
        side.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(side)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget(scroll)
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(10)

        heading = QLabel("Prospects", side)
        heading.setObjectName("logoTitle")
        layout.addWidget(heading)

        sub = QLabel("Businesses we may sell advertising to.", side)
        sub.setObjectName("logoSubtitle")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        layout.addSpacing(6)
        status_lbl = QLabel("Status", side)
        status_lbl.setObjectName("projectMeta")
        layout.addWidget(status_lbl)
        self.status_filter = QComboBox(side)
        self.status_filter.currentIndexChanged.connect(self._on_filter_changed)
        layout.addWidget(self.status_filter)

        category_lbl = QLabel("Category", side)
        category_lbl.setObjectName("projectMeta")
        layout.addWidget(category_lbl)
        self.category_filter = QComboBox(side)
        self.category_filter.currentIndexChanged.connect(self._on_filter_changed)
        layout.addWidget(self.category_filter)

        layout.addSpacing(8)

        # Sprint 5E: Location enrichment section
        loc_lbl = QLabel("Location", side)
        loc_lbl.setObjectName("projectMeta")
        layout.addWidget(loc_lbl)

        self.location_display = QLabel("", side)
        self.location_display.setObjectName("emptyState")
        self.location_display.setWordWrap(True)
        layout.addWidget(self.location_display)

        self.resolve_location_button = QPushButton("Resolve Location", side)
        self.resolve_location_button.clicked.connect(self._on_resolve_location)
        self.resolve_location_button.setEnabled(False)
        layout.addWidget(self.resolve_location_button)

        layout.addSpacing(8)

        # Sprint 5F: Opportunity overview section
        opp_lbl = QLabel("Opportunity", side)
        opp_lbl.setObjectName("projectMeta")
        layout.addWidget(opp_lbl)

        self.opportunity_overview = QLabel("", side)
        self.opportunity_overview.setObjectName("emptyState")
        self.opportunity_overview.setWordWrap(True)
        layout.addWidget(self.opportunity_overview)

        self.open_project_btn = QPushButton("Open Project", side)
        self.open_project_btn.clicked.connect(self._on_open_best_project)
        self.open_project_btn.setEnabled(False)
        layout.addWidget(self.open_project_btn)

        self.view_store_btn = QPushButton("View Store", side)
        self.view_store_btn.clicked.connect(self._on_view_best_store)
        self.view_store_btn.setEnabled(False)
        layout.addWidget(self.view_store_btn)

        layout.addSpacing(8)

        # Sprint 5G: Sales Follow-Up panel
        followup_lbl = QLabel("Sales Follow-Up", side)
        followup_lbl.setObjectName("projectMeta")
        layout.addWidget(followup_lbl)

        self.workflow_status_combo = QComboBox(side)
        self.workflow_status_combo.addItem("—", "")
        for ws in WORKFLOW_STATUSES:
            self.workflow_status_combo.addItem(WORKFLOW_STATUS_LABELS[ws], ws)
        layout.addWidget(self.workflow_status_combo)

        self.workflow_priority_combo = QComboBox(side)
        for pr in PRIORITIES:
            self.workflow_priority_combo.addItem(PRIORITY_LABELS[pr], pr)
        layout.addWidget(self.workflow_priority_combo)

        self.workflow_next_action = QLineEdit(side)
        self.workflow_next_action.setPlaceholderText("Next action...")
        layout.addWidget(self.workflow_next_action)

        date_row = QHBoxLayout()
        self.workflow_date_check = QCheckBox("Due", side)
        self.workflow_date_check.setChecked(False)
        self.workflow_date_check.stateChanged.connect(self._on_workflow_date_check_changed)
        date_row.addWidget(self.workflow_date_check)
        self.workflow_date_edit = QDateEdit(side)
        self.workflow_date_edit.setCalendarPopup(True)
        self.workflow_date_edit.setEnabled(False)
        date_row.addWidget(self.workflow_date_edit, 1)
        layout.addLayout(date_row)

        self.workflow_notes = QTextEdit(side)
        self.workflow_notes.setPlaceholderText("Notes...")
        self.workflow_notes.setMaximumHeight(70)
        layout.addWidget(self.workflow_notes)

        self.workflow_save_btn = QPushButton("Save Follow-Up", side)
        self.workflow_save_btn.setObjectName("primaryButton")
        self.workflow_save_btn.clicked.connect(self._on_save_workflow)
        layout.addWidget(self.workflow_save_btn)

        count_lbl = QLabel("Overview", side)
        count_lbl.setObjectName("projectMeta")
        layout.addWidget(count_lbl)
        self.summary_label = QLabel("0 prospects", side)
        self.summary_label.setObjectName("emptyState")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        layout.addStretch(1)

        return side

    def _build_main_area(self) -> QWidget:
        main = QWidget(self)
        layout = QVBoxLayout(main)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(10)
        main.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.primary_actions_label = QLabel("Primary workflow", main)
        self.primary_actions_label.setObjectName("previewHeading")
        layout.addWidget(self.primary_actions_label)

        toolbar = QVBoxLayout()
        toolbar.setSpacing(8)
        primary_toolbar = QHBoxLayout()
        primary_toolbar.setSpacing(8)
        self.search_input = QLineEdit(main)
        self.search_input.setPlaceholderText("Search company / domain...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.refresh)
        self.search_input.setMinimumWidth(180)
        primary_toolbar.addWidget(self.search_input, 1)

        self.import_button = QPushButton("Import CSV", main)
        self.import_button.setObjectName("primaryButton")
        self.import_button.clicked.connect(self._on_import)
        primary_toolbar.addWidget(self.import_button)

        self.add_button = QPushButton("Add Prospect", main)
        self.add_button.clicked.connect(self._on_add)
        primary_toolbar.addWidget(self.add_button)

        self.edit_button = QPushButton("Edit", main)
        self.edit_button.clicked.connect(self._on_edit)
        primary_toolbar.addWidget(self.edit_button)

        self.archive_button = QPushButton("Archive", main)
        self.archive_button.clicked.connect(self._on_archive)
        primary_toolbar.addWidget(self.archive_button)

        primary_toolbar.addStretch(1)
        toolbar.addLayout(primary_toolbar)
        layout.addLayout(toolbar)

        self.table = QTableWidget(main)
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(
            [c.replace("_", " ").title() for c in _COLUMNS]
        )
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.setMinimumHeight(120)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        content_splitter = QSplitter(Qt.Orientation.Vertical, main)
        content_splitter.setChildrenCollapsible(False)
        content_splitter.setHandleWidth(6)
        content_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        table_container = QWidget(content_splitter)
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.table)

        lower_splitter = QSplitter(Qt.Orientation.Vertical, content_splitter)
        lower_splitter.setChildrenCollapsible(False)
        lower_splitter.setHandleWidth(6)
        research_panel = self._build_research_panel(main)
        recommendation_panel = self._build_recommendation_panel(main)
        lower_splitter.addWidget(research_panel)
        lower_splitter.addWidget(recommendation_panel)
        lower_splitter.setStretchFactor(0, 2)
        lower_splitter.setStretchFactor(1, 1)
        lower_splitter.setSizes([320, 240])

        lower_container = QWidget(content_splitter)
        lower_layout = QVBoxLayout(lower_container)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.setSpacing(0)
        self.lower_content_scroll = QScrollArea(lower_container)
        self.lower_content_scroll.setWidgetResizable(True)
        self.lower_content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.lower_content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lower_content_scroll.setWidget(lower_splitter)
        lower_layout.addWidget(self.lower_content_scroll)

        content_splitter.addWidget(table_container)
        content_splitter.addWidget(lower_container)
        content_splitter.setStretchFactor(0, 2)
        content_splitter.setStretchFactor(1, 2)
        content_splitter.setSizes([280, 400])

        self.main_content_splitter = content_splitter
        self.research_recommendation_splitter = lower_splitter
        layout.addWidget(content_splitter, stretch=1)
        return main

    def _build_research_actions(self, parent: QWidget) -> QWidget:
        container = QWidget(parent)
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        row = QVBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        primary_group = QWidget(container)
        primary = _FlowLayout(primary_group, hspacing=8, vspacing=8)

        self.queue_button = QPushButton("Queue Selected", primary_group)
        self.queue_button.clicked.connect(self._on_queue_selected)
        primary.addWidget(self.queue_button)

        self.queue_all_button = QPushButton("Queue All Ready", primary_group)
        self.queue_all_button.clicked.connect(self._on_queue_all)
        primary.addWidget(self.queue_all_button)

        primary.addWidget(QLabel("Next", primary_group))
        self.research_next_spin = QSpinBox(primary_group)
        self.research_next_spin.setRange(1, 25)
        self.research_next_spin.setValue(1)
        self.research_next_spin.setMinimumWidth(72)
        primary.addWidget(self.research_next_spin)

        self.run_button = QPushButton("Research Next N", primary_group)
        self.run_button.setObjectName("primaryButton")
        self.run_button.clicked.connect(self._on_research_next)
        primary.addWidget(self.run_button)

        self.review_button = QPushButton("Campaign Review", primary_group)
        self.review_button.clicked.connect(self._on_open_campaign_review)
        primary.addWidget(self.review_button)
        row.addWidget(primary_group)

        secondary_group = QWidget(container)
        secondary = _FlowLayout(secondary_group, hspacing=8, vspacing=8)

        self.advanced_actions_badge = QLabel("Advanced queue controls", secondary_group)
        self.advanced_actions_badge.setObjectName("projectMeta")
        secondary.addWidget(self.advanced_actions_badge)

        self.retry_button = QPushButton("Retry Failed", secondary_group)
        self.retry_button.clicked.connect(self._on_retry_failed)
        secondary.addWidget(self.retry_button)

        self.cancel_button = QPushButton("Cancel Selected", secondary_group)
        self.cancel_button.clicked.connect(self._on_cancel_selected)
        secondary.addWidget(self.cancel_button)

        self.stop_button = QPushButton("Stop After Current", secondary_group)
        self.stop_button.clicked.connect(self._on_stop_after_current)
        secondary.addWidget(self.stop_button)

        self.open_project_button = QPushButton("Open Project", secondary_group)
        self.open_project_button.clicked.connect(self._on_open_project)
        secondary.addWidget(self.open_project_button)
        row.addWidget(secondary_group)

        self.research_actions_container = container
        return container

    def _build_research_panel(self, parent: QWidget) -> QWidget:
        """Research Queue panel: summary counts, active progress, queue table."""
        panel = QFrame(parent)
        panel.setObjectName("workspaceSidebar")
        root = QVBoxLayout(panel)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        head = QHBoxLayout()
        title = QLabel("Research Queue", panel)
        title.setObjectName("logoTitle")
        head.addWidget(title)
        head.addStretch(1)

        self.research_counts_label = QLabel("Queued 0 | Running 0 | Done 0", panel)
        self.research_counts_label.setObjectName("projectMeta")
        head.addWidget(self.research_counts_label)
        root.addLayout(head)

        self.research_progress_label = QLabel("No active job.", panel)
        self.research_progress_label.setObjectName("emptyState")
        self.research_progress_label.setWordWrap(True)
        root.addWidget(self.research_progress_label)

        self.status_label = QLabel("", panel)
        self.status_label.setObjectName("projectMeta")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.research_actions_container = self._build_research_actions(panel)
        root.addWidget(self.research_actions_container)

        self.queue_table = QTableWidget(panel)
        self.queue_table.setColumnCount(len(_QUEUE_COLUMNS))
        self.queue_table.setHorizontalHeaderLabels(list(_QUEUE_COLUMNS))
        self.queue_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.queue_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.queue_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.queue_table.setMinimumHeight(140)
        self.queue_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.queue_table.itemSelectionChanged.connect(self._on_queue_selection_changed)
        root.addWidget(self.queue_table, stretch=1)

        return panel
    # ------------------------------------------------------------------
    # Sprint 5D: Store recommendations panel
    # ------------------------------------------------------------------

    def _build_recommendation_panel(self, parent: QWidget) -> QFrame:
        panel = QFrame(parent)
        panel.setObjectName("workspaceSidebar")
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Recommended Stores", panel)
        title.setObjectName("logoTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.rec_limit_combo = QComboBox(panel)
        self.rec_limit_combo.addItem("Top 3", 3)
        self.rec_limit_combo.addItem("Top 5", 5)
        self.rec_limit_combo.currentIndexChanged.connect(self._on_rec_limit_changed)
        header.addWidget(self.rec_limit_combo)

        self.rec_refresh_btn = QPushButton("Refresh", panel)
        self.rec_refresh_btn.clicked.connect(self._on_refresh_recommendations)
        header.addWidget(self.rec_refresh_btn)
        layout.addLayout(header)

        self.rec_cards_container = QWidget(panel)
        self.rec_content = QVBoxLayout(self.rec_cards_container)
        self.rec_content.setSpacing(8)
        self.rec_content.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.rec_cards_container)

        self.rec_empty_label = QLabel(
            "Select a researched prospect to see store recommendations.", panel
        )
        self.rec_empty_label.setObjectName("emptyState")
        self.rec_empty_label.setWordWrap(True)
        self.rec_content.addWidget(self.rec_empty_label)
        return panel

    def _on_rec_limit_changed(self, *_args) -> None:
        if self._controller is None:
            return
        limit = self.rec_limit_combo.currentData() or 3
        self._controller.set_rec_limit(limit)
    def _refresh_recommendations(self) -> None:
        """Rebuild recommendation cards from controller."""
        while self.rec_content.count():
            item = self.rec_content.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        if self._controller is None:
            w = QLabel("Select a researched prospect to see store recommendations.")
            w.setObjectName("emptyState")
            w.setWordWrap(True)
            self.rec_content.addWidget(w)
            return

        recs = self._controller.recommendations
        if not recs:
            w = QLabel("No eligible store recommendations for this prospect.")
            w.setObjectName("emptyState")
            w.setWordWrap(True)
            self.rec_content.addWidget(w)
            return

        for idx, rec in enumerate(recs):
            card = self._build_recommendation_card(idx, rec)
            self.rec_content.addWidget(card)

    def _build_recommendation_card(self, idx: int, rec) -> QFrame:
        """Build a single store recommendation card."""
        card = QFrame()
        card.setObjectName("recCard")
        card.setStyleSheet(
            "QFrame#recCard { border: 1px solid #333; "
            "border-radius: 6px; padding: 8px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Row 1: Store name + score badge
        row1 = QHBoxLayout()
        name = f"#{idx + 1} {rec.retailer_name} #{rec.store_number}"
        if rec.city:
            name += f" \u2014 {rec.city}"
        name_label = QLabel(name)
        name_label.setObjectName("logoTitle")
        row1.addWidget(name_label)
        row1.addStretch(1)

        score_badge = QLabel(f"Score {rec.score}")
        score_badge.setStyleSheet(
            "background: #1a472a; color: #4CAF50; border-radius: 4px; "
            "padding: 2px 8px; font-weight: bold;"
        )
        row1.addWidget(score_badge)
        layout.addLayout(row1)

        # Row 2: Placement name + availability
        row2 = QHBoxLayout()
        pl_label = QLabel(rec.placement_name)
        pl_label.setObjectName("projectMeta")
        row2.addWidget(pl_label)
        row2.addStretch(1)

        avail_label = QLabel("AVAILABLE")
        avail_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        row2.addWidget(avail_label)
        layout.addLayout(row2)

        # Row 3: Stats
        row3 = QHBoxLayout()
        stats = []
        if rec.weekly_traffic:
            stats.append(f"{rec.weekly_traffic:,} shoppers/week")
        if rec.distance_miles is not None:
            stats.append(f"{rec.distance_miles:.1f} mi")
        if rec.price_display:
            stats.append(rec.price_display)
        for s in stats:
            lbl = QLabel(s)
            lbl.setObjectName("projectMeta")
            row3.addWidget(lbl)
        row3.addStretch(1)
        layout.addLayout(row3)

        # Row 4: Why this fits
        if rec.reasons:
            rlbl = QLabel("Why this fits")
            rlbl.setObjectName("projectMeta")
            layout.addWidget(rlbl)
        # Row 5: Actions
        actions = QHBoxLayout()
        if rec.project_id:
            open_btn = QPushButton("Open Project")
            open_btn.clicked.connect(
                lambda checked=False, r=rec: (
                    self._controller.open_recommendation_project(r)
                    if self._controller else None
                )
            )
            actions.addWidget(open_btn)

        view_btn = QPushButton("View Opportunity")
        view_btn.clicked.connect(
            lambda checked=False, r=rec: self._show_status(
                f"Opportunity: {r.opportunity_id[:12]}... | "
                f"{r.placement_name} | {r.location_name}"
            )
        )
        actions.addWidget(view_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        return card


    def _on_refresh_recommendations(self) -> None:
        if self._controller is None:
            return
        self._controller.refresh_recommendations()

    # ------------------------------------------------------------------
    # Controller wiring
    # ------------------------------------------------------------------

    def set_controller(self, controller: "ProspectController") -> None:
        """Attach a controller and wire its signals to this page."""
        self._controller = controller
        controller.prospects_changed.connect(self.refresh)
        controller.error_message.connect(self._show_error)
        controller.status_message.connect(self._show_status)
        research = controller.research
        research.queue_changed.connect(self._refresh_research_panel)
        research.counts_changed.connect(self._apply_research_counts)
        research.progress.connect(self._on_research_progress)
        research.running_changed.connect(self._on_research_running)
        research.status_message.connect(self._show_status)
        # Sprint 5D: recommendation panel
        controller.recommendations_changed.connect(self._refresh_recommendations)
        # Sprint 5E: location enrichment
        controller.enrichment_changed.connect(self._refresh_location_display)
        # Sprint 5F: opportunity snapshot
        controller.opportunity_snapshot_changed.connect(self._refresh_opportunity_overview)
        # Sprint 5G: sales follow-up workflow
        controller.workflow_changed.connect(self._populate_workflow_panel)
        self._populate_filter_options()
        self.load()
        self.refresh()
        self._refresh_research_panel()
        self._populate_workflow_panel()

    def get_selected_prospect_id(self) -> Optional[str]:
        """Return the currently selected prospect id (row-based)."""
        row = self.table.currentRow()
        if row < 0 or row >= len(self._prospects):
            return self._selected_id
        return self._prospects[row].prospect_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load prospects through the controller (no crash on empty store)."""
        if self._controller is None:
            return
        self._controller.load()

    def refresh(self, *_args) -> None:
        """Re-read the current prospect list through filters + search combo."""
        if self._controller is None:
            self._prospects = []
        else:
            status = self._status_filter_value()
            category = self._category_filter_value()
            rows = self._controller.list_prospects()
            if status != _STATUS_ALL:
                rows = [p for p in rows if p.status == status]
            if category != _CATEGORY_ALL:
                rows = [
                    p
                    for p in rows
                    if (p.category or "").lower() == category.lower()
                ]
            query = self.search_input.text().strip()
            if query:
                rows = [p for p in rows if _matches_search(p, query)]
            self._prospects = rows
        self._render_table()
        self._update_summary()

    def select_prospect(self, prospect_id: Optional[str]) -> None:
        """Select a prospect by id (if present in the current table).

        Sprint 5H: this is the entry point used by the Follow-Up Queue to open a
        prospect in this workspace. In addition to selecting the correct row, it
        makes the controller selection (which refreshes the recommendation and
        opportunity snapshot via signals) and populates the persisted 5G workflow
        state so the workspace is fully ready for the user.
        """
        self._selected_id = prospect_id
        if self._controller is not None and prospect_id:
            self._controller.select(prospect_id)
        self.refresh()
        self._populate_workflow_panel()
        self._refresh_location_display()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_table(self) -> None:
        self.table.setRowCount(len(self._prospects))
        for row_idx, p in enumerate(self._prospects):
            contact = p.primary_contact
            contact_text = contact.name if contact else ""
            if contact and contact.name and (contact.email or contact.phone):
                contact_text += " (" + (contact.email or contact.phone) + ")"
            values = [
                p.company_name,
                p.domain or p.website,
                p.category,
                _location_text(p),
                format_status(p.status),
                format_status(_prospect_research_label(p)),
                contact_text,
                "Yes" if p.is_ready_for_research() else "No",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, p.prospect_id)
                self.table.setItem(row_idx, col, item)
        self.table.resizeColumnsToContents()

    def _update_summary(self) -> None:
        total = len(self._controller.list_prospects()) if self._controller else 0
        readable = sum(1 for p in self._prospects if p.is_ready_for_research())
        if total == 0:
            self.summary_label.setText("No prospects yet.\nImport a CSV or add your first prospect.")
            return
        self.summary_label.setText(
            f"{total} total prospects\n"
            f"{readable} ready for research\n"
            f"{len(self._prospects)} shown"
        )

    def _populate_filter_options(self) -> None:
        if self._controller is None:
            return
        self.status_filter.blockSignals(True)
        self.category_filter.blockSignals(True)
        self.status_filter.clear()
        self.category_filter.clear()
        self.status_filter.addItem("All Statuses", _STATUS_ALL)
        for status in self._controller.statuses():
            self.status_filter.addItem(format_status(status), status)
        self.category_filter.addItem("All Categories", _CATEGORY_ALL)
        for category in self._controller.categories():
            self.category_filter.addItem(category, category)
        self.status_filter.blockSignals(False)
        self.category_filter.blockSignals(False)
# ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_filter_changed(self, *_args) -> None:
        self.refresh()

    def _on_import(self) -> None:
        if self._controller is None:
            return
        dialog = _ImportDialog(self._controller, self)
        dialog.exec()

    def _on_add(self) -> None:
        if self._controller is None:
            return
        dialog = _ProspectEditorDialog(self._controller, None, self)
        dialog.exec()

    def _on_edit(self) -> None:
        if self._controller is None:
            return
        prospect_id = self.get_selected_prospect_id()
        if not prospect_id:
            return
        prospect = self._controller.get_prospect(prospect_id)
        if prospect is None:
            return
        dialog = _ProspectEditorDialog(self._controller, prospect, self)
        dialog.exec()

    def _on_archive(self) -> None:
        if self._controller is None:
            return
        prospect_id = self.get_selected_prospect_id()
        if not prospect_id:
            self._show_error("Select a prospect to archive.")
            return
        self._controller.archive_prospect(prospect_id)

    def _on_selection_changed(self) -> None:
        prospect_id = self.get_selected_prospect_id()
        if prospect_id:
            self._selected_id = prospect_id
            if self._controller:
                self._controller.select(prospect_id)
        self._update_actions()
        self._refresh_location_display()
        self._populate_workflow_panel()

    def _update_actions(self) -> None:
        has_selection = self.table.currentRow() >= 0
        self.edit_button.setEnabled(has_selection)
        self.archive_button.setEnabled(has_selection)
        self.queue_button.setEnabled(has_selection)
        self.open_project_button.setEnabled(has_selection)
        self.review_button.setEnabled(True)

    def _on_open_campaign_review(self) -> None:
        self._show_status("Open Campaign Review from Generate once mockups are available.")

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Prospects", str(message))

    # ------------------------------------------------------------------
    # Sprint 5B: research queue handlers
    # ------------------------------------------------------------------

    def _research_controller(self):
        """Return the research controller (or None when unattached)."""
        if self._controller is None:
            return None
        return getattr(self._controller, "research", None)

    def _show_status(self, message: str) -> None:
        if getattr(self, "status_label", None) is not None:
            self.status_label.setText(str(message))

    def _refresh_research_panel(self) -> None:
        """Populate the Research Queue table + counts from the controller."""
        research = self._research_controller()
        if research is None:
            return
        jobs = research.list_jobs()
        companies: Dict[str, str] = {}
        if self._controller is not None:
            for pr in self._controller.list_prospects():
                companies[pr.prospect_id] = pr.company_name
        self.queue_table.setRowCount(len(jobs))
        for row_idx, job in enumerate(jobs):
            updated = job.completed_at or job.started_at or job.created_at
            values = [
                companies.get(job.prospect_id, job.prospect_id),
                job.website,
                job.status,
                str(job.attempt_count),
                job.last_error or "",
                (job.project_id or "")[:8],
                updated,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, job.job_id)
                elif col == 5:
                    item.setData(Qt.ItemDataRole.UserRole, job.project_id or "")
                self.queue_table.setItem(row_idx, col, item)
        self.queue_table.resizeColumnsToContents()
        self._apply_research_counts(research.counts())

    def _apply_research_counts(self, counts: object) -> None:
        counts = counts or {}
        if isinstance(counts, dict):
            self.research_counts_label.setText(
                f"Queued {counts.get('queued', 0)} | Running {counts.get('running', 0)} | "
                f"Succeeded {counts.get('succeeded', 0)} | Failed {counts.get('failed', 0)} | "
                f"Retry {counts.get('retry_pending', 0)}"
            )

    def _on_research_progress(self, stage: str, company: str) -> None:
        self.research_progress_label.setText(f"{company}: {stage}...")

    def _on_research_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        if running:
            self.research_progress_label.setText("Research in progress...")

    def _on_queue_selected(self) -> None:
        research = self._research_controller()
        if research is None:
            return
        prospect_id = self.get_selected_prospect_id()
        if not prospect_id:
            self._show_status("Select a prospect to queue.")
            return
        research.enqueue(prospect_id)

    def _on_queue_all(self) -> None:
        research = self._research_controller()
        if research is None:
            return
        research.enqueue_all()

    def _on_research_next(self) -> None:
        research = self._research_controller()
        if research is None:
            return
        count = self.research_next_spin.value() if self.research_next_spin else 1
        research.research_next(count, concurrency=1)

    def _on_retry_failed(self) -> None:
        research = self._research_controller()
        if research is None:
            return
        research.retry_failed()

    def _on_cancel_selected(self) -> None:
        research = self._research_controller()
        if research is None:
            return
        job_id = self._selected_queue_job_id()
        if job_id:
            research.cancel(job_id)
        else:
            self._show_status("Select a queued job to cancel.")

    def _on_stop_after_current(self) -> None:
        research = self._research_controller()
        if research is None:
            return
        research.stop_after_current()

    def _on_open_project(self) -> None:
        if self._controller is None:
            return
        project_id = self._selected_queue_project_id()
        if not project_id:
            prospect_id = self.get_selected_prospect_id()
            if prospect_id:
                project_id = self._project_id_for_prospect(prospect_id)
        if project_id:
            self._controller.open_project(project_id)
        else:
            self._show_status("No project available for the selected prospect.")

    def _on_queue_selection_changed(self) -> None:
        self.cancel_button.setEnabled(bool(self._selected_queue_job_id()))
        self.open_project_button.setEnabled(
            bool(self._selected_queue_project_id())
        )

    def _selected_queue_job_id(self) -> Optional[str]:
        row = self.queue_table.currentRow()
        if row < 0:
            return None
        item = self.queue_table.item(row, 0)
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selected_queue_project_id(self) -> Optional[str]:
        row = self.queue_table.currentRow()
        if row < 0:
            return None
        item = self.queue_table.item(row, 5)
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _project_id_for_prospect(self, prospect_id: str) -> str:
        research = self._research_controller()
        if research is None:
            return ""
        for job in research.list_jobs():
            if job.prospect_id == prospect_id and job.project_id:
                return job.project_id
        return ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _status_filter_value(self) -> str:
        return str(self.status_filter.currentData() or _STATUS_ALL)

    def _category_filter_value(self) -> str:
        return str(self.category_filter.currentData() or _CATEGORY_ALL)


    # ------------------------------------------------------------------
    # Sprint 5E: Location enrichment UI handlers
    # ------------------------------------------------------------------

    def _on_resolve_location(self) -> None:
        """Trigger geocoding enrichment for the selected prospect."""
        if self._controller is None:
            self._show_error("No controller attached.")
            return
        self._controller.enrich_location_for_selected()

    def _refresh_location_display(self) -> None:
        """Update the location display in the sidebar."""
        if self._controller is None:
            self.location_display.setText("")
            self.resolve_location_button.setEnabled(False)
            return

        prospect = self._controller.get_selected()
        if prospect is None:
            self.location_display.setText("(select a prospect)")
            self.resolve_location_button.setEnabled(False)
            return

        # Build display text
        lines = []
        addr = _location_text(prospect)
        if addr:
            lines.append(f"Address: {addr}")
        if prospect.latitude is not None and prospect.longitude is not None:
            lines.append(
                f"Coordinates: {prospect.latitude:.4f}, {prospect.longitude:.4f}"
            )
            geo = getattr(prospect, "geocode_metadata", None) or {}
            source = geo.get("source", "Unknown")
            lines.append(f"Source: {source.title()}")
        else:
            lines.append("Coordinates: not resolved")
            lines.append("Source: unknown")

        self.location_display.setText("\n".join(lines))
        self.resolve_location_button.setEnabled(True)

    # ------------------------------------------------------------------
    # Sprint 5F: Opportunity overview display
    # ------------------------------------------------------------------

    def _refresh_opportunity_overview(self) -> None:
        """Update the opportunity overview section in the sidebar from snapshot."""
        if self._controller is None:
            self.opportunity_overview.setText("")
            self.open_project_btn.setEnabled(False)
            self.view_store_btn.setEnabled(False)
            return

        snap = self._controller.snapshot
        if snap is None or snap.is_empty:
            self.opportunity_overview.setText("(select a prospect)")
            self.open_project_btn.setEnabled(False)
            self.view_store_btn.setEnabled(False)
            return

        lines = []
        lines.append(f"Research     {snap.research_status}")
        lines.append(f"Location     {snap.location_status}")
        lines.append(f"Opportunity  {snap.match_strength}")

        if snap.best_retailer and snap.best_location_name:
            lines.append("")
            lines.append("Best Store")
            display_name = snap.best_location_name
            if snap.best_store is not None and snap.best_store.store_number:
                display_name = f"{snap.best_retailer} #{snap.best_store.store_number}"
            lines.append(display_name)

        if snap.distance_miles is not None:
            lines.append(f"Distance     {snap.distance_miles:.1f} mi")
        else:
            lines.append("Distance     unavailable")

        if snap.weekly_traffic is not None:
            lines.append(f"Wkly Traffic {snap.weekly_traffic:,}")

        if snap.price_display:
            lines.append(f"Price        {snap.price_display}")

        if snap.best_match_score > 0:
            lines.append(f"Score        {snap.best_match_score}")

        if snap.best_placement_name:
            lines.append(f"Best Plcmnt  {snap.best_placement_name}")

        # Why This Fits (first few reasons)
        if snap.reasons:
            lines.append("")
            lines.append("Why This Fits")
            for reason in snap.reasons[:4]:
                lines.append(f"  • {reason}")

        self.opportunity_overview.setText("\n".join(lines))
        self.open_project_btn.setEnabled(snap.project_available)
        self.view_store_btn.setEnabled(bool(snap.best_location_id))

    def _on_open_best_project(self) -> None:
        """Open the project associated with the best store."""
        if self._controller is None:
            return
        snap = self._controller.snapshot
        if snap and snap.project_id:
            self._controller.open_project(snap.project_id)
        else:
            self._show_status("No project available.")

    def _on_view_best_store(self) -> None:
        """Navigate to inventory workspace and select the best store location."""
        if self._controller is None:
            return
        snap = self._controller.snapshot
        if snap and snap.best_location_id:
            self._controller.view_store(snap.best_location_id)
        else:
            self._show_status("No store selected.")

    # ------------------------------------------------------------------
    # Sprint 5G: Sales follow-up workflow UI handlers
    # ------------------------------------------------------------------

    def _set_workflow_enabled(self, enabled: bool) -> None:
        """Enable or disable all workflow input controls together."""
        self.workflow_status_combo.setEnabled(enabled)
        self.workflow_priority_combo.setEnabled(enabled)
        self.workflow_next_action.setEnabled(enabled)
        self.workflow_date_check.setEnabled(enabled)
        self.workflow_date_edit.setEnabled(enabled and self.workflow_date_check.isChecked())
        self.workflow_notes.setEnabled(enabled)
        self.workflow_save_btn.setEnabled(enabled)

    def _populate_workflow_panel(self) -> None:
        """Load the selected prospect's workflow state into the sidebar."""
        if self._controller is None:
            self._set_workflow_enabled(False)
            return

        prospect = self._controller.get_selected()
        if prospect is None:
            self.workflow_status_combo.setCurrentIndex(0)
            self.workflow_priority_combo.setCurrentIndex(
                self.workflow_priority_combo.findData("NORMAL")
            )
            self.workflow_next_action.setText("")
            self.workflow_date_check.setChecked(False)
            self.workflow_date_edit.setDate(QDate.currentDate())
            self.workflow_notes.setPlainText("")
            self._set_workflow_enabled(False)
            return

        self._set_workflow_enabled(True)

        status_index = self.workflow_status_combo.findData(prospect.workflow_status)
        if status_index >= 0:
            self.workflow_status_combo.setCurrentIndex(status_index)
        else:
            self.workflow_status_combo.setCurrentIndex(0)

        priority_index = self.workflow_priority_combo.findData(prospect.priority)
        if priority_index >= 0:
            self.workflow_priority_combo.setCurrentIndex(priority_index)
        else:
            self.workflow_priority_combo.setCurrentIndex(
                self.workflow_priority_combo.findData("NORMAL")
            )

        self.workflow_next_action.setText(prospect.next_action)

        if prospect.next_action_date:
            try:
                from datetime import date
                parsed = date.fromisoformat(prospect.next_action_date)
                self.workflow_date_edit.setDate(
                    QDate(parsed.year, parsed.month, parsed.day)
                )
                self.workflow_date_check.setChecked(True)
            except (TypeError, ValueError):
                self.workflow_date_check.setChecked(False)
                self.workflow_date_edit.setDate(QDate.currentDate())
        else:
            self.workflow_date_check.setChecked(False)
            self.workflow_date_edit.setDate(QDate.currentDate())

        self.workflow_notes.setPlainText(prospect.workflow_notes)

    def _on_workflow_date_check_changed(self, *_args) -> None:
        self.workflow_date_edit.setEnabled(
            self.workflow_date_check.isChecked()
        )

    def _on_save_workflow(self) -> None:
        """Persist the workflow fields for the currently selected prospect."""
        if self._controller is None:
            self._show_error("No controller attached.")
            return

        prospect_id = self.get_selected_prospect_id()
        if not prospect_id:
            self._show_status("Select a prospect to save follow-up.")
            return

        status = self.workflow_status_combo.currentData()
        priority = self.workflow_priority_combo.currentData()
        next_action = self.workflow_next_action.text()
        notes = self.workflow_notes.toPlainText()

        if self.workflow_date_check.isChecked():
            qdate = self.workflow_date_edit.date()
            next_action_date = qdate.toString("yyyy-MM-dd")
        else:
            next_action_date = None

        self._controller.update_workflow(
            prospect_id,
            status=status if status else None,
            priority=priority if priority else None,
            next_action=next_action,
            next_action_date=next_action_date,
            notes=notes,
        )


def _location_text(p: Prospect) -> str:
    parts = [part for part in (p.city, p.state) if part]
    return ", ".join(parts) or ""


def _prospect_research_label(p: Prospect) -> str:
    """High-level research display value for the prospects table.

    Uses the existing ``Prospect.research_status`` value when set; otherwise
    falls back to a READY / NOT_READY label derived deterministically from the
    prospect's website/domain (no second status model).
    """
    status = (p.research_status or "").strip()
    if status:
        return status
    return "READY" if p.is_ready_for_research() else "NOT_READY"


def _matches_search(p: Prospect, query: str) -> bool:
    q = query.lower()
    return (
        q in p.company_name.lower()
        or q in (p.domain or "").lower()
        or q in (p.website or "").lower()
    )