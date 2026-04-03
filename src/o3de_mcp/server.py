# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""O3DE MCP Server — entry point."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from o3de_mcp.tools.capabilities import register_capabilities_tools
from o3de_mcp.tools.editor import register_editor_tools
from o3de_mcp.tools.project import register_project_tools

mcp = FastMCP(
    "o3de-mcp",
    instructions="MCP server for Open 3D Engine — editor automation and project management",
)

register_capabilities_tools(mcp)
register_editor_tools(mcp)
register_project_tools(mcp)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
