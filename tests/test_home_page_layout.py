from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication, QPushButton, QSizePolicy, QWidget

from gui.main_window import MainWindow
from gui.views.home_page import HomePage


def _app():
    app = QApplication.instance()
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication([])
    return app


def _show(widget: QWidget, width: int, height: int) -> None:
    app = _app()
    widget.resize(width, height)
    widget.show()
    app.processEvents()


def _browse_button(page: HomePage) -> QPushButton:
    buttons = page.output_selector.findChildren(QPushButton)
    assert buttons
    return buttons[0]


def test_home_upper_regions_are_sequential_and_visible_at_restored_size() -> None:
    page = HomePage()
    _show(page, 1100, 700)

    assert page.layout() is not None
    assert page.layout().indexOf(page.header) == 0
    assert page.layout().indexOf(page.input_card) == 1
    assert page.layout().indexOf(page.action_row) == 2
    assert page.layout().indexOf(page.progress_panel) == 3
    assert page.layout().indexOf(page.results_scroll_area) == 4

    for widget in [page.header, page.input_card, page.action_row, page.progress_panel, page.results_scroll_area]:
        assert widget.isVisible()
        assert widget.height() > 0

    assert page.input_card.geometry().bottom() < page.action_row.geometry().top()
    assert page.action_row.geometry().bottom() < page.progress_panel.geometry().top()
    assert page.progress_panel.geometry().bottom() < page.results_scroll_area.geometry().top()


def test_home_input_card_contains_all_form_rows_and_browse_button() -> None:
    page = HomePage()
    _show(page, 1100, 700)

    frame = page.input_card
    assert frame is page.url_input.parentWidget()
    assert frame.layout() is not None
    assert frame.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed

    output_row = page.output_selector
    browse = _browse_button(page)

    assert page.url_input.isVisible()
    assert page.template_combo.isVisible()
    assert output_row.isVisible()
    assert browse.isVisible()

    assert output_row.parentWidget() is frame
    assert browse.parentWidget() is output_row

    assert output_row.y() + output_row.height() <= frame.height()
    assert browse.y() + browse.height() <= output_row.height()


def test_home_lower_region_is_scroll_backed_and_owns_remaining_space() -> None:
    page = HomePage()
    _show(page, 1100, 700)

    assert page.content_splitter is None
    assert page.splitter is page.results_scroll_area
    assert page.results_scroll_area.widgetResizable() is True
    assert page.results_scroll_area.widget() is page.results_container

    assert page.concept_gallery.parentWidget() is page.results_container
    assert page.preview_panel.parentWidget() is page.results_container
    assert page.bottom_row.parentWidget() is page.results_container
    assert page.details_panel.parentWidget() is page.bottom_row
    assert page.recent_websites.parentWidget() is page.bottom_row

    assert page.results_scroll_area.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding
    assert page.preview_panel.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding
    assert page.results_scroll_area.height() > 0


def test_home_hosted_in_main_window_preserves_same_ordering_at_restored_size() -> None:
    window = MainWindow()
    _show(window, 1100, 700)

    page = window.home_page
    assert page.input_card.geometry().bottom() < page.action_row.geometry().top()
    assert page.action_row.geometry().bottom() < page.progress_panel.geometry().top()
    assert page.progress_panel.geometry().bottom() < page.results_scroll_area.geometry().top()

    assert page.url_input.isVisible()
    assert page.template_combo.isVisible()
    assert page.output_selector.isVisible()
    assert _browse_button(page).isVisible()


def test_home_large_size_preserves_structure_without_splitter() -> None:
    page = HomePage()
    _show(page, 1600, 950)

    assert page.content_splitter is None
    assert page.concept_gallery.height() > 0
    assert page.preview_panel.height() >= page.preview_panel.minimumHeight()
    assert page.results_scroll_area.height() > page.progress_panel.height()