# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Live integration tests for o3de-mcp tools that do NOT require the AiCompanion gem."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from o3de_mcp.tools.assets import register_assets_tools
from o3de_mcp.tools.capabilities import register_capabilities_tools
from o3de_mcp.tools.editor import register_editor_tools
from o3de_mcp.tools.introspection import register_introspection_tools
from o3de_mcp.tools.project import register_project_tools
from o3de_mcp.utils.o3de import find_o3de_engine_path, list_registered_projects


def _resolve_engine_path() -> str:
    engine = find_o3de_engine_path()
    if engine is None:
        pytest.skip("O3DE engine not found. Set O3DE_ENGINE_PATH or register the engine.")
    return str(engine)


def _resolve_project_path() -> str:
    env = os.environ.get("O3DE_PROJECT_PATH", "").strip()
    if env:
        return env
    projects = list_registered_projects()
    if projects:
        return projects[0]["path"]
    pytest.skip("No O3DE project found. Set O3DE_PROJECT_PATH or register a project.")


@pytest.fixture
def mcp_server() -> FastMCP:
    mcp = FastMCP("live-test")
    register_capabilities_tools(mcp)
    register_editor_tools(mcp)
    register_introspection_tools(mcp)
    register_project_tools(mcp)
    register_assets_tools(mcp)
    return mcp


@pytest.fixture
def engine_path() -> str:
    return _resolve_engine_path()


@pytest.fixture
def project_path() -> str:
    return _resolve_project_path()


@pytest.fixture
def o3de_root() -> str:
    return str(Path(_resolve_project_path()).parent.parent)


async def _call(mcp: FastMCP, tool_name: str, **kwargs) -> str:
    content, _ = await mcp.call_tool(tool_name, kwargs)
    return content[0].text


def _run(coro):
    return asyncio.run(coro)


def _editor_is_running() -> bool:
    """Check if the O3DE Editor is listening on the configured port."""
    editor_port = int(os.environ.get("O3DE_EDITOR_PORT", "4600"))
    import socket as _sock

    _s = _sock.socket()
    try:
        _s.settimeout(0.5)
        _s.connect(("127.0.0.1", editor_port))
        _s.close()
        return True
    except OSError:
        return False


# Marker: tests that require NO editor running. Skipped at collection time
# if the editor is detected on the configured port.
_editor_running = _editor_is_running()
requires_no_editor = pytest.mark.skipif(
    _editor_running,
    reason="O3DE Editor is running — this test verifies the no-editor failure path.",
)


class TestCapabilities:
    def test_all_tools_registered(self, mcp_server: FastMCP) -> None:
        async def _mock_probe(*a, **kw):
            from o3de_mcp.utils.capabilities import EditorStatus
            return EditorStatus.UNREACHABLE
        with patch("o3de_mcp.utils.capabilities.probe_editor_connection", side_effect=_mock_probe):
            result = _run(_call(mcp_server, "get_capabilities"))
        parsed = json.loads(result)
        cats = parsed["tool_categories"]

        total = sum(cat["tool_count"] for cat in cats.values())
        assert total == 63, f"Expected 63 tools, got {total}"

        assert cats["editor_tools"]["tool_count"] == 37
        assert cats["project_tools"]["tool_count"] == 17
        assert cats["asset_tools"]["tool_count"] == 5
        assert cats["introspection_tools"]["tool_count"] == 3
        assert cats["capabilities_tools"]["tool_count"] == 1

    def test_no_other_tools_category(self, mcp_server: FastMCP) -> None:
        async def _mock_probe(*a, **kw):
            from o3de_mcp.utils.capabilities import EditorStatus
            return EditorStatus.UNREACHABLE
        with patch("o3de_mcp.utils.capabilities.probe_editor_connection", side_effect=_mock_probe):
            result = _run(_call(mcp_server, "get_capabilities"))
        parsed = json.loads(result)
        cats = parsed["tool_categories"]
        assert "other_tools" not in cats, f"Uncategorized tools found: {cats.get('other_tools')}"

    def test_editor_status(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "get_capabilities"))
        parsed = json.loads(result)
        assert parsed["editor"]["status"] in ("unreachable", "connected")

    def test_cli_available(self, mcp_server: FastMCP) -> None:
        async def _mock_probe(*a, **kw):
            from o3de_mcp.utils.capabilities import EditorStatus
            return EditorStatus.UNREACHABLE
        with patch("o3de_mcp.utils.capabilities.probe_editor_connection", side_effect=_mock_probe):
            result = _run(_call(mcp_server, "get_capabilities"))
        parsed = json.loads(result)
        assert parsed["cli"]["available"] is True
        assert parsed["cli"]["engine_version"] is not None


