"""Agentctl CLI - tmux session management for boxctl containers"""

import os
import subprocess
import sys
import json
import time
import click
from rich.console import Console
from rich.table import Table

from boxctl.agentctl.helpers import (
    get_tmux_sessions,
    session_exists,
    capture_pane,
    get_agent_command,
    kill_session as kill_session_helper,
    detach_client as detach_client_helper,
    _tmux_cmd,
)
from boxctl.agentctl.worktree import worktree_group
from boxctl.utils.terminal import reset_terminal

console = Console()

# Known agent names for validation
AGENT_NAMES = ["claude", "superclaude", "codex", "supercodex", "gemini", "supergemini", "shell"]


@click.group(invoke_without_command=True)
@click.version_option(version="0.2.0", prog_name="agentctl")
@click.pass_context
def cli(ctx):
    """Agentctl - Tmux session management inside boxctl

    Manage tmux sessions for AI agents and shells within boxctl containers.

    Examples:
        agentctl list              # List all sessions
        agentctl attach claude     # Attach to claude session
        agentctl peek codex 100    # View last 100 lines from codex
        agentctl kill shell        # Kill shell session
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command(name="list")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def list_sessions(json_output: bool):
    """List tmux sessions

    Shows all active tmux sessions with their status.
    Use --json for machine-readable output.
    """
    sessions = get_tmux_sessions()

    if json_output:
        # Machine-readable JSON output
        output = {"sessions": sessions}
        click.echo(json.dumps(output, indent=2))
    else:
        # Human-readable table output
        if not sessions:
            console.print("[yellow]No tmux sessions found[/yellow]")
            return

        table = Table(title="TMUX SESSIONS")
        table.add_column("NAME", style="cyan")
        table.add_column("WINDOWS", style="magenta")
        table.add_column("ATTACHED", style="green")
        table.add_column("CREATED", style="blue")

        for session in sessions:
            table.add_row(
                session["name"],
                str(session["windows"]),
                "yes" if session["attached"] else "no",
                session["created"],
            )

        console.print(table)


@cli.command(name="attach")
@click.argument("agent")
def attach(agent: str):
    """Attach to agent session (create if missing)

    AGENT: Name of the agent session (claude, codex, gemini, shell, etc.)

    If the session doesn't exist, a new one will be created.
    This command will replace the current process with tmux.
    """
    # Sanitize session name (same logic as boxctl uses)
    session_name = agent.replace("/", "-").replace(".", "-")

    try:
        if session_exists(session_name):
            # Session exists, attach to it (use = prefix for exact matching)
            result = subprocess.run(_tmux_cmd(["attach", "-t", f"={session_name}"]))
            sys.exit(result.returncode)
        else:
            # Session doesn't exist, create it
            console.print(
                f"[yellow]Session '{session_name}' not found. Creating new session...[/yellow]"
            )

            # Get command for this agent
            cmd = get_agent_command(agent)

            # Determine working directory
            # If current directory is a worktree, use it; otherwise use /workspace
            cwd = os.getcwd()
            working_dir = cwd if cwd.startswith("/git-worktrees/") else "/workspace"

            # Preserve SSH_AUTH_SOCK for SSH agent forwarding
            # This ensures git SSH operations work in agent sessions
            ssh_auth_sock = os.environ.get("SSH_AUTH_SOCK")
            if ssh_auth_sock:
                # Set SSH_AUTH_SOCK in tmux global environment before creating session
                subprocess.run(
                    _tmux_cmd(["set-environment", "-g", "SSH_AUTH_SOCK", ssh_auth_sock]),
                    check=False,
                )

            # Create new tmux session with standard boxctl config
            result = subprocess.run(
                _tmux_cmd(["new-session", "-s", session_name, "-c", working_dir, cmd])
            )
            sys.exit(result.returncode)
    finally:
        # Reset terminal to disable mouse mode when tmux exits
        reset_terminal()


@cli.command(name="detach")
def detach():
    """Detach current tmux client

    Detaches from the current tmux session, leaving it running in the background.
    """
    # Check if we're in a tmux session
    if not os.environ.get("TMUX"):
        console.print("[yellow]Not in a tmux session[/yellow]")
        sys.exit(0)

    if detach_client_helper():
        # This won't actually print since we'll be detached
        console.print("[green]Detached from session[/green]")
    else:
        console.print("[red]Failed to detach[/red]")
        sys.exit(1)


@cli.command(name="peek")
@click.argument("agent")
@click.argument("lines", type=int, default=50, required=False)
@click.option("--follow", "-f", is_flag=True, help="Follow output (like tail -f)")
def peek(agent: str, lines: int, follow: bool):
    """View session scrollback without attaching

    AGENT: Name of the agent session

    LINES: Number of lines to show (default: 50)

    Shows the last N lines from the session's scrollback buffer.
    Use --follow to continuously watch output.
    """
    session_name = agent.replace("/", "-").replace(".", "-")

    if not session_exists(session_name):
        console.print(f"[red]Session '{session_name}' not found[/red]")
        sys.exit(1)

    if follow:
        # Follow mode - continuously show output
        console.print(f"[cyan]=== Following {session_name} (Ctrl-C to stop) ===[/cyan]")
        try:
            while True:
                output = capture_pane(session_name, lines)
                # Clear screen and show output
                click.clear()
                console.print(f"[cyan]=== {session_name} ===[/cyan]")
                click.echo(output)
                time.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped following[/yellow]")
    else:
        # Single peek
        sessions = get_tmux_sessions()
        session_info = next((s for s in sessions if s["name"] == session_name), None)

        if session_info:
            status = "attached" if session_info["attached"] else "detached"
            console.print(
                f"[cyan]=== {session_name} ({status}, {session_info['windows']} window(s)) ===[/cyan]"
            )
        else:
            console.print(f"[cyan]=== {session_name} ===[/cyan]")

        console.print(f"[dim]Last {lines} lines:[/dim]")
        console.print("─" * 60)

        output = capture_pane(session_name, lines)
        click.echo(output)

        console.print("─" * 60)


@cli.command(name="kill")
@click.argument("agent")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
def kill(agent: str, force: bool):
    """Kill a tmux session

    AGENT: Name of the agent session to kill

    Terminates the specified tmux session.
    Use --force to skip the confirmation prompt.
    """
    session_name = agent.replace("/", "-").replace(".", "-")

    if not session_exists(session_name):
        console.print(f"[red]Session '{session_name}' not found[/red]")
        sys.exit(1)

    if not force:
        if not click.confirm(f"Kill session '{session_name}'?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    if kill_session_helper(session_name):
        # Reset terminal in case user was attached to this session
        reset_terminal()
        console.print(f"[green]Session '{session_name}' killed[/green]")
    else:
        console.print(f"[red]Failed to kill session '{session_name}'[/red]")
        sys.exit(1)


# Add worktree command group
cli.add_command(worktree_group)


if __name__ == "__main__":
    cli()
