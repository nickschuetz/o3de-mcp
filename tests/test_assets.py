# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Tests for asset processor and log tools."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from o3de_mcp.tools.assets import (
    _get_log_dir,
    _read_log_tail,
    _resolve_project_path,
    register_assets_tools,
)

# --- Helper to call tools ---


async def _call_asset_tool(tool_name: str, arguments: dict) -> str:
    """Register asset tools on a throwaway FastMCP and call a tool."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test")
    register_assets_tools(mcp)
    content, _ = await mcp.call_tool(tool_name, arguments)
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
    def test_log_dir_path(self, tmp_path: Path) -> None:
        log_dir = _get_log_dir(tmp_path)
        assert log_dir == tmp_path / "log"


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
        result = asyncio.run(_call_asset_tool("wait_for_assets", {"timeout": 0}))
        parsed = json.loads(result)
        assert "error" in parsed


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
        assert "error" in parsed

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        result = asyncio.run(
            _call_asset_tool(
                "tail_log",
                {"log_name": "../etc/passwd", "project_path": str(tmp_path)},
            )
        )
        parsed = json.loads(result)
        assert "error" in parsed


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
        assert "error" in parsed
