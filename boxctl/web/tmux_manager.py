# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tmux session management for web UI using existing boxctl helpers."""

import logging
import subprocess
from typing import List, Dict, Optional
from boxctl.container import ContainerManager
from boxctl.paths import BinPaths, ContainerPaths, ContainerDefaults
from boxctl.cli.helpers import _get_tmux_sessions, _get_tmux_socket
from boxctl.host_config import get_config

logger = logging.getLogger(__name__)


def _build_tmux_cmd(socket_path: Optional[str], *args: str) -> list[str]:
    """Build tmux command with optional socket path.

    Args:
        socket_path: Optional tmux socket path (inserted as -S <path>)
        *args: Tmux subcommand and arguments

    Returns:
        Complete tmux command as list
    """
    if socket_path:
        return [BinPaths.TMUX, "-S", socket_path, *args]
    return [BinPaths.TMUX, *args]


def _tmux_cmd(args: list[str]) -> tuple[int, str]:
    """Execute tmux command directly (fast, in-container).

    Args:
        args: Tmux command arguments

    Returns:
        Tuple of (exit_code, output)
    """
    try:
        config = get_config()
        timeout = config.get("timeouts", "tmux_command", default=2.0)
        result = subprocess.run(
            [BinPaths.TMUX] + args, capture_output=True, text=True, timeout=timeout
        )
        return (result.returncode, result.stdout)
    except Exception:
        return (1, "")


def _get_container_env() -> dict:
    """Get standard container environment variables for tmux commands.

    Returns:
        Dict of environment variables for container exec
    """
    return {"HOME": ContainerPaths.HOME, "USER": ContainerPaths.USER, "TMUX_TMPDIR": "/tmp"}


def get_sessions_for_container(container_name: str) -> List[Dict]:
    """Get tmux sessions for a specific container.

    Args:
        container_name: Name of the container

    Returns:
        List of session dicts with keys: name, windows, attached, created
    """
    try:
        manager = ContainerManager()
        if not manager.is_running(container_name):
            return []
        return _get_tmux_sessions(manager, container_name)
    except Exception:
        return []


def get_all_sessions() -> List[Dict]:
    """Get tmux sessions across all running boxctl containers.

    Returns:
        List of session dicts with keys: container, name, windows, attached, created
    """
    try:
        manager = ContainerManager()
        all_containers = manager.client.containers.list(
            filters={"name": ContainerDefaults.CONTAINER_PREFIX}
        )

        all_sessions = []
        for container in all_containers:
            container_name = container.name
            if not container_name.startswith(ContainerDefaults.CONTAINER_PREFIX):
                continue

            # Skip test containers to avoid hanging on broken ones
            if any(x in container_name for x in ["-test", "_test"]):
                continue

            try:
                sessions = _get_tmux_sessions(manager, container_name)
                for sess in sessions:
                    all_sessions.append(
                        {
                            "container": container_name,
                            "name": sess["name"],
                            "windows": sess["windows"],
                            "attached": sess["attached"],
                            "created": sess.get("created", ""),
                        }
                    )
            except Exception as e:
                # Skip containers that fail (broken, stale, etc.)
                logger.warning(f"Skipping container {container_name}: {e}")
                continue

        return all_sessions
    except Exception:
        return []


def capture_session_output(
    container_name: str, session_name: str, include_escape: bool = True
) -> str:
    """Capture current visible pane from a tmux session including scrollback history.

    Args:
        container_name: Name of the container
        session_name: Name of the tmux session
        include_escape: Whether to include escape sequences

    Returns:
        Captured pane output as string (includes scrollback history)
    """
    try:
        manager = ContainerManager()
        if not manager.is_running(container_name):
            return ""

        socket_path = _get_tmux_socket(manager, container_name)

        # Capture visible pane with escape sequences AND scrollback history
        # -e includes escape sequences (colors, cursor position, etc.)
        # -p prints to stdout
        # -S -10000 captures last 10,000 lines of scrollback history (tmux default history-limit is 2000)
        escape_flag = ["-e"] if include_escape else []
        tmux_cmd = _build_tmux_cmd(
            socket_path, "capture-pane", *escape_flag, "-p", "-S", "-10000", "-t", session_name
        )

        exit_code, output = manager.exec_command(
            container_name,
            tmux_cmd,
            environment=_get_container_env(),
            user=ContainerPaths.USER,
        )

        return output if exit_code == 0 else ""
    except Exception:
        return ""


