#!/usr/bin/env python3
# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Run Example 4 (Scripted Mini-Game) against a running O3DE Editor.

Creates a "falling crates" mini-game scene: environment lighting, a ground
plane, a player ball, a goal zone trigger, falling obstacle crates, a game
manager, and a follow camera.  Works on a blank level — no prior scene setup
required.

Prerequisites:
  - O3DE Editor running with AiCompanion (or RemoteConsole) + EditorPythonBindings gems
  - A level loaded (blank is fine)
  - o3de-mcp installed: pip install -e ".[dev]"

Usage:
  python scripts/run-example-04.py [--enter-game-mode] [--cleanup]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from o3de_mcp.server import mcp
from o3de_mcp.tools.editor import _async_run_editor_script
from o3de_mcp.utils.capabilities import get_server_capabilities

# Component names — O3DE 2510+ renamed PhysX components.
# The script auto-detects available names at startup.
COLLIDER_COMP = "PhysX Primitive Collider"  # fallback: "PhysX Collider"
RIGID_BODY_COMP = "PhysX Dynamic Rigid Body"  # fallback: "PhysX Rigid Body"

# Mesh asset paths (Atom built-in primitives)
SPHERE_MODEL = "materialeditor/viewportmodels/quadsphere.fbx.azmodel"
CUBE_MODEL = "materialeditor/viewportmodels/cube.fbx.azmodel"
PLANE_MODEL = "materialeditor/viewportmodels/plane_1x1.fbx.azmodel"

# Entity names created by this script, used for cleanup
ENTITY_NAMES = [
    "Environment",
    "Sun",
    "Ground",
    "Player",
    "GoalZone",
    "CrateSpawners",
    "FallingCrate_00",
    "FallingCrate_01",
    "FallingCrate_02",
    "FallingCrate_03",
    "GameManager",
    "FollowCamera",
]


# Reusable azlmbr helper snippet injected into editor scripts.
# Sets the Model Asset on a Mesh component using EntityComponentIdPair.
_SET_MESH_ASSET_FUNC = """
def _set_mesh_asset(eid, asset_id, mesh_type_id):
    outcome = editor.EditorComponentAPIBus(
        bus.Broadcast, 'GetComponentOfType', eid, mesh_type_id
    )
    if outcome.IsSuccess():
        pair = outcome.GetValue()
        editor.EditorComponentAPIBus(
            bus.Broadcast, 'SetComponentProperty', pair,
            'Controller|Configuration|Model Asset', asset_id
        )
"""


async def check_capabilities() -> bool:
    """Verify the editor is reachable and detect correct PhysX component names."""
    global COLLIDER_COMP, RIGID_BODY_COMP

    print("Checking capabilities...")
    caps = await get_server_capabilities(mcp)
    editor_status = caps["editor"]["status"]
    if editor_status != "connected":
        print(f"  ERROR: Editor status is '{editor_status}'. Is the editor running?")
        return False
    host = caps["editor"]["host"]
    port = caps["editor"]["port"]
    print(f"  Editor connected on {host}:{port}")

    level = await _async_run_editor_script(
        "import azlmbr.legacy.general as g; import json; "
        'print(json.dumps({"name": g.get_current_level_name(), '
        '"path": g.get_current_level_path()}))'
    )
    try:
        info = json.loads(level)
        print(f"  Level: {info['name']} ({info['path']})")
    except (json.JSONDecodeError, KeyError):
        print(f"  Level info: {level}")

    # Auto-detect PhysX component names (changed in O3DE 2510+)
    detect_result = await _async_run_editor_script(
        "import azlmbr.editor as editor, azlmbr.bus as bus, azlmbr.entity as entity, json\n"
        "gt = entity.EntityType().Game\n"
        "candidates = [\n"
        '  ("PhysX Primitive Collider", "PhysX Collider"),\n'
        '  ("PhysX Dynamic Rigid Body", "PhysX Rigid Body"),\n'
        "]\n"
        "result = {}\n"
        "for new, old in candidates:\n"
        "  ids = editor.EditorComponentAPIBus(bus.Broadcast, "
        '"FindComponentTypeIdsByEntityType", [new], gt)\n'
        '  if ids and str(ids[0]) != "{00000000-0000-0000-0000-000000000000}":\n'
        "    result[old] = new\n"
        "  else:\n"
        "    ids2 = editor.EditorComponentAPIBus(bus.Broadcast, "
        '"FindComponentTypeIdsByEntityType", [old], gt)\n'
        '    if ids2 and str(ids2[0]) != "{00000000-0000-0000-0000-000000000000}":\n'
        "      result[old] = old\n"
        "    else:\n"
        "      result[old] = None\n"
        "print(json.dumps(result))\n"
    )
    try:
        names = json.loads(detect_result)
        if names.get("PhysX Collider"):
            COLLIDER_COMP = names["PhysX Collider"]
        if names.get("PhysX Rigid Body"):
            RIGID_BODY_COMP = names["PhysX Rigid Body"]
        print(f"  Collider component: {COLLIDER_COMP}")
        print(f"  Rigid body component: {RIGID_BODY_COMP}")
    except (json.JSONDecodeError, KeyError):
        print("  WARNING: Could not detect PhysX names, using defaults")

    return True


