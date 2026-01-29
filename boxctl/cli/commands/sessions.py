# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tmux session management commands."""

from typing import Optional

import click
from rich.table import Table

from boxctl.cli import cli
from boxctl.container import get_abox_environment
from boxctl.paths import BinPaths, ContainerPaths, ContainerDefaults
from boxctl.utils.terminal import reset_terminal
from boxctl.utils.project import resolve_project_dir
from boxctl.cli.helpers import (
    _attach_tmux_session,
    _complete_connect_session,
    _complete_session_name,
    _ensure_container_running,
    _generate_session_name,
    _get_agent_sessions,
    _get_project_context,
    _get_tmux_sessions,
    _get_tmux_socket,
    _require_container_running,
    _sanitize_tmux_name,
    _session_exists,
    get_sessions_from_daemon,
    console,
    handle_errors,
    require_initialized,
)


# Supported agent types for sessions
AGENT_TYPES = ["claude", "superclaude", "codex", "supercodex", "gemini", "supergemini", "shell"]


def _run_session_agent(session_name: str, agent_type: str):
    """Create and attach to a new agent session."""
    from boxctl.cli.commands.agents import (
        _read_agent_instructions,
        _read_super_prompt,
        _has_vscode,
    )
    from boxctl.cli.helpers import _run_agent_command

    # Check project is initialized (raises NotInitializedError if not)
    require_initialized()

    pctx = _get_project_context()

    # Ensure container is running (raises ContainerError on failure)
    _ensure_container_running(pctx.manager, pctx.container_name)

    # Sanitize session name
    full_session_name = f"{agent_type}-{_sanitize_tmux_name(session_name)}"

    # Check if session already exists
    if _session_exists(pctx.manager, pctx.container_name, full_session_name):
        # Attach to existing session
        console.print(f"[yellow]Session '{full_session_name}' exists, attaching...[/yellow]")
        _attach_tmux_session(pctx.manager, pctx.container_name, full_session_name)
        return

    # Prepare agent-specific settings
    command = None
    extra_args = []
    label = None
    persist_session = False

    if agent_type == "claude":
        command = "claude"
        label = f"Claude Code ({full_session_name})"
        instructions = _read_agent_instructions()
        extra_args = [
            "--settings",
            ContainerPaths.claude_settings(),
            "--mcp-config",
            ContainerPaths.mcp_config(),
            "--append-system-prompt",
            instructions,
        ]
        if _has_vscode():
            extra_args.append("--ide")

    elif agent_type == "superclaude":
        command = "claude"
        label = f"Claude Code (auto-approve, {full_session_name})"
        prompt = _read_super_prompt()
        extra_args = [
            "--settings",
            ContainerPaths.claude_super_settings(),
            "--mcp-config",
            ContainerPaths.mcp_config(),
            "--dangerously-skip-permissions",
            "--append-system-prompt",
            prompt,
        ]
        if _has_vscode():
            extra_args.append("--ide")
        persist_session = False

    elif agent_type == "codex":
        command = "codex"
        label = f"Codex ({full_session_name})"

    elif agent_type == "supercodex":
        command = "codex"
        label = f"Codex (auto-approve, {full_session_name})"
        extra_args = ["--dangerously-bypass-approvals-and-sandbox"]
        persist_session = False

    elif agent_type == "gemini":
        command = "gemini"
        label = f"Gemini ({full_session_name})"

    elif agent_type == "supergemini":
        command = "gemini"
        label = f"Gemini (auto-approve, {full_session_name})"
        extra_args = ["--non-interactive"]
        persist_session = False

    elif agent_type == "shell":
        command = "/bin/bash"
        label = f"Shell ({full_session_name})"

    console.print(f"[green]Creating session: {full_session_name}[/green]")
    _run_agent_command(
        pctx.manager,
        None,
        tuple(),
        command,
        extra_args=extra_args,
        label=label,
        reuse_tmux_session=False,
        persist_session=persist_session,
        custom_session_name=full_session_name,
    )


@cli.group(name="session")
def session_group():
    """Manage tmux sessions in containers.

    \b
    Usage:
        abox session add [NAME]      # Create shell session
        abox session new AGENT [NAME] # Create agent session
        abox session list [all]      # List sessions
        abox session attach SESSION  # Attach to existing session
        abox session remove SESSION  # Remove session
        abox session rename OLD NEW  # Rename session

    \b
    Agent types: claude, superclaude, codex, supercodex, gemini, supergemini

    \b
    Examples:
        abox session add                      # Create shell-1
        abox session add my-shell             # Create shell-my-shell
        abox session new superclaude          # Create superclaude-1
        abox session new superclaude feature  # Create superclaude-feature
        abox session list                     # List all sessions
    """
    pass


