# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **20 new tools** across 4 categories:
  - **Editor tools (15 new):**
    - `set_transform`, `get_transform`, `set_parent` — entity transform management
    - `remove_component` — remove components from entities
    - `assign_asset` — assign assets to component properties by path
    - `run_console_command`, `get_cvar`, `set_cvar` — console/CVAR control
    - `create_level`, `list_levels` — level creation and listing
    - `get_viewport_camera`, `set_viewport_camera`, `focus_entity`, `capture_viewport` — viewport camera and screenshot
    - `instantiate_prefab`, `create_prefab_from_entity`, `save_prefab` — prefab manipulation
    - `begin_session`, `exec_in_session`, `end_session`, `get_session_vars` — persistent Python sessions
  - **Project tools (5 new):**
    - `list_project_gems` — list gems enabled in a specific project
    - `register_engine`, `set_active_engine` — engine registration
    - `start_build`, `get_build_status` — async background builds with process tracking
  - **Asset tools (5 new, new `assets.py` module):**
    - `get_asset_processor_status`, `wait_for_assets`, `refresh_assets` — AP monitoring
    - `tail_log`, `get_log_errors` — log file reading and error extraction
  - **Introspection tools (2 new):**
    - `get_bus_schema_live` — live BehaviorContext queries with stub fallback
    - `capture_renderdoc_frame` — RenderDoc capture trigger for cross-MCP workflow
- `live_editor` pytest marker for integration tests requiring a running editor
  (skipped unless `O3DE_LIVE_EDITOR_TEST=1`)
- New tool categories in `get_capabilities`: `asset_tools`, `introspection_tools`
- New validators: `_validate_vec3`, `_validate_console_command`, `_validate_prefab_path`
- `atexit` handler to terminate orphaned background build processes

### Changed

- `get_capabilities` now reports 5 tool categories (was 3): added `asset_tools`
  and `introspection_tools`

### Fixed — O3DE 2.7.0 API compatibility

- **`run_console_command` / `set_cvar` / `get_cvar`**: Fixed CVAR name casing
  (`r_displayInfo` → `r_DisplayInfo`). O3DE CVARs are case-sensitive.
- **`capture_viewport`**: Replaced the non-existent `r_ScreenShot` console command
  (CryEngine legacy, removed in O3DE 2.7.0) with a PySide6 `QWidget.grab()` of the
  editor's `ViewportUiOverlay` widget. This captures just the 3D viewport, not the
  full screen.
- **`get_viewport_camera`**: Replaced broken `EditorCameraRequestBus` EBus calls
  (which return `None` in the Python bindings) with
  `general.get_current_view_position()` / `get_current_view_rotation()`. Rotation
  is now 3-element Euler angles (was 4-element quaternion). FOV is no longer
  reported (not available via the Python bindings).
- **`set_viewport_camera`**: Replaced `ed_cameraPos` / `ed_cameraRot` console
  commands with `general.set_current_view_position()` /
  `set_current_view_rotation()` using `math.Vector3`. Rotation validation now
  expects 3 elements (Euler angles) instead of 4 (quaternion).

### Fixed — connection pool robustness

- **Event-loop safety**: `_EditorConnectionPool` now detects when the asyncio
  event loop has changed (e.g. `asyncio.run()` creates a new loop each call) and
  recreates the `asyncio.Lock`, force-closes the dead-loop socket, and reconnects.
  Previously, a loop change caused `RuntimeError` or stale-connection hangs.
- **Connection retry**: Added 3-attempt retry with backoff for the AgentServer's
  single-client connection policy. Rapid reconnects after closing a previous
  connection could be refused.
- **Lock lifetime**: The pool tracks the event loop that owns its `asyncio.Lock`
  separately from the connection's loop, so the lock is recreated only on an
  actual loop change (not on every reconnect). This keeps concurrent calls
  serialized against the single-client AgentServer. The fast-fail window stays
  at 5s.

### Fixed — tests

- `test_live_editor.py`: Reuse a single event loop across all live tests to
  avoid unnecessary reconnect churn with the AgentServer's single-client policy.
- `test_live_no_editor.py`: Replaced runtime `_skip_if_editor_running()` socket
  probes with a `@requires_no_editor` pytest marker (evaluated once at import).
- `test_project.py` / `test_live_no_editor.py`: Updated `get_build_status` empty-
  ID tests to expect a `ValueError` (raised by the tool) instead of a JSON error
  response.

### Fixed — post-merge follow-ups

- **`get_build_status`**: Wait (bounded) for the output drain thread to flush
  before reading and evicting a finished build, so a failed build's final error
  lines are no longer lost to a race between process exit and the drain thread.
