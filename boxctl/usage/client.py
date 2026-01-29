# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Unified client for agent usage tracking.

Provides a single API that:
- Tries to communicate with the host service via control channel
- Falls back to local file storage when service is unavailable

This module is designed to work both inside containers (with service)
and standalone (without service).
"""

import json
import os
import socket
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple

from boxctl.paths import HostPaths, TempPaths

# Local state file (fallback when service unavailable)
LOCAL_STATE_DIR = HostPaths.usage_state_file().parent
LOCAL_STATE_FILE = HostPaths.usage_state_file()

# Local IPC socket path (container client listens here)
LOCAL_IPC_SOCKET = Path(TempPaths.LOCAL_IPC_SOCKET)

# Fallback chains
FALLBACK_CHAINS = {
    "superclaude": ["supercodex", "supergemini", "superqwen"],
    "supercodex": ["superclaude", "supergemini", "superqwen"],
    "supergemini": ["superclaude", "supercodex", "superqwen"],
    "superqwen": ["superclaude", "supercodex", "supergemini"],
    "claude": ["codex", "gemini", "qwen"],
    "codex": ["claude", "gemini", "qwen"],
    "gemini": ["claude", "codex", "qwen"],
    "qwen": ["claude", "codex", "gemini"],
}


def _ensure_local_state_dir() -> None:
    """Ensure the local state directory exists."""
    LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)


def _load_local_state() -> dict:
    """Load state from local file."""
    if not LOCAL_STATE_FILE.exists():
        return {}
    try:
        return json.loads(LOCAL_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_local_state(state: dict) -> None:
    """Save state to local file."""
    _ensure_local_state_dir()
    LOCAL_STATE_FILE.write_text(json.dumps(state, indent=2))


def _send_to_service(action: str, payload: dict, timeout: float = 5.0) -> Optional[dict]:
    """Send a request to the container client's local IPC socket.

    The container client forwards this to the host service via SSH control channel.

    Returns:
        Response dict if successful, None if service unavailable.
    """
    if not LOCAL_IPC_SOCKET.exists():
        return None

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(LOCAL_IPC_SOCKET))

            request = {"action": action, **payload}
            sock.sendall((json.dumps(request) + "\n").encode())

            # Read response
            data = b""
            while b"\n" not in data and len(data) < 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk

            if data:
                return json.loads(data.decode().strip())
            return None
    except (OSError, json.JSONDecodeError, socket.timeout):
        return None


def report_rate_limit(
    agent: str,
    resets_in_seconds: Optional[int] = None,
    error_type: Optional[str] = None,
) -> bool:
    """Report that an agent hit a rate limit.

    Tries to report to service first, falls back to local file.

    Args:
        agent: Agent name (e.g., "superclaude", "supercodex")
        resets_in_seconds: Seconds until limit resets (if known)
        error_type: Type of error (e.g., "usage_limit_reached", "rate_limit")

    Returns:
        True if reported successfully (to service or local).
    """
    now = datetime.now(timezone.utc)
    resets_at = None
    if resets_in_seconds:
        resets_at = (now + timedelta(seconds=resets_in_seconds)).isoformat()

    # Try service first
    response = _send_to_service(
        "report_rate_limit",
        {
            "agent": agent,
            "limited": True,
            "resets_at": resets_at,
            "error_type": error_type,
        },
    )

    if response and response.get("ok"):
        return True

    # Fallback to local file
    state = _load_local_state()
    state[agent] = {
        "limited": True,
        "detected_at": now.isoformat(),
        "resets_at": resets_at,
        "error_type": error_type,
    }
    _save_local_state(state)
    return True


def clear_rate_limit(agent: str) -> bool:
    """Clear rate limit state for an agent.

    Args:
        agent: Agent name to clear.

    Returns:
        True if cleared successfully.
    """
    # Try service first
    response = _send_to_service("clear_rate_limit", {"agent": agent})

    if response and response.get("ok"):
        return True

    # Fallback to local file
    state = _load_local_state()
    if agent in state:
        del state[agent]
        _save_local_state(state)
    return True


def is_agent_available(agent: str) -> bool:
    """Check if an agent is available (not rate-limited).

    Tries service first, falls back to local file.

    Args:
        agent: Agent name to check.

    Returns:
        True if agent is available.
    """
    # Try service first
    response = _send_to_service("check_agent", {"agent": agent})

    if response is not None:
        return response.get("available", True)

    # Fallback to local state
    state = _load_local_state()
    agent_state = state.get(agent, {})

    if not agent_state.get("limited"):
        return True

    # Check if limit has reset
    resets_at_str = agent_state.get("resets_at")
    if resets_at_str:
        try:
            resets_at = datetime.fromisoformat(resets_at_str)
            if resets_at.tzinfo is None:
                resets_at = resets_at.replace(tzinfo=timezone.utc)
            if resets_at < datetime.now(timezone.utc):
                return True
        except (ValueError, TypeError):
            pass

    return False


def get_fallback_agent(requested: str) -> Tuple[str, Optional[str]]:
    """Get available agent from fallback chain.

    Args:
        requested: The agent originally requested.

    Returns:
        Tuple of (agent_to_use, reason) where reason is None if using requested,
        or a string explaining why fallback was used.
    """
    if is_agent_available(requested):
        return requested, None

    # Get the fallback chain
    chain = FALLBACK_CHAINS.get(requested, [])

    for fallback in chain:
        if is_agent_available(fallback):
            return fallback, f"{requested} is rate-limited, using {fallback}"

    # All agents in chain are limited
    return requested, f"all fallback agents are limited, trying {requested} anyway"


def get_usage_status() -> dict:
    """Get status of all agents.

    Returns:
        Dict with agent statuses.
    """
    # Try service first
    response = _send_to_service("get_usage_status", {})

    if response and response.get("ok"):
        return response.get("status", {})

    # Fallback to local state
    state = _load_local_state()
    now = datetime.now(timezone.utc)

    result = {}
    agents = list(FALLBACK_CHAINS.keys())

    for agent in agents:
        agent_state = state.get(agent, {})
        available = is_agent_available(agent)

        entry = {
            "available": available,
            "limited": agent_state.get("limited", False),
            "resets_at": agent_state.get("resets_at"),
            "error_type": agent_state.get("error_type"),
        }

        # Calculate resets_in
        if not available and agent_state.get("resets_at"):
            try:
                resets_at = datetime.fromisoformat(agent_state["resets_at"])
                if resets_at.tzinfo is None:
                    resets_at = resets_at.replace(tzinfo=timezone.utc)
                delta = resets_at - now
                if delta.total_seconds() > 0:
                    entry["resets_in_seconds"] = int(delta.total_seconds())
            except (ValueError, TypeError):
                pass

        result[agent] = entry

    return result


def parse_rate_limit_error(output: str) -> Optional[dict]:
    """Parse agent output to detect rate limit errors.

    Args:
        output: Agent stdout/stderr output.

    Returns:
        Dict with is_limited, resets_in_seconds, error_type if rate-limited,
        None if not rate-limited.
    """
    import re

    output_lower = output.lower()

    # Check for rate limit indicators
    is_limited = any(
        phrase in output_lower
        for phrase in [
            "rate limit",
            "usage limit",
            "quota exceeded",
            "too many requests",
            "usage_limit_reached",
        ]
    )

    if not is_limited:
        return None

    # Try to extract resets_in_seconds from codex-style JSON error
    resets_in_seconds = None
    resets_match = re.search(r'"resets_in_seconds"\s*:\s*(\d+)', output)
    if resets_match:
        resets_in_seconds = int(resets_match.group(1))

    # Try to extract error type
    error_type = None
    if "usage_limit_reached" in output_lower:
        error_type = "usage_limit_reached"
    elif "rate limit" in output_lower:
        error_type = "rate_limit"
    elif "quota exceeded" in output_lower:
        error_type = "quota_exceeded"

    return {
        "is_limited": True,
        "resets_in_seconds": resets_in_seconds,
        "error_type": error_type,
    }
