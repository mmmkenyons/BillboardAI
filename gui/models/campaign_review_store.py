"""Persistent store for campaign review decisions only."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from gui.models.campaign_review import CampaignReviewDecision

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_REVIEW_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "prospects",
)
DEFAULT_REVIEW_PATH = os.path.join(DEFAULT_REVIEW_DIR, "campaign_review.json")


class CampaignReviewCorruptionError(Exception):
    """Raised when the review file exists but cannot be parsed."""


class CampaignReviewStore:
    def __init__(self, path: str | None = None) -> None:
        self._path = os.path.abspath(path or DEFAULT_REVIEW_PATH)
        self._schema_version = SCHEMA_VERSION
        self._decisions: dict[str, CampaignReviewDecision] = {}
        try:
            self.load(safe_missing=True, safe_corrupt=True)
        except Exception:
            self._decisions = {}
            self._schema_version = SCHEMA_VERSION

    @property
    def path(self) -> str:
        return self._path

    def list(self) -> list[CampaignReviewDecision]:
        return [self._decisions[key] for key in sorted(self._decisions)]

    def get(self, prospect_id: str) -> CampaignReviewDecision | None:
        return self._decisions.get(str(prospect_id or "").strip())

    def upsert(self, decision: CampaignReviewDecision) -> CampaignReviewDecision:
        if not decision.prospect_id:
            return decision
        self._decisions[decision.prospect_id] = decision
        return decision

    def load(self, safe_missing: bool = False, safe_corrupt: bool = False) -> None:
        if not os.path.exists(self._path):
            self._decisions = {}
            self._schema_version = SCHEMA_VERSION
            if safe_missing:
                return
            raise FileNotFoundError(self._path)
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            if safe_corrupt:
                logger.warning("Invalid campaign review store; using empty state: %s", exc)
                self._decisions = {}
                self._schema_version = SCHEMA_VERSION
                return
            raise CampaignReviewCorruptionError(str(exc)) from exc
        raw_decisions = payload.get("decisions", []) if isinstance(payload, dict) else []
        self._schema_version = int((payload or {}).get("schema_version", SCHEMA_VERSION) or SCHEMA_VERSION)
        decisions: dict[str, CampaignReviewDecision] = {}
        for item in raw_decisions:
            if not isinstance(item, dict):
                continue
            decision = CampaignReviewDecision.from_dict(item)
            if decision.prospect_id:
                decisions[decision.prospect_id] = decision
        self._decisions = decisions

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        payload: dict[str, Any] = {
            "schema_version": self._schema_version,
            "decisions": [decision.to_dict() for decision in self.list()],
        }
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, self._path)