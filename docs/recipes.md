# Recipes

Composable patterns for common O3DE game development tasks. Each recipe is a
self-contained sequence of tool calls that can be combined to build larger
workflows.

---

## Project Setup

### Recipe: Capability-first workflow

Always start by checking what's available:

```
1. get_capabilities()          → check editor + CLI status
2. list_templates()            → see available project/gem templates
```

If the editor is unreachable, stick to project tools. If the CLI is also
missing, set `O3DE_ENGINE_PATH` and try again.

### Recipe: New project from scratch

> **Platform note:** Replace the example path with an appropriate absolute path
> for your OS — e.g. `/home/user/projects/MyGame` (Linux),
> `~/projects/MyGame` (macOS), or `C:\Users\YourName\projects\MyGame` (Windows).

```
1. get_capabilities()          → verify engine is found
2. list_templates()            → discover templates
3. create_project(name="MyGame", path="<your_projects_dir>/MyGame")
4. enable_gem(gem_name="PhysX", project_path="<your_projects_dir>/MyGame")
5. enable_gem(gem_name="EditorPythonBindings", project_path="<your_projects_dir>/MyGame")
6. enable_gem(gem_name="AiCompanion", project_path="<your_projects_dir>/MyGame")
7. build_project(project_path="<your_projects_dir>/MyGame", config="profile")
```

> Always enable `AiCompanion` and `EditorPythonBindings`. They are required
> for the editor tools to function.

### Recipe: Verify environment

```
1. get_capabilities()          → full status check
2. get_engine_info()           → confirms engine is found
3. list_projects()             → see registered projects
4. list_gems()                 → see available gems
```

### Recipe: Create and register a custom gem

```
1. create_gem(name="MyGem", path="<your_gems_dir>/MyGem")
2. register_gem(gem_path="<your_gems_dir>/MyGem", project_path="<project_path>")
3. enable_gem(gem_name="MyGem", project_path="<project_path>")
4. build_project(project_path="<project_path>")
```

### Recipe: Export project for distribution

```
1. build_project(project_path="<project_path>", config="release")
2. export_project(project_path="<project_path>", output_path="<output_dir>", config="release")
```

### Recipe: Remove unwanted gems

```
1. list_project_gems(project_path="<project_path>")  → see what's enabled
2. disable_gem(gem_name="UnneededGem", project_path="<project_path>")
3. build_project(project_path="<project_path>")
```

---

## Scene Construction

### Recipe: Empty scene with camera and light

```
1. load_level(level_path="Levels/Main")
2. create_entity(name="MainCamera")
3. add_component(entity_id=<camera_id>, component_type="Camera")
4. create_entity(name="DirectionalLight")
5. add_component(entity_id=<light_id>, component_type="Directional Light")
```

### Recipe: Static mesh object

```
1. create_entity(name="Ground")
2. add_component(entity_id=<id>, component_type="Mesh")
3. add_component(entity_id=<id>, component_type="Material")
```

### Recipe: Physics-enabled object

```
1. create_entity(name="Crate")
2. add_component(entity_id=<id>, component_type="Mesh")
3. add_component(entity_id=<id>, component_type="PhysX Primitive Collider")
4. add_component(entity_id=<id>, component_type="PhysX Dynamic Rigid Body")
```

### Recipe: Entity hierarchy (parent-child)

```
1. create_entity(name="Vehicle")                            → parent_id
2. create_entity(name="Chassis", parent_id=<parent_id>)     → child 1
3. create_entity(name="Wheel_FL", parent_id=<parent_id>)    → child 2
4. create_entity(name="Wheel_FR", parent_id=<parent_id>)    → child 3
```

---

## Lighting

### Recipe: Three-point lighting setup

```
1. create_entity(name="KeyLight")
2. add_component(entity_id=<id>, component_type="Directional Light")
3. create_entity(name="FillLight")
4. add_component(entity_id=<id>, component_type="Point Light")
5. create_entity(name="RimLight")
6. add_component(entity_id=<id>, component_type="Spot Light")
```

### Recipe: Skybox and global illumination

```
1. create_entity(name="Sky")
2. add_component(entity_id=<id>, component_type="HDRi Skybox")
3. add_component(entity_id=<id>, component_type="Global Skylight (IBL)")
4. create_entity(name="Sun")
5. add_component(entity_id=<id>, component_type="Directional Light")
```

---

## Physics

### Recipe: Static collider (walls, floors)

```
1. create_entity(name="Wall")
2. add_component(entity_id=<id>, component_type="Mesh")
3. add_component(entity_id=<id>, component_type="PhysX Primitive Collider")
```

> No Rigid Body = static. The collider alone makes it solid but immovable.

