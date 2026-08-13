"""Asset hosting service (Sprint 5R): resolve publishable mockups, fingerprint,
reuse idempotent receipts, dry-run, upload via provider, and persist durable
receipts. Never uploads non-approved assets and never runs during unit tests
(which inject a fake provider).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from typing import Any

from gui.models.hosted_asset import (
    HOSTING_MODE_DRY_RUN,
    HOSTING_MODE_LIVE,
    HOSTING_STATUS_BLOCKED,
    HOSTING_STATUS_FAILED,
    HOSTING_STATUS_HOSTED,
    HOSTING_STATUS_PENDING,
    HOSTING_STATUS_REUSED,
    HostedMockupAsset,
    HostingAssetResult,
    HostingCandidate,
    HostingSummary,
    hosted_identity_key,
    is_valid_public_url,
    utc_now_iso,
)
from gui.models.hosted_asset_store import HostedAssetStore
from gui.services.asset_hosting import HostedAssetProvider

HOSTING_ROOT_FOLDER = "billboardai"


def sha256_file(path: str) -> str:
    """Deterministic content fingerprint (SHA-256). Timestamps are never used."""
    if not path or not os.path.isfile(path):
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_segment(value: str, *, max_len: int = 96) -> str:
    """Sanitize a naming segment to a safe provider public-id token."""
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-_")
    text = text[:max_len].strip("-_")
    return text or "unknown"


def build_public_id(*, package_id: str, prospect_id: str, generation_job_id: str) -> str:
    """Deterministic provider asset/public id.

    Pattern: billboardai/<campaign-package-id>/<prospect-id>/<generation-job-id>.
    Sanitizes provider-specific values and avoids accidental collisions by always
    including the package id (never relying only on company name).
    """
    parts = [
        HOSTING_ROOT_FOLDER,
        sanitize_segment(package_id, max_len=48),
        sanitize_segment(prospect_id, max_len=64),
        sanitize_segment(generation_job_id, max_len=32),
    ]
    return "/".join(parts)


class AssetHostingService:
    def __init__(
        self,
        *,
        provider: HostedAssetProvider,
        asset_store: HostedAssetStore | None = None,
    ) -> None:
        self._provider = provider
        self._asset_store = asset_store or HostedAssetStore()

    @property
    def provider(self) -> HostedAssetProvider:
        return self._provider

    @property
    def asset_store(self) -> HostedAssetStore:
        return self._asset_store

    def test_connection(self):
        return self._provider.test_connection()

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def resolve_candidates(self, package_directory: str, handoff_directory: str) -> tuple[list[HostingCandidate], list[HostingAssetResult]]:
        """Resolve publishable mockups (handoff READY/WARNING only) plus blocked ones."""
        package_root = os.path.abspath(str(package_directory or ""))
        handoff_root = os.path.abspath(str(handoff_directory or ""))
        candidates: list[HostingCandidate] = []
        blocked: list[HostingAssetResult] = []

        handoff_manifest_path = os.path.join(handoff_root, "smartlead_handoff_manifest.json")
        manifest_path = os.path.join(package_root, "manifest.json")
        package_root2 = package_root
        if not os.path.isfile(handoff_manifest_path) or not os.path.isfile(manifest_path):
            return candidates, blocked

        with open(manifest_path, "r", encoding="utf-8") as handle:
            package_manifest = json.load(handle)
        with open(handoff_manifest_path, "r", encoding="utf-8") as handle:
            handoff_manifest = json.load(handle)

        resolved_package_root = os.path.abspath(str(handoff_manifest.get("package_directory") or package_root2))
        package_id = str(package_manifest.get("package_id") or "")
        prospects_by_id: dict[str, dict[str, Any]] = {}
        for entry in list(package_manifest.get("prospects") or []):
            if isinstance(entry, dict):
                prospects_by_id[str(entry.get("prospect_id") or "")] = entry

        for row in list(handoff_manifest.get("rows") or []):
            if not isinstance(row, dict):
                continue
            prospect_id = str(row.get("prospect_id") or "")
            status = str(row.get("status") or "").upper()
            if not prospect_id:
                continue
            entry = prospects_by_id.get(prospect_id)
            relative = str((entry or {}).get("mockup_relative_path") or "").strip()
            source_path = os.path.join(resolved_package_root, relative.replace("/", os.sep)) if relative else ""
            generation_job_id = str((entry or {}).get("generation_job_id") or "")
            project_id = str((entry or {}).get("project_id") or "")
            public_id = build_public_id(package_id=package_id, prospect_id=prospect_id, generation_job_id=generation_job_id)
            if status not in {"READY", "WARNING"}:
                blocked.append(
                    HostingAssetResult(
                        prospect_id=prospect_id,
                        source_path=source_path,
                        source_fingerprint="",
                        status=HOSTING_STATUS_BLOCKED,
                        reason=f"Asset is not eligible for hosting (status {status}).",
                    )
                )
                continue
            candidates.append(
                HostingCandidate(
                    prospect_id=prospect_id,
                    source_path=source_path,
                    generation_job_id=generation_job_id,
                    project_id=project_id,
                    provider_asset_id=public_id,
                )
            )
        return candidates, blocked

    # ------------------------------------------------------------------
    # Fingerprinting + idempotency
    # ------------------------------------------------------------------
    def _enrich(self, candidate: HostingCandidate) -> HostingCandidate:
        fingerprint = sha256_file(candidate.source_path)
        source_valid = bool(fingerprint) and os.path.isfile(candidate.source_path)
        return HostingCandidate(
            prospect_id=candidate.prospect_id,
            source_path=candidate.source_path,
            generation_job_id=candidate.generation_job_id,
            project_id=candidate.project_id,
            provider_asset_id=candidate.provider_asset_id,
            status=candidate.status,
            source_fingerprint=fingerprint,
            source_valid=source_valid,
            reason=candidate.reason,
        )

    def _existing_asset(self, candidate: HostingCandidate) -> HostedMockupAsset | None:
        if not candidate.source_fingerprint:
            return None
        key = hosted_identity_key(
            generation_job_id=candidate.generation_job_id,
            project_id=candidate.project_id,
            source_fingerprint=candidate.source_fingerprint,
        )
        existing = self._asset_store.get(key)
        if existing is not None and existing.has_valid_public_url:
            return existing
        return None

    def _existing_for_prospect(self, prospect_id: str) -> list[HostedMockupAsset]:
        return self._asset_store.find_by_prospect(prospect_id)

    def find_stale(self, candidates: list[HostingCandidate]) -> dict[str, list[HostedMockupAsset]]:
        """Detect previously hosted assets whose source fingerprint has changed.

        A changed fingerprint means the old hosted URL must NOT be silently reused
        as current; it is marked stale and the new version requires an explicit
        re-upload. Old remote assets are never silently overwritten or deleted.
        """
        stale: dict[str, list[HostedMockupAsset]] = {}
        for candidate in candidates:
            if not candidate.source_fingerprint:
                continue
            for old in self._existing_for_prospect(candidate.prospect_id):
                if old.source_fingerprint != candidate.source_fingerprint:
                    stale.setdefault(candidate.prospect_id, []).append(old)
        return stale

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------
    def dry_run(self, package_directory: str, handoff_directory: str) -> HostingSummary:
        candidates, blocked = self.resolve_candidates(package_directory, handoff_directory)
        results: list[HostingAssetResult] = list(blocked)
        hosted = 0
        reused = 0
        pending = 0
        for raw in candidates:
            candidate = self._enrich(raw)
            if not candidate.source_valid:
                results.append(
                    HostingAssetResult(
                        prospect_id=candidate.prospect_id,
                        source_path=candidate.source_path,
                        source_fingerprint="",
                        status=HOSTING_STATUS_BLOCKED,
                        reason="Source mockup file is missing or unreadable.",
                    )
                )
                continue
            existing = self._existing_asset(candidate)
            if existing is not None:
                reused += 1
                results.append(
                    HostingAssetResult(
                        prospect_id=candidate.prospect_id,
                        source_path=candidate.source_path,
                        source_fingerprint=candidate.source_fingerprint,
                        status=HOSTING_STATUS_REUSED,
                        public_url=existing.public_url,
                        reason="Already hosted; reusing persisted URL.",
                        reused=True,
                    )
                )
            else:
                pending += 1
                results.append(
                    HostingAssetResult(
                        prospect_id=candidate.prospect_id,
                        source_path=candidate.source_path,
                        source_fingerprint=candidate.source_fingerprint,
                        status=HOSTING_STATUS_PENDING,
                        reason="Needs upload in live mode.",
                    )
                )
        return HostingSummary(
            mode=HOSTING_MODE_DRY_RUN,
            success=True,
            message=f"Hosting dry run prepared. No remote uploads performed. ({len(candidates)} candidates, {pending} pending, {reused} reused).",
            total_candidates=len(candidates),
            total_currently_hosted_or_reused=reused,
            hosted=hosted,
            reused=reused,
            pending=pending,
            failed=0,
            blocked=len(blocked),
            results=tuple(results),
        )

    # ------------------------------------------------------------------
    # Live hosting
    # ------------------------------------------------------------------
    def host(
        self,
        package_directory: str,
        handoff_directory: str,
        *,
        mode: str = HOSTING_MODE_DRY_RUN,
        live_enabled: bool = False,
        confirmed: bool = False,
    ) -> HostingSummary:
        resolved_mode = HOSTING_MODE_LIVE if mode == HOSTING_MODE_LIVE else HOSTING_MODE_DRY_RUN
        if resolved_mode == HOSTING_MODE_DRY_RUN:
            return self.dry_run(package_directory, handoff_directory)
        if not live_enabled or not confirmed:
            return HostingSummary(
                mode=HOSTING_MODE_LIVE,
                success=False,
                message="Live hosting requires explicit enable and confirmation.",
            )
        candidates, blocked = self.resolve_candidates(package_directory, handoff_directory)
        results: list[HostingAssetResult] = list(blocked)
        hosted_count = 0
        reused_count = 0
        failed_count = 0
        for raw in candidates:
            candidate = self._enrich(raw)
            if not candidate.source_valid:
                results.append(
                    HostingAssetResult(
                        prospect_id=candidate.prospect_id,
                        source_path=candidate.source_path,
                        source_fingerprint="",
                        status=HOSTING_STATUS_BLOCKED,
                        reason="Source mockup file is missing or unreadable.",
                    )
                )
                continue
            existing = self._existing_asset(candidate)
            if existing is not None:
                reused_count += 1
                results.append(
                    HostingAssetResult(
                        prospect_id=candidate.prospect_id,
                        source_path=candidate.source_path,
                        source_fingerprint=candidate.source_fingerprint,
                        status=HOSTING_STATUS_REUSED,
                        public_url=existing.public_url,
                        reason="Already hosted; reusing persisted URL.",
                        reused=True,
                    )
                )
                continue
            try:
                uploaded = self._provider.upload_asset(
                    source_path=candidate.source_path,
                    public_id=candidate.provider_asset_id,
                )
            except Exception as exc:  # noqa: BLE001 - per-asset failure isolation
                failed_count += 1
                results.append(
                    HostingAssetResult(
                        prospect_id=candidate.prospect_id,
                        source_path=candidate.source_path,
                        source_fingerprint=candidate.source_fingerprint,
                        status=HOSTING_STATUS_FAILED,
                        reason=f"Upload failed: {_safe_exc(exc)}",
                    )
                )
                continue
            url = str(uploaded.secure_url or uploaded.public_url or "")
            if not is_valid_public_url(url):
                failed_count += 1
                results.append(
                    HostingAssetResult(
                        prospect_id=candidate.prospect_id,
                        source_path=candidate.source_path,
                        source_fingerprint=candidate.source_fingerprint,
                        status=HOSTING_STATUS_FAILED,
                        reason="Provider did not return a valid HTTPS public URL.",
                    )
                )
                continue

            asset = HostedMockupAsset(
                prospect_id=candidate.prospect_id,
                generation_job_id=candidate.generation_job_id,
                project_id=candidate.project_id,
                source_path=candidate.source_path,
                source_fingerprint=candidate.source_fingerprint,
                provider=self._provider.name,
                provider_asset_id=uploaded.provider_asset_id or candidate.provider_asset_id,
                public_url=url,
                secure_url=url,
                hosted_at=utc_now_iso(),
                width=uploaded.width,
                height=uploaded.height,
                bytes=os.path.getsize(candidate.source_path),
            )
            self._asset_store.put(asset)
            self._asset_store.save()
            hosted_count += 1
            results.append(
                HostingAssetResult(
                    prospect_id=candidate.prospect_id,
                    source_path=candidate.source_path,
                    source_fingerprint=candidate.source_fingerprint,
                    status=HOSTING_STATUS_HOSTED,
                    public_url=url,
                    reason="Hosted.",
                )
            )
        return HostingSummary(
            mode=HOSTING_MODE_LIVE,
            success=failed_count == 0,
            message=f"Hosting completed. Hosted: {hosted_count}, Reused: {reused_count}, Failed: {failed_count}, Blocked: {len(blocked)}.",
            total_candidates=len(candidates),
            total_currently_hosted_or_reused=reused_count,
            hosted=hosted_count,
            reused=reused_count,
            pending=0,
            failed=failed_count,
            blocked=len(blocked),
            results=tuple(results),
        )


def _safe_exc(exc: Exception) -> str:
    message = str(exc or "")
    return message.strip() or type(exc).__name__