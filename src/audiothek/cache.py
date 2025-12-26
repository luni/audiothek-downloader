"""Caching utilities for Audiothek GraphQL responses."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .file_utils import ensure_directory_exists


class GraphQLCache:
    """SQLite-backed cache for GraphQL responses."""

    def __init__(
        self,
        cache_dir: str | os.PathLike[str] | None = None,
        ttl_seconds: int = 6 * 60 * 60,
        logger: logging.Logger | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Initialize the cache.

        Args:
            cache_dir: Directory where the cache database should be stored. Defaults to
                ``$XDG_CACHE_HOME/audiothek-downloader`` or ``~/.cache/audiothek-downloader``.
            ttl_seconds: Time-to-live for cached entries.
            logger: Logger instance to use for informational messages.
            enabled: Force enable/disable caching. When None, respects the
                ``AUDIOTHEK_DISABLE_CACHE`` environment variable.

        """
        self.logger = logger or logging.getLogger(__name__)
        base_dir = self._resolve_cache_dir(cache_dir)
        self.cache_path = base_dir / "graphql_cache.sqlite3"
        disable_env = os.environ.get("AUDIOTHEK_DISABLE_CACHE", "").lower() in {"1", "true", "yes"}
        if enabled is None:
            self._enabled = not disable_env
        else:
            self._enabled = enabled

        self.ttl_seconds = max(0, int(ttl_seconds)) if self._enabled else 0
        self._lock = threading.Lock()
        if self.ttl_seconds > 0:
            ensure_directory_exists(str(base_dir), self.logger)
            self._initialize_database()

    @staticmethod
    def _resolve_cache_dir(cache_dir: str | os.PathLike[str] | None) -> Path:
        if cache_dir:
            return Path(cache_dir)
        xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
        if xdg_cache_home:
            return Path(xdg_cache_home) / "audiothek-downloader"
        return Path.home() / ".cache" / "audiothek-downloader"

    def _initialize_database(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS graphql_cache (
                    cache_key TEXT PRIMARY KEY,
                    query_name TEXT,
                    query TEXT NOT NULL,
                    variables TEXT NOT NULL,
                    response TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_graphql_cache_updated_at
                ON graphql_cache(updated_at)
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.cache_path, check_same_thread=False)

    def get(self, query: str, variables: dict[str, Any], _query_name: str = "") -> dict[str, Any] | None:
        """Return cached GraphQL response if it exists and is fresh."""
        if self.ttl_seconds <= 0:
            return None

        cache_key = self._build_cache_key(query, variables)
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT response, updated_at FROM graphql_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()

        if not row:
            return None

        updated_at = float(row[1])
        if time.time() - updated_at > self.ttl_seconds:
            self._evict(cache_key)
            return None

        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            self._evict(cache_key)
            return None

    def set(self, query: str, variables: dict[str, Any], response: dict[str, Any], query_name: str = "") -> None:
        """Persist a GraphQL response in the cache."""
        if self.ttl_seconds <= 0:
            return

        cache_key = self._build_cache_key(query, variables)
        payload = json.dumps(response, separators=(",", ":"), ensure_ascii=False)
        timestamp = time.time()

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO graphql_cache(cache_key, query_name, query, variables, response, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        response=excluded.response,
                        updated_at=excluded.updated_at,
                        query_name=excluded.query_name
                    """,
                    (cache_key, query_name, query, self._serialize_variables(variables), payload, timestamp),
                )
                conn.commit()

    def clear(self) -> None:
        """Remove all cached entries."""
        if self.ttl_seconds <= 0:
            return

        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM graphql_cache")
                conn.commit()

    def _evict(self, cache_key: str) -> None:
        if self.ttl_seconds <= 0:
            return

        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM graphql_cache WHERE cache_key = ?", (cache_key,))
                conn.commit()

    @staticmethod
    def _serialize_variables(variables: dict[str, Any]) -> str:
        return json.dumps(variables, sort_keys=True, separators=(",", ":"))

    def _build_cache_key(self, query: str, variables: dict[str, Any]) -> str:
        serialized = json.dumps(
            {"query": query, "variables": variables},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
