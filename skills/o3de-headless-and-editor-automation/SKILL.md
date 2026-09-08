---
name: O3DE headless verify + editor automation
description: >-
  Verify O3DE rendering and automate the O3DE editor on Windows or Linux. Use
  when working on any O3DE project or gem and you need to: capture a rendered
  frame or video of a level (GameLauncher on the native GPU + ffmpeg, with Xvfb
  for a monitor-less Linux box); drive the editor programmatically
  (entity/component/asset wiring via editor Python or the o3de-mcp server);
  author asset references in prefab/level JSON offline by computing source
  GUIDs; or prove an engine/gem change with a ScriptContext unit test. Encodes
  the traps that waste hours.
argument-hint: "[project_path] [engine_path] [build_dir] [config]"
---

# O3DE headless verification + editor automation

This skill packages a repeatable process for O3DE work: rendering verification
(with or without a monitor), programmatic editor automation, offline asset wiring,
and pixel-free C++ behavior proofs. It applies to Windows and Linux; the editor
Python, o3de-mcp, GUID and ScriptContext parts are identical on both, and the
capture and process-handling parts carry a per-OS note where they differ. The
Linux path has been run end to end on O3DE 26.10.0 (also 26.05.0); the Windows
path is written from the engine's layout and needs a run on a Windows machine.

Several engines can be registered under the same `engine_name` (`o3de`), and a
project's `project.json` `"engine": "o3de"` does not say which one it built
against. Check the build tree before trusting a result (`strings` on a built
`.so`, or the `.pdb`/`.dll` properties on Windows, show the engine include path). Read the operating rules first, then jump to the relevant part.

## Parameters

Resolve these once per session (from `$ARGUMENTS` if provided, else detect/ask):

```
PROJECT_PATH   = /abs/path/to/MyProject     # contains project.json
ENGINE_PATH    = engine/SDK root            # Linux /opt/O3DE/<ver>, Windows C:\O3DE\<ver>
BUILD_DIR      = $PROJECT_PATH/build/linux   # Windows: build\windows
CONFIG         = profile                     # profile | debug | release
```

Where the binaries live, by OS:

| Binary | Linux | Windows |
|--------|-------|---------|
| AssetProcessor (GUI) | `$ENGINE_PATH/bin/Linux/$CONFIG/Default/AssetProcessor` | `$ENGINE_PATH\bin\Windows\$CONFIG\Default\AssetProcessor.exe` |
| AssetProcessorBatch | same folder | same folder, `.exe` |
| Editor | same folder, `Editor` | same folder, `Editor.exe` |
| GameLauncher | `$BUILD_DIR/bin/$CONFIG/<Project>.GameLauncher` | `$BUILD_DIR\bin\$CONFIG\<Project>.GameLauncher.exe` |
| AP log | `$PROJECT_PATH/user/log/AP_GUI.log` | `$PROJECT_PATH\user\log\AP_GUI.log` |

`o3de.sh` / `o3de.bat` under `$ENGINE_PATH/scripts/` is the CLI on each OS; the
registered engines are in `~/.o3de/o3de_manifest.json` on both (`%USERPROFILE%`
on Windows).

## Operating rules (non-negotiable)

- **Never claim a visual result you did not capture and view.** "It should render
  X" is not verification. Capture a frame/video or read instrumented output, then
  state what you actually saw.
- **Headless FPS is not a performance benchmark.** Under Xvfb (or an RDP/virtual
  display on Windows) the swapchain presents into a software framebuffer, so FPS
  is present-capped (~48) regardless of scene or GPU. Prove batching/perf with
  instrumented counts (draw calls, batch counts via `AZ_Printf` to the log),
  never with FPS.
- **Use the real GPU.** Linux: Vulkan against the native driver (`--rhi=vulkan`),
  not lavapipe. Windows: the default DX12 (`--rhi=dx12`) or `--rhi=vulkan`, not
  the WARP software adapter. `--rhi=null` is only for logic that needs no pixels.
- **AssetProcessor (AP) must be running BEFORE the editor or GameLauncher**, or you
  get "Negotiation Failed" / "no platforms" and nothing renders. Start AP, wait
  until it reports idle, then launch. The AP GUI never prints "idle" to stdout;
  it appends `Job processing completed. Asset Processor is currently idle` to
  `$PROJECT_PATH/user/log/AP_GUI.log`. Poll that file for a line newer than your
  launch (the file persists across runs), or run `AssetProcessorBatch` first,
  which exits when done, and start the GUI AP afterwards.