async def cleanup_entities() -> None:
    """Delete all entities created by this script."""
    print("\nCleaning up previous entities...")
    result = await _async_run_editor_script(
        """
import azlmbr.editor as editor
import azlmbr.entity as entity
import azlmbr.bus as bus
import json

names = """
        + json.dumps(ENTITY_NAMES)
        + """

deleted = []
for name in names:
    sf = entity.SearchFilter()
    sf.names = [name]
    eids = entity.SearchBus(bus.Broadcast, 'SearchEntities', sf)
    for eid in eids:
        editor.ToolsApplicationRequestBus(bus.Broadcast, 'DeleteEntityById', eid)
        deleted.append(name)

print(json.dumps(deleted))
"""
    )
    try:
        deleted = json.loads(result)
        if deleted:
            print(f"  Deleted {len(deleted)} entities: {', '.join(deleted)}")
        else:
            print("  No existing entities to clean up")
    except json.JSONDecodeError:
        print(f"  Cleanup result: {result}")


async def step_0_setup_environment() -> str:
    """Create environment: directional light (Sun), HDRi skybox, and ground plane."""
    print("\nStep 0: Setting up environment (Sun, Sky, Ground)...")
    collider = json.dumps(COLLIDER_COMP)
    plane_model = json.dumps(PLANE_MODEL)
    result = await _async_run_editor_script(f"""
import azlmbr.editor as editor
import azlmbr.bus as bus
import azlmbr.entity as entity
import azlmbr.components as comp
import azlmbr.asset as asset
import azlmbr.math as math
import json
{_SET_MESH_ASSET_FUNC}
gt = entity.EntityType().Game
root = azlmbr.entity.EntityId()
results = []

# --- Environment parent ---
env_id = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', root)
editor.EditorEntityAPIBus(bus.Event, 'SetName', env_id, 'Environment')
results.append({{'name': 'Environment', 'id': str(env_id)}})

# --- Sun (Directional Light) ---
sun_id = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', env_id)
editor.EditorEntityAPIBus(bus.Event, 'SetName', sun_id, 'Sun')
dl_t = editor.EditorComponentAPIBus(
    bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['Directional Light'], gt
)
if dl_t:
    editor.EditorComponentAPIBus(bus.Broadcast, 'AddComponentOfType', sun_id, dl_t[0])
# Rotate to angle sunlight down (pitch ~50 degrees)
comp.TransformBus(bus.Event, 'SetWorldTranslation', sun_id, math.Vector3(0.0, 0.0, 20.0))
comp.TransformBus(bus.Event, 'SetLocalRotation', sun_id, math.Vector3(-0.87, 0.2, 0.0))
results.append({{'name': 'Sun', 'id': str(sun_id)}})

# --- Ground plane ---
ground_id = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', env_id)
editor.EditorEntityAPIBus(bus.Event, 'SetName', ground_id, 'Ground')

mesh_t = editor.EditorComponentAPIBus(
    bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['Mesh'], gt
)
if mesh_t:
    editor.EditorComponentAPIBus(bus.Broadcast, 'AddComponentOfType', ground_id, mesh_t[0])

col_name = json.loads({collider!r})
col_t = editor.EditorComponentAPIBus(
    bus.Broadcast, 'FindComponentTypeIdsByEntityType', [col_name], gt
)
if col_t:
    editor.EditorComponentAPIBus(bus.Broadcast, 'AddComponentOfType', ground_id, col_t[0])

# Scale ground to be large (50x50 meters)
comp.TransformBus(bus.Event, 'SetWorldTranslation', ground_id, math.Vector3(10.0, 0.0, 0.0))
comp.TransformBus(bus.Event, 'SetLocalUniformScale', ground_id, 50.0)

# Assign the plane mesh asset
plane_path = json.loads({plane_model!r})
plane_asset = asset.AssetCatalogRequestBus(
    bus.Broadcast, 'GetAssetIdByPath', plane_path, math.Uuid(), False
)
if mesh_t:
    _set_mesh_asset(ground_id, plane_asset, mesh_t[0])

results.append({{'name': 'Ground', 'id': str(ground_id)}})

print(json.dumps(results))
""")
    _print_result(result)
    return result


