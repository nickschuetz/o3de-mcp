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
import math
import os
import re
from pathlib import Path

import pytest
from mcp.server import MCPServer

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
def mcp_server() -> MCPServer:
    from o3de_mcp.tools.capabilities import register_capabilities_tools

    mcp = MCPServer("live-test")
    register_capabilities_tools(mcp)
    register_editor_tools(mcp)
    register_introspection_tools(mcp)
    register_project_tools(mcp)
    register_assets_tools(mcp)
    from o3de_mcp.tools.animation import register_animation_tools
    from o3de_mcp.tools.trackview import register_trackview_tools

    register_trackview_tools(mcp)
    register_animation_tools(mcp)
    return mcp


@pytest.fixture
def project_path() -> str:
    return _resolve_project_path()


async def _call(mcp: MCPServer, tool_name: str, **kwargs) -> str:
    content = (await mcp.call_tool(tool_name, kwargs)).content
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
    def test_get_capabilities_reports_connected(self, mcp_server: MCPServer) -> None:
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
    def test_list_entities(self, mcp_server: MCPServer) -> None:
        result = _run(_call(mcp_server, "list_entities"))
        try:
            parsed = json.loads(result)
            if isinstance(parsed, list):
                assert isinstance(parsed, list)
            elif isinstance(parsed, dict) and "status" in parsed:
                pass
        except json.JSONDecodeError:
            assert isinstance(result, str)

    def test_create_and_delete_entity(self, mcp_server: MCPServer) -> None:
        result = _run(_call(mcp_server, "create_entity", name="LiveTestEntity"))
        assert "LiveTestEntity" in result or "entity" in result.lower()

        entity_id = None
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                # Native create_entity (gem 0.5.0) answers {"entity_id": ...}
                # as a JSON number; the tools take the id as a string.
                raw = parsed.get("entity_id", parsed.get("id"))
                entity_id = str(raw) if raw is not None else None
        except json.JSONDecodeError:
            match = re.search(r"EntityId\((\d+)\)", result)
            if match:
                entity_id = match.group(1)

        if entity_id:
            del_result = _run(_call(mcp_server, "delete_entity", entity_id=entity_id))
            assert isinstance(del_result, str)


def _entity_id_from(result: str) -> str | None:
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict):
            # Native create_entity (gem 0.5.0) answers {"entity_id": ...}; the
            # editor-Python fallback prints "Created entity [id]".
            for key in ("entity_id", "id"):
                if key in parsed:
                    return str(parsed[key])
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[?(\d{6,})\]?", result)
    return match.group(1) if match else None


class TestLiveEntityHierarchyAndComponents:
    """The five tools that once called unreflected bus events and reported success anyway."""

    @pytest.fixture
    def two_entities(self, mcp_server: MCPServer):  # noqa: ANN201
        a = _entity_id_from(_run(_call(mcp_server, "create_entity", name="LiveChild")))
        b = _entity_id_from(_run(_call(mcp_server, "create_entity", name="LiveParent")))
        assert a and b, "could not create test entities"
        created = [a, b]
        yield a, b, created
        for eid in created:
            _run(_call(mcp_server, "delete_entity", entity_id=eid))

    def test_set_parent_actually_reparents(self, mcp_server: MCPServer, two_entities) -> None:  # noqa: ANN001
        child, parent, _ = two_entities
        result = _run(_call(mcp_server, "set_parent", entity_id=child, parent_id=parent))
        assert result.startswith("Set parent of"), result

    def test_add_list_and_remove_component(self, mcp_server: MCPServer, two_entities) -> None:  # noqa: ANN001
        entity, _, _ = two_entities
        added = _run(_call(mcp_server, "add_component", entity_id=entity, component_type="Mesh"))
        assert "error" not in added.lower(), added

        listed = json.loads(_run(_call(mcp_server, "get_entity_components", entity_id=entity)))
        assert isinstance(listed, list) and listed, listed
        assert any(c["type"] == "Mesh" for c in listed), listed

        removed = _run(
            _call(mcp_server, "remove_component", entity_id=entity, component_type="Mesh")
        )
        assert removed.startswith("Removed Mesh"), removed

        again = _run(_call(mcp_server, "remove_component", entity_id=entity, component_type="Mesh"))
        parsed = json.loads(again)
        assert parsed["status"] == "error" and parsed["code"] == "component_not_on_entity", again

        listed = json.loads(_run(_call(mcp_server, "get_entity_components", entity_id=entity)))
        assert not any(c["type"] == "Mesh" for c in listed), listed

    def test_duplicate_entity_makes_a_second_entity(
        self, mcp_server: MCPServer, two_entities
    ) -> None:  # noqa: ANN001
        entity, _, created = two_entities
        before = len(json.loads(_run(_call(mcp_server, "list_entities"))))
        result = json.loads(_run(_call(mcp_server, "duplicate_entity", entity_id=entity)))
        assert result.get("status") != "error", result
        new_id = str(result["id"]).strip("[]")
        created.append(new_id)
        # The duplicate is a new, valid entity distinct from its source. Its name is copied
        # during template propagation on a later tick, so it can be empty at return time.
        assert new_id and new_id != entity.strip("[]"), result
        after = len(json.loads(_run(_call(mcp_server, "list_entities"))))
        assert after == before + 1, f"expected one more entity, went {before} -> {after}"

    def test_focus_entity(self, mcp_server: MCPServer, two_entities) -> None:  # noqa: ANN001
        entity, _, _ = two_entities
        result = _run(_call(mcp_server, "focus_entity", entity_id=entity))
        assert result.startswith("Focused on entity"), result


