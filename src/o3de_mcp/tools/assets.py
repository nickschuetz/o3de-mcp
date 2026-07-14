# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""MCP tools for O3DE Asset Processor status and log file access."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from o3de_mcp.utils.o3de import list_registered_projects


def _resolve_project_path(project_path: str | None = None) -> Path | None:
    """Resolve a project path from the argument, env var, or registered projects."""
    if project_path:
        return Path(project_path)
    env_path = os.environ.get("O3DE_PROJECT_PATH", "").strip()
    if env_path:
        return Path(env_path)
    projects = list_registered_projects()
    if len(projects) == 1:
        return Path(projects[0]["path"])
    return None


def _is_asset_processor_running() -> bool:
    """Check if the O3DE Asset Processor process is running."""
    system = platform.system()
    try:
        if system == "Windows":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq AssetProcessor.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return "AssetProcessor.exe" in result.stdout
        else:
            result = subprocess.run(
                ["pgrep", "-f", "AssetProcessor"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _get_log_dir(project_path: Path) -> Path:
    """Return the log directory for an O3DE project."""
    return project_path / "log"


def _read_log_tail(log_path: Path, lines: int = 50, filter_pattern: str | None = None) -> list[str]:
    """Read the last N lines of a log file, optionally filtered by a regex pattern."""
    if not log_path.exists():
        return []
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    all_lines = content.splitlines()
    if filter_pattern:
        try:
            pattern = re.compile(filter_pattern)
            all_lines = [line for line in all_lines if pattern.search(line)]
        except re.error:
            pass
    return all_lines[-lines:] if lines > 0 else all_lines


def register_assets_tools(mcp: FastMCP) -> None:
    """Register asset processor and log tools with the MCP server."""

    @mcp.tool()
    async def get_asset_processor_status(project_path: str | None = None) -> str:
        """Check whether the O3DE Asset Processor is running."""
        running = await asyncio.to_thread(_is_asset_processor_running)
        proj = _resolve_project_path(project_path)
        log_dir = str(_get_log_dir(proj)) if proj else None
        return json.dumps(
            {"running": running, "log_dir": log_dir, "project": str(proj) if proj else None}
        )

    @mcp.tool()
    async def wait_for_assets(timeout: int = 300) -> str:
        """Wait for the Asset Processor to finish processing (or until timeout)."""
        if timeout <= 0:
            return json.dumps(
                {"completed": False, "elapsed": 0.0, "error": "timeout must be positive"}
            )
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            running = await asyncio.to_thread(_is_asset_processor_running)
            if not running:
                elapsed = time.monotonic() - start
                return json.dumps({"completed": True, "elapsed": round(elapsed, 2)})
            await asyncio.sleep(2.0)
        elapsed = time.monotonic() - start
        return json.dumps(
            {
                "completed": False,
                "elapsed": round(elapsed, 2),
                "error": f"Asset Processor still running after {timeout}s",
            }
        )

    @mcp.tool()
    async def refresh_assets(project_path: str | None = None) -> str:
        """Trigger an Asset Processor rescan for a project."""
        proj = _resolve_project_path(project_path)
        if proj is None:
            return json.dumps({"status": "error", "message": "Could not resolve project path."})
        from o3de_mcp.utils.o3de import find_o3de_engine_path

        engine = find_o3de_engine_path()
        if engine is None:
            return json.dumps({"status": "error", "message": "O3DE engine not found."})

        ap_path = engine / "build" / "bin" / "profile" / "AssetProcessorBatch.exe"
        if not ap_path.exists():
            if platform.system() == "Windows":
                ap_path = (
                    engine / "build" / "windows" / "bin" / "profile" / "AssetProcessorBatch.exe"
                )
            else:
                ap_path = engine / "build" / "linux" / "bin" / "profile" / "AssetProcessorBatch"

        if not ap_path.exists():
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Asset Processor batch not found at {ap_path}",
                }
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                str(ap_path),
                "--project-path",
                str(proj),
                "--refresh",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return json.dumps({"status": "error", "message": "Asset refresh timed out (120s)."})
            if proc.returncode == 0:
                return json.dumps({"status": "ok", "message": "Asset refresh completed."})
            err_text = stderr.decode(errors="replace") if stderr else ""
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Asset refresh failed: {err_text[:500]}",
                }
            )
        except OSError as e:
            return json.dumps({"status": "error", "message": f"Failed to run AP: {e}"})

    @mcp.tool()
    async def tail_log(
        log_name: str,
        lines: int = 50,
        filter: str | None = None,
        project_path: str | None = None,
    ) -> str:
        """Read the last N lines of an O3DE log file."""
        if not log_name.lower().endswith(".log"):
            log_name = log_name + ".log"

        if "/" in log_name or "\\" in log_name or ".." in log_name:
            return json.dumps(
                {"error": f"Invalid log name: {log_name!r}. No path separators allowed."}
            )

        proj = _resolve_project_path(project_path)
        if proj is None:
            return json.dumps({"error": "Could not resolve project path for log directory."})

        log_dir = _get_log_dir(proj)
        log_path = log_dir / log_name

        if not log_path.exists():
            return json.dumps(
                {"error": f"Log file not found: {log_path}", "log_name": log_name, "lines": []}
            )

        tail = await asyncio.to_thread(_read_log_tail, log_path, lines=lines, filter_pattern=filter)
        return json.dumps(
            {"log_name": log_name, "lines": tail, "count": len(tail), "path": str(log_path)}
        )

    @mcp.tool()
    async def get_log_errors(
        log_name: str = "Editor",
        since_lines: int = 200,
        project_path: str | None = None,
    ) -> str:
        """Extract error lines from an O3DE log file."""
        if not log_name.lower().endswith(".log"):
            log_name = log_name + ".log"

        if "/" in log_name or "\\" in log_name or ".." in log_name:
            return json.dumps(
                {"error": f"Invalid log name: {log_name!r}. No path separators allowed."}
            )

        proj = _resolve_project_path(project_path)
        if proj is None:
            return json.dumps({"error": "Could not resolve project path for log directory."})

        log_dir = _get_log_dir(proj)
        log_path = log_dir / log_name

        if not log_path.exists():
            return json.dumps({"error": f"Log file not found: {log_path}", "errors": []})

        tail = await asyncio.to_thread(_read_log_tail, log_path, lines=since_lines)
        error_pattern = re.compile(r"ERROR|AZ_Error|Error:|FATAL|AZ_Assert", re.IGNORECASE)
        errors = [line for line in tail if error_pattern.search(line)]
        return json.dumps(
            {"errors": errors, "count": len(errors), "log_name": log_name, "path": str(log_path)}
        )
