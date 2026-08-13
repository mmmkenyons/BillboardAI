"""Explicit models for hosted mockup assets and per-asset hosting results.

Sprint 5R. These models carry the durable identity, provider provenance, and
public URL contract for approved BillboardAI mockups once they are copied to a
remote hosting provider (e.g. Cloudinary). No secret credentials are ever stored
on these records.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

HOSTING_MODE_DRY_RUN = "DRY_RUN"
HOSTING_MODE_LIVE = "LIVE"

HOSTING_STATUS_PENDING = "PENDING"
HOSTING_STATUS_HOSTED = "HOSTED"
HOSTING_STATUS_REUSED = "REUSED"
HOSTING_STATUS_FAILED = "FAILED"
HOSTING_STATUS_BLOCKED = "BLOCKED"

HOSTING_STATUSES: tuple[str, ...] = (
    HOSTING_STATUS_PENDING,
    HOSTING_STATUS_HOSTED,
    HOSTING_STATUS_REUSED,
    HOSTING_STATUS_FAILED,
    HOSTING_STATUS_BLOCKED,
)

# External, recipient-facing URLs must be HTTPS and non-empty. Values are
# provider-returned only; local paths are never accepted.
_HTTPS_PATTERN = re.compile(r"^https://")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hosted_identity_key(*, generation_job_id: str, project_id: str, source_fingerprint: str) -> str:
    """Deterministic identity for a hosted asset.

    Built from the canonical generation/job/project provenance plus the content
    fingerprint so that the same file is never uploaded twice and a changed file
    is never silently treated as unchanged.
    """
    return f"{str(generation_job_id or '').strip()}::{str(project_id or '').strip()}::{str(source_fingerprint or '').strip()}"


def is_valid_public_url(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text) and bool(_HTTPS_PATTERN.match(text))


@dataclass(frozen=True)
class HostedMockupAsset:
    """A durable, idempotent record of one hosted mockup upload."""

    prospect_id: str
    generation_job_id: str
    project_id: str
    source_path: str
    source_fingerprint: str
    provider: str
    provider_asset_id: str
    public_url: str
    secure_url: str
    hosted_at: str = ""
    width: int = 0
    height: int = 0
    bytes: int = 0

    def identity_key(self) -> str:
        return hosted_identity_key(
            generation_job_id=self.generation_job_id,
            project_id=self.project_id,
            source_fingerprint=self.source_fingerprint,
        )

    @property
    def has_valid_public_url(self) -> bool:
        return is_valid_public_url(self.public_url)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "HostedMockupAsset":
        raw = data if isinstance(data, dict) else {}
        return cls(
            prospect_id=str(raw.get("prospect_id") or ""),
            generation_job_id=str(raw.get("generation_job_id") or ""),
            project_id=str(raw.get("project_id") or ""),
            source_path=str(raw.get("source_path") or ""),
            source_fingerprint=str(raw.get("source_fingerprint") or ""),
            provider=str(raw.get("provider") or ""),
            provider_asset_id=str(raw.get("provider_asset_id") or ""),
            public_url=str(raw.get("public_url") or ""),
            secure_url=str(raw.get("secure_url") or ""),
            hosted_at=str(raw.get("hosted_at") or ""),
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
            bytes=int(raw.get("bytes") or 0),
        )


@dataclass(frozen=True)
class HostingCandidate:
    """A prospective mockup that may be hosted (approved / 5P READY or WARNING)."""

    prospect_id: str
    source_path: str
    generation_job_id: str
    project_id: str
    provider_asset_id: str
    status: str = HOSTING_STATUS_PENDING
    source_fingerprint: str = ""
    source_valid: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HostingConflictAsset:
    """A non-approved/out-of-scope asset that must never be uploaded."""

    prospect_id: str
    source_path: str
    status: str = HOSTING_STATUS_BLOCKED
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HostingAssetResult:
    """Per-asset outcome after a hosting dry-run or live run."""

    prospect_id: str
    source_path: str
    source_fingerprint: str
    status: str
    public_url: str = ""
    reason: str = ""
    reused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HostingSummary:
    mode: str
    success: bool
    message: str
    total_candidates: int = 0
    total_currently_hosted_or_reused: int = 0
    hosted: int = 0
    reused: int = 0
    pending: int = 0
    failed: int = 0
    blocked: int = 0
    results: tuple[HostingAssetResult, ...] = ()

    def counts(self) -> dict[str, int]:
        return {
            "total_candidates": self.total_candidates,
            "hosted": self.hosted,
            "reused": self.reused,
            "pending": self.pending,
            "failed": self.failed,
            "blocked": self.blocked,
        }