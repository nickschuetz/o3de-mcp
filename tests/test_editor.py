# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Tests for editor tools and utilities."""

import asyncio
import base64
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from o3de_mcp.tools.editor import (
    _async_run_editor_script,
    _build_framed_request,
    _EditorConnectionPool,
    _encode_script,
    _format_error,
    _get_editor_connect_timeout,
    _get_editor_host,
    _get_editor_port,
    _get_editor_timeout,
    _get_tls_context,
    _send_editor_command,
    _validate_component_type,
    _validate_console_command,
    _validate_entity_id,
    _validate_prefab_path,
    _validate_vec3,
)

# --- Validation tests ---


class TestValidateEntityId:
    def test_plain_numeric(self) -> None:
        assert _validate_entity_id("1234") == "1234"

    def test_bracketed_numeric(self) -> None:
        assert _validate_entity_id("[5678]") == "[5678]"

    def test_strips_whitespace(self) -> None:
        assert _validate_entity_id("  42  ") == "42"

    def test_rejects_alpha(self) -> None:
        with pytest.raises(ValueError, match="Invalid entity ID"):
            _validate_entity_id("abc")

    def test_rejects_shell_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid entity ID"):
            _validate_entity_id("1; rm -rf /")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="Invalid entity ID"):
            _validate_entity_id("")


class TestValidateComponentType:
    def test_simple_name(self) -> None:
        assert _validate_component_type("Mesh") == "Mesh"

    def test_name_with_spaces(self) -> None:
        assert _validate_component_type("PhysX Rigid Body") == "PhysX Rigid Body"

    def test_name_with_parentheses(self) -> None:
        assert _validate_component_type("Script (Lua)") == "Script (Lua)"

    def test_rejects_code_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid component type"):
            _validate_component_type("Mesh'; print('pwned')#")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="Invalid component type"):
            _validate_component_type("")


# --- Configuration tests ---


