# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Fallback logic for agent rate limit handling.

When an agent is rate-limited, this module determines which fallback agent to use.
"""

from datetime import datetime, timezone
from typing import Optional

from boxctl.usage.state import load_state, get_agent_state

# Fallback chains: when an agent is limited, try these in order
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


def is_agent_available(agent: str) -> bool:
    """Check if an agent is available (not rate-limited).

    Args:
        agent: Agent name (e.g., "superclaude", "supercodex")

    Returns:
        True if agent is available, False if rate-limited.
    """
    agent_state = get_agent_state(agent)

    # No state means never been limited
    if not agent_state:
        return True

    # Not currently limited
    if not agent_state.get("limited"):
        return True

    # Check if limit has reset
    resets_at_str = agent_state.get("resets_at")
    if resets_at_str:
        try:
            resets_at = datetime.fromisoformat(resets_at_str)
            # Handle naive datetime by assuming UTC
            if resets_at.tzinfo is None:
                resets_at = resets_at.replace(tzinfo=timezone.utc)
            if resets_at < datetime.now(timezone.utc):
                return True
        except (ValueError, TypeError):
            pass

    return False


def get_fallback_agent(requested: str) -> tuple[str, Optional[str]]:
    """Get available agent from fallback chain.

    Args:
        requested: The agent originally requested

    Returns:
        Tuple of (agent_to_use, reason) where reason is None if using requested,
        or a string explaining why fallback was used.
    """
    if is_agent_available(requested):
        return requested, None

    # Get the fallback chain for this agent
    chain = FALLBACK_CHAINS.get(requested, [])

    for fallback in chain:
        if is_agent_available(fallback):
            agent_state = get_agent_state(requested)
            resets_at = agent_state.get("resets_at", "unknown")
            return fallback, f"{requested} is rate-limited (resets: {resets_at})"

    # All agents in chain are limited, use requested anyway
    return requested, f"all fallback agents are limited, trying {requested} anyway"


def get_status_summary() -> list[dict]:
    """Get a summary of all agent statuses.

    Returns:
        List of dicts with agent, status, and resets_in info.
    """
    state = load_state()
    agents = [
        "superclaude",
        "supercodex",
        "supergemini",
        "superqwen",
        "claude",
        "codex",
        "gemini",
        "qwen",
    ]

    summary = []
    now = datetime.now(timezone.utc)

    for agent in agents:
        agent_state = state.get(agent, {})
        available = is_agent_available(agent)

        entry = {
            "agent": agent,
            "status": "OK" if available else "Limited",
            "resets_in": None,
        }

        if not available and agent_state.get("resets_at"):
            try:
                resets_at = datetime.fromisoformat(agent_state["resets_at"])
                if resets_at.tzinfo is None:
                    resets_at = resets_at.replace(tzinfo=timezone.utc)
                delta = resets_at - now
                if delta.total_seconds() > 0:
                    entry["resets_in"] = _format_timedelta(delta)
            except (ValueError, TypeError):
                pass

        summary.append(entry)

    return summary


def _format_timedelta(delta) -> str:
    """Format a timedelta as a human-readable string."""
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds}s"

    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    remaining_minutes = minutes % 60
    if hours < 24:
        return f"{hours}h {remaining_minutes}m"

    days = hours // 24
    remaining_hours = hours % 24
    return f"{days}d {remaining_hours}h"
