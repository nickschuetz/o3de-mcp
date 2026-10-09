# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.0] - 2026-10-09

Pairs with AiCompanion gem 0.6.0 (API 0.5.0); the animation, asset readiness and
native scale features need it. 96 tools. Highlights: EMotion FX anim graph reads and
authoring (17 tools), per-asset readiness (`wait_for_asset` and friends), real
non-uniform scale and native quaternions in `set_transform`, one failure envelope across
every tool, entity ids that survive 64-bit values, and a pre-release audit that fixed a
set of tools that reported success for things that did not happen.

### Changed

- **The last failures reported as successes, and three that never worked.** A
  pre-release audit found more paths outside the error envelope, now fixed:
  - `set_component_property` printed "Set ..." without checking the result, and
    `get_component_property` reported a failed read as `{"value": "None"}`. Both now
    check the outcome (`set_property_failed`, `get_property_failed`) and report an
    unknown component or one not on the entity.
  - `add_component` reported "Added" when the add raised or returned no outcome.
  - `get_cvar` answered a CVAR that does not exist with `"value": "(missing)"` (the
    engine's own text) and a failed read with `"value": "Error: ..."`; those are now
    `cvar_not_found` and `get_cvar_failed`. `get_viewport_camera` returned a bare
    `error` key; it now returns `viewport_camera_unavailable`.
  - `get_bus_schema_live` answered a bus missing from a real module as a live result
    with an `error` key; it now falls back to the stubs and reports `bus_not_found`.
  - Three fallbacks addressed Broadcast-only events with `bus.Event` and could never
    work; they are gone.
  - `instantiate_prefab` rebuilt its `parent_id` with `entity.EntityId(n)`, which is
    invalid on 26.10.0, so the parent was silently ignored. It now looks the parent up
    (an unknown one is `entity_not_found`).
  - With `O3DE_EDITOR_TLS_VERIFY=1` and no `O3DE_EDITOR_TLS_CA`, no CA was trusted, so
    every handshake failed. The system CA store is now loaded, as documented.
- **`set_transform` applies non-uniform scale for real, and stops faking it.** An O3DE
  Transform holds only a uniform scale, so a scale like `[50, 50, 1]` was applied as a
  uniform 50 and reported as success. On AiCompanion gem API 0.5.0+ (gem 0.6.0) the
  gem now applies it with the engine's Non-uniform Scale component (the editor
  Python API cannot add that component; tried live), and `set_transform` sends
  rotations as quaternions natively, which also removes the editor-Python detour
  for rotations at a gimbal pole. On older gems a non-uniform scale is refused with
  `non_uniform_scale_unsupported`. `get_transform` reports the effective scale with
  `uniform_scale` and `non_uniform_scale`. The editor-Python path also no longer
  resets an entity's scale to 1 when `scale` is not given, and it reads the scale
  back, reporting `set_transform_failed` when it did not land.
- **Entity ids are looked up, never rebuilt, in editor scripts.** The shared
  resolver tried `azlmbr.entity.EntityId(n)` first; on 26.10.0 that answers an
  invalid id for every `n` (reported by the AiCompanion session), so it only ever
  worked through its search fallback. It now always finds the entity's own id by
  its text, and an unknown id is the error `entity_not_found` instead of a
  traceback. Script refusals also keep the gem's own code (for example
  `secure_mode` when editor Python is disabled) instead of a generic `editor_error`.
- **`assign_asset` reports only an assignment that holds.** It printed "Assigned"
  without checking anything, then fell back to a misaddressed call that also
  "succeeded". It also treated an unknown asset path as found (the catalog answers
  an invalid id, not `None`) and passed the id as text. It now resolves the
  asset with the reflected three-argument call and checks it is valid, sets the
  property with the `AssetId` and checks the outcome, and reads the property back.
  Failures are `asset_not_found`, `component_type_not_found`,
  `component_not_on_entity`, `set_property_failed` or `assign_asset_failed`.
