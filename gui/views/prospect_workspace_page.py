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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.models.prospect import Prospect

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
    "contact",
    "ready",
)


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
        side.setFixedWidth(260)
        layout = QVBoxLayout(side)
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

        layout.addStretch(1)

        count_lbl = QLabel("Overview", side)
        count_lbl.setObjectName("projectMeta")
        layout.addWidget(count_lbl)
        self.summary_label = QLabel("0 prospects", side)
        self.summary_label.setObjectName("emptyState")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        return side

    def _build_main_area(self) -> QWidget:
        main = QWidget(self)
        layout = QVBoxLayout(main)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search_input = QLineEdit(main)
        self.search_input.setPlaceholderText("Search company / domain...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search_input, 1)

        self.import_button = QPushButton("Import CSV", main)
        self.import_button.setObjectName("primaryButton")
        self.import_button.clicked.connect(self._on_import)
        toolbar.addWidget(self.import_button)

        self.add_button = QPushButton("Add Prospect", main)
        self.add_button.clicked.connect(self._on_add)
        toolbar.addWidget(self.add_button)

        self.edit_button = QPushButton("Edit", main)
        self.edit_button.clicked.connect(self._on_edit)
        toolbar.addWidget(self.edit_button)

        self.archive_button = QPushButton("Archive", main)
        self.archive_button.clicked.connect(self._on_archive)
        toolbar.addWidget(self.archive_button)

        self.research_button = QPushButton("Start Research", main)
        self.research_button.setEnabled(False)
        toolbar.addWidget(self.research_button)

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
        layout.addWidget(self.table, stretch=1)

        return main
    # ------------------------------------------------------------------
    # Controller wiring
    # ------------------------------------------------------------------

    def set_controller(self, controller: "ProspectController") -> None:
        """Attach a controller and wire its signals to this page."""
        self._controller = controller
        controller.prospects_changed.connect(self.refresh)
        controller.error_message.connect(self._show_error)
        self._populate_filter_options()
        self.load()
        self.refresh()

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
        """Select a prospect by id (if present in the current table)."""
        self._selected_id = prospect_id
        self.refresh()

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
                p.status,
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
        self.summary_label.setText(
            f"{total} total prospects\n"
            f"{readable} research-ready\n"
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
            self.status_filter.addItem(status, status)
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
        self._update_actions()

    def _update_actions(self) -> None:
        has_selection = self.table.currentRow() >= 0
        self.edit_button.setEnabled(has_selection)
        self.archive_button.setEnabled(has_selection)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Prospects", str(message))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _status_filter_value(self) -> str:
        return str(self.status_filter.currentData() or _STATUS_ALL)

    def _category_filter_value(self) -> str:
        return str(self.category_filter.currentData() or _CATEGORY_ALL)


def _location_text(p: Prospect) -> str:
    parts = [part for part in (p.city, p.state) if part]
    return ", ".join(parts) or ""


def _matches_search(p: Prospect, query: str) -> bool:
    q = query.lower()
    return (
        q in p.company_name.lower()
        or q in (p.domain or "").lower()
        or q in (p.website or "").lower()
    )