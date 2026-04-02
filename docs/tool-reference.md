# Tool Reference

Compact reference for all o3de-mcp tools. Optimized for agent consumption.

---

## Editor Tools

Require a running O3DE Editor with RemoteConsole + EditorPythonBindings gems.

### run_editor_python

Execute arbitrary Python in the editor. Full `azlmbr` API access.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `script` | str | yes | Python code to run in editor |

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

### enter_game_mode

Enter play-in-editor mode. No parameters.

### exit_game_mode

Exit game mode, return to edit mode. No parameters.

### undo

Undo the last editor action. No parameters.

### redo

Redo the last undone action. No parameters.

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

---

## Input Validation Rules

All tools validate inputs before execution:

- **Entity IDs**: Numeric only — `1234` or `[1234]`
- **Component types**: Alphanumeric, spaces, hyphens, underscores, parentheses
- **Project/gem names**: Start with letter, then alphanumeric/hyphens/underscores
- **Paths**: Resolved to absolute; `must_exist` tools verify the path exists
- **Build configs**: Allowlisted to `debug`, `profile`, `release`
