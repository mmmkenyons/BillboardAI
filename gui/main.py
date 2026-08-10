"""BillboardAI GUI launcher.

Run with:  python -m gui.main
"""

from __future__ import annotations

import logging
import os
import sys

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from gui.controllers.app_controller import BillboardController
from gui.controllers.inventory_controller import InventoryController
from gui.controllers.project_controller import ProjectWorkspaceController
from gui.controllers.prospect_controller import ProspectController
from gui.main_window import MainWindow
from gui.resources import APP_VERSION
from gui.resources.styles import APP_STYLESHEET

logger = logging.getLogger(__name__)

# Path where an application icon can be dropped without code changes.
ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")
ICON_CANDIDATES = ["billboardai.png", "app.png", "icon.png"]


def _load_icon() -> QIcon | None:
    """Load the application icon if one exists in assets/icons/."""
    for name in ICON_CANDIDATES:
        path = os.path.join(ICON_DIR, name)
        if os.path.isfile(path):
            return QIcon(path)
    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info("Application Started (v%s)", APP_VERSION)

    app = QApplication(sys.argv)
    app.setApplicationName("BillboardAI")
    app.setOrganizationName("BillboardAI")
    app.setApplicationVersion(APP_VERSION)
    app.setStyleSheet(APP_STYLESHEET)

    icon = _load_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    # Ensure default font works on all platforms
    font = QFont("Segoe UI", 13)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    controller = BillboardController()
    workspace_controller = ProjectWorkspaceController()
    inventory_controller = InventoryController()
    prospect_controller = ProspectController()
    window = MainWindow(
        controller,
        workspace_controller,
        inventory_controller,
        prospect_controller,
    )
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()