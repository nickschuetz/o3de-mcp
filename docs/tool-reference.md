# Tool Reference

Compact reference for all o3de-mcp tools. Optimized for agent consumption.

---

## Capabilities Tools

Always available — use these first to determine what other tools can be used.

### get_capabilities

Check what O3DE MCP capabilities are currently available. No parameters.
Returns JSON with `editor`, `cli`, and `tool_categories` sections. When the
editor is connected, `editor.ai_companion_gem` says whether the AiCompanion
AgentServer answered `get_api_version`, and `editor.agent_server` carries its
`protocol_version`, `gem_version` and `api_version` (or `null` on a legacy
RemoteConsole with no gem behind it).

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

Tries the AiCompanion gem's native `get_bus_schema` request first (gem 0.4.0
or later; includes argument names and tooltips, works in secure mode), then
the editor-Python query, then the stub files. The `source` field says which
answered: `native`, `live` or `stub_fallback`.

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

### get_scene_snapshot

Full scene state (entities, components, transforms, hierarchy) as JSON, served
natively by the AiCompanion gem's C++ `SceneSnapshotProvider`. No parameters.
Needs the AgentServer protocol; returns `agent_server_required` on the legacy
RemoteConsole transport. Works in the gem's secure mode.

### get_entity_tree

Entity hierarchy as a nested JSON tree, served natively by the gem. No parameters.

### get_entity

One entity's name, transform, parent and component list as JSON, served
natively by the gem's C++ (`get_entity` request type, gem 0.4.0 or later).
Works in secure mode. An unknown id returns `{"error": ...}`.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Entity id, `"1234"` or `"[1234]"` |

### validate_scene

The gem's scene validation report as JSON (missing cameras, transform-less
entities, physics bodies without colliders, and similar). No parameters.

### list_entities

List all entities in the current level. No parameters.
Returns JSON array: `[{"id": "...", "name": "..."}]`

### create_entity

Create a new entity in the current level.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Entity name |
| `parent_id` | int or str | no | Parent entity ID (omit for root) |

Tries the AiCompanion gem's native `create_entity` request first (gem 0.5.0
or later, works in secure mode) and returns its JSON verbatim:
`{"entity_id": 123, "name": "...", "position": [0.0, 0.0, 0.0]}`. The name is
checked with the gem's own rule before either path (a letter first, then
letters, digits, `_` or `-`, at most 128 characters); the gem validates the
parent, and a refusal comes back as an error and is not retried through
Python. Older gems and the legacy transport fall back to editor
Python, which prints `Created entity [<id>]`.

### delete_entity

Delete an entity from the current level.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Entity ID to delete |

Tries the gem's native `delete_entity` request first (gem 0.5.0 or later, works
in secure mode) and returns `{"deleted": <id>}` verbatim. The gem refuses an
unknown entity and the level's root entity. Older gems and the legacy transport
fall back to editor Python, which prints `Deleted entity [<id>]`.

### duplicate_entity

Duplicate an entity and its children.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Entity ID to duplicate |

Returns JSON: `{"id": "...", "name": "..."}`

### get_entity_components

List components on an entity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Entity ID (numeric, e.g. `1234` or `[1234]`) |

Returns JSON array: `[{"component_id": "...", "type": "..."}]`

### add_component

Add a component to an entity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Target entity ID |
| `component_type` | str | yes | Component name (e.g. `Mesh`, `PhysX Rigid Body`) |

### get_component_property

Get a property value from a component.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Entity ID |
| `component_type` | str | yes | Component type name |
| `property_path` | str | yes | Property path with `\|` separator (e.g. `Transform\|Translate`) |

### set_component_property

Set a property value on a component.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Entity ID |
| `component_type` | str | yes | Component type name |
| `property_path` | str | yes | Property path with `\|` separator |
| `value` | str | yes | Value as string (`true`/`false` for bools, numbers as strings) |

### assign_asset

Assign an asset to a component property by resolving the asset path to an O3DE asset ID.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Entity ID |
| `component_type` | str | yes | Component type name |
| `property_path` | str | yes | Property path with `\|` separator |
| `asset_path` | str | yes | Project-relative asset path (e.g. `Objects/Props/box.fbx`) |

