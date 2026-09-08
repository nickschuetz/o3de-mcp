# Tooling and engine availability

## Automation helpers

- **o3de-mcp** — MCP server exposing O3DE editor automation to an agent loop
  (66 tools: entities, components, prefabs, levels, viewport, console, sessions,
  native scene snapshot, project/build, AP and logs).
  https://github.com/nickschuetz/o3de-mcp
  Requires the `mcp` **2.x** Python SDK (`mcp[cli]>=2,<3`). With a 1.x `mcp` in
  the same interpreter the server dies at import (`cannot import name
  'MCPServer' from 'mcp.server'`) and the MCP client only reports "Connection
  closed". Check with `python3 -m pip show mcp`; `pip install --user --upgrade
  "mcp[cli]>=2,<3"` fixes it.
- **AiCompanion gem** (gem name `AiCompanion`) — the in-editor gem that hosts the
  AgentServer (length-prefixed JSON on TCP 4600) the MCP talks to, plus the
  `ai_companion` Python API and example content. Enable it together with
  **EditorPythonBindings** (it is a requirement, not bundled).
  https://github.com/nickschuetz/o3de-ai-companion-gem

## Engine installs by OS

Every install registers in `~/.o3de/o3de_manifest.json` (`%USERPROFILE%\.o3de`
on Windows) with an `engine_name`, usually `o3de`, so several versions can coexist
under one name. Binaries live under `<engine>/bin/<Linux|Windows>/<config>/Default/`
(`Editor`, `AssetProcessor`, `AssetProcessorBatch`, `.exe` on Windows).

- **Windows**: the O3DE installer from o3de.org, or a source build with Visual
  Studio 2022 and CMake; o3de-mcp's `build_project` detects the installed Visual
  Studio. Nothing here needs WSL; the editor, launcher and ffmpeg all run natively.
- **Linux (Fedora/CentOS)**: the COPR RPMs below, or a source build.

The Editor accepts `--rhi=vulkan --rhi-device-validation=disable` on both. On
Linux prefer a virtual display (Xvfb) over `:0` so it does not land on the user's
desktop; on Windows it will open on the desktop, which is fine.

## Engine RPMs (Fedora / CentOS) via COPR

Instead of building the engine from source you can install it from COPR, packaged
by **o3de-rpm**: https://github.com/nickschuetz/o3de-rpm . It populates these
`hellaenergy/*` COPR projects:

- **`hellaenergy/o3de`** — stable channel (upstream tagged releases). Default for a
  supportable install: `dnf copr enable hellaenergy/o3de`.
- **`hellaenergy/o3de-testing`** — pre-promotion soak for stable (~48h,
  updates-testing semantics). Enable ONE of `o3de` or `o3de-testing`, not both
  (dnf installs the higher NVR, defeating the point of stable).
- **`hellaenergy/o3de-stabilization`** — builds from upstream `stabilization/<rel>`
  during the ~4-week pre-release window (release-candidate quality); dormant
  between cycles.
- **`hellaenergy/o3de-development`** — bleeding-edge `development` branch (refreshed
  weekly); for engine contributors.
- **`hellaenergy/o3de-experimental`** — packagers' in-flight spec work; not for
  end-user testing.
- **`hellaenergy/o3de-dependencies`** — Fedora-clean 3rdParty SRPMs (custom Qt
  5.15, PhysX, AWSNativeSDK, azslc, ...); auto-enabled as a runtime dep of the
  engine projects.
- **`hellaenergy/o3de-testing-debug`** and **`hellaenergy/o3de-development-debug`**
  — debug-config siblings of the matching channel. Install the `o3de<rel>-debug`
  subpackage (`o3de2610-debug` for 26.10, `o3de2605-debug` for 26.05) for a real `-O0` + full-symbols build so a crash yields a usable stack
  trace instead of a profile build silently closing. Enable alongside the namesake
  channel (refreshed in lockstep at the same NVR).

## Crash work

When you need a real stack trace (records + memory guards, full symbols), use a
debug-config engine rather than a profile build that silently closes.

- **Linux**: enable the matching `-debug` COPR and `dnf install o3de<rel>-debug`
  (e.g. `o3de2610-debug`) rather than rebuilding the engine from source. Capture
  the FULL contiguous backtrace with `coredumpctl gdb <pid>` (use `thread apply
  all bt` then select the faulting thread; gdb may auto-select a waiting worker
  thread, not the crashing one).
- **Windows**: build or install the `debug` configuration (the installer ships
  `profile` only), enable local crash dumps
  (`HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps`, or run
  under the Visual Studio debugger), then open the `.dmp` in WinDbg or Visual
  Studio with the matching `.pdb` files and use `!analyze -v` / `~*k` for all
  threads before picking the faulting one.

Report all frames #0..#N including the signal handler and main, never a
cherry-picked subset.
