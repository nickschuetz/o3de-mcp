# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""Tests for editor tools and utilities."""

import asyncio
import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from o3de_mcp.tools.editor import (
    _async_run_editor_script,
    _EditorConnectionPool,
    _encode_script,
    _format_error,
    _get_editor_host,
    _get_editor_port,
    _send_editor_command,
    _validate_component_type,
    _validate_entity_id,
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
    def test_send_command_connection_refused(self) -> None:
        pool = _EditorConnectionPool()
        result = asyncio.run(pool.send_command("test", host="127.0.0.1", port=19997))
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["code"] == "connection_refused"

    def test_pool_reconnects_on_host_change(self) -> None:
        pool = _EditorConnectionPool()
        # First call with one port
        result1 = asyncio.run(pool.send_command("test", host="127.0.0.1", port=19996))
        # Second call with different port should reconnect, not reuse
        result2 = asyncio.run(pool.send_command("test", host="127.0.0.1", port=19995))
        # Both should fail (no server), but shouldn't crash
        assert json.loads(result1)["status"] == "error"
        assert json.loads(result2)["status"] == "error"

    def test_pool_reuses_connection(self) -> None:
        pool = _EditorConnectionPool()

        mock_reader = AsyncMock()
        mock_reader.read = AsyncMock(return_value=b"ok\n")
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.is_closing = MagicMock(return_value=False)
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        call_count = 0

        async def mock_open_connection(*_args: object, **_kwargs: object) -> tuple:
            nonlocal call_count
            call_count += 1
            return mock_reader, mock_writer

        async def run() -> None:
            nonlocal call_count
            with patch("asyncio.open_connection", side_effect=mock_open_connection):
                await pool.send_command("cmd1", host="127.0.0.1", port=19994)
                await pool.send_command("cmd2", host="127.0.0.1", port=19994)

        asyncio.run(run())
        # Should only have connected once (reused the connection)
        assert call_count == 1


# --- Async script execution tests ---


class TestAsyncRunEditorScript:
    def test_sends_encoded_script(self) -> None:
        script = "print('hello')"

        async def run() -> str:
            with patch("o3de_mcp.tools.editor._pool") as mock_pool:
                mock_pool.send_command = AsyncMock(return_value="hello")
                result = await _async_run_editor_script(script)
                # Verify the command sent contains base64-encoded script
                call_args = mock_pool.send_command.call_args[0][0]
                assert "pyRunScript" in call_args
                assert "base64" in call_args
                return result

        result = asyncio.run(run())
        assert result == "hello"


# --- Fast-fail tests ---


class TestEditorConnectionPoolFastFail:
    def test_fast_fail_after_connection_failure(self) -> None:
        """After a connection failure, subsequent calls within the window fail immediately."""
        pool = _EditorConnectionPool()

        # First call — real connection failure
        result1 = asyncio.run(pool.send_command("test", host="127.0.0.1", port=19993))
        parsed1 = json.loads(result1)
        assert parsed1["status"] == "error"

        # Second call — should fast-fail (different error code)
        result2 = asyncio.run(pool.send_command("test", host="127.0.0.1", port=19993))
        parsed2 = json.loads(result2)
        assert parsed2["status"] == "error"
        assert parsed2["code"] == "editor_unavailable"
        assert "get_capabilities()" in parsed2["message"]

    def test_fast_fail_expires(self) -> None:
        """After the fast-fail window expires, the pool re-attempts connection."""
        pool = _EditorConnectionPool()

        # Trigger a failure
        asyncio.run(pool.send_command("test", host="127.0.0.1", port=19992))

        # Manually expire the window
        pool._last_failure_time = time.monotonic() - pool._FAST_FAIL_WINDOW - 1.0

        # Next call should attempt a real connection (not fast-fail)
        result = asyncio.run(pool.send_command("test", host="127.0.0.1", port=19992))
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        # Should be a real connection error, not the fast-fail code
        assert parsed["code"] == "connection_refused"

    def test_fast_fail_resets_on_success(self) -> None:
        """Successful connection resets the fast-fail timer."""
        pool = _EditorConnectionPool()

        mock_reader = AsyncMock()
        mock_reader.read = AsyncMock(return_value=b"ok\n")
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.is_closing = MagicMock(return_value=False)
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        # Set a recent failure time
        pool._last_failure_time = time.monotonic()

        async def run() -> None:
            with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
                # Manually clear the fast-fail to allow the connection attempt
                pool._last_failure_time = None
                await pool.send_command("cmd", host="127.0.0.1", port=19991)
                # After success, failure time should be cleared
                assert pool._last_failure_time is None

        asyncio.run(run())
