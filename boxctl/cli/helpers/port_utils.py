# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Port conflict detection utilities for CLI.

Provides functions to check port availability before container start
and handle conflicts with user prompts.
"""

import json
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

console = Console()


def _get_boxctld_socket_path() -> Path:
    """Get the boxctld IPC socket path (platform-aware: macOS vs Linux)."""
    from boxctl.host_config import get_config

    return get_config().socket_path


def _send_boxctld_command(command: dict) -> dict:
    """Send a command to boxctld and get response."""
    socket_path = _get_boxctld_socket_path()
    if not socket_path.exists():
        return {"ok": False, "error": "boxctld not running"}

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(socket_path))
        sock.settimeout(5.0)
        sock.sendall((json.dumps(command) + "\n").encode())

        # Read response
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

        if data:
            return json.loads(data.decode().strip())
        return {"ok": False, "error": "No response from boxctld"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        sock.close()


@dataclass
class PortConflict:
    """Represents a port conflict."""

    port: int
    container_port: int
    direction: str  # "exposed" or "forwarded"
    blocker_type: str  # "boxctl" or "external"
    blocker_container: Optional[str] = None  # if boxctl
    blocker_process: Optional[str] = None  # if external
    blocker_pid: Optional[int] = None  # if external


def check_port_available(port: int) -> Dict[str, Any]:
    """Check if a port is available on the host.

    Args:
        port: The port number to check

    Returns:
        Dict with keys:
            - ok: bool
            - available: bool
            - used_by: dict with blocker info or None
    """
    response = _send_boxctld_command(
        {
            "action": "check_port",
            "port": port,
        }
    )

    if not response.get("ok"):
        # Daemon not available, try to check locally with socket
        return _check_port_locally(port)

    return response


def _check_port_locally(port: int) -> Dict[str, Any]:
    """Fallback port check when daemon is unavailable.

    Just tries to bind to the port to see if it's available.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        sock.bind(("127.0.0.1", port))
        sock.close()
        return {"ok": True, "available": True, "used_by": None}
    except OSError:
        return {
            "ok": True,
            "available": False,
            "used_by": {"type": "external", "process": "unknown", "pid": None},
        }


def check_configured_ports(
    project_dir: Path,
    container_name: str,
) -> List[PortConflict]:
    """Check all configured ports for conflicts.

    Args:
        project_dir: Path to the project directory
        container_name: Name of the container being started

    Returns:
        List of PortConflict objects for ports that have conflicts
    """
    from boxctl.config import ProjectConfig

    conflicts = []

    try:
        config = ProjectConfig(project_dir)
    except Exception:
        return conflicts

    # Check exposed ports (container -> host)
    for port_spec in config.ports_host:
        host_port, container_port = _parse_port_spec(port_spec)
        if host_port is None:
            continue

        result = check_port_available(host_port)
        if result.get("available") is False:
            used_by = result.get("used_by", {})
            # Skip if it's our own container
            if used_by.get("type") == "boxctl" and used_by.get("container") == container_name:
                continue

            conflicts.append(
                PortConflict(
                    port=host_port,
                    container_port=container_port,
                    direction="exposed",
                    blocker_type=used_by.get("type", "external"),
                    blocker_container=used_by.get("container"),
                    blocker_process=used_by.get("process"),
                    blocker_pid=used_by.get("pid"),
                )
            )

    # Check forwarded ports (host -> container)
    for port_config in config.ports_container:
        host_port, container_port = _parse_forward_config(port_config)
        if host_port is None:
            continue

        result = check_port_available(host_port)
        if result.get("available") is False:
            used_by = result.get("used_by", {})
            # Skip if it's our own container
            if used_by.get("type") == "boxctl" and used_by.get("container") == container_name:
                continue

            conflicts.append(
                PortConflict(
                    port=host_port,
                    container_port=container_port,
                    direction="forwarded",
                    blocker_type=used_by.get("type", "external"),
                    blocker_container=used_by.get("container"),
                    blocker_process=used_by.get("process"),
                    blocker_pid=used_by.get("pid"),
                )
            )

    return conflicts


def _parse_port_spec(port_spec: str) -> tuple:
    """Parse a port spec like '8080' or '3000:8080'.

    Returns:
        (host_port, container_port) tuple, or (None, None) on error
    """
    try:
        if isinstance(port_spec, int):
            return (port_spec, port_spec)
        parts = str(port_spec).split(":")
        if len(parts) == 1:
            port = int(parts[0])
            return (port, port)
        elif len(parts) == 2:
            return (int(parts[0]), int(parts[1]))
        elif len(parts) == 3:
            # host_ip:host_port:container_port
            return (int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        pass
    return (None, None)


def _parse_forward_config(port_config) -> tuple:
    """Parse a forward port config (dict or simple spec).

    Returns:
        (host_port, container_port) tuple, or (None, None) on error
    """
    try:
        if isinstance(port_config, dict):
            host_port = port_config.get("port")
            container_port = port_config.get("container_port", host_port)
            return (host_port, container_port)
        else:
            return _parse_port_spec(port_config)
    except Exception:
        pass
    return (None, None)


def format_conflict_message(conflict: PortConflict) -> str:
    """Format a conflict for display to user."""
    from boxctl import container_naming

    direction_desc = "exposed" if conflict.direction == "exposed" else "forwarded"

    if conflict.blocker_type == "boxctl":
        # Extract just the project name for cleaner display
        display_name = (
            container_naming.extract_project_name(conflict.blocker_container)
            or conflict.blocker_container
        )
        return (
            f"Port {conflict.port} ({direction_desc}) is used by "
            f"boxctl: [cyan]{display_name}[/cyan]"
        )
    else:
        process_info = conflict.blocker_process or "unknown process"
        if conflict.blocker_pid:
            process_info += f" (pid {conflict.blocker_pid})"
        return (
            f"Port {conflict.port} ({direction_desc}) is used by "
            f"[yellow]{process_info}[/yellow]"
        )


def release_port_from_container(container_name: str, port: int, direction: str) -> bool:
    """Release a port from another boxctl container.

    Args:
        container_name: The container currently holding the port
        port: The host port to release
        direction: "exposed" or "forwarded"

    Returns:
        True if successfully released
    """
    if direction == "exposed":
        action = "remove_host_port"
    else:
        action = "remove_container_port"

    response = _send_boxctld_command(
        {
            "action": action,
            "container": container_name,
            "host_port": port,
        }
    )

    return response.get("ok", False)
