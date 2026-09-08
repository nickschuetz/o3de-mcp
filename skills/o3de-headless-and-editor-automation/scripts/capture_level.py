#!/usr/bin/env python3
# Copyright (c) Contributors to the Open 3D Engine Project.
# SPDX-License-Identifier: Apache-2.0 OR MIT
"""Render a level with the O3DE GameLauncher and capture a frame or a video.

Cross-platform (Linux and Windows) replacement for the old capture_level.sh:

  1. Start AssetProcessor for the project and wait until it reports idle. The AP
     GUI never prints "idle" on stdout; it appends "Asset Processor is currently
     idle" to <project>/user/log/AP_GUI.log, so that file is polled for a line
     written after this launch.
  2. Linux only: start Xvfb without a cursor when no usable display is wanted
     (default), so the capture works on a headless box. Windows always has a
     desktop session, so nothing is started there.
  3. Launch <Project>.GameLauncher on the native GPU, optionally loading a level
     with +LoadLevel, then wait until the launcher's own "Level load complete"
     lines in <project>/user/log/Game.log have gone quiet and the last one names
     the requested level. A project whose Registry/*.setreg carries an autoexec
     LoadLevel loads that level first (twice, in practice) before +LoadLevel
     loads yours, and a frame grabbed between loads is black. A fixed sleep is
     wrong in both directions: a cold shader cache has taken 40 s to the first
     load, a warm one 1 s.
  4. Capture with ffmpeg: x11grab on Linux, gdigrab on Windows. A .png output
     captures one frame, anything else records --duration seconds of video.

This is a TEMPLATE: the level-load mechanism varies per project (+LoadLevel is
the default here). Verify the output by opening it; never report a result you
did not view. Headless FPS is present-capped and is not a benchmark.

Usage:
  capture_level.py --project PATH [--engine PATH] [--build DIR] [options]

Required (or via env PROJECT_PATH):
  --project PATH     project root (contains project.json)

Optional (or via env ENGINE_PATH / BUILD_DIR / CONFIG):
  --engine PATH      engine root; default: resolved from ~/.o3de/o3de_manifest.json
                     by the project's "engine" name (first match wins)
  --build DIR        cmake build tree; default: <project>/build/linux or build/windows
  --config CFG       profile (default) | debug | release
  --launcher NAME    launcher binary name; default: <project_name>.GameLauncher
  --level NAME       level to load with +LoadLevel (default: project autoexec setreg)
  --out FILE         capture.png (default) for one frame, or a .mp4 for video
  --duration SEC     video length (default 10; ignored for .png)
  --res WxH          capture resolution (default 1920x1080)
  --rhi NAME         vulkan (Linux default) | dx12 (Windows default) | null
  --load-timeout SEC how long to wait for the level to load (default 300)
  --settle SEC       seconds the load log must stay quiet, and the frame wait after (default 5)
  --ap-timeout SEC   how long to wait for AP idle (default 600)
  --display N        Linux: Xvfb display number (default 99)
  --use-display      Linux: use the current $DISPLAY instead of starting Xvfb
  --keep             leave AP, Xvfb and the launcher running afterwards
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")
EXE = ".exe" if IS_WINDOWS else ""
OS_DIR = "Windows" if IS_WINDOWS else "Linux"
AP_IDLE_LINE = "Asset Processor is currently idle"
LEVEL_LOADED_LINE = "Level load complete"


def fail(msg: str) -> None:
    print(f"capture_level: {msg}", file=sys.stderr)
    sys.exit(1)


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def resolve_engine(project: Path) -> Path:
    """Pick the registered engine whose engine_name matches the project's "engine"."""
    manifest = Path.home() / ".o3de" / "o3de_manifest.json"
    if not manifest.is_file():
        fail(f"no --engine given and {manifest} does not exist")
    wanted = str(read_json(project / "project.json").get("engine", "o3de")).split("==")[0]
    matches: list[Path] = []
    for entry in read_json(manifest).get("engines", []):
        root = Path(entry["path"] if isinstance(entry, dict) else entry)
        engine_json = root / "engine.json"
        if engine_json.is_file() and read_json(engine_json).get("engine_name") == wanted:
            matches.append(root)
    if not matches:
        fail(f"no registered engine named {wanted!r}; pass --engine")
    if len(matches) > 1:
        print(f"   note: {len(matches)} engines are named {wanted!r}; using {matches[0]}")
    return matches[0]


