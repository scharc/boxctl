# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tmux session operations and utilities for CLI.

This module provides CLI-specific tmux operations. The core tmux functions
are imported from boxctl.core.tmux and re-exported here as the CLI API.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from boxctl.container import ContainerManager, get_abox_environment
from boxctl.config import ProjectConfig
from boxctl.paths import BinPaths
from boxctl.utils.terminal import reset_terminal

# Import from core and re-export as CLI API
from boxctl.core.tmux import (
    sanitize_tmux_name as _sanitize_tmux_name,
    get_tmux_socket_path,
    list_tmux_sessions,
    session_exists,
)
from boxctl.core.sessions import (
    get_agent_sessions,
    generate_session_name,
)

console = Console()


def _show_warning_panel(message: str, title: str) -> None:
    """Display a warning panel with consistent styling.

    Args:
        message: Warning message to display
        title: Panel title (will be prefixed with ⚠)
    """
    from rich.panel import Panel

    console.print(Panel(message, title=f"⚠ {title}", border_style="yellow"))


# CLI wrapper functions (add error handling and formatting)
def _get_tmux_socket(manager: ContainerManager, container_name: str) -> Optional[str]:
    """Get tmux socket path for container. Wrapper for core function."""
    return get_tmux_socket_path(manager, container_name)


def _get_tmux_sessions(manager: ContainerManager, container_name: str) -> list[dict]:
    """List tmux sessions in container. Wrapper for core function with CLI error handling."""
    from boxctl.utils.exceptions import TmuxError

    try:
        return list_tmux_sessions(manager, container_name)
    except TmuxError as e:
        console.print(f"[red]Failed to list tmux sessions in {container_name}[/red]")
        console.print(str(e))
        return []


def _session_exists(manager: ContainerManager, container_name: str, session_name: str) -> bool:
    """Check if a tmux session exists. Wrapper for core function."""
    return session_exists(manager, container_name, session_name)


def _get_agent_sessions(
    manager: ContainerManager, container_name: str, agent_type: Optional[str] = None
) -> list[dict]:
    """Get tmux sessions filtered by agent type. Wrapper for core function."""
    return get_agent_sessions(manager, container_name, agent_type)


def _generate_session_name(
    manager: ContainerManager,
    container_name: str,
    agent_type: str,
    identifier: Optional[str] = None,
) -> str:
    """Generate a unique session name for an agent instance. Wrapper for core function."""
    return generate_session_name(manager, container_name, agent_type, identifier)


def _resolve_tmux_prefix() -> Optional[str]:
    """Resolve tmux prefix key from environment or detect nested tmux."""
    raw_prefix = os.getenv("BOXCTL_TMUX_PREFIX", "").strip()
    if raw_prefix:
        lowered = raw_prefix.lower()
        if lowered in {"default", "none", "off"}:
            return None
        return raw_prefix
    if os.getenv("TMUX"):
        return "C-a"
    return None


def _warn_if_agents_running(
    manager: ContainerManager, container_name: str, action: str = "rebuild"
) -> bool:
    """Check for active sessions and warn user before disruptive actions.

    Warns about ALL tmux sessions (agents, shells, etc.) since any active
    session represents work that could be lost.

    Args:
        manager: ContainerManager instance
        container_name: Name of container to check
        action: Description of action being taken (e.g., "rebuild", "remove")

    Returns:
        True if user wants to proceed, False otherwise
    """
    if not manager.container_exists(container_name) or not manager.is_running(container_name):
        return True

    sessions = _get_tmux_sessions(manager, container_name)
    if not sessions:
        return True

    # Show warning for ALL sessions (agents, shells, etc.)
    console.print(f"\n[yellow]⚠ Warning: Active sessions detected[/yellow]")
    console.print(f"[yellow]This {action} will interrupt:[/yellow]")
    for session in sessions:
        attached_str = "(attached)" if session["attached"] else "(detached)"
        console.print(f"  - {session['name']} {attached_str}")

    # Ask for confirmation
    return click.confirm(f"\nProceed with {action}?", default=False)


def _warn_if_base_outdated(
    manager: ContainerManager, container_name: str, project_dir: Optional[Path] = None
) -> None:
    """Show warnings if container or config is outdated.

    Checks:
    1. If the container was created from an older base image
    2. If the .boxctl/config.yml was created with an older boxctl version

    Args:
        manager: ContainerManager instance
        container_name: Name of container to check
        project_dir: Optional project directory for config check
    """
    warnings = []

    # Check base image
    if manager.is_base_image_outdated(container_name):
        warnings.append("Container uses an older base image")

    # Check config version
    try:
        config = ProjectConfig(project_dir)
        if config.exists() and config.is_version_outdated():
            from boxctl import __version__ as current_version

            stored = config.boxctl_version or "unknown"
            warnings.append(f"Config created with boxctl {stored} (current: {current_version})")
    except Exception:
        pass  # Don't fail on config check errors

    if warnings:
        warning_text = "\n".join(f"• {w}" for w in warnings)
        warning_text += "\n\nRun 'abox rebase' to update."
        _show_warning_panel(warning_text, "Outdated Environment")
        import time

        time.sleep(2)  # Give user time to see the warning


def _warn_if_devices_missing(project_dir: Path) -> None:
    """Check for missing devices and prompt user to connect or skip.

    Shows an interactive prompt if any configured devices are not available,
    allowing the user to plug in devices and retry, or skip and continue.

    Args:
        project_dir: Project directory containing .boxctl/config.yml
    """
    config = ProjectConfig(project_dir)
    if not config.exists() or not config.devices:
        return

    # Check which devices are missing
    missing = []
    for device in config.devices:
        device_path = Path(device.split(":")[0])  # Handle host:container format
        if not device_path.exists():
            missing.append(device)

    if not missing:
        return

    # Interactive prompt loop
    while missing:
        device_list = "\n".join(f"  • {d}" for d in missing)
        _show_warning_panel(
            f"The following devices are not available:\n{device_list}\n\n"
            f"[dim]Connect the device(s) and press Enter to retry, or type 'skip' to continue without them.[/dim]",
            "Missing Devices",
        )

        try:
            user_input = (
                console.input("[yellow]Press Enter to retry, or type 'skip': [/yellow]")
                .strip()
                .lower()
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Skipping missing devices...[/yellow]")
            break

        if user_input == "skip":
            console.print("[yellow]Continuing without missing devices...[/yellow]")
            break

        # Re-check devices
        still_missing = []
        for device in missing:
            device_path = Path(device.split(":")[0])
            if device_path.exists():
                console.print(f"[green]✓ Device found: {device}[/green]")
            else:
                still_missing.append(device)

        missing = still_missing

        if not missing:
            console.print("[green]All devices are now available![/green]")


def _attach_tmux_session(manager: ContainerManager, container_name: str, session_name: str) -> None:
    from boxctl.cli.helpers.utils import wait_for_container_ready

    if not wait_for_container_ready(manager, container_name, timeout_s=90.0):
        console.print("[red]Container not ready for session attach[/red]")
        raise SystemExit(1)

    socket_path = _get_tmux_socket(manager, container_name)
    # Use "=session_name" syntax for exact matching (prevents prefix matching)
    exact_session = f"={session_name}"
    tmux_cmd = ["tmux", "attach", "-t", exact_session]
    if socket_path:
        tmux_cmd = ["tmux", "-S", socket_path, "attach", "-t", exact_session]
    cmd = [
        "docker",
        "exec",
        "-it",
        "-u",
        "abox",
        "-e",
        "HOME=/home/abox",
        "-e",
        "USER=abox",
        container_name,
        BinPaths.TMUX,
        *tmux_cmd[1:],
    ]
    try:
        result = subprocess.run(cmd)
        sys.exit(result.returncode)
    finally:
        # Reset terminal to disable mouse mode when docker exits
        # This handles all cases: normal exit, container destroyed, ctrl-c
        reset_terminal()
