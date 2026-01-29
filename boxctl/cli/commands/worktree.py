# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Git worktree management commands for host-side boxctl CLI."""

import subprocess
import sys
from typing import Optional

import click

from boxctl.cli import cli
from boxctl.container import get_abox_environment
from boxctl.paths import ContainerPaths
from boxctl.cli.helpers import (
    _ensure_container_running,
    _get_project_context,
    _run_agent_command,
    _complete_worktree_branch,
    console,
    handle_errors,
)
from boxctl.cli.commands.agents import (
    _has_vscode,
    _read_agent_instructions,
    _read_super_prompt,
)


# Supported agent types
AGENT_TYPES = ["claude", "superclaude", "codex", "supercodex", "gemini", "supergemini", "shell"]


def _exec_worktree_command(manager, container_name: str, args: list[str]) -> tuple[int, str]:
    """Execute agentctl worktree command in container."""
    cmd = ["agentctl", "worktree"] + args
    exit_code, output = manager.exec_command(
        container_name,
        cmd,
        environment=get_abox_environment(include_tmux=True, container_name=container_name),
        user=ContainerPaths.USER,
        workdir="/workspace",
    )
    return exit_code, output


def _get_worktree_path(branch: str) -> str:
    """Get the worktree path for a branch."""
    return f"/git-worktrees/worktree-{branch}"


def _verify_worktree_exists(manager, container_name: str, worktree_path: str) -> bool:
    """Verify a worktree directory exists."""
    exit_code, _ = manager.exec_command(
        container_name,
        ["test", "-d", worktree_path],
        user=ContainerPaths.USER,
    )
    return exit_code == 0


