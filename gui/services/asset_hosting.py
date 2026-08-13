"""Hosted asset provider boundary (Sprint 5R).

The campaign / Smartlead / hosting layer depends only on this narrow provider
abstraction, never directly on a specific provider's API.

The concrete provider available in this repository is Cloudinary, reusing the
already-installed canonical ``cloudinary`` SDK and the repository's existing
environment-variable convention (``CLOUDINARY_CLOUD_NAME`` / ``CLOUDINARY_API_KEY``
/ ``CLOUDINARY_API_SECRET`` -- the same variables the legacy scraper seam reads).
No secrets are committed, logged, or serialized here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

CLOUDINARY_CLOUD_NAME_ENV = "CLOUDINARY_CLOUD_NAME"
CLOUDINARY_API_KEY_ENV = "CLOUDINARY_API_KEY"
CLOUDINARY_API_SECRET_ENV = "CLOUDINARY_API_SECRET"


@dataclass(frozen=True)
class HostingConnectionSettings:
    cloud_name_env_var: str = CLOUDINARY_CLOUD_NAME_ENV
    api_key_env_var: str = CLOUDINARY_API_KEY_ENV
    api_secret_env_var: str = CLOUDINARY_API_SECRET_ENV
    live_default: bool = False

    def cloud_name(self) -> str:
        return str(os.getenv(self.cloud_name_env_var, "") or "").strip()

    def api_key(self) -> str:
        return str(os.getenv(self.api_key_env_var, "") or "").strip()

    def api_secret(self) -> str:
        return str(os.getenv(self.api_secret_env_var, "") or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.cloud_name() and self.api_key() and self.api_secret())


@dataclass(frozen=True)
class HostingConnectionResult:
    connected: bool
    status: str
    message: str


@dataclass(frozen=True)
class UploadedAsset:
    provider_asset_id: str
    public_url: str
    secure_url: str
    width: int = 0
    height: int = 0


class HostedAssetProvider(Protocol):
    """Narrow provider boundary used by the hosting service."""

    name: str

    def test_connection(self) -> HostingConnectionResult:
        """Perform a read-only/non-destructive connection check when possible."""
        ...

    def upload_asset(self, *, source_path: str, public_id: str) -> UploadedAsset:
        ...

    def delete_asset(self, *, public_id: str) -> bool:
        """Delete a remote asset. Only used when a caller explicitly requires it."""
        ...

    def resolve_existing(self, *, public_id: str) -> UploadedAsset | None:
        """Resolve an already-uploaded asset by its deterministic public id."""
        ...
class CloudinaryAssetProvider:
    """Cloudinary concrete provider.

    * ``test_connection`` uses the read-only admin ``ping`` (no upload side effect).
      When credentials are not configured we validate configuration locally and
      return a NOT_CONFIGURED status rather than performing any network call.
    * ``upload_asset`` uploads with a deterministic ``public_id`` and never
      overwrites silently (``overwrite=False``); an existing asset is simply
      resolved and reused.
    """

    name = "cloudinary"

    def __init__(
        self,
        *,
        settings: HostingConnectionSettings | None = None,
        cloudinary: Any | None = None,
    ) -> None:
        self._settings = settings or HostingConnectionSettings()
        # Injectable for tests; default resolves the canonical Cloudinary SDK.
        self._cloudinary = cloudinary

    def _import_cloudinary(self) -> Any:
        if self._cloudinary is not None:
            return self._cloudinary
        import cloudinary  # canonical, already-installed SDK
        import cloudinary.api
        import cloudinary.uploader

        cloudinary.config(
            cloud_name=self._settings.cloud_name(),
            api_key=self._settings.api_key(),
            api_secret=self._settings.api_secret(),
            secure=True,
        )
        self._cloudinary = cloudinary
        return cloudinary

    def _require_configured(self) -> None:
        if not self._settings.configured:
            raise RuntimeError(
                "Cloudinary credentials are not configured. Set CLOUDINARY_CLOUD_NAME, "
                "CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET in the environment."
            )

    def test_connection(self) -> HostingConnectionResult:
        if not self._settings.configured:
            return HostingConnectionResult(connected=False, status="NOT_CONFIGURED", message="Hosting credentials not configured.")
        try:
            cloud = self._import_cloudinary()
            cloud.api.ping()  # read-only admin ping, no upload side effect
            return HostingConnectionResult(connected=True, status="CONNECTED", message="Hosting provider connected.")
        except Exception as exc:  # noqa: BLE001 - normalize remote errors
            return HostingConnectionResult(connected=False, status="UNAVAILABLE", message=f"Hosting connection failed: {_safe_error(exc)}")

    def upload_asset(self, *, source_path: str, public_id: str) -> UploadedAsset:
        self._require_configured()
        cloud = self._import_cloudinary()
        result = cloud.uploader.upload(
            source_path,
            public_id=str(public_id or "").strip() or None,
            overwrite=False,
            unsigned=False,
        )
        if not isinstance(result, dict):
            raise RuntimeError("Hosting provider returned a malformed upload result.")
        public_url = str(result.get("secure_url") or result.get("url") or "").strip()
        if not public_url:
            asset_id: str = str(result.get("public_id") or "").strip()
            raise RuntimeError(f"Hosting provider returned an empty URL for public_id {asset_id or public_id or 'unknown'}.")
        return UploadedAsset(
            provider_asset_id=str(result.get("public_id") or public_id or ""),
            public_url=public_url,
            secure_url=public_url,
            width=int(result.get("width") or 0),
            height=int(result.get("height") or 0),
        )

    def delete_asset(self, *, public_id: str) -> bool:
        self._require_configured()
        cloud = self._import_cloudinary()
        result = cloud.uploader.destroy(str(public_id or "").strip())
        if isinstance(result, dict):
            return str(result.get("result") or "").lower() in {"ok", "deleted"}
        return False

    def resolve_existing(self, *, public_id: str) -> UploadedAsset | None:
        self._require_configured()
        cloud = self._import_cloudinary()
        try:
            result = cloud.api.resource(str(public_id or "").strip())
        except Exception:  # noqa: BLE001 - asset simply does not exist
            return None
        if not isinstance(result, dict):
            return None
        public_url = str(result.get("secure_url") or result.get("url") or "").strip()
        if not public_url:
            return None
        return UploadedAsset(
            provider_asset_id=str(result.get("public_id") or public_id or ""),
            public_url=public_url,
            secure_url=public_url,
            width=int(result.get("width") or 0),
            height=int(result.get("height") or 0),
        )


def _safe_error(exc: Exception) -> str:
    message = str(exc or "")
    if not message:
        return type(exc).__name__
    for token in (
        CLOUDINARY_API_KEY_ENV,
        CLOUDINARY_API_SECRET_ENV,
    ):
        env_value = os.getenv(token, "")
        if env_value:
            message = message.replace(env_value, "***REDACTED***")
    return message.strip() or type(exc).__name__