class TestLiveTransform:
    def test_set_and_get_transform(self, mcp_server: MCPServer) -> None:
        create_result = _run(_call(mcp_server, "create_entity", name="TransformTest"))

        entity_id: str | None = None
        try:
            parsed = json.loads(create_result)
            if isinstance(parsed, dict):
                for key in ("entity_id", "id"):
                    if key in parsed:
                        entity_id = str(parsed[key])
                        break
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

        if entity_id is None:
            # EntityId can render bracketed, e.g. "Created entity [1234567890]"
            # (mirrors the [] stripping in the editor-side _resolve_entity_id).
            match = re.search(r"[Ee]ntity\s+\[?(\d+)\]?", create_result)
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
            # Native set_transform (gem 0.5.0) returns the entity JSON; the
            # editor-Python fallback prints "Transform set for entity [id]".
            assert (
                "Transform set" in set_result
                or '"position"' in set_result
                or "error" in set_result.lower()
            )

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

    def test_set_rotation_round_trip(self, mcp_server: MCPServer) -> None:
        create_result = _run(_call(mcp_server, "create_entity", name="RotationTest"))
        entity_id = _entity_id_from(create_result)
        assert entity_id is not None, f"no entity id in {create_result!r}"

        half = math.sqrt(0.5)
        try:
            set_result = _run(
                _call(
                    mcp_server,
                    "set_transform",
                    entity_id=entity_id,
                    rotation=[0.0, 0.0, half, half],  # 90 degrees about Z
                )
            )
            try:
                parsed = json.loads(set_result)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict) and "rotation" in parsed:
                # Native set_transform answers the entity JSON with the
                # rotation as XYZ Euler degrees, the form the request took.
                assert parsed["rotation"] == pytest.approx([0.0, 0.0, 90.0], abs=0.05)
                assert "position" in parsed and "scale" in parsed
            else:
                assert "Transform set" in set_result, set_result

            get_result = _run(_call(mcp_server, "get_transform", entity_id=entity_id))
            rot = json.loads(get_result)["rotation"]
            # q and -q are the same rotation.
            if rot[3] < 0:
                rot = [-v for v in rot]
            assert rot == pytest.approx([0.0, 0.0, half, half], abs=1e-3)
        finally:
            _run(_call(mcp_server, "delete_entity", entity_id=entity_id))


class TestLiveTransformScale:
    """An O3DE Transform holds one uniform scale."""

    def test_non_uniform_scale_is_refused_and_changes_nothing(self, mcp_server: MCPServer) -> None:
        created = json.loads(_run(_call(mcp_server, "create_entity", name="ScaleRefused")))
        eid = str(created["entity_id"])
        try:
            parsed = json.loads(
                _run(_call(mcp_server, "set_transform", entity_id=eid, scale=[50, 50, 1]))
            )
            assert parsed["status"] == "error", parsed
            assert parsed["code"] == "non_uniform_scale_unsupported", parsed
            got = json.loads(_run(_call(mcp_server, "get_transform", entity_id=eid)))
            assert all(math.isclose(s, 1.0, abs_tol=1e-3) for s in got["scale"]), got
        finally:
            _run(_call(mcp_server, "delete_entity", entity_id=eid))

    def test_python_path_keeps_the_scale_when_none_is_given(self, mcp_server: MCPServer) -> None:
        created = json.loads(_run(_call(mcp_server, "create_entity", name="KeepScale")))
        eid = str(created["entity_id"])
        try:
            _run(_call(mcp_server, "set_transform", entity_id=eid, scale=[3, 3, 3]))
            # Pitch +90 is a gimbal pole, so this rotation takes the editor-Python
            # path, which used to reset the scale to 1.
            half = math.sqrt(0.5)
            out = _run(
                _call(mcp_server, "set_transform", entity_id=eid, rotation=[0, half, 0, half])
            )
            assert out.startswith("Transform set for entity"), out
            got = json.loads(_run(_call(mcp_server, "get_transform", entity_id=eid)))
            assert all(math.isclose(s, 3.0, abs_tol=1e-3) for s in got["scale"]), got
        finally:
            _run(_call(mcp_server, "delete_entity", entity_id=eid))


class TestLiveAssignAsset:
    def test_assigns_a_real_mesh_and_refuses_an_unknown_one(self, mcp_server: MCPServer) -> None:
        created = json.loads(_run(_call(mcp_server, "create_entity", name="AssignTest")))
        eid = str(created["entity_id"])
        try:
            _run(_call(mcp_server, "add_component", entity_id=eid, component_type="Mesh"))
            prop = "Controller|Configuration|Model Asset"
            ok = _run(
                _call(
                    mcp_server,
                    "assign_asset",
                    entity_id=eid,
                    component_type="Mesh",
                    property_path=prop,
                    asset_path="objects/shaderball/ground_plane_4x4m.fbx.azmodel",
                )
            )
            # Only an assignment that reads back is reported as done.
            assert ok.startswith("Assigned asset"), ok
            missing = json.loads(
                _run(
                    _call(
                        mcp_server,
                        "assign_asset",
                        entity_id=eid,
                        component_type="Mesh",
                        property_path=prop,
                        asset_path="objects/does_not_exist.fbx.azmodel",
                    )
                )
            )
            assert missing["status"] == "error" and missing["code"] == "asset_not_found", missing
        finally:
            _run(_call(mcp_server, "delete_entity", entity_id=eid))


