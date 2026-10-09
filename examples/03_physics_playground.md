# Example 3: Physics Playground

Add dynamic physics objects to a scene — crates, balls, and trigger zones.

## Prerequisites

- Scene from [Example 2](02_build_scene.md) or any level with a ground plane
- PhysX gem enabled in the project
- O3DE Editor running with AiCompanion + EditorPythonBindings gems

> **Editor required:** Call `get_capabilities()` first to verify editor
> connectivity.

## Steps

### 1. Create a dynamic crate

```json
{"tool": "create_entity", "arguments": {"name": "Crate"}}
{"tool": "add_component", "arguments": {"entity_id": "<crate_id>", "component_type": "Mesh"}}
{"tool": "add_component", "arguments": {"entity_id": "<crate_id>", "component_type": "PhysX Primitive Collider"}}
{"tool": "add_component", "arguments": {"entity_id": "<crate_id>", "component_type": "PhysX Dynamic Rigid Body"}}
```

Position it above the ground so it falls when play mode starts:

```json
{"tool": "set_transform", "arguments": {"entity_id": "<crate_id>", "position": [0.0, 0.0, 10.0]}}
```

### 2. Batch-create a stack of crates

More efficient than individual calls — a single `run_editor_python`:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.bus as bus\nimport azlmbr.components as comp\nimport azlmbr.entity as entity\nimport azlmbr.math as math\nimport json\n\nparent = entity.EntityId()\nresults = []\nfor i in range(5):\n    eid = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', parent)\n    editor.EditorEntityAPIBus(bus.Event, 'SetName', eid, f'StackCrate_{i:02d}')\n    comp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(0.0, 0.0, 1.0 + i * 1.1))\n    results.append({'name': f'StackCrate_{i:02d}', 'id': str(eid)})\nprint(json.dumps(results))"
  }
}
```

Then add physics components to each:

```json
{"tool": "add_component", "arguments": {"entity_id": "<id_0>", "component_type": "Mesh"}}
{"tool": "add_component", "arguments": {"entity_id": "<id_0>", "component_type": "PhysX Primitive Collider"}}
{"tool": "add_component", "arguments": {"entity_id": "<id_0>", "component_type": "PhysX Dynamic Rigid Body"}}
```

Repeat for each crate, or use a batch script:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.bus as bus\nimport azlmbr.entity as entity\n\nsearch = entity.SearchFilter()\nsearch.names = ['StackCrate_*']\nids = entity.SearchBus(bus.Broadcast, 'SearchEntities', search)\n\nmesh_types = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['Mesh'], entity.EntityType().Game)\ncollider_types = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['PhysX Primitive Collider'], entity.EntityType().Game)\nrb_types = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['PhysX Dynamic Rigid Body'], entity.EntityType().Game)\n\nfor eid in ids:\n    for type_id in [mesh_types[0], collider_types[0], rb_types[0]]:\n        editor.EditorComponentAPIBus(bus.Broadcast, 'AddComponentOfType', eid, type_id)\n\nprint(f'Added components to {len(ids)} crates')"
  }
}
```

### 3. Create a trigger zone

A trigger zone detects when entities enter/exit without blocking them:

```json
{"tool": "create_entity", "arguments": {"name": "GoalZone"}}
{"tool": "add_component", "arguments": {"entity_id": "<zone_id>", "component_type": "PhysX Primitive Collider"}}
```

Configure it as a trigger:

```json
{"tool": "set_component_property", "arguments": {"entity_id": "<zone_id>", "component_type": "PhysX Primitive Collider", "property_path": "Collider Configuration|Trigger", "value": "true"}}
```

### 4. Create a bouncing ball

```json
{"tool": "create_entity", "arguments": {"name": "Ball"}}
{"tool": "add_component", "arguments": {"entity_id": "<ball_id>", "component_type": "Mesh"}}
{"tool": "add_component", "arguments": {"entity_id": "<ball_id>", "component_type": "PhysX Primitive Collider"}}
{"tool": "add_component", "arguments": {"entity_id": "<ball_id>", "component_type": "PhysX Dynamic Rigid Body"}}
```

Position it, and set the collider shape to a sphere (the `Shape` value `0` is
the engine's `ShapeType` Sphere):

```json
{"tool": "set_transform", "arguments": {"entity_id": "<ball_id>", "position": [5.0, 0.0, 15.0]}}
{"tool": "set_component_property", "arguments": {"entity_id": "<ball_id>", "component_type": "PhysX Primitive Collider", "property_path": "Shape Configuration|Shape", "value": "0"}}
```

### 5. Verify physics setup

```json
{"tool": "list_entities"}
```

```json
{"tool": "get_entity_components", "arguments": {"entity_id": "<crate_id>"}}
```

Expected components: `Mesh`, `PhysX Primitive Collider`, `PhysX Dynamic Rigid Body`, `Transform`.

## Physics Summary

| Behavior | Components Needed |
|----------|-------------------|
| Static (walls, floor) | Mesh + PhysX Primitive Collider |
| Dynamic (crates, balls) | Mesh + PhysX Primitive Collider + PhysX Dynamic Rigid Body |
| Trigger (zones) | PhysX Primitive Collider (IsTrigger=True) |
| Kinematic (moving platforms) | PhysX Primitive Collider + PhysX Dynamic Rigid Body (Kinematic=True) |

Next: [Example 4: Scripted Game](04_scripted_game.md)