def _complete_list_scope(ctx, param, incomplete):
    """Shell completion for list scope."""
    return [c for c in ["all"] if c.startswith(incomplete)]


@session_group.command(name="list")
@click.argument(
    "scope", required=False, type=click.Choice(["all"]), shell_complete=_complete_list_scope
)
@handle_errors
def session_list(scope: Optional[str]):
    """List tmux sessions.

    SCOPE: Use "all" to list sessions across all containers.

    Examples:
        abox session list       # List sessions in current project
        abox session list all   # List sessions in all containers
    """
    pctx = _get_project_context()

    if scope == "all":
        # Try daemon cache first (fast path)
        daemon_sessions = get_sessions_from_daemon(timeout=1.0)
        if daemon_sessions is not None:
            all_sessions = [
                {
                    "project": s.get("project", ""),
                    "session": s.get("session_name", ""),
                    "status": "attached" if s.get("attached") else "detached",
                    "windows": s.get("windows", 1),
                }
                for s in daemon_sessions
            ]
        else:
            # Fallback to docker exec (slow path)
            all_containers = pctx.manager.client.containers.list(
                filters={"name": ContainerDefaults.CONTAINER_PREFIX}
            )

            if not all_containers:
                console.print("[yellow]No boxctl containers found[/yellow]")
                return

            all_sessions = []
            for container in all_containers:
                cname = container.name
                if not cname.startswith(ContainerDefaults.CONTAINER_PREFIX):
                    continue

                project_name = ContainerDefaults.project_from_container(cname)

                sessions = _get_tmux_sessions(pctx.manager, cname)
                for sess in sessions:
                    all_sessions.append(
                        {
                            "project": project_name,
                            "session": sess["name"],
                            "status": "attached" if sess["attached"] else "detached",
                            "windows": sess["windows"],
                        }
                    )

        if not all_sessions:
            console.print("[yellow]No tmux sessions found in any container[/yellow]")
            return

        table = Table(title="All boxctl Sessions")
        table.add_column("Project", style="cyan")
        table.add_column("Session", style="magenta")
        table.add_column("Status", style="green")
        table.add_column("Windows", style="blue")

        for sess in all_sessions:
            table.add_row(sess["project"], sess["session"], sess["status"], str(sess["windows"]))

        console.print(table)
        console.print("\n[blue]Connect:[/blue] abox connect <project> <session>")
    else:
        if not pctx.manager.is_running(pctx.container_name):
            console.print(f"[red]Container {pctx.container_name} is not running[/red]")
            console.print("[blue]Start it with: boxctl start[/blue]")
            return

        table = Table(title="boxctl Tmux Sessions")
        table.add_column("Session", style="magenta")
        table.add_column("Agent Type", style="cyan")
        table.add_column("Identifier", style="yellow")
        table.add_column("Attached", style="green")
        table.add_column("Windows", style="blue")

        sessions = _get_agent_sessions(pctx.manager, pctx.container_name)
        if not sessions:
            console.print("[yellow]No tmux sessions found[/yellow]")
            return

        for session_entry in sessions:
            table.add_row(
                session_entry["name"],
                session_entry["agent_type"],
                session_entry["identifier"],
                "yes" if session_entry["attached"] else "no",
                str(session_entry["windows"]),
            )

        console.print(table)
        console.print("\n[blue]Attach:[/blue] abox session attach <session>")
        console.print("[blue]Create:[/blue] abox session new <agent> [name]")


@session_group.command(name="attach")
@click.argument("session_name", shell_complete=_complete_session_name)
@handle_errors
def session_attach(session_name: str):
    """Attach to an existing session.

    SESSION_NAME: Name of the session to attach to

    Examples:
        abox session attach superclaude-my-feature
    """
    pctx = _get_project_context()
    _require_container_running(pctx.manager, pctx.container_name)

    _attach_tmux_session(pctx.manager, pctx.container_name, session_name)


@session_group.command(name="remove")
@click.argument("session_name", shell_complete=_complete_session_name)
@handle_errors
def session_remove(session_name: str):
    """Remove a session.

    SESSION_NAME: Name of the session to remove

    Examples:
        abox session remove superclaude-my-feature
    """
    pctx = _get_project_context()
    _require_container_running(pctx.manager, pctx.container_name)

    socket_path = _get_tmux_socket(pctx.manager, pctx.container_name)
    tmux_cmd = [BinPaths.TMUX, "kill-session", "-t", session_name]
    if socket_path:
        tmux_cmd = [BinPaths.TMUX, "-S", socket_path, "kill-session", "-t", session_name]
    exit_code, output = pctx.manager.exec_command(
        pctx.container_name,
        tmux_cmd,
        environment=get_abox_environment(include_tmux=True, container_name=pctx.container_name),
        user=ContainerPaths.USER,
    )
    if exit_code != 0:
        msg = f"Failed to remove session {session_name}"
        if output.strip():
            msg += f": {output.strip()}"
        raise click.ClickException(msg)

    reset_terminal()
    console.print(f"[green]Removed session {session_name}[/green]")