async def step_1_create_player() -> str:
    """Create the Player entity — a sphere with physics."""
    print("\nStep 1: Creating Player entity...")
    comp_names = json.dumps(["Mesh", COLLIDER_COMP, RIGID_BODY_COMP, "Lua Script"])
    sphere_model = json.dumps(SPHERE_MODEL)
    result = await _async_run_editor_script(f"""
import azlmbr.editor as editor
import azlmbr.bus as bus
import azlmbr.entity as entity
import azlmbr.components as comp
import azlmbr.asset as asset
import azlmbr.math as math
import json
{_SET_MESH_ASSET_FUNC}
gt = entity.EntityType().Game
comp_names = json.loads({comp_names!r})

player_id = editor.ToolsApplicationRequestBus(
    bus.Broadcast, 'CreateNewEntity', azlmbr.entity.EntityId()
)
editor.EditorEntityAPIBus(bus.Event, 'SetName', player_id, 'Player')

mesh_type = None
for cn in comp_names:
    t = editor.EditorComponentAPIBus(
        bus.Broadcast, 'FindComponentTypeIdsByEntityType', [cn], gt
    )
    if t:
        editor.EditorComponentAPIBus(bus.Broadcast, 'AddComponentOfType', player_id, t[0])
        if cn == 'Mesh':
            mesh_type = t[0]

# Position above ground, scale down
comp.TransformBus(bus.Event, 'SetWorldTranslation', player_id, math.Vector3(0.0, 0.0, 2.0))
comp.TransformBus(bus.Event, 'SetLocalUniformScale', player_id, 0.5)

# Assign sphere mesh
sphere_path = json.loads({sphere_model!r})
sphere_asset = asset.AssetCatalogRequestBus(
    bus.Broadcast, 'GetAssetIdByPath', sphere_path, math.Uuid(), False
)
if mesh_type:
    _set_mesh_asset(player_id, sphere_asset, mesh_type)

print(json.dumps({{'name': 'Player', 'id': str(player_id)}}))
""")
    _print_result(result)
    return result