class TestProjectTools:
    def test_get_engine_info(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "get_engine_info"))
        parsed = json.loads(result)
        assert "engine_path" in parsed
        assert "o3de" in parsed["engine_path"].lower()

    def test_list_projects(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "list_projects"))
        parsed = json.loads(result)
        if isinstance(parsed, list):
            assert len(parsed) > 0
        elif isinstance(parsed, dict) and "status" in parsed:
            pass

    def test_list_gems(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "list_gems"))
        try:
            parsed = json.loads(result)
            assert isinstance(parsed, (list, dict))
        except json.JSONDecodeError:
            pytest.fail(f"list_gems returned invalid JSON: {result}")

    def test_list_project_gems(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(_call(mcp_server, "list_project_gems", project_path=project_path))
        parsed = json.loads(result)
        assert "gems" in parsed
        assert parsed["count"] > 0

    def test_list_templates(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "list_templates"))
        try:
            parsed = json.loads(result)
            if isinstance(parsed, list):
                names = [t.get("template_name", "") for t in parsed]
                assert len(names) > 0
                assert any("Default" in n for n in names)
        except json.JSONDecodeError:
            pass

    def test_set_active_engine(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "set_active_engine", name="o3de"))
        assert "o3de" in result

    def test_get_build_status_not_found(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "get_build_status", build_id="fake123"))
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["code"] == "not_found"


