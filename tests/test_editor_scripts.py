# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Run every editor tool's generated script against the editor's real ``azlmbr`` surface.

The mocked tests in ``test_editor.py`` feed a canned string back through the connection
pool, so they cannot tell whether the Python a tool sends to the editor calls anything
that exists. ``save_prefab`` called a bus event that no O3DE version reflects and passed
those tests for months.

This module closes that gap without an editor. ``tests/data/azlmbr_surface.json`` is
extracted from the stub dump the editor writes to ``<project>/user/python_symbols``
(see ``scripts/extract-azlmbr-surface.py``). A stub ``azlmbr`` package is built from it
in which every bus checks the event name and call type against that surface, and every
module refuses attributes the editor does not reflect. Each tool's script is then
generated with representative arguments and executed against the stubs.

What this catches: nonexistent bus events, ``Broadcast`` used where the bus is
addressed (``Event``) or the reverse, functions and classes that do not exist, and
scripts that raise before reaching the editor API. What it does not catch: wrong
argument values, wrong return handling, or anything that needs a real level.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server import MCPServer

from o3de_mcp.tools.editor import register_editor_tools
from o3de_mcp.tools.introspection import register_introspection_tools
from o3de_mcp.tools.trackview import register_trackview_tools

SURFACE_PATH = Path(__file__).parent / "data" / "azlmbr_surface.json"


class SurfaceViolation(BaseException):
    """The script touched something the editor does not reflect.

    Derives from ``BaseException`` on purpose: most generated scripts wrap their bus
    calls in ``try/except Exception`` and print a failure message, which would hide
    the violation behind a passing test.
    """


class Anything(dict):
    """Permissive stand-in for whatever a real bus call or constructor returns.

    A ``dict`` subclass so ``json.dumps`` accepts it and iteration is empty; overrides
    make it truthy, numeric and string-like so the surrounding script keeps running.
    """

    def __getattr__(self, name: str) -> Anything:
        if name.startswith("__"):
            raise AttributeError(name)
        return Anything()

    def __call__(self, *args: object, **kwargs: object) -> Anything:
        return Anything()

    def __getitem__(self, key: object) -> Anything:
        return Anything()

    def __bool__(self) -> bool:
        return True

    def __int__(self) -> int:
        return 123

    def __index__(self) -> int:
        # A reflected count (e.g. get_num_sequences) returns this; 1 lets a
        # ``range(count)`` loop run once so the loop body is validated too.
        return 1

    def __float__(self) -> float:
        return 1.0

    def __str__(self) -> str:
        return "[123]"

    def __repr__(self) -> str:
        return "Anything()"

    def __hash__(self) -> int:  # type: ignore[override]
        return 123


class _NamedEntity(Anything):
    """An entity id stub that prints as the given text."""

    def __init__(self, text: str) -> None:
        super().__init__()
        object.__setattr__(self, "_text", text)

    def __str__(self) -> str:
        return object.__getattribute__(self, "_text")


class MissingAttribute(AttributeError):
    """A module attribute the editor does not reflect.

    Unlike ``SurfaceViolation`` this stays an ``AttributeError`` so ``hasattr`` and
    ``getattr(..., default)`` probes behave as they would in the editor. Every miss is
    recorded on the log and the test decides afterwards whether it was expected.
    """


class OutcomeStub(Anything):
    """Stand-in for a reflected ``AZ::Outcome``.

    ``GetValue()`` on a failed outcome asserts "expected doesn't have a value" and then
    reads uninitialised memory; on 26.10.0 that segfaults the editor (seen live with
    ``DuplicateEntitiesInInstance``). So a script must call ``IsSuccess()`` on an
    outcome before ``GetValue()``, and this stub treats anything else as a violation.
    """

    def __init__(self, origin: str) -> None:
        super().__init__()
        object.__setattr__(self, "_origin", origin)
        object.__setattr__(self, "_checked", False)

    def IsSuccess(self) -> bool:  # noqa: N802
        object.__setattr__(self, "_checked", True)
        return True

    def GetValue(self) -> Anything:  # noqa: N802
        if not object.__getattribute__(self, "_checked"):
            raise SurfaceViolation(
                f"GetValue() called on the outcome of {object.__getattribute__(self, '_origin')} "
                "without checking IsSuccess() first; on a failed outcome this crashes the editor"
            )
        return Anything()

    def GetError(self) -> str:  # noqa: N802
        return "stub error"


