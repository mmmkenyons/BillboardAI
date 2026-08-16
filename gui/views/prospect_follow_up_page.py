"""Sprint 5H Prospect Follow-Up Queue page (Qt view).

A portfolio-level triage view over existing Prospect workflow state. This page
is read-only with respect to prospect data: filtering and sorting derive from
the authoritative ProspectStore via ProspectFollowUpService. Selecting a row
navigates into the existing Prospect Workspace.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.models.prospect import PRIORITY_LABELS, WORKFLOW_STATUS_LABELS
from gui.services.prospect_follow_up import (
    PRIORITY_FILTER_ALL,
    STATUS_FILTER_ACTIVE,
    STATUS_FILTER_ALL,
    STATUS_FILTER_CLOSED,
    TIMING_DUE_TODAY,
    TIMING_FILTER_ALL,
    TIMING_FILTER_NEEDS_ATTENTION,
    TIMING_NO_DUE_DATE,
    TIMING_OVERDUE,
    TIMING_UPCOMING,
)

if TYPE_CHECKING:
    from gui.controllers.prospect_controller import ProspectController

logger = logging.getLogger(__name__)

_COLUMNS = (
    "Company",
    "Status",
    "Priority",
    "Next Action",
    "Due",
    "Timing",
    "Location",
)

_TIMING_LABELS = {
    TIMING_OVERDUE: "Overdue",
    TIMING_DUE_TODAY: "Due Today",
    TIMING_UPCOMING: "Upcoming",
    TIMING_NO_DUE_DATE: "No Date",
}


class ProspectFollowUpPage(QWidget):
    """Portfolio triage page for prospect follow-up work."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._controller: Optional["ProspectController"] = None
        self._items: list = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("<h2>Follow-Up Queue</h2>")
        root.addWidget(title)

        # Filter toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search company, domain, next action...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_filter_changed)
        self.search_input.setMinimumWidth(220)
        toolbar.addWidget(self.search_input)

        self.status_combo = QComboBox(self)
        self.status_combo.addItem("Active", STATUS_FILTER_ACTIVE)
        self.status_combo.addItem("All", STATUS_FILTER_ALL)
        self.status_combo.addItem("Closed", STATUS_FILTER_CLOSED)
        self.status_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.status_combo)

        self.priority_combo = QComboBox(self)
        self.priority_combo.addItem("All Priorities", PRIORITY_FILTER_ALL)
        from gui.models.prospect import PRIORITIES
        for pr in PRIORITIES:
            self.priority_combo.addItem(PRIORITY_LABELS[pr], pr)
        self.priority_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.priority_combo)

        self.timing_combo = QComboBox(self)
        self.timing_combo.addItem("All Timing", TIMING_FILTER_ALL)
        self.timing_combo.addItem("Needs Attention", TIMING_FILTER_NEEDS_ATTENTION)
        self.timing_combo.addItem("Overdue", TIMING_OVERDUE)
        self.timing_combo.addItem("Due Today", TIMING_DUE_TODAY)
        self.timing_combo.addItem("Upcoming", TIMING_UPCOMING)
        self.timing_combo.addItem("No Due Date", TIMING_NO_DUE_DATE)
        self.timing_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.timing_combo)

        self.clear_button = QPushButton("Clear Filters", self)
        self.clear_button.clicked.connect(self._on_clear_filters)
        toolbar.addWidget(self.clear_button)

        toolbar.addStretch()

        self.open_button = QPushButton("Open Prospect", self)
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._on_open_selected)
        toolbar.addWidget(self.open_button)

        root.addLayout(toolbar)

        # Quick-view buttons
        quick = QHBoxLayout()
        quick.setSpacing(8)
        quick_label = QLabel("Quick views:")
        quick.addWidget(quick_label)

        self.btn_needs_attention = QPushButton("Needs Attention", self)
        self.btn_needs_attention.clicked.connect(
            lambda: self._apply_quick_view(TIMING_FILTER_NEEDS_ATTENTION)
        )
        quick.addWidget(self.btn_needs_attention)

        self.btn_overdue = QPushButton("Overdue", self)
        self.btn_overdue.clicked.connect(
            lambda: self._apply_quick_view(TIMING_OVERDUE)
        )
        quick.addWidget(self.btn_overdue)

        self.btn_due_today = QPushButton("Due Today", self)
        self.btn_due_today.clicked.connect(
            lambda: self._apply_quick_view(TIMING_DUE_TODAY)
        )
        quick.addWidget(self.btn_due_today)

        self.btn_high_priority = QPushButton("High Priority", self)
        self.btn_high_priority.clicked.connect(self._on_high_priority_quick_view)
        quick.addWidget(self.btn_high_priority)

        self.btn_all_active = QPushButton("All Active", self)
        self.btn_all_active.clicked.connect(self._on_all_active_quick_view)
        quick.addWidget(self.btn_all_active)

        self.btn_closed = QPushButton("Closed", self)
        self.btn_closed.clicked.connect(self._on_closed_quick_view)
        quick.addWidget(self.btn_closed)

        quick.addStretch()
        root.addLayout(quick)

        # Empty state
        self.empty_label = QLabel(
            "No prospects match the current filters.", self
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setVisible(False)
        root.addWidget(self.empty_label)

        # Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.table.setSortingEnabled(False)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(self._on_open_selected)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)

        # Status line
        self.status_label = QLabel("No prospects loaded.", self)
        root.addWidget(self.status_label)


    def set_controller(self, controller: "ProspectController") -> None:
        """Wire the page to a ProspectController."""
        self._controller = controller
        controller.prospects_changed.connect(self.refresh)
        controller.workflow_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Reload items from the authoritative store and render the table."""
        if self._controller is None:
            return

        try:
            items = self._controller.follow_up_service.list_items(
                status_filter=self._current_status_filter(),
                priority_filter=self._current_priority_filter(),
                timing_filter=self._current_timing_filter(),
                search_text=self.search_input.text(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Follow-Up Queue refresh failed: %s", exc)
            self._items = []
            self._render_table()
            self.status_label.setText(f"Error loading queue: {exc}")
            return

        self._items = items
        self._render_table()
        self._update_status()

    def _render_table(self) -> None:
        """Populate the table from self._items without side effects."""
        self.table.clearContents()
        self.table.setRowCount(len(self._items))

        if not self._items:
            self.empty_label.setVisible(True)
            self.table.setVisible(False)
            self.open_button.setEnabled(False)
            return

        self.empty_label.setVisible(False)
        self.table.setVisible(True)

        for row, item in enumerate(self._items):
            self.table.setItem(row, 0, self._text_item(item.company_name))
            status_label = WORKFLOW_STATUS_LABELS.get(
                item.workflow_status, item.workflow_status
            )
            self.table.setItem(row, 1, self._text_item(status_label))
            priority_label = PRIORITY_LABELS.get(item.priority, item.priority)
            self.table.setItem(row, 2, self._text_item(priority_label))
            self.table.setItem(row, 3, self._text_item(item.next_action))
            self.table.setItem(row, 4, self._text_item(
                item.next_action_date or ""
            ))
            self.table.setItem(row, 5, self._text_item(_TIMING_LABELS.get(
                item.timing_state, item.timing_state
            )))
            self.table.setItem(row, 6, self._text_item(item.location_summary))
            self.table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole, item.prospect_id
            )

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )

    def _text_item(self, text: str) -> QTableWidgetItem:
        """Create a non-editable table item."""
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _update_status(self) -> None:
        """Update the status line below the table."""
        count = len(self._items)
        if count == 0:
            self.status_label.setText(
                "No prospects match the current filters."
            )
        else:
            self.status_label.setText(
                f"Showing {count} prospect{'s' if count != 1 else ''}."
            )


    def _current_status_filter(self) -> str:
        return self.status_combo.currentData() or STATUS_FILTER_ACTIVE

    def _current_priority_filter(self) -> str:
        return self.priority_combo.currentData() or PRIORITY_FILTER_ALL

    def _current_timing_filter(self) -> str:
        return self.timing_combo.currentData() or TIMING_FILTER_ALL

    def _on_filter_changed(self) -> None:
        self.refresh()

    def _on_clear_filters(self) -> None:
        self.search_input.clear()
        self.status_combo.setCurrentIndex(0)
        self.priority_combo.setCurrentIndex(0)
        self.timing_combo.setCurrentIndex(0)
        self.refresh()

    def _apply_quick_view(self, timing_value: str) -> None:
        self.status_combo.setCurrentIndex(
            self.status_combo.findData(STATUS_FILTER_ACTIVE)
        )
        self.timing_combo.setCurrentIndex(
            self.timing_combo.findData(timing_value)
        )
        self.refresh()

    def _on_high_priority_quick_view(self) -> None:
        from gui.models.prospect import PRIORITY_HIGH
        self.status_combo.setCurrentIndex(
            self.status_combo.findData(STATUS_FILTER_ACTIVE)
        )
        self.priority_combo.setCurrentIndex(
            self.priority_combo.findData(PRIORITY_HIGH)
        )
        self.timing_combo.setCurrentIndex(0)
        self.refresh()

    def _on_all_active_quick_view(self) -> None:
        self._on_clear_filters()
        self.status_combo.setCurrentIndex(
            self.status_combo.findData(STATUS_FILTER_ACTIVE)
        )

    def _on_closed_quick_view(self) -> None:
        self.search_input.clear()
        self.priority_combo.setCurrentIndex(0)
        self.timing_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(
            self.status_combo.findData(STATUS_FILTER_CLOSED)
        )
        self.refresh()

    def _on_selection_changed(self) -> None:
        self.open_button.setEnabled(
            self._selected_prospect_id() is not None
        )

    def _selected_prospect_id(self) -> Optional[str]:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._items):
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        prospect_id = item.data(Qt.ItemDataRole.UserRole)
        return prospect_id if prospect_id else None

    def _on_open_selected(self) -> None:
        prospect_id = self._selected_prospect_id()
        if prospect_id is None or self._controller is None:
            return
        self._controller.open_prospect_requested.emit(prospect_id)

    def selected_prospect_id(self) -> Optional[str]:
        """Return the prospect id of the currently selected row."""
        return self._selected_prospect_id()

