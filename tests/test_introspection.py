# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Tests for generic EBus schema introspection from azlmbr stubs."""

from __future__ import annotations

from pathlib import Path

import pytest

from o3de_mcp.utils.introspection import (
    _parse_args_and_return,
    _split_top_level,
    get_bus_schema,
    parse_stub,
)

# A stub with an addressable bus, a broadcast-only bus, a templated return type,
# and a free function (which must NOT be parsed as a bus). Built line-by-line so
# the long, realistic .pyi lines stay intact without tripping the line-length lint.
SAMPLE_STUB = "\n".join(
    [
        "def DioramaSpriteRequestBus(busCallType: int, busEventName: str, "
        "address: EntityId, args: Tuple[Any]) -> Any:",
        '    """',
        "    The following bus Call types, Event names and "
        "Argument types are supported by this bus:",
        "    bus.Event, 'GetSpriteInfo', () -> Diorama::SpriteInfo",
        "    bus.Event, 'SetSize', (float, float) -> None",
        "    bus.Event, 'SetTextureByPath', (str) -> bool",
        '    """',
        "    pass",
        "",
        "def EditorComponentAPIBus(busCallType: int, busEventName: str, args: Tuple[Any]) -> Any:",
        '    """',
        "    The following bus Call types, Event names and "
        "Argument types are supported by this bus:",
        "    bus.Broadcast, 'AddComponentOfType', (EntityId, AZ::Uuid) -> "
        "Outcome<AZStd::vector<Pair, allocator>, AZStd::basic_string<char, traits, allocator>>",
        '    """',
        "    pass",
        "",
        "def Math_Lerp(a: float,b: float,t: float) -> None:",
        '    """A free function, not a bus."""',
        "    pass",
    ]
)


class TestSplitTopLevel:
    def test_simple(self) -> None:
        assert _split_top_level("float, float, bool") == ["float", "float", "bool"]

    def test_respects_template_commas(self) -> None:
        assert _split_top_level("EntityId, vector<A, B>, int") == [
            "EntityId",
            "vector<A, B>",
            "int",
        ]

    def test_empty(self) -> None:
        assert _split_top_level("") == []


class TestParseArgsAndReturn:
    def test_no_args(self) -> None:
        assert _parse_args_and_return("() -> Diorama::SpriteInfo") == (
            [],
            "Diorama::SpriteInfo",
        )

    def test_scalar_args(self) -> None:
        assert _parse_args_and_return("(float, float) -> None") == (
            ["float", "float"],
            "None",
        )

    def test_templated_return_with_commas(self) -> None:
        args, returns = _parse_args_and_return(
            "(EntityId, AZ::Uuid) -> Outcome<vector<Pair, alloc>, string<char, t, alloc>>"
        )
        assert args == ["EntityId", "AZ::Uuid"]
        assert returns == "Outcome<vector<Pair, alloc>, string<char, t, alloc>>"


class TestParseStub:
    def test_finds_both_buses_not_the_function(self) -> None:
        buses = parse_stub(SAMPLE_STUB)
        names = {bus["name"] for bus in buses}
        assert names == {"DioramaSpriteRequestBus", "EditorComponentAPIBus"}

    def test_addressable_detection(self) -> None:
        buses = {bus["name"]: bus for bus in parse_stub(SAMPLE_STUB)}
        assert buses["DioramaSpriteRequestBus"]["addressable"] is True
        assert buses["DioramaSpriteRequestBus"]["address_type"] == "EntityId"
        assert buses["EditorComponentAPIBus"]["addressable"] is False
        assert buses["EditorComponentAPIBus"]["address_type"] is None

    def test_event_parsing(self) -> None:
        buses = {bus["name"]: bus for bus in parse_stub(SAMPLE_STUB)}
        events = {e["name"]: e for e in buses["DioramaSpriteRequestBus"]["events"]}
        assert events["SetSize"]["args"] == ["float", "float"]
        assert events["SetSize"]["returns"] == "None"
        assert events["GetSpriteInfo"]["args"] == []
        assert events["GetSpriteInfo"]["returns"] == "Diorama::SpriteInfo"
        assert events["SetTextureByPath"]["returns"] == "bool"

    def test_call_type_preserved(self) -> None:
        buses = {bus["name"]: bus for bus in parse_stub(SAMPLE_STUB)}
        event = buses["EditorComponentAPIBus"]["events"][0]
        assert event["call_type"] == "Broadcast"
        assert event["returns"].startswith("Outcome<")

    def test_empty_text(self) -> None:
        assert parse_stub("") == []


def _make_project(tmp_path: Path, module: str, content: str) -> Path:
    symbols = tmp_path / "user" / "python_symbols" / "azlmbr"
    symbols.mkdir(parents=True)
    (symbols / f"{module}.pyi").write_text(content)
    return tmp_path