async def step_2_create_goal_zone() -> str:
    """Create the GoalZone trigger entity — a visible cube marker."""
    print("\nStep 2: Creating GoalZone entity...")
    comp_names = json.dumps([COLLIDER_COMP, "Mesh", "Lua Script"])
    cube_model = json.dumps(CUBE_MODEL)
    result = await _async_run_editor_script(f"""
import azlmbr.editor as editor
import azlmbr.bus as bus
import azlmbr.entity as entity
import azlmbr.components as comp
import azlmbr.asset as asset
import azlmbr.math as math
import json
{_SET_MESH_ASSET_FUNC}
gt = entity.EntityType().Game
comp_names = json.loads({comp_names!r})

goal_id = editor.ToolsApplicationRequestBus(
    bus.Broadcast, 'CreateNewEntity', azlmbr.entity.EntityId()
)
editor.EditorEntityAPIBus(bus.Event, 'SetName', goal_id, 'GoalZone')

mesh_type = None
for cn in comp_names:
    t = editor.EditorComponentAPIBus(
        bus.Broadcast, 'FindComponentTypeIdsByEntityType', [cn], gt
    )
    if t:
        editor.EditorComponentAPIBus(bus.Broadcast, 'AddComponentOfType', goal_id, t[0])
        if cn == 'Mesh':
            mesh_type = t[0]

comp.TransformBus(bus.Event, 'SetWorldTranslation', goal_id, math.Vector3(20.0, 0.0, 0.5))
comp.TransformBus(bus.Event, 'SetLocalUniformScale', goal_id, 3.0)

# Assign cube mesh so the goal zone is visible
cube_path = json.loads({cube_model!r})
cube_asset = asset.AssetCatalogRequestBus(
    bus.Broadcast, 'GetAssetIdByPath', cube_path, math.Uuid(), False
)
if mesh_type:
    _set_mesh_asset(goal_id, cube_asset, mesh_type)

print(json.dumps({{'name': 'GoalZone', 'id': str(goal_id)}}))
""")
    _print_result(result)
    return result


async def step_3_create_spawners() -> str:
    """Create the CrateSpawners parent with 4 child spawner entities."""
    print("\nStep 3: Creating CrateSpawners hierarchy...")
    result = await _async_run_editor_script("""
import azlmbr.editor as editor
import azlmbr.bus as bus
import azlmbr.entity as entity
import azlmbr.components as comp
import azlmbr.math as math
import json

parent_id = editor.ToolsApplicationRequestBus(
    bus.Broadcast, 'CreateNewEntity', azlmbr.entity.EntityId()
)
editor.EditorEntityAPIBus(bus.Event, 'SetName', parent_id, 'CrateSpawners')

positions = [
    (5.0, 0.0, 20.0),
    (10.0, 2.0, 22.0),
    (15.0, -2.0, 18.0),
    (8.0, 3.0, 25.0),
]
results = [{'name': 'CrateSpawners', 'id': str(parent_id)}]
for i, (x, y, z) in enumerate(positions):
    eid = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', parent_id)
    name = f'Spawner_{i:02d}'
    editor.EditorEntityAPIBus(bus.Event, 'SetName', eid, name)
    comp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(x, y, z))
    results.append({'name': name, 'id': str(eid)})

print(json.dumps(results))
""")
    _print_result(result)
    return result


