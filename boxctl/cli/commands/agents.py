# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Agent command handlers."""

import shutil
from pathlib import Path
from typing import Optional

import click

from boxctl.cli import cli
from boxctl.container import ContainerManager
from boxctl.cli.helpers import (
    _build_dynamic_context,
    _run_agent_command,
    handle_errors,
    require_initialized,
    console,
)
from boxctl.utils.project import resolve_project_dir


def _check_fallback(agent: str) -> Optional[str]:
    """Check if an agent needs fallback due to rate limiting.

    Uses the unified usage client which checks service first, then local state.

    Args:
        agent: The requested agent name (e.g., "superclaude")

    Returns:
        The fallback agent name if fallback is needed, None otherwise.
        If the fallback is the same as the requested agent (no fallback available),
        returns None to proceed with the original agent.
    """
    try:
        from boxctl.usage.client import get_fallback_agent

        fallback_agent, reason = get_fallback_agent(agent)

        if reason and fallback_agent != agent:
            console.print(f"[yellow]{reason}[/yellow]")
            console.print(f"[blue]Using fallback: {fallback_agent}[/blue]")
            return fallback_agent

        return None
    except ImportError:
        # Usage module not available, proceed without fallback
        return None


def _has_vscode() -> bool:
    """Check if VSCode CLI is available on the host."""
    return shutil.which("code") is not None


def _read_agent_instructions() -> str:
    """Read base agent instructions + dynamic context."""
    project_dir = resolve_project_dir()
    boxctl_dir = project_dir / ".boxctl"

    # Read agents.md
    agents_md = boxctl_dir / "agents.md"
    if not agents_md.exists():
        base_instructions = (
            "# Agent Context\n\nYou are running in an boxctl container at /workspace."
        )
    else:
        base_instructions = agents_md.read_text()

    # Add dynamic context
    dynamic_context = _build_dynamic_context(boxctl_dir)

    return f"{base_instructions}\n\n{dynamic_context}"


def _read_super_prompt() -> str:
    """Read base + super agent instructions + dynamic context."""
    project_dir = resolve_project_dir()
    boxctl_dir = project_dir / ".boxctl"

    # Read agents.md
    agents_md = boxctl_dir / "agents.md"
    if not agents_md.exists():
        base_instructions = (
            "# Agent Context\n\nYou are running in an boxctl container at /workspace."
        )
    else:
        base_instructions = agents_md.read_text()

    # Read superagents.md
    superagents_md = boxctl_dir / "superagents.md"
    if not superagents_md.exists():
        # Default super agent instructions if file is missing
        super_instructions = (
            "# Super Agent Context\n\n"
            "## Auto-Approve Mode Enabled\n"
            "You are running with auto-approve permissions."
        )
    else:
        super_instructions = superagents_md.read_text()

    # Add dynamic context
    dynamic_context = _build_dynamic_context(boxctl_dir)

    return f"{base_instructions}\n\n{super_instructions}\n\n{dynamic_context}"


@cli.command()
@click.argument("prompt", nargs=-1)
@click.pass_context
@handle_errors
def claude(ctx, prompt: tuple):
    """Run Claude Code in the current project.

    Runs in the project container from current directory.
    Use 'abox worktree BRANCH claude' for other branches.

    Examples:
        abox claude
        abox claude "implement user authentication"
    """
    require_initialized()

    # Check for rate limit fallback
    fallback = _check_fallback("claude")
    if fallback:
        fallback_cmd = cli.get_command(ctx, fallback)
        if fallback_cmd:
            ctx.invoke(fallback_cmd, prompt=prompt)
            return

    manager = ContainerManager()
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
        manager,
        None,  # Current project
        prompt,
        "claude",
        extra_args=extra_args,
        label="Claude Code",
        reuse_tmux_session=True,
        session_key="claude",
    )


@cli.command()
@click.argument("prompt", nargs=-1)
@click.pass_context
@handle_errors
def superclaude(ctx, prompt: tuple):
    """Run Claude Code with auto-approve permissions.

    Runs in the project container from current directory.
    Use 'abox worktree BRANCH superclaude' for other branches.

    Examples:
        abox superclaude
        abox superclaude "refactor the auth module"
    """
    require_initialized()

    # Check for rate limit fallback
    fallback = _check_fallback("superclaude")
    if fallback:
        fallback_cmd = cli.get_command(ctx, fallback)
        if fallback_cmd:
            ctx.invoke(fallback_cmd, prompt=prompt)
            return

    manager = ContainerManager()
    prompt_text = _read_super_prompt()
    extra_args = [
        "--settings",
        "/home/abox/.claude/settings-super.json",
        "--mcp-config",
        "/home/abox/.mcp.json",
        "--dangerously-skip-permissions",
        "--append-system-prompt",
        prompt_text,
    ]

    if _has_vscode():
        extra_args.append("--ide")

    _run_agent_command(
        manager,
        None,
        prompt,
        "claude",
        extra_args=extra_args,
        label="Claude Code (auto-approve)",
        reuse_tmux_session=True,
        session_key="superclaude",
        persist_session=False,
    )


