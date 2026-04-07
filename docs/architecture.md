# Architecture

This document describes the high-level architecture of **o3de-mcp** — an MCP server that bridges AI assistants and the Open 3D Engine.

## Overview

o3de-mcp exposes O3DE capabilities through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io), enabling AI assistants (Claude Code, Claude Desktop, or any MCP-compatible client) to automate the O3DE Editor and manage projects, gems, and builds.

Editor communication relies on the [**o3de-ai-companion-gem**](https://github.com/nschuetz/o3de-ai-companion-gem) — an O3DE Gem that runs an AgentServer inside the editor, accepting Python script execution requests over a length-prefixed JSON protocol. The gem also bundles [**EditorPythonBindings**](https://docs.o3de.org/docs/api/gems/editorpythonbindings/index.html) support, giving scripts access to the full `azlmbr` API.

## Diagram

```mermaid
---
config:
  themeVariables:
    fontSize: 14px
  flowchart:
    nodeSpacing: 30
    rankSpacing: 40
---
graph LR
    subgraph AI["AI Assistant"]
        CC["Claude Code<br/>Claude Desktop<br/>MCP Client"]
    end

    subgraph MCP["o3de-mcp Server"]
        S["server.py<br/>(FastMCP)"]
        CAP["capabilities.py<br/>get_capabilities"]
        ED["editor.py<br/>Entity, Component,<br/>Level, Game Mode"]
        PR["project.py<br/>Project, Gem,<br/>Build, Export"]
        UC["utils/capabilities.py<br/>Probe editor & CLI"]
        UO["utils/o3de.py<br/>Engine discovery,<br/>CLI runner"]
    end

    subgraph O3DE["O3DE Editor"]
        AS["AgentServer<br/>(AiCompanion Gem)"]
        EPB["EditorPythonBindings<br/>(azlmbr API)"]
    end

    subgraph CLI["O3DE CLI"]
        SCRIPT["scripts/o3de.sh<br/>scripts/o3de.bat"]
    end

    subgraph FS["Filesystem"]
        MANIFEST["~/.o3de/<br/>o3de_manifest.json"]
    end

    CC -- "MCP protocol<br/>(stdio)" --> S
    S --> CAP
    S --> ED
    S --> PR
    CAP --> UC
    ED -- "TCP :4600<br/>(length-prefixed JSON)" --> AS
    AS --> EPB
    PR --> UO
    UO -- subprocess --> SCRIPT
    UO -- reads --> MANIFEST
    UC --> UO
    UC -- "TCP probe" --> AS

    style AI fill:#e8f0fe,stroke:#4285f4
    style MCP fill:#fef7e0,stroke:#f9ab00
    style O3DE fill:#e6f4ea,stroke:#34a853
    style CLI fill:#fce8e6,stroke:#ea4335
    style FS fill:#f3e8fd,stroke:#a142f4
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
