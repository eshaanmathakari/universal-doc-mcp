"""Detect declared project dependencies from common manifests/lockfiles.

Local-only tool (the hosted Worker has no filesystem). Beta supports the
manifests most teams actually use; pnpm-lock.yaml, yarn.lock, Pipfile.lock,
go.mod, Gemfile, etc. are deferred.

Supported (beta):
    Python : pyproject.toml, requirements*.txt, uv.lock
    npm    : package.json, package-lock.json
    Rust   : Cargo.toml, Cargo.lock
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover — 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]


PEP503_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
REQ_LINE = re.compile(
    r"""
    ^\s*
    (?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)
    (?:\[[^\]]+\])?                     # extras
    \s*
    (?P<spec>[<>=!~][^;#]*)?            # version spec
    """,
    re.VERBOSE,
)


@dataclass
class Dependency:
    name: str
    ecosystem: str
    declared_version: Optional[str]
    source_file: str
    is_dev: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(deps: Iterable[Dependency]) -> list[Dependency]:
    seen: dict[tuple[str, str], Dependency] = {}
    for dep in deps:
        key = (dep.ecosystem, dep.name.lower())
        if key not in seen:
            seen[key] = dep
    return list(seen.values())


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


def _parse_pep508(spec: str) -> tuple[Optional[str], Optional[str]]:
    """Return (name, version_spec) from a PEP 508 requirement string."""
    spec = spec.split(";", 1)[0].strip()
    if not spec or spec.startswith(("-", "@", "git+", "https://", "http://")):
        return None, None
    name_match = PEP503_NAME.match(spec)
    if not name_match:
        return None, None
    name = name_match.group(0)
    rest = spec[name_match.end() :].strip()
    if rest.startswith("["):
        rest = rest.split("]", 1)[-1].strip()
    return name, (rest or None)


def _from_pyproject(path: Path, root: Path, include_dev: bool) -> list[Dependency]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return []
    deps: list[Dependency] = []
    project = data.get("project", {}) or {}

    for raw in project.get("dependencies") or []:
        name, version = _parse_pep508(str(raw))
        if name:
            deps.append(
                Dependency(name, "python", version, _rel(path, root), is_dev=False)
            )

    if include_dev:
        for group_deps in (project.get("optional-dependencies") or {}).values():
            for raw in group_deps:
                name, version = _parse_pep508(str(raw))
                if name:
                    deps.append(
                        Dependency(name, "python", version, _rel(path, root), is_dev=True)
                    )
        # PEP 735 dependency-groups
        for group_deps in (data.get("dependency-groups") or {}).values():
            for raw in group_deps:
                if isinstance(raw, str):
                    name, version = _parse_pep508(raw)
                    if name:
                        deps.append(
                            Dependency(name, "python", version, _rel(path, root), is_dev=True)
                        )
    return deps


def _from_requirements_txt(path: Path, root: Path) -> list[Dependency]:
    deps: list[Dependency] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(("-", "git+", "http://", "https://")):
                continue
            match = REQ_LINE.match(stripped)
            if not match:
                continue
            name = match.group("name")
            version = (match.group("spec") or "").strip() or None
            # requirements*.txt are conventionally dev/test if filename includes dev/test
            is_dev = any(token in path.name.lower() for token in ("dev", "test"))
            deps.append(Dependency(name, "python", version, _rel(path, root), is_dev=is_dev))
    except OSError:
        return []
    return deps


def _from_uv_lock(path: Path, root: Path) -> list[Dependency]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return []
    deps: list[Dependency] = []
    for pkg in data.get("package", []) or []:
        name = pkg.get("name")
        version = pkg.get("version")
        if not name:
            continue
        # Only include packages sourced from a registry (skip the project itself + git/path).
        source = pkg.get("source", {}) or {}
        if "registry" not in source and "virtual" not in source:
            continue
        deps.append(Dependency(name, "python", version, _rel(path, root)))
    return deps


# ---------------------------------------------------------------------------
# npm
# ---------------------------------------------------------------------------


def _from_package_json(path: Path, root: Path, include_dev: bool) -> list[Dependency]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    deps: list[Dependency] = []
    for name, version in (data.get("dependencies") or {}).items():
        deps.append(Dependency(name, "javascript", str(version), _rel(path, root)))
    if include_dev:
        for name, version in (data.get("devDependencies") or {}).items():
            deps.append(
                Dependency(name, "javascript", str(version), _rel(path, root), is_dev=True)
            )
        for name, version in (data.get("peerDependencies") or {}).items():
            deps.append(
                Dependency(name, "javascript", str(version), _rel(path, root), is_dev=True)
            )
    return deps


def _from_package_lock(path: Path, root: Path) -> list[Dependency]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    deps: list[Dependency] = []
    # npm 7+ format: "packages": {"node_modules/foo": {"version": "..."}}
    for key, meta in (data.get("packages") or {}).items():
        if not key or key == "":
            continue
        if not isinstance(meta, dict):
            continue
        version = meta.get("version")
        # Strip leading "node_modules/"; nested deps look like "node_modules/a/node_modules/b"
        last = key.rsplit("node_modules/", 1)[-1]
        if not last:
            continue
        deps.append(Dependency(last, "javascript", version, _rel(path, root)))
    return deps


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------


def _from_cargo_toml(path: Path, root: Path, include_dev: bool) -> list[Dependency]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return []
    deps: list[Dependency] = []

    def _flatten(table: dict, is_dev: bool) -> None:
        for name, spec in (table or {}).items():
            if isinstance(spec, str):
                version = spec
            elif isinstance(spec, dict):
                version = spec.get("version")
            else:
                version = None
            deps.append(
                Dependency(name, "rust", version, _rel(path, root), is_dev=is_dev)
            )

    _flatten(data.get("dependencies"), False)
    if include_dev:
        _flatten(data.get("dev-dependencies"), True)
        _flatten(data.get("build-dependencies"), True)
    return deps


def _from_cargo_lock(path: Path, root: Path) -> list[Dependency]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return []
    deps: list[Dependency] = []
    for pkg in data.get("package", []) or []:
        name = pkg.get("name")
        version = pkg.get("version")
        if not name:
            continue
        deps.append(Dependency(name, "rust", version, _rel(path, root)))
    return deps


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


PYTHON_REQ_GLOBS = ("requirements.txt", "requirements-*.txt", "requirements/*.txt")


def detect_project_dependencies(
    root: Optional[Path] = None,
    include_dev: bool = False,
) -> list[Dependency]:
    """Walk *root* (default cwd) for known manifests; return a deduped list."""
    base = Path(root or Path.cwd()).resolve()
    if not base.exists() or not base.is_dir():
        return []

    collected: list[Dependency] = []

    # --- Python -----------------------------------------------------------
    pyproject = base / "pyproject.toml"
    if pyproject.is_file():
        collected.extend(_from_pyproject(pyproject, base, include_dev))

    for pattern in PYTHON_REQ_GLOBS:
        for path in base.glob(pattern):
            if path.is_file():
                collected.extend(_from_requirements_txt(path, base))

    uv_lock = base / "uv.lock"
    if uv_lock.is_file():
        collected.extend(_from_uv_lock(uv_lock, base))

    # --- npm --------------------------------------------------------------
    package_json = base / "package.json"
    if package_json.is_file():
        collected.extend(_from_package_json(package_json, base, include_dev))

    package_lock = base / "package-lock.json"
    if package_lock.is_file():
        collected.extend(_from_package_lock(package_lock, base))

    # --- Rust -------------------------------------------------------------
    cargo_toml = base / "Cargo.toml"
    if cargo_toml.is_file():
        collected.extend(_from_cargo_toml(cargo_toml, base, include_dev))

    cargo_lock = base / "Cargo.lock"
    if cargo_lock.is_file():
        collected.extend(_from_cargo_lock(cargo_lock, base))

    # If include_dev is False, drop dev-marked dupes (already filtered above for
    # most sources, but lockfiles don't distinguish). We just dedupe by (eco, name).
    return _dedupe(collected)