- **Editor failures use the error envelope too.** The failure envelope from the error
  contract below was returned by the server and by some editor tools, but other editor
  tools still printed plain-text failures (add/remove component, assign_asset, set_parent,
  console commands and CVARs, load_level, create_level, viewport camera, focus,
  capture_viewport, prefab instantiate/create). An agent checking `status == "error"` read
  those as successes. Every editor-script failure now goes through one `_o3de_fail(code,
  message)` helper that prints the same envelope, each with its own code
  (`component_type_not_found`, `set_parent_failed`, `load_level_failed`,
  `capture_not_written`, ...). `save_prefab`, which cannot save, now reports
  `status: "error"` (code `prefab_save_unavailable`) instead of `"unsupported"`, and
  capture_renderdoc_frame's failure carries a code.
- **Entity-id parameters accept a number, a digit string, or `[1234]`.** They were typed
  string-only, so passing back a gem 0.5.0 numeric id failed. Widening them naively to
  `int | str` would have broken the bracketed form, because the MCP layer JSON-decodes a
  string argument unless the parameter is annotated exactly `str`. They now keep a `str`
  annotation that also accepts a JSON number at full precision. This also fixes the
  optional `parent_id` of `create_entity` and `instantiate_prefab`, which never accepted
  the bracketed form.
- **One failure shape across every tool.** A tool that fails now always returns
  `{"status": "error", "code": "<slug>", "message": "<text>"}`, so a caller can
  detect any failure with a single `status == "error"` check and branch on the
  stable `code`. Previously some tools (several Track View, duplicate/transform,
  session and log tools) returned a bare `{"error": "<text>"}` with no `status`
  or `code`, while others already used the structured shape. The envelope is now
  defined once in `utils/errors.py` and shared by every tool module. Input that
  is rejected at the tool boundary is raised as a tool error rather than returned
  as the envelope; `wait_for_assets` keeps its progress result (`completed`,
  `elapsed`), since a timed-out wait is a result, not a failure.

### Compatibility

- **Entity IDs are tolerated as decimal strings.** AiCompanion gem 0.6.0 (API 0.4.0
  and up) emits every native 64-bit entity id as a decimal string instead
  of a JSON number, so a client with a 53-bit-float JSON parser cannot corrupt a u64
  id. o3de-mcp already carries ids through unchanged and accepts a number or a string
  on input; tests now pin that a full-precision u64 string round-trips through
  `create_entity`, `delete_entity`, `get_entity` and `set_transform` natively with no
  loss and no editor-Python fallback, and a live run against a gem built from
  main round-tripped a past-2^53 id exactly. AGENTS.md documents treating ids as opaque.

### Documentation

- A pre-release audit reconciled the docs with the code:
  - the architecture diagram gains the utils modules, the introspection to AgentServer
    edge and the anim graph native types;
  - the native-first fallback conditions are stated precisely, the gem versions of the
    native types are corrected, and the gem's error codes are listed;
  - `recipes.md` calls `GetAssetIdByPath` with its reflected three arguments and lists
    enabled gems with `list_project_gems`;
  - the examples and the agent skill show real `get_capabilities` and `list_projects`
    output, reflected bus calls only, and current tool counts;
  - the README no longer claims `save_prefab` saves;
  - `docs/releasing.md` makes the documentation audit a required release gate.

### Testing

- The azlmbr surface harness now checks that a tool's generated script calls each reflected function with the correct number of arguments, not just that the function exists. The reflection dump records each function's arity; a wrong-arity call now fails the surface test. This is the class of bug `create_level` shipped with (a six-argument engine function called with two) that the name-only check could not catch.

### Added

