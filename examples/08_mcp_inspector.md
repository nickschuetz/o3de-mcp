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

In the Inspector UI, click **Tools** in the left sidebar. You should see all
registered tools listed — capabilities, editor, and project tools.

### 3. Check capabilities

Select `get_capabilities` from the tool list and click **Run**. No parameters
needed.

**Expected response (editor running):**
```json
{
  "editor": {
    "status": "connected",
    "host": "127.0.0.1",
    "port": 4600,
    "protocol": "AgentServer"
  },
  "cli": {
    "status": "available",
    "engine_path": "/path/to/o3de",
    "engine_version": "2310.1"
  }
}
```

### 4. List registered projects

Select `list_projects` and click **Run**.

**Expected response:**
```json
{
  "projects": [
    {
      "name": "MyGame",
      "path": "/home/user/o3de-projects/MyGame"
    }
  ]
}
```

### 5. Test editor tools

Select `list_entities` and run it. This sends a command to the running editor
and returns the entity hierarchy for the current level.

> **Tip:** If the editor is not running, you'll get a clear error:
> `Editor is not reachable at 127.0.0.1:4600`

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
