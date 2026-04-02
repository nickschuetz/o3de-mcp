# Agent Guide — o3de-mcp

Instructions for AI agents using this MCP server to create O3DE content.
Optimized for minimal token usage while maintaining accuracy.

## Quick Start Decision Tree

```
Need to create/build a project?  → Project tools (no editor needed)
Need to modify a level/scene?    → Editor tools (editor must be running)
Creating 1-2 simple entities?    → Use create_entity + add_component
Creating 3+ entities?            → Use run_editor_python with batch script
Setting a single property?       → Use set_component_property
Setting many properties?         → Use run_editor_python
Need to test gameplay?           → enter_game_mode / exit_game_mode
Made a mistake?                  → undo / redo
```

## Token Efficiency Rules

### 1. Batch over individual calls

**Bad** (15 tool calls for 5 physics objects):
```
create_entity("Box1") → add_component(Mesh) → add_component(Collider) → ...
create_entity("Box2") → add_component(Mesh) → add_component(Collider) → ...
```

**Good** (1 tool call):
```python
# run_editor_python: create all entities, add all components, set all transforms
for item in items:
    eid = create(item.name)
    set_position(eid, item.pos)
    add_components(eid, [Mesh, Collider, RigidBody])
```

See [examples/05_batch_operations.md](examples/05_batch_operations.md) for
complete patterns.

### 2. Query before modifying

Always call `list_entities()` before creating entities to avoid duplicates.
One query call is cheaper than debugging duplicate-entity errors.

### 3. Pre-resolve component type IDs

When adding the same component type to multiple entities, resolve the type ID
once and reuse it:

```python
mesh_t = FindComponentTypeIdsByEntityType(['Mesh'], Game)  # once
for eid in entity_ids:
    AddComponentsOfType(eid, mesh_t)  # reuse
```

### 4. Combine create + configure

Set transforms and properties in the same `run_editor_python` call that creates
entities — don't make a separate call to position each one.

## Component Quick Reference

Use these exact strings with `add_component`:

| Category | Components |
|----------|------------|
| Rendering | `Mesh`, `Material`, `Decal` |
| Lighting | `Directional Light`, `Point Light`, `Spot Light`, `Area Light` |
| Sky | `HDRi Skybox`, `Global Skylight (IBL)` |
| Physics | `PhysX Collider`, `PhysX Rigid Body`, `PhysX Character Controller` |
| Scripting | `Lua Script`, `Script Canvas` |
| Camera | `Camera` |
| Animation | `Actor`, `Anim Graph`, `Simple Motion` |
| Shapes | `Box Shape`, `Sphere Shape`, `Capsule Shape` |

Full catalog: [docs/components.md](docs/components.md)

## Common Entity Patterns

```
Static prop     = Mesh + Material + PhysX Collider
Dynamic object  = Mesh + Material + PhysX Collider + PhysX Rigid Body
Trigger zone    = PhysX Collider (IsTrigger=True)
Character       = Actor + Anim Graph + PhysX Character Controller
Environment     = HDRi Skybox + Global Skylight (IBL)
```

## Workflow: New Game from Scratch

Minimal sequence to go from nothing to a playable scene:

```
1. create_project(name, path)
2. enable_gem("RemoteConsole", path)         ← required for editor tools
3. enable_gem("EditorPythonBindings", path)  ← required for editor tools
4. enable_gem("PhysX", path)
5. build_project(path)
   ── launch editor manually ──
6. load_level("Levels/Main")
7. run_editor_python(sky + light + ground + camera script)
8. run_editor_python(game entities script)
```

Steps 7-8 use batch scripts to create the entire scene in 2 calls.

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `O3DE_ENGINE_PATH` | Auto-detect | Engine install path |
| `O3DE_EDITOR_HOST` | `127.0.0.1` | Editor remote console host |
| `O3DE_EDITOR_PORT` | `4600` | Editor remote console port |
| `O3DE_CMAKE_GENERATOR` | Auto-detect | CMake generator for builds |
| `O3DE_CONFIGURE_TIMEOUT` | `600` | CMake configure timeout (seconds) |
| `O3DE_BUILD_TIMEOUT` | `1800` | CMake build timeout (seconds) |

## Security Constraints

Inputs are validated — these will be rejected:

- Entity IDs with non-numeric characters: `abc`, `1; rm -rf /`
- Component types with special characters: `Mesh'; DROP TABLE`
- Project names starting with numbers or containing specials: `123game`, `my game!`
- Build configs other than: `debug`, `profile`, `release`
- Paths that don't exist (for tools that require existing paths)

## Error Handling

| Error | Likely Cause | Fix |
|-------|-------------|-----|
| "Could not connect to O3DE Editor" | Editor not running or RemoteConsole not enabled | Start editor with RemoteConsole gem |
| "Connection timed out" | Editor busy or firewall blocking port 4600 | Wait and retry |
| "Invalid entity ID" | Non-numeric ID passed | Use numeric IDs from list_entities() |
| "Component type not found" | Typo in component name or gem not enabled | Check [component catalog](docs/components.md) |
| "O3DE CLI not found" | Engine not installed or O3DE_ENGINE_PATH not set | Run get_engine_info() to diagnose |
| "does not exist" | Path validation failed | Verify path exists on disk |

## Reference

- [Tool Reference](docs/tool-reference.md) — all tools with parameters
- [Recipes](docs/recipes.md) — composable game-dev patterns
- [Component Catalog](docs/components.md) — all component names and dependencies
- [Examples](examples/) — complete worked examples
