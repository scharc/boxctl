"""Worktree command implementations"""

import os
import subprocess
import sys
import time
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from boxctl.agentctl.worktree.utils import (
    sanitize_branch_name,
    get_worktree_path,
    run_git_command,
    list_git_worktrees,
    worktree_exists,
    branch_exists,
    is_git_repo,
)
from boxctl.agentctl.worktree.metadata import WorktreeMetadata
from boxctl.agentctl.helpers import (
    get_current_tmux_session,
    send_keys_to_session,
    get_agent_command,
    session_exists as tmux_session_exists,
    _tmux_cmd,
    _get_tmux_socket,
)

console = Console()


@click.group(name="worktree")
def worktree_group():
    """Git worktree management

    Manage git worktrees for multi-branch parallel development.
    Create, list, and remove worktrees with automatic metadata tracking.

    Examples:
        agentctl worktree list                # List all worktrees
        agentctl worktree add feature-auth    # Create worktree for branch
        agentctl worktree remove feature-auth # Remove worktree
    """
    pass


@worktree_group.command(name="list")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def list_worktrees(json_output: bool):
    """List all git worktrees

    Shows all git worktrees with their paths, branches, and associated sessions.
    Use --json for machine-readable output.
    """
    # Check if we're in a git repo
    if not is_git_repo():
        console.print("[red]Not in a git repository[/red]")
        sys.exit(1)

    # Get worktrees from git
    worktrees = list_git_worktrees()

    # Get metadata
    metadata = WorktreeMetadata()
    metadata_list = {wt.get("path"): wt for wt in metadata.list_all()}

    if json_output:
        import json

        # Add metadata to worktrees
        for wt in worktrees:
            meta = metadata_list.get(wt["path"], {})
            wt["sessions"] = meta.get("sessions", [])
            wt["created"] = meta.get("created")
        click.echo(json.dumps({"worktrees": worktrees}, indent=2))
    else:
        if not worktrees:
            console.print("[yellow]No worktrees found[/yellow]")
            console.print(
                "\n[dim]Tip: Create a worktree with: agentctl worktree add <branch>[/dim]"
            )
            return

        table = Table(title="GIT WORKTREES")
        table.add_column("PATH", style="cyan")
        table.add_column("BRANCH", style="magenta")
        table.add_column("COMMIT", style="blue")
        table.add_column("SESSIONS", style="green")

        for wt in worktrees:
            path = wt.get("path", "")
            branch = wt.get("branch", "")
            commit = wt.get("commit", "")[:8]  # Short hash

            # Get sessions from metadata
            meta = metadata_list.get(path, {})
            sessions = meta.get("sessions", [])
            sessions_str = ", ".join(sessions) if sessions else "-"

            # Highlight main workspace
            if path == "/workspace":
                path = f"{path} [dim](main)[/dim]"

            table.add_row(path, branch, commit, sessions_str)

        console.print(table)
        console.print(f"\n[dim]Total: {len(worktrees)} worktree(s)[/dim]")


@worktree_group.command(name="add")
@click.argument("branch")
@click.option("--path", help="Custom worktree path (default: /worktree-<branch>)")
@click.option("--create", "-c", is_flag=True, help="Create new branch if it doesn't exist")
def add_worktree(branch: str, path: str, create: bool):
    """Create a new git worktree

    BRANCH: Name of the branch to check out in the worktree

    Creates a new worktree for the specified branch. If the branch doesn't
    exist locally, it will be fetched from origin. Use --create to create
    a new branch.

    Examples:
        agentctl worktree add feature-auth
        agentctl worktree add fix-bug --path /worktree-bugfix
        agentctl worktree add new-feature --create
    """
    # Check if we're in a git repo
    if not is_git_repo():
        console.print("[red]Not in a git repository[/red]")
        sys.exit(1)

    # Determine worktree path
    if not path:
        path = get_worktree_path(branch)

    # Check if worktree already exists at this path
    if worktree_exists(path):
        console.print(f"[red]Worktree already exists at {path}[/red]")
        sys.exit(1)

    # Check if directory already exists
    if os.path.exists(path):
        console.print(f"[red]Directory already exists: {path}[/red]")
        sys.exit(1)

    # Prepare git command
    cmd = ["worktree", "add"]

    if create:
        # Create new branch
        cmd.extend(["-b", branch, path])
        console.print(f"[cyan]Creating new branch '{branch}' in worktree {path}...[/cyan]")
    else:
        # Check if branch exists
        if not branch_exists(branch):
            console.print(f"[red]Branch '{branch}' not found[/red]")
            console.print("[dim]Tip: Use --create to create a new branch[/dim]")
            sys.exit(1)

        cmd.extend([path, branch])
        console.print(f"[cyan]Creating worktree for branch '{branch}' at {path}...[/cyan]")

    # Run git worktree add
    exit_code, stdout, stderr = run_git_command(cmd)

    if exit_code != 0:
        console.print(f"[red]Failed to create worktree:[/red]")
        console.print(stderr)
        sys.exit(1)

    # Get commit hash
    exit_code, commit_hash, _ = run_git_command(["rev-parse", "HEAD"], cwd=path)
    commit_hash = commit_hash.strip() if exit_code == 0 else None

    # Save metadata
    metadata = WorktreeMetadata()
    metadata.add(path, branch, commit_hash)

    console.print(f"[green]✓ Worktree created successfully[/green]")
    console.print(f"[dim]Path: {path}[/dim]")
    console.print(f"[dim]Branch: {branch}[/dim]")
    console.print(f"\n[cyan]To start working in the worktree:[/cyan]")
    console.print(f"  cd {path}")
    console.print(f"  agentctl a claude")


