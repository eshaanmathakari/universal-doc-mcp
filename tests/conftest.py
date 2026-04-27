"""Shared pytest fixtures for scoutdocs-mcp tests."""

import json
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    """Return a callable that loads a JSON fixture by filename (no extension)."""

    def _load(name: str) -> dict:
        path = FIXTURES / f"{name}.json"
        return json.loads(path.read_text())

    return _load


@pytest.fixture
def tmp_cache_dir(tmp_path, monkeypatch):
    """Redirect the default cache to a tmp dir for the test session."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("scoutdocs_mcp.cache.DEFAULT_CACHE_DIR", cache_dir)
    return cache_dir
