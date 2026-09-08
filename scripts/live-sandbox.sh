#!/usr/bin/env bash
# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT
#
# Bring up an isolated O3DE Editor for tests/test_live_editor.py and tear it down again.
#
# The editor runs on its own X display and its own ports, so it never collides with an
# editor you already have open (which normally holds 4600 and 45643). The AiCompanion gem
# reads O3DE_EDITOR_PORT for its AgentServer bind port, so the same variable points both
# the editor and o3de-mcp at the sandbox.
#
#   scripts/live-sandbox.sh up      start Xvfb, AssetProcessor and the Editor, load a level
#   scripts/live-sandbox.sh test    run the live suite against the sandbox
#   scripts/live-sandbox.sh down    stop everything the script started
#
# Configure with environment variables (defaults shown):
#   O3DE_SANDBOX_PROJECT   path to a project with the AiCompanion gem enabled and built
#   O3DE_SANDBOX_ENGINE    engine root                     (/opt/O3DE/26.10.0)
#   O3DE_SANDBOX_LEVEL     level to open after start       (DefaultLevel)
#   O3DE_SANDBOX_DISPLAY   X display for Xvfb              (:99)
#   O3DE_SANDBOX_PORT      AgentServer port                (4610)
#   O3DE_SANDBOX_AP_PORT   AssetProcessor port             (45644)
#   O3DE_SANDBOX_CONFIG    engine build config             (profile)
set -euo pipefail

PROJECT="${O3DE_SANDBOX_PROJECT:?set O3DE_SANDBOX_PROJECT to a project with the AiCompanion gem built}"
ENGINE="${O3DE_SANDBOX_ENGINE:-/opt/O3DE/26.10.0}"
LEVEL="${O3DE_SANDBOX_LEVEL:-DefaultLevel}"
DISPLAY_NUM="${O3DE_SANDBOX_DISPLAY:-:99}"
PORT="${O3DE_SANDBOX_PORT:-4610}"
AP_PORT="${O3DE_SANDBOX_AP_PORT:-45644}"
CONFIG="${O3DE_SANDBOX_CONFIG:-profile}"
BIN="$ENGINE/bin/Linux/$CONFIG/Default"
STATE="${XDG_RUNTIME_DIR:-/tmp}/o3de-live-sandbox"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$STATE"

wait_for_port() {
    local port=$1 tries=${2:-60}
    for ((i = 0; i < tries; i++)); do
        ss -ltn 2>/dev/null | grep -q ":$port " && return 0
        sleep 3
    done
    echo "port $port never opened" >&2
    return 1
}

wait_for_ap_idle() {
    local log=$1 before=$2 tries=${3:-600} now
    for ((i = 0; i < tries; i++)); do
        if [[ -f "$log" ]]; then
            now="$(wc -l <"$log")"
            (( now < before )) && before=0   # rotated: everything in it is new
            if tail -n +"$((before + 1))" "$log" | grep -q "Asset Processor is currently idle"; then
                echo "AssetProcessor idle after ${i}s"
                return 0
            fi
        fi
        sleep 1
    done
    echo "AssetProcessor did not report idle within ${tries}s (see $log); continuing" >&2
    return 0
}

case "${1:-}" in
up)
    echo "Xvfb on $DISPLAY_NUM"
    Xvfb "$DISPLAY_NUM" -screen 0 1920x1080x24 -nocursor >"$STATE/xvfb.log" 2>&1 &
    echo $! >"$STATE/xvfb.pid"

    echo "AssetProcessor for $PROJECT on port $AP_PORT (must be up before the editor)"
    # AP never prints "idle" on stdout; it appends "Asset Processor is currently idle"
    # to the project's user/log/AP_GUI.log, which persists across runs (rotating at
    # 4 MB), so only a line written after this launch counts.
    ap_gui_log="$PROJECT/user/log/AP_GUI.log"
    ap_lines_before=0
    [[ -f "$ap_gui_log" ]] && ap_lines_before="$(wc -l <"$ap_gui_log")"
    DISPLAY="$DISPLAY_NUM" "$BIN/AssetProcessor" --project-path="$PROJECT" \
        --regset="/Amazon/AzCore/Bootstrap/remote_port=$AP_PORT" >"$STATE/ap.log" 2>&1 &
    echo $! >"$STATE/ap.pid"
    wait_for_ap_idle "$ap_gui_log" "$ap_lines_before"

    echo "Editor with AgentServer on $PORT"
    DISPLAY="$DISPLAY_NUM" O3DE_EDITOR_PORT="$PORT" "$BIN/Editor" --project-path="$PROJECT" \
        --skipWelcomeScreenDialog \
        --regset="/Amazon/AzCore/Bootstrap/remote_port=$AP_PORT" >"$STATE/editor.log" 2>&1 &
    echo $! >"$STATE/editor.pid"
    wait_for_port "$PORT"
    sleep 20

    # --skipWelcomeScreenDialog opens no level, and several tools need one. Each call is
    # its own process: the AgentServer serves one client at a time, and a second request
    # on a pooled connection right after startup has been seen to fail protocol detection.
    call() {
        O3DE_PROJECT_PATH="$PROJECT" O3DE_EDITOR_PORT="$PORT" python - "$1" "$2" <<'EOF' 2>/dev/null
import asyncio, json, sys
from mcp.server import MCPServer
from o3de_mcp.tools.editor import register_editor_tools
m = MCPServer("sandbox"); register_editor_tools(m)
print(asyncio.run(m.call_tool(sys.argv[1], json.loads(sys.argv[2]))).content[0].text)
EOF
    }
    call run_console_command '{"command": "ed_keepEditorActive 1"}'
    echo "Loading level $LEVEL"
    call load_level "{\"level_path\": \"$LEVEL\"}"
    sleep 5
    if ! call get_level_info '{}' | grep -q "\"level_name\": \"$LEVEL\""; then
        echo "level $LEVEL did not open; see $STATE/editor.log" >&2
        exit 1
    fi
    echo "Sandbox ready. Run: scripts/live-sandbox.sh test"
    ;;
test)
    cd "$REPO"
    O3DE_LIVE_EDITOR_TEST=1 O3DE_PROJECT_PATH="$PROJECT" O3DE_EDITOR_PORT="$PORT" \
        python -m pytest tests/test_live_editor.py -p no:randomly "${@:2}"
    ;;
down)
    for name in editor ap xvfb; do
        if [[ -f "$STATE/$name.pid" ]]; then
            kill "$(cat "$STATE/$name.pid")" 2>/dev/null || true
            rm -f "$STATE/$name.pid"
        fi
        sleep 2
    done
    # AssetProcessor leaves resident AssetBuilder workers behind.
    pkill -f "AssetBuilder .*-project-path=\"?$PROJECT" 2>/dev/null || true
    echo "Sandbox stopped. Logs in $STATE"
    ;;
*)
    sed -n '7,26p' "$0"
    exit 2
    ;;
esac
