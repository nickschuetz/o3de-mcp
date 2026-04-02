# Example 3: Physics Playground

Add dynamic physics objects to a scene — crates, balls, and trigger zones.

## Prerequisites

- Scene from [Example 2](02_build_scene.md) or any level with a ground plane
- PhysX gem enabled in the project

## Steps

### 1. Create a dynamic crate

```json
{"tool": "create_entity", "arguments": {"name": "Crate"}}
{"tool": "add_component", "arguments": {"entity_id": "<crate_id>", "component_type": "Mesh"}}
{"tool": "add_component", "arguments": {"entity_id": "<crate_id>", "component_type": "PhysX Collider"}}
{"tool": "add_component", "arguments": {"entity_id": "<crate_id>", "component_type": "PhysX Rigid Body"}}
```

Position it above the ground so it falls when play mode starts:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.components as comp\nimport azlmbr.bus as bus\nimport azlmbr.math as math\n\neid = azlmbr.entity.EntityId('<crate_id>')\ncomp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(0.0, 0.0, 10.0))"
  }
}
```

### 2. Batch-create a stack of crates

More efficient than individual calls — a single `run_editor_python`:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.bus as bus\nimport azlmbr.components as comp\nimport azlmbr.math as math\nimport json\n\nparent = azlmbr.entity.EntityId()\nresults = []\nfor i in range(5):\n    eid = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', parent)\n    editor.EditorEntityAPIBus(bus.Event, 'SetName', eid, f'StackCrate_{i:02d}')\n    comp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(0.0, 0.0, 1.0 + i * 1.1))\n    results.append({'name': f'StackCrate_{i:02d}', 'id': str(eid)})\nprint(json.dumps(results))"
  }
}
```

Then add physics components to each:

```json
{"tool": "add_component", "arguments": {"entity_id": "<id_0>", "component_type": "Mesh"}}
{"tool": "add_component", "arguments": {"entity_id": "<id_0>", "component_type": "PhysX Collider"}}
{"tool": "add_component", "arguments": {"entity_id": "<id_0>", "component_type": "PhysX Rigid Body"}}
```

Repeat for each crate, or use a batch script:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.bus as bus\nimport azlmbr.entity as entity\n\nsearch = entity.SearchFilter()\nsearch.names = ['StackCrate_*']\nids = entity.SearchBus(bus.Broadcast, 'SearchEntities', search)\n\nfor eid in ids:\n    mesh_types = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['Mesh'], entity.EntityType().Game)\n    collider_types = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['PhysX Collider'], entity.EntityType().Game)\n    rb_types = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['PhysX Rigid Body'], entity.EntityType().Game)\n    editor.EditorComponentAPIBus(bus.Event, 'AddComponentsOfType', eid, mesh_types + collider_types + rb_types)\n\nprint(f'Added components to {len(ids)} crates')"
  }
}
```

### 3. Create a trigger zone

A trigger zone detects when entities enter/exit without blocking them:

```json
{"tool": "create_entity", "arguments": {"name": "GoalZone"}}
{"tool": "add_component", "arguments": {"entity_id": "<zone_id>", "component_type": "PhysX Collider"}}
```

Configure it as a trigger:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.bus as bus\n\neid = azlmbr.entity.EntityId('<zone_id>')\neditor.EditorComponentAPIBus(bus.Event, 'SetComponentProperty', eid, 'PhysX Collider|IsTrigger', True)\nprint('GoalZone configured as trigger')"
  }
}
```

### 4. Create a bouncing ball

```json
{"tool": "create_entity", "arguments": {"name": "Ball"}}
{"tool": "add_component", "arguments": {"entity_id": "<ball_id>", "component_type": "Mesh"}}
{"tool": "add_component", "arguments": {"entity_id": "<ball_id>", "component_type": "PhysX Collider"}}
{"tool": "add_component", "arguments": {"entity_id": "<ball_id>", "component_type": "PhysX Rigid Body"}}
```

Set the collider shape to sphere and configure restitution for bouncing:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.bus as bus\nimport azlmbr.components as comp\nimport azlmbr.math as math\n\neid = azlmbr.entity.EntityId('<ball_id>')\ncomp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(5.0, 0.0, 15.0))\neditor.EditorComponentAPIBus(bus.Event, 'SetComponentProperty', eid, 'PhysX Collider|Shape|Shape Configuration|Sphere', True)\nprint('Ball configured')"
  }
}
```

### 5. Verify physics setup

```json
{"tool": "list_entities"}
```

```json
{"tool": "get_entity_components", "arguments": {"entity_id": "<crate_id>"}}
```

Expected components: `Mesh`, `PhysX Collider`, `PhysX Rigid Body`, `Transform`.

## Physics Summary

| Behavior | Components Needed |
|----------|-------------------|
| Static (walls, floor) | Mesh + PhysX Collider |
| Dynamic (crates, balls) | Mesh + PhysX Collider + PhysX Rigid Body |
| Trigger (zones) | PhysX Collider (IsTrigger=True) |
| Kinematic (moving platforms) | PhysX Collider + PhysX Rigid Body (Kinematic=True) |

Next: [Example 4: Scripted Game](04_scripted_game.md)