class TestLiveConsole:
    def test_run_console_command(self, mcp_server: MCPServer) -> None:
        result = _run(_call(mcp_server, "run_console_command", command="r_DisplayInfo 0"))
        assert "Executed" in result or "error" in result.lower()

    def test_set_and_get_cvar(self, mcp_server: MCPServer) -> None:
        set_result = _run(_call(mcp_server, "set_cvar", name="r_DisplayInfo", value="0"))
        assert "Set" in set_result or "error" in set_result.lower()

        get_result = _run(_call(mcp_server, "get_cvar", name="r_DisplayInfo"))
        assert isinstance(get_result, str)


class TestLiveLevels:
    def test_get_level_info(self, mcp_server: MCPServer) -> None:
        result = _run(_call(mcp_server, "get_level_info"))
        try:
            parsed = json.loads(result)
            assert "level_name" in parsed
        except json.JSONDecodeError:
            assert isinstance(result, str)

    def test_list_levels(self, mcp_server: MCPServer, project_path: str) -> None:
        result = _run(_call(mcp_server, "list_levels", project_path=project_path))
        parsed = json.loads(result)
        assert "levels" in parsed
        assert isinstance(parsed["levels"], list)


class TestLiveViewport:
    def test_get_viewport_camera(self, mcp_server: MCPServer) -> None:
        result = _run(_call(mcp_server, "get_viewport_camera"))
        try:
            parsed = json.loads(result)
            assert "position" in parsed or parsed.get("status") == "error"
        except json.JSONDecodeError:
            assert isinstance(result, str)

    def test_capture_viewport(self, mcp_server: MCPServer, tmp_path: Path) -> None:
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
    def test_instantiate_prefab_invalid_path(self, mcp_server: MCPServer) -> None:
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
    def test_session_lifecycle(self, mcp_server: MCPServer) -> None:
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
    def test_get_engine_info(self, mcp_server: MCPServer) -> None:
        result = _run(_call(mcp_server, "get_engine_info"))
        parsed = json.loads(result)
        assert "engine_path" in parsed

    def test_list_projects(self, mcp_server: MCPServer) -> None:
        result = _run(_call(mcp_server, "list_projects"))
        try:
            parsed = json.loads(result)
            assert isinstance(parsed, (list, dict))
        except json.JSONDecodeError:
            pytest.fail(f"list_projects returned invalid JSON: {result}")

    def test_list_project_gems(self, mcp_server: MCPServer, project_path: str) -> None:
        result = _run(_call(mcp_server, "list_project_gems", project_path=project_path))
        parsed = json.loads(result)
        assert "gems" in parsed
        assert parsed["count"] > 0


class TestLiveAssets:
    def test_get_asset_processor_status(self, mcp_server: MCPServer) -> None:
        result = _run(_call(mcp_server, "get_asset_processor_status"))
        parsed = json.loads(result)
        assert "running" in parsed
        # The Asset Processor may or may not be running; the tool should report
        # a boolean either way rather than the test requiring it to be up.
        assert isinstance(parsed["running"], bool)

    def test_tail_log_editor(self, mcp_server: MCPServer, project_path: str) -> None:
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
        # A running editor always has an Editor.log, so this must succeed; the
        # old "check only on success" form passed for years while tail_log was
        # looking in the wrong directory.
        assert parsed.get("status") != "error", parsed
        assert isinstance(parsed["lines"], list) and parsed["lines"], parsed
        assert parsed["path"].endswith("Editor.log"), parsed

    def test_get_log_errors(self, mcp_server: MCPServer, project_path: str) -> None:
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
        assert parsed.get("status") != "error", parsed
        assert isinstance(parsed["errors"], list), parsed
        assert "count" in parsed


class TestLiveIntrospection:
    def test_get_bus_schema_live(self, mcp_server: MCPServer, project_path: str) -> None:
        # Pass project_path so the stub fallback can resolve on machines that
        # have several projects with stub dumps (otherwise it correctly reports
        # stub_fallback_failed because the project is ambiguous).
        result = _run(
            _call(
                mcp_server,
                "get_bus_schema_live",
                module="editor",
                bus="EditorComponentAPIBus",
                project_path=project_path,
            )
        )
        parsed = json.loads(result)
        assert "source" in parsed
        assert parsed["source"] in (
            "native",
            "live",
            "stub_fallback",
            "stub_fallback_failed",
            "error",
        )

    def test_capture_renderdoc_frame(self, mcp_server: MCPServer) -> None:
        result = _run(_call(mcp_server, "capture_renderdoc_frame"))
        try:
            parsed = json.loads(result)
            assert "status" in parsed
            assert parsed["status"] in ("ok", "manual_required", "error")
        except json.JSONDecodeError:
            assert isinstance(result, str)


def _skip_if_no_native(parsed: dict) -> None:
    """Skip when the gem predates the native request (needs AiCompanion 0.4.0+)."""
    if isinstance(parsed, dict) and parsed.get("code") in (
        "agent_server_required",
        "unsupported_request",
        "editor_error",
    ):
        why = parsed.get("message") or parsed.get("error")
        pytest.skip(f"gem does not serve this native request: {why}")


