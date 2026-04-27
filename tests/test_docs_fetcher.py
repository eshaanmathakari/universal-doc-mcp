"""Mocked tests for docs_fetcher (README extraction, source fallback)."""

import pytest

from scoutdocs_mcp.docs_fetcher import (
    fetch_docs_content,
    fetch_npm_readme,
    fetch_pypi_description,
    fetch_readme_from_github,
    _UA,
)


async def test_pypi_description_truncated_when_long(httpx_mock):
    long_desc = "x" * 10_000
    httpx_mock.add_response(
        url="https://pypi.org/pypi/big/json",
        json={"info": {"description": long_desc}},
    )

    out = await fetch_pypi_description("big")
    assert out is not None
    assert "[truncated]" in out
    assert len(out) < len(long_desc)


async def test_pypi_description_404(httpx_mock):
    httpx_mock.add_response(url="https://pypi.org/pypi/missing/json", status_code=404)
    assert await fetch_pypi_description("missing") is None


async def test_pypi_description_empty_returns_none(httpx_mock):
    httpx_mock.add_response(
        url="https://pypi.org/pypi/empty/json",
        json={"info": {"description": ""}},
    )
    assert await fetch_pypi_description("empty") is None


async def test_npm_readme_filters_error_marker(httpx_mock):
    httpx_mock.add_response(
        url="https://registry.npmjs.org/broken",
        json={"readme": "ERROR: No README data found!"},
    )
    assert await fetch_npm_readme("broken") is None


async def test_npm_readme_returns_content(httpx_mock):
    httpx_mock.add_response(
        url="https://registry.npmjs.org/express",
        json={"readme": "# Express\nFast framework"},
    )
    out = await fetch_npm_readme("express")
    assert out == "# Express\nFast framework"


async def test_github_readme_uses_raw_accept_header(httpx_mock):
    """Regression: was sending application/vnd.github.raw+json (invalid)."""
    httpx_mock.add_response(
        url="https://api.github.com/repos/psf/requests/readme",
        text="# Requests\nclean readme",
    )

    out = await fetch_readme_from_github("https://github.com/psf/requests")
    assert out == "# Requests\nclean readme"

    request = httpx_mock.get_request()
    assert request.headers["accept"] == "application/vnd.github.raw"
    assert request.headers["user-agent"] == _UA
    assert "authorization" not in request.headers


async def test_github_readme_sends_token_when_set(httpx_mock, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    httpx_mock.add_response(
        url="https://api.github.com/repos/psf/requests/readme",
        text="readme",
    )

    await fetch_readme_from_github("https://github.com/psf/requests")
    request = httpx_mock.get_request()
    assert request.headers["authorization"] == "Bearer ghp_fake"


async def test_github_readme_skips_non_github_url():
    out = await fetch_readme_from_github("https://gitlab.com/foo/bar")
    assert out is None


async def test_github_readme_handles_404(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/psf/missing/readme",
        status_code=404,
    )
    assert await fetch_readme_from_github("https://github.com/psf/missing") is None


async def test_fetch_docs_content_python_prefers_pypi(httpx_mock):
    httpx_mock.add_response(
        url="https://pypi.org/pypi/requests/json",
        json={"info": {"description": "PyPI long description"}},
    )

    out = await fetch_docs_content("requests", "python", repo_url="https://github.com/psf/requests")
    assert out == "PyPI long description"


async def test_fetch_docs_content_falls_back_to_github(httpx_mock):
    """Python: empty PyPI description should fall through to GitHub."""
    httpx_mock.add_response(
        url="https://pypi.org/pypi/lib/json",
        json={"info": {"description": ""}},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/o/r/readme",
        text="# from github",
    )

    out = await fetch_docs_content("lib", "python", repo_url="https://github.com/o/r")
    assert out == "# from github"
