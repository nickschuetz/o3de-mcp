# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""EMotion FX animation tools.

EMotion FX anim graphs are not usefully reflected to editor Python, so these
tools call the AiCompanion gem's native C++ request types directly. They need a
gem that serves them (gem main, or 0.6.0 and later) and the EMotionFX gem
enabled in the project. An older gem answers with the failure envelope and code
``unknown_request_type``; a project without EMotion FX answers with code
``unavailable``. There is no editor-Python fallback, and every tool works in the
gem's secure mode.

Graph ids are 32-bit numbers; node, transition and entity ids are decimal
strings. Authoring writes refuse a graph owned by an asset or a running actor
instance, so author on a graph from ``create_anim_graph`` or
``load_anim_graph``. Each write is one step in the Animation Editor's own undo
history, separate from the editor's main undo: the ``undo`` tool does not revert
it. ``save_anim_graph`` is not undoable.
"""

from __future__ import annotations

import math
import re

from mcp.server import MCPServer

_U32_MAX = 2**32 - 1
_U64_MAX = 2**64 - 1

# Node and parameter type names: an RTTI class name (AnimGraphMotionNode), a
# palette name ("Blend Tree") or a namespaced class name. The gem resolves them.
_TYPE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _:\-]{0,127}$")

ParameterValue = bool | int | float | str | list[float]


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


def _validate_node_id(node_id: int | str, label: str = "node_id") -> str:
    """Return a node id as the decimal string the gem expects (a u64)."""
    if isinstance(node_id, bool):
        raise ValueError(f"Invalid {label} {node_id!r}: expected a decimal id.")
    text = str(node_id).strip()
    if not text.isdigit() or int(text) > _U64_MAX:
        raise ValueError(f"Invalid {label} {node_id!r}: expected a decimal 64-bit id.")
    return text


def _validate_file_name(file_name: str) -> str:
    file_name = file_name.strip()
    if not file_name:
        raise ValueError("file_name cannot be empty.")
    if len(file_name) > 1024:
        raise ValueError("file_name is too long (max 1024 characters).")
    if any(ord(ch) < 32 for ch in file_name):
        raise ValueError("file_name must not contain control characters.")
    return file_name


def _validate_text(value: str, label: str, max_len: int = 128) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label} cannot be empty.")
    if len(value) > max_len:
        raise ValueError(f"{label} is too long (max {max_len} characters).")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError(f"{label} must not contain control characters.")
    return value


def _validate_type_name(value: str, label: str) -> str:
    value = value.strip()
    if not _TYPE_NAME_RE.match(value):
        raise ValueError(
            f"Invalid {label} {value!r}: expected a class or palette name "
            "(letters first; letters, digits, spaces, '_', ':' or '-')."
        )
    return value


def _validate_position(position: list[int]) -> list[int]:
    """Return a graph-canvas position as two integers."""
    if not isinstance(position, (list, tuple)) or len(position) != 2:
        raise ValueError("position must be [x, y].")
    out: list[int] = []
    for v in position:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("position must contain two integers (graph canvas pixels).")
        if not math.isfinite(v) or v != int(v):
            raise ValueError("position must contain two integers (graph canvas pixels).")
        out.append(int(v))
    return out


def _validate_parameter_value(value: ParameterValue, label: str) -> ParameterValue:
    """Check a default/min/max value's shape; the gem checks it against the type."""
    if isinstance(value, (bool, str)):
        if isinstance(value, str) and len(value) > 1024:
            raise ValueError(f"{label} is too long (max 1024 characters).")
        return value
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError(f"{label} must be a finite number.")
        return value
    if isinstance(value, (list, tuple)) and 2 <= len(value) <= 4:
        for v in value:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"{label} must contain only finite numbers.")
        return list(value)
    raise ValueError(f"{label} must be a number, bool, string, or a list of 2 to 4 numbers.")