### Recipe: Dynamic rigid body (crates, balls)

```
1. create_entity(name="Ball")
2. add_component(entity_id=<id>, component_type="Mesh")
3. add_component(entity_id=<id>, component_type="PhysX Primitive Collider")
4. add_component(entity_id=<id>, component_type="PhysX Dynamic Rigid Body")
```

### Recipe: Trigger volume (invisible zone)

```
1. create_entity(name="WinZone")
2. add_component(entity_id=<id>, component_type="PhysX Primitive Collider")
3. set_component_property(entity_id=<id>, component_type="PhysX Primitive Collider",
                          property_path="Collider Configuration|Trigger", value="true")
```

---

## Scripting

### Recipe: Attach Lua script to entity

```
1. create_entity(name="GameManager")
2. add_component(entity_id=<id>, component_type="Lua Script")
```

### Recipe: Set entity transform (position/rotation/scale)

```
1. set_transform(entity_id=<id>, position=[10.0, 5.0, 0.0])
2. set_transform(entity_id=<id>, rotation=[0.0, 0.0, 0.7071068, 0.7071068], scale=[2.0, 2.0, 2.0])
3. get_transform(entity_id=<id>)               → read it back
```

> Only the parts you pass change. `rotation` is an `[x, y, z, w]` quaternion
> (this one turns 90 degrees about Z). A non-uniform `scale` such as
> `[4.0, 4.0, 0.1]` works on the AiCompanion gem 0.6.0 (gem API 0.5.0) and
> later, through the engine's Non-uniform Scale component; older gems refuse it
> with `non_uniform_scale_unsupported`.

### Recipe: Set mesh asset on entity

```
assign_asset(entity_id=<id>, component_type="Mesh",
             property_path="Controller|Configuration|Model Asset",
             asset_path="objects/shaderball/ground_plane_4x4m.fbx.azmodel")
```

> The entity needs a Mesh component first (`add_component`). `asset_path` is
> the product path in the asset catalog. `assign_asset` reads the property back
> and reports only an assignment that holds; an unknown asset, a component the
> entity lacks, or a value that does not stick comes back as an error.

### Recipe: Batch-create multiple entities

```python
# Use via run_editor_python — efficient single call
import azlmbr.editor as editor
import azlmbr.bus as bus
import azlmbr.entity as entity
import json

entities = ['Tree_01', 'Tree_02', 'Tree_03', 'Rock_01', 'Rock_02']
parent = entity.EntityId()  # an empty id: create at the level root
results = []
for name in entities:
    eid = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', parent)
    editor.EditorEntityAPIBus(bus.Event, 'SetName', eid, name)
    results.append({'name': name, 'id': str(eid)})
print(json.dumps(results))
```

---

## Workflow Patterns

### Pattern: Discover-then-act

Always query state before modifying it to avoid duplicates and errors:

```
1. list_entities()                              → check what exists
2. get_entity_components(entity_id=<id>)        → check current components
3. add_component(...)                           → add only what's missing
```

### Pattern: Level bootstrap

Complete sequence to set up a playable level from empty:

```
1.  load_level(level_path="Levels/Main")
2.  create_entity(name="Sky")
3.  add_component(<sky>, "HDRi Skybox")
4.  add_component(<sky>, "Global Skylight (IBL)")
5.  create_entity(name="Sun")
6.  add_component(<sun>, "Directional Light")
7.  create_entity(name="Ground")
8.  add_component(<ground>, "Mesh")
9.  add_component(<ground>, "PhysX Primitive Collider")
10. create_entity(name="PlayerCamera")
11. add_component(<cam>, "Camera")
12. create_entity(name="GameManager")
13. add_component(<gm>, "Lua Script")
```

### Pattern: Iterative refinement

For complex scenes, build incrementally and verify at each step:

```
1. Create entity → verify with list_entities()
2. Add components → verify with get_entity_components()
3. Configure via run_editor_python → verify output
4. Repeat
```

---

## Efficiency Tips

1. **Batch with `run_editor_python`**: When creating many entities or setting
   many properties, use a single `run_editor_python` call with a loop instead
   of multiple individual tool calls.

2. **Check before creating**: Call `list_entities()` first to avoid duplicates.
   This uses fewer tokens than handling duplicate-creation errors.

3. **Component names are exact**: Use the precise O3DE component names from
   the [component catalog](components.md). A typo fails with code
   `component_type_not_found`.

4. **Parent early**: Set `parent_id` at creation time rather than reparenting
   later — it's one call vs. two.

5. **Use profile builds**: Default `config="profile"` is fastest for iteration.
   Switch to `release` only for final testing.