@worktree_group.command(name="remove")
@click.argument("branch_or_path")
@click.option("--force", "-f", is_flag=True, help="Force removal even with uncommitted changes")
def remove_worktree(branch_or_path: str, force: bool):
    """Remove a git worktree

    BRANCH_OR_PATH: Branch name or worktree path to remove

    Removes the specified worktree and cleans up metadata.
    Use --force to remove worktrees with uncommitted changes.

    Examples:
        agentctl worktree remove feature-auth
        agentctl worktree remove /worktree-feature-auth
        agentctl worktree remove feature-auth --force
    """
    # Check if we're in a git repo
    if not is_git_repo():
        console.print("[red]Not in a git repository[/red]")
        sys.exit(1)

    # Determine if input is a path or branch name
    if os.path.isabs(branch_or_path):
        # Absolute path provided
        path = branch_or_path
    else:
        # Branch name provided, construct path
        path = get_worktree_path(branch_or_path)

    # Check if worktree exists
    if not worktree_exists(path):
        console.print(f"[red]Worktree not found: {path}[/red]")
        sys.exit(1)

    # Can't remove main workspace
    if path == "/workspace":
        console.print("[red]Cannot remove main workspace[/red]")
        sys.exit(1)

    # Get worktree info for confirmation
    worktrees = list_git_worktrees()
    wt_info = next((wt for wt in worktrees if wt.get("path") == path), None)
    branch = wt_info.get("branch", "unknown") if wt_info else "unknown"

    # Confirm removal
    if not force:
        console.print(f"[yellow]About to remove worktree:[/yellow]")
        console.print(f"  Path: {path}")
        console.print(f"  Branch: {branch}")
        if not click.confirm("\nContinue?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    # Run git worktree remove
    cmd = ["worktree", "remove", path]
    if force:
        cmd.append("--force")

    exit_code, stdout, stderr = run_git_command(cmd)

    if exit_code != 0:
        console.print(f"[red]Failed to remove worktree:[/red]")
        console.print(stderr)
        sys.exit(1)

    # Remove from metadata
    metadata = WorktreeMetadata()
    metadata.remove(path)

    console.print(f"[green]✓ Worktree removed successfully[/green]")
    console.print(f"[dim]Path: {path}[/dim]")
    console.print(f"[dim]Branch: {branch}[/dim]")


@worktree_group.command(name="prune")
def prune_worktrees():
    """Remove stale worktree metadata

    Cleans up metadata for worktrees that no longer exist in git.
    Useful after manually removing worktree directories.
    """
    # Check if we're in a git repo
    if not is_git_repo():
        console.print("[red]Not in a git repository[/red]")
        sys.exit(1)

    # Get current worktrees from git
    git_worktrees = {wt.get("path") for wt in list_git_worktrees()}

    # Get tracked worktrees from metadata
    metadata = WorktreeMetadata()
    tracked_worktrees = metadata.list_all()

    # Find stale entries
    stale = [wt for wt in tracked_worktrees if wt.get("path") not in git_worktrees]

    if not stale:
        console.print("[green]No stale worktree metadata found[/green]")
        return

    console.print(f"[yellow]Found {len(stale)} stale worktree(s) in metadata:[/yellow]")
    for wt in stale:
        console.print(f"  • {wt.get('path')} ({wt.get('branch')})")

    if click.confirm("\nRemove stale metadata?"):
        for wt in stale:
            metadata.remove(wt.get("path"))
        console.print(f"[green]✓ Removed {len(stale)} stale metadata entries[/green]")
    else:
        console.print("[yellow]Cancelled[/yellow]")


@worktree_group.command(name="switch")
@click.argument("branch")
@click.argument("agent", default="shell")
def switch_worktree(branch: str, agent: str):
    """Switch to an existing worktree

    BRANCH: Branch name of the worktree to switch to

    AGENT: Agent to start in the worktree (default: shell)

    Changes to the specified worktree directory and starts an agent session.
    If you're currently in an agent session, it will be notified to STOP before switching.

    Examples:
        agentctl worktree switch feature-auth claude
        agentctl worktree switch main shell
        agentctl worktree switch fix-bugs superclaude
    """
    # Check if we're in a git repo
    if not is_git_repo():
        console.print("[red]Not in a git repository[/red]")
        sys.exit(1)

    # Get worktree path
    target_path = get_worktree_path(branch)

    # Check if worktree exists
    if not worktree_exists(target_path):
        console.print(f"[red]Worktree not found for branch '{branch}'[/red]")
        console.print(f"[dim]Expected path: {target_path}[/dim]")
        console.print("\n[dim]Tip: Create it with: agentctl worktree add {branch}[/dim]")
        sys.exit(1)

    # Get current session if any
    current_session = get_current_tmux_session()

    if current_session:
        # Agent is currently running - send STOP message
        console.print(f"[yellow]⚠ Currently in session: {current_session}[/yellow]")

        # Create a very visible STOP message
        stop_message = """

╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║                    🛑 STOP WORKING NOW 🛑                      ║
║                                                                ║
║  You are about to switch to a different worktree/branch.      ║
║                                                                ║
║  DO NOT CONTINUE working on this task.                        ║
║  DO NOT make any more changes in this session.                ║
║  DO NOT commit anything.                                      ║
║                                                                ║
║  This session will be detached in 3 seconds.                  ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝

"""
        # Send the stop message to the current session
        for line in stop_message.split("\n"):
            send_keys_to_session(current_session, f"# {line}", literal=False)
            send_keys_to_session(current_session, "Enter", literal=False)
            time.sleep(0.1)

        # Also print it to current terminal
        panel = Panel(
            Text.from_markup(
                "\n[bold red]🛑 STOPPING CURRENT SESSION 🛑[/bold red]\n\n"
                f"Sending STOP message to session: [cyan]{current_session}[/cyan]\n\n"
                "[yellow]The agent has been instructed to STOP working.[/yellow]\n"
            ),
            border_style="red",
            title="[bold]Session Switch[/bold]",
        )
        console.print(panel)

        # Give the agent time to see the message
        console.print("\n[dim]Waiting 3 seconds for agent to see STOP message...[/dim]")
        time.sleep(3)

    # Sanitize session name - include branch to avoid conflict with main workspace sessions
    # Format: <branch>-<agent> (e.g., "nextcloud-superclaude")
    sanitized_branch = sanitize_branch_name(branch)
    sanitized_agent = agent.replace("/", "-").replace(".", "-")
    session_name = f"{sanitized_branch}-{sanitized_agent}"

    # Get command for the agent
    cmd = get_agent_command(agent)

    console.print(f"\n[green]→ Switching to worktree:[/green] {target_path}")
    console.print(f"[green]→ Starting agent:[/green] {agent}")

    # Create new tmux session in the target worktree or attach if exists
    if tmux_session_exists(session_name):
        console.print(f"[cyan]Attaching to existing session: {session_name}[/cyan]")
        # Use = prefix for exact session matching (prevents prefix matching)
        tmux_args = _tmux_cmd(["attach", "-t", f"={session_name}"])
        os.execvp("tmux", tmux_args)
    else:
        console.print(f"[cyan]Creating new session: {session_name}[/cyan]")

        # Preserve SSH_AUTH_SOCK for SSH agent forwarding
        # This ensures git SSH operations work in worktree sessions
        ssh_auth_sock = os.environ.get("SSH_AUTH_SOCK")
        if ssh_auth_sock:
            # Set SSH_AUTH_SOCK in tmux global environment before creating session
            subprocess.run(
                _tmux_cmd(["set-environment", "-g", "SSH_AUTH_SOCK", ssh_auth_sock]), check=False
            )

        tmux_args = _tmux_cmd(["new-session", "-s", session_name, "-c", target_path, cmd])
        os.execvp("tmux", tmux_args)

    # Note: os.execvp replaces the current process, so this line is never reached
    # But added for completeness
    sys.exit(0)
