# Agent Guide — o3de-mcp

Instructions for AI agents using this MCP server to create O3DE content.
Optimized for minimal token usage while maintaining accuracy.

## Quick Start Decision Tree

```
First call in a session?         → get_capabilities() to check what's available
CLI available but no editor?     → Project tools only (create, build, gems)
Editor connected?                → Full tool access (entities, components, levels)

Need to create/build a project?  → Project tools (no editor needed)
Need to modify a level/scene?    → Editor tools (editor must be running)
Creating 1-2 simple entities?    → Use create_entity + add_component
Creating 3+ entities?            → Use run_editor_python with batch script
Setting a single property?       → Use set_component_property
Setting many properties?         → Use run_editor_python
Need to test gameplay?           → enter_game_mode / exit_game_mode
Made a mistake?                  → undo / redo
```

> **Important:** Editor tools require the `AiCompanion` and
> `EditorPythonBindings` gems enabled in the project, with the editor running.
> Always call `get_capabilities()` first to determine what is available. If the
> editor is unreachable, focus on project tools.

## Tool Surface

86 tools in seven groups. Full parameters in [docs/tool-reference.md](docs/tool-reference.md).

| Group | Count | Editor needed | What it covers |
|-------|-------|---------------|----------------|
| Capabilities | 1 | No | `get_capabilities` — call this first |
| Editor | 41 | Yes | Entities, components, transforms, prefabs, levels, viewport/camera, console/CVARs, game mode, undo/redo, persistent sessions |
| Introspection | 3 | Partly | EBus schema (static stubs and live), RenderDoc capture |
| Project | 17 | No | Engines, projects, gems, templates, builds (blocking and background), export |
| Assets | 5 | No | Asset Processor status, refresh/wait, log tailing |
| Track View | 8 | Yes | Cinematic sequences: create/list/describe/delete, time range, add nodes, play/stop |
| Animation | 11 | Yes | EMotion FX anim graphs: list and describe; author graphs, nodes, entry states and parameters (gem main or 0.6.0+) |

Less obvious tools worth knowing:

- `begin_session` / `exec_in_session` / `get_session_vars` / `end_session` — keep Python
  state alive across calls instead of rebuilding it in every `run_editor_python`.
- `start_build` / `get_build_status` — non-blocking builds; use these over
  `build_project` when you do not want to hold the call open for minutes.
- `capture_viewport` — screenshot the editor viewport; `focus_entity` first to frame it.
- `get_bus_schema` / `get_bus_schema_live` — discover EBus APIs instead of guessing them.
- `tail_log` / `get_log_errors` — read editor and Asset Processor logs when something
  fails without a useful message.
- `assign_asset` — set an asset-typed component property by path.
- `get_scene_snapshot` / `get_entity_tree` / `get_entity` / `validate_scene` — scene state from
  the AiCompanion gem's C++ in one call; cheaper than `list_entities` plus per-entity queries.
- `create_entity` / `set_transform` / `delete_entity`: try the gem's native request types
  first (gem 0.5.0 or later; the gem validates the input and the call works in secure mode)
  and fall back to editor Python on older gems. The native path answers with the gem's JSON
  (`{"entity_id": ...}`, the entity, `{"deleted": ...}`); the fallback prints a sentence.

**Treat entity IDs as opaque.** In native tool output an id is a JSON number on gem 0.5.0
and a decimal string on gem main / 0.6.0 or later (the gem switched so a 64-bit id survives
a 53-bit-float JSON parser). Pass the id straight back as you received it; every tool accepts
a number or a string. Do not parse an id into a number of your own and do arithmetic on it.

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
    AddComponentOfType(eid, mesh_t[0])  # reuse
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
| Physics | `PhysX Primitive Collider`, `PhysX Dynamic Rigid Body`, `PhysX Character Controller` |
| Scripting | `Lua Script`, `Script Canvas` |
| Camera | `Camera` |
| Animation | `Actor`, `Anim Graph`, `Simple Motion` |
| Shapes | `Box Shape`, `Sphere Shape`, `Capsule Shape` |

Full catalog: [docs/components.md](docs/components.md)

## Common Entity Patterns

```
Static prop     = Mesh + Material + PhysX Primitive Collider
Dynamic object  = Mesh + Material + PhysX Primitive Collider + PhysX Dynamic Rigid Body
Trigger zone    = PhysX Primitive Collider (IsTrigger=True)
Character       = Actor + Anim Graph + PhysX Character Controller
Environment     = HDRi Skybox + Global Skylight (IBL)
```

## Workflow: New Game from Scratch

Minimal sequence to go from nothing to a playable scene:

```
0. get_capabilities()                        ← check what's available
1. list_templates()                          ← discover available templates
2. create_project(name, path)
3. enable_gem("AiCompanion", path)           ← required for editor tools
4. enable_gem("EditorPythonBindings", path)  ← required for editor tools
5. enable_gem("PhysX", path)
6. build_project(path)
   ── launch editor manually ──
7. load_level("Levels/Main")
8. run_editor_python(sky + light + ground + camera script)
9. run_editor_python(game entities script)
```

