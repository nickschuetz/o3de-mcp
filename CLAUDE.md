# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

An MCP server (Model Context Protocol) that exposes Open 3D Engine (O3DE) capabilities to AI assistants. 92 tools across seven categories:
- **Capabilities tools** (`src/o3de_mcp/tools/capabilities.py`, 1 tool) — runtime detection of editor connectivity and CLI availability. Call `get_capabilities()` first to know what's available.
- **Editor tools** (`src/o3de_mcp/tools/editor.py`, 41 tools): send Python scripts to a running O3DE Editor over TCP port 4600. Covers entities, components, transforms, prefabs, levels, viewport/camera, console and CVARs, game mode, undo/redo, and persistent scripting sessions. Requires the AiCompanion and EditorPythonBindings gems active in the editor. Four of the tools (`get_scene_snapshot`, `get_entity_tree`, `get_entity`, `validate_scene`) use the AgentServer's native C++ request types instead of sending Python. `get_bus_schema_live`, `create_entity`, `set_transform` and `delete_entity` try their native request types first (`_native_bus_schema` in `tools/introspection.py`, `_native_mutation` in `tools/editor.py`) and fall back to editor Python when the gem answers `unknown_request_type` (too old to serve them) or the transport is the legacy RemoteConsole; a native refusal (validation, missing entity) is returned as an error, never retried through Python. `set_transform` uses editor Python directly for a rotation near a gimbal pole and refuses a non-uniform scale (a Transform's scale is uniform), and `get_bus_schema_live` falls back on any native failure, including an unknown bus. Fast-fails when the editor is unreachable.
- **Introspection tools** (`src/o3de_mcp/tools/introspection.py`, 3 tools) — EBus schema discovery (static stub parsing and live query) plus RenderDoc frame capture.
- **Project tools** (`src/o3de_mcp/tools/project.py`, 17 tools) — wrap the O3DE CLI (`scripts/o3de.sh` / `o3de.bat`) and CMake for project creation, gem management, engine registration, builds (blocking and background), and export.
- **Asset tools** (`src/o3de_mcp/tools/assets.py`, 5 tools) — Asset Processor status, asset refresh/wait, and log tailing.
- **Track View tools** (`src/o3de_mcp/tools/trackview.py`, 8 tools): cinematic sequence authoring: create/list/describe/delete sequences, set time range, add nodes (Director, Event, entity, component), and play/stop. Editor-Python over `azlmbr.legacy.trackview`; no gem request type. Track and keyframe authoring are intentionally not exposed (the reflected API's per-node parameter-type strings and record-only key workflow are not reliable to drive).
- **Animation tools** (`src/o3de_mcp/tools/animation.py`, 17 tools): EMotion FX anim graph reads (`list_anim_graphs`, `get_anim_graph`) and authoring (create/remove/load/save a graph, add/edit/remove nodes, set the entry state, add/remove parameters, add/edit/remove transitions with conditions, connect/disconnect blend-tree ports) over the AiCompanion gem's native C++ request types (gem main or 0.6.0+, plus the EMotionFX gem). Native only, no editor-Python fallback; work in secure mode. Writes refuse asset- or runtime-owned graphs, and each is an Animation Editor undo step, not one the `undo` tool reverts.

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

# Live editor suite in an isolated sandbox (required before a release, see docs/releasing.md)
O3DE_SANDBOX_PROJECT=/path/to/ProjectWithAiCompanion scripts/live-sandbox.sh up
scripts/live-sandbox.sh test
scripts/live-sandbox.sh down

# Refresh the reflected azlmbr surface used by tests/test_editor_scripts.py
# (run after moving to a new engine version; needs a project the editor has opened)
python scripts/extract-azlmbr-surface.py <project>/user/python_symbols/azlmbr tests/data/azlmbr_surface.json
```

## Architecture

```
src/o3de_mcp/
├── server.py            # MCPServer entry point — registers all tools, called via `o3de-mcp` CLI
├── tools/
│   ├── capabilities.py  # Capability detection tool (get_capabilities)
│   ├── editor.py        # Editor automation tools (socket → AgentServer)
│   ├── introspection.py # EBus schema discovery, RenderDoc capture
│   ├── project.py       # Project/build management tools (subprocess → o3de CLI + cmake)
│   ├── assets.py        # Asset Processor status, refresh/wait, log tailing
│   ├── trackview.py     # Track View cinematic sequence tools (editor-Python)
│   └── animation.py     # EMotion FX anim graph tools (native gem requests)
└── utils/
    ├── capabilities.py  # Runtime probing (editor connectivity, CLI availability)
    ├── errors.py        # The one failure envelope every tool returns
    ├── introspection.py # azlmbr stub parsing for the EBus schema
    └── o3de.py          # Engine/manifest discovery, CLI runner, project/gem listing
```

- **server.py** creates a `MCPServer` instance and calls `register_*_tools(mcp)` from each tool module. Each tool module defines a `register_*_tools` function that decorates functions with `@mcp.tool()`.
- **utils/capabilities.py** provides `probe_editor_connection()` (a ping script through the connection pool), `probe_agent_server_version()` (the gem's native `get_api_version`), `probe_cli()` (CLI availability), and `get_server_capabilities()` (aggregated report).
- **utils/o3de.py** handles O3DE engine discovery via `O3DE_ENGINE_PATH` env var or `~/.o3de/o3de_manifest.json`. Supports multiple engines via `O3DE_ENGINE_NAME`. All subprocess calls to the O3DE CLI go through `run_o3de_cli()`. Also provides `find_o3de_engine_version()`, `find_all_engines()`, `list_available_templates()`, and `find_asset_processor_batch()` (installed-SDK and source-build layouts).
- Editor tools talk to the editor over a raw TCP socket, auto-detecting the protocol on connect: the **AiCompanion gem's AgentServer** (length-prefixed JSON, preferred) with automatic fallback to the **legacy RemoteConsole** text `pyRunScript` protocol for setups without the companion gem. Host/port are configurable via `O3DE_EDITOR_HOST` and `O3DE_EDITOR_PORT` env vars (default: `127.0.0.1:4600`). Two separate timeouts apply: `O3DE_EDITOR_CONNECT_TIMEOUT` bounds the TCP connect (default: 5s) so an unreachable editor fails fast, while `O3DE_EDITOR_TIMEOUT` bounds per-command execution (default: 600s) — the editor runs each script synchronously and does not reply until done, so this is effectively "how long an editor op may take." `run_editor_python` also takes a per-call `timeout`. The scripts use the `azlmbr` namespace available inside the O3DE Editor Python environment.
- **utils/introspection.py** reads the editor's generated `azlmbr` stubs (`<project>/user/python_symbols/azlmbr/<module>.pyi`) to build a gem-agnostic EBus schema for the `get_bus_schema` tool. The project is resolved from the `O3DE_PROJECT_PATH` env var (or the single registered project with a stub dump), so set `O3DE_PROJECT_PATH` to disambiguate when several projects have dumps.

## Key Conventions

- Tools are registered via `register_*_tools(mcp: MCPServer)` pattern — add new tool modules by creating a file in `tools/`, defining this function, and calling it from `server.py`.
- All O3DE path discovery is centralized in `utils/o3de.py` — never hardcode engine paths elsewhere.
- Python 3.10+ is required (uses `X | Y` union types).
- Ruff is used for both linting and formatting (line length 100). Run `ruff check --fix` and `ruff format` before committing.
- Every editor tool's generated script is executed by `tests/test_editor_scripts.py` against the reflected `azlmbr` surface in `tests/data/azlmbr_surface.json`. A bus event, function or class that the editor does not reflect fails the test; so does the wrong call type, and so does calling a reflected function with the wrong number of arguments (the `create_level` bug: a 6-arg engine function called with 2). Check the surface file before calling anything new, and do not trust a mocked test that only echoes its own `mock_output`.
- All user-supplied strings that flow into editor scripts must be passed via `json.dumps`/`json.loads` round-trip — never interpolate raw user input into Python code strings.
- Every failure uses the one envelope `{"status": "error", "code": "<slug>", "message": "<text>"}`: `format_error` from `utils/errors.py` in server code, and `_o3de_fail(code, message)` inside generated editor scripts (prepended automatically when a script calls it). Never print a plain-text failure; an agent detects failure with `status == "error"`.
- Entity-id tool parameters use `EntityIdArg` / `OptionalEntityIdArg` from `tools/editor.py`, not `int | str`: the MCP layer JSON-decodes a string argument unless the parameter is annotated exactly `str`, which would turn `"[1234]"` into a list.
- Validate inputs at tool boundaries: entity IDs, component types, project/gem names, and filesystem paths all have dedicated validators.
- All source files must include the O3DE-style SPDX header: `# Copyright (c) Contributors to the Open 3D Engine Project.` / `# For complete copyright and license terms please see the LICENSE at the root of this distribution.` / `#` / `# SPDX-License-Identifier: Apache-2.0 OR MIT`.
- CI runs lint, type checking (mypy), tests, and SBOM generation via GitHub Actions. PyPI publishing triggers on GitHub releases.
- SBOM is generated via `cyclonedx-bom` in an isolated venv (runtime deps only). Generated files (`sbom.cdx.json`, `sbom.cdx.xml`) are gitignored — they're CI artifacts, not checked in.
- Pre-commit hooks are configured for ruff linting/formatting. Install with `pre-commit install`.

## Documentation

- `AGENTS.md` — Agent-specific guide: token efficiency rules, quick reference, decision tree, error handling. Read this first when using the MCP tools as an AI agent.
- `docs/tool-reference.md`: Compact parameter reference for all 92 tools.
- `docs/architecture.md` — System diagram, editor protocol details, and communication flow.
- `docs/releasing.md` covers the release checklist. The live editor suite (`scripts/live-sandbox.sh up|test|down`) is a required gate before tagging, and CI cannot run it.
- `docs/recipes.md` — Composable game-dev patterns (scene setup, physics, lighting, scripting).
- `docs/components.md` — O3DE component name catalog with dependency chains. Component names must be exact — use this as the source of truth.
- `skills/o3de-headless-and-editor-automation/` — Installable Agent Skill (SKILL.md, reference notes, `capture_level.py`, `compute_asset_guid.py`, a ScriptContext test template) for render verification and editor automation on Windows and Linux. Symlink it into `~/.claude/skills/` to use it here.
- `examples/` — Eight progressive walkthroughs: project creation → scene building → physics → scripted game → batch operations → CLI-only workflow → gem development → MCP Inspector.
