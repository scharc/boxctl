# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Agent command handlers."""

import shutil
from pathlib import Path
from typing import Optional

import click

from agentbox.cli import cli
from agentbox.container import ContainerManager
from agentbox.cli.helpers import (
    _build_dynamic_context,
    _complete_project_name,
    _run_agent_command,
    _run_agent_command_noninteractive,
    handle_errors,
)
from agentbox.utils.project import resolve_project_dir


def _has_vscode() -> bool:
    """Check if VSCode CLI is available on the host."""
    return shutil.which("code") is not None


def _read_agent_instructions() -> str:
    """Read base agent instructions + dynamic context."""
    project_dir = resolve_project_dir()
    agentbox_dir = project_dir / ".agentbox"

    # Read agents.md
    agents_md = agentbox_dir / "agents.md"
    if not agents_md.exists():
        base_instructions = "# Agent Context\n\nYou are running in an Agentbox container at /workspace."
    else:
        base_instructions = agents_md.read_text()

    # Add dynamic context
    dynamic_context = _build_dynamic_context(agentbox_dir)

    return f"{base_instructions}\n\n{dynamic_context}"


def _read_super_prompt() -> str:
    """Read base + super agent instructions + dynamic context."""
    project_dir = resolve_project_dir()
    agentbox_dir = project_dir / ".agentbox"

    # Read agents.md
    agents_md = agentbox_dir / "agents.md"
    if not agents_md.exists():
        base_instructions = "# Agent Context\n\nYou are running in an Agentbox container at /workspace."
    else:
        base_instructions = agents_md.read_text()

    # Read superagents.md
    superagents_md = agentbox_dir / "superagents.md"
    if not superagents_md.exists():
        raise click.ClickException(
            "Super agent instructions not found. Expected `.agentbox/superagents.md`. "
            "Run 'agentbox init' to create it.",
        )
    super_instructions = superagents_md.read_text()

    # Add dynamic context
    dynamic_context = _build_dynamic_context(agentbox_dir)

    return f"{base_instructions}\n\n{super_instructions}\n\n{dynamic_context}"




@cli.command()
@click.argument("project", required=False, shell_complete=_complete_project_name)
@click.argument("args", nargs=-1)
@handle_errors
def claude(project: Optional[str], args: tuple):
    """Run Claude Code in an Agentbox container.

    If no project name is provided, runs in the current project's container.

    Examples:
        agentbox claude
        agentbox claude "implement user authentication"
        agentbox claude my-project "fix the bug in login"
    """
    manager = ContainerManager()
    instructions = _read_agent_instructions()
    extra_args = [
        "--settings",
        "/home/abox/.claude/config.json",
        "--mcp-config",
        "/workspace/.agentbox/claude/mcp.json",
        "--append-system-prompt",
        instructions,
    ]

    # Auto-enable VSCode integration if available on host
    if _has_vscode():
        extra_args.append("--ide")

    _run_agent_command(
        manager,
        project,
        args,
        "claude",
        extra_args=extra_args,
        label="Claude Code",
        reuse_tmux_session=True,
        session_key="claude",
    )


@cli.command()
@click.option("-p", "--print", "print_mode", is_flag=True, help="Run in non-interactive mode (no tmux, output to stdout)")
@click.argument("project", required=False, shell_complete=_complete_project_name)
@click.argument("args", nargs=-1)
@handle_errors
def superclaude(print_mode: bool, project: Optional[str], args: tuple):
    """Run Claude Code with auto-approve permissions enabled.

    If no project name is provided, runs in the current project's container.

    Use -p/--print for non-interactive mode (useful for automation/scripting).
    """
    manager = ContainerManager()
    prompt = _read_super_prompt()
    extra_args = [
        "--settings",
        "/home/abox/.claude/config-super.json",
        "--mcp-config",
        "/workspace/.agentbox/claude/mcp.json",
        "--dangerously-skip-permissions",
        "--append-system-prompt",
        prompt,
    ]

    # Auto-enable VSCode integration if available on host (only in interactive mode)
    if not print_mode and _has_vscode():
        extra_args.append("--ide")

    # Add -p flag to claude when in print mode
    if print_mode:
        extra_args.append("-p")
        exit_code = _run_agent_command_noninteractive(
            manager,
            project,
            args,
            "claude",
            extra_args=extra_args,
            label="Claude Code (auto-approve)",
        )
        raise SystemExit(exit_code)
    else:
        _run_agent_command(
            manager,
            project,
            args,
            "claude",
            extra_args=extra_args,
            label="Claude Code (auto-approve)",
            reuse_tmux_session=True,
            session_key="superclaude",
            persist_session=False,
        )