class TestGetBusSchema:
    def test_list_modules(self, tmp_path: Path) -> None:
        _make_project(tmp_path, "diorama", SAMPLE_STUB)
        result = get_bus_schema(project_path=str(tmp_path))
        assert result["modules"] == ["diorama"]

    def test_module_schema(self, tmp_path: Path) -> None:
        _make_project(tmp_path, "diorama", SAMPLE_STUB)
        result = get_bus_schema(module="diorama", project_path=str(tmp_path))
        assert result["module"] == "diorama"
        assert len(result["buses"]) == 2
        assert "note" in result

    def test_filter_to_one_bus(self, tmp_path: Path) -> None:
        _make_project(tmp_path, "diorama", SAMPLE_STUB)
        result = get_bus_schema(
            module="diorama", bus="DioramaSpriteRequestBus", project_path=str(tmp_path)
        )
        assert len(result["buses"]) == 1
        assert result["buses"][0]["name"] == "DioramaSpriteRequestBus"

    def test_unknown_module_raises(self, tmp_path: Path) -> None:
        _make_project(tmp_path, "diorama", SAMPLE_STUB)
        with pytest.raises(LookupError, match="No stub for module 'nope'"):
            get_bus_schema(module="nope", project_path=str(tmp_path))

    def test_rejects_path_traversal_module(self, tmp_path: Path) -> None:
        _make_project(tmp_path, "diorama", SAMPLE_STUB)
        with pytest.raises(ValueError, match="Invalid module name"):
            get_bus_schema(module="../../../../etc/hostname", project_path=str(tmp_path))

    def test_rejects_module_with_separators(self, tmp_path: Path) -> None:
        _make_project(tmp_path, "diorama", SAMPLE_STUB)
        with pytest.raises(ValueError, match="Invalid module name"):
            get_bus_schema(module="sub/diorama", project_path=str(tmp_path))

    def test_unknown_bus_raises(self, tmp_path: Path) -> None:
        _make_project(tmp_path, "diorama", SAMPLE_STUB)
        with pytest.raises(LookupError, match="No bus 'Nope'"):
            get_bus_schema(module="diorama", bus="Nope", project_path=str(tmp_path))

    def test_missing_dump_raises(self, tmp_path: Path) -> None:
        with pytest.raises(LookupError):
            get_bus_schema(project_path=str(tmp_path))


# --- Phase 10: Live bus schema + RenderDoc integration tool tests ---


class TestGetBusSchemaLive:
    """Tests for the get_bus_schema_live MCP tool."""

    def test_live_query_success(self) -> None:
        """When the editor returns live schema, it's returned directly."""
        import asyncio
        import json
        from unittest.mock import AsyncMock, patch

        from mcp.server.fastmcp import FastMCP

        from o3de_mcp.tools.introspection import register_introspection_tools

        live_json = json.dumps(
            {"source": "live", "module": "physics", "bus": "PhysicsRequestBus", "events": []}
        )

        async def run() -> str:
            mcp = FastMCP("test")
            register_introspection_tools(mcp)
            with patch(
                "o3de_mcp.tools.editor._async_run_editor_script",
                new_callable=AsyncMock,
                return_value=live_json,
            ):
                content, _ = await mcp.call_tool(
                    "get_bus_schema_live",
                    {"module": "physics", "bus": "PhysicsRequestBus"},
                )
                return content[0].text

        result = asyncio.run(run())
        parsed = json.loads(result)
        assert parsed["source"] == "live"
        assert parsed["module"] == "physics"

    def test_falls_back_to_stubs_on_error(self, tmp_path: Path) -> None:
        """When the editor is unreachable, falls back to stub-based schema."""
        import asyncio
        import json
        from unittest.mock import AsyncMock, patch

        from mcp.server.fastmcp import FastMCP

        from o3de_mcp.tools.introspection import register_introspection_tools

        # Create a project with a stub so the fallback can find it
        _make_project(tmp_path, "diorama", SAMPLE_STUB)

        error_response = json.dumps({"source": "error", "error": "Connection refused"})

        async def run() -> str:
            mcp = FastMCP("test")
            register_introspection_tools(mcp)
            with patch(
                "o3de_mcp.tools.editor._async_run_editor_script",
                new_callable=AsyncMock,
                return_value=error_response,
            ):
                content, _ = await mcp.call_tool(
                    "get_bus_schema_live",
                    {
                        "module": "diorama",
                        "bus": "DioramaSpriteRequestBus",
                        "project_path": str(tmp_path),
                    },
                )
                return content[0].text

        result = asyncio.run(run())
        parsed = json.loads(result)
        assert parsed["source"] == "stub_fallback"


class TestCaptureRenderdocFrame:
    """Tests for the capture_renderdoc_frame MCP tool."""

    def test_triggers_capture(self) -> None:
        import asyncio
        import json
        from unittest.mock import AsyncMock, patch

        from mcp.server.fastmcp import FastMCP

        from o3de_mcp.tools.introspection import register_introspection_tools

        capture_json = json.dumps({"status": "ok", "message": "RenderDoc frame capture triggered."})

        async def run() -> str:
            mcp = FastMCP("test")
            register_introspection_tools(mcp)
            with patch(
                "o3de_mcp.tools.editor._async_run_editor_script",
                new_callable=AsyncMock,
                return_value=capture_json,
            ):
                content, _ = await mcp.call_tool("capture_renderdoc_frame", {})
                return content[0].text

        result = asyncio.run(run())
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert "next_steps" in parsed
        assert "renderdoc-mcp" in parsed["next_steps"]

    def test_handles_error(self) -> None:
        import asyncio
        import json
        from unittest.mock import AsyncMock, patch

        from mcp.server.fastmcp import FastMCP

        from o3de_mcp.tools.introspection import register_introspection_tools

        error_json = json.dumps({"status": "error", "message": "RenderDoc not attached."})

        async def run() -> str:
            mcp = FastMCP("test")
            register_introspection_tools(mcp)
            with patch(
                "o3de_mcp.tools.editor._async_run_editor_script",
                new_callable=AsyncMock,
                return_value=error_json,
            ):
                content, _ = await mcp.call_tool("capture_renderdoc_frame", {})
                return content[0].text

        result = asyncio.run(run())
        parsed = json.loads(result)
        assert parsed["status"] == "error"
