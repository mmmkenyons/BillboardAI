"""Home page for the BillboardAI GUI.

Assembles the reusable widgets into the main input/preview layout.
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
    QVBoxLayout,
    QWidget,
)

from gui.widgets.header import Header
from gui.widgets.output_selector import OutputSelector
from gui.widgets.preview_panel import PreviewPanel
from gui.widgets.progress_panel import ProgressPanel


class HomePage(QWidget):
    """Main home view: input form, preview, progress, and status."""

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

        # Content area: preview panel on the right, status/progress bottom.
        content_layout = QHBoxLayout()
        content_layout.setSpacing(16)

        self.preview_panel = PreviewPanel(self)
        content_layout.addWidget(self.preview_panel, stretch=3)

        root_layout.addLayout(content_layout, stretch=1)

        self.progress_panel = ProgressPanel(self)
        root_layout.addWidget(self.progress_panel)

        root_layout.addWidget(self._build_status_bar())

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

    def _build_status_bar(self) -> QWidget:
        """Build the status message label."""
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self.status_label = QLabel("Ready", container)
        self.status_label.setObjectName("statusLabel")

        layout.addWidget(self.status_label)
        return container

    # ------------------------------------------------------------------
    # Backward-compatible attribute access
    # ------------------------------------------------------------------
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