Steps 8-9 use batch scripts to create the entire scene in 2 calls.

## Workflow: CLI-Only (No Editor)

When the editor is not available, you can still manage projects and gems:

```
1. get_capabilities()                        ← confirms CLI available
2. list_templates()                          ← see templates
3. create_project(name, path)
4. create_gem(name, gem_path)                ← create custom gems
5. enable_gem(gem_name, project_path)
6. build_project(project_path)
7. export_project(project_path, output_path) ← package for distribution
```

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `O3DE_ENGINE_PATH` | Auto-detect | Engine install path |
| `O3DE_ENGINE_NAME` | (none) | Select engine by name when multiple registered |
| `O3DE_PROJECT_PATH` | Single registered project | Project used by asset and introspection tools |
| `O3DE_EDITOR_HOST` | `127.0.0.1` | Editor AgentServer host |
| `O3DE_EDITOR_PORT` | `4600` | Editor AgentServer port |
| `O3DE_EDITOR_TIMEOUT` | `600` | Per-command editor execution timeout (seconds) |
| `O3DE_EDITOR_CONNECT_TIMEOUT` | `5` | Editor TCP connect timeout (seconds) |
| `O3DE_CAPTURE_WAIT` | `15` | Wait for a viewport capture to reach disk (seconds) |
| `O3DE_EDITOR_TLS` | `0` | Wrap the editor connection in TLS |
| `O3DE_EDITOR_TLS_VERIFY` | `0` | Verify the editor certificate and hostname |
| `O3DE_EDITOR_TLS_CA` | System | CA bundle used when verification is on |
| `O3DE_CMAKE_GENERATOR` | Auto-detect | CMake generator for builds |
| `O3DE_CONFIGURE_TIMEOUT` | `600` | CMake configure timeout (seconds) |
| `O3DE_BUILD_TIMEOUT` | `1800` | CMake build timeout (seconds) |
| `O3DE_EXPORT_TIMEOUT` | `3600` | Project export timeout (seconds) |

## Security Constraints

Inputs are validated — these will be rejected:

- Entity IDs with non-numeric characters: `abc`, `1; rm -rf /`
- Component types with special characters: `Mesh'; DROP TABLE`
- Project names starting with numbers or containing specials: `123game`, `my game!`
- Build configs other than: `debug`, `profile`, `release`
- Paths that don't exist (for tools that require existing paths)

## Error Handling

Every tool reports failure the same way: a JSON object

```json
{"status": "error", "code": "<slug>", "message": "<human-readable text>"}
```

Detect any failure with a single check: `status == "error"`. Branch on the stable
`code` slug (for example `connection_refused`, `timeout`, `no_level_open`,
`log_not_found`, `duplicate_failed`); show the `message` to the user. A successful
call never carries a top-level `status` of `"error"`; its payload is tool-specific
(some successes use `status: "ok"` or `"manual_required"`).

Three things fall outside this envelope by design:

- **Invalid input** caught at the tool boundary (a malformed entity ID, an empty
  name, a non-positive timeout) is raised as a tool error before any editor or
  CLI work runs, rather than returned as the envelope.
- **`wait_for_assets`** returns a progress result `{"completed": bool,
  "elapsed": seconds}`. A wait that times out is a result (`completed: false`),
  not a failure.
- **Native read tools** (`get_entity`, `get_scene_snapshot`, `get_entity_tree`,
  `validate_scene`) pass the AiCompanion gem's response through verbatim. A gem
  refusal (unreflected request, validation) is converted to the envelope, but a
  logical not-found the gem reports inside a successful response keeps the gem's
  own shape (for example `get_entity` on a missing id returns
  `{"entity_id": ..., "error": "No entity with id ..."}`).

| Error | Likely Cause | Fix |
|-------|-------------|-----|
| "Could not connect to O3DE Editor" | Editor not running or AiCompanion gem not enabled | Start editor with the AiCompanion and EditorPythonBindings gems |
| "timeout" (command did not complete) | A single editor op ran past `O3DE_EDITOR_TIMEOUT`; editor may still be working | Raise `O3DE_EDITOR_TIMEOUT` or pass `run_editor_python(..., timeout=N)`; don't blindly retry (may duplicate work) |
| "Invalid entity ID" | Non-numeric ID passed | Use numeric IDs from list_entities() |
| "Component type not found" | Typo in component name or gem not enabled | Check [component catalog](docs/components.md) |
| "O3DE CLI not found" | Engine not installed or O3DE_ENGINE_PATH not set | Run get_engine_info() to diagnose |
| "editor_unavailable" | Editor unreachable (fast-fail) | Call get_capabilities(); editor tools need running editor |
| "does not exist" | Path validation failed | Verify path exists on disk |

## Reference

- [Tool Reference](docs/tool-reference.md) — all tools with parameters
- [Recipes](docs/recipes.md) — composable game-dev patterns
- [Component Catalog](docs/components.md) — all component names and dependencies
- [Examples](examples/) — complete worked examples