def send_keys_to_session_fast(session_name: str, keys: str, literal: bool = True) -> bool:
    """Send keystrokes to tmux session - FAST version (direct tmux call).

    Args:
        session_name: Name of the tmux session
        keys: Keys to send
        literal: If True, use -l flag for literal text

    Returns:
        True if successful
    """
    try:
        if literal:
            args = ["send-keys", "-l", "-t", session_name, keys]
        else:
            args = ["send-keys", "-t", session_name, keys]

        exit_code, _ = _tmux_cmd(args)
        return exit_code == 0
    except Exception:
        return False


def send_keys_to_session(
    container_name: str, session_name: str, keys: str, literal: bool = True
) -> bool:
    """Send keystrokes to a tmux session.

    Args:
        container_name: Name of the container
        session_name: Name of the tmux session
        keys: Keys to send (literal text or tmux key name)
        literal: If True, use -l flag for literal text. If False, interpret as tmux key names.

    Returns:
        True if successful, False otherwise
    """
    try:
        manager = ContainerManager()
        if not manager.is_running(container_name):
            return False

        socket_path = _get_tmux_socket(manager, container_name)

        # Build tmux command (-l flag for literal text input)
        literal_flag = ["-l"] if literal else []
        tmux_cmd = _build_tmux_cmd(
            socket_path, "send-keys", *literal_flag, "-t", session_name, keys
        )

        exit_code, _ = manager.exec_command(
            container_name,
            tmux_cmd,
            environment=_get_container_env(),
            user=ContainerPaths.USER,
        )

        return exit_code == 0
    except Exception:
        return False


def capture_session_output_fast(session_name: str) -> str:
    """Capture visible pane including scrollback - FAST version (direct tmux call).

    Args:
        session_name: Name of the tmux session

    Returns:
        Captured output with ANSI escape codes (colors preserved) and scrollback history
    """
    try:
        # -e flag includes ANSI escape sequences for colors
        # -S -10000 captures last 10,000 lines of scrollback history
        args = ["capture-pane", "-e", "-p", "-S", "-10000", "-t", session_name]
        exit_code, output = _tmux_cmd(args)
        return output if exit_code == 0 else ""
    except Exception:
        return ""


def get_cursor_position(container_name: str, session_name: str) -> tuple[int, int]:
    """Get cursor position in tmux session.

    Args:
        container_name: Name of the container
        session_name: Name of the tmux session

    Returns:
        Tuple of (cursor_x, cursor_y) positions (0-indexed)
    """
    try:
        manager = ContainerManager()
        if not manager.is_running(container_name):
            return (0, 0)

        socket_path = _get_tmux_socket(manager, container_name)

        # Get cursor position using tmux display-message
        tmux_cmd = _build_tmux_cmd(
            socket_path, "display-message", "-p", "-t", session_name, "#{cursor_x},#{cursor_y}"
        )

        exit_code, output = manager.exec_command(
            container_name, tmux_cmd, environment=_get_container_env()
        )

        if exit_code == 0 and output:
            parts = output.strip().split(",")
            if len(parts) == 2:
                return (int(parts[0]), int(parts[1]))
        return (0, 0)
    except Exception:
        return (0, 0)


