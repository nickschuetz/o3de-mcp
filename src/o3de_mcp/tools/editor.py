# Copyright (c) Contributors to the Open 3D Engine Project.
# For complete copyright and license terms please see the LICENSE at the root of this distribution.
#
# SPDX-License-Identifier: Apache-2.0 OR MIT

"""MCP tools for O3DE Editor automation.

These tools interact with a running O3DE Editor instance via its
EditorPythonBindings (EPB) interface. Communication uses the AiCompanion
Gem's AgentServer (length-prefixed JSON protocol), with automatic fallback
to the legacy RemoteConsole text protocol for older setups.

Communication flow:
  MCP client → this server → TCP socket (port 4600) → O3DE Editor AgentServer
  The AgentServer executes Python scripts in the editor's embedded Python
  interpreter, which has access to the ``azlmbr`` namespace.

Configuration:
  O3DE_EDITOR_HOST            — editor host (default: 127.0.0.1)
  O3DE_EDITOR_PORT            — editor port (default: 4600)
  O3DE_EDITOR_TIMEOUT         — per-command execution timeout, seconds (default: 600)
  O3DE_EDITOR_CONNECT_TIMEOUT — TCP connect timeout, seconds (default: 5)
  O3DE_EDITOR_TLS             — enable TLS (default: 0)
  O3DE_EDITOR_TLS_VERIFY      — verify TLS cert (default: 0)
  O3DE_EDITOR_TLS_CA          — path to CA cert for verification
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import socket
import ssl as ssl_module
import struct
import textwrap
import time
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Hosts considered safe for plaintext communication
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

# Validates entity IDs — O3DE uses numeric IDs like "[1234]" or plain integers
_ENTITY_ID_RE = re.compile(r"^\[?\d+\]?$")

# Validates component type names — alphanumeric, spaces, hyphens, parentheses
_COMPONENT_TYPE_RE = re.compile(r"^[A-Za-z0-9 ()\-_]+$")

# Safety limit to prevent unbounded reads
_MAX_RESPONSE_BYTES = 1024 * 1024  # 1 MiB

# Short timeout used after receiving initial data to detect end-of-response
_TAIL_TIMEOUT = 0.5


# Default per-command execution timeout (seconds). Deliberately generous:
# editor operations run the submitted Python *synchronously* and the editor
# does not reply until the script finishes, so this is really "how long an
# editor operation may take" — level loads, game-mode entry, and on-demand
# asset compilation routinely exceed tens of seconds. A dead editor is caught
# in milliseconds by the connect timeout / fast-fail window, not this value,
# so a large default costs nothing on the healthy path.
_DEFAULT_EDITOR_TIMEOUT = 600.0

# Default TCP connect timeout (seconds). On loopback a dead editor refuses
# instantly; this only bounds the pathological "host silently blackholes" case.
_DEFAULT_CONNECT_TIMEOUT = 5.0


def _get_editor_timeout() -> float:
    """Return the per-command editor execution timeout in seconds.

    Read per call (like host/port) from O3DE_EDITOR_TIMEOUT. A missing/invalid
    value falls back to the default, and a non-positive value is treated as
    invalid (a 0 or negative timeout would make every editor call fail
    instantly).
    """
    try:
        value = float(os.environ.get("O3DE_EDITOR_TIMEOUT", str(_DEFAULT_EDITOR_TIMEOUT)))
    except (TypeError, ValueError):
        return _DEFAULT_EDITOR_TIMEOUT
    return value if value > 0.0 else _DEFAULT_EDITOR_TIMEOUT


def _get_editor_connect_timeout() -> float:
    """Return the TCP connect timeout in seconds.

    Separate from the command timeout so that "editor is unreachable" is
    detected quickly even when a long command timeout is configured. Read per
    call from O3DE_EDITOR_CONNECT_TIMEOUT; invalid/non-positive falls back to
    the default.
    """
    try:
        value = float(os.environ.get("O3DE_EDITOR_CONNECT_TIMEOUT", str(_DEFAULT_CONNECT_TIMEOUT)))
    except (TypeError, ValueError):
        return _DEFAULT_CONNECT_TIMEOUT
    return value if value > 0.0 else _DEFAULT_CONNECT_TIMEOUT


def _get_editor_host() -> str:
    """Return the configured editor remote console host.

    Logs a warning when the host is not a loopback address, since commands
    are sent in plaintext over TCP.
    """
    host = os.environ.get("O3DE_EDITOR_HOST", "127.0.0.1")
    if host not in _LOOPBACK_HOSTS:
        logger.warning(
            "O3DE_EDITOR_HOST is set to %r which is not a loopback address. "
            "Commands will be sent over the network in plaintext.",
            host,
        )
    return host


def _get_editor_port() -> int:
    """Return the configured editor remote console port."""
    raw = os.environ.get("O3DE_EDITOR_PORT", "4600")
    try:
        return int(raw)
    except ValueError:
        return 4600


def _format_error(code: str, message: str) -> str:
    """Return a structured JSON error string."""
    return json.dumps({"status": "error", "code": code, "message": message})


def _connection_error_response(exc: Exception, host: str, port: int, timeout: float) -> str:
    """Map a socket exception to a structured JSON error string."""
    if isinstance(exc, ConnectionRefusedError):
        return _format_error(
            "connection_refused",
            f"Could not connect to O3DE Editor on {host}:{port}. "
            "Ensure the editor is running with the AiCompanion gem enabled.",
        )
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return _format_error(
            "timeout",
            f"Connection to O3DE Editor timed out after {timeout}s.",
        )
    return _format_error(
        "socket_error",
        f"Socket error communicating with O3DE Editor: {exc}",
    )


class EditorConnectionError(Exception):
    """Raised when the MCP server cannot reach the O3DE Editor."""


# ---------------------------------------------------------------------------
# Input validators
# ---------------------------------------------------------------------------


def _validate_entity_id(entity_id: str) -> str:
    """Validate and normalize an entity ID string.

    Raises ValueError if the entity ID doesn't match the expected format.
    """
    entity_id = entity_id.strip()
    if not _ENTITY_ID_RE.match(entity_id):
        raise ValueError(
            f"Invalid entity ID format: {entity_id!r}. "
            "Expected a numeric ID like '1234' or '[1234]'."
        )
    return entity_id


def _validate_component_type(component_type: str) -> str:
    """Validate a component type name.

    Raises ValueError if the component type contains unexpected characters.
    """
    component_type = component_type.strip()
    if not _COMPONENT_TYPE_RE.match(component_type):
        raise ValueError(
            f"Invalid component type: {component_type!r}. "
            "Expected alphanumeric characters, spaces, hyphens, or parentheses."
        )
    return component_type


_CONSOLE_COMMAND_RE = re.compile(r"^[A-Za-z0-9 ._\-=/\"']+$")


def _validate_console_command(command: str) -> str:
    """Validate a console command string, rejecting shell metacharacters."""
    command = command.strip()
    if not command:
        raise ValueError("Console command cannot be empty.")
    if not _CONSOLE_COMMAND_RE.match(command):
        raise ValueError(
            f"Invalid console command: {command!r}. "
            "Expected alphanumeric characters, spaces, dots, underscores, "
            "hyphens, equals, quotes, or forward slashes."
        )
    return command


def _validate_vec3(
    value: list[float] | tuple[float, float, float] | None, name: str
) -> list[float]:
    """Validate a 3-element numeric vector (position, rotation, or scale)."""
    if value is None:
        raise ValueError(f"{name} cannot be None.")
    if not isinstance(value, (list, tuple)):
        raise ValueError(
            f"{name} must be a list or tuple of 3 numbers, got {type(value).__name__}."
        )
    if len(value) != 3:
        raise ValueError(f"{name} must have exactly 3 elements, got {len(value)}.")
    try:
        result = [float(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain only numbers, got {value!r}.") from exc
    return result


def _validate_prefab_path(path: str) -> str:
    """Validate a prefab file path (must end in .prefab, no path traversal)."""
    path = path.strip()
    if not path:
        raise ValueError("Prefab path cannot be empty.")
    if not path.endswith(".prefab"):
        raise ValueError(f"Prefab path must end in '.prefab': {path!r}.")
    if ".." in path:
        raise ValueError(f"Prefab path must not contain '..': {path!r}.")
    return path


# ---------------------------------------------------------------------------
# Script encoding — legacy (RemoteConsole text protocol)
# ---------------------------------------------------------------------------


def _encode_script(script: str) -> str:
    """Encode a Python script as a ``pyRunScript`` command (legacy protocol).

    Uses base64 encoding so that arbitrary script content (including triple
    quotes, backslashes, and any other special characters) is transported
    safely without escaping issues.
    """
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return (
        f"pyRunScript '''import base64 as _b64; "
        f'exec(_b64.b64decode("{encoded}").decode("utf-8"))\'\'\''
    )


_ENTITY_RESOLVER_SNIPPET = """
import azlmbr.entity as entity
import azlmbr.bus as bus

