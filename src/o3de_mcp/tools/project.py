# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""MCP tools for O3DE project and build management.

These tools wrap the O3DE CLI (``scripts/o3de.sh`` or ``o3de.bat``) and CMake
to provide project creation, gem management, and build orchestration.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from o3de_mcp.utils.o3de import (
    find_o3de_engine_path,
    list_registered_gems,
    list_registered_projects,
    run_o3de_cli,
)

# Allowed build configurations — prevents arbitrary strings from reaching cmake
_VALID_BUILD_CONFIGS = {"debug", "profile", "release"}

# Project/gem names: alphanumeric, hyphens, underscores (O3DE convention)
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

# Default timeout for CMake configure (seconds), overridable via env
_DEFAULT_CONFIGURE_TIMEOUT = 600

# Default timeout for CMake build (seconds), overridable via env
_DEFAULT_BUILD_TIMEOUT = 1800


def _get_configure_timeout() -> int:
    """Return CMake configure timeout from env or default."""
    raw = os.environ.get("O3DE_CONFIGURE_TIMEOUT", "")
    try:
        return int(raw) if raw else _DEFAULT_CONFIGURE_TIMEOUT
    except ValueError:
        return _DEFAULT_CONFIGURE_TIMEOUT


def _get_build_timeout() -> int:
    """Return CMake build timeout from env or default."""
    raw = os.environ.get("O3DE_BUILD_TIMEOUT", "")
    try:
        return int(raw) if raw else _DEFAULT_BUILD_TIMEOUT
    except ValueError:
        return _DEFAULT_BUILD_TIMEOUT


def _get_cmake_generator() -> str | None:
    """Return the CMake generator to use, or None for CMake's default.

    Can be overridden via ``O3DE_CMAKE_GENERATOR``.  When not set, picks a
    sensible default per platform:
      - Windows: ``Visual Studio 17 2022`` (most common for O3DE)
      - macOS / Linux: ``Ninja Multi-Config`` if ``ninja`` is on PATH,
        otherwise falls back to CMake's default.
    """
    env = os.environ.get("O3DE_CMAKE_GENERATOR", "").strip()
    if env:
        return env

    if sys.platform == "win32":
        return "Visual Studio 17 2022"

    # Prefer Ninja Multi-Config on Unix if available (faster builds)
    import shutil

    if shutil.which("ninja"):
        return "Ninja Multi-Config"

    return None  # Let CMake choose


def _format_error(code: str, message: str) -> str:
    """Return a structured JSON error string."""
    return json.dumps({"status": "error", "code": code, "message": message})


def _validate_name(value: str, label: str) -> str:
    """Validate that a project or gem name follows O3DE naming conventions."""
    value = value.strip()
    if not _NAME_RE.match(value):
        raise ValueError(
            f"Invalid {label}: {value!r}. "
            "Must start with a letter and contain only alphanumeric characters, "
            "hyphens, or underscores."
        )
    return value


def _validate_path(value: str, label: str, must_exist: bool = False) -> Path:
    """Validate and resolve a filesystem path."""
    path = Path(value).resolve()
    if must_exist and not path.exists():
        raise ValueError(f"{label} does not exist: {path}")
    return path


