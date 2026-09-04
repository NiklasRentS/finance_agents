"""Content-addressed disk cache.

Caching is a hard requirement of the cost strategy: filings never change, so
they are fetched once and reused forever.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock

from app.infra.logging import get_logger

logger = get_logger(__name__)

TTL_IMMUTABLE = timedelta(days=3650)
"""For documents that cannot change once published, e.g. a filed 10-K."""

TTL_FUNDAMENTALS = timedelta(days=1)
TTL_QUOTE = timedelta(minutes=15)


def cache_key(*parts: str) -> str:
    """Build a stable cache key from arbitrary string parts."""
    joined = "\x1f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class DiskCache:
    """Simple JSON-on-disk cache with per-entry expiry."""

    def __init__(self, root: Path, *, enabled: bool = True) -> None:
        self._root = root
        self._enabled = enabled
        self._lock = Lock()
        if self._enabled:
            self._root.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _path_for(self, key: str) -> Path:
        return self._root / key[:2] / f"{key}.json"

    def get(self, key: str) -> str | None:
        """Return the cached body, or None when absent or expired."""
        if not self._enabled:
            return None
        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("cache.unreadable", key=key)
            return None

        expires_at = raw.get("expires_at")
        if expires_at is not None and datetime.fromisoformat(expires_at) <= datetime.now(UTC):
            return None
        body = raw.get("body")
        return body if isinstance(body, str) else None

    def set(self, key: str, body: str, ttl: timedelta | None) -> None:
        """Store a body. ``ttl=None`` disables caching for this entry."""
        if not self._enabled or ttl is None:
            return
        now = datetime.now(UTC)
        payload = {
            "key": key,
            "created_at": now.isoformat(),
            "expires_at": (now + ttl).isoformat(),
            "body": body,
        }
        path = self._path_for(key)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                os.replace(tmp_name, path)
            except OSError:
                Path(tmp_name).unlink(missing_ok=True)
                raise

    def clear(self) -> int:
        """Delete every cached entry. Returns the number of removed files."""
        if not self._root.exists():
            return 0
        removed = 0
        for path in self._root.rglob("*.json"):
            path.unlink(missing_ok=True)
            removed += 1
        return removed
