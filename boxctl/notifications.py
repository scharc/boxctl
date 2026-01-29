# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Notification client for sending alerts via boxctld.

Uses SSH control channel to communicate with the host daemon.
"""

import json
import os
import socket
import struct
import time
from pathlib import Path
from typing import Optional

from boxctl.host_config import get_config
from boxctl.paths import HostPaths


def _get_ssh_socket_path() -> Optional[Path]:
    """Find the SSH tunnel socket path."""
    env_socket = os.environ.get("BOXCTL_SSH_SOCKET")
    if env_socket:
        path = Path(env_socket)
        if path.exists():
            return path

    # Try XDG runtime location
    ssh_socket = HostPaths.ssh_socket()
    if ssh_socket.exists():
        return ssh_socket

    # Container mount location (fallback)
    container_path = Path("/run/boxctld/ssh.sock")
    if container_path.exists():
        return container_path

    return None


def send_notification(
    title: str,
    message: str,
    urgency: str = "normal",
    container: Optional[str] = None,
    session: Optional[str] = None,
    buffer: Optional[str] = None,
    enhance: bool = False,
) -> bool:
    """Send a notification via the boxctld daemon.

    Args:
        title: Notification title
        message: Notification message
        urgency: Urgency level (normal, low, critical)
        container: Container name (for task agent enhancement)
        session: Session name (for task agent enhancement)
        buffer: Session buffer content (for task agent enhancement)
        enhance: Enable task agent analysis

    Returns:
        True if notification sent successfully, False otherwise
    """
    try:
        import asyncssh
    except ImportError:
        return False

    ssh_socket = _get_ssh_socket_path()
    if not ssh_socket:
        return False

    # Build metadata if enhancement requested
    metadata = None
    if enhance:
        metadata = {
            "container": container,
            "session": session,
            "buffer": buffer,
        }

    # Determine timeout
    config = get_config()
    timeout = config.get("notifications", "timeout_enhanced" if enhance else "timeout")

    container_name = os.environ.get("BOXCTL_CONTAINER") or socket.gethostname()

    try:
        import asyncio

        async def send_notify():
            try:
                conn = await asyncssh.connect(
                    path=str(ssh_socket),
                    username=container_name,
                    known_hosts=None,
                )

                process = await conn.create_process(
                    term_type=None,
                    encoding=None,
                )

                # Build request message
                request = {
                    "kind": "request",
                    "type": "notify",
                    "id": f"notify-{time.time()}",
                    "ts": time.time(),
                    "payload": {
                        "title": title,
                        "message": message,
                        "urgency": urgency,
                    },
                }

                if metadata:
                    request["payload"]["metadata"] = metadata

                # Send with length prefix
                data = json.dumps(request).encode("utf-8")
                header = struct.pack(">I", len(data))
                process.stdin.write(header + data)
                await process.stdin.drain()

                # Read response with length prefix
                response_header = await asyncio.wait_for(
                    process.stdout.readexactly(4), timeout=timeout
                )
                response_length = struct.unpack(">I", response_header)[0]
                response_data = await asyncio.wait_for(
                    process.stdout.readexactly(response_length), timeout=timeout
                )
                response = json.loads(response_data.decode("utf-8"))

                conn.close()
                await conn.wait_closed()

                return response.get("payload", {}).get("ok", False)

            except Exception:
                return False

        # Handle both sync and async contexts
        try:
            loop = asyncio.get_running_loop()
            # Already in async context - run in a daemon thread to avoid blocking
            # Using daemon thread with join(timeout) instead of ThreadPoolExecutor
            # because TPE.shutdown(wait=True) blocks even after timeout
            import threading

            result_container = [False]

            def run_in_thread():
                try:
                    result_container[0] = asyncio.run(send_notify())
                except Exception:
                    result_container[0] = False

            thread = threading.Thread(target=run_in_thread, daemon=True)
            thread.start()
            thread.join(timeout=timeout + 5)

            # If thread is still alive, timeout occurred - return False
            # The daemon thread will be cleaned up when the process exits
            if thread.is_alive():
                return False
            return result_container[0]
        except RuntimeError:
            # No running loop - use asyncio.run
            return asyncio.run(send_notify())

    except Exception:
        return False
