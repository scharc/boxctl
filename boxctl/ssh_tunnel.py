# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""SSH-based tunnel implementation using AsyncSSH.

This module provides the complete container-host communication system:
- Control channel: JSON messages over SSH session (notifications, streaming, etc.)
- Port forwarding: Native SSH -L/-R forwards for data tunnels

Architecture:
- Host runs SSHTunnelServer (AsyncSSH server on Unix socket)
- Container runs SSHTunnelClient (AsyncSSH client)
- Single SSH connection handles all communication
- Control messages use length-prefixed JSON framing

Protocol:
- All messages use envelope: {kind, type, id?, ts, payload}
- kind: "request" (expects response), "response", "event" (fire-and-forget)
- Framing: 4-byte big-endian length prefix + UTF-8 JSON
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    import asyncssh

    ASYNCSSH_AVAILABLE = True
    _SSHServerBase = asyncssh.SSHServer
except ImportError:
    asyncssh = None
    ASYNCSSH_AVAILABLE = False
    _SSHServerBase = object

from boxctl.paths import ContainerDefaults
from boxctl.utils.logging import get_daemon_logger

logger = get_daemon_logger("ssh-tunnel")

# Constants
MIN_ALLOWED_PORT = 1024  # Block privileged ports
SSH_KEEPALIVE_INTERVAL = 15  # seconds
SSH_KEEPALIVE_COUNT_MAX = 3  # missed keepalives before disconnect
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10MB max message
CONTROL_PROTOCOL_VERSION = "2.0"


def check_asyncssh_available() -> bool:
    """Check if asyncssh is available."""
    return ASYNCSSH_AVAILABLE


@dataclass
class PortForwardConfig:
    """Configuration for a port forward."""

    name: str
    host_port: int
    container_port: int
    direction: str  # "local" (container→host) or "remote" (host→container)
    bind_addresses: List[str] = field(default_factory=lambda: ["127.0.0.1"])


@dataclass
class ContainerConnection:
    """Tracks an active container SSH connection."""

    container: str
    connected_at: float
    connection: Any  # asyncssh.SSHServerConnection
    control_channel: Optional["ControlChannel"] = None
    control_task: Optional[asyncio.Task] = None  # Control channel loop task
    local_forwards: List[Dict[str, Any]] = field(default_factory=list)
    remote_forwards: List[Dict[str, Any]] = field(default_factory=list)
    sessions: Dict[str, Dict[str, Any]] = field(
        default_factory=dict
    )  # session_name -> session_data


