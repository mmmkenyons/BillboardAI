"""Durable local receipt store for hosted mockup assets (Sprint 5R).

Purpose is idempotency: the same authoritative mockup (by canonical generation +
job + project provenance and content fingerprint) is not uploaded twice, and
restart preserves the known public URL. No secrets are ever serialized.
"""

from __future__ import annotations

import json
import os
from typing import Any

from gui.models.hosted_asset import HostedMockupAsset, hosted_identity_key

DEFAULT_HOSTED_ASSET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "hosting",
)
DEFAULT_HOSTED_ASSET_PATH = os.path.join(DEFAULT_HOSTED_ASSET_DIR, "hosted_asset_receipts.json")


class HostedAssetStore:
    def __init__(self, path: str | None = None) -> None:
        self._path = os.path.abspath(path or DEFAULT_HOSTED_ASSET_PATH)
        self._assets: list[HostedMockupAsset] = []
        self.load(safe_missing=True, safe_corrupt=True)

    @property
    def path(self) -> str:
        return self._path

    def list(self) -> list[HostedMockupAsset]:
        return list(self._assets)

    def get(self, identity_key: str) -> HostedMockupAsset | None:
        for asset in self._assets:
            if asset.identity_key() == identity_key:
                return asset
        return None

    def find_by_prospect(self, prospect_id: str) -> list[HostedMockupAsset]:
        pid = str(prospect_id or "").strip()
        return [asset for asset in self._assets if asset.prospect_id == pid]

    def put(self, asset: HostedMockupAsset) -> HostedMockupAsset:
        identity = asset.identity_key()
        for index, existing in enumerate(self._assets):
            if existing.identity_key() == identity:
                self._assets[index] = asset
                return asset
        self._assets.append(asset)
        return asset

    def load(self, safe_missing: bool = False, safe_corrupt: bool = False) -> None:
        if not os.path.exists(self._path):
            self._assets = []
            if safe_missing:
                return
            raise FileNotFoundError(self._path)
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            if safe_corrupt:
                self._assets = []
                return
            raise
        self._assets = [HostedMockupAsset.from_dict(item) for item in list((payload or {}).get("assets") or [])]

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        payload: dict[str, Any] = {
            "schema_version": 1,
            "assets": [asset.to_dict() for asset in self._assets],
        }
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, self._path)