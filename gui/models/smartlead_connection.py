"""Connection and request policy models for Smartlead live API access."""

from __future__ import annotations

import os
from dataclasses import dataclass

SMARTLEAD_DEFAULT_BASE_URL = "https://server.smartlead.ai/api/v1"
SMARTLEAD_API_KEY_ENV = "SMARTLEAD_API_KEY"


@dataclass(frozen=True)
class SmartleadConnectionSettings:
    base_url: str = SMARTLEAD_DEFAULT_BASE_URL
    api_key_env_var: str = SMARTLEAD_API_KEY_ENV
    timeout_seconds: float = 30.0
    dry_run_default: bool = True
    max_retries: int = 2

    def resolve_api_key(self) -> str:
        return str(os.getenv(self.api_key_env_var, "") or "").strip()

    @property
    def api_key_configured(self) -> bool:
        return bool(self.resolve_api_key())