class ControlChannel:
    """Bidirectional control channel over SSH session.

    Uses length-prefixed JSON framing for reliable message boundaries.
    Supports request/response correlation and fire-and-forget events.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        container_name: str = "unknown",
    ):
        self.reader = reader
        self.writer = writer
        self.container_name = container_name
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._write_lock = asyncio.Lock()
        self._closed = False

    async def send(self, message: dict) -> None:
        """Send a message with length prefix."""
        if self._closed:
            raise ConnectionError("Control channel closed")

        # Add timestamp if not present
        if "ts" not in message:
            message["ts"] = time.time()

        data = json.dumps(message, ensure_ascii=False).encode("utf-8")
        if len(data) > MAX_MESSAGE_SIZE:
            raise ValueError(f"Message too large: {len(data)} bytes")

        # Length prefix (4 bytes, big-endian)
        header = struct.pack(">I", len(data))

        async with self._write_lock:
            try:
                self.writer.write(header + data)
                await self.writer.drain()
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                self._closed = True
                raise ConnectionError(f"Failed to send: {e}")

    async def recv(self) -> Optional[dict]:
        """Receive a message. Returns None on EOF."""
        if self._closed:
            return None

        try:
            # Read length header
            header = await self.reader.readexactly(4)
            length = struct.unpack(">I", header)[0]

            if length > MAX_MESSAGE_SIZE:
                logger.error(f"Message too large: {length} bytes from {self.container_name}")
                return None

            if length == 0:
                logger.warning(f"Empty message from {self.container_name}")
                return {}

            # Read message body
            data = await self.reader.readexactly(length)

            try:
                return json.loads(data.decode("utf-8"))
            except UnicodeDecodeError as e:
                logger.error(
                    f"UTF-8 decode error from {self.container_name}: {e}, header={header.hex()}, data[:20]={data[:20].hex()}"
                )
                return None

        except asyncio.IncompleteReadError:
            self._closed = True
            return None
        except (json.JSONDecodeError, struct.error) as e:
            logger.error(f"Invalid message from {self.container_name}: {e}")
            return None
        except (BrokenPipeError, ConnectionResetError, OSError):
            self._closed = True
            return None

    async def request(self, msg_type: str, payload: dict, timeout: float = 30.0) -> dict:
        """Send a request and wait for response."""
        request_id = str(uuid.uuid4())

        message = {
            "kind": "request",
            "type": msg_type,
            "id": request_id,
            "ts": time.time(),
            "payload": payload,
        }

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            await self.send(message)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Request {msg_type} timed out after {timeout}s")
        finally:
            self._pending_requests.pop(request_id, None)

    async def respond(
        self,
        request_id: str,
        msg_type: str,
        ok: bool,
        error: Optional[str] = None,
        data: Optional[dict] = None,
    ) -> None:
        """Send a response to a request."""
        payload = {"ok": ok}
        if error:
            payload["error"] = error
        if data:
            payload["data"] = data

        message = {
            "kind": "response",
            "type": msg_type,
            "id": request_id,
            "ts": time.time(),
            "payload": payload,
        }
        await self.send(message)

    async def send_event(self, msg_type: str, payload: dict) -> None:
        """Send an event (no response expected)."""
        message = {
            "kind": "event",
            "type": msg_type,
            "ts": time.time(),
            "payload": payload,
        }
        await self.send(message)

    def handle_response(self, message: dict) -> bool:
        """Handle an incoming response message. Returns True if handled."""
        request_id = message.get("id")
        if request_id and request_id in self._pending_requests:
            future = self._pending_requests[request_id]
            if not future.done():
                future.set_result(message.get("payload", {}))
            return True
        return False

    def close(self) -> None:
        """Close the control channel."""
        self._closed = True
        # Cancel all pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

        try:
            self.writer.close()
        except Exception:
            pass


class SSHTunnelServer:
    """SSH server for tunnel connections from containers.

    Runs an AsyncSSH server on a Unix socket that accepts connections
    from containers and handles:
    - Control channel for JSON messages (notifications, streaming, etc.)
    - Port forwarding (local and remote)
    """

    def __init__(
        self,
        socket_path: Path,
        allowed_hosts: Optional[Set[str]] = None,
        get_bind_addresses: Optional[Callable[[], List[str]]] = None,
    ):
        if not check_asyncssh_available():
            raise ImportError("asyncssh is required for SSH tunneling")

        self.socket_path = socket_path
        self.allowed_hosts = allowed_hosts or ContainerDefaults.ALLOWED_HOSTS
        self.get_bind_addresses = get_bind_addresses or (lambda: ["127.0.0.1"])

        # Port allowlist for local forwards (empty = all non-privileged allowed)
        self.allowed_ports: Set[int] = set()
        self.allowed_ports_lock = threading.Lock()

        # Active connections: container_name -> ContainerConnection
        self.connections: Dict[str, ContainerConnection] = {}
        self.connections_lock = threading.Lock()

        # Message handlers: type -> async handler function
        self._request_handlers: Dict[str, Callable] = {}
        self._event_handlers: Dict[str, Callable] = {}

        # Server state
        self._server: Optional[asyncssh.SSHAcceptor] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._host_key: Optional[asyncssh.SSHKey] = None

    def register_request_handler(self, msg_type: str, handler: Callable) -> None:
        """Register a handler for request messages."""
        self._request_handlers[msg_type] = handler

    def register_event_handler(self, msg_type: str, handler: Callable) -> None:
        """Register a handler for event messages."""
        self._event_handlers[msg_type] = handler

    def add_allowed_port(self, port: int) -> None:
        """Add a port to the allowlist for local forwards."""
        with self.allowed_ports_lock:
            self.allowed_ports.add(port)

    def remove_allowed_port(self, port: int) -> None:
        """Remove a port from the allowlist."""
        with self.allowed_ports_lock:
            self.allowed_ports.discard(port)

    def is_port_allowed(self, port: int) -> bool:
        """Check if a port is allowed for local forwarding."""
        if port < MIN_ALLOWED_PORT:
            return False
        with self.allowed_ports_lock:
            if not self.allowed_ports:
                return True
            return port in self.allowed_ports

    def is_host_allowed(self, host: str) -> bool:
        """Check if a host is allowed for local forwarding."""
        return host in self.allowed_hosts

    def _generate_host_key(self) -> asyncssh.SSHKey:
        """Generate an SSH host key."""
        return asyncssh.generate_private_key("ssh-ed25519")

    async def _start_server(self) -> None:
        """Start the SSH server (runs in asyncio loop)."""
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        if self.socket_path.exists():
            self.socket_path.unlink()

        if self._host_key is None:
            self._host_key = self._generate_host_key()
            logger.info("Generated SSH host key")

        # Create and bind Unix socket manually since asyncssh.create_server
        # doesn't support 'path' parameter directly
        import socket as sock_module

        unix_sock = sock_module.socket(sock_module.AF_UNIX, sock_module.SOCK_STREAM)
        unix_sock.bind(str(self.socket_path))
        unix_sock.listen(100)
        unix_sock.setblocking(False)
        os.chmod(self.socket_path, 0o600)

        self._server = await asyncssh.listen(
            sock=unix_sock,
            server_factory=lambda: SSHTunnelServerConnection(self),
            server_host_keys=[self._host_key],
            process_factory=self._create_process,
            encoding=None,  # Binary mode
            allow_pty=False,
            keepalive_interval=SSH_KEEPALIVE_INTERVAL,
            keepalive_count_max=SSH_KEEPALIVE_COUNT_MAX,
        )

        logger.info(f"SSH tunnel server listening on {self.socket_path}")

    async def _create_process(self, process: asyncssh.SSHServerProcess) -> None:
        """Factory for SSH process (control channel).

        Called when a client opens a session for the control channel.
        Must be async and await the handler to keep the process alive.
        """
        # Get the SSHTunnelServerConnection for this process
        conn_handler = process.channel.get_connection()

        # Find the container name from the connection
        container_name = None
        with self.connections_lock:
            for name, conn in self.connections.items():
                if conn.connection and conn.connection == conn_handler:
                    container_name = name
                    break

        if not container_name:
            logger.warning("Process created but no container found")
            process.exit(1)
            return

        # Run control channel handler directly (await keeps the process alive)
        await self._run_control_channel(container_name, process)

    async def _call_handler(self, handler: Callable, *args) -> Any:
        """Call a handler, handling both sync and async handlers."""
        import inspect

        if inspect.iscoroutinefunction(handler):
            return await handler(*args)
        else:
            return handler(*args)

    async def _run_control_channel(
        self,
        container: str,
        process: asyncssh.SSHServerProcess,
    ) -> None:
        """Handle control channel messages for a container."""

        # Create control channel
        channel = ControlChannel(
            process.stdin,
            process.stdout,
            container,
        )

        # Store in connection
        with self.connections_lock:
            conn = self.connections.get(container)
            if conn:
                conn.control_channel = channel

        logger.info(f"Control channel opened for {container}")

        try:
            while True:
                message = await channel.recv()
                if message is None:
                    break

                kind = message.get("kind")
                msg_type = message.get("type")
                request_id = message.get("id")
                payload = message.get("payload", {})

                if kind == "response":
                    channel.handle_response(message)
                    continue

                if kind == "request":
                    handler = self._request_handlers.get(msg_type)
                    if handler:
                        try:
                            result = await self._call_handler(handler, container, payload)
                            if isinstance(result, dict):
                                ok = result.get("ok", True)
                                error = result.get("error")
                                data = result.get("data")
                            else:
                                ok = True
                                error = None
                                data = None
                            await channel.respond(request_id, msg_type, ok, error, data)
                        except Exception as e:
                            logger.error(f"Request handler error for {msg_type}: {e}")
                            await channel.respond(request_id, msg_type, False, str(e))
                    else:
                        await channel.respond(request_id, msg_type, False, f"Unknown: {msg_type}")

                elif kind == "event":
                    handler = self._event_handlers.get(msg_type)
                    if handler:
                        try:
                            await self._call_handler(handler, container, payload)
                        except Exception as e:
                            logger.error(f"Event handler error for {msg_type}: {e}")

        except asyncio.CancelledError:
            # Task was cancelled (e.g., during disconnect) - exit quietly
            logger.debug(f"Control channel task cancelled for {container}")
        except Exception as e:
            logger.error(f"Control channel error for {container}: {e}")
        finally:
            logger.info(f"Control channel closed for {container}")
            channel.close()
            process.exit(0)

    async def _run_loop(self) -> None:
        """Main asyncio loop for the server."""
        await self._start_server()

        while self._running:
            await asyncio.sleep(1)

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        if self.socket_path.exists():
            self.socket_path.unlink()

    def _run_in_thread(self) -> None:
        """Run the asyncio loop in a dedicated thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._run_loop())
        except Exception as e:
            logger.error(f"SSH server error: {e}")
        finally:
            self._loop.close()

    def start(self) -> None:
        """Start the SSH tunnel server."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_in_thread, daemon=True, name="ssh-tunnel-server"
        )
        self._thread.start()

        # Wait for server to be ready
        for _ in range(50):
            if self.socket_path.exists():
                break
            time.sleep(0.1)

        logger.info("SSH tunnel server started")

    def stop(self) -> None:
        """Stop the SSH tunnel server."""
        if not self._running:
            return

        self._running = False

        if self._thread:
            self._thread.join(timeout=5.0)

        logger.info("SSH tunnel server stopped")

    def get_stats(self) -> Dict[str, Any]:
        """Get server statistics."""
        with self.connections_lock:
            return {
                "active_connections": len(self.connections),
                "connections": {
                    name: {
                        "connected_at": conn.connected_at,
                        "local_forwards": list(conn.local_forwards),
                        "remote_forwards": list(conn.remote_forwards),
                        "sessions": list(conn.sessions.keys()),
                        "has_control_channel": conn.control_channel is not None,
                    }
                    for name, conn in self.connections.items()
                },
            }

    def get_connection(self, container: str) -> Optional[ContainerConnection]:
        """Get a container's connection (thread-safe)."""
        with self.connections_lock:
            return self.connections.get(container)

    async def send_to_container(self, container: str, msg_type: str, payload: dict) -> bool:
        """Send an event to a container's control channel."""
        conn = self.get_connection(container)
        if not conn or not conn.control_channel:
            return False

        try:
            await conn.control_channel.send_event(msg_type, payload)
            return True
        except Exception as e:
            logger.error(f"Failed to send to {container}: {e}")
            return False

    def send_to_container_sync(self, container: str, msg_type: str, payload: dict) -> bool:
        """Send an event to a container (sync wrapper for threaded code)."""
        if not self._loop:
            return False

        future = asyncio.run_coroutine_threadsafe(
            self.send_to_container(container, msg_type, payload), self._loop
        )
        try:
            return future.result(timeout=5.0)
        except Exception:
            return False

    async def request_to_container(
        self, container: str, msg_type: str, payload: dict, timeout: float = 30.0
    ) -> Optional[dict]:
        """Send a request to a container and wait for response."""
        conn = self.get_connection(container)
        if not conn or not conn.control_channel:
            return None

        try:
            return await conn.control_channel.request(msg_type, payload, timeout)
        except Exception as e:
            logger.error(f"Request to {container} failed: {e}")
            return None

    def request_to_container_sync(
        self, container: str, msg_type: str, payload: dict, timeout: float = 30.0
    ) -> Optional[dict]:
        """Send a request to a container (sync wrapper for threaded code)."""
        if not self._loop:
            return None

        future = asyncio.run_coroutine_threadsafe(
            self.request_to_container(container, msg_type, payload, timeout), self._loop
        )
        try:
            return future.result(timeout=timeout + 1.0)
        except Exception:
            return None


