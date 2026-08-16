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
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
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
        root_layout.setContentsMargins(20, 12, 20, 16)
        root_layout.setSpacing(12)

        self.header = Header(self)
        root_layout.addWidget(self.header)

        self.input_card = self._build_input_form()
        root_layout.addWidget(self.input_card, stretch=0)

        self.action_row = self._build_action_row()
        root_layout.addWidget(self.action_row)

        self.progress_panel = ProgressPanel(self)
        self.progress_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        root_layout.addWidget(self.progress_panel)

        # Home lower content owns all remaining height and is scroll-backed.
        # This keeps header / input card / generate row / progress sequential
        # and prevents the old vertical splitter from imposing a competing
        # minimum-height contract on restored windows.
        self.results_scroll_area = QScrollArea(self)
        self.results_scroll_area.setWidgetResizable(True)
        self.results_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.results_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results_scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.results_scroll_area.setMinimumHeight(0)

        results_container = QWidget(self.results_scroll_area)
        results_container.setMinimumHeight(0)
        self.results_scroll_area.setWidget(results_container)
        results_layout = QVBoxLayout(results_container)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(10)

        self.concept_gallery = ConceptGallery(results_container)
        self.concept_gallery.setObjectName("conceptGalleryArea")
        self.concept_gallery.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.concept_gallery.setMinimumHeight(60)
        self.concept_gallery.setMaximumHeight(140)
        results_layout.addWidget(self.concept_gallery, stretch=0)

        self.preview_panel = PreviewPanel(results_container)
        self.preview_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        results_layout.addWidget(self.preview_panel, stretch=1)

        bottom_row = QWidget(results_container)
        bottom_row_layout = QHBoxLayout(bottom_row)
        bottom_row_layout.setContentsMargins(0, 0, 0, 0)
        bottom_row_layout.setSpacing(10)

        self.details_panel = MockupDetailsPanel(bottom_row)
        self.details_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bottom_row_layout.addWidget(self.details_panel, 1)

        self.recent_websites = RecentWebsites(bottom_row)
        self.recent_websites.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bottom_row_layout.addWidget(self.recent_websites, 1)

        results_layout.addWidget(bottom_row, stretch=0)
        results_layout.addStretch(1)

        # Backward-compatible attribute names from the removed splitter era.
        self.content_splitter = None
        self.splitter = self.results_scroll_area
        self.results_container = results_container
        self.bottom_row = bottom_row

        root_layout.addWidget(self.results_scroll_area, stretch=1)

    def _build_input_form(self) -> QFrame:
        """Build the URL / template / output folder input section."""
        frame = QFrame(self)
        frame.setObjectName("cardFrame")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        form = QFormLayout(frame)
        form.setContentsMargins(18, 16, 18, 16)
        form.setSpacing(10)
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
        self.template_combo.setMinimumWidth(180)
        form.addRow("Template:", self.template_combo)

        # Output folder selector
        self.output_selector = OutputSelector(frame)
        form.addRow("Output folder:", self.output_selector)

        # QSizePolicy.Fixed sizes the card to the frame's sizeHint(), which can
        # under-report relative to the layout's real required height under
        # Windows font/DPI metrics and clip the last row. Derive the height from
        # the populated layout instead and pin the card to it so Website URL /
        # Template / Output Folder (incl. full field + Browse) always fit.
        form.activate()
        required = max(
            frame.sizeHint().height(),
            frame.minimumSizeHint().height(),
        )
        frame.setMinimumHeight(required)
        frame.setMaximumHeight(required)
        return frame

    def _build_action_row(self) -> QWidget:
        """Build the Generate Mockup button row."""
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.generate_button = QPushButton("Generate Mockup", container)
        self.generate_button.setObjectName("primaryButton")
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
