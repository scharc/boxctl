"""Helper functions for agentctl tmux session management"""

import os
import subprocess
from typing import List, Dict, Optional

from boxctl.utils.terminal import reset_terminal

# Timeout for tmux operations (seconds)
TMUX_TIMEOUT = 5


def _get_tmux_socket() -> Optional[str]:
    """Get the tmux socket path from TMUX environment variable.

    TMUX env var format: /path/to/socket,pid,session_index
    Returns the socket path or None if not in tmux.
    """
    tmux_env = os.environ.get("TMUX")
    if tmux_env:
        # Extract socket path (first comma-separated field)
        return tmux_env.split(",")[0]
    return None


def _tmux_cmd(args: List[str]) -> List[str]:
    """Build tmux command with socket if available.

    Ensures all tmux commands use the same server as the current session.
    """
    socket = _get_tmux_socket()
    if socket:
        return ["tmux", "-S", socket] + args
    return ["tmux"] + args


def get_tmux_sessions() -> List[Dict[str, any]]:
    """Get list of tmux sessions with details

    Returns:
        List of dicts with keys: name, windows, attached, created
    """
    fmt = "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_created_string}"
    try:
        result = subprocess.run(
            _tmux_cmd(["list-sessions", "-F", fmt]),
            capture_output=True,
            text=True,
            check=False,
            timeout=TMUX_TIMEOUT,
        )
        if result.returncode != 0:
            return []

        sessions = []
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                sessions.append(
                    {
                        "name": parts[0],
                        "windows": int(parts[1]),
                        "attached": parts[2] == "1",
                        "created": parts[3] if len(parts) > 3 else "",
                    }
                )
        return sessions
    except Exception:
        return []


def session_exists(name: str) -> bool:
    """Check if tmux session exists

    Args:
        name: Session name to check

    Returns:
        True if session exists, False otherwise
    """
    try:
        result = subprocess.run(
            _tmux_cmd(["has-session", "-t", name]),
            capture_output=True,
            check=False,
            timeout=TMUX_TIMEOUT,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def capture_pane(session: str, lines: int) -> str:
    """Capture last N lines from session pane

    Args:
        session: Session name
        lines: Number of lines to capture

    Returns:
        Captured output as string
    """
    try:
        result = subprocess.run(
            _tmux_cmd(["capture-pane", "-t", session, "-p", "-S", f"-{lines}"]),
            capture_output=True,
            text=True,
            check=False,
            timeout=TMUX_TIMEOUT,
        )
        return result.stdout if result.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        return ""


def get_agent_command(agent: str) -> str:
    """Get the command to run for an agent

    Args:
        agent: Agent name (claude, codex, etc.)

    Returns:
        Command path to execute
    """
    agent_commands = {
        "claude": "/usr/local/bin/claude",
        "superclaude": "/usr/local/bin/claude",
        "codex": "/usr/local/bin/codex",
        "supercodex": "/usr/local/bin/codex",
        "gemini": "/usr/local/bin/gemini",
        "supergemini": "/usr/local/bin/gemini",
        "shell": "/bin/bash",
    }
    return agent_commands.get(agent, "/bin/bash")


def kill_session(name: str) -> bool:
    """Kill a tmux session

    Args:
        name: Session name to kill

    Returns:
        True if successful, False otherwise
    """
    try:
        result = subprocess.run(
            _tmux_cmd(["kill-session", "-t", name]),
            capture_output=True,
            check=False,
            timeout=TMUX_TIMEOUT,
        )
        if result.returncode == 0:
            # Reset terminal to disable mouse mode in case caller was attached
            reset_terminal()
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def detach_client() -> bool:
    """Detach current tmux client

    Returns:
        True if successful, False otherwise
    """
    try:
        result = subprocess.run(
            _tmux_cmd(["detach-client"]), capture_output=True, check=False, timeout=TMUX_TIMEOUT
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def send_keys_to_session(session: str, keys: str, literal: bool = False) -> bool:
    """Send keys/text to a tmux session

    Args:
        session: Session name
        keys: Keys or text to send
        literal: If True, send as literal text; if False, interpret special keys

    Returns:
        True if successful, False otherwise
    """
    args = ["send-keys", "-t", session]
    if literal:
        args.append("-l")
    args.append(keys)

    try:
        result = subprocess.run(
            _tmux_cmd(args), capture_output=True, check=False, timeout=TMUX_TIMEOUT
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def get_current_tmux_session() -> Optional[str]:
    """Get the name of the current tmux session (if in one)

    Returns:
        Session name if in a tmux session, None otherwise
    """
    tmux_var = os.environ.get("TMUX")
    if not tmux_var:
        return None

    # TMUX variable format: /tmp/tmux-1000/default,<pane_id>,<session_id>
    # We need to query tmux for the session name
    try:
        result = subprocess.run(
            _tmux_cmd(["display-message", "-p", "#{session_name}"]),
            capture_output=True,
            text=True,
            check=False,
            timeout=TMUX_TIMEOUT,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        pass
    return None
