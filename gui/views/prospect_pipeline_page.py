"""Sprint 5I Sales Pipeline / Command Center page."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.models.prospect import PRIORITY_LABELS, WORKFLOW_STATUS_LABELS
from gui.services.prospect_follow_up import TIMING_DUE_TODAY, TIMING_OVERDUE

if TYPE_CHECKING:
    from gui.controllers.prospect_controller import ProspectController

logger = logging.getLogger(__name__)


_STAGE_COLUMNS = ("Stage", "Count")
_PROSPECT_COLUMNS = ("Company", "Priority", "Next Action", "Due", "Follow-Up State")
_TIMING_LABELS = {
    TIMING_OVERDUE: "Overdue",
    TIMING_DUE_TODAY: "Due Today",
    "UPCOMING": "Upcoming",
    "NO_DUE_DATE": "No Date",
    "CLOSED": "Closed",
}


class ProspectPipelinePage(QWidget):
    """Portfolio-level Sales Pipeline / Command Center."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._controller: Optional["ProspectController"] = None
        self._summary = None
        self._stage_items: list = []
        self._selected_stage: Optional[str] = None
        # Sprint 5X.8: guards the programmatic repopulation of the prospect table
        # so that internal itemSelectionChanged churn is not mistaken for a user
        # selection and does not overwrite the authoritative prospect selection.
        self._populating = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        root.addWidget(QLabel("<h2>Sales Pipeline</h2>"))

        self.summary_grid = QGridLayout()
        self.summary_grid.setHorizontalSpacing(8)
        self.summary_grid.setVerticalSpacing(8)
        self.summary_cards = {}
        labels = (
            ("total", "Total"),
            ("active", "Active"),
            ("needs_attention", "Needs Attention"),
            ("overdue", "Overdue"),
            ("due_today", "Due Today"),
            ("won", "Won"),
        )
        for idx, (key, title) in enumerate(labels):
            card = QFrame(self)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(12, 10, 12, 10)
            heading = QLabel(title, card)
            heading.setObjectName("projectMeta")
            value = QLabel("0", card)
            value.setObjectName("logoTitle")
            layout.addWidget(heading)
            layout.addWidget(value)
            self.summary_cards[key] = value
            self.summary_grid.addWidget(card, 0, idx)
        root.addLayout(self.summary_grid)

        root.addWidget(QLabel("Stage Breakdown"))
        self.stage_table = QTableWidget(self)
        self.stage_table.setColumnCount(len(_STAGE_COLUMNS))
        self.stage_table.setHorizontalHeaderLabels(_STAGE_COLUMNS)
        self.stage_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.stage_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.stage_table.setSortingEnabled(False)
        self.stage_table.itemSelectionChanged.connect(self._on_stage_selection_changed)
        self.stage_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.stage_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.stage_table)

        detail_header = QHBoxLayout()
        self.detail_label = QLabel("Selected Stage / Prospects")
        detail_header.addWidget(self.detail_label)
        detail_header.addStretch()
        self.open_button = QPushButton("Open Prospect", self)
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_selected_prospect)
        detail_header.addWidget(self.open_button)
        root.addLayout(detail_header)

        self.prospect_table = QTableWidget(self)
        self.prospect_table.setColumnCount(len(_PROSPECT_COLUMNS))
        self.prospect_table.setHorizontalHeaderLabels(_PROSPECT_COLUMNS)
        self.prospect_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.prospect_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.prospect_table.setSortingEnabled(False)
        self.prospect_table.itemSelectionChanged.connect(self._on_prospect_selection_changed)
        self.prospect_table.doubleClicked.connect(self._open_selected_prospect)
        self.prospect_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.prospect_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.prospect_table)

        self.status_label = QLabel("No pipeline data loaded.", self)
        root.addWidget(self.status_label)

    def set_controller(self, controller: "ProspectController") -> None:
        self._controller = controller
        controller.prospects_changed.connect(self.refresh)
        controller.workflow_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        if self._controller is None:
            return
        try:
            self._summary = self._controller.pipeline_service.summary()
            self._render_summary()
            self._render_stage_table()
            if self._selected_stage is None and self._controller.pipeline_service.stage_order:
                self._selected_stage = self._controller.pipeline_service.stage_order[0]
            self._refresh_stage_detail()
        except Exception as exc:  # noqa: BLE001
            logger.error("Pipeline refresh failed: %s", exc)
            self.status_label.setText(f"Error loading pipeline: {exc}")

    def selected_prospect_id(self) -> Optional[str]:
        row = self.prospect_table.currentRow()
        if row < 0 or row >= len(self._stage_items):
            return None
        item = self.prospect_table.item(row, 0)
        if item is None:
            return None
        prospect_id = item.data(Qt.ItemDataRole.UserRole)
        return str(prospect_id) if prospect_id else None

    def _render_summary(self) -> None:
        summary = self._summary
        if summary is None:
            return
        self.summary_cards["total"].setText(str(summary.total_prospects))
        self.summary_cards["active"].setText(str(summary.active_prospects))
        self.summary_cards["needs_attention"].setText(str(summary.needs_attention_prospects))
        self.summary_cards["overdue"].setText(str(summary.overdue_prospects))
        self.summary_cards["due_today"].setText(str(summary.due_today_prospects))
        self.summary_cards["won"].setText(str(summary.won_prospects))

    def _render_stage_table(self) -> None:
        if self._controller is None or self._summary is None:
            return
        order = self._controller.pipeline_service.stage_order
        self.stage_table.setRowCount(len(order))
        for row, status in enumerate(order):
            label = WORKFLOW_STATUS_LABELS.get(status, status)
            label_item = self._text_item(label)
            label_item.setData(Qt.ItemDataRole.UserRole, status)
            self.stage_table.setItem(row, 0, label_item)
            self.stage_table.setItem(row, 1, self._text_item(str(self._summary.stage_counts.get(status, 0))))

        if self._selected_stage:
            for row in range(self.stage_table.rowCount()):
                item = self.stage_table.item(row, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == self._selected_stage:
                    self.stage_table.selectRow(row)
                    break

    def _refresh_stage_detail(self) -> None:
        if self._controller is None or self._selected_stage is None:
            self._stage_items = []
            self.prospect_table.setRowCount(0)
            return
        try:
            self._stage_items = self._controller.pipeline_service.list_stage(self._selected_stage)
        except ValueError:
            self._stage_items = []
        self.detail_label.setText(
            f"{WORKFLOW_STATUS_LABELS.get(self._selected_stage, self._selected_stage)} / Prospects"
        )
        self._render_prospect_table()

    def _render_prospect_table(self) -> None:
        self._populating = True
        try:
            self.prospect_table.clearContents()
            self.prospect_table.setRowCount(len(self._stage_items))
            for row, item in enumerate(self._stage_items):
                company = self._text_item(item.company_name)
                company.setData(Qt.ItemDataRole.UserRole, item.prospect_id)
                self.prospect_table.setItem(row, 0, company)
                self.prospect_table.setItem(row, 1, self._text_item(PRIORITY_LABELS.get(item.priority, item.priority)))
                self.prospect_table.setItem(row, 2, self._text_item(item.next_action))
                self.prospect_table.setItem(row, 3, self._text_item(item.next_action_date or ""))
                self.prospect_table.setItem(row, 4, self._text_item(_TIMING_LABELS.get(item.timing_state, item.timing_state)))
        finally:
            self._populating = False
        self.status_label.setText(f"Showing {len(self._stage_items)} prospect{'s' if len(self._stage_items) != 1 else ''}.")
        self._restore_selection_from_controller()
        self.open_button.setEnabled(self.selected_prospect_id() is not None)

    def _restore_selection_from_controller(self) -> None:
        """Restore the visible table selection from the authoritative prospect selection.

        The ProspectController owns the single source of truth for the selected
        prospect. Repopulating the pipeline table would otherwise wipe any visible
        selection (for example after Continue Campaign routes a run member with a
        Resolve Opportunity next action). Reflect the authoritative selection when
        the matching row is present in the currently displayed stage, and otherwise
        leave the visible table untouched.
        """
        if self._controller is None:
            return
        desired = self._controller.selected_id
        if not desired:
            return
        for row, item in enumerate(self._stage_items):
            if item.prospect_id == desired:
                self.prospect_table.selectRow(row)
                return

    def _on_stage_selection_changed(self) -> None:
        row = self.stage_table.currentRow()
        if row < 0:
            return
        item = self.stage_table.item(row, 0)
        if item is None:
            return
        status = item.data(Qt.ItemDataRole.UserRole)
        self._selected_stage = str(status) if status else None
        self._refresh_stage_detail()

    def _on_prospect_selection_changed(self) -> None:
        prospect_id = self.selected_prospect_id()
        self.open_button.setEnabled(prospect_id is not None)
        # Sprint 5X.8: keep the authoritative selected-prospect identity in sync
        # with the visible pipeline selection (single source of truth). Ignore the
        # selection churn caused by programmatic repopulation so a refresh does not
        # overwrite the authoritative selection with a stale row.
        if self._controller is not None and prospect_id and not self._populating:
            self._controller.select(prospect_id)

    def _open_selected_prospect(self) -> None:
        prospect_id = self.selected_prospect_id()
        if prospect_id is None or self._controller is None:
            return
        self._controller.open_prospect_requested.emit(prospect_id)

    def _text_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item