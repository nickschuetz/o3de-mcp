# Example 1: Create a New O3DE Project

End-to-end walkthrough: from zero to a built project ready for the editor.

## Prerequisites

- O3DE engine installed and registered
- `o3de-mcp` server running

> **Platform note:** This example uses placeholder paths. Replace them with
> absolute paths appropriate for your OS:
> - **Linux:** `/home/user/projects/SpaceExplorer`
> - **macOS:** `/Users/user/projects/SpaceExplorer`
> - **Windows:** `C:\Users\YourName\projects\SpaceExplorer`

## Steps

### 1. Verify the engine is available

**Tool call:**
```json
{"tool": "get_engine_info"}
```

**Expected response (paths vary by OS and install location):**
```json
{
  "engine_name": "o3de",
  "version": "2305.0",
  "engine_path": "/opt/O3DE/24.09"
}
```

### 2. Create the project

**Tool call:**
```json
{
  "tool": "create_project",
  "arguments": {
    "name": "SpaceExplorer",
    "path": "<your_projects_dir>/SpaceExplorer"
  }
}
```

**Expected response:**
```
Project 'SpaceExplorer' created at <your_projects_dir>/SpaceExplorer
```

### 3. Enable required gems

The editor tools require RemoteConsole and EditorPythonBindings. Enable them
along with any gameplay gems you need:

**Tool calls (sequential):**
```json
{"tool": "enable_gem", "arguments": {"gem_name": "RemoteConsole", "project_path": "<your_projects_dir>/SpaceExplorer"}}
{"tool": "enable_gem", "arguments": {"gem_name": "EditorPythonBindings", "project_path": "<your_projects_dir>/SpaceExplorer"}}
{"tool": "enable_gem", "arguments": {"gem_name": "PhysX", "project_path": "<your_projects_dir>/SpaceExplorer"}}
{"tool": "enable_gem", "arguments": {"gem_name": "Stars", "project_path": "<your_projects_dir>/SpaceExplorer"}}
```

### 4. Build the project

**Tool call:**
```json
{
  "tool": "build_project",
  "arguments": {
    "project_path": "<your_projects_dir>/SpaceExplorer",
    "config": "profile"
  }
}
```

**Expected response:**
```
Project built successfully (config=profile)
```

### 5. Verify registration

**Tool call:**
```json
{"tool": "list_projects"}
```

The response should include your new project in the list.

## What's Next

Open the O3DE Editor for this project, then use the editor tools:
- [Example 2: Build a Scene](02_build_scene.md)
- [Example 3: Add Physics](03_physics_playground.md)
