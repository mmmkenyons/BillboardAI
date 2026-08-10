"""Sprint 4B Inventory Workspace page.

A hierarchical inventory manager for sellable advertising inventory:

    Retailer
        -> Market
            -> Location
                -> Placement

The left panel is a tree navigation with placement status labels (text, not
color-only), create buttons, a placement status filter and a compact summary.
The right panel is a detail form for the selected entity (retailer / market /
location / placement) including pricing, traffic, category restrictions and a
dynamic scene-template selector.

This page is a thin view: it reads state through the
:class:`~gui.controllers.inventory_controller.InventoryController` and calls
controller methods for mutations. All business logic and persistence live in
the Qt-free service layer. Widgets never write JSON directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.models.inventory import (
    PERIOD_MONTH,
    PERIOD_ONETIME,
    PERIOD_YEAR,
    PRICE_PERIODS,
    STATUS_AVAILABLE,
    STATUS_HELD,
    STATUS_SOLD,
)
from gui.services.inventory_workspace import InventoryValidationError

if TYPE_CHECKING:
    from gui.controllers.inventory_controller import InventoryController

logger = logging.getLogger(__name__)

_KIND_RETAILER = "retailer"
_KIND_MARKET = "market"
_KIND_LOCATION = "location"
_KIND_PLACEMENT = "placement"

# Placement status aliases used for short tree labels.
_STATUS_SHORT = {
    STATUS_AVAILABLE: "AVAILABLE",
    STATUS_HELD: "HELD",
    STATUS_SOLD: "SOLD",
    "UNAVAILABLE": "UNAVAILABLE",
    "MAINTENANCE": "MAINTENANCE",
    "ARCHIVED": "ARCHIVED",
}

_PERIOD_LABELS = {
    PERIOD_ONETIME: "ONE TIME",
    PERIOD_MONTH: "MONTH",
    PERIOD_YEAR: "YEAR",
}


class InventoryWorkspacePage(QWidget):
    """The inventory workspace: tree navigation + editable detail forms."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._controller: Optional["InventoryController"] = None
        self._mode: str = _KIND_RETAILER
        self._editing_id: Optional[str] = None
        self._context_location_id: Optional[str] = None
        self._context_retailer_id: Optional[str] = None
        self._context_market_id: Optional[str] = None
        self._build_ui()
        self._show_placeholder()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(16)

        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_detail_area(), stretch=1)

    def _build_sidebar(self) -> QFrame:
        side = QFrame(self)
        side.setObjectName("workspaceSidebar")
        side.setFixedWidth(340)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(10)

        title = QLabel("Inventory", side)
        title.setObjectName("projectTitle")
        layout.addWidget(title)

        sub = QLabel("Retailers / markets / locations / placements", side)
        sub.setObjectName("projectMeta")
        layout.addWidget(sub)

        # Create buttons.
        create_row = QHBoxLayout()
        create_row.setSpacing(6)
        self.new_retailer_btn = QPushButton("New Retailer", side)
        self.new_market_btn = QPushButton("New Market", side)
        self.new_location_btn = QPushButton("New Location", side)
        self.new_placement_btn = QPushButton("New Placement", side)
        for btn in (
            self.new_retailer_btn,
            self.new_market_btn,
            self.new_location_btn,
            self.new_placement_btn,
        ):
            btn.setObjectName("secondaryButton")
        create_row.addWidget(self.new_retailer_btn)
        create_row.addWidget(self.new_market_btn)
        create_row.addWidget(self.new_location_btn)
        create_row.addWidget(self.new_placement_btn)
        layout.addLayout(create_row)

        # Create button actions.
        self.new_retailer_btn.clicked.connect(self._on_new_retailer)
        self.new_market_btn.clicked.connect(self._on_new_market)
        self.new_location_btn.clicked.connect(self._on_new_location)
        self.new_placement_btn.clicked.connect(self._on_new_placement)

        # Status filter.
        filter_row = QHBoxLayout()
        filter_label = QLabel("Placements:", side)
        filter_label.setObjectName("projectMeta")
        self.filter_combo = QComboBox(side)
        self.filter_combo.addItem("ALL", None)
        for status in (STATUS_AVAILABLE, STATUS_HELD, STATUS_SOLD,
                       "UNAVAILABLE", "MAINTENANCE", "ARCHIVED"):
            self.filter_combo.addItem(status, status)
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(filter_label)
        filter_row.addWidget(self.filter_combo, stretch=1)
        layout.addLayout(filter_row)

        # Summary.
        self.summary_label = QLabel("", side)
        self.summary_label.setObjectName("projectMeta")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        # Tree.
        self.tree = QTreeWidget(side)
        self.tree.setHeaderHidden(True)
        self.tree.setObjectName("inventoryTree")
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        layout.addWidget(self.tree, stretch=1)

        return side
