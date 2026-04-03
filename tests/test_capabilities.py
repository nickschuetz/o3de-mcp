# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Tests for capability detection."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from o3de_mcp.utils.capabilities import (
    EditorStatus,
    _discover_tool_categories,
    get_server_capabilities,
    probe_cli,
    probe_editor_connection,
)


class TestProbeEditorConnection:
    def test_unreachable_on_dead_port(self) -> None:
        result = asyncio.run(probe_editor_connection(host="127.0.0.1", port=19999, timeout=0.5))
        assert result == EditorStatus.UNREACHABLE

    def test_connected_when_server_listening(self) -> None:
        """Verify CONNECTED status when a server is actually listening."""

        async def run() -> EditorStatus:
            # Start a temporary TCP server
            server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            try:
                return await probe_editor_connection(host="127.0.0.1", port=port, timeout=1.0)
            finally:
                server.close()
                await server.wait_closed()

        result = asyncio.run(run())
        assert result == EditorStatus.CONNECTED


class TestProbeCli:
    def test_cli_found(self) -> None:
        mock_cli = Path("/opt/o3de/scripts/o3de.sh")
        mock_engine = Path("/opt/o3de")
        with patch("o3de_mcp.utils.capabilities.find_o3de_cli", return_value=mock_cli):
            with patch(
                "o3de_mcp.utils.capabilities.find_o3de_engine_path",
                return_value=mock_engine,
            ):
                with patch(
                    "o3de_mcp.utils.capabilities.find_o3de_engine_version",
                    return_value="24.09",
                ):
                    result = probe_cli()
        assert result["available"] is True
        assert result["path"] == str(mock_cli)
        assert result["engine_version"] == "24.09"

    def test_cli_not_found(self) -> None:
        with patch("o3de_mcp.utils.capabilities.find_o3de_cli", return_value=None):
            with patch(
                "o3de_mcp.utils.capabilities.find_o3de_engine_path",
                return_value=None,
            ):
                with patch(
                    "o3de_mcp.utils.capabilities.find_o3de_engine_version",
                    return_value=None,
                ):
                    result = probe_cli()
        assert result["available"] is False
        assert result["path"] is None


class TestGetServerCapabilities:
    def test_no_editor_no_cli(self) -> None:
        async def run() -> dict:
            with patch(
                "o3de_mcp.utils.capabilities.probe_editor_connection",
                new_callable=AsyncMock,
                return_value=EditorStatus.UNREACHABLE,
            ):
                with patch(
                    "o3de_mcp.utils.capabilities.probe_cli",
                    return_value={
                        "available": False,
                        "path": None,
                        "engine_path": None,
                        "engine_version": None,
                    },
                ):
                    return await get_server_capabilities()

        caps = asyncio.run(run())
        assert caps["editor"]["status"] == "unreachable"
        assert "hint" in caps["editor"]
        assert caps["cli"]["available"] is False
        assert caps["tool_categories"]["editor_tools"]["available"] is False
        assert caps["tool_categories"]["project_tools"]["available"] is False

    def test_cli_only(self) -> None:
        async def run() -> dict:
            with patch(
                "o3de_mcp.utils.capabilities.probe_editor_connection",
                new_callable=AsyncMock,
                return_value=EditorStatus.UNREACHABLE,
            ):
                with patch(
                    "o3de_mcp.utils.capabilities.probe_cli",
                    return_value={
                        "available": True,
                        "path": "/opt/o3de/scripts/o3de.sh",
                        "engine_path": "/opt/o3de",
                        "engine_version": "24.09",
                    },
                ):
                    return await get_server_capabilities()

        caps = asyncio.run(run())
        assert caps["editor"]["status"] == "unreachable"
        assert caps["cli"]["available"] is True
        assert caps["tool_categories"]["editor_tools"]["available"] is False
        assert caps["tool_categories"]["project_tools"]["available"] is True

    def test_full_capabilities(self) -> None:
        async def run() -> dict:
            with patch(
                "o3de_mcp.utils.capabilities.probe_editor_connection",
                new_callable=AsyncMock,
                return_value=EditorStatus.CONNECTED,
            ):
                with patch(
                    "o3de_mcp.utils.capabilities.probe_cli",
                    return_value={
                        "available": True,
                        "path": "/opt/o3de/scripts/o3de.sh",
                        "engine_path": "/opt/o3de",
                        "engine_version": "24.09",
                    },
                ):
                    return await get_server_capabilities()

        caps = asyncio.run(run())
        assert caps["editor"]["status"] == "connected"
        assert "hint" not in caps["editor"]
        assert caps["tool_categories"]["editor_tools"]["available"] is True
        assert caps["tool_categories"]["project_tools"]["available"] is True


class TestDiscoverToolCategories:
    def test_dynamic_discovery_from_mcp(self) -> None:
        """Tools are discovered dynamically from the FastMCP registry."""
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")

        @mcp.tool()
        def list_entities() -> str:
            """Test editor tool."""
            return ""

        @mcp.tool()
        def create_project() -> str:
            """Test project tool."""
            return ""

        categories = _discover_tool_categories(mcp)
        assert "list_entities" in categories["editor_tools"]
        assert "create_project" in categories["project_tools"]

    def test_unknown_tools_in_other_category(self) -> None:
        """Tools not in any known category appear under 'other_tools'."""
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")

        @mcp.tool()
        def some_future_tool() -> str:
            """A tool that doesn't match any known category."""
            return ""

        categories = _discover_tool_categories(mcp)
        assert "other_tools" in categories
        assert "some_future_tool" in categories["other_tools"]

    def test_no_other_category_when_all_known(self) -> None:
        """No 'other_tools' category when all tools are in known sets."""
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")

        @mcp.tool()
        def get_capabilities() -> str:
            """Known capability tool."""
            return ""

        categories = _discover_tool_categories(mcp)
        assert "other_tools" not in categories

    def test_fallback_without_mcp(self) -> None:
        """Without an mcp instance, returns the known built-in sets."""
        categories = _discover_tool_categories(None)
        assert len(categories["editor_tools"]) > 0
        assert len(categories["project_tools"]) > 0
        assert "other_tools" not in categories
