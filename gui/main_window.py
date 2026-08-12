"""BillboardAI main window.

Thin shell hosting the application views in a stacked widget, with a
professional menu bar, toolbar, status bar, and keyboard shortcuts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QToolBar,
)

from gui.resources import APP_VERSION
from gui.views.batch_page import BatchPage
from gui.views.history_page import HistoryPage
from gui.views.home_page import HomePage
from gui.views.inventory_workspace_page import InventoryWorkspacePage
from gui.views.project_list_page import ProjectBrowserPage
from gui.views.project_workspace_page import ProjectWorkspacePage
from gui.views.prospect_follow_up_page import ProspectFollowUpPage
from gui.views.prospect_pipeline_page import ProspectPipelinePage
from gui.views.prospect_workspace_page import ProspectWorkspacePage
from gui.views.settings_page import SettingsPage

if TYPE_CHECKING:
    from gui.controllers.app_controller import BillboardController
    from gui.controllers.batch_generation_controller import BatchGenerationController
    from gui.controllers.inventory_controller import InventoryController
    from gui.controllers.project_controller import ProjectWorkspaceController
    from gui.controllers.prospect_controller import ProspectController

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window for BillboardAI."""

    def __init__(
        self,
        controller: BillboardController | None = None,
        batch_controller: "BatchGenerationController | None" = None,
        workspace_controller: ProjectWorkspaceController | None = None,
        inventory_controller: "InventoryController | None" = None,
        prospect_controller: "ProspectController | None" = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"BillboardAI v{APP_VERSION}")
        self.setMinimumSize(960, 640)

        self._controller = controller
        self._batch_controller = batch_controller
        self._workspace_controller = workspace_controller
        self._inventory_controller = inventory_controller
        self._prospect_controller = prospect_controller

        self._build_ui()
        self._build_menu()
        self._build_toolbar()
        self._build_status_bar()
        self._build_shortcuts()

        if self._controller is not None:
            self._controller.attach(self)
            self.update_toolbar_state()  # Initial state for Sprint 4B toolbar

        if self._workspace_controller is not None:
            self._wire_workspace_controller()

        if self._inventory_controller is not None:
            self._wire_inventory_controller()

        if self._prospect_controller is not None:
            self._wire_prospect_controller()

        if self._batch_controller is not None:
            self._wire_batch_controller()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self._stack = QStackedWidget(self)

        self.home_page = HomePage(self._stack)
        self.settings_page = SettingsPage(self._stack)
        self.batch_page = BatchPage(self._stack)
        self.history_page = HistoryPage(self._stack)
        self.project_browser = ProjectBrowserPage(self._stack)
        self.project_workspace = ProjectWorkspacePage(self._stack)
        self.inventory_workspace = InventoryWorkspacePage(self._stack)
        self.prospects_workspace = ProspectWorkspacePage(self._stack)
        self.follow_up_page = ProspectFollowUpPage(self._stack)
        self.pipeline_page = ProspectPipelinePage(self._stack)

        self._stack.addWidget(self.home_page)
        self._stack.addWidget(self.settings_page)
        self._stack.addWidget(self.batch_page)
        self._stack.addWidget(self.history_page)
        self._stack.addWidget(self.project_browser)
        self._stack.addWidget(self.project_workspace)
        self._stack.addWidget(self.inventory_workspace)
        self._stack.addWidget(self.prospects_workspace)
        self._stack.addWidget(self.follow_up_page)
        self._stack.addWidget(self.pipeline_page)

        self._stack.setCurrentWidget(self.home_page)

        self.setCentralWidget(self._stack)

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        self.new_mockup_action = QAction("&New Mockup", self)
        self.new_mockup_action.setShortcut(QKeySequence("Ctrl+N"))
        self.new_mockup_action.triggered.connect(self._on_new_mockup)
        file_menu.addAction(self.new_mockup_action)

        self.open_output_action = QAction("&Open Output Folder", self)
        self.open_output_action.setShortcut(QKeySequence("Ctrl+O"))
        self.open_output_action.triggered.connect(self._on_open_output_folder)
        file_menu.addAction(self.open_output_action)

        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menubar.addMenu("&View")
        home_action = QAction("&Home", self)
        home_action.triggered.connect(lambda: self.show_page("home"))
        view_menu.addAction(home_action)

        projects_action = QAction("Pr&ojects", self)
        projects_action.triggered.connect(lambda: self.show_page("projects"))
        view_menu.addAction(projects_action)

        workspace_action = QAction("&Workspace", self)
        workspace_action.triggered.connect(lambda: self.show_page("workspace"))
        view_menu.addAction(workspace_action)

        inventory_action = QAction("&Inventory", self)
        inventory_action.triggered.connect(lambda: self.show_page("inventory"))
        view_menu.addAction(inventory_action)

        prospects_action = QAction("&Prospects", self)
        prospects_action.triggered.connect(lambda: self.show_page("prospects"))
        view_menu.addAction(prospects_action)

        follow_up_action = QAction("&Follow-Up", self)
        follow_up_action.triggered.connect(lambda: self.show_page("follow_up"))
        view_menu.addAction(follow_up_action)

        pipeline_action = QAction("&Pipeline", self)
        pipeline_action.triggered.connect(lambda: self.show_page("pipeline"))
        view_menu.addAction(pipeline_action)

        history_action = QAction("&History", self)
        history_action.setEnabled(False)
        view_menu.addAction(history_action)

        batch_action = QAction("&Batch", self)
        batch_action.setEnabled(False)
        view_menu.addAction(batch_action)

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        settings_action = QAction("&Settings", self)
        settings_action.setEnabled(False)
        tools_menu.addAction(settings_action)

        batch_mode_action = QAction("&Batch Mode", self)
        batch_mode_action.setEnabled(False)
        tools_menu.addAction(batch_mode_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About BillboardAI", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.toolbar_generate = QAction("Generate", self)
        self.toolbar_generate.triggered.connect(self._on_generate)
        toolbar.addAction(self.toolbar_generate)

        # Sprint 4B Phase E1: Toolbar-only actions (gallery is passive view)
        self.toolbar_new_concept = QAction("Generate New Concept", self)
        self.toolbar_new_concept.triggered.connect(self._on_generate_new_concept)
        self.toolbar_new_concept.setEnabled(False)  # Disabled until project/selection
        toolbar.addAction(self.toolbar_new_concept)

        self.toolbar_duplicate = QAction("Duplicate", self)
        self.toolbar_duplicate.triggered.connect(self._on_duplicate_concept)
        self.toolbar_duplicate.setEnabled(False)
        toolbar.addAction(self.toolbar_duplicate)

        self.toolbar_delete = QAction("Delete", self)
        self.toolbar_delete.triggered.connect(self._on_delete_concept)
        self.toolbar_delete.setEnabled(False)
        toolbar.addAction(self.toolbar_delete)

        self.toolbar_open_folder = QAction("Open Folder", self)
        self.toolbar_open_folder.triggered.connect(self._on_open_output_folder)
        toolbar.addAction(self.toolbar_open_folder)

        toolbar.addSeparator()
        settings_action = QAction("Settings", self)
        settings_action.setEnabled(False)
        toolbar.addAction(settings_action)

    def _build_status_bar(self) -> None:
        self.status_bar = self.statusBar()
        self.status_message = QLabel("Ready", self)
        self.status_bar.addWidget(self.status_message, 1)

        self.version_label = QLabel(f"Version {APP_VERSION}", self)
        self.status_bar.addPermanentWidget(self.version_label)

        self.output_folder_label = QLabel("", self)
        self.status_bar.addPermanentWidget(self.output_folder_label)

    def _build_shortcuts(self) -> None:
        # Ctrl+Enter -> Generate
        generate_shortcut = QAction(self)
        generate_shortcut.setShortcut(QKeySequence("Ctrl+Return"))
        generate_shortcut.triggered.connect(self._on_generate)
        self.addAction(generate_shortcut)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_status(self, message: str) -> None:
        """Update the status bar message."""
        self.status_message.setText(message)

    def set_output_folder_status(self, folder: str) -> None:
        """Update the output folder shown in the status bar."""
        self.output_folder_label.setText(f"Output Folder: {folder}")

    def show_page(self, page: str) -> None:
        """Switch to the named page ('home', 'settings', 'batch', 'history',
        'projects', 'workspace', 'inventory', 'prospects')."""
        pages = {
            "home": self.home_page,
            "settings": self.settings_page,
            "batch": self.batch_page,
            "history": self.history_page,
            "projects": self.project_browser,
            "workspace": self.project_workspace,
            "inventory": self.inventory_workspace,
            "prospects": self.prospects_workspace,
            "follow_up": self.follow_up_page,
            "pipeline": self.pipeline_page,
        }
        widget = pages.get(page)
        if widget is not None:
            self._stack.setCurrentWidget(widget)
            if page == "projects":
                self.refresh_project_browser()
            if page == "prospects":
                self.prospects_workspace.refresh()
            if page == "follow_up":
                self.follow_up_page.refresh()
            if page == "pipeline":
                self.pipeline_page.refresh()

    # ------------------------------------------------------------------
    # Prospect workspace wiring (Sprint 5A)
    # ------------------------------------------------------------------
    def _wire_prospect_controller(self) -> None:
        """Give the prospects page its controller (loads + refreshes).

        Sprint 5B: "Open Project" on a researched prospect navigates to the
        existing Project Workspace by calling the workspace controller.
        """
        if self._prospect_controller is None:
            return
        ctrl = self._prospect_controller
        self.prospects_workspace.set_controller(ctrl)
        self.follow_up_page.set_controller(ctrl)
        self.pipeline_page.set_controller(ctrl)
        ctrl.open_project_requested.connect(self._on_prospect_open_project)
        ctrl.open_prospect_requested.connect(self._on_open_prospect_in_workspace)
        ctrl.view_store_requested.connect(self._on_prospect_view_store)

    def _wire_batch_controller(self) -> None:
        if self._batch_controller is None:
            return
        ctrl = self._batch_controller
        self.batch_page.set_controller(ctrl)
        ctrl.open_project_requested.connect(self._on_prospect_open_project)

    def _on_open_prospect_in_workspace(self, prospect_id: str) -> None:
        """Sprint 5H: open a queue-selected prospect in the Prospect Workspace."""
        self.prospects_workspace.select_prospect(prospect_id)
        self.show_page("prospects")

    def _on_prospect_open_project(self, project_id: str) -> None:
        """Open a researched prospect's Project in the Project Workspace."""
        if self._workspace_controller is not None:
            self._workspace_controller.open_project(project_id)

    def _on_prospect_view_store(self, location_id: str) -> None:
        """Navigate to inventory workspace and select a location."""
        if self._inventory_controller is not None:
            self._inventory_controller.select("location", location_id)
            self.inventory_workspace.refresh()
        self.show_page("inventory")

    # ------------------------------------------------------------------
    # Inventory workspace wiring (Sprint 4B)
    # ------------------------------------------------------------------
    def _wire_inventory_controller(self) -> None:
        """Give the inventory page its controller (loads + refreshes)."""
        if self._inventory_controller is None:
            return
        self.inventory_workspace.set_controller(self._inventory_controller)

    # ------------------------------------------------------------------
    # Project workspace wiring (Sprint 3B)
    # ------------------------------------------------------------------
    def _wire_workspace_controller(self) -> None:
        """Connect the workspace/browser pages to their controller."""
        if self._workspace_controller is None:
            return
        ctrl = self._workspace_controller
        # Give the workspace page a reference to the controller for data queries.
        self.project_workspace.set_controller(ctrl)

        # Browser signals.
        self.project_browser.open_project_requested.connect(ctrl.open_project)
        self.project_browser.archive_requested.connect(ctrl.archive_project)
        self.project_browser.new_generate_requested.connect(
            lambda: self.show_page("home")
        )

        # Workspace signals -> controller.
        ws = self.project_workspace
        ws.back_requested.connect(ctrl.back_to_projects)
        ws.open_concept_requested.connect(ctrl.select_concept)
        ws.set_override_requested.connect(ctrl.set_override)
        ws.reset_override_requested.connect(ctrl.reset_override)
        ws.set_status_requested.connect(ctrl.set_status)
        ws.generate_mockup_requested.connect(ctrl.generate_mockup)
        ws.open_image_requested.connect(ctrl.open_file)
        ws.open_folder_requested.connect(ctrl.open_folder)

        # Controller signals -> window / pages.
        ctrl.navigate.connect(self._on_workspace_navigate)
        ctrl.project_opened.connect(self._on_workspace_project_opened)
        ctrl.project_updated.connect(lambda: self.project_workspace.refresh())
        ctrl.artifacts_changed.connect(
            lambda: self.project_workspace.refresh()
        )
        ctrl.projects_changed.connect(self.refresh_project_browser)
        ctrl.error_message.connect(self._on_workspace_error)
        ctrl.status_message.connect(self.set_status)

        # Refresh the browser with the persisted project list.
        self.refresh_project_browser()

    def _on_workspace_navigate(self, page: str) -> None:
        self.show_page(page)

    def _on_workspace_project_opened(self, project: object) -> None:
        self.project_workspace.set_project(project)  # type: ignore[arg-type]

    def _on_workspace_error(self, message: str) -> None:
        self.set_status(message)
        QMessageBox.warning(self, "Project Workspace", str(message))

    def refresh_project_browser(self) -> None:
        """Reload the project browser from the workspace controller's store."""
        if self._workspace_controller is None:
            self.project_browser.set_projects([])
            return
        try:
            projects = self._workspace_controller.list_projects()
            self.project_browser.set_projects(projects)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not refresh project browser: %s", exc)
            self.project_browser.set_projects([])

    def update_toolbar_state(self) -> None:
        """Update toolbar button enabled state based on project/selection (Sprint 4B)."""
        controller = self._controller
        if controller is None:
            has_project = False
            has_selection = False
        else:
            project = controller.project
            has_project = project is not None
            has_selection = has_project and project.get_selected_concept() is not None

        if hasattr(self, 'toolbar_new_concept'):
            self.toolbar_new_concept.setEnabled(has_project)
        if hasattr(self, 'toolbar_duplicate'):
            self.toolbar_duplicate.setEnabled(has_selection)
        if hasattr(self, 'toolbar_delete'):
            self.toolbar_delete.setEnabled(has_selection)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_generate(self) -> None:
        if self._controller is not None:
            self._controller.generate_mockup()

    def _on_generate_new_concept(self) -> None:
        """Sprint 4B Phase E1: Toolbar action for Generate New Concept."""
        if self._controller is not None:
            self._controller.generate_new_concept()

    def _on_duplicate_concept(self) -> None:
        """Toolbar action for Duplicate (controller handles)."""
        controller = self._controller
        if controller is not None and controller.project is not None:
            project = controller.project
            if project.get_selected_concept():
                selected_id = project.selected_concept_id
                if selected_id:
                    controller.duplicate_concept(selected_id)

    def _on_delete_concept(self) -> None:
        """Toolbar action for Delete (controller handles confirmation)."""
        controller = self._controller
        if controller is None:
            return
        project = controller.project
        if project is None:
            return
        if project.get_selected_concept():
            selected_id = project.selected_concept_id
            if selected_id:
                controller.delete_concept(selected_id)

    def _on_new_mockup(self) -> None:
        if self._controller is not None:
            self._controller.new_mockup()

    def _on_open_output_folder(self) -> None:
        if self._controller is not None:
            self._controller.open_output_folder()

    def _on_about(self) -> None:
        import platform
        import sys

        from PySide6.QtCore import qVersion

        QMessageBox.about(
            self,
            "About BillboardAI",
            f"<h3>BillboardAI v{APP_VERSION}</h3>"
            "<p>AI-Powered Billboard Mockup Generator</p>"
            f"<p>Python {platform.python_version()}<br>"
            f"Qt {qVersion()}</p>"
            "<p>© 2026 BillboardAI. All rights reserved.</p>",
        )

    # ------------------------------------------------------------------
    # Backward-compatible attribute access (delegated to HomePage)
    # ------------------------------------------------------------------
    @property
    def url_input(self) -> QLineEdit:
        return self.home_page.url_input

    @property
    def template_combo(self) -> QComboBox:
        return self.home_page.template_combo

    @property
    def output_folder_input(self) -> QLineEdit:
        return self.home_page.output_folder_input

    @property
    def generate_button(self) -> QPushButton:
        return self.home_page.generate_button

    @property
    def preview_label(self) -> QLabel:
        return self.home_page.preview_label

    @property
    def progress_bar(self) -> QProgressBar:
        return self.home_page.progress_bar

    @property
    def status_label(self) -> QLabel:
        return self.status_message
