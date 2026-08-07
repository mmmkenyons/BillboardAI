"""Application controller for the BillboardAI GUI.

Routes user actions to the engine bridge. Handles input validation,
background threading, progress updates, and GUI state changes.

The controller owns the :class:`Project` instance — the single source
of truth for the session. Widgets communicate through the controller
via signals; they never talk to each other directly.

**Sprint 4B ownership rule:** only this controller may create or own a
``Project``. The engine bridge never creates project directories.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from gui.models.app_settings import DEFAULT_OUTPUT_FOLDER, AppSettings
from gui.models.mockup_concept import MockupConcept
from gui.models.mockup_request import MockupRequest
from gui.models.mockup_result import MockupResult
from gui.models.project import Project
from gui.models.recent_websites import RecentWebsitesStore
from gui.workers.generation_worker import GenerationWorker
from gui.workers.rerender_worker import ReRenderWorker

if TYPE_CHECKING:
    from gui.main_window import MainWindow

logger = logging.getLogger(__name__)

_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")

# Debounce window for local re-render after concept edits (ms).
_RERENDER_DELAY_MS = 500


def normalize_url(raw: str) -> str:
    """Normalize a user-entered URL, prepending https:// when needed."""
    url = raw.strip()
    if not url:
        return ""
    if not _URL_SCHEME_RE.match(url):
        url = "https://" + url
    return url


