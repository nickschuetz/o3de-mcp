# Tool Reference

Compact reference for all o3de-mcp tools. Optimized for agent consumption.

---

## Capabilities Tools

Always available — use these first to determine what other tools can be used.

### get_capabilities

Check what O3DE MCP capabilities are currently available. No parameters.
Returns JSON with `editor`, `cli`, and `tool_categories` sections.

> **Best practice:** Call this first in every session to avoid wasting tokens
> on tools that will fail.

---

## Introspection Tools

Discover a gem's scripting API. These read the editor's generated stubs from
disk, so they work without a running editor (the project must have been opened
in the editor once to produce the stubs).

### get_bus_schema

Return the reflected EBus schema for a module as JSON, so an agent can learn an
API before calling it. Gem-agnostic: works for any reflected bus with no
per-gem catalog.

Parameters:

- `module` (optional): azlmbr submodule to inspect, e.g. `diorama`, `physics`.
  Must be a bare identifier. Omit to list the modules that have a stub.
- `bus` (optional): bus name to filter to, e.g. `DioramaSpriteRequestBus`.
- `project_path` (optional): project whose stubs to read. Omit to resolve from
  `O3DE_PROJECT_PATH` or the single registered project that has a stub dump.

Returns JSON. With no module: `{symbols_dir, modules}`. With a module:
`{module, source, buses: [{name, addressable, address_type, events: [{call_type,
name, args, returns}]}], note}`.

> **Note:** The generated stub lists EBus event arguments by type only. For
> argument names and tooltips, use `get_bus_schema_live` (below) which queries
> the running editor's BehaviorContext.

### get_bus_schema_live

Query the running editor's BehaviorContext for a bus schema. Falls back to
`get_bus_schema` (stub-based) if the editor is unreachable.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `module` | str | yes | azlmbr submodule name (e.g. `physics`) |
| `bus` | str | yes | Bus name (e.g. `PhysicsRequestBus`) |
| `project_path` | str | no | Project path for fallback stub resolution |

Returns JSON with a `source` field: `"live"` or `"stub_fallback"`.

### capture_renderdoc_frame

Trigger a RenderDoc frame capture in the O3DE editor. Sends the
`r_captureFrame` console command. After capture, use the `renderdoc-mcp` MCP
server tools to analyze the frame. No parameters.

---

## Editor Tools

Require a running O3DE Editor with AiCompanion + EditorPythonBindings gems.
If the editor is unreachable, these tools will fast-fail with an
`editor_unavailable` error within seconds rather than timing out.

### run_editor_python

Execute arbitrary Python in the editor. Full `azlmbr` API access.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `script` | str | yes | Python code to run in editor |
| `timeout` | float | no | Per-call execution timeout (seconds). Omit to use `O3DE_EDITOR_TIMEOUT` (default 600). Raise for known-heavy scripts — the editor runs the script synchronously and does not reply until it finishes. |

### list_entities

List all entities in the current level. No parameters.
Returns JSON array: `[{"id": "...", "name": "..."}]`

### create_entity

Create a new entity in the current level.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Entity name |
| `parent_id` | str | no | Parent entity ID (omit for root) |

### delete_entity

Delete an entity from the current level.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Entity ID to delete |

### duplicate_entity

Duplicate an entity and its children.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Entity ID to duplicate |

Returns JSON: `{"id": "...", "name": "..."}`

### get_entity_components

List components on an entity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Entity ID (numeric, e.g. `1234` or `[1234]`) |

Returns JSON array: `[{"component_id": "...", "type": "..."}]`

### add_component

Add a component to an entity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Target entity ID |
| `component_type` | str | yes | Component name (e.g. `Mesh`, `PhysX Rigid Body`) |

### get_component_property

Get a property value from a component.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Entity ID |
| `component_type` | str | yes | Component type name |
| `property_path` | str | yes | Property path with `\|` separator (e.g. `Transform\|Translate`) |

### set_component_property

Set a property value on a component.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Entity ID |
| `component_type` | str | yes | Component type name |
| `property_path` | str | yes | Property path with `\|` separator |
| `value` | str | yes | Value as string (`true`/`false` for bools, numbers as strings) |

### assign_asset

Assign an asset to a component property by resolving the asset path to an O3DE asset ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Entity ID |
| `component_type` | str | yes | Component type name |
| `property_path` | str | yes | Property path with `\|` separator |
| `asset_path` | str | yes | Project-relative asset path (e.g. `Objects/Props/box.fbx`) |