class CallLog:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []  # (bus, call_type, event)
        self.functions: list[str] = []
        self.missing: list[str] = []  # "module.attr" the script asked for


_CALL_TYPES = {
    "Broadcast": object(),
    "Event": object(),
    "QueueBroadcast": object(),
    "QueueEvent": object(),
}
_CALL_TYPE_NAMES = {v: k for k, v in _CALL_TYPES.items()}


Overrides = dict[tuple[str, str], object]


def _make_bus(module: str, name: str, events: dict, log: CallLog, overrides: Overrides):  # noqa: ANN202
    def bus(call_type: object, event: str, *args: object) -> object:
        if event not in events:
            raise SurfaceViolation(
                f"{module}.{name} does not reflect event {event!r}; "
                f"reflected events: {sorted(events)}"
            )
        type_name = _CALL_TYPE_NAMES.get(call_type, repr(call_type))
        allowed = events[event]["call_types"]
        if type_name not in allowed:
            raise SurfaceViolation(
                f"{module}.{name}.{event} must be called with bus.{'/'.join(allowed)}, "
                f"script used bus.{type_name}"
            )
        log.calls.append((f"{module}.{name}", type_name, event))
        if (name, event) in overrides:
            value = overrides[(name, event)]
            return value(*args) if callable(value) else value
        if events[event]["returns"].startswith("Outcome<"):
            return OutcomeStub(f"{name}.{event}")
        return Anything()

    bus.__name__ = name
    return bus


class StrictModule(types.ModuleType):
    """Module that refuses attributes absent from the reflected surface."""

    _log: CallLog

    def __getattr__(self, name: str):  # noqa: ANN204
        if name.startswith("__"):
            raise AttributeError(name)
        self._log.missing.append(f"{self.__name__}.{name}")
        raise MissingAttribute(f"{self.__name__} does not reflect {name!r}")


def build_stub_azlmbr(
    surface: dict, log: CallLog, project_root: str = "/stub", overrides: Overrides | None = None
) -> dict[str, types.ModuleType]:
    overrides = overrides or {}
    modules: dict[str, types.ModuleType] = {}
    for mod_name, spec in surface["modules"].items():
        mod = StrictModule(mod_name)
        mod._log = log
        for bus_name, bus_spec in spec["buses"].items():
            setattr(
                mod, bus_name, _make_bus(mod_name, bus_name, bus_spec["events"], log, overrides)
            )
        for fn, fn_spec in spec["functions"].items():

            def _fn(
                *args: object,
                _n: str = f"{mod_name}.{fn}",
                _expected: int = fn_spec["num_args"],
                **kwargs: object,
            ) -> Anything:
                # The editor reflects a fixed arity for these legacy functions, so a
                # wrong argument count (the create_level bug: 2 args for a 6-arg call)
                # is a real defect, not something the editor would accept.
                got = len(args) + len(kwargs)
                if got != _expected:
                    raise SurfaceViolation(
                        f"{_n} takes {_expected} argument(s); the script called it with {got}"
                    )
                log.functions.append(_n)
                return Anything()

            setattr(mod, fn, _fn)
        for cls in spec["classes"]:
            setattr(mod, cls, lambda *a, **k: Anything())
        modules[mod_name] = mod

    # Call-type constants live on azlmbr.bus at runtime, not in the stub dump.
    bus_mod = modules.setdefault("azlmbr.bus", StrictModule("azlmbr.bus"))
    for name, sentinel in _CALL_TYPES.items():
        setattr(bus_mod, name, sentinel)

    # azlmbr.paths is populated at runtime and has no stub. These attributes were read
    # from a live 26.10.0 editor (projectroot, engroot and products were non-empty).
    paths_mod = modules.setdefault("azlmbr.paths", StrictModule("azlmbr.paths"))
    for name in ("projectroot", "engroot", "products", "devroot", "devassets"):
        setattr(paths_mod, name, project_root)

    # Wire parents to children so ``import azlmbr.legacy.general as general`` resolves.
    for mod_name in sorted(modules):
        parts = mod_name.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[:i])
            modules.setdefault(parent, StrictModule(parent))
        for i in range(1, len(parts)):
            parent, child = ".".join(parts[:i]), ".".join(parts[: i + 1])
            types.ModuleType.__setattr__(modules[parent], parts[i], modules[child])
    for mod in modules.values():
        types.ModuleType.__setattr__(mod, "__path__", [])  # lets ``import azlmbr.x`` resolve
        types.ModuleType.__setattr__(mod, "_log", log)
    return modules