- **`get_capabilities`**: Report `introspection_tools` as available even when the
  editor is disconnected — `get_bus_schema` reads `.pyi` stubs from disk and does
  not need a running editor (only `get_bus_schema_live` and
  `capture_renderdoc_frame` do).
- **Live tests**: `get_bus_schema_live` test passes `project_path` so the stub
  fallback resolves on machines with several stub dumps (and accepts the
  `stub_fallback_failed` status); `get_asset_processor_status` test tolerates the
  Asset Processor being down; the transform test also handles a bracketed
  `[EntityId]` create-entity form.
- **CI robustness**: `test_cli_available` and `test_get_engine_info` now depend
  on the existing `engine_path` fixture, so they skip when no O3DE engine is
  installed instead of failing on a bare CI runner.
- Applied `ruff format` to `test_capabilities.py` and `test_live_no_editor.py`.

### Previous additions

- `O3DE_EDITOR_TIMEOUT` env var (default: **600s**) for the per-command editor
  execution timeout, so slower editor operations are not cut off. The editor
  runs each script synchronously and does not reply until it finishes, so this
  value is effectively "how long an editor operation may take."
- `O3DE_EDITOR_CONNECT_TIMEOUT` env var (default: 5s) — a separate TCP connect
  timeout so an unreachable editor is detected in milliseconds even when a long
  command timeout is configured.
- `run_editor_python` now accepts an optional per-call `timeout` argument to
  raise the execution ceiling for known-heavy scripts.
- `get_bus_schema` tool: generic, gem-agnostic discovery of any reflected EBus
  API by reading the editor's generated `azlmbr` stubs. Resolves the project
  from `O3DE_PROJECT_PATH` or the single registered project with a stub dump.

### Changed

- Raised the default editor command timeout from 10s to 600s. 10s was far too
  short for real editor operations (level loads, game-mode entry, on-demand
  asset compilation), causing spurious `timeout` errors while the editor was
  still working — the change that most deterred use.
- Timeout errors now state that the *command* did not complete (and the editor
  may still be running the script) and point at `O3DE_EDITOR_TIMEOUT`, instead
  of misattributing the failure to the connection.

### Fixed

- Legacy RemoteConsole fallback was broken: after protocol detection reconnected
  for the legacy path, `send_script` used the stale (already-closed) socket and
  lost the pooled connection identity, so every legacy call returned empty/errored
  and reconnected. Detection now repoints the pool at the reconnected socket.
- `create_entity` referenced the unbound name `azlmbr` (only `azlmbr.entity` was
  imported, as `entity`), risking a `NameError`; it now uses `entity.EntityId(...)`
  consistently with the other entity tools.
- `load_level` now calls `open_level_no_prompt` instead of `open_level`, so the
  level switch actually happens without popping a modal confirmation dialog that
  a headless/automated session cannot dismiss. It also strips a leading `Levels/`
  from the path (`open_level_no_prompt` wants the bare level name, so the
  documented `Levels/MyLevel` form previously returned `False` without switching),
  reports the level the editor actually landed on, and surfaces an explicit error
  when the open fails instead of falsely claiming success.
- `list_entities` no longer fails with `NameError: name 'editor' is not defined`
  — the generated editor script now imports `azlmbr.editor` and uses an
  unfiltered `SearchFilter` so it reliably returns all entities.

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
- **O3DE 2510+ API compatibility**: Editor tools now work with the updated
  EditorComponentAPIBus API in O3DE 2510+, with backward-compatible fallbacks.
  - `add_component`: Uses `AddComponentOfType` (singular) via `bus.Broadcast`
    with `Outcome` checking; falls back to legacy `AddComponentsOfType`.
  - `get_entity_components`: Probe-based `HasComponentOfType` approach replaces
    `GetComponentsOfEntity` which returns `None` in 2510+.
  - `get_component_property` / `set_component_property`: Resolve
    `EntityComponentIdPair` via `GetComponentOfType` before accessing
    properties; falls back to legacy bare `EntityId` approach.
- **PhysX component names**: Updated all documentation and examples to use
  O3DE 2510+ names (`PhysX Primitive Collider`, `PhysX Dynamic Rigid Body`).
- **Mesh property path**: Corrected `Mesh|Model Asset` to
  `Controller|Configuration|Model Asset` in documentation.
- **Inline script patterns**: All `run_editor_python` examples in docs now
  use `AddComponentOfType` (singular) with `bus.Broadcast` and
  `EntityComponentIdPair` for property access.

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
