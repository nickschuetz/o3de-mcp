# Example 2: Build a Complete Scene

Construct a playable scene with environment, lighting, player camera, and
static geometry — all through MCP tool calls.

## Prerequisites

- O3DE Editor running with your project loaded
- RemoteConsole and EditorPythonBindings gems active

## Steps

### 1. Open the level

```json
{"tool": "load_level", "arguments": {"level_path": "Levels/Main"}}
```

### 2. Check existing entities

```json
{"tool": "list_entities"}
```

Review the response. A fresh level typically has no entities or just a default
camera.

### 3. Create the sky and environment

```json
{"tool": "create_entity", "arguments": {"name": "Environment"}}
```

Capture the returned entity ID, then:

```json
{"tool": "add_component", "arguments": {"entity_id": "<env_id>", "component_type": "HDRi Skybox"}}
{"tool": "add_component", "arguments": {"entity_id": "<env_id>", "component_type": "Global Skylight (IBL)"}}
```

### 4. Add a directional light (sun)

```json
{"tool": "create_entity", "arguments": {"name": "Sun"}}
{"tool": "add_component", "arguments": {"entity_id": "<sun_id>", "component_type": "Directional Light"}}
```

### 5. Create the ground plane

```json
{"tool": "create_entity", "arguments": {"name": "Ground"}}
{"tool": "add_component", "arguments": {"entity_id": "<ground_id>", "component_type": "Mesh"}}
{"tool": "add_component", "arguments": {"entity_id": "<ground_id>", "component_type": "Material"}}
{"tool": "add_component", "arguments": {"entity_id": "<ground_id>", "component_type": "PhysX Collider"}}
```

Set the ground mesh and scale via script:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.components as comp\nimport azlmbr.bus as bus\nimport azlmbr.math as math\n\neid = azlmbr.entity.EntityId('<ground_id>')\ncomp.TransformBus(bus.Event, 'SetLocalScale', eid, math.Vector3(50.0, 50.0, 1.0))"
  }
}
```

### 6. Add a player camera

```json
{"tool": "create_entity", "arguments": {"name": "PlayerCamera"}}
{"tool": "add_component", "arguments": {"entity_id": "<cam_id>", "component_type": "Camera"}}
```

Position the camera:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.components as comp\nimport azlmbr.bus as bus\nimport azlmbr.math as math\n\neid = azlmbr.entity.EntityId('<cam_id>')\ncomp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(0.0, -10.0, 5.0))"
  }
}
```

### 7. Add some static objects

```json
{"tool": "create_entity", "arguments": {"name": "Building_01"}}
{"tool": "add_component", "arguments": {"entity_id": "<bldg_id>", "component_type": "Mesh"}}
{"tool": "add_component", "arguments": {"entity_id": "<bldg_id>", "component_type": "Material"}}
{"tool": "add_component", "arguments": {"entity_id": "<bldg_id>", "component_type": "PhysX Collider"}}
```

### 8. Verify the scene

```json
{"tool": "list_entities"}
```

Expected: `Environment`, `Sun`, `Ground`, `PlayerCamera`, `Building_01`.

```json
{"tool": "get_entity_components", "arguments": {"entity_id": "<ground_id>"}}
```

Expected: `Mesh`, `Material`, `PhysX Collider`, `Transform`.

## Result

You now have a level with:
- Sky + global illumination
- Directional sun light
- Collidable ground plane
- Positioned player camera
- A static building

Next: [Example 3: Add Physics](03_physics_playground.md)