- **Per-asset readiness** (4 asset tools over the AiCompanion gem's native request
  types, gem 0.6.0+): `get_asset_status`, `get_asset_jobs` (with failed jobs' logs),
  `get_asset_processor_connection` and `wait_for_asset`. `wait_for_assets` only waits
  for an Asset Processor process to exit, which never happens with the GUI Asset
  Processor beside the editor; `wait_for_asset` waits for one asset. A source whose
  build failed answers `missing`, exactly like one the Asset Processor has not
  registered yet (observed live), so after a short grace period `wait_for_asset` asks
  the job list: a failed job ends the wait with `asset_build_failed` and its log.
- **Anim graph wiring** (6 more animation tools, 17 in all): `add_anim_graph_transition`,
  `set_anim_graph_transition`, `remove_anim_graph_transition` (state-machine transitions
  with parameter, time, play-time, motion, state, tag and vector conditions),
  `connect_anim_graph_ports` and `disconnect_anim_graph_ports` (blend-tree wiring), and
  `set_anim_graph_node` (rename, move, enable, and reflected fields such as a motion node's
  motion ids). A transition with no source must be requested with `wildcard=True`, so a
  missing source cannot silently become a from-any-state transition. Verified live against
  the gem's 0.6.0 development build (4b5298a), including a node nested under a blend tree.
- **Anim graph authoring** (9 more animation tools, 11 in all): `create_anim_graph`,
  `remove_anim_graph`, `load_anim_graph`, `save_anim_graph`, `add_anim_graph_node`,
  `remove_anim_graph_node`, `set_anim_graph_entry_state`, `add_anim_graph_parameter`
  and `remove_anim_graph_parameter`, over the gem's native authoring request types
  (gem 0.6.0+). Writes refuse asset- or runtime-owned graphs, so author on a
  graph from `create_anim_graph` or `load_anim_graph`; each write is one Animation
  Editor undo step, separate from the editor's main undo, and `save_anim_graph` (which
  must stay inside the project root) is not undoable. Verified live: build a graph with
  states, entry state and parameters, save it, reload it, and the gem's refusals.
- **Animation tools** (`tools/animation.py`, 2 tools): `list_anim_graphs` and
  `get_anim_graph`, EMotion FX anim graph reads over the AiCompanion gem's native
  request types. They need gem 0.6.0+ and the EMotionFX gem; an older gem
  answers `Unknown request type` (code `unknown_request_type` from gem 0.5.0). No editor-Python fallback (EMotion FX
  anim graphs are not usefully reflected to Python); they work in secure mode.
  `get_anim_graph` takes exactly one of `anim_graph_id` (32-bit number or digit
  string) or `file_name`. `_native_request` moved to module level in `editor.py`
  so tool modules other than the editor can call native request types.
- **Track View tools** (`tools/trackview.py`, 8 tools): `list_sequences`,
  `create_sequence`, `delete_sequence`, `get_sequence`, `set_sequence_time_range`,
  `add_sequence_node`, `play_sequence`, `stop_sequence`. Cinematic sequence authoring
  over the reflected `azlmbr.legacy.trackview` editor-Python API, no gem request type.
  Track and keyframe authoring are intentionally not exposed: the reflected API needs
  each node type's exact parameter-type name strings and the only key path is the
  interactive record workflow, neither reliable to drive. Verified live: full sequence
  lifecycle (create, describe, time range, Director and Event nodes, play/stop, delete).

## [0.5.0] - 2026-10-09

### Added

- **`get_entity`**, a native editor tool: one entity's name, transform, parent
  and component list from the AiCompanion gem's C++ `get_entity` request type
  (gem 0.4.0 or later), with no editor Python. Works in secure mode. Tool count
  is now 67 (41 editor tools).

### Changed

- **`create_entity`, `set_transform` and `delete_entity` try the gem's native
  request types first.** AiCompanion 0.5.0 serves all three in C++ with its
  own validation (entity names, the position bound, the scale range, the
  level's root entity), so the tools now send the native request, return the
  gem's JSON verbatim (`{"entity_id": ...}`, the updated entity, or
  `{"deleted": ...}`) and work in secure mode. A refusal from the gem is
  returned as an error, not retried through Python. Older gems and the legacy
  transport fall back to the existing editor-Python scripts and their text
  output, unchanged. `set_transform` keeps its quaternion and `[x, y, z]`
  scale parameters: the quaternion is converted to the XYZ Euler degrees the
  gem takes, while a non-uniform scale and a rotation at a gimbal pole (pitch
  within 0.02 degrees of plus or minus 90) always use the Python path, and an
  all-zero quaternion is rejected. `create_entity` checks the name with the
  gem's own rule before either path, so a bad name never reaches the Python
  fallback. The fallback triggers only on a reply that starts with
  `Unknown request type` or carries the `unknown_request_type` code, not on a
  refusal that merely echoes those words.
- **`get_bus_schema_live` tries the gem's native `get_bus_schema` first.** The
  C++ path reads the live BehaviorContext and includes each event's argument
  names and tooltips, which the Python bindings do not expose, and it works in
  secure mode. Older gems, the legacy transport or an unknown bus fall through
  to the editor-Python query and then to the stub files; the `source` field
  reports which answered (`native`, `live`, `stub_fallback`).
