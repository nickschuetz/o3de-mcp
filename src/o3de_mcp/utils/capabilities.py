# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Runtime capability probing for the O3DE MCP server."""

from __future__ import annotations

import asyncio
import enum
import json
import logging
from typing import TYPE_CHECKING

from o3de_mcp.tools.editor import _get_editor_host, _get_editor_port
from o3de_mcp.utils.o3de import find_o3de_cli, find_o3de_engine_path, find_o3de_engine_version

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

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
        "assign_asset",
        "remove_component",
        "set_transform",
        "get_transform",
        "set_parent",
        "run_console_command",
        "get_cvar",
        "set_cvar",
        "load_level",
        "get_level_info",
        "save_level",
        "create_level",
        "list_levels",
        "enter_game_mode",
        "exit_game_mode",
        "undo",
        "redo",
        "get_viewport_camera",
        "set_viewport_camera",
        "focus_entity",
        "capture_viewport",
        "instantiate_prefab",
        "create_prefab_from_entity",
        "save_prefab",
        "begin_session",
        "exec_in_session",
        "end_session",
        "get_session_vars",
    }
)

_PROJECT_TOOLS = frozenset(
    {
        "get_engine_info",
        "list_projects",
        "list_gems",
        "list_project_gems",
        "create_project",
        "register_gem",
        "enable_gem",
        "disable_gem",
        "create_gem",
        "export_project",
        "edit_project_properties",
        "list_templates",
        "build_project",
        "register_engine",
        "set_active_engine",
        "start_build",
        "get_build_status",
    }
)

_ASSET_TOOLS = frozenset(
    {
        "get_asset_processor_status",
        "wait_for_assets",
        "refresh_assets",
        "tail_log",
        "get_log_errors",
    }
)

_INTROSPECTION_TOOLS = frozenset(
    {
        "get_bus_schema",
        "get_bus_schema_live",
        "capture_renderdoc_frame",
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
    """Lightweight ping check against the editor via the connection pool."""
    from o3de_mcp.tools.editor import _pool

    host = host or _get_editor_host()
    port = port or _get_editor_port()

    _pool._last_failure_time = None

    try:
        result = await _pool.send_script("print('ping')", host=host, port=port, timeout=timeout)
        try:
            parsed = json.loads(result)
            if parsed.get("status") == "error":
                code = parsed.get("code", "")
                if code in (
                    "connection_refused",
                    "timeout",
                    "socket_error",
                    "editor_unavailable",
                    "connection_error",
                ):
                    return EditorStatus.UNREACHABLE
                return EditorStatus.CONNECTED
            return EditorStatus.CONNECTED
        except (json.JSONDecodeError, TypeError):
            return EditorStatus.CONNECTED
    except (ConnectionRefusedError, ConnectionError, TimeoutError, asyncio.TimeoutError, OSError):
        return EditorStatus.UNREACHABLE
    finally:
        await _pool._close()


def probe_cli() -> dict:
    """Check whether the O3DE CLI is available."""
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
    """Categorize registered tools from the FastMCP instance."""
    if mcp is None:
        return {
            "editor_tools": list(_EDITOR_TOOLS),
            "project_tools": list(_PROJECT_TOOLS),
            "asset_tools": list(_ASSET_TOOLS),
            "introspection_tools": list(_INTROSPECTION_TOOLS),
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
            "asset_tools": list(_ASSET_TOOLS),
            "introspection_tools": list(_INTROSPECTION_TOOLS),
            "capabilities_tools": list(_CAPABILITIES_TOOLS),
        }

    categorized: dict[str, list[str]] = {
        "editor_tools": sorted(registered & _EDITOR_TOOLS),
        "project_tools": sorted(registered & _PROJECT_TOOLS),
        "asset_tools": sorted(registered & _ASSET_TOOLS),
        "introspection_tools": sorted(registered & _INTROSPECTION_TOOLS),
        "capabilities_tools": sorted(registered & _CAPABILITIES_TOOLS),
    }

    known = (
        _EDITOR_TOOLS | _PROJECT_TOOLS | _ASSET_TOOLS | _INTROSPECTION_TOOLS | _CAPABILITIES_TOOLS
    )
    other = sorted(registered - known)
    if other:
        categorized["other_tools"] = other

    return categorized


async def get_server_capabilities(mcp: FastMCP | None = None) -> dict:
    """Aggregate editor and CLI probing into a single capabilities report."""
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
        elif category_name == "asset_tools":
            available = cli_info["available"]
            reason = None if available else "O3DE CLI/engine not found"
        elif category_name == "introspection_tools":
            # get_bus_schema reads .pyi stubs from disk and works without a
            # running editor; only get_bus_schema_live / capture_renderdoc_frame
            # need the connection, which the editor status already conveys.
            available = True
            reason = None
        else:
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
