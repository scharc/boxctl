# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""PTY session manager for terminal WebSocket passthrough.

Uses tmux attach -r (read-only) for output streaming via PTY socket,
and tmux send-keys for input. This avoids attach conflicts while
providing proper PTY rendering without buffer duplication issues.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Set, Tuple, Callable, Any

from docker.errors import NotFound, APIError

from boxctl.container import ContainerManager
from boxctl.paths import BinPaths, ContainerPaths

logger = logging.getLogger(__name__)


class PTYSession:
    """Manages streaming connection to a tmux session via read-only PTY.

    Uses tmux attach -r for output streaming (proper PTY rendering)
    and send-keys for input. Supports multiple WebSocket readers.
    """

    def __init__(self, container_name: str, session_name: str, client_id: str):
        self.container_name = container_name
        self.session_name = session_name
        self.client_id = client_id  # UUID to track this client
        self.manager = ContainerManager()
        self.exec_id: Optional[str] = None
        self._socket = None
        self._raw_socket = None
        self._readers: Set[Callable[[bytes], Any]] = set()
        self._read_task: Optional[asyncio.Task] = None
        self.running = False
        self._paused = False  # Pause broadcasting during resize
        self._lock = asyncio.Lock()
        self.last_heartbeat = time.time()  # Track last activity

    async def start(self) -> bool:
        """Start PTY streaming using tmux attach with full duplex socket.

        Returns:
            True if session started successfully, False otherwise.
        """
        try:
            if not self.manager.is_running(self.container_name):
                logger.warning(f"Container not running: {self.container_name}")
                return False

            container = self.manager.client.containers.get(self.container_name)

            # Disable tmux mouse mode before attaching to prevent conflict with xterm.js
            # Tmux mouse mode interferes with xterm.js scrollback scrolling
            try:
                disable_mouse = [
                    BinPaths.TMUX,
                    "set-option",
                    "-t",
                    self.session_name,
                    "mouse",
                    "off",
                ]
                container.exec_run(
                    disable_mouse, user=ContainerPaths.USER, environment={"TMUX_TMPDIR": "/tmp"}
                )
                logger.debug(
                    f"Disabled tmux mouse mode for web UI: {self.container_name}/{self.session_name}"
                )
            except Exception as e:
                logger.warning(f"Could not disable tmux mouse mode: {e}")

            # Use regular tmux attach (not read-only) with BOTH stdin and stdout
            # This gives us full bidirectional PTY socket
            # Use = prefix for exact session matching (prevents prefix matching)
            exec_create = self.manager.client.api.exec_create(
                container.id,
                cmd=[BinPaths.TMUX, "attach", "-t", f"={self.session_name}"],
                stdin=True,  # Enable input via socket
                stdout=True,
                stderr=True,
                tty=True,
                user=ContainerPaths.USER,
                environment={
                    "TERM": "xterm-256color",
                    "HOME": ContainerPaths.HOME,
                    "USER": ContainerPaths.USER,
                    "TMUX_TMPDIR": "/tmp",
                    "LANG": "en_US.UTF-8",
                    "LC_ALL": "en_US.UTF-8",
                },
            )
            self.exec_id = exec_create["Id"]

            # Get socket for streaming - full duplex (read and write)
            self._socket = self.manager.client.api.exec_start(
                self.exec_id, tty=True, socket=True, demux=False
            )

            # Get underlying socket
            self._raw_socket = self._socket._sock
            self._raw_socket.setblocking(False)

            self.running = True

            # Start read loop
            self._read_task = asyncio.create_task(self._read_loop())

            logger.info(
                f"PTY streaming started (full duplex): {self.container_name}/{self.session_name}"
            )
            return True

        except NotFound:
            logger.warning(f"Container not found: {self.container_name}")
            return False
        except APIError as e:
            logger.error(f"Docker API error starting PTY: {e}")
            return False
        except Exception as e:
            logger.exception(f"Error starting PTY session: {e}")
            return False

    async def _read_loop(self):
        """Read from pipe-pane socket and broadcast to all readers."""
        loop = asyncio.get_event_loop()

        while self.running:
            try:
                # Read from socket in executor to avoid blocking
                data = await loop.run_in_executor(None, self._blocking_read)

                if data is None:
                    # Error reading
                    break

                if len(data) == 0:
                    # No data but still alive
                    await asyncio.sleep(0.01)
                    continue

                # Broadcast to all readers
                await self._broadcast(data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.running:
                    logger.error(f"PTY read error: {e}")
                break

        self.running = False
        await self._cleanup()

    def _blocking_read(self) -> Optional[bytes]:
        """Blocking read from raw socket with timeout."""
        import select

        if not self._raw_socket:
            return None

        try:
            # Use select with short timeout
            ready, _, _ = select.select([self._raw_socket], [], [], 0.1)
            if ready:
                # Read available data
                data = self._raw_socket.recv(8192)
                if not data:
                    # Socket closed
                    return None
                return data
            return b""  # Timeout, no data available
        except BlockingIOError:
            return b""
        except Exception as e:
            logger.error(f"Socket read error: {e}")
            return None

    async def _broadcast(self, data: bytes):
        """Broadcast data to all registered readers."""
        # Skip broadcasting if paused (during resize)
        if self._paused:
            return

        # Copy set to avoid modification during iteration
        readers = set(self._readers)
        for callback in readers:
            try:
                # Callbacks may be sync or async
                result = callback(data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Error in PTY reader callback: {e}")

    async def write(self, data: str) -> bool:
        """Write input directly to PTY socket.

        Args:
            data: String data to write to PTY.

        Returns:
            True if write succeeded, False otherwise.
        """
        if not self.running or not self._raw_socket:
            return False

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self._raw_socket.sendall(data.encode("utf-8")))
            return True
        except Exception as e:
            logger.error(f"PTY write error: {e}")
            return False

    async def resize(self, width: int, height: int) -> bool:
        """Resize PTY using Docker API.

        Pauses broadcasting during resize to prevent tmux screen redraw
        escape sequences from being added as new scrollback lines.

        Args:
            width: New terminal width in columns.
            height: New terminal height in rows.

        Returns:
            True if resize succeeded, False otherwise.
        """
        if not self.exec_id:
            return False

        try:
            # Pause broadcasting to prevent resize redraw from appearing as new lines
            self._paused = True
            logger.debug(f"PTY broadcasting paused for resize: {width}x{height}")

            # Resize the PTY
            self.manager.client.api.exec_resize(self.exec_id, height=height, width=width)
            logger.debug(f"PTY resized: {width}x{height}")

            # Wait for tmux to fully stabilize after resize (tmux redraws screen)
            # Must be at least as long as client-side wait before __READY__
            await asyncio.sleep(1.2)

            # Resume broadcasting
            self._paused = False
            logger.debug(f"PTY broadcasting resumed after resize")

            return True
        except Exception as e:
            logger.error(f"PTY resize error: {e}")
            self._paused = False  # Ensure we resume even on error
            return False

    def add_reader(self, callback: Callable[[bytes], Any]):
        """Add a reader callback to receive PTY output.

        Args:
            callback: Async or sync function that receives bytes.
        """
        self._readers.add(callback)

    def remove_reader(self, callback: Callable[[bytes], Any]):
        """Remove a reader callback.

        Args:
            callback: Previously registered callback.
        """
        self._readers.discard(callback)

        # If no more readers, stop the session
        if not self._readers and self.running:
            logger.info(f"No more readers, stopping PTY: {self.container_name}/{self.session_name}")
            asyncio.create_task(self.stop())

    async def stop(self):
        """Stop the PTY session."""
        self.running = False

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        await self._cleanup()

    async def _cleanup(self):
        """Clean up resources and detach from tmux."""
        # Send detach sequence to tmux before closing (Ctrl+B, D)
        if self._raw_socket and self.running:
            try:
                # Send tmux prefix (Ctrl+B) followed by 'd' to detach
                self._raw_socket.sendall(b"\x02d")
                logger.debug(
                    f"Sent detach sequence to tmux: {self.container_name}/{self.session_name}"
                )
                await asyncio.sleep(0.1)  # Give tmux time to process
            except Exception as e:
                logger.warning(f"Failed to send detach sequence: {e}")

        # Close socket
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
            self._raw_socket = None

        # Try to stop the exec process explicitly via Docker API
        if self.exec_id:
            try:
                # Note: Docker doesn't provide exec_stop, but closing socket should terminate it
                # If process doesn't terminate, we've sent detach sequence above
                logger.debug(
                    f"Closed exec {self.exec_id} for {self.container_name}/{self.session_name}"
                )
            except Exception as e:
                logger.warning(f"Error during exec cleanup: {e}")

        self._readers.clear()


class PTYSessionManager:
    """Manages PTY sessions - one per client (identified by UUID).

    Each WebSocket connection gets its own PTY session with a unique client_id.
    Includes heartbeat monitoring and automatic cleanup of stale sessions.
    """

    STALE_TIMEOUT = 30  # Seconds without heartbeat before considering stale

    def __init__(self):
        self._sessions: Dict[str, PTYSession] = {}  # client_id -> PTYSession
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start_cleanup_task(self):
        """Start background task to clean up stale sessions."""
        if not self._cleanup_task or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_stale_sessions())
            logger.info("Started PTY session cleanup task")

    async def stop_cleanup_task(self):
        """Stop the background cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("Stopped PTY session cleanup task")

    async def _cleanup_stale_sessions(self):
        """Background task to detect and remove stale PTY sessions."""
        while True:
            try:
                await asyncio.sleep(10)  # Check every 10 seconds
                current_time = time.time()
                stale_clients = []

                async with self._lock:
                    for client_id, session in self._sessions.items():
                        if current_time - session.last_heartbeat > self.STALE_TIMEOUT:
                            stale_clients.append(client_id)
                            logger.warning(
                                f"Detected stale session: {client_id} "
                                f"({session.container_name}/{session.session_name}) "
                                f"- last heartbeat {current_time - session.last_heartbeat:.1f}s ago"
                            )

                # Remove stale sessions outside the lock
                for client_id in stale_clients:
                    await self.remove_session(client_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error in cleanup task: {e}")

    async def get_or_create_session(
        self, container: str, session_name: str, client_id: str
    ) -> Optional[PTYSession]:
        """Get existing or create new PTY session for a client.

        Args:
            container: Docker container name.
            session_name: tmux session name.
            client_id: Unique client identifier (UUID).

        Returns:
            PTYSession instance or None if creation failed.
        """
        async with self._lock:
            # Check if session exists and is running
            if client_id in self._sessions:
                session = self._sessions[client_id]
                if session.running:
                    session.last_heartbeat = time.time()  # Update heartbeat
                    return session
                else:
                    # Clean up dead session
                    del self._sessions[client_id]

            # Create new session
            session = PTYSession(container, session_name, client_id)
            if await session.start():
                self._sessions[client_id] = session
                logger.info(
                    f"Created PTY session for client {client_id}: {container}/{session_name}"
                )
                return session

            return None

    async def update_heartbeat(self, client_id: str):
        """Update last heartbeat time for a client.

        Args:
            client_id: Client identifier.
        """
        async with self._lock:
            if client_id in self._sessions:
                self._sessions[client_id].last_heartbeat = time.time()

    async def remove_session(self, client_id: str):
        """Remove and stop a PTY session by client_id.

        Args:
            client_id: Client identifier.
        """
        async with self._lock:
            if client_id in self._sessions:
                session = self._sessions.pop(client_id)
                logger.info(f"Removing PTY session for client {client_id}")
                # Stop session outside the lock
                asyncio.create_task(session.stop())

    async def cleanup_all(self):
        """Stop and remove all PTY sessions."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            for session in self._sessions.values():
                await session.stop()
            self._sessions.clear()

    def get_session_count(self) -> int:
        """Get count of active PTY sessions."""
        return len(self._sessions)

    def get_all_sessions(self) -> Dict[str, Tuple[str, str, float]]:
        """Get info about all active sessions.

        Returns:
            Dict mapping client_id to (container, session_name, last_heartbeat).
        """
        return {
            client_id: (session.container_name, session.session_name, session.last_heartbeat)
            for client_id, session in self._sessions.items()
        }


# Singleton instance
_pty_manager: Optional[PTYSessionManager] = None


def get_pty_manager() -> PTYSessionManager:
    """Get the global PTY session manager."""
    global _pty_manager
    if _pty_manager is None:
        _pty_manager = PTYSessionManager()
    return _pty_manager
