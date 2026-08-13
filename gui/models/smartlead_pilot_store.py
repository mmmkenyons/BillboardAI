"""Durable local persistence for Smartlead pilot runs and audit history."""

from __future__ import annotations

import json
import os
from typing import Any

from gui.models.smartlead_pilot import SmartleadPilotRun

DEFAULT_SMARTLEAD_PILOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "smartlead",
)
DEFAULT_SMARTLEAD_PILOT_PATH = os.path.join(DEFAULT_SMARTLEAD_PILOT_DIR, "pilot_runs.json")


class SmartleadPilotStore:
    def __init__(self, path: str | None = None) -> None:
        self._path = os.path.abspath(path or DEFAULT_SMARTLEAD_PILOT_PATH)
        self._runs: list[SmartleadPilotRun] = []
        self.load(safe_missing=True, safe_corrupt=True)

    @property
    def path(self) -> str:
        return self._path

    def list(self) -> list[SmartleadPilotRun]:
        return list(self._runs)

    def get(self, pilot_id: str) -> SmartleadPilotRun | None:
        expected = str(pilot_id or "").strip()
        for run in self._runs:
            if run.definition.pilot_id == expected:
                return run
        return None

    def get_by_campaign(self, campaign_id: str) -> list[SmartleadPilotRun]:
        expected = str(campaign_id or "").strip()
        return [run for run in self._runs if run.definition.campaign_id == expected]

    def upsert(self, run: SmartleadPilotRun) -> SmartleadPilotRun:
        existing = self.get(run.definition.pilot_id)
        if existing is None:
            self._runs.append(run)
            return run
        self._runs = [run if item.definition.pilot_id == run.definition.pilot_id else item for item in self._runs]
        return run

    def load(self, safe_missing: bool = False, safe_corrupt: bool = False) -> None:
        if not os.path.exists(self._path):
            self._runs = []
            if safe_missing:
                return
            raise FileNotFoundError(self._path)
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            if safe_corrupt:
                self._runs = []
                return
            raise
        self._runs = [SmartleadPilotRun.from_dict(item) for item in list((payload or {}).get("runs") or [])]

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        payload: dict[str, Any] = {
            "schema_version": 1,
            "runs": [item.to_dict() for item in self._runs],
        }
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, self._path)