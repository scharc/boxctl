# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""High-level session management for boxctl.

This module provides business logic for managing tmux sessions across containers,
including agent session detection, creation, and lifecycle management.

For low-level tmux operations, see core/tmux.py.
"""

from typing import TYPE_CHECKING, Dict, List, Optional

from boxctl.paths import ContainerDefaults
from boxctl.core.tmux import (
    capture_pane,
    create_session as tmux_create_session,
    list_tmux_sessions,
    resize_window,
    sanitize_tmux_name,
    send_keys,
    session_exists,
)

if TYPE_CHECKING:
    from boxctl.container import ContainerManager

# Known agent types for session filtering
AGENT_TYPES = ["claude", "superclaude", "codex", "supercodex", "gemini", "supergemini", "shell"]

# Agent commands mapping
AGENT_COMMANDS = {
    "claude": "/usr/local/bin/claude --settings /home/abox/.claude/settings.json --mcp-config /home/abox/.mcp.json",
    "superclaude": "/usr/local/bin/claude --settings /home/abox/.claude/settings-super.json --mcp-config /home/abox/.mcp.json --dangerously-skip-permissions",
    "codex": "/usr/local/bin/codex",
    "supercodex": "/usr/local/bin/codex --dangerously-bypass-approvals-and-sandbox",
    "gemini": "/usr/local/bin/gemini",
    "supergemini": "/usr/local/bin/gemini --non-interactive",
    "shell": "/bin/bash",
}


def get_sessions_for_container(container_name: str) -> List[Dict]:
    """Get tmux sessions for a specific container.

    Args:
        container_name: Name of the container

    Returns:
        List of session dicts with keys: name, windows, attached, created
    """
    from boxctl.container import ContainerManager

    try:
        manager = ContainerManager()
        if not manager.is_running(container_name):
            return []
        return list_tmux_sessions(manager, container_name)
    except Exception:
        return []


def get_all_sessions() -> List[Dict]:
    """Get tmux sessions across all running boxctl containers.

    Performance optimized: Uses ThreadPoolExecutor to parallelize docker exec
    calls across containers (reduces N sequential calls to ~1 parallel batch).

    Returns:
        List of session dicts with keys: container, name, windows, attached, created
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from boxctl.container import ContainerManager

    def fetch_sessions_for_container(
        manager: "ContainerManager", container_name: str
    ) -> List[Dict]:
        """Fetch sessions for a single container (runs in thread pool)."""
        if not container_name.startswith(ContainerDefaults.CONTAINER_PREFIX):
            return []
        project_name = ContainerDefaults.project_from_container(container_name)
        try:
            sessions = list_tmux_sessions(manager, container_name)
            return [
                {
                    "container": container_name,
                    "project": project_name,
                    "name": sess["name"],
                    "windows": sess["windows"],
                    "attached": sess["attached"],
                    "created": sess.get("created", ""),
                }
                for sess in sessions
            ]
        except Exception:
            return []

    try:
        manager = ContainerManager()
        all_containers = manager.client.containers.list(
            filters={"name": ContainerDefaults.CONTAINER_PREFIX}
        )

        if not all_containers:
            return []

        # Parallelize docker exec calls across containers
        all_sessions = []
        with ThreadPoolExecutor(max_workers=min(len(all_containers), 10)) as executor:
            futures = {
                executor.submit(fetch_sessions_for_container, manager, c.name): c.name
                for c in all_containers
            }
            for future in as_completed(futures):
                sessions = future.result()
                all_sessions.extend(sessions)

        return all_sessions
    except Exception:
        return []


def capture_session_output(container_name: str, session_name: str, lines: int = 50) -> str:
    """Capture recent output from a tmux session.

    Args:
        container_name: Name of the container
        session_name: Name of the tmux session
        lines: Number of lines to capture

    Returns:
        Captured output as string
    """
    from boxctl.container import ContainerManager

    try:
        manager = ContainerManager()
        if not manager.is_running(container_name):
            return ""
        return capture_pane(manager, container_name, session_name, lines)
    except Exception:
        return ""


def send_keys_to_session(
    container_name: str, session_name: str, keys: str, literal: bool = True
) -> bool:
    """Send keystrokes to a tmux session.

    Args:
        container_name: Name of the container
        session_name: Name of the tmux session
        keys: Keys to send
        literal: If True, send as literal text; if False, interpret special keys

    Returns:
        True if successful, False otherwise
    """
    from boxctl.container import ContainerManager

    try:
        manager = ContainerManager()
        if not manager.is_running(container_name):
            return False
        return send_keys(manager, container_name, session_name, keys, literal)
    except Exception:
        return False


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
    from boxctl.container import ContainerManager

    try:
        manager = ContainerManager()
        if not manager.is_running(container_name):
            return False
        return resize_window(manager, container_name, session_name, width, height)
    except Exception:
        return False


