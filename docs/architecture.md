# Architecture

This document describes the high-level architecture of **o3de-mcp** — an MCP server that bridges AI assistants and the Open 3D Engine.

## Overview

o3de-mcp exposes O3DE capabilities through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io), enabling AI assistants (Claude Code, Claude Desktop, or any MCP-compatible client) to automate the O3DE Editor and manage projects, gems, and builds.

Editor communication relies on the [**o3de-ai-companion-gem**](https://github.com/nschuetz/o3de-ai-companion-gem) — an O3DE Gem that runs an AgentServer inside the editor, accepting Python script execution requests over a length-prefixed JSON protocol. The gem also bundles [**EditorPythonBindings**](https://docs.o3de.org/docs/api/gems/editorpythonbindings/index.html) support, giving scripts access to the full `azlmbr` API.

## Diagram

```mermaid
graph LR
    subgraph AI["AI Assistant"]
        CC["Claude Code / Claude Desktop / MCP Client"]
    end

    subgraph MCP["o3de-mcp Server"]
        S["server.py (FastMCP)"]
        ED["editor.py"] & PR["project.py"] & CAP["capabilities.py"]
        UO["utils/o3de.py"]
    end

    subgraph O3DE["O3DE Ecosystem"]
        AS["AgentServer (AiCompanion Gem)"] --> EPB["EditorPythonBindings (azlmbr)"]
        SCRIPT["O3DE CLI (scripts/o3de.sh)"]
        MANIFEST["~/.o3de/o3de_manifest.json"]
    end

    CC -- "MCP (stdio)" --> S
    S --> ED & PR & CAP
    ED -- "TCP :4600" --> AS
    PR --> UO
    CAP --> UO
    UO -- subprocess --> SCRIPT
    UO -- reads --> MANIFEST

    style AI fill:#e8f0fe,stroke:#4285f4
    style MCP fill:#fef7e0,stroke:#f9ab00
    style O3DE fill:#e6f4ea,stroke:#34a853
```

## Communication Paths

### Editor tools (real-time automation)

```
MCP Client → o3de-mcp → TCP :4600 → AiCompanion AgentServer → azlmbr API
```

The [**o3de-ai-companion-gem**](https://github.com/nschuetz/o3de-ai-companion-gem) provides the AgentServer that listens on port 4600. o3de-mcp auto-detects the protocol on connection:

1. **AgentServer protocol** (preferred) — length-prefixed JSON framing with request/response semantics.
2. **Legacy RemoteConsole** (fallback) — raw text `pyRunScript` commands for older setups without the companion gem.

Scripts are base64-encoded for safe transport and executed in the editor's embedded Python interpreter.

### Project tools (CLI-based)

```
MCP Client → o3de-mcp → subprocess → scripts/o3de.sh (or .bat) → O3DE CLI
```

No running editor required. Engine discovery reads `~/.o3de/o3de_manifest.json` and supports multiple registered engines via `O3DE_ENGINE_NAME`.

### Capability detection

```
MCP Client → get_capabilities() → TCP probe + CLI probe → aggregated report
```

Always call `get_capabilities()` first to determine which tool categories are available before invoking other tools.

## Module Responsibilities

| Module | Role |
|--------|------|
| `server.py` | FastMCP entry point — registers all tool modules |
| `tools/capabilities.py` | Exposes `get_capabilities` tool |
| `tools/editor.py` | 16 editor automation tools — entity CRUD, components, levels, game mode |
| `tools/project.py` | 12 project management tools — create, build, export, gem management |
| `utils/capabilities.py` | Runtime probing logic (TCP connect check, CLI availability) |
| `utils/o3de.py` | Engine/manifest discovery, CLI runner, project/gem listing |

## Related Projects

- [**o3de-ai-companion-gem**](https://github.com/nschuetz/o3de-ai-companion-gem) — The O3DE Gem that enables editor-side communication. Provides the AgentServer that o3de-mcp connects to for real-time editor automation. Must be enabled in your O3DE project alongside [EditorPythonBindings](https://docs.o3de.org/docs/api/gems/editorpythonbindings/index.html) for editor tools to work.
- [**O3DE (Open 3D Engine)**](https://github.com/o3de/o3de) — The game engine itself.
