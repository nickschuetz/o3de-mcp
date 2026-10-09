# Example 8: Testing with MCP Inspector

Using [MCP Inspector](https://github.com/modelcontextprotocol/inspector) to
interactively test o3de-mcp tools through a web UI — no AI assistant required.

## Prerequisites

- Node.js 18+ (for `npx`)
- `o3de-mcp` installed (`pip install -e .`)
- O3DE engine installed and registered (for project/build tools)
- O3DE Editor running with the o3de-ai-companion-gem enabled (for editor tools, optional)

## Steps

### 1. Launch the Inspector

```bash
npx @modelcontextprotocol/inspector o3de-mcp
```

This starts two services:
- **Inspector UI:** `http://localhost:6274`
- **Proxy server:** port `6277`

Open `http://localhost:6274` in your browser.

### 2. Browse available tools

In the Inspector UI, click **Tools** in the left sidebar. You should see all 92
registered tools, from the seven tool modules: capabilities, editor,
introspection, project, assets, Track View and animation.

### 3. Check capabilities

Select `get_capabilities` from the tool list and click **Run**. No parameters
needed.

**Expected response (editor running with the AiCompanion gem):**
```json
{
  "editor": {
    "status": "connected",
    "host": "127.0.0.1",
    "port": 4600,
    "agent_server": {
      "protocol_version": 1,
      "gem_version": "0.5.0",
      "api_version": "0.4.0"
    },
    "ai_companion_gem": true
  },
  "cli": {
    "available": true,
    "path": "/opt/O3DE/24.09/scripts/o3de.sh",
    "engine_path": "/opt/O3DE/24.09",
    "engine_version": "24.09"
  },
  "tool_categories": {
    "editor_tools": {"available": true, "reason": null, "tool_count": 66},
    "project_tools": {"available": true, "reason": null, "tool_count": 17},
    "asset_tools": {"available": true, "reason": null, "tool_count": 5},
    "introspection_tools": {"available": true, "reason": null, "tool_count": 3},
    "capabilities_tools": {"available": true, "reason": null, "tool_count": 1}
  }
}
```

Each category also carries a `tools` array with its tool names, left out here
for brevity. `editor_tools` counts the editor, Track View and animation tools
together (41 + 8 + 17).

### 4. List registered projects

Select `list_projects` and click **Run**.

**Expected response** (a JSON array holding each registered project's
`project.json` with its `path` added, abridged here):
```json
[
  {
    "project_name": "MyGame",
    "version": "1.0.0",
    "display_name": "MyGame",
    "engine": "o3de",
    "gem_names": ["Atom", "PhysX", "AiCompanion", "EditorPythonBindings"],
    "path": "/home/user/o3de-projects/MyGame"
  }
]
```

### 5. Test editor tools

Select `list_entities` and run it. This sends a command to the running editor
and returns a flat JSON array of `{"id", "name"}` objects for the current level.
For the parent/child hierarchy, run `get_entity_tree` instead.

> **Tip:** If the editor is not running, you'll get the standard error envelope:
> `{"status": "error", "code": "connection_refused", "message": "Could not connect to O3DE Editor on 127.0.0.1:4600. Ensure the editor is running with the AiCompanion gem enabled."}`
> A repeat call within a few seconds fails fast with `"code": "editor_unavailable"`
> and `"message": "O3DE Editor is not reachable on 127.0.0.1:4600. ..."`.

### 6. Test with custom environment variables

To point at a specific engine installation or editor port:

```bash
npx @modelcontextprotocol/inspector \
  -e O3DE_ENGINE_PATH=/opt/o3de \
  -e O3DE_EDITOR_PORT=4601 \
  o3de-mcp
```

### 7. Use custom ports for the Inspector itself

If the default ports conflict with other services:

```bash
CLIENT_PORT=8080 SERVER_PORT=9000 npx @modelcontextprotocol/inspector o3de-mcp
```

The UI will be at `http://localhost:8080` instead.

## What to use the Inspector for

- **Verifying tool registration** — confirm new tools appear after code changes
- **Testing parameter validation** — try invalid inputs and check error messages
- **Inspecting raw responses** — see exact JSON output without AI interpretation
- **Debugging editor connectivity** — test `get_capabilities` and editor tools in isolation
- **Developing new tools** — rapid iteration loop without restarting an AI assistant
