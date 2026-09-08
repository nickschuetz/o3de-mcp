# Part B — Editor automation (programmatic scene authoring + verification)

Goal: create/configure entities, wire component asset/property refs, and verify,
without hand-clicking. Two channels.

## Channel 1 — Editor Python

Run a script in the editor's Python (`Editor --runpython script.py`, or via the
o3de-mcp `run_editor_python` tool). Everything in this file is the same on Windows
and Linux: `azlmbr` is the editor's embedded Python, and o3de-mcp talks to the
AiCompanion AgentServer over localhost TCP on both. Only the paths you pass
differ (use raw strings for Windows paths). Useful `azlmbr` calls for wiring components
(the gap that plain build scripts cannot do):

- `azlmbr.editor.EditorComponentAPIBus` — `FindComponentTypeIdsByEntityType`,
  `AddComponentsOfType`, `BuildComponentPropertyList`, `GetComponentProperty`,
  `SetComponentProperty`.
- `azlmbr.asset.AssetCatalogRequestBus` `GetAssetIdByPath` — resolve a product
  path to an `AssetId` before assigning it to a component field.
- Set the Lua Script asset, Tags, transform, and spawnable refs this way.

## Channel 2 — o3de-mcp + AiCompanion gem

- o3de-mcp (https://github.com/nickschuetz/o3de-mcp) exposes 66 tools: entity and
  component CRUD, transforms, prefabs, levels, viewport/camera, console/CVARs,
  game mode, `run_editor_python`, persistent sessions (`begin_session` /
  `exec_in_session` / `end_session`), project/build tools, AP and log tools.
- AiCompanion gem (https://github.com/nickschuetz/o3de-ai-companion-gem, gem name
  `AiCompanion`) hosts the AgentServer on port 4600 that o3de-mcp talks to, plus
  the `ai_companion` Python API (builders, templates, snapshot, validation).
  Enable it together with EditorPythonBindings; the gem does not bundle EPB.
- Call `get_capabilities` first. `editor.ai_companion_gem: true` with
  `editor.agent_server` versions means the gem answered `get_api_version`; a bare
  "connected" with `ai_companion_gem: false` is a legacy RemoteConsole with no gem,
  so `import ai_companion` will fail there.
- `get_scene_snapshot`, `get_entity_tree`, `validate_scene` return the gem's C++
  output without editor Python; cheaper than `list_entities` plus per-entity calls
  and they still work when the gem's secure mode disables `execute_python`.
- For multi-step authoring, open one session and `exec_in_session` each step;
  the editor's main thread drains between requests (this avoids the SetName race
  the single-script form hits), and imports persist across steps.
- The AgentServer answers `ping` within seconds of the editor window appearing,
  before AP has finished; do not treat a ping as "assets ready".
- See [tooling-and-copr.md](tooling-and-copr.md) for both.

## Editor launch + frame traps

- Start AP FIRST, then the editor (same "Negotiation Failed" rule as capture).
  Wait for the idle line in `<project>/user/log/AP_GUI.log`, not for AP stdout.
- The editor needs a display: the desktop on Windows, Xvfb on a monitor-less Linux
  box (`Xvfb :99 -screen 0 1600x900x24 -nocursor`, then `DISPLAY=:99 Editor ...`).
  `--rhi=vulkan --rhi-device-validation=disable` works on both OSes.
- The editor throttles frames when its window is not focused. Set CVar
  `ed_keepEditorActive 1` (console, or `run_console` over the remote console) so
  frames advance while the window is unfocused/headless; otherwise automation
  appears to hang.
- A phantom engine registration in `~/.o3de/o3de_manifest.json` (e.g. a pip/venv
  `o3de` python package path listed under `engines` with the same name+version as
  the real SDK) makes AP pick the wrong root and crash-loop with "no platforms
  enabled". Remove the venv entry from `engines`.

## Persistence traps (these cost the most time)

- Runtime `TransformBus.SetLocalRotation` / any `Set*` on a loaded prefab does NOT
  persist to the saved level. Level save serializes the prefab template DOM; only
  undo-batched editor edits (Inspector ChangeNotify) or entity creation propagate
  into it. To change a saved scene reliably: **patch the prefab/level JSON
  directly, then reopen the level.** Driving the live editor to "save" runtime
  changes silently drops them.
- Programmatic assignment of a Lua Script asset to a Script component can segfault
  in some 26.05 editors (fixed upstream as o3de/o3de#19800, not in 26.05.0). If you
  hit it: assign the Lua script by hand in the Inspector, OR wire it via prefab
  JSON and run only in the GameLauncher (the runtime ScriptComponent does not
  enumerate properties, so it does not trip the crash). Do not reopen that level in
  the editor afterward.
- Creating an entity with no level open crashes older 26.05 editors (fixed as
  o3de/o3de#19797). Always confirm a level is open before creating entities.
- `PrefabPublicRequestBus.InstantiatePrefab` with a prefab that cannot be loaded
  segfaults the editor (26.10.0: `PrefabPublicHandler::InstantiatePrefab` hands an
  empty DOM to `PrefabDomUtils::GetTemplateSourcePaths`). A C++ crash is not a
  Python exception, so `try/except` does not help; prove the file exists BEFORE
  the call. Relative prefab paths resolve through the Asset Processor
  (`PrefabLoader::GetFullPath`), so a prefab in any scan folder is valid, including
  a gem's `Assets` folder outside the project root. `GetSourceInfoBySourcePath` is
  not reflected to Python; the reflected proof is the catalog:
  `AssetCatalogRequestBus(bus.Broadcast, 'GetAssetIdByPath', 'Prefabs/X.spawnable',
  math.Uuid(), False).is_valid()`, plus an `os.path.isfile` check under
  `azlmbr.paths.projectroot` / `engroot`. o3de-mcp's `instantiate_prefab` and the
  AiCompanion gem's `spawn_prefab` both carry this guard; use them rather than a
  raw bus call.
- `PrefabPublicRequestBus.SavePrefabToFile` does not exist in any O3DE version and
  `CreatePrefabInMemory` writes nothing to disk. To get a prefab file out of the
  editor: `PrefabSystemScriptingBus.CreatePrefab([ids], path)` for a template id,
  then `PrefabLoaderScriptingBus.SaveTemplateToString(id)` and write the JSON
  yourself (o3de-mcp `create_prefab_from_entity` does exactly this).

## When to skip the editor entirely

If you only need to write component asset/property references into a prefab or
level, do it offline by computing the source GUID and editing the JSON — no editor
launch, no AP races. See [asset-guid-wiring.md](asset-guid-wiring.md).
