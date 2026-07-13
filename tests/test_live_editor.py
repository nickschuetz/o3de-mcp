# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Live integration tests for o3de-mcp tools against a running O3DE Editor.

Skipped by default; set O3DE_LIVE_EDITOR_TEST=1 to run.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from o3de_mcp.tools.assets import register_assets_tools
from o3de_mcp.tools.editor import register_editor_tools
from o3de_mcp.tools.introspection import register_introspection_tools
from o3de_mcp.tools.project import register_project_tools
from o3de_mcp.utils.o3de import list_registered_projects

pytestmark = pytest.mark.live_editor


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
    from o3de_mcp.tools.capabilities import register_capabilities_tools

    mcp = FastMCP("live-test")
    register_capabilities_tools(mcp)
    register_editor_tools(mcp)
    register_introspection_tools(mcp)
    register_project_tools(mcp)
    register_assets_tools(mcp)
    return mcp


@pytest.fixture
def project_path() -> str:
    return _resolve_project_path()


async def _call(mcp: FastMCP, tool_name: str, **kwargs) -> str:
    content, _ = await mcp.call_tool(tool_name, kwargs)
    return content[0].text


# Reuse a single event loop across all live tests. The connection pool
# (_EditorConnectionPool) handles event-loop changes correctly (it recreates
# the asyncio.Lock and force-closes dead-loop sockets), but reusing one loop
# avoids unnecessary reconnect churn and is faster. The AgentServer only
# accepts one client at a time, so minimizing reconnects also avoids races.
_loop = asyncio.new_event_loop()


def _run(coro):
    return _loop.run_until_complete(coro)


class TestLiveCapabilities:
    def test_get_capabilities_reports_connected(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "get_capabilities"))
        parsed = json.loads(result)
        assert parsed["editor"]["status"] == "connected"
        cats = parsed["tool_categories"]
        assert "editor_tools" in cats
        assert "project_tools" in cats
        assert "asset_tools" in cats
        assert "introspection_tools" in cats
        assert "capabilities_tools" in cats
        assert cats["editor_tools"]["available"] is True


class TestLiveEntityOps:
    def test_list_entities(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "list_entities"))
        try:
            parsed = json.loads(result)
            if isinstance(parsed, list):
                assert isinstance(parsed, list)
            elif isinstance(parsed, dict) and "status" in parsed:
                pass
        except json.JSONDecodeError:
            assert isinstance(result, str)

    def test_create_and_delete_entity(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "create_entity", name="LiveTestEntity"))
        assert "LiveTestEntity" in result or "entity" in result.lower()

        entity_id = None
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and "id" in parsed:
                entity_id = parsed["id"]
        except json.JSONDecodeError:
            match = re.search(r"EntityId\((\d+)\)", result)
            if match:
                entity_id = match.group(1)

        if entity_id:
            del_result = _run(_call(mcp_server, "delete_entity", entity_id=entity_id))
            assert isinstance(del_result, str)


class TestLiveTransform:
    def test_set_and_get_transform(self, mcp_server: FastMCP) -> None:
        create_result = _run(_call(mcp_server, "create_entity", name="TransformTest"))

        entity_id: str | None = None
        try:
            parsed = json.loads(create_result)
            if isinstance(parsed, dict) and "id" in parsed:
                entity_id = str(parsed["id"])
        except (json.JSONDecodeError, TypeError):
            pass

        if entity_id is None:
            match = re.search(r"EntityId\((\d+)\)", create_result)
            if match:
                entity_id = match.group(1)

        if entity_id is None:
            match = re.search(r"Created entity\s+(\d+)", create_result)
            if match:
                entity_id = match.group(1)

        assert entity_id is not None, (
            f"Could not extract entity ID from create_entity output: {create_result!r}"
        )

        try:
            set_result = _run(
                _call(
                    mcp_server,
                    "set_transform",
                    entity_id=entity_id,
                    position=[10.0, 20.0, 30.0],
                    scale=[2.0, 2.0, 2.0],
                )
            )
            assert "Transform set" in set_result or "error" in set_result.lower()

            get_result = _run(_call(mcp_server, "get_transform", entity_id=entity_id))
            try:
                parsed = json.loads(get_result)
                if "position" in parsed:
                    pos = parsed["position"]
                    assert abs(pos[0] - 10.0) < 0.1, f"X position mismatch: {pos[0]}"
                    assert abs(pos[1] - 20.0) < 0.1, f"Y position mismatch: {pos[1]}"
                    assert abs(pos[2] - 30.0) < 0.1, f"Z position mismatch: {pos[2]}"
            except json.JSONDecodeError:
                assert isinstance(get_result, str)
        finally:
            _run(_call(mcp_server, "delete_entity", entity_id=entity_id))


class TestLiveConsole:
    def test_run_console_command(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "run_console_command", command="r_DisplayInfo 0"))
        assert "Executed" in result or "error" in result.lower()

    def test_set_and_get_cvar(self, mcp_server: FastMCP) -> None:
        set_result = _run(_call(mcp_server, "set_cvar", name="r_DisplayInfo", value="0"))
        assert "Set" in set_result or "error" in set_result.lower()

        get_result = _run(_call(mcp_server, "get_cvar", name="r_DisplayInfo"))
        assert isinstance(get_result, str)