def register_project_tools(mcp: FastMCP) -> None:
    """Register all project management tools with the MCP server."""

    @mcp.tool()
    def get_engine_info() -> str:
        """Get information about the local O3DE engine installation.

        Returns:
            JSON object with engine metadata, or an error message if no engine is found.
        """
        engine_path = find_o3de_engine_path()
        if engine_path is None:
            return _format_error(
                "engine_not_found",
                "No O3DE engine found. Set O3DE_ENGINE_PATH or register one in the O3DE manifest.",
            )

        engine_json = engine_path / "engine.json"
        if engine_json.exists():
            info = json.loads(engine_json.read_text())
            info["engine_path"] = str(engine_path)
            return json.dumps(info, indent=2)
        return json.dumps({"engine_path": str(engine_path)}, indent=2)

    @mcp.tool()
    def list_projects() -> str:
        """List all O3DE projects registered on this machine.

        Returns:
            JSON array of project objects, or a message if none are found.
        """
        projects = list_registered_projects()
        if not projects:
            return _format_error("no_projects", "No projects found in O3DE manifest.")
        return json.dumps(projects, indent=2)

    @mcp.tool()
    def list_gems() -> str:
        """List all external gems registered on this machine.

        Returns:
            JSON array of gem objects, or a message if none are found.
        """
        gems = list_registered_gems()
        if not gems:
            return _format_error("no_gems", "No external gems found in O3DE manifest.")
        return json.dumps(gems, indent=2)

    @mcp.tool()
    def create_project(name: str, path: str, template: str = "DefaultProject") -> str:
        """Create a new O3DE project.

        Args:
            name: Project name (alphanumeric, hyphens, underscores).
            path: Directory where the project will be created.
            template: Project template to use (default: DefaultProject).
        """
        name = _validate_name(name, "project name")
        template = _validate_name(template, "template name")
        project_path = _validate_path(path, "Project parent directory")

        result = run_o3de_cli(
            [
                "create-project",
                "--project-name",
                name,
                "--project-path",
                str(project_path),
                "--template-name",
                template,
            ]
        )
        if result.returncode != 0:
            return _format_error("create_failed", f"Failed to create project:\n{result.stderr}")
        return f"Project '{name}' created at {project_path}"

    @mcp.tool()
    def register_gem(gem_path: str, project_path: str) -> str:
        """Register an external gem with an O3DE project.

        Args:
            gem_path: Path to the gem directory.
            project_path: Path to the project to add the gem to.
        """
        gem = _validate_path(gem_path, "Gem path", must_exist=True)
        project = _validate_path(project_path, "Project path", must_exist=True)

        result = run_o3de_cli(
            [
                "register",
                "--gem-path",
                str(gem),
                "--project-path",
                str(project),
            ]
        )
        if result.returncode != 0:
            return _format_error("register_failed", f"Failed to register gem:\n{result.stderr}")
        return f"Gem at '{gem}' registered with project at '{project}'"

    @mcp.tool()
    def enable_gem(gem_name: str, project_path: str) -> str:
        """Enable a gem in an O3DE project.

        Args:
            gem_name: Name of the gem to enable.
            project_path: Path to the project.
        """
        gem_name = _validate_name(gem_name, "gem name")
        project = _validate_path(project_path, "Project path", must_exist=True)

        result = run_o3de_cli(
            [
                "enable-gem",
                "--gem-name",
                gem_name,
                "--project-path",
                str(project),
            ]
        )
        if result.returncode != 0:
            return _format_error("enable_failed", f"Failed to enable gem:\n{result.stderr}")
        return f"Gem '{gem_name}' enabled in project at '{project}'"

    @mcp.tool()
    def build_project(project_path: str, config: str = "profile") -> str:
        """Build an O3DE project using CMake.

        Args:
            project_path: Path to the O3DE project.
            config: Build configuration — profile, debug, or release (default: profile).
        """
        config = config.lower().strip()
        if config not in _VALID_BUILD_CONFIGS:
            return _format_error(
                "invalid_config",
                f"Invalid build config: {config!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_BUILD_CONFIGS))}",
            )

        project = _validate_path(project_path, "Project path", must_exist=True)
        build_dir = project / "build"
        build_dir.mkdir(exist_ok=True)

        # Guard against symlink attacks on the build directory
        if build_dir.is_symlink():
            return _format_error(
                "symlink_rejected",
                f"Build directory is a symlink, which is not allowed: {build_dir}",
            )

        engine_path = find_o3de_engine_path()
        if engine_path is None:
            return _format_error("engine_not_found", "O3DE engine not found. Cannot build.")

        # Build CMake configure command
        cmake_cmd: list[str] = [
            "cmake",
            "-S",
            str(project),
            "-B",
            str(build_dir),
            f"-DLY_ENGINE_PATH={engine_path.as_posix()}",
        ]
        generator = _get_cmake_generator()
        if generator:
            cmake_cmd.extend(["-G", generator])

        # CMake configure
        configure = subprocess.run(
            cmake_cmd,
            capture_output=True,
            text=True,
            timeout=_get_configure_timeout(),
        )
        if configure.returncode != 0:
            return _format_error("configure_failed", f"CMake configure failed:\n{configure.stderr}")

        # CMake build
        build = subprocess.run(
            [
                "cmake",
                "--build",
                str(build_dir),
                "--config",
                config,
                "--parallel",
            ],
            capture_output=True,
            text=True,
            timeout=_get_build_timeout(),
        )
        if build.returncode != 0:
            return _format_error("build_failed", f"Build failed:\n{build.stderr}")

        return f"Project built successfully (config={config})"