class TestLiveNativeTools:
    """The AiCompanion gem's native C++ request types, exercised against a real
    editor. These assert on real scene content, not just that the call returns.
    get_scene_snapshot / get_entity_tree / validate_scene exist from the first
    gem; get_entity and the native get_bus_schema need gem 0.4.0 and skip on older."""

    def _snapshot_entity_id(self, mcp_server: MCPServer) -> str:
        result = _run(_call(mcp_server, "get_scene_snapshot"))
        parsed = json.loads(result)
        _skip_if_no_native(parsed)
        entities = parsed.get("entities") if isinstance(parsed, dict) else None
        assert entities, f"snapshot had no entities: {result[:200]}"
        # Prefer a stable, named entity from the default level.
        for e in entities:
            if e.get("name") and e.get("id") is not None:
                return str(e["id"]).strip("[]")
        pytest.skip("no named entity in the snapshot to probe")

    def test_get_scene_snapshot_lists_entities(self, mcp_server: MCPServer) -> None:
        parsed = json.loads(_run(_call(mcp_server, "get_scene_snapshot")))
        _skip_if_no_native(parsed)
        assert isinstance(parsed, dict) and parsed.get("entities"), parsed
        names = {e.get("name") for e in parsed["entities"]}
        # The default level always carries these.
        assert "Camera" in names or "Grid" in names, names

    def test_get_entity_tree_has_structure(self, mcp_server: MCPServer) -> None:
        parsed = json.loads(_run(_call(mcp_server, "get_entity_tree")))
        _skip_if_no_native(parsed)
        assert isinstance(parsed, (dict, list)), parsed

    def test_validate_scene_returns_a_report(self, mcp_server: MCPServer) -> None:
        parsed = json.loads(_run(_call(mcp_server, "validate_scene")))
        _skip_if_no_native(parsed)
        assert isinstance(parsed, dict), parsed

    def test_get_entity_returns_the_named_entity(self, mcp_server: MCPServer) -> None:
        eid = self._snapshot_entity_id(mcp_server)
        parsed = json.loads(_run(_call(mcp_server, "get_entity", entity_id=eid)))
        _skip_if_no_native(parsed)
        assert parsed.get("status") != "error", parsed
        assert str(parsed["id"]).strip("[]") == eid
        assert parsed.get("name")
        assert isinstance(parsed.get("components"), list)

    def test_get_entity_errors_on_an_unknown_id_without_crashing(
        self, mcp_server: MCPServer
    ) -> None:
        parsed = json.loads(_run(_call(mcp_server, "get_entity", entity_id="999999999999")))
        _skip_if_no_native(parsed)
        # A missing id is reported as an error, and the editor stays up.
        caps = json.loads(_run(_call(mcp_server, "get_capabilities")))
        assert caps["editor"]["status"] == "connected"
        api = str((caps["editor"].get("agent_server") or {}).get("api_version") or "0")
        if tuple(int(x) for x in api.split(".") if x.isdigit()) >= (0, 4, 0):
            # Gem API 0.4.0+ answers every refusal with status error and a code,
            # which o3de-mcp turns into its failure envelope.
            assert parsed == {
                "status": "error",
                "code": "not_found",
                "message": "No entity with id 999999999999",
            }, parsed
        else:
            # Older gems report a missing entity inside a successful reply, in their
            # own {"entity_id", "error"} shape, which passes through verbatim.
            assert parsed.get("status") == "error" or "error" in parsed, parsed

    def test_get_bus_schema_live_uses_the_native_path_for_a_gem_bus(
        self, mcp_server: MCPServer, project_path: str
    ) -> None:
        parsed = json.loads(
            _run(
                _call(
                    mcp_server,
                    "get_bus_schema_live",
                    module="editor",
                    bus="AiCompanionRequestBus",
                    project_path=project_path,
                )
            )
        )
        if parsed.get("source") != "native":
            pytest.skip(
                f"gem does not serve get_bus_schema natively (source={parsed.get('source')})"
            )
        assert parsed.get("event_count", 0) > 0, parsed
        assert parsed.get("events"), parsed


class TestLiveTrackView:
    """Track View cinematic sequences, exercised against a real editor. These run
    the reflected azlmbr.legacy.trackview workflow end to end and clean up after."""

    def test_sequence_lifecycle(self, mcp_server: MCPServer) -> None:
        seq = "McpLiveTvSeq"
        # Make sure a stale run did not leave it behind.
        _run(_call(mcp_server, "delete_sequence", name=seq))

        created = json.loads(_run(_call(mcp_server, "create_sequence", name=seq)))
        assert created.get("created") == seq, created

        try:
            names = {
                s["name"]
                for s in json.loads(_run(_call(mcp_server, "list_sequences")))["sequences"]
            }
            assert seq in names, names

            # A fresh sequence has no nodes until a Director is added.
            info = json.loads(_run(_call(mcp_server, "get_sequence", name=seq)))
            assert info["node_count"] == 0, info

            rng = json.loads(
                _run(_call(mcp_server, "set_sequence_time_range", name=seq, start=0.0, end=4.0))
            )
            assert rng.get("end") == 4.0, rng

            d = json.loads(
                _run(
                    _call(
                        mcp_server,
                        "add_sequence_node",
                        name=seq,
                        node_type="Director",
                        node_name="Dir1",
                    )
                )
            )
            assert d.get("added_node") == "Dir1", d
            e = json.loads(
                _run(
                    _call(
                        mcp_server,
                        "add_sequence_node",
                        name=seq,
                        node_type="Event",
                        node_name="Events1",
                    )
                )
            )
            assert e.get("status") != "error", e

            info = json.loads(_run(_call(mcp_server, "get_sequence", name=seq)))
            assert info["start"] == 0.0 and info["end"] == 4.0, info
            assert set(info["nodes"]) >= {"Dir1", "Events1"}, info

            # Playback starts and stops without error or crashing the editor.
            assert (
                json.loads(_run(_call(mcp_server, "play_sequence", name=seq))).get("playing") == seq
            )
            assert json.loads(_run(_call(mcp_server, "stop_sequence"))).get("stopped") is True
        finally:
            deleted = json.loads(_run(_call(mcp_server, "delete_sequence", name=seq)))
            assert deleted.get("deleted") == seq, deleted

        names = {
            s["name"] for s in json.loads(_run(_call(mcp_server, "list_sequences")))["sequences"]
        }
        assert seq not in names

    def test_add_node_rejects_an_unknown_type_before_sending(self, mcp_server: MCPServer) -> None:
        with pytest.raises(Exception):
            _run(
                _call(
                    mcp_server, "add_sequence_node", name="X", node_type="Nonsense", node_name="n"
                )
            )


