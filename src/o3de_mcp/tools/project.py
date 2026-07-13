# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""MCP tools for O3DE project and build management."""

from __future__ import annotations

import atexit
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from collections import deque
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from o3de_mcp.utils.o3de import (
    find_o3de_engine_path,
    list_available_templates,
    list_registered_gems,
    list_registered_projects,
    run_o3de_cli,
)

_VALID_BUILD_CONFIGS = {"debug", "profile", "release"}
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_DEFAULT_CONFIGURE_TIMEOUT = 600
_DEFAULT_BUILD_TIMEOUT = 1800
_DEFAULT_EXPORT_TIMEOUT = 3600


class _BuildProcess:
    """Wraps a ``Popen`` build process with a background thread that drains
    stdout into a ring buffer.

    Without draining, a CMake build whose output exceeds the OS pipe buffer
    (~64 KB) will block on ``write()`` and stall the build.  The reader thread
    continuously reads lines so the pipe never fills, and ``get_build_status``
    reads from the in-memory buffer instead of the pipe (which also avoids
    ``select.select`` not working on Windows pipes).
    """

    _MAX_BUFFER_LINES = 5000

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self._proc = proc
        self._buffer: deque[str] = deque(maxlen=self._MAX_BUFFER_LINES)
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        """Background thread: read stdout line-by-line into the buffer."""
        if self._proc.stdout is None:
            return
        try:
            for line in self._proc.stdout:
                with self._lock:
                    self._buffer.append(line)
        except (OSError, ValueError):
            pass

    def poll(self) -> int | None:
        return self._proc.poll()

    def get_output(self, max_chars: int = 2000) -> str:
        """Return the tail of the buffered output (up to *max_chars*)."""
        with self._lock:
            lines = list(self._buffer)
        text = "".join(lines)
        return text[-max_chars:] if text else ""

    def terminate(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()


_BUILDS: dict[str, _BuildProcess] = {}


def _cleanup_builds() -> None:
    """Terminate any orphaned background build processes on exit."""
    for build_id, build in list(_BUILDS.items()):
        build.terminate()
        _BUILDS.pop(build_id, None)


atexit.register(_cleanup_builds)


def _get_configure_timeout() -> int:
    raw = os.environ.get("O3DE_CONFIGURE_TIMEOUT", "")
    try:
        return int(raw) if raw else _DEFAULT_CONFIGURE_TIMEOUT
    except ValueError:
        return _DEFAULT_CONFIGURE_TIMEOUT


def _get_build_timeout() -> int:
    raw = os.environ.get("O3DE_BUILD_TIMEOUT", "")
    try:
        return int(raw) if raw else _DEFAULT_BUILD_TIMEOUT
    except ValueError:
        return _DEFAULT_BUILD_TIMEOUT


def _get_export_timeout() -> int:
    raw = os.environ.get("O3DE_EXPORT_TIMEOUT", "")
    try:
        return int(raw) if raw else _DEFAULT_EXPORT_TIMEOUT
    except ValueError:
        return _DEFAULT_EXPORT_TIMEOUT


def _detect_vs_generator() -> str | None:
    """Detect the latest installed Visual Studio and return its CMake generator string."""
    vswhere = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft Visual Studio"
        / "Installer"
        / "vswhere.exe"
    )
    if not vswhere.is_file():
        return None

    try:
        result = subprocess.run(
            [
                str(vswhere),
                "-latest",
                "-products",
                "*",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-format",
                "json",
                "-utf8",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        instances = json.loads(result.stdout)
        if not instances:
            return None

        instance = instances[0]
        version_str = instance.get("installationVersion", "")
        major = int(version_str.split(".")[0])

        catalog = instance.get("catalog", {})
        year = catalog.get("productLineVersion", "")

        if major and year:
            return f"Visual Studio {major} {year}"
    except (
        subprocess.TimeoutExpired,
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ):
        pass

    return None


def _get_cmake_generator() -> str | None:
    """Return the CMake generator to use, or None for CMake's default."""
    env = os.environ.get("O3DE_CMAKE_GENERATOR", "").strip()
    if env:
        return env

    if sys.platform == "win32":
        return _detect_vs_generator()

    import shutil

    if shutil.which("ninja"):
        return "Ninja Multi-Config"

    return None


def _format_error(code: str, message: str) -> str:
    return json.dumps({"status": "error", "code": code, "message": message})


def _validate_name(value: str, label: str) -> str:
    value = value.strip()
    if not _NAME_RE.match(value):
        raise ValueError(
            f"Invalid {label}: {value!r}. "
            "Must start with a letter and contain only alphanumeric characters, "
            "hyphens, or underscores."
        )
    return value


def _validate_path(value: str, label: str, must_exist: bool = False) -> Path:
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
    def list_project_gems(project_path: str) -> str:
        """List gems enabled in a specific O3DE project.

        Args:
            project_path: Path to the O3DE project.
        """
        project = _validate_path(project_path, "Project path", must_exist=True)
        project_json = project / "project.json"
        if not project_json.exists():
            return _format_error(
                "not_found",
                f"project.json not found at {project_json}",
            )
        try:
            data = json.loads(project_json.read_text())
        except json.JSONDecodeError as e:
            return _format_error("parse_error", f"Failed to parse project.json: {e}")
        gem_names = data.get("gem_names", [])
        return json.dumps(
            {"gems": gem_names, "project_path": str(project), "count": len(gem_names)}, indent=2
        )

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

        This runs CMake configure followed by CMake build. Timeouts are
        configurable via ``O3DE_CONFIGURE_TIMEOUT`` and ``O3DE_BUILD_TIMEOUT``
        environment variables.

        Args:
            project_path: Path to the O3DE project.
            config: Build configuration -- profile, debug, or release (default: profile).
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

        if build_dir.is_symlink():
            return _format_error(
                "symlink_rejected",
                f"Build directory is a symlink, which is not allowed: {build_dir}",
            )

        engine_path = find_o3de_engine_path()
        if engine_path is None:
            return _format_error("engine_not_found", "O3DE engine not found. Cannot build.")

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

        configure = subprocess.run(
            cmake_cmd,
            capture_output=True,
            text=True,
            timeout=_get_configure_timeout(),
        )
        if configure.returncode != 0:
            return _format_error("configure_failed", f"CMake configure failed:\n{configure.stderr}")

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

    @mcp.tool()
    def disable_gem(gem_name: str, project_path: str) -> str:
        """Disable a gem in an O3DE project.

        Args:
            gem_name: Name of the gem to disable.
            project_path: Path to the project.
        """
        gem_name = _validate_name(gem_name, "gem name")
        project = _validate_path(project_path, "Project path", must_exist=True)

        result = run_o3de_cli(
            [
                "disable-gem",
                "--gem-name",
                gem_name,
                "--project-path",
                str(project),
            ]
        )
        if result.returncode != 0:
            return _format_error("disable_failed", f"Failed to disable gem:\n{result.stderr}")
        return f"Gem '{gem_name}' disabled in project at '{project}'"

    @mcp.tool()
    def create_gem(name: str, path: str, template: str = "DefaultGem") -> str:
        """Create a new O3DE gem.

        Args:
            name: Gem name (alphanumeric, hyphens, underscores).
            path: Directory where the gem will be created.
            template: Gem template to use (default: DefaultGem).
        """
        name = _validate_name(name, "gem name")
        template = _validate_name(template, "template name")
        gem_path = _validate_path(path, "Gem parent directory")

        result = run_o3de_cli(
            [
                "create-gem",
                "--gem-name",
                name,
                "--gem-path",
                str(gem_path),
                "--template-name",
                template,
            ]
        )
        if result.returncode != 0:
            return _format_error("create_failed", f"Failed to create gem:\n{result.stderr}")
        return f"Gem '{name}' created at {gem_path}"

    @mcp.tool()
    def export_project(project_path: str, output_path: str, config: str = "profile") -> str:
        """Export an O3DE project for distribution.

        This is a long-running operation. Timeout is configurable via
        the ``O3DE_EXPORT_TIMEOUT`` environment variable (default: 3600s).

        Args:
            project_path: Path to the O3DE project to export.
            output_path: Directory where the exported project will be written.
            config: Build configuration -- profile, debug, or release (default: profile).
        """
        config = config.lower().strip()
        if config not in _VALID_BUILD_CONFIGS:
            return _format_error(
                "invalid_config",
                f"Invalid build config: {config!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_BUILD_CONFIGS))}",
            )

        project = _validate_path(project_path, "Project path", must_exist=True)
        output = _validate_path(output_path, "Output path")

        try:
            result = run_o3de_cli(
                [
                    "export-project",
                    "--project-path",
                    str(project),
                    "--output-path",
                    str(output),
                    "--config",
                    config,
                ]
            )
        except subprocess.TimeoutExpired:
            return _format_error(
                "export_timeout",
                f"Project export timed out after {_get_export_timeout()}s. "
                "Increase O3DE_EXPORT_TIMEOUT if the project requires more time.",
            )
        if result.returncode != 0:
            return _format_error("export_failed", f"Failed to export project:\n{result.stderr}")
        return f"Project exported successfully to {output} (config={config})"

    @mcp.tool()
    def edit_project_properties(
        project_path: str,
        project_name: str | None = None,
        origin: str | None = None,
    ) -> str:
        """Edit properties of an existing O3DE project.

        Args:
            project_path: Path to the project.
            project_name: New name for the project (optional).
            origin: New origin URL or description (optional).
        """
        project = _validate_path(project_path, "Project path", must_exist=True)

        args: list[str] = ["edit-project-properties", "--project-path", str(project)]

        if project_name is not None:
            project_name = _validate_name(project_name, "project name")
            args.extend(["--project-name", project_name])
        if origin is not None:
            args.extend(["--origin", origin])

        if len(args) == 3:
            return _format_error(
                "no_changes",
                "No properties specified to change. Provide at least one of: project_name, origin.",
            )

        result = run_o3de_cli(args)
        if result.returncode != 0:
            return _format_error(
                "edit_failed", f"Failed to edit project properties:\n{result.stderr}"
            )
        return f"Project properties updated for '{project}'"

    @mcp.tool()
    def list_templates() -> str:
        """List available O3DE project and gem templates.

        Scans the engine's Templates directory for template definitions.

        Returns:
            JSON array of template objects with name, summary, and path.
        """
        templates = list_available_templates()
        if not templates:
            return _format_error(
                "no_templates",
                "No templates found. Ensure O3DE engine path is configured correctly.",
            )
        return json.dumps(templates, indent=2)

    @mcp.tool()
    def register_engine(engine_path: str) -> str:
        """Register an O3DE engine installation with the O3DE manifest.

        Args:
            engine_path: Path to the engine root directory (must contain engine.json).
        """
        engine = _validate_path(engine_path, "Engine path", must_exist=True)
        engine_json = engine / "engine.json"
        if not engine_json.exists():
            return _format_error(
                "not_found",
                f"engine.json not found at {engine_json}. "
                "The path must point to a valid O3DE engine root.",
            )
        result = run_o3de_cli(["register", "--engine-path", str(engine)])
        if result.returncode != 0:
            return _format_error("register_failed", f"Failed to register engine:\n{result.stderr}")
        return f"Engine registered: {engine}"

    @mcp.tool()
    def set_active_engine(name: str) -> str:
        """Set the active O3DE engine by name (in-process, not persistent).

        Args:
            name: Name of the registered engine to activate.
        """
        name = _validate_name(name, "engine name")
        os.environ["O3DE_ENGINE_NAME"] = name
        return f"Active engine set to '{name}' (in-process only)"

    @mcp.tool()
    def start_build(
        project_path: str,
        config: str = "profile",
        target: str | None = None,
    ) -> str:
        """Start a CMake build in the background and return a build ID.

        Unlike ``build_project``, this returns immediately with a build ID
        that can be polled via ``get_build_status``. Output is drained on a
        background thread to prevent pipe stalls on large builds.

        Args:
            project_path: Path to the O3DE project.
            config: Build configuration -- profile, debug, or release (default: profile).
            target: Optional CMake target to build (default: all targets).
        """
        project = _validate_path(project_path, "Project path", must_exist=True)
        config = config.lower().strip()
        if config not in _VALID_BUILD_CONFIGS:
            return _format_error(
                "invalid_config",
                f"Invalid build config: {config!r}. Must be one of {sorted(_VALID_BUILD_CONFIGS)}.",
            )

        build_dir = project / "build" / "windows"
        if not build_dir.exists():
            build_dir = project / "build"
            if not build_dir.exists():
                return _format_error(
                    "no_build_dir",
                    f"No build directory found at {project}/build. Run cmake configure first.",
                )

        cmd = ["cmake", "--build", str(build_dir), "--config", config]
        if target:
            cmd.extend(["--target", target])

        build_id = str(uuid.uuid4())[:8]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            _BUILDS[build_id] = _BuildProcess(proc)
        except OSError as e:
            return _format_error("build_failed", f"Failed to start build: {e}")

        return json.dumps(
            {
                "build_id": build_id,
                "status": "running",
                "config": config,
                "target": target,
                "build_dir": str(build_dir),
            }
        )

    @mcp.tool()
    def get_build_status(build_id: str) -> str:
        """Check the status of a background build.

        Args:
            build_id: Build ID returned by ``start_build``.
        """
        build_id = build_id.strip()
        if not build_id:
            raise ValueError("build_id cannot be empty.")

        build = _BUILDS.get(build_id)
        if build is None:
            return _format_error("not_found", f"No build found with ID {build_id!r}.")

        output = build.get_output(max_chars=2000)
        returncode = build.poll()
        if returncode is None:
            status = "running"
        elif returncode == 0:
            status = "completed"
            _BUILDS.pop(build_id, None)
        else:
            status = "failed"
            _BUILDS.pop(build_id, None)

        return json.dumps(
            {
                "build_id": build_id,
                "status": status,
                "returncode": returncode,
                "output": output,
            }
        )