async def step_4_create_crates() -> str:
    """Batch-create 4 FallingCrate entities with physics and cube meshes."""
    print("\nStep 4: Creating FallingCrate entities...")
    comp_names = json.dumps(["Mesh", COLLIDER_COMP, RIGID_BODY_COMP])
    cube_model = json.dumps(CUBE_MODEL)
    result = await _async_run_editor_script(f"""
import azlmbr.editor as editor
import azlmbr.bus as bus
import azlmbr.entity as entity
import azlmbr.components as comp
import azlmbr.asset as asset
import azlmbr.math as math
import json
{_SET_MESH_ASSET_FUNC}
gt = entity.EntityType().Game
root = azlmbr.entity.EntityId()
comp_names = json.loads({comp_names!r})

# Pre-resolve component type IDs
type_ids = []
mesh_type = None
for cn in comp_names:
    ids = editor.EditorComponentAPIBus(
        bus.Broadcast, 'FindComponentTypeIdsByEntityType', [cn], gt
    )
    if ids:
        type_ids.append(ids[0])
        if cn == 'Mesh':
            mesh_type = ids[0]

# Resolve cube model asset
cube_path = json.loads({cube_model!r})
cube_asset = asset.AssetCatalogRequestBus(
    bus.Broadcast, 'GetAssetIdByPath', cube_path, math.Uuid(), False
)

positions = [
    (5.0, 0.0, 20.0),
    (10.0, 2.0, 22.0),
    (15.0, -2.0, 18.0),
    (8.0, 3.0, 25.0),
]
results = []
for i, (x, y, z) in enumerate(positions):
    eid = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', root)
    name = f'FallingCrate_{{i:02d}}'
    editor.EditorEntityAPIBus(bus.Event, 'SetName', eid, name)
    comp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(x, y, z))
    for t in type_ids:
        editor.EditorComponentAPIBus(bus.Broadcast, 'AddComponentOfType', eid, t)
    if mesh_type:
        _set_mesh_asset(eid, cube_asset, mesh_type)
    results.append({{'name': name, 'id': str(eid)}})

print(json.dumps(results))
""")
    _print_result(result)
    return result


async def step_5_create_game_manager_and_camera() -> str:
    """Create GameManager (Lua Script) and FollowCamera (Camera)."""
    print("\nStep 5: Creating GameManager and FollowCamera...")
    result = await _async_run_editor_script("""
import azlmbr.editor as editor
import azlmbr.bus as bus
import azlmbr.entity as entity
import azlmbr.components as comp
import azlmbr.math as math
import json

gt = entity.EntityType().Game
root = azlmbr.entity.EntityId()

# GameManager
gm_id = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', root)
editor.EditorEntityAPIBus(bus.Event, 'SetName', gm_id, 'GameManager')
lua_t = editor.EditorComponentAPIBus(
    bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['Lua Script'], gt
)
if lua_t:
    editor.EditorComponentAPIBus(bus.Broadcast, 'AddComponentOfType', gm_id, lua_t[0])

# FollowCamera — positioned behind and above the player, angled down
cam_id = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', root)
editor.EditorEntityAPIBus(bus.Event, 'SetName', cam_id, 'FollowCamera')
cam_t = editor.EditorComponentAPIBus(
    bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['Camera'], gt
)
if cam_t:
    editor.EditorComponentAPIBus(bus.Broadcast, 'AddComponentOfType', cam_id, cam_t[0])
comp.TransformBus(bus.Event, 'SetWorldTranslation', cam_id, math.Vector3(0.0, -15.0, 10.0))
# Pitch down ~30 degrees to look at the play area
comp.TransformBus(bus.Event, 'SetLocalRotation', cam_id, math.Vector3(-0.52, 0.0, 0.0))

print(json.dumps([
    {'name': 'GameManager', 'id': str(gm_id)},
    {'name': 'FollowCamera', 'id': str(cam_id)},
]))
""")
    _print_result(result)
    return result