@pytest.fixture(scope="module")
def surface() -> dict:
    return json.loads(SURFACE_PATH.read_text())


def _all_tools() -> list[str]:
    mcp = MCPServer("names")
    register_editor_tools(mcp)
    register_introspection_tools(mcp)
    register_trackview_tools(mcp)
    return sorted(t.name for t in mcp._tool_manager.list_tools())


# Representative arguments. Values only need to pass the tools' own validators.
SAMPLE_ARGS: dict[str, dict] = {
    # Track View
    "list_sequences": {},
    "create_sequence": {"name": "Seq1"},
    "delete_sequence": {"name": "Seq1"},
    "get_sequence": {"name": "Seq1"},
    "set_sequence_time_range": {"name": "Seq1", "start": 0, "end": 5},
    "add_sequence_node": {"name": "Seq1", "node_type": "Director", "node_name": "Dir1"},
    "play_sequence": {"name": "Seq1"},
    "stop_sequence": {},
    "add_component": {"entity_id": "123", "component_type": "Mesh"},
    "assign_asset": {
        "entity_id": "123",
        "component_type": "Mesh",
        "property_path": "Controller|Configuration|Model Asset",
        "asset_path": "Objects/test.fbx",
    },
    "begin_session": {},
    "capture_viewport": {"output_path": "shot.png"},
    "create_entity": {"name": "TestEntity"},
    "create_level": {"name": "TestLevel"},
    "create_prefab_from_entity": {"entity_id": "123", "prefab_path": "Prefabs/t.prefab"},
    "delete_entity": {"entity_id": "123"},
    "duplicate_entity": {"entity_id": "123"},
    "end_session": {"session_id": "abcd1234"},
    "enter_game_mode": {},
    "exec_in_session": {"session_id": "abcd1234", "script": "x = 1"},
    "exit_game_mode": {},
    "focus_entity": {"entity_id": "123"},
    "get_component_property": {
        "entity_id": "123",
        "component_type": "Mesh",
        "property_path": "Controller|Configuration|Model Asset",
    },
    "get_cvar": {"name": "r_fog"},
    "get_entity_components": {"entity_id": "123"},
    "get_entity": {"entity_id": "123"},
    "get_entity_tree": {},
    "get_scene_snapshot": {},
    "get_level_info": {},
    "get_session_vars": {"session_id": "abcd1234"},
    "get_transform": {"entity_id": "123"},
    "get_viewport_camera": {},
    "instantiate_prefab": {"prefab_path": "Prefabs/t.prefab", "position": [0, 0, 0]},
    "list_entities": {},
    "list_levels": {"project_path": "."},
    "load_level": {"level_path": "Levels/Test"},
    "redo": {},
    "remove_component": {"entity_id": "123", "component_type": "Mesh"},
    "run_console_command": {"command": "r_displayInfo 0"},
    "run_editor_python": {"script": "print('hello')"},
    "save_level": {},
    "save_prefab": {"entity_id": "123"},
    "set_component_property": {
        "entity_id": "123",
        "component_type": "Mesh",
        "property_path": "Controller|Configuration|Model Asset",
        "value": "0",
    },
    "set_cvar": {"name": "r_fog", "value": "0"},
    "set_parent": {"entity_id": "123", "parent_id": "456"},
    "set_transform": {"entity_id": "123", "position": [1, 2, 3], "rotation": [0, 0, 0, 1]},
    "set_viewport_camera": {"position": [0, 0, 0], "rotation": [0, 0, 0]},
    "undo": {},
    "validate_scene": {},
    "capture_renderdoc_frame": {},
    "get_bus_schema": {"project_path": "."},
    "get_bus_schema_live": {"module": "editor", "bus": "EditorComponentAPIBus"},
}

