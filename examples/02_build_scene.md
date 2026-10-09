# Example 2: Build a Complete Scene

Construct a playable scene with environment, lighting, player camera, and
static geometry — all through MCP tool calls.

## Prerequisites

- O3DE Editor running with your project loaded
- AiCompanion and EditorPythonBindings gems active

> **Editor required:** These tools need a running editor. Call
> `get_capabilities()` first to verify the editor is connected. If it's
> not available, see [Example 6](06_cli_only_workflow.md) for CLI-only options.

## Steps

### 1. Open the level

```json
{"tool": "load_level", "arguments": {"level_path": "Levels/Main"}}
```

### 2. Check existing entities

```json
{"tool": "list_entities"}
```

Review the response. A level made by `create_level` with its default template
(`Prefabs/Default_Level.prefab`) already holds an `Atom Default Environment`
entity with `Sun`, `Ground`, `Camera`, `Grid`, `Shader Ball` and `Global Sky`
children; a level made from an empty template has no entities.

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
{"tool": "add_component", "arguments": {"entity_id": "<ground_id>", "component_type": "PhysX Primitive Collider"}}
```

Give it a flat mesh and size it. The engine's 4 x 4 m ground plane, scaled
uniformly by 12.5, is a 50 x 50 m ground. `set_transform` also takes a
non-uniform `[x, y, z]` scale on the AiCompanion gem 0.6.0 (gem API 0.5.0) and
later, which applies it through the engine's Non-uniform Scale component; older
gems refuse a non-uniform scale with `non_uniform_scale_unsupported`.

```json
{"tool": "assign_asset", "arguments": {"entity_id": "<ground_id>", "component_type": "Mesh", "property_path": "Controller|Configuration|Model Asset", "asset_path": "objects/shaderball/ground_plane_4x4m.fbx.azmodel"}}
{"tool": "set_transform", "arguments": {"entity_id": "<ground_id>", "position": [0, 0, 0], "scale": [12.5, 12.5, 12.5]}}
```

The collider's box keeps its own size; the entity's uniform scale multiplies it.
For a flat collider, set the PhysX Primitive Collider's box dimensions on the
component itself rather than through the scale.

### 6. Add a player camera

```json
{"tool": "create_entity", "arguments": {"name": "PlayerCamera"}}
{"tool": "add_component", "arguments": {"entity_id": "<cam_id>", "component_type": "Camera"}}
```

Position the camera:

```json
{"tool": "set_transform", "arguments": {"entity_id": "<cam_id>", "position": [0.0, -10.0, 5.0]}}
```

### 7. Add some static objects

```json
{"tool": "create_entity", "arguments": {"name": "Building_01"}}
{"tool": "add_component", "arguments": {"entity_id": "<bldg_id>", "component_type": "Mesh"}}
{"tool": "add_component", "arguments": {"entity_id": "<bldg_id>", "component_type": "Material"}}
{"tool": "add_component", "arguments": {"entity_id": "<bldg_id>", "component_type": "PhysX Primitive Collider"}}
```

### 8. Verify the scene

```json
{"tool": "list_entities"}
```

Expected: `Environment`, `Sun`, `Ground`, `PlayerCamera`, `Building_01`,
alongside any entities the level started with.

```json
{"tool": "get_entity_components", "arguments": {"entity_id": "<ground_id>"}}
```

Expected: `Mesh`, `Material`, `PhysX Primitive Collider`, `Transform`.

## Result

You now have a level with:
- Sky + global illumination
- Directional sun light
- Collidable ground plane
- Positioned player camera
- A static building

Next: [Example 3: Add Physics](03_physics_playground.md)
