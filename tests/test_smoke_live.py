"""Live smoke tests against real registries.

These hit pypi.org / registry.npmjs.org / crates.io. They are skipped by
default to keep CI deterministic. Run before a release with:

    RUN_LIVE_TESTS=1 uv run pytest tests/test_smoke_live.py
"""

import os

import pytest

from scoutdocs_mcp.registries import fetch_pypi, fetch_npm, fetch_crates


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="Set RUN_LIVE_TESTS=1 to run live registry checks",
)


async def test_live_pypi_requests():
    info = await fetch_pypi("requests")
    assert info is not None and info.latest_stable


async def test_live_npm_express():
    info = await fetch_npm("express")
    assert info is not None and info.latest_stable


async def test_live_crates_serde():
    info = await fetch_crates("serde")
    assert info is not None and info.latest_stable
    assert "docs.rs/serde" in (info.docs_url or "")