def _domain_slug(url: str) -> str:
    """Best-effort folder slug from a URL host."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001
        host = ""
    host = host.removeprefix("www.")
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", host).strip("._")
    return slug or "billboard"


class BillboardController:
    """Coordinates GUI actions with the engine bridge.

    Owns the :class:`Project` and mediates all communication between
    the concept gallery, preview panel, and details panel.
    """

    def __init__(self) -> None:
        self._window: MainWindow | None = None
        self._thread: QThread | None = None
        self._worker: GenerationWorker | None = None
        self._rerender_thread: QThread | None = None
        self._rerender_worker: ReRenderWorker | None = None
        self._rerender_timer: QTimer | None = None
        self._rerender_generation: int = 0
        self._pending_rerender_concept_id: str | None = None
        self._recent = RecentWebsitesStore()
        self._success_timer: QTimer | None = None
        self._settings = AppSettings.load()
        self._project: Project | None = None

    @property
    def project(self) -> Project | None:
        """Return the current project (or None if no project is open)."""
        return self._project

    def _require_window(self) -> MainWindow:
        """Return the attached main window.

        Raises RuntimeError if called before :meth:`attach`.
        """
        if self._window is None:
            raise RuntimeError("Controller is not attached to a MainWindow")
        return self._window

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def attach(self, window: MainWindow) -> None:
        """Attach the controller to the main window and wire signals."""
        self._window = window
        page = window.home_page

        page.output_selector.browse_requested.connect(self.request_output_folder)
        page.generate_button.clicked.connect(self.generate_mockup)
        page.preview_panel.open_image_requested.connect(self.open_image)
        page.preview_panel.open_folder_requested.connect(self.open_output_folder)
        page.preview_panel.copy_path_requested.connect(self.copy_file_path)
        page.recent_websites.website_selected.connect(self._on_recent_selected)
        page.concept_gallery.concept_selected.connect(self._on_concept_selected)
        page.details_panel.concept_fields_changed.connect(self._on_concept_fields_changed)
        page.details_panel.replace_logo_requested.connect(self.replace_logo_requested)
        page.details_panel.remove_logo_override_requested.connect(self.remove_logo_override)

        # Sprint 4B Phase E1: Toolbar actions (MainWindow calls these)
        window.toolbar_new_concept.triggered.connect(self.generate_new_concept)
        window.toolbar_duplicate.triggered.connect(self._on_duplicate_requested)
        window.toolbar_delete.triggered.connect(self._on_delete_requested)

        # Load recent websites into the UI.
        page.recent_websites.set_websites(self._recent.websites())
        window.set_output_folder_status(page.output_selector.folder())

        # Attempt session restore.
        self._check_session_restore()

    def _check_session_restore(self) -> None:
        """Prompt the user to restore the last project, if one exists."""
        last_path = self._settings.last_project_path
        if not last_path or not os.path.isfile(last_path):
            return

        window = self._require_window()

        msg = QMessageBox(window)
        msg.setWindowTitle("BillboardAI")
        msg.setText(f"A previous project was found:\n{last_path}")
        msg.setInformativeText("Restore the previous project?")
        # Qt6 has no RestoreButton; Yes/No with custom labels is the
        # type-safe equivalent of the old Restore/Discard pattern.
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setEscapeButton(QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)

        # Relabel buttons.
        restore_btn = msg.button(QMessageBox.StandardButton.Yes)
        if restore_btn is not None:
            restore_btn.setText("Restore")
        discard_btn = msg.button(QMessageBox.StandardButton.No)
        if discard_btn is not None:
            discard_btn.setText("New Project")

        msg.exec()
        if msg.clickedButton() is restore_btn:
            self._restore_project(last_path)
        else:
            self._new_project()

    def _restore_project(self, project_path: str) -> None:
        """Load an existing project from disk."""
        window = self._require_window()
        try:
            self._project = Project.load(project_path)
            self._settings.update_last_project(project_path)
            self._populate_project_ui()
            window.set_status(f"Project loaded: {self._project.company}")
            logger.info("Restored project: %s", project_path)
        except (OSError, KeyError, ValueError) as exc:
            logger.error("Could not restore project: %s", exc)
            self._show_warning(
                "Restore Failed",
                f"Could not load project:\n{exc}\n\nStarting a new project.",
            )
            self._new_project()

    def _new_project(self) -> None:
        """Clear any existing project and reset to a blank state."""
        window = self._require_window()
        self._project = None
        window.home_page.clear_result()
        window.home_page.set_concepts([])
        window.set_status("Ready — enter a URL and click Generate Mockup.")

    # ------------------------------------------------------------------
    # Output folder
    # ------------------------------------------------------------------
    def request_output_folder(self) -> None:
        """Open a folder picker and update the output selector."""
        if self._window is None:
            return
        window = self._window
        selector = window.home_page.output_selector
        current = selector.folder() or DEFAULT_OUTPUT_FOLDER
        from PySide6.QtWidgets import QFileDialog

        selected = QFileDialog.getExistingDirectory(
            window, "Select Output Folder", current
        )
        if selected:
            selector.set_folder(selected)
            window.set_output_folder_status(selected)
            window.set_status(f"Output folder set to: {selected}")
            logger.info("Output folder set to: %s", selected)

    def open_output_folder(self) -> None:
        """Open the current project folder (or output folder) in the file manager."""
        if self._window is None:
            return
        if self._project and self._project.root_dir and os.path.isdir(self._project.root_dir):
            folder = self._project.root_dir
        else:
            folder = self._window.home_page.output_selector.folder()
        if not folder or not os.path.isdir(folder):
            self._show_warning("Output Folder", "The output folder does not exist yet.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
            logger.info("Opened output folder: %s", folder)
        except OSError as exc:
            logger.warning("Could not open output folder: %s", exc)

    def open_image(self) -> None:
        """Open the generated image in the system default viewer."""
        if self._window is None:
            return
        path = self._window.home_page.preview_panel.image_path()
        if not path or not os.path.isfile(path):
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            logger.info("Opened image: %s", path)
        except OSError as exc:
            logger.warning("Could not open image: %s", exc)

    def copy_file_path(self) -> None:
        """Copy the generated image path to the clipboard."""
        if self._window is None:
            return
        window = self._window
        path = window.home_page.preview_panel.image_path()
        if not path:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(path)
        window.set_status("File path copied to clipboard.")
        logger.info("Copied file path to clipboard: %s", path)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate_mockup(self) -> None:
        """Validate inputs and start generation in a background thread."""
        if self._window is None or self._is_running():
            return

        window = self._window
        page = window.home_page

        # Normalize and validate the URL.
        url = normalize_url(page.url_input.text())
        if not url:
            self._show_warning("Invalid URL", "Please enter a website URL.")
            return
        if "." not in url.split("://")[-1].split("/")[0]:
            self._show_warning("Invalid URL", "Please enter a valid website URL.")
            return

        # Validate the output folder.
        output_folder = page.output_selector.folder()
        if not output_folder:
            self._show_warning("Invalid Output Folder", "Please choose an output folder.")
            return

        # Validate the template.
        template = page.selected_template
        if not template:
            self._show_warning("Invalid Template", "Please choose a template.")
            return

        # Controller owns the Project — create before the worker runs so the
        # bridge can write straight into project/images/.
        if self._project is None:
            self._project = Project.create(
                output_root=output_folder,
                name=_domain_slug(url),
                website=url,
                company="",
            )
            self._settings.update_last_project(self._project.metadata_path)
            logger.info("Created project at %s", self._project.root_dir)

        concept_filename = self._project.next_concept_filename()
        output_path = os.path.join(self._project.image_path, concept_filename)

        request = MockupRequest(
            url=url,
            template=template,
            output_folder=output_folder,
            output_path=output_path,
        )

        self._set_busy(True)
        window.set_status("Generating billboard...")
        page.progress_panel.reset()
        # Clear preview/details only — keep gallery + project intact.
        page.clear_result()

        logger.info("Generation started for %s → %s", url, output_path)
        self._start_worker(request)

    def generate_new_concept(self) -> None:
        """Generate New Concept: run full AI pipeline, create new MockupConcept (never overwrites).
        
        Reuses current project/context. Controller handles pipeline; Project.create_concept for state.
        """
        if self._window is None or self._is_running() or self._project is None:
            return

        window = self._window
        page = window.home_page

        if not self._project.render_context:
            self._show_warning(
                "Cannot Generate New Concept",
                "Generate a mockup first to establish project context."
            )
            return

        # Reuse current for full pipeline (scraper etc.)
        url = self._project.website or page.url_input.text()
        template = page.selected_template
        concept_filename = self._project.next_concept_filename()
        output_path = os.path.join(self._project.image_path, concept_filename)

        request = MockupRequest(
            url=url,
            template=template,
            output_folder=self._project.root_dir,  # Project owned
            output_path=output_path,
        )

        self._set_busy(True)
        window.set_status("Generating new concept...")
        page.progress_panel.reset()
        page.clear_result()  # Clear preview only

        # Mark for create_concept in _handle
        request.extra = {"is_new_concept": True}  # Simple flag

        logger.info("Generate New Concept started for %s → %s", url, output_path)
        self._start_worker(request)

    def new_mockup(self) -> None:
        """Clear the current result and focus the URL field."""
        if self._window is None:
            return
        window = self._window
        page = window.home_page
        page.clear_result()
        page.progress_panel.reset()
        window.set_status("Ready")
        page.url_input.setFocus()
        logger.info("New mockup requested")

    def _start_worker(self, request: MockupRequest) -> None:
        """Create and start the background generation worker."""
        thread = QThread()
        worker = GenerationWorker(request)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._cleanup_thread)

        self._thread = thread
        self._worker = worker

        logger.info("Starting generation thread")
        thread.start()

    def _on_progress(self, percent: int, message: str, stage: str) -> None:
        """Update the progress bar, stage label, and status bar."""
        if self._window is None:
            return
        window = self._window
        page = window.home_page
        page.progress_panel.set_progress(percent, message, stage)
        window.set_status(message)

    def _on_finished(self, result: MockupResult) -> None:
        """Handle a completed generation."""
        if self._window is None:
            return
        window = self._window
        page = window.home_page

        if result.success:
            self._handle_successful_generation(result)
            self._recent.add(result.website)
            page.recent_websites.set_websites(self._recent.websites())
            logger.info("Generation completed: %s", result.preview_path)
        else:
            window.set_status("Generation failed")
            QMessageBox.critical(
                window,
                "Generation Failed",
                result.message or "An unknown error occurred.",
            )
            logger.error("Generation failed: %s", result.message)

        self._set_busy(False)
        if self._window:
            self._window.update_toolbar_state()

    def _handle_successful_generation(self, result: MockupResult) -> None:
        """Update the controller-owned project with a new concept from the result.
        
        For 'Generate New Concept', uses project.create_concept (per rules). Existing concepts untouched.
        """
        window = self._require_window()
        page = window.home_page

        if self._project is None:
            output_folder = page.output_selector.folder() or DEFAULT_OUTPUT_FOLDER
            self._project = Project.create(
                output_root=output_folder,
                name=result.company_name or _domain_slug(result.website) or "billboard",
                website=result.website,
                company=result.company_name,
            )
            self._settings.update_last_project(self._project.metadata_path)

        # Fill company/website once we know them from the scrape.
        if result.company_name and not self._project.company:
            self._project.company = result.company_name
        if result.website:
            self._project.website = result.website

        # Image should already be at the controller-supplied path.
        dest_image_path = result.preview_path or result.output_path or ""
        if dest_image_path and not dest_image_path.startswith(self._project.image_path):
            concept_filename = self._project.next_concept_filename()
            dest_image_path = os.path.join(self._project.image_path, concept_filename)
            if result.preview_path and os.path.isfile(result.preview_path):
                shutil.copy2(result.preview_path, dest_image_path)

        # Persist render inputs (logo/hero/colors/etc.) into project assets.
        self._ingest_render_context(result)

        template = (
            str(result.extra.get("template") or "")
            or page.selected_template
            or "contractor"
        )

        # For Generate New Concept, use Project.create_concept (sets name/source_id)
        if getattr(result, 'extra', {}).get('is_new_concept', False):
            concept = self._project.create_concept(result)
        else:
            concept = MockupConcept.create(
                image_path=dest_image_path,
                template=template,
                headline=result.headline,
                cta=result.cta,
                quality_score=result.quality_score,
                company_name=result.company_name or self._project.company,
            )
            self._project.add_concept(concept)

        page.add_concept(concept)
        page.set_result(result)
        self._populate_project_ui()
        window.set_status("✓ Mockup generated successfully")
        self._show_success_notification()

    def _ingest_render_context(self, result: MockupResult) -> None:
        """Copy scrape assets into the project and store a complete v1 contract."""
        if self._project is None:
            return

        from gui.models.render_context import ensure_render_context

        raw_ctx: dict[str, Any] = {}
        if isinstance(result.extra, dict):
            maybe = result.extra.get("render_context")
            if isinstance(maybe, dict):
                raw_ctx = dict(maybe)

        if not raw_ctx:
            raw_ctx = {
                "company_name": result.company_name,
                "headline": result.headline,
                "cta": result.cta,
                "template": result.extra.get("template") or "contractor",
                "logo_image": result.logo_path,
                "hero_image": result.extra.get("hero_path") or "",
                "background_image": result.extra.get("screenshot_path") or "",
                "source_url": result.website,
                "quality_score": result.quality_score,
                "brand_colors": list(result.extra.get("brand_colors") or []),
            }

        ctx = ensure_render_context(raw_ctx)

        logo_src = result.logo_path or ctx.logo_image or ""
        if logo_src and os.path.isfile(str(logo_src)):
            if not str(logo_src).lower().startswith(("http://", "https://")):
                ext = os.path.splitext(str(logo_src))[1] or ".png"
                logo_dest = self._project.copy_asset(str(logo_src), dest_name=f"logo{ext}")
                self._project.set_logo_override(logo_dest)
                ctx.logo_image = logo_dest
        elif self._project.logo_override:
            ctx.logo_image = self._project.logo_override

        project = self._project

        def _localize(src: str, dest_name: str) -> str:
            if not src or not os.path.isfile(str(src)):
                return ""
            if str(src).lower().startswith(("http://", "https://")):
                return ""
            ext = os.path.splitext(str(src))[1] or ".png"
            base, _ = os.path.splitext(dest_name)
            return project.copy_asset(str(src), dest_name=f"{base}{ext}")


        hero_dest = _localize(ctx.hero_image, "hero.png")
        if hero_dest:
            ctx.hero_image = hero_dest

        bg_dest = _localize(ctx.background_image, "screenshot.png")
        if bg_dest:
            ctx.background_image = bg_dest
            if not ctx.hero_image or not os.path.isfile(ctx.hero_image):
                ctx.hero_image = bg_dest

        if result.company_name:
            ctx.company_name = result.company_name
        if result.headline:
            ctx.headline = result.headline
        if result.cta:
            ctx.cta = result.cta
        if result.website:
            ctx.source_url = result.website
        if result.quality_score:
            ctx.quality_score = float(result.quality_score)
        template = str(result.extra.get("template") or ctx.template or "contractor")
        if template and template != ctx.template:
            ctx.apply_template_theme(template, preserve_user_cta=bool(result.cta))

        self._project.set_render_context(ctx.to_dict())


    def _populate_project_ui(self) -> None:
        """Refresh the gallery and details from the current project."""
        if self._window is None or self._project is None:
            return
        page = self._window.home_page
        page.set_concepts(self._project.concepts)

        selected = self._project.get_selected_concept()
        if selected:
            page.preview_panel.set_concept(selected)
            page.details_panel.set_concept(selected)
        if self._window:
            self._window.update_toolbar_state()

    def _on_concept_selected(self, concept_id: str) -> None:
        """Handle gallery selection — update project and UI, no regeneration."""
        if self._project is None or self._window is None:
            return
        window = self._window
        self._project.select_concept(concept_id)
        concept = self._project.get_concept(concept_id)
        if concept:
            page = window.home_page
            page.preview_panel.set_concept(concept)
            page.details_panel.set_concept(concept)
            window.set_status(f"Selected concept {concept_id[:8]}...")
        if self._window:
            self._window.update_toolbar_state()

    # ------------------------------------------------------------------
    # In-place concept edits → debounced local re-render
    # ------------------------------------------------------------------
    def _on_concept_fields_changed(self, fields: dict) -> None:
        """Apply detail-panel edits to the selected concept and schedule re-render."""
        if self._project is None or self._window is None:
            return
        if not isinstance(fields, dict) or not fields:
            return

        concept = self._project.get_selected_concept()
        if concept is None:
            return

        allowed = {"headline", "cta", "company_name", "template"}
        updates = {k: v for k, v in fields.items() if k in allowed and isinstance(v, str)}
        if not updates:
            return

        changed = concept.apply_updates(**updates)
        if not changed:
            return

        # Keep project-level company in sync when edited.
        if "company_name" in changed and concept.company_name:
            self._project.company = concept.company_name

        self._project._mark_dirty()  # noqa: SLF001 - intentional SSOT dirty flag
        self._schedule_rerender(concept.id)
        self._window.set_status("Updating preview...")

    def _schedule_rerender(self, concept_id: str) -> None:
        """Debounce local re-render so typing does not thrash the renderer."""
        self._pending_rerender_concept_id = concept_id
        window = self._window
        if window is None:
            return

        if self._rerender_timer is None:
            self._rerender_timer = QTimer(window)
            self._rerender_timer.setSingleShot(True)
            self._rerender_timer.timeout.connect(self._start_rerender)
        else:
            self._rerender_timer.stop()
        self._rerender_timer.start(_RERENDER_DELAY_MS)

    def _start_rerender(self) -> None:
        """Kick off ReRenderWorker for the pending concept."""
        if self._project is None or self._window is None:
            return
        # Only wait on full generation — never block the GUI on a prior re-render.
        if self._thread is not None and self._thread.isRunning():
            self._schedule_rerender(self._pending_rerender_concept_id or "")
            return

        concept_id = self._pending_rerender_concept_id
        concept = self._project.get_concept(concept_id) if concept_id else None
        if concept is None:
            concept = self._project.get_selected_concept()
        if concept is None:
            return

        if not self._project.render_context:
            self._show_warning(
                "Cannot Update Preview",
                "This project is missing render inputs. Generate a mockup first.",
            )
            return

        output_path = concept.image_path
        if not output_path:
            output_path = os.path.join(
                self._project.image_path, self._project.next_concept_filename()
            )
            concept.image_path = output_path

        # Merge concept overrides into the complete project contract.
        effective_ctx = self._project.effective_render_context(
            headline=concept.headline,
            cta=concept.cta,
            company_name=concept.company_name or self._project.company,
            template=concept.template,
        )

        # Bump generation token so stale worker finishes are ignored.
        self._rerender_generation += 1
        token = self._rerender_generation

        # Drop prior re-render refs without waiting (stale results ignored via token).
        old_thread = self._rerender_thread
        old_worker = self._rerender_worker
        self._rerender_thread = None
        self._rerender_worker = None
        if old_thread is not None and old_thread.isRunning():
            old_thread.quit()
        if old_worker is not None:
            old_worker.deleteLater()
        if old_thread is not None:
            old_thread.deleteLater()

        thread = QThread()
        worker = ReRenderWorker(
            render_context=effective_ctx,
            output_path=output_path,
            concept_id=concept.id,
        )

        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(
            lambda result, t=token: self._on_rerender_finished(result, t)
        )
        worker.failed.connect(
            lambda err, t=token: self._on_rerender_failed(err, t)
        )
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._cleanup_rerender_thread)

        self._rerender_thread = thread
        self._rerender_worker = worker
        logger.info("Starting re-render thread for concept %s", concept.id[:8])
        thread.start()


    def _on_rerender_finished(self, result: MockupResult, token: int) -> None:
        """Apply a completed local re-render to the UI."""
        if token != self._rerender_generation:
            logger.info("Ignoring stale re-render result (token mismatch)")
            return
        if self._window is None or self._project is None:
            return

        concept_id = str((result.extra or {}).get("concept_id") or "")
        concept = self._project.get_concept(concept_id) if concept_id else None
        if concept is None:
            concept = self._project.get_selected_concept()
        if concept is None:
            return

        if not result.success:
            self._window.set_status("Preview update failed")
            logger.error("Re-render failed: %s", result.message)
            return

        if result.preview_path:
            concept.image_path = result.preview_path
        self._project._mark_dirty()  # noqa: SLF001

        # Refresh preview + gallery thumbnail for the active concept.
        page = self._window.home_page
        if self._project.selected_concept_id == concept.id:
            page.preview_panel.set_concept(concept)
            page.details_panel.set_concept(concept)
        page.set_concepts(self._project.concepts)
        self._window.set_status("✓ Preview updated")
        logger.info("Re-render applied for concept %s", concept.id[:8])
        if self._window:
            self._window.update_toolbar_state()

    def _on_rerender_failed(self, error: str, token: int) -> None:
        if token != self._rerender_generation:
            return
        if self._window is None:
            return
        self._window.set_status("Preview update failed")
        logger.error("Re-render worker failed: %s", error)
        if self._window:
            self._window.update_toolbar_state()

    def _cleanup_rerender_thread(self) -> None:
        """Clean up a finished re-render thread/worker."""
        if self._rerender_thread is not None:
            if self._rerender_thread.isRunning():
                self._rerender_thread.quit()
                self._rerender_thread.wait(3000)
            self._rerender_thread.deleteLater()
        if self._rerender_worker is not None:
            self._rerender_worker.deleteLater()
        self._rerender_thread = None
        self._rerender_worker = None
        if self._project is not None:
            try:
                self._project.save()
            except OSError as exc:
                logger.warning("Could not save project after re-render: %s", exc)

    def _on_failed(self, error: str) -> None:
        """Handle an unexpected worker failure."""
        if self._window is None:
            return
        window = self._window
        window.set_status("Generation failed")
        QMessageBox.critical(
            window,
            "Generation Failed",
            f"An unexpected error occurred:\n{error}",
        )
        logger.error("Unexpected generation failure: %s", error)
        self._set_busy(False)
        if self._window:
            self._window.update_toolbar_state()

    def _cleanup_thread(self) -> None:
        """Clean up the finished thread and worker."""
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None

        # Force a final save of the project now that the thread is gone.
        if self._project is not None:
            self._project.save()

    # ------------------------------------------------------------------
    # Recent websites
    # ------------------------------------------------------------------
    def _on_recent_selected(self, url: str) -> None:
        """Populate the URL field when a recent website is selected."""
        if self._window is None:
            return
        window = self._window
        window.home_page.url_input.setText(url)
        window.set_status(f"Selected: {url}")
        logger.info("Recent website selected: %s", url)

    # ------------------------------------------------------------------
    # Logo replacement (Sprint 4B Phase D)
    # ------------------------------------------------------------------
    def replace_logo_requested(self) -> None:
        """Handle replace logo request from details panel (controller owns dialog)."""
        if self._window is None or self._project is None:
            self._show_warning("No Project", "Open or generate a project first.")
            return
        if self._is_running():
            return

        window = self._require_window()
        from PySide6.QtWidgets import QFileDialog

        selected, _ = QFileDialog.getOpenFileName(
            window,
            "Replace Logo",
            "",
            "Image Files (*.png *.jpg *.jpeg *.svg)",
        )
        if not selected or not os.path.isfile(selected):
            return

        try:
            # Copy to assets/ with unique name to never overwrite original scraped logo
            dest_name = f"logo_override_{int(os.path.getmtime(selected))}.png"
            override_path = self._project.copy_asset(selected, dest_name=dest_name)
            self._project.set_logo_override(override_path)

            # Trigger re-render with fresh revision token
            self._rerender_generation = self._project.get_render_revision()
            token = self._rerender_generation
            self._start_rerender()  # Will use current revision

            window.set_status(f"Logo replaced with {os.path.basename(override_path)}")
            logger.info("Logo override set: %s (revision %s)", override_path, token)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Logo replacement failed")
            self._show_warning("Logo Replacement Failed", str(exc))

    def remove_logo_override(self) -> None:
        """Clear logo override (falls back to scraped or none)."""
        if self._project is None or self._window is None:
            return
        self._project.clear_logo_override()
        self._rerender_generation = self._project.get_render_revision()
        self._start_rerender()
        self._window.set_status("Logo override removed (using scraped if available)")
        logger.info("Logo override cleared (revision %s)", self._rerender_generation)

    # ------------------------------------------------------------------
    # Sprint 4B Phase E1: New Concept Management (toolbar-driven)
    # ------------------------------------------------------------------
    def _on_duplicate_requested(self) -> None:
        """Toolbar duplicate handler."""
        if self._project is None or self._window is None:
            return
        selected = self._project.get_selected_concept()
        if selected:
            self.duplicate_concept(selected.id)

    def duplicate_concept(self, concept_id: str) -> None:
        """Duplicate: copy PNG only, no AI/renderer. New concept with sequential name."""
        if self._project is None or self._window is None:
            return
        try:
            new_concept = self._project.duplicate_concept(concept_id)
            self._window.home_page.add_concept(new_concept)  # Uses gallery add
            self._window.update_toolbar_state()
            self._window.set_status(f"Duplicated as {new_concept.name}")
            self._project.save()
            logger.info("Concept duplicated: %s -> %s", concept_id, new_concept.id)
        except Exception as exc:
            self._show_warning("Duplicate Failed", str(exc))

    def _on_delete_requested(self) -> None:
        """Toolbar delete handler with exact confirmation."""
        if self._project is None or self._window is None:
            return
        selected = self._project.get_selected_concept()
        if selected:
            self.delete_concept(selected.id)

    def delete_concept(self, concept_id: str) -> None:
        """Delete: exact dialog, move to trash/, update selection, refresh, autosave."""
        if self._window is None:
            return
        window = self._window

        msg = QMessageBox(window)
        msg.setWindowTitle("Move to Trash?")
        msg.setText("Move this concept to Trash?")
        msg.setInformativeText(
            "The image will be removed from this project but can be restored manually from the Trash folder."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        yes_btn = msg.button(QMessageBox.StandardButton.Yes)
        if yes_btn:
            yes_btn.setText("Move to Trash")

        if msg.exec() == QMessageBox.StandardButton.Yes:
            if self._project:
                self._project.remove_concept(concept_id)
                self._populate_project_ui()
                self._window.update_toolbar_state()
                self._project.save()
                window.set_status("Concept moved to trash")
                logger.info("Concept moved to trash: %s", concept_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _is_running(self) -> bool:
        gen_running = self._thread is not None and self._thread.isRunning()
        rerender_running = (
            self._rerender_thread is not None and self._rerender_thread.isRunning()
        )
        return gen_running or rerender_running

    def _set_busy(self, busy: bool) -> None:
        """Enable/disable interactive controls during generation."""
        if self._window is None:
            return
        window = self._window
        page = window.home_page
        page.url_input.setEnabled(not busy)
        page.template_combo.setEnabled(not busy)
        page.output_selector.setEnabled(not busy)
        page.generate_button.setEnabled(not busy)
        window.toolbar_generate.setEnabled(not busy)
        if hasattr(window, 'toolbar_new_concept'):
            window.toolbar_new_concept.setEnabled(not busy)
        if hasattr(window, 'toolbar_duplicate'):
            window.toolbar_duplicate.setEnabled(not busy)
        if hasattr(window, 'toolbar_delete'):
            window.toolbar_delete.setEnabled(not busy)

    def _show_success_notification(self) -> None:
        """Briefly show a success message in the status bar."""
        if self._window is None:
            return
        window = self._window
        if self._success_timer is not None:
            self._success_timer.stop()
        window.set_status("✓ Mockup generated successfully")

        def _reset_status() -> None:
            if self._window is not None:
                self._window.set_status("✓ Ready")

        timer = QTimer(window)
        timer.setSingleShot(True)
        timer.timeout.connect(_reset_status)
        timer.start(4000)
        self._success_timer = timer

    def _show_warning(self, title: str, message: str) -> None:
        if self._window is not None:
            QMessageBox.warning(self._window, title, message)