### remove_component

Remove a component from an entity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Entity ID |
| `component_type` | str | yes | Component type name to remove |

### set_transform

Set the world transform of an entity. Only provided components are changed.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Entity ID |
| `position` | list[float] | no | [x, y, z] world position |
| `rotation` | list[float] | no | [x, y, z, w] quaternion rotation (4 elements) |
| `scale` | list[float] | no | [x, y, z] scale |

### get_transform

Get the world transform of an entity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Entity ID |

Returns JSON: `{"position": [x,y,z], "rotation": [x,y,z,w], "scale": [x,y,z]}`

### set_parent

Set the parent of an entity (reparent in the hierarchy).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Entity ID to reparent |
| `parent_id` | str | yes | New parent entity ID |

### run_console_command

Execute an O3DE console command in the running editor.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | str | yes | Console command (e.g. `r_fog 0`, `loadlevel Levels/MyLevel`) |

### get_cvar

Get the value of an O3DE console variable.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | CVAR name (e.g. `r_fog`) |

Returns JSON: `{"name": "...", "value": "..."}`

### set_cvar

Set the value of an O3DE console variable.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | CVAR name |
| `value` | str | yes | Value as string |

### load_level

Open a level in the editor.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `level_path` | str | yes | Level path relative to project (e.g. `Levels/Main`) |

### get_level_info

Get current level name and path. No parameters.
Returns JSON: `{"level_name": "...", "level_path": "..."}`

### save_level

Save the currently open level. No parameters.

### create_level

Create a new empty level in the current project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Level name (alphanumeric, starts with letter) |

### list_levels

List all levels in a project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_path` | str | no | Project path (auto-resolves if omitted) |

Returns JSON: `{"levels": [...], "project": "..."}`

### enter_game_mode

Enter play-in-editor mode. No parameters.

### exit_game_mode

Exit game mode, return to edit mode. No parameters.

### undo

Undo the last editor action. No parameters.

### redo

Redo the last undone action. No parameters.

### get_viewport_camera

Get the active editor viewport camera transform. No parameters.
Returns JSON: `{"position": [...], "rotation": [...], "fov": ...}`

### set_viewport_camera

Set the active editor viewport camera transform.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `position` | list[float] | no | [x, y, z] camera position |
| `rotation` | list[float] | no | [x, y, z, w] quaternion rotation |

### focus_entity

Focus the viewport camera on an entity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Entity ID to focus on |

### capture_viewport

Capture a screenshot of the editor viewport.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `output_path` | str | yes | File path (must end in .png/.jpg/.bmp/.tga) |
| `width` | int | no | Capture width in pixels |
| `height` | int | no | Capture height in pixels |

### instantiate_prefab

Instantiate a prefab in the current level.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `prefab_path` | str | yes | Path to .prefab file |
| `position` | list[float] | no | [x, y, z] spawn position (defaults to origin) |
| `parent_id` | str | no | Parent entity ID |

### create_prefab_from_entity

Create a prefab file from an existing entity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Entity ID to create prefab from |
| `prefab_path` | str | yes | Path for the new .prefab file |

### save_prefab

Save a prefab instance (propagate entity changes to the prefab file).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | str | yes | Root entity ID of the prefab instance |

### begin_session

Begin a persistent Python session in the editor. No parameters.
Returns JSON: `{"session_id": "..."}`

### exec_in_session

Execute Python code in a persistent session. Variables persist across calls.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | str | yes | Session ID from `begin_session` |
| `script` | str | yes | Python code to execute |

### end_session

End a persistent Python session and clean up.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | str | yes | Session ID from `begin_session` |

### get_session_vars

List variable names in a persistent session (names only, not values).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | str | yes | Session ID from `begin_session` |

---

## Project Tools

Wrap the O3DE CLI and CMake. Do not require a running editor.

### get_engine_info

Get local O3DE engine metadata. No parameters.
Returns JSON with engine version, path, and metadata.

### list_projects

List all registered O3DE projects. No parameters.
Returns JSON array of project objects.

### list_gems

List all registered external gems. No parameters.
Returns JSON array of gem objects.

### create_project

Create a new O3DE project from a template.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Project name (alphanumeric, hyphens, underscores) |
| `path` | str | yes | Directory for the project |
| `template` | str | no | Template name (default: `DefaultProject`) |

### register_gem

Register an external gem with a project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `gem_path` | str | yes | Path to gem directory (must exist) |
| `project_path` | str | yes | Path to project directory (must exist) |

### enable_gem

Enable a registered gem in a project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `gem_name` | str | yes | Gem name |
| `project_path` | str | yes | Path to project directory (must exist) |

### build_project

Build a project with CMake.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_path` | str | yes | Path to project (must exist) |
| `config` | str | no | `debug`, `profile`, or `release` (default: `profile`) |

