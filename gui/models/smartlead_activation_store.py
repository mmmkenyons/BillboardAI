"""Persistent local activation receipt store for Smartlead campaign activation."""

from __future__ import annotations

import json
import os
from typing import Any

from gui.models.smartlead_activation import SmartleadActivationReceipt

DEFAULT_SMARTLEAD_ACTIVATION_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "smartlead",
)
DEFAULT_SMARTLEAD_ACTIVATION_PATH = os.path.join(DEFAULT_SMARTLEAD_ACTIVATION_DIR, "activation_receipts.json")


class SmartleadActivationStore:
    def __init__(self, path: str | None = None) -> None:
        self._path = os.path.abspath(path or DEFAULT_SMARTLEAD_ACTIVATION_PATH)
        self._receipts: list[SmartleadActivationReceipt] = []
        self.load(safe_missing=True, safe_corrupt=True)

    @property
    def path(self) -> str:
        return self._path

    def list(self) -> list[SmartleadActivationReceipt]:
        return list(self._receipts)

    def append(self, receipt: SmartleadActivationReceipt) -> SmartleadActivationReceipt:
        self._receipts.append(receipt)
        return receipt

    def find_by_campaign(self, campaign_id: str) -> list[SmartleadActivationReceipt]:
        expected = str(campaign_id or "").strip()
        return [receipt for receipt in self._receipts if receipt.campaign_id == expected]

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
        self._receipts = [SmartleadActivationReceipt.from_dict(item) for item in list((payload or {}).get("receipts") or [])]

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