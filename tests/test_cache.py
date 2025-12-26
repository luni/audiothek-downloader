"""Tests for GraphQL cache implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from audiothek.cache import GraphQLCache


@pytest.fixture(autouse=True)
def _enable_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure cache is enabled for cache-specific tests."""
    monkeypatch.delenv("AUDIOTHEK_DISABLE_CACHE", raising=False)


def _fake_response() -> dict[str, Any]:
    return {"data": {"result": {"value": 42}}}


def test_graphql_cache_set_and_get(tmp_path: Path) -> None:
    cache = GraphQLCache(cache_dir=str(tmp_path), ttl_seconds=3600, enabled=True)
    query = "query Test { result }"
    variables = {"id": "123"}
    response = _fake_response()

    cache.set(query, variables, response, "TestQuery")
    cached = cache.get(query, variables, "TestQuery")

    assert cached == response


def test_graphql_cache_expires_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ttl = 10
    cache = GraphQLCache(cache_dir=str(tmp_path), ttl_seconds=ttl, enabled=True)
    query = "query Test { result }"
    variables = {"id": "expiring"}
    response = _fake_response()

    current_time = {"value": 1_000.0}

    def fake_time() -> float:
        return current_time["value"]

    monkeypatch.setattr("audiothek.cache.time.time", fake_time)

    cache.set(query, variables, response, "ExpiringQuery")
    cached = cache.get(query, variables, "ExpiringQuery")
    assert cached == response

    current_time["value"] += ttl + 1
    expired = cache.get(query, variables, "ExpiringQuery")
    assert expired is None
