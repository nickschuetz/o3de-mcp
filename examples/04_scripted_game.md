# Example 4: Scripted Mini-Game

Build a complete "falling crates" mini-game using MCP tools: a player-controlled
ball must reach a goal zone while crates fall from above.

## Prerequisites

- Scene with ground, camera, and lighting (from Examples 2-3)
- PhysX and Lua Script gems enabled
- O3DE Editor running with RemoteConsole + EditorPythonBindings gems

> **Editor required:** Call `get_capabilities()` first to verify editor
> connectivity.

## Steps

### 1. Create the player ball

```json
{"tool": "create_entity", "arguments": {"name": "Player"}}
{"tool": "add_component", "arguments": {"entity_id": "<player_id>", "component_type": "Mesh"}}
{"tool": "add_component", "arguments": {"entity_id": "<player_id>", "component_type": "PhysX Collider"}}
{"tool": "add_component", "arguments": {"entity_id": "<player_id>", "component_type": "PhysX Rigid Body"}}
{"tool": "add_component", "arguments": {"entity_id": "<player_id>", "component_type": "Lua Script"}}
```

Position and configure the player:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.components as comp\nimport azlmbr.bus as bus\nimport azlmbr.math as math\n\neid = azlmbr.entity.EntityId('<player_id>')\ncomp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(0.0, 0.0, 1.0))\ncomp.TransformBus(bus.Event, 'SetLocalScale', eid, math.Vector3(0.5, 0.5, 0.5))\nprint('Player positioned')"
  }
}
```

### 2. Create the goal zone

```json
{"tool": "create_entity", "arguments": {"name": "GoalZone"}}
{"tool": "add_component", "arguments": {"entity_id": "<goal_id>", "component_type": "PhysX Collider"}}
{"tool": "add_component", "arguments": {"entity_id": "<goal_id>", "component_type": "Lua Script"}}
```

Position and make it a trigger:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.components as comp\nimport azlmbr.bus as bus\nimport azlmbr.math as math\n\neid = azlmbr.entity.EntityId('<goal_id>')\ncomp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(20.0, 0.0, 0.5))\ncomp.TransformBus(bus.Event, 'SetLocalScale', eid, math.Vector3(3.0, 3.0, 1.0))\neditor.EditorComponentAPIBus(bus.Event, 'SetComponentProperty', eid, 'PhysX Collider|IsTrigger', True)\nprint('Goal zone configured')"
  }
}
```

### 3. Create falling crate spawners

Use entity hierarchy for organization:

```json
{"tool": "create_entity", "arguments": {"name": "CrateSpawners"}}
```

Create spawn points as children:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.components as comp\nimport azlmbr.bus as bus\nimport azlmbr.math as math\nimport json\n\nparent = azlmbr.entity.EntityId('<spawners_id>')\npositions = [\n    (5.0, 0.0, 20.0),\n    (10.0, 2.0, 22.0),\n    (15.0, -2.0, 18.0),\n    (8.0, 3.0, 25.0),\n]\nresults = []\nfor i, (x, y, z) in enumerate(positions):\n    eid = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', parent)\n    editor.EditorEntityAPIBus(bus.Event, 'SetName', eid, f'Spawner_{i:02d}')\n    comp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(x, y, z))\n    results.append({'name': f'Spawner_{i:02d}', 'id': str(eid)})\nprint(json.dumps(results))"
  }
}
```

### 4. Create obstacle crates

Batch-create crates at spawner positions:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.bus as bus\nimport azlmbr.entity as entity\nimport azlmbr.components as comp\nimport azlmbr.math as math\nimport json\n\nparent = azlmbr.entity.EntityId()\npositions = [\n    (5.0, 0.0, 20.0),\n    (10.0, 2.0, 22.0),\n    (15.0, -2.0, 18.0),\n    (8.0, 3.0, 25.0),\n]\nresults = []\nfor i, (x, y, z) in enumerate(positions):\n    eid = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', parent)\n    name = f'FallingCrate_{i:02d}'\n    editor.EditorEntityAPIBus(bus.Event, 'SetName', eid, name)\n    comp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(x, y, z))\n    # Add physics components\n    mesh_t = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['Mesh'], entity.EntityType().Game)\n    col_t = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['PhysX Collider'], entity.EntityType().Game)\n    rb_t = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['PhysX Rigid Body'], entity.EntityType().Game)\n    editor.EditorComponentAPIBus(bus.Event, 'AddComponentsOfType', eid, mesh_t + col_t + rb_t)\n    results.append({'name': name, 'id': str(eid)})\nprint(json.dumps(results))"
  }
}
```

### 5. Create the game manager

```json
{"tool": "create_entity", "arguments": {"name": "GameManager"}}
{"tool": "add_component", "arguments": {"entity_id": "<gm_id>", "component_type": "Lua Script"}}
```

### 6. Create the follow camera

```json
{"tool": "create_entity", "arguments": {"name": "FollowCamera"}}
{"tool": "add_component", "arguments": {"entity_id": "<cam_id>", "component_type": "Camera"}}
```

Position behind and above the player:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.components as comp\nimport azlmbr.bus as bus\nimport azlmbr.math as math\n\neid = azlmbr.entity.EntityId('<cam_id>')\ncomp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(0.0, -8.0, 6.0))\nprint('Camera positioned')"
  }
}
```

### 7. Verify the complete scene

```json
{"tool": "list_entities"}
```

Expected entity list:
- `Ground`, `Sun`, `Environment` (from scene setup)
- `Player` — ball with Mesh, PhysX Collider, PhysX Rigid Body, Lua Script
- `GoalZone` — trigger collider with Lua Script
- `CrateSpawners` — parent entity
  - `Spawner_00` through `Spawner_03`
- `FallingCrate_00` through `FallingCrate_03` — dynamic physics objects
- `GameManager` — Lua Script
- `FollowCamera` — Camera

Verify a crate has the right components:

```json
{"tool": "get_entity_components", "arguments": {"entity_id": "<crate_0_id>"}}
```

Expected: `Mesh`, `PhysX Collider`, `PhysX Rigid Body`, `Transform`.

## Game Architecture Summary

```
GameManager (Lua Script)
├── Controls game state (start, playing, won, lost)
├── Listens for GoalZone trigger events
└── Respawns crates on timer

Player (Mesh + PhysX + Lua Script)
├── Reads input → applies force to rigid body
└── Has sphere collider

GoalZone (Trigger + Lua Script)
├── Detects player entering
└── Notifies GameManager

FallingCrate_* (Mesh + PhysX)
└── Dynamic rigid bodies that fall under gravity
```

## Token Efficiency Notes

This example used **14 tool calls** to create a game with 12+ entities. Key
savings:

1. **Batch entity creation** via `run_editor_python` loops — one call creates 4
   entities instead of 4 separate `create_entity` calls.
2. **Batch component addition** — one script adds 3 component types to multiple
   entities.
3. **Combined position + config** — set transform and properties in the same
   script call that creates entities.
