# Example 6: CLI-Only Workflow (No Editor)

Working with o3de-mcp when the O3DE Editor is not running or the AiCompanion
gem is not enabled. This covers project management, gem creation, builds, and
export. All operations are done via CLI tools.

## Prerequisites

- O3DE engine installed and registered
- `o3de-mcp` server running

> **Note:** This example shows everything you can do without a running editor
> and without the AiCompanion gem enabled.

## Steps

### 1. Check what's available

**Tool call:**
```json
{"tool": "get_capabilities"}
```

**Expected response (editor unreachable, CLI available):**
```json
{
  "editor": {
    "status": "unreachable",
    "host": "127.0.0.1",
    "port": 4600,
    "hint": "Start the O3DE Editor with the AiCompanion and EditorPythonBindings gems enabled."
  },
  "cli": {
    "available": true,
    "path": "/opt/O3DE/24.09/scripts/o3de.sh",
    "engine_path": "/opt/O3DE/24.09",
    "engine_version": "24.09"
  },
  "tool_categories": {
    "editor_tools": {"available": false, "reason": "Editor not connected", "tool_count": 70},
    "project_tools": {"available": true, "reason": null, "tool_count": 17},
    "asset_tools": {"available": true, "reason": null, "tool_count": 5},
    "introspection_tools": {"available": true, "reason": null, "tool_count": 3},
    "capabilities_tools": {"available": true, "reason": null, "tool_count": 1}
  }
}
```

Each category also carries a `tools` array with its tool names, left out here
for brevity.

The response tells you: project tools are available, editor tools are not.
Focus on project management.

### 2. Discover available templates

**Tool call:**
```json
{"tool": "list_templates"}
```

**Expected response:**
```json
[
  {
    "template_name": "DefaultProject",
    "display_name": "Default Project",
    "summary": "A basic O3DE project with standard settings",
    "path": "/opt/O3DE/24.09/Templates/DefaultProject"
  },
  {
    "template_name": "MinimalProject",
    "display_name": "Minimal Project",
    "summary": "Bare-bones project with minimal dependencies",
    "path": "/opt/O3DE/24.09/Templates/MinimalProject"
  }
]
```

### 3. Create a project

**Tool call:**
```json
{
  "tool": "create_project",
  "arguments": {
    "name": "RacingGame",
    "path": "<your_projects_dir>/RacingGame"
  }
}
```

### 4. Enable gems

**Tool calls (sequential):**
```json
{"tool": "enable_gem", "arguments": {"gem_name": "PhysX", "project_path": "<your_projects_dir>/RacingGame"}}
{"tool": "enable_gem", "arguments": {"gem_name": "Terrain", "project_path": "<your_projects_dir>/RacingGame"}}
```

### 5. Build the project

**Tool call:**
```json
{
  "tool": "build_project",
  "arguments": {
    "project_path": "<your_projects_dir>/RacingGame",
    "config": "profile"
  }
}
```

### 6. Export for distribution

Once the game is ready, package it:

**Tool call:**
```json
{
  "tool": "export_project",
  "arguments": {
    "project_path": "<your_projects_dir>/RacingGame",
    "output_path": "<your_exports_dir>/RacingGame-Release",
    "config": "release"
  }
}
```

### 7. Disable unwanted gems

If you added a gem that isn't needed:

**Tool call:**
```json
{
  "tool": "disable_gem",
  "arguments": {
    "gem_name": "Terrain",
    "project_path": "<your_projects_dir>/RacingGame"
  }
}
```

## What's Available Without the Editor

| Tool | Available | Notes |
|------|-----------|-------|
| `get_capabilities` | Yes | Always available |
| `get_engine_info` | Yes | Reads engine.json |
| `list_projects` | Yes | Reads manifest |
| `list_gems` | Yes | Reads manifest |
| `list_project_gems` | Yes | Reads the project's project.json |
| `list_templates` | Yes | Reads engine Templates/ |
| `create_project` | Yes | CLI: create-project |
| `create_gem` | Yes | CLI: create-gem |
| `enable_gem` | Yes | CLI: enable-gem |
| `disable_gem` | Yes | CLI: disable-gem |
| `register_gem` | Yes | CLI: register |
| `register_engine` | Yes | CLI: register --engine-path |
| `set_active_engine` | Yes | Sets O3DE_ENGINE_NAME for this server process |
| `build_project` | Yes | CMake configure + build |
| `start_build` | Yes | Background CMake build, returns a build ID |
| `get_build_status` | Yes | Polls a `start_build` build |
| `export_project` | Yes | CLI: export-project |
| `edit_project_properties` | Yes | CLI: edit-project-properties |
| `get_asset_processor_status` | Yes | Checks for a running Asset Processor process |
| `wait_for_assets` | Yes | Waits for the Asset Processor process to exit |
| `refresh_assets` | Yes | Runs AssetProcessorBatch --refresh |
| `tail_log` | Yes | Reads the project's log files |
| `get_log_errors` | Yes | Reads the project's log files |
| `get_bus_schema` | Yes | Reads the editor's generated azlmbr stubs from disk |
| `list_levels` | Yes | Reads the project's Levels/ directory |
| Editor tools (70, except `list_levels`) | **No** | Require running editor (includes the per-asset readiness tools `get_asset_status`, `get_asset_jobs`, `get_asset_processor_connection` and `wait_for_asset`) |

## What's Next

- Launch the O3DE Editor with AiCompanion + EditorPythonBindings gems
- Use the editor tools for scene construction: [Example 2](02_build_scene.md)