### disable_gem

Disable a gem in a project. Complement of `enable_gem`.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `gem_name` | str | yes | Gem name |
| `project_path` | str | yes | Path to project directory (must exist) |

### create_gem

Create a new O3DE gem from a template.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Gem name (alphanumeric, hyphens, underscores) |
| `path` | str | yes | Directory for the gem |
| `template` | str | no | Template name (default: `DefaultGem`) |

### export_project

Export a project for distribution. Long-running operation.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_path` | str | yes | Path to project (must exist) |
| `output_path` | str | yes | Directory for exported output |
| `config` | str | no | `debug`, `profile`, or `release` (default: `profile`) |

Timeout configurable via `O3DE_EXPORT_TIMEOUT` env var (default: 3600s).

### edit_project_properties

Edit properties of an existing project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_path` | str | yes | Path to project (must exist) |
| `project_name` | str | no | New project name |
| `origin` | str | no | New origin URL or description |

### list_templates

List available project and gem templates. No parameters.
Returns JSON array of template objects with name, summary, and path.

### list_project_gems

List gems enabled in a specific project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_path` | str | yes | Path to the O3DE project |

Returns JSON: `{"gems": [...], "count": N, "project_path": "..."}`

### register_engine

Register an O3DE engine installation with the manifest.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `engine_path` | str | yes | Path to engine root (must contain engine.json) |

### set_active_engine

Set the active O3DE engine by name (in-process, not persistent).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Engine name |

### start_build

Start a CMake build in the background and return a build ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_path` | str | yes | Path to project (must have a build directory) |
| `config` | str | no | `debug`, `profile`, or `release` (default: `profile`) |
| `target` | str | no | Build target (e.g. `Editor`). Omit to build all. |

Returns JSON: `{"build_id": "...", "status": "running", ...}`

### get_build_status

Check the status of a background build.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `build_id` | str | yes | Build ID from `start_build` |

Returns JSON: `{"status": "running|completed|failed", "returncode": N, "output": "..."}`

---

## Asset Tools

Monitor the Asset Processor and read diagnostic log files. These tools work
with the filesystem and process list — they do not require a running editor.

### get_asset_processor_status

Check whether the O3DE Asset Processor is running.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_path` | str | no | Project path (for log directory info) |

Returns JSON: `{"running": bool, "log_dir": "...", "project": "..."}`

### wait_for_assets

Wait for the Asset Processor to finish processing (or until timeout).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `timeout` | int | no | Maximum wait in seconds (default: 300) |

Returns JSON: `{"completed": bool, "elapsed": float}`

### refresh_assets

Trigger an Asset Processor rescan for a project.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `project_path` | str | no | Project path (auto-resolves if omitted) |

### tail_log

Read the last N lines of an O3DE log file.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `log_name` | str | yes | Log name: `Editor`, `AssetProcessor`, `CMakeOutput` |
| `lines` | int | no | Number of lines (default: 50) |
| `filter` | str | no | Regex pattern to filter lines |
| `project_path` | str | no | Project path (auto-resolves if omitted) |

Returns JSON: `{"log_name": "...", "lines": [...], "count": N}`

### get_log_errors

Extract error lines from an O3DE log file.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `log_name` | str | no | Log name (default: `Editor`) |
| `since_lines` | int | no | Lines to scan (default: 200) |
| `project_path` | str | no | Project path (auto-resolves if omitted) |

Returns JSON: `{"errors": [...], "count": N}`

---

## Input Validation Rules

All tools validate inputs before execution:

- **Entity IDs**: Numeric only — `1234` or `[1234]`
- **Component types**: Alphanumeric, spaces, hyphens, underscores, parentheses
- **Project/gem names**: Start with letter, then alphanumeric/hyphens/underscores
- **Paths**: Resolved to absolute; `must_exist` tools verify the path exists
- **Build configs**: Allowlisted to `debug`, `profile`, `release`