- The connection pool's `send_request()` and `_build_framed_request()` accept
  extra request fields (`params`) for request types that take arguments.

### Fixed

- **`create_level` never created a level.** Its editor script called
  `create_level_no_prompt(name, 0)`, but the engine reflects that function as
  `create_level_no_prompt(templateName, levelName, heightmapResolution,
  heightmapUnitSize, terrainExportTextureSize, useTerrain)` with all six
  arguments required (`Code/Editor/CryEditPy.cpp`, the same on `development`
  and the 26.05 and 26.10 stabilization branches). The bindings refused the
  two-argument call with a warning in the editor log and returned `None`, so
  the tool always reported that it could not create the level. The script now
  passes the full argument list with the values the engine's own Python tests
  use, and reads the result as an `ECreateLevelResult` code where `0` is
  success. The old `if result:` check would have been backwards even with the
  right arguments. A new optional `template` parameter selects the level
  template, defaulting to the editor's own `Prefabs/Default_Level.prefab`.

## [0.4.0] - 2026-09-08

### Changed

- **`get_capabilities` now detects the AiCompanion gem, not just an open socket.**
  When the editor is reachable it sends the AgentServer's native
  `get_api_version` request and reports `editor.ai_companion_gem` plus the
  gem's `protocol_version`, `gem_version` and `api_version` under
  `editor.agent_server`. A legacy RemoteConsole that answers the port but has
  no gem behind it is now reported as connected without the gem, with a hint,
  instead of looking identical to a full AgentServer.

- **Migrated to the `mcp` 2.x API.** `FastMCP` was renamed to `MCPServer` and
  moved to `mcp.server.mcpserver` in `mcp` 2.0, which broke every import. All
  seven call sites now use `from mcp.server import MCPServer`. The server
  version is passed via the new `version=` constructor argument instead of
  assigning to the private `_mcp_server.version` attribute.
- **Bounded the dependency ranges.** `mcp[cli]` is now `>=2.0,<3`, and the dev
  dependencies carry upper bounds. Previously every range was open-ended, so
  the `mcp` 2.0 release broke CI on `main` with no warning.

### Fixed

- **`instantiate_prefab` refused every gem-shipped prefab.** The segfault guard
  added below only looked for the `.prefab` file under `projectroot` and
  `engroot`, but `PrefabLoader::GetFullPath` resolves a relative path through
  the Asset Processor, so prefabs in a gem's own `Assets` scan folder (for
  example the AiCompanion gem's `Prefabs/Player_TwinStick.prefab`) are valid
  and were being reported as "not found". The guard now also accepts a path
  whose `.spawnable` product is in the asset catalog, which exists only when
  the Asset Processor has seen the source in some scan folder. Covered by
  stub-bus tests in both directions.
- **`build_project` crashed instead of reporting a rejected symlink.** The
  build directory was created with `mkdir(exist_ok=True)` before the symlink
  guard ran, and that raises `FileExistsError` when the path is a symlink whose
  target does not exist. The guard now runs first, so both broken and intact
  symlinks return the intended `symlink_rejected` error.
- **`instantiate_prefab` crashed the editor when the prefab did not exist.**
  `PrefabPublicRequestBus.InstantiatePrefab` segfaults on O3DE 26.10.0 when the
  template cannot be loaded: `PrefabPublicHandler::InstantiatePrefab` hands an
  empty DOM to `PrefabDomUtils::GetTemplateSourcePaths`, which dereferences it
  without a null check. The tool already wrapped the bus call in `try`/`except`,
  but a C++ segfault is not a Python exception, so the generated script now
  resolves the path against `azlmbr.paths.projectroot` and `engroot` and
  reports a normal "not found" failure instead of dispatching. Found by running
  the live suite against a real editor; every mocked test passed.
- **`save_prefab` was a silent no-op.** It called
  `PrefabPublicRequestBus.SavePrefabToFile`, an event that no O3DE version
  reflects; the call returned `None` and the tool printed
  `Saved prefab instance: <id>` regardless. Propagating live entity edits back
  to a `.prefab` is not reachable from the editor's Python API at all: the bus
  reflects no save event, and the only serialiser, `SaveTemplateToString`, is
  keyed by template id with nothing exposed to map an entity to one. The tool
  now returns a `prefab_save_unavailable` result carrying the owning prefab
  path and pointing at `create_prefab_from_entity`, instead of reporting a
  success that never happened.