### remove_component

Remove a component from an entity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Entity ID |
| `component_type` | str | yes | Component type name to remove |

### set_transform

Set the world transform of an entity. Only provided components are changed.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Entity ID |
| `position` | list[float] | no | [x, y, z] world position |
| `rotation` | list[float] | no | [x, y, z, w] quaternion rotation (4 elements) |
| `scale` | list[float] | no | [x, y, z] scale |

Tries the gem's native `set_transform` request first (gem 0.5.0 or later,
works in secure mode). The quaternion is converted to the XYZ Euler degrees the
gem takes (the inverse of its own `CreateFromEulerDegreesXYZ`) and a uniform
scale to its single number. On success it returns the updated entity's JSON
verbatim, the same shape as `get_entity`. The gem refuses an unknown entity, an
out-of-bounds position or a scale outside (0, 1000], and that is returned as an
error. Older gems, the legacy transport, a non-uniform scale and a rotation at
a gimbal pole (pitch within 0.02 degrees of plus or minus 90, where the Euler
form cannot carry roll and yaw separately) use the editor Python path, which
applies the quaternion directly and prints `Transform set for entity [<id>]`.
An all-zero quaternion is rejected before either path.

### get_transform

Get the world transform of an entity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Entity ID |

Returns JSON: `{"position": [x,y,z], "rotation": [x,y,z,w], "scale": [x,y,z]}`

### set_parent

Set the parent of an entity (reparent in the hierarchy).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Entity ID to reparent |
| `parent_id` | int or str | yes | New parent entity ID |

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

Create a new level in the current project and open it in the editor. The level is
written to `<project>/Levels/<name>/`.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Level name (alphanumeric, starts with letter) |
| `template` | str | no | Level template prefab, relative to an asset scan folder. Defaults to `Prefabs/Default_Level.prefab`, the editor's own New Level default (camera, sun, grid). Pass `""` for a bare level with no entities. |

Reports `Created and opened level: <name>` on success. The engine's result code is
turned into an error message otherwise: the level already exists, its directory could
not be created, or its path is too long.

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
| `entity_id` | int or str | yes | Entity ID to focus on |

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
| `parent_id` | int or str | no | Parent entity ID |

### create_prefab_from_entity

Create a prefab file from an existing entity.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Entity ID to create prefab from |
| `prefab_path` | str | yes | Path for the new .prefab file |

### save_prefab

Save a prefab instance (propagate entity changes to the prefab file).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | int or str | yes | Root entity ID of the prefab instance |

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

## Track View Tools

Cinematic sequence authoring, over the reflected `azlmbr.legacy.trackview` API. A new
sequence has no nodes; add a `Director` node before other node types. Track and keyframe
authoring are not exposed.

### list_sequences

List the cinematic sequences in the current level. Returns a JSON array of
`{name, start, end}`. No parameters.

### create_sequence

Create a modern Sequence Component sequence. An existing name is an error.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Sequence name (letter/digit first; letters, digits, spaces, `_`, `-`) |

### delete_sequence

Delete a sequence by name.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Sequence name |

### get_sequence

Describe a sequence: its time range and the node names at its root (empty until a
`Director` is added).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Sequence name |

### set_sequence_time_range

Set the sequence play range in seconds.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Sequence name |
| `start` | float | yes | Range start (seconds) |
| `end` | float | yes | Range end (seconds), greater than start |

### add_sequence_node

Add a node to a sequence. Add a `Director` first; other types need one present.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Sequence name |
| `node_type` | str | yes | `Director`, `Event`, `AzEntity`, `Component`, `CVar`, `Material`, `Group`, `Layer`, `Comment` |
| `node_name` | str | yes | Name for the new node |

### play_sequence

Start playing a sequence in the editor.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | str | yes | Sequence name |

### stop_sequence

Stop the sequence currently playing. No parameters.

## Animation Tools

EMotion FX anim graph reads and authoring over the AiCompanion gem's native C++ request
types. They need gem main or 0.6.0+ and the EMotionFX gem; an older gem answers with code
`unknown_request_type`. Native only (no editor-Python fallback); they work in secure
mode. Graph ids are 32-bit numbers; node, transition and entity ids are decimal strings.