@cli.command()
@click.argument("project", required=False, shell_complete=_complete_project_name)
@click.argument("args", nargs=-1)
@handle_errors
def codex(project: Optional[str], args: tuple):
    """Run Codex in an Agentbox container.

    If no project name is provided, runs in the current project's container.
    Codex uses AGENTS.md files for custom instructions (auto-discovered).
    """
    manager = ContainerManager()

    _run_agent_command(
        manager,
        project,
        args,
        "codex",
        label="Codex",
        reuse_tmux_session=True,
        session_key="codex",
    )


@cli.command()
@click.option("-p", "--print", "print_mode", is_flag=True, help="Run in non-interactive mode (no tmux, output to stdout)")
@click.argument("project", required=False, shell_complete=_complete_project_name)
@click.argument("args", nargs=-1)
@handle_errors
def supercodex(print_mode: bool, project: Optional[str], args: tuple):
    """Run Codex with auto-approve permissions enabled.

    If no project name is provided, runs in the current project's container.
    Codex uses AGENTS.md files for custom instructions (auto-discovered).

    Use -p/--print for non-interactive mode (useful for automation/scripting).
    """
    manager = ContainerManager()

    extra_args = [
        "--dangerously-bypass-approvals-and-sandbox",
    ]

    if print_mode:
        exit_code = _run_agent_command_noninteractive(
            manager,
            project,
            args,
            "codex",
            extra_args=extra_args,
            label="Codex (auto-approve)",
        )
        raise SystemExit(exit_code)
    else:
        _run_agent_command(
            manager,
            project,
            args,
            "codex",
            extra_args=extra_args,
            label="Codex (auto-approve)",
            reuse_tmux_session=True,
            session_key="supercodex",
            persist_session=False,
        )


@cli.command()
@click.argument("project", required=False, shell_complete=_complete_project_name)
@click.argument("args", nargs=-1)
@handle_errors
def gemini(project: Optional[str], args: tuple):
    """Run Gemini in an Agentbox container.

    If no project name is provided, runs in the current project's container.
    Gemini uses GEMINI.md files for custom instructions (auto-discovered).
    """
    manager = ContainerManager()

    _run_agent_command(
        manager,
        project,
        args,
        "gemini",
        label="Gemini",
        reuse_tmux_session=True,
        session_key="gemini",
    )


@cli.command()
@click.option("-p", "--print", "print_mode", is_flag=True, help="Run in non-interactive mode (no tmux, output to stdout)")
@click.argument("project", required=False, shell_complete=_complete_project_name)
@click.argument("args", nargs=-1)
@handle_errors
def supergemini(print_mode: bool, project: Optional[str], args: tuple):
    """Run Gemini with auto-approve permissions enabled.

    Gemini uses GEMINI.md files for custom instructions (auto-discovered).

    Use -p/--print for non-interactive mode (useful for automation/scripting).
    """
    manager = ContainerManager()

    extra_args = ["--non-interactive"]

    if print_mode:
        exit_code = _run_agent_command_noninteractive(
            manager,
            project,
            args,
            "gemini",
            extra_args=extra_args,
            label="Gemini (auto-approve)",
        )
        raise SystemExit(exit_code)
    else:
        _run_agent_command(
            manager,
            project,
            args,
            "gemini",
            extra_args=extra_args,
            label="Gemini (auto-approve)",
            reuse_tmux_session=True,
            session_key="supergemini",
            persist_session=False,
        )
