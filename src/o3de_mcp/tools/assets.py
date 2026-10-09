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

from mcp.server import MCPServer

from o3de_mcp.utils.errors import format_error
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
    """Return the log directory for an O3DE project.

    The editor and Asset Processor write to ``<project>/user/log``. A bare
    ``<project>/log`` is used only when it exists and ``user/log`` does not
    (an older layout).
    """
    user_log = project_path / "user" / "log"
    legacy = project_path / "log"
    if not user_log.is_dir() and legacy.is_dir():
        return legacy
    return user_log


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


# How long a "missing" status is taken at face value right after a write before
# wait_for_asset asks the job list why: a failed build also answers "missing".
_MISSING_GRACE_SECONDS = 3.0


def _validate_asset_path(path: str, label: str = "path") -> str:
    path = path.strip()
    if not path:
        raise ValueError(f"{label} cannot be empty.")
    if len(path.encode("utf-8")) > 1024:
        raise ValueError(f"{label} is too long (max 1024 bytes).")
    if any(ord(ch) < 32 for ch in path):
        raise ValueError(f"{label} must not contain control characters.")
    return path


def _parse(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def register_assets_tools(mcp: MCPServer) -> None:
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
        """Wait for the Asset Processor process to exit (or until timeout).

        This watches for the process to stop, not for it to go idle, so it suits
        a one-off AssetProcessorBatch run. A GUI Asset Processor running beside
        the editor stays up while idle, so with one running this waits out the
        timeout and reports ``completed: false``.

        Returns a progress result ``{"completed": bool, "elapsed": seconds}``.
        ``completed`` is ``True`` when no Asset Processor process is running, or
        ``False`` when one was still running when ``timeout`` elapsed, with a
        ``message`` noting the timeout. A not-yet-finished wait is a result, not
        a failure, so this tool does not return the error envelope.
        """
        if timeout <= 0:
            raise ValueError("timeout must be positive.")
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
                "message": f"Asset Processor still running after {timeout}s",
            }
        )

    @mcp.tool()
    async def refresh_assets(project_path: str | None = None) -> str:
        """Trigger an Asset Processor rescan for a project."""
        proj = _resolve_project_path(project_path)
        if proj is None:
            return format_error("project_not_found", "Could not resolve project path.")
        from o3de_mcp.utils.o3de import (
            asset_processor_batch_candidates,
            find_asset_processor_batch,
            find_o3de_engine_path,
        )

        engine = find_o3de_engine_path()
        if engine is None:
            return format_error("engine_not_found", "O3DE engine not found.")

        ap_path = find_asset_processor_batch(engine)
        if ap_path is None:
            searched = ", ".join(str(p) for p in asset_processor_batch_candidates(engine))
            return format_error(
                "ap_not_found", f"AssetProcessorBatch not found; looked in: {searched}"
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
                return format_error("timeout", "Asset refresh timed out (120s).")
            if proc.returncode == 0:
                return json.dumps({"status": "ok", "message": "Asset refresh completed."})
            err_text = stderr.decode(errors="replace") if stderr else ""
            return format_error("refresh_failed", f"Asset refresh failed: {err_text[:500]}")
        except OSError as e:
            return format_error("ap_launch_failed", f"Failed to run AP: {e}")

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
            return format_error(
                "invalid_log_name", f"Invalid log name: {log_name!r}. No path separators allowed."
            )

        proj = _resolve_project_path(project_path)
        if proj is None:
            return format_error(
                "project_not_found", "Could not resolve project path for log directory."
            )

        log_dir = _get_log_dir(proj)
        log_path = log_dir / log_name

        if not log_path.exists():
            return format_error("log_not_found", f"Log file not found: {log_path}")

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
            return format_error(
                "invalid_log_name", f"Invalid log name: {log_name!r}. No path separators allowed."
            )

        proj = _resolve_project_path(project_path)
        if proj is None:
            return format_error(
                "project_not_found", "Could not resolve project path for log directory."
            )

        log_dir = _get_log_dir(proj)
        log_path = log_dir / log_name

        if not log_path.exists():
            return format_error("log_not_found", f"Log file not found: {log_path}")

        tail = await asyncio.to_thread(_read_log_tail, log_path, lines=since_lines)
        error_pattern = re.compile(r"ERROR|AZ_Error|Error:|FATAL|AZ_Assert", re.IGNORECASE)
        errors = [line for line in tail if error_pattern.search(line)]
        return json.dumps(
            {"errors": errors, "count": len(errors), "log_name": log_name, "path": str(log_path)}
        )

    # --- Asset readiness (native AiCompanion requests, gem 0.6.0+) ---

    from o3de_mcp.tools.editor import _native_request

    @mcp.tool()
    async def get_asset_status(path: str, flush_io: bool = False) -> str:
        """Ask the Asset Processor, through the editor, for one asset's build status.

        Returns ``{"path", "status", "connected"}`` with ``status`` one of
        ``unknown``, ``missing``, ``queued``, ``compiling``, ``compiled`` or
        ``failed`` (plus ``query_path`` when the gem rewrote the path). The query
        also escalates the asset in the build queue. A source whose build failed
        has no products and answers ``missing``; use ``get_asset_jobs`` or
        ``wait_for_asset`` to tell that apart from a file not registered yet.
        Needs the AiCompanion gem 0.6.0+; works in secure mode.

        Args:
            path: A source or product path, relative to the project, or a full path.
            flush_io: Flush the file monitor first. Use right after writing the file.
        """
        return await _native_request(
            "get_asset_status",
            {"path": _validate_asset_path(path), "flush_io": bool(flush_io)},
        )

    @mcp.tool()
    async def get_asset_jobs(
        source_path: str, escalate: bool = False, include_logs: bool = False
    ) -> str:
        """List the Asset Processor jobs for one source file, with failure logs.

        Returns ``{"source_path", "jobs": [{"job_key", "platform", "builder",
        "status", "error_count", "warning_count", "job_run_key", "source_file",
        "watch_folder", "log"?, "truncated"?}]}`` with ``status`` one of
        ``queued``, ``in_progress``, ``failed``, ``completed`` or ``missing``. A
        source the Asset Processor has not registered answers the error code
        ``engine_error``. Needs the AiCompanion gem 0.6.0+; works in secure mode.

        Args:
            source_path: The source file, relative to the project or a full path.
            escalate: Move the file's queued jobs to the front of the queue.
            include_logs: Attach each failed job's log (cut at 64 KB).
        """
        return await _native_request(
            "get_asset_jobs",
            {
                "source_path": _validate_asset_path(source_path, "source_path"),
                "escalate": bool(escalate),
                "include_logs": bool(include_logs),
            },
        )

    @mcp.tool()
    async def get_asset_processor_connection() -> str:
        """Report whether the editor is connected to the Asset Processor.

        Returns ``{"connected", "ping_ms"}``. Unlike ``get_asset_processor_status``,
        which checks for the process on this machine without the editor, this asks
        the editor itself. Needs the AiCompanion gem 0.6.0+.
        """
        return await _native_request("get_asset_processor_status")

    @mcp.tool()
    async def wait_for_asset(
        path: str,
        timeout: float = 120,
        just_written: bool = False,
        source_path: str | None = None,
        poll_interval: float = 1.0,
    ) -> str:
        """Wait until one asset is built, or report why it failed.

        Polls ``get_asset_status``. ``compiled`` returns ``{"path", "status":
        "compiled", "ready": true, "elapsed"}``. A failed build returns the error
        ``asset_build_failed`` with the failed jobs and their logs. A source whose
        build failed answers ``missing``, just like one the Asset Processor has
        not seen yet, so after a short grace period a ``missing`` status is
        checked against ``get_asset_jobs``. When ``timeout`` runs out the result
        is ``{"ready": false, "status": <last status>}``, not an error. Needs the
        AiCompanion gem 0.6.0+.

        Args:
            path: The asset to wait for: its source path (best, since the job
                check needs the source) or a product path.
            timeout: Seconds to wait (default 120, max 3600).
            just_written: True right after writing the file, so the first query
                flushes the file monitor.
            source_path: The source file to check for failed jobs, when ``path``
                is a product path.
            poll_interval: Seconds between polls (0.1 to 10, default 1).
        """
        path = _validate_asset_path(path)
        source = _validate_asset_path(source_path, "source_path") if source_path else path
        if not 0 < timeout <= 3600:
            raise ValueError("timeout must be more than 0 and at most 3600 seconds.")
        if not 0.1 <= poll_interval <= 10:
            raise ValueError("poll_interval must be between 0.1 and 10 seconds.")

        start = time.monotonic()
        status = "unknown"
        first = True
        while True:
            reply = await _native_request(
                "get_asset_status", {"path": path, "flush_io": bool(just_written and first)}
            )
            first = False
            parsed = _parse(reply)
            if parsed is None or parsed.get("status") == "error":
                return reply  # not connected, bad path, or an older gem
            status = str(parsed.get("status", "unknown"))
            elapsed = round(time.monotonic() - start, 2)
            if status == "compiled":
                return json.dumps(
                    {"path": path, "status": status, "ready": True, "elapsed": elapsed}
                )
            if status == "failed" or (
                status in ("missing", "unknown") and elapsed >= _MISSING_GRACE_SECONDS
            ):
                jobs = _parse(
                    await _native_request(
                        "get_asset_jobs", {"source_path": source, "include_logs": True}
                    )
                )
                job_list = (jobs or {}).get("jobs") or []
                failed = [j for j in job_list if j.get("status") == "failed"]
                if failed:
                    return json.dumps(
                        {
                            "status": "error",
                            "code": "asset_build_failed",
                            "message": f"{len(failed)} job(s) failed building {source}",
                            "path": path,
                            "jobs": failed,
                        }
                    )
            if time.monotonic() - start + poll_interval > timeout:
                return json.dumps(
                    {
                        "path": path,
                        "status": status,
                        "ready": False,
                        "elapsed": round(time.monotonic() - start, 2),
                        "message": f"{path} was not built within {timeout:g}s",
                    }
                )
            await asyncio.sleep(poll_interval)
