# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Tests for asset processor and log tools."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from o3de_mcp.tools.assets import (
    _get_log_dir,
    _read_log_tail,
    _resolve_project_path,
    register_assets_tools,
)

# --- Helper to call tools ---


async def _call_asset_tool(tool_name: str, arguments: dict) -> str:
    """Register asset tools on a throwaway MCPServer and call a tool."""
    from mcp.server import MCPServer

    mcp = MCPServer("test")
    register_assets_tools(mcp)
    content = (await mcp.call_tool(tool_name, arguments)).content
    return content[0].text


# --- Project path resolution tests ---


class TestResolveProjectPath:
    def test_explicit_path(self) -> None:
        result = _resolve_project_path("/some/project")
        assert result == Path("/some/project")

    def test_from_env_var(self) -> None:
        with patch.dict("os.environ", {"O3DE_PROJECT_PATH": "/env/project"}):
            result = _resolve_project_path(None)
            assert result == Path("/env/project")

    def test_none_when_no_project(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("o3de_mcp.tools.assets.list_registered_projects", return_value=[]):
                result = _resolve_project_path(None)
                assert result is None


# --- Log directory tests ---


class TestGetLogDir:
    def test_defaults_to_user_log(self, tmp_path: Path) -> None:
        # Where the editor and Asset Processor actually write.
        assert _get_log_dir(tmp_path) == tmp_path / "user" / "log"

    def test_prefers_user_log(self, tmp_path: Path) -> None:
        (tmp_path / "user" / "log").mkdir(parents=True)
        (tmp_path / "log").mkdir()
        assert _get_log_dir(tmp_path) == tmp_path / "user" / "log"

    def test_falls_back_to_a_bare_log_dir(self, tmp_path: Path) -> None:
        (tmp_path / "log").mkdir()
        assert _get_log_dir(tmp_path) == tmp_path / "log"


# --- Log tail reading tests ---


class TestReadLogTail:
    def test_reads_last_n_lines(self, tmp_path: Path) -> None:
        log_file = tmp_path / "Editor.log"
        log_file.write_text("\n".join(f"Line {i}" for i in range(100)))
        tail = _read_log_tail(log_file, lines=10)
        assert len(tail) == 10
        assert tail[-1] == "Line 99"

    def test_filters_by_pattern(self, tmp_path: Path) -> None:
        log_file = tmp_path / "Editor.log"
        lines = ["INFO: starting", "ERROR: something broke", "INFO: running", "ERROR: another"]
        log_file.write_text("\n".join(lines))
        tail = _read_log_tail(log_file, lines=50, filter_pattern="ERROR")
        assert len(tail) == 2
        assert "something broke" in tail[0]

    def test_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        tail = _read_log_tail(tmp_path / "nonexistent.log", lines=10)
        assert tail == []

    def test_invalid_regex_falls_back_to_unfiltered(self, tmp_path: Path) -> None:
        log_file = tmp_path / "Editor.log"
        log_file.write_text("Line 1\nLine 2\n")
        tail = _read_log_tail(log_file, lines=10, filter_pattern="[invalid(")
        assert len(tail) == 2


# --- Asset Processor status tests ---


class TestAssetProcessorStatus:
    def test_not_running(self) -> None:
        with patch("o3de_mcp.tools.assets._is_asset_processor_running", return_value=False):
            with patch.dict("os.environ", {}, clear=True):
                with patch("o3de_mcp.tools.assets.list_registered_projects", return_value=[]):
                    result = asyncio.run(_call_asset_tool("get_asset_processor_status", {}))
                    parsed = json.loads(result)
                    assert parsed["running"] is False

    def test_running_with_project(self, tmp_path: Path) -> None:
        with patch("o3de_mcp.tools.assets._is_asset_processor_running", return_value=True):
            result = asyncio.run(
                _call_asset_tool("get_asset_processor_status", {"project_path": str(tmp_path)})
            )
            parsed = json.loads(result)
            assert parsed["running"] is True
            assert "log" in parsed["log_dir"]


# --- Wait for assets tests ---


class TestWaitForAssets:
    def test_completes_when_ap_not_running(self) -> None:
        with patch("o3de_mcp.tools.assets._is_asset_processor_running", return_value=False):
            result = asyncio.run(_call_asset_tool("wait_for_assets", {"timeout": 5}))
            parsed = json.loads(result)
            assert parsed["completed"] is True

    def test_times_out_when_ap_running(self) -> None:
        # Use a very short timeout to keep the test fast
        with patch("o3de_mcp.tools.assets._is_asset_processor_running", return_value=True):
            result = asyncio.run(_call_asset_tool("wait_for_assets", {"timeout": 2}))
            parsed = json.loads(result)
            assert parsed["completed"] is False

    def test_rejects_zero_timeout(self) -> None:
        # A non-positive timeout is invalid input, raised like every other
        # tool-boundary validation rather than returned as a result.
        with pytest.raises(Exception) as exc_info:
            asyncio.run(_call_asset_tool("wait_for_assets", {"timeout": 0}))
        assert "timeout must be positive" in str(exc_info.value.__cause__)


# --- Tail log tests ---


class TestTailLog:
    def test_reads_log_file(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "log"
        log_dir.mkdir()
        log_file = log_dir / "Editor.log"
        log_file.write_text("Line 1\nLine 2\nLine 3\n")

        result = asyncio.run(
            _call_asset_tool(
                "tail_log",
                {"log_name": "Editor", "lines": 10, "project_path": str(tmp_path)},
            )
        )
        parsed = json.loads(result)
        assert parsed["count"] == 3
        assert "Line 3" in parsed["lines"]

    def test_filters_log_lines(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "log"
        log_dir.mkdir()
        log_file = log_dir / "Editor.log"
        log_file.write_text("INFO: ok\nERROR: broke\nINFO: ok2\n")

        result = asyncio.run(
            _call_asset_tool(
                "tail_log",
                {
                    "log_name": "Editor",
                    "lines": 10,
                    "filter": "ERROR",
                    "project_path": str(tmp_path),
                },
            )
        )
        parsed = json.loads(result)
        assert parsed["count"] == 1
        assert "broke" in parsed["lines"][0]

    def test_nonexistent_log(self, tmp_path: Path) -> None:
        result = asyncio.run(
            _call_asset_tool(
                "tail_log",
                {"log_name": "NonExistent", "project_path": str(tmp_path)},
            )
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["code"] == "log_not_found"

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        result = asyncio.run(
            _call_asset_tool(
                "tail_log",
                {"log_name": "../etc/passwd", "project_path": str(tmp_path)},
            )
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["code"] == "invalid_log_name"


# --- Get log errors tests ---


class TestGetLogErrors:
    def test_extracts_errors(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "log"
        log_dir.mkdir()
        log_file = log_dir / "Editor.log"
        log_file.write_text(
            "INFO: starting\n"
            "ERROR: something broke\n"
            "INFO: running\n"
            "AZ_Error: another error\n"
            "WARNING: minor issue\n"
        )

        result = asyncio.run(
            _call_asset_tool(
                "get_log_errors",
                {"log_name": "Editor", "since_lines": 100, "project_path": str(tmp_path)},
            )
        )
        parsed = json.loads(result)
        assert parsed["count"] == 2
        assert any("something broke" in e for e in parsed["errors"])
        assert any("another error" in e for e in parsed["errors"])

    def test_no_errors_returns_empty(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "log"
        log_dir.mkdir()
        log_file = log_dir / "Editor.log"
        log_file.write_text("INFO: all good\nINFO: no problems\n")

        result = asyncio.run(
            _call_asset_tool(
                "get_log_errors",
                {"project_path": str(tmp_path)},
            )
        )
        parsed = json.loads(result)
        assert parsed["count"] == 0

    def test_nonexistent_log(self, tmp_path: Path) -> None:
        result = asyncio.run(
            _call_asset_tool(
                "get_log_errors",
                {"project_path": str(tmp_path)},
            )
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["code"] == "log_not_found"


# --- Asset readiness (native AiCompanion request types) ---


def _ok(payload: dict) -> dict:
    return {"status": "ok", "output": json.dumps(payload)}


async def _call_with_gem(
    tool: str, arguments: dict, statuses: list[dict], jobs: dict | None = None
):
    """Run an asset tool against a fake gem; statuses answer get_asset_status in turn."""
    from mcp.server import MCPServer

    sent: list[tuple[str, dict]] = []
    replies = list(statuses)

    async def _request(request_type: str, params: dict | None = None, **kwargs: object) -> dict:
        sent.append((request_type, params or {}))
        if request_type == "get_asset_status":
            return replies.pop(0) if len(replies) > 1 else replies[0]
        if request_type == "get_asset_jobs":
            return jobs or _ok({"source_path": "x", "jobs": []})
        return _ok({"connected": True, "ping_ms": 0.2})

    mcp = MCPServer("test")
    register_assets_tools(mcp)
    with patch("o3de_mcp.tools.editor._pool") as pool:
        pool.send_request = AsyncMock(side_effect=_request)
        text = (await mcp.call_tool(tool, arguments)).content[0].text
    return text, sent


def _status(value: str) -> dict:
    return _ok({"path": "Assets/a.fbx", "status": value, "connected": True})


class TestAssetReadinessWrappers:
    def test_get_asset_status_sends_the_path_and_flag(self) -> None:
        text, sent = asyncio.run(
            _call_with_gem(
                "get_asset_status",
                {"path": " Assets/a.fbx ", "flush_io": True},
                [_status("queued")],
            )
        )
        assert sent == [("get_asset_status", {"path": "Assets/a.fbx", "flush_io": True})]
        assert json.loads(text)["status"] == "queued"

    def test_get_asset_jobs_sends_its_flags(self) -> None:
        _, sent = asyncio.run(
            _call_with_gem(
                "get_asset_jobs",
                {"source_path": "Assets/a.fbx", "include_logs": True},
                [_status("x")],
            )
        )
        assert sent == [
            (
                "get_asset_jobs",
                {"source_path": "Assets/a.fbx", "escalate": False, "include_logs": True},
            )
        ]

    def test_connection_uses_the_gem_status_request(self) -> None:
        text, sent = asyncio.run(
            _call_with_gem("get_asset_processor_connection", {}, [_status("x")])
        )
        assert sent[0][0] == "get_asset_processor_status"
        assert json.loads(text) == {"connected": True, "ping_ms": 0.2}

    def test_rejects_an_empty_path(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_with_gem("get_asset_status", {"path": "  "}, [_status("x")]))


class TestWaitForAsset:
    ARGS = {"path": "Assets/a.fbx", "timeout": 2, "poll_interval": 0.1}

    def test_compiled_returns_ready(self) -> None:
        text, sent = asyncio.run(_call_with_gem("wait_for_asset", self.ARGS, [_status("compiled")]))
        parsed = json.loads(text)
        assert parsed["ready"] is True and parsed["status"] == "compiled"
        assert sent[0][1]["flush_io"] is False

    def test_just_written_flushes_only_the_first_poll(self) -> None:
        _, sent = asyncio.run(
            _call_with_gem(
                "wait_for_asset",
                {**self.ARGS, "just_written": True},
                [_status("queued"), _status("compiled")],
            )
        )
        flags = [p["flush_io"] for t, p in sent if t == "get_asset_status"]
        assert flags == [True, False]

    def test_waits_through_queued_and_compiling(self) -> None:
        text, _ = asyncio.run(
            _call_with_gem(
                "wait_for_asset",
                self.ARGS,
                [_status("queued"), _status("compiling"), _status("compiled")],
            )
        )
        assert json.loads(text)["ready"] is True

    def test_a_failed_build_behind_missing_is_reported_with_logs(self) -> None:
        failed_job = {
            "job_key": "Scene compilation",
            "status": "failed",
            "error_count": 4,
            "log": "boom",
        }
        with patch("o3de_mcp.tools.assets._MISSING_GRACE_SECONDS", 0.0):
            text, sent = asyncio.run(
                _call_with_gem(
                    "wait_for_asset",
                    self.ARGS,
                    [_status("missing")],
                    jobs=_ok({"source_path": "Assets/a.fbx", "jobs": [failed_job]}),
                )
            )
        parsed = json.loads(text)
        assert parsed["status"] == "error" and parsed["code"] == "asset_build_failed"
        assert parsed["jobs"] == [failed_job]
        assert ("get_asset_jobs", {"source_path": "Assets/a.fbx", "include_logs": True}) in sent

    def test_a_status_of_failed_is_reported_too(self) -> None:
        failed_job = {"job_key": "k", "status": "failed"}
        text, _ = asyncio.run(
            _call_with_gem(
                "wait_for_asset",
                self.ARGS,
                [_status("failed")],
                jobs=_ok({"source_path": "Assets/a.fbx", "jobs": [failed_job]}),
            )
        )
        assert json.loads(text)["code"] == "asset_build_failed"

    def test_not_registered_yet_keeps_waiting_until_timeout(self) -> None:
        # get_asset_jobs answers engine_error for a file the AP has not seen.
        with patch("o3de_mcp.tools.assets._MISSING_GRACE_SECONDS", 0.0):
            text, _ = asyncio.run(
                _call_with_gem(
                    "wait_for_asset",
                    {**self.ARGS, "timeout": 0.5},
                    [_status("missing")],
                    jobs={"status": "error", "code": "engine_error", "error": "no answer"},
                )
            )
        parsed = json.loads(text)
        assert parsed["ready"] is False and parsed["status"] == "missing"

    def test_source_path_is_used_for_the_job_check(self) -> None:
        with patch("o3de_mcp.tools.assets._MISSING_GRACE_SECONDS", 0.0):
            _, sent = asyncio.run(
                _call_with_gem(
                    "wait_for_asset",
                    {
                        **self.ARGS,
                        "timeout": 0.3,
                        "path": "a.fbx.azmodel",
                        "source_path": "Assets/a.fbx",
                    },
                    [_status("missing")],
                )
            )
        assert ("get_asset_jobs", {"source_path": "Assets/a.fbx", "include_logs": True}) in sent

    def test_a_gem_error_is_passed_through(self) -> None:
        unavailable = {"status": "error", "code": "unavailable", "error": "not connected to the AP"}
        text, _ = asyncio.run(_call_with_gem("wait_for_asset", self.ARGS, [unavailable]))
        parsed = json.loads(text)
        assert parsed["status"] == "error" and parsed["code"] == "unavailable"

    @pytest.mark.parametrize(
        "arguments", [{"timeout": 0}, {"timeout": 4000}, {"poll_interval": 0.01}]
    )
    def test_rejects_bad_timing(self, arguments: dict) -> None:
        with pytest.raises(Exception):
            asyncio.run(
                _call_with_gem(
                    "wait_for_asset", {"path": "Assets/a.fbx", **arguments}, [_status("x")]
                )
            )