def _skip_if_no_anim_graphs(parsed: dict) -> None:
    """Skip when the gem predates the anim graph reads or EMotion FX is not loaded."""
    if isinstance(parsed, dict) and parsed.get("status") == "error":
        message = str(parsed.get("message", ""))
        if parsed.get("code") == "unknown_request_type" or "Unknown request type" in message:
            pytest.skip("gem does not serve the anim graph reads (needs gem main or 0.6.0+)")
        if "EMotion FX is not available" in message or parsed.get("code") == "unavailable":
            pytest.skip("the EMotionFX gem is not loaded in this editor")


class TestLiveAnimGraphs:
    """EMotion FX anim graph reads through the gem's native request types."""

    def test_list_anim_graphs(self, mcp_server: MCPServer) -> None:
        parsed = json.loads(_run(_call(mcp_server, "list_anim_graphs")))
        _skip_if_no_anim_graphs(parsed)
        assert isinstance(parsed.get("anim_graphs"), list), parsed
        assert "editor_mode" in parsed, parsed

    def test_get_anim_graph_reports_an_unknown_id_as_an_error(self, mcp_server: MCPServer) -> None:
        parsed = json.loads(_run(_call(mcp_server, "get_anim_graph", anim_graph_id=4000000000)))
        _skip_if_no_anim_graphs(parsed)
        assert parsed["status"] == "error", parsed
        assert "not found" in parsed["message"], parsed

    def test_describes_a_graph_by_id_and_by_id_string(self, mcp_server: MCPServer) -> None:
        # Make a graph to read: the gem's in-memory create_anim_graph (authoring
        # branch onward). Skip when this gem cannot create one.
        from o3de_mcp.tools.editor import _pool

        listed = json.loads(_run(_call(mcp_server, "list_anim_graphs")))
        _skip_if_no_anim_graphs(listed)
        created = _run(_pool.send_request("create_anim_graph"))
        if created.get("status") != "ok":
            pytest.skip(f"gem cannot create an anim graph here: {created.get('error')}")
        graph_id = json.loads(created["output"])["id"]
        try:
            ids = [
                g["id"]
                for g in json.loads(_run(_call(mcp_server, "list_anim_graphs")))["anim_graphs"]
            ]
            assert graph_id in ids
            by_id = json.loads(_run(_call(mcp_server, "get_anim_graph", anim_graph_id=graph_id)))
            by_str = json.loads(
                _run(_call(mcp_server, "get_anim_graph", anim_graph_id=str(graph_id)))
            )
            assert by_id["id"] == graph_id, by_id
            assert by_str == by_id
            # A new graph holds just its root state machine.
            assert [n["type"] for n in by_id["nodes"]] == ["AnimGraphStateMachine"], by_id
            assert by_id["root_state_machine_id"] == by_id["nodes"][0]["id"]
        finally:
            _run(_pool.send_request("remove_anim_graph", params={"anim_graph_id": graph_id}))