class LogMark:
    """Where a log stood before a launch, so only lines written afterwards count.

    AP_GUI.log is appended to across runs (and rotated at 4 MB), while the
    GameLauncher recreates Game.log on every start. A recreated file is detected
    by its first line changing (O3DE stamps the launch time there); size alone is
    not enough, since two identical runs can produce byte-identical logs.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.head = b""
        self.lines = 0
        if path.is_file():
            with path.open("rb") as fh:
                for i, line in enumerate(fh):
                    if i == 0:
                        self.head = line
                    self.lines = i + 1

    def new_lines_with(self, needle: str) -> list[str]:
        """Lines written since the mark that contain `needle`, in order."""
        if not self.path.is_file():
            return []
        with self.path.open("rb") as fh:
            head = fh.readline()
        skip = 0 if head != self.head else self.lines
        with self.path.open("r", encoding="utf-8", errors="replace") as fh:
            return [line.rstrip() for i, line in enumerate(fh) if i >= skip and needle in line]

    def has_new_line_with(self, needle: str) -> bool:
        return bool(self.new_lines_with(needle))


def terminate(proc: subprocess.Popen | None, tree: bool = False) -> None:
    if proc is None or proc.poll() is not None:
        return
    if IS_WINDOWS and tree:
        # AssetProcessor keeps AssetBuilder workers alive; kill the whole tree.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--project", default=os.environ.get("PROJECT_PATH", ""))
    ap.add_argument("--engine", default=os.environ.get("ENGINE_PATH", ""))
    ap.add_argument("--build", default=os.environ.get("BUILD_DIR", ""))
    ap.add_argument("--config", default=os.environ.get("CONFIG", "profile"))
    ap.add_argument("--launcher", default="")
    ap.add_argument("--level", default="")
    ap.add_argument("--out", default="capture.png")
    ap.add_argument("--duration", type=float, default=10.0)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--rhi", default="")
    ap.add_argument("--load-timeout", type=float, default=300.0)
    ap.add_argument("--settle", type=float, default=5.0)
    ap.add_argument("--ap-timeout", type=float, default=600.0)
    ap.add_argument("--display", type=int, default=99)
    ap.add_argument("--use-display", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    args = ap.parse_args()
    if args.help:
        print(__doc__)
        return 0

    if not args.project:
        fail("missing --project (or PROJECT_PATH)")
    project = Path(args.project).resolve()
    if not (project / "project.json").is_file():
        fail(f"no project.json in {project}")
    engine = Path(args.engine).resolve() if args.engine else resolve_engine(project)
    build = Path(args.build).resolve() if args.build else project / "build" / OS_DIR.lower()
    launcher_name = args.launcher or f"{read_json(project / 'project.json')['project_name']}.GameLauncher"

    ap_bin = engine / "bin" / OS_DIR / args.config / "Default" / f"AssetProcessor{EXE}"
    game_bin = build / "bin" / args.config / f"{launcher_name}{EXE}"
    for label, path in (("AssetProcessor", ap_bin), ("GameLauncher", game_bin)):
        if not path.is_file():
            fail(f"{label} not found: {path}")
    if not shutil.which("ffmpeg"):
        fail("ffmpeg not on PATH")
    if not IS_WINDOWS and not args.use_display and not shutil.which("Xvfb"):
        fail("Xvfb not installed (or pass --use-display to capture the current display)")

    out = Path(args.out).resolve()
    single_frame = out.suffix.lower() == ".png"
    rhi = args.rhi or ("dx12" if IS_WINDOWS else "vulkan")
    env = dict(os.environ)
    procs: dict[str, subprocess.Popen] = {}
    logs = Path.cwd()

    try:
        # 1. AssetProcessor first, then wait for a fresh idle line in AP_GUI.log.
        ap_log = project / "user" / "log" / "AP_GUI.log"
        ap_mark = LogMark(ap_log)
        print(f"== AssetProcessor ({ap_bin}) ==")
        procs["ap"] = subprocess.Popen(
            [str(ap_bin), f"--project-path={project}"],
            stdout=(logs / "capture_ap.log").open("w"), stderr=subprocess.STDOUT, env=env,
        )
        deadline = time.monotonic() + args.ap_timeout
        idle = False
        while time.monotonic() < deadline:
            if ap_mark.has_new_line_with(AP_IDLE_LINE):
                idle = True
                break
            if procs["ap"].poll() is not None:
                fail(f"AssetProcessor exited early; see {logs / 'capture_ap.log'}")
            time.sleep(1)
        print("   AP idle" if idle else f"   AP idle not seen within {args.ap_timeout:.0f}s; continuing (check {ap_log})")

        # 2. Display. Linux gets a cursor-less Xvfb unless told to use the real one.
        if not IS_WINDOWS and not args.use_display:
            display = f":{args.display}"
            print(f"== Xvfb {display} ({args.res}) ==")
            procs["xvfb"] = subprocess.Popen(
                ["Xvfb", display, "-screen", "0", f"{args.res}x24", "-nocursor"],
                stdout=(logs / "capture_xvfb.log").open("w"), stderr=subprocess.STDOUT,
            )
            env["DISPLAY"] = display
            time.sleep(2)

        # 3. GameLauncher on the native GPU, then wait for its level-load line.
        game_log = project / "user" / "log" / "Game.log"
        game_mark = LogMark(game_log)
        cmd = [str(game_bin), f"--rhi={rhi}", "--rhi-device-validation=disable", f"--project-path={project}"]
        if args.level:
            cmd += ["+LoadLevel", args.level]
        print(f"== GameLauncher: {' '.join(cmd)} ==")
        procs["game"] = subprocess.Popen(
            cmd, stdout=(logs / "capture_launcher.log").open("w"), stderr=subprocess.STDOUT, env=env, cwd=str(project),
        )
        deadline = time.monotonic() + args.load_timeout
        started = time.monotonic()
        loaded = False
        seen = 0
        quiet_since = None
        while time.monotonic() < deadline:
            loads = game_mark.new_lines_with(LEVEL_LOADED_LINE)
            if loads and len(loads) != seen:
                seen, quiet_since = len(loads), time.monotonic()
            # Done when the last load names the requested level (any level if none
            # was requested) and no further load has started for --settle seconds.
            if loads and args.level.lower() in loads[-1].lower() and quiet_since is not None:
                if time.monotonic() - quiet_since >= args.settle:
                    loaded = True
                    break
            if procs["game"].poll() is not None:
                fail(f"GameLauncher exited before loading a level; see {logs / 'capture_launcher.log'}")
            time.sleep(1)
        elapsed = time.monotonic() - started
        if loaded:
            print(f"   level loaded after {elapsed:.0f}s, {seen} load(s) in {game_log}")
        else:
            print(f"   no settled '{LEVEL_LOADED_LINE}' for {args.level or 'any level'} within {args.load_timeout:.0f}s; capturing anyway (expect black)")
        time.sleep(args.settle)

        # 4. Capture.
        if IS_WINDOWS:
            grab = ["-f", "gdigrab", "-draw_mouse", "0", "-framerate", "30", "-i", "desktop"]
        else:
            grab = ["-f", "x11grab", "-draw_mouse", "0", "-video_size", args.res, "-i", env["DISPLAY"]]
        length = ["-frames:v", "1"] if single_frame else ["-t", str(args.duration)]
        print(f"== ffmpeg -> {out} ==")
        subprocess.run(["ffmpeg", "-loglevel", "error", *grab, *length, "-y", str(out)], check=True, env=env)
        print(f"== done: {out} ==")
        print("Now OPEN the output and confirm what actually rendered before reporting a result.")
        return 0
    finally:
        if not args.keep:
            terminate(procs.get("game"))
            terminate(procs.get("ap"), tree=True)
            terminate(procs.get("xvfb"))


if __name__ == "__main__":
    sys.exit(main())
