#!/usr/bin/env python3
# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Extract the reflected ``azlmbr`` surface from an editor stub dump.

The O3DE Editor writes ``<project>/user/python_symbols/azlmbr/**/*.pyi`` describing
every EBus, event, function and class it reflects to Python. This script folds that
dump into one JSON file so the test suite can check generated editor scripts against
the real surface without a running editor. Regenerate it when the engine version
changes::

    python scripts/extract-azlmbr-surface.py <project>/user/python_symbols/azlmbr \\
        tests/data/azlmbr_surface.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_BUS_DEF = re.compile(r"^def (\w+)\(busCallType: int, busEventName: str, (?:address: \w+, )?args")
_EVENT_LINE = re.compile(
    r"^\s*bus\.(Broadcast|Event|QueueBroadcast|QueueEvent), '(\w+)', \((.*?)\) -> (.*?)\s*$"
)
_FUNC_DEF = re.compile(r"^def (\w+)\(")
_CLASS_DEF = re.compile(r"^class (\w+)")


def _module_name(root: Path, stub: Path) -> str:
    rel = stub.relative_to(root).with_suffix("")
    parts = [p for p in rel.parts if p != "__init__"]
    return ".".join(["azlmbr", *parts]) if parts else "azlmbr"


def extract(root: Path) -> dict:
    surface: dict = {"engine_stub_root": str(root), "modules": {}}
    for stub in sorted(root.rglob("*.pyi")):
        mod = surface["modules"].setdefault(
            _module_name(root, stub), {"buses": {}, "functions": [], "classes": []}
        )
        current_bus: dict | None = None
        for line in stub.read_text(errors="replace").splitlines():
            if m := _BUS_DEF.match(line):
                current_bus = mod["buses"].setdefault(m.group(1), {"events": {}})
                continue
            if m := _EVENT_LINE.match(line):
                if current_bus is not None:
                    call_type, event, args, ret = m.groups()
                    current_bus["events"].setdefault(
                        event, {"call_types": [], "args": args, "returns": ret}
                    )
                    if call_type not in current_bus["events"][event]["call_types"]:
                        current_bus["events"][event]["call_types"].append(call_type)
                continue
            if m := _FUNC_DEF.match(line):
                current_bus = None
                if m.group(1) not in mod["functions"]:
                    mod["functions"].append(m.group(1))
                continue
            if m := _CLASS_DEF.match(line):
                current_bus = None
                if m.group(1) not in mod["classes"]:
                    mod["classes"].append(m.group(1))
    return surface


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    root, out = Path(argv[1]), Path(argv[2])
    surface = extract(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(surface, indent=1, sort_keys=True) + "\n")
    buses = sum(len(m["buses"]) for m in surface["modules"].values())
    events = sum(len(b["events"]) for m in surface["modules"].values() for b in m["buses"].values())
    print(f"{len(surface['modules'])} modules, {buses} buses, {events} events -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
