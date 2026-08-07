"""Mockup details panel widget for the BillboardAI GUI.

Sprint 4B Phase C: full editable creative workspace (headline, CTA, company,
template). Read-only: website, quality, created, elapsed (future). Edits emit
concept_fields_changed(dict) → controller → Project.update_selected_concept()
→ debounced ReRenderWorker (local render_context pipeline, no scraper/AI).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.models.mockup_concept import MockupConcept
from gui.models.mockup_result import MockupResult
from gui.widgets.quality_badge import QualityBadge

_EMPTY_TEXT = "Generate your first billboard mockup."
_NOT_AVAILABLE = "Not Available"


class MockupDetailsPanel(QFrame):
    """Creative editor for the selected mockup concept.

    All editable fields update the Project → render_context → re-render
    pipeline instantly (debounced). Only emits signals; controller owns state.
    """

    concept_fields_changed = Signal(dict)
    replace_logo_requested = Signal()
    remove_logo_override_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("detailsPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._suppress_signals = False
        self._build_ui()
        self.clear()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        heading = QLabel("Mockup Details", self)
        heading.setObjectName("previewHeading")
        layout.addWidget(heading)

        self.empty_label = QLabel(_EMPTY_TEXT, self)
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        self.form = QFormLayout()
        self.form.setSpacing(8)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.quality_badge = QualityBadge(self)

        # Editable fields (Phase C)
        self.company_edit = QLineEdit(self)
        self.company_edit.setObjectName("companyEdit")
        self.company_edit.setPlaceholderText("Company name")
        self.company_edit.editingFinished.connect(self._on_company_finished)

        self.headline_edit = QLineEdit(self)
        self.headline_edit.setObjectName("headlineEdit")
        self.headline_edit.setPlaceholderText("Headline")
        self.headline_edit.editingFinished.connect(self._on_headline_finished)

        self.cta_edit = QLineEdit(self)
        self.cta_edit.setObjectName("ctaEdit")
        self.cta_edit.setPlaceholderText("Call to action")
        self.cta_edit.editingFinished.connect(self._on_cta_finished)

        self.template_combo = QComboBox(self)
        self.template_combo.setObjectName("templateCombo")
        for display, value in [
            ("Contractor", "contractor"),
            ("Dentist", "dentist"),
            ("Realtor", "realtor"),
        ]:
            self.template_combo.addItem(display, value)
        self.template_combo.currentIndexChanged.connect(self._on_template_changed)

        self.created_value = QLabel(self)
        self.website_value = QLabel(self)  # read-only (future)

        # Logo replacement buttons (Sprint 4B Phase D)
        self.replace_logo_button = QPushButton("Replace Logo", self)
        self.replace_logo_button.setObjectName("secondaryButton")
        self.replace_logo_button.clicked.connect(self.replace_logo_requested.emit)
        self.remove_logo_button = QPushButton("Remove Logo Override", self)
        self.remove_logo_button.setObjectName("secondaryButton")
        self.remove_logo_button.clicked.connect(self.remove_logo_override_requested.emit)

        self.form.addRow("Company", self.company_edit)
        self.form.addRow("Quality", self.quality_badge)
        self.form.addRow("Headline", self.headline_edit)
        self.form.addRow("CTA", self.cta_edit)
        self.form.addRow("Template", self.template_combo)
        self.form.addRow("Created", self.created_value)
        self.form.addRow("Website", self.website_value)  # read-only placeholder

        layout.addLayout(self.form)

        # Logo buttons (Sprint 4B Phase D) - after form for better UX
        button_layout = QVBoxLayout()
        button_layout.setSpacing(8)
        button_layout.addWidget(self.replace_logo_button)
        button_layout.addWidget(self.remove_logo_button)
        layout.addLayout(button_layout)

    def _on_company_finished(self) -> None:
        if self._suppress_signals:
            return
        text = self.company_edit.text().strip()
        self.concept_fields_changed.emit({"company_name": text})

    def _on_headline_finished(self) -> None:
        if self._suppress_signals:
            return
        text = self.headline_edit.text().strip()
        self.concept_fields_changed.emit({"headline": text})

    def _on_cta_finished(self) -> None:
        if self._suppress_signals:
            return
        text = self.cta_edit.text().strip()
        self.concept_fields_changed.emit({"cta": text})

    def _on_template_changed(self, index: int) -> None:
        if self._suppress_signals or index < 0:
            return
        value = self.template_combo.currentData()
        if value:
            self.concept_fields_changed.emit({"template": str(value)})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_result(self, result: MockupResult) -> None:
        """Populate from legacy MockupResult (limited editability)."""
        self.empty_label.hide()
        self.form.setRowVisible(0, bool(result.company_name))
        self.form.setRowVisible(1, result.quality_score > 0)
        self.form.setRowVisible(2, True)
        self.form.setRowVisible(3, bool(result.cta))
        self.form.setRowVisible(4, False)  # template
        self.form.setRowVisible(5, False)  # created
        self.form.setRowVisible(6, False)  # website

        self._set_company(result.company_name or "")
        self.quality_badge.set_score(result.quality_score)
        self._set_headline(result.headline or "")
        self._set_cta(result.cta or "")
        self._set_template("contractor")  # default for legacy
        self.created_value.setText(_NOT_AVAILABLE)
        self.website_value.setText(result.website or _NOT_AVAILABLE)
        self.company_edit.setEnabled(True)
        self.headline_edit.setEnabled(True)
        self.cta_edit.setEnabled(True)
        self.template_combo.setEnabled(False)  # legacy results lock template
        self.replace_logo_button.setEnabled(False)
        self.remove_logo_button.setEnabled(False)

    def set_concept(self, concept: MockupConcept) -> None:
        """Populate from MockupConcept (full editor)."""
        self.empty_label.hide()
        self.form.setRowVisible(0, True)
        self.form.setRowVisible(1, True)
        self.form.setRowVisible(2, True)
        self.form.setRowVisible(3, True)
        self.form.setRowVisible(4, True)
        self.form.setRowVisible(5, True)
        self.form.setRowVisible(6, bool(concept.extra.get("source_url")))

        self._set_company(concept.company_name or "")
        self.quality_badge.set_score(concept.quality_score)
        self._set_headline(concept.headline or "")
        self._set_cta(concept.cta or "")
        self._set_template(concept.template or "contractor")
        self.created_value.setText(
            concept.created_at.strftime("%Y-%m-%d %H:%M")
        )
        self.website_value.setText(
            concept.extra.get("source_url") or _NOT_AVAILABLE
        )
        self.company_edit.setEnabled(True)
        self.headline_edit.setEnabled(True)
        self.cta_edit.setEnabled(True)
        self.template_combo.setEnabled(True)
        self.replace_logo_button.setEnabled(True)
        self.remove_logo_button.setEnabled(True)

    def clear(self) -> None:
        """Reset to the empty state."""
        self.empty_label.show()
        for row in range(self.form.rowCount()):
            self.form.setRowVisible(row, False)
        self._set_company("")
        self._set_headline("")
        self._set_cta("")
        self._set_template("contractor")
        self.created_value.setText("")
        self.website_value.setText("")
        self.company_edit.setEnabled(False)
        self.headline_edit.setEnabled(False)
        self.cta_edit.setEnabled(False)
        self.template_combo.setEnabled(False)
        self.replace_logo_button.setEnabled(False)
        self.remove_logo_button.setEnabled(False)

    def _set_company(self, text: str) -> None:
        self._suppress_signals = True
        try:
            if self.company_edit.text() != text:
                self.company_edit.setText(text)
        finally:
            self._suppress_signals = False

    def _set_headline(self, text: str) -> None:
        self._suppress_signals = True
        try:
            if self.headline_edit.text() != text:
                self.headline_edit.setText(text)
        finally:
            self._suppress_signals = False

    def _set_cta(self, text: str) -> None:
        self._suppress_signals = True
        try:
            if self.cta_edit.text() != text:
                self.cta_edit.setText(text)
        finally:
            self._suppress_signals = False

    def _set_template(self, template: str) -> None:
        self._suppress_signals = True
        try:
            for i in range(self.template_combo.count()):
                if self.template_combo.itemData(i) == template:
                    if self.template_combo.currentIndex() != i:
                        self.template_combo.setCurrentIndex(i)
                    break
        finally:
            self._suppress_signals = False
