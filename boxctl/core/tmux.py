# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Low-level tmux operations for host-side use (via docker exec).

This module provides the canonical implementation of tmux operations
that run on the host and execute commands inside containers.

For container-internal tmux operations (no docker exec), see agentctl/helpers.py.
"""

from typing import TYPE_CHECKING, Dict, List, Optional

from boxctl.paths import BinPaths, ContainerPaths
from boxctl.utils.exceptions import TmuxError
from boxctl.utils.logging import get_logger

if TYPE_CHECKING:
    from boxctl.container import ContainerManager

logger = get_logger(__name__)


def sanitize_tmux_name(name: str) -> str:
    """Sanitize a name for use as tmux session name.

    Args:
        name: Raw name string

    Returns:
        Sanitized name safe for tmux (alphanumeric, hyphens, underscores only)
    """
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in name)
    return cleaned.strip("-") or "boxctl"


def get_tmux_socket_path(manager: "ContainerManager", container_name: str) -> Optional[str]:
    """Get tmux socket path for container.

    Args:
        manager: ContainerManager instance
        container_name: Container name

    Returns:
        Socket path or None if not available
    """
    from boxctl.container import get_abox_environment

    exit_code, output = manager.exec_command(
        container_name,
        ["/usr/bin/id", "-u"],
        environment=get_abox_environment(container_name=container_name),
        user=ContainerPaths.USER,
    )
    if exit_code != 0:
        return None

    uid = output.strip()
    return f"/tmp/tmux-{uid}/default" if uid else None


def list_tmux_sessions(manager: "ContainerManager", container_name: str) -> List[Dict]:
    """List all tmux sessions in container.

    Args:
        manager: ContainerManager instance
        container_name: Container name

    Returns:
        List of session dicts with keys: name, windows, attached, created

    Raises:
        TmuxError: If tmux command fails unexpectedly
    """
    from boxctl.container import get_abox_environment

    fmt = "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_created_string}"
    socket_path = get_tmux_socket_path(manager, container_name)

    tmux_cmd = [BinPaths.TMUX, "list-sessions", "-F", fmt]
    if socket_path:
        tmux_cmd = [BinPaths.TMUX, "-S", socket_path, "list-sessions", "-F", fmt]

    exit_code, output = manager.exec_command(
        container_name,
        tmux_cmd,
        environment=get_abox_environment(include_tmux=True, container_name=container_name),
        user=ContainerPaths.USER,
    )

    if exit_code != 0:
        lowered = output.lower()
        if any(
            phrase in lowered
            for phrase in ["no server running", "failed to connect", "error connecting"]
        ):
            return []

        logger.error(f"Failed to list tmux sessions in {container_name}")
        if output.strip():
            logger.debug(f"TMux error output: {output.strip()}")
        raise TmuxError(f"Failed to list sessions: {output}")

    sessions = []
    for line in output.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 3:
            parts.append("")
        if len(parts) != 4:
            continue

        name, windows, attached, created = parts
        sessions.append(
            {
                "name": name,
                "windows": windows,
                "attached": attached == "1",
                "created": created,
            }
        )

    return sessions


def session_exists(manager: "ContainerManager", container_name: str, session_name: str) -> bool:
    """Check if tmux session exists.

    Args:
        manager: ContainerManager instance
        container_name: Container name
        session_name: Session name to check

    Returns:
        True if session exists
    """
    try:
        sessions = list_tmux_sessions(manager, container_name)
        return any(s["name"] == session_name for s in sessions)
    except TmuxError:
        return False


def capture_pane(
    manager: "ContainerManager",
    container_name: str,
    session_name: str,
    lines: int = 50,
) -> str:
    """Capture recent output from a tmux session.

    Args:
        manager: ContainerManager instance
        container_name: Container name
        session_name: Session name
        lines: Number of lines to capture (default 50)

    Returns:
        Captured output as string, empty string on failure
    """
    from boxctl.container import get_abox_environment

    socket_path = get_tmux_socket_path(manager, container_name)
    tmux_cmd = [BinPaths.TMUX, "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"]
    if socket_path:
        tmux_cmd = [
            BinPaths.TMUX,
            "-S",
            socket_path,
            "capture-pane",
            "-t",
            session_name,
            "-p",
            "-S",
            f"-{lines}",
        ]

    exit_code, output = manager.exec_command(
        container_name,
        tmux_cmd,
        environment=get_abox_environment(include_tmux=True, container_name=container_name),
        user=ContainerPaths.USER,
    )

    return output if exit_code == 0 else ""


def send_keys(
    manager: "ContainerManager",
    container_name: str,
    session_name: str,
    keys: str,
    literal: bool = True,
) -> bool:
    """Send keys to a tmux session.

    Args:
        manager: ContainerManager instance
        container_name: Container name
        session_name: Session name
        keys: Keys or text to send
        literal: If True, send as literal text (default); if False, interpret special keys

    Returns:
        True if successful
    """
    from boxctl.container import get_abox_environment

    socket_path = get_tmux_socket_path(manager, container_name)
    tmux_cmd = [BinPaths.TMUX, "send-keys", "-t", session_name]
    if literal:
        tmux_cmd.append("-l")
    tmux_cmd.append(keys)

    if socket_path:
        tmux_cmd = [BinPaths.TMUX, "-S", socket_path] + tmux_cmd[1:]

    exit_code, _ = manager.exec_command(
        container_name,
        tmux_cmd,
        environment=get_abox_environment(include_tmux=True, container_name=container_name),
        user=ContainerPaths.USER,
    )

    return exit_code == 0


def resize_window(
    manager: "ContainerManager",
    container_name: str,
    session_name: str,
    width: int,
    height: int,
) -> bool:
    """Resize a tmux window.

    Args:
        manager: ContainerManager instance
        container_name: Container name
        session_name: Session name
        width: New width in columns
        height: New height in rows

    Returns:
        True if successful
    """
    from boxctl.container import get_abox_environment

    socket_path = get_tmux_socket_path(manager, container_name)
    tmux_cmd = [
        BinPaths.TMUX,
        "resize-window",
        "-t",
        session_name,
        "-x",
        str(width),
        "-y",
        str(height),
    ]
    if socket_path:
        tmux_cmd = [BinPaths.TMUX, "-S", socket_path] + tmux_cmd[1:]

    exit_code, _ = manager.exec_command(
        container_name,
        tmux_cmd,
        environment=get_abox_environment(include_tmux=True, container_name=container_name),
        user=ContainerPaths.USER,
    )

    return exit_code == 0


def create_session(
    manager: "ContainerManager",
    container_name: str,
    session_name: str,
    command: str,
    working_dir: str = "/workspace",
) -> bool:
    """Create a new tmux session.

    Args:
        manager: ContainerManager instance
        container_name: Container name
        session_name: Session name to create
        command: Command to run in the session
        working_dir: Working directory (default /workspace)

    Returns:
        True if successful
    """
    from boxctl.container import get_abox_environment

    socket_path = get_tmux_socket_path(manager, container_name)
    tmux_cmd = [
        BinPaths.TMUX,
        "new-session",
        "-d",
        "-s",
        session_name,
        "-c",
        working_dir,
        "/bin/bash",
        "-lc",
        command,
    ]
    if socket_path:
        tmux_cmd = [BinPaths.TMUX, "-S", socket_path] + tmux_cmd[1:]

    exit_code, output = manager.exec_command(
        container_name,
        tmux_cmd,
        environment=get_abox_environment(include_tmux=True, container_name=container_name),
        user=ContainerPaths.USER,
    )

    if exit_code != 0:
        logger.error(f"Failed to create tmux session {session_name}: {output}")
        return False

    return True