def register_animation_tools(mcp: MCPServer) -> None:
    """Register EMotion FX animation tools with the MCP server."""
    from o3de_mcp.tools.editor import _native_request

    # --- Reads ---

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
        connections; state machines also carry ``entry_state_id``),
        ``transitions`` (with blend time and conditions), ``parameters``,
        ``node_groups`` and the ``root_state_machine_id``. Pass exactly one
        selector. An unknown graph is returned as an error. Needs the AiCompanion
        gem's native request (gem main or 0.6.0+) and the EMotionFX gem.

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

    # --- Graph lifecycle ---

    @mcp.tool()
    async def create_anim_graph() -> str:
        """Create a new, empty, in-memory EMotion FX anim graph to author.

        Returns ``{"id": <graph id>, "file_name": ""}``. The graph starts with
        only its root state machine. Save it with ``save_anim_graph``; remove it
        with ``remove_anim_graph``.
        """
        return await _native_request("create_anim_graph")

    @mcp.tool()
    async def remove_anim_graph(anim_graph_id: int | str) -> str:
        """Remove an anim graph from the engine (not its file on disk).

        Returns ``{"removed": <graph id>}``.

        Args:
            anim_graph_id: Graph id (number or digit string).
        """
        return await _native_request(
            "remove_anim_graph", {"anim_graph_id": _validate_anim_graph_id(anim_graph_id)}
        )

    @mcp.tool()
    async def load_anim_graph(file_name: str) -> str:
        """Load an ``.animgraph`` file into the engine so it can be authored.

        Returns ``{"id", "file_name"}``. Loading a file that is already loaded
        this way returns the existing graph's id.

        Args:
            file_name: Absolute path, an ``@alias@`` path, or a path relative to
                the project.
        """
        return await _native_request(
            "load_anim_graph", {"file_name": _validate_file_name(file_name)}
        )

    @mcp.tool()
    async def save_anim_graph(anim_graph_id: int | str, file_name: str | None = None) -> str:
        """Save an anim graph to disk. Not undoable.

        Returns ``{"id", "file_name"}``. The file must land inside the project
        root; the gem refuses any other path.

        Args:
            anim_graph_id: Graph id (number or digit string).
            file_name: Where to save. Omit to save to the graph's current file.
        """
        params: dict[str, object] = {"anim_graph_id": _validate_anim_graph_id(anim_graph_id)}
        if file_name is not None:
            params["file_name"] = _validate_file_name(file_name)
        return await _native_request("save_anim_graph", params)

    # --- Nodes and states ---

    @mcp.tool()
    async def add_anim_graph_node(
        anim_graph_id: int | str,
        node_type: str,
        parent_id: int | str | None = None,
        name: str | None = None,
        position: list[int] | None = None,
    ) -> str:
        """Add a node to an anim graph.

        Returns the new node object exactly as ``get_anim_graph`` emits it. An
        unknown ``node_type`` is refused with the list of known types.

        Args:
            anim_graph_id: Graph id (number or digit string).
            node_type: RTTI or palette name, case-insensitive (for example
                ``AnimGraphMotionNode``, ``AnimGraphStateMachine``, ``BlendTree``,
                ``BlendTreeBlend2Node``).
            parent_id: Parent node id (a state machine or blend tree). Defaults to
                the root state machine.
            name: Node name. The engine generates one when omitted.
            position: ``[x, y]`` graph-canvas position in integer pixels.
        """
        params: dict[str, object] = {
            "anim_graph_id": _validate_anim_graph_id(anim_graph_id),
            "node_type": _validate_type_name(node_type, "node_type"),
        }
        if parent_id is not None:
            params["parent_id"] = _validate_node_id(parent_id, "parent_id")
        if name is not None:
            params["name"] = _validate_text(name, "name")
        if position is not None:
            params["position"] = _validate_position(position)
        return await _native_request("add_anim_graph_node", params)

    @mcp.tool()
    async def remove_anim_graph_node(anim_graph_id: int | str, node_id: int | str) -> str:
        """Remove a node (and its children) from an anim graph. The root is refused.

        Returns ``{"removed": "<node id>"}``.

        Args:
            anim_graph_id: Graph id (number or digit string).
            node_id: Node id from ``get_anim_graph``.
        """
        return await _native_request(
            "remove_anim_graph_node",
            {
                "anim_graph_id": _validate_anim_graph_id(anim_graph_id),
                "node_id": _validate_node_id(node_id),
            },
        )

    @mcp.tool()
    async def set_anim_graph_entry_state(anim_graph_id: int | str, node_id: int | str) -> str:
        """Make a node the entry state of the state machine that contains it.

        Returns ``{"entry_state_id": "<node id>"}``.

        Args:
            anim_graph_id: Graph id (number or digit string).
            node_id: The node to enter first; it must be able to act as a state.
        """
        return await _native_request(
            "set_anim_graph_entry_state",
            {
                "anim_graph_id": _validate_anim_graph_id(anim_graph_id),
                "node_id": _validate_node_id(node_id),
            },
        )

    # --- Parameters ---

    @mcp.tool()
    async def add_anim_graph_parameter(
        anim_graph_id: int | str,
        name: str,
        parameter_type: str,
        default: ParameterValue | None = None,
        min: ParameterValue | None = None,  # noqa: A002 - mirrors the gem's field name
        max: ParameterValue | None = None,  # noqa: A002 - mirrors the gem's field name
        description: str | None = None,
        group: str | None = None,
    ) -> str:
        """Add a value parameter to an anim graph.

        Returns the parameter object as ``get_anim_graph`` emits it. The gem
        checks each value against the type; ``min`` and ``max`` are only valid
        for ranged types (Float, Int, Vector2/3/4, Color, Rotation).

        Args:
            anim_graph_id: Graph id (number or digit string).
            name: Parameter name.
            parameter_type: ``Float`` (a FloatSlider), ``FloatSpinner``, ``Int``
                (an IntSlider), ``IntSpinner``, ``Bool``, ``String``, ``Tag``,
                ``Vector2``, ``Vector3``, ``Vector3Gizmo``, ``Vector4``, ``Color``,
                ``Rotation``, or the full class name.
            default: Default value: a number, bool, string, or a list of numbers
                for vector, color and rotation types.
            min: Range minimum (ranged types only).
            max: Range maximum (ranged types only).
            description: Optional description.
            group: Group to put the parameter in; created when missing.
        """
        params: dict[str, object] = {
            "anim_graph_id": _validate_anim_graph_id(anim_graph_id),
            "name": _validate_text(name, "name"),
            "parameter_type": _validate_type_name(parameter_type, "parameter_type"),
        }
        for key, value in (("default", default), ("min", min), ("max", max)):
            if value is not None:
                params[key] = _validate_parameter_value(value, key)
        if description is not None:
            params["description"] = _validate_text(description, "description", max_len=1024)
        if group is not None:
            params["group"] = _validate_text(group, "group")
        return await _native_request("add_anim_graph_parameter", params)

    @mcp.tool()
    async def remove_anim_graph_parameter(anim_graph_id: int | str, name: str) -> str:
        """Remove a value parameter from an anim graph. Groups are refused.

        Returns ``{"removed": "<name>"}``.

        Args:
            anim_graph_id: Graph id (number or digit string).
            name: The parameter's name.
        """
        return await _native_request(
            "remove_anim_graph_parameter",
            {
                "anim_graph_id": _validate_anim_graph_id(anim_graph_id),
                "name": _validate_text(name, "name"),
            },
        )