@cli.command()
@click.argument("prompt", nargs=-1)
@click.pass_context
@handle_errors
def codex(ctx, prompt: tuple):
    """Run Codex in the current project.

    Runs in the project container from current directory.
    Codex uses AGENTS.md files for custom instructions (auto-discovered).

    Examples:
        abox codex
        abox codex "add tests for the API"
    """
    require_initialized()

    # Check for rate limit fallback
    fallback = _check_fallback("codex")
    if fallback:
        fallback_cmd = cli.get_command(ctx, fallback)
        if fallback_cmd:
            ctx.invoke(fallback_cmd, prompt=prompt)
            return

    manager = ContainerManager()

    _run_agent_command(
        manager,
        None,
        prompt,
        "codex",
        label="Codex",
        reuse_tmux_session=True,
        session_key="codex",
    )


@cli.command()
@click.argument("prompt", nargs=-1)
@click.pass_context
@handle_errors
def supercodex(ctx, prompt: tuple):
    """Run Codex with auto-approve permissions.

    Runs in the project container from current directory.
    Codex uses AGENTS.md files for custom instructions (auto-discovered).

    Examples:
        abox supercodex
        abox supercodex "optimize database queries"
    """
    require_initialized()

    # Check for rate limit fallback
    fallback = _check_fallback("supercodex")
    if fallback:
        fallback_cmd = cli.get_command(ctx, fallback)
        if fallback_cmd:
            ctx.invoke(fallback_cmd, prompt=prompt)
            return

    manager = ContainerManager()

    extra_args = [
        "--dangerously-bypass-approvals-and-sandbox",
    ]

    _run_agent_command(
        manager,
        None,
        prompt,
        "codex",
        extra_args=extra_args,
        label="Codex (auto-approve)",
        reuse_tmux_session=True,
        session_key="supercodex",
        persist_session=False,
    )


@cli.command()
@click.argument("prompt", nargs=-1)
@click.pass_context
@handle_errors
def gemini(ctx, prompt: tuple):
    """Run Gemini in the current project.

    Runs in the project container from current directory.
    Gemini uses GEMINI.md files for custom instructions (auto-discovered).

    Examples:
        abox gemini
        abox gemini "explain the codebase"
    """
    require_initialized()

    # Check for rate limit fallback
    fallback = _check_fallback("gemini")
    if fallback:
        fallback_cmd = cli.get_command(ctx, fallback)
        if fallback_cmd:
            ctx.invoke(fallback_cmd, prompt=prompt)
            return

    manager = ContainerManager()

    _run_agent_command(
        manager,
        None,
        prompt,
        "gemini",
        label="Gemini",
        reuse_tmux_session=True,
        session_key="gemini",
    )


@cli.command()
@click.argument("prompt", nargs=-1)
@click.pass_context
@handle_errors
def supergemini(ctx, prompt: tuple):
    """Run Gemini with auto-approve permissions.

    Runs in the project container from current directory.
    Gemini uses GEMINI.md files for custom instructions (auto-discovered).

    Examples:
        abox supergemini
        abox supergemini "update all dependencies"
    """
    require_initialized()

    # Check for rate limit fallback
    fallback = _check_fallback("supergemini")
    if fallback:
        fallback_cmd = cli.get_command(ctx, fallback)
        if fallback_cmd:
            ctx.invoke(fallback_cmd, prompt=prompt)
            return

    manager = ContainerManager()

    extra_args = ["--non-interactive"]

    _run_agent_command(
        manager,
        None,
        prompt,
        "gemini",
        extra_args=extra_args,
        label="Gemini (auto-approve)",
        reuse_tmux_session=True,
        session_key="supergemini",
        persist_session=False,
    )


@cli.command()
@click.argument("prompt", nargs=-1)
@click.pass_context
@handle_errors
def qwen(ctx, prompt: tuple):
    """Run Qwen Code in the current project.

    Runs in the project container from current directory.
    Qwen uses QWEN.md files for custom instructions (auto-discovered).

    Examples:
        abox qwen
        abox qwen "explain the API structure"
    """
    require_initialized()

    # Check for rate limit fallback
    fallback = _check_fallback("qwen")
    if fallback:
        fallback_cmd = cli.get_command(ctx, fallback)
        if fallback_cmd:
            ctx.invoke(fallback_cmd, prompt=prompt)
            return

    manager = ContainerManager()

    _run_agent_command(
        manager,
        None,
        prompt,
        "qwen",
        label="Qwen Code",
        reuse_tmux_session=True,
        session_key="qwen",
    )


@cli.command()
@click.argument("prompt", nargs=-1)
@click.pass_context
@handle_errors
def superqwen(ctx, prompt: tuple):
    """Run Qwen Code with auto-approve permissions.

    Runs in the project container from current directory.
    Qwen uses QWEN.md files for custom instructions (auto-discovered).

    Examples:
        abox superqwen
        abox superqwen "refactor all controllers"
    """
    require_initialized()

    # Check for rate limit fallback
    fallback = _check_fallback("superqwen")
    if fallback:
        fallback_cmd = cli.get_command(ctx, fallback)
        if fallback_cmd:
            ctx.invoke(fallback_cmd, prompt=prompt)
            return

    manager = ContainerManager()

    extra_args = ["--yolo"]

    _run_agent_command(
        manager,
        None,
        prompt,
        "qwen",
        extra_args=extra_args,
        label="Qwen Code (auto-approve)",
        reuse_tmux_session=True,
        session_key="superqwen",
        persist_session=False,
    )