def _ensure_worktree(pctx, branch: str) -> str:
    """Ensure worktree exists, creating if needed. Returns worktree path."""
    worktree_path = _get_worktree_path(branch)

    if _verify_worktree_exists(pctx.manager, pctx.container_name, worktree_path):
        return worktree_path

    # Worktree doesn't exist - create it
    console.print(f"[yellow]Creating worktree for branch: {branch}[/yellow]")

    # Check if branch exists
    exit_code, _ = pctx.manager.exec_command(
        pctx.container_name,
        ["git", "-C", "/workspace", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        user=ContainerPaths.USER,
    )
    branch_exists = exit_code == 0

    args = ["add", branch]
    if not branch_exists:
        args.append("--create")

    exit_code, output = _exec_worktree_command(pctx.manager, pctx.container_name, args)
    if exit_code != 0:
        raise click.ClickException(f"Failed to create worktree: {output}")

    if output:
        console.print(output.rstrip())

    return worktree_path


def _run_worktree_agent(branch: str, agent: str, args: tuple):
    """Run an agent in a worktree."""
    pctx = _get_project_context()

    if not _ensure_container_running(pctx.manager, pctx.container_name):
        raise click.ClickException(f"Container {pctx.container_name} is not running")

    worktree_path = _ensure_worktree(pctx, branch)

    is_super = agent.startswith("super")
    base_agent = agent[5:] if is_super else agent  # Remove 'super' prefix

    if base_agent == "claude":
        if is_super:
            prompt = _read_super_prompt()
            extra_args = [
                "--settings",
                "/home/abox/.claude/settings-super.json",
                "--mcp-config",
                "/home/abox/.mcp.json",
                "--dangerously-skip-permissions",
                "--append-system-prompt",
                prompt,
            ]
        else:
            instructions = _read_agent_instructions()
            extra_args = [
                "--settings",
                "/home/abox/.claude/settings.json",
                "--mcp-config",
                "/home/abox/.mcp.json",
                "--append-system-prompt",
                instructions,
            ]

        if _has_vscode():
            extra_args.append("--ide")

        _run_agent_command(
            pctx.manager,
            None,
            args,
            "claude",
            extra_args=extra_args,
            label=f"Claude {'auto-approve ' if is_super else ''}({branch})",
            reuse_tmux_session=True,
            session_key=f"{agent}-{branch}",
            persist_session=not is_super,
            workdir=worktree_path,
        )

    elif base_agent == "codex":
        extra_args = []
        if is_super:
            extra_args.append("--dangerously-bypass-approvals-and-sandbox")

        _run_agent_command(
            pctx.manager,
            None,
            args,
            "codex",
            extra_args=extra_args,
            label=f"Codex {'auto-approve ' if is_super else ''}({branch})",
            reuse_tmux_session=True,
            session_key=f"{agent}-{branch}",
            persist_session=not is_super,
            workdir=worktree_path,
        )

    elif base_agent == "gemini":
        extra_args = []
        if is_super:
            extra_args.append("--sandbox=false")

        _run_agent_command(
            pctx.manager,
            None,
            args,
            "gemini",
            extra_args=extra_args,
            label=f"Gemini {'no-sandbox ' if is_super else ''}({branch})",
            reuse_tmux_session=True,
            session_key=f"{agent}-{branch}",
            persist_session=not is_super,
            workdir=worktree_path,
        )

    else:
        raise click.ClickException(f"Unknown agent type: {agent}")


def _run_worktree_shell(branch: str):
    """Open a shell in a worktree."""
    pctx = _get_project_context()

    if not _ensure_container_running(pctx.manager, pctx.container_name):
        raise click.ClickException(f"Container {pctx.container_name} is not running")

    worktree_path = _ensure_worktree(pctx, branch)

    console.print(f"[green]Entering worktree: {branch}[/green]")
    console.print(f"[dim]Working directory: {worktree_path}[/dim]")
    console.print("[dim]Start an agent with: agentctl a claude[/dim]\n")

    subprocess.run(
        [
            "docker",
            "exec",
            "-it",
            "-u",
            "abox",
            "-w",
            worktree_path,
            pctx.container_name,
            "/bin/bash",
        ],
        check=False,
    )


@cli.group(name="worktree")
def worktree_group():
    """Git worktree management.

    \b
    Usage:
        abox worktree add BRANCH          # Create worktree (shell access)
        abox worktree new AGENT BRANCH    # Create worktree + run agent
        abox worktree list [json]         # List worktrees
        abox worktree remove BRANCH [force]
        abox worktree prune               # Clean stale metadata

    \b
    Agent types: claude, superclaude, codex, supercodex, gemini, supergemini

    \b
    Examples:
        abox worktree add feature-auth              # Create worktree only
        abox worktree new superclaude feature-auth  # Create + run agent
        abox worktree new claude bugfix-123         # Create + run agent
        abox worktree list                          # List all worktrees
    """
    pass


@worktree_group.command(name="list")
@click.argument("format", required=False, type=click.Choice(["json"]))
@handle_errors
def worktree_list(format: Optional[str]):
    """List all git worktrees.

    FORMAT: Use "json" for machine-readable output

    Examples:
        abox worktree list
        abox worktree list json
    """
    pctx = _get_project_context()
    if not _ensure_container_running(pctx.manager, pctx.container_name):
        raise click.ClickException(f"Container {pctx.container_name} is not running")

    args = ["list"]
    if format == "json":
        args.append("--json")

    exit_code, output = _exec_worktree_command(pctx.manager, pctx.container_name, args)
    if output:
        click.echo(output.rstrip())
    sys.exit(exit_code)


@worktree_group.command(name="add")
@click.argument("branch")
@handle_errors
def worktree_add(branch: str):
    """Create a new git worktree (shell access only).

    BRANCH: Name of the branch to check out in the worktree

    Creates a new worktree for the specified branch.
    If the branch doesn't exist, it will be created automatically.
    Use 'worktree new AGENT BRANCH' to also start an agent.

    Examples:
        abox worktree add feature-auth
        abox worktree add bugfix-123
    """
    pctx = _get_project_context()
    if not _ensure_container_running(pctx.manager, pctx.container_name):
        raise click.ClickException(f"Container {pctx.container_name} is not running")

    # Check if branch exists
    exit_code, _ = pctx.manager.exec_command(
        pctx.container_name,
        ["git", "-C", "/workspace", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        user=ContainerPaths.USER,
    )
    branch_exists = exit_code == 0

    args = ["add", branch]
    if not branch_exists:
        args.append("--create")

    exit_code, output = _exec_worktree_command(pctx.manager, pctx.container_name, args)
    if output:
        click.echo(output.rstrip())
    sys.exit(exit_code)


def _complete_agent_type(ctx, param, incomplete):
    """Shell completion for agent types."""
    return [a for a in AGENT_TYPES if a.startswith(incomplete)]


@worktree_group.command(name="new")
@click.argument("agent", type=click.Choice(AGENT_TYPES), shell_complete=_complete_agent_type)
@click.argument("branch", shell_complete=_complete_worktree_branch)
@handle_errors
def worktree_new(agent: str, branch: str):
    """Create a worktree and run an agent in it.

    AGENT: Agent type (claude, superclaude, codex, supercodex, gemini, supergemini, shell)
    BRANCH: Name of the branch for the worktree

    Creates a new worktree for the specified branch and starts an agent session.
    If the branch doesn't exist, it will be created automatically.

    Examples:
        abox worktree new superclaude feature-auth
        abox worktree new claude bugfix-123
        abox worktree new codex new-feature
    """
    if agent == "shell":
        _run_worktree_shell(branch)
    else:
        _run_worktree_agent(branch, agent, tuple())


@worktree_group.command(name="remove")
@click.argument("branch_or_path", shell_complete=_complete_worktree_branch)
@click.argument("mode", required=False, type=click.Choice(["force"]))
@handle_errors
def worktree_remove(branch_or_path: str, mode: Optional[str]):
    """Remove a git worktree.

    BRANCH_OR_PATH: Branch name or worktree path to remove
    MODE: Use "force" to remove even with uncommitted changes

    Examples:
        abox worktree remove feature-auth
        abox worktree remove feature-auth force
    """
    pctx = _get_project_context()
    if not _ensure_container_running(pctx.manager, pctx.container_name):
        raise click.ClickException(f"Container {pctx.container_name} is not running")

    args = ["remove", branch_or_path]
    if mode == "force":
        args.append("--force")

    exit_code, output = _exec_worktree_command(pctx.manager, pctx.container_name, args)
    if output:
        click.echo(output.rstrip())
    sys.exit(exit_code)


@worktree_group.command(name="prune")
@handle_errors
def worktree_prune():
    """Remove stale worktree metadata.

    Cleans up metadata for worktrees that no longer exist in git.
    """
    pctx = _get_project_context()
    if not _ensure_container_running(pctx.manager, pctx.container_name):
        raise click.ClickException(f"Container {pctx.container_name} is not running")

    exit_code, output = _exec_worktree_command(pctx.manager, pctx.container_name, ["prune"])
    if output:
        click.echo(output.rstrip())
    sys.exit(exit_code)
