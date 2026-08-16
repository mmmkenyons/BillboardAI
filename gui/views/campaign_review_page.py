"""Campaign review & approval workspace."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from gui.services.workflow_presentation import format_blocker, format_status


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
        self._last_rows: list[dict] = []

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

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)
        layout.addWidget(self.splitter, 1)

        left = QWidget(self.splitter)
        left.setMinimumWidth(360)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        self.table = QTableWidget(0, 5, left)
        self.table.setHorizontalHeaderLabels(["Select", "Company", "Email", "Readiness", "Decision"])
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        left_layout.addWidget(self.table)

        bulk = QVBoxLayout()
        bulk.setSpacing(8)
        bulk_primary = QHBoxLayout()
        bulk_primary.setSpacing(8)
        self.bulk_approve_button = QPushButton("Approve Selected", left)
        self.bulk_approve_button.setObjectName("primaryButton")
        self.bulk_approve_button.clicked.connect(self._bulk_approve)
        bulk_primary.addWidget(self.bulk_approve_button)
        self.bulk_exclude_button = QPushButton("Exclude Selected", left)
        self.bulk_exclude_button.clicked.connect(self._bulk_exclude)
        bulk_primary.addWidget(self.bulk_exclude_button)
        bulk.addLayout(bulk_primary)

        bulk_secondary = QHBoxLayout()
        bulk_secondary.setSpacing(8)
        self.bulk_needs_review_button = QPushButton("Mark Selected Needs Review", left)
        self.bulk_needs_review_button.clicked.connect(self._bulk_needs_review)
        bulk_secondary.addWidget(self.bulk_needs_review_button)
        bulk_secondary.addStretch(1)
        bulk.addLayout(bulk_secondary)
        left_layout.addLayout(bulk)

        right = QWidget(self.splitter)
        right.setMinimumWidth(360)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.detail_scroll_area = QScrollArea(right)
        self.detail_scroll_area.setWidgetResizable(True)
        self.detail_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_layout.addWidget(self.detail_scroll_area)

        self.detail_content = QWidget(self.detail_scroll_area)
        self.detail_content.setMinimumWidth(360)
        self.detail_scroll_area.setWidget(self.detail_content)

        detail_layout = QVBoxLayout(self.detail_content)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(10)

        self.identity_label = QLabel("No campaign prospects are ready for review yet.", self.detail_content)
        self.identity_label.setWordWrap(True)
        detail_layout.addWidget(self.identity_label)
        self.readiness_label = QLabel("Research prospects and generate mockups first.", self.detail_content)
        self.readiness_label.setWordWrap(True)
        detail_layout.addWidget(self.readiness_label)
        self.opportunity_label = QLabel("", self.detail_content)
        self.opportunity_label.setWordWrap(True)
        detail_layout.addWidget(self.opportunity_label)
        self.mockup_label = QLabel("No mockup preview available.", self.detail_content)
        self.mockup_label.setWordWrap(True)
        detail_layout.addWidget(self.mockup_label)
        self.subject_label = QLabel("", self.detail_content)
        self.subject_label.setWordWrap(True)
        detail_layout.addWidget(self.subject_label)
        self.email_body = QPlainTextEdit(self.detail_content)
        self.email_body.setReadOnly(True)
        self.email_body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.email_body.setMinimumHeight(70)
        detail_layout.addWidget(self.email_body, 1)
        self.issues_list = QListWidget(self.detail_content)
        self.issues_list.setMinimumHeight(60)
        self.issues_list.setMaximumHeight(150)
        detail_layout.addWidget(self.issues_list)
        self.note_edit = QPlainTextEdit(self.detail_content)
        self.note_edit.setPlaceholderText("Review note")
        self.note_edit.setMinimumHeight(60)
        self.note_edit.setMaximumHeight(150)
        detail_layout.addWidget(self.note_edit)

        decision_card = QFrame(self.detail_content)
        decision_card.setObjectName("cardFrame")
        decision_layout = QVBoxLayout(decision_card)
        decision_layout.setContentsMargins(12, 12, 12, 12)
        decision_layout.setSpacing(8)
        decision_layout.addWidget(QLabel("Review Decisions", decision_card))

        actions = QVBoxLayout()
        actions.setSpacing(8)
        actions_top = QHBoxLayout()
        actions_top.setSpacing(8)
        self.approve_button = QPushButton("Approve", decision_card)
        self.approve_button.clicked.connect(self._approve_current)
        actions_top.addWidget(self.approve_button)
        self.exclude_button = QPushButton("Exclude", decision_card)
        self.exclude_button.clicked.connect(self._exclude_current)
        actions_top.addWidget(self.exclude_button)
        self.needs_review_button = QPushButton("Needs Review", decision_card)
        self.needs_review_button.clicked.connect(self._needs_review_current)
        actions_top.addWidget(self.needs_review_button)
        actions_top.addStretch(1)
        actions.addLayout(actions_top)

        actions_bottom = QHBoxLayout()
        actions_bottom.setSpacing(8)
        self.save_note_button = QPushButton("Save Note", decision_card)
        self.save_note_button.clicked.connect(self._save_note)
        actions_bottom.addWidget(self.save_note_button)
        actions_bottom.addStretch(1)
        actions.addLayout(actions_bottom)
        decision_layout.addLayout(actions)
        detail_layout.addWidget(decision_card)

        open_card = QFrame(self.detail_content)
        open_card.setObjectName("cardFrame")
        open_layout = QVBoxLayout(open_card)
        open_layout.setContentsMargins(12, 12, 12, 12)
        open_layout.setSpacing(8)
        open_layout.addWidget(QLabel("Package + Recovery Actions", open_card))

        open_actions_primary = QHBoxLayout()
        open_actions_primary.setSpacing(8)
        self.open_project_button = QPushButton("Open Project", open_card)
        self.open_project_button.clicked.connect(self._open_project)
        open_actions_primary.addWidget(self.open_project_button)
        self.open_mockup_button = QPushButton("Open Mockup", open_card)
        self.open_mockup_button.clicked.connect(self._open_mockup)
        open_actions_primary.addWidget(self.open_mockup_button)
        self.open_folder_button = QPushButton("Open Folder", open_card)
        self.open_folder_button.clicked.connect(self._open_mockup_folder)
        open_actions_primary.addWidget(self.open_folder_button)
        open_actions_primary.addStretch(1)
        open_layout.addLayout(open_actions_primary)

        open_actions_secondary = QHBoxLayout()
        open_actions_secondary.setSpacing(8)
        self.build_package_button = QPushButton("Build Campaign Package", open_card)
        self.build_package_button.setObjectName("primaryButton")
        self.build_package_button.clicked.connect(self._build_approved_package)
        open_actions_secondary.addWidget(self.build_package_button)
        self.smartlead_button = QPushButton("Prepare for Smartlead", open_card)
        self.smartlead_button.clicked.connect(self._prepare_smartlead_handoff)
        open_actions_secondary.addWidget(self.smartlead_button)
        self.open_existing_package_button = QPushButton("Open Existing Package", open_card)
        self.open_existing_package_button.clicked.connect(self._open_existing_package)
        open_actions_secondary.addWidget(self.open_existing_package_button)
        open_actions_secondary.addStretch(1)
        open_layout.addLayout(open_actions_secondary)
        detail_layout.addWidget(open_card)
        detail_layout.addStretch(1)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([480, 680])

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
        if hasattr(controller, "refresh"):
            controller.refresh()

    def set_rows(self, rows: list[dict]) -> None:
        self._last_rows = list(rows or [])
        current = self.current_prospect_id()
        self.table.setRowCount(len(rows))
        self._row_ids = []
        if not rows:
            self.identity_label.setText("No campaign prospects are ready for review yet.")
            self.readiness_label.setText("Research prospects and generate mockups first.")
            self.opportunity_label.setText("")
            self.mockup_label.setText("No mockup preview available.")
            self.subject_label.setText("")
            self.email_body.setPlainText("")
            self.note_edit.setPlainText("")
            self.issues_list.clear()
            return
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
            self.table.setItem(row_index, self.COL_TECHNICAL, QTableWidgetItem(format_status(row.get("technical_status") or "")))
            self.table.setItem(row_index, self.COL_REVIEW, QTableWidgetItem(format_status(row.get("review_status") or "")))
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
        self.identity_label.setText(f"{company}\n{contact}\n{email}".strip())
        self.readiness_label.setText(
            f"Campaign readiness: {format_status(technical)}\nDecision: {format_status(review)}"
        )
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
            self.issues_list.addItem(QListWidgetItem(f"Cannot continue: {format_blocker(reason)}"))
        for warning in warnings:
            self.issues_list.addItem(QListWidgetItem(f"Warning: {format_status(warning)}"))

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
        self._apply_package_action_state(summary)

    def _apply_package_action_state(self, summary: object) -> None:
        packageable = int(getattr(summary, "approved_packageable", 0) or 0)
        can_build = packageable > 0
        self.build_package_button.setEnabled(can_build)
        self.build_package_button.setToolTip(
            "Build a canonical approved package for the currently approved, packageable prospects."
            if can_build else
            "Approve at least one campaign-ready prospect before building a package."
        )
        has_preferred_package = False
        if self._controller is not None and hasattr(self._controller, "resolve_preferred_package_directory"):
            has_preferred_package = bool(self._controller.resolve_preferred_package_directory())
        self.smartlead_button.setEnabled(has_preferred_package)
        self.smartlead_button.setToolTip(
            "Prepare Smartlead files from the current canonical campaign package."
            if has_preferred_package else
            "No canonical package is available yet. Build a package first, or use Open Existing Package as a recovery action."
        )
        self.open_existing_package_button.setToolTip(
            "Recovery / advanced: open a previously created canonical package when you need to resume from an existing folder."
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
        if not self.build_package_button.isEnabled():
            self.show_status("Approve at least one campaign-ready prospect before building a package.")
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
        directory = ""
        if hasattr(self._controller, "resolve_preferred_package_directory"):
            directory = self._controller.resolve_preferred_package_directory()
        if directory:
            self._controller.prepare_smartlead_handoff(directory)
            return
        self.show_status("No canonical package is available yet. Build a package first, or use Open Existing Package for recovery.")

    def _open_existing_package(self) -> None:
        if self._controller is None:
            return
        directory = QFileDialog.getExistingDirectory(self, "Open Existing Approved Campaign Package")
        if not directory:
            self.show_status("Open existing package cancelled.")
            return
        self._controller.prepare_smartlead_handoff(directory)