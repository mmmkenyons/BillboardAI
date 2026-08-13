"""Campaign review & approval workspace."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QDialog,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.views.smartlead_handoff_page import SmartleadHandoffPage


class CampaignReviewPage(QWidget):
    COL_SELECT = 0
    COL_COMPANY = 1
    COL_EMAIL = 2
    COL_TECHNICAL = 3
    COL_REVIEW = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = None
        self._bound_controller = None
        self._row_ids: list[str] = []

        layout = QVBoxLayout(self)
        heading = QLabel("Campaign Review", self)
        heading.setObjectName("previewHeading")
        layout.addWidget(heading)

        top = QHBoxLayout()
        self.filter_combo = QComboBox(self)
        self.filter_combo.addItems(["All", "Approved", "Excluded", "Needs Review", "Blocked"])
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        top.addWidget(QLabel("Filter:", self))
        top.addWidget(self.filter_combo)
        top.addStretch(1)
        self.summary_label = QLabel("", self)
        self.summary_label.setWordWrap(True)
        top.addWidget(self.summary_label, 2)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(splitter, 1)

        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        self.table = QTableWidget(0, 5, left)
        self.table.setHorizontalHeaderLabels(["Select", "Company", "Email", "Technical", "Review"])
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        left_layout.addWidget(self.table)

        bulk = QHBoxLayout()
        self.bulk_approve_button = QPushButton("Approve Selected", left)
        self.bulk_approve_button.clicked.connect(self._bulk_approve)
        bulk.addWidget(self.bulk_approve_button)
        self.bulk_exclude_button = QPushButton("Exclude Selected", left)
        self.bulk_exclude_button.clicked.connect(self._bulk_exclude)
        bulk.addWidget(self.bulk_exclude_button)
        self.bulk_needs_review_button = QPushButton("Mark Selected Needs Review", left)
        self.bulk_needs_review_button.clicked.connect(self._bulk_needs_review)
        bulk.addWidget(self.bulk_needs_review_button)
        left_layout.addLayout(bulk)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        self.identity_label = QLabel("Select a prospect to review.", right)
        self.identity_label.setWordWrap(True)
        right_layout.addWidget(self.identity_label)
        self.opportunity_label = QLabel("", right)
        self.opportunity_label.setWordWrap(True)
        right_layout.addWidget(self.opportunity_label)
        self.mockup_label = QLabel("No mockup preview available.", right)
        self.mockup_label.setWordWrap(True)
        right_layout.addWidget(self.mockup_label)
        self.subject_label = QLabel("", right)
        self.subject_label.setWordWrap(True)
        right_layout.addWidget(self.subject_label)
        self.email_body = QPlainTextEdit(right)
        self.email_body.setReadOnly(True)
        right_layout.addWidget(self.email_body, 1)
        self.issues_list = QListWidget(right)
        right_layout.addWidget(self.issues_list)
        self.note_edit = QPlainTextEdit(right)
        self.note_edit.setPlaceholderText("Review note")
        right_layout.addWidget(self.note_edit)

        actions = QHBoxLayout()
        self.approve_button = QPushButton("Approve", right)
        self.approve_button.clicked.connect(self._approve_current)
        actions.addWidget(self.approve_button)
        self.exclude_button = QPushButton("Exclude", right)
        self.exclude_button.clicked.connect(self._exclude_current)
        actions.addWidget(self.exclude_button)
        self.needs_review_button = QPushButton("Needs Review", right)
        self.needs_review_button.clicked.connect(self._needs_review_current)
        actions.addWidget(self.needs_review_button)
        self.save_note_button = QPushButton("Save Note", right)
        self.save_note_button.clicked.connect(self._save_note)
        actions.addWidget(self.save_note_button)
        right_layout.addLayout(actions)

        open_actions = QHBoxLayout()
        self.open_project_button = QPushButton("Open Project", right)
        self.open_project_button.clicked.connect(self._open_project)
        open_actions.addWidget(self.open_project_button)
        self.open_mockup_button = QPushButton("Open Mockup", right)
        self.open_mockup_button.clicked.connect(self._open_mockup)
        open_actions.addWidget(self.open_mockup_button)
        self.open_folder_button = QPushButton("Open Folder", right)
        self.open_folder_button.clicked.connect(self._open_mockup_folder)
        open_actions.addWidget(self.open_folder_button)
        self.build_package_button = QPushButton("Build Approved Package", right)
        self.build_package_button.clicked.connect(self._build_approved_package)
        open_actions.addWidget(self.build_package_button)
        self.smartlead_button = QPushButton("Prepare Smartlead Handoff", right)
        self.smartlead_button.clicked.connect(self._prepare_smartlead_handoff)
        open_actions.addWidget(self.smartlead_button)
        right_layout.addLayout(open_actions)

        self.message_label = QLabel("", self)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

    def set_controller(self, controller: object) -> None:
        if controller is self._bound_controller:
            return
        self._controller = controller
        self._bound_controller = controller
        if hasattr(controller, "rows_changed"):
            controller.rows_changed.connect(self.set_rows)
        if hasattr(controller, "selection_changed"):
            controller.selection_changed.connect(self.set_detail)
        if hasattr(controller, "summary_changed"):
            controller.summary_changed.connect(self.set_summary)
        if hasattr(controller, "status_message"):
            controller.status_message.connect(self.show_status)
        if hasattr(controller, "error_message"):
            controller.error_message.connect(self.show_error)
        if hasattr(controller, "smartlead_handoff_ready"):
            controller.smartlead_handoff_ready.connect(self._show_smartlead_handoff)
        if hasattr(controller, "refresh"):
            controller.refresh()

    def set_rows(self, rows: list[dict]) -> None:
        current = self.current_prospect_id()
        self.table.setRowCount(len(rows))
        self._row_ids = []
        for row_index, row in enumerate(rows):
            prospect_id = str(row.get("prospect_id") or "")
            self._row_ids.append(prospect_id)
            select_item = QTableWidgetItem("")
            select_item.setFlags(select_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            select_item.setCheckState(Qt.CheckState.Unchecked)
            select_item.setData(Qt.ItemDataRole.UserRole, prospect_id)
            self.table.setItem(row_index, self.COL_SELECT, select_item)
            self.table.setItem(row_index, self.COL_COMPANY, QTableWidgetItem(str(row.get("company") or "")))
            self.table.setItem(row_index, self.COL_EMAIL, QTableWidgetItem(str(row.get("email") or "")))
            self.table.setItem(row_index, self.COL_TECHNICAL, QTableWidgetItem(str(row.get("technical_status") or "")))
            self.table.setItem(row_index, self.COL_REVIEW, QTableWidgetItem(str(row.get("review_status") or "")))
        if current and current in self._row_ids:
            self.select_prospect(current)
        elif rows:
            self.select_prospect(self._row_ids[0])

    def set_detail(self, detail: dict) -> None:
        company = str(detail.get("company") or "")
        contact = str(detail.get("contact_name") or "")
        email = str(detail.get("email") or "")
        technical = str(detail.get("technical_status") or "")
        review = str(detail.get("review_status") or "")
        self.identity_label.setText(f"{company}\n{contact}\n{email}\nTechnical: {technical} | Review: {review}")
        self.opportunity_label.setText(f"Opportunity: {detail.get('opportunity_display', '')}\nCreative: {detail.get('creative_summary', '')}")
        mockup_path = str(detail.get("mockup_path") or "")
        self.mockup_label.setText(mockup_path if mockup_path else "No mockup preview available.")
        self.subject_label.setText(f"Subject: {detail.get('email_subject', '')}")
        self.email_body.setPlainText(str(detail.get("email_body") or ""))
        self.note_edit.setPlainText(str(detail.get("review_note") or ""))
        self.issues_list.clear()
        reasons = list(detail.get("technical_reasons") or [])
        warnings = list(detail.get("technical_warnings") or [])
        if not reasons and not warnings:
            self.issues_list.addItem(QListWidgetItem("No warnings or blockers."))
        for reason in reasons:
            self.issues_list.addItem(QListWidgetItem(f"BLOCKER: {reason}"))
        for warning in warnings:
            self.issues_list.addItem(QListWidgetItem(f"WARNING: {warning}"))

    def set_summary(self, summary: object) -> None:
        self.summary_label.setText(
            " | ".join(
                [
                    f"Total {getattr(summary, 'total', 0)}",
                    f"Approved {getattr(summary, 'approved', 0)}",
                    f"Excluded {getattr(summary, 'excluded', 0)}",
                    f"Needs Review {getattr(summary, 'needs_review', 0)}",
                    f"Blocked {getattr(summary, 'technically_blocked', 0)}",
                    f"Approved+Packageable {getattr(summary, 'approved_packageable', 0)}",
                ]
            )
        )

    def current_prospect_id(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, self.COL_SELECT)
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item is not None else ""

    def selected_prospect_ids(self) -> list[str]:
        selected: list[str] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_SELECT)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            prospect_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if prospect_id:
                selected.append(prospect_id)
        return selected

    def select_prospect(self, prospect_id: str) -> None:
        for row_index in range(self.table.rowCount()):
            item = self.table.item(row_index, self.COL_SELECT)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == prospect_id:
                self.table.setCurrentCell(row_index, self.COL_COMPANY)
                if self._controller is not None and hasattr(self._controller, "select"):
                    self._controller.select(prospect_id)
                return

    def show_status(self, message: str) -> None:
        self.message_label.setText(str(message or ""))

    def show_error(self, message: str) -> None:
        self.message_label.setText(str(message or ""))
        QMessageBox.warning(self, "Campaign Review", str(message or ""))

    def _on_filter_changed(self, value: str) -> None:
        if self._controller is not None and hasattr(self._controller, "set_filter"):
            self._controller.set_filter(str(value or "").replace(" ", "_").upper())

    def _on_row_selected(self) -> None:
        prospect_id = self.current_prospect_id()
        if prospect_id and self._controller is not None and hasattr(self._controller, "select"):
            self._controller.select(prospect_id)

    def _approve_current(self) -> None:
        prospect_id = self.current_prospect_id()
        if prospect_id and self._controller is not None:
            self._controller.approve(prospect_id)

    def _exclude_current(self) -> None:
        prospect_id = self.current_prospect_id()
        if prospect_id and self._controller is not None:
            self._controller.exclude(prospect_id)

    def _needs_review_current(self) -> None:
        prospect_id = self.current_prospect_id()
        if prospect_id and self._controller is not None:
            self._controller.mark_needs_review(prospect_id)

    def _save_note(self) -> None:
        prospect_id = self.current_prospect_id()
        if prospect_id and self._controller is not None:
            self._controller.save_note(prospect_id, self.note_edit.toPlainText())

    def _bulk_approve(self) -> None:
        if self._controller is not None:
            self._controller.bulk_approve(self.selected_prospect_ids())

    def _bulk_exclude(self) -> None:
        if self._controller is not None:
            self._controller.bulk_exclude(self.selected_prospect_ids())

    def _bulk_needs_review(self) -> None:
        if self._controller is not None:
            self._controller.bulk_mark_needs_review(self.selected_prospect_ids())

    def _open_project(self) -> None:
        prospect_id = self.current_prospect_id()
        if prospect_id and self._controller is not None:
            self._controller.open_project(prospect_id)

    def _open_mockup(self) -> None:
        prospect_id = self.current_prospect_id()
        if prospect_id and self._controller is not None:
            self._controller.open_mockup(prospect_id)

    def _open_mockup_folder(self) -> None:
        prospect_id = self.current_prospect_id()
        if prospect_id and self._controller is not None:
            self._controller.open_mockup_folder(prospect_id)

    def _build_approved_package(self) -> None:
        if self._controller is None:
            return
        destination = QFileDialog.getExistingDirectory(self, "Choose Approved Campaign Package Destination")
        if not destination:
            self.show_status("Approved campaign package cancelled.")
            return
        result = self._controller.build_approved_package(destination, "approved_campaign")
        if getattr(result, "success", False):
            self.show_status(result.message)

    def _prepare_smartlead_handoff(self) -> None:
        if self._controller is None:
            return
        directory = QFileDialog.getExistingDirectory(self, "Choose Approved Campaign Package Directory")
        if not directory:
            self.show_status("Smartlead handoff cancelled.")
            return
        self._controller.prepare_smartlead_handoff(directory)

    def _show_smartlead_handoff(self, result: object) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Smartlead Preflight")
        dialog.resize(900, 600)
        layout = QVBoxLayout(dialog)
        page = SmartleadHandoffPage(dialog)
        layout.addWidget(page)
        from gui.controllers.smartlead_handoff_controller import SmartleadHandoffController
        from gui.models.smartlead_connection import SmartleadConnectionSettings
        from gui.models.smartlead_publication_store import SmartleadPublicationStore
        from gui.services.smartlead_api import SmartleadApiClient
        from gui.services.smartlead_handoff import SmartleadHandoffService
        from gui.services.smartlead_publish import SmartleadPublishService

        publish_service = SmartleadPublishService(
            api_client=SmartleadApiClient(settings=SmartleadConnectionSettings()),
            receipt_store=SmartleadPublicationStore(),
        )
        controller = SmartleadHandoffController(service=SmartleadHandoffService(), publish_service=publish_service)
        page.set_controller(controller)
        controller.summary_changed.emit(getattr(result, "summary", None))
        controller.rows_changed.emit([row.to_dict() for row in getattr(result, "rows", ())])
        page.set_handoff_directory(getattr(result, "handoff_directory", ""))
        dialog.exec()