# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""O3DE installation discovery and common helpers."""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# How long (seconds) cached manifest data is considered fresh
_CACHE_TTL = 30.0


class _ManifestCache:
    """Simple TTL cache for O3DE manifest data.

    Avoids re-reading the manifest and all project/gem JSON files on every
    tool call.  The cache is invalidated when the manifest file's mtime
    changes or after ``_CACHE_TTL`` seconds, whichever comes first.
    """

    def __init__(self) -> None:
        self._data: dict | None = None
        self._mtime: float = 0.0
        self._read_at: float = 0.0
        self._path: Path | None = None

    def get(self, manifest: Path) -> dict:
        now = time.monotonic()
        try:
            current_mtime = manifest.stat().st_mtime
        except OSError:
            return {}

        if (
            self._data is not None
            and self._path == manifest
            and self._mtime == current_mtime
            and (now - self._read_at) < _CACHE_TTL
        ):
            return self._data

        data: dict = json.loads(manifest.read_text())
        self._data = data
        self._mtime = current_mtime
        self._read_at = now
        self._path = manifest
        return data

    def invalidate(self) -> None:
        self._data = None


_manifest_cache = _ManifestCache()


def find_o3de_engine_path() -> Path | None:
    """Discover the O3DE engine root from the manifest or environment.

    Resolution order:
      1. ``O3DE_ENGINE_PATH`` environment variable (explicit override).
      2. ``O3DE_ENGINE_NAME`` environment variable — selects a specific engine
         by name from the manifest.
      3. First registered engine in the manifest whose ``engine.json`` exists.
      4. First registered engine path in the manifest (fallback).
    """
    env_path = os.environ.get("O3DE_ENGINE_PATH")
    if env_path:
        return Path(env_path)

    manifest = _o3de_manifest_path()
    if manifest is None or not manifest.exists():
        return None

    data = _manifest_cache.get(manifest)
    engines = data.get("engines", [])
    if not engines:
        return None

    # If a specific engine name is requested, look for it
    engine_name = os.environ.get("O3DE_ENGINE_NAME", "").strip()
    if engine_name:
        for engine_str in engines:
            engine_json = Path(engine_str) / "engine.json"
            if engine_json.exists():
                try:
                    info = json.loads(engine_json.read_text())
                    if info.get("engine_name") == engine_name:
                        return Path(engine_str)
                except (json.JSONDecodeError, OSError):
                    continue

    # Prefer the first engine with a valid engine.json
    for engine_str in engines:
        engine_json = Path(engine_str) / "engine.json"
        if engine_json.exists():
            return Path(engine_str)

    # Fall back to first entry
    return Path(engines[0])


# Cached CLI path to avoid repeated filesystem checks
_cached_cli: Path | None = None
_cached_cli_engine: Path | None = None


def find_o3de_cli() -> Path | None:
    """Locate the o3de CLI script.

    Checks for ``scripts/o3de.sh`` (Unix) or ``scripts/o3de.bat`` (Windows),
    then falls back to ``python/o3de.py`` as an alternative entry point.
    Caches the result for the current engine path.
    """
    global _cached_cli, _cached_cli_engine  # noqa: PLW0603

    engine = find_o3de_engine_path()
    if engine is None:
        _cached_cli = None
        _cached_cli_engine = None
        return None

    # Return cached result if engine path hasn't changed
    if _cached_cli is not None and _cached_cli_engine == engine:
        return _cached_cli

    is_windows = platform.system() == "Windows"

    # Primary: platform-specific CLI script
    primary = engine / ("scripts/o3de.bat" if is_windows else "scripts/o3de.sh")
    if primary.exists():
        if not is_windows and not os.access(primary, os.X_OK):
            logger.warning("O3DE CLI script %s exists but is not executable.", primary)
        _cached_cli = primary
        _cached_cli_engine = engine
        return primary

    # Fallback: python/o3de.py (some installations use this)
    fallback = engine / "python" / "o3de.py"
    if fallback.exists():
        _cached_cli = fallback
        _cached_cli_engine = engine
        return fallback

    _cached_cli = None
    _cached_cli_engine = engine
    return None


def run_o3de_cli(args: list[str], cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    """Run the O3DE CLI with given arguments."""
    cli = find_o3de_cli()
    if cli is None:
        raise FileNotFoundError(
            "O3DE CLI not found. Set O3DE_ENGINE_PATH or register an engine in the O3DE manifest."
        )

    # If the CLI is a .py file, invoke it via Python
    cmd: list[str]
    if cli.suffix == ".py":
        import sys

        cmd = [sys.executable, str(cli)] + args
    else:
        cmd = [str(cli)] + args

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=300,
    )


def _o3de_manifest_path() -> Path | None:
    """Return the path to the O3DE manifest file."""
    home = Path.home()

    manifest = home / ".o3de" / "o3de_manifest.json"
    return manifest if manifest.exists() else None


def list_registered_projects() -> list[dict]:
    """List projects registered in the O3DE manifest."""
    manifest = _o3de_manifest_path()
    if manifest is None or not manifest.exists():
        return []
    data = _manifest_cache.get(manifest)
    projects = []
    for proj_path in data.get("projects", []):
        proj_json = Path(proj_path) / "project.json"
        if proj_json.exists():
            projects.append(json.loads(proj_json.read_text()) | {"path": proj_path})
        else:
            projects.append({"path": proj_path, "project_name": Path(proj_path).name})
    return projects


def list_registered_gems() -> list[dict]:
    """List gems registered in the O3DE manifest."""
    manifest = _o3de_manifest_path()
    if manifest is None or not manifest.exists():
        return []
    data = _manifest_cache.get(manifest)
    gems = []
    for gem_path in data.get("external_subdirectories", []):
        gem_json = Path(gem_path) / "gem.json"
        if gem_json.exists():
            gems.append(json.loads(gem_json.read_text()) | {"path": gem_path})
        else:
            gems.append({"path": gem_path, "gem_name": Path(gem_path).name})
    return gems


def find_o3de_engine_version() -> str | None:
    """Read the O3DE engine version from ``engine.json``."""
    engine = find_o3de_engine_path()
    if engine is None:
        return None
    engine_json = engine / "engine.json"
    if not engine_json.exists():
        return None
    try:
        data = json.loads(engine_json.read_text())
        version: str | None = data.get("version") or data.get("O3DEVersion")
        return version
    except (json.JSONDecodeError, OSError):
        return None


def find_all_engines() -> list[dict]:
    """Return metadata for all engines registered in the O3DE manifest."""
    manifest = _o3de_manifest_path()
    if manifest is None or not manifest.exists():
        return []
    data = _manifest_cache.get(manifest)
    engines: list[dict] = []
    for engine_str in data.get("engines", []):
        entry: dict = {"path": engine_str}
        engine_json = Path(engine_str) / "engine.json"
        if engine_json.exists():
            try:
                info = json.loads(engine_json.read_text())
                entry["engine_name"] = info.get("engine_name", "")
                entry["version"] = info.get("version") or info.get("O3DEVersion", "")
            except (json.JSONDecodeError, OSError):
                pass
        engines.append(entry)
    return engines


def list_available_templates() -> list[dict]:
    """Scan the engine's ``Templates/`` directory for project/gem templates."""
    engine = find_o3de_engine_path()
    if engine is None:
        return []
    templates_dir = engine / "Templates"
    if not templates_dir.is_dir():
        return []
    templates: list[dict] = []
    for entry in sorted(templates_dir.iterdir()):
        if not entry.is_dir():
            continue
        template_json = entry / "template.json"
        if template_json.exists():
            try:
                info = json.loads(template_json.read_text())
                templates.append(
                    {
                        "template_name": info.get("template_name", entry.name),
                        "display_name": info.get("display_name", entry.name),
                        "summary": info.get("summary", ""),
                        "path": str(entry),
                    }
                )
            except (json.JSONDecodeError, OSError):
                templates.append({"template_name": entry.name, "path": str(entry)})
        else:
            templates.append({"template_name": entry.name, "path": str(entry)})
    return templates
