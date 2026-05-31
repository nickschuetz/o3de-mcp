# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Generic, gem-agnostic introspection of O3DE reflected EBuses.

The O3DE editor (EditorPythonBindings, ``PythonLogSymbolsComponent``) writes a
typed Python stub of every reflected module to
``<project>/user/python_symbols/azlmbr/<module>.pyi`` whenever the editor runs.
Each EBus appears as a function whose docstring lists the supported events:

    def DioramaSpriteRequestBus(busCallType: int, busEventName: str,
                                address: EntityId, args: Tuple[Any]) -> Any:
        \"\"\"
        The following bus Call types, Event names and Argument types are
        supported by this bus:
        bus.Event, 'SetSize', (float, float) -> None
        bus.Event, 'GetSpriteInfo', () -> Diorama::SpriteInfo
        \"\"\"

This module reads and parses those stubs into a structured schema so an agent
can discover any gem's scripting API with no hand-maintained catalog. It is a
pure file reader: it needs the editor to have run at least once to produce the
dump, but it does not require a live editor connection.

Note: the editor's generated stub lists EBus event arguments by TYPE only (the
same for every first-party bus); argument names and tooltips live in the C++
BehaviorContext, not the stub. A future BehaviorContext-backed query is needed
to surface those names.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from o3de_mcp.utils.o3de import list_registered_projects

#: Relative location of the azlmbr symbol dump within a project.
_SYMBOLS_SUBPATH = Path("user") / "python_symbols" / "azlmbr"

#: Marker text in a bus function's docstring (identifies it as an EBus stub).
_BUS_MARKER = "are supported by this bus"

#: A module is an azlmbr submodule name and becomes a path segment, so it must
#: be a bare identifier (no separators or "..") to keep it inside the symbols
#: directory. Mirrors the validator in tools.project so the rule is consistent.
_MODULE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

#: ``def <Name>(busCallType: int, busEventName: str[, address: <T>], ...)``
_BUS_DEF_RE = re.compile(
    r"^def\s+(?P<name>\w+)\s*\("
    r"\s*busCallType\s*:[^,]+,"
    r"\s*busEventName\s*:[^,]+"
    r"(?:,\s*address\s*:\s*(?P<address>[^,]+?)\s*,)?"
    r".*\)\s*(?:->\s*.+?)?:\s*$"
)

#: ``bus.<CallType>, '<Event>', <rest>`` where rest is ``(<args>) -> <return>``.
_EVENT_RE = re.compile(r"^bus\.(?P<call>\w+),\s*'(?P<event>[^']+)',\s*(?P<rest>.+?)\s*$")


def _split_top_level(text: str) -> list[str]:
    """Split a comma list at depth-0 commas, respecting <>, (), [] nesting.

    Keeps templated types such as ``AZStd::vector<X, Y>`` as a single element.
    """
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    openers = {"<": ">", "(": ")", "[": "]"}
    closers = {">", ")", "]"}
    for ch in text:
        if ch in openers:
            depth += 1
            current.append(ch)
        elif ch in closers:
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_args_and_return(rest: str) -> tuple[list[str], str]:
    """Parse ``(<argtypes>) -> <return>`` into a type list and a return type.

    The return type can itself contain ``->``-free templated text with commas
    and ``::``; the argument list is paren-matched so a ``)`` inside a return
    type cannot truncate it.
    """
    rest = rest.strip()
    if not rest.startswith("("):
        return [], rest
    depth = 0
    close_index = -1
    for index, ch in enumerate(rest):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                close_index = index
                break
    if close_index == -1:
        return [], rest
    inside = rest[1:close_index].strip()
    after = rest[close_index + 1 :].strip()
    return_type = after[2:].strip() if after.startswith("->") else after.lstrip("->").strip()
    args = _split_top_level(inside) if inside else []
    return args, return_type