class MultiAddressListener:
    """SSH listener that binds on multiple addresses."""

    def __init__(self, listeners: List[Any], port: int):
        self._listeners = listeners
        self._port = port

    def get_port(self) -> int:
        return self._port

    def close(self) -> None:
        for listener in self._listeners:
            try:
                listener.close()
            except Exception:
                pass

    async def wait_closed(self) -> None:
        for listener in self._listeners:
            try:
                await listener.wait_closed()
            except Exception:
                pass


class SSHTunnelServerConnection(_SSHServerBase):
    """SSH server connection handler for a single container."""

    def __init__(self, server: SSHTunnelServer):
        self.server = server
        self.container_name: Optional[str] = None
        self._conn: Optional[asyncssh.SSHServerConnection] = None

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        """Called when a connection is established."""
        self._conn = conn
        logger.debug("SSH connection established")

        if self.container_name:
            with self.server.connections_lock:
                stored = self.server.connections.get(self.container_name)
                if stored and stored.connection is None:
                    stored.connection = conn

    def connection_lost(self, exc: Optional[Exception]) -> None:
        """Called when a connection is lost."""
        if self.container_name:
            logger.info(f"Container {self.container_name} disconnected")

            should_notify = False
            container_to_notify = self.container_name
            task_to_cancel = None

            with self.server.connections_lock:
                stored = self.server.connections.get(self.container_name)
                if stored and stored.connection is self._conn:
                    # Cancel control channel task
                    if stored.control_task:
                        task_to_cancel = stored.control_task
                    # Close control channel
                    if stored.control_channel:
                        stored.control_channel.close()
                    self.server.connections.pop(self.container_name, None)
                    should_notify = True

            # Cancel task outside lock
            if task_to_cancel:
                task_to_cancel.cancel()

            # Notify handlers outside the lock
            if should_notify:
                handler = self.server._event_handlers.get("_container_disconnect")
                if handler:
                    try:
                        handler(container_to_notify)
                    except Exception as e:
                        logger.error(f"Disconnect handler error: {e}")

    def begin_auth(self, username: str) -> bool:
        """Handle authentication start."""
        self.container_name = username
        logger.info(f"Container {username} connecting")

        old_connection_to_close = None
        old_task_to_cancel = None

        with self.server.connections_lock:
            old_conn = self.server.connections.get(username)
            if old_conn:
                if old_conn.control_task:
                    old_task_to_cancel = old_conn.control_task
                if old_conn.control_channel:
                    old_conn.control_channel.close()
                if old_conn.connection:
                    old_connection_to_close = old_conn.connection

            self.server.connections[username] = ContainerConnection(
                container=username,
                connected_at=time.time(),
                connection=self._conn,
            )

        # Cancel old task outside lock
        if old_task_to_cancel:
            old_task_to_cancel.cancel()

        if old_connection_to_close:
            logger.info(f"Closing previous connection for {username}")
            try:
                old_connection_to_close.close()
            except Exception:
                pass

        return False  # Accept without auth

    def password_auth_supported(self) -> bool:
        return False

    def public_key_auth_supported(self) -> bool:
        return False

    def auth_completed(self) -> None:
        """Called when authentication completes."""
        logger.info(f"Container {self.container_name} authenticated")

        # Notify connection handler
        handler = self.server._event_handlers.get("_container_connect")
        if handler:
            try:
                handler(self.container_name)
            except Exception as e:
                logger.error(f"Connect handler error: {e}")

    def session_requested(self) -> bool:
        """Handle session request - used for control channel."""
        return True

    async def server_requested(self, listen_host: str, listen_port: int):
        """Handle remote port forward request (host→container).

        When client calls forward_remote_port(), this method is invoked.
        Return True to allow asyncssh to create the listener automatically.
        """
        if not self.container_name:
            return False

        if listen_port != 0 and listen_port < MIN_ALLOWED_PORT:
            logger.warning(f"Rejected remote forward to privileged port {listen_port}")
            return False

        # Allow asyncssh to handle the port binding - just return True
        logger.info(
            f"Remote forward approved: {listen_host or '*'}:{listen_port} -> {self.container_name}"
        )

        # Track the forward
        with self.server.connections_lock:
            if self.container_name in self.server.connections:
                self.server.connections[self.container_name].remote_forwards.append(
                    {
                        "host_port": listen_port,
                        "listen_host": listen_host,
                    }
                )

        return True

    def connection_requested(
        self, dest_host: str, dest_port: int, orig_host: str, orig_port: int
    ) -> bool:
        """Handle local port forward request (container→host)."""
        if not self.server.is_host_allowed(dest_host):
            logger.warning(f"Rejected forward to disallowed host {dest_host}")
            return False

        if not self.server.is_port_allowed(dest_port):
            logger.warning(f"Rejected forward to disallowed port {dest_port}")
            return False

        logger.debug(f"Local forward: {self.container_name} -> {dest_host}:{dest_port}")

        with self.server.connections_lock:
            if self.container_name in self.server.connections:
                self.server.connections[self.container_name].local_forwards.append(
                    {
                        "host": dest_host,
                        "port": dest_port,
                    }
                )

        return True