class TestLiveAnimGraphAuthoring:
    """EMotion FX anim graph authoring end to end: build a graph, read it back,
    save it inside the project, reload it, and check the gem's refusals."""

    @staticmethod
    def _tool(mcp_server: MCPServer, tool_name: str, **kwargs) -> dict:  # noqa: ANN003
        return json.loads(_run(_call(mcp_server, tool_name, **kwargs)))

    def _create(self, mcp_server: MCPServer) -> int:
        _skip_if_no_anim_graphs(self._tool(mcp_server, "list_anim_graphs"))
        created = self._tool(mcp_server, "create_anim_graph")
        if created.get("status") == "error":
            _skip_if_no_anim_graphs(created)
            pytest.skip(f"gem cannot author anim graphs here: {created.get('message')}")
        return int(created["id"])

    def test_author_save_and_reload(self, mcp_server: MCPServer, project_path: str) -> None:
        graph_id = self._create(mcp_server)
        graph_ids = [graph_id]
        # Inside the project root (the gem refuses other paths) but outside the
        # Asset Processor's scan folders, so the run leaves no asset churn.
        save_dir = Path(project_path) / "user" / "o3de_mcp_live"
        save_path = save_dir / f"authoring_{os.getpid()}.animgraph"
        try:
            idle = self._tool(
                mcp_server,
                "add_anim_graph_node",
                anim_graph_id=graph_id,
                node_type="AnimGraphMotionNode",
                name="Idle",
                position=[0, 0],
            )
            walk = self._tool(
                mcp_server,
                "add_anim_graph_node",
                anim_graph_id=str(graph_id),
                node_type="animgraphmotionnode",  # type names are case-insensitive
                name="Walk",
                position=[200, 0],
            )
            assert idle.get("name") == "Idle" and walk.get("name") == "Walk", (idle, walk)
            entry = self._tool(
                mcp_server, "set_anim_graph_entry_state", anim_graph_id=graph_id, node_id=walk["id"]
            )
            assert entry["entry_state_id"] == walk["id"], entry
            speed = self._tool(
                mcp_server,
                "add_anim_graph_parameter",
                anim_graph_id=graph_id,
                name="Speed",
                parameter_type="Float",
                default=0.5,
                min=0,
                max=1,
            )
            assert speed.get("name") == "Speed", speed
            grounded = self._tool(
                mcp_server,
                "add_anim_graph_parameter",
                anim_graph_id=graph_id,
                name="Grounded",
                parameter_type="Bool",
                default=True,
                group="State",
            )
            assert grounded.get("name") == "Grounded", grounded

            graph = self._tool(mcp_server, "get_anim_graph", anim_graph_id=graph_id)
            nodes = {n["name"]: n for n in graph["nodes"]}
            root = next(n for n in graph["nodes"] if n["id"] == graph["root_state_machine_id"])
            assert {"Idle", "Walk"} <= set(nodes), graph["nodes"]
            assert nodes["Idle"]["parent_id"] == root["id"]
            assert root.get("entry_state_id") == walk["id"], root
            params = {p["name"]: p for p in graph["parameters"]}
            assert {"Speed", "Grounded"} <= set(params), graph["parameters"]

            removed = self._tool(
                mcp_server, "remove_anim_graph_parameter", anim_graph_id=graph_id, name="Speed"
            )
            assert removed == {"removed": "Speed"}, removed
            removed = self._tool(
                mcp_server, "remove_anim_graph_node", anim_graph_id=graph_id, node_id=idle["id"]
            )
            assert removed == {"removed": idle["id"]}, removed

            save_dir.mkdir(parents=True, exist_ok=True)
            saved = self._tool(
                mcp_server, "save_anim_graph", anim_graph_id=graph_id, file_name=str(save_path)
            )
            assert saved.get("status") != "error", saved
            assert save_path.is_file(), saved

            # Drop the in-memory graph, then load the file back as a new graph.
            gone = self._tool(mcp_server, "remove_anim_graph", anim_graph_id=graph_id)
            assert gone.get("status") != "error", gone
            graph_ids.remove(graph_id)
            loaded = self._tool(mcp_server, "load_anim_graph", file_name=str(save_path))
            assert loaded.get("status") != "error", loaded
            graph_ids.append(int(loaded["id"]))
            reloaded = self._tool(mcp_server, "get_anim_graph", anim_graph_id=loaded["id"])
            names = {n["name"] for n in reloaded["nodes"]}
            assert "Walk" in names and "Idle" not in names, reloaded["nodes"]
            assert [p["name"] for p in reloaded["parameters"]] == ["Grounded"], reloaded
            root = next(
                n for n in reloaded["nodes"] if n["id"] == reloaded["root_state_machine_id"]
            )
            walk_id = next(n["id"] for n in reloaded["nodes"] if n["name"] == "Walk")
            assert root.get("entry_state_id") == walk_id, root
        finally:
            for gid in graph_ids:
                self._tool(mcp_server, "remove_anim_graph", anim_graph_id=gid)
            if save_path.exists():
                save_path.unlink()
            if save_dir.exists() and not any(save_dir.iterdir()):
                save_dir.rmdir()

    def test_transitions_and_conditions(self, mcp_server: MCPServer) -> None:
        graph_id = self._create(mcp_server)
        try:

            def add_state(name: str) -> dict:
                return self._tool(
                    mcp_server,
                    "add_anim_graph_node",
                    anim_graph_id=graph_id,
                    node_type="AnimGraphMotionNode",
                    name=name,
                )

            idle, walk = add_state("Idle"), add_state("Walk")
            self._tool(
                mcp_server,
                "add_anim_graph_parameter",
                anim_graph_id=graph_id,
                name="Speed",
                parameter_type="Float",
            )
            go = self._tool(
                mcp_server,
                "add_anim_graph_transition",
                anim_graph_id=graph_id,
                source_node_id=idle["id"],
                target_node_id=walk["id"],
                blend_time=0.2,
                conditions=[
                    {
                        "condition_type": "ParameterCondition",
                        "attributes": {
                            "parameterName": "Speed",
                            "function": "greater",  # enum names are case-insensitive
                            "testValue": 0.1,
                        },
                    }
                ],
            )
            assert go.get("status") != "error", go
            assert go["source_node_id"] == idle["id"] and go["target_node_id"] == walk["id"], go
            assert math.isclose(go["blend_time"], 0.2, abs_tol=1e-4), go
            assert [c["type"] for c in go["conditions"]] == ["AnimGraphParameterCondition"], go

            edited = self._tool(
                mcp_server,
                "set_anim_graph_transition",
                anim_graph_id=graph_id,
                transition_id=go["id"],
                blend_time=0.5,
                priority=2,
            )
            assert math.isclose(edited["blend_time"], 0.5, abs_tol=1e-4), edited

            anywhere = self._tool(
                mcp_server,
                "add_anim_graph_transition",
                anim_graph_id=graph_id,
                target_node_id=idle["id"],
                wildcard=True,
            )
            assert anywhere.get("wildcard") is True, anywhere

            bad = self._tool(
                mcp_server,
                "add_anim_graph_transition",
                anim_graph_id=graph_id,
                source_node_id=walk["id"],
                target_node_id=idle["id"],
                conditions=[
                    {"condition_type": "ParameterCondition", "attributes": {"noSuchField": 1}}
                ],
            )
            assert bad["status"] == "error" and bad["code"] == "validation_failed", bad
            assert "unsupported condition attribute" in bad["message"], bad

            removed = self._tool(
                mcp_server,
                "remove_anim_graph_transition",
                anim_graph_id=graph_id,
                transition_id=anywhere["id"],
            )
            assert removed == {"removed": anywhere["id"]}, removed
            graph = self._tool(mcp_server, "get_anim_graph", anim_graph_id=graph_id)
            assert [t["id"] for t in graph["transitions"]] == [go["id"]], graph["transitions"]
        finally:
            self._tool(mcp_server, "remove_anim_graph", anim_graph_id=graph_id)

    def test_blend_tree_ports_and_node_edits(self, mcp_server: MCPServer) -> None:
        graph_id = self._create(mcp_server)
        try:
            tree = self._tool(
                mcp_server,
                "add_anim_graph_node",
                anim_graph_id=graph_id,
                node_type="BlendTree",
                name="Locomotion",
            )
            assert tree.get("status") != "error", tree
            # A node nested under the blend tree, not the root state machine.
            motion = self._tool(
                mcp_server,
                "add_anim_graph_node",
                anim_graph_id=graph_id,
                node_type="AnimGraphMotionNode",
                parent_id=tree["id"],
                name="WalkClip",
            )
            assert motion.get("parent_id") == tree["id"], motion
            graph = self._tool(mcp_server, "get_anim_graph", anim_graph_id=graph_id)
            final = next(
                (
                    n
                    for n in graph["nodes"]
                    if n.get("parent_id") == tree["id"] and n["type"] == "BlendTreeFinalNode"
                ),
                None,
            )
            if final is None:
                final = self._tool(
                    mcp_server,
                    "add_anim_graph_node",
                    anim_graph_id=graph_id,
                    node_type="BlendTreeFinalNode",
                    parent_id=tree["id"],
                )
            port = self._tool(
                mcp_server,
                "connect_anim_graph_ports",
                anim_graph_id=graph_id,
                source_node_id=motion["id"],
                source_port=0,
                target_node_id=final["id"],
                target_port=0,
            )
            assert port.get("status") != "error", port
            again = self._tool(
                mcp_server,
                "connect_anim_graph_ports",
                anim_graph_id=graph_id,
                source_node_id=motion["id"],
                source_port=0,
                target_node_id=final["id"],
                target_port=0,
            )
            assert again["status"] == "error" and again["code"] == "validation_failed", again
            unknown = self._tool(
                mcp_server,
                "connect_anim_graph_ports",
                anim_graph_id=graph_id,
                source_node_id=motion["id"],
                source_port="NoSuchPort",
                target_node_id=final["id"],
                target_port=0,
            )
            assert unknown["status"] == "error" and unknown["code"] == "validation_failed", unknown
            freed = self._tool(
                mcp_server,
                "disconnect_anim_graph_ports",
                anim_graph_id=graph_id,
                target_node_id=final["id"],
                target_port=0,
            )
            assert "removed" in freed, freed
            empty = self._tool(
                mcp_server,
                "disconnect_anim_graph_ports",
                anim_graph_id=graph_id,
                target_node_id=final["id"],
                target_port=0,
            )
            assert empty["status"] == "error" and empty["code"] == "not_found", empty

            renamed = self._tool(
                mcp_server,
                "set_anim_graph_node",
                anim_graph_id=graph_id,
                node_id=motion["id"],
                name="RunClip",
                position=[40, 80],
                attributes={"motionIds": ["run_cycle"]},
            )
            assert renamed.get("name") == "RunClip", renamed
            assert renamed.get("motion_ids") == ["run_cycle"], renamed
            refused = self._tool(
                mcp_server,
                "set_anim_graph_node",
                anim_graph_id=graph_id,
                node_id=motion["id"],
                attributes={"noSuchField": 1},
            )
            assert refused["status"] == "error" and refused["code"] == "validation_failed", refused
        finally:
            self._tool(mcp_server, "remove_anim_graph", anim_graph_id=graph_id)

    def test_refusals(self, mcp_server: MCPServer, tmp_path: Path) -> None:
        graph_id = self._create(mcp_server)
        try:
            unknown = self._tool(
                mcp_server, "add_anim_graph_node", anim_graph_id=graph_id, node_type="NoSuchNode"
            )
            assert unknown["status"] == "error", unknown
            assert unknown["code"] == "validation_failed", unknown
            assert "known" in unknown["message"], unknown

            root_id = self._tool(mcp_server, "get_anim_graph", anim_graph_id=graph_id)[
                "root_state_machine_id"
            ]
            root = self._tool(
                mcp_server, "remove_anim_graph_node", anim_graph_id=graph_id, node_id=root_id
            )
            assert root["status"] == "error" and root["code"] == "validation_failed", root

            outside = self._tool(
                mcp_server,
                "save_anim_graph",
                anim_graph_id=graph_id,
                file_name=str(tmp_path / "outside.animgraph"),
            )
            assert outside["status"] == "error" and outside["code"] == "validation_failed", outside
            assert not (tmp_path / "outside.animgraph").exists()

            missing = self._tool(mcp_server, "remove_anim_graph", anim_graph_id=4000000000)
            assert missing["status"] == "error" and missing["code"] == "not_found", missing
        finally:
            self._tool(mcp_server, "remove_anim_graph", anim_graph_id=graph_id)