def parse_stub(text: str) -> list[dict]:
    """Parse a ``.pyi`` stub into a list of bus schema dicts.

    Returns one entry per EBus found, each with ``name``, ``addressable``,
    ``address_type`` and a list of ``events`` (``call_type``, ``name``,
    ``args``, ``returns``).
    """
    buses: list[dict] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = _BUS_DEF_RE.match(lines[index].strip())
        if match is None:
            index += 1
            continue
        # Collect the docstring/body lines until the next top-level def.
        body: list[str] = []
        index += 1
        while index < len(lines) and not lines[index].startswith("def "):
            body.append(lines[index])
            index += 1
        body_text = "\n".join(body)
        if _BUS_MARKER not in body_text:
            continue
        events: list[dict] = []
        for body_line in body:
            event_match = _EVENT_RE.match(body_line.strip())
            if event_match is None:
                continue
            args, returns = _parse_args_and_return(event_match.group("rest"))
            events.append(
                {
                    "call_type": event_match.group("call"),
                    "name": event_match.group("event"),
                    "args": args,
                    "returns": returns,
                }
            )
        address = match.group("address")
        buses.append(
            {
                "name": match.group("name"),
                "addressable": address is not None,
                "address_type": address.strip() if address else None,
                "events": events,
            }
        )
    return buses


def resolve_symbols_dir(project_path: str | None = None) -> Path:
    """Locate the azlmbr symbol-dump directory for a project.

    Resolution order: explicit ``project_path`` argument, the
    ``O3DE_PROJECT_PATH`` environment variable, then the single registered
    project that has a symbol dump. Raises ``LookupError`` with a helpful
    message when the project is ambiguous or no dump exists yet.
    """
    if project_path:
        return Path(project_path) / _SYMBOLS_SUBPATH

    env_path = os.environ.get("O3DE_PROJECT_PATH", "").strip()
    if env_path:
        return Path(env_path) / _SYMBOLS_SUBPATH

    candidates = [
        Path(project["path"])
        for project in list_registered_projects()
        if (Path(project["path"]) / _SYMBOLS_SUBPATH).is_dir()
    ]
    if len(candidates) == 1:
        return candidates[0] / _SYMBOLS_SUBPATH
    if not candidates:
        raise LookupError(
            "No project has a python_symbols dump yet. Open the project in the "
            "O3DE Editor once to generate it, or pass project_path explicitly."
        )
    listed = ", ".join(str(path) for path in candidates)
    raise LookupError(
        f"Multiple projects have symbol dumps ({listed}). Pass project_path to "
        "choose one, or set O3DE_PROJECT_PATH."
    )


def list_modules(project_path: str | None = None) -> dict:
    """List the azlmbr modules that have a generated stub for a project."""
    symbols_dir = resolve_symbols_dir(project_path)
    if not symbols_dir.is_dir():
        raise LookupError(
            f"Symbol dump directory not found: {symbols_dir}. Open the project "
            "in the O3DE Editor once to generate it."
        )
    modules = sorted(path.stem for path in symbols_dir.glob("*.pyi"))
    return {"symbols_dir": str(symbols_dir), "modules": modules}


def get_bus_schema(
    module: str | None = None,
    bus: str | None = None,
    project_path: str | None = None,
) -> dict:
    """Return the reflected EBus schema for a module from its generated stub.

    With no ``module``, lists the available modules. With ``module`` set,
    returns every EBus in that module (or just ``bus`` if given), each with its
    events and argument/return types.
    """
    if module is None:
        return list_modules(project_path)

    # Validate before building a path from it: module is a path segment, so an
    # unchecked value like "../../etc/hostname" would escape the symbols dir.
    if not _MODULE_RE.match(module):
        raise ValueError(
            f"Invalid module name {module!r}. Must be a bare identifier: start "
            "with a letter and contain only letters, digits, hyphens, or underscores."
        )

    symbols_dir = resolve_symbols_dir(project_path)
    stub_path = symbols_dir / f"{module}.pyi"
    if not stub_path.is_file():
        available = list_modules(project_path)["modules"]
        raise LookupError(
            f"No stub for module '{module}' at {stub_path}. "
            f"Available modules: {', '.join(available) or '(none)'}."
        )

    all_buses = parse_stub(stub_path.read_text())
    buses = all_buses
    if bus is not None:
        buses = [entry for entry in all_buses if entry["name"] == bus]
        if not buses:
            names = ", ".join(entry["name"] for entry in all_buses)
            raise LookupError(f"No bus '{bus}' in module '{module}'. Buses: {names or '(none)'}.")

    return {
        "module": module,
        "source": str(stub_path),
        "buses": buses,
        "note": (
            "Argument types are from the editor's generated stub, which lists "
            "EBus event arguments by type only (the same for every O3DE bus). "
            "Argument names and tooltips live in the C++ BehaviorContext, not "
            "this stub."
        ),
    }