class SSHTunnelClient:
    """SSH client for connecting container to host.

    Provides:
    - Control channel for JSON messages
    - Local port forwarding (container→host)
    - Remote port forwarding (host→container)
    - Auto-reconnect with state restoration
    """

    def __init__(
        self,
        socket_path: Path,
        container_name: str,
        local_forwards: Optional[List[PortForwardConfig]] = None,
        remote_forwards: Optional[List[PortForwardConfig]] = None,
    ):
        if not check_asyncssh_available():
            raise ImportError("asyncssh is required for SSH tunneling")

        self.socket_path = socket_path
        self.container_name = container_name
        self.local_forwards = local_forwards or []
        self.remote_forwards = remote_forwards or []

        # Connection state
        self._conn: Optional[asyncssh.SSHClientConnection] = None
        self._local_listeners: Dict[int, asyncssh.SSHListener] = {}
        self._remote_listeners: Dict[int, asyncssh.SSHListener] = {}
        self._control_channel: Optional[ControlChannel] = None
        self._control_process: Optional[asyncssh.SSHClientProcess] = None

        # Message handlers
        self._request_handlers: Dict[str, Callable] = {}
        self._event_handlers: Dict[str, Callable] = {}

        # State
        self._running = False
        self._connected = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

        # Callbacks
        self.on_connect: Optional[Callable[[], None]] = None
        self.on_disconnect: Optional[Callable[[], None]] = None

    def register_request_handler(self, msg_type: str, handler: Callable) -> None:
        """Register a handler for request messages from server."""
        self._request_handlers[msg_type] = handler

    def register_event_handler(self, msg_type: str, handler: Callable) -> None:
        """Register a handler for event messages from server."""
        self._event_handlers[msg_type] = handler

    async def _call_handler(self, handler: Callable, *args) -> Any:
        """Call a handler, handling both sync and async handlers."""
        import inspect

        if inspect.iscoroutinefunction(handler):
            return await handler(*args)
        else:
            return handler(*args)

    @property
    def control_channel(self) -> Optional[ControlChannel]:
        """Get the control channel (if connected)."""
        return self._control_channel

    @property
    def is_connected(self) -> bool:
        """Check if connected to server."""
        return self._connected and self._control_channel is not None

    async def _connect(self) -> bool:
        """Connect to the SSH server."""
        if not self.socket_path.exists():
            logger.debug(f"SSH socket not found: {self.socket_path}")
            return False

        try:
            # Create Unix socket connection manually since asyncssh.connect
            # doesn't support 'path' parameter directly
            import socket as sock_module

            unix_sock = sock_module.socket(sock_module.AF_UNIX, sock_module.SOCK_STREAM)
            unix_sock.setblocking(False)

            loop = asyncio.get_event_loop()
            await loop.sock_connect(unix_sock, str(self.socket_path))

            self._conn = await asyncssh.connect(
                sock=unix_sock,
                username=self.container_name,
                known_hosts=None,
                keepalive_interval=SSH_KEEPALIVE_INTERVAL,
                keepalive_count_max=SSH_KEEPALIVE_COUNT_MAX,
            )

            logger.info(f"Connected to SSH server at {self.socket_path}")
            self._connected = True
            self._reconnect_delay = 1.0

            return True

        except Exception as e:
            logger.warning(f"Failed to connect to SSH server: {e}")
            return False

    async def _setup_control_channel(self) -> bool:
        """Set up the control channel after connection."""
        if not self._conn:
            return False

        try:
            # Create a process/session for control channel
            self._control_process = await self._conn.create_process(
                term_type=None,
                encoding=None,
            )

            self._control_channel = ControlChannel(
                self._control_process.stdout,
                self._control_process.stdin,
                self.container_name,
            )

            logger.info("Control channel established")
            return True

        except Exception as e:
            logger.error(f"Failed to set up control channel: {e}")
            return False

    async def _setup_forwards(self) -> None:
        """Set up port forwards after connection."""
        if not self._conn:
            return

        # Set up local forwards (container→host)
        local_forwards_info = []
        for config in self.local_forwards:
            try:
                listener = await self._conn.forward_local_port(
                    listen_host="127.0.0.1",
                    listen_port=config.container_port,
                    dest_host="127.0.0.1",
                    dest_port=config.host_port,
                )
                self._local_listeners[config.container_port] = listener
                local_forwards_info.append(
                    {
                        "host_port": config.host_port,
                        "container_port": config.container_port,
                    }
                )
                logger.info(
                    f"Local forward: 127.0.0.1:{config.container_port} -> host:{config.host_port}"
                )
            except Exception as e:
                logger.error(f"Failed to create local forward for {config.name}: {e}")

        # Notify daemon about local forwards (so it can track them for display)
        if local_forwards_info:
            await self.send_event_async(
                "local_forwards_registered",
                {
                    "forwards": local_forwards_info,
                },
            )

        # Set up remote forwards (host→container)
        for config in self.remote_forwards:
            try:
                listener = await self._conn.forward_remote_port(
                    listen_host="",
                    listen_port=config.host_port,
                    dest_host="127.0.0.1",
                    dest_port=config.container_port,
                )
                if listener:
                    self._remote_listeners[config.host_port] = listener
                logger.info(
                    f"Remote forward: host:{config.host_port} -> 127.0.0.1:{config.container_port}"
                )
            except Exception as e:
                logger.error(f"Failed to create remote forward for {config.name}: {e}")

    async def _control_channel_loop(self) -> None:
        """Process messages from control channel."""
        if not self._control_channel:
            return

        try:
            while self._running and self._connected:
                message = await self._control_channel.recv()
                if message is None:
                    break

                kind = message.get("kind")
                msg_type = message.get("type")
                request_id = message.get("id")
                payload = message.get("payload", {})

                if kind == "response":
                    self._control_channel.handle_response(message)
                    continue

                if kind == "request":
                    handler = self._request_handlers.get(msg_type)
                    if handler:
                        try:
                            result = await self._call_handler(handler, payload)
                            if isinstance(result, dict):
                                ok = result.get("ok", True)
                                error = result.get("error")
                                data = result.get("data")
                            else:
                                ok = True
                                error = None
                                data = None
                            await self._control_channel.respond(
                                request_id, msg_type, ok, error, data
                            )
                        except Exception as e:
                            logger.error(f"Request handler error: {e}")
                            await self._control_channel.respond(request_id, msg_type, False, str(e))
                    else:
                        await self._control_channel.respond(
                            request_id, msg_type, False, f"Unknown: {msg_type}"
                        )

                elif kind == "event":
                    handler = self._event_handlers.get(msg_type)
                    if handler:
                        try:
                            await self._call_handler(handler, payload)
                        except Exception as e:
                            logger.error(f"Event handler error: {e}")

        except asyncio.CancelledError:
            # Task was cancelled (e.g., during disconnect) - exit quietly
            logger.debug("Control channel loop cancelled")
        except Exception as e:
            logger.error(f"Control channel loop error: {e}")

    async def _run_loop(self) -> None:
        """Main asyncio loop for the client."""
        while self._running:
            if not self._connected:
                if await self._connect():
                    if await self._setup_control_channel():
                        await self._setup_forwards()

                        # Notify connection
                        if self.on_connect:
                            try:
                                self.on_connect()
                            except Exception as e:
                                logger.error(f"Connect callback error: {e}")

                        # Run control channel loop
                        await self._control_channel_loop()
                    else:
                        # Control channel failed, disconnect
                        if self._conn:
                            self._conn.close()
                            self._conn = None
                else:
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(
                        self._reconnect_delay * 2, self._max_reconnect_delay
                    )
                    continue

            # Connection lost - clean up properly
            self._connected = False

            # Close control channel
            if self._control_channel:
                self._control_channel.close()
            self._control_channel = None
            self._control_process = None

            # Close SSH connection
            if self._conn:
                try:
                    self._conn.close()
                    await self._conn.wait_closed()
                except Exception:
                    pass
            self._conn = None

            self._local_listeners.clear()

            if self.on_disconnect:
                try:
                    self.on_disconnect()
                except Exception as e:
                    logger.error(f"Disconnect callback error: {e}")

            if self._running:
                logger.info("Connection lost, will reconnect...")
                await asyncio.sleep(self._reconnect_delay)

    def _run_in_thread(self) -> None:
        """Run the asyncio loop in a dedicated thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._run_loop())
        except Exception as e:
            logger.error(f"SSH client error: {e}")
        finally:
            self._loop.close()

    def start(self) -> None:
        """Start the SSH tunnel client."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_in_thread, daemon=True, name="ssh-tunnel-client"
        )
        self._thread.start()

        logger.info("SSH tunnel client started")

    def stop(self) -> None:
        """Stop the SSH tunnel client."""
        if not self._running:
            return

        self._running = False

        if self._loop and self._conn:
            asyncio.run_coroutine_threadsafe(self._close_connection(), self._loop)

        if self._thread:
            self._thread.join(timeout=5.0)

        logger.info("SSH tunnel client stopped")

    async def _close_connection(self) -> None:
        """Close the SSH connection."""
        if self._control_channel:
            self._control_channel.close()
        if self._conn:
            self._conn.close()
            await self._conn.wait_closed()

    # Async methods for use within the event loop

    async def send_event_async(self, msg_type: str, payload: dict) -> bool:
        """Send an event to the server (async version)."""
        if not self._control_channel:
            return False
        try:
            await self._control_channel.send_event(msg_type, payload)
            return True
        except Exception:
            return False

    async def request_async(
        self, msg_type: str, payload: dict, timeout: float = 30.0
    ) -> Optional[dict]:
        """Send a request and wait for response (async version)."""
        if not self._control_channel:
            return None
        try:
            return await self._control_channel.request(msg_type, payload, timeout)
        except Exception:
            return None

    async def add_local_forward_async(
        self, config: PortForwardConfig
    ) -> Tuple[bool, Optional[str]]:
        """Dynamically add a local forward (async version for use in event loop).

        Returns:
            Tuple of (success, error_message). error_message is None on success.
        """
        return await self._add_local_forward_async(config)

    async def add_remote_forward_async(
        self, config: PortForwardConfig
    ) -> Tuple[bool, Optional[str]]:
        """Dynamically add a remote forward (async version for use in event loop).

        Returns:
            Tuple of (success, error_message). error_message is None on success.
        """
        return await self._add_remote_forward_async(config)

    # Sync wrappers for threaded code (do NOT call from the event loop thread)

    def _check_not_on_loop(self, method_name: str) -> bool:
        """Check that we're not on the event loop thread. Returns True if safe."""
        try:
            running_loop = asyncio.get_running_loop()
            if running_loop is self._loop:
                logger.error(
                    f"{method_name}() called from event loop thread - use async version instead. "
                    f"This will deadlock!"
                )
                return False
        except RuntimeError:
            # No running loop - safe to proceed
            pass
        return True

    def send_event(self, msg_type: str, payload: dict) -> bool:
        """Send an event to the server (sync wrapper - do not call from event loop)."""
        if not self._loop or not self._control_channel:
            return False
        if not self._check_not_on_loop("send_event"):
            return False

        future = asyncio.run_coroutine_threadsafe(
            self._control_channel.send_event(msg_type, payload), self._loop
        )
        try:
            future.result(timeout=5.0)
            return True
        except Exception:
            return False

    def request(self, msg_type: str, payload: dict, timeout: float = 30.0) -> Optional[dict]:
        """Send a request and wait for response (sync wrapper - do not call from event loop)."""
        if not self._loop or not self._control_channel:
            return None
        if not self._check_not_on_loop("request"):
            return None

        future = asyncio.run_coroutine_threadsafe(
            self._control_channel.request(msg_type, payload, timeout), self._loop
        )
        try:
            return future.result(timeout=timeout + 1)
        except Exception:
            return None

    def add_local_forward(self, config: PortForwardConfig) -> Tuple[bool, Optional[str]]:
        """Dynamically add a local forward.

        Returns:
            Tuple of (success, error_message). error_message is None on success.
        """
        if not self._loop or not self._running:
            return False, "SSH tunnel not running"
        if not self._check_not_on_loop("add_local_forward"):
            return False, "Called from event loop thread"

        future = asyncio.run_coroutine_threadsafe(self._add_local_forward_async(config), self._loop)
        try:
            return future.result(timeout=5.0)
        except Exception as e:
            return False, str(e)

    async def _add_local_forward_async(
        self, config: PortForwardConfig
    ) -> Tuple[bool, Optional[str]]:
        """Add a local forward (async version).

        Returns:
            Tuple of (success, error_message). error_message is None on success.
        """
        if not self._conn:
            return False, "SSH connection not established"

        try:
            listener = await self._conn.forward_local_port(
                listen_host="127.0.0.1",
                listen_port=config.container_port,
                dest_host="127.0.0.1",
                dest_port=config.host_port,
            )
            self._local_listeners[config.container_port] = listener
            self.local_forwards.append(config)
            logger.info(f"Added local forward: {config.container_port} -> host:{config.host_port}")
            return True, None
        except Exception as e:
            logger.error(f"Failed to add local forward: {e}")
            return False, str(e)

    def add_remote_forward(self, config: PortForwardConfig) -> Tuple[bool, Optional[str]]:
        """Dynamically add a remote forward.

        Returns:
            Tuple of (success, error_message). error_message is None on success.
        """
        if not self._loop or not self._running:
            return False, "SSH tunnel not running"
        if not self._check_not_on_loop("add_remote_forward"):
            return False, "Called from event loop thread"

        future = asyncio.run_coroutine_threadsafe(
            self._add_remote_forward_async(config), self._loop
        )
        try:
            return future.result(timeout=5.0)
        except Exception as e:
            return False, str(e)

    async def _add_remote_forward_async(
        self, config: PortForwardConfig
    ) -> Tuple[bool, Optional[str]]:
        """Add a remote forward (async version).

        Returns:
            Tuple of (success, error_message). error_message is None on success.
        """
        if not self._conn:
            return False, "SSH connection not established"

        try:
            listener = await self._conn.forward_remote_port(
                listen_host="",
                listen_port=config.host_port,
                dest_host="127.0.0.1",
                dest_port=config.container_port,
            )
            if listener:
                self._remote_listeners[config.host_port] = listener
            self.remote_forwards.append(config)
            logger.info(f"Added remote forward: host:{config.host_port} -> {config.container_port}")
            return True, None
        except Exception as e:
            logger.error(f"Failed to add remote forward: {e}")
            return False, str(e)

    async def remove_local_forward_async(self, host_port: int) -> bool:
        """Remove a local forward by host port."""
        # Find the config with this host_port to get the container_port (listener key)
        config = None
        for fwd in self.local_forwards:
            if fwd.host_port == host_port:
                config = fwd
                break

        if not config:
            logger.warning(f"No local forward config found for host port {host_port}")
            return False

        container_port = config.container_port
        if container_port not in self._local_listeners:
            logger.warning(f"No local listener found for container port {container_port}")
            return False

        try:
            listener = self._local_listeners.pop(container_port)
            listener.close()
            await listener.wait_closed()
            # Remove from config list
            self.local_forwards = [f for f in self.local_forwards if f.host_port != host_port]
            # Notify server to update its tracking
            await self.send_event_async(
                "forward_removed",
                {
                    "direction": "local",
                    "host_port": host_port,
                    "container_port": container_port,
                },
            )
            logger.info(f"Removed local forward: container:{container_port} -> host:{host_port}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove local forward: {e}")
            return False

    async def remove_remote_forward_async(self, host_port: int) -> bool:
        """Remove a remote forward by host port."""
        # Check if we have a listener for this port
        if host_port not in self._remote_listeners:
            logger.warning(f"No remote listener found for host port {host_port}")
            return False

        # Find the container_port for this forward
        container_port = host_port
        for fwd in self.remote_forwards:
            if fwd.host_port == host_port:
                container_port = fwd.container_port
                break

        try:
            listener = self._remote_listeners.pop(host_port)
            listener.close()
            await listener.wait_closed()

            # Remove from config list
            self.remote_forwards = [f for f in self.remote_forwards if f.host_port != host_port]
            # Notify server to update its tracking
            await self.send_event_async(
                "forward_removed",
                {
                    "direction": "remote",
                    "host_port": host_port,
                    "container_port": container_port,
                },
            )
            logger.info(f"Removed remote forward: host:{host_port}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove remote forward: {e}")
            return False