- **Do not capture on a timer; wait for the launcher's level-load lines to
  settle.** The GameLauncher writes `Level load complete: '<level>.spawnable'`
  to `$PROJECT_PATH/user/log/Game.log` (recreated each run; its first line holds
  the launch time), and a project autoexec `LoadLevel` fires twice before a
  `+LoadLevel` fires once more. Wait until the last line names your level and
  the log has been quiet for a few seconds. Cold shader cache: ~40 s to the
  first line. Warm: ~1 s. A sleep picked for one case gives a black frame in
  the other.
- **Killing by command-line pattern can kill your own shell.** `pkill -f` /
  `pgrep -f` match the shell that runs them (the pattern is in its argv); bracket
  the first character: `pkill -f "Default/[E]ditor"`, `pkill -f "[X]vfb :99"`.
  On Windows use `taskkill /IM Editor.exe /F` (by image name) and `/T` for
  AssetProcessor so its AssetBuilder workers go with it; PowerShell
  `Get-Process | Where-Object CommandLine -match` has the same self-match hazard.
- **`PrefabPublicRequestBus.InstantiatePrefab` segfaults the editor on a missing
  prefab** (26.10.0, null DOM in `PrefabDomUtils::GetTemplateSourcePaths`). Not a
  Python exception; check the path exists before the call (see editor-automation).
- **Build and test strictly sequentially.** Parallel builds racing the same `.so`
  / `.dll` give stale-library results you will misread.
- **Markdown/stack-trace discipline:** blank line before and after every code
  fence; when pasting a stack trace, paste the FULL contiguous frames (#0..#N,
  including the signal handler and main), never a cherry-picked subset.

## How to use this skill

Each part lives in a reference file; read the one you need (they are not all
loaded up front). Bundled scripts live under `scripts/` and run via
`${CLAUDE_SKILL_DIR}`.

- **Visual verification** (GameLauncher + ffmpeg, Xvfb when there is no monitor,
  or an in-renderer screenshot from editor Python) →
  [reference/render-capture.md](reference/render-capture.md).
  Bundled: `scripts/capture_level.py` (AP-first with a real idle check, Xvfb
  -nocursor on Linux, native GPU, ffmpeg x11grab/gdigrab). Run it:

  ```
  python3 ${CLAUDE_SKILL_DIR}/scripts/capture_level.py --help
  ```

- **Editor automation** (entity/component/asset wiring, scene authoring, the
  persistence traps) → [reference/editor-automation.md](reference/editor-automation.md).

- **Offline asset-GUID wiring** (write prefab/level JSON refs with no editor) →
  [reference/asset-guid-wiring.md](reference/asset-guid-wiring.md).
  Bundled: `scripts/compute_asset_guid.py` (faithful `Uuid::CreateName` port).
  Run it (and verify once against an editor-generated GUID):

  ```
  python3 ${CLAUDE_SKILL_DIR}/scripts/compute_asset_guid.py "diorama/textures/spark.png"
  python3 ${CLAUDE_SKILL_DIR}/scripts/compute_asset_guid.py --selftest
  ```

- **C++ behavior proof without pixels** (ScriptContext unit test + the mandatory
  revert-cycle) → [reference/behavior-tests.md](reference/behavior-tests.md).
  Bundled: `scripts/scriptcontext_test_template.cpp`.

- **Tooling + engine availability** (o3de-mcp, AiCompanion gem, installing the
  engine per OS, getting a real crash stack on each) →
  [reference/tooling-and-copr.md](reference/tooling-and-copr.md).

## Quick decision guide

- Need to see what a scene looks like → render-capture (works with or without a
  monitor).
- Need to build/configure a scene or wire component refs → editor-automation
  (live) or asset-guid-wiring (offline JSON, no editor).
- Changed engine/gem reflection or logic → behavior-tests (ScriptContext +
  revert-cycle), not a screenshot.
- Engine crashes / need a real stack trace → a debug-config engine
  (tooling-and-copr), then the full backtrace with `coredumpctl gdb` on Linux or
  WinDbg / Visual Studio on the `.dmp` on Windows.
