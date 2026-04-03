# Example 7: Gem Development

Create a custom O3DE gem, register it with a project, and build.

## Prerequisites

- O3DE engine installed and registered
- An existing project (see [Example 1](01_new_project.md))
- `o3de-mcp` server running

## Steps

### 1. Check capabilities

**Tool call:**
```json
{"tool": "get_capabilities"}
```

Verify that `cli.available` is `true`.

### 2. Create the gem

**Tool call:**
```json
{
  "tool": "create_gem",
  "arguments": {
    "name": "VehiclePhysics",
    "path": "<your_gems_dir>/VehiclePhysics"
  }
}
```

**Expected response:**
```
Gem 'VehiclePhysics' created at <your_gems_dir>/VehiclePhysics
```

This creates a gem directory with the standard O3DE gem structure:
```
VehiclePhysics/
├── Code/
│   └── Source/
├── gem.json
└── CMakeLists.txt
```

### 3. Register and enable the gem

**Tool calls (sequential):**
```json
{
  "tool": "register_gem",
  "arguments": {
    "gem_path": "<your_gems_dir>/VehiclePhysics",
    "project_path": "<your_projects_dir>/RacingGame"
  }
}
```

```json
{
  "tool": "enable_gem",
  "arguments": {
    "gem_name": "VehiclePhysics",
    "project_path": "<your_projects_dir>/RacingGame"
  }
}
```

### 4. Rebuild the project

The project must be rebuilt after adding a gem:

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

### 5. Verify the gem is registered

**Tool call:**
```json
{"tool": "list_gems"}
```

The response should include your new gem.

### 6. Update project properties (optional)

If the gem changes the project's purpose, update its metadata:

**Tool call:**
```json
{
  "tool": "edit_project_properties",
  "arguments": {
    "project_path": "<your_projects_dir>/RacingGame",
    "origin": "https://github.com/myorg/RacingGame"
  }
}
```

## Gem Development Workflow

```
create_gem → register_gem → enable_gem → build_project → iterate
```

After the initial setup, the development loop is:
1. Edit gem source code in `Code/Source/`
2. Rebuild with `build_project`
3. Test in the editor (if editor tools are available)

To remove a gem from a project:
```
disable_gem → build_project
```

## What's Next

- Use editor tools to test gem components: [Example 2](02_build_scene.md)
- Build a full game with physics: [Example 4](04_scripted_game.md)
