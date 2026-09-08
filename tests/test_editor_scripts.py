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

    def __float__(self) -> float:
        return 1.0

    def __str__(self) -> str:
        return "[123]"

    def __repr__(self) -> str:
        return "Anything()"

    def __hash__(self) -> int:  # type: ignore[override]
        return 123


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
        for fn in spec["functions"]:

            def _fn(*args: object, _n: str = f"{mod_name}.{fn}", **kwargs: object) -> Anything:
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
    return sorted(t.name for t in mcp._tool_manager.list_tools())


# Representative arguments. Values only need to pass the tools' own validators.
SAMPLE_ARGS: dict[str, dict] = {
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
    {"list_levels", "get_bus_schema", "get_scene_snapshot", "get_entity_tree", "validate_scene"}
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
    env = {"O3DE_CAPTURE_WAIT": "0", "O3DE_PROJECT_PATH": str(tmp_path)}
    with (
        patch("o3de_mcp.tools.editor._pool") as pool,
        patch.dict(os.environ, env),
    ):
        pool.send_script = AsyncMock(side_effect=_record)
        pool.send_request = AsyncMock(return_value={"status": "ok", "output": "{}"})
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
        assert "Failed to remove" in out
        assert "Removed" not in out.replace("Failed to remove", "")

    def test_remove_component_reports_a_component_that_is_not_there(
        self, surface: dict, tmp_path: Path
    ) -> None:
        out = _run_tool(
            "remove_component",
            surface,
            tmp_path,
            {("EditorComponentAPIBus", "GetComponentOfType"): Failure()},
        )
        assert "is not on entity" in out
        assert "Removed" not in out

    def test_set_parent_reports_when_the_parent_did_not_change(
        self, surface: dict, tmp_path: Path
    ) -> None:
        # GetParent answers with something other than the requested parent.
        out = _run_tool(
            "set_parent", surface, tmp_path, {("EditorEntityInfoRequestBus", "GetParent"): "[999]"}
        )
        assert "Failed to set parent" in out

    def test_set_parent_confirms_only_after_reading_the_parent_back(
        self, surface: dict, tmp_path: Path
    ) -> None:
        out = _run_tool(
            "set_parent", surface, tmp_path, {("EditorEntityInfoRequestBus", "GetParent"): "[123]"}
        )
        assert out.startswith("Set parent of")

    def test_duplicate_entity_reports_a_failed_duplicate(
        self, surface: dict, tmp_path: Path
    ) -> None:
        out = _run_tool(
            "duplicate_entity",
            surface,
            tmp_path,
            {("PrefabPublicRequestBus", "DuplicateEntitiesInInstance"): Failure()},
        )
        assert "error" in json.loads(out)

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