class TestAssetTools:
    def test_asset_processor_running(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(_call(mcp_server, "get_asset_processor_status", project_path=project_path))
        parsed = json.loads(result)
        if parsed["running"]:
            assert parsed["log_dir"] is not None
        else:
            pytest.skip("Asset Processor is not running")

    def test_tail_log_editor(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(
            _call(mcp_server, "tail_log", log_name="Editor", lines=10, project_path=project_path)
        )
        parsed = json.loads(result)
        if "error" not in parsed:
            assert "lines" in parsed
            assert isinstance(parsed["lines"], list)
            assert len(parsed["lines"]) <= 10

    def test_tail_log_asset_processor(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(
            _call(
                mcp_server,
                "tail_log",
                log_name="AssetProcessor",
                lines=5,
                project_path=project_path,
            )
        )
        parsed = json.loads(result)
        if "error" not in parsed:
            assert "lines" in parsed

    def test_tail_log_with_filter(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(
            _call(
                mcp_server,
                "tail_log",
                log_name="Editor",
                lines=50,
                filter="INFO|WARNING|ERROR",
                project_path=project_path,
            )
        )
        parsed = json.loads(result)
        if "error" not in parsed:
            for line in parsed["lines"]:
                assert re.search(r"INFO|WARNING|ERROR", line, re.IGNORECASE) or line == ""

    def test_get_log_errors(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(
            _call(
                mcp_server,
                "get_log_errors",
                log_name="Editor",
                since_lines=500,
                project_path=project_path,
            )
        )
        parsed = json.loads(result)
        if "error" not in parsed:
            assert "errors" in parsed
            assert "count" in parsed
            assert isinstance(parsed["errors"], list)

    def test_tail_log_rejects_path_traversal(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(
            _call(mcp_server, "tail_log", log_name="../etc/passwd", project_path=project_path)
        )
        parsed = json.loads(result)
        assert "error" in parsed

    def test_tail_log_nonexistent_log(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(
            _call(mcp_server, "tail_log", log_name="NonExistentLog", project_path=project_path)
        )
        parsed = json.loads(result)
        assert "error" in parsed


class TestIntrospectionTools:
    def test_get_bus_schema_lists_modules(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(_call(mcp_server, "get_bus_schema", project_path=project_path))
        try:
            parsed = json.loads(result)
            if "modules" in parsed:
                assert isinstance(parsed["modules"], list)
            elif "error" in parsed:
                pass
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {result}")

    @requires_no_editor
    def test_capture_renderdoc_frame_returns_error(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "capture_renderdoc_frame"))
        assert isinstance(result, str)
        try:
            parsed = json.loads(result)
            assert "status" in parsed
        except json.JSONDecodeError:
            assert "error" in result.lower() or "unreachable" in result.lower()


class TestEditorToolsGracefulFailure:
    @requires_no_editor
    def test_list_entities_returns_error(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "list_entities"))
        assert isinstance(result, str)
        try:
            parsed = json.loads(result)
            assert parsed.get("status") == "error"
        except json.JSONDecodeError:
            assert "error" in result.lower() or "unreachable" in result.lower()

    @requires_no_editor
    def test_run_editor_python_returns_error(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "run_editor_python", script="print('hello')"))
        assert isinstance(result, str)
        try:
            parsed = json.loads(result)
            assert parsed.get("status") == "error"
        except json.JSONDecodeError:
            assert "error" in result.lower() or "unreachable" in result.lower()

    @requires_no_editor
    def test_get_transform_returns_error(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "get_transform", entity_id="123"))
        assert isinstance(result, str)
        try:
            parsed = json.loads(result)
            assert parsed.get("status") == "error"
        except json.JSONDecodeError:
            pass

    @requires_no_editor
    def test_run_console_command_returns_error(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "run_console_command", command="r_displayInfo 0"))
        assert isinstance(result, str)
        try:
            parsed = json.loads(result)
            assert parsed.get("status") == "error"
        except json.JSONDecodeError:
            pass

    @requires_no_editor
    def test_capture_viewport_returns_error(self, mcp_server: FastMCP, tmp_path: Path) -> None:
        result = _run(_call(mcp_server, "capture_viewport", output_path=str(tmp_path / "test.png")))
        assert isinstance(result, str)
        try:
            parsed = json.loads(result)
            assert parsed.get("status") == "error"
        except json.JSONDecodeError:
            pass

    @requires_no_editor
    def test_begin_session_returns_error(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "begin_session"))
        assert isinstance(result, str)
        try:
            parsed = json.loads(result)
            assert parsed.get("status") == "error"
        except json.JSONDecodeError:
            pass


class TestEdgeCases:
    def test_invalid_entity_id(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "get_transform", entity_id="not_a_number"))

    def test_empty_entity_id(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "get_transform", entity_id=""))

    def test_invalid_component_type(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(
                _call(
                    mcp_server,
                    "remove_component",
                    entity_id="123",
                    component_type="Bad'; DROP",
                )
            )

    def test_console_command_shell_injection(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "run_console_command", command="; rm -rf /"))

    def test_console_command_pipe(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "run_console_command", command="r_fog | cat"))

    def test_console_command_empty(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "run_console_command", command=""))

    def test_cvar_empty_name(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "get_cvar", name=""))

    def test_cvar_empty_value(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "set_cvar", name="r_fog", value=""))

    def test_prefab_wrong_extension(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "instantiate_prefab", prefab_path="test.json"))

    def test_prefab_path_traversal(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "instantiate_prefab", prefab_path="../escape.prefab"))

    def test_prefab_empty_path(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "instantiate_prefab", prefab_path=""))

    def test_transform_wrong_position_length(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "set_transform", entity_id="123", position=[1, 2]))

    def test_transform_wrong_rotation_length(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "set_transform", entity_id="123", rotation=[0, 0, 0]))

    def test_transform_non_numeric_position(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "set_transform", entity_id="123", position=["a", "b", "c"]))

    def test_transform_position_not_a_list(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(
                _call(mcp_server, "set_transform", entity_id="123", position=42)  # type: ignore[arg-type]
            )

    def test_viewport_invalid_extension(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "capture_viewport", output_path="test.txt"))

    def test_viewport_empty_path(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "capture_viewport", output_path=""))

    def test_level_invalid_name_starts_with_number(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "create_level", name="123Level"))

    def test_level_invalid_name_with_spaces(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "create_level", name="My Level"))

    def test_level_empty_name(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "create_level", name=""))

    def test_session_empty_id(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "end_session", session_id=""))

    def test_session_empty_script(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "exec_in_session", session_id="abc", script=""))

    def test_build_empty_id(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "get_build_status", build_id=""))

    def test_build_invalid_config(self, mcp_server: FastMCP, tmp_path: Path) -> None:
        build_dir = tmp_path / "build" / "windows"
        build_dir.mkdir(parents=True)
        result = _run(
            _call(
                mcp_server,
                "start_build",
                project_path=str(tmp_path),
                config="invalid_config",
            )
        )
        parsed = json.loads(result)
        assert parsed["status"] == "error"

    def test_asset_path_traversal(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(
                _call(
                    mcp_server,
                    "assign_asset",
                    entity_id="123",
                    component_type="Mesh",
                    property_path="Controller|Configuration|Model Asset",
                    asset_path="../escape.fbx",
                )
            )

    def test_asset_empty_path(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(
                _call(
                    mcp_server,
                    "assign_asset",
                    entity_id="123",
                    component_type="Mesh",
                    property_path="Controller|Configuration|Model Asset",
                    asset_path="",
                )
            )

    def test_project_name_invalid(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "set_active_engine", name="123Invalid"))


class TestAllToolsCallable:
    # Tools with real side effects (create/modify projects, gems, builds)
    # are excluded from the smoke test — calling them would create real
    # directories and run the O3DE CLI on the user's machine.
    _SKIP_TOOLS = frozenset(
        {
            "create_project",
            "create_gem",
            "export_project",
            "build_project",
            "register_gem",
            "enable_gem",
            "disable_gem",
            "register_engine",
            "start_build",
            "edit_project_properties",
        }
    )

    def _safe_calls(self, engine_path: str, project_path: str, o3de_root: str, tmp: Path) -> dict:
        return {
            "get_capabilities": {},
            "get_engine_info": {},
            "list_projects": {},
            "list_gems": {},
            "list_templates": {},
            "list_project_gems": {"project_path": project_path},
            "get_asset_processor_status": {"project_path": project_path},
            "tail_log": {"log_name": "Editor", "project_path": project_path, "lines": 5},
            "get_log_errors": {"log_name": "Editor", "project_path": project_path},
            "get_bus_schema": {"project_path": project_path},
            "capture_renderdoc_frame": {},
            "list_entities": {},
            "get_level_info": {},
            "get_viewport_camera": {},
            "begin_session": {},
            "run_editor_python": {"script": "print('test')"},
            "get_transform": {"entity_id": "123"},
            "set_transform": {"entity_id": "123", "position": [1, 2, 3]},
            "set_parent": {"entity_id": "123", "parent_id": "456"},
            "remove_component": {"entity_id": "123", "component_type": "Mesh"},
            "run_console_command": {"command": "r_displayInfo 0"},
            "get_cvar": {"name": "r_fog"},
            "set_cvar": {"name": "r_fog", "value": "0"},
            "create_level": {"name": "TestLevel"},
            "list_levels": {"project_path": project_path},
            "set_viewport_camera": {"position": [0, 0, 0]},
            "focus_entity": {"entity_id": "123"},
            "capture_viewport": {"output_path": str(tmp / "test_screenshot.png")},
            "instantiate_prefab": {"prefab_path": "Prefabs/test.prefab"},
            "create_prefab_from_entity": {
                "entity_id": "123",
                "prefab_path": "Prefabs/test.prefab",
            },
            "save_prefab": {"entity_id": "123"},
            "exec_in_session": {"session_id": "test", "script": "x = 1"},
            "end_session": {"session_id": "test"},
            "get_session_vars": {"session_id": "test"},
            "assign_asset": {
                "entity_id": "123",
                "component_type": "Mesh",
                "property_path": "Controller|Configuration|Model Asset",
                "asset_path": "Objects/test.fbx",
            },
            "set_active_engine": {"name": "o3de"},
            "get_build_status": {"build_id": "nonexistent"},
            "get_bus_schema_live": {"module": "editor", "bus": "EditorComponentAPIBus"},
            "create_entity": {"name": "TestEntity"},
            "delete_entity": {"entity_id": "123"},
            "duplicate_entity": {"entity_id": "123"},
            "get_entity_components": {"entity_id": "123"},
            "add_component": {"entity_id": "123", "component_type": "Mesh"},
            "get_component_property": {
                "entity_id": "123",
                "component_type": "Mesh",
                "property_path": "Controller|Configuration|Model Asset",
            },
            "set_component_property": {
                "entity_id": "123",
                "component_type": "Mesh",
                "property_path": "Controller|Configuration|Model Asset",
                "value": "0",
            },
            "load_level": {"level_path": "Levels/Test"},
            "save_level": {},
            "enter_game_mode": {},
            "exit_game_mode": {},
            "undo": {},
            "redo": {},
            "wait_for_assets": {"timeout": 1},
            "refresh_assets": {"project_path": project_path},
        }

    def test_all_tools_callable(
        self,
        mcp_server: FastMCP,
        engine_path: str,
        project_path: str,
        o3de_root: str,
        tmp_path: Path,
    ) -> None:
        safe_calls = self._safe_calls(engine_path, project_path, o3de_root, tmp_path)
        tools = mcp_server._tool_manager.list_tools()
        tool_names = [t.name for t in tools]

        successes = []
        validation_errors = []
        crashes = []
        skipped = []

        async def _mock_probe(*a, **kw):
            from o3de_mcp.utils.capabilities import EditorStatus
            return EditorStatus.UNREACHABLE

        async def _mock_send_script(*a, **kw):
            return (
                '{"status": "error", "code": "connection_refused", '
                '"message": "Editor not running"}'
            )

        for tool_name in tool_names:
            if tool_name in self._SKIP_TOOLS:
                skipped.append(tool_name)
                continue
            kwargs = safe_calls.get(tool_name, {})
            try:
                with patch(
                    "o3de_mcp.utils.capabilities.probe_editor_connection",
                    side_effect=_mock_probe,
                ):
                    with patch(
                        "o3de_mcp.tools.editor._pool.send_script",
                        new_callable=AsyncMock,
                        side_effect=_mock_send_script,
                    ):
                        result = _run(_call(mcp_server, tool_name, **kwargs))
                assert result is not None, f"{tool_name} returned None"
                assert isinstance(result, str), f"{tool_name} returned {type(result)}"
                successes.append(tool_name)
            except Exception as e:
                err_str = str(e)
                if (
                    "ValueError" in type(e).__name__
                    or "ValidationError" in type(e).__name__
                    or "ToolError" in type(e).__name__
                    or "missing" in err_str.lower()
                    or "field required" in err_str.lower()
                ):
                    validation_errors.append(f"{tool_name}: {type(e).__name__}")
                else:
                    crashes.append(f"{tool_name}: {type(e).__name__}: {e}")

        print(f"\n  Successes ({len(successes)}): {', '.join(sorted(successes))}")
        print(
            f"  Validation errors ({len(validation_errors)}): "
            f"{', '.join(sorted(validation_errors))}"
        )
        print(f"  Skipped side-effect tools ({len(skipped)}): {', '.join(sorted(skipped))}")
        if crashes:
            print(f"  Crashes ({len(crashes)}): {chr(10).join(crashes)}")

        assert not crashes, "Tools crashed unexpectedly:\n" + "\n".join(crashes)
        assert len(successes) >= 40, (
            f"Only {len(successes)} tools succeeded. Validation errors: {validation_errors}"
        )

    def test_tool_count_matches(self, mcp_server: FastMCP) -> None:
        tools = mcp_server._tool_manager.list_tools()
        assert len(tools) == 63, f"Expected 63 tools, got {len(tools)}: {[t.name for t in tools]}"