# Tools that legitimately never send a script to the editor. The three snapshot
# tools use the AiCompanion AgentServer's native request types instead.
NO_SCRIPT_TOOLS = frozenset(
    {
        "list_levels",
        "get_bus_schema",
        "get_scene_snapshot",
        "get_entity_tree",
        "get_entity",
        "validate_scene",
    }
)

# Native request types whose tools fall back to editor Python when the gem is
# too old to serve them. Refusing them keeps those scripts under test.
PYTHON_FALLBACK_TYPES = frozenset(
    {"get_bus_schema", "create_entity", "set_transform", "delete_entity"}
)

# Scripts that run in the editor but touch no azlmbr symbol: the session tools keep
# state on ``__main__``, and the two introspection tools probe with ``hasattr``.
NO_AZLMBR_TOOLS = frozenset(
    {
        "begin_session",
        "end_session",
        "exec_in_session",
        "get_session_vars",
        "get_bus_schema_live",
        "capture_renderdoc_frame",
        "run_editor_python",
    }
)


def generate_script(tool: str, arguments: dict, tmp_path: Path) -> str | None:
    """Invoke the tool through MCP dispatch and return the script it sent, if any."""
    captured: list[str] = []

    async def _record(script: str, timeout: float | None = None, **kwargs: object) -> str:
        captured.append(script)
        return ""

    mcp = MCPServer("scripts")
    register_editor_tools(mcp)
    register_introspection_tools(mcp)
    register_trackview_tools(mcp)
    env = {"O3DE_CAPTURE_WAIT": "0", "O3DE_PROJECT_PATH": str(tmp_path)}
    with (
        patch("o3de_mcp.tools.editor._pool") as pool,
        patch.dict(os.environ, env),
    ):
        pool.send_script = AsyncMock(side_effect=_record)

        # Native request types answer; the ones that have a Python fallback are
        # refused as an older gem would, so that get_bus_schema_live and the
        # native-first mutation tools still exercise their scripts here.
        async def _native(request_type: str, **kwargs: object) -> dict:
            if request_type in PYTHON_FALLBACK_TYPES:
                return {"status": "error", "code": "editor_error", "error": "Unknown request type"}
            return {"status": "ok", "output": "{}"}

        pool.send_request = AsyncMock(side_effect=_native)
        try:
            asyncio.run(mcp.call_tool(tool, arguments))
        except Exception as exc:  # the tool may reject the empty reply; the script was still sent
            if not captured:
                raise AssertionError(f"{tool} raised before sending a script: {exc}") from exc
    return captured[0] if captured else None


# Attributes a script is expected to probe for and find absent on 26.10.0.
EXPECTED_PROBES: dict[str, set[str]] = {
    "capture_renderdoc_frame": {"azlmbr.bus.GraphicsProfilerBus"},
}


def run_against_surface(
    script: str, surface: dict, project_root: str = "/stub", overrides: Overrides | None = None
) -> tuple[CallLog, str]:
    log = CallLog()
    # The level holds entities whose ids print as "[123]" and "[456]", matching
    # the sample ids, so the entity resolver (which looks ids up by text) finds them.
    overrides = {
        ("SearchBus", "SearchEntities"): [Anything(), _NamedEntity("[456]")],
        **(overrides or {}),
    }
    modules = build_stub_azlmbr(surface, log, project_root, overrides)
    out = io.StringIO()
    with patch.dict(sys.modules, modules), redirect_stdout(out):
        exec(script, {"__name__": "__main__"})  # noqa: S102 - the point of the test
    return log, out.getvalue()


class Failure:
    """An AZ::Outcome that failed."""

    def IsSuccess(self) -> bool:  # noqa: N802
        return False

    def GetError(self) -> str:  # noqa: N802
        return "stub failure"


def test_surface_harness_enforces_function_arity(surface: dict) -> None:
    # The reflection records each legacy function's argument count, and the stub
    # enforces it, so a wrong-arity call fails. This is the class of bug create_level
    # shipped with (it called a 6-arg engine function with 2) that the name-only
    # harness could not catch.
    log = CallLog()
    mods = build_stub_azlmbr(surface, log)
    gen = mods["azlmbr.legacy.general"]
    # The correct 6-argument call is accepted.
    gen.create_level_no_prompt("Prefabs/Default_Level.prefab", "Lvl", 1024, 1, 4096, False)
    # The original bug shape (2 args) is rejected.
    with pytest.raises(SurfaceViolation):
        gen.create_level_no_prompt("Lvl", 0)


