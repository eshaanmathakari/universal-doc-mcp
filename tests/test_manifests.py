"""Tests for manifest/lockfile dependency detection."""

import json
import textwrap
from pathlib import Path

import pytest

from scoutdocs_mcp.manifests import (
    Dependency,
    _parse_pep508,
    detect_project_dependencies,
)


# ---------- pure helpers ----------


def test_parse_pep508_basic():
    assert _parse_pep508("requests>=2.31") == ("requests", ">=2.31")
    assert _parse_pep508("httpx") == ("httpx", None)
    assert _parse_pep508("pydantic[dotenv]>=2") == ("pydantic", ">=2")
    assert _parse_pep508("foo ; python_version>='3.11'") == ("foo", None)
    assert _parse_pep508("git+https://example.com/x.git") == (None, None)


def _names(deps, ecosystem=None):
    return sorted(d.name for d in deps if ecosystem is None or d.ecosystem == ecosystem)


# ---------- pyproject ----------


def test_detects_pyproject_dependencies(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "demo"
            version = "0.1.0"
            dependencies = ["requests>=2.31", "httpx"]
            [project.optional-dependencies]
            dev = ["pytest"]
            """
        )
    )

    deps = detect_project_dependencies(tmp_path)
    assert _names(deps) == ["httpx", "requests"]
    # dev excluded by default
    assert "pytest" not in _names(deps)

    deps_dev = detect_project_dependencies(tmp_path, include_dev=True)
    assert "pytest" in _names(deps_dev)


def test_pep735_dependency_groups(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "demo"
            version = "0.1.0"

            [dependency-groups]
            test = ["pytest", "coverage"]
            """
        )
    )

    deps = detect_project_dependencies(tmp_path, include_dev=True)
    names = _names(deps)
    assert "pytest" in names
    assert "coverage" in names


# ---------- requirements.txt ----------


def test_detects_requirements_txt(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        textwrap.dedent(
            """
            # comment
            requests==2.32.3
            httpx>=0.27
            -e .
            git+https://github.com/foo/bar.git
            uvicorn[standard]>=0.30
            """
        ).strip()
    )

    deps = detect_project_dependencies(tmp_path)
    by_name = {d.name: d for d in deps}
    assert by_name["requests"].declared_version == "==2.32.3"
    assert by_name["httpx"].declared_version == ">=0.27"
    assert by_name["uvicorn"].declared_version == ">=0.30"
    assert "bar" not in by_name  # git+ skipped


def test_requirements_dev_filename_marks_dev(tmp_path: Path):
    (tmp_path / "requirements-dev.txt").write_text("pytest>=8\n")
    deps = detect_project_dependencies(tmp_path, include_dev=True)
    pytest_dep = next(d for d in deps if d.name == "pytest")
    assert pytest_dep.is_dev is True


# ---------- uv.lock ----------


def test_detects_uv_lock(tmp_path: Path):
    (tmp_path / "uv.lock").write_text(
        textwrap.dedent(
            """
            version = 1
            [[package]]
            name = "httpx"
            version = "0.27.0"
            source = { registry = "https://pypi.org/simple" }

            [[package]]
            name = "scoutdocs-mcp"
            version = "0.2.0b1"
            source = { virtual = "." }

            [[package]]
            name = "from-git"
            version = "1.0.0"
            source = { git = "https://example.com/x.git" }
            """
        )
    )

    deps = detect_project_dependencies(tmp_path)
    names = _names(deps)
    assert "httpx" in names
    assert "scoutdocs-mcp" in names  # virtual project itself is included
    assert "from-git" not in names  # git source skipped


# ---------- npm ----------


def test_detects_package_json(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "app",
                "dependencies": {"express": "^4.21.0"},
                "devDependencies": {"vitest": "^2.0.0"},
                "peerDependencies": {"react": "^18"},
            }
        )
    )

    deps = detect_project_dependencies(tmp_path)
    assert _names(deps, "javascript") == ["express"]

    deps_dev = detect_project_dependencies(tmp_path, include_dev=True)
    names = _names(deps_dev, "javascript")
    assert "express" in names
    assert "vitest" in names
    assert "react" in names


def test_detects_package_lock(tmp_path: Path):
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "app",
                "lockfileVersion": 3,
                "packages": {
                    "": {"version": "1.0.0"},  # the project itself
                    "node_modules/express": {"version": "4.21.1"},
                    "node_modules/express/node_modules/cookie": {"version": "0.7.1"},
                },
            }
        )
    )

    deps = detect_project_dependencies(tmp_path)
    by_name = {d.name: d for d in deps}
    assert "express" in by_name and by_name["express"].declared_version == "4.21.1"
    assert "cookie" in by_name and by_name["cookie"].declared_version == "0.7.1"


# ---------- Rust ----------


def test_detects_cargo_toml(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text(
        textwrap.dedent(
            """
            [package]
            name = "demo"

            [dependencies]
            serde = "1.0"
            tokio = { version = "1.40", features = ["full"] }

            [dev-dependencies]
            criterion = "0.5"
            """
        )
    )

    deps = detect_project_dependencies(tmp_path)
    by_name = {d.name: d for d in deps if d.ecosystem == "rust"}
    assert by_name["serde"].declared_version == "1.0"
    assert by_name["tokio"].declared_version == "1.40"
    assert "criterion" not in by_name

    deps_dev = detect_project_dependencies(tmp_path, include_dev=True)
    by_name_dev = {d.name: d for d in deps_dev if d.ecosystem == "rust"}
    assert "criterion" in by_name_dev
    assert by_name_dev["criterion"].is_dev is True


def test_detects_cargo_lock(tmp_path: Path):
    (tmp_path / "Cargo.lock").write_text(
        textwrap.dedent(
            """
            version = 3

            [[package]]
            name = "serde"
            version = "1.0.215"

            [[package]]
            name = "tokio"
            version = "1.42.0"
            """
        )
    )

    deps = detect_project_dependencies(tmp_path)
    by_name = {d.name: d for d in deps if d.ecosystem == "rust"}
    assert by_name["serde"].declared_version == "1.0.215"
    assert by_name["tokio"].declared_version == "1.42.0"


# ---------- combined / edge ----------


def test_dedupes_across_sources(tmp_path: Path):
    """Same dep declared in pyproject and requirements.txt should appear once."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="0"\ndependencies=["httpx>=0.27"]\n'
    )
    (tmp_path / "requirements.txt").write_text("httpx==0.28.1\n")

    deps = detect_project_dependencies(tmp_path)
    names = [d.name for d in deps if d.ecosystem == "python"]
    assert names.count("httpx") == 1


def test_returns_empty_for_missing_root(tmp_path: Path):
    assert detect_project_dependencies(tmp_path / "does-not-exist") == []


def test_returns_empty_when_no_manifests(tmp_path: Path):
    assert detect_project_dependencies(tmp_path) == []


def test_handles_corrupt_files(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("not [valid] toml = =")
    (tmp_path / "package.json").write_text("{not json")
    (tmp_path / "Cargo.toml").write_text("[broken")

    # Should not raise.
    assert detect_project_dependencies(tmp_path) == []