class TestEditorConfig:
    def test_default_host(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _get_editor_host() == "127.0.0.1"

    def test_custom_host(self) -> None:
        with patch.dict("os.environ", {"O3DE_EDITOR_HOST": "10.0.0.5"}):
            assert _get_editor_host() == "10.0.0.5"

    def test_non_loopback_host_logs_warning(self) -> None:
        with patch.dict("os.environ", {"O3DE_EDITOR_HOST": "192.168.1.100"}):
            with patch("o3de_mcp.tools.editor.logger") as mock_logger:
                _get_editor_host()
                mock_logger.warning.assert_called_once()

    def test_loopback_host_no_warning(self) -> None:
        with patch.dict("os.environ", {"O3DE_EDITOR_HOST": "127.0.0.1"}):
            with patch("o3de_mcp.tools.editor.logger") as mock_logger:
                _get_editor_host()
                mock_logger.warning.assert_not_called()

    def test_default_port(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _get_editor_port() == 4600

    def test_custom_port(self) -> None:
        with patch.dict("os.environ", {"O3DE_EDITOR_PORT": "9000"}):
            assert _get_editor_port() == 9000

    def test_invalid_port_falls_back(self) -> None:
        with patch.dict("os.environ", {"O3DE_EDITOR_PORT": "not_a_number"}):
            assert _get_editor_port() == 4600

    def test_default_command_timeout(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _get_editor_timeout() == 600.0

    def test_custom_command_timeout(self) -> None:
        with patch.dict("os.environ", {"O3DE_EDITOR_TIMEOUT": "45"}):
            assert _get_editor_timeout() == 45.0

    def test_invalid_command_timeout_falls_back(self) -> None:
        with patch.dict("os.environ", {"O3DE_EDITOR_TIMEOUT": "nope"}):
            assert _get_editor_timeout() == 600.0

    def test_non_positive_command_timeout_falls_back(self) -> None:
        with patch.dict("os.environ", {"O3DE_EDITOR_TIMEOUT": "0"}):
            assert _get_editor_timeout() == 600.0

    def test_default_connect_timeout(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _get_editor_connect_timeout() == 5.0

    def test_custom_connect_timeout(self) -> None:
        with patch.dict("os.environ", {"O3DE_EDITOR_CONNECT_TIMEOUT": "12"}):
            assert _get_editor_connect_timeout() == 12.0

    def test_invalid_connect_timeout_falls_back(self) -> None:
        with patch.dict("os.environ", {"O3DE_EDITOR_CONNECT_TIMEOUT": "-3"}):
            assert _get_editor_connect_timeout() == 5.0


# --- Script encoding tests ---


class TestEncodeScript:
    def test_round_trip(self) -> None:
        script = "print('hello world')"
        encoded_cmd = _encode_script(script)
        # Extract the base64 payload from the command
        assert "pyRunScript" in encoded_cmd
        assert "base64" in encoded_cmd
        # Verify the base64-encoded script is present and decodable
        b64_str = base64.b64encode(script.encode("utf-8")).decode("ascii")
        assert b64_str in encoded_cmd

    def test_triple_quotes_safe(self) -> None:
        script = "x = '''triple quoted string'''"
        cmd = _encode_script(script)
        # The base64 encoding means no triple quotes from the script leak into the payload
        b64_payload = base64.b64encode(script.encode("utf-8")).decode("ascii")
        assert "'''" not in b64_payload
        assert b64_payload in cmd

    def test_backslashes_safe(self) -> None:
        script = r"path = 'C:\\Users\\test'"
        encoded_cmd = _encode_script(script)
        b64_payload = base64.b64encode(script.encode("utf-8")).decode("ascii")
        assert b64_payload in encoded_cmd

    def test_unicode_safe(self) -> None:
        script = "name = '日本語テスト'"
        encoded_cmd = _encode_script(script)
        b64_payload = base64.b64encode(script.encode("utf-8")).decode("ascii")
        assert b64_payload in encoded_cmd


# --- Structured error tests ---


class TestFormatError:
    def test_produces_valid_json(self) -> None:
        result = _format_error("test_code", "something went wrong")
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["code"] == "test_code"
        assert parsed["message"] == "something went wrong"


# --- Connection tests ---


class TestSendEditorCommand:
    def test_connection_refused(self) -> None:
        result = _send_editor_command("test", host="127.0.0.1", port=19999)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["code"] == "connection_refused"

    def test_timeout_with_unreachable_host(self) -> None:
        result = _send_editor_command("test", host="192.0.2.1", port=4600, timeout=0.5)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["code"] in ("timeout", "socket_error")

    def test_uses_env_config(self) -> None:
        with patch.dict("os.environ", {"O3DE_EDITOR_PORT": "19998"}):
            result = _send_editor_command("test")
            parsed = json.loads(result)
            assert parsed["status"] == "error"


# --- Connection pool tests ---


class TestEditorConnectionPool:
    def test_send_script_connection_refused(self) -> None:
        pool = _EditorConnectionPool()
        result = asyncio.run(pool.send_script("print(1)", host="127.0.0.1", port=19997))
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["code"] == "connection_refused"

    def test_pool_reconnects_on_host_change(self) -> None:
        pool = _EditorConnectionPool()
        # First call with one port
        result1 = asyncio.run(pool.send_script("print(1)", host="127.0.0.1", port=19996))
        # Second call with different port should reconnect, not reuse
        result2 = asyncio.run(pool.send_script("print(2)", host="127.0.0.1", port=19995))
        # Both should fail (no server), but shouldn't crash
        assert json.loads(result1)["status"] == "error"
        assert json.loads(result2)["status"] == "error"


# --- Async script execution tests ---


class TestAsyncRunEditorScript:
    def test_sends_script_via_pool(self) -> None:
        script = "print('hello')"

        async def run() -> str:
            with patch("o3de_mcp.tools.editor._pool") as mock_pool:
                mock_pool.send_script = AsyncMock(return_value="hello")
                result = await _async_run_editor_script(script)
                # Verify the script was passed to send_script
                mock_pool.send_script.assert_called_once_with(script, timeout=None)
                return result

        result = asyncio.run(run())
        assert result == "hello"


# --- Fast-fail tests ---


class TestEditorConnectionPoolFastFail:
    def test_fast_fail_after_connection_failure(self) -> None:
        """After a connection failure, subsequent calls within the window fail immediately."""
        pool = _EditorConnectionPool()

        # First call — real connection failure
        result1 = asyncio.run(pool.send_script("print(1)", host="127.0.0.1", port=19993))
        parsed1 = json.loads(result1)
        assert parsed1["status"] == "error"

        # Second call — should fast-fail (different error code)
        result2 = asyncio.run(pool.send_script("print(2)", host="127.0.0.1", port=19993))
        parsed2 = json.loads(result2)
        assert parsed2["status"] == "error"
        assert parsed2["code"] == "editor_unavailable"
        assert "get_capabilities()" in parsed2["message"]

    def test_fast_fail_expires(self) -> None:
        """After the fast-fail window expires, the pool re-attempts connection."""
        pool = _EditorConnectionPool()

        # Trigger a failure
        asyncio.run(pool.send_script("print(1)", host="127.0.0.1", port=19992))

        # Manually expire the window
        pool._last_failure_time = time.monotonic() - pool._FAST_FAIL_WINDOW - 1.0

        # Next call should attempt a real connection (not fast-fail)
        result = asyncio.run(pool.send_script("print(1)", host="127.0.0.1", port=19992))
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        # Should be a real connection error, not the fast-fail code
        assert parsed["code"] == "connection_refused"


# --- Framed protocol tests ---


class TestFramedProtocol:
    def test_build_framed_request_ping(self) -> None:
        data = _build_framed_request("ping", request_id="test-id")
        # First 4 bytes are big-endian length
        import struct

        length = struct.unpack(">I", data[:4])[0]
        body = json.loads(data[4:])
        assert body["id"] == "test-id"
        assert body["type"] == "ping"
        assert length == len(data) - 4

    def test_build_framed_request_execute_python(self) -> None:
        data = _build_framed_request("execute_python", script="print('hi')", request_id="exec-1")
        import struct

        length = struct.unpack(">I", data[:4])[0]
        body = json.loads(data[4:])
        assert body["type"] == "execute_python"
        assert body["id"] == "exec-1"
        # Script should be base64 encoded
        decoded = base64.b64decode(body["script"]).decode("utf-8")
        assert decoded == "print('hi')"
        assert length == len(data) - 4

    def test_build_framed_request_auto_generates_id(self) -> None:
        data = _build_framed_request("ping")
        body = json.loads(data[4:])
        assert len(body["id"]) > 0  # UUID was generated


class TestTlsContext:
    def test_tls_disabled_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert _get_tls_context() is None

    def test_tls_enabled(self) -> None:
        with patch.dict("os.environ", {"O3DE_EDITOR_TLS": "1"}):
            ctx = _get_tls_context()
            assert ctx is not None


# --- End-to-end protocol tests against a fake in-process server ---


class TestProtocolRoundTrip:
    """Drive send_script against a real local server speaking each protocol.

    These exercise the connect → detect → command flow end-to-end, which the
    connection-refused tests never reach.
    """

    def test_agent_server_framed_round_trip(self) -> None:
        """A framed AgentServer replies to ping then execute_python."""
        import struct

        async def run() -> str:
            async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                try:
                    while True:
                        header = await reader.readexactly(4)
                        length = struct.unpack(">I", header)[0]
                        body = await reader.readexactly(length)
                        msg = json.loads(body)
                        if msg["type"] == "ping":
                            resp = {"id": msg["id"], "status": "ok"}
                        else:
                            resp = {"id": msg["id"], "status": "ok", "output": "framed-output"}
                        data = json.dumps(resp).encode("utf-8")
                        writer.write(struct.pack(">I", len(data)) + data)
                        await writer.drain()
                except (asyncio.IncompleteReadError, ConnectionError):
                    pass

            server = await asyncio.start_server(handle, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            async with server:
                pool = _EditorConnectionPool()
                try:
                    return await pool.send_script(
                        "print('x')", host="127.0.0.1", port=port, timeout=2.0
                    )
                finally:
                    # Close the pooled connection so the server's handler stops
                    # awaiting and the context manager can tear down (otherwise
                    # wait_closed blocks on the live connection on Python 3.12+).
                    await pool._close()

        assert asyncio.run(run()) == "framed-output"

    def test_legacy_fallback_round_trip(self) -> None:
        """A non-framed server triggers legacy fallback and still returns output.

        Regression test: legacy detection reconnects, and send_script must use
        the reconnected socket — not the closed one the ping was sent on.
        """

        async def run() -> str:
            async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                try:
                    # Respond to any input with plain text. On the detection
                    # connection this is read as a (nonsensical) frame length,
                    # failing detection fast; on the command connection it is
                    # the script's output.
                    await reader.read(4096)
                    writer.write(b"legacy-output\n")
                    await writer.drain()
                    await asyncio.sleep(0.05)
                except ConnectionError:
                    pass
                finally:
                    writer.close()

            server = await asyncio.start_server(handle, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            async with server:
                pool = _EditorConnectionPool()
                try:
                    return await pool.send_script(
                        "print('x')", host="127.0.0.1", port=port, timeout=2.0
                    )
                finally:
                    await pool._close()

        assert "legacy-output" in asyncio.run(run())


# --- Helpers for tool-level tests ---


async def _call_tool(tool_name: str, arguments: dict, mock_output: str = "ok") -> str:
    """Register editor tools on a throwaway FastMCP and call a tool with a mocked pool.

    Returns the text content of the tool's response.
    """
    from mcp.server.fastmcp import FastMCP

    from o3de_mcp.tools.editor import register_editor_tools

    mcp = FastMCP("test")
    register_editor_tools(mcp)
    with patch("o3de_mcp.tools.editor._pool") as mock_pool:
        mock_pool.send_script = AsyncMock(return_value=mock_output)
        content, _ = await mcp.call_tool(tool_name, arguments)
    return content[0].text


# --- Phase 1: Vec3 validator tests ---


class TestValidateVec3:
    def test_valid_list(self) -> None:
        assert _validate_vec3([1.0, 2.0, 3.0], "position") == [1.0, 2.0, 3.0]

    def test_valid_tuple(self) -> None:
        assert _validate_vec3((1, 2, 3), "position") == [1.0, 2.0, 3.0]

    def test_valid_ints_converted_to_floats(self) -> None:
        result = _validate_vec3([1, 2, 3], "scale")
        assert all(isinstance(v, float) for v in result)

    def test_rejects_none(self) -> None:
        with pytest.raises(ValueError, match="cannot be None"):
            _validate_vec3(None, "position")

    def test_rejects_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="exactly 3 elements"):
            _validate_vec3([1, 2], "position")

    def test_rejects_non_numeric(self) -> None:
        with pytest.raises(ValueError, match="only numbers"):
            _validate_vec3(["a", "b", "c"], "position")

    def test_rejects_non_sequence(self) -> None:
        with pytest.raises(ValueError, match="list or tuple"):
            _validate_vec3(42, "position")  # type: ignore[arg-type]


# --- Phase 1: Console command validator tests ---


class TestValidateConsoleCommand:
    def test_valid_simple(self) -> None:
        assert _validate_console_command("r_displayInfo 1") == "r_displayInfo 1"

    def test_valid_with_path(self) -> None:
        assert _validate_console_command("loadlevel Levels/test") == "loadlevel Levels/test"

    def test_strips_whitespace(self) -> None:
        assert _validate_console_command("  r_fog 0  ") == "r_fog 0"

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_console_command("")

    def test_rejects_shell_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid console command"):
            _validate_console_command("r_fog 0; rm -rf /")

    def test_rejects_pipe(self) -> None:
        with pytest.raises(ValueError, match="Invalid console command"):
            _validate_console_command("r_fog | cat")


# --- Phase 1: Prefab path validator tests ---


class TestValidatePrefabPath:
    def test_valid_path(self) -> None:
        assert _validate_prefab_path("Prefabs/MyPrefab.prefab") == "Prefabs/MyPrefab.prefab"

    def test_strips_whitespace(self) -> None:
        assert _validate_prefab_path("  Prefabs/My.prefab  ") == "Prefabs/My.prefab"

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_prefab_path("")

    def test_rejects_wrong_extension(self) -> None:
        with pytest.raises(ValueError, match="must end in '.prefab'"):
            _validate_prefab_path("Prefabs/MyPrefab.json")

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(ValueError, match="must not contain"):
            _validate_prefab_path("../escape.prefab")


# --- Phase 1: Transform tool tests (mocked editor) ---


class TestSetTransform:
    def test_set_position_only(self) -> None:
        result = asyncio.run(
            _call_tool(
                "set_transform",
                {"entity_id": "123", "position": [1, 2, 3]},
                mock_output="Transform set for entity 123",
            )
        )
        assert "Transform set" in result

    def test_set_all_components(self) -> None:
        result = asyncio.run(
            _call_tool(
                "set_transform",
                {
                    "entity_id": "456",
                    "position": [1, 2, 3],
                    "rotation": [0, 0, 0, 1],
                    "scale": [2, 2, 2],
                },
                mock_output="Transform set for entity 456",
            )
        )
        assert "Transform set" in result

    def test_invalid_entity_id_raises(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("set_transform", {"entity_id": "abc", "position": [1, 2, 3]}))


class TestGetTransform:
    def test_returns_json_transform(self) -> None:
        transform_json = json.dumps(
            {"position": [1.0, 2.0, 3.0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]}
        )
        result = asyncio.run(
            _call_tool("get_transform", {"entity_id": "123"}, mock_output=transform_json)
        )
        parsed = json.loads(result)
        assert parsed["position"] == [1.0, 2.0, 3.0]


class TestSetParent:
    def test_set_parent_calls_editor(self) -> None:
        result = asyncio.run(
            _call_tool(
                "set_parent",
                {"entity_id": "123", "parent_id": "456"},
                mock_output="Set parent of 123 to 456",
            )
        )
        assert "Set parent" in result


class TestRemoveComponent:
    def test_remove_component_calls_editor(self) -> None:
        result = asyncio.run(
            _call_tool(
                "remove_component",
                {"entity_id": "123", "component_type": "Mesh"},
                mock_output="Removed Mesh from 123",
            )
        )
        assert "Removed" in result

    def test_invalid_component_type_raises(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(
                _call_tool(
                    "remove_component",
                    {"entity_id": "123", "component_type": "Mesh'; DROP"},
                )
            )


# --- Phase 2: Console/CVAR tool tests ---


class TestRunConsoleCommand:
    def test_executes_command(self) -> None:
        result = asyncio.run(
            _call_tool(
                "run_console_command",
                {"command": "r_fog 0"},
                mock_output="Executed: r_fog 0",
            )
        )
        assert "Executed" in result

    def test_rejects_shell_injection(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(
                _call_tool(
                    "run_console_command",
                    {"command": "r_fog 0; rm -rf /"},
                )
            )

    def test_rejects_empty(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("run_console_command", {"command": ""}))


class TestGetCvar:
    def test_returns_cvar_value(self) -> None:
        cvar_json = json.dumps({"name": "r_fog", "value": "1"})
        result = asyncio.run(_call_tool("get_cvar", {"name": "r_fog"}, mock_output=cvar_json))
        parsed = json.loads(result)
        assert parsed["name"] == "r_fog"
        assert parsed["value"] == "1"

    def test_rejects_invalid_name(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("get_cvar", {"name": "r_fog; cat /etc/passwd"}))


class TestSetCvar:
    def test_sets_cvar(self) -> None:
        result = asyncio.run(
            _call_tool(
                "set_cvar",
                {"name": "r_fog", "value": "0"},
                mock_output="Set r_fog = 0",
            )
        )
        assert "Set r_fog" in result

    def test_rejects_empty_value(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("set_cvar", {"name": "r_fog", "value": ""}))

    def test_rejects_invalid_name(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("set_cvar", {"name": "r_fog | nc", "value": "0"}))


# --- Phase 3: Level creation/listing tool tests ---


class TestCreateLevel:
    def test_creates_level(self) -> None:
        result = asyncio.run(
            _call_tool(
                "create_level",
                {"name": "MyLevel"},
                mock_output="Created and opened level: MyLevel",
            )
        )
        assert "Created" in result

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("create_level", {"name": ""}))

    def test_rejects_invalid_name(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("create_level", {"name": "123Level"}))

    def test_rejects_path_separators(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("create_level", {"name": "Levels/MyLevel"}))


class TestListLevels:
    def test_lists_levels_from_project_path(self, tmp_path: Path) -> None:
        # Create a fake project structure
        levels_dir = tmp_path / "Levels"
        levels_dir.mkdir()
        (levels_dir / "Level1").mkdir()
        (levels_dir / "Level1" / "level.prefab").write_text("fake")
        (levels_dir / "Level2").mkdir()
        (levels_dir / "Level2" / "level.prefab").write_text("fake")
        (levels_dir / "NotALevel").mkdir()  # No level file

        result = asyncio.run(
            _call_tool("list_levels", {"project_path": str(tmp_path)}, mock_output="")
        )
        # list_levels doesn't go through the editor pool — it reads the filesystem
        # directly, so the mock_output is ignored
        parsed = json.loads(result)
        assert "Level1" in parsed["levels"]
        assert "Level2" in parsed["levels"]
        assert "NotALevel" not in parsed["levels"]

    def test_no_levels_directory(self, tmp_path: Path) -> None:
        result = asyncio.run(
            _call_tool("list_levels", {"project_path": str(tmp_path)}, mock_output="")
        )
        parsed = json.loads(result)
        assert "error" in parsed
        assert parsed["levels"] == []

    def test_no_project_path_and_no_registered(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("o3de_mcp.utils.o3de.list_registered_projects", return_value=[]):
                result = asyncio.run(_call_tool("list_levels", {}, mock_output=""))
                parsed = json.loads(result)
                assert "error" in parsed


# --- Phase 4: Viewport camera + screenshot tool tests ---


class TestGetViewportCamera:
    def test_returns_camera_transform(self) -> None:
        cam_json = json.dumps({"position": [10.0, 20.0, 30.0], "rotation": [0.0, 0.0, 0.0]})
        result = asyncio.run(_call_tool("get_viewport_camera", {}, mock_output=cam_json))
        parsed = json.loads(result)
        assert parsed["position"] == [10.0, 20.0, 30.0]
        assert parsed["rotation"] == [0.0, 0.0, 0.0]


class TestSetViewportCamera:
    def test_set_position(self) -> None:
        result = asyncio.run(
            _call_tool(
                "set_viewport_camera",
                {"position": [10, 20, 30]},
                mock_output="Viewport camera set",
            )
        )
        assert "Viewport camera set" in result

    def test_set_position_and_rotation(self) -> None:
        result = asyncio.run(
            _call_tool(
                "set_viewport_camera",
                {"position": [10, 20, 30], "rotation": [0, 0, 0]},
                mock_output="Viewport camera set",
            )
        )
        assert "Viewport camera set" in result

    def test_invalid_position_raises(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("set_viewport_camera", {"position": [1, 2]}))

    def test_invalid_rotation_length_raises(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("set_viewport_camera", {"rotation": [0, 0, 0, 0]}))


class TestFocusEntity:
    def test_focuses_on_entity(self) -> None:
        result = asyncio.run(
            _call_tool(
                "focus_entity",
                {"entity_id": "123"},
                mock_output="Focused on entity 123",
            )
        )
        assert "Focused" in result

    def test_invalid_entity_id_raises(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("focus_entity", {"entity_id": "abc"}))


class TestCaptureViewport:
    def test_captures_screenshot(self) -> None:
        result = asyncio.run(
            _call_tool(
                "capture_viewport",
                {"output_path": "screenshot.png"},
                mock_output="Screenshot saved to screenshot.png",
            )
        )
        assert "Screenshot" in result

    def test_rejects_empty_path(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("capture_viewport", {"output_path": ""}))

    def test_rejects_invalid_extension(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("capture_viewport", {"output_path": "screenshot.txt"}))


# --- Phase 5: Prefab tool tests ---


class TestInstantiatePrefab:
    def test_instantiates_prefab(self) -> None:
        result = asyncio.run(
            _call_tool(
                "instantiate_prefab",
                {"prefab_path": "Prefabs/MyPrefab.prefab", "position": [0, 0, 0]},
                mock_output="Instantiated prefab: Prefabs/MyPrefab.prefab",
            )
        )
        assert "Instantiated" in result

    def test_rejects_wrong_extension(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(
                _call_tool(
                    "instantiate_prefab",
                    {"prefab_path": "Prefabs/MyPrefab.json"},
                )
            )

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(
                _call_tool(
                    "instantiate_prefab",
                    {"prefab_path": "../escape.prefab"},
                )
            )

    def test_invalid_position_raises(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(
                _call_tool(
                    "instantiate_prefab",
                    {"prefab_path": "Prefabs/My.prefab", "position": [1, 2]},
                )
            )


class TestCreatePrefabFromEntity:
    def test_creates_prefab(self) -> None:
        result = asyncio.run(
            _call_tool(
                "create_prefab_from_entity",
                {"entity_id": "123", "prefab_path": "Prefabs/New.prefab"},
                mock_output="Created prefab: Prefabs/New.prefab from entity 123",
            )
        )
        assert "Created" in result

    def test_invalid_entity_id_raises(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(
                _call_tool(
                    "create_prefab_from_entity",
                    {"entity_id": "abc", "prefab_path": "Prefabs/New.prefab"},
                )
            )


class TestSavePrefab:
    def test_saves_prefab(self) -> None:
        result = asyncio.run(
            _call_tool(
                "save_prefab",
                {"entity_id": "123"},
                mock_output="Saved prefab instance: 123",
            )
        )
        assert "Saved" in result

    def test_invalid_entity_id_raises(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("save_prefab", {"entity_id": "xyz"}))


# --- Phase 7: Asset assignment tool tests ---


class TestAssignAsset:
    def test_assigns_asset(self) -> None:
        result = asyncio.run(
            _call_tool(
                "assign_asset",
                {
                    "entity_id": "123",
                    "component_type": "Mesh",
                    "property_path": "Controller|Configuration|Model Asset",
                    "asset_path": "Objects/Props/box.fbx",
                },
                mock_output="Assigned asset Objects/Props/box.fbx to "
                "Controller|Configuration|Model Asset",
            )
        )
        assert "Assigned" in result

    def test_rejects_empty_asset_path(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(
                _call_tool(
                    "assign_asset",
                    {
                        "entity_id": "123",
                        "component_type": "Mesh",
                        "property_path": "Controller|Configuration|Model Asset",
                        "asset_path": "",
                    },
                )
            )

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(
                _call_tool(
                    "assign_asset",
                    {
                        "entity_id": "123",
                        "component_type": "Mesh",
                        "property_path": "Controller|Configuration|Model Asset",
                        "asset_path": "../escape.fbx",
                    },
                )
            )

    def test_rejects_invalid_entity_id(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(
                _call_tool(
                    "assign_asset",
                    {
                        "entity_id": "abc",
                        "component_type": "Mesh",
                        "property_path": "Controller|Configuration|Model Asset",
                        "asset_path": "Objects/box.fbx",
                    },
                )
            )


# --- Phase 9: Persistent Python session tool tests ---


class TestBeginSession:
    def test_begins_session(self) -> None:
        session_json = json.dumps({"session_id": "abc12345"})
        result = asyncio.run(_call_tool("begin_session", {}, mock_output=session_json))
        parsed = json.loads(result)
        assert "session_id" in parsed


class TestExecInSession:
    def test_executes_in_session(self) -> None:
        result = asyncio.run(
            _call_tool(
                "exec_in_session",
                {"session_id": "abc12345", "script": "x = 42"},
                mock_output="",
            )
        )
        # The tool should send the script to the editor
        # With mocked output, we just verify it doesn't raise
        assert isinstance(result, str)

    def test_rejects_empty_session_id(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("exec_in_session", {"session_id": "", "script": "x = 1"}))

    def test_rejects_empty_script(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("exec_in_session", {"session_id": "abc", "script": ""}))


class TestEndSession:
    def test_ends_session(self) -> None:
        result = asyncio.run(
            _call_tool(
                "end_session",
                {"session_id": "abc12345"},
                mock_output="Session abc12345 ended",
            )
        )
        assert "ended" in result

    def test_rejects_empty_session_id(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("end_session", {"session_id": ""}))


class TestGetSessionVars:
    def test_returns_vars(self) -> None:
        vars_json = json.dumps({"vars": ["x", "y", "my_entity"], "count": 3})
        result = asyncio.run(
            _call_tool(
                "get_session_vars",
                {"session_id": "abc12345"},
                mock_output=vars_json,
            )
        )
        parsed = json.loads(result)
        assert parsed["count"] == 3
        assert "x" in parsed["vars"]

    def test_rejects_empty_session_id(self) -> None:
        with pytest.raises(Exception):
            asyncio.run(_call_tool("get_session_vars", {"session_id": ""}))