def test_surface_file_is_populated(surface: dict) -> None:
    buses = sum(len(m["buses"]) for m in surface["modules"].values())
    assert buses > 50, "azlmbr_surface.json looks truncated; regenerate it from a stub dump"
    assert "PrefabPublicRequestBus" in surface["modules"]["azlmbr.prefab"]["buses"]
    assert "run_console" in surface["modules"]["azlmbr.legacy.general"]["functions"]


def test_every_tool_has_sample_arguments() -> None:
    missing = set(_all_tools()) - set(SAMPLE_ARGS)
    assert not missing, f"add SAMPLE_ARGS for: {sorted(missing)}"


@pytest.mark.parametrize("tool", _all_tools())
def test_generated_script_uses_only_reflected_api(tool: str, surface: dict, tmp_path: Path) -> None:
    script = generate_script(tool, SAMPLE_ARGS[tool], tmp_path)
    if tool in NO_SCRIPT_TOOLS:
        assert script is None, (
            f"{tool} started sending a script; update NO_SCRIPT_TOOLS if intended"
        )
        return
    assert script is not None, f"{tool} sent no script to the editor"

    # instantiate_prefab checks the file exists before touching the bus; give it one.
    (tmp_path / "Prefabs").mkdir(exist_ok=True)
    (tmp_path / "Prefabs" / "t.prefab").write_text("{}")

    log, _ = run_against_surface(script, surface, project_root=str(tmp_path))

    unexpected = set(log.missing) - EXPECTED_PROBES.get(tool, set())
    assert not unexpected, (
        f"{tool} used attributes the editor does not reflect: {sorted(unexpected)}"
    )

    if tool not in NO_AZLMBR_TOOLS:
        assert log.calls or log.functions, f"{tool}'s script called nothing in azlmbr"


# --- Tools that used to report success on a bus call that could not have worked ---


def _run_tool(tool: str, surface: dict, tmp_path: Path, overrides: Overrides) -> str:
    script = generate_script(tool, SAMPLE_ARGS[tool], tmp_path)
    assert script is not None
    _, output = run_against_surface(script, surface, str(tmp_path), overrides)
    return output


class TestNoFalseSuccess:
    """Each of these tools once printed success after calling an event that does not exist."""

    def test_remove_component_reports_a_refused_removal(
        self, surface: dict, tmp_path: Path
    ) -> None:
        out = _run_tool(
            "remove_component",
            surface,
            tmp_path,
            {("EditorComponentAPIBus", "RemoveComponents"): False},
        )
        parsed = json.loads(out)
        assert parsed["status"] == "error" and parsed["code"] == "remove_component_failed"

    def test_remove_component_reports_a_component_that_is_not_there(
        self, surface: dict, tmp_path: Path
    ) -> None:
        out = _run_tool(
            "remove_component",
            surface,
            tmp_path,
            {("EditorComponentAPIBus", "GetComponentOfType"): Failure()},
        )
        parsed = json.loads(out)
        assert parsed["status"] == "error" and parsed["code"] == "component_not_on_entity"

    def test_set_parent_reports_when_the_parent_did_not_change(
        self, surface: dict, tmp_path: Path
    ) -> None:
        # GetParent answers with something other than the requested parent.
        out = _run_tool(
            "set_parent", surface, tmp_path, {("EditorEntityInfoRequestBus", "GetParent"): "[999]"}
        )
        parsed = json.loads(out)
        assert parsed["status"] == "error" and parsed["code"] == "set_parent_failed"

    def test_add_component_reports_an_unknown_type(self, surface: dict, tmp_path: Path) -> None:
        out = _run_tool(
            "add_component",
            surface,
            tmp_path,
            {("EditorComponentAPIBus", "FindComponentTypeIdsByEntityType"): []},
        )
        parsed = json.loads(out)
        assert parsed["status"] == "error" and parsed["code"] == "component_type_not_found"

    def test_remove_component_reports_an_unknown_type(self, surface: dict, tmp_path: Path) -> None:
        out = _run_tool(
            "remove_component",
            surface,
            tmp_path,
            {("EditorComponentAPIBus", "FindComponentTypeIdsByEntityType"): []},
        )
        parsed = json.loads(out)
        assert parsed["status"] == "error" and parsed["code"] == "component_type_not_found"

    def test_set_parent_confirms_only_after_reading_the_parent_back(
        self, surface: dict, tmp_path: Path
    ) -> None:
        out = _run_tool(
            "set_parent", surface, tmp_path, {("EditorEntityInfoRequestBus", "GetParent"): "[456]"}
        )
        assert out.startswith("Set parent of")

    def test_duplicate_entity_reports_a_failed_duplicate(
        self, surface: dict, tmp_path: Path
    ) -> None:
        out = _run_tool(
            "duplicate_entity",
            surface,
            tmp_path,
            {
                # The entity must be found first, so the script reaches the
                # duplicate call and reports its failure (not entity_not_found).
                ("SearchBus", "SearchEntities"): [Anything()],
                ("PrefabPublicRequestBus", "DuplicateEntitiesInInstance"): Failure(),
            },
        )
        parsed = json.loads(out)
        assert parsed["status"] == "error"
        assert parsed["code"] == "duplicate_failed"

    def test_duplicate_entity_returns_the_new_id(self, surface: dict, tmp_path: Path) -> None:
        class Ok:
            def IsSuccess(self) -> bool:  # noqa: N802
                return True

            def GetValue(self) -> list[str]:  # noqa: N802
                return ["[777]"]

        out = _run_tool(
            "duplicate_entity",
            surface,
            tmp_path,
            {
                ("SearchBus", "SearchEntities"): [Anything()],
                ("PrefabPublicRequestBus", "DuplicateEntitiesInInstance"): Ok(),
            },
        )
        assert json.loads(out)["id"] == "[777]"

    def test_create_entity_refuses_without_a_level(self, surface: dict, tmp_path: Path) -> None:
        # With no level open, CreateNewEntity pops a modal dialog that blocks the editor's
        # main thread until someone clicks OK; every later request then times out.
        class NoLevel:
            def IsValid(self) -> bool:  # noqa: N802
                return False

        script = generate_script("create_entity", SAMPLE_ARGS["create_entity"], tmp_path)
        assert script is not None
        log, out = run_against_surface(
            script,
            surface,
            str(tmp_path),
            {("ToolsApplicationRequestBus", "GetCurrentLevelEntityId"): NoLevel()},
        )
        assert json.loads(out)["code"] == "no_level_open"
        assert (
            "azlmbr.editor.ToolsApplicationRequestBus",
            "Broadcast",
            "CreateNewEntity",
        ) not in log.calls


def test_add_component_treats_a_null_type_uuid_as_unknown(surface: dict, tmp_path: Path) -> None:
    # Live 26.10.0 answers an unknown component name with [null uuid], not [].
    class NullUuid:
        def __str__(self) -> str:
            return "{00000000-0000-0000-0000-000000000000}"

    out = _run_tool(
        "add_component",
        surface,
        tmp_path,
        {("EditorComponentAPIBus", "FindComponentTypeIdsByEntityType"): [NullUuid()]},
    )
    parsed = json.loads(out)
    assert parsed["status"] == "error" and parsed["code"] == "component_type_not_found"


class _UniformTM(Anything):
    """A world transform stub whose uniform scale reads back as given."""

    def __init__(self, uniform: float) -> None:
        super().__init__()
        object.__setattr__(self, "_uniform", uniform)

    def GetUniformScale(self) -> float:  # noqa: N802
        return object.__getattribute__(self, "_uniform")


def _set_transform_script(surface: dict, tmp_path: Path, arguments: dict, readback: float) -> str:
    script = generate_script("set_transform", {"entity_id": "123", **arguments}, tmp_path)
    assert script is not None
    _, out = run_against_surface(
        script,
        surface,
        str(tmp_path),
        {("TransformBus", "GetWorldTM"): lambda *a: _UniformTM(readback)},
    )
    return out


