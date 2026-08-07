"""Application stylesheet for the BillboardAI GUI.

The stylesheet is defined here so it can be shared across the application
without being embedded in the launcher module.
"""

# ---------------------------------------------------------------------------
# Application stylesheet (professional dark theme)
# ---------------------------------------------------------------------------
APP_STYLESHEET = """
/* Global */
QWidget {
    font-family: "Segoe UI", "Arial", sans-serif;
    font-size: 13px;
    color: #e0e0e0;
    background-color: #1e1e2e;
}

/* Logo header */
#logoTitle {
    color: #ffffff;
    font-size: 26px;
    font-weight: bold;
    padding: 0px;
    margin: 0px;
}
#logoSubtitle {
    color: #a0a0b8;
    font-size: 13px;
    padding: 0px;
    margin: 0px;
}

/* Card frame (input form) */
#cardFrame {
    background-color: #282840;
    border: 1px solid #3a3a5c;
    border-radius: 8px;
}

/* Input fields */
QLineEdit, QComboBox {
    background-color: #1e1e2e;
    color: #e0e0e0;
    border: 1px solid #3a3a5c;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    min-height: 20px;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #7c5cfc;
}
QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #282840;
    border: 1px solid #3a3a5c;
    selection-background-color: #7c5cfc;
    color: #e0e0e0;
}

/* Labels (form labels) */
QLabel {
    color: #c0c0d0;
    background: transparent;
}
#previewHeading {
    font-size: 14px;
    font-weight: 600;
    color: #e0e0e0;
}
#previewPlaceholder {
    color: #808090;
    background-color: #1a1a2e;
    border: 1px dashed #3a3a5c;
    border-radius: 6px;
    padding: 20px;
}
#previewPanel {
    background-color: #282840;
    border: 1px solid #3a3a5c;
    border-radius: 8px;
}

/* Buttons */
QPushButton {
    background-color: #3a3a5c;
    color: #e0e0e0;
    border: none;
    border-radius: 6px;
    padding: 6px 18px;
    font-size: 13px;
    min-height: 28px;
}
QPushButton:hover {
    background-color: #4a4a6c;
}
QPushButton:pressed {
    background-color: #5a5a7c;
}
QPushButton:disabled {
    background-color: #2a2a40;
    color: #606070;
}

#primaryButton {
    background-color: #7c5cfc;
    color: #ffffff;
    font-size: 15px;
    font-weight: 600;
    padding: 0px 32px;
    min-height: 44px;
    border-radius: 8px;
}
#primaryButton:hover {
    background-color: #8e6cfd;
}
#primaryButton:pressed {
    background-color: #6a4ce0;
}

#secondaryButton {
    background-color: #3a3a5c;
    color: #e0e0e0;
    border: 1px solid #7c5cfc;
    padding: 6px 16px;
    min-height: 28px;
}
#secondaryButton:hover {
    background-color: #4a4a6c;
    border-color: #9a7dfd;
}
#secondaryButton:pressed {
    background-color: #2a2a40;
}

#browseButton {
    background-color: #3a3a5c;
    color: #e0e0e0;
    padding: 6px 16px;
    min-height: 28px;
}
#browseButton:hover {
    background-color: #4a4a6c;
}

/* Progress bar */
QProgressBar {
    background-color: #1e1e2e;
    border: 1px solid #3a3a5c;
    border-radius: 6px;
    text-align: center;
    color: #e0e0e0;
    font-size: 12px;
    min-height: 22px;
}
QProgressBar::chunk {
    background-color: #7c5cfc;
    border-radius: 5px;
}

/* Stage label */
#stageLabel {
    color: #a0a0b8;
    font-size: 12px;
    padding: 2px 0px;
}

/* Status label */
#statusLabel {
    color: #808090;
    font-size: 12px;
    padding: 2px 0px;
}

/* Details panel */
#detailsPanel {
    background-color: #282840;
    border: 1px solid #3a3a5c;
    border-radius: 8px;
}
#detailsPanel QLabel {
    color: #c0c0d0;
}

/* Quality badge */
#qualityBadge {
    font-weight: 600;
    padding: 2px 10px;
    border-radius: 10px;
}
#qualityBadge[qualityLevel="excellent"] {
    color: #2ecc71;
    background-color: rgba(46, 204, 113, 0.15);
}
#qualityBadge[qualityLevel="good"] {
    color: #f1c40f;
    background-color: rgba(241, 196, 15, 0.15);
}
#qualityBadge[qualityLevel="needs_improvement"] {
    color: #e67e22;
    background-color: rgba(230, 126, 34, 0.15);
}

/* Recent websites */
#recentPanel {
    background-color: #282840;
    border: 1px solid #3a3a5c;
    border-radius: 8px;
}
#recentList {
    background-color: #1e1e2e;
    border: 1px solid #3a3a5c;
    border-radius: 6px;
}
#recentList::item {
    padding: 6px 10px;
    color: #e0e0e0;
}
#recentList::item:selected {
    background-color: #7c5cfc;
    color: #ffffff;
}

/* Empty state */
#emptyState {
    color: #808090;
    font-size: 13px;
    padding: 12px;
}

/* Menu bar */
QMenuBar {
    background-color: #282840;
    color: #e0e0e0;
    border-bottom: 1px solid #3a3a5c;
}
QMenuBar::item:selected {
    background-color: #3a3a5c;
}
QMenu {
    background-color: #282840;
    color: #e0e0e0;
    border: 1px solid #3a3a5c;
}
QMenu::item:selected {
    background-color: #7c5cfc;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #606070;
}

/* Toolbar */
QToolBar {
    background-color: #282840;
    border-bottom: 1px solid #3a3a5c;
    spacing: 4px;
    padding: 4px;
}
QToolBar QToolButton {
    background-color: #3a3a5c;
    color: #e0e0e0;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
}
QToolBar QToolButton:hover {
    background-color: #4a4a6c;
}
QToolBar QToolButton:disabled {
    background-color: #2a2a40;
    color: #606070;
}

/* Status bar */
QStatusBar {
    background-color: #282840;
    color: #a0a0b8;
    border-top: 1px solid #3a3a5c;
}
QStatusBar QLabel {
    color: #a0a0b8;
    background: transparent;
}

/* Splitter */
QSplitter::handle {
    background-color: #3a3a5c;
    height: 4px;
}
"""