"""Explicit models for Smartlead sequence readiness, sequence state capture, and
safe change receipts (Sprint 5R). Sequences are inspected read-only; mutation is
offer-only and never automatic. No credentials are stored.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# Required BillboardAI custom variables referenced by a BillboardAI sequence.
SEQUENCE_VARIABLE_SUBJECT = "bb_subject"
SEQUENCE_VARIABLE_BODY = "bb_body"
SEQUENCE_VARIABLE_MOCKUP_URL = "bb_mockup_url"

REQUIRED_SEQUENCE_VARIABLES: tuple[str, ...] = (
    SEQUENCE_VARIABLE_SUBJECT,
    SEQUENCE_VARIABLE_BODY,
)
# bb_mockup_url is required for full BillboardAI mockup outreach (recommended 5R mode).
REQUIRED_MOCKUP_SEQUENCE_VARIABLES: tuple[str, ...] = (SEQUENCE_VARIABLE_MOCKUP_URL,)

# Smartlead custom-field variable syntax is {{variable_name}}.
_VARIABLE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def extract_sequence_variables(text: str) -> set[str]:
    """Return the set of {{variable}} tokens present in a sequence text block."""
    return set(_VARIABLE_PATTERN.findall(str(text or "")))


def sequence_fingerprint(state: "SmartleadSequenceState") -> str:
    """Deterministic fingerprint of the current sequence content for change safety."""
    import hashlib

    canonical = "\n".join([str(state.campaign_id), str(state.sequence_exists), str(state.subject), str(state.body)]).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SmartleadSequenceStep:
    subject: str = ""
    body: str = ""
    delay_days: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SmartleadSequenceState:
    campaign_id: str
    sequence_exists: bool
    sequence_fingerprint: str = ""
    subject: str = ""
    body: str = ""
    captured_at: str = ""

    def capture_fingerprint(self) -> str:
        return sequence_fingerprint(self)


@dataclass(frozen=True)
class SmartleadSequenceProposal:
    campaign_id: str
    subject: str
    body: str
    steps: tuple[SmartleadSequenceStep, ...] = ()

    @property
    def deterministic_subject(self) -> str:
        return str(self.subject or "").strip()

    @property
    def deterministic_body(self) -> str:
        return str(self.body or "").strip()

    def fingerprint(self) -> str:
        import hashlib

        canonical = "\n".join([self.campaign_id, self.deterministic_subject, self.deterministic_body]).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class SmartleadSequenceReadiness:
    campaign_id: str
    campaign_status: str
    sequence_exists: bool
    bb_subject_present: bool
    bb_body_present: bool
    bb_mockup_url_present: bool
    sender_accounts_present: bool
    sender_account_count: int
    ready_for_manual_activation: bool
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SequenceChangeReceipt:
    campaign_id: str
    action: str
    before_fingerprint: str
    after_fingerprint: str
    changed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_SEQUENCE_CHANGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output",
    "smartlead",
)
DEFAULT_SEQUENCE_CHANGE_PATH = os.path.join(DEFAULT_SEQUENCE_CHANGE_DIR, "sequence_change_receipts.json")


class SequenceChangeStore:
    """Persistent local log of safe sequence changes. Stores never contain secrets."""

    def __init__(self, path: str | None = None) -> None:
        self._path = os.path.abspath(path or DEFAULT_SEQUENCE_CHANGE_PATH)
        self._receipts: list[SequenceChangeReceipt] = []
        self.load(safe_missing=True, safe_corrupt=True)

    @property
    def path(self) -> str:
        return self._path

    def list(self) -> list[SequenceChangeReceipt]:
        return list(self._receipts)

    def append(self, receipt: SequenceChangeReceipt) -> SequenceChangeReceipt:
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
        self._receipts = [
            SequenceChangeReceipt(
                campaign_id=str(item.get("campaign_id") or ""),
                action=str(item.get("action") or ""),
                before_fingerprint=str(item.get("before_fingerprint") or ""),
                after_fingerprint=str(item.get("after_fingerprint") or ""),
                changed_at=str(item.get("changed_at") or ""),
            )
            for item in list((payload or {}).get("receipts") or [])
        ]

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        payload: dict[str, Any] = {
            "schema_version": 1,
            "receipts": [receipt.to_dict() for receipt in self._receipts],
        }
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp, self._path)