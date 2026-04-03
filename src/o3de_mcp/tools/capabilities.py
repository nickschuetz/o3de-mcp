# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""MCP tool for querying O3DE MCP server capabilities.

Exposes a single ``get_capabilities`` tool that reports the current
availability of the editor connection and CLI, helping agents decide
which tools to use before wasting tokens on unavailable features.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from o3de_mcp.utils.capabilities import get_server_capabilities


def register_capabilities_tools(mcp: FastMCP) -> None:
    """Register capability-detection tools with the MCP server."""

    @mcp.tool()
    async def get_capabilities() -> str:
        """Check what O3DE MCP capabilities are currently available.

        Call this first to determine whether the editor is connected (for
        editor tools) and whether the O3DE CLI is available (for project
        tools). This avoids wasting tokens on tools that will fail.

        Tool categories are discovered dynamically — any new tools added
        to the server will automatically appear in the response.

        Returns:
            JSON object with ``editor``, ``cli``, and ``tool_categories``
            sections describing current availability and configuration.
        """
        caps = await get_server_capabilities(mcp)
        return json.dumps(caps, indent=2)
