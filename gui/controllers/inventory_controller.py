"""Sprint 4B inventory workspace controller (Qt).

Coordinates the inventory workspace views with the Qt-free
:class:`~gui.services.inventory_workspace.InventoryWorkspaceService`. Exposes
Qt signals, invokes the service, coordinates the selected entity, surfaces
errors and notifies views after save/create/update. No field parsing or
business rules live here — those belong to the service layer.

Threading: inventory operations are local JSON and fast, so no worker threads
are created for CRUD (kept simple per the sprint brief).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from gui.models.inventory import (
    Placement,
    Retailer,
    Market,
    Location,
    PLACEMENT_STATUSES,
)
from gui.models.inventory_store import InventoryCorruptionError, InventoryStore
from gui.services.inventory_workspace import (
    InventoryValidationError,
    InventoryWorkspaceService,
)

logger = logging.getLogger(__name__)


class InventoryController(QObject):
    """Routes inventory workspace actions to the service and drives the UI."""

    # Public signals (views connect to these).
    inventory_loaded = Signal()  # after initial load
    inventory_changed = Signal()  # after any mutation / save
    error_message = Signal(str)
    status_message = Signal(str)

    def __init__(
        self,
        service: Optional[InventoryWorkspaceService] = None,
        path: Optional[str] = None,
    ) -> None:
        super().__init__()
        if service is None:
            service = InventoryWorkspaceService(
                store=InventoryStore(path=path)
            )
        self._service = service
        self._selected_kind: Optional[str] = None
        self._selected_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def service(self) -> InventoryWorkspaceService:
        return self._service

    @property
    def store(self) -> InventoryStore:
        return self._service.store

    @property
    def selected_kind(self) -> Optional[str]:
        return self._selected_kind

    @property
    def selected_id(self) -> Optional[str]:
        return self._selected_id

    def select(self, kind: Optional[str], entity_id: Optional[str]) -> None:
        """Track the currently selected entity (retailer/market/location/placement)."""
        self._selected_kind = kind
        self._selected_id = entity_id

    @staticmethod
    def placement_statuses() -> List[str]:
        return list(PLACEMENT_STATUSES)

    # ------------------------------------------------------------------
    # Load / refresh
    # ------------------------------------------------------------------
    def load(self) -> None:
        """Load inventory (empty when missing); surface corruption clearly."""
        try:
            self._service.load()
            self.inventory_loaded.emit()
        except InventoryCorruptionError as exc:
            logger.warning("Inventory load failed (corrupt): %s", exc)
            self.error_message.emit(f"Corrupt inventory file: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface any load failure
            logger.warning("Inventory load failed: %s", exc)
            self.error_message.emit(f"Could not load inventory: {exc}")

    def reload(self) -> None:
        """Force a fresh load from disk and notify views."""
        try:
            self._service.reload()
        except InventoryCorruptionError as exc:
            self.error_message.emit(f"Corrupt inventory file: {exc}")
            return
        self.inventory_changed.emit()

    # ------------------------------------------------------------------
    # Queries (delegate to service)
    # ------------------------------------------------------------------
    def hierarchy(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._service.hierarchy(status_filter)

    def list_retailers(self) -> List[Retailer]:
        return self._service.list_retailers()

    def list_markets(self) -> List[Market]:
        return self._service.list_markets()

    def list_locations(self) -> List[Location]:
        return self._service.list_locations()

    def list_placements(self) -> List[Placement]:
        return self._service.list_placements()

    def get_retailer(self, retailer_id: str) -> Optional[Retailer]:
        return self._service.get_retailer(retailer_id)

    def get_market(self, market_id: str) -> Optional[Market]:
        return self._service.get_market(market_id)

    def get_location(self, location_id: str) -> Optional[Location]:
        return self._service.get_location(location_id)

    def get_placement(self, placement_id: str) -> Optional[Placement]:
        return self._service.get_placement(placement_id)

    def scene_template_options(self) -> List[Dict[str, Any]]:
        return self._service.scene_template_options()

    def summary(self) -> Dict[str, Any]:
        return self._service.summary()

    def orphans(self) -> Dict[str, List[str]]:
        return self._service.orphans()

    def availability_details(self, placement_id: str, category: str) -> Dict[str, Any]:
        return self._service.availability_details(placement_id, category)

    def effective_traffic(self, placement_id: str) -> Optional[int]:
        return self._service.effective_traffic(placement_id)
# ------------------------------------------------------------------
    # Mutations (service handles logic + persistence; this surfaces errors)
    # ------------------------------------------------------------------
    def _mutate(self, fn, success: str) -> Any:
        try:
            result = fn()
        except InventoryValidationError as exc:
            logger.warning("Inventory validation failed: %s", exc)
            self.error_message.emit(str(exc))
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("Inventory mutation failed: %s", exc)
            self.error_message.emit(f"Save failed: {exc}")
            return None
        self.inventory_changed.emit()
        self.status_message.emit(success)
        return result

    def create_retailer(self, **kw) -> Optional[Retailer]:
        return self._mutate(
            lambda: self._service.create_retailer(**kw), "Retailer created."
        )

    def create_market(self, **kw) -> Optional[Market]:
        return self._mutate(
            lambda: self._service.create_market(**kw), "Market created."
        )

    def create_location(self, **kw) -> Optional[Location]:
        return self._mutate(
            lambda: self._service.create_location(**kw), "Location created."
        )

    def create_placement(self, **kw) -> Optional[Placement]:
        return self._mutate(
            lambda: self._service.create_placement(**kw), "Placement created."
        )

    def update_retailer(self, retailer_id: str, **kw) -> Optional[Retailer]:
        return self._mutate(
            lambda: self._service.update_retailer(retailer_id, **kw),
            "Retailer saved.",
        )

    def update_market(self, market_id: str, **kw) -> Optional[Market]:
        return self._mutate(
            lambda: self._service.update_market(market_id, **kw), "Market saved."
        )

    def update_location(self, location_id: str, **kw) -> Optional[Location]:
        return self._mutate(
            lambda: self._service.update_location(location_id, **kw),
            "Location saved.",
        )

    def update_placement(self, placement_id: str, **kw) -> Optional[Placement]:
        return self._mutate(
            lambda: self._service.update_placement(placement_id, **kw),
            "Placement saved.",
        )

    def set_placement_status(
        self, placement_id: str, status: str
    ) -> Optional[Placement]:
        return self._mutate(
            lambda: self._service.set_placement_status(placement_id, status),
            f"Placement status set to {status}.",
        )

    def archive_placement(self, placement_id: str) -> Optional[Placement]:
        return self._mutate(
            lambda: self._service.archive_placement(placement_id),
            "Placement archived.",
        )

    def remove_retailer(self, retailer_id: str) -> None:
        self._mutate(
            lambda: self._service.remove_retailer(retailer_id), "Retailer removed."
        )

    def remove_market(self, market_id: str) -> None:
        self._mutate(
            lambda: self._service.remove_market(market_id), "Market removed."
        )