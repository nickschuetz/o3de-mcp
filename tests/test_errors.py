# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""The shared failure envelope and the tools that must emit it."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp.server import MCPServer

from o3de_mcp.utils.errors import error_dict, format_error


class TestFailureEnvelope:
    def test_format_error_shape(self) -> None:
        parsed = json.loads(format_error("some_code", "a message"))
        assert parsed == {"status": "error", "code": "some_code", "message": "a message"}

    def test_error_dict_shape(self) -> None:
        assert error_dict("c", "m") == {"status": "error", "code": "c", "message": "m"}

    def test_format_error_is_the_json_of_error_dict(self) -> None:
        assert json.loads(format_error("c", "m")) == error_dict("c", "m")

    def test_editor_and_project_share_the_one_helper(self) -> None:
        # Both modules bind the same shared helper, so the envelope cannot drift.
        from o3de_mcp.tools import editor, project

        assert editor._format_error is format_error
        assert project._format_error is format_error


def _call(mcp: MCPServer, tool: str, **kwargs: object) -> dict:
    content = asyncio.run(mcp.call_tool(tool, kwargs)).content
    return json.loads(content[0].text)


class TestToolsEmitTheEnvelope:
    """A representative failure from each tool family carries status/code/message."""

    def test_asset_log_tool_failure(self, tmp_path: Path) -> None:
        from o3de_mcp.tools.assets import register_assets_tools

        mcp = MCPServer("test")
        register_assets_tools(mcp)
        parsed = _call(mcp, "tail_log", log_name="../escape", project_path=str(tmp_path))
        assert parsed["status"] == "error"
        assert parsed["code"] == "invalid_log_name"
        assert parsed["message"]

    def test_project_tool_failure(self) -> None:
        from o3de_mcp.tools.project import register_project_tools

        mcp = MCPServer("test")
        register_project_tools(mcp)
        # An unknown build id is reported with the envelope, not a raw string.
        parsed = _call(mcp, "get_build_status", build_id="no-such-build")
        assert parsed["status"] == "error"
        assert parsed["code"] == "not_found"
        assert parsed["message"]

    def test_introspection_tool_failure(self, tmp_path: Path) -> None:
        from o3de_mcp.tools.introspection import register_introspection_tools

        mcp = MCPServer("test")
        register_introspection_tools(mcp)
        parsed = _call(mcp, "get_bus_schema", module="does.not.exist", project_path=str(tmp_path))
        assert parsed["status"] == "error"
        assert parsed["code"] == "schema_not_found"
