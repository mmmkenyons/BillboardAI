"""Persistence for the list of recently generated websites."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_RECENT = 20


class RecentWebsitesStore:
    """Stores the last ``MAX_RECENT`` successfully generated websites.

    Persists to a JSON file. No duplicates; most recent first.
    """

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        if path is None:
            path = Path(__file__).resolve().parent.parent / "resources" / "recent_websites.json"
        self._path = Path(path)
        self._websites: list[str] = []
        self.load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def add(self, url: str) -> None:
        """Record a successfully generated website (most recent first)."""
        url = url.strip()
        if not url:
            return
        if url in self._websites:
            self._websites.remove(url)
        self._websites.insert(0, url)
        self._websites = self._websites[:MAX_RECENT]
        self.save()

    def websites(self) -> list[str]:
        """Return the stored websites, most recent first."""
        return list(self._websites)

    def load(self) -> None:
        """Load websites from disk."""
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._websites = [str(item) for item in data if item][:MAX_RECENT]
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load recent websites: %s", exc)
            self._websites = []

    def save(self) -> None:
        """Persist websites to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._websites, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Could not save recent websites: %s", exc)