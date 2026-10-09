# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""EMotion FX animation tools.

EMotion FX anim graphs are not usefully reflected to editor Python, so these
tools call the AiCompanion gem's native C++ request types directly. They need a
gem that serves them (gem main, or 0.6.0 and later) and the EMotionFX gem
enabled in the project. An older gem answers with the failure envelope and code
``unknown_request_type``; a project without EMotion FX answers
``EMotion FX is not available``. There is no editor-Python fallback.

The reads work in the gem's secure mode. Graph ids are 32-bit numbers; node,
transition and entity ids inside the output are decimal strings.
"""

from __future__ import annotations

from mcp.server import MCPServer

_U32_MAX = 2**32 - 1


def _validate_anim_graph_id(anim_graph_id: int | str) -> int:
    """Return an anim graph id as an int, accepting a number or a digit string."""
    if isinstance(anim_graph_id, bool):
        raise ValueError(f"Invalid anim_graph_id {anim_graph_id!r}: expected a number.")
    if isinstance(anim_graph_id, int):
        value = anim_graph_id
    else:
        text = str(anim_graph_id).strip()
        if not text.isdigit():
            raise ValueError(
                f"Invalid anim_graph_id {anim_graph_id!r}: expected a non-negative integer."
            )
        value = int(text)
    if not 0 <= value <= _U32_MAX:
        raise ValueError(f"Invalid anim_graph_id {anim_graph_id!r}: out of the 32-bit range.")
    return value


def _validate_file_name(file_name: str) -> str:
    file_name = file_name.strip()
    if not file_name:
        raise ValueError("file_name cannot be empty.")
    if len(file_name) > 1024:
        raise ValueError("file_name is too long (max 1024 characters).")
    if any(ord(ch) < 32 for ch in file_name):
        raise ValueError("file_name must not contain control characters.")
    return file_name


def register_animation_tools(mcp: MCPServer) -> None:
    """Register EMotion FX animation tools with the MCP server."""
    from o3de_mcp.tools.editor import _native_request

    @mcp.tool()
    async def list_anim_graphs() -> str:
        """List every EMotion FX anim graph the engine holds.

        Returns the gem's JSON: ``editor_mode`` and an ``anim_graphs`` array with
        each graph's ``id``, ``file_name``, ownership and dirty flags, node and
        parameter counts, and the actor ``instances`` using it. Needs the
        AiCompanion gem's native request (gem main or 0.6.0+) and the EMotionFX gem.
        """
        return await _native_request("list_anim_graphs")

    @mcp.tool()
    async def get_anim_graph(
        anim_graph_id: int | str | None = None,
        file_name: str | None = None,
    ) -> str:
        """Describe one EMotion FX anim graph in full.

        Returns the gem's JSON: ``nodes`` (with type, parent, position, ports and
        connections), ``transitions`` (with blend time and conditions),
        ``parameters``, ``node_groups`` and the ``root_state_machine_id``. Pass
        exactly one selector. An unknown graph is returned as an error. Needs the
        AiCompanion gem's native request (gem main or 0.6.0+) and the EMotionFX gem.

        Args:
            anim_graph_id: Graph id from ``list_anim_graphs`` (number or digit string).
            file_name: Graph file name, matched exactly first, then by its tail
                case-insensitively (for example ``Character.animgraph``).
        """
        if (anim_graph_id is None) == (file_name is None):
            raise ValueError("Pass exactly one of anim_graph_id or file_name.")
        params: dict[str, object]
        if anim_graph_id is not None:
            params = {"anim_graph_id": _validate_anim_graph_id(anim_graph_id)}
        else:
            params = {"file_name": _validate_file_name(str(file_name))}
        return await _native_request("get_anim_graph", params)
