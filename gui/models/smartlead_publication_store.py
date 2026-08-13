"""Persistent local receipt store for Smartlead publication idempotency."""

from __future__ import annotations

import json
import os
from typing import Any

from gui.models.smartlead_publication import SmartleadPublicationReceipt

DEFAULT_SMARTLEAD_PUBLICATION_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "smartlead",
)
DEFAULT_SMARTLEAD_PUBLICATION_PATH = os.path.join(DEFAULT_SMARTLEAD_PUBLICATION_DIR, "publication_receipts.json")


class SmartleadPublicationStore:
    def __init__(self, path: str | None = None) -> None:
        self._path = os.path.abspath(path or DEFAULT_SMARTLEAD_PUBLICATION_PATH)
        self._receipts: list[SmartleadPublicationReceipt] = []
        self.load(safe_missing=True, safe_corrupt=True)

    @property
    def path(self) -> str:
        return self._path

    def list(self) -> list[SmartleadPublicationReceipt]:
        return list(self._receipts)

    def append(self, receipt: SmartleadPublicationReceipt) -> SmartleadPublicationReceipt:
        self._receipts.append(receipt)
        return receipt

    def replace(self, receipt: SmartleadPublicationReceipt) -> SmartleadPublicationReceipt:
        """Replace an existing receipt by publication_id (used to persist sync state)."""
        for index, existing in enumerate(self._receipts):
            if existing.publication_id == receipt.publication_id:
                self._receipts[index] = receipt
                return receipt
        self._receipts.append(receipt)
        return receipt

    def load(self, safe_missing: bool = False, safe_corrupt: bool = False) -> None:
        if not os.path.exists(self._path):
            self._receipts = []
            if safe_missing:
                return
            raise FileNotFoundError(self._path)
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            if safe_corrupt:
                self._receipts = []
                return
            raise
        self._receipts = [SmartleadPublicationReceipt.from_dict(item) for item in list((payload or {}).get("receipts") or [])]

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        payload: dict[str, Any] = {
            "schema_version": 1,
            "receipts": [item.to_dict() for item in self._receipts],
        }
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, self._path)