"""Mocked tests for registry clients. No network calls."""

import json

import pytest

from scoutdocs_mcp.registries import (
    fetch_pypi,
    fetch_npm,
    fetch_crates,
    fetch_package,
    _UA,
)


# ---------- PyPI ----------


async def test_fetch_pypi_parses_metadata(httpx_mock, load_fixture):
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=load_fixture("pypi_requests"),
    )

    info = await fetch_pypi("requests")

    assert info is not None
    assert info.name == "requests"
    assert info.ecosystem == "python"
    assert info.latest_stable == "2.32.3"
    assert "HTTP" in info.description
    assert info.docs_url == "https://requests.readthedocs.io"
    assert info.repository == "https://github.com/psf/requests"
    assert info.license == "Apache-2.0"


async def test_fetch_pypi_skips_prereleases_and_empty_releases(httpx_mock, load_fixture):
    """Prereleases (rc/b/a) and versions without files should be skipped."""
    httpx_mock.add_response(
        url="https://pypi.org/pypi/experimental/json",
        json=load_fixture("pypi_with_prereleases"),
    )

    info = await fetch_pypi("experimental")

    assert info is not None
    # 1.4.0 has no files (empty release list); 2.0.0rc1 + 2.0.0b2 are prereleases.
    # Highest stable with files is 1.5.0.
    assert info.latest_stable == "1.5.0"


async def test_fetch_pypi_404(httpx_mock):
    httpx_mock.add_response(
        url="https://pypi.org/pypi/nonexistent/json",
        status_code=404,
    )

    info = await fetch_pypi("nonexistent")
    assert info is None


async def test_fetch_pypi_sends_user_agent(httpx_mock, load_fixture):
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json=load_fixture("pypi_requests"),
    )

    await fetch_pypi("requests")

    request = httpx_mock.get_request()
    assert request is not None
    assert request.headers["user-agent"] == _UA


# ---------- npm ----------


async def test_fetch_npm_parses_metadata(httpx_mock, load_fixture):
    httpx_mock.add_response(
        url="https://registry.npmjs.org/express",
        json=load_fixture("npm_express"),
    )

    info = await fetch_npm("express")

    assert info is not None
    assert info.name == "express"
    assert info.ecosystem == "javascript"
    assert info.latest_stable == "4.21.1"
    assert info.repository == "https://github.com/expressjs/express"
    assert info.homepage == "http://expressjs.com/"
    assert info.license == "MIT"


async def test_fetch_npm_404(httpx_mock):
    httpx_mock.add_response(
        url="https://registry.npmjs.org/nonexistent",
        status_code=404,
    )

    assert await fetch_npm("nonexistent") is None


# ---------- crates.io ----------


async def test_fetch_crates_parses_metadata(httpx_mock, load_fixture):
    httpx_mock.add_response(
        url="https://crates.io/api/v1/crates/serde",
        json=load_fixture("crates_serde"),
    )

    info = await fetch_crates("serde")

    assert info is not None
    assert info.name == "serde"
    assert info.ecosystem == "rust"
    assert info.latest_stable == "1.0.215"
    assert info.docs_url == "https://docs.rs/serde/1.0.215"
    assert info.repository == "https://github.com/serde-rs/serde"
    assert "MIT" in info.license


async def test_fetch_crates_skips_yanked_and_prereleases(httpx_mock):
    """Yanked versions and prereleases (containing '-') are skipped."""
    payload = {
        "crate": {
            "name": "demo",
            "newest_version": "0.0.0",
            "description": "demo",
            "homepage": None,
            "repository": None,
        },
        "versions": [
            {"num": "1.0.0-beta.1", "yanked": False, "license": "MIT"},
            {"num": "0.9.0", "yanked": True, "license": "MIT"},
            {"num": "0.8.0", "yanked": False, "license": "MIT"},
        ],
    }
    httpx_mock.add_response(
        url="https://crates.io/api/v1/crates/demo",
        json=payload,
    )

    info = await fetch_crates("demo")

    assert info is not None
    assert info.latest_stable == "0.8.0"


async def test_fetch_crates_sends_user_agent(httpx_mock, load_fixture):
    httpx_mock.add_response(
        url="https://crates.io/api/v1/crates/serde",
        json=load_fixture("crates_serde"),
    )

    await fetch_crates("serde")
    request = httpx_mock.get_request()
    assert request is not None
    assert request.headers["user-agent"] == _UA


# ---------- Auto-detect ----------


async def test_fetch_package_explicit_ecosystem(httpx_mock, load_fixture):
    httpx_mock.add_response(
        url="https://registry.npmjs.org/express",
        json=load_fixture("npm_express"),
    )

    info = await fetch_package("express", ecosystem="npm")
    assert info is not None
    assert info.ecosystem == "javascript"


async def test_fetch_package_unknown_ecosystem_returns_none(httpx_mock):
    info = await fetch_package("anything", ecosystem="cobol")
    assert info is None


async def test_fetch_package_auto_detect_falls_through(httpx_mock, load_fixture):
    """PyPI 404, npm hit succeeds — auto-detect should return the npm result."""
    httpx_mock.add_response(
        url="https://pypi.org/pypi/express/json",
        status_code=404,
    )
    httpx_mock.add_response(
        url="https://registry.npmjs.org/express",
        json=load_fixture("npm_express"),
    )

    info = await fetch_package("express")
    assert info is not None
    assert info.ecosystem == "javascript"


async def test_fetch_package_all_404(httpx_mock):
    for url in (
        "https://pypi.org/pypi/ghost/json",
        "https://registry.npmjs.org/ghost",
        "https://crates.io/api/v1/crates/ghost",
    ):
        httpx_mock.add_response(url=url, status_code=404)

    info = await fetch_package("ghost")
    assert info is None