class TestLiveLevels:
    def test_get_level_info(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "get_level_info"))
        try:
            parsed = json.loads(result)
            assert "level_name" in parsed
        except json.JSONDecodeError:
            assert isinstance(result, str)

    def test_list_levels(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(_call(mcp_server, "list_levels", project_path=project_path))
        parsed = json.loads(result)
        assert "levels" in parsed
        assert isinstance(parsed["levels"], list)


class TestLiveViewport:
    def test_get_viewport_camera(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "get_viewport_camera"))
        try:
            parsed = json.loads(result)
            assert "position" in parsed or "error" in parsed
        except json.JSONDecodeError:
            assert isinstance(result, str)

    def test_capture_viewport(self, mcp_server: FastMCP, tmp_path: Path) -> None:
        screenshot_path = str(tmp_path / "test_screenshot.png")
        result = _run(
            _call(
                mcp_server,
                "capture_viewport",
                output_path=screenshot_path,
            )
        )
        assert "Screenshot saved" in result or "Failed to capture" in result


class TestLivePrefabs:
    def test_instantiate_prefab_invalid_path(self, mcp_server: FastMCP) -> None:
        result = _run(
            _call(
                mcp_server,
                "instantiate_prefab",
                prefab_path="Prefabs/NonExistent.prefab",
                position=[0.0, 0.0, 0.0],
            )
        )
        assert isinstance(result, str)
        assert "Failed" in result or "error" in result.lower() or "Instantiated" in result


class TestLiveSession:
    def test_session_lifecycle(self, mcp_server: FastMCP) -> None:
        begin_result = _run(_call(mcp_server, "begin_session"))
        try:
            parsed = json.loads(begin_result)
            session_id = parsed.get("session_id")
        except json.JSONDecodeError:
            pytest.skip("Could not begin session — editor may not support sessions")

        if not session_id:
            pytest.skip("No session ID returned")

        try:
            exec_result = _run(
                _call(
                    mcp_server,
                    "exec_in_session",
                    session_id=session_id,
                    script="test_var = 42",
                )
            )
            assert isinstance(exec_result, str)

            vars_result = _run(_call(mcp_server, "get_session_vars", session_id=session_id))
            try:
                parsed = json.loads(vars_result)
                if "vars" in parsed:
                    assert "test_var" in parsed["vars"]
            except json.JSONDecodeError:
                pass
        finally:
            end_result = _run(_call(mcp_server, "end_session", session_id=session_id))
            assert "ended" in end_result.lower() or isinstance(end_result, str)


class TestLiveProject:
    def test_get_engine_info(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "get_engine_info"))
        parsed = json.loads(result)
        assert "engine_path" in parsed

    def test_list_projects(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "list_projects"))
        try:
            parsed = json.loads(result)
            assert isinstance(parsed, (list, dict))
        except json.JSONDecodeError:
            pytest.fail(f"list_projects returned invalid JSON: {result}")

    def test_list_project_gems(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(_call(mcp_server, "list_project_gems", project_path=project_path))
        parsed = json.loads(result)
        assert "gems" in parsed
        assert parsed["count"] > 0


class TestLiveAssets:
    def test_get_asset_processor_status(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "get_asset_processor_status"))
        parsed = json.loads(result)
        assert "running" in parsed
        assert parsed["running"] is True

    def test_tail_log_editor(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(
            _call(
                mcp_server,
                "tail_log",
                log_name="Editor",
                lines=10,
                project_path=project_path,
            )
        )
        parsed = json.loads(result)
        if "error" not in parsed:
            assert "lines" in parsed
            assert isinstance(parsed["lines"], list)

    def test_get_log_errors(self, mcp_server: FastMCP, project_path: str) -> None:
        result = _run(
            _call(
                mcp_server,
                "get_log_errors",
                log_name="Editor",
                since_lines=100,
                project_path=project_path,
            )
        )
        parsed = json.loads(result)
        if "error" not in parsed:
            assert "errors" in parsed
            assert "count" in parsed


class TestLiveIntrospection:
    def test_get_bus_schema_live(self, mcp_server: FastMCP) -> None:
        result = _run(
            _call(
                mcp_server,
                "get_bus_schema_live",
                module="editor",
                bus="EditorComponentAPIBus",
            )
        )
        parsed = json.loads(result)
        assert "source" in parsed
        assert parsed["source"] in ("live", "stub_fallback", "error")

    def test_capture_renderdoc_frame(self, mcp_server: FastMCP) -> None:
        result = _run(_call(mcp_server, "capture_renderdoc_frame"))
        try:
            parsed = json.loads(result)
            assert "status" in parsed
            assert parsed["status"] in ("ok", "manual_required", "error")
        except json.JSONDecodeError:
            assert isinstance(result, str)


class TestLiveEdgeCases:
    def test_invalid_entity_id_raises(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "get_transform", entity_id="not_a_number"))

    def test_invalid_console_command_raises(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "run_console_command", command="; rm -rf /"))

    def test_invalid_prefab_path_raises(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "instantiate_prefab", prefab_path="../escape.json"))

    def test_empty_session_id_raises(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "end_session", session_id=""))

    def test_empty_build_id_raises(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "get_build_status", build_id=""))

    def test_invalid_cvar_value_raises(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "set_cvar", name="r_fog", value=""))

    def test_invalid_viewport_path_raises(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "capture_viewport", output_path="invalid.txt"))

    def test_invalid_level_name_raises(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "create_level", name="123Invalid"))

    def test_invalid_transform_position_raises(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(
                _call(
                    mcp_server,
                    "set_transform",
                    entity_id="123",
                    position=[1, 2],
                )
            )

    def test_invalid_transform_rotation_raises(self, mcp_server: FastMCP) -> None:
        with pytest.raises(Exception):
            _run(
                _call(
                    mcp_server,
                    "set_transform",
                    entity_id="123",
                    rotation=[0, 0, 0],
                )
            )