# ------------------------------------------------------------------
    # Detail area
    # ------------------------------------------------------------------
    def _build_detail_area(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        heading = QLabel("Inventory Editor", container)
        heading.setObjectName("projectTitle")
        layout.addWidget(heading)

        self._scroll = QScrollArea(container)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._detail = QWidget(self._scroll)
        self._detail.setObjectName("cardFrame")
        detail_layout = QVBoxLayout(self._detail)
        detail_layout.setContentsMargins(20, 20, 20, 20)
        detail_layout.setSpacing(14)

        self._form = QFormLayout()
        self._form.setSpacing(10)
        self._form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        detail_layout.addLayout(self._form)

        self._build_fields()

        # Extra placement-only rows (wrapped in widgets so they can be hidden).
        self._traffic_row = QWidget(self._detail)
        traffic_layout = QHBoxLayout(self._traffic_row)
        traffic_layout.setContentsMargins(0, 0, 0, 0)
        traffic_layout.setSpacing(8)
        self.effective_traffic_label = QLabel("—", self._traffic_row)
        self.effective_traffic_label.setObjectName("projectMeta")
        traffic_layout.addWidget(self.effective_traffic_label)
        traffic_layout.addStretch(1)
        detail_layout.addWidget(self._traffic_row)

        # Availability check row.
        self._avail_row = QWidget(self._detail)
        avail_layout = QHBoxLayout(self._avail_row)
        avail_layout.setContentsMargins(0, 0, 0, 0)
        avail_layout.setSpacing(8)
        avail_label = QLabel("Check category:", self._avail_row)
        avail_label.setObjectName("projectMeta")
        self.avail_input = QLineEdit(self._avail_row)
        self.avail_input.setPlaceholderText("e.g. Roofing")
        self.check_button = QPushButton("Check category", self._avail_row)
        self.check_button.setObjectName("secondaryButton")
        self.check_button.clicked.connect(self._on_check_availability)
        self.avail_result = QLabel("", self._avail_row)
        self.avail_result.setObjectName("availabilityResult")
        avail_layout.addWidget(avail_label)
        avail_layout.addWidget(self.avail_input)
        avail_layout.addWidget(self.check_button)
        avail_layout.addWidget(self.avail_result)
        avail_layout.addStretch(1)
        detail_layout.addWidget(self._avail_row)

        # Action buttons.
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.save_button = QPushButton("Save", self._detail)
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._on_save)
        self.archive_button = QPushButton("Archive", self._detail)
        self.archive_button.setObjectName("secondaryButton")
        self.archive_button.clicked.connect(self._on_archive)
        self.cancel_button = QPushButton("Cancel", self._detail)
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.clicked.connect(self._on_cancel)
        actions.addWidget(self.save_button)
        actions.addWidget(self.archive_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        detail_layout.addLayout(actions)

        self._scroll.setWidget(self._detail)
        layout.addWidget(self._scroll, stretch=1)
        return container
# ------------------------------------------------------------------
    # Field construction
    # ------------------------------------------------------------------
    def _build_fields(self) -> None:
        """Create all form fields once; rows are shown/hidden per entity kind."""
        self._fields: Dict[str, Any] = {}

        def line(name: str, label: str, placeholder: str = "") -> QLineEdit:
            widget = QLineEdit(self._detail)
            widget.setPlaceholderText(placeholder)
            self._form.addRow(label, widget)
            self._fields[name] = widget
            return widget

        def combo(name: str, label: str, items: Dict[str, Any]) -> QComboBox:
            widget = QComboBox(self._detail)
            for text, data in items.items():
                widget.addItem(text, data)
            self._form.addRow(label, widget)
            self._fields[name] = widget
            return widget

        # Retailer
        self.f_name = line("name", "Name")
        self.f_parent_company = line("parent_company", "Parent Company")
        self.f_brand_name = line("brand_name", "Brand Name")
        self.f_website = line("website", "Website")

        # Market
        self.f_state = line("state", "State")
        self.f_region = line("region", "Region")

        # Location
        self.f_store_number = line("store_number", "Store Number")
        self.f_retailer = combo("retailer", "Retailer", {})
        self.f_market = combo("market", "Market", {})
        self.f_address = line("address", "Address")
        self.f_city = line("city", "City")
        self.f_postal_code = line("postal_code", "Postal Code")
        self.f_weekly_traffic = line("weekly_traffic", "Weekly Traffic")
        self.f_latitude = line("latitude", "Latitude")
        self.f_longitude = line("longitude", "Longitude")

        # Placement
        self.f_placement_type = line("placement_type", "Placement Type")
        self.f_scene_template = combo("scene_template", "Scene Template", {})
        self.f_status = combo(
            "status",
            "Status",
            {
                "AVAILABLE": "AVAILABLE",
                "HELD": "HELD",
                "SOLD": "SOLD",
                "UNAVAILABLE": "UNAVAILABLE",
                "MAINTENANCE": "MAINTENANCE",
                "ARCHIVED": "ARCHIVED",
            },
        )
        self.f_price = line("price", "Price", "e.g. 12000")
        self.f_price_period = combo(
            "price_period",
            "Price Period",
            {
                _PERIOD_LABELS[PERIOD_ONETIME]: PERIOD_ONETIME,
                _PERIOD_LABELS[PERIOD_MONTH]: PERIOD_MONTH,
                _PERIOD_LABELS[PERIOD_YEAR]: PERIOD_YEAR,
            },
        )
        self.f_setup_fee = line("setup_fee", "Setup Fee", "e.g. 500")
        self.f_exclusive_category = line("exclusive_category", "Exclusive Category")
        self.f_blocked_categories = line(
            "blocked_categories", "Blocked Categories", "comma separated"
        )
        self.f_traffic_override = line(
            "traffic_override", "Traffic Override", "blank = inherit"
        )
        self.f_start_date = line("start_date", "Start Date")
        self.f_end_date = line("end_date", "End Date")
        self.f_notes = QPlainTextEdit(self._detail)
        self.f_notes.setPlaceholderText("Notes")
        self._form.addRow("Notes", self.f_notes)
        self._fields["notes"] = self.f_notes

        # Row visibility metadata.
        self._field_rows: Dict[str, str] = {
            "name": _KIND_RETAILER,
            "parent_company": _KIND_RETAILER,
            "brand_name": _KIND_RETAILER,
            "website": _KIND_RETAILER,
            "state": _KIND_MARKET,
            "region": _KIND_MARKET,
            "store_number": _KIND_LOCATION,
            "retailer": _KIND_LOCATION,
            "market": _KIND_LOCATION,
            "address": _KIND_LOCATION,
            "city": _KIND_LOCATION,
            "postal_code": _KIND_LOCATION,
            "weekly_traffic": _KIND_LOCATION,
            "latitude": _KIND_LOCATION,
            "longitude": _KIND_LOCATION,
            "placement_type": _KIND_PLACEMENT,
            "scene_template": _KIND_PLACEMENT,
            "status": _KIND_PLACEMENT,
            "price": _KIND_PLACEMENT,
            "price_period": _KIND_PLACEMENT,
            "setup_fee": _KIND_PLACEMENT,
            "exclusive_category": _KIND_PLACEMENT,
            "blocked_categories": _KIND_PLACEMENT,
            "traffic_override": _KIND_PLACEMENT,
            "start_date": _KIND_PLACEMENT,
            "end_date": _KIND_PLACEMENT,
            "notes": _KIND_PLACEMENT,
        }
# ------------------------------------------------------------------
    # Controller wiring
    # ------------------------------------------------------------------
    def set_controller(self, controller: "InventoryController") -> None:
        """Attach the controller and wire its signals, then load + refresh."""
        self._controller = controller
        controller.inventory_changed.connect(self._on_inventory_changed)
        controller.inventory_loaded.connect(self._on_inventory_changed)
        controller.error_message.connect(self._on_error)
        controller.status_message.connect(lambda msg: self._set_status(msg))
        controller.load()
        self.refresh()

    def _on_inventory_changed(self) -> None:
        self.refresh()

    def _on_error(self, message: str) -> None:
        self.avail_result.setText("")
        if self._controller is not None:
            self._controller.status_message.emit(message)

    def _user_error(self, message: str) -> None:
        """Surface a concise user-facing error without a dialog."""
        if self._controller is not None:
            self._controller.error_message.emit(message)
            self._controller.status_message.emit(message)
            self.avail_result.setText(message)
            self.avail_result.setStyleSheet("color: #e74c3c; font-weight: 600;")

    def _set_status(self, message: str) -> None:
        # Route to the window status bar when available.
        window = self.window()
        if hasattr(window, "set_status"):
            window.set_status(message)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Refresh / tree
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Rebuild the tree and summary from the controller's service."""
        if self._controller is None:
            return
        filter_status = self.filter_combo.currentData()
        hierarchy = self._controller.hierarchy(filter_status)
        self._populate_tree(hierarchy)
        self._update_summary()

    def _status_filter(self) -> Optional[str]:
        return self.filter_combo.currentData()

    def _populate_tree(self, hierarchy: list) -> None:
        self.tree.clear()
        if self._controller is None:
            return

        if not hierarchy:
            empty = QTreeWidgetItem(["No retailers yet"])
            empty.setData(0, Qt.ItemDataRole.UserRole, None)
            self.tree.addTopLevelItem(empty)
            return

        for rnode in hierarchy:
            retailer = rnode["retailer"]
            r_item = QTreeWidgetItem(
                [retailer.name or retailer.parent_company or "Retailer"]
            )
            r_item.setData(0, Qt.ItemDataRole.UserRole, (_KIND_RETAILER, retailer.retailer_id))
            self.tree.addTopLevelItem(r_item)

            markets = rnode["markets"]
            if not markets:
                hint = QTreeWidgetItem(["No locations"])
                hint.setData(0, Qt.ItemDataRole.UserRole, None)
                r_item.addChild(hint)
                continue

            for mnode in markets:
                m = mnode["market"]
                m_label = m.name if m else mnode["label"]
                m_item = QTreeWidgetItem([m_label])
                mid = m.market_id if m else ""
                m_item.setData(0, Qt.ItemDataRole.UserRole, (_KIND_MARKET, mid))
                r_item.addChild(m_item)

                for lnode in mnode["locations"]:
                    loc = lnode["location"]
                    loc_label = loc.name
                    if loc.store_number:
                        loc_label += f" (#{loc.store_number})"
                    if loc.city:
                        loc_label += f" — {loc.city}"
                    l_item = QTreeWidgetItem([loc_label])
                    l_item.setData(
                        0, Qt.ItemDataRole.UserRole, (_KIND_LOCATION, loc.location_id)
                    )
                    m_item.addChild(l_item)

                    placements = lnode["placements"]
                    if not placements:
                        p_hint = QTreeWidgetItem(["No placements"])
                        p_hint.setData(0, Qt.ItemDataRole.UserRole, None)
                        l_item.addChild(p_hint)
                    for placement in placements:
                        short = _STATUS_SHORT.get(placement.status, placement.status)
                        p_item = QTreeWidgetItem(
                            [f"{placement.name}  [{short}]"]
                        )
                        p_item.setData(
                            0,
                            Qt.ItemDataRole.UserRole,
                            (_KIND_PLACEMENT, placement.placement_id),
                        )
                        l_item.addChild(p_item)

        self.tree.expandAll()

    def _update_summary(self) -> None:
        if self._controller is None:
            return
        s = self._controller.summary()
        annual = s.get("available_annual_cents", 0) / 100
        self.summary_label.setText(
            f"Placements: {s['total']} total · {s['available']} available · "
            f"{s['held']} held · {s['sold']} sold\n"
            f"Available annual value: ${annual:,.0f}"
        )
# ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def _on_tree_selection(self) -> None:
        if self._controller is None:
            return
        items = self.tree.selectedItems()
        if not items:
            return
        item = items[0]
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None:
            self._show_placeholder()
            return
        kind, entity_id = data
        self.select_entity(kind, entity_id)

    def select_entity(self, kind: str, entity_id: str) -> None:
        """Populate the detail form for the given entity (public/testable)."""
        if self._controller is None:
            return
        self._controller.select(kind, entity_id)
        self._mode = kind
        self._editing_id = entity_id

        if kind == _KIND_RETAILER:
            entity = self._controller.get_retailer(entity_id)
        elif kind == _KIND_MARKET:
            entity = self._controller.get_market(entity_id)
        elif kind == _KIND_LOCATION:
            entity = self._controller.get_location(entity_id)
        else:
            entity = self._controller.get_placement(entity_id)

        self._populate_combos()
        if entity is None:
            self._show_placeholder()
            return
        self._show_kind(kind)
        self._populate_from_entity(kind, entity)
        self.save_button.setText("Save")
        self.archive_button.setVisible(kind == _KIND_PLACEMENT)
        self._traffic_row.setVisible(kind == _KIND_PLACEMENT)
        self._avail_row.setVisible(kind == _KIND_PLACEMENT)

    def _populate_combos(self) -> None:
        if self._controller is None:
            return
        retailers = self._controller.list_retailers()
        self.f_retailer.clear()
        self.f_retailer.addItem("— None —", "")
        for r in retailers:
            self.f_retailer.addItem(r.name, r.retailer_id)
        markets = self._controller.list_markets()
        self.f_market.clear()
        self.f_market.addItem("— None —", "")
        for m in markets:
            self.f_market.addItem(m.name, m.market_id)
        self._populate_scene_selector()

    def _populate_scene_selector(self) -> None:
        current = self.f_scene_template.currentData()
        self.f_scene_template.blockSignals(True)
        self.f_scene_template.clear()
        self.f_scene_template.addItem("— None —", "")
        for meta in self._controller.scene_template_options():
            name = meta.get("name") or meta.get("id") or "—"
            size = meta.get("artwork_size") or {}
            label = f"{name} ({size.get('width', '?')}×{size.get('height', '?')})"
            self.f_scene_template.addItem(label, meta.get("id"))
        if current:
            idx = self.f_scene_template.findData(current)
            if idx >= 0:
                self.f_scene_template.setCurrentIndex(idx)
        self.f_scene_template.blockSignals(False)

    def _show_kind(self, kind: str) -> None:
        """Show only the rows belonging to the given entity kind."""
        for name, widget in self._fields.items():
            widget.setVisible(self._field_rows.get(name) == kind)
        self._traffic_row.setVisible(kind == _KIND_PLACEMENT)
        self._avail_row.setVisible(kind == _KIND_PLACEMENT)

    def _show_placeholder(self) -> None:
        self._mode = ""
        self._editing_id = None
        for widget in self._fields.values():
            widget.setVisible(False)
        self._traffic_row.setVisible(False)
        self._avail_row.setVisible(False)
        self.save_button.setVisible(False)
        self.archive_button.setVisible(False)
        self.avail_result.setText("")
        self.effective_traffic_label.setText(
            "Select an entity in the tree to edit it."
        )
        self.effective_traffic_label.setVisible(True)

    # ------------------------------------------------------------------
    # Populate from entity
    # ------------------------------------------------------------------
    def _populate_from_entity(self, kind: str, entity: Any) -> None:
        if kind == _KIND_RETAILER:
            self.f_name.setText(entity.name)
            self.f_parent_company.setText(entity.parent_company)
            self.f_brand_name.setText(entity.brand_name)
            self.f_website.setText(entity.website)
        elif kind == _KIND_MARKET:
            self.f_name.setText(entity.name)
            self.f_state.setText(entity.state)
            self.f_region.setText(entity.region)
        elif kind == _KIND_LOCATION:
            self.f_name.setText(entity.name)
            self.f_store_number.setText(entity.store_number)
            self._set_combo_data(self.f_retailer, entity.retailer_id)
            self._set_combo_data(self.f_market, entity.market_id)
            self.f_address.setText(entity.address)
            self.f_city.setText(entity.city)
            self.f_state.setText(entity.state)
            self.f_postal_code.setText(entity.postal_code)
            self.f_weekly_traffic.setText(
                "" if entity.weekly_traffic is None else str(entity.weekly_traffic)
            )
            self.f_latitude.setText(
                "" if entity.latitude is None else str(entity.latitude)
            )
            self.f_longitude.setText(
                "" if entity.longitude is None else str(entity.longitude)
            )
        else:  # placement
            self.f_name.setText(entity.name)
            self.f_placement_type.setText(entity.placement_type)
            self._set_combo_data(self.f_scene_template, entity.scene_template)
            self._set_combo_data(self.f_status, entity.status)
            self.f_price.setText(
                "" if entity.price is None else str(entity.price.amount_dollars)
            )
            self._set_combo_data(self.f_price_period, entity.price_period)
            self.f_setup_fee.setText(
                "" if entity.setup_fee is None else str(entity.setup_fee.amount_dollars)
            )
            self.f_exclusive_category.setText(entity.exclusive_category)
            self.f_blocked_categories.setText(", ".join(entity.blocked_categories))
            self.f_traffic_override.setText(
                "" if entity.traffic_override is None else str(entity.traffic_override)
            )
            self.f_start_date.setText(entity.start_date or "")
            self.f_end_date.setText(entity.end_date or "")
            self.f_notes.setPlainText(entity.notes)
            self._update_placement_extras(kind, entity)

    def _update_placement_extras(self, kind: str, entity: Any) -> None:
        if kind != _KIND_PLACEMENT:
            return
        eff = self._controller.effective_traffic(entity.placement_id)
        if eff is None:
            self.effective_traffic_label.setText(
                "Effective weekly traffic: not set"
            )
        else:
            self.effective_traffic_label.setText(
                f"Effective weekly traffic: {eff:,}"
            )
        self.avail_result.setText("")

    @staticmethod
    def _set_combo_data(combo: QComboBox, data: Any) -> None:
        idx = combo.findData(data)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    # ------------------------------------------------------------------
    # Create handlers (context-aware)
    # ------------------------------------------------------------------
    def _on_new_retailer(self) -> None:
        self._begin_create(_KIND_RETAILER)

    def _on_new_market(self) -> None:
        self._begin_create(_KIND_MARKET)

    def _on_new_location(self) -> None:
        self._begin_create(_KIND_LOCATION)

    def _on_new_placement(self) -> None:
        self._begin_create(_KIND_PLACEMENT)

    def _begin_create(self, kind: str) -> None:
        if self._controller is None:
            return
        self._mode = kind
        self._editing_id = None
        # Prefill context from the current selection.
        self._context_retailer_id = None
        self._context_market_id = None
        self._context_location_id = None
        if self._controller.selected_kind == _KIND_RETAILER:
            self._context_retailer_id = self._controller.selected_id
        elif self._controller.selected_kind == _KIND_MARKET:
            self._context_market_id = self._controller.selected_id
        elif self._controller.selected_kind == _KIND_LOCATION:
            self._context_location_id = self._controller.selected_id
            loc = self._controller.get_location(self._controller.selected_id)
            if loc:
                self._context_retailer_id = loc.retailer_id
                self._context_market_id = loc.market_id

        self._populate_combos()
        self._clear_fields()
        self._show_kind(kind)
        self.save_button.setVisible(True)
        self.archive_button.setVisible(False)
        self.save_button.setText("Create")
        title = {
            _KIND_RETAILER: "New Retailer",
            _KIND_MARKET: "New Market",
            _KIND_LOCATION: "New Location",
            _KIND_PLACEMENT: "New Placement",
        }[kind]
        self.effective_traffic_label.setText(title)
        self.effective_traffic_label.setVisible(True)
        self.avail_result.setText("")

        # Prefill relationship combos / context.
        if kind == _KIND_LOCATION:
            self._set_combo_data(self.f_retailer, self._context_retailer_id or "")
            self._set_combo_data(self.f_market, self._context_market_id or "")
        if kind == _KIND_PLACEMENT:
            self._set_combo_data(self.f_status, STATUS_AVAILABLE)
# ------------------------------------------------------------------
    # Save / Cancel / Archive
    # ------------------------------------------------------------------
    def _on_save(self) -> None:
        if self._controller is None or not self._mode:
            return
        kind = self._mode
        if self._editing_id is None:
            self._on_create(kind)
        else:
            self._on_update(kind, self._editing_id)

    def _on_create(self, kind: str) -> None:
        # Prevent obviously orphaned entities through the UI.
        if kind == _KIND_LOCATION and not self._data(self.f_retailer):
            self._user_error("Select a retailer before creating a location.")
            return
        if kind == _KIND_PLACEMENT and not self._context_location_id:
            self._user_error("Select a location before creating a placement.")
            return
        if kind == _KIND_RETAILER:
            self._controller.create_retailer(
                name=self.f_name.text(),
                parent_company=self.f_parent_company.text(),
                brand_name=self.f_brand_name.text(),
                website=self.f_website.text(),
            )
        elif kind == _KIND_MARKET:
            self._controller.create_market(
                name=self.f_name.text(),
                state=self.f_state.text(),
                region=self.f_region.text(),
            )
        elif kind == _KIND_LOCATION:
            self._controller.create_location(
                retailer_id=self._data(self.f_retailer),
                market_id=self._data(self.f_market),
                name=self.f_name.text(),
                store_number=self.f_store_number.text(),
                address=self.f_address.text(),
                city=self.f_city.text(),
                state=self.f_state.text(),
                postal_code=self.f_postal_code.text(),
                weekly_traffic=self._int_or_none(self.f_weekly_traffic),
                latitude=self._float_or_none(self.f_latitude),
                longitude=self._float_or_none(self.f_longitude),
            )
        elif kind == _KIND_PLACEMENT:
            self._controller.create_placement(
                location_id=self._context_location_id or "",
                name=self.f_name.text(),
                placement_type=self.f_placement_type.text(),
                scene_template=self._data(self.f_scene_template),
                status=self._data(self.f_status) or STATUS_AVAILABLE,
                price=self.f_price.text(),
                price_period=self._data(self.f_price_period) or PERIOD_YEAR,
                setup_fee=self.f_setup_fee.text(),
                exclusive_category=self.f_exclusive_category.text(),
                blocked_categories=self.f_blocked_categories.text(),
                traffic_override=self._int_or_none(self.f_traffic_override),
                start_date=self.f_start_date.text(),
                end_date=self.f_end_date.text(),
                notes=self.f_notes.toPlainText(),
            )
    def _on_update(self, kind: str, entity_id: str) -> None:
        if kind == _KIND_RETAILER:
            self._controller.update_retailer(
                entity_id,
                name=self.f_name.text(),
                parent_company=self.f_parent_company.text(),
                brand_name=self.f_brand_name.text(),
                website=self.f_website.text(),
            )
        elif kind == _KIND_MARKET:
            self._controller.update_market(
                entity_id,
                name=self.f_name.text(),
                state=self.f_state.text(),
                region=self.f_region.text(),
            )
        elif kind == _KIND_LOCATION:
            self._controller.update_location(
                entity_id,
                retailer_id=self._data(self.f_retailer),
                market_id=self._data(self.f_market),
                name=self.f_name.text(),
                store_number=self.f_store_number.text(),
                address=self.f_address.text(),
                city=self.f_city.text(),
                state=self.f_state.text(),
                postal_code=self.f_postal_code.text(),
                weekly_traffic=self._int_or_none(self.f_weekly_traffic),
                latitude=self._float_or_none(self.f_latitude),
                longitude=self._float_or_none(self.f_longitude),
            )
        elif kind == _KIND_PLACEMENT:
            self._controller.update_placement(
                entity_id,
                name=self.f_name.text(),
                placement_type=self.f_placement_type.text(),
                scene_template=self._data(self.f_scene_template),
                status=self._data(self.f_status) or STATUS_AVAILABLE,
                price=self.f_price.text(),
                price_period=self._data(self.f_price_period) or PERIOD_YEAR,
                setup_fee=self.f_setup_fee.text(),
                exclusive_category=self.f_exclusive_category.text(),
                blocked_categories=self.f_blocked_categories.text(),
                traffic_override=self._int_or_none(self.f_traffic_override),
                start_date=self.f_start_date.text(),
                end_date=self.f_end_date.text(),
                notes=self.f_notes.toPlainText(),
            )

    def _on_archive(self) -> None:
        if self._controller is None or self._mode != _KIND_PLACEMENT:
            return
        if self._editing_id:
            self._controller.archive_placement(self._editing_id)

    def _on_cancel(self) -> None:
        self._show_placeholder()

    def _on_check_availability(self) -> None:
        if self._controller is None or self._mode != _KIND_PLACEMENT:
            return
        if not self._editing_id:
            return
        category = self.avail_input.text()
        details = self._controller.availability_details(self._editing_id, category)
        if details["available"]:
            self.avail_result.setText("Available")
            self.avail_result.setStyleSheet("color: #2ecc71; font-weight: 600;")
        else:
            self.avail_result.setText(details["reason"])
            self.avail_result.setStyleSheet("color: #e74c3c; font-weight: 600;")

    def _on_filter_changed(self, _index: int) -> None:
        self.refresh()

    # ------------------------------------------------------------------
    # Field helpers
    # ------------------------------------------------------------------
    def _data(self, combo: QComboBox) -> str:
        return str(combo.currentData() or "")

    def _int_or_none(self, field: QLineEdit) -> Optional[str]:
        text = field.text().strip()
        return text if text else None

    def _float_or_none(self, field: QLineEdit) -> Optional[str]:
        text = field.text().strip()
        return text if text else None

    def _clear_fields(self) -> None:
        for widget in self._fields.values():
            if isinstance(widget, QLineEdit):
                widget.clear()
            elif isinstance(widget, QPlainTextEdit):
                widget.setPlainText("")
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(0)