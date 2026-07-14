# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""MCP tools for discovering O3DE reflected EBus APIs."""

from __future__ import annotations

import json
import textwrap

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
        """Discover the scripting API of any O3DE gem's reflected EBuses."""
        try:
            result = _get_bus_schema(module=module, bus=bus, project_path=project_path)
        except (LookupError, ValueError) as error:
            return json.dumps({"error": str(error)}, indent=2)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_bus_schema_live(
        module: str,
        bus: str,
        project_path: str | None = None,
    ) -> str:
        """Query the running editor's BehaviorContext for a bus schema."""
        from o3de_mcp.tools.editor import _async_run_editor_script

        params = json.dumps({"module": module, "bus": bus})
        script = textwrap.dedent(f"""\
            import json

            _params = json.loads({params!r})
            _module_name = _params['module']
            _bus_name = _params['bus']

            result = {{'source': 'live', 'module': _module_name, 'bus': _bus_name}}

            try:
                import importlib
                mod = importlib.import_module(f'azlmbr.{{_module_name}}')
                bus_obj = getattr(mod, _bus_name, None)
                if bus_obj is None:
                    result['error'] = f'Bus {{_bus_name}} not found in azlmbr.{{_module_name}}'
                else:
                    events = []
                    if hasattr(bus_obj, 'Events'):
                        for evt in bus_obj.Events:
                            events.append({{
                                'name': str(evt),
                            }})
                    result['events'] = events
                    result['event_count'] = len(events)
            except Exception as e:
                result['source'] = 'error'
                result['error'] = str(e)

            print(json.dumps(result))
        """)

        live_result = await _async_run_editor_script(script)

        try:
            parsed = json.loads(live_result)
            if parsed.get("source") == "live":
                return json.dumps(parsed, indent=2)
        except (json.JSONDecodeError, TypeError):
            pass

        try:
            stub_result = _get_bus_schema(module=module, bus=bus, project_path=project_path)
            stub_result["source"] = "stub_fallback"
            stub_result["live_error"] = live_result[:500] if live_result else "No response"
            return json.dumps(stub_result, indent=2)
        except (LookupError, ValueError) as error:
            return json.dumps(
                {
                    "error": str(error),
                    "source": "stub_fallback_failed",
                    "live_error": live_result[:500] if live_result else "No response",
                },
                indent=2,
            )

    @mcp.tool()
    async def capture_renderdoc_frame() -> str:
        """Trigger a RenderDoc frame capture in the O3DE editor.

        Attempts to trigger a RenderDoc capture via ``GraphicsProfilerBus``
        (reflected in the BehaviorContext but not exposed as a Python bus
        function in O3DE 2.7.0). If the bus call is not available, reports
        the limitation and suggests manual alternatives.

        Returns:
            JSON with status ``ok`` if the capture was triggered, ``error``
            on failure, or ``manual_required`` if the Python API cannot
            trigger the capture and manual action is needed.
        """
        from o3de_mcp.tools.editor import _async_run_editor_script

        script = textwrap.dedent("""\
            import azlmbr.bus as bus
            import json

            try:
                if hasattr(bus, 'GraphicsProfilerBus'):
                    bus.GraphicsProfilerBus(bus.Broadcast, 'TriggerCapture')
                    result = {
                        'status': 'ok',
                        'message': 'RenderDoc frame capture triggered via '
                                   'GraphicsProfilerBus.TriggerCapture.'
                    }
                else:
                    result = {
                        'status': 'manual_required',
                        'message': 'GraphicsProfilerBus is not exposed to Python '
                                   'in this O3DE version. Trigger the capture '
                                   'manually: press F12 in RenderDoc, or use the '
                                   'editor ImGui menu View > Profiling > '
                                   'Trigger GPU Capture.'
                    }
            except Exception as e:
                result = {
                    'status': 'error',
                    'message': f'Failed to trigger capture: {e}.'
                }
            print(json.dumps(result))
        """)
        result = await _async_run_editor_script(script)

        try:
            parsed = json.loads(result)
            if parsed.get("status") == "ok":
                parsed["next_steps"] = (
                    "Use the renderdoc-mcp MCP server to analyze the captured frame: "
                    "1) list_drawcalls to see the draw call list, "
                    "2) get_texture for specific texture data, "
                    "3) get_pipeline_state for shader/blend state, "
                    "4) get_performance_counters for GPU timing data."
                )
                return json.dumps(parsed, indent=2)
        except (json.JSONDecodeError, TypeError):
            pass

        return result