- **Five editor tools called bus events that no O3DE version reflects, or the right
  event the wrong way.** Found by running every tool's generated script against the
  editor's own stub dump (see Testing). In a real editor an unreflected event returns
  `None` without raising, so each tool's `try`/`except` never fired and it reported
  success:
  - `set_parent` called `ToolsApplicationRequestBus.SetEntityParent` and printed
    "Set parent" with `result=None`; nothing was reparented. It now calls
    `EditorEntityAPIBus.SetParent` and reads the parent back before confirming.
  - `remove_component` called `EditorComponentAPIBus.RemoveComponentOfType` and, since
    `None` has no `IsSuccess`, took the branch that printed "Removed". It now looks the
    component up with `GetComponentOfType` and removes it with `RemoveComponents`,
    reporting the editor's boolean.
  - `duplicate_entity` called `ToolsApplicationRequestBus.CloneEntity` and reported a
    duplicate with id `None`. It now uses `PrefabPublicRequestBus.DuplicateEntitiesInInstance`.
  - `get_entity_components` tried `GetComponentsOfEntity` and `GetComponentName`,
    neither of which exists, so only a hard-coded list of 36 component names was ever
    checked. It now enumerates every type from `BuildComponentTypeNameListByEntityType`.
  - `focus_entity` called `EditorCameraRequestBus.SetViewFromEntityPerspective` with
    `bus.Event`, which consumed the entity id as the bus address and passed no argument.
    It is a broadcast.
- **`duplicate_entity` reported a duplicate that never happened, or crashed the editor.** It called `CloneEntity`, which is not reflected, so it returned a duplicate with id `None`. Rewritten to use `PrefabPublicRequestBus.DuplicateEntitiesInInstance`. That takes the editor's own `EntityId`, not one rebuilt from an int (which passes `IsValid()` but fails the hierarchy lookup), and its outcome must be checked with `IsSuccess()` before `GetValue()`: on a failed outcome `GetValue()` reads uninitialised memory and segfaults the editor. Verified live.
- **`create_entity` with no level open blocked the editor.** `CreateNewEntity` raises a
  modal "Entity Creation Error" dialog on the main thread, and until a human clicks OK
  every AgentServer request times out with "waiting for main thread dispatch". The tool
  now checks `GetCurrentLevelEntityId` first and returns a `no_level_open` error.
- **`create_prefab_from_entity` never wrote a file.** It called
  `CreatePrefabInMemory`, which builds an in-level container and writes nothing,
  while its docstring promised a prefab file. It now creates the template with
  `PrefabSystemScriptingBus.CreatePrefab`, serialises it with
  `PrefabLoaderScriptingBus.SaveTemplateToString`, writes it to the project root
  and reports success only if the file is on disk. The level is no longer
  modified as a side effect. Verified end to end against a live editor: entity
  to `.prefab` on disk to `instantiate_prefab` loading it back.

### Testing

- New `tests/test_editor_scripts.py` runs the Python that every editor tool sends to
  the editor against a stub `azlmbr` built from the editor's own reflection dump
  (`tests/data/azlmbr_surface.json`, extracted from `<project>/user/python_symbols` by
  `scripts/extract-azlmbr-surface.py`). Unknown buses, events, functions and classes
  fail the test, as does using `bus.Event` on a broadcast or the reverse. This is what
  found the five tools above; the mocked tests could not, because they echo their own
  expected string back.
- `tests/test_live_editor.py` gained tests for `set_parent`, `get_entity_components`,
  `add_component`/`remove_component`, `duplicate_entity` and `focus_entity`, none of
  which the live suite had covered.
