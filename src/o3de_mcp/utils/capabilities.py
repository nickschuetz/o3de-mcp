# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Runtime capability probing for the O3DE MCP server.

Detects whether the O3DE Editor is reachable via its remote console socket
and whether the O3DE CLI is available, so that agents can make informed
decisions about which tools to use.

Tool categories are discovered dynamically from the FastMCP tool registry,
so new tools added in the future are automatically reported.
"""

from __future__ import annotations

import asyncio
import enum
import logging
from typing import TYPE_CHECKING

from o3de_mcp.tools.editor import _get_editor_host, _get_editor_port
from o3de_mcp.utils.o3de import find_o3de_cli, find_o3de_engine_path, find_o3de_engine_version

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Known tool names by category. Tools not in any of these sets are reported
# in an "other_tools" category, ensuring new tools are never silently hidden.
_EDITOR_TOOLS = frozenset(
    {
        "run_editor_python",
        "list_entities",
        "create_entity",
        "delete_entity",
        "duplicate_entity",
        "get_entity_components",
        "add_component",
        "get_component_property",
        "set_component_property",
        "load_level",
        "get_level_info",
        "save_level",
        "enter_game_mode",
        "exit_game_mode",
        "undo",
        "redo",
    }
)

_PROJECT_TOOLS = frozenset(
    {
        "get_engine_info",
        "list_projects",
        "list_gems",
        "create_project",
        "register_gem",
        "enable_gem",
        "disable_gem",
        "create_gem",
        "export_project",
        "edit_project_properties",
        "list_templates",
        "build_project",
    }
)

_CAPABILITIES_TOOLS = frozenset(
    {
        "get_capabilities",
    }
)


class EditorStatus(enum.Enum):
    """Result of probing the O3DE Editor remote console."""

    CONNECTED = "connected"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


async def probe_editor_connection(
    host: str | None = None,
    port: int | None = None,
    timeout: float = 2.0,
) -> EditorStatus:
    """Perform a lightweight TCP connect check against the editor.

    Does not send any commands — only verifies that the port is listening.
    """
    host = host or _get_editor_host()
    port = port or _get_editor_port()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return EditorStatus.CONNECTED
    except (ConnectionRefusedError, TimeoutError, asyncio.TimeoutError, OSError):
        return EditorStatus.UNREACHABLE


def probe_cli() -> dict:
    """Check whether the O3DE CLI is available.

    Returns a dict with ``available``, ``path``, and ``engine_version`` keys.
    """
    cli = find_o3de_cli()
    engine = find_o3de_engine_path()
    version = find_o3de_engine_version()
    return {
        "available": cli is not None,
        "path": str(cli) if cli else None,
        "engine_path": str(engine) if engine else None,
        "engine_version": version,
    }


def _discover_tool_categories(mcp: FastMCP | None) -> dict:
    """Dynamically categorize registered tools from the FastMCP instance.

    Any tool not in a known category is reported under ``other_tools``,
    ensuring newly added tools are never silently hidden.
    """
    if mcp is None:
        # Fallback when mcp instance is not available (e.g., unit tests)
        return {
            "editor_tools": list(_EDITOR_TOOLS),
            "project_tools": list(_PROJECT_TOOLS),
            "capabilities_tools": list(_CAPABILITIES_TOOLS),
        }

    registered: set[str] = set()
    try:
        for tool in mcp._tool_manager.list_tools():
            registered.add(tool.name)
    except AttributeError:
        logger.debug("Could not introspect FastMCP tool registry.")
        return {
            "editor_tools": list(_EDITOR_TOOLS),
            "project_tools": list(_PROJECT_TOOLS),
            "capabilities_tools": list(_CAPABILITIES_TOOLS),
        }

    categorized: dict[str, list[str]] = {
        "editor_tools": sorted(registered & _EDITOR_TOOLS),
        "project_tools": sorted(registered & _PROJECT_TOOLS),
        "capabilities_tools": sorted(registered & _CAPABILITIES_TOOLS),
    }

    # Catch any tools that don't belong to a known category
    known = _EDITOR_TOOLS | _PROJECT_TOOLS | _CAPABILITIES_TOOLS
    other = sorted(registered - known)
    if other:
        categorized["other_tools"] = other

    return categorized


async def get_server_capabilities(mcp: FastMCP | None = None) -> dict:
    """Aggregate editor and CLI probing into a single capabilities report.

    Args:
        mcp: The FastMCP server instance. When provided, tool categories
             are discovered dynamically from the registry. When ``None``,
             falls back to the known built-in tool sets.
    """
    host = _get_editor_host()
    port = _get_editor_port()
    editor_status = await probe_editor_connection(host, port)
    cli_info = probe_cli()

    editor_connected = editor_status == EditorStatus.CONNECTED

    editor_info: dict = {
        "status": editor_status.value,
        "host": host,
        "port": port,
    }
    if not editor_connected:
        editor_info["hint"] = (
            "Start the O3DE Editor with the AiCompanion and EditorPythonBindings gems enabled."
        )

    categories = _discover_tool_categories(mcp)

    tool_categories: dict = {}
    for category_name, tool_names in categories.items():
        if category_name == "editor_tools":
            available = editor_connected
            reason = None if available else "Editor not connected"
        elif category_name == "capabilities_tools":
            available = True
            reason = None
        elif category_name == "project_tools":
            available = cli_info["available"]
            reason = None if available else "O3DE CLI not found"
        else:
            # Unknown category — report as available (conservative default)
            available = True
            reason = None

        tool_categories[category_name] = {
            "available": available,
            "reason": reason,
            "tool_count": len(tool_names),
            "tools": tool_names,
        }

    return {
        "editor": editor_info,
        "cli": cli_info,
        "tool_categories": tool_categories,
    }