class TestSetTransformScale:
    def test_keeps_the_current_scale_when_none_is_given(
        self, surface: dict, tmp_path: Path
    ) -> None:
        # The entity is at scale 3 and stays there; rebuilding the transform from
        # rotation and translation alone used to reset it to 1.
        out = _set_transform_script(surface, tmp_path, {"position": [1, 2, 3]}, 3.0)
        assert out.startswith("Transform set for entity"), out

    def test_a_uniform_scale_is_applied(self, surface: dict, tmp_path: Path) -> None:
        out = _set_transform_script(surface, tmp_path, {"scale": [2, 2, 2]}, 2.0)
        assert out.startswith("Transform set for entity"), out

    def test_a_scale_that_does_not_land_is_an_error(self, surface: dict, tmp_path: Path) -> None:
        out = _set_transform_script(surface, tmp_path, {"scale": [2, 2, 2]}, 3.0)
        parsed = json.loads(out)
        assert parsed["status"] == "error" and parsed["code"] == "set_transform_failed"


def test_an_unknown_entity_id_is_entity_not_found(surface: dict, tmp_path: Path) -> None:
    # The resolver finds ids by their text; with nothing in the level the tool
    # reports entity_not_found instead of acting on a rebuilt (wrong) id.
    out = _run_tool("get_transform", surface, tmp_path, {("SearchBus", "SearchEntities"): []})
    parsed = json.loads(out)
    assert parsed["status"] == "error" and parsed["code"] == "entity_not_found"
    assert "123" in parsed["message"]


class _Asset(Anything):
    """An AssetId stub: valid or not, printing as the given text."""

    def __init__(self, valid: bool, text: str = "{ASSET}:0") -> None:
        super().__init__()
        object.__setattr__(self, "_valid", valid)
        object.__setattr__(self, "_text", text)

    def is_valid(self) -> bool:
        return object.__getattribute__(self, "_valid")

    def __str__(self) -> str:
        return object.__getattribute__(self, "_text")


class _Ok(Anything):
    def __init__(self, value: object = None) -> None:
        super().__init__()
        object.__setattr__(self, "_value", value)

    def IsSuccess(self) -> bool:  # noqa: N802
        return True

    def GetValue(self) -> object:  # noqa: N802
        return object.__getattribute__(self, "_value")


class TestAssignAsset:
    """assign_asset reports only an assignment that reads back."""

    def _run(self, surface: dict, tmp_path: Path, overrides: dict) -> dict | str:
        out = _run_tool("assign_asset", surface, tmp_path, overrides)
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return out

    def test_an_unknown_asset_is_asset_not_found(self, surface: dict, tmp_path: Path) -> None:
        parsed = self._run(
            surface,
            tmp_path,
            {("AssetCatalogRequestBus", "GetAssetIdByPath"): lambda *a: _Asset(False)},
        )
        assert parsed["code"] == "asset_not_found"

    def test_a_refused_set_is_reported(self, surface: dict, tmp_path: Path) -> None:
        parsed = self._run(
            surface,
            tmp_path,
            {
                ("AssetCatalogRequestBus", "GetAssetIdByPath"): lambda *a: _Asset(True),
                ("EditorComponentAPIBus", "SetComponentProperty"): Failure(),
            },
        )
        assert parsed["code"] == "set_property_failed"

    def test_a_value_that_does_not_stick_is_reported(self, surface: dict, tmp_path: Path) -> None:
        parsed = self._run(
            surface,
            tmp_path,
            {
                ("AssetCatalogRequestBus", "GetAssetIdByPath"): lambda *a: _Asset(True, "{A}:0"),
                ("EditorComponentAPIBus", "SetComponentProperty"): lambda *a: _Ok(),
                ("EditorComponentAPIBus", "GetComponentProperty"): lambda *a: _Ok(
                    _Asset(True, "{B}:0")
                ),
            },
        )
        assert parsed["code"] == "assign_asset_failed"

    def test_an_assignment_that_reads_back_succeeds(self, surface: dict, tmp_path: Path) -> None:
        out = self._run(
            surface,
            tmp_path,
            {
                ("AssetCatalogRequestBus", "GetAssetIdByPath"): lambda *a: _Asset(True, "{A}:0"),
                ("EditorComponentAPIBus", "SetComponentProperty"): lambda *a: _Ok(),
                ("EditorComponentAPIBus", "GetComponentProperty"): lambda *a: _Ok(
                    _Asset(True, "{A}:0")
                ),
            },
        )
        assert isinstance(out, str) and out.startswith("Assigned asset"), out