Authoring writes refuse a graph owned by an asset or a running actor instance
(`validation_failed`), so author on a graph from `create_anim_graph` or `load_anim_graph`.
Each write is one step in the Animation Editor's own undo history; the `undo` tool does
not revert it. `save_anim_graph` is not undoable. Parameter objects report `default`,
`min` and `max` in the engine's text form (for example `"0.50000000"`).

### list_anim_graphs

List every anim graph the engine holds: `editor_mode` and `anim_graphs` (each with
`id`, `file_name`, ownership and dirty flags, node and parameter counts, and the actor
`instances` using it). No parameters.

### get_anim_graph

Describe one graph: `nodes` (type, parent, position, ports, connections),
`transitions` (blend time, conditions), `parameters`, `node_groups` and
`root_state_machine_id`. Pass exactly one selector; an unknown graph is an error.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | one of | Graph id from `list_anim_graphs` (number or digit string, 32-bit) |
| `file_name` | str | one of | Graph file name; exact match first, then its tail case-insensitively |

### create_anim_graph

Create a new, empty, in-memory graph to author (just its root state machine). Returns
`{"id", "file_name": ""}`. No parameters.

### remove_anim_graph

Remove a graph from the engine (not its file). Returns `{"removed": <id>}`.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |

### load_anim_graph

Load an `.animgraph` file so it can be authored. Returns `{"id", "file_name"}`; a file
already loaded this way returns the existing id.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `file_name` | str | yes | Absolute path, `@alias@` path, or path relative to the project |

### save_anim_graph

Save a graph to disk. The file must land inside the project root. Not undoable.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |
| `file_name` | str | no | Target path; omit to save to the graph's current file |

### add_anim_graph_node

Add a node. Returns the node object as `get_anim_graph` emits it. An unknown type is
refused with the list of known types.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |
| `node_type` | str | yes | RTTI or palette name, case-insensitive (`AnimGraphMotionNode`, `AnimGraphStateMachine`, `BlendTree`, ...) |
| `parent_id` | int or str | no | Parent node id (state machine or blend tree); default the root |
| `name` | str | no | Node name; engine-generated when omitted |
| `position` | [int, int] | no | Graph-canvas position in pixels |

### remove_anim_graph_node

Remove a node and its children; the root is refused. Returns `{"removed": "<node id>"}`.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |
| `node_id` | int or str | yes | Node id |

### set_anim_graph_entry_state

Make a node the entry state of its state machine. Returns `{"entry_state_id": "<id>"}`.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |
| `node_id` | int or str | yes | A node that can act as a state |

### add_anim_graph_parameter

Add a value parameter. Returns the parameter object as `get_anim_graph` emits it.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |
| `name` | str | yes | Parameter name |
| `parameter_type` | str | yes | `Float` (slider), `FloatSpinner`, `Int` (slider), `IntSpinner`, `Bool`, `String`, `Tag`, `Vector2`, `Vector3`, `Vector3Gizmo`, `Vector4`, `Color`, `Rotation`, or the class name |
| `default` | number, bool, str or list | no | Default value; a list of numbers for vector, color and rotation types |
| `min` / `max` | number or list | no | Range; ranged types only (Float, Int, Vector2/3/4, Color, Rotation) |
| `description` | str | no | Description |
| `group` | str | no | Group; created when missing |

### remove_anim_graph_parameter

Remove a value parameter; groups are refused. Returns `{"removed": "<name>"}`.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |
| `name` | str | yes | Parameter name |

### set_anim_graph_node

Edit a node. Pass at least one change. Returns the node object. An unknown attribute is
refused with the settable fields listed.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |
| `node_id` | int or str | yes | Node id |
| `name` | str | no | New name |
| `position` | [int, int] | no | Graph-canvas position in pixels |
| `enabled` | bool | no | Enable or disable the node |
| `attributes` | object | no | Reflected fields to set, e.g. a motion node's `{"motionIds": ["<id>"]}` (read back as `motion_ids`) |