def get_agent_sessions(
    manager: "ContainerManager",
    container_name: str,
    agent_type: Optional[str] = None,
) -> List[Dict]:
    """Get tmux sessions filtered by agent type.

    Args:
        manager: ContainerManager instance
        container_name: Name of container
        agent_type: Optional agent type to filter (e.g., 'superclaude', 'codex')
                   If None, returns all agent sessions

    Returns:
        List of session dicts with keys: name, agent_type, identifier, windows, attached, created
    """
    all_sessions = list_tmux_sessions(manager, container_name)

    result = []
    for session in all_sessions:
        session_name = session["name"]

        # Parse session name to extract agent_type and identifier
        matched_agent = None
        identifier = None

        for atype in AGENT_TYPES:
            if session_name == atype:
                # Default session (no suffix)
                matched_agent = atype
                identifier = "default"
                break
            elif session_name.startswith(f"{atype}-"):
                # Named or numbered session
                matched_agent = atype
                identifier = session_name[len(atype) + 1 :]
                break

        # Skip sessions that don't match known agents
        if matched_agent is None:
            continue

        # Filter by agent_type if specified
        if agent_type and matched_agent != agent_type:
            continue

        result.append(
            {
                "name": session_name,
                "agent_type": matched_agent,
                "identifier": identifier,
                "windows": session["windows"],
                "attached": session["attached"],
                "created": session.get("created", ""),
            }
        )

    return result


def generate_session_name(
    manager: "ContainerManager",
    container_name: str,
    agent_type: str,
    identifier: Optional[str] = None,
) -> str:
    """Generate a unique session name for an agent instance.

    Args:
        manager: ContainerManager instance
        container_name: Name of container
        agent_type: Agent type (e.g., 'superclaude', 'codex')
        identifier: Optional identifier (can be name or number)
                   If None, auto-generates next available number

    Returns:
        Session name in format: agent_type-identifier
    """
    # If identifier provided, sanitize and return
    if identifier:
        sanitized = sanitize_tmux_name(identifier)
        return f"{agent_type}-{sanitized}"

    # Auto-number: find next available number
    sessions = get_agent_sessions(manager, container_name, agent_type)

    # Extract existing numbers
    used_numbers = set()
    for session in sessions:
        ident = session["identifier"]
        if ident == "default":
            continue
        try:
            num = int(ident)
            used_numbers.add(num)
        except ValueError:
            continue

    # Find lowest available number starting from 1
    next_num = 1
    while next_num in used_numbers:
        next_num += 1

    return f"{agent_type}-{next_num}"


def create_agent_session(
    container_name: str,
    agent_type: str,
    identifier: Optional[str] = None,
) -> Dict[str, str]:
    """Create a new tmux session for an agent.

    Args:
        container_name: Name of the container
        agent_type: Type of agent (claude, superclaude, codex, supercodex, gemini, supergemini, shell)
        identifier: Optional identifier for the session (if None, auto-numbers)

    Returns:
        Dict with keys: success (bool), session_name (str), message (str)
    """
    from boxctl.container import ContainerManager

    try:
        manager = ContainerManager()
        if not manager.is_running(container_name):
            return {"success": False, "session_name": "", "message": "Container not running"}

        if not manager.wait_for_ready(container_name, timeout_s=90.0):
            return {
                "success": False,
                "session_name": "",
                "message": "Container is still initializing. MCP packages are being installed. Please wait up to 90 seconds and try again.",
            }

        # Generate session name
        session_name = generate_session_name(manager, container_name, agent_type, identifier)

        # Check if session already exists
        if session_exists(manager, container_name, session_name):
            return {
                "success": False,
                "session_name": session_name,
                "message": "Session already exists",
            }

        # Get agent command
        command = AGENT_COMMANDS.get(agent_type, "/bin/bash")

        # Create tmux session
        if tmux_create_session(manager, container_name, session_name, command):
            return {
                "success": True,
                "session_name": session_name,
                "message": "Session created successfully",
            }
        else:
            return {"success": False, "session_name": "", "message": "Failed to create session"}

    except Exception as e:
        return {"success": False, "session_name": "", "message": str(e)}
