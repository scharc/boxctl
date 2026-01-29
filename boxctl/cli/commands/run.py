# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Non-interactive agent execution for automation and scripting.

This module provides the `abox run` command for running agents without tmux,
suitable for CI/CD pipelines, automation tools, and scripting.

Examples:
    abox run superclaude "implement feature X"
    abox run claude "analyze this code"
    output=$(abox run supercodex "add tests" 2>&1)
"""

import shlex
import subprocess
import sys
from typing import Optional

import click

from boxctl.cli import cli
from boxctl.container import ContainerManager
from boxctl.cli.helpers import (
    _build_dynamic_context,
    handle_errors,
    require_initialized,
    console,
    wait_for_container_ready,
)
from boxctl.cli.helpers.agent_commands import (
    _resolve_container_and_args,
    _ensure_container_running,
    _require_config_migrated,
)
from boxctl.cli.helpers.tmux_ops import _warn_if_base_outdated
from boxctl.utils.project import resolve_project_dir


# Agent configurations: name -> (command, extra_args_builder, label)
AGENT_CONFIGS = {
    "claude": {
        "command": "claude",
        "label": "Claude Code",
        "auto_approve": False,
    },
    "superclaude": {
        "command": "claude",
        "label": "Claude Code (auto-approve)",
        "auto_approve": True,
    },
    "codex": {
        "command": "codex",
        "label": "Codex",
        "auto_approve": False,
    },
    "supercodex": {
        "command": "codex",
        "label": "Codex (auto-approve)",
        "auto_approve": True,
    },
    "gemini": {
        "command": "gemini",
        "label": "Gemini",
        "auto_approve": False,
    },
    "supergemini": {
        "command": "gemini",
        "label": "Gemini (auto-approve)",
        "auto_approve": True,
    },
    "qwen": {
        "command": "qwen",
        "label": "Qwen Code",
        "auto_approve": False,
    },
    "superqwen": {
        "command": "qwen",
        "label": "Qwen Code (auto-approve)",
        "auto_approve": True,
    },
}


def _read_agent_instructions() -> str:
    """Read base agent instructions + dynamic context."""
    project_dir = resolve_project_dir()
    boxctl_dir = project_dir / ".boxctl"

    agents_md = boxctl_dir / "agents.md"
    if not agents_md.exists():
        base_instructions = (
            "# Agent Context\n\nYou are running in an boxctl container at /workspace."
        )
    else:
        base_instructions = agents_md.read_text()

    dynamic_context = _build_dynamic_context(boxctl_dir)
    return f"{base_instructions}\n\n{dynamic_context}"


def _read_super_prompt() -> str:
    """Read base + super agent instructions + dynamic context."""
    project_dir = resolve_project_dir()
    boxctl_dir = project_dir / ".boxctl"

    agents_md = boxctl_dir / "agents.md"
    if not agents_md.exists():
        base_instructions = (
            "# Agent Context\n\nYou are running in an boxctl container at /workspace."
        )
    else:
        base_instructions = agents_md.read_text()

    superagents_md = boxctl_dir / "superagents.md"
    if not superagents_md.exists():
        super_instructions = (
            "# Super Agent Context\n\n"
            "## Auto-Approve Mode Enabled\n"
            "You are running with auto-approve permissions."
        )
    else:
        super_instructions = superagents_md.read_text()

    dynamic_context = _build_dynamic_context(boxctl_dir)
    return f"{base_instructions}\n\n{super_instructions}\n\n{dynamic_context}"


def _build_extra_args(agent: str, config: dict) -> list[str]:
    """Build extra arguments for the agent command."""
    extra_args = []
    command = config["command"]
    auto_approve = config["auto_approve"]

    if command == "claude":
        # Claude-specific args
        if auto_approve:
            instructions = _read_super_prompt()
            extra_args = [
                "--settings",
                "/home/abox/.claude/settings-super.json",
                "--mcp-config",
                "/home/abox/.mcp.json",
                "--dangerously-skip-permissions",
                "--append-system-prompt",
                instructions,
                "-p",  # Print mode for non-interactive
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
                "-p",  # Print mode for non-interactive
            ]
    elif command == "codex":
        if auto_approve:
            extra_args = ["--dangerously-bypass-approvals-and-sandbox"]
    elif command == "gemini":
        if auto_approve:
            extra_args = ["--non-interactive"]
    elif command == "qwen":
        if auto_approve:
            extra_args = ["--yolo"]

    return extra_args


def _run_noninteractive(
    manager: ContainerManager,
    container_name: str,
    command: str,
    args: tuple,
    extra_args: Optional[list[str]] = None,
    label: Optional[str] = None,
    workdir: Optional[str] = None,
) -> int:
    """Run an agent command non-interactively (no tmux, no TTY).

    Args:
        manager: Container manager instance
        container_name: Name of the container to run in
        command: The agent command to run (claude, codex, etc.)
        args: Prompt arguments
        extra_args: Additional arguments for the agent
        label: Display label for the agent
        workdir: Working directory inside container

    Returns:
        Exit code from the command
    """
    # Build the command
    cmd = [command]
    if extra_args:
        cmd.extend(extra_args)
    if args:
        cmd.extend(args)

    display = label or command

    # Build docker exec command without -it (non-interactive)
    docker_cmd = [
        "docker",
        "exec",
        "-u",
        "abox",
        "-w",
        workdir or "/workspace",
        "-e",
        "HOME=/home/abox",
        "-e",
        "USER=abox",
        "-e",
        f"BOXCTL_AGENT_LABEL={display}",
        "-e",
        f"BOXCTL_CONTAINER={container_name}",
        "-e",
        "BOXCTL_NONINTERACTIVE=1",
        container_name,
    ]
    docker_cmd.extend(cmd)

    result = subprocess.run(docker_cmd)
    return result.returncode


@cli.command("run")
@click.argument("agent", type=click.Choice(list(AGENT_CONFIGS.keys())))
@click.argument("prompt", nargs=-1)
@handle_errors
def run_command(agent: str, prompt: tuple):
    """Run an agent non-interactively (for automation/scripting).

    Executes the specified agent without tmux, outputting directly to stdout.
    Suitable for CI/CD pipelines, automation tools, and scripting.

    AGENT is one of: claude, superclaude, codex, supercodex, gemini,
    supergemini, qwen, superqwen

    Examples:

        abox run superclaude "implement user auth"

        abox run claude "analyze this codebase"

        output=$(abox run supercodex "add tests" 2>&1)
    """
    require_initialized()

    if not prompt:
        console.print("[red]Error: prompt is required for non-interactive mode[/red]")
        console.print("\nUsage: abox run <agent> <prompt>")
        console.print('Example: abox run superclaude "implement feature X"')
        raise SystemExit(1)

    config = AGENT_CONFIGS[agent]
    manager = ContainerManager()

    # Resolve container
    container_name, prompt = _resolve_container_and_args(manager, None, prompt)

    # Get project dir for config version check
    project_dir = resolve_project_dir()

    # Block if config needs migration
    if not _require_config_migrated(project_dir):
        raise SystemExit(1)

    # Ensure container is running
    _ensure_container_running(manager, container_name)

    _warn_if_base_outdated(manager, container_name, project_dir)

    # Wait for container to be ready
    if not manager.wait_for_user(container_name, "abox"):
        console.print("[red]Container user 'abox' not found.[/red]")
        console.print("[yellow]Rebuild the base image with: boxctl update[/yellow]")
        raise SystemExit(1)

    if not wait_for_container_ready(manager, container_name, timeout_s=90.0):
        console.print("[red]Container failed to initialize[/red]")
        raise SystemExit(1)

    # Build args and run
    extra_args = _build_extra_args(agent, config)

    exit_code = _run_noninteractive(
        manager=manager,
        container_name=container_name,
        command=config["command"],
        args=prompt,
        extra_args=extra_args,
        label=config["label"],
    )

    sys.exit(exit_code)
