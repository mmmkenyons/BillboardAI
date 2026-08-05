"""BillboardAI GUI launcher.

Run with:  python -m gui.main
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from gui.controllers.app_controller import BillboardController
from gui.main_window import MainWindow
from gui.resources.styles import APP_STYLESHEET


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("BillboardAI")
    app.setOrganizationName("BillboardAI")
    app.setStyleSheet(APP_STYLESHEET)

    # Ensure default font works on all platforms
    font = QFont("Segoe UI", 13)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    controller = BillboardController()
    window = MainWindow(controller)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()