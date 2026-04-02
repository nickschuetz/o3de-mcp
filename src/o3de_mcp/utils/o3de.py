# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""O3DE installation discovery and common helpers."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from pathlib import Path

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
    """Discover the O3DE engine root from the manifest or environment."""
    env_path = os.environ.get("O3DE_ENGINE_PATH")
    if env_path:
        return Path(env_path)

    manifest = _o3de_manifest_path()
    if manifest and manifest.exists():
        data = _manifest_cache.get(manifest)
        engines = data.get("engines", [])
        if engines:
            return Path(engines[0])

    return None


def find_o3de_cli() -> Path | None:
    """Locate the o3de CLI script."""
    engine = find_o3de_engine_path()
    if engine is None:
        return None
    script = "scripts/o3de.bat" if platform.system() == "Windows" else "scripts/o3de.sh"
    cli = engine / script
    return cli if cli.exists() else None


def run_o3de_cli(args: list[str], cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    """Run the O3DE CLI with given arguments."""
    cli = find_o3de_cli()
    if cli is None:
        raise FileNotFoundError(
            "O3DE CLI not found. Set O3DE_ENGINE_PATH or register an engine in the O3DE manifest."
        )
    return subprocess.run(
        [str(cli)] + args,
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