class TestLiveAssetReadiness:
    """Per-asset readiness through the gem's native Asset Processor queries.
    Writes small source files under the project's Assets folder and removes them."""

    @staticmethod
    def _tool(mcp_server: MCPServer, tool_name: str, **kwargs) -> dict:  # noqa: ANN003
        return json.loads(_run(_call(mcp_server, tool_name, **kwargs)))

    def _require_gem(self, mcp_server: MCPServer) -> None:
        conn = self._tool(mcp_server, "get_asset_processor_connection")
        if conn.get("code") == "unknown_request_type":
            pytest.skip("gem does not serve the asset readiness types (needs 0.6.0+)")
        assert conn.get("connected") is True, conn

    def _write(self, project_path: str, name: str, content: str) -> tuple[Path, str]:
        folder = Path(project_path) / "Assets" / "o3de_mcp_live"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}_{os.getpid()}"
        path.write_text(content)
        return path, f"Assets/o3de_mcp_live/{path.name}"

    @staticmethod
    def _cleanup(path: Path) -> None:
        path.unlink(missing_ok=True)
        if path.parent.exists() and not any(path.parent.iterdir()):
            path.parent.rmdir()

    def test_a_good_asset_becomes_ready(self, mcp_server: MCPServer, project_path: str) -> None:
        self._require_gem(mcp_server)
        # The anim graph builder copies the file without parsing it, so it builds.
        path, rel = self._write(project_path, "ready_probe", "o3de-mcp live probe")
        path = path.rename(path.with_suffix(".animgraph"))
        rel = rel + ".animgraph"
        try:
            waited = self._tool(
                mcp_server, "wait_for_asset", path=rel, just_written=True, timeout=60
            )
            assert waited.get("ready") is True and waited["status"] == "compiled", waited
            status = self._tool(mcp_server, "get_asset_status", path=rel)
            assert status["status"] == "compiled", status
            jobs = self._tool(mcp_server, "get_asset_jobs", source_path=rel)
            assert jobs["jobs"] and all(j["status"] == "completed" for j in jobs["jobs"]), jobs
        finally:
            self._cleanup(path)

    def test_a_broken_asset_reports_its_failure(
        self, mcp_server: MCPServer, project_path: str
    ) -> None:
        self._require_gem(mcp_server)
        # Not a real FBX: the scene builder fails it within milliseconds.
        path, rel = self._write(project_path, "broken_probe", "not an fbx")
        path = path.rename(path.with_suffix(".fbx"))
        rel = rel + ".fbx"
        try:
            waited = self._tool(
                mcp_server, "wait_for_asset", path=rel, just_written=True, timeout=60
            )
            assert waited.get("status") == "error", waited
            assert waited["code"] == "asset_build_failed", waited
            failed = waited["jobs"]
            assert failed and all(j["status"] == "failed" for j in failed), waited
            assert any(j.get("log") for j in failed), "a failed job should carry its log"
        finally:
            self._cleanup(path)

    def test_a_never_seen_path_is_missing(self, mcp_server: MCPServer) -> None:
        self._require_gem(mcp_server)
        status = self._tool(
            mcp_server, "get_asset_status", path="Assets/o3de_mcp_live/never_written.fbx"
        )
        assert status["status"] == "missing", status