def _resolve_entity_id(eid_str):
    eid_str = str(eid_str).strip()
    try:
        candidate = entity.EntityId(int(eid_str.strip('[]')))
        if candidate.IsValid():
            return candidate
    except Exception:
        pass
    search_filter = entity.SearchFilter()
    entity_ids = entity.SearchBus(bus.Broadcast, 'SearchEntities', search_filter)
    for eid in (entity_ids or []):
        if str(eid) == eid_str or str(eid).strip('[]') == eid_str.strip('[]'):
            return eid
    return None
"""


# ---------------------------------------------------------------------------
# Framed protocol — AgentServer (length-prefixed JSON)
# ---------------------------------------------------------------------------


def _build_framed_request(
    request_type: str, script: str | None = None, request_id: str | None = None
) -> bytes:
    """Build a length-prefixed JSON request for the AgentServer protocol."""
    msg: dict = {
        "id": request_id or str(uuid.uuid4()),
        "type": request_type,
    }
    if script is not None:
        msg["script"] = base64.b64encode(script.encode("utf-8")).decode("ascii")
    body = json.dumps(msg).encode("utf-8")
    return struct.pack(">I", len(body)) + body


def _recv_framed(sock: socket.socket, timeout: float) -> dict[str, object]:
    """Read a length-prefixed JSON response from a socket (sync)."""
    sock.settimeout(timeout)
    header = b""
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk:
            raise ConnectionError("Connection closed while reading header")
        header += chunk

    length = struct.unpack(">I", header)[0]
    if length > _MAX_RESPONSE_BYTES:
        raise ValueError(f"Response too large: {length} bytes")

    body = b""
    while len(body) < length:
        chunk = sock.recv(min(8192, length - len(body)))
        if not chunk:
            raise ConnectionError("Connection closed while reading body")
        body += chunk

    result: dict[str, object] = json.loads(body.decode("utf-8"))
    return result


async def _async_recv_framed(reader: asyncio.StreamReader, timeout: float) -> dict[str, object]:
    """Read a length-prefixed JSON response from an async reader."""
    header = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
    length = struct.unpack(">I", header)[0]
    if length > _MAX_RESPONSE_BYTES:
        raise ValueError(f"Response too large: {length} bytes")
    body = await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
    result: dict[str, object] = json.loads(body.decode("utf-8"))
    return result


# ---------------------------------------------------------------------------
# Legacy protocol helpers — timeout-based I/O for RemoteConsole fallback
# ---------------------------------------------------------------------------


def _recv_all(sock: socket.socket, timeout: float) -> bytes:
    """Read from a socket until EOF or no more data arrives (legacy protocol).

    Uses the full *timeout* for the first chunk (waiting for the editor to
    respond), then switches to a short tail timeout to collect any remaining
    data without blocking unnecessarily.
    """
    chunks: list[bytes] = []
    total = 0
    original_timeout = sock.gettimeout()
    try:
        while total < _MAX_RESPONSE_BYTES:
            try:
                chunk = sock.recv(min(8192, _MAX_RESPONSE_BYTES - total))
                if not chunk:
                    break  # EOF — server closed connection
                chunks.append(chunk)
                total += len(chunk)
                # After first data, use short timeout to detect end-of-response
                sock.settimeout(_TAIL_TIMEOUT)
            except TimeoutError:
                if chunks:
                    break  # Got data, just no more coming
                raise  # No data at all — real timeout
    finally:
        sock.settimeout(original_timeout)
    return b"".join(chunks)


async def _async_recv_all(reader: asyncio.StreamReader, timeout: float) -> bytes:
    """Async equivalent of :func:`_recv_all` (legacy protocol)."""
    chunks: list[bytes] = []
    total = 0
    while total < _MAX_RESPONSE_BYTES:
        try:
            read_timeout = timeout if not chunks else _TAIL_TIMEOUT
            chunk = await asyncio.wait_for(
                reader.read(min(8192, _MAX_RESPONSE_BYTES - total)),
                timeout=read_timeout,
            )
            if not chunk:
                break  # EOF
            chunks.append(chunk)
            total += len(chunk)
        except (TimeoutError, asyncio.TimeoutError):
            if chunks:
                break
            raise
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# TLS helpers
# ---------------------------------------------------------------------------


def _get_tls_context() -> ssl_module.SSLContext | None:
    """Build an SSL context if TLS is enabled via environment variables."""
    if os.environ.get("O3DE_EDITOR_TLS", "0") not in ("1", "true"):
        return None

    ctx = ssl_module.SSLContext(ssl_module.PROTOCOL_TLS_CLIENT)

    verify = os.environ.get("O3DE_EDITOR_TLS_VERIFY", "0")
    if verify in ("0", "false"):
        ctx.check_hostname = False
        ctx.verify_mode = ssl_module.CERT_NONE
    else:
        ca_path = os.environ.get("O3DE_EDITOR_TLS_CA")
        if ca_path:
            ctx.load_verify_locations(ca_path)

    return ctx


# ---------------------------------------------------------------------------
# Sync transport (used by tests)
# ---------------------------------------------------------------------------


def _send_editor_command(
    command: str,
    host: str | None = None,
    port: int | None = None,
    timeout: float | None = None,
) -> str:
    """Send a command to the O3DE Editor and return the response.

    Creates a new TCP connection for each call.  This synchronous variant is
    kept primarily for test convenience; the async path via
    :class:`_EditorConnectionPool` is used by all MCP tools.
    """
    host = host or _get_editor_host()
    port = port or _get_editor_port()
    timeout = _get_editor_timeout() if timeout is None else timeout
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(command.encode("utf-8") + b"\n")
            response = _recv_all(sock, timeout)
            return response.decode("utf-8", errors="replace").strip()
    except (ConnectionRefusedError, TimeoutError, OSError) as exc:
        return _connection_error_response(exc, host, port, timeout)


# ---------------------------------------------------------------------------
# Async transport — persistent connection pool with protocol auto-detection
# ---------------------------------------------------------------------------


# Protocol enum
_PROTO_UNKNOWN = 0
_PROTO_AGENT_SERVER = 1  # length-prefixed JSON (AiCompanion AgentServer)
_PROTO_LEGACY = 2  # raw text (RemoteConsole)


class _EditorConnectionPool:
    """Maintains a persistent async TCP connection to the O3DE Editor.

    Reuses a single connection across multiple tool calls to avoid TCP
    handshake overhead.  Automatically reconnects when the connection is
    lost or when host/port configuration changes.

    Supports two protocols:
      - **AgentServer** (preferred): length-prefixed JSON framing, used by
        the AiCompanion gem's built-in server.
      - **Legacy**: raw text ``pyRunScript`` commands over RemoteConsole.

    Protocol is auto-detected on first connection by sending a framed
    ``ping`` request. If a valid framed JSON response is received, the
    AgentServer protocol is used for the connection lifetime. Otherwise,
    the pool falls back to legacy mode.

    Includes a fast-fail window: after a connection failure, subsequent
    calls within ``_FAST_FAIL_WINDOW`` seconds return an error immediately
    instead of re-attempting the TCP connection.
    """

    _FAST_FAIL_WINDOW = 5.0

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._host: str | None = None
        self._port: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        self._last_failure_time: float | None = None
        self._protocol: int = _PROTO_UNKNOWN

    async def send_script(
        self,
        script: str,
        host: str | None = None,
        port: int | None = None,
        timeout: float | None = None,
    ) -> str:
        """Encode and send a Python script, returning the output text."""
        host = host or _get_editor_host()
        port = port or _get_editor_port()
        timeout = _get_editor_timeout() if timeout is None else timeout
        connect_timeout = _get_editor_connect_timeout()

        current_loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not current_loop:
            self._lock = asyncio.Lock()
            self._lock_loop = current_loop

        async with self._lock:
            if self._last_failure_time is not None:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed < self._FAST_FAIL_WINDOW:
                    return _format_error(
                        "editor_unavailable",
                        f"O3DE Editor is not reachable on {host}:{port}. "
                        "Start the editor with the AiCompanion gem enabled, "
                        "or call get_capabilities() to check status. "
                        "This operation requires a running editor and "
                        "cannot be performed via CLI.",
                    )

            try:
                reader, writer = await self._ensure_connected(host, port, connect_timeout)
            except (
                ConnectionRefusedError,
                ConnectionError,
                TimeoutError,
                asyncio.TimeoutError,
                OSError,
            ) as exc:
                self._last_failure_time = time.monotonic()
                await self._close()
                return _connection_error_response(exc, host, port, connect_timeout)

            try:
                if self._protocol == _PROTO_AGENT_SERVER:
                    return await self._send_framed_script(reader, writer, script, timeout)
                else:
                    return await self._send_legacy_script(reader, writer, script, timeout)
            except (TimeoutError, asyncio.TimeoutError):
                self._last_failure_time = time.monotonic()
                await self._close()
                return _format_error(
                    "timeout",
                    f"O3DE Editor command did not complete within {timeout}s. The editor "
                    "may still be running the script — increase O3DE_EDITOR_TIMEOUT for "
                    "long operations (level loads, game-mode entry, asset compilation).",
                )
            except (ConnectionRefusedError, OSError) as exc:
                self._last_failure_time = time.monotonic()
                await self._close()
                return _connection_error_response(exc, host, port, timeout)

    async def _send_framed_script(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        script: str,
        timeout: float,
    ) -> str:
        """Send a script via the AgentServer framed JSON protocol."""
        request_bytes = _build_framed_request("execute_python", script=script)
        writer.write(request_bytes)
        await writer.drain()
        response = await _async_recv_framed(reader, timeout)
        self._last_failure_time = None

        if response.get("status") == "error":
            error_msg = str(response.get("error", "Unknown error"))
            return _format_error("editor_error", error_msg)

        return str(response.get("output", ""))

    async def _send_legacy_script(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        script: str,
        timeout: float,
    ) -> str:
        """Send a script via the legacy RemoteConsole text protocol."""
        command = _encode_script(script)
        writer.write(command.encode("utf-8") + b"\n")
        await writer.drain()
        response = await _async_recv_all(reader, timeout)
        self._last_failure_time = None
        return response.decode("utf-8", errors="replace").strip()

    async def _ensure_connected(
        self, host: str, port: int, connect_timeout: float
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        current_loop = asyncio.get_running_loop()
        if (
            self._writer is not None
            and not self._writer.is_closing()
            and self._loop is current_loop
            and self._host == host
            and self._port == port
        ):
            return self._reader, self._writer  # type: ignore[return-value]

        had_previous = self._writer is not None
        await self._close()

        if had_previous:
            await asyncio.sleep(0.5)

        ssl_ctx = _get_tls_context()
        max_attempts = 3 if had_previous else 1
        last_err: Exception | None = None
        reader, writer = None, None
        for attempt in range(max_attempts):
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port, ssl=ssl_ctx), timeout=connect_timeout
                )
                last_err = None
                break
            except (OSError, ConnectionError) as e:
                last_err = e
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
        if last_err is not None or reader is None or writer is None:
            raise last_err if last_err else ConnectionError("Failed to connect")
        self._reader = reader
        self._writer = writer
        self._host = host
        self._port = port
        self._loop = current_loop

        # Auto-detect protocol. Detection may reconnect (legacy fallback), so
        # always hand back the pool's *current* sockets rather than the locals
        # captured above, which detection may have already closed.
        self._protocol = await self._detect_protocol(host, port, connect_timeout)
        logger.info(
            "Connected to %s:%d (protocol=%s, tls=%s)",
            host,
            port,
            "agent_server" if self._protocol == _PROTO_AGENT_SERVER else "legacy",
            "yes" if ssl_ctx else "no",
        )

        return self._reader, self._writer  # type: ignore[return-value]

    async def _detect_protocol(self, host: str, port: int, connect_timeout: float) -> int:
        """Detect whether the server speaks AgentServer or legacy protocol.

        Sends a framed ``ping`` on the current connection. If a valid framed
        JSON response with ``"status": "ok"`` comes back, the server is an
        AgentServer and the connection is left ready for use.

        If the server sends a non-framed response (e.g. raw text), it's a
        legacy RemoteConsole — reconnect fresh for the text protocol.

        If the ping times out or the connection errors, we do NOT fall back
        to legacy (which would send ``pyRunScript`` to an AgentServer and
        produce a "Message too large" error on the server). Instead, we
        raise the error so the caller can handle it.
        """
        ping_bytes = _build_framed_request("ping")
        self._writer.write(ping_bytes)  # type: ignore[union-attr]
        await self._writer.drain()  # type: ignore[union-attr]

        try:
            response = await _async_recv_framed(self._reader, timeout=5.0)  # type: ignore[arg-type]
        except (asyncio.TimeoutError, TimeoutError):
            await self._close()
            raise ConnectionError("Ping timed out during protocol detection")
        except (ConnectionError, OSError, asyncio.IncompleteReadError) as exc:
            await self._close()
            raise ConnectionError(f"Connection error during protocol detection: {exc}")
        except (ValueError, json.JSONDecodeError):
            response = None

        if isinstance(response, dict) and response.get("status") == "ok":
            return _PROTO_AGENT_SERVER

        await self._close()
        ssl_ctx = _get_tls_context()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl_ctx), timeout=connect_timeout
        )
        self._reader = reader
        self._writer = writer
        self._host = host
        self._port = port
        self._loop = asyncio.get_running_loop()
        return _PROTO_LEGACY

    async def _close(self) -> None:
        if self._writer is not None:
            current_loop = None
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
            if self._loop is None or self._loop is current_loop:
                try:
                    self._writer.close()
                    await self._writer.wait_closed()
                except (OSError, RuntimeError):
                    pass
            else:
                try:
                    sock = self._writer.get_extra_info("socket")
                    if sock is not None:
                        sock.close()
                except Exception:
                    pass
            self._reader = None
            self._writer = None
            self._host = None
            self._port = None
            self._loop = None
            self._protocol = _PROTO_UNKNOWN


# Module-level pool instance shared by all tools
_pool = _EditorConnectionPool()


# ---------------------------------------------------------------------------
# Script execution helpers
# ---------------------------------------------------------------------------


async def _async_run_editor_script(script: str, timeout: float | None = None) -> str:
    """Encode a Python script and send it to the editor via the pool.

    ``timeout`` overrides the per-command execution timeout for this call;
    ``None`` uses the O3DE_EDITOR_TIMEOUT default.
    """
    if "_resolve_entity_id" in script:
        script = _ENTITY_RESOLVER_SNIPPET + script
    return await _pool.send_script(script, timeout=timeout)


def _run_editor_script(script: str) -> str:
    """Encode a Python script and send it to the editor (sync)."""
    return _send_editor_command(_encode_script(script))


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_editor_tools(mcp: FastMCP) -> None:
    """Register all editor automation tools with the MCP server."""

    # --- Script execution ---

    @mcp.tool()
    async def run_editor_python(script: str, timeout: float | None = None) -> str:
        """Execute a Python script inside the running O3DE Editor.

        The script runs in the editor's embedded Python interpreter and has
        access to the full azlmbr (EditorPythonBindings) API. Use this for
        custom editor automation that isn't covered by other tools.

        Args:
            script: Python code to execute. Has access to azlmbr modules.
            timeout: Optional per-call execution timeout in seconds. The editor
                runs the script synchronously and does not reply until it
                finishes, so raise this for known-heavy operations. Omit to use
                the O3DE_EDITOR_TIMEOUT default (600s).
        """
        return await _async_run_editor_script(script, timeout=timeout)

    # --- Entity management ---

    @mcp.tool()
    async def list_entities() -> str:
        """List all entities in the currently open O3DE level.

        Returns a JSON array of objects with 'id' and 'name' fields.
        """
        script = textwrap.dedent("""\
            import azlmbr.entity as entity
            import azlmbr.bus as bus
            import azlmbr.editor as editor
            import json

            search_filter = entity.SearchFilter()
            entity_ids = entity.SearchBus(bus.Broadcast, 'SearchEntities', search_filter)

            results = []
            for eid in (entity_ids or []):
                name = editor.EditorEntityInfoRequestBus(bus.Event, 'GetName', eid)
                results.append({'id': str(eid), 'name': name})

            print(json.dumps(results))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def create_entity(name: str, parent_id: str | None = None) -> str:
        """Create a new entity in the current O3DE level.

        Args:
            name: Name for the new entity.
            parent_id: Optional entity ID of the parent. None for root-level.
        """
        if parent_id is not None:
            parent_id = _validate_entity_id(parent_id)

        params = json.dumps({"name": name, "parent_id": parent_id})
        script = textwrap.dedent(f"""\
            import azlmbr.editor as editor
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import json

            _params = json.loads({params!r})
            _name = _params['name']
            _parent_id_str = _params['parent_id']

            if _parent_id_str:
                parent = _resolve_entity_id(_parent_id_str)
            else:
                parent = entity.EntityId()

            new_id = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', parent)
            editor.EditorEntityAPIBus(bus.Event, 'SetName', new_id, _name)
            print(f'Created entity {{new_id}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def delete_entity(entity_id: str) -> str:
        """Delete an entity from the current O3DE level.

        Args:
            entity_id: The entity ID to delete.
        """
        entity_id = _validate_entity_id(entity_id)
        params = json.dumps({"entity_id": entity_id})
        script = textwrap.dedent(f"""\
            import azlmbr.editor as editor
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])
            editor.ToolsApplicationRequestBus(bus.Broadcast, 'DeleteEntityById', eid)
            print(f'Deleted entity {{eid}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def duplicate_entity(entity_id: str) -> str:
        """Duplicate an entity (and its children) in the current O3DE level.

        Args:
            entity_id: The entity ID to duplicate.
        """
        entity_id = _validate_entity_id(entity_id)
        params = json.dumps({"entity_id": entity_id})
        script = textwrap.dedent(f"""\
            import azlmbr.editor as editor
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])
            clone = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CloneEntity', eid)
            name = editor.EditorEntityInfoRequestBus(bus.Event, 'GetName', clone)
            print(json.dumps({{'id': str(clone), 'name': name}}))
        """)
        return await _async_run_editor_script(script)

    # --- Component management ---

    @mcp.tool()
    async def get_entity_components(entity_id: str) -> str:
        """List all components attached to an entity.

        Args:
            entity_id: The entity ID to inspect.

        Returns:
            JSON array of objects with 'component_id' and 'type' fields.
        """
        entity_id = _validate_entity_id(entity_id)
        params = json.dumps({"entity_id": entity_id})
        script = textwrap.dedent(f"""\
            import azlmbr.editor as editor
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])
            gt = entity.EntityType().Game

            results = []
            # Try legacy GetComponentsOfEntity first
            try:
                components = editor.EditorComponentAPIBus(
                    bus.Broadcast, 'GetComponentsOfEntity', eid
                )
                if components is not None and len(components) > 0:
                    for comp in components:
                        type_name = editor.EditorComponentAPIBus(
                            bus.Broadcast, 'GetComponentName', comp
                        )
                        results.append({{'component_id': str(comp), 'type': type_name}})
                    print(json.dumps(results))
                else:
                    raise RuntimeError('empty')
            except Exception:
                # O3DE 2510+: probe known component types via HasComponentOfType
                known = [
                    'Mesh', 'Material', 'Decal', 'SkinnedMesh',
                    'Directional Light', 'Point Light', 'Spot Light', 'Area Light',
                    'HDRi Skybox', 'Global Skylight (IBL)', 'Physical Sky',
                    'PhysX Primitive Collider', 'PhysX Collider',
                    'PhysX Dynamic Rigid Body', 'PhysX Rigid Body',
                    'PhysX Static Rigid Body', 'PhysX Mesh Collider',
                    'PhysX Shape Collider', 'PhysX Character Controller',
                    'PhysX Force Region',
                    'Lua Script', 'Script Canvas', 'Camera',
                    'Actor', 'Anim Graph', 'Simple Motion',
                    'Box Shape', 'Sphere Shape', 'Capsule Shape',
                    'Cylinder Shape', 'Axis Aligned Box Shape', 'Spline',
                    'Audio Trigger', 'Comment',
                    'Net Binding', 'Network Transform',
                ]
                for cn in known:
                    tids = editor.EditorComponentAPIBus(
                        bus.Broadcast, 'FindComponentTypeIdsByEntityType', [cn], gt
                    )
                    if not tids:
                        continue
                    uid = str(tids[0])
                    if '00000000-0000-0000-0000-000000000000' in uid:
                        continue
                    has = editor.EditorComponentAPIBus(
                        bus.Broadcast, 'HasComponentOfType', eid, tids[0]
                    )
                    if has:
                        comp_id = ''
                        try:
                            out = editor.EditorComponentAPIBus(
                                bus.Broadcast, 'GetComponentOfType', eid, tids[0]
                            )
                            if hasattr(out, 'IsSuccess') and out.IsSuccess():
                                comp_id = str(out.GetValue())
                        except Exception:
                            pass
                        results.append({{'component_id': comp_id, 'type': cn}})
                print(json.dumps(results))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def add_component(entity_id: str, component_type: str) -> str:
        """Add a component to an entity.

        Args:
            entity_id: The entity ID to add the component to.
            component_type: Component type name (e.g. 'Mesh', 'PhysX Dynamic Rigid Body').
        """
        entity_id = _validate_entity_id(entity_id)
        component_type = _validate_component_type(component_type)
        params = json.dumps({"entity_id": entity_id, "component_type": component_type})
        script = textwrap.dedent(f"""\
            import azlmbr.editor as editor
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])
            comp_type = _params['component_type']

            type_ids = editor.EditorComponentAPIBus(
                bus.Broadcast, 'FindComponentTypeIdsByEntityType',
                [comp_type], entity.EntityType().Game
            )
            if not type_ids:
                print(f'Component type "{{comp_type}}" not found')
            else:
                tid = type_ids[0]
                # O3DE 2510+: AddComponentOfType (singular) via Broadcast
                try:
                    outcome = editor.EditorComponentAPIBus(
                        bus.Broadcast, 'AddComponentOfType', eid, tid
                    )
                    if hasattr(outcome, 'IsSuccess'):
                        if outcome.IsSuccess():
                            print(f'Added {{comp_type}} to {{eid}}')
                        else:
                            err = outcome.GetError() if hasattr(outcome, 'GetError') else 'unknown'
                            print(f'Failed to add {{comp_type}}: {{err}}')
                    else:
                        print(f'Added {{comp_type}} to {{eid}}')
                except Exception:
                    # Fallback: legacy AddComponentsOfType via Event bus
                    editor.EditorComponentAPIBus(
                        bus.Event, 'AddComponentsOfType', eid, type_ids
                    )
                    print(f'Added {{comp_type}} to {{eid}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def get_component_property(
        entity_id: str, component_type: str, property_path: str
    ) -> str:
        """Get a property value from a component on an entity.

        Args:
            entity_id: The entity ID.
            component_type: Component type name (e.g. 'Transform').
            property_path: Property path using '|' separator
                           (e.g. 'Controller|Configuration|Model Asset').
        """
        entity_id = _validate_entity_id(entity_id)
        component_type = _validate_component_type(component_type)
        params = json.dumps(
            {
                "entity_id": entity_id,
                "component_type": component_type,
                "property_path": property_path,
            }
        )
        script = textwrap.dedent(f"""\
            import azlmbr.editor as editor
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])

            value = None
            # O3DE 2510+: resolve EntityComponentIdPair, then get property
            type_ids = editor.EditorComponentAPIBus(
                bus.Broadcast, 'FindComponentTypeIdsByEntityType',
                [_params['component_type']], entity.EntityType().Game
            )
            try:
                if type_ids:
                    outcome = editor.EditorComponentAPIBus(
                        bus.Broadcast, 'GetComponentOfType', eid, type_ids[0]
                    )
                    if hasattr(outcome, 'IsSuccess') and outcome.IsSuccess():
                        pair = outcome.GetValue()
                        prop = editor.EditorComponentAPIBus(
                            bus.Broadcast, 'GetComponentProperty', pair,
                            _params['property_path']
                        )
                        if hasattr(prop, 'IsSuccess') and prop.IsSuccess():
                            value = prop.GetValue()
                        elif hasattr(prop, 'IsSuccess'):
                            value = None
                        else:
                            value = prop
                    else:
                        raise RuntimeError('GetComponentOfType failed')
                else:
                    raise RuntimeError('type not found')
            except Exception:
                # Fallback: legacy API with bare EntityId
                value = editor.EditorComponentAPIBus(
                    bus.Event, 'GetComponentProperty', eid,
                    _params['property_path']
                )
            print(json.dumps({{'property': _params['property_path'], 'value': str(value)}}))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def set_component_property(
        entity_id: str, component_type: str, property_path: str, value: str
    ) -> str:
        """Set a property value on a component.

        Args:
            entity_id: The entity ID.
            component_type: Component type name (e.g. 'Transform').
            property_path: Property path using '|' separator
                           (e.g. 'Controller|Configuration|Model Asset').
            value: The value to set (as a string — booleans as 'true'/'false',
                   numbers as their string representation).
        """
        entity_id = _validate_entity_id(entity_id)
        component_type = _validate_component_type(component_type)
        params = json.dumps(
            {
                "entity_id": entity_id,
                "component_type": component_type,
                "property_path": property_path,
                "value": value,
            }
        )
        script = textwrap.dedent(f"""\
            import azlmbr.editor as editor
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])
            raw = _params['value']

            # Attempt type coercion for common types
            if raw.lower() in ('true', 'false'):
                val = raw.lower() == 'true'
            else:
                try:
                    val = float(raw)
                    if val == int(val):
                        val = int(val)
                except ValueError:
                    val = raw

            # O3DE 2510+: resolve EntityComponentIdPair, then set property
            type_ids = editor.EditorComponentAPIBus(
                bus.Broadcast, 'FindComponentTypeIdsByEntityType',
                [_params['component_type']], entity.EntityType().Game
            )
            success = False
            try:
                if type_ids:
                    outcome = editor.EditorComponentAPIBus(
                        bus.Broadcast, 'GetComponentOfType', eid, type_ids[0]
                    )
                    if hasattr(outcome, 'IsSuccess') and outcome.IsSuccess():
                        pair = outcome.GetValue()
                        result = editor.EditorComponentAPIBus(
                            bus.Broadcast, 'SetComponentProperty', pair,
                            _params['property_path'], val
                        )
                        print(f'Set {{_params["property_path"]}} = {{val}} (result={{result}})')
                        success = True
            except Exception:
                pass

            if not success:
                # Fallback: legacy API with bare EntityId
                result = editor.EditorComponentAPIBus(
                    bus.Event, 'SetComponentProperty', eid,
                    _params['property_path'], val
                )
                print(f'Set {{_params["property_path"]}} = {{val}} (result={{result}})')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def assign_asset(
        entity_id: str, component_type: str, property_path: str, asset_path: str
    ) -> str:
        """Assign an asset to a component property by resolving the asset path."""
        entity_id = _validate_entity_id(entity_id)
        component_type = _validate_component_type(component_type)
        asset_path = asset_path.strip()
        if not asset_path:
            raise ValueError("asset_path cannot be empty.")
        if ".." in asset_path:
            raise ValueError(f"asset_path must not contain '..': {asset_path!r}")
        params = json.dumps(
            {
                "entity_id": entity_id,
                "component_type": component_type,
                "property_path": property_path,
                "asset_path": asset_path,
            }
        )
        script = textwrap.dedent(f"""\
            import azlmbr.editor as editor
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])
            comp_type = _params['component_type']
            prop_path = _params['property_path']
            asset_path = _params['asset_path']

            # Resolve the asset ID from the project-relative path
            try:
                import azlmbr.asset as asset
                asset_id = asset.AssetCatalogRequestBus(
                    bus.Broadcast, 'GetAssetIdByPath',
                    asset_path, azlmbr.math.Uuid(), False
                )
            except Exception:
                try:
                    asset_id = asset.AssetCatalogRequestBus(
                        bus.Broadcast, 'GetAssetIdByPath',
                        asset_path
                    )
                except Exception as e:
                    print(f'Failed to resolve asset path: {{e}}')
                    asset_id = None

            if asset_id is None:
                print(f'Asset not found: {{asset_path}}')
            else:
                asset_ref = str(asset_id)
                type_ids = editor.EditorComponentAPIBus(
                    bus.Broadcast, 'FindComponentTypeIdsByEntityType',
                    [comp_type], entity.EntityType().Game
                )
                success = False
                try:
                    if type_ids:
                        outcome = editor.EditorComponentAPIBus(
                            bus.Broadcast, 'GetComponentOfType', eid, type_ids[0]
                        )
                        if hasattr(outcome, 'IsSuccess') and outcome.IsSuccess():
                            pair = outcome.GetValue()
                            result = editor.EditorComponentAPIBus(
                                bus.Broadcast, 'SetComponentProperty', pair,
                                prop_path, asset_ref
                            )
                            print(f'Assigned asset {{asset_path}} to '
                                  f'{{prop_path}} (result={{result}})')
                            success = True
                except Exception:
                    pass

                if not success:
                    result = editor.EditorComponentAPIBus(
                        bus.Event, 'SetComponentProperty', eid,
                        prop_path, asset_ref
                    )
                    print(f'Assigned asset {{asset_path}} to {{prop_path}} (result={{result}})')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def remove_component(entity_id: str, component_type: str) -> str:
        """Remove a component from an entity."""
        entity_id = _validate_entity_id(entity_id)
        component_type = _validate_component_type(component_type)
        params = json.dumps({"entity_id": entity_id, "component_type": component_type})
        script = textwrap.dedent(f"""\
            import azlmbr.editor as editor
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])
            comp_type = _params['component_type']

            type_ids = editor.EditorComponentAPIBus(
                bus.Broadcast, 'FindComponentTypeIdsByEntityType',
                [comp_type], entity.EntityType().Game
            )
            if not type_ids:
                print(f'Component type "{{comp_type}}" not found')
            else:
                tid = type_ids[0]
                try:
                    outcome = editor.EditorComponentAPIBus(
                        bus.Broadcast, 'RemoveComponentOfType', eid, tid
                    )
                    if hasattr(outcome, 'IsSuccess'):
                        if outcome.IsSuccess():
                            print(f'Removed {{comp_type}} from {{eid}}')
                        else:
                            err = outcome.GetError() if hasattr(outcome, 'GetError') else 'unknown'
                            print(f'Failed to remove {{comp_type}}: {{err}}')
                    else:
                        print(f'Removed {{comp_type}} from {{eid}}')
                except Exception:
                    try:
                        comp = editor.EditorComponentAPIBus(
                            bus.Event, 'GetComponentOfType', eid, tid
                        )
                        editor.EditorComponentAPIBus(bus.Event, 'RemoveComponent', comp)
                        print(f'Removed {{comp_type}} from {{eid}}')
                    except Exception as e:
                        print(f'Failed to remove {{comp_type}}: {{e}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def set_transform(
        entity_id: str,
        position: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
    ) -> str:
        """Set the world transform of an entity (only provided components are changed)."""
        entity_id = _validate_entity_id(entity_id)
        pos = _validate_vec3(position, "position") if position is not None else None
        scl = _validate_vec3(scale, "scale") if scale is not None else None
        rot = None
        if rotation is not None:
            if not isinstance(rotation, (list, tuple)):
                raise ValueError("rotation must be a list or tuple of 4 numbers.")
            if len(rotation) != 4:
                raise ValueError(
                    f"rotation must have exactly 4 elements (quaternion), got {len(rotation)}."
                )
            try:
                rot = [float(v) for v in rotation]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"rotation must contain only numbers, got {rotation!r}.") from exc

        params = json.dumps(
            {"entity_id": entity_id, "position": pos, "rotation": rot, "scale": scl}
        )
        script = textwrap.dedent(f"""\
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import azlmbr.components as components
            import azlmbr.math as math
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])

            pos = _params['position']
            rot = _params['rotation']
            scl = _params['scale']

            current = components.TransformBus(bus.Event, 'GetWorldTM', eid)
            if current is None:
                current = math.Transform_CreateIdentity()

            if pos is not None:
                t_pos = math.Vector3(float(pos[0]), float(pos[1]), float(pos[2]))
            else:
                t_pos = current.translation

            if rot is not None:
                t_rot = math.Quaternion(float(rot[0]), float(rot[1]), float(rot[2]), float(rot[3]))
            else:
                t_rot = current.rotation

            if scl is not None:
                t_scl = math.Vector3(float(scl[0]), float(scl[1]), float(scl[2]))
                rot_m3 = math.Matrix3x3_CreateFromQuaternion(t_rot)
                scale_m = math.Matrix3x3_CreateDiagonal(t_scl)
                try:
                    final_m3 = math.Matrix3x3_Multiply(scale_m, rot_m3)
                except Exception:
                    b0 = rot_m3.BasisX
                    b1 = rot_m3.BasisY
                    b2 = rot_m3.BasisZ
                    final_m3 = math.Matrix3x3_CreateFromColumns(
                        math.Vector3(b0.x * t_scl.x, b0.y * t_scl.x, b0.z * t_scl.x),
                        math.Vector3(b1.x * t_scl.y, b1.y * t_scl.y, b1.z * t_scl.y),
                        math.Vector3(b2.x * t_scl.z, b2.y * t_scl.z, b2.z * t_scl.z),
                    )
                new_tm = math.Transform_CreateFromMatrix3x3AndTranslation(final_m3, t_pos)
            else:
                new_tm = math.Transform_CreateFromQuaternionAndTranslation(t_rot, t_pos)

            components.TransformBus(bus.Event, 'SetWorldTM', eid, new_tm)
            print(f'Transform set for entity {{eid}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def get_transform(entity_id: str) -> str:
        """Get the world transform of an entity."""
        entity_id = _validate_entity_id(entity_id)
        params = json.dumps({"entity_id": entity_id})
        script = textwrap.dedent(f"""\
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import azlmbr.components as components
            import azlmbr.math as math
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])

            tm = components.TransformBus(bus.Event, 'GetWorldTM', eid)
            if tm is None:
                print(json.dumps({{'error': 'Could not get transform'}}))
            else:
                pos = tm.translation
                rot = tm.rotation
                try:
                    m3 = math.Matrix3x3_CreateFromTransform(tm)
                    b0 = m3.BasisX
                    b1 = m3.BasisY
                    b2 = m3.BasisZ
                    import math as _math
                    scl = [_math.sqrt(b0.x**2 + b0.y**2 + b0.z**2),
                           _math.sqrt(b1.x**2 + b1.y**2 + b1.z**2),
                           _math.sqrt(b2.x**2 + b2.y**2 + b2.z**2)]
                except Exception:
                    scl = [1.0, 1.0, 1.0]
                result = {{
                    'position': [pos.x, pos.y, pos.z],
                    'rotation': [rot.x, rot.y, rot.z, rot.w],
                    'scale': scl,
                }}
                print(json.dumps(result))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def set_parent(entity_id: str, parent_id: str) -> str:
        """Set the parent of an entity (reparent in the hierarchy)."""
        entity_id = _validate_entity_id(entity_id)
        parent_id = _validate_entity_id(parent_id)
        params = json.dumps({"entity_id": entity_id, "parent_id": parent_id})
        script = textwrap.dedent(f"""\
            import azlmbr.editor as editor
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import azlmbr.components as components
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])
            pid = _resolve_entity_id(_params['parent_id'])

            try:
                result = editor.ToolsApplicationRequestBus(
                    bus.Broadcast, 'SetEntityParent', eid, pid
                )
                print(f'Set parent of {{eid}} to {{pid}} (result={{result}})')
            except Exception as e:
                components.TransformBus(bus.Event, 'SetParent', eid, pid)
                print(f'Set parent of {{eid}} to {{pid}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def run_console_command(command: str) -> str:
        """Execute an O3DE console command in the running editor."""
        command = _validate_console_command(command)
        params = json.dumps({"command": command})
        script = textwrap.dedent(f"""\
            import json

            _params = json.loads({params!r})
            cmd = _params['command']
            try:
                import azlmbr.legacy.general as general
                general.run_console(cmd)
                print(f'Executed: {{cmd}}')
            except Exception as e:
                print(f'Failed to execute command: {{e}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def get_cvar(name: str) -> str:
        """Get the value of an O3DE console variable (CVAR)."""
        name = _validate_console_command(name)
        params = json.dumps({"name": name})
        script = textwrap.dedent(f"""\
            import json

            _params = json.loads({params!r})
            cvar_name = _params['name']

            value = None
            try:
                import azlmbr.legacy.general as general
                value = general.get_cvar(cvar_name)
            except Exception:
                try:
                    import io, contextlib
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        general.run_console(cvar_name)
                    output = buf.getvalue().strip()
                    for line in output.splitlines():
                        if '=' in line:
                            value = line.split('=', 1)[1].strip()
                            break
                    if value is None:
                        value = output
                except Exception as e:
                    value = f'Error: {{e}}'

            print(json.dumps({{'name': cvar_name, 'value': value}}))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def set_cvar(name: str, value: str) -> str:
        """Set the value of an O3DE console variable (CVAR)."""
        name = _validate_console_command(name)
        value = value.strip()
        if not value:
            raise ValueError("CVAR value cannot be empty.")
        combined = f"{name} {value}"
        _validate_console_command(combined)
        params = json.dumps({"name": name, "value": value})
        script = textwrap.dedent(f"""\
            import azlmbr.legacy.general as general
            import json

            _params = json.loads({params!r})
            cvar_name = _params['name']
            cvar_value = _params['value']
            cmd = f'{{cvar_name}}={{cvar_value}}'
            try:
                general.run_console(cmd)
                print(f'Set {{cvar_name}} = {{cvar_value}}')
            except Exception as e:
                print(f'Failed to set {{cvar_name}}: {{e}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def load_level(level_path: str) -> str:
        """Open a level in the O3DE Editor.

        Args:
            level_path: Path to the level relative to the project
                        (e.g. 'Levels/MyLevel').
        """
        params = json.dumps({"level_path": level_path})
        script = textwrap.dedent(f"""\
            import azlmbr.legacy.general as general
            import json

            _params = json.loads({params!r})
            _name = _params['level_path']
            for _prefix in ('Levels/', 'levels/'):
                if _name.startswith(_prefix):
                    _name = _name[len(_prefix):]
                    break
            _ok = general.open_level_no_prompt(_name)
            _actual = general.get_current_level_name()
            if _ok:
                print(f"Opened level: {{_actual}}")
            else:
                print(f"ERROR: could not open level {{_name!r}}; still on {{_actual!r}}")
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def get_level_info() -> str:
        """Get information about the currently loaded level.

        Returns:
            JSON object with 'level_name' and 'level_path' fields.
        """
        script = textwrap.dedent("""\
            import azlmbr.legacy.general as general
            import json

            info = {
                'level_name': general.get_current_level_name(),
                'level_path': general.get_current_level_path(),
            }
            print(json.dumps(info))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def save_level() -> str:
        """Save the currently open level."""
        script = textwrap.dedent("""\
            import azlmbr.legacy.general as general
            general.save_level()
            print('Level saved')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def create_level(name: str) -> str:
        """Create a new empty level in the current O3DE project."""
        name = name.strip()
        if not name:
            raise ValueError("Level name cannot be empty.")
        if not re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", name):
            raise ValueError(
                f"Invalid level name: {name!r}. "
                "Expected alphanumeric characters, hyphens, or underscores, "
                "starting with a letter."
            )
        params = json.dumps({"name": name})
        script = textwrap.dedent(f"""\
            import azlmbr.legacy.general as general
            import json

            _params = json.loads({params!r})
            _name = _params['name']
            try:
                _ok = general.create_level_no_prompt(_name, 0)
                if _ok:
                    print(f'Created and opened level: {{_name}}')
                else:
                    _actual = general.get_current_level_name()
                    print(f'ERROR: could not create level {{_name!r}}; '
                          f'still on {{_actual!r}}')
            except Exception as e:
                print(f'ERROR: failed to create level {{_name!r}}: {{e}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def list_levels(project_path: str | None = None) -> str:
        """List all levels available in an O3DE project."""
        if project_path:
            proj = Path(project_path)
        else:
            env_path = os.environ.get("O3DE_PROJECT_PATH", "").strip()
            if env_path:
                proj = Path(env_path)
            else:
                from o3de_mcp.utils.o3de import list_registered_projects

                projects = list_registered_projects()
                if len(projects) == 1:
                    proj = Path(projects[0]["path"])
                elif not projects:
                    return json.dumps(
                        {"error": "No project path provided and no registered project found."}
                    )
                else:
                    return json.dumps(
                        {
                            "error": (
                                "Multiple projects registered. "
                                "Pass project_path explicitly or set O3DE_PROJECT_PATH."
                            )
                        }
                    )

        levels_dir = proj / "Levels"
        if not levels_dir.is_dir():
            return json.dumps(
                {"error": f"No Levels/ directory found at {levels_dir}", "levels": []}
            )

        levels = []
        for entry in sorted(levels_dir.iterdir()):
            if entry.is_dir():
                has_ly = any(entry.glob("*.ly"))
                has_prefab = any(entry.glob("level.prefab")) or any(entry.glob("*.prefab"))
                if has_ly or has_prefab:
                    levels.append(entry.name)

        return json.dumps({"levels": levels, "project": str(proj)})

    @mcp.tool()
    async def enter_game_mode() -> str:
        """Enter game mode (play-in-editor) in the O3DE Editor."""
        script = textwrap.dedent("""\
            import azlmbr.legacy.general as general
            general.enter_game_mode()
            print('Entered game mode')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def exit_game_mode() -> str:
        """Exit game mode and return to edit mode."""
        script = textwrap.dedent("""\
            import azlmbr.legacy.general as general
            general.exit_game_mode()
            print('Exited game mode')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def undo() -> str:
        """Undo the last editor action."""
        script = textwrap.dedent("""\
            import azlmbr.legacy.general as general
            general.undo()
            print('Undo performed')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def redo() -> str:
        """Redo the last undone editor action."""
        script = textwrap.dedent("""\
            import azlmbr.legacy.general as general
            general.redo()
            print('Redo performed')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def get_viewport_camera() -> str:
        """Get the position and rotation of the active editor viewport camera.

        Returns JSON with ``position`` (3 floats) and ``rotation`` (3 Euler
        angles in degrees). FOV is not available via the Python bindings.
        """
        script = textwrap.dedent("""\
            import azlmbr.legacy.general as general
            import json

            result = {}
            try:
                pos = general.get_current_view_position()
                if pos is not None:
                    result['position'] = [pos.x, pos.y, pos.z]
            except Exception as e:
                result['error'] = str(e)

            try:
                rot = general.get_current_view_rotation()
                if rot is not None:
                    result['rotation'] = [rot.x, rot.y, rot.z]
            except Exception as e:
                if 'error' not in result:
                    result['error'] = str(e)

            print(json.dumps(result))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def set_viewport_camera(
        position: list[float] | None = None,
        rotation: list[float] | None = None,
    ) -> str:
        """Set the active editor viewport camera transform."""
        pos = _validate_vec3(position, "position") if position is not None else None
        rot = None
        if rotation is not None:
            if not isinstance(rotation, (list, tuple)):
                raise ValueError("rotation must be a list or tuple of 3 numbers (Euler angles).")
            if len(rotation) != 3:
                raise ValueError(
                    f"rotation must have exactly 3 elements (Euler angles), got {len(rotation)}."
                )
            try:
                rot = [float(v) for v in rotation]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"rotation must contain only numbers, got {rotation!r}.") from exc

        params = json.dumps({"position": pos, "rotation": rot})
        script = textwrap.dedent(f"""\
            import azlmbr.legacy.general as general
            import json

            _params = json.loads({params!r})
            pos = _params['position']
            rot = _params['rotation']

            try:
                if pos is not None:
                    general.set_current_view_position(float(pos[0]), float(pos[1]), float(pos[2]))
                if rot is not None:
                    general.set_current_view_rotation(float(rot[0]), float(rot[1]), float(rot[2]))
                print('Viewport camera set')
            except Exception as e:
                print(f'Failed to set viewport camera: {{e}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def focus_entity(entity_id: str) -> str:
        """Focus the viewport camera on an entity."""
        entity_id = _validate_entity_id(entity_id)
        params = json.dumps({"entity_id": entity_id})
        script = textwrap.dedent(f"""\
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])
            try:
                import azlmbr.editor as editor_mod
                editor_mod.EditorCameraRequestBus(bus.Event, 'SetViewFromEntityPerspective', eid)
                print(f'Focused on entity {{eid}}')
            except Exception as e:
                print(f'Failed to focus on entity: {{e}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def capture_viewport(
        output_path: str,
        width: int | None = None,
        height: int | None = None,
    ) -> str:
        """Capture a screenshot of the editor viewport.

        Tries PySide6 widget grab first (captures the viewport widget
        including UI overlays). Falls back to ``azlmbr.atom``
        ``FrameCaptureRequestBus.CaptureScreenshot`` which captures the
        actual rendered frame and works on platforms where PySide6 is not
        importable in the editor's embedded interpreter.

        Args:
            output_path: File path for the screenshot (.png, .jpg, .jpeg, .bmp, or .tga).
            width: Optional width to scale the screenshot to (PySide6 path only).
            height: Optional height to scale the screenshot to (PySide6 path only).
        """
        output_path = output_path.strip()
        if not output_path:
            raise ValueError("output_path cannot be empty.")
        valid_extensions = (".png", ".jpg", ".jpeg", ".bmp", ".tga")
        if not output_path.lower().endswith(valid_extensions):
            raise ValueError(f"output_path must end in one of {valid_extensions}: {output_path!r}")

        params = json.dumps({"output_path": output_path, "width": width, "height": height})
        script = textwrap.dedent(f"""\
            import json
            import os

            _params = json.loads({params!r})
            _path = _params['output_path']
            _w = _params['width']
            _h = _params['height']

            def _try_pyside6():
                from PySide6 import QtWidgets, QtCore
                app = QtWidgets.QApplication.instance()
                if not app:
                    return False, 'No QApplication instance'
                main_win = None
                for w in app.topLevelWidgets():
                    if isinstance(w, QtWidgets.QMainWindow) and w.isVisible():
                        main_win = w
                        break
                if not main_win:
                    return False, 'No main window'
                viewport = main_win.findChild(QtWidgets.QWidget, 'ViewportUiOverlay')
                if viewport is None:
                    viewport = main_win
                pixmap = viewport.grab()
                if pixmap.isNull():
                    return False, 'Pixmap is null'
                if _w is not None and _h is not None:
                    pixmap = pixmap.scaled(
                        _w, _h,
                        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                        QtCore.Qt.TransformationMode.SmoothTransformation,
                    )
                pixmap.save(_path, 'PNG')
                if os.path.exists(_path):
                    size = os.path.getsize(_path)
                    print(f'Screenshot saved to {{_path}} '
                          f'({{size}} bytes, '
                          f'{{pixmap.width()}}x{{pixmap.height()}})')
                    return True, ''
                return False, f'File was not created at {{_path}}'

            def _try_atom_frame_capture():
                import azlmbr.atom
                import azlmbr.bus
                import azlmbr.legacy.general as general

                if not azlmbr.atom.FrameCaptureRequestBus(
                    azlmbr.bus.Broadcast, 'CanCapture'
                ):
                    return False, 'Frame capture is not available (null renderer?)'

                outcome = azlmbr.atom.FrameCaptureRequestBus(
                    azlmbr.bus.Broadcast, 'CaptureScreenshot', _path
                )
                if not outcome.IsSuccess():
                    err = outcome.GetError()
                    msg = err.error_message if hasattr(err, 'error_message') else str(err)
                    return False, f'CaptureScreenshot failed: {{msg}}'

                capture_id = outcome.GetValue()
                done = [False]
                success = [False]
                info_str = ['']

                handler = azlmbr.atom.FrameCaptureNotificationBusHandler()
                handler.connect(capture_id)

                def _on_finished(parameters):
                    result_code, info = parameters[0], parameters[1]
                    if result_code == azlmbr.atom.FrameCaptureResult_Success:
                        success[0] = True
                    info_str[0] = str(info)
                    done[0] = True

                handler.add_callback('OnFrameCaptureFinished', _on_finished)

                max_frames = 60
                for _ in range(max_frames):
                    if done[0]:
                        break
                    general.idle_wait_frames(1)

                if not done[0]:
                    handler.disconnect()
                    return False, 'Timed out waiting for frame capture'

                handler.disconnect()
                if success[0] and os.path.exists(_path):
                    size = os.path.getsize(_path)
                    print(f'Screenshot saved to {{_path}} ({{size}} bytes)')
                    return True, ''
                return False, f'Frame capture result: {{info_str[0]}}'

            pyside_ok = False
            try:
                ok, msg = _try_pyside6()
                pyside_ok = ok
            except ImportError:
                pass
            except Exception:
                pass

            if not pyside_ok:
                try:
                    ok, msg = _try_atom_frame_capture()
                    if not ok:
                        print(f'Failed to capture viewport: {{msg}}')
                except Exception as e:
                    print(f'Failed to capture viewport: {{e}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def instantiate_prefab(
        prefab_path: str,
        position: list[float] | None = None,
        parent_id: str | None = None,
    ) -> str:
        """Instantiate a prefab in the current level."""
        prefab_path = _validate_prefab_path(prefab_path)
        pos = _validate_vec3(position, "position") if position is not None else [0.0, 0.0, 0.0]
        if parent_id is not None:
            parent_id = _validate_entity_id(parent_id)
        params = json.dumps({"prefab_path": prefab_path, "position": pos, "parent_id": parent_id})
        script = textwrap.dedent(f"""\
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import azlmbr.math as math
            import azlmbr.prefab as prefab
            import json

            _params = json.loads({params!r})
            _path = _params['prefab_path']
            _pos = _params['position']
            _parent_id = _params['parent_id']

            if _parent_id:
                parent = entity.EntityId(_parent_id)
            else:
                parent = entity.EntityId()

            pos_vec = math.Vector3(float(_pos[0]), float(_pos[1]), float(_pos[2]))

            try:
                result = prefab.PrefabPublicRequestBus(
                    bus.Broadcast, 'InstantiatePrefab',
                    _path, parent, pos_vec
                )
                if hasattr(result, 'IsSuccess'):
                    if result.IsSuccess():
                        eid = result.GetValue()
                        print(f'Instantiated prefab: {{_path}} (entity={{eid}})')
                    else:
                        err = result.GetError() if hasattr(result, 'GetError') else 'unknown'
                        print(f'Failed to instantiate prefab: {{err}}')
                else:
                    print(f'Instantiated prefab: {{_path}}')
            except Exception as e:
                print(f'Failed to instantiate prefab: {{e}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def create_prefab_from_entity(entity_id: str, prefab_path: str) -> str:
        """Create a prefab file from an existing entity."""
        entity_id = _validate_entity_id(entity_id)
        prefab_path = _validate_prefab_path(prefab_path)
        params = json.dumps({"entity_id": entity_id, "prefab_path": prefab_path})
        script = textwrap.dedent(f"""\
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import azlmbr.prefab as prefab
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])
            _path = _params['prefab_path']

            try:
                result = prefab.PrefabPublicRequestBus(
                    bus.Broadcast, 'CreatePrefabInMemory',
                    [eid], _path
                )
                if hasattr(result, 'IsSuccess'):
                    if result.IsSuccess():
                        print(f'Created prefab: {{_path}} from entity {{eid}}')
                    else:
                        err = result.GetError() if hasattr(result, 'GetError') else 'unknown'
                        print(f'Failed to create prefab: {{err}}')
                else:
                    print(f'Created prefab: {{_path}} from entity {{eid}}')
            except Exception as e:
                print(f'Failed to create prefab: {{e}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def save_prefab(entity_id: str) -> str:
        """Save a prefab instance (propagate entity changes to the prefab file)."""
        entity_id = _validate_entity_id(entity_id)
        params = json.dumps({"entity_id": entity_id})
        script = textwrap.dedent(f"""\
            import azlmbr.bus as bus
            import azlmbr.entity as entity
            import azlmbr.prefab as prefab
            import json

            _params = json.loads({params!r})
            eid = _resolve_entity_id(_params['entity_id'])

            try:
                prefab.PrefabPublicRequestBus(
                    bus.Broadcast, 'SavePrefabToFile', eid
                )
                print(f'Saved prefab instance: {{eid}}')
            except Exception as e:
                print(f'Failed to save prefab: {{e}}')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def begin_session() -> str:
        """Begin a persistent Python session in the O3DE editor."""
        session_id = str(uuid.uuid4())[:8]
        params = json.dumps({"session_id": session_id})
        script = textwrap.dedent(f"""\
            import json

            _params = json.loads({params!r})
            _sid = _params['session_id']
            if not hasattr(__import__('__main__'), '_o3de_sessions'):
                import __main__
                __main__._o3de_sessions = {{}}
            __main__._o3de_sessions[_sid] = {{}}
            print(json.dumps({{'session_id': _sid}}))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def exec_in_session(session_id: str, script: str) -> str:
        """Execute Python code in a persistent session."""
        session_id = session_id.strip()
        if not session_id:
            raise ValueError("session_id cannot be empty.")
        if not script.strip():
            raise ValueError("script cannot be empty.")
        params = json.dumps({"session_id": session_id, "script": script})
        wrapper = textwrap.dedent(f"""\
            import json
            import __main__

            _params = json.loads({params!r})
            _sid = _params['session_id']
            _script = _params['script']

            if not hasattr(__main__, '_o3de_sessions'):
                print(json.dumps({{'error': 'No sessions exist. Call begin_session first.'}}))
            elif _sid not in __main__._o3de_sessions:
                print(json.dumps(
                    {{'error': f'Session {{_sid}} not found. Call begin_session first.'}}
                ))
            else:
                _ns = __main__._o3de_sessions[_sid]
                try:
                    exec(_script, _ns, _ns)
                except Exception as e:
                    print(json.dumps({{'error': str(e)}}))
        """)
        return await _async_run_editor_script(wrapper)

    @mcp.tool()
    async def end_session(session_id: str) -> str:
        """End a persistent Python session and clean up its namespace."""
        session_id = session_id.strip()
        if not session_id:
            raise ValueError("session_id cannot be empty.")
        params = json.dumps({"session_id": session_id})
        script = textwrap.dedent(f"""\
            import json
            import __main__

            _params = json.loads({params!r})
            _sid = _params['session_id']
            if hasattr(__main__, '_o3de_sessions') and _sid in __main__._o3de_sessions:
                del __main__._o3de_sessions[_sid]
                print(f'Session {{_sid}} ended')
            else:
                print(f'Session {{_sid}} not found (already ended)')
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def get_session_vars(session_id: str) -> str:
        """List the variable names in a persistent Python session."""
        session_id = session_id.strip()
        if not session_id:
            raise ValueError("session_id cannot be empty.")
        params = json.dumps({"session_id": session_id})
        script = textwrap.dedent(f"""\
            import json
            import __main__

            _params = json.loads({params!r})
            _sid = _params['session_id']
            if not hasattr(__main__, '_o3de_sessions') or _sid not in __main__._o3de_sessions:
                print(json.dumps({{'error': f'Session {{_sid}} not found.'}}))
            else:
                _ns = __main__._o3de_sessions[_sid]
                _vars = [k for k in _ns.keys() if not k.startswith('__') and k != '__builtins__']
                print(json.dumps({{'vars': _vars, 'count': len(_vars)}}))
        """)
        return await _async_run_editor_script(script)