### add_anim_graph_transition

Add a state-machine transition. Returns the transition object as `get_anim_graph` emits
it. Source and target must share a state-machine parent; an exit node cannot be a
source. All conditions land as one Animation Editor undo step.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |
| `target_node_id` | int or str | yes | State to transition to |
| `source_node_id` | int or str | unless `wildcard` | State to transition from |
| `wildcard` | bool | no | True for a transition from any state (omit `source_node_id`) |
| `blend_time` | float | no | Seconds, 0 or more |
| `priority` | int | no | Higher wins when several are ready |
| `disabled` | bool | no | Create disabled |
| `sync_mode` | int | no | 0 disabled, 1 track based, 2 clip based |
| `interpolation` | int | no | 0 linear, 1 ease curve |
| `conditions` | list | no | `[{"condition_type", "attributes"}]`; see below |

Condition types (or the RTTI name) and their attribute keys; enum values take the
integer or the name, case-insensitive. An unknown key is refused with the supported list.

| `condition_type` | Attributes |
|------------------|------------|
| `ParameterCondition` | `parameterName`, `function` (GREATER, GREATEREQUAL, LESS, LESSEQUAL, NOTEQUAL, EQUAL, INRANGE, NOTINRANGE), `testValue`, `rangeValue`, `timeRequirement`, `stringFunction`, `testString` |
| `TimeCondition` | `countDownTime`, `useRandomization`, `minRandomTime`, `maxRandomTime` |
| `PlayTimeCondition` | `nodeId`, `mode` (REACHEDTIME, REACHEDEND, HASLESSTHAN), `playTime` |
| `MotionCondition` | `motionNodeId`, `testFunction` (EVENT, HASENDED, HASREACHEDMAXNUMLOOPS, PLAYTIME, PLAYTIMELEFT, ISMOTIONASSIGNED, ISMOTIONNOTASSIGNED, NONE), `numLoops`, `playTime` |
| `StateCondition` | `stateId`, `testFunction` (EXITSTATES, ENTERING, ENTER, EXIT, END, PLAYTIME, NONE), `playTime` |
| `TagCondition` | `function` (ALL, NOTALL, ONEORMORE, NONE), `tags` (list) |
| `Vector2Condition` | `parameterName`, `operation` (LENGTH, GETX, GETY), `testFunction`, `testValue`, `rangeValue` |

### set_anim_graph_transition

Change a transition's settings (at least one). Returns the transition object.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |
| `transition_id` | int or str | yes | Transition id |
| `blend_time` / `priority` / `disabled` / `sync_mode` / `interpolation` | as above | no | Settings to change |

### remove_anim_graph_transition

Remove a transition and its conditions. Returns `{"removed": "<transition id>"}`.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |
| `transition_id` | int or str | yes | Transition id |

### connect_anim_graph_ports

Connect an output port to an input port in a blend tree. Returns the target node's input
port object. Refused: a target inside a state machine (use `add_anim_graph_transition`),
incompatible port types, an occupied input, a duplicate, a cycle. An unknown port name is
refused with the node's ports listed as `"name" (index)`.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |
| `source_node_id` | int or str | yes | Node whose output to connect |
| `source_port` | int or str | yes | Output port index or name |
| `target_node_id` | int or str | yes | Node whose input to connect |
| `target_port` | int or str | yes | Input port index or name |

### disconnect_anim_graph_ports

Remove the connection feeding an input port. Returns `{"removed": "<connection id>"}`; a
free port is `not_found`.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `anim_graph_id` | int or str | yes | Graph id |
| `target_node_id` | int or str | yes | Node whose input to free |
| `target_port` | int or str | yes | Input port index or name |

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

Wait for the Asset Processor process to exit (or until timeout). It watches for the process
to stop, not for it to go idle: suited to a one-off AssetProcessorBatch run. A GUI Asset
Processor running beside the editor stays up while idle, so this then waits out the
timeout and returns `completed: false`.

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
| `log_name` | str | yes | Log file in `<project>/user/log`: `Editor`, `AP_GUI`, `AP_Batch` (`.log` optional) |
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
