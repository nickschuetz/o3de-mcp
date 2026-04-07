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
  O3DE_EDITOR_HOST       — editor host (default: 127.0.0.1)
  O3DE_EDITOR_PORT       — editor port (default: 4600)
  O3DE_EDITOR_TLS        — enable TLS (default: 0)
  O3DE_EDITOR_TLS_VERIFY — verify TLS cert (default: 0)
  O3DE_EDITOR_TLS_CA     — path to CA cert for verification
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
    timeout: float = 10.0,
) -> str:
    """Send a command to the O3DE Editor and return the response.

    Creates a new TCP connection for each call.  This synchronous variant is
    kept primarily for test convenience; the async path via
    :class:`_EditorConnectionPool` is used by all MCP tools.
    """
    host = host or _get_editor_host()
    port = port or _get_editor_port()
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

    _FAST_FAIL_WINDOW = 5.0  # seconds

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._host: str | None = None
        self._port: int | None = None
        self._lock = asyncio.Lock()
        self._last_failure_time: float | None = None
        self._protocol: int = _PROTO_UNKNOWN

    async def send_script(
        self,
        script: str,
        host: str | None = None,
        port: int | None = None,
        timeout: float = 10.0,
    ) -> str:
        """Encode and send a Python script, returning the output text."""
        host = host or _get_editor_host()
        port = port or _get_editor_port()

        async with self._lock:
            # Fast-fail if we recently failed to connect
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
                reader, writer = await self._ensure_connected(host, port, timeout)

                if self._protocol == _PROTO_AGENT_SERVER:
                    return await self._send_framed_script(reader, writer, script, timeout)
                else:
                    return await self._send_legacy_script(reader, writer, script, timeout)

            except (
                ConnectionRefusedError,
                TimeoutError,
                asyncio.TimeoutError,
                OSError,
            ) as exc:
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
        self, host: str, port: int, timeout: float
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        # Reconnect if target changed or connection is stale
        if (
            self._writer is not None
            and not self._writer.is_closing()
            and self._host == host
            and self._port == port
        ):
            return self._reader, self._writer  # type: ignore[return-value]

        await self._close()

        ssl_ctx = _get_tls_context()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl_ctx), timeout=timeout
        )
        self._reader = reader
        self._writer = writer
        self._host = host
        self._port = port

        # Auto-detect protocol by sending a framed ping
        self._protocol = await self._detect_protocol(reader, writer)
        logger.info(
            "Connected to %s:%d (protocol=%s, tls=%s)",
            host,
            port,
            "agent_server" if self._protocol == _PROTO_AGENT_SERVER else "legacy",
            "yes" if ssl_ctx else "no",
        )

        return reader, writer

    async def _detect_protocol(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> int:
        """Detect whether the server speaks AgentServer or legacy protocol.

        Sends a framed ``ping`` request. If a valid framed JSON response
        with ``"status": "ok"`` comes back within 2 seconds, the server
        is an AgentServer. Otherwise, fall back to legacy mode.
        """
        try:
            ping_bytes = _build_framed_request("ping")
            writer.write(ping_bytes)
            await writer.drain()
            response = await _async_recv_framed(reader, timeout=2.0)
            if isinstance(response, dict) and response.get("status") == "ok":
                return _PROTO_AGENT_SERVER
        except Exception:
            # Any failure means not an AgentServer — reconnect for legacy
            await self._close()
            host = self._host or _get_editor_host()
            port = self._port or _get_editor_port()
            ssl_ctx = _get_tls_context()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, ssl=ssl_ctx), timeout=5.0
            )
            self._reader = reader
            self._writer = writer

        return _PROTO_LEGACY

    async def _close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
            self._reader = None
            self._writer = None
            self._host = None
            self._port = None
            self._protocol = _PROTO_UNKNOWN


# Module-level pool instance shared by all tools
_pool = _EditorConnectionPool()


# ---------------------------------------------------------------------------
# Script execution helpers
# ---------------------------------------------------------------------------


async def _async_run_editor_script(script: str) -> str:
    """Encode a Python script and send it to the editor via the pool."""
    return await _pool.send_script(script)


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
    async def run_editor_python(script: str) -> str:
        """Execute a Python script inside the running O3DE Editor.

        The script runs in the editor's embedded Python interpreter and has
        access to the full azlmbr (EditorPythonBindings) API. Use this for
        custom editor automation that isn't covered by other tools.

        Args:
            script: Python code to execute. Has access to azlmbr modules.
        """
        return await _async_run_editor_script(script)

    # --- Entity management ---

    @mcp.tool()
    async def list_entities() -> str:
        """List all entities in the currently open O3DE level.

        Returns a JSON array of objects with 'id' and 'name' fields.
        """
        script = textwrap.dedent("""\
            import azlmbr.entity as entity
            import azlmbr.bus as bus
            import json

            search_filter = entity.SearchFilter()
            search_filter.names = ['*']
            entity_ids = entity.SearchBus(bus.Broadcast, 'SearchEntities', search_filter)

            results = []
            for eid in entity_ids:
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
                parent = azlmbr.entity.EntityId(_parent_id_str)
            else:
                parent = azlmbr.entity.EntityId()

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
            eid = entity.EntityId(_params['entity_id'])
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
            eid = entity.EntityId(_params['entity_id'])
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
            eid = entity.EntityId(_params['entity_id'])
            components = editor.EditorComponentAPIBus(bus.Event, 'GetComponentsOfEntity', eid)

            results = []
            for comp in components:
                type_name = editor.EditorComponentAPIBus(bus.Event, 'GetComponentName', comp)
                results.append({{'component_id': str(comp), 'type': type_name}})
            print(json.dumps(results))
        """)
        return await _async_run_editor_script(script)

    @mcp.tool()
    async def add_component(entity_id: str, component_type: str) -> str:
        """Add a component to an entity.

        Args:
            entity_id: The entity ID to add the component to.
            component_type: Component type name (e.g. 'Mesh', 'PhysX Rigid Body').
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
            eid = entity.EntityId(_params['entity_id'])
            comp_type = _params['component_type']

            type_ids = editor.EditorComponentAPIBus(
                bus.Broadcast, 'FindComponentTypeIdsByEntityType',
                [comp_type], entity.EntityType().Game
            )
            if type_ids:
                editor.EditorComponentAPIBus(bus.Event, 'AddComponentsOfType', eid, type_ids)
                print(f'Added {{type_ids[0]}} to {{eid}}')
            else:
                print(f'Component type "{{comp_type}}" not found')
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
                           (e.g. 'Transform|Translate').
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
            eid = entity.EntityId(_params['entity_id'])
            value = editor.EditorComponentAPIBus(
                bus.Event, 'GetComponentProperty', eid, _params['property_path']
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
                           (e.g. 'PhysX Collider|IsTrigger').
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
            eid = entity.EntityId(_params['entity_id'])
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

            result = editor.EditorComponentAPIBus(
                bus.Event, 'SetComponentProperty', eid, _params['property_path'], val
            )
            print(f'Set {{_params["property_path"]}} = {{val}} (result={{result}})')
        """)
        return await _async_run_editor_script(script)

    # --- Level management ---

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
            general.open_level(_params['level_path'])
            print(f"Opened level: {{_params['level_path']}}")
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

    # --- Editor state ---

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
