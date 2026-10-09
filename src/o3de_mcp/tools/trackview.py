# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Track View (cinematic sequence) tools.

Track View is O3DE's cinematic sequencer. Its editor Python surface is reflected
as ``azlmbr.legacy.trackview`` (a plain function module, not a bus), so these tools
run as editor-Python scripts over the same transport as the other editor tools; no
AiCompanion gem request type is involved.

The reflected API has a specific, non-obvious workflow that these tools encapsulate,
learned by probing a live 26.10.0 editor:

- Most calls act on the *current* sequence, set with ``set_current_sequence`` first.
- A sequence has no Director node when created; node queries and tracks need one, so
  add a ``Director`` node before other nodes.
- The string arguments to the node and track calls are director-scoping names, not the
  sequence name; the empty string ``""`` means the sequence root.
- ``new_sequence(name, type)`` takes a ``SequenceType``: 0 is the legacy Cry sequence,
  1 is the modern Sequence Component on an entity. These tools always create type 1.

Track creation and keyframe authoring are deliberately not exposed: ``add_track`` needs
each node type's exact parameter-type name string (not enumerable through this API), and
the only key-authoring path is the interactive record workflow, neither of which is
reliable to drive programmatically yet.
"""

from __future__ import annotations

import json
import re
import textwrap

from mcp.server import MCPServer

# Node types the reflected ``add_node`` accepts, confirmed against a live editor.
# The gem rejects anything else with "Invalid node type".
_NODE_TYPES = frozenset(
    {
        "Director",
        "Event",
        "AzEntity",
        "Component",
        "CVar",
        "Material",
        "Group",
        "Layer",
        "Comment",
    }
)

_SEQUENCE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,127}$")


def _validate_sequence_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Sequence name cannot be empty.")
    if not _SEQUENCE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid sequence name {name!r}: it must start with a letter or digit and "
            "contain only letters, digits, spaces, underscores or hyphens (max 128 chars)."
        )
    return name


def _validate_node_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Node name cannot be empty.")
    if not _SEQUENCE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid node name {name!r}: it must start with a letter or digit and contain "
            "only letters, digits, spaces, underscores or hyphens (max 128 chars)."
        )
    return name


def register_trackview_tools(mcp: MCPServer) -> None:
    """Register Track View cinematic-sequence tools with the MCP server."""
    from o3de_mcp.tools.editor import _async_run_editor_script

    @mcp.tool()
    async def list_sequences() -> str:
        """List the Track View cinematic sequences in the current level.

        Returns a JSON array of ``{"name": ..., "start": ..., "end": ...}`` objects,
        one per sequence, with each sequence's time range in seconds.
        """
        script = textwrap.dedent("""\
            import azlmbr.legacy.trackview as tv
            import json

            _out = []
            _n = tv.get_num_sequences()
            for _i in range(_n or 0):
                _name = tv.get_sequence_name(_i)
                try:
                    _r = tv.get_sequence_time_range(_name)
                    _out.append({'name': _name, 'start': _r.start, 'end': _r.end})
                except Exception:
                    _out.append({'name': _name})
            print(json.dumps({'sequences': _out, 'count': len(_out)}))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def create_sequence(name: str) -> str:
        """Create a new Track View cinematic sequence in the current level.

        Creates a modern Sequence Component sequence (on its own entity). A new
        sequence has no nodes; add a ``Director`` node with ``add_sequence_node``
        before adding other nodes. An existing name is reported as an error.

        Args:
            name: Sequence name.
        """
        name = _validate_sequence_name(name)
        params = json.dumps({"name": name})
        script = textwrap.dedent(f"""\
            import azlmbr.legacy.trackview as tv
            import json

            _name = json.loads({params!r})['name']
            try:
                tv.new_sequence(_name, 1)  # 1 = SequenceComponent (modern)
                print(json.dumps({{'created': _name}}))
            except Exception as e:
                print(json.dumps({{'error': f'could not create sequence {{_name!r}}: {{e}}'}}))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def delete_sequence(name: str) -> str:
        """Delete a Track View cinematic sequence from the current level.

        Args:
            name: Sequence name.
        """
        name = _validate_sequence_name(name)
        params = json.dumps({"name": name})
        script = textwrap.dedent(f"""\
            import azlmbr.legacy.trackview as tv
            import json

            _name = json.loads({params!r})['name']
            try:
                tv.delete_sequence(_name)
                print(json.dumps({{'deleted': _name}}))
            except Exception as e:
                print(json.dumps({{'error': f'could not delete sequence {{_name!r}}: {{e}}'}}))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def get_sequence(name: str) -> str:
        """Describe one Track View sequence: its time range and its nodes.

        Returns JSON with the time range and the node names at the sequence root.
        A sequence with no Director node yet reports an empty node list.

        Args:
            name: Sequence name.
        """
        name = _validate_sequence_name(name)
        params = json.dumps({"name": name})
        script = textwrap.dedent(f"""\
            import azlmbr.legacy.trackview as tv
            import json

            _name = json.loads({params!r})['name']
            try:
                tv.set_current_sequence(_name)
            except Exception as e:
                print(json.dumps({{'error': f'no sequence named {{_name!r}}: {{e}}'}}))
            else:
                _info = {{'name': _name}}
                try:
                    _r = tv.get_sequence_time_range(_name)
                    _info['start'] = _r.start
                    _info['end'] = _r.end
                except Exception:
                    pass
                # Node queries are director-scoped; '' is the sequence root. A sequence
                # with no Director raises, which just means there are no nodes yet.
                _nodes = []
                try:
                    _count = tv.get_num_nodes('')
                    for _i in range(_count or 0):
                        _nodes.append(tv.get_node_name(_i, ''))
                except Exception:
                    pass
                _info['nodes'] = _nodes
                _info['node_count'] = len(_nodes)
                print(json.dumps(_info))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def set_sequence_time_range(name: str, start: float, end: float) -> str:
        """Set a Track View sequence's play time range, in seconds.

        Args:
            name: Sequence name.
            start: Range start in seconds.
            end: Range end in seconds (must be greater than start).
        """
        name = _validate_sequence_name(name)
        try:
            start_f, end_f = float(start), float(end)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"start and end must be numbers, got {start!r}, {end!r}.") from exc
        if end_f <= start_f:
            raise ValueError(f"end ({end_f}) must be greater than start ({start_f}).")
        params = json.dumps({"name": name, "start": start_f, "end": end_f})
        script = textwrap.dedent(f"""\
            import azlmbr.legacy.trackview as tv
            import json

            _p = json.loads({params!r})
            try:
                tv.set_sequence_time_range(_p['name'], _p['start'], _p['end'])
                print(json.dumps({{'name': _p['name'], 'start': _p['start'], 'end': _p['end']}}))
            except Exception as e:
                print(json.dumps({{'error': f'could not set time range: {{e}}'}}))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def add_sequence_node(name: str, node_type: str, node_name: str) -> str:
        """Add a node to a Track View sequence.

        Add a ``Director`` node first; most other node types need a Director present.

        Args:
            name: Sequence name.
            node_type: One of ``Director``, ``Event``, ``AzEntity``, ``Component``,
                ``CVar``, ``Material``, ``Group``, ``Layer``, ``Comment``.
            node_name: Name for the new node.
        """
        name = _validate_sequence_name(name)
        node_name = _validate_node_name(node_name)
        node_type = node_type.strip()
        if node_type not in _NODE_TYPES:
            raise ValueError(
                f"Invalid node_type {node_type!r}. Expected one of: {sorted(_NODE_TYPES)}."
            )
        params = json.dumps({"name": name, "type": node_type, "node": node_name})
        script = textwrap.dedent(f"""\
            import azlmbr.legacy.trackview as tv
            import json

            _p = json.loads({params!r})
            _nm, _ty, _nd = _p['name'], _p['type'], _p['node']
            try:
                tv.set_current_sequence(_nm)
            except Exception as e:
                print(json.dumps({{'error': f'no sequence named {{_nm!r}}: {{e}}'}}))
            else:
                try:
                    tv.add_node(_ty, _nd)
                    print(json.dumps({{'sequence': _nm, 'added_node': _nd, 'type': _ty}}))
                except Exception as e:
                    print(json.dumps({{'error': f'could not add {{_ty}} node {{_nd!r}}: {{e}} '
                                       f'(a Director node must exist before other node types)'}}))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def play_sequence(name: str) -> str:
        """Start playing a Track View sequence in the editor.

        Args:
            name: Sequence name.
        """
        name = _validate_sequence_name(name)
        params = json.dumps({"name": name})
        script = textwrap.dedent(f"""\
            import azlmbr.legacy.trackview as tv
            import json

            _name = json.loads({params!r})['name']
            try:
                tv.set_current_sequence(_name)
                tv.play_sequence()
                print(json.dumps({{'playing': _name}}))
            except Exception as e:
                print(json.dumps({{'error': f'could not play sequence {{_name!r}}: {{e}}'}}))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def stop_sequence() -> str:
        """Stop the Track View sequence currently playing in the editor."""
        script = textwrap.dedent("""\
            import azlmbr.legacy.trackview as tv
            import json

            try:
                tv.stop_sequence()
                print(json.dumps({'stopped': True}))
            except Exception as e:
                print(json.dumps({'error': f'could not stop sequence: {e}'}))
        """)
        return await _async_run_editor_script(script)
