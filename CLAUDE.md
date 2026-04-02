# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

An MCP server (Model Context Protocol) that exposes Open 3D Engine (O3DE) capabilities to AI assistants. Two tool categories:
- **Editor tools** (`src/o3de_mcp/tools/editor.py`) — send Python scripts to a running O3DE Editor via its remote console socket (port 4600). Requires RemoteConsole + EditorPythonBindings gems active in the editor.
- **Project tools** (`src/o3de_mcp/tools/project.py`) — wrap the O3DE CLI (`scripts/o3de.sh` / `o3de.bat`) and CMake for project creation, gem management, and builds.

## Commands

```bash
# Install (editable, with dev tools)
pip install -e ".[dev]"

# Run the MCP server
o3de-mcp

# Tests
pytest
pytest tests/test_project.py::TestValidateName::test_valid_simple  # single test

# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Type checking
mypy src/

# Generate SBOM (CycloneDX)
python scripts/generate-sbom.py
```

## Architecture

```
src/o3de_mcp/
├── server.py          # FastMCP entry point — registers all tools, called via `o3de-mcp` CLI
├── tools/
│   ├── editor.py      # Editor automation tools (socket → remote console)
│   └── project.py     # Project/build management tools (subprocess → o3de CLI + cmake)
└── utils/
    └── o3de.py         # Engine/manifest discovery, CLI runner, project/gem listing
```

- **server.py** creates a `FastMCP` instance and calls `register_*_tools(mcp)` from each tool module. Each tool module defines a `register_*_tools` function that decorates functions with `@mcp.tool()`.
- **utils/o3de.py** handles O3DE engine discovery via `O3DE_ENGINE_PATH` env var or `~/.o3de/o3de_manifest.json`. All subprocess calls to the O3DE CLI go through `run_o3de_cli()`.
- Editor tools use raw TCP sockets to send `pyRunScript` commands. Host/port are configurable via `O3DE_EDITOR_HOST` and `O3DE_EDITOR_PORT` env vars (default: `127.0.0.1:4600`). The scripts use the `azlmbr` namespace available inside the O3DE Editor Python environment.

## Key Conventions

- Tools are registered via `register_*_tools(mcp: FastMCP)` pattern — add new tool modules by creating a file in `tools/`, defining this function, and calling it from `server.py`.
- All O3DE path discovery is centralized in `utils/o3de.py` — never hardcode engine paths elsewhere.
- Python 3.10+ is required (uses `X | Y` union types).
- Ruff is used for both linting and formatting (line length 100). Run `ruff check --fix` and `ruff format` before committing.
- All user-supplied strings that flow into editor scripts must be passed via `json.dumps`/`json.loads` round-trip — never interpolate raw user input into Python code strings.
- Validate inputs at tool boundaries: entity IDs, component types, project/gem names, and filesystem paths all have dedicated validators.
- All source files must include the O3DE-style SPDX header: `# Copyright (c) Contributors to the Open 3D Engine Project.` / `# For complete copyright and license terms please see the LICENSE at the root of this distribution.` / `#` / `# SPDX-License-Identifier: Apache-2.0 OR MIT`.
- CI runs lint, type checking (mypy), tests, and SBOM generation via GitHub Actions. PyPI publishing triggers on GitHub releases.
- SBOM is generated via `cyclonedx-bom` in an isolated venv (runtime deps only). Generated files (`sbom.cdx.json`, `sbom.cdx.xml`) are gitignored — they're CI artifacts, not checked in.
- Pre-commit hooks are configured for ruff linting/formatting. Install with `pre-commit install`.

## Documentation

- `AGENTS.md` — Agent-specific guide: token efficiency rules, quick reference, decision tree, error handling. Read this first when using the MCP tools as an AI agent.
- `docs/tool-reference.md` — Compact parameter reference for all tools.
- `docs/recipes.md` — Composable game-dev patterns (scene setup, physics, lighting, scripting).
- `docs/components.md` — O3DE component name catalog with dependency chains. Component names must be exact — use this as the source of truth.
- `examples/` — Five progressive walkthroughs: project creation → scene building → physics → scripted game → batch operations.
