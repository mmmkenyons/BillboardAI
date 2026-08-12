"""Minimal Smartlead preflight workspace."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class SmartleadHandoffPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = None
        self._rows: list[dict] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Smartlead Preflight", self))

        top = QHBoxLayout()
        self.filter_combo = QComboBox(self)
        self.filter_combo.addItems(["All", "Ready", "Warning", "Blocked", "Conflict"])
        self.filter_combo.currentTextChanged.connect(self._apply_filter)
        top.addWidget(QLabel("Filter:", self))
        top.addWidget(self.filter_combo)
        top.addStretch(1)
        self.summary_label = QLabel("No preflight run yet.", self)
        top.addWidget(self.summary_label)
        layout.addLayout(top)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Prospect", "Company", "Email", "Status"])
        self.table.itemSelectionChanged.connect(self._show_selected)
        layout.addWidget(self.table)

        self.detail = QPlainTextEdit(self)
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail)

    def set_controller(self, controller: object) -> None:
        self._controller = controller
        if hasattr(controller, "summary_changed"):
            controller.summary_changed.connect(self.set_summary)
        if hasattr(controller, "rows_changed"):
            controller.rows_changed.connect(self.set_rows)
        if hasattr(controller, "status_message"):
            controller.status_message.connect(self.show_status)
        if hasattr(controller, "error_message"):
            controller.error_message.connect(self.show_status)

    def set_summary(self, summary: object) -> None:
        self.summary_label.setText(
            f"Approved: {getattr(summary, 'total_approved_rows', 0)} | "
            f"Ready: {getattr(summary, 'ready', 0)} | "
            f"Warning: {getattr(summary, 'warnings', 0)} | "
            f"Blocked: {getattr(summary, 'blocked', 0)} | "
            f"Conflict: {getattr(summary, 'conflicts', 0)}"
        )

    def set_rows(self, rows: list[dict]) -> None:
        self._rows = list(rows or [])
        self._render_rows(self._rows)

    def show_status(self, message: str) -> None:
        if message:
            self.detail.setPlainText(str(message))

    def _apply_filter(self, value: str) -> None:
        status = str(value or "All").strip().upper()
        if status == "ALL":
            self._render_rows(self._rows)
            return
        self._render_rows([row for row in self._rows if str(row.get("status") or "").upper() == status])

    def _render_rows(self, rows: list[dict]) -> None:
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            self.table.setItem(index, 0, QTableWidgetItem(str(row.get("prospect_id") or "")))
            self.table.setItem(index, 1, QTableWidgetItem(str(row.get("company") or "")))
            self.table.setItem(index, 2, QTableWidgetItem(str(row.get("email") or "")))
            self.table.setItem(index, 3, QTableWidgetItem(str(row.get("status") or "")))

    def _show_selected(self) -> None:
        row_index = self.table.currentRow()
        if row_index < 0 or row_index >= self.table.rowCount():
            return
        prospect_id_item = self.table.item(row_index, 0)
        prospect_id = prospect_id_item.text() if prospect_id_item is not None else ""
        payload = next((row for row in self._rows if str(row.get("prospect_id") or "") == prospect_id), None)
        if payload is None:
            return
        mapped = payload.get("mapped_fields") or {}
        lines = [
            f"Prospect: {payload.get('prospect_id', '')}",
            f"Status: {payload.get('status', '')}",
            f"Reason: {payload.get('reason', '')}",
            f"Warning: {payload.get('warning', '')}",
            "",
            "Mapped Fields:",
        ]
        for key, value in mapped.items():
            lines.append(f"{key}: {value}")
        self.detail.setPlainText("\n".join(lines))