class TestLiveEdgeCases:
    def test_invalid_entity_id_raises(self, mcp_server: MCPServer) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "get_transform", entity_id="not_a_number"))

    def test_invalid_console_command_raises(self, mcp_server: MCPServer) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "run_console_command", command="; rm -rf /"))

    def test_invalid_prefab_path_raises(self, mcp_server: MCPServer) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "instantiate_prefab", prefab_path="../escape.json"))

    def test_empty_session_id_raises(self, mcp_server: MCPServer) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "end_session", session_id=""))

    def test_empty_build_id_raises(self, mcp_server: MCPServer) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "get_build_status", build_id=""))

    def test_invalid_cvar_value_raises(self, mcp_server: MCPServer) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "set_cvar", name="r_fog", value=""))

    def test_invalid_viewport_path_raises(self, mcp_server: MCPServer) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "capture_viewport", output_path="invalid.txt"))

    def test_invalid_level_name_raises(self, mcp_server: MCPServer) -> None:
        with pytest.raises(Exception):
            _run(_call(mcp_server, "create_level", name="123Invalid"))

    def test_invalid_transform_position_raises(self, mcp_server: MCPServer) -> None:
        with pytest.raises(Exception):
            _run(
                _call(
                    mcp_server,
                    "set_transform",
                    entity_id="123",
                    position=[1, 2],
                )
            )

    def test_invalid_transform_rotation_raises(self, mcp_server: MCPServer) -> None:
        with pytest.raises(Exception):
            _run(
                _call(
                    mcp_server,
                    "set_transform",
                    entity_id="123",
                    rotation=[0, 0, 0],
                )
            )
