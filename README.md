# o3de-mcp

[![License](https://img.shields.io/badge/License-Apache_2.0_OR_MIT-blue.svg)](LICENSE.txt)

Automate [Open 3D Engine (O3DE)](https://o3de.org) with AI — an [MCP](https://modelcontextprotocol.io) server for editor control, project & build management.

See the [architecture documentation](docs/architecture.md) for a detailed system diagram and communication flow.

## Features

**Capability Detection**:
- `get_capabilities` — check editor connectivity and CLI availability before using other tools
- Dynamic tool discovery — new tools are automatically reported

**Editor Automation** (requires a running O3DE Editor with RemoteConsole gem):
- Execute arbitrary Python scripts inside the editor (`azlmbr` API)
- List, create, delete, and duplicate entities
- Add components, get/set component properties
- Load, save, and query levels
- Enter/exit game mode, undo/redo
- Fast-fail when editor is unreachable (avoids repeated timeouts)

**Project & Build Management** (CLI-based, no editor required):
- Discover local O3DE engine installations (multi-engine support)
- List registered projects, gems, and available templates
- Create projects and gems from templates
- Register, enable, and disable gems
- Edit project properties
- Build projects via CMake
- Export projects for distribution

## Prerequisites

- Python 3.10+
- O3DE installed and registered (engine path in the O3DE manifest or `O3DE_ENGINE_PATH` env var)
  - **Linux/macOS:** `~/.o3de/o3de_manifest.json`
  - **Windows:** `%USERPROFILE%\.o3de\o3de_manifest.json`
- For editor tools (optional): O3DE Editor running with the [**o3de-ai-companion-gem**](https://github.com/nickschuetz/o3de-ai-companion-gem) and **EditorPythonBindings** gems enabled. The companion gem provides the AgentServer that o3de-mcp connects to for real-time editor automation. Project tools work without the editor — call `get_capabilities()` to check what's available.

## Installation

```bash
pip install -e .
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv pip install -e .
```

## Usage

### As a standalone MCP server

```bash
o3de-mcp
```

### With Claude Code

Add to your MCP config (or use a project-level `.mcp.json`):
- **Linux/macOS:** `~/.claude/mcp.json`
- **Windows:** `%USERPROFILE%\.claude\mcp.json`

```json
{
  "mcpServers": {
    "o3de": {
      "command": "o3de-mcp"
    }
  }
}
```

### With Claude Desktop

Add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "o3de": {
      "command": "o3de-mcp"
    }
  }
}
```

### Testing with MCP Inspector

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) provides a web UI for interactively testing tools without an AI assistant. Useful for verifying tool behavior, inspecting responses, and debugging.

```bash
npx @modelcontextprotocol/inspector o3de-mcp
```

This opens the Inspector UI at `http://localhost:6274`. From there you can browse all registered tools, invoke them with custom parameters, and see raw responses.

To pass environment variables (e.g., a custom engine path or editor port):

```bash
npx @modelcontextprotocol/inspector -e O3DE_ENGINE_PATH=/path/to/engine -e O3DE_EDITOR_PORT=4600 o3de-mcp
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run a single test
pytest tests/test_project.py::TestValidateName::test_valid_simple

# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Type checking
mypy src/
```

### SBOM (Software Bill of Materials)

A CycloneDX SBOM is generated on every CI run and uploaded as a build artifact. To generate one locally:

```bash
python scripts/generate-sbom.py              # JSON + XML
python scripts/generate-sbom.py --format json # JSON only
```

The script creates an isolated virtual environment with only runtime dependencies, so the SBOM accurately reflects what ships — dev/build tooling is excluded.

### CI

GitHub Actions runs lint, type checking, tests, and SBOM generation on every push and PR to `main`. See [.github/workflows/ci.yml](.github/workflows/ci.yml).

### Security

- Editor tool inputs (entity IDs, component types) are validated against strict regex patterns before use.
- User-supplied strings are serialized via `json.dumps` / `json.loads` when passed into editor scripts — never raw string interpolation.
- Project and gem names are validated against O3DE naming conventions.
- Filesystem paths are resolved and validated before being passed to subprocesses.

## Documentation

| Document | Audience | Description |
|----------|----------|-------------|
| [AGENTS.md](AGENTS.md) | AI agents | Token-efficient usage guide, decision trees, error handling |
| [docs/architecture.md](docs/architecture.md) | Developers & agents | System architecture diagram and communication flows |
| [docs/tool-reference.md](docs/tool-reference.md) | Agents & developers | Compact parameter reference for all tools |
| [docs/recipes.md](docs/recipes.md) | Agents & developers | Composable patterns for scenes, physics, lighting, scripting |
| [docs/components.md](docs/components.md) | Agents & developers | O3DE component name catalog with dependency chains |

### Examples

Progressive walkthroughs from project creation to a complete game:

1. [New Project](examples/01_new_project.md) — create, configure, and build a project
2. [Build a Scene](examples/02_build_scene.md) — sky, lights, ground, camera, static objects
3. [Physics Playground](examples/03_physics_playground.md) — dynamic bodies, triggers, stacking
4. [Scripted Game](examples/04_scripted_game.md) — complete mini-game with player, obstacles, goals
5. [Batch Operations](examples/05_batch_operations.md) — efficient bulk entity creation patterns
6. [CLI-Only Workflow](examples/06_cli_only_workflow.md) — project management without the editor
7. [Gem Development](examples/07_gem_development.md) — create and integrate custom gems
8. [MCP Inspector](examples/08_mcp_inspector.md) — interactively test tools via a web UI

## Configuration

| Environment Variable | Description | Default |
|---|---|---|
| `O3DE_ENGINE_PATH` | Override automatic engine discovery | Auto-detected from manifest |
| `O3DE_ENGINE_NAME` | Select engine by name when multiple are registered | First valid engine |
| `O3DE_EDITOR_HOST` | Editor remote console host | `127.0.0.1` |
| `O3DE_EDITOR_PORT` | Editor remote console port | `4600` |
| `O3DE_CMAKE_GENERATOR` | CMake generator for builds | Auto-detected per platform |
| `O3DE_CONFIGURE_TIMEOUT` | CMake configure timeout (seconds) | `600` |
| `O3DE_BUILD_TIMEOUT` | CMake build timeout (seconds) | `1800` |
| `O3DE_EXPORT_TIMEOUT` | Project export timeout (seconds) | `3600` |

The server also reads the O3DE manifest for registered engines, projects, and gems:
- **Linux/macOS:** `~/.o3de/o3de_manifest.json`
- **Windows:** `%USERPROFILE%\.o3de\o3de_manifest.json`

## Related Projects

- [**o3de-ai-companion-gem**](https://github.com/nickschuetz/o3de-ai-companion-gem) — O3DE Gem that provides the AgentServer for editor-side communication. Required for editor automation tools. Enable it alongside [EditorPythonBindings](https://docs.o3de.org/docs/api/gems/editorpythonbindings/index.html) in your O3DE project.
- [**O3DE (Open 3D Engine)**](https://github.com/o3de/o3de) — The open-source game engine.

## License

This project is dual-licensed under [Apache 2.0](LICENSE-APACHE2.txt) or [MIT](LICENSE-MIT.txt) (your choice), matching the [O3DE engine license](https://github.com/o3de/o3de/blob/development/LICENSE.txt). Free for commercial and non-commercial use.

`SPDX-License-Identifier: Apache-2.0 OR MIT`