- Prefab tool tests now execute the generated editor script against stub
  `azlmbr` modules whose buses reject any event the engine does not actually
  reflect (the list is taken from the editor's own generated stubs). The
  previous tests passed their own expected string in as the canned output, so
  they confirmed nothing about the editor and let `save_prefab` call a
  nonexistent bus event for months without failing.

- **Every registered tool is now exercised through MCP dispatch.** The eight
  CLI-backed project tools (`create_project`, `create_gem`, `register_gem`,
  `enable_gem`, `disable_gem`, `edit_project_properties`, `build_project`,
  `export_project`) were previously only covered via their helpers, because
  invoking them shells out to the O3DE CLI or CMake. They now have dispatch
  tests with the subprocess layer mocked, asserting on the arguments actually
  handed to the CLI. All 63 registered tools are now invoked at least once
  through `call_tool`. This covers dispatch and argument marshalling only: the
  editor tools still mock the remote console socket, so none of it exercises a
  running O3DE Editor.

### Documentation

- `docs/releasing.md`: the release checklist. The live editor suite is now a required
  gate before tagging, with `scripts/live-sandbox.sh up|test|down` to run it against an
  isolated editor (own X display, own AgentServer and AssetProcessor ports) so an editor
  already open on the machine is never touched.

- **Corrected the editor protocol description.** `CLAUDE.md` described only the
  legacy RemoteConsole `pyRunScript` fallback. The primary protocol is the
  AiCompanion gem's AgentServer (length-prefixed JSON), with RemoteConsole as an
  automatic fallback. `README.md` and `docs/architecture.md` were already correct.
- **Documented the full tool surface.** `README.md`, `AGENTS.md`, `CLAUDE.md` and
  `docs/architecture.md` described three tool categories and stale counts (16
  editor, 12 project). There are 63 tools in five categories: capabilities (1),
  editor (37), introspection (3), project (17), assets (5). `tools/assets.py` was
  missing entirely from the architecture diagram and module table.
- **Documented five missing environment variables.** `O3DE_PROJECT_PATH`,
  `O3DE_CAPTURE_WAIT`, `O3DE_EDITOR_TLS`, `O3DE_EDITOR_TLS_VERIFY` and
  `O3DE_EDITOR_TLS_CA` were read by the code but appeared in no documentation.
  The README now also notes that enabling TLS without `O3DE_EDITOR_TLS_VERIFY=1`
  encrypts the channel without authenticating the peer.
- **Added a tool-surface table to `AGENTS.md`**, listing each group, its size,
  whether it needs a running editor, and the less discoverable tools (persistent
  sessions, background builds, viewport capture, EBus discovery, log tailing).
- Corrected the example count (eight, not seven) and added `docs/architecture.md`
  to the `CLAUDE.md` documentation index.

### Added

- **`skills/o3de-headless-and-editor-automation/`, an installable Agent Skill
  for Windows and Linux.** `SKILL.md` plus reference notes and three scripts
  covering AssetProcessor-first launch order (and where the AP GUI actually
  reports idle: the project's `user/log/AP_GUI.log`, never stdout), level capture
  with the GameLauncher on the native GPU and ffmpeg (`capture_level.py`: x11grab
  plus Xvfb on Linux, gdigrab on Windows, waits for the launcher's own level-load
  marker before grabbing), in-renderer screenshots through Atom's
  `FrameCaptureRequestBus` from editor Python, editor automation through o3de-mcp
  and the AiCompanion gem, offline source-GUID computation for prefab and level
  JSON, and ScriptContext behavior tests. Documents the `InstantiatePrefab`
  segfault on a missing template, the kill-by-pattern self-match trap on both
  shells, per-OS crash-dump workflows, and the `mcp` 2.x requirement. The Linux
  path is run end to end on O3DE 26.10.0; the Windows path is written from the
  engine layout and awaits a run on Windows.
- **Native snapshot tools backed by the AiCompanion gem's C++.**
  `get_scene_snapshot`, `get_entity_tree` and `validate_scene` send the
  AgentServer's script-less request types instead of editor Python, so they
  are cheaper than `list_entities` plus per-entity queries and keep working
  when the gem's secure mode disables `execute_python`. On the legacy
  RemoteConsole transport they return an `agent_server_required` error rather
  than a fake result. The connection pool gained `send_request()` for these.
  Tool count is now 66 (40 editor tools).
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
- **Test deadlock**: `TestProtocolRoundTrip`'s fake-server round-trip tests tear
  down the test server with a bounded `wait_closed()`, so they no longer
  intermittently hang the suite on Python 3.12+ (an asyncio `wait_closed`
  deadlock waiting on a lingering connection-handler task).
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