async def step_6_verify() -> str:
    """List all entities and verify component presence."""
    print("\nStep 6: Verifying scene...")
    expected = json.dumps(
        {
            "Sun": ["Directional Light"],
            "Ground": ["Mesh", COLLIDER_COMP],
            "Player": ["Mesh", COLLIDER_COMP, RIGID_BODY_COMP, "Lua Script"],
            "GoalZone": [COLLIDER_COMP, "Mesh", "Lua Script"],
            "FallingCrate_00": ["Mesh", COLLIDER_COMP, RIGID_BODY_COMP],
            "FallingCrate_01": ["Mesh", COLLIDER_COMP, RIGID_BODY_COMP],
            "FallingCrate_02": ["Mesh", COLLIDER_COMP, RIGID_BODY_COMP],
            "FallingCrate_03": ["Mesh", COLLIDER_COMP, RIGID_BODY_COMP],
            "GameManager": ["Lua Script"],
            "FollowCamera": ["Camera"],
        }
    )
    result = await _async_run_editor_script(f"""
import azlmbr.editor as editor
import azlmbr.entity as entity
import azlmbr.bus as bus
import json

gt = entity.EntityType().Game
expected = json.loads({expected!r})

# Build type ID cache for all unique component names
all_comp_names = set()
for comps in expected.values():
    all_comp_names.update(comps)

check_types = {{}}
for cn in all_comp_names:
    ids = editor.EditorComponentAPIBus(
        bus.Broadcast, 'FindComponentTypeIdsByEntityType', [cn], gt
    )
    if ids:
        check_types[cn] = ids[0]

report = {{}}
all_ok = True
for ent_name, comps in expected.items():
    sf = entity.SearchFilter()
    sf.names = [ent_name]
    eids = entity.SearchBus(bus.Broadcast, 'SearchEntities', sf)
    if not eids:
        report[ent_name] = 'MISSING'
        all_ok = False
        continue
    eid = eids[0]
    status = {{}}
    for comp_name in comps:
        t = check_types.get(comp_name)
        if t:
            has = editor.EditorComponentAPIBus(
                bus.Broadcast, 'HasComponentOfType', eid, t
            )
            status[comp_name] = 'ok' if has else 'MISSING'
            if not has:
                all_ok = False
        else:
            status[comp_name] = 'TYPE_NOT_FOUND'
            all_ok = False
    report[ent_name] = status

print(json.dumps({{'all_ok': all_ok, 'entities': report}}, indent=2))
""")
    _print_result(result)
    return result


async def enter_game_mode(duration: float = 5.0) -> None:
    """Enter game mode, wait, then exit."""
    print(f"\nEntering game mode for {duration}s...")
    result = await _async_run_editor_script("""
import azlmbr.legacy.general as general
general.enter_game_mode()
print('Entered game mode')
""")
    print(f"  {result}")

    await asyncio.sleep(duration)

    result = await _async_run_editor_script("""
import azlmbr.legacy.general as general
general.exit_game_mode()
print('Exited game mode')
""")
    print(f"  {result}")


def _print_result(result: str) -> None:
    """Pretty-print a JSON result or raw string."""
    try:
        data = json.loads(result)
        if isinstance(data, dict) and data.get("status") == "error":
            print(f"  ERROR: {data.get('message', result)}")
        elif isinstance(data, list):
            for item in data:
                name = item.get("name", "?")
                eid = item.get("id", "?")
                print(f"  {name}: {eid}")
        elif isinstance(data, dict):
            for key, val in data.items():
                print(f"  {key}: {val}")
        else:
            print(f"  {result}")
    except (json.JSONDecodeError, TypeError):
        print(f"  {result}")


async def run(args: argparse.Namespace) -> int:
    if not await check_capabilities():
        return 1

    if args.cleanup:
        await cleanup_entities()

    await step_0_setup_environment()
    await step_1_create_player()
    await step_2_create_goal_zone()
    await step_3_create_spawners()
    await step_4_create_crates()
    await step_5_create_game_manager_and_camera()
    result = await step_6_verify()

    try:
        data = json.loads(result)
        if not data.get("all_ok"):
            print("\nWARNING: Some components are missing — check output above.")
    except (json.JSONDecodeError, TypeError):
        pass

    # Save the level so work isn't lost if the editor crashes
    print("\nSaving level...")
    save_result = await _async_run_editor_script(
        "import azlmbr.legacy.general as general\ngeneral.save_level()\nprint('Level saved')\n"
    )
    print(f"  {save_result}")

    if args.enter_game_mode:
        await enter_game_mode(args.game_mode_duration)

    print("\nDone.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Example 4 (Scripted Mini-Game) against a running O3DE Editor."
    )
    parser.add_argument(
        "--enter-game-mode",
        action="store_true",
        help="Enter game mode after creating the scene",
    )
    parser.add_argument(
        "--game-mode-duration",
        type=float,
        default=5.0,
        help="Seconds to stay in game mode (default: 5)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete any existing example entities before creating new ones",
    )
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
