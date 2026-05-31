# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""MCP tool for discovering O3DE reflected EBus APIs.

Exposes ``get_bus_schema``: a generic, gem-agnostic query that reads the
editor's generated Python stubs and returns the verbs, argument types and
return type of any reflected EBus. Lets an agent learn a gem's scripting API
with no hand-maintained per-gem catalog.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from o3de_mcp.utils.introspection import get_bus_schema as _get_bus_schema


def register_introspection_tools(mcp: FastMCP) -> None:
    """Register reflection-introspection tools with the MCP server."""

    @mcp.tool()
    async def get_bus_schema(
        module: str | None = None,
        bus: str | None = None,
        project_path: str | None = None,
    ) -> str:
        """Discover the scripting API of any O3DE gem's reflected EBuses.

        Reads the editor's generated azlmbr stubs (written to
        ``<project>/user/python_symbols/azlmbr``) and returns the available
        buses, their events, and each event's argument types and return type.
        This is gem-agnostic: it works for any reflected bus with no per-gem
        special-casing, so an agent can learn an API before calling it.

        The stub is produced when the editor runs; a live editor connection is
        not required, but the project must have been opened in the editor at
        least once.

        Args:
            module: azlmbr submodule to inspect (e.g. "diorama", "physics").
                Omit to list the modules that have a generated stub.
            bus: Optional bus name to filter to (e.g. "DioramaSpriteRequestBus").
            project_path: Project whose stubs to read. Omit to auto-resolve from
                the O3DE_PROJECT_PATH env var or the single registered project
                that has a dump.

        Returns:
            JSON. With no module: ``{symbols_dir, modules}``. With a module:
            ``{module, source, buses: [{name, addressable, address_type,
            events: [{call_type, name, args, returns}]}], note}``.
        """
        try:
            result = _get_bus_schema(module=module, bus=bus, project_path=project_path)
        except LookupError as error:
            return json.dumps({"error": str(error)}, indent=2)
        return json.dumps(result, indent=2)