@session_group.command(name="rename")
@click.argument("session_name", shell_complete=_complete_session_name)
@click.argument("new_name")
@handle_errors
def session_rename(session_name: str, new_name: str):
    """Rename a session.

    SESSION_NAME: Current session name
    NEW_NAME: New identifier (agent type prefix preserved)

    Examples:
        abox session rename superclaude-1 feature-auth
        # Results in: superclaude-feature-auth
    """
    pctx = _get_project_context()
    _require_container_running(pctx.manager, pctx.container_name)

    sessions = _get_agent_sessions(pctx.manager, pctx.container_name)
    old_session = next((s for s in sessions if s["name"] == session_name), None)

    if not old_session:
        raise click.ClickException(f"Session '{session_name}' not found")

    agent_type = old_session["agent_type"]
    full_new_name = f"{agent_type}-{_sanitize_tmux_name(new_name)}"

    if _session_exists(pctx.manager, pctx.container_name, full_new_name):
        raise click.ClickException(f"Session '{full_new_name}' already exists")

    socket_path = _get_tmux_socket(pctx.manager, pctx.container_name)
    tmux_cmd = [BinPaths.TMUX, "rename-session", "-t", session_name, full_new_name]
    if socket_path:
        tmux_cmd = [
            BinPaths.TMUX,
            "-S",
            socket_path,
            "rename-session",
            "-t",
            session_name,
            full_new_name,
        ]

    exit_code, output = pctx.manager.exec_command(
        pctx.container_name,
        tmux_cmd,
        environment=get_abox_environment(include_tmux=True, container_name=pctx.container_name),
        user=ContainerPaths.USER,
    )

    if exit_code != 0:
        msg = "Failed to rename session"
        if output.strip():
            msg += f": {output.strip()}"
        raise click.ClickException(msg)

    console.print(f"[green]Renamed '{session_name}' to '{full_new_name}'[/green]")


def _complete_agent_type(ctx, param, incomplete):
    """Shell completion for agent types."""
    return [a for a in AGENT_TYPES if a.startswith(incomplete)]


@session_group.command(name="add")
@click.argument("name", required=False)
@handle_errors
def session_add(name: Optional[str]):
    """Create a shell session (no AI agent).

    NAME: Optional session identifier. Auto-numbered if omitted.

    Examples:
        abox session add              # Creates shell-1 (or next available)
        abox session add my-shell     # Creates shell-my-shell
    """
    require_initialized()
    pctx = _get_project_context()

    # Ensure container is running (raises ContainerError on failure)
    _ensure_container_running(pctx.manager, pctx.container_name)

    if name:
        _run_session_agent(name, "shell")
    else:
        # Auto-generate name
        session_name = _generate_session_name(
            pctx.manager, pctx.container_name, "shell", identifier=None
        )
        identifier = session_name.split("-", 1)[1] if "-" in session_name else "1"
        _run_session_agent(identifier, "shell")


@session_group.command(name="new")
@click.argument("agent", type=click.Choice(AGENT_TYPES), shell_complete=_complete_agent_type)
@click.argument("name", required=False)
@handle_errors
def session_new(agent: str, name: Optional[str]):
    """Create a new agent session.

    AGENT: Agent type (claude, superclaude, codex, supercodex, gemini, supergemini, shell)
    NAME: Optional session identifier. Auto-numbered if omitted.

    Examples:
        abox session new superclaude          # Creates superclaude-1
        abox session new superclaude feature  # Creates superclaude-feature
        abox session new claude bugfix        # Creates claude-bugfix
    """
    require_initialized()
    pctx = _get_project_context()

    # Ensure container is running (raises ContainerError on failure)
    _ensure_container_running(pctx.manager, pctx.container_name)

    if name:
        _run_session_agent(name, agent)
    else:
        # Auto-generate name
        session_name = _generate_session_name(
            pctx.manager, pctx.container_name, agent, identifier=None
        )
        identifier = session_name.split("-", 1)[1] if "-" in session_name else "1"
        _run_session_agent(identifier, agent)