def get_session_dimensions_fast(session_name: str) -> tuple[int, int]:
    """Get session dimensions - FAST version (direct tmux call).

    Args:
        session_name: Name of the tmux session

    Returns:
        Tuple of (width, height)
    """
    try:
        config = get_config()
        default_width = config.get("terminal", "default_width", default=80)
        default_height = config.get("terminal", "default_height", default=24)

        args = ["display-message", "-p", "-t", session_name, "#{window_width} #{window_height}"]
        exit_code, output = _tmux_cmd(args)

        if exit_code == 0 and output:
            parts = output.strip().split()
            if len(parts) == 2:
                return (int(parts[0]), int(parts[1]))

        return (default_width, default_height)
    except Exception:
        config = get_config()
        default_width = config.get("terminal", "default_width", default=80)
        default_height = config.get("terminal", "default_height", default=24)
        return (default_width, default_height)


def resize_session_fast(session_name: str, width: int, height: int) -> bool:
    """Resize session - FAST version (direct tmux call).

    Args:
        session_name: Name of the tmux session
        width: New width
        height: New height

    Returns:
        True if successful
    """
    try:
        # Try pane resize first
        args = ["resize-pane", "-t", f"{session_name}:0.0", "-x", str(width), "-y", str(height)]
        exit_code, _ = _tmux_cmd(args)

        if exit_code != 0:
            # Fallback to window resize
            args = ["resize-window", "-t", session_name, "-x", str(width), "-y", str(height)]
            exit_code, _ = _tmux_cmd(args)

        return exit_code == 0
    except Exception:
        return False


def get_session_dimensions(container_name: str, session_name: str) -> tuple[int, int]:
    """Get the dimensions of a tmux session.

    Args:
        container_name: Name of the container
        session_name: Name of the tmux session

    Returns:
        Tuple of (width, height) in characters, or configured defaults
    """
    try:
        config = get_config()
        default_width = config.get("terminal", "default_width", default=80)
        default_height = config.get("terminal", "default_height", default=24)

        manager = ContainerManager()
        if not manager.is_running(container_name):
            return (default_width, default_height)

        socket_path = _get_tmux_socket(manager, container_name)

        # Get window dimensions using display-message
        tmux_cmd = _build_tmux_cmd(
            socket_path,
            "display-message",
            "-p",
            "-t",
            session_name,
            "#{window_width} #{window_height}",
        )

        exit_code, output = manager.exec_command(
            container_name,
            tmux_cmd,
            environment=_get_container_env(),
            user=ContainerPaths.USER,
        )

        if exit_code == 0 and output:
            parts = output.strip().split()
            if len(parts) == 2:
                width = int(parts[0])
                height = int(parts[1])
                return (width, height)

        return (default_width, default_height)
    except Exception:
        config = get_config()
        default_width = config.get("terminal", "default_width", default=80)
        default_height = config.get("terminal", "default_height", default=24)
        return (default_width, default_height)


def resize_session(container_name: str, session_name: str, width: int, height: int) -> bool:
    """Resize a tmux session.

    Args:
        container_name: Name of the container
        session_name: Name of the tmux session
        width: New width in columns
        height: New height in rows

    Returns:
        True if successful, False otherwise
    """
    try:
        manager = ContainerManager()
        if not manager.is_running(container_name):
            return False

        socket_path = _get_tmux_socket(manager, container_name)

        # Use resize-pane with -x and -y to set exact dimensions
        tmux_cmd = _build_tmux_cmd(
            socket_path,
            "resize-pane",
            "-t",
            f"{session_name}:0.0",
            "-x",
            str(width),
            "-y",
            str(height),
        )

        exit_code, output = manager.exec_command(
            container_name,
            tmux_cmd,
            environment=_get_container_env(),
            user=ContainerPaths.USER,
        )

        if exit_code != 0:
            # Fallback to resize-window if pane resize fails
            tmux_cmd = _build_tmux_cmd(
                socket_path,
                "resize-window",
                "-t",
                session_name,
                "-x",
                str(width),
                "-y",
                str(height),
            )

            exit_code, _ = manager.exec_command(
                container_name,
                tmux_cmd,
                environment=_get_container_env(),
                user=ContainerPaths.USER,
            )

        return exit_code == 0
    except Exception as e:
        return False
