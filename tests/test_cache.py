"""Tests for the SQLite-backed DocsCache."""

import time
from pathlib import Path

from scoutdocs_mcp.cache import DocsCache


def test_set_and_get_roundtrip(tmp_path: Path):
    cache = DocsCache(cache_dir=tmp_path, ttl=60)
    cache.set("k", {"hello": "world"})
    assert cache.get("k") == {"hello": "world"}


def test_get_missing_key(tmp_path: Path):
    cache = DocsCache(cache_dir=tmp_path)
    assert cache.get("nope") is None


def test_ttl_expiry(tmp_path: Path):
    """Entries older than ttl seconds return None."""
    cache = DocsCache(cache_dir=tmp_path, ttl=1)
    cache.set("k", {"v": 1})
    # Force expiration by reaching back into the row and rewriting fetched_at.
    conn = cache._get_conn()
    conn.execute("UPDATE docs_cache SET fetched_at = ? WHERE key = ?", (time.time() - 10, "k"))
    conn.commit()
    assert cache.get("k") is None


def test_overwrite_replaces_value(tmp_path: Path):
    cache = DocsCache(cache_dir=tmp_path)
    cache.set("k", {"v": 1})
    cache.set("k", {"v": 2})
    assert cache.get("k") == {"v": 2}


def test_stats_counts(tmp_path: Path):
    cache = DocsCache(cache_dir=tmp_path, ttl=1)
    cache.set("fresh", {"v": 1})
    cache.set("stale", {"v": 2})
    conn = cache._get_conn()
    conn.execute("UPDATE docs_cache SET fetched_at = ? WHERE key = ?", (time.time() - 10, "stale"))
    conn.commit()

    stats = cache.stats()
    assert stats["total"] == 2
    assert stats["valid"] == 1
    assert stats["expired"] == 1


def test_clear_empties_cache(tmp_path: Path):
    cache = DocsCache(cache_dir=tmp_path)
    cache.set("k", {"v": 1})
    cache.clear()
    assert cache.stats()["total"] == 0
