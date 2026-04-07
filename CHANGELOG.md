# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-04-07

### Added

- **AgentServer protocol support**: Length-prefixed JSON framing for communication
  with the AiCompanion gem's built-in AgentServer (replaces RemoteConsole dependency).
  - `_build_framed_request()` — constructs length-prefixed JSON messages
  - `_recv_framed()` / `_async_recv_framed()` — reads length-prefixed responses
  - Automatic protocol detection: sends a framed `ping` on first connect;
    falls back to legacy RemoteConsole text protocol if the server doesn't respond
    with valid JSON.
- **TLS client support**: Optional encrypted connections via `O3DE_EDITOR_TLS`,
  `O3DE_EDITOR_TLS_VERIFY`, and `O3DE_EDITOR_TLS_CA` env vars.
- **Architecture documentation**: System diagram (Mermaid) and communication flow
  documentation in `docs/architecture.md`.
- **MCP Inspector example** (`examples/08_mcp_inspector.md`): Walkthrough for
  interactively testing tools via the MCP Inspector web UI.
- **Server version reporting**: MCP server now reports the actual package version
  (from `importlib.metadata`) instead of a default. Falls back to `0.0.0-dev`
  when the package is not installed.

### Changed

- Updated project description to lead with value proposition:
  "Automate Open 3D Engine with AI."
- README now includes an MCP Inspector section under Usage.
- `_EditorConnectionPool` now uses `send_script()` (was `send_command()`),
  dispatching to framed or legacy protocol based on auto-detection.
- Updated capability probe hint to reference AiCompanion instead of RemoteConsole.
- Error messages now reference AiCompanion AgentServer instead of RemoteConsole.
- README now links to [o3de-ai-companion-gem](https://github.com/nickschuetz/o3de-ai-companion-gem)
  and [EditorPythonBindings](https://docs.o3de.org/docs/api/gems/editorpythonbindings/index.html)
  documentation. Added Related Projects section.

### Fixed

- **Windows Visual Studio detection**: CMake generator is now auto-detected
  via `vswhere.exe` instead of being hardcoded to `Visual Studio 17 2022`.
  This supports all VS editions and versions (2017, 2019, 2022, 2026, etc.).
  Falls back to CMake's default if detection fails.
- **Mypy type errors**: Added explicit type annotations to framed protocol
  helpers (`_recv_framed`, `_async_recv_framed`) and `str()` casts for
  `json.loads` return values in editor tools.

## [0.2.0] - 2026-04-03

### Added

- **Capability detection** (`get_capabilities` tool):
  - Runtime probing of editor connectivity and CLI availability.
  - Dynamic tool discovery from the FastMCP registry — unknown tools
    appear in an `other_tools` category so new tools are never hidden.
  - Returns structured JSON with editor status, CLI info, and per-category
    tool availability.
- **5 new project tools** (CLI-based, no editor required):
  - `disable_gem` — complement to `enable_gem`.
  - `create_gem` — create custom gems from templates.
  - `export_project` — package projects for distribution.
  - `edit_project_properties` — modify project metadata.
  - `list_templates` — discover available project/gem templates.
- **Enhanced engine discovery**:
  - `O3DE_ENGINE_NAME` env var to select a specific engine when multiple
    are registered.
  - `python/o3de.py` fallback when `scripts/o3de.sh` is absent.
  - CLI path caching to avoid repeated filesystem checks.
  - `find_o3de_engine_version()`, `find_all_engines()`,
    `list_available_templates()` utility functions.
- **Editor fast-fail**: Connection pool skips re-probing for 5 seconds
  after a failure, returning `editor_unavailable` immediately instead of
  timing out repeatedly.
- `O3DE_EXPORT_TIMEOUT` env var (default: 3600s) for long-running exports.
- New examples: CLI-only workflow (`06`), gem development (`07`).
- 37 new tests (93 total).

### Changed

- `get_capabilities` response now includes a `tools` list per category
  with actual tool names, not just counts.
- Engine discovery prefers engines with a valid `engine.json` when
  multiple are registered (was: always `engines[0]`).
- Updated all existing examples to reference `get_capabilities()` and
  note editor connectivity requirements.
- Expanded AGENTS.md decision tree, recipes, and tool reference for new tools.

## [0.1.0] - 2026-04-02

### Added

- Initial release of o3de-mcp.
- **Editor tools** (16 tools):
  - `run_editor_python` — execute arbitrary Python in the editor
  - `list_entities`, `create_entity`, `delete_entity`, `duplicate_entity`
  - `get_entity_components`, `add_component`
  - `get_component_property`, `set_component_property`
  - `load_level`, `get_level_info`, `save_level`
  - `enter_game_mode`, `exit_game_mode`
  - `undo`, `redo`
- **Project tools** (7 tools):
  - `get_engine_info`, `list_projects`, `list_gems`
  - `create_project`, `register_gem`, `enable_gem`
  - `build_project`
- Input validation for entity IDs, component types, project/gem names, paths.
- Injection-safe parameter passing via JSON round-trip for editor scripts.
- Configurable editor connection via `O3DE_EDITOR_HOST` / `O3DE_EDITOR_PORT` env vars.
- Engine discovery via `O3DE_ENGINE_PATH` env var or `~/.o3de/o3de_manifest.json`.
- GitHub Actions CI: lint, type checking, tests (Python 3.10 + 3.12), SBOM generation.
- CycloneDX SBOM generation via `python scripts/generate-sbom.py`.
- Comprehensive documentation: tool reference, recipes, component catalog, 5 progressive examples.
- Agent-optimized guide (`AGENTS.md`) for token-efficient usage.
- Dual-licensed under Apache-2.0 OR MIT (matching O3DE).
