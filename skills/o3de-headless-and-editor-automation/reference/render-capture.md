# Part A — Visual verification (with or without a monitor)

Goal: render a level to a screenshot or video and look at it. Two channels:

- **GameLauncher + ffmpeg** (any OS): the most reliable because it pulls in no
  AzToolsFramework/Qt. Needs a display to present to: the desktop on Windows,
  Xvfb on a monitor-less Linux box.
- **In-renderer screenshot from editor Python** (any OS, needs the editor): Atom's
  `FrameCaptureRequestBus` writes a PNG straight from the render pipeline, so no
  screen grab, no cursor, no display-size math. Reach it through o3de-mcp's
  `run_editor_python` or `Editor --runpython`.

The bundled `scripts/capture_level.py` automates the launcher channel end to end
on Linux and Windows. Read it before running so you understand what it launches:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/capture_level.py --help
```

## Recipe 1 — GameLauncher + ffmpeg

1. Start AssetProcessor and wait for idle. AP does not print "idle" on stdout; it
   appends `Job processing completed. Asset Processor is currently idle` to
   `$PROJECT_PATH/user/log/AP_GUI.log`. That file persists across runs, so note
   its line count before launching and only accept a line written after. Or run
   `AssetProcessorBatch` first (it exits when processing is done), then start
   the GUI AP, which will have nothing left to do.

   ```
   # Linux
   $ENGINE_PATH/bin/Linux/$CONFIG/Default/AssetProcessor --project-path=$PROJECT_PATH &
   # Windows (PowerShell)
   Start-Process "$ENGINE_PATH\bin\Windows\$CONFIG\Default\AssetProcessor.exe" "--project-path=$PROJECT_PATH"
   ```

2. Linux without a monitor: start a virtual X display WITHOUT a cursor (the cursor
   bakes into captures). Windows: skip this; the desktop session is the display.
   A Windows box reached over RDP still has a desktop, but presents through a
   software path (see the FPS rule).

   ```
   Xvfb :99 -screen 0 1920x1080x24 -nocursor &
   export DISPLAY=:99
   ```

3. Launch the GameLauncher on the native GPU, loading the target level (set the
   level via the project bootstrap setreg `LoadLevel`, or a `+LoadLevel <name>`
   console command if supported):

   ```
   # Linux
   $BUILD_DIR/bin/$CONFIG/MyProject.GameLauncher --rhi=vulkan --rhi-device-validation=disable +LoadLevel MyLevel
   # Windows
   $BUILD_DIR\bin\$CONFIG\MyProject.GameLauncher.exe --rhi=dx12 --rhi-device-validation=disable +LoadLevel MyLevel
   ```

   Then wait for the launcher's own readiness lines before grabbing. It writes
   `(LevelSystem) - Level load complete: '<level>.spawnable'` to
   `$PROJECT_PATH/user/log/Game.log`, a file it recreates on every start (the
   first line carries the launch time, so compare that, not the size, to know it
   is the new file). Wait until the last such line names your level and no new
   one has appeared for a few seconds (see the multiple-load trap below). A
   cold shader cache has taken 40 s to reach the first line; a warm one about
   1 s. A fixed sleep guesses wrong in one direction or the other and hands you
   a black frame. `capture_level.py` does all of this.

4. Capture with ffmpeg, suppressing the pointer:

   ```
   # Linux (x11grab)
   ffmpeg -f x11grab -draw_mouse 0 -video_size 1920x1080 -i :99 -t 10 -y out.mp4
   ffmpeg -f x11grab -draw_mouse 0 -video_size 1920x1080 -i :99 -frames:v 1 out.png
   # Windows (gdigrab; "desktop" or title=<window title>)
   ffmpeg -f gdigrab -draw_mouse 0 -framerate 30 -i desktop -t 10 -y out.mp4
   ffmpeg -f gdigrab -draw_mouse 0 -i title=MyProject.GameLauncher -frames:v 1 out.png
   ```

5. View the result (open the PNG / inspect frames). Only now describe what
   rendered.

## Recipe 2 — In-renderer screenshot from the editor (any OS)

With the editor running (AP first, then `Editor --project-path=...`), send this
through o3de-mcp `run_editor_python` (or `Editor --runpython shot.py`):

```python
import azlmbr.bus as bus
import azlmbr.atom as atom
out = r'/abs/path/shot.png'          # Windows: r'C:\path\shot.png'
result = atom.FrameCaptureRequestBus(bus.Broadcast, 'CaptureScreenshot', out)
print('capture id', result.GetValue() if result.IsSuccess() else result.GetError())
```

The write is asynchronous: the file appears a frame or two later, so poll for it
before reading. This captures the editor's active viewport; frame the shot first
(o3de-mcp `focus_entity` / `set_viewport_camera`), and set `ed_keepEditorActive 1`
so frames advance while the window is unfocused. o3de-mcp's `capture_viewport`
tool is the Qt-widget-grab alternative (`QWidget.grab()` on the viewport), which
also needs no external tool.

## Known traps

- A level with NO active camera renders BLACK. Ensure a camera entity exists and
  is the active view before capturing a new scene.
- `Xvfb -nocursor` is required on Linux; `ffmpeg -draw_mouse 0` alone does not
  remove the Xvfb framebuffer cursor. On Windows `-draw_mouse 0` is enough.
- Do not modify an existing sample/demo level to stage a shot for a different
  feature. Give each feature its own throwaway level.
- Expect more than one level load per launch. A project `Registry/*.setreg`
  with `/O3DE/Autoexec/ConsoleCommands/LoadLevel` runs that command twice on
  26.10.0 (measured: two `Level load complete` lines with no other input), and a
  `+LoadLevel` on the command line adds a third, last. A frame grabbed between
  loads is black or a bare clear colour with the debug overlay. Wait for the
  load log to settle on the level you asked for (the bundled script does),
  or remove the autoexec entry from the project and pass the level on the
  command line so it loads once. Overriding the key with `--regset` does not
  help: the file's value still runs last.
- Headless/virtual-display FPS is present-capped (~48); never report it as a
  benchmark. To prove rendering performance (e.g. draw-call batching), add an
  `AZ_Printf` counter in the feature processor and read it from the game log,
  not the frame rate.
- On Windows, AssetProcessor leaves `AssetBuilder.exe` workers behind when killed;
  end it with `taskkill /T` (the bundled script does).
