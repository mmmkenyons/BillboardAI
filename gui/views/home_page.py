"""Home page for the BillboardAI GUI.

Assembles the reusable widgets into a vertical layout where the generated
mockup preview is the visual centerpiece. A concept gallery sits above
the preview so users can switch between concepts without regenerating.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gui.models.mockup_concept import MockupConcept
from gui.models.mockup_result import MockupResult
from gui.widgets.concept_gallery import ConceptGallery
from gui.widgets.header import Header
from gui.widgets.mockup_details_panel import MockupDetailsPanel
from gui.widgets.output_selector import OutputSelector
from gui.widgets.preview_panel import PreviewPanel
from gui.widgets.progress_panel import ProgressPanel
from gui.widgets.recent_websites import RecentWebsites


class HomePage(QWidget):
    """Main home view: input form, concept gallery, preview, details."""

    TEMPLATES = [
        ("Contractor", "contractor"),
        ("Dentist", "dentist"),
        ("Realtor", "realtor"),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 16, 24, 24)
        root_layout.setSpacing(16)

        root_layout.addWidget(Header(self))
        root_layout.addWidget(self._build_input_form(), stretch=0)
        root_layout.addWidget(self._build_action_row())

        self.progress_panel = ProgressPanel(self)
        root_layout.addWidget(self.progress_panel)

        # Resizable content area: gallery / preview / details / recent websites.
        self.splitter = QSplitter(Qt.Orientation.Vertical, self)

        self.concept_gallery = ConceptGallery(self.splitter)
        self.concept_gallery.setObjectName("conceptGalleryArea")

        self.preview_panel = PreviewPanel(self.splitter)
        self.details_panel = MockupDetailsPanel(self.splitter)
        self.recent_websites = RecentWebsites(self.splitter)

        self.splitter.addWidget(self.concept_gallery)
        self.splitter.addWidget(self.preview_panel)
        self.splitter.addWidget(self.details_panel)
        self.splitter.addWidget(self.recent_websites)
        self.splitter.setStretchFactor(0, 1)  # gallery
        self.splitter.setStretchFactor(1, 4)  # preview (largest)
        self.splitter.setStretchFactor(2, 1)  # details
        self.splitter.setStretchFactor(3, 1)  # recent websites

        root_layout.addWidget(self.splitter, stretch=1)

    def _build_input_form(self) -> QFrame:
        """Build the URL / template / output folder input section."""
        frame = QFrame(self)
        frame.setObjectName("cardFrame")
        frame.setFrameShape(QFrame.Shape.StyledPanel)

        form = QFormLayout(frame)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(14)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # URL input
        self.url_input = QLineEdit(frame)
        self.url_input.setPlaceholderText("https://example.com")
        self.url_input.setClearButtonEnabled(True)
        form.addRow("Website URL:", self.url_input)

        # Template dropdown
        self.template_combo = QComboBox(frame)
        for display_name, _value in self.TEMPLATES:
            self.template_combo.addItem(display_name)
        self.template_combo.setMinimumWidth(220)
        form.addRow("Template:", self.template_combo)

        # Output folder selector
        self.output_selector = OutputSelector(frame)
        form.addRow("Output folder:", self.output_selector)

        return frame

    def _build_action_row(self) -> QWidget:
        """Build the Generate Mockup button row."""
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self.generate_button = QPushButton("Generate Mockup", container)
        self.generate_button.setObjectName("primaryButton")
        self.generate_button.setMinimumHeight(44)
        self.generate_button.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addStretch(1)
        layout.addWidget(self.generate_button)

        return container

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_result(self, result: MockupResult) -> None:
        """Populate the preview and details panels from a result."""
        self.preview_panel.set_image(result.preview_path)
        self.details_panel.set_result(result)

    def set_concept(self, concept: MockupConcept) -> None:
        """Populate the preview and details panels from a concept."""
        self.preview_panel.set_concept(concept)
        self.details_panel.set_concept(concept)

    def clear_result(self) -> None:
        """Reset the preview and details panels to their empty states."""
        self.preview_panel.clear()
        self.details_panel.clear()

    def add_concept(self, concept: MockupConcept) -> None:
        """Add a concept to the gallery and display it."""
        self.concept_gallery.add_concept(concept)
        self.set_concept(concept)

    def set_concepts(self, concepts: list[MockupConcept]) -> None:
        """Populate the gallery with concepts and select the active one."""
        self.concept_gallery.set_concepts(concepts)
        selected = next(
            (c for c in concepts if c.selected), concepts[0] if concepts else None
        )
        if selected:
            self.set_concept(selected)

    # ------------------------------------------------------------------
    # Backward-compatible attribute access
    # ------------------------------------------------------------------
    @property
    def selected_template(self) -> str:
        """Return the template value for the currently selected display name."""
        display = self.template_combo.currentText()
        for name, value in self.TEMPLATES:
            if name == display:
                return value
        return "contractor"

    @property
    def output_folder_input(self) -> QLineEdit:
        """Backward-compatible access to the output folder line edit."""
        return self.output_selector.output_folder_input

    @property
    def preview_label(self) -> QLabel:
        """Backward-compatible access to the preview placeholder label."""
        return self.preview_panel.preview_label

    @property
    def progress_bar(self) -> QProgressBar:
        """Backward-compatible access to the progress bar."""
        return self.progress_panel.progress_